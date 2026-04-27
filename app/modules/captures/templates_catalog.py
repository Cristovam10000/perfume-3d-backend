"""Mapeamento de templates 3D normalizados → descrição em texto para CLIP.

Cada chave é um `template_id` (que deve corresponder a um arquivo GLB em
`assets/templates/normalized/<template_id>.glb`); o valor é uma descrição
curta em inglês que o CLIP compara com a imagem do produto.

Convenção das descrições:
- Em inglês (CLIP base é melhor em inglês);
- Comece sempre com "a" / "an" e termine sem ponto final;
- Foque em forma + material genérico, não em marca/produto específico.
"""

from __future__ import annotations

# Os templates listados aqui devem ter um GLB correspondente em
# `templates_dir`. A factory `build_classifier()` filtra automaticamente os
# que ainda não foram normalizados.
TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "feeling_rectangular_blue": "a tall slim rectangular dark blue glass perfume bottle with a black rectangular cap and gold vertical text",
    "rectangular_basic": "a tall rectangular glass perfume bottle with a square cap",
    "cylindrical_basic": "a tall cylindrical glass perfume bottle with a rounded body",
    "square_compact": "a small square compact glass perfume bottle",
    "round_spherical": "a round spherical glass perfume bottle",
    "ornamental_modernist": "an ornamental decorative perfume bottle with artistic design",
}
