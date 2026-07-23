# 13 — Endpoints HTTP e contrato com o app

> **O que você vai aprender neste doc**
> - O contrato HTTP completo entre o backend e o app Flutter (request, response, erros).
> - Por que as respostas usam **camelCase** (`jobId`, `modelUrl`) via `serialization_alias`.
> - Como cache hit e geração se distinguem **sem** um campo `origem` dedicado.
>
> **Pré-requisitos:** [01 - Visão geral](01-visao-geral.md). Para a sequência interna do
> `POST /captures`, leia [09f - Pipeline integrado](09f-pipeline-integrado.md).

Base URL: `http://<host>:<porta>/` (ex.: `http://127.0.0.1:8000` ou `http://10.0.2.2:8000` no emulador Android). Prefixos sem versão (não há `/v1`).

## `GET /health`

- **200** com corpo: `{ "status": "ok" }`
- Liveness; não toca banco.

## `POST /captures`

- **Content-Type:** `multipart/form-data`
- **Campos:**
  - `images` — um ou mais ficheiros (nome do campo **images**, repetido para N ficheiros).
  - `productId` (opcional, parte do form-data) — `integer`. Quando enviado, o backend amarra o GLB ao produto correspondente em `modelos_3d_produto` ao final do pipeline (cache miss → INSERT; cache hit → UPSERT do vínculo). Se omitido, o GLB é entregue ao job e (em miss) populado em `modelos_3d_universais`, **sem** vincular a nenhum produto comercial. Recebido em `router.py` (`create_capture`) e propagado pelo `CaptureService.create_job`.
- **201 Created** com corpo JSON (camelCase por alias Pydantic):

```json
{ "jobId": "<uuid-v4>" }
```

- **422** se não houver imagens (`{"error": "Nenhuma imagem recebida"}`) ou validação de domínio semelhante.
- Não exige `Authorization` (não há autenticação no MVP).

> **Quando passar `productId`:** quando a captura partir de dentro de uma tela de produto no app (botão "Atualizar modelo 3D" em `product_3d_page.dart`, por exemplo). Quando o usuário inicia uma captura "solta" no fluxo principal sem ter escolhido um produto, omite o campo e o backend trata como captura sem vínculo. Em ambos os casos o cache global ainda funciona — o que muda é apenas a amarração `modelos_3d_produto`.

## `GET /captures/{job_id}/status`

- **200** com corpo (campos `null` omitidos em alguns clientes, mas o schema Pydantic serializa `null` explícito quando aplicável):

| Campo (JSON) | Tipo | Descrição |
|---------------|------|-----------|
| `status` | string | `waiting` \| `processing` \| `completed` \| `error` |
| `message` | string ou null | mensagem informativa (ex.: "Reconstruindo modelo 3D", "Modelo entregue pelo cache (similaridade=0.95)") |
| `modelUrl` | string ou null | URL **absoluta** do GLB, só quando concluído; montada com `request.base_url` + `model_path` do job |
| `productId` | integer ou null | produto vinculado ao job; permite recuperar o destino ao retomar o polling |
| `error` | string ou null | detalhe se `status=error` |

- **404** se o `job_id` não existir: `{"error": "Job <id> não encontrado"}`.

O front deve fazer *polling* (ex. a cada 2–3 s) até `status` ser `completed` ou `error`.

> **Cache hit vs. miss**: o backend não devolve um campo dedicado `origem` ainda. O sinal vem pelo `message` ("Modelo entregue pelo cache (similaridade=0.95)" vs "Modelo gerado via Hunyuan3D-2mv") e pelo tempo: hits respondem em segundos, misses em minutos. Um campo explícito `origem: "cache" | "generated"` está no roadmap mas não foi implementado ainda. Ver [09g - Cache de similaridade CLIP](09g-cache-similaridade-clip.md).

## Ficheiros estáticos

| Caminho | Descrição |
|---------|-----------|
| `GET /files/models/{job_id}.glb` | Modelo 3D final (o mesmo de `modelUrl` quando o host bate certo) |
| `GET /files/uploads/...` | Possível acesso direto a uploads (tipicamente o app usa só a API) |
| `GET /files/model_viewer.html` | Viewer local de depuração (model-viewer) |
| `GET /templates/{nome}.glb` | Só se `TEMPLATES_DIR` existir; template normalizado puro, sem customização de job |

## Endpoints comerciais — `/sales/*`

API CRUD do módulo `sales/`. Todos retornam JSON com aliases camelCase (Pydantic `serialization_alias`); consumido pelo `SalesController` do app Flutter ([`sales_repository.dart`](../../perfume-3d-frontend/lib/features/sales/data/sales_repository.dart) — não existe uma classe `HttpSalesRepository` separada).

### `GET /sales/snapshot`

- **200** — devolve o estado completo da operação comercial num único payload.
  Antes da leitura, o backend cria/reagenda os avisos de cobrança sem duplicá-los
  e retorna somente notificações cuja data programada já chegou:

```json
{
  "hoje": "2026-05-09T00:00:00",
  "clientes": [ {"id": "...", "nome": "...", "telefone": "...", "bairro": "...", "score": 0, "status": "...", "emAberto": 0.0, "totalCompras": 0, "parcelasAtraso": 0, "totalComprado": 0.0, "syncStatus": "synced"} ],
  "produtos": [ {"id": "...", "nome": "...", "categoria": "...", "precoBase": 0.0, "custo": 0.0, "estoque": 0, "estoqueMinimo": 1, "volumeMl": 100, "frascoColorValue": 4285558395, "tem3D": false, "modelo3DPath": null, "previewImg": null, "syncStatus": "synced"} ],
  "vendas": [ {"id": "...", "clienteId": "...", "data": "...", "itens": [...], "total": 0.0, "entrada": 0.0, "numParcelas": 1, "observacoes": null, "syncStatus": "synced"} ],
  "parcelas": [...],
  "pagamentos": [...],
  "notificacoes": [...]
}
```

### `POST /sales/clients` e `PATCH /sales/clients/{client_id}`

```json
{
  "nome": "Maria Silva",
  "telefone": "85999998888",
  "bairro": "Centro"
}
```

- `POST` responde **201**; `PATCH`, **200**.
- Nome, telefone e bairro são obrigatórios. O `PATCH` responde **404** quando o
  cliente ativo não existe.

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

- Preço e custo precisam ser maiores que zero.
- **201 Created** com corpo `ProdutoOut` (mesmo schema da listagem em `snapshot.produtos`).

### `PATCH /sales/products/{product_id}`

Edita nome, categoria, preço, custo, estoque mínimo, volume e cor. Estoque não
faz parte deste payload e continua no endpoint específico abaixo.

### `PATCH /sales/products/{product_id}/stock`

- **Body** (`ProductStockUpdateIn`):

```json
{ "mode": "add", "quantity": 5 }
```

- `mode = "add"` soma à quantidade atual; `mode = "set"` substitui.
- **200** com corpo atualizado `ProdutoOut`.
- **404** se o produto não existir.

### `POST /sales/installments/{installment_id}/payments`

```json
{
  "requestId": "payment-18-1784788800000000",
  "valor": 50.0,
  "data": "2026-07-23",
  "forma": "Pix",
  "observacoes": "Pagamento parcial"
}
```

- `forma`: `Pix`, `Dinheiro`, `Cartão` ou `Transferência`.
- Aceita total ou parcial; rejeita zero, excesso e parcela já paga.
- `requestId` é único. Repetir a mesma requisição devolve o mesmo recebimento,
  sem duplicar o pagamento.
- Pagamento, saldo/status da parcela, evento, notificação e resumo do cliente
  são atualizados na mesma transação.

### `PATCH /sales/installments/{installment_id}/due-date`

```json
{ "dueDate": "2026-08-15", "observacoes": "Combinado com a cliente" }
```

Altera uma parcela aberta, registra o evento e reagenda os avisos de amanhã,
hoje e atraso. Parcela paga ou data no passado retorna **422**.

### `PATCH /sales/notifications/{notification_id}/read`

```json
{ "lida": true }
```

Marca ou desmarca a notificação e devolve o objeto atualizado.

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
- Erros de validação de regra de negócio retornam **422** com mensagem do `ValidationError`. Casos cobertos por `SalesRepository.create_sale`: venda sem itens, `clienteId` inexistente, `produtoId` inexistente, **estoque insuficiente** (`estoque < quantidade solicitada`) e preço unitário negativo.

> **Idempotência:** recebimentos usam `requestId` no corpo. As demais telas
> bloqueiam toque duplo e só apresentam a alteração depois de uma resposta de
> sucesso do backend.

## OpenAPI

- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

## Alinhamento com o Flutter

- Campos de resposta usam **camelCase** (`jobId`, `modelUrl`, `precoBase`, `tem3D`, ...) — ver `serialization_alias` em `schemas.py` de cada módulo. Manter o contrato alinhado com `processing_repository.dart` (captures) e `sales_repository.dart` (sales) no front.

## Endpoints administrativos de cache (planejado, não MVP)

Em uma sessão futura, o backend exporá rotas para curadoria manual do cache de modelos:

```
GET    /captures/cache          → lista de entradas (id, glb_url, created_at, hit_count, product_id)
GET    /captures/cache/{cache_id} → detalhe + (opcional) top-5 vizinhos similares
DELETE /captures/cache/{cache_id} → remove entrada da tabela modelos_3d_universais e o GLB do disco
```

Documentado em [09g - Cache de similaridade CLIP](09g-cache-similaridade-clip.md). Útil quando o threshold der falsos positivos ou quando você precisar regenerar um produto específico após melhorar fotos/parâmetros.

## Leituras relacionadas

- [08 — Módulo `captures`](08-modulo-captures.md)
- [09f — Pipeline integrado](09f-pipeline-integrado.md) (sequência interna do `POST /captures`)
- [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md) (endpoints admin futuros)
- [12 — Armazenamento e banco](12-armazenamento-e-banco.md) (tabelas referenciadas pelos endpoints `/sales/*` e a nova `modelos_3d_universais`)
- Frontend: [`16 - Contrato do backend`](../../perfume-3d-frontend/docs/16-contrato-backend.md), [`18 - Feature sales`](../../perfume-3d-frontend/docs/18-feature-sales.md)
