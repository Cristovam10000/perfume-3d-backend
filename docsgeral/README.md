# Documentacao tecnica consolidada

## Visao geral

Este diretorio centraliza a documentacao tecnica atual do projeto em `C:\TCC`. O projeto e composto por um app Flutter em `front/`, um backend FastAPI em `back/`, servicos Docker em `docker/` e orquestracao em `docker-compose.yml` (fontes: `front/pubspec.yaml`, `back/requirements.txt`, `back/app/main.py`, `docker-compose.yml`).

O produto atual e um MVP academico para gestao/venda de perfumes com captura guiada de imagens, processamento 3D e visualizacao de modelos `.glb` no app (fontes: `front/lib/features/product_capture/data/capture_repository.dart`, `front/lib/features/processing/data/processing_repository.dart`, `front/lib/features/product_viewer/presentation/pages/product_3d_viewer_page.dart`, `back/app/modules/captures/router.py`).

## Por que existe

Os documentos antigos continuam em `front/docs/` e `back/docs/`, mas alguns pontos ficaram divergentes do codigo atual. Esta pasta cria uma visao unica, atualizada e citada por fonte, sem apagar os docs antigos (fontes: `front/docs/README.md`, `back/docs/README.md`, `front/lib/core/constants/app_constants.dart`, `back/app/main.py`).

## Stack/dependencias

| Camada | Stack atual | Fontes |
|---|---|---|
| Frontend | Flutter/Dart, Riverpod, GoRouter, Dio, camera/image_picker, sensors_plus, opencv_dart, model_viewer_plus | `front/pubspec.yaml` |
| Backend | FastAPI, Uvicorn, Pydantic v2, pydantic-settings, SQLAlchemy async, asyncpg, python-multipart, httpx | `back/requirements.txt` |
| Banco | PostgreSQL 16 em container, acessado por `postgresql+asyncpg://...` | `docker-compose.yml`, `back/.env.example`, `back/app/database.py` |
| IA/3D Docker | Hunyuan3D-2mv em container FastAPI separado, com PyTorch CUDA 12.8 e mmgp | `docker/hunyuan/Dockerfile`, `docker/hunyuan/server.py` |
| Testes | Backend com pytest/pytest-asyncio/httpx/aiosqlite; frontend com flutter_test | `back/requirements-dev.txt`, `back/pytest.ini`, `front/test/sale_wizard_test.dart` |

## Estrutura

```text
docs/
  README.md
  arquitetura.md
  frontend.md
  backend.md
  docker.md
  build.md
  como-rodar.md
  reconciliacao-docs-antigos.md
```

Os documentos de `docs/` sao consolidados. Os documentos de `front/docs/` e `back/docs/` continuam como historico e referencia detalhada por subsistema (fontes: `front/docs/README.md`, `back/docs/README.md`).

## Como rodar/usar

Leitura recomendada:

1. Comece por `docs/arquitetura.md` para entender a comunicacao entre app, backend, banco e Hunyuan.
2. Use `docs/como-rodar.md` para subir o ambiente local.
3. Use `docs/frontend.md`, `docs/backend.md` e `docs/docker.md` para detalhes por camada.
4. Use `docs/reconciliacao-docs-antigos.md` para saber o que foi corrigido em relacao aos docs antigos.

Comandos de referencia:

```powershell
# Banco Postgres local via Compose
docker compose up -d postgres

# Backend FastAPI
cd C:\TCC\back
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend Flutter
cd C:\TCC\front
flutter run --dart-define=BACKEND_BASE_URL=http://localhost:8000
```

Esses comandos sao derivados dos manifests e configuracoes atuais; a criacao de venv, instalacao de dependencias e builds devem ser executadas manualmente quando necessario (fontes: `back/requirements-dev.txt`, `back/.env.example`, `front/pubspec.yaml`, `front/lib/core/constants/app_constants.dart`).

## Pontos de atencao

- `docker-compose.yml` sobe `postgres` e `hunyuan`; ele nao sobe o backend FastAPI nem o app Flutter (fonte: `docker-compose.yml`).
- O backend escolhe somente `FakeProcessor` ou `TemplateProcessor` via `PROCESSOR_TYPE`; `Hunyuan3DProcessor` existe no codigo, mas nao esta conectado na factory `build_processor()` (fontes: `back/app/config.py`, `back/app/main.py`, `back/app/modules/captures/processor.py`).
- O modulo `sales` depende de um schema comercial preexistente; `ensure_sales_schema()` aplica apenas compatibilidade incremental com `ALTER TABLE` (fonte: `back/app/modules/sales/repository.py`).
- `build/` e `tmp/` devem ser tratados como leitura/artefato local. Esta documentacao nao modifica esses diretorios (fontes: `build/`, `tmp/`).

