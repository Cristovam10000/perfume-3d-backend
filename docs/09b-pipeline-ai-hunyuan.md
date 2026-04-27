# 09b — Pipeline IA: Hunyuan3D-2mv

Alternativa ao `TemplateProcessor` que usa o modelo de IA [Hunyuan3D-2mv](https://github.com/Tencent/Hunyuan3D-2)
para gerar malhas 3D diretamente das fotos do produto, sem necessidade de templates GLB pré-criados.

> **Status:** disponível como processor standalone (Fase 2). Integração com `CaptureService`
> e roteamento entre processors chegam na Fase 4.

## Visão geral

O `TemplateProcessor` gera modelos de alta qualidade para frascos conhecidos, mas exige que
um template GLB normalizado exista para cada formato de frasco. O `Hunyuan3DProcessor` não
exige template: recebe de 1 a 6 fotos do frasco e gera a geometria e textura PBR do zero,
possibilitando generalizar para qualquer produto sem trabalho manual de modelagem.

## Arquitetura: backend → HTTP → Docker → GPU

```
FastAPI (back/)
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

O backend **não importa** `torch`, `transformers`, nem qualquer lib ML pesada.
Toda a inferência fica no contêiner isolado, com sua própria versão de Python,
CUDA 12.8 e dependências. A comunicação é puramente HTTP multipart.

## Como subir o contêiner

Veja [docker/hunyuan/README.md](../../docker/hunyuan/README.md) para instruções
detalhadas. Resumo:

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

## Trade-offs: Hunyuan3D vs TemplateProcessor

| | `TemplateProcessor` | `Hunyuan3DProcessor` |
|---|---|---|
| Tempo por job | ~10s (Blender headless) | 3–5min (IA na GPU) |
| VRAM necessária | 0 (só CPU) | ~6GB (profile 4) |
| Templates necessários | Sim (GLB por forma) | Não |
| Qualidade (frascos conhecidos) | Alta (geometria exata) | Boa (estimativa IA) |
| Qualidade (frascos novos) | Depende do template mais próximo | Razoável |
| Textura da label | Via `LabelExtractor` + Blender | Inferida das fotos |

## Limitações conhecidas

- **Vidro translúcido**: o Hunyuan3D-2mv tende a tratar vidro como superfície opaca.
  Materiais de vidro com PBR realista exigem pós-processamento (Fase 3 planejada:
  substituição de shader no Blender).
- **Tampa**: em frascos com tampa destacada, o modelo pode fundir a tampa ao corpo
  dependendo do ângulo das fotos. Fotos com a tampa claramente separada ajudam.
- **Fundo não removido**: enviar fotos sem remoção de fundo (`BackgroundRemover`)
  degrada significativamente a qualidade da malha gerada — o modelo inclui
  partes do fundo como geometria.
- **Tempo de geração**: 3–5 minutos inviabiliza uso síncrono; o `CaptureService`
  precisa do modelo de fila (já implementado) para gerir esses jobs.

## Próximos passos

- **Fase 3**: refinamento da malha gerada — substituição do material de vidro por
  shader fisicamente correto no Blender, e aplicação da label via `LabelExtractor`.
- **Fase 4**: roteamento inteligente — `CaptureService` decide entre `TemplateProcessor`
  e `Hunyuan3DProcessor` com base em `template_id`, velocidade desejada ou flag do usuário.
  Também integra `BackgroundRemover` e `LabelExtractor` no fluxo do job.

## Leituras relacionadas

- [09 — Pipeline 3D (TemplateProcessor e Blender)](09-pipeline-3d.md)
- [10b — Segmentação e extração de label](10b-segmentacao-e-label.md) (entrada do Hunyuan)
- Código: [`app/modules/captures/processor.py`](../app/modules/captures/processor.py) (classe `Hunyuan3DProcessor`)
- Docker: [`docker/hunyuan/`](../../docker/hunyuan/) (Dockerfile, server.py, README)
