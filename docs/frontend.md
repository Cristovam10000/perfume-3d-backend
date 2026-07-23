# Frontend

## Visao geral

O frontend esta no repositorio irmao `C:\TCC\perfume-3d-frontend`. E um aplicativo Flutter com duas jornadas integradas:

- operacao comercial de clientes, produtos, estoque, vendas, cobrancas e notificacoes;
- captura guiada das quatro vistas cardeais do frasco, envio ao backend, polling e visualizacao do GLB.

## Stack e estrutura

| Area | Tecnologia/local |
|---|---|
| Estado | Riverpod |
| Navegacao | GoRouter |
| HTTP | Dio |
| Captura | `image_picker`, camera e implementacao legada com sensores/ORB |
| Viewer 3D | `model_viewer_plus` |
| Codigo | `perfume-3d-frontend/lib/` |
| Documentacao detalhada | `perfume-3d-frontend/docs/` |

O app abre em `HomeDashboardPage`. A captura ativa usa `CaptureViewsPage`, exige `front`, `left`, `back` e `right` e aceita ate duas imagens extras.

## Integracao HTTP

A URL e definida em runtime:

```text
--dart-define=BACKEND_BASE_URL=http://localhost:8000
```

Captura/processamento usa `/captures/*`. O `SalesController` usa `/sales/*`; o
mock/cache serve como fallback de leitura, mas novas escritas comerciais so entram
no estado depois de confirmadas pelo backend.

## Executar e testar

```powershell
cd C:\TCC\perfume-3d-frontend
flutter pub get
flutter run --dart-define=BACKEND_BASE_URL=http://localhost:8000
flutter analyze
flutter test
```

Em aparelho fisico, use o IP do computador. No Android Emulator, normalmente use `http://10.0.2.2:8000`.

Estado verificado em 2026-07-23: analise estatica sem problemas e 21 testes aprovados.

## Limitacoes atuais

- Nao ha autenticacao.
- A sincronizacao comercial e *best-effort*, sem fila duravel ou resolucao de conflitos.
- O cadastro de cliente ainda nao esta implementado.
- A rota `/captura/:produtoId` ainda nao repassa o produto ao envio.
- `/processando/:jobId` nao reidrata o controller pelo parametro; o fluxo normal inicia o polling antes de navegar.
