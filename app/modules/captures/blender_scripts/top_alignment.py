"""Estima a rotacao entre a foto do topo e a tampa da malha, por silhueta.

Problema
--------
A projecao ortografica do topo mapeia XY do mundo para UV da imagem. Nada amarra
a **rotacao em torno de Z**: a foto foi tirada com o frasco numa orientacao
qualquer, e a malha do Hunyuan tem a propria orientacao (definida pela vista
`front` enviada ao gerador). Sem corrigir isso, o logo da tampa aparece girado.

Solucao
-------
A silhueta da tampa vista de cima raramente e circular — a do Lattafa ASAD e um
triangulo arredondado, a do La vivacite e quadrada. Isso da sinal suficiente para
estimar o angulo por **maxima sobreposicao (IoU)** entre duas mascaras binarias:
a silhueta da foto (canal alpha do BackgroundRemover) e a silhueta da tampa
projetada em XY.

Tampas circulares sao ambiguas por construcao — girar um circulo nao muda a
silhueta. Nesses casos a curva de IoU fica plana; `confianca` detecta isso e o
chamador decide nao aplicar rotacao em vez de aplicar uma aleatoria.

Este modulo nao importa `bpy` — e numpy puro, para poder ser testado sem Blender.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Resolucao da grade onde as duas silhuetas sao comparadas. 96x96 e suficiente
# para capturar a forma (triangulo vs quadrado vs circulo) e mantem a busca em
# ~180 angulos barata.
_RESOLUCAO = 96

# Meia-largura da grade em unidades de raio RMS. 2.5 cobre a silhueta inteira
# com folga depois da normalizacao de escala.
_EXTENSAO_RMS = 2.5


@dataclass(frozen=True)
class RotacaoEstimada:
    """Resultado da estimativa.

    `angulo_graus` gira a foto para alinhar com a malha (sentido anti-horario no
    plano XY). `espelhar` indica que a foto precisa ser espelhada no eixo X antes
    da rotacao — acontece porque fotografar de cima inverte a lateralidade em
    relacao a projecao ortografica.

    `confianca` e a razao entre o melhor IoU e a mediana dos IoUs de todos os
    angulos testados. 1.0 significa curva totalmente plana (silhueta circular,
    rotacao indeterminada); quanto maior, mais nitido o pico.
    """

    angulo_graus: float
    espelhar: bool
    iou: float
    confianca: float

    @property
    def confiavel(self) -> bool:
        return self.confianca >= 1.08 and self.iou >= 0.5


def _pontos_normalizados(mascara: np.ndarray) -> np.ndarray | None:
    """Converte mascara booleana em pontos (x, y) centrados e com raio RMS 1.

    A normalizacao torna a comparacao invariante a translacao e escala, sobrando
    so a rotacao — que e o que queremos medir.
    """
    ys, xs = np.nonzero(mascara)
    if len(xs) < 16:
        return None

    pontos = np.stack([xs.astype(np.float64), ys.astype(np.float64)], axis=1)
    pontos -= pontos.mean(axis=0)

    raio_rms = float(np.sqrt((pontos**2).sum(axis=1).mean()))
    if raio_rms <= 1e-9:
        return None
    return pontos / raio_rms


def _rasterizar(pontos: np.ndarray) -> np.ndarray:
    """Rasteriza pontos normalizados numa grade booleana fixa."""
    escala = _RESOLUCAO / (2.0 * _EXTENSAO_RMS)
    centro = _RESOLUCAO / 2.0
    ix = np.clip((pontos[:, 0] * escala + centro).astype(np.int32), 0, _RESOLUCAO - 1)
    iy = np.clip((pontos[:, 1] * escala + centro).astype(np.int32), 0, _RESOLUCAO - 1)

    grade = np.zeros((_RESOLUCAO, _RESOLUCAO), dtype=bool)
    grade[iy, ix] = True
    return _fechar(grade)


def _fechar(grade: np.ndarray) -> np.ndarray:
    """Fechamento morfologico 3x3 (dilata e depois erode).

    A silhueta e construida por splatting de vertices, entao vem pontilhada.
    O fechamento a torna solida sem depender de scipy/cv2, indisponiveis dentro
    do Blender.
    """
    def dilatar(g: np.ndarray) -> np.ndarray:
        saida = g.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                saida |= np.roll(np.roll(g, dy, axis=0), dx, axis=1)
        return saida

    def erodir(g: np.ndarray) -> np.ndarray:
        saida = g.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                saida &= np.roll(np.roll(g, dy, axis=0), dx, axis=1)
        return saida

    return erodir(dilatar(dilatar(grade)))


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    uniao = np.count_nonzero(a | b)
    if uniao == 0:
        return 0.0
    return float(np.count_nonzero(a & b) / uniao)


def estimar_rotacao(
    mascara_modelo: np.ndarray,
    mascara_foto: np.ndarray,
    *,
    passo_graus: float = 2.0,
    permitir_espelho: bool = True,
) -> RotacaoEstimada | None:
    """Acha o angulo (e espelhamento) que melhor alinha a foto com a malha.

    Retorna None quando alguma das mascaras nao tem pontos suficientes.
    """
    pontos_modelo = _pontos_normalizados(mascara_modelo)
    pontos_foto = _pontos_normalizados(mascara_foto)
    if pontos_modelo is None or pontos_foto is None:
        return None

    grade_modelo = _rasterizar(pontos_modelo)

    angulos = np.arange(0.0, 360.0, passo_graus)
    melhor = (-1.0, 0.0, False)
    todos_ious: list[float] = []

    for espelhar in ((False, True) if permitir_espelho else (False,)):
        base = pontos_foto.copy()
        if espelhar:
            base[:, 0] *= -1.0

        for angulo in angulos:
            rad = np.radians(angulo)
            cos, sen = np.cos(rad), np.sin(rad)
            girados = np.stack(
                [
                    base[:, 0] * cos - base[:, 1] * sen,
                    base[:, 0] * sen + base[:, 1] * cos,
                ],
                axis=1,
            )
            valor = _iou(grade_modelo, _rasterizar(girados))
            todos_ious.append(valor)
            if valor > melhor[0]:
                melhor = (valor, float(angulo), espelhar)

    iou, angulo, espelhar = melhor
    mediana = float(np.median(todos_ious)) or 1e-9
    return RotacaoEstimada(
        angulo_graus=angulo,
        espelhar=espelhar,
        iou=iou,
        confianca=iou / mediana,
    )
