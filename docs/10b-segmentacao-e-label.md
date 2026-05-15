# 10b — Segmentação de fundo e extração de label

Duas etapas de **pré-processamento de imagem** que preparam as fotos do frasco antes da reconstrução 3D. Ambas são *stages* do `IntegratedPipeline` (ver [09f](09f-pipeline-integrado.md)) e seguem o padrão Strategy do restante do módulo: ABC + implementação desativada (zero deps) + implementação real trocável por configuração.

| Stage | Posição no pipeline | Componente |
|---|---|---|
| Remoção de fundo | (2) — depois do preprocess, antes do cache | `RembgBackgroundRemover` |
| Extração de label | (7) — depois do refiner, antes do projector | `HomographyLabelExtractor` |

---

## Removedor de fundo — `BackgroundRemover`

Recebe uma foto do frasco e entrega um **PNG RGBA** em que o canal alpha é a máscara da silhueta: 255 = frasco, 0 = fundo removido.

### `DisabledBackgroundRemover`

Copia o arquivo de entrada sem alterar nada. Use quando `rembg` não estiver instalado ou quando estiver depurando isoladamente. **Não recomendado em produção** — o Hunyuan inclui partes do fundo como geometria se receber JPEG cru. Não exige dependências extras.

### `RembgBackgroundRemover` (quando `BACKGROUND_REMOVER_TYPE=rembg`)

Usa a biblioteca [rembg](https://github.com/danielgatis/rembg) com o modelo **`isnet-general-use`** — melhor equilíbrio qualidade/velocidade para fotos de produtos com fundo relativamente neutro.

- A sessão rembg é inicializada preguiçosamente na primeira chamada e reutilizada nas seguintes (cache na instância). Isso evita recarregar ~200 MB de pesos a cada job.
- A inferência roda em `asyncio.to_thread` para não bloquear o event loop do FastAPI.
- A saída é sempre convertida para RGBA antes de salvar, mesmo que a entrada seja JPEG.
- **Primeira execução**: rembg faz download automático dos pesos ONNX para `~/.u2net/` (~200 MB). As execuções seguintes usam o cache local.

**Dependência:** `pip install -r requirements-vision.txt`

**GPU (opcional):** em placas RTX (e.g. RTX 5050), instale `onnxruntime-gpu` após instalar o requirements-vision.txt para ~5× de aceleração:

```bash
pip install onnxruntime-gpu
```

### Encaixe no `IntegratedPipeline`

| Entrada | Saída | Falha |
|---|---|---|
| `tmp/<job>/preprocessed/*.jpg` (do stage 1) | `tmp/<job>/masked/*.png` (RGBA com alpha) | Degrade: pipeline cai para `DisabledBackgroundRemover` (cópia). Loga warning. Hunyuan recebe foto sem máscara — qualidade cai. |

A máscara é usada por dois stages depois:
- **Stage 4 (Hunyuan)**: recebe as imagens RGBA segmentadas (qualidade significativamente melhor que foto crua).
- **Stage 7 (LabelExtractor)**: usa o canal alpha para limitar a busca da label à área do frasco.

---

## Extrator de label — `LabelExtractor`

Recebe a foto preprocessada (RGB) e a máscara RGBA do `BackgroundRemover`. Localiza a região retangular da label frontal, corrige a perspectiva e entrega um **PNG plano** pronto para ser ampliado pelo `LabelUpscaler` e projetado pelo `LabelProjector`.

Retorna `ExtractedLabel` (com `image_path`, `confidence`, `aspect_ratio`) ou `None` quando nenhuma região plausível for encontrada.

### `DisabledLabelExtractor`

Sempre retorna `None`. Use quando a extração não é necessária (e.g. testes de integração focados no Hunyuan).

### `HomographyLabelExtractor` (quando `LABEL_EXTRACTOR_TYPE=homography`)

Detecção baseada em contorno + transformação de perspectiva via OpenCV.

**Algoritmo:**

1. Limiariza o canal alpha da máscara para obter a silhueta binária do frasco.
2. Dentro da bounding box do frasco, aplica `cv2.Canny` na imagem RGB original para realçar as bordas da label.
3. Encontra contornos via `findContours` e aproxima para quadriláteros (`approxPolyDP` com 4 vértices).
4. Filtra candidatos por:
   - **Área**: entre `min_area_ratio` (5%) e `max_area_ratio` (60%) da área da máscara.
   - **Proporção**: entre 0.3 e 3.0 (labels não são quadradas nem extremamente finas).
   - **Posição**: centrado horizontalmente no frasco (desvio ≤ 25% da largura do frasco).
   - **Sobreposição com silhueta**: ≥ 70% do candidato deve estar dentro do corpo do frasco (rejeita tags físicas penduradas no gargalo).
5. Escolhe o maior contorno válido. Se nenhum → retorna `None`.
6. Ordena os 4 cantos em [TL, TR, BR, BL] via soma/diferença das coordenadas (`_ordenar_cantos`).
7. Calcula retângulo alvo: `target_width` × `(target_width / aspect_ratio)`.
8. `getPerspectiveTransform` + `warpPerspective` para achatar a label.
9. Salva como PNG e retorna `ExtractedLabel`.

O campo `confidence` é `area_contorno / area_mascara` (limitado a 1.0): quanto maior a label em relação ao frasco, maior a confiança de que foi a label que foi detectada, e não um artefato pequeno.

**Dependência:** `pip install -r requirements-vision.txt`

### Encaixe no `IntegratedPipeline`

| Entrada | Saída | Falha |
|---|---|---|
| foto preprocessada + máscara RGBA + `LABEL_MIN_CONFIDENCE` (default 0.3) | `tmp/<job>/label_raw.png` (ou `None`) | O pipeline tenta fallback por recorte (heurística de bordas em região central/direita). Se o fallback também falhar, devolve `None` — o `LabelProjector` degrada para cópia do `refined.glb`. |

O pipeline itera todas as fotos preprocessadas até encontrar uma com `confidence ≥ label_min_confidence` (não usa só a primeira). Isso ajuda em sets de fotos onde a primeira é uma vista lateral.

---

## Dependências (`requirements-vision.txt`)

```
rembg>=2.0.50
opencv-python>=4.10
numpy>=1.26
pillow>=10.0
```

Instale **apenas** quando for ativar `BACKGROUND_REMOVER_TYPE=rembg` ou `LABEL_EXTRACTOR_TYPE=homography`. As implementações `Disabled*` funcionam sem nenhuma dependência extra.

No pipeline integrado em produção, ambos são esperados como `rembg` e `homography`. Manter os `Disabled*` é só para suíte de testes e ambientes que não conseguem instalar `opencv-python` (raro).

---

## Leituras relacionadas

- [09f — Pipeline integrado](09f-pipeline-integrado.md) (composição)
- [09b — Pipeline IA: Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md) (recebe as fotos segmentadas)
- [09e — Aplicação de Label Real](09e-aplicacao-label.md) (consumidor da label extraída)
- [02 — Stack tecnológico](02-stack-tecnologico.md) (deps de visão)
- [10 — Embedder CLIP e detector de cor](10-classificador-e-cor.md)
- Código:
  [`app/modules/captures/background_remover.py`](../app/modules/captures/background_remover.py),
  [`app/modules/captures/label_extractor.py`](../app/modules/captures/label_extractor.py)
