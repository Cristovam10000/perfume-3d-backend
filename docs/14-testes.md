# 14 — Testes (pytest)

> **O que você vai aprender neste doc**
> - A estratégia de teste: mockar o que é caro (Blender, CLIP, Hunyuan) e ter testes
>   reais *opt-in* quando o binário/serviço existe.
> - Por que a suíte **não precisa de Postgres** (usa SQLite em arquivo temporário).
> - O padrão de **skip condicional** (`importorskip` / guard de Blender) que deixa a
>   suíte verde em qualquer máquina.
>
> **Pré-requisitos:** [04 - Estrutura de pastas](04-estrutura-de-pastas.md) (árvore de `tests/`).

Estratégia: testes de unidade e integração com **mocks** onde custo é alto (Blender, CLIP) e testes reais opt-in quando o binário existe.

## Contagem atual

A suíte tem **285 funções de teste** distribuídas em 24 ficheiros (`pytest --collect-only`, 2026-05-28). Na prática, vários são **pulados** (não falham) quando dependências externas faltam — Blender, `rembg`, CLIP (`torch`/`transformers`) ou o contêiner Hunyuan. Nenhum teste exige Postgres.

### Núcleo (Fase 2 — templates + CLIP + cor)

| Ficheiro | Tema | Notas |
|----------|------|-------|
| `tests/test_main.py` | App FastAPI, fluxo e2e com `httpx` | Cria `create_app` com SQLite, lifespan custom |
| `tests/modules/captures/test_service.py` | `CaptureService` (job, classificador, processador) | Mocks de processor/classifier/detectors |
| `tests/modules/captures/test_router.py` | Rotas com `TestClient` | — |
| `tests/modules/captures/test_queue.py` | `ProcessingQueue` | — |
| `tests/modules/captures/test_processor.py` | `FakeProcessor` + `TemplateProcessor` + `Hunyuan3DProcessor` (com `_FakeTransport`) | cliente HTTP do Hunyuan testado sem container |
| `tests/modules/captures/test_template_processor.py` | `TemplateProcessor` | Mocks de subprocess + integração real se Blender no path |
| `tests/modules/captures/test_customize_template.py` | Script Blender de customize | Pula se sem Blender |
| `tests/modules/captures/test_classifier.py` | Classificador CLIP | Mocks de `transformers`; sem download em CI |
| `tests/modules/captures/test_color_detector.py` | `AverageColorDetector` | Imagens em memória / temporárias |
| `tests/assets/test_normalized_templates.py` | GLBs normalizados (magic, estrutura, nodes obrigatórios) | Parametrizado nos 6 templates em `assets/templates/normalized/` |

### Pipeline IA — Fases 1, 3, 4, 5

| Ficheiro | Tema | Skip se… |
|----------|------|----------|
| `tests/modules/captures/test_background_remover.py` | `RembgBackgroundRemover` | `rembg` não instalado |
| `tests/modules/captures/test_label_extractor.py` | `HomographyLabelExtractor` + `_ordenar_cantos` | `cv2` não instalado |
| `tests/modules/captures/test_image_preprocessor.py` | `StandardImagePreprocessor` (EXIF, WB, CLAHE, sharpen, resize, JPEG quality) | `cv2`/`PIL` ausente |
| `tests/modules/captures/test_mesh_cleaner.py` | `BlenderMeshCleaner` mocked + integração Blender | Blender ausente |
| `tests/modules/captures/test_mesh_refiner.py` | `BlenderMeshRefiner` mocked + integração Blender | Blender ausente |
| `tests/modules/captures/test_label_upscaler.py` | `LanczosLabelUpscaler` | Pillow ausente |
| `tests/modules/captures/test_label_projector.py` | `BlenderLabelProjector` mocked + integração | Blender ausente |
| `tests/integration/test_hunyuan_real.py` | exercita `POST /generate` real | Contêiner offline |

### Cache CLIP e pipeline integrado

| Ficheiro | Tema | Skip se… |
|----------|------|----------|
| `tests/modules/captures/test_embeddings.py` | `ClipImageEmbedder` (embedder do cache) | `torch`/`transformers` ausente |
| `tests/modules/captures/test_cache.py` | `ClipSimilarityCache` (lookup/store, threshold de similaridade) | — |
| `tests/modules/captures/test_pipeline.py` | `IntegratedPipeline` (composição dos stages, degradação graciosa) | — |
| `tests/modules/captures/test_view_router.py` | `Labeled`/`CLIP`/`PositionalViewRouter` (rotulagem de vistas) | CLIP opcional em parte dos casos |

### Suíte de avaliação — `tests/eval/` (52 testes)

| Ficheiro | Tema | Skip se… |
|----------|------|----------|
| `tests/eval/test_geometric.py` | métricas Chamfer/Hausdorff/F-Score (cubo/esfera sintéticos) | — |
| `tests/eval/test_held_out_dataset.py` | loader + validador do `manifest.json` do held-out | — |
| `tests/eval/test_synthetic_dataset.py` | wrapper de render Blender (subprocess mockado) | Blender p/ integração real |

Cobrem a suíte de benchmark em [`back/eval/`](../eval/) — ver [eval/README.md](../eval/README.md).

> **Ausentes**: o módulo `sales/` ainda não tem cobertura automatizada. Validação manual via app Flutter contra Postgres real.

## Banco de dados

- Não depende de Postgres: `conftest.py` fornece `session_factory` com **SQLite** em ficheiro temporário (`tmp_path`).

## Executar

```powershell
cd c:\TCC\back
.\.venv\Scripts\python.exe -m pytest
```

- `pytest -q` (quieto) — visão compacta.
- `pytest -m "not slow"` — pula testes marcados como lentos (Hunyuan integration, integrações Blender longas).
- `pytest tests/modules/captures/test_image_preprocessor.py -v` — alvo específico.

## Skips condicionais (`importorskip` e guards)

Convenção do pipeline IA: cada módulo Python e cada teste fazem **lazy import**. Os testes que dependem de uma lib pesada chamam `pytest.importorskip("rembg")` (ou `cv2`, `PIL`) no início. Os testes que dependem do Blender real verificam:

```python
blender = Path(os.environ.get("BLENDER_EXECUTABLE", str(DEFAULT_BLENDER)))
if not blender.exists():
    pytest.skip(f"Blender não encontrado em {blender}")
```

Resultado prático: a suíte roda em qualquer máquina (com ou sem GPU/Blender/Hunyuan), com testes pulados em vez de falhos quando dependências externas faltam.

## Leituras relacionadas

- [05 — Arquitetura](05-arquitetura.md) (o que é mockado e porquê)
- `pytest.ini` — `asyncio_mode = auto`
