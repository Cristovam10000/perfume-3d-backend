# 03 — Inicialização do projeto

> **O que você vai aprender neste doc**
> - Sair de um clone novo até o `/health` respondendo `200`, passo a passo.
> - Qual modo de pipeline escolher conforme sua máquina (`fake`/`template`/`integrated`).
> - O que o backend faz no *startup* (a sequência do `production_lifespan`).
> - Como diagnosticar os erros mais comuns (venv errado, Postgres parado, Hunyuan lento).
>
> **Pré-requisitos:** [02 - Stack tecnológico](02-stack-tecnologico.md) (o que instalar).

Como sair de um clone novo até o servidor respondendo `200` no `/health`. Comandos em **PowerShell**; em bash/zsh ajuste só os ativadores de venv e os paths.

## Pré-requisitos

- **Python 3.12+** (recomendado 3.14, mas 3.12 e 3.13 funcionam)
- **Docker Desktop** (necessário para Postgres e — no `PIPELINE_MODE=integrated` — para o serviço Hunyuan3D)
- **NVIDIA Container Toolkit** (somente para `PIPELINE_MODE=integrated`: o Hunyuan exige GPU NVIDIA, ~6-8GB VRAM com `mmgp` profile 4)
- **Git**
- **Blender 5.1+** — necessário em `PIPELINE_MODE=integrated` (refiner, cleaner, label projector) ou `template` (TemplateProcessor). Para o `FakeProcessor` (cubo sintético) não precisa.

## 1. Postgres + Hunyuan via docker-compose

A raiz do repositório backend (`C:\TCC\perfume-3d-backend`) tem um `docker-compose.yml` que sobe `postgres` (DB do backend) e `hunyuan` (serviço de geração 3D). Em uma instalação fresca:

```powershell
cd C:\TCC\perfume-3d-backend
docker compose up -d postgres   # rápido (~10s)
docker compose up -d hunyuan    # primeira vez: build de 20-40min + download de ~5GB de pesos
```

Verificar:

```powershell
docker compose ps
# postgres deve ficar healthy; hunyuan fica starting até os modelos estarem prontos.
Invoke-RestMethod http://localhost:7860/health
# sucesso completo: status=ready, shape_mode=multi-view, fallback=False
```

Para desenvolvimento sem GPU, é possível subir só o postgres e usar `PIPELINE_MODE=fake` ou `PIPELINE_MODE=template` no backend.

> **Por que porta 5433** no Postgres e não a default 5432? Para não conflitar com instalações nativas de Postgres. Se já roda outro Postgres na 5432, o backend assume 5433 por convenção. O Hunyuan fica na porta 7860 (default do gradio_app upstream, mantido).

## 2. Ambiente Python

```powershell
cd C:\TCC\perfume-3d-backend

py -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements-dev.txt
```

`requirements-dev.txt` herda `requirements.txt`, então uma instalação só puxa runtime + ferramentas de teste.

### Embedder CLIP (cache do pipeline integrado)

Necessário se `CACHE_EMBEDDER_TYPE=clip` (default em `PIPELINE_MODE=integrated`) ou se for usar `COLOR_DETECTOR_TYPE=average`:

```powershell
pip install -r requirements-classifier.txt
```

Custo: ~2GB de download (`torch` + pesos do CLIP). Para CPU-only, funciona; com RTX 5050+ é ~10x mais rápido. O CLIP é usado pelo `ClipImageEmbedder` para gerar embeddings das fotos durante o cache lookup.

### Visão computacional (rembg, OpenCV)

Necessário em `PIPELINE_MODE=integrated`:

```powershell
pip install -r requirements-vision.txt
```

Custo: ~200MB de pesos ONNX do `rembg` na primeira execução (cacheado em `~/.u2net/`). O backend importa `rembg`, `opencv-python` e `numpy` apenas quando os stages reais estão ativos — os bypasses `Disabled*` funcionam sem essas libs.

## 3. Variáveis de ambiente

```powershell
Copy-Item .env.example .env
# Troque POSTGRES_PASSWORD e repita a senha na DATABASE_URL.
```

O `.env.example` já vem com valores de desenvolvimento. Pontos que talvez você queira ajustar:

| Variável | Default | Quando mudar |
|---|---|---|
| `PIPELINE_MODE` | `integrated` | Use `fake` para dev sem Blender/GPU; `template` para demo offline com templates pré-existentes. |
| `HUNYUAN_URL` | `http://localhost:7860` | Mude se o container estiver em outra máquina ou porta. |
| `BLENDER_EXECUTABLE` | path Windows | Ajuste se Blender estiver em outro path ou outro SO. |
| `CACHE_ENABLED` | `true` | Desligue (`false`) para forçar todos os jobs a passarem pelo Hunyuan; útil para coletar embeddings de calibração. |
| `CACHE_SIMILARITY_THRESHOLD` | `0.92` | Calibre com dataset real — mais alto = mais cache miss (conservador); mais baixo = mais hits mas risco de falso positivo. |
| `CACHE_EMBEDDER_TYPE` | `clip` | Mude para `disabled` em ambientes sem `torch`/transformers; o cache opera apenas com cold-store. |
| `COLOR_DETECTOR_TYPE` | `disabled` | Mude para `average` se quer persistir cor do líquido como metadado (Hunyuan já infere; opcional). |
| `PIPELINE_FALLBACK_TO_TEMPLATE` | `false` | Ative se quer que o backend gere via `TemplateProcessor` quando o Hunyuan estiver offline. |
| `POSTGRES_PASSWORD` | placeholder local | Troque e mantenha a mesma senha dentro de `DATABASE_URL`. |
| `DATABASE_URL` | aponta para o Postgres local na 5433 | Mude se seu Postgres está em outro host/porta. |

Detalhes de cada chave em [07 — Camada `core` → secção *Settings*](07-camada-core.md#settings) e [09f](09f-pipeline-integrado.md) §"Configuração".

> **Compat:** se o seu `.env` ainda usar `PROCESSOR_TYPE`, o backend lê como `PIPELINE_MODE` com aviso de deprecation. Valores aceitos: `fake`, `template`, `integrated`. Qualquer outra coisa (ex.: `template_fitting`, que apareceu por engano em ambientes antigos) faz o Pydantic falhar no startup.

## 4. Subir o servidor

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

O `--reload` reinicia automaticamente quando você edita `.py`. Com `--host 0.0.0.0`, o servidor responde em todas as interfaces — necessário para o app Flutter em device físico alcançar via Wi-Fi.

### O que acontece no startup

O `production_lifespan` em [`app/main.py`](../app/main.py) executa, em ordem:

1. `configure_logging()` — handler em stdout com timestamp.
2. `create_all()` — cria as tabelas (`capture_jobs`, `capture_images`, `modelos_3d_universais`) se faltarem.
3. `ensure_sales_schema(engine)` — `ALTER TABLE IF EXISTS` no schema do módulo `sales`.
4. `ensure_captures_schema(engine)` — migração incremental do captures: adiciona `modelo_universal_id` (+FK) em `modelos_3d_produto`, `product_id` em `capture_jobs` e `view` em `capture_images`. Idempotente (não faz nada se as colunas já existem).
5. `LocalStorage().ensure_dirs()` — garante `storage/uploads/`, `storage/models/` e `storage/cache/`.
6. `build_pipeline()` — instancia `FakeProcessor`, `TemplateProcessor` ou `IntegratedPipeline` (com cada stage configurado via factories internas), conforme `PIPELINE_MODE`.
7. `ProcessingQueue().start(handler=service.process_job)` — sobe o worker async.
8. Loga `Backend pronto em 0.0.0.0:8000 (pipeline=<mode>, cache_enabled=<bool>, hunyuan_url=<url>)`.

## 5. Sanity check

Em outro terminal:

```powershell
curl.exe http://localhost:8000/health
# → {"status":"ok"}
```

| URL | Para quê |
|---|---|
| http://localhost:8000/health | Liveness check |
| http://localhost:8000/docs | Swagger UI (requests interativas) |
| http://localhost:8000/redoc | ReDoc |
| http://localhost:8000/files/model_viewer.html | Viewer local de GLBs (debug) |
| http://10.0.2.2:8000 | Base URL para o app Flutter no **emulador Android** |
| http://&lt;IP-da-LAN&gt;:8000 | Base URL para device físico na mesma Wi-Fi |

Para device físico, passe `--dart-define=BACKEND_BASE_URL=http://IP_DA_MAQUINA:8000` ao executar o Flutter; a configuração está em [`AppConstants`](../../perfume-3d-frontend/lib/core/constants/app_constants.dart). Se necessário, libere a porta 8000 no firewall do Windows (`New-NetFirewallRule -DisplayName "Perfume 3D backend 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`).

## 6. Smoke test do fluxo completo

Com o backend no ar:

```powershell
.\scripts\smoke.ps1
```

Esse script ([`scripts/smoke.ps1`](../scripts/smoke.ps1)):

1. `GET /health`.
2. `POST /captures` com 2 imagens sintéticas (bytes random — o backend não valida conteúdo).
3. Polling em `GET /captures/<id>/status` até `completed` ou timeout (default 30s).
4. Baixa o `.glb` em `modelUrl` e valida o magic header `glTF`.

Se passar, todas as camadas estão saudáveis: HTTP, DB, fila, processor, storage, static files.

### Equivalente em curl

```bash
# 1) upload
curl -F "images=@foto1.jpg" -F "images=@foto2.jpg" http://localhost:8000/captures
# → {"jobId":"<uuid>"}

# 2) status (repetir até status=completed)
curl http://localhost:8000/captures/<uuid>/status

# 3) baixar o modelo
curl -o cubo.glb http://localhost:8000/files/models/<uuid>.glb
```

## 7. Rodar a suíte de testes

```powershell
.\.venv\Scripts\python.exe -m pytest
```

A suíte completa tem **319 testes em 29 arquivos** (`pytest`, 2026-07-23). Os testes **não precisam** de Postgres rodando — usam SQLite ou sessões falsas isoladas. Componentes que dependem de Blender/rembg/CLIP/Hunyuan são pulados quando essas dependências faltam. Na execução local de referência, 318 testes passaram e apenas a integração real com o Hunyuan foi pulada porque exige o contêiner ativo.

Detalhes em [14 - Testes](14-testes.md).

## 8. (Opcional) Regenerar o template procedural Feelin' Flame

```powershell
# 1. PNG da label dourada (Brush Script + emblema HINODE)
.\.venv\Scripts\python.exe scripts\build_feeling_label.py

# 2. GLB procedural (geometria com bevels + label texturizada)
& "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" `
    --background --python scripts\blender\generate_feeling_template.py

# 3. Render preview Cycles (frontal)
& "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe" `
    --background --python scripts\blender\preview_feeling_template.py
```

Mais sobre os templates em [11 - Templates 3D](11-templates-3d.md).

## Problemas comuns

### `cannot import name '...'` no startup

Provavelmente você ativou o venv errado. Confirme com:

```powershell
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"
```

O caminho deve apontar para `.venv\Scripts\python.exe` dentro de `perfume-3d-backend/`.

### `connection refused` no Postgres

Container parado:

```powershell
docker ps -a | Select-String tcc-postgres
docker start tcc-postgres
```

### `BLENDER_EXECUTABLE` não existe

Em `.env`, ajuste o path. Em Linux geralmente é `/usr/bin/blender`; no macOS, `/Applications/Blender.app/Contents/MacOS/Blender`. Sem Blender, troque para `PIPELINE_MODE=fake`.

### CLIP travando ou OOM

Em CPU, a primeira inferência leva ~5-10s (carrega pesos). Se travar, é provavelmente download de pesos do HuggingFace — confira a rede. Para offline, defina `HF_HUB_OFFLINE=1` depois do primeiro download.

### Hunyuan demora muito a ficar `ready`

O `GET /health` do container retorna `loading` enquanto baixa pesos e o `mmgp`
os organiza entre RAM e VRAM. Na RTX 5050 observada, a inicialização com cache
pode levar cerca de 4–10 minutos; no primeiro uso, some o download de ~5 GB.
Acompanhe em vez de confiar apenas no ponto verde do Docker Desktop:

```powershell
docker compose logs -f --tail=120 hunyuan
```

Procure por erros de CUDA (`no kernel image`, `out of memory`) ou de carregamento de checkpoint. Detalhes em [`../docker/hunyuan/README.md`](../docker/hunyuan/README.md) e [09b](09b-pipeline-ai-hunyuan.md).

Mesmo com `status=ready`, confira `shape_mode=multi-view` e `fallback=False`.
`single-view` com fallback significa que o serviço está disponível em modo
degradado e usa somente a primeira imagem para gerar a geometria.

### Hunyuan responde 503 / timeout durante `/generate`

O contêiner pode estar fazendo fallback de `dmc` para `mc`, retentando octree menor, ou simplesmente sobrecarregado. Confirme com:

```powershell
docker compose exec hunyuan python -c "import server; print(server.DEFAULT_MC_ALGO)"
# → mc
```

Se a inferência continuar inviável, mantenha `PIPELINE_FALLBACK_TO_TEMPLATE=true` no `.env` para que o backend caia no `TemplateProcessor` quando o Hunyuan falhar.

## Próximas leituras

- Como o código está organizado: [04 - Estrutura de pastas](04-estrutura-de-pastas.md).
- Por que cada camada existe: [05 - Arquitetura](05-arquitetura.md).
