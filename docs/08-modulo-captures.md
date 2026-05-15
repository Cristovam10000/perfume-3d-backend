# 08 — Módulo `captures`

Todo o domínio de **captura de fotos → job → modelo 3D** vive em `app/modules/captures/`. Este módulo segue o padrão *feature-first*: router, service, repository, models, schemas, fila, pipeline integrado e estratégias por stage.

## Arquivos e responsabilidades

### Núcleo (orquestração do job)

| Arquivo | Função |
|---------|--------|
| `router.py` | `POST /captures`, `GET /captures/{id}/status` |
| `service.py` | `CaptureService`: `create_job`, `get_job`, `process_job` (worker) |
| `repository.py` | `CaptureRepository`: CRUD de job e imagens no Postgres |
| `models.py` | `CaptureJob`, `CaptureImage` (SQLAlchemy 2.0) |
| `schemas.py` | DTOs Pydantic com alias camelCase para o Flutter |
| `status.py` | Enum / valores de status (`waiting`, `processing`, `completed`, `error`) |
| `queue.py` | `ProcessingQueue` — fila in-process e worker assíncrono |

### Pipeline 3D (composição e processors raiz)

| Arquivo | Função | Doc dedicada |
|---------|--------|--------------|
| `pipeline.py` | `IntegratedPipeline`: compõe os stages (preprocess → rembg → cache → hunyuan → cleaner → refiner → label → store) | [09f](09f-pipeline-integrado.md) |
| `processor.py` | `Processor` ABC + `FakeProcessor` + `TemplateProcessor` + `Hunyuan3DProcessor` | [09](09-pipeline-3d.md), [09b](09b-pipeline-ai-hunyuan.md) |
| `blender_scripts/customize_template.py` | Roda dentro do Blender — customiza template paramétrico (fallback) | [09](09-pipeline-3d.md) |

### Cache de modelos (similaridade CLIP)

| Arquivo | Função | Doc dedicada |
|---------|--------|--------------|
| `embeddings.py` | `ImageEmbedder` ABC + `DisabledEmbedder` + `ClipImageEmbedder` (mean-pool de embeddings CLIP por job) | [10](10-classificador-e-cor.md) |
| `cache.py` | `ModelCache` ABC + `DisabledModelCache` + `ClipSimilarityCache` (lookup cosine + store) | [09g](09g-cache-similaridade-clip.md) |
| `modelos_universais.py` | `ModeloUniversal` SQLAlchemy: tabela `modelos_3d_universais` (id uuid, caminho_arquivo_modelo, embedding bytes, source_job_id, hit_count, ultimo_hit_em). Cache **global**, sem FK direta para produtos — vínculo com `produtos` acontece via `modelos_3d_produto.modelo_universal_id`. | [09g](09g-cache-similaridade-clip.md), [12](12-armazenamento-e-banco.md) |

### Stages do pipeline IA (ABCs Strategy)

Cada stage tem um bypass `Disabled*` (zero deps, útil para testes) e uma implementação real (configurável via `.env`).

| Arquivo | Função | Doc dedicada |
|---------|--------|--------------|
| `image_preprocessor.py` | `ImagePreprocessor` ABC + `StandardImagePreprocessor` (EXIF, gray-world, CLAHE, sharpen condicional, resize ≤2048) | [09d](09d-preprocessamento-e-cleanup.md) |
| `background_remover.py` | `BackgroundRemover` ABC + `RembgBackgroundRemover` (modelo `isnet-general-use`) | [10b](10b-segmentacao-e-label.md) |
| `mesh_cleaner.py` | `MeshCleaner` ABC + `BlenderMeshCleaner` (loose parts → bbox volume → fill_holes 4 → normais → smooth; default `min_island_ratio=0`) | [09d](09d-preprocessamento-e-cleanup.md) |
| `mesh_refiner.py` | `MeshRefiner` ABC + `BlenderMeshRefiner` (shader de vidro PBR no corpo do frasco) | [09c](09c-refinamento-mesh.md) |
| `label_extractor.py` | `LabelExtractor` ABC + `HomographyLabelExtractor` (OpenCV: Canny + approxPolyDP + warpPerspective) | [10b](10b-segmentacao-e-label.md) |
| `label_upscaler.py` | `LabelUpscaler` ABC + `LanczosLabelUpscaler` (Pillow LANCZOS, default 2048 px) | [09e](09e-aplicacao-label.md) |
| `label_projector.py` | `LabelProjector` ABC + `BlenderLabelProjector` (decal frontal via UV planar) | [09e](09e-aplicacao-label.md) |
| `top_projector.py` | `TopProjector` ABC + `BlenderTopProjector` (textura da tampa via foto do topo — opcional) | (sem doc dedicada) |
| `blender_scripts/cleanup_mesh.py` | Script Blender — limpeza conservadora | [09d](09d-preprocessamento-e-cleanup.md) |
| `blender_scripts/refine_ai_mesh.py` | Script Blender — shader de vidro PBR | [09c](09c-refinamento-mesh.md) |
| `blender_scripts/project_label.py` | Script Blender — decal de label | [09e](09e-aplicacao-label.md) |
| `blender_scripts/project_top_texture.py` | Script Blender — textura da tampa | (sem doc dedicada) |

### Histórico / fallback

| Arquivo | Estado |
|---------|--------|
| `classifier.py` (`CLIPClassifier`) | **Deprecado**. Lógica de zero-shot por descrição em inglês foi substituída pelo `ClipImageEmbedder` em `embeddings.py`. O arquivo é mantido para referência. |
| `color_detector.py` (`AverageColorDetector`) | **Deprecado** do fluxo principal. O Hunyuan infere cor das fotos. Pode ser ativado se você quiser persistir cor como metadado. |
| `templates_catalog.py` | **Apenas seed/fallback**. Mantém o dicionário `template_id → descrição` para o `TemplateProcessor` (fallback quando o Hunyuan está offline). |

> **Convenção comum** dos scripts Blender da trilha IA: emitem `STATS:<chave1>=<v1>,<chave2>=<v2>,...` em uma única linha de stdout para parsing tolerante por regex no wrapper Python.

## `CaptureService` (resumo)

- **`create_job`**: valida que há imagens; gera UUID; cria registro com status `waiting`; grava arquivos em `storage/uploads/<job_id>/`; persiste caminhos em `capture_images`; `commit`; `queue.submit(job_id)`.
- **`get_job`**: lê job + imagens (repositório).
- **`process_job`**: chama `_prepare_job` (status `processing`); delega para `self._pipeline.process(ProcessingInput(...))`; em sucesso marca `completed` com `model_path` público (e propaga `origem` cache/generated para o `message`); em exceção marca `error` com string da falha.

A diferença em relação a versões anteriores: o service **deixou de orquestrar classifier + color detector + processor diretamente**. Toda essa coreografia (incluindo cache, fallback, degrade) está dentro do `IntegratedPipeline`. O service permanece magro: persistência + status + delegar.

## `IncomingImage`

- Dataclass com `filename` e `content: bytes` — o router lê `UploadFile` e monta a lista.

## `CaptureRepository`

- Encapsula consultas assíncronas ao banco; mantém o service sem SQL direto (exceto via ORM do repositório).
- Não conhece a tabela `modelos_3d_universais` — essa é responsabilidade do `ClipSimilarityCache` (em `cache.py`).

## Separação router / service / pipeline

- O **router** só monta DTOs, lê arquivos e converte `model_path` em URL absoluta com `request.base_url` para o campo `modelUrl` no response.
- O **service** orquestra job (criação, status, queue) e delega a geração ao pipeline.
- O **pipeline** sabe da composição de stages e do cache; é o único que conhece os componentes da trilha IA.

## Leituras relacionadas

- [05 — Arquitetura](05-arquitetura.md)
- [09 — Pipeline 3D (templates — fallback)](09-pipeline-3d.md)
- [09b — Pipeline IA Hunyuan](09b-pipeline-ai-hunyuan.md)
- [09c — Refinamento de malha](09c-refinamento-mesh.md)
- [09d — Pré-processamento e cleanup](09d-preprocessamento-e-cleanup.md)
- [09e — Aplicação de label](09e-aplicacao-label.md)
- [09f — Pipeline integrado](09f-pipeline-integrado.md)
- [09g — Cache de similaridade CLIP](09g-cache-similaridade-clip.md)
- [10 — Embedder CLIP e detector de cor](10-classificador-e-cor.md)
- [10b — Segmentação e label](10b-segmentacao-e-label.md)
- [13 — Endpoints HTTP](13-endpoints-http.md)
