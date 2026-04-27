# 08 — Módulo `captures`

Todo o domínio de **captura de fotos → job → modelo 3D** vive em `app/modules/captures/`. Este módulo segue o padrão *feature-first*: router, service, repository, models, schemas, fila e estratégias de pipeline.

## Arquivos e responsabilidades

| Arquivo | Função |
|---------|--------|
| `router.py` | `POST /captures`, `GET /captures/{id}/status` |
| `service.py` | `CaptureService`: `create_job`, `get_job`, `process_job` (worker) |
| `repository.py` | `CaptureRepository`: CRUD de job e imagens no Postgres |
| `models.py` | `CaptureJob`, `CaptureImage` (SQLAlchemy 2.0) |
| `schemas.py` | DTOs Pydantic com alias camelCase para o Flutter |
| `status.py` | Enum / valores de status (`waiting`, `processing`, `completed`, `error`) |
| `queue.py` | `ProcessingQueue` — fila in-process e worker assíncrono |
| `processor.py` | `Processor` ABC, `FakeProcessor`, `TemplateProcessor`, `ProcessingInput` |
| `classifier.py` | `Classifier` ABC, `DisabledClassifier`, `CLIPClassifier` |
| `color_detector.py` | `ColorDetector` ABC, detectores de cor do líquido |
| `templates_catalog.py` | Dicionário `template_id` → descrição em inglês (CLIP) |
| `blender_scripts/customize_template.py` | Roda **dentro** do Blender; não importa o FastAPI |

## `CaptureService` (resumo)

- **`create_job`**: valida que há imagens; gera UUID; cria registro com status `waiting`; grava arquivos em `storage/uploads/<job_id>/`; persiste caminhos em `capture_images`; `commit`; `queue.submit(job_id)`.
- **`get_job`**: lê job + imagens (repositório).
- **`process_job`**: chama `_prepare_job` (status `processing`); tenta `classify` e `detect` (falhas não abortam o job); chama `processor.process(ProcessingInput(...))`; em sucesso marca `completed` com `model_path` público; em exceção `error` com string da falha.

## `IncomingImage`

- Dataclass com `filename` e `content: bytes` — o router lê `UploadFile` e monta a lista.

## `CaptureRepository`

- Encapsula consultas assíncronas ao banco; mantém o service sem SQL direto (exceto via ORM do repositório).

## Separação router / service

- O router **não** contém regra de negócio: só monta DTOs, lê arquivos e converte `model_path` em URL absoluta com `request.base_url` para o campo `modelUrl` no response.

## Leituras relacionadas

- [05 — Arquitetura](05-arquitetura.md)
- [09 — Pipeline 3D](09-pipeline-3d.md)
- [10 — Classificador e cor](10-classificador-e-cor.md)
- [13 — Endpoints HTTP](13-endpoints-http.md)
