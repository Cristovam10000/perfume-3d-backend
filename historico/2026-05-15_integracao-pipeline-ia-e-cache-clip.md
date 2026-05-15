# Sessão 2026-05-15 — Integração do pipeline IA ao `/captures` com cache CLIP cross-tenant

## 1. Metadados

- **Título:** Integração do pipeline IA (Hunyuan + pos-proc) no `/captures` com cache global por similaridade CLIP, desenhado para multi-tenant futuro.
- **Data:** 2026-05-15.
- **Fase do projeto:** transição entre Fases 1–5 (componentes standalone exercitados por smokes) e a **Fase 7** prevista nos históricos anteriores: composição efetiva do pipeline IA dentro do `CaptureService` + introdução do mecanismo de cache.
- **Escopo/objetivo principal:** sair do estado "Hunyuan e auxiliares só via `scripts/smoke_phase5.py`" para "Hunyuan é o caminho default do `/captures`, com cache cross-tenant que evita regerar o mesmo perfume quando outro usuário (futuro) fotografar o mesmo frasco".
- **Posicionamento cronológico inferido:** **sessão 8 documentada.** Vem depois da sessão 7 (`2026-05-09_validacao-smoke-hunyuan-e-documentacao-cronologica.md`). Esta sessão consolida a Fase 7 que aparecia como pendência recorrente desde o histórico de 2026-04-28.
- **Commits Git associados (back):**
  - `a2170b0` — 2026-05-15 — `docs: update documentation for integrated pipeline and cache system`. Reescrita extensiva dos 22 arquivos de `docs/` + `.env.example`, descrevendo o pipeline integrado e o cache CLIP **antes** do código (sessão de docs precedente ao código, por preferência do usuário).
  - `<hash-fase-1>` — Fase 1: fundações (config, storage, embedder, modelo SQLAlchemy, ModelCache).
  - `<hash-fase-2>` — Fase 2: IntegratedPipeline, factories, service delegando ao pipeline.
  - `<hash-fase-3>` — Fase 3: router com `productId` opcional, testes ajustados, histórico.
- **Trabalho sem âncora Git nesta sessão:**
  - `C:\TCC\back\.env` foi corrigido (`PROCESSOR_TYPE=template_fitting` → `PIPELINE_MODE=integrated` + blocos novos). `.env` está no `.gitignore`, então a mudança fica como evidência de working tree.
- **Sessões anteriores referenciadas:**
  - `historico/2026-04-28_fase4-fase5-preprocessamento-cleanup-label.md` (Fases 4–5).
  - `historico/2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` (Fases 1–3).
  - `historico/2026-05-09_integracao-sales-e-melhorias-hunyuan.md` (sales + parâmetros Hunyuan).
  - `historico/2026-05-09_validacao-smoke-hunyuan-e-documentacao-cronologica.md` (validação smoke).

## 2. Contexto inicial

Antes desta sessão, o backend tinha:

- **Pipeline 3D em duas vias**, sem integração:
  1. `TemplateProcessor` (Blender + GLB pré-existente) — o que rodava em produção via `/captures`.
  2. Hunyuan3D + rembg + mesh refiner + label extractor/upscaler/projector — todos como **componentes standalone**, exercitados apenas pelos `scripts/smoke_phase{3,4,5}.py`.
- **Sistema comercial** (`/sales/*`) ativo, com tabela `modelos_3d_produto` já existente no banco amarrando `produto_id UNIQUE → caminho_arquivo_modelo`. Detectada na sessão.
- **`.env` corrompido**: `PROCESSOR_TYPE=template_fitting` não é um valor aceito pelo `Literal["fake","template"]` do `Settings`; o backend caía no startup com erro de Pydantic. O usuário tinha esse problema sem se dar conta.
- **Front Flutter** com um único fluxo prático de captura (`/capture/intro → /capture/camera → /capture/review → /processing → /viewer`) e uma rota fantasma `/captura/:produtoId` declarada mas sem widget que leia o `produtoId`.

O problema que motivou a sessão foi triplo:

- Validar Hunyuan como modelo de produção exigia integrá-lo ao `/captures` (não mais smoke isolado).
- O custo do Hunyuan (3–8 min de GPU por job) inviabiliza regerar quando outro usuário fotografar o mesmo perfume. Sem cache, o produto não escala.
- A intenção declarada do usuário é **disponibilizar o app para múltiplos vendedores no futuro**. Isso impõe que o cache seja **global cross-tenant**, não amarrado ao `produto_id` (que é por vendedor).

## 3. Decisões arquiteturais e de design

### 3.1 Cache global em tabela separada da `modelos_3d_produto`

Opções consideradas explicitamente com o usuário:

| Opção | Decisão | Justificativa |
|---|---|---|
| Estender `modelos_3d_produto` com embedding | Descartada | `produto_id UNIQUE` torna a tabela inadequada para multi-tenant: produto A da Ana e produto A do João são linhas diferentes; o cache precisa servir os dois. |
| Tabela auxiliar 1:1 com `modelos_3d_produto` | Descartada | Acopla cache à tabela por-tenant; mesma limitação. |
| **Nova `modelos_3d_universais` global + `modelo_universal_id` em `modelos_3d_produto`** | **Escolhida** | Cache é por molde de frasco (universal); amarração comercial fica em `modelos_3d_produto` (por tenant). Vários produtos de vendedores diferentes podem apontar para o mesmo molde. |

O usuário ratificou: "Sim, já separa as duas tabelas (recomendado)" + "[POST /captures] aceita `productId` opcional".

### 3.2 CLIP zero-shot como chave do cache

Comparado com:

- **`product_id` direto** — não funciona cross-tenant (cada vendedor tem `produto_id` próprio).
- **Hash perceptual (pHash, dHash)** — frágil a iluminação/ângulo; dois usuários fotografando o mesmo perfume em locais diferentes virariam cache miss.
- **CLIP embedding + cosine** — robusto, e o backend já tem CLIP (era usado pelo `CLIPClassifier` legado). **Decisão final.**

CLIP é repurposado: deixa de classificar entre 6 templates (uso antigo) e vira `ImageEmbedder` que produz embedding 512-d para o `ModelCache` comparar com a tabela.

### 3.3 `productId` opcional, não obrigatório

Capturas podem vir:

- Com `productId` (quando o front amarra a um produto comercial) → backend faz UPSERT em `modelos_3d_produto`.
- Sem `productId` (captura "solta" ou estado intermediário) → backend popula só `modelos_3d_universais`; o cache global ainda funciona, só sem vínculo comercial.

O contrato HTTP existente (`POST /captures` aceita `images` como multipart) ficou preservado; `productId` é um campo `Form` adicional.

### 3.4 Service magro, pipeline gordo

Mudança estrutural: `CaptureService` deixou de orquestrar `classifier + color_detector + processor` diretamente. Agora ele:

1. Persiste o job + imagens + `product_id` opcional.
2. Enfileira o `job_id`.
3. No worker, lê o job do banco e delega tudo ao `Processor` injetado (`IntegratedPipeline` em produção).

Toda a coreografia (preprocess → rembg → cache lookup → Hunyuan → cleaner → refiner → label → cache store) vive dentro do `IntegratedPipeline`. Isso permite testar o pipeline isoladamente com stubs e mantém o service como camada fina de persistência + filas.

### 3.5 `PROCESSOR_TYPE` → `PIPELINE_MODE` com alias legacy

Renomeação semântica: o conceito antigo "processor" cobria só `fake|template`; agora `pipeline_mode` cobre `fake|template|integrated`. Alias mapeia `PROCESSOR_TYPE` antigo para o nome novo no startup, com `WARNING` no log. Valores inválidos (como `template_fitting` que apareceu no `.env` do usuário) caem para o default `integrated` com log explicativo.

### 3.6 Cache desligável e bypasses por stage

Cada componente do pipeline tem ABC + `Disabled*` + impl real:

- `CACHE_ENABLED=false` → `DisabledEmbedder` + `DisabledModelCache` (cache passa a ser sempre miss; pipeline gera tudo).
- `BACKGROUND_REMOVER_TYPE=disabled` → cópia byte-a-byte (perde qualidade Hunyuan mas roda).
- Idem para `MESH_REFINER_TYPE`, `LABEL_*_TYPE`.

Permite degrade local e teste sem deps pesadas.

### 3.7 `ensure_captures_schema` para `modelos_3d_produto`

A tabela `modelos_3d_produto` **já existe** no banco e não é gerenciada pelo SQLAlchemy do backend captures (foi criada fora). Para adicionar a coluna `modelo_universal_id` (FK opcional para `modelos_3d_universais`) sem migrations formais, usa-se o mesmo padrão do `ensure_sales_schema`: `ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT EXISTS ...` + CREATE INDEX + bloco `do $$` para a constraint FK que o Postgres não tem `IF NOT EXISTS`. Idempotente.

A `modelos_3d_universais` em si é criada pelo `Base.metadata.create_all()` via importação do novo modelo `cached_models.py`. Coluna `product_id` em `capture_jobs` também ganha um `ALTER` para compatibilidade com ambientes antigos.

## 4. Implementação realizada

### 4.1 Documentação (`a2170b0`)

Antes do código, foi feita uma sessão extensiva de docs (preferência do usuário: "Plano detalhado + atualizar docs primeiro, código depois"):

- 22 docs reescritos em `docs/`.
- Dois novos: `09f-pipeline-integrado.md` (composição do pipeline) e `09g-cache-similaridade-clip.md` (cache CLIP).
- `.env.example` reformulado.
- `01-visao-geral.md` mostra Hunyuan como caminho default; `09-pipeline-3d.md` rebate TemplateProcessor como fallback.

### 4.2 Fundações (Fase 1)

Arquivos criados:

- `app/modules/captures/embeddings.py` — `ImageEmbedder` ABC + `DisabledEmbedder` (vetor zero) + `ClipImageEmbedder` (mean-pool + L2-norm via CLIP HuggingFace).
- `app/modules/captures/modelos_universais.py` — modelo SQLAlchemy `ModeloUniversal` (tabela `modelos_3d_universais`) + `ensure_captures_schema(engine)` para o ALTER em `modelos_3d_produto` e `capture_jobs`.
- `app/modules/captures/cache.py` — `ModelCache` ABC + `DisabledModelCache` + `ClipSimilarityCache` com `lookup`/`store`/`bind_product`. Cosine linear sobre embeddings; UPSERT em `modelos_3d_produto` quando `product_id` está presente.
- Testes: `tests/modules/captures/test_embeddings.py` (5 testes), `tests/modules/captures/test_cache.py` (8 testes).

Arquivos alterados:

- `app/config.py` — `Settings` reescrito com `PIPELINE_MODE`, blocos Hunyuan/Cache/Stages, alias `_apply_legacy_aliases` para `PROCESSOR_TYPE` antigo.
- `app/storage/local_storage.py` — `cache_dir` + `cache_path(universal_id)`; `ensure_dirs` cria `storage/cache/`.
- `app/database.py` — `create_all` importa `modelos_universais` para registrar a tabela.
- `tests/conftest.py` — fixture `session_factory` registra `modelos_universais` no SQLite de teste.

### 4.3 Pipeline integrado (Fase 2)

Arquivos criados:

- `app/modules/captures/pipeline.py` — `IntegratedPipeline(Processor)` orquestrando 8 stages com falhas degradadas: preprocess → rembg → embed → cache.lookup → hunyuan → cleaner → refiner → label → cache.store. Cache hit pula direto para a cópia do GLB cacheado. Fallback opcional para `TemplateProcessor` quando o Hunyuan falha e `PIPELINE_FALLBACK_TO_TEMPLATE=true`.
- Testes: `tests/modules/captures/test_pipeline.py` (6 testes com stubs in-process).

Arquivos alterados:

- `app/modules/captures/processor.py` — `ProcessingInput.product_id`, `ProcessingResult.origem`/`similarity`.
- `app/modules/captures/models.py` — `CaptureJob.product_id: BigInteger | None` com index.
- `app/modules/captures/repository.py` — `create_job(product_id=...)`.
- `app/modules/captures/service.py` — Reescrito magro: deixou de injetar `classifier`/`color_detector`; agora `process_job` apenas lê do banco e delega ao `Processor`.
- `app/main.py` — Reescrito com `build_pipeline()` + factories por stage (`build_image_preprocessor`, `build_background_remover`, `build_embedder`, `build_model_cache`, `build_hunyuan`, `build_mesh_cleaner`, `build_mesh_refiner`, `build_label_extractor`, `build_label_upscaler`, `build_label_projector`, `build_template_processor`). Lifespan chama `ensure_captures_schema(engine)` depois de `create_all`.

### 4.4 Router + testes (Fase 3)

Arquivos alterados:

- `app/modules/captures/router.py` — `POST /captures` aceita `productId` opcional via `Form(alias="productId")`. Repassa ao `service.create_job(images, product_id=...)`.
- `tests/test_main.py` — Reescrito: removidos `TestBuildProcessorFactory`/`TestBuildClassifierFactory`/`TestBuildColorDetectorFactory`. Substituídos por `TestBuildPipelineFactory` testando `fake|template|integrated`, alias legacy (`PROCESSOR_TYPE=template_fitting`), e fluxo E2E com `productId`.
- `tests/modules/captures/test_service.py` — Removidos `TestClassifierIntegration`/`TestColorDetectorIntegration` (orquestração que não existe mais). Adicionados testes para persistência e propagação de `product_id`.

### 4.5 Decisão: `.env` corrigido fora de commit

O `.env` ativo do usuário tinha `PROCESSOR_TYPE=template_fitting`. Foi reescrito para o novo layout (`PIPELINE_MODE=integrated`, blocos Hunyuan/Cache/Stages, `PIPELINE_FALLBACK_TO_TEMPLATE=true` para que demos sem container ainda funcionem). Como `.env` está no `.gitignore`, a mudança não vai em commit; ficou registrada aqui como evidência.

## 5. Problemas encontrados e soluções

### 5.1 `PROCESSOR_TYPE=template_fitting` no `.env` ativo

Diagnóstico durante a sessão: o usuário não havia notado, mas o `.env` tinha esse valor inválido. A `Settings` aceitava `Literal["fake","template"]` então o Pydantic falhava no startup.

Solução: `_apply_legacy_aliases(Settings())` lê `processor_type` como string opcional, mapeia `fake`/`template`/`integrated` para `pipeline_mode` com log de deprecation, e valores desconhecidos viram fallback para `integrated` com WARNING explicativo. `.env` foi corrigido em paralelo.

### 5.2 `modelos_3d_produto` existente complicou a tabela do cache

Diagnóstico: quando propus a tabela `cached_models`, o usuário perguntou "por que criar uma nova tabela?". A inspeção via `docker exec tcc-postgres psql -U postgres -d tcc -c '\d modelos_3d_produto'` mostrou que a tabela já existia com `produto_id UNIQUE`, `caminho_arquivo_modelo`, `capture_job_id`.

Solução: separar conceitos. `modelos_3d_universais` é o cache global (sem FK para produtos). `modelos_3d_produto` ganha apenas `modelo_universal_id` (FK opcional). Diferenciação importante para multi-tenant futuro.

### 5.3 `_serve_cache_hit` chamava `store` em vez de fazer UPSERT direto

Bug detectado durante a implementação do pipeline: em cache hit com `product_id`, a primeira versão chamava `cache.store(...)` para amarrar produto, mas isso geraria um id NOVO em `modelos_3d_universais` (cache duplicado).

Solução: adicionado método `ModelCache.bind_product(universal_id, product_id, capture_job_id)` que apenas faz UPSERT em `modelos_3d_produto`, sem criar entrada nova no cache. Hit fica idempotente.

### 5.4 Testes legados quebraram com a refatoração do service

Diagnóstico: `tests/modules/captures/test_service.py::TestClassifierIntegration/TestColorDetectorIntegration` testavam injeção de `classifier`/`color_detector` no `CaptureService` — esses parâmetros foram removidos. `tests/test_main.py` testava `build_classifier`/`build_color_detector` que viraram factories internas do pipeline.

Solução: reescrita dos testes. As classes de integração de classifier/color detector foram removidas (o equivalente vive em `test_pipeline.py`, validando a sequência completa com stubs). `TestBuildPipelineFactory` cobre o novo desenho. Testes do alias legacy também adicionados.

### 5.5 Front com rota fantasma `/captura/:produtoId`

Diagnóstico: ao planejar o ajuste do front para enviar `productId`, descobri que `app_router.dart:75-78` declara `/captura/:produtoId` mas `CaptureCameraPage` **não lê** `state.pathParameters['produtoId']`. O único caller (HomeDashboardPage `_QuickAction "Capturar"`) passa `data.produtos.first.id` arbitrário — sempre o primeiro produto.

Decisão: deixar o front sem mudança nesta sessão. O backend já aceita `productId` opcional via Form; quando o front decidir como ligar captura a produto real, basta um ajuste mínimo no `CaptureRepository`. Este histórico documenta a divergência para futura sessão.

## 6. Conceitos teóricos envolvidos

- **Multi-tenant arquitetura híbrida.** `produtos` é por-tenant (cada vendedor tem o próprio catálogo); `modelos_3d_universais` é cross-tenant (compartilhado). Separação evita que o cache fique acoplado à granularidade comercial.
- **Embedding visual via CLIP.** Mean-pool de N vetores → 1 vetor; L2-normalização converte cosine em produto interno trivial. Suficiente para perfumes parecidos visualmente, fraco para distinguir labels diferentes em frascos idênticos (calibração de threshold pendente).
- **Strategy + Factory.** Cada stage tem ABC, bypass `Disabled*` para teste/degrade, e factory parametrizada em `main.py`. Composição feita pelo `IntegratedPipeline`; testes podem injetar qualquer combinação.
- **Cosine similarity em vetores L2-normalizados.** Métrica de proximidade no intervalo [-1, 1]; insensível a magnitude (robusto a fotos de iluminações diferentes que possam normalizar a tons distintos).
- **Linear search vs index.** Até ~10k entradas, busca cosine linear é trivial (<5ms). Acima disso troca por pgvector/FAISS mantendo a ABC `ModelCache`.
- **Idempotência de schema migration ad-hoc.** `ALTER TABLE IF EXISTS ... ADD COLUMN IF NOT EXISTS ...` permite rodar `ensure_captures_schema` em todo startup sem efeito colateral. Substituto pragmático de Alembic enquanto o projeto não migra para migrations versionadas.
- **Falha degradada em pipeline.** Cada stage opcional tem cópia byte-a-byte como fallback; o GLB final sempre existe exceto se Hunyuan falhar sem `fallback_processor` configurado.

## 7. Pendências e próximos passos

### 7.1 Pendências anteriores cobertas

| Pendência anterior | Origem | Estado |
|---|---|---|
| Compor pipeline IA dentro do `CaptureService` | `2026-05-09_integracao-sales-e-melhorias-hunyuan.md` §7.1, e várias anteriores | ✅ **Cumprida.** `IntegratedPipeline` orquestra preprocess → rembg → cache → Hunyuan → cleaner → refiner → label → store dentro do worker. |
| Roteamento entre processors | `2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` §7 | ✅ **Cumprida via PIPELINE_MODE.** `fake|template|integrated` em `.env`, mais `pipeline_fallback_to_template=true` para usar `TemplateProcessor` quando o Hunyuan falha. |
| Cache de modelos | (intenção declarada pelo usuário) | ✅ **Cumprida.** `ClipSimilarityCache` com `modelos_3d_universais`. Cross-tenant por construção. |
| Persistir metadados de processamento | `2026-04-26_validacao-e2e-mobile-viewer-local.md` §7.2.3 | 🔄 **Parcial.** Embedding + label_path + liquid_color persistidos em `modelos_3d_universais`. Metadados completos do pipeline (tempo por stage, parâmetros Hunyuan usados) ainda não.|

### 7.2 Pendências anteriores não cobertas

| Pendência | Origem | Estado |
|---|---|---|
| Calibração CLIP em casos reais | `2026-04-26_fase2-templates-clip-cor.md` §7.2.1 | ⏳ **Ganhou nova dimensão.** Agora vira "calibrar `CACHE_SIMILARITY_THRESHOLD` com dataset real de perfumes". Plano em `docs/09g-cache-similaridade-clip.md`. |
| Limitações Hunyuan (vidro/tampa/fundo) | `2026-05-09_*` | 🔄 **Mitigadas no pipeline.** Refiner cobre vidro; cleaner pode cobrir tampa; rembg cobre fundo. Validação visual com dataset real continua pendente. |
| Validação visual do refiner | `2026-05-09_pipeline-ia-segmentacao-e-refinamento.md` §7.2.2 | ⏳ Pendente. Smoke da Fase 5 ainda é o único validador; falta relatório comparativo. |
| Suite de testes lentos em CI separado | mesmo | ⏳ Pendente. Os smokes manuais e `tests/integration/test_hunyuan_real.py` continuam opt-in. |
| Migration formal (Alembic) | `2026-05-09_integracao-sales-e-melhorias-hunyuan.md` §3.5 | ⏳ Adiada. `ensure_captures_schema` resolve no curto prazo. |

### 7.3 Novas pendências geradas

1. **Front sem `productId`.** A rota `/captura/:produtoId` é esqueleto; nenhuma página real chama com produto válido. Decidir: (a) deixar como está (cache funciona sem amarração) ou (b) adicionar botão "Atualizar 3D" no `Product3DPage` que navega `/captura/<id-real>` e o `CaptureCameraPage` lê `produtoId`.
2. **Calibração `CACHE_SIMILARITY_THRESHOLD=0.92`.** Chute pedagógico; precisa de calibração com fotos reais antes da defesa do TCC.
3. **Endpoint admin do cache.** `GET /captures/cache`, `DELETE /captures/cache/{id}` previstos em docs/09g; ainda não implementados.
4. **Validação E2E real.** Pipeline montado, mas faltou rodar `POST /captures` real com fotos e container Hunyuan ativo nesta sessão. Próxima sessão: smoke completo do `POST /captures` -> Hunyuan -> cache populado.
5. **`/sales` ainda usa `caminho_arquivo_modelo` direto.** O `SalesRepository` lê `modelos_3d_produto.caminho_arquivo_modelo` para preencher `modelo3DPath`; quando o cache popular essa coluna via UPSERT, o link já funciona. Mas o `produto.tem3D` ainda depende da flag `possui_modelo_3d` em `produtos`, que **não é atualizada automaticamente**. Decidir se atualizar essa flag faz parte do UPSERT futuro.
6. **Limpeza de pesos em ambientes sem GPU.** Primeira execução baixa ~2GB de CLIP + ~200MB rembg. Não é problema, mas merece doc no `03-inicializacao` (já está).

## 8. Reflexão para o TCC

Esta sessão consolida a inversão de paradigma do projeto:

1. **De pipeline determinístico a pipeline probabilístico.** O MVP original usava CLIP zero-shot só para escolher entre 6 templates pré-feitos — uma classificação de baixa entropia. O pipeline integrado coloca uma IA generativa (Hunyuan) no caminho crítico; a saída não é mais determinística, depende de seeds, hardware e calibração.
2. **De cache implícito (template reusado por descrição) a cache explícito (embedding visual).** A versão anterior usava `template_id` como chave implícita: "perfumes que pareciam rectangulares pegavam o GLB rectangular". O cache CLIP torna isso explícito: cada molde tem um vetor que representa a aparência visual específica do frasco; reuso acontece quando duas fotos descrevem a mesma aparência.
3. **De arquitetura single-tenant a esquema preparado para multi-tenant.** Apesar de o app ainda não ter autenticação, a separação `modelos_3d_universais` (global) vs `modelos_3d_produto` (por-tenant) antecipa a evolução. Quando `produtos` ganhar `usuario_id`, o cache continua funcionando sem refator.

Para o TCC, isso significa três contribuições argumentáveis:

- **Cache cross-tenant baseado em embedding visual** como solução para o custo de IA generativa em produtos de uso repetido.
- **Composição modular de pipeline IA** (cada stage substituível) como padrão para projetos onde diferentes etapas têm diferentes maturidades — preprocess clássico (estável) coexiste com Hunyuan (experimental) coexiste com Blender (determinístico).
- **Esquema multi-tenant antecipado** sem custo de autenticação no MVP: as decisões de tabela são tomadas como se o produto já fosse multi-tenant, mesmo que a autenticação fique para depois.

Também fica registrado que o front-end **ainda não reflete essa evolução**. A rota `/captura/:produtoId` foi declarada num momento anterior do projeto (presumivelmente quando o usuário pensou em ligar captura a produto), mas nunca foi implementada de verdade. O backend agora aceita `productId` opcional; o front continua mandando sem. A defasagem é metodologicamente honesta: design > docs > código de backend > código de front, com pausas explícitas de validação entre cada etapa.

---

*Documento gerado em 2026-05-15 a partir da sessão de design + implementação + testes. Reflete o estado do código após os três commits da Fase 1/2/3 + o commit anterior `a2170b0` de docs. Quando houver divergência entre conteúdo e Git, o Git é a fonte canônica.*
