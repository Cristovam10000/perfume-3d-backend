# Backend

## Visao geral

`perfume-3d-backend` e uma aplicacao FastAPI para captura e geracao de modelos 3D, armazenamento local dos artefatos e operacoes comerciais de clientes, produtos e vendas.

O fluxo principal usa `PIPELINE_MODE=integrated`: preprocessamento, remocao de fundo, cache por similaridade CLIP, Hunyuan3D em container separado e pos-processamento Blender. Os modos `fake` e `template` permitem desenvolvimento sem o servico de IA.

## Componentes

| Area | Local |
|---|---|
| Bootstrap, factories e lifespan | `app/main.py` |
| Configuracao | `app/config.py`, `.env.example` |
| Banco e sessoes async | `app/database.py` |
| Captura, fila e pipeline | `app/modules/captures/` |
| Clientes, produtos e vendas | `app/modules/sales/` |
| Armazenamento de uploads/GLBs | `app/storage/` e `storage/` em runtime |
| Hunyuan3D | `docker/hunyuan/` |
| Postgres + Hunyuan | `docker-compose.yml` |

## Endpoints principais

| Metodo | Endpoint | Funcao |
|---|---|---|
| `GET` | `/health` | Liveness da API. |
| `POST` | `/captures` | Recebe `images`, `views` opcionais e `productId`; cria um job. |
| `GET` | `/captures/{job_id}/status` | Retorna status, mensagem, erro e `modelUrl`. |
| `GET` | `/sales/snapshot` | Snapshot comercial completo. |
| `POST/PATCH` | `/sales/clients`, `/sales/clients/{id}` | Cria ou edita cliente. |
| `POST/PATCH` | `/sales/products`, `/sales/products/{id}` | Cria ou edita produto. |
| `PATCH` | `/sales/products/{product_id}/stock` | Ajusta estoque. |
| `POST` | `/sales/sales` | Cria venda e parcelas. |
| `POST` | `/sales/installments/{id}/payments` | Recebe valor total ou parcial. |
| `PATCH` | `/sales/installments/{id}/due-date` | Renegocia vencimento. |
| `PATCH` | `/sales/notifications/{id}/read` | Marca notificação como lida. |

O contrato detalhado esta em [13 - Endpoints HTTP](13-endpoints-http.md).

## Executar

```powershell
cd C:\TCC\perfume-3d-backend
Copy-Item .env.example .env
# Troque POSTGRES_PASSWORD e repita a senha na DATABASE_URL.
docker compose up -d postgres
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Para o pipeline integrado, suba tambem `docker compose up -d hunyuan` e configure Blender 5.1+ em `BLENDER_EXECUTABLE`. Para um start leve, use `PIPELINE_MODE=fake`.

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Estado verificado em 2026-07-23: 320 testes coletados, 319 aprovados e 1 integração real com Hunyuan pulada por exigir o contêiner ativo.

## Pontos de atencao

- O Compose nao sobe o processo FastAPI; Uvicorn roda separadamente.
- O `.env` real e ignorado pelo Git; somente `.env.example` deve ser publicado.
- O schema de `captures` usa SQLAlchemy. O modulo comercial usa SQL textual sobre as tabelas existentes e `ensure_sales_schema()` nao cria todo o schema do zero.
- O servico Hunyuan roda em processo/container proprio e e chamado por HTTP.
- Os documentos numerados [01 a 15](README.md) sao a referencia tecnica canônica.
