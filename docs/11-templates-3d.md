# 11 — Templates 3D (catálogo, normalização, procedural)

> **O que você vai aprender neste doc**
> - O que são os GLBs "template" e onde moram (`assets/templates/`), com a distinção raw × normalized.
> - O processo **offline** de normalização (Blender) que padroniza nós e escala.
> - Para que eles servem **hoje**: exclusivamente como referência do dataset sintético do benchmark.
>
> **Pré-requisitos:** [04 - Estrutura de pastas](04-estrutura-de-pastas.md).

> **Mudança de escopo (2026-08).** O `TemplateProcessor`, o `PIPELINE_MODE=template`, o `templates_catalog.py` e o `classifier.py` foram **removidos** — ver [16 - Auditoria do Blender](16-auditoria-blender.md). Os GLBs em `assets/templates/normalized/` **continuam versionados** porque `eval/synthetic_dataset.py` os usa como referência para gerar o dataset sintético do benchmark. Nenhum código de runtime os consome.

## Estrutura de pastas

- `assets/templates/raw/` — modelos originais (pasta **gitignored**; licenças e tamanho).
- `assets/templates/catalog.json` — metadados dos *raw* (caminho, licença, notas).
- `assets/templates/ATTRIBUTIONS.md` — créditos e licenças.
- `assets/templates/normalized/` — GLBs normalizados (versionados no Git).

Templates disponíveis: `feeling_rectangular_blue` (procedural V2, não Sketchfab), `rectangular_basic`, `cylindrical_basic`, `square_compact`, `round_spherical`, `ornamental_modernist`.

## Uso atual: dataset sintético do benchmark

[`eval/synthetic_dataset.py`](../eval/synthetic_dataset.py) renderiza vistas cardeais a partir de um GLB de referência para alimentar o benchmark comparativo. O default é:

```python
glb_path=Path("assets/templates/normalized/feeling_rectangular_blue.glb")
```

É o único consumidor desses arquivos hoje. Apagá-los quebraria a geração do dataset.

## Normalização (offline)

- Script: [`scripts/blender/normalize_template.py`](../scripts/blender/normalize_template.py) — roda no Blender, importa `raw/.../scene.gltf`, agrupa malhas, renomeia nós (`Bottle`, `Cap`, `Liquid`, `Label` conforme *strategy*), adiciona plano de label se necessário, centra, escala altura 1, exporta `normalized/<id>.glb`.
- Script auxiliar: [`scripts/blender/inspect_raw_templates.py`](../scripts/blender/inspect_raw_templates.py) — inspeciona materiais/meshes dos brutos.

> A convenção de nós (`Bottle`/`Cap`/`Liquid`/`Label`) existia para o `customize_template.py`, que foi removido. Ela é preservada nos scripts porque os GLBs versionados já a seguem e regerá-los sem ela invalidaria as atribuições.

## Template procedural Hinode (Feelin' Flame) — V2

- **Geração da label PNG**: [`scripts/build_feeling_label.py`](../scripts/build_feeling_label.py) (PIL) → `feeling_rectangular_blue_label.png` junto ao GLB.
- **Geração do GLB**: [`scripts/blender/generate_feeling_template.py`](../scripts/blender/generate_feeling_template.py) — geometria com *bevels*, materiais vidro/água/base/capa, plano de label com UVs 0..1, export.
- **Preview Cycles (opcional)**: [`scripts/blender/preview_feeling_template.py`](../scripts/blender/preview_feeling_template.py).

Estes três passos **não** são invocados automaticamente no servidor; atualizam o artefato em `assets/templates/normalized/`.

## Servir templates via HTTP (removido)

O mount `/templates` em `create_app` foi removido junto com a chave `TEMPLATES_DIR`. Para inspecionar um template, abra o `.glb` direto no viewer local (`storage/model_viewer.html`) servindo a pasta do backend por HTTP.

## Validação

[`tests/assets/test_normalized_templates.py`](../tests/assets/test_normalized_templates.py) continua verificando integridade e convenção dos GLBs versionados.

## Leituras relacionadas

- [09 — Pipeline 3D (abstração `Processor`)](09-pipeline-3d.md)
- [04 — Estrutura de pastas](04-estrutura-de-pastas.md) (árvore detalhada)
- [16 — Auditoria do papel do Blender](16-auditoria-blender.md) (por que o caminho de templates saiu)
