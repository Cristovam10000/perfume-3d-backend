# 03 — Inicialização do projeto

Como sair de um clone novo até o servidor respondendo `200` no `/health`. Comandos em **PowerShell**; em bash/zsh ajuste só os ativadores de venv e os paths.

## Pré-requisitos

- **Python 3.12+** (recomendado 3.14, mas 3.12 e 3.13 funcionam)
- **Docker Desktop** (só para subir o Postgres)
- **Git**
- **Blender 5.1+** — apenas se quiser usar `PROCESSOR_TYPE=template` (pipeline 3D real). Para o `FakeProcessor` (cubo sintético) não precisa.

## 1. Postgres em container

```powershell
docker run -d `
  --name tcc-postgres `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=tcc `
  -p 5433:5432 `
  postgres:16
```

Se já criou e só está parado:

```powershell
docker start tcc-postgres
```

> **Por que porta 5433** e não a default 5432? Para não conflitar com instalações nativas de Postgres. Se já roda outro Postgres na 5432, o backend assume 5433 por convenção.

## 2. Ambiente Python

```powershell
cd c:\TCC\back

py -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements-dev.txt
```

`requirements-dev.txt` herda `requirements.txt`, então uma instalação só puxa runtime + ferramentas de teste.

### (Opcional) Classificador CLIP

Se for usar `CLASSIFIER_TYPE=clip` ou `COLOR_DETECTOR_TYPE=average`:

```powershell
pip install -r requirements-classifier.txt
```

Custo: ~2GB de download (`torch` + pesos do CLIP). Para CPU-only, funciona; com RTX 5050+ é ~10x mais rápido.

## 3. Variáveis de ambiente

```powershell
Copy-Item .env.example .env
```

O `.env.example` já vem com defaults sãs para dev local. Pontos que talvez você queira ajustar:

| Variável | Default | Quando mudar |
|---|---|---|
| `PROCESSOR_TYPE` | `fake` | Mude para `template` quando tiver Blender instalado e quiser modelos reais. |
| `BLENDER_EXECUTABLE` | path Windows | Ajuste se Blender estiver em outro path ou outro SO. |
| `CLASSIFIER_TYPE` | `disabled` | Mude para `clip` se instalou `requirements-classifier.txt`. |
| `COLOR_DETECTOR_TYPE` | `disabled` | Mude para `average` se quer cor real do líquido (precisa de Pillow). |
| `DATABASE_URL` | aponta para `tcc-postgres` na 5433 | Mude se seu Postgres está em outro host/porta. |

Detalhes de cada chave em [07 — Camada `core` → secção *Settings*](07-camada-core.md#settings).

## 4. Subir o servidor

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

O `--reload` reinicia automaticamente quando você edita `.py`. Com `--host 0.0.0.0`, o servidor responde em todas as interfaces — necessário para o app Flutter em device físico alcançar via Wi-Fi.

### O que acontece no startup

O `production_lifespan` em [`app/main.py`](../app/main.py) executa, em ordem:

1. `configure_logging()` — handler em stdout com timestamp.
2. `create_all()` — cria as tabelas (`capture_jobs`, `capture_images`) se faltarem.
3. `LocalStorage().ensure_dirs()` — garante `storage/uploads/` e `storage/models/`.
4. `build_processor()` / `build_classifier()` / `build_color_detector()` — instancia conforme o `.env`.
5. `ProcessingQueue().start(handler=service.process_job)` — sobe o worker async.
6. Loga `Backend pronto em 0.0.0.0:8000 (processor=..., classifier=..., color=...)`.

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

Para device físico, ajuste `backendBaseUrl` em [`../../front/lib/core/constants/app_constants.dart`](../../front/lib/core/constants/app_constants.dart) e libere a porta 8000 no firewall do Windows (`New-NetFirewallRule -DisplayName "TCC backend 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`).

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

A suíte completa tem ~106 testes em 10 arquivos. Os testes **não precisam** de Postgres rodando — usam SQLite em arquivo temporário (fixture `session_factory` em [`tests/conftest.py`](../tests/conftest.py)).

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

O caminho deve apontar para `.venv\Scripts\python.exe` dentro de `back/`.

### `connection refused` no Postgres

Container parado:

```powershell
docker ps -a | Select-String tcc-postgres
docker start tcc-postgres
```

### `BLENDER_EXECUTABLE` não existe

Em `.env`, ajuste o path. Em Linux geralmente é `/usr/bin/blender`; no macOS, `/Applications/Blender.app/Contents/MacOS/Blender`. Sem Blender, troque para `PROCESSOR_TYPE=fake`.

### CLIP travando ou OOM

Em CPU, a primeira inferência leva ~5-10s (carrega pesos). Se travar, é provavelmente download de pesos do HuggingFace — confira a rede. Para offline, defina `HF_HUB_OFFLINE=1` depois do primeiro download.

## Próximas leituras

- Como o código está organizado: [04 - Estrutura de pastas](04-estrutura-de-pastas.md).
- Por que cada camada existe: [05 - Arquitetura](05-arquitetura.md).
