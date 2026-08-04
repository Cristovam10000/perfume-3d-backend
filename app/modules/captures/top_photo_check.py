"""Verifica se a foto rotulada como `top` é de fato uma vista superior.

Motivação: o `TopProjector` recorta a foto no contorno do que não é fundo e
**estica esse recorte inteiro** sobre as faces da tampa. Ele não procura a
tampa dentro da imagem — assume que a imagem *é* a tampa. Uma foto oblíqua do
frasco inteiro, portanto, não gera erro nenhum: ela é colada na tampa como se
fosse a tampa, e o frasco inteiro aparece amassado no topo do modelo.

Aconteceu no job `3901ff83`, mesmo com o app já exibindo a instrução escrita
("posicione a câmera perpendicular à tampa"). Texto sozinho não resolve, então
o backend mede.

## O sinal

Elongação da silhueta: a razão entre os dois eixos principais (PCA) dos pixels
opacos da máscara. 1,0 = silhueta compacta (círculo, quadrado); valores altos =
alongada.

A justificativa é geométrica, não estatística. De cima, o frasco apresenta a
**pegada** — largura × profundidade —, que é compacta. De lado, apresenta o
**perfil** — largura × altura —, que num frasco de perfume é sempre alongado.

Medido nas 34 fotos reais de todos os jobs do projeto:

    topo correto (ASAD, perpendicular)      1,03
    topo incorreto (Fakhar, oblíquo)        2,06
    32 fotos cardeais                  1,50 – 4,23

O corte default de 1,35 fica folgado entre o topo correto e a cardeal mais
compacta.

Por que PCA e não a razão da bounding box: PCA é invariante a rotação. Uma foto
de perfil enquadrada a 45° tem bounding box quase quadrada e passaria batido no
teste da bbox; os eixos principais continuam denunciando a elongação real.

Ressalva honesta: há **um** exemplo positivo no projeto. O que sustenta o corte
é o argumento geométrico mais o fato de o modo de falha ser seguro — reprovar
apenas pula um estágio opcional, nunca corrompe o modelo.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Abaixo disso a silhueta é pequena demais para a covariância significar algo.
_MIN_PIXELS = 64


@dataclass(frozen=True)
class VereditoTopo:
    """Resultado da checagem. `elongacao` é NaN quando não foi possível medir."""

    aprovado: bool
    elongacao: float
    motivo: str


def elongacao_da_mascara(mascara) -> float:
    """Razão entre os eixos principais dos pixels marcados. 1.0 = compacta.

    `mascara` é um array booleano 2D. Usa a raiz dos autovalores da matriz de
    covariância das coordenadas — ou seja, o desvio padrão ao longo de cada eixo
    principal, que é a extensão da silhueta em cada direção.
    """
    import numpy as np

    ys, xs = np.nonzero(mascara)
    if len(xs) < _MIN_PIXELS:
        return float("nan")

    pontos = np.stack([xs, ys]).astype(np.float64)
    pontos -= pontos.mean(axis=1, keepdims=True)
    autovalores = np.linalg.eigvalsh(np.cov(pontos))

    menor = max(float(autovalores[0]), 1e-12)
    maior = max(float(autovalores[1]), 0.0)
    return float(np.sqrt(maior / menor))


def _mascara_de_alpha(caminho: Path):
    """Silhueta a partir do canal alpha da imagem mascarada."""
    import numpy as np
    from PIL import Image

    with Image.open(caminho) as img:
        arr = np.array(img.convert("RGBA"))
    return arr[:, :, 3] > 25


def checar_foto_de_topo(caminho: Path, limite: float = 1.35) -> VereditoTopo:
    """Decide se a foto mascarada parece uma vista superior.

    Falha ao abrir/medir **aprova**: a checagem é uma guarda contra foto obliqua,
    não um validador de arquivo. Reprovar por não conseguir medir transformaria
    um problema de leitura numa perda silenciosa de funcionalidade.
    """
    try:
        mascara = _mascara_de_alpha(caminho)
    except Exception as exc:
        return VereditoTopo(True, float("nan"), f"não foi possível abrir ({exc})")

    medida = elongacao_da_mascara(mascara)
    if medida != medida:  # NaN
        return VereditoTopo(True, medida, "silhueta pequena demais para medir")

    if medida <= limite:
        return VereditoTopo(
            True, medida, f"elongação {medida:.2f} <= {limite:.2f}"
        )
    return VereditoTopo(
        False,
        medida,
        (
            f"elongação {medida:.2f} > {limite:.2f} — a silhueta é alongada como "
            "uma vista lateral, não como um frasco visto de cima"
        ),
    )
