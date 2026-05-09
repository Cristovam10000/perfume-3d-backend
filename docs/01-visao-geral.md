# 01 — Visão geral

## O que o backend é hoje

O `perfume-3d-backend` é um serviço HTTP em **FastAPI** que recebe um lote de fotos de um perfume, gera um modelo 3D `.glb` correspondente e devolve a URL do modelo pronto. É o servidor par do app Flutter em [`../../front`](../../front).

O backend **não faz fotogrametria real** (apesar do diagrama original ter previsto Meshroom/AliceVision). Em vez disso, usa uma abordagem mais defensável academicamente para o MVP:

1. um **classificador CLIP** decide qual template 3D pré-existente melhor representa a forma do frasco fotografado;
2. um **detector de cor** extrai a cor do líquido a partir de um crop central das fotos;
3. um **Processor** chama o **Blender headless** para customizar o template escolhido com a cor detectada;
4. o GLB customizado é servido via `StaticFiles` em `/files/models/<job_id>.glb`.

Esse fluxo está documentado em detalhe em [09 - Pipeline 3D](09-pipeline-3d.md).

## Fluxo ponta a ponta

```
[App Flutter]
   │
   │  POST /captures + N fotos JPEG
   ▼
[FastAPI / router.py]
   │
   ▼
[CaptureService.create_job]
   │   • cria UUID do job
   │   • salva fotos em storage/uploads/<job_id>/
   │   • registra CaptureJob + CaptureImage no Postgres (status=waiting)
   │   • enfileira o job em ProcessingQueue
   ▼
[Worker assíncrono — ProcessingQueue]
   │
   ▼
[CaptureService.process_job]
   │   • marca status=processing
   │   • chama Classifier.classify(fotos) → template_id
   │   • chama ColorDetector.detect(fotos) → "#RRGGBB"
   │   • chama Processor.process(input) → gera <job_id>.glb
   │   • marca status=completed e grava model_path
   │
   │  (concorrentemente, o app faz GET /captures/<id>/status a cada ~3s)
   ▼
[GET /captures/<job_id>/status]
   │   → { status: "completed", modelUrl: "http://.../files/models/<id>.glb" }
   ▼
[App baixa o GLB e renderiza com model_viewer_plus]
```

## Escopo atual (o que o backend faz)

- Receber 1..N fotos via `multipart/form-data` em `POST /captures`.
- Persistir job + imagens em PostgreSQL.
- Enfileirar e processar **um job por vez** num worker `asyncio` in-process.
- Classificar a forma do frasco entre **6 templates pré-existentes** com **OpenAI CLIP** (zero-shot por descrição em texto).
- Detectar **uma única característica visual**: cor hex média do crop central das fotos.
- Customizar o template escolhido no **Blender headless** aplicando a cor detectada e (opcionalmente) uma label PNG.
- Expor o GLB final via `StaticFiles` em `/files/models/<id>.glb`.
- Responder `GET /captures/<id>/status` com URL absoluta do modelo (montada a partir de `request.base_url` para funcionar tanto em emulador quanto em device físico).
- Servir templates puros via `/templates/<id>.glb` para inspeção/debug.
- Oferecer um **pipeline alternativo por IA generativa** (Hunyuan3D-2mv em contêiner Docker dedicado) com pré-processamento clássico de imagem, limpeza conservadora de malha, refinamento de shader de vidro PBR e projeção de label real extraída da foto. Esse caminho **não está integrado ao `CaptureService` ainda** (Fase 7); cada componente é exercitado standalone via smokes manuais (`scripts/smoke_phase3.py`, `smoke_phase4.py`, `smoke_phase5.py`). Ver [09b](09b-pipeline-ai-hunyuan.md), [09c](09c-refinamento-mesh.md), [09d](09d-preprocessamento-e-cleanup.md), [09e](09e-aplicacao-label.md).
- Expor uma **API comercial mínima** (`/sales/*`) para o módulo do app que gerencia clientes, produtos, vendas parceladas, estoque e pagamentos — modelo monolítico modular: o módulo `app/modules/sales/` compartilha o mesmo banco do `captures` (ver [13](13-endpoints-http.md), [12](12-armazenamento-e-banco.md)).

## Fora do escopo (o que **não** existe)

- Autenticação, multi-tenant, RBAC.
- Pipeline de fotogrametria real (Meshroom/AliceVision/COLMAP) — está no [roadmap](#roadmap-curto).
- Object storage (S3, Firebase, GCS) — armazenamento é local em disco.
- Observability (Prometheus, OpenTelemetry, Sentry).
- Migrations com Alembic — hoje o schema é criado por `Base.metadata.create_all()` no startup.
- Histórico de jobs (`GET /captures/history`) ou paginação.
- Cache, rate limiting, fila distribuída (Celery/RQ/Arq), worker em outra máquina.
- Renderização server-side dos modelos (PNG preview da banca foi gerado offline com Cycles, fora do request).

## Premissas e simplificações deliberadas

- **Worker único in-process**: bom o bastante para MVP de TCC e demo local. Trocar por Celery/RQ é uma linha em `main.py` (substituir `ProcessingQueue` por outra implementação que respeite a mesma assinatura `submit/start/stop`).
- **Processor é uma Strategy plugável**: `FakeProcessor` (cubo sintético, ~3s, zero deps) ou `TemplateProcessor` (Blender, ~5-15s). Configurado por `PROCESSOR_TYPE` no `.env`.
- **Classifier também é Strategy**: `disabled` (sempre usa template default) ou `clip` (CLIP zero-shot, ~2GB de download da primeira vez). Configurado por `CLASSIFIER_TYPE`.
- **ColorDetector também**: `disabled` (cor padrão do material) ou `average` (RGB médio do crop central, requer Pillow). Configurado por `COLOR_DETECTOR_TYPE`.
- **Falha graciosa nas etapas opcionais**: se o classificador ou o detector de cor crasharem, o job não falha — cai no template/cor default e segue. Só falha de fato se o `Processor` em si crashar.
- **Schema criado no startup**: `create_all()` no `production_lifespan` cria tabelas se faltarem. Adequado pro MVP, mas não substitui Alembic em produção.

## Roadmap curto

O backend está estável no MVP atual. As evoluções planejadas/discutidas:

- **Fidelidade visual**: substituir o pipeline atual por **AI image-to-3D** (Hunyuan3D-2 ou TripoSR) ou **3D Gaussian Splatting**, mantendo `Processor` como Strategy. O ABC já comporta — basta adicionar `Hunyuan3DProcessor` e plugar via `PROCESSOR_TYPE=hunyuan3d`.
- **Histórico**: endpoint `GET /captures` paginado + tela de histórico no app.
- **Migrations**: introduzir Alembic quando o schema começar a evoluir.
- **Object storage**: trocar `LocalStorage` por `S3Storage` mantendo a interface.

Detalhes sobre evolução de fidelidade (fotogrametria, image-to-3D, splats) são decisões de produto/tese — ver conversas de planeamento e o roadmap do orientador, não estão rastreadas neste repositório como issue única.

## Decisões técnicas chave (TL;DR)

| Decisão | Por quê |
|---|---|
| **Templates pré-existentes** em vez de fotogrametria | Vidro e superfícies reflexivas quebram fotogrametria; templates dão resultado determinístico em ~5s. |
| **CLIP zero-shot** em vez de classificador treinado | Sem dataset rotulado de frascos. CLIP "entende" descrições em inglês ("a tall slim rectangular dark blue glass perfume bottle"). |
| **Blender via subprocess + thread** em vez de API Python | `bpy` é difícil de subir como lib em servidor; subprocess é o jeito padrão e isolado. `subprocess.run` em `asyncio.to_thread` evita `NotImplementedError` no Windows com event loop não-Proactor. |
| **Single async worker in-process** | Suficiente para 1 usuário fazendo 1 job por vez (cenário de demo de TCC). Trocar por Celery é local em 1 ponto. |
| **Static files servindo o GLB** em vez de streaming | `StaticFiles` lida com Range requests e ETag de graça; o app só precisa fazer GET. |
| **`request.base_url` para montar `modelUrl`** | Mesmo DB funciona em emulador (`10.0.2.2`) e device físico (IP da LAN) sem reconfig. |

## Próximas leituras

- Como rodar: [03 - Inicialização do projeto](03-inicializacao-do-projeto.md).
- Onde cada coisa mora: [04 - Estrutura de pastas](04-estrutura-de-pastas.md).
- Como o pipeline funciona em detalhe: [09 - Pipeline 3D](09-pipeline-3d.md).
