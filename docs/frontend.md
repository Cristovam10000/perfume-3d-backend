# Frontend

## Visao geral

O frontend em `front/` e um app Flutter chamado `perfume_3d_mvp`, com Material, Riverpod para estado/injecao, GoRouter para navegacao, Dio para HTTP e ModelViewer para modelos 3D (fontes: `front/pubspec.yaml`, `front/lib/app/app.dart`, `front/lib/app/router/app_router.dart`).

As areas funcionais atuais sao dashboard/vendas, captura de imagens, polling de processamento e visualizacao de modelos 3D (fontes: `front/lib/features/sales/data/sales_repository.dart`, `front/lib/features/product_capture/data/capture_repository.dart`, `front/lib/features/processing/data/processing_repository.dart`, `front/lib/features/product_viewer/data/viewer_repository.dart`).

## Por que existe

O app existe para demonstrar o fluxo completo do TCC: gerir uma operacao comercial de perfumes, capturar fotos de um produto e visualizar modelos 3D gerados pelo backend (fontes: `front/lib/features/sales/presentation/pages/home_dashboard_page.dart`, `front/lib/features/product_capture/presentation/pages/capture_camera_page.dart`, `front/lib/features/product_viewer/presentation/pages/product_3d_viewer_page.dart`).

## Stack/dependencias

| Categoria | Dependencias | Fontes |
|---|---|---|
| SDK | Dart `>=3.3.0 <4.0.0`, Flutter `>=3.19.0` | `front/pubspec.yaml` |
| Estado | `flutter_riverpod` | `front/pubspec.yaml`, `front/lib/features/processing/presentation/state/processing_controller.dart` |
| Rotas | `go_router` | `front/pubspec.yaml`, `front/lib/app/router/app_router.dart` |
| HTTP | `dio` | `front/pubspec.yaml`, `front/lib/core/network/dio_client.dart` |
| Captura/midia | `camera`, `image_picker`, `path_provider` | `front/pubspec.yaml` |
| Sensores/CV | `sensors_plus`, `opencv_dart` | `front/pubspec.yaml`, `front/lib/core/utils/orb_similarity_tracker.dart` |
| 3D/UI | `model_viewer_plus`, `intl`, `google_fonts` | `front/pubspec.yaml` |
| Testes/lint | `flutter_test`, `flutter_lints` | `front/pubspec.yaml`, `front/analysis_options.yaml` |

## Estrutura

```text
front/lib/
  main.dart
  app/
    app.dart
    router/
    theme/
  core/
    constants/
    errors/
    network/
    utils/
  features/
    home/
    product_capture/
    processing/
    product_viewer/
    sales/
  shared/widgets/
```

O app inicializa locale `pt_BR` antes de montar `ProviderScope(child: PerfumeApp())` (fonte: `front/lib/main.dart`). A URL base do backend fica em `AppConstants.backendBaseUrl`, lida por `String.fromEnvironment('BACKEND_BASE_URL', defaultValue: 'http://localhost:8000')` (fonte: `front/lib/core/constants/app_constants.dart`).

Rotas comerciais e de captura estao declaradas em `AppRoutes` e montadas no `GoRouter` (fontes: `front/lib/app/router/app_routes.dart`, `front/lib/app/router/app_router.dart`). As rotas atuais incluem `/`, `/clientes`, `/cliente/:id`, `/venda/nova`, `/venda/:id`, `/cobranca`, `/produtos`, `/produto/:id/3d`, `/captura/:produtoId`, `/processando/:jobId`, `/notificacoes`, `/capture/*`, `/processing` e `/viewer` (fontes: `front/lib/app/router/app_routes.dart`, `front/lib/app/router/app_router.dart`).

## Como rodar/usar

Instalacao e execucao local:

```powershell
cd C:\TCC\front
flutter pub get
flutter run --dart-define=BACKEND_BASE_URL=http://localhost:8000
```

Para Android fisico ou emulador, ajuste `BACKEND_BASE_URL` para um host acessivel pelo dispositivo. O proprio codigo recomenda passar a URL via `--dart-define` (fonte: `front/lib/core/constants/app_constants.dart`).

Comandos uteis:

```powershell
cd C:\TCC\front
flutter analyze
flutter test
flutter run -d chrome --dart-define=BACKEND_BASE_URL=http://localhost:8000
```

Nao ha scripts `package.json`; o projeto Flutter e comandado pela CLI do Flutter (fonte: ausencia de `package.json` na exploracao e presenca de `front/pubspec.yaml`).

## Pontos de atencao

- `SalesController` comeca com dados mockados, tenta restaurar cache local e depois tenta `/sales/snapshot`; falhas HTTP sao engolidas para manter o app utilizavel offline (fonte: `front/lib/features/sales/data/sales_repository.dart`).
- No Web, `SalesLocalStorage` usa `window.localStorage`; fora do Web, o stub atual guarda em memoria estatica do processo (fontes: `front/lib/features/sales/data/sales_local_storage.dart`, `front/lib/features/sales/data/sales_local_storage_web.dart`, `front/lib/features/sales/data/sales_local_storage_stub.dart`).
- A rota `/processando/:jobId` existe, mas a tela nao reidrata o controller a partir do parametro de rota; o fluxo funcional atual inicia polling antes de navegar para `/processing` (fontes: `front/lib/app/router/app_router.dart`, `front/lib/features/product_capture/presentation/pages/capture_review_page.dart`, `front/lib/features/processing/presentation/state/processing_controller.dart`).
- O Android permite internet e trafego HTTP claro, necessario para backend local sem HTTPS em demo (fonte: `front/android/app/src/main/AndroidManifest.xml`).
- O README raiz do front ainda e o template padrao do Flutter e deve ser considerado supersedido por esta documentacao (fonte: `front/README.md`).

