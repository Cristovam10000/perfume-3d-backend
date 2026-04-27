# 10b — Segmentação de fundo e extração de label

Duas etapas de **pré-processamento de imagem** que preparam as fotos do frasco antes
da reconstrução 3D. Ambas seguem o padrão Strategy do restante do módulo: ABC +
implementação desativada (zero deps) + implementação real trocável por configuração.

---

## Removedor de fundo — `BackgroundRemover`

Recebe uma foto do frasco e entrega um **PNG RGBA** em que o canal alpha é a máscara
da silhueta: 255 = frasco, 0 = fundo removido.

### `DisabledBackgroundRemover`

Copia o arquivo de entrada sem alterar nada. Use quando `rembg` não estiver instalado
ou quando a fase seguinte (extração de label, reconstrução) não precisar da máscara.
Não exige dependências extras.

### `RembgBackgroundRemover` (quando `BACKGROUND_REMOVER_TYPE=rembg`)

Usa a biblioteca [rembg](https://github.com/danielgatis/rembg) com o modelo
**`isnet-general-use`** — melhor equilíbrio qualidade/velocidade para fotos de
produtos com fundo relativamente neutro.

- A sessão rembg é inicializada preguiçosamente na primeira chamada e reutilizada
  nas seguintes (cache na instância). Isso evita recarregar ~200 MB de pesos a cada job.
- A inferência roda em `asyncio.to_thread` para não bloquear o event loop do FastAPI.
- A saída é sempre convertida para RGBA antes de salvar, mesmo que a entrada seja JPEG.
- **Primeira execução**: rembg faz download automático dos pesos ONNX para `~/.u2net/`
  (~200 MB). As execuções seguintes usam o cache local.

**Dependência:** `pip install -r requirements-vision.txt`

**GPU (opcional):** em placas RTX (e.g. RTX 5050), instale `onnxruntime-gpu` após
instalar o requirements-vision.txt para ~5× de aceleração:

```bash
pip install onnxruntime-gpu
```

---

## Extrator de label — `LabelExtractor`

Recebe a foto original (RGB) e a máscara RGBA do `BackgroundRemover`. Localiza a
região retangular da label frontal, corrige a perspectiva e entrega um **PNG plano**
pronto para ser projetado como textura no template 3D.

Retorna `ExtractedLabel` (com `image_path`, `confidence`, `aspect_ratio`) ou `None`
quando nenhuma região plausível for encontrada.

### `DisabledLabelExtractor`

Sempre retorna `None`. Use quando a extração não é necessária (e.g. templates sem plano
de label, testes de integração do pipeline principal).

### `HomographyLabelExtractor` (quando `LABEL_EXTRACTOR_TYPE=homography`)

Detecção baseada em contorno + transformação de perspectiva via OpenCV.

**Algoritmo:**

1. Limiariza o canal alpha da máscara para obter a silhueta binária do frasco.
2. Dentro da bounding box do frasco, aplica `cv2.Canny` na imagem RGB original para
   realçar as bordas da label.
3. Encontra contornos via `findContours` e aproxima para quadriláteros (`approxPolyDP`
   com 4 vértices).
4. Filtra candidatos por:
   - **Área**: entre `min_area_ratio` (5%) e `max_area_ratio` (60%) da área da máscara.
   - **Proporção**: entre 0.3 e 3.0 (labels não são quadradas nem extremamente finas).
   - **Posição**: centrado horizontalmente no frasco (desvio ≤ 35% da largura do frasco).
5. Escolhe o maior contorno válido. Se nenhum → retorna `None`.
6. Ordena os 4 cantos em [TL, TR, BR, BL] via soma/diferença das coordenadas (`_ordenar_cantos`).
7. Calcula retângulo alvo: `target_width` × `(target_width / aspect_ratio)`.
8. `getPerspectiveTransform` + `warpPerspective` para achatar a label.
9. Salva como PNG e retorna `ExtractedLabel`.

O campo `confidence` é `area_contorno / area_mascara` (limitado a 1.0): quanto maior
a label em relação ao frasco, maior a confiança de que foi a label que foi detectada,
e não um artefato pequeno.

**Dependência:** `pip install -r requirements-vision.txt`

---

## Dependências (`requirements-vision.txt`)

```
rembg>=2.0.50
opencv-python>=4.10
numpy>=1.26
pillow>=10.0
```

Instale **apenas** quando for ativar `BACKGROUND_REMOVER_TYPE=rembg` ou
`LABEL_EXTRACTOR_TYPE=homography`. As implementações `Disabled*` funcionam sem
nenhuma dependência extra.

---

## Leituras relacionadas

- [02 — Stack tecnológico](02-stack-tecnologico.md)
- [10 — Classificador (CLIP) e detector de cor](10-classificador-e-cor.md)
- Código: [`app/modules/captures/background_remover.py`](../app/modules/captures/background_remover.py), [`app/modules/captures/label_extractor.py`](../app/modules/captures/label_extractor.py)
