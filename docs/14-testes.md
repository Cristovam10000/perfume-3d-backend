# 14 — Testes (pytest)

Estratégia: testes de unidade e integração com **mocks** onde custo é alto (Blender, CLIP) e testes reais opt-in quando o binário existe.

## Contagem aproximada (execução `pytest` local)

A suíte está organizada em cerca de **86** funções de teste distribuídas por ficheiro (número sujeito a crescimento):

| Ficheiro | Tema aproximado | Notas |
|----------|-----------------|-------|
| `tests/test_main.py` | App FastAPI, fluxo e2e com `httpx` | Cria `create_app` com SQLite, lifespan custom |
| `tests/modules/captures/test_service.py` | `CaptureService` (job, classificador, processador) | Mocks de processor/classifier/detectors |
| `tests/modules/captures/test_router.py` | Rotas com `TestClient` | — |
| `tests/modules/captures/test_queue.py` | `ProcessingQueue` | — |
| `tests/modules/captures/test_processor.py` | `FakeProcessor` | — |
| `tests/modules/captures/test_template_processor.py` | `TemplateProcessor` | Mocks de subprocess + integração real se Blender no path |
| `tests/modules/captures/test_customize_template.py` | Script Blender de customize | Pula se sem Blender |
| `tests/modules/captures/test_classifier.py` | Classificador | Mocks; CLIP não baixa em todos os testes |
| `tests/modules/captures/test_color_detector.py` | Detector de cor | Imagens em memória / temporárias |
| `tests/assets/test_normalized_templates.py` | GLBs normalizados (magic, estrutura) | Lê ficheiros em `assets/templates/normalized/` |

## Banco de dados

- Não depende de Postgres: `conftest.py` fornece `session_factory` com **SQLite** em ficheiro temporário (`tmp_path`).

## Executar

```powershell
cd c:\TCC\back
.\.venv\Scripts\python.exe -m pytest
```

Opção verbosa: `pytest -q` (quieta) ou `pytest tests/modules/captures/test_classifier.py -v`.

## Integração Blender

- Vários testes de `TemplateProcessor` e `test_customize_template` procuram `BLENDER_EXECUTABLE` (env) ou o caminho default Windows. Se o Blender não estiver instalado, os testes realistas são **skipped** com `pytest.skip`.

## Leituras relacionadas

- [05 — Arquitetura](05-arquitetura.md) (o que é mockado e porquê)
- `pytest.ini` — `asyncio_mode = auto`
