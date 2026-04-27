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

## OpenAPI

- `GET /docs` — Swagger UI
- `GET /redoc` — ReDoc

## Alinhamento com o Flutter

- Campos de resposta usam **camelCase** (`jobId`, `modelUrl`) — ver `serialization_alias` em `schemas.py`. Manter o contrato alinhado com o repositório de processamento no front (ex. `processing_repository.dart`).

## Leituras relacionadas

- [08 — Módulo `captures`](08-modulo-captures.md)
- Documentação do app (se existir ficheiro de contrato partilhado no monorepo)
