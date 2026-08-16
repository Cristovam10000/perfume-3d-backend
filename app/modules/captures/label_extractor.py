"""Extração e correção perspectiva da label frontal do frasco de perfume.

Recebe a foto original (RGB) e a máscara RGBA gerada pelo BackgroundRemover.
Localiza a região da label, aplica transformação de perspectiva (homografia) e
entrega a label como PNG plano — pronto para ser projetado sobre o GLB.

Mesmo padrão Strategy do restante do módulo: ABC + bypass + implementação
real trocável por configuração.

Implementações disponíveis:
- `DisabledLabelExtractor`: sempre retorna None (sem extração).
- `HomographyLabelExtractor`: detecção por região + warpPerspective via OpenCV.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from ...core.logging import get_logger

_log = get_logger("captures.label_extractor")


@dataclass(frozen=True)
class ExtractedLabel:
    image_path: Path    # PNG da label com perspectiva corrigida
    confidence: float   # 0..1, score de quão "label" a região parece
    aspect_ratio: float # largura / altura da label extraída
    # Altura do centro da label na silhueta do frasco: 0.0 = topo, 1.0 = base.
    # O `LabelProjector` usa isso para posicionar o decal na altura certa; sem
    # essa informação ele cai no centroide do corpo, que fica abaixo da label
    # real na maioria dos frascos.
    vertical_position: float = 0.5
    # Bounding rect do candidato em pixels da foto **inteira** (x, y, w, h).
    # Vira a janela da projeção: o pipeline converte para coordenadas
    # normalizadas da silhueta e o script Blender estica a imagem exatamente
    # sobre essas faces. Sem isso a projeção não sabe onde a label fica.
    box_px: tuple[int, int, int, int] = (0, 0, 0, 0)


class LabelExtractor(ABC):
    """Contrato dos extratores de label."""

    @abstractmethod
    async def extract(
        self,
        image_path: Path,   # foto preprocessada (RGB)
        mask_path: Path,    # PNG RGBA do BackgroundRemover
        output_path: Path,
        hires_path: Path | None = None,  # upload original, se disponível
    ) -> ExtractedLabel | None:
        """Localiza e corrige a perspectiva da label frontal.

        Retorna None quando nenhuma região plausível de label for encontrada.

        `hires_path` é o upload original. A detecção sempre roda na
        preprocessada (barata), mas o recorte final sai do original quando ele
        existe — medido no Camille, isso são 6120x8160 contra 1536x2048, ou 4x
        de resolução linear na placa que hoje se joga fora.
        """


class DisabledLabelExtractor(LabelExtractor):
    """Bypass: sempre retorna None. Use quando extração não é desejada."""

    async def extract(
        self,
        image_path: Path,
        mask_path: Path,
        output_path: Path,
        hires_path: Path | None = None,
    ) -> ExtractedLabel | None:
        return None


class HomographyLabelExtractor(LabelExtractor):
    """Extrai a label frontal por **detecção de região** + correção de perspectiva.

    Por que região e não borda
    --------------------------
    A implementação anterior procurava quadriláteros nos contornos de um mapa de
    bordas Canny dilatado. Em foto real o Canny produz traços **fragmentados e
    abertos**, e `contourArea` de um traço mede a área do risco (~3 px de
    espessura), não a região que ele delimita. Medido nas 21 fotos reais dos 6
    jobs do projeto: **0 detecções**, com o maior candidato em 0,03%–1,0% da
    máscara contra um mínimo exigido de 5%.

    Os 12 testes unitários passavam porque usavam um retângulo branco perfeito
    sobre fundo preto (`cv2.rectangle(..., thickness=3)`), onde o Canny fecha o
    contorno e a área bate. O teste validava a premissa, não a realidade.

    Algoritmo atual
    ---------------
    1. Silhueta binária a partir do canal alpha da máscara.
    2. Recorte na bounding box do frasco.
    3. **Ensemble de binarizações** (Otsu claro/escuro + fechamentos
       morfológicos). Cada hipótese responde a um jeito de a label se destacar:
       placa clara sobre vidro escuro, texto claro sobre corpo escuro, etc. O
       fechamento une letras soltas num bloco.
    4. Cada região vira candidato; `_pontuar` combina área, proporção,
       centralização e retangularidade num score 0..1.
    5. Melhor score acima de `min_score` vence; senão devolve None.
    6. `minAreaRect` do contorno dá os 4 cantos (sempre 4, mesmo com contorno
       irregular) → `getPerspectiveTransform` → `warpPerspective`.

    Por que o score geométrico não basta (2026-08)
    ----------------------------------------------
    Os quatro sinais de `_pontuar` medem **forma**, nunca conteúdo. No job
    `15ef21e9` (Camille, frasco de vidro transparente) a base do frasco — vidro
    liso, sem nada impresso — pontuou **melhor que a label real da vivacité**:

    | candidato                              | score | altura | laplaciano |
    |----------------------------------------|-------|--------|------------|
    | La vivacité, placa com texto            | 0,776 | 0,53   | **1833**   |
    | vivacité, tampa transparente            | 0,763 | 0,10   | 1427       |
    | Camille lateral, vidro liso             | 0,855 | 0,82   | **60**     |
    | Camille traseira, vidro liso            | 0,831 | 0,82   | 96         |
    | Camille direita, vidro liso             | 0,862 | 0,83   | 28         |

    Uma região lisa de ~9% da máscara, proporção ~2,0 e centralizada é o
    candidato geométrico *perfeito*. Daí os dois portões novos:

    - **Conteúdo**: label carrega impressão; vidro liso não. Variância do
      laplaciano separa com 15x de margem (28–96 contra 1427+), e a densidade
      de bordas Canny confirma (0,010–0,032 contra 0,115+). Argumento físico,
      não estatístico — por isso vale fora da amostra medida.
    - **Posição vertical**: a tampa transparente da vivacité passa no portão de
      conteúdo (as bordas são o *fundo* visto através do vidro), mas está em
      altura 0,10. Label vive no corpo, não na tampa.

    Os dois falham para o lado seguro: rejeitar devolve None e o modelo fica
    com a textura do Hunyuan, que já traz o texto impresso — pior é colar um
    recorte errado por cima dela.

    Calibração e limites
    --------------------
    Medido nas fotos reais do projeto:

    - **La vivacité** (placa prateada retangular): detecção correta, score 0,78.
    - **ASAD** (texto dourado + medalhão): encontra o **medalhão**, não o texto.
      É um emblema real da marca, mas não é a label.
    - **Feeling Sexy** (texto em script diagonal): região parcial, score 0,67.
    - **GRAND** (texto impresso direto no vidro): nenhum candidato.

    O default `min_score=0.75` deixa passar apenas o caso de placa real. Isso é
    deliberado: projetar um recorte errado no GLB é pior do que não projetar
    nada. Frascos sem placa — texto impresso direto no vidro — não têm região
    para extrair, e devolver None neles é o comportamento correto.

    Quando o usuário marca a label no app (`labelBox` no POST /captures), este
    extrator nem roda: coordenada explícita vence heurística, mesmo raciocínio
    do campo `material`.
    """

    # Faixa de área do candidato, em % da máscara do frasco. Placa de perfume
    # fica em torno de 8%; abaixo de 1,5% é ruído, acima de 45% é o corpo.
    _AREA_IDEAL_PCT = 8.0

    # Teto da largura do warp. Casa com `LABEL_TARGET_SIZE` (2048): acima disso
    # a textura só engorda o GLB sem ganho visível na tela do celular.
    _MAX_TARGET_WIDTH = 2048

    def __init__(
        self,
        min_area_ratio: float = 0.015,  # 1,5% da máscara
        max_area_ratio: float = 0.45,   # 45% (acima disso é o corpo do frasco)
        target_width: int = 1024,       # resolução horizontal do PNG de saída
        min_score: float = 0.75,        # abaixo disso, não projeta
        min_vertical: float = 0.30,     # label não vive na tampa
        max_vertical: float = 0.92,     # nem colada na base
        min_laplaciano: float = 250.0,  # detalhe interno: texto impresso
        min_densidade_bordas: float = 0.06,
    ):
        if not 0.0 < min_area_ratio < max_area_ratio <= 1.0:
            raise ValueError(
                "min_area_ratio e max_area_ratio devem satisfazer "
                "0 < min < max <= 1"
            )
        if not 0.0 <= min_score <= 1.0:
            raise ValueError(f"min_score deve estar em [0, 1]: {min_score}")
        if not 0.0 <= min_vertical < max_vertical <= 1.0:
            raise ValueError(
                "min_vertical e max_vertical devem satisfazer 0 <= min < max <= 1"
            )
        self.min_area_ratio = min_area_ratio
        self.max_area_ratio = max_area_ratio
        self.target_width = target_width
        self.min_score = min_score
        self.min_vertical = min_vertical
        self.max_vertical = max_vertical
        self.min_laplaciano = min_laplaciano
        self.min_densidade_bordas = min_densidade_bordas

    async def extract(
        self,
        image_path: Path,
        mask_path: Path,
        output_path: Path,
        hires_path: Path | None = None,
    ) -> ExtractedLabel | None:
        if not image_path.exists():
            raise FileNotFoundError(f"Imagem não encontrada: {image_path}")
        if not mask_path.exists():
            raise FileNotFoundError(f"Máscara não encontrada: {mask_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return await asyncio.to_thread(
            self._extract_sync, image_path, mask_path, output_path, hires_path
        )

    # ------------------------------------------------------------------ sync

    def _extract_sync(
        self,
        image_path: Path,
        mask_path: Path,
        output_path: Path,
        hires_path: Path | None = None,
    ) -> ExtractedLabel | None:
        # Imports lazy: módulo importa mesmo sem cv2/numpy instalados.
        import cv2
        import numpy as np

        imagem_rgb = cv2.imread(str(image_path))
        if imagem_rgb is None:
            raise FileNotFoundError(f"cv2 não conseguiu abrir a imagem: {image_path}")

        mascara_rgba = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
        if mascara_rgba is None:
            raise FileNotFoundError(f"cv2 não conseguiu abrir a máscara: {mask_path}")

        canal_alpha = (
            mascara_rgba[:, :, 3]
            if mascara_rgba.ndim == 3 and mascara_rgba.shape[2] == 4
            else (mascara_rgba[:, :, 0] if mascara_rgba.ndim == 3 else mascara_rgba)
        )

        # Foto e máscara vêm do mesmo frame, mas o preprocessador pode ter
        # redimensionado uma delas. Sem alinhar as dimensões, os dois recortes
        # saem com shapes diferentes e o `bitwise_and` estoura.
        altura_img, largura_img = imagem_rgb.shape[:2]
        if canal_alpha.shape[:2] != (altura_img, largura_img):
            _log.info(
                "Máscara %s difere da foto %s; redimensionando a máscara",
                canal_alpha.shape[:2],
                (altura_img, largura_img),
            )
            canal_alpha = cv2.resize(
                canal_alpha, (largura_img, altura_img), interpolation=cv2.INTER_NEAREST
            )

        _, silhueta = cv2.threshold(canal_alpha, 127, 255, cv2.THRESH_BINARY)

        area_mascara = float(np.count_nonzero(silhueta))
        if area_mascara == 0:
            _log.warning("Máscara vazia — sem frasco detectado em %s", mask_path)
            return None

        x_bb, y_bb, w_bb, h_bb = cv2.boundingRect(cv2.findNonZero(silhueta))
        recorte = imagem_rgb[y_bb : y_bb + h_bb, x_bb : x_bb + w_bb]
        if recorte.size == 0:
            return None
        cinza = cv2.cvtColor(recorte, cv2.COLOR_BGR2GRAY)
        silhueta_recorte = silhueta[y_bb : y_bb + h_bb, x_bb : x_bb + w_bb]

        melhor = self._melhor_candidato(
            cinza,
            silhueta_recorte,
            area_mascara=area_mascara,
            largura_frasco=w_bb,
            altura_frasco=h_bb,
        )
        if melhor is None:
            _log.info("Nenhuma label plausível encontrada em %s", image_path)
            return None

        score, contorno = melhor

        # Altura relativa do centro da label dentro da silhueta do frasco.
        # Preservada para o projetor posicionar o decal na altura correta.
        x_c, y_c, w_c, h_c = cv2.boundingRect(contorno)
        posicao_vertical = min(max((y_c + h_c / 2.0) / max(h_bb, 1), 0.0), 1.0)

        # Portão de conteúdo: label carrega impressão, vidro liso não. Roda
        # sobre o candidato vencedor porque é caro demais para o laço interno,
        # e um único veredito no fim resolve — se o melhor candidato não tem
        # detalhe, nenhum dos piores teria.
        if not self._tem_conteudo(cinza[y_c : y_c + h_c, x_c : x_c + w_c], image_path):
            return None

        # `minAreaRect` devolve sempre 4 cantos, mesmo com contorno irregular —
        # ao contrário de `approxPolyDP`, que só às vezes fecha em quadrilátero.
        cantos = cv2.boxPoints(cv2.minAreaRect(contorno)).astype(np.float32)
        cantos[:, 0] += x_bb
        cantos[:, 1] += y_bb
        cantos_ordenados = _ordenar_cantos(cantos)

        largura_label = float(
            max(
                np.linalg.norm(cantos_ordenados[1] - cantos_ordenados[0]),
                np.linalg.norm(cantos_ordenados[2] - cantos_ordenados[3]),
            )
        )
        altura_label = float(
            max(
                np.linalg.norm(cantos_ordenados[3] - cantos_ordenados[0]),
                np.linalg.norm(cantos_ordenados[2] - cantos_ordenados[1]),
            )
        )
        if altura_label <= 0 or largura_label <= 0:
            return None

        # Fonte dos pixels: o upload original quando existir. A detecção rodou
        # na preprocessada, mas os cantos escalam para o original por um fator
        # uniforme (o preprocessador preserva a proporção), então o mesmo warp
        # vale — só que sobre muito mais pixels.
        fonte, escala = self._fonte_de_pixels(imagem_rgb, hires_path)

        proporcao = largura_label / altura_label
        # `target_width` é piso, não teto: quando a fonte tem mais pixels reais
        # que isso, esticar para 1024 jogaria fora detalhe que existe. O teto
        # duro evita que uma foto de 8160px vire uma textura absurda no GLB.
        disponiveis = int(round(largura_label * escala))
        largura_alvo = max(self.target_width, min(disponiveis, self._MAX_TARGET_WIDTH))
        altura_alvo = max(int(round(largura_alvo / proporcao)), 1)
        if largura_alvo > self.target_width:
            _log.info(
                "Label com %d px reais de largura; warp em %d em vez de %d",
                disponiveis, largura_alvo, self.target_width,
            )

        destino = np.array(
            [
                [0, 0],
                [largura_alvo - 1, 0],
                [largura_alvo - 1, altura_alvo - 1],
                [0, altura_alvo - 1],
            ],
            dtype=np.float32,
        )

        matriz = cv2.getPerspectiveTransform(cantos_ordenados * escala, destino)
        label_plana = cv2.warpPerspective(
            fonte, matriz, (largura_alvo, altura_alvo)
        )
        cv2.imwrite(str(output_path), label_plana)

        _log.info(
            "Label extraída: proporção=%.2f, score=%.3f, altura=%.2f, saída=%s",
            proporcao,
            score,
            posicao_vertical,
            output_path,
        )
        return ExtractedLabel(
            image_path=output_path,
            confidence=score,
            aspect_ratio=proporcao,
            vertical_position=posicao_vertical,
            # Coordenadas da foto inteira: o contorno vive no recorte da
            # bounding box do frasco, então soma-se a origem dela de volta.
            box_px=(x_c + x_bb, y_c + y_bb, w_c, h_c),
        )

    def _fonte_de_pixels(self, imagem_prep, hires_path: Path | None):
        """(imagem, fator de escala dos cantos) para o warp final.

        Devolve a preprocessada com escala 1.0 quando não há original utilizável.
        Recusa o original se a proporção não bater: um fator uniforme só é
        válido com o mesmo aspect ratio, e um EXIF não aplicado deixaria a
        imagem girada — nos dois casos o recorte sairia no lugar errado, o que
        é pior que perder resolução.
        """
        import cv2

        if hires_path is None or not hires_path.exists():
            return imagem_prep, 1.0

        altura_prep, largura_prep = imagem_prep.shape[:2]
        try:
            # `IMREAD_UNCHANGED | IMREAD_IGNORE_ORIENTATION` NÃO: aqui queremos
            # justamente que o OpenCV aplique o EXIF, para casar com o que o
            # preprocessador fez.
            hires = cv2.imread(str(hires_path), cv2.IMREAD_COLOR)
        except Exception as exc:  # noqa: BLE001 — degradar é o comportamento certo
            _log.warning("Falha ao abrir original %s (%s); usando a preprocessada",
                         hires_path, exc)
            return imagem_prep, 1.0
        if hires is None:
            return imagem_prep, 1.0

        altura_hi, largura_hi = hires.shape[:2]
        if largura_hi <= largura_prep:
            return imagem_prep, 1.0

        escala = largura_hi / largura_prep
        if abs(altura_hi / max(altura_prep, 1) - escala) > 0.01:
            _log.warning(
                "Original %s tem proporção diferente da preprocessada "
                "(%dx%d vs %dx%d); usando a preprocessada",
                hires_path.name, largura_hi, altura_hi, largura_prep, altura_prep,
            )
            return imagem_prep, 1.0

        _log.info(
            "Recorte da label na resolução original: %dx%d (%.1fx a preprocessada)",
            largura_hi, altura_hi, escala,
        )
        return hires, escala

    def _tem_conteudo(self, roi, image_path: Path) -> bool:
        """A região tem impressão, ou é superfície lisa?

        Dois sinais redundantes sobre o mesmo fenômeno físico — texto e
        gravura criam alta frequência; vidro e plástico lisos não. Exigir os
        dois evita que um brilho especular isolado (que inflaria só o
        laplaciano) passe por label.
        """
        import cv2
        import numpy as np

        if roi.size < 100:
            return False

        laplaciano = float(cv2.Laplacian(roi, cv2.CV_64F).var())
        bordas = cv2.Canny(roi, 60, 160)
        densidade = float(np.count_nonzero(bordas)) / roi.size

        if laplaciano < self.min_laplaciano or densidade < self.min_densidade_bordas:
            _log.info(
                "Candidato reprovado por falta de conteúdo em %s "
                "(laplaciano=%.1f < %.1f ou bordas=%.4f < %.4f) — "
                "provavelmente superfície lisa, não label",
                image_path.name,
                laplaciano,
                self.min_laplaciano,
                densidade,
                self.min_densidade_bordas,
            )
            return False
        return True

    # -------------------------------------------------------------- detecção

    def _binarizacoes(self, cinza) -> dict[str, object]:
        """Hipóteses de "a label se destaca do corpo do frasco".

        Duas polaridades porque a label tanto pode ser clara sobre corpo escuro
        (placa prateada) quanto escura sobre corpo claro. Os fechamentos unem
        letras soltas num bloco — sem isso, texto impresso vira dezenas de
        regiões minúsculas em vez de uma região só.
        """
        import cv2

        saida: dict[str, object] = {}
        for nome, flag in (
            ("claro", cv2.THRESH_BINARY),
            ("escuro", cv2.THRESH_BINARY_INV),
        ):
            _, base = cv2.threshold(cinza, 0, 255, flag + cv2.THRESH_OTSU)
            saida[f"otsu_{nome}"] = base
            for k in (15, 31):
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
                saida[f"otsu_{nome}_close{k}"] = cv2.morphologyEx(
                    base, cv2.MORPH_CLOSE, kernel
                )
        return saida

    def _melhor_candidato(
        self,
        cinza,
        silhueta_recorte,
        *,
        area_mascara: float,
        largura_frasco: int,
        altura_frasco: int,
    ):
        """Percorre o ensemble e devolve (score, contorno) do melhor candidato."""
        import cv2

        melhor = None
        for binaria in self._binarizacoes(cinza).values():
            # Restringe ao interior do frasco: fundo removido não gera candidato.
            dentro = cv2.bitwise_and(binaria, silhueta_recorte)
            contornos, _ = cv2.findContours(
                dentro, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for contorno in contornos:
                area = float(cv2.contourArea(contorno))
                if area <= 0:
                    continue
                x, y, w, h = cv2.boundingRect(contorno)
                if w == 0 or h == 0:
                    continue
                score = self._pontuar(
                    area_pct=100.0 * area / area_mascara,
                    proporcao=w / h,
                    desvio_centro=abs((x + w / 2.0) - largura_frasco / 2.0)
                    / max(largura_frasco, 1),
                    retangularidade=area / (w * h),
                    posicao_vertical=(y + h / 2.0) / max(altura_frasco, 1),
                )
                if score >= self.min_score and (melhor is None or score > melhor[0]):
                    melhor = (score, contorno)
        return melhor

    def _pontuar(
        self,
        *,
        area_pct: float,
        proporcao: float,
        desvio_centro: float,
        retangularidade: float,
        posicao_vertical: float = 0.5,
    ) -> float:
        """Score 0..1 de quanto a região parece uma label de perfume.

        Zera fora dos limites duros; dentro deles, combina quatro sinais. A
        proporção ideal 2.0 reflete que labels de perfume são tipicamente mais
        largas que altas.
        """
        if not (self.min_area_ratio * 100 <= area_pct <= self.max_area_ratio * 100):
            return 0.0
        if not (0.4 <= proporcao <= 4.0):
            return 0.0
        if desvio_centro > 0.22:
            return 0.0
        if retangularidade < 0.55:
            return 0.0
        # Label vive no corpo do frasco. Sem este corte, a tampa transparente
        # da vivacité (altura 0,10) vence a label real dela (0,53) — o que o
        # Otsu vê ali é o azulejo do fundo através do vidro.
        if not (self.min_vertical <= posicao_vertical <= self.max_vertical):
            return 0.0

        s_area = 1.0 - min(abs(area_pct - self._AREA_IDEAL_PCT) / 20.0, 1.0)
        s_prop = 1.0 - min(abs(proporcao - 2.0) / 2.0, 1.0)
        s_centro = 1.0 - desvio_centro / 0.22
        return 0.35 * s_area + 0.25 * s_prop + 0.15 * s_centro + 0.25 * retangularidade


def _ordenar_cantos(pontos):
    """Ordena 4 pontos como [TL, TR, BR, BL] usando soma e diferença de coordenadas.

    Soma mínima → TL; soma máxima → BR.
    Diferença mínima → TR; diferença máxima → BL.
    """
    import numpy as np

    soma = pontos.sum(axis=1)
    diff = np.diff(pontos, axis=1).ravel()

    cantos = np.zeros((4, 2), dtype=np.float32)
    cantos[0] = pontos[np.argmin(soma)]   # TL: menor soma (x+y)
    cantos[2] = pontos[np.argmax(soma)]   # BR: maior soma (x+y)
    cantos[1] = pontos[np.argmin(diff)]   # TR: menor diff (x-y)
    cantos[3] = pontos[np.argmax(diff)]   # BL: maior diff (x-y)
    return cantos
