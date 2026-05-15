# Como rodar

## Visao geral

Este guia descreve como subir o ambiente local do projeto: Postgres via Docker Compose, backend FastAPI via Uvicorn e frontend Flutter via CLI. O servico Hunyuan e opcional e pesado; ele roda em Docker separado na porta `7860` (fontes: `docker-compose.yml`, `back/.env.example`, `front/pubspec.yaml`, `docker/hunyuan/README.md`).

## Por que existe

O projeto tem partes independentes. O Compose nao sobe tudo sozinho, e o app Flutter precisa receber uma URL de backend que faca sentido para o dispositivo usado na demo (fontes: `docker-compose.yml`, `front/lib/core/constants/app_constants.dart`, `back/app/main.py`).

## Stack/dependencias

Requisitos locais:

| Requisito | Motivo | Fontes |
|---|---|---|
| Flutter SDK compativel com `>=3.19.0` | Rodar o app em `front/` | `front/pubspec.yaml` |
| Python compativel com dependencias FastAPI | Rodar backend em `back/` | `back/requirements.txt` |
| Docker Desktop | Subir Postgres e, opcionalmente, Hunyuan | `docker-compose.yml` |
| GPU NVIDIA + suporte Docker GPU | Necessario para Hunyuan | `docker-compose.yml`, `docker/hunyuan/README.md` |
| Blender 5.1+ | Necessario se `PROCESSOR_TYPE=template` | `back/.env.example`, `back/app/modules/captures/processor.py` |

## Estrutura

```text
C:\TCC
  docker-compose.yml
  back/
    .env.example
    requirements*.txt
    app/main.py
  front/
    pubspec.yaml
    lib/core/constants/app_constants.dart
  docker/hunyuan/
    Dockerfile
    server.py
```

## Como rodar/usar

1. Subir o Postgres:

```powershell
cd C:\TCC
docker compose up -d postgres
```

2. Preparar o backend:

```powershell
cd C:\TCC\back
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

3. Conferir `.env` do backend:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/tcc
PROCESSOR_TYPE=fake
CORS_ORIGINS=*
```

Esses defaults batem com `docker-compose.yml` para Postgres local e com o processor leve sem Blender (fontes: `back/.env.example`, `docker-compose.yml`, `back/app/config.py`).

4. Rodar o backend:

```powershell
cd C:\TCC\back
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

5. Testar o backend:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

6. Preparar e rodar o frontend:

```powershell
cd C:\TCC\front
flutter pub get
flutter run --dart-define=BACKEND_BASE_URL=http://localhost:8000
```

Para Android fisico, substitua `localhost` pelo IP da maquina na mesma rede. Para emulador Android, use um host acessivel ao emulador, como `http://10.0.2.2:8000` quando aplicavel `⚠️ a confirmar no ambiente` (fonte: `front/lib/core/constants/app_constants.dart`).

7. Opcional: subir Hunyuan:

```powershell
cd C:\TCC
docker compose up hunyuan
```

Depois:

```powershell
Invoke-RestMethod http://localhost:7860/health
```

O backend principal nao usa Hunyuan automaticamente sem alteracao de factory/configuracao (fontes: `back/app/main.py`, `back/app/modules/captures/processor.py`, `docker/hunyuan/server.py`).

## Pontos de atencao

- Se `/sales/snapshot` falhar, o app continua com dados locais/mockados; isso e comportamento esperado do `SalesController` (fonte: `front/lib/features/sales/data/sales_repository.dart`).
- Se `PROCESSOR_TYPE=template`, o caminho `BLENDER_EXECUTABLE` precisa existir; caso contrario, o `TemplateProcessor` falha antes de rodar (fontes: `back/.env.example`, `back/app/modules/captures/processor.py`).
- Se o Postgres nao estiver em `localhost:5433`, ajuste `DATABASE_URL` (fontes: `back/.env.example`, `docker-compose.yml`).
- Se o dispositivo nao acessa o backend, ajuste `BACKEND_BASE_URL` no comando Flutter e confira firewall/rede local (fonte: `front/lib/core/constants/app_constants.dart`).
- Hunyuan pode demorar para ficar `ready`, pois carrega modelos em background (fonte: `docker/hunyuan/server.py`).

