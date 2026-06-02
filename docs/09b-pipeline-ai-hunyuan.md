# 09b — Pipeline IA: Hunyuan3D-2mv

> **O que você vai aprender neste doc**
> - Por que a geração 3D vive em um **container Docker separado** (com GPU) e não no backend.
> - Como o `Hunyuan3DProcessor` (cliente HTTP) conversa com esse serviço via `POST /generate`.
> - Os parâmetros de inferência (`octree_resolution`, `num_inference_steps`, ...) e por que esses valores.
> - As limitações do modelo (vidro, tampa, texto da label) e como o pós-processamento as mitiga.
>
> **Pré-requisitos:** [09f - Pipeline integrado](09f-pipeline-integrado.md) (onde este stage encaixa).

Implementação da etapa de **geração** dentro do `IntegratedPipeline`. O `Hunyuan3DProcessor` é o cliente HTTP que conversa com o contêiner Docker dedicado ao modelo [Hunyuan3D-2mv](https://github.com/Tencent/Hunyuan3D-2) (fork low-VRAM por deepbeepmeep). Recebe 1–6 fotos pré-processadas e segmentadas e devolve um GLB com geometria + textura PBR.

Esse processor **não** é mais usado como Strategy raiz solta — ele é um *stage* dentro do `IntegratedPipeline` (ver [09f](09f-pipeline-integrado.md)). Continua sendo possível instanciá-lo direto nos smokes para depurar a inferência isoladamente.

## Por que Hunyuan3D-2mv

- `TemplateProcessor` gera modelos de alta qualidade para frascos conhecidos, mas exige um GLB normalizado para cada formato — não generaliza.
- Hunyuan3D-2mv aceita até 6 vistas, infere geometria + textura PBR sem template, e funciona em GPUs domésticas (testado em RTX 5050 8GB com `mmgp profile 4`).
- Para perfumes recorrentes (mesmo frasco fotografado de novo), o **cache de similaridade CLIP** evita pagar o custo de inferência novamente — ver [09g](09g-cache-similaridade-clip.md).

## Arquitetura: backend → HTTP → Docker → GPU

```
FastAPI (back/)
    └── IntegratedPipeline
            └── Hunyuan3DProcessor
                    │  httpx.AsyncClient
                    │  POST /generate (multipart, 1-6 PNGs RGBA)
                    ▼
            Docker container (docker/hunyuan/)
                    │  FastAPI + uvicorn
                    │  Hunyuan3DDiTFlowMatchingPipeline  (shape)
                    │  Hunyuan3DPaintPipeline             (texture)
                    │  mmgp offload profile 4
                    ▼
            NVIDIA RTX 5050 8GB
                    │
                    ▼
            GLB binário com PBR → response body
```

O backend **não importa** `torch`, `transformers`, nem qualquer lib ML pesada. Toda a inferência fica no contêiner isolado, com sua própria versão de Python, CUDA 12.8 e dependências. A comunicação é puramente HTTP multipart.

## Parâmetros padrão (operacionalmente validados)

| Parâmetro | Valor | Observação |
|---|---|---|
| `octree_resolution` | 384 | Mais detalhe geométrico; cabe em 8GB com `mmgp profile 4`. |
| `num_inference_steps` | 75 | Equilíbrio entre estabilidade de superfície e tempo. |
| `guidance_scale` | 7.5 | CFG/guidance da forma. |
| `mc_algo` | `mc` | Marching Cubes clássico. `dmc` (Dual MC) foi tentado mas a `diso` falha no container (símbolo CUDA). O server faz fallback automático se `dmc` quebrar. |
| `texture_resolution` | 2048 | Textura multi-view quando disponível, single-view caso contrário. |
| `timeout_seconds` (cliente) | 1200 | 20 min — uma run com parâmetros pesados pode demorar 6–12 min na RTX 5050. |
| `service_url` | `http://localhost:7860` | Configurável via `HUNYUAN_URL` no `.env`. |

Esses defaults vieram da sessão `historico/2026-05-09_integracao-sales-e-melhorias-hunyuan.md`.

## Como subir o contêiner

Veja [docker/hunyuan/README.md](../../docker/hunyuan/README.md) para instruções detalhadas. Resumo:

```bash
# Na raiz do repositório (C:\TCC):

# Build (20-40min na primeira vez — baixa ~5GB de pesos):
docker build -t perfume-hunyuan ./docker/hunyuan

# Run com GPU:
docker run --gpus all -p 7860:7860 perfume-hunyuan

# Ou via docker-compose (inclui postgres + volume persistente):
docker compose up hunyuan
```

Aguarde ~2 minutos para o modelo carregar, então:

```bash
curl http://localhost:7860/health
# → {"status":"ready"}
```

## Contrato HTTP do contêiner

- `GET /health` — `{"status": "loading" | "ready" | "error"}`.
- `POST /generate` (multipart):
  - `images`: 1..6 arquivos (PNG RGBA preferencial; o servidor faz `convert("RGBA")` mas máscara pré-aplicada melhora a qualidade do mesh).
  - `octree_resolution`, `num_inference_steps`, `guidance_scale`, `mc_algo`, `texture_resolution` — todos como `Form`.
  - **Resposta**: `model/gltf-binary` (GLB bruto). Header `Content-Type` confirma o formato.

O cliente Python valida o magic header `b"glTF"` antes de gravar em disco; se vier outra coisa, levanta `ProcessingError`.

## Pré-requisitos antes de chamar

O `IntegratedPipeline` garante isto, mas se você instanciar o processor solo:

- Serviço Hunyuan (`docker compose up hunyuan`) rodando e com modelo carregado (`/health → ready`).
- Imagens **pré-segmentadas** pelo `RembgBackgroundRemover` (Hunyuan inclui fundo como geometria se receber JPEG cru).
- Resolução das imagens ≤ 2048 px no maior lado (Hunyuan não consome mais que isso).

`template_id`, `liquid_color` e `label_image` do `ProcessingInput` são **ignorados** pelo `Hunyuan3DProcessor`. A integração com esses campos acontece em outros stages do pipeline:

- `liquid_color`: a cor é inferida pelo Hunyuan a partir das fotos; persistida como metadado em `modelos_3d_universais.liquid_color` se você quiser.
- `label_image`: o `IntegratedPipeline` extrai a label real via `LabelExtractor` e a projeta com `LabelProjector` no GLB do Hunyuan.

## Trade-offs: Hunyuan3D vs TemplateProcessor

| | `TemplateProcessor` (fallback) | `Hunyuan3DProcessor` (default) |
|---|---|---|
| Tempo por job (miss) | ~10s (Blender headless) | 3–8min (IA na GPU) |
| Tempo por job (hit do cache) | n/a | ~5s (cópia do GLB) |
| VRAM necessária | 0 (só CPU) | ~6-8GB (profile 4) |
| Templates pré-existentes? | Sim (GLB por forma) | Não |
| Qualidade (frascos conhecidos) | Alta (geometria exata) | Boa (estimativa IA) |
| Qualidade (frascos novos) | Depende do template mais próximo | Razoável |
| Textura da label | `LabelExtractor` + Blender (decal) | Inferida das fotos pelo Hunyuan, depois substituída pelo decal do `LabelProjector` (ver [09e](09e-aplicacao-label.md)) |
| Cor do líquido | Veio do `AverageColorDetector` (depreciado) ou metadado do cache | Inferida pelo Hunyuan |

## Falhas e degrade

Dentro do `IntegratedPipeline`, falhas do Hunyuan caem em duas categorias:

1. **Recuperáveis no próprio contêiner** (server.py faz fallback): `dmc → mc`, `octree 384 → 256`, textura multi-view → single-view, lista vazia (`PipelineSemMalhaError`). Tudo isso é log + retry interno.
2. **Não recuperáveis** (`/health` não responde, timeout do cliente, GLB inválido): o pipeline integrado decide entre:
   - Fallback para `TemplateProcessor` se `PIPELINE_FALLBACK_TO_TEMPLATE=true` (default `false` — preserva a falha como sinal de problema operacional).
   - Marcar o job como `error` com mensagem específica.

## Limitações conhecidas

- **Vidro translúcido**: o Hunyuan3D-2mv trata vidro como superfície opaca azulada. O `BlenderMeshRefiner` resolve isso aplicando shader PBR (ver [09c](09c-refinamento-mesh.md)).
- **Tampa**: em frascos com tampa destacada, o modelo pode fundir a tampa ao corpo dependendo do ângulo das fotos. Fotos com a tampa claramente separada ajudam; ângulo da câmera importa.
- **Fundo não removido**: enviar fotos sem `RembgBackgroundRemover` degrada significativamente a qualidade — o modelo inclui partes do fundo como geometria.
- **Tempo de geração**: 3–8 min inviabiliza uso síncrono; o cache + a fila do `CaptureService` mitigam isso.
- **Texto da label**: Hunyuan inventa texto. Por isso o pipeline integra `LabelExtractor` + `LabelProjector` (ver [09e](09e-aplicacao-label.md)).

## Leituras relacionadas

- [09 — Pipeline 3D (TemplateProcessor e Blender — fallback)](09-pipeline-3d.md)
- [09c — Refinamento de malha (shader de vidro PBR)](09c-refinamento-mesh.md)
- [09d — Pré-processamento e cleanup](09d-preprocessamento-e-cleanup.md)
- [09e — Aplicação de label](09e-aplicacao-label.md)
- [09f — Pipeline integrado (composição)](09f-pipeline-integrado.md)
- [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md)
- [10b — Segmentação e extração de label](10b-segmentacao-e-label.md) (entrada do Hunyuan)
- Código: [`app/modules/captures/processor.py`](../app/modules/captures/processor.py) (classe `Hunyuan3DProcessor`)
- Docker: [`docker/hunyuan/`](../../docker/hunyuan/) (Dockerfile, server.py, README)
