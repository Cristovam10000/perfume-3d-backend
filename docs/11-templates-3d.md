# 11 — Templates 3D (catálogo, normalização, procedural)

## Catálogo textual (CLIP)

O ficheiro [`app/modules/captures/templates_catalog.py`](../app/modules/captures/templates_catalog.py) define `TEMPLATE_DESCRIPTIONS`: mapa `template_id` → descrição curta em **inglês** (requisito do CLIP base). Exemplos de chaves hoje:

- `feeling_rectangular_blue` — frasco retangular fino, azul escuro, tampa preta, texto dourado (template procedural V2, não Sketchfab)
- `rectangular_basic`, `cylindrical_basic`, `square_compact`, `round_spherical`, `ornamental_modernist` — a partir de modelos *raw* do catálogo Sketchfab, normalizados

O `build_classifier()` só inclui entradas cujo ficheiro `assets/templates/normalized/<id>.glb` exista.

## Estrutura de pastas

- `assets/templates/raw/` — modelos originais (pasta **gitignored**; licenças e tamanho).
- `assets/templates/catalog.json` — metadados dos *raw* (caminho, licença, notas).
- `assets/templates/ATTRIBUTIONS.md` — créditos e licenças.
- `assets/templates/normalized/` — GLBs prontos para o `TemplateProcessor` (versionados no Git).

## Normalização (offline)

- Script: [`scripts/blender/normalize_template.py`](../scripts/blender/normalize_template.py) — roda no Blender, importa `raw/.../scene.gltf`, agrupa malhas, renomeia nós (`Bottle`, `Cap`, `Liquid`, `Label` conforme *strategy*), adiciona plano de label se necessário, centra, escala altura 1, exporta `normalized/<id>.glb`.
- Script auxiliar: [`scripts/blender/inspect_raw_templates.py`](../scripts/blender/inspect_raw_templates.py) — inspeciona materiais/meshes dos brutos.

## Template procedural Hinode (Feelin' Flame) — V2

- **Geração da label PNG**: [`scripts/build_feeling_label.py`](../scripts/build_feeling_label.py) (PIL) → `feeling_rectangular_blue_label.png` junto ao GLB.
- **Geração do GLB**: [`scripts/blender/generate_feeling_template.py`](../scripts/blender/generate_feeling_template.py) — geometria com *bevels*, materiais vidro/água/base/capa, plano de label com UVs 0..1, export.
- **Preview Cycles (opcional)**: [`scripts/blender/preview_feeling_template.py`](../scripts/blender/preview_feeling_template.py).

Estes três passos **não** são invocados automaticamente no servidor; atualizam o artefato em `assets/templates/normalized/`.

## Servir templates via HTTP (debug)

- Com `create_app` padrão, se `TEMPLATES_DIR` existir, a app monta `/templates` → ficheiros estáticos do diretório normalizado, por exemplo: `GET /templates/feeling_rectangular_blue.glb`.
- O viewer em `storage/model_viewer.html` pode apontar para esses URLs.

## Leituras relacionadas

- [09 — Pipeline 3D](09-pipeline-3d.md) (como o runtime customiza o GLB)
- [04 — Estrutura de pastas](04-estrutura-de-pastas.md) (árvore detalhada)
