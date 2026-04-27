"""Gera o PNG da label do template `feeling_rectangular_blue`.

A label é uma textura PNG com fundo transparente que vai ser projetada no
plano `Label` do template procedural pelo `generate_feeling_template.py`.

Conteúdo da label (de cima pra baixo):
- "Feelin' Flame" em script dourado, com leve inclinação (referência: rótulo
  real do Hinode Feelin' Flame).
- "FOR HIM" em sans-serif compacto à direita.
- Logo "HINODE" em caps no rodapé.

Saída: `back/assets/templates/normalized/feeling_rectangular_blue_label.png`

Uso:
    python -m scripts.build_feeling_label
    # ou
    .\\.venv\\Scripts\\python.exe scripts\\build_feeling_label.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SCRIPT_PATH = Path(__file__).resolve()
BACK_ROOT = SCRIPT_PATH.parent.parent
OUTPUT_PATH = (
    BACK_ROOT / "assets" / "templates" / "normalized" / "feeling_rectangular_blue_label.png"
)

# Resolução alta para a textura sobreviver a zoom no model-viewer.
WIDTH, HEIGHT = 1024, 1536

# Cor dourada do print (rgba). O canal alfa total fica em 255 — a transparência
# vem do fundo, não do glyph.
GOLD = (228, 178, 70, 255)
GOLD_DARK = (175, 130, 40, 255)  # sombra/contorno suave atrás do script


# Procura fontes Windows na ordem de preferência. Cada item é (path, kind).
# `kind=script` = cursivo elegante; `kind=sans` = humanista normal.
_WIN_FONTS = Path("C:/Windows/Fonts")

SCRIPT_CANDIDATES = [
    "BRUSHSCI.TTF",   # Brush Script MT — referência mais próxima do Feelin' Flame
    "MISTRAL.TTF",    # Mistral — handwritten brush
    "VLADIMIR.TTF",   # Vladimir Script
    "FRSCRIPT.TTF",   # French Script
    "VIVALDII.TTF",   # Vivaldi Italic
]

SANS_CANDIDATES = [
    "segoeui.ttf",
    "arial.ttf",
    "calibri.ttf",
    "tahoma.ttf",
]

SANS_BOLD_CANDIDATES = [
    "segoeuib.ttf",
    "arialbd.ttf",
    "calibrib.ttf",
    "tahomabd.ttf",
]


def find_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    """Tenta carregar a primeira fonte do Windows que existir na lista."""
    for name in candidates:
        path = _WIN_FONTS / name
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    # Fallback final: bitmap default (não fica bonito mas não quebra a build).
    print(
        f"[label] AVISO: nenhuma fonte de {candidates[:2]}... encontrada, usando default",
        file=sys.stderr,
    )
    return ImageFont.load_default()


def draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    cx: int,
    cy: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    *,
    shadow: tuple[int, int, int, int] | None = None,
    shadow_offset: tuple[int, int] = (4, 4),
) -> None:
    """Desenha `text` centralizado em (cx, cy) com sombra opcional."""
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = cx - w // 2 - bbox[0]
    y = cy - h // 2 - bbox[1]
    if shadow is not None:
        dx, dy = shadow_offset
        draw.text((x + dx, y + dy), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def fit_font(
    candidates: list[str], text: str, max_width_px: int, max_size: int = 400
) -> ImageFont.FreeTypeFont:
    """Devolve a primeira fonte da lista no MAIOR tamanho cuja largura do
    `text` ainda caiba em `max_width_px`. Garante que o texto não vaza
    horizontalmente da label.
    """
    for name in candidates:
        path = _WIN_FONTS / name
        if not path.exists():
            continue
        size = max_size
        # Itera reduzindo até caber. Step de 6 px é mais que suficiente.
        while size > 24:
            font = ImageFont.truetype(str(path), size=size)
            bbox = font.getbbox(text)
            text_w = bbox[2] - bbox[0]
            if text_w <= max_width_px:
                return font
            size -= 6
        return ImageFont.truetype(str(path), size=24)
    return ImageFont.load_default()


def build_label() -> Image.Image:
    """Monta a textura da label a partir dos elementos textuais."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Margem horizontal de 10% pra garantir que nada vaze da textura quando
    # ela for projetada num plano levemente menor que a foto-real do frasco.
    safe_margin = int(WIDTH * 0.10)
    safe_w = WIDTH - 2 * safe_margin

    # "Feelin'" e "Flame" empilhados, ambos cabendo no espaço seguro.
    feelin_font = fit_font(SCRIPT_CANDIDATES, "Feelin'", max_width_px=safe_w, max_size=300)
    flame_font = fit_font(SCRIPT_CANDIDATES, "Flame", max_width_px=safe_w, max_size=300)
    for_him_font = find_font(SANS_CANDIDATES, size=78)
    hinode_font = find_font(SANS_BOLD_CANDIDATES, size=120)

    # Linha 1: "Feelin'" levemente para a esquerda do centro.
    draw_centered_text(
        draw,
        "Feelin'",
        cx=int(WIDTH * 0.45),
        cy=int(HEIGHT * 0.38),
        font=feelin_font,
        fill=GOLD,
        shadow=GOLD_DARK,
        shadow_offset=(5, 6),
    )
    # Linha 2: "Flame" levemente para a direita, criando o efeito de assinatura.
    draw_centered_text(
        draw,
        "Flame",
        cx=int(WIDTH * 0.52),
        cy=int(HEIGHT * 0.52),
        font=flame_font,
        fill=GOLD,
        shadow=GOLD_DARK,
        shadow_offset=(5, 6),
    )

    # "FOR HIM" centralizado (não mais ancorado à direita — evita estourar a borda).
    for_him = "FOR  HIM"
    draw_centered_text(
        draw,
        for_him,
        cx=int(WIDTH * 0.55),
        cy=int(HEIGHT * 0.62),
        font=for_him_font,
        fill=GOLD,
        shadow=GOLD_DARK,
        shadow_offset=(2, 2),
    )

    # Rodapé: emblema + "HINODE" tratados como um conjunto centralizado.
    hinode_text = "HINODE"
    hbbox = draw.textbbox((0, 0), hinode_text, font=hinode_font)
    hw = hbbox[2] - hbbox[0]

    radius = 26
    emblem_gap = 24  # espaço entre o emblema e a letra "H"
    total_w = (radius + 22) * 2 + emblem_gap + hw  # diâmetro_externo + gap + texto
    block_left = WIDTH // 2 - total_w // 2

    emblem_cx = block_left + (radius + 22)
    emblem_cy = int(HEIGHT * 0.88)
    text_x = emblem_cx + (radius + 22) + emblem_gap - hbbox[0]
    text_y = emblem_cy - (hbbox[3] - hbbox[1]) // 2 - hbbox[1]

    draw.ellipse(
        [emblem_cx - radius, emblem_cy - radius, emblem_cx + radius, emblem_cy + radius],
        outline=GOLD,
        width=4,
    )
    import math

    for i in range(8):
        angle = math.radians(i * 45)
        x_inner = emblem_cx + int(math.cos(angle) * (radius + 8))
        y_inner = emblem_cy + int(math.sin(angle) * (radius + 8))
        x_outer = emblem_cx + int(math.cos(angle) * (radius + 22))
        y_outer = emblem_cy + int(math.sin(angle) * (radius + 22))
        draw.line([(x_inner, y_inner), (x_outer, y_outer)], fill=GOLD, width=4)

    draw.text((text_x + 3, text_y + 3), hinode_text, font=hinode_font, fill=GOLD_DARK)
    draw.text((text_x, text_y), hinode_text, font=hinode_font, fill=GOLD)

    return img


def main() -> int:
    print(f"[label] saída = {OUTPUT_PATH}")
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    img = build_label()
    img.save(OUTPUT_PATH, format="PNG")
    print(f"[label] OK ({img.size[0]}x{img.size[1]} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
