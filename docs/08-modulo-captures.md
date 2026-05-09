# 08 — Módulo `captures`

Todo o domínio de **captura de fotos → job → modelo 3D** vive em `app/modules/captures/`. Este módulo segue o padrão *feature-first*: router, service, repository, models, schemas, fila e estratégias de pipeline.

## Arquivos e responsabilidades

### Núcleo (em uso pelo `CaptureService`)

| Arquivo | Função |
|---------|--------|
| `router.py` | `POST /captures`, `GET /captures/{id}/status` |
| `service.py` | `CaptureService`: `create_job`, `get_job`, `process_job` (worker) |
| `repository.py` | `CaptureRepository`: CRUD de job e imagens no Postgres |
| `models.py` | `CaptureJob`, `CaptureImage` (SQLAlchemy 2.0) |
| `schemas.py` | DTOs Pydantic com alias camelCase para o Flutter |
| `status.py` | Enum / valores de status (`waiting`, `processing`, `completed`, `error`) |
| `queue.py` | `ProcessingQueue` — fila in-process e worker assíncrono |
| `processor.py` | `Processor` ABC + `FakeProcessor` + `TemplateProcessor` + `Hunyuan3DProcessor` + `ProcessingInput` |
| `classifier.py` | `Classifier` ABC + `DisabledClassifier` + `CLIPClassifier` |
| `color_detector.py` | `ColorDetector` ABC + `DisabledColorDetector` + `AverageColorDetector` |
| `templates_catalog.py` | Dicionário `template_id` → descrição em inglês (CLIP) |
| `blender_scripts/customize_template.py` | Roda **dentro** do Blender — customiza template paramétrico |

### Pipeline IA — componentes standalone (Fases 1–5)

Implementados como ABCs Strategy com bypass `Disabled*`. Hoje são exercitados via smokes manuais (`scripts/smoke_phase{3,4,5}.py`); a integração no `CaptureService.process_job` é deferida para a Fase 7.

| Arquivo | Função | Doc dedicada |
|---------|--------|--------------|
| `background_remover.py` | `BackgroundRemover` ABC + `Disabled*` + `RembgBackgroundRemover` | [10b](10b-segmentacao-e-label.md) |
| `label_extractor.py` | `LabelExtractor` ABC + `Disabled*` + `HomographyLabelExtractor` (OpenCV) | [10b](10b-segmentacao-e-label.md) |
| `image_preprocessor.py` | `ImagePreprocessor` ABC + `Disabled*` + `StandardImagePreprocessor` (EXIF, gray-world, CLAHE, sharpen condicional, resize) | [09d](09d-preprocessamento-e-cleanup.md) |
| `mesh_cleaner.py` | `MeshCleaner` ABC + `Disabled*` + `BlenderMeshCleaner` (loose parts → bbox volume → fill_holes 4 → normais → smooth) | [09d](09d-preprocessamento-e-cleanup.md) |
| `mesh_refiner.py` | `MeshRefiner` ABC + `Disabled*` + `BlenderMeshRefiner` (shader de vidro PBR) | [09c](09c-refinamento-mesh.md) |
| `label_upscaler.py` | `LabelUpscaler` ABC + `Disabled*` + `LanczosLabelUpscaler` (Pillow) | [09e](09e-aplicacao-label.md) |
| `label_projector.py` | `LabelProjector` ABC + `Disabled*` + `BlenderLabelProjector` (decal frontal) | [09e](09e-aplicacao-label.md) |
| `blender_scripts/refine_ai_mesh.py` | Script Blender — Fase 3 | [09c](09c-refinamento-mesh.md) |
| `blender_scripts/cleanup_mesh.py` | Script Blender — Fase 4 | [09d](09d-preprocessamento-e-cleanup.md) |
| `blender_scripts/project_label.py` | Script Blender — Fase 5 | [09e](09e-aplicacao-label.md) |

> **Convenção comum** dos três scripts Blender da trilha IA: emitem `STATS:<chave1>=<v1>,<chave2>=<v2>,...` em uma única linha de stdout para parsing tolerante por regex no wrapper Python.

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
- [09 — Pipeline 3D (templates)](09-pipeline-3d.md)
- [09b — Pipeline IA Hunyuan](09b-pipeline-ai-hunyuan.md)
- [09c — Refinamento de malha](09c-refinamento-mesh.md)
- [09d — Pré-processamento e cleanup](09d-preprocessamento-e-cleanup.md)
- [09e — Aplicação de label](09e-aplicacao-label.md)
- [10 — Classificador e cor](10-classificador-e-cor.md)
- [10b — Segmentação e label](10b-segmentacao-e-label.md)
- [13 — Endpoints HTTP](13-endpoints-http.md)
