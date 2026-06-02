# Docker

## Visao geral

O Docker do projeto cobre dois servicos em `docker-compose.yml`: `postgres` e `hunyuan`. O backend FastAPI e o frontend Flutter nao possuem servicos Compose no estado atual (fonte: `docker-compose.yml`).

`postgres` fornece o banco PostgreSQL 16 para o backend. `hunyuan` builda `docker/hunyuan/Dockerfile` e expoe um servidor FastAPI separado para geracao de GLB via Hunyuan3D-2mv (fontes: `docker-compose.yml`, `docker/hunyuan/Dockerfile`, `docker/hunyuan/server.py`).

## Por que existe

O Compose evita rodar manualmente o Postgres e encapsula o ambiente pesado do Hunyuan, que exige CUDA, PyTorch, dependencias nativas e cache de modelos (fontes: `docker-compose.yml`, `docker/hunyuan/Dockerfile`, `docker/hunyuan/README.md`).

## Stack/dependencias

| Servico | Imagem/build | Porta host | Volumes | Fontes |
|---|---|---:|---|---|
| `postgres` | `postgres:16` | `5433 -> 5432` | `postgres_data:/var/lib/postgresql/data` | `docker-compose.yml` |
| `hunyuan` | `build: ./docker/hunyuan` | `7860 -> 7860` | `hunyuan_cache:/app/hf_cache` | `docker-compose.yml` |

O Dockerfile do Hunyuan usa `pytorch/pytorch:2.7.0-cuda12.8-cudnn9-devel`, instala dependencias de sistema, clona `deepbeepmeep/Hunyuan3D-2GP`, instala dependencias Python, compila rasterizadores e expoe `7860` (fonte: `docker/hunyuan/Dockerfile`).

Variaveis do servico `hunyuan` no Compose:

| Variavel | Default no Compose | Fontes |
|---|---|---|
| `HUNYUAN_ENABLE_TEXTURE` | `1` | `docker-compose.yml`, `docker/hunyuan/server.py` |
| `HUNYUAN_TEXTURE_MULTI_VIEW` | `1` | `docker-compose.yml`, `docker/hunyuan/server.py` |
| `HUNYUAN_SHAPE_SUBFOLDER` | `hunyuan3d-dit-v2-mv` | `docker-compose.yml`, `docker/hunyuan/server.py` |
| `HUNYUAN_SHAPE_VARIANT` | `bf16` | `docker-compose.yml`, `docker/hunyuan/server.py` |
| `HUNYUAN_ALLOW_SINGLE_VIEW_FALLBACK` | `1` | `docker-compose.yml`, `docker/hunyuan/server.py` |
| `HUNYUAN_VRAM_BUDGET_MB` | `2200` | `docker-compose.yml`, `docker/hunyuan/server.py` |
| `MMGP_PROFILE` | `4` | `docker-compose.yml`, `docker/hunyuan/server.py` |

## Estrutura

```text
docker-compose.yml
docker/
  hunyuan/
    Dockerfile
    README.md
    entrypoint.sh
    server.py
```

`entrypoint.sh` define `HF_HOME`, `CUDA_VISIBLE_DEVICES`, adiciona `/app/hunyuan` ao `PYTHONPATH` e executa `uvicorn server:app --host 0.0.0.0 --port 7860` (fonte: `docker/hunyuan/entrypoint.sh`).

O servidor Hunyuan expoe:

| Metodo | Caminho | Funcao | Fonte |
|---|---|---|---|
| GET | `/health` | Retorna `loading`, `ready` ou `error` conforme carga dos modelos | `docker/hunyuan/server.py` |
| POST | `/generate` | Recebe 1 a 6 imagens e retorna GLB binario | `docker/hunyuan/server.py` |

## Como rodar/usar

Postgres:

```powershell
cd C:\TCC
docker compose up -d postgres
```

Hunyuan:

```powershell
cd C:\TCC
docker compose up hunyuan
```

Teste de saude do Hunyuan:

```powershell
Invoke-RestMethod http://localhost:7860/health
```

Teste de saude do Postgres depende de cliente local (`psql`) ou do backend apontando para `DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/tcc` (fontes: `docker-compose.yml`, `back/.env.example`).

## Pontos de atencao

- `hunyuan` reserva GPU NVIDIA no Compose; sem GPU/driver compatível, o servico tende a falhar ou nao ficar pronto (fonte: `docker-compose.yml`).
- O build do Hunyuan pode baixar pesos do Hugging Face durante o Docker build; o README do servico cita download grande e cache em volume (fontes: `docker/hunyuan/Dockerfile`, `docker/hunyuan/README.md`).
- `postgres` usa senha `postgres` e banco `tcc`, adequado para desenvolvimento local, nao para producao (fonte: `docker-compose.yml`).
- O Compose nao declara `backend`; subir `postgres` nao inicia Uvicorn automaticamente (fonte: `docker-compose.yml`).
- Com `PIPELINE_MODE=integrated` (default), o backend principal **chama** o container Hunyuan via HTTP durante o `POST /captures`; nos modos `fake`/`template` ele não toca o container (fontes: `back/app/main.py`, `back/app/modules/captures/pipeline.py`).

