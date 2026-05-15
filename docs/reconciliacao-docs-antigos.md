# Reconciliacao dos docs antigos

## Visao geral

Este relatorio compara a documentacao antiga em `front/docs/`, `back/docs/`, `front/README.md`, `back/README.md` e `docker/hunyuan/README.md` contra o codigo e configuracoes atuais. A classificacao usa: ✅ correto, ⚠️ desatualizado, ❌ ausente, 🆕 a adicionar.

## Por que existe

Os docs antigos sao uteis, mas algumas afirmacoes ficaram para tras depois da integracao comercial, da configuracao por `BACKEND_BASE_URL` e do servico Hunyuan via Docker Compose (fontes: `front/docs/16-contrato-backend.md`, `front/docs/18-feature-sales.md`, `back/docs/README.md`, `back/README.md`, `docker-compose.yml`).

## Stack/dependencias

As fontes usadas para reconciliacao foram:

| Area | Fontes atuais |
|---|---|
| Front | `front/pubspec.yaml`, `front/lib/core/constants/app_constants.dart`, `front/lib/features/sales/data/sales_repository.dart`, `front/lib/app/router/app_router.dart` |
| Back | `back/requirements.txt`, `back/app/main.py`, `back/app/config.py`, `back/app/modules/*/router.py`, `back/app/modules/captures/processor.py`, `back/app/modules/sales/repository.py` |
| Docker | `docker-compose.yml`, `docker/hunyuan/Dockerfile`, `docker/hunyuan/server.py`, `docker/hunyuan/entrypoint.sh` |
| Build | `build/`, `front/android/app/build.gradle.kts`, `front/pubspec.yaml` |

## Estrutura

| Status | Item | Evidencia atual | Acao na documentacao consolidada |
|---|---|---|---|
| ✅ | Front usa Flutter, Riverpod, GoRouter, Dio, camera/image_picker e model_viewer_plus. | `front/pubspec.yaml`, `front/lib/app/router/app_router.dart`, `front/lib/core/network/dio_client.dart` | Mantido em `frontend.md`. |
| ✅ | Backend expõe `/health`, `/captures`, `/sales`, `/files` e `/templates`. | `back/app/main.py`, `back/app/modules/health/router.py`, `back/app/modules/captures/router.py`, `back/app/modules/sales/router.py` | Mantido em `backend.md`. |
| ✅ | Contrato `POST /captures` usa multipart `images` e retorna `jobId`. | `front/lib/features/product_capture/data/capture_repository.dart`, `back/app/modules/captures/router.py`, `back/app/modules/captures/schemas.py` | Mantido em `backend.md` e `frontend.md`. |
| ✅ | Polling de processamento usa `/captures/{jobId}/status` e `modelUrl`. | `front/lib/features/processing/data/processing_repository.dart`, `front/lib/features/processing/presentation/state/processing_controller.dart`, `back/app/modules/captures/router.py` | Mantido em `arquitetura.md`. |
| ✅ | Testes backend usam SQLite async em fixture, sem exigir Postgres. | `back/tests/conftest.py`, `back/requirements-dev.txt` | Mantido em `backend.md`. |
| ⚠️ | Docs antigos mostram `backendBaseUrl` hardcoded como `http://192.168.0.3:8000`. | O codigo usa `String.fromEnvironment('BACKEND_BASE_URL', defaultValue: 'http://localhost:8000')` em `front/lib/core/constants/app_constants.dart`. | Corrigido em `frontend.md` e `como-rodar.md`. |
| ⚠️ | Docs citam `HttpSalesRepository`. | Nao existe classe `HttpSalesRepository`; o HTTP comercial fica dentro de `SalesController` em `front/lib/features/sales/data/sales_repository.dart`. | Corrigido em `frontend.md`. |
| ⚠️ | Docs citam `salesRepositoryProvider`. | Os providers atuais sao `salesControllerProvider` e `salesSnapshotProvider` em `front/lib/features/sales/data/sales_repository.dart`. | Corrigido em `frontend.md`. |
| ⚠️ | Docs dizem que `SalesLocalStorage` usa SharedPreferences/localStorage. | Web usa `window.localStorage`; demais plataformas usam stub em memoria em `front/lib/features/sales/data/sales_local_storage_stub.dart`. | Corrigido em `frontend.md`. |
| ⚠️ | Docs dizem "Dados nao persistem". | Ha persistencia local best-effort e sync remoto best-effort no `SalesController`; fora do Web o stub e apenas memoria. | Corrigido com nuance em `frontend.md`. |
| ⚠️ | `back/README.md` ainda aponta `MeshroomProcessor`/AliceVision como pipeline planejado central. | `PROCESSOR_TYPE` atual aceita `fake` ou `template`; `Hunyuan3DProcessor` existe, mas nao e plugado na factory. Fontes: `back/app/config.py`, `back/app/main.py`, `back/app/modules/captures/processor.py`. | Corrigido em `backend.md` e `arquitetura.md`. |
| ⚠️ | Docs dizem que Docker e apenas para Postgres. | `docker-compose.yml` tambem tem `hunyuan` na porta `7860`. | Corrigido em `docker.md`. |
| ⚠️ | Alguns docs antigos dizem que modulo comercial/financeiro nao existe. | `back/app/modules/sales/router.py`, `schemas.py` e `repository.py` existem e expõem `/sales/*`. | Corrigido em `backend.md`. |
| ❌ | Documentacao central em `C:\TCC\docs\`. | A pasta nao existia antes desta geracao. | Criada com este conjunto de arquivos. |
| ❌ | Documento consolidado de Compose/Docker. | Havia `docker/hunyuan/README.md`, mas nao um documento central que explique Postgres + Hunyuan + portas + volumes. | Criado `docker.md`. |
| ❌ | Documento sobre `build/`. | Nao havia doc central para o estado do diretorio `build/`. | Criado `build.md`. |
| 🆕 | Registrar que Compose nao sobe backend/front. | Confirmado por `docker-compose.yml`. | Adicionado em `README.md`, `docker.md` e `como-rodar.md`. |
| 🆕 | Registrar que `ensure_sales_schema()` nao cria o schema comercial completo. | Confirmado em `back/app/modules/sales/repository.py`. | Adicionado em `backend.md`. |
| 🆕 | Registrar que Hunyuan e standalone no estado atual. | Confirmado em `docker/hunyuan/server.py` e `back/app/main.py`. | Adicionado em `arquitetura.md`, `backend.md` e `docker.md`. |

## Como rodar/usar

Use este relatorio como mapa de migracao mental: quando um doc antigo contradizer esta tabela, prefira os arquivos em `docs/`. Os docs antigos nao devem ser deletados; eles podem ser referenciados como historico ou detalhamento por modulo (fontes: `front/docs/README.md`, `back/docs/README.md`).

## Pontos de atencao

- Este relatorio nao altera `front/docs` nem `back/docs`; ele apenas marca o que foi supersedido pela documentacao central.
- Onde a fonte atual nao confirma uma inferencia, foi usado `⚠️ a confirmar`, especialmente no caso do gerador exato de `build/` (fonte: `build/`).
- A classificacao deve ser revisada sempre que `front/lib/core/constants/app_constants.dart`, `back/app/main.py`, `back/app/config.py`, `docker-compose.yml` ou `back/app/modules/sales/repository.py` mudarem.

