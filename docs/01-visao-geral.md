# 01 — Visão geral

> **O que você vai aprender neste doc**
> - O que o backend faz, em uma frase, e qual problema ele resolve.
> - O caminho completo de uma foto até virar um `.glb` (o "fluxo ponta a ponta").
> - O que está **dentro** e **fora** do escopo, e o porquê de cada simplificação.
>
> **Pré-requisitos:** nenhum. Este é o ponto de partida. Depois dele, siga para
> [03 - Inicialização](03-inicializacao-do-projeto.md) (rodar) e
> [05 - Arquitetura](05-arquitetura.md) (entender as camadas).

## O que o backend é

O `perfume-3d-backend` é um serviço HTTP em **FastAPI** que recebe um lote de fotos de um perfume, gera um modelo 3D `.glb` correspondente e devolve a URL do modelo pronto. É o servidor par do app Flutter em [`perfume-3d-frontend`](../../perfume-3d-frontend).

A geração 3D usa um **pipeline integrado** baseado em IA generativa:

1. **Pré-processamento** clássico das fotos (EXIF, white balance, CLAHE, resize ≤2048).
2. **Remoção de fundo** via `rembg` (modelo `isnet-general-use`).
3. **Cache global por similaridade CLIP**: se as fotos baterem com um perfume já gerado **por qualquer usuário** (cross-tenant), devolve o GLB cacheado em segundos. Senão, segue para o Hunyuan.
4. **Hunyuan3D-2mv** (em contêiner Docker dedicado com GPU) gera geometria + textura PBR.
5. **Pós-processamento** no Blender headless: limpeza conservadora, shader de vidro PBR, extração da label real da foto e projeção como decal frontal.
6. **Persistência** do GLB final + embedding + metadados na tabela `modelos_3d_universais` (cache global, compartilhado entre todos os usuários). Se o `POST /captures` veio com `productId` opcional, também faz UPSERT em `modelos_3d_produto` para vincular o produto comercial daquele tenant ao molde universal.

O **`TemplateProcessor`** (caminho de templates Blender pré-existentes, usado em versões anteriores do MVP) foi **removido em 2026-08** junto com o fallback — ver [16 - Auditoria do Blender](16-auditoria-blender.md). Falha do Hunyuan agora marca o job como `error`.

Esse fluxo está documentado em detalhe em [09f - Pipeline integrado](09f-pipeline-integrado.md) e [09g - Cache de similaridade CLIP](09g-cache-similaridade-clip.md).

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
   │   • delega para IntegratedPipeline.process(input)
   │
   ▼
[IntegratedPipeline]
   │   (1) ImagePreprocessor    → fotos_clean/
   │   (2) BackgroundRemover    → fotos_mask/
   │   (3) ModelCache.lookup    → embedding CLIP + cosine vs modelos_3d_universais
   │
   ├── HIT  → copia cache/<id>.glb → output_path → fim
   │
   └── MISS:
       (4) Hunyuan3DProcessor   → raw.glb  (~3-5min, GPU)
       (5) TransparencyClassifier → body_mode (glass | keep | auto)
       (6) BlenderMeshRefiner   → refined.glb (segmenta corpo/tampa + vidro PBR)
       (7) LabelExtractor + Upscaler + Projector
                                → with_label.glb (degrade se não achou label)
       (8) ModelCache.store     → persiste GLB + embedding + metadata
   │
   │  • marca status=completed + grava model_path
   │
   │  (concorrentemente, o app faz GET /captures/<id>/status a cada ~3s)
   ▼
[GET /captures/<job_id>/status]
   │   → { status: "completed",
   │       message: "Modelo entregue pelo cache (...)" | "Modelo gerado via Hunyuan...",
   │       modelUrl: "http://.../files/models/<id>.glb", error: null }
   ▼
[App baixa o GLB e renderiza com model_viewer_plus]
```

## Escopo atual (o que o backend faz)

- Receber 1..N fotos via `multipart/form-data` em `POST /captures`.
- Persistir job + imagens em PostgreSQL.
- Enfileirar e processar **um job por vez** num worker `asyncio` in-process.
- Pré-processar as fotos (EXIF, gray-world WB, CLAHE no canal L do LAB, sharpen condicional, resize ≤2048).
- Remover o fundo via `rembg` (modelo `isnet-general-use`), entregando PNG RGBA com a silhueta do frasco.
- **Buscar o GLB no cache** comparando o embedding CLIP das fotos com a tabela `modelos_3d_universais`. Hit ≈ 5 s; miss segue o pipeline IA.
- Gerar geometria + textura via **Hunyuan3D-2mv** num contêiner Docker dedicado (GPU NVIDIA, ~3-5 min).
- Limpar a malha (Blender headless, em modo conservador / no-op por default).
- Refinar materiais aplicando shader de **vidro PBR** no corpo do frasco.
- Extrair a **label real da foto** via OpenCV (`HomographyLabelExtractor`), fazer upscale Lanczos para 2048 px e projetar como **decal frontal** no GLB.
- Persistir o GLB final + embedding + metadados (cor do líquido inferida, label) na tabela `modelos_3d_universais`.
- Expor o GLB final via `StaticFiles` em `/files/models/<id>.glb`.
- Responder `GET /captures/<id>/status` com URL absoluta do modelo (montada a partir de `request.base_url` para funcionar tanto em emulador Android quanto em device físico). Cache hit vs. geração se distinguem pelo campo `message` e pelo tempo de resposta — **não** há um campo `origem` dedicado (ver [13](13-endpoints-http.md)).
- Servir templates puros via `/templates/<id>.glb` para inspeção/debug.
- Expor uma **API comercial mínima** (`/sales/*`) para o módulo do app que gerencia clientes, produtos, vendas parceladas, estoque e pagamentos — modelo monolítico modular: o módulo `app/modules/sales/` compartilha o mesmo banco do `captures` (ver [13](13-endpoints-http.md), [12](12-armazenamento-e-banco.md)).

## Fora do escopo (o que **não** existe)

- Autenticação, multi-tenant, RBAC.
- Fotogrametria real (Meshroom/AliceVision/COLMAP) — descartada após validação em sessões anteriores; vidro e superfícies reflexivas quebram a correspondência de pontos.
- Object storage (S3, Firebase, GCS) — armazenamento é local em disco (`storage/cache/`, `storage/uploads/`, `storage/models/`).
- Observability (Prometheus, OpenTelemetry, Sentry).
- Migrations com Alembic — hoje o schema é criado por `Base.metadata.create_all()` no startup (já cobre `modelos_3d_universais`).
- Histórico de jobs (`GET /captures/history`) ou paginação.
- Cache, rate limiting, fila distribuída (Celery/RQ/Arq), worker em outra máquina.
- Pgvector / FAISS — busca de similaridade é linear sobre os embeddings na tabela `modelos_3d_universais`; cabe RAM até ~10k entradas. Acima disso troca-se o `ClipSimilarityCache` por uma implementação indexada mantendo a ABC `ModelCache`.
- Autenticação / multi-tenant real — não existe ainda. O esquema do cache (`modelos_3d_universais` global + `modelos_3d_produto` por tenant) **já está pronto** para quando isso for adicionado: basta colocar `usuario_id` em `produtos`, e o cache continua funcionando cross-tenant sem refactor.

## Premissas e simplificações deliberadas

- **Worker único in-process**: bom o bastante para MVP de TCC e demo local. Trocar por Celery/RQ é uma linha em `main.py` (substituir `ProcessingQueue` por outra implementação que respeite a mesma assinatura `submit/start/stop`).
- **Pipeline como Strategy plugável**: `FakeProcessor` (cubo sintético, ~3s, zero deps) ou `IntegratedPipeline` (cache + Hunyuan + pós-proc). Configurado por `PIPELINE_MODE` no `.env`.
- **Cada stage do pipeline também é Strategy**: `BackgroundRemover`, `ImagePreprocessor`, `TransparencyClassifier`, `MeshRefiner`, `LabelExtractor`, `LabelUpscaler`, `LabelProjector` — cada um com um `Disabled*` para teste e uma implementação real configurada por `.env`.
- **CLIP repurposado**: o `CLIPClassifier` legado, que escolhia o `template_id` entre 6 frascos, foi removido; o mesmo checkpoint serve hoje a três usos — `ImageEmbedder` (cache), `CLIPViewRouter` (rotulagem de vistas) e `ClipTransparencyClassifier` (vidro vs opaco).
- **`ColorDetector`**: mantido no código como histórico mas **não usado** pelo pipeline integrado (o Hunyuan infere cor das fotos). Pode ser ativado para preencher `liquid_color` como metadado se você quiser usar essa informação no `/sales/*`.
- **Falha graciosa em cada stage**:
  - Pré-processamento falha → segue com a foto original.
  - Remoção de fundo falha → segue com a foto preprocessada (qualidade do Hunyuan cai, mas o job termina).
  - Cache lookup falha → comporta como miss.
  - Label extraction falha → degrade, mantém `refined.glb` sem label.
  - **Hunyuan offline ou timeout** → marca o job como `error`. Não há fallback.
- **Schema criado no startup**: `create_all()` no `production_lifespan` cria as tabelas se faltarem, incluindo a `modelos_3d_universais`. Adequado para o MVP, mas não substitui Alembic em produção.
- **Threshold de similaridade do cache** inicia em `0.92` (cosine); precisa ser calibrado com fotos reais antes da defesa.

## Roadmap curto

O backend está em fase de **integração** do pipeline IA com cache. Evoluções planejadas:

- **Calibração do threshold do cache**: rodar dataset real, medir taxa de falso-positivo/falso-negativo, ajustar `CACHE_SIMILARITY_THRESHOLD`.
- **Endpoint admin do cache**: `GET /captures/cache` e `DELETE /captures/cache/<id>` para invalidação manual.
- **Histórico**: endpoint `GET /captures` paginado + tela de histórico no app.
- **Migrations**: introduzir Alembic quando o schema começar a evoluir.
- **Object storage**: trocar `LocalStorage` por `S3Storage` mantendo a interface.
- **Busca indexada**: trocar busca linear de embeddings por pgvector/FAISS quando o cache passar de ~10k entradas.

## Decisões técnicas chave (TL;DR)

| Decisão | Por quê |
|---|---|
| **Hunyuan3D-2mv** em vez de fotogrametria | Vidro e superfícies reflexivas quebram fotogrametria (Meshroom/COLMAP). Hunyuan3D-2mv aceita 1–6 vistas e infere geometria + textura. |
| **Cache global (cross-tenant) por similaridade CLIP** | Hunyuan custa ~3-5 min e GPU. Quando o app virar multi-usuário, o mesmo perfume vai ser fotografado por gente diferente — o GLB precisa ser **reaproveitado entre usuários**. CLIP embedding compara foto-vs-foto, então o cache hita independente do `produto_id` (que é por tenant). |
| **Tabela `modelos_3d_universais` separada da `modelos_3d_produto`** | `produtos.id` é por vendedor; o molde do frasco é universal. `modelos_3d_universais` guarda o cache global; `modelos_3d_produto` (que já existe) amarra produto comercial → molde via `modelo_universal_id`. Vários produtos de tenants diferentes podem apontar para o mesmo molde. |
| **Cosine + threshold em vez de pgvector/FAISS** | Até ~10k entradas a busca linear é trivial. Trocar mantendo a ABC `ModelCache` quando virar gargalo. |
| **`rembg` antes do Hunyuan** | Fotos com fundo não removido degradam significativamente o mesh gerado (modelo inclui partes do fundo como geometria). |
| **Shader de vidro PBR no Blender** | O Hunyuan pinta vidro como superfície opaca azulada; o refiner substitui o material por `Principled BSDF` com IOR 1.45, transmission 1.0, roughness 0.05. |
| **Label real extraída da foto** | O Hunyuan inventa texto/marca; perfumaria depende da legibilidade da label, então extraímos da foto via OpenCV (`HomographyLabelExtractor`) e projetamos como decal. |
| **Blender via subprocess + thread** | `bpy` é difícil de subir como lib em servidor; subprocess é o jeito padrão e isolado. `subprocess.run` em `asyncio.to_thread` evita `NotImplementedError` no Windows. |
| **Single async worker in-process** | Suficiente para 1 usuário fazendo 1 job por vez (cenário de demo de TCC). Trocar por Celery é local em 1 ponto. |
| **`request.base_url` para montar `modelUrl`** | Mesmo banco funciona em emulador (`10.0.2.2`) e device físico (IP da LAN) sem reconfig. |
| **Sem fallback de template** | Mascarar a falha do Hunyuan poluía a medição do pipeline de IA — um job entregue por template contava como sucesso. Falhar explicitamente preserva o sinal. |

## Próximas leituras

- Como rodar: [03 - Inicialização do projeto](03-inicializacao-do-projeto.md).
- Onde cada coisa mora: [04 - Estrutura de pastas](04-estrutura-de-pastas.md).
- Como o pipeline integrado funciona em detalhe: [09f - Pipeline integrado](09f-pipeline-integrado.md).
- Como o cache funciona: [09g - Cache de similaridade CLIP](09g-cache-similaridade-clip.md).
