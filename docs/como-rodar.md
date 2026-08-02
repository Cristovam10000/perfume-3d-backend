# Como rodar

## Visao geral

Este guia descreve como subir o ambiente local do projeto: Postgres via Docker Compose, backend FastAPI via Uvicorn e frontend Flutter via CLI. O servico Hunyuan e opcional e pesado; ele roda em Docker separado na porta `7860` (fontes: `docker-compose.yml`, `.env.example`, `../perfume-3d-frontend/pubspec.yaml`, `docker/hunyuan/README.md`).

## Por que existe

O projeto tem partes independentes. O Compose nao sobe tudo sozinho, e o app Flutter precisa receber uma URL de backend que faca sentido para o dispositivo usado na demo (fontes: `docker-compose.yml`, `../perfume-3d-frontend/lib/core/constants/app_constants.dart`, `app/main.py`).

## Stack/dependencias

Requisitos locais:

| Requisito | Motivo | Fontes |
|---|---|---|
| Flutter SDK compativel com `>=3.19.0` | Rodar o app em `perfume-3d-frontend/` | `../perfume-3d-frontend/pubspec.yaml` |
| Python compativel com dependencias FastAPI | Rodar backend em `perfume-3d-backend/` | `requirements.txt` |
| Docker Desktop | Subir Postgres e, opcionalmente, Hunyuan | `docker-compose.yml` |
| GPU NVIDIA + suporte Docker GPU | Necessario para Hunyuan | `docker-compose.yml`, `docker/hunyuan/README.md` |
| Blender 5.1+ | Necessario em `PIPELINE_MODE=integrated` (refiner/cleaner/label) ou `template` | `.env.example`, `app/modules/captures/processor.py` |

## Estrutura

```text
C:\TCC
  perfume-3d-backend/
    docker-compose.yml
    docker/hunyuan/
    .env.example
    requirements*.txt
    app/main.py
  perfume-3d-frontend/
    pubspec.yaml
    lib/core/constants/app_constants.dart
```

## Como rodar/usar

1. Preparar a configuracao do backend:

```powershell
cd C:\TCC\perfume-3d-backend
Copy-Item .env.example .env
# Troque POSTGRES_PASSWORD e use a mesma senha na DATABASE_URL.
```

2. Subir o Postgres:

```powershell
docker compose up -d postgres
docker compose ps
```

3. Preparar o ambiente Python:

```powershell
cd C:\TCC\perfume-3d-backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

4. Conferir `.env` do backend:

```env
POSTGRES_PASSWORD=troque-esta-senha-local
DATABASE_URL=postgresql+asyncpg://postgres:troque-esta-senha-local@localhost:5433/tcc
# integrated (default) usa Hunyuan (GPU/Docker) + Blender. Para subir rápido sem GPU, use fake:
PIPELINE_MODE=fake
CORS_ORIGINS=*
```

O default real é `PIPELINE_MODE=integrated` (Hunyuan + cache CLIP + pós-processamento Blender). Para um **primeiro start sem GPU/Docker**, `PIPELINE_MODE=fake` sobe o servidor com um processor leve (cubo sintético); `template` usa Blender sobre GLBs prontos. Para o modo integrated completo, veja [03 — Inicialização](03-inicializacao-do-projeto.md) (fontes: `.env.example`, `docker-compose.yml`, `app/config.py`).

5. Rodar o backend:

```powershell
cd C:\TCC\perfume-3d-backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

6. Testar o backend:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

7. Preparar e rodar o frontend:

```powershell
cd C:\TCC\perfume-3d-frontend
flutter pub get
flutter run --dart-define=BACKEND_BASE_URL=http://localhost:8000
```

Para Android fisico, substitua `localhost` pelo IP da maquina na mesma rede. Para **emulador Android**, use `http://10.0.2.2:8000` — `10.0.2.2` é o alias padrão do emulador para o `localhost` da máquina host (fonte: `../perfume-3d-frontend/lib/core/constants/app_constants.dart`).

8. Opcional: subir Hunyuan:

```powershell
cd C:\TCC\perfume-3d-backend
docker compose up hunyuan
```

Depois:

```powershell
Invoke-RestMethod http://localhost:7860/health
```

Com `PIPELINE_MODE=integrated` (default), o backend usa o Hunyuan automaticamente no `POST /captures`; em `fake`/`template` ele não chama o container (fontes: `app/main.py`, `app/modules/captures/pipeline.py`, `docker/hunyuan/server.py`).

## Pontos de atencao

- Se `/sales/snapshot` falhar, o app pode abrir com dados locais/mockados; novas
  escritas comerciais exigem o backend disponível e exibem erro quando não forem confirmadas.
- Nos stages Blender do `PIPELINE_MODE=integrated`, o caminho `BLENDER_EXECUTABLE` precisa existir; caso contrario, o passo Blender falha antes de rodar (fontes: `.env.example`, `app/modules/captures/mesh_refiner.py`).
- Se o Postgres nao estiver em `localhost:5433`, ajuste `DATABASE_URL` (fontes: `.env.example`, `docker-compose.yml`).
- Se o dispositivo nao acessa o backend, ajuste `BACKEND_BASE_URL` no comando Flutter e confira firewall/rede local (fonte: `../perfume-3d-frontend/lib/core/constants/app_constants.dart`).
- Hunyuan pode demorar para ficar `ready`, pois carrega modelos em background (fonte: `docker/hunyuan/server.py`).

