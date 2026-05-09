# 13 — Endpoints HTTP e contrato com o app

Base URL: `http://<host>:<porta>/` (ex.: `http://127.0.0.1:8000` ou `http://10.0.2.2:8000` no emulador Android). Prefixos sem versão (não há `/v1`).

## `GET /health`

- **200** com corpo: `{ "status": "ok" }`
- Liveness; não toca banco.

## `POST /captures`

- **Content-Type:** `multipart/form-data`
- **Campo:** `images` — um ou mais ficheiros (nome do campo **images**, repetido para N ficheiros).
- **201 Created** com corpo JSON (camelCase por alias Pydantic):

```json
{ "jobId": "<uuid-v4>" }
```

- **422** se não houver imagens (`{"error": "Nenhuma imagem recebida"}`) ou validação de domínio semelhante.
- Não exige `Authorization` (não há autenticação no MVP).

## `GET /captures/{job_id}/status`

- **200** com corpo (campos `null` omitidos em alguns clientes, mas o schema Pydantic serializa `null` explícito quando aplicável):

| Campo (JSON) | Tipo | Descrição |
|---------------|------|-----------|
| `status` | string | `waiting` \| `processing` \| `completed` \| `error` |
| `message` | string ou null | mensagem informativa (ex.: "Reconstruindo modelo 3D") |
| `modelUrl` | string ou null | URL **absoluta** do GLB, só quando concluído; montada com `request.base_url` + `model_path` do job |
| `error` | string ou null | detalhe se `status=error` |

- **404** se o `job_id` não existir: `{"error": "Job <id> não encontrado"}`.

O front deve fazer *polling* (ex. a cada 2–3 s) até `status` ser `completed` ou `error`.

## Ficheiros estáticos

| Caminho | Descrição |
|---------|-----------|
| `GET /files/models/{job_id}.glb` | Modelo 3D final (o mesmo de `modelUrl` quando o host bate certo) |
| `GET /files/uploads/...` | Possível acesso direto a uploads (tipicamente o app usa só a API) |
| `GET /files/model_viewer.html` | Viewer local de depuração (model-viewer) |
| `GET /templates/{nome}.glb` | Só se `TEMPLATES_DIR` existir; template normalizado puro, sem customização de job |

## Endpoints comerciais — `/sales/*`

API CRUD do módulo `sales/`. Todos retornam JSON com aliases camelCase (Pydantic `serialization_alias`); compatível com `HttpSalesRepository` do app Flutter.

### `GET /sales/snapshot`

- **200** — devolve o estado completo da operação comercial num único payload, otimizado para *first paint* do dashboard:

```json
{
  "hoje": "2026-05-09T00:00:00",
  "clientes": [ {"id": "...", "nome": "...", "telefone": "...", "score": 0, "status": "...", "emAberto": 0.0, "totalCompras": 0, "parcelasAtraso": 0, "totalComprado": 0.0, "syncStatus": "synced"} ],
  "produtos": [ {"id": "...", "nome": "...", "categoria": "...", "precoBase": 0.0, "custo": 0.0, "estoque": 0, "estoqueMinimo": 1, "volumeMl": 100, "frascoColorValue": 4285558395, "tem3D": false, "modelo3DPath": null, "previewImg": null, "syncStatus": "synced"} ],
  "vendas": [ {"id": "...", "clienteId": "...", "data": "...", "itens": [...], "total": 0.0, "entrada": 0.0, "numParcelas": 1, "observacoes": null, "syncStatus": "synced"} ],
  "parcelas": [...],
  "pagamentos": [...],
  "notificacoes": [...]
}
```

### `POST /sales/products`

- **Content-Type:** `application/json`
- **Body** (`ProductCreateIn`):

```json
{
  "nome": "Empire Sport 100ml",
  "categoria": "Perfume",
  "precoBase": 199.90,
  "custo": 80.0,
  "estoque": 12,
  "estoqueMinimo": 2,
  "volumeMl": 100,
  "frascoColorValue": 4292216955
}
```

- **201 Created** com corpo `ProdutoOut` (mesmo schema da listagem em `snapshot.produtos`).

### `PATCH /sales/products/{product_id}/stock`

- **Body** (`ProductStockUpdateIn`):

```json
{ "mode": "add", "quantity": 5 }
```

- `mode = "add"` soma à quantidade atual; `mode = "set"` substitui.
- **200** com corpo atualizado `ProdutoOut`.
- **404** se o produto não existir.

### `POST /sales/sales`

- **Body** (`SaleCreateIn`):

```json
{
  "clienteId": "...",
  "data": "2026-05-09T14:30:00",
  "itens": [
    { "produtoId": "...", "quantidade": 1, "precoUnitario": 199.90 }
  ],
  "total": 199.90,
  "entrada": 50.0,
  "numParcelas": 3,
  "observacoes": null
}
```

- **201 Created** com corpo `{ "id": "<uuid-da-venda>" }`.
- A criação da venda também gera as parcelas automaticamente (regra de negócio do `SalesRepository.create_sale`); são lidas via `/sales/snapshot` no próximo refresh.
- Erros de validação de regra de negócio (cliente inativo, produto sem estoque, total inconsistente) retornam **422** com mensagem do `ValidationError`.

> **Idempotência:** os endpoints de escrita não exigem `Idempotency-Key` no MVP. O `HttpSalesRepository` do app garante que cada ação dispara uma única requisição via *queue* local de eventos.

## OpenAPI

- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

## Alinhamento com o Flutter

- Campos de resposta usam **camelCase** (`jobId`, `modelUrl`, `precoBase`, `tem3D`, ...) — ver `serialization_alias` em `schemas.py` de cada módulo. Manter o contrato alinhado com `processing_repository.dart` (captures) e `sales_repository.dart` (sales) no front.

## Leituras relacionadas

- [08 — Módulo `captures`](08-modulo-captures.md)
- [12 — Armazenamento e banco](12-armazenamento-e-banco.md) (tabelas referenciadas pelos endpoints `/sales/*`)
- Front: [`16 - Contrato do backend`](../../front/docs/16-contrato-backend.md), [`18 - Feature sales`](../../front/docs/18-feature-sales.md)
