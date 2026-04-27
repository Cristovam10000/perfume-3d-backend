# 09 — Pipeline 3D (Processor e Blender)

O “motor” de geração do `.glb` é a abstração `Processor` e, em produção, o `TemplateProcessor` que invoca o Blender headless com um script Python embutido no repositório.

## `ProcessingInput` (dataclass)

Campos usados hoje:

- `job_id`, `image_paths` (fotos salvas no disco)
- `output_path` — destino do `.glb` final (ex.: `storage/models/<uuid>.glb`)
- `template_id` — nome base do template (ex.: `feeling_rectangular_blue`); se `None`, o `TemplateProcessor` usa `default_template_id` da instância
- `liquid_color` — string `#RRGGBB` ou `None` (vem do `AverageColorDetector` quando ativo)
- `label_image` — opcional; **não** é preenchido automaticamente pelo service (evita colar a foto inteira no plano da label; seria tarefa de um futuro *label extractor*)

## `FakeProcessor`

- Útil para desenvolvimento e testes: gera um GLB mínimo válido (cubo) via `struct` + JSON, sem dependências externas, com atraso simulado opcional.
- Ativado com `PROCESSOR_TYPE=fake` no `.env`.

## `TemplateProcessor`

- Resolve `templates_dir / f"{template_id}.glb"`.
- Monta linha de comando:

  `blender --background --python <customize_template.py> -- --template <path> --output <path> [--label-image <png>] [--liquid-color #HEX]`

- O subprocess roda com `subprocess.run` dentro de `asyncio.to_thread` para **não bloquear o event loop** e evitar problemas de subprocess async em alguns loops no Windows.
- Exige exit code 0 e arquivo de saída presente; senão levanta `ProcessingError` (o service marca o job como `error`).

## Script `customize_template.py` (dentro do Blender)

- Convenção de nós no GLB: `Bottle`, `Liquid` (material `water`), `Cap`, `Label` (material `LabelMaterial`); o script é tolerante a nós ausentes.
- Aplica `Base Color` no material `water` quando `--liquid-color` é passado.
- Aplica textura no `LabelMaterial` se `--label-image` existir.
- Exporta GLB com `bpy.ops.export_scene.gltf(export_format="GLB", export_apply=True)`.

## O que **não** acontece em runtime

- Não existe geração procedural completa de malha no request: os templates são **arquivos `.glb` versionados** em `assets/templates/normalized/`. Scripts como `generate_feeling_template.py` rodam **offline** (bancada) para atualizar um template.
- Não há fotogrametria (Meshroom/COLMAP) no pipeline HTTP atual.

## Leituras relacionadas

- [10 — Classificador e cor](10-classificador-e-cor.md) (de onde vêm `template_id` e cor)
- [11 — Templates 3D](11-templates-3d.md) (origem e manutenção dos GLBs)
- Código: [`app/modules/captures/processor.py`](../app/modules/captures/processor.py), [`app/modules/captures/blender_scripts/customize_template.py`](../app/modules/captures/blender_scripts/customize_template.py)
