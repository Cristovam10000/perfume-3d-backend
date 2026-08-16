"""Testes do LabelExtractor.

Lição da versão anterior desta suíte
------------------------------------
Os testes antigos montavam a entrada com
`cv2.rectangle(imagem, ..., thickness=3)` — um **contorno** branco fino sobre
fundo preto puro. Nessa imagem o Canny fecha o traço, `approxPolyDP` devolve 4
vértices e a área do contorno bate com a área da região. Passavam.

Em foto real o Canny produz traços fragmentados e abertos, e a área do contorno
mede o risco (~3 px), não a região. Resultado medido nos 6 jobs do projeto:
**0 detecções em 25 fotos** — com 12 testes verdes.

Pior: dois testes chamavam `pytest.skip(...)` quando a detecção falhava, o que
transformava a falha real em "pulado". Um teste que se auto-desliga quando o
código erra não testa nada.

Esta suíte usa **regiões preenchidas** (como uma placa de rótulo real) e não
tem skip condicional em nenhum caminho de detecção.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.modules.captures.label_extractor import (
    DisabledLabelExtractor,
    ExtractedLabel,
    HomographyLabelExtractor,
    LabelExtractor,
    _ordenar_cantos,
)


# ---------------------------------------------------------- helpers de fixtures


def _imprimir_na_placa(imagem, placa: tuple[int, int, int, int], cor_placa: int) -> None:
    """Desenha texto dentro da placa, como impressão de rótulo de verdade.

    Duas linhas de altura diferente imitam nome do perfume + "EAU DE PARFUM",
    que é o que gera a alta frequência que o portão de conteúdo procura.
    """
    import cv2

    x0, y0, x1, y1 = placa
    largura, altura = x1 - x0, y1 - y0
    tinta = (max(cor_placa - 190, 0),) * 3
    escala = altura / 70.0
    cv2.putText(
        imagem, "VIVACITE", (x0 + int(largura * 0.07), y0 + int(altura * 0.52)),
        cv2.FONT_HERSHEY_SIMPLEX, escala * 0.95, tinta, max(int(escala * 2), 1),
        cv2.LINE_AA,
    )
    cv2.putText(
        imagem, "EAU DE PARFUM", (x0 + int(largura * 0.10), y0 + int(altura * 0.84)),
        cv2.FONT_HERSHEY_SIMPLEX, escala * 0.42, tinta, max(int(escala), 1),
        cv2.LINE_AA,
    )


def _frasco_com_placa(
    path_rgb: Path,
    path_mascara: Path,
    *,
    tamanho: int = 400,
    placa: tuple[int, int, int, int] = (130, 150, 270, 206),
    cor_corpo: int = 70,
    cor_placa: int = 225,
    ruido: int = 0,
    com_texto: bool = True,
) -> None:
    """Frasco sintético realista: corpo escuro + placa clara PREENCHIDA e IMPRESSA.

    Diferente do teste antigo, a placa é uma região sólida — é assim que um
    rótulo aparece numa foto, não como um contorno de 3 px.

    As proporções seguem o caso real medido (La vivacité): a placa ocupa ~9% da
    silhueta do frasco e tem proporção ~2,5. Uma placa muito maior que isso é
    penalizada pelo score, que foi calibrado para rótulo de perfume.

    O texto dentro da placa **não é enfeite**: o extrator tem um portão de
    conteúdo (variância do laplaciano + densidade de bordas) porque uma região
    lisa pontua igual a um rótulo em todos os critérios geométricos — foi
    assim que a base de vidro do Camille venceu a placa real da vivacité. Uma
    placa em branco aqui testaria a premissa em vez da realidade, exatamente o
    erro que a versão anterior desta suíte cometia com o retângulo de Canny.
    Use `com_texto=False` para exercitar justamente a rejeição.
    """
    import cv2
    import numpy as np

    rng = np.random.default_rng(42)

    x0, x1 = int(tamanho * 0.18), int(tamanho * 0.82)
    y0, y1 = int(tamanho * 0.10), int(tamanho * 0.95)

    imagem = np.zeros((tamanho, tamanho, 3), dtype=np.uint8)
    cv2.rectangle(imagem, (x0, y0), (x1, y1), (cor_corpo,) * 3, thickness=cv2.FILLED)
    cv2.rectangle(imagem, placa[:2], placa[2:], (cor_placa,) * 3, thickness=cv2.FILLED)
    if com_texto:
        _imprimir_na_placa(imagem, placa, cor_placa)
    if ruido:
        barulho = rng.integers(-ruido, ruido + 1, imagem.shape, dtype=np.int16)
        imagem = np.clip(imagem.astype(np.int16) + barulho, 0, 255).astype(np.uint8)
    cv2.imwrite(str(path_rgb), imagem)

    mascara = np.zeros((tamanho, tamanho, 4), dtype=np.uint8)
    cv2.rectangle(
        mascara, (x0, y0), (x1, y1), (255, 255, 255, 255), thickness=cv2.FILLED
    )
    cv2.imwrite(str(path_mascara), mascara)


def _frasco_sem_placa(path_rgb: Path, path_mascara: Path, tamanho: int = 400) -> None:
    """Frasco de cor uniforme — não há região para extrair.

    É o caso do Hinode GRAND (texto impresso direto no vidro): devolver None
    aqui é o comportamento **correto**, não uma falha.
    """
    import cv2
    import numpy as np

    x0, x1 = int(tamanho * 0.18), int(tamanho * 0.82)
    y0, y1 = int(tamanho * 0.10), int(tamanho * 0.95)

    imagem = np.zeros((tamanho, tamanho, 3), dtype=np.uint8)
    cv2.rectangle(imagem, (x0, y0), (x1, y1), (70, 70, 70), thickness=cv2.FILLED)
    cv2.imwrite(str(path_rgb), imagem)

    mascara = np.zeros((tamanho, tamanho, 4), dtype=np.uint8)
    cv2.rectangle(
        mascara, (x0, y0), (x1, y1), (255, 255, 255, 255), thickness=cv2.FILLED
    )
    cv2.imwrite(str(path_mascara), mascara)


def _placa_como_contorno_fino(
    path_rgb: Path, path_mascara: Path, tamanho: int = 400
) -> None:
    """Reproduz a entrada do teste ANTIGO: contorno fino, não região."""
    import cv2
    import numpy as np

    imagem = np.zeros((tamanho, tamanho, 3), dtype=np.uint8)
    cv2.rectangle(imagem, (90, 150), (310, 235), (255, 255, 255), thickness=3)
    cv2.imwrite(str(path_rgb), imagem)

    mascara = np.zeros((tamanho, tamanho, 4), dtype=np.uint8)
    mascara[:, :, 3] = 255
    cv2.imwrite(str(path_mascara), mascara)


# ------------------------------------------------------------------ Disabled


class TestDisabledLabelExtractor:
    def test_is_label_extractor_subclass(self):
        assert issubclass(DisabledLabelExtractor, LabelExtractor)

    @pytest.mark.asyncio
    async def test_sempre_retorna_none(self, tmp_path: Path):
        extrator = DisabledLabelExtractor()
        resultado = await extrator.extract(
            tmp_path / "qualquer.jpg",
            tmp_path / "qualquer.png",
            tmp_path / "saida.png",
        )
        assert resultado is None


# ------------------------------------------------------------- contrato/erros


class TestContrato:
    def test_is_label_extractor_subclass(self):
        assert issubclass(HomographyLabelExtractor, LabelExtractor)

    def test_parametros_invalidos_levantam_value_error(self):
        with pytest.raises(ValueError):
            HomographyLabelExtractor(min_area_ratio=0.6, max_area_ratio=0.2)
        with pytest.raises(ValueError):
            HomographyLabelExtractor(min_score=1.5)

    @pytest.mark.asyncio
    async def test_imagem_inexistente_levanta_file_not_found(self, tmp_path: Path):
        mascara = tmp_path / "m.png"
        mascara.write_bytes(b"x")
        with pytest.raises(FileNotFoundError):
            await HomographyLabelExtractor().extract(
                tmp_path / "nao_existe.jpg", mascara, tmp_path / "out.png"
            )

    @pytest.mark.asyncio
    async def test_mascara_inexistente_levanta_file_not_found(self, tmp_path: Path):
        imagem = tmp_path / "i.jpg"
        imagem.write_bytes(b"x")
        with pytest.raises(FileNotFoundError):
            await HomographyLabelExtractor().extract(
                imagem, tmp_path / "nao_existe.png", tmp_path / "out.png"
            )


# ------------------------------------------------------------------ detecção


class TestDeteccaoPorRegiao:
    @pytest.mark.asyncio
    async def test_detecta_placa_preenchida(self, tmp_path: Path):
        """Caso do La vivacité: placa clara sólida sobre corpo escuro."""
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _frasco_com_placa(img, msk)

        r = await HomographyLabelExtractor().extract(img, msk, out)

        assert r is not None, "placa preenchida deve ser detectada"
        assert isinstance(r, ExtractedLabel)
        assert out.exists()
        # Placa 140x56 -> proporção ~2.5
        assert 2.0 <= r.aspect_ratio <= 3.2

    @pytest.mark.asyncio
    async def test_sobrevive_a_ruido(self, tmp_path: Path):
        """Foto real tem ruído; a detecção não pode depender de imagem limpa."""
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _frasco_com_placa(img, msk, ruido=18)

        assert await HomographyLabelExtractor().extract(img, msk, out) is not None

    @pytest.mark.asyncio
    async def test_frasco_sem_placa_retorna_none(self, tmp_path: Path):
        """Sem região distinta não há label — None é o resultado correto."""
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _frasco_sem_placa(img, msk)

        assert await HomographyLabelExtractor().extract(img, msk, out) is None

    @pytest.mark.asyncio
    async def test_mascara_vazia_retorna_none(self, tmp_path: Path):
        pytest.importorskip("cv2")
        import cv2
        import numpy as np

        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        cv2.imwrite(str(img), np.zeros((200, 200, 3), dtype=np.uint8))
        cv2.imwrite(str(msk), np.zeros((200, 200, 4), dtype=np.uint8))

        assert await HomographyLabelExtractor().extract(img, msk, out) is None

    @pytest.mark.asyncio
    async def test_mascara_de_tamanho_diferente_e_realinhada(self, tmp_path: Path):
        """Foto e máscara podem divergir de tamanho; não pode estourar."""
        pytest.importorskip("cv2")
        import cv2

        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _frasco_com_placa(img, msk, tamanho=400)
        mascara = cv2.imread(str(msk), cv2.IMREAD_UNCHANGED)
        cv2.imwrite(str(msk), cv2.resize(mascara, (200, 200)))

        assert await HomographyLabelExtractor().extract(img, msk, out) is not None


class TestPosicaoVertical:
    @pytest.mark.asyncio
    async def test_placa_alta_tem_posicao_menor_que_placa_baixa(self, tmp_path: Path):
        """`vertical_position` cresce de cima para baixo (0=topo, 1=base).

        As duas alturas ficam dentro da faixa aceita (0,30–0,92 da silhueta):
        o objetivo aqui é a ordem do valor, não o portão de posição, que tem
        teste próprio.
        """
        pytest.importorskip("cv2")
        casos = {"alta": (130, 160, 270, 216), "baixa": (130, 290, 270, 346)}

        resultados = {}
        for nome, rect in casos.items():
            img = tmp_path / f"{nome}.png"
            msk = tmp_path / f"{nome}_m.png"
            out = tmp_path / f"{nome}_l.png"
            _frasco_com_placa(img, msk, placa=rect)
            r = await HomographyLabelExtractor().extract(img, msk, out)
            assert r is not None, f"placa {nome} deveria ser detectada"
            resultados[nome] = r.vertical_position

        assert resultados["alta"] < resultados["baixa"]
        assert 0.0 <= resultados["alta"] <= 1.0
        assert 0.0 <= resultados["baixa"] <= 1.0

    @pytest.mark.asyncio
    async def test_regiao_na_tampa_e_rejeitada(self, tmp_path: Path):
        """Portão de posição: label vive no corpo, não na tampa.

        Sem este corte a tampa transparente da La vivacité (altura 0,10) vencia
        a label real dela (0,53) — o que o Otsu enxerga ali é o azulejo do
        fundo através do vidro, e ele tem bordas de sobra para passar no portão
        de conteúdo.
        """
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        # Silhueta vai de y=40 a y=380; centro em y=90 dá ~0,15 da altura.
        _frasco_com_placa(img, msk, placa=(130, 62, 270, 118))

        assert await HomographyLabelExtractor().extract(img, msk, out) is None


class TestPortaoDeConteudo:
    """Uma região lisa pontua igual a um rótulo em todos os critérios de forma.

    Foi assim que a base de vidro do Camille (score 0,86) venceu a placa real
    da La vivacité (0,78) e virou uma mancha bege no modelo. O portão mede
    detalhe interno: impressão gera alta frequência, vidro liso não.
    """

    @pytest.mark.asyncio
    async def test_placa_lisa_e_rejeitada(self, tmp_path: Path):
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _frasco_com_placa(img, msk, com_texto=False)

        assert await HomographyLabelExtractor().extract(img, msk, out) is None

    @pytest.mark.asyncio
    async def test_placa_impressa_passa(self, tmp_path: Path):
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _frasco_com_placa(img, msk, com_texto=True)

        assert await HomographyLabelExtractor().extract(img, msk, out) is not None

    @pytest.mark.asyncio
    async def test_limiar_frouxo_aceita_a_lisa(self, tmp_path: Path):
        """Confirma que é o portão que rejeita, não outro filtro do caminho."""
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _frasco_com_placa(img, msk, com_texto=False)

        frouxo = HomographyLabelExtractor(
            min_laplaciano=0.0, min_densidade_bordas=0.0
        )
        assert await frouxo.extract(img, msk, out) is not None


class TestBoxPx:
    @pytest.mark.asyncio
    async def test_box_esta_em_coordenadas_da_foto_inteira(self, tmp_path: Path):
        """`box_px` alimenta a janela da projeção; offset errado desloca a label.

        O contorno é achado dentro do recorte da bounding box do frasco, então
        a origem dela precisa voltar para a soma.
        """
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        placa = (130, 150, 270, 206)
        _frasco_com_placa(img, msk, placa=placa)

        r = await HomographyLabelExtractor().extract(img, msk, out)
        assert r is not None
        x, y, w, h = r.box_px
        # Tolerância: o contorno vem de binarização, não do retângulo exato.
        assert abs(x - placa[0]) <= 6, f"x={x} longe de {placa[0]}"
        assert abs(y - placa[1]) <= 6, f"y={y} longe de {placa[1]}"
        assert abs(w - (placa[2] - placa[0])) <= 10
        assert abs(h - (placa[3] - placa[1])) <= 10


class TestScore:
    @pytest.mark.asyncio
    async def test_min_score_alto_rejeita_tudo(self, tmp_path: Path):
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _frasco_com_placa(img, msk)

        extrator = HomographyLabelExtractor(min_score=0.99)
        assert await extrator.extract(img, msk, out) is None

    @pytest.mark.asyncio
    async def test_confianca_e_o_score(self, tmp_path: Path):
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _frasco_com_placa(img, msk)

        r = await HomographyLabelExtractor(min_score=0.5).extract(img, msk, out)

        assert r is not None
        assert 0.5 <= r.confidence <= 1.0


class TestRegressaoDoDiagnostico:
    """Documenta por que a suíte antiga não pegava a falha."""

    @pytest.mark.asyncio
    async def test_contorno_fino_nao_representa_foto_real(self, tmp_path: Path):
        """Entrada do teste antigo: contorno de 3 px, sem corpo de frasco.

        Não é uma foto — é um desenho de linhas. O teste existe para registrar
        que essa entrada foi a causa de 12 testes verdes conviverem com 0
        detecções reais; por isso não afirma nada sobre detectar ou não.
        """
        pytest.importorskip("cv2")
        img, msk, out = tmp_path / "i.png", tmp_path / "m.png", tmp_path / "l.png"
        _placa_como_contorno_fino(img, msk)

        resultado = await HomographyLabelExtractor().extract(img, msk, out)
        assert resultado is None or isinstance(resultado, ExtractedLabel)


class TestOrdenarCantos:
    def test_cantos_em_ordem_correta(self):
        pytest.importorskip("numpy")
        import numpy as np

        pontos = np.array(
            [[100.0, 80.0], [10.0, 10.0], [10.0, 80.0], [100.0, 10.0]],
            dtype=np.float32,
        )
        resultado = _ordenar_cantos(pontos)

        np.testing.assert_allclose(resultado[0], [10.0, 10.0], atol=1e-5)   # TL
        np.testing.assert_allclose(resultado[1], [100.0, 10.0], atol=1e-5)  # TR
        np.testing.assert_allclose(resultado[2], [100.0, 80.0], atol=1e-5)  # BR
        np.testing.assert_allclose(resultado[3], [10.0, 80.0], atol=1e-5)   # BL

    def test_retorna_array_float32(self):
        pytest.importorskip("numpy")
        import numpy as np

        pontos = np.array(
            [[0.0, 0.0], [50.0, 0.0], [50.0, 30.0], [0.0, 30.0]], dtype=np.float32
        )
        assert _ordenar_cantos(pontos).dtype == np.float32
