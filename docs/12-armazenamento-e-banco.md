# 12 — Armazenamento local e banco de dados

> **O que você vai aprender neste doc**
> - Onde os arquivos moram em disco (`uploads/`, `models/`, `cache/`) e o que é versionado.
> - O schema do Postgres: tabelas do `captures` (ORM) e do `sales` (SQL textual).
> - Por que dois estilos de acesso ao banco convivem (typed mappings vs. `text()`).
>
> **Pré-requisitos:** [07 - Camada core](07-camada-core.md). Código: [`app/storage/local_storage.py`](../app/storage/local_storage.py), [`app/modules/captures/models.py`](../app/modules/captures/models.py).

## Armazenamento em disco — `LocalStorage`

Raiz: `settings.storage_root` (default `./storage`), resolvida para caminho absoluto.

| Caminho | Conteúdo | Git |
|---------|----------|-----|
| `uploads/<job_id>/<filename>` | Fotos enviadas no `POST /captures` | ignorado (`.gitignore`) |
| `models/<job_id>.glb` | Modelo 3D entregue para o job (cópia do cache em hit, ou GLB recém-gerado em miss) | ignorado |
| `cache/<cache_id>.glb` | GLB cacheado, referenciado por `modelos_3d_universais.caminho_arquivo_modelo` no banco | ignorado |
| `model_viewer.html` (na raiz de `storage/`) | Viewer HTML de debug | versionado (exceção) |

- `model_public_path(job_id)` retorna a string `"/files/models/{job_id}.glb"`, usada no campo `model_path` persistido e depois exposta no status como URL absoluta.
- `cache_path(cache_id)` (novo helper) retorna `storage/cache/<cache_id>.glb` — usado pelo `ClipSimilarityCache.store` para gravar e pelo `ClipSimilarityCache.lookup` para localizar o GLB cacheado antes de copiá-lo para o `output_path` do job.

## Servir ficheiros — `StaticFiles`

- O mount `/files` aponta para a mesma raiz de `storage`. O cliente (Flutter) faz `GET` nessa URL; suporta cache e requisições em intervalo (range) conforme o Starlette.

## PostgreSQL e schema

### Schema do módulo `captures`

- Tabelas criadas com `Base.metadata.create_all` no startup (sem Alembic no MVP):
  - **`capture_jobs`**: `id` (PK string UUID), `status`, `message`, `model_path`, `error`, `product_id` (BigInteger, opcional/index — vínculo com produto comercial), `created_at`, `updated_at`
  - **`capture_images`**: `id`, `job_id` (FK com cascade), `filename`, `path`, `view` (varchar 16, opcional — rótulo de vista do app guiado; NULL dispara o `CLIPViewRouter`)
  - **`modelos_3d_universais`** (cache global cross-tenant do `IntegratedPipeline`): `id` (PK varchar 36 uuid), `caminho_arquivo_modelo` (text), `embedding` (bytea com 512 floats float32 ≈ 2KB), `embedding_dim` (int), `source_job_id` (varchar 36, index), `liquid_color`, `label_path`, `hit_count`, `ultimo_hit_em`, `criado_em`. **Sem FK direto para `produtos`** — o vínculo entre produto comercial e molde universal acontece em `modelos_3d_produto.modelo_universal_id`. Permite que vários produtos de tenants diferentes apontem para o mesmo molde. Ver [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md) §"DDL" para o SQL completo.
- O status é guardado como string, alinhado com o enum `CaptureStatus` no código.

### Schema do módulo `sales`

O módulo `sales/` usa um schema **pré-existente** (criado via `psql` manual ou script externo, não controlado pelo backend). O bootstrap do FastAPI chama [`ensure_sales_schema(engine)`](../app/modules/sales/repository.py) no startup, que aplica apenas `ALTER TABLE IF EXISTS … ADD COLUMN IF NOT EXISTS …` para garantir compatibilidade com instalações antigas — **não cria tabelas do zero**.

Tabelas referenciadas pelo `SalesRepository` (todas em snake_case e em português, refletindo o domínio comercial brasileiro):

| Tabela | Conteúdo |
|---|---|
| `clientes` | Clientes ativos do app comercial. |
| `produtos` | Catálogo de perfumes por tenant. Colunas garantidas pelo `ensure_sales_schema`: `custo numeric(10,2)`, `estoque_minimo integer`, `volume_ml integer`, `frasco_color_value bigint`. Possui flag `possui_modelo_3d boolean` para integração com captures. |
| `modelos_3d_produto` | **Tabela existente** que amarra produto comercial → GLB. `produto_id bigint UNIQUE NOT NULL` (FK para `produtos` ON DELETE CASCADE), `caminho_arquivo_modelo text`, `caminho_imagem_preview text`, `status varchar(50)`, `capture_job_id varchar(36)` (FK para `capture_jobs` ON DELETE SET NULL), `criado_em`, `atualizado_em`. Ganha a coluna **`modelo_universal_id varchar(36)` (FK para `modelos_3d_universais` ON DELETE SET NULL)**, adicionada no startup por `ensure_captures_schema` (idempotente). UNIQUE em `produto_id` preservada (1 modelo por produto do tenant). Ver [09g](09g-cache-similaridade-clip.md). |
| `vendas` | Cabeçalho da venda (cliente, data, total, parcelado). |
| `itens_venda` | Linhas de cada venda (produto, quantidade, preço unitário). |
| `parcelas` | Parcelas geradas para vendas a prazo. |
| `eventos_parcela` | Histórico de eventos por parcela (vencida, paga, renegociada). |
| `pagamentos` | Pagamentos recebidos. |
| `notificacoes` | Notificações comerciais (parcelas vencendo, etc). |
| `resumo_financeiro_cliente` | Tabela de resumo materializada por cliente. |

> **Decisão arquitetural:** o `SalesRepository` usa SQL textual (`sqlalchemy.text`) em vez de modelos ORM, deliberadamente — o schema comercial é grande, estável e mais legível em SQL puro do que em mappings declarativos. Captures usa SQLAlchemy 2.0 (typed mappings). Ambos compartilham a mesma `AsyncEngine`/`SessionFactory`.

### Driver assíncrono

- O driver assíncrono é `asyncpg` via URL `postgresql+asyncpg://...` em `Settings.database_url`.
- Captures e sales compartilham a mesma engine/session — modelo monolítico modular.

## Testes

- A suíte de testes do `captures` usa **SQLite** assíncrono (fixture em `conftest.py`), não requer Docker do Postgres.
- O `sales` ainda não tem cobertura de testes automatizada (apenas exercitado manualmente via app Flutter contra um Postgres real). Ver [14 — Testes](14-testes.md).

## Leituras relacionadas

- [07 — Camada `core`](07-camada-core.md) (config e URL da base)
- Código: [`app/storage/local_storage.py`](../app/storage/local_storage.py), [`app/modules/captures/models.py`](../app/modules/captures/models.py), [`app/modules/sales/repository.py`](../app/modules/sales/repository.py)
