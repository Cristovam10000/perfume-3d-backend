# 10 — Classificador (CLIP) e detector de cor

Duas etapas **opcionais** antes de chamar o `Processor`, ambas com falha “graciosa” (não derrubam o job se explodirem).

## Classificador de forma — `Classifier`

- **`DisabledClassifier`**: devolve sempre `default_template_id` (do `.env` ou do construtor), confiança 1.0. Zero dependências extras.
- **`CLIPClassifier`** (quando `CLASSIFIER_TYPE=clip` e deps instaladas):
  - Carrega `CLIPModel` + `CLIPProcessor` do HuggingFace (`CLIP_MODEL`, default `openai/clip-vit-base-patch32`). Pesos na primeira execução podem exigir download (~centenas de MB).
  - O conjunto de rótulos textuais vem de `templates_catalog.TEMPLATE_DESCRIPTIONS`, **filtrado** em `build_classifier()`: só entram `template_id` cujo ficheiro `templates_dir / f"{id}.glb"` exista. Assim o CLIP nunca escolhe um template inexistente.
  - Para cada imagem, softmax sobre as descrições; soma votos se houver N imagens; o vencedor vira `template_id`.
  - Inferência roda em `asyncio.to_thread` para não bloquear o event loop.
- Requer `pip install -r requirements-classifier.txt` (torch, transformers, pillow).

## Detector de cor — `ColorDetector`

- **`DisabledColorDetector`**: sempre `None` → o customize não aplica `--liquid-color` (material default do template).
- **`AverageColorDetector`** (`COLOR_DETECTOR_TYPE=average`):
  - Abre cada imagem com Pillow, corrige EXIF com `ImageOps.exif_transpose`.
  - Recorta o **centro** da imagem (razão configurável, default 40% da largura/altura).
  - Calcula RGB médio; opcionalmente filtra pixels muito acinzentados (`_chromatic_pixels`) para aproximar a cor do líquido e não o fundo.
  - Retorna string `#RRGGBB` em maiúsculas.
- Não utiliza **OpenCV**; seria possível trocar a implementação no futuro mantendo a mesma ABC.

## Ordem e tolerância a falhas

1. `classify` → `template_id` (ou None em erro → processor usa default interno)
2. `detect` → `liquid_color` (ou None)
3. `processor.process(ProcessingInput(...))`

Falhas em classificador ou detector são logadas; o job continua com defaults.

## Leituras relacionadas

- [02 — Stack tecnológico](02-stack-tecnologico.md) (deps do classificador)
- Código: [`app/modules/captures/classifier.py`](../app/modules/captures/classifier.py), [`app/modules/captures/color_detector.py`](../app/modules/captures/color_detector.py), [`app/modules/captures/templates_catalog.py`](../app/modules/captures/templates_catalog.py)
