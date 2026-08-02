# 09 — Pipeline 3D (abstração raiz `Processor`)

> **O que você vai aprender neste doc**
> - A interface raiz `Processor` (`process(input) -> result`) que une os modos de geração.
> - O `FakeProcessor` (cubo, p/ testes) e quando usá-lo.
> - Por que o caminho de templates **deixou de existir** e o que substituiu cada função dele.
>
> **Pré-requisitos:** [05 - Arquitetura](05-arquitetura.md). O caminho principal (IA) está em
> [09f - Pipeline integrado](09f-pipeline-integrado.md).

O único caminho de geração é o **`IntegratedPipeline`**, baseado em Hunyuan3D + pós-processamento + cache CLIP, documentado em [09f](09f-pipeline-integrado.md). Este documento descreve a **abstração raiz `Processor`** e o `FakeProcessor`.

## `Processor` (ABC raiz)

Toda implementação de geração 3D herda de `Processor`:

```python
class Processor(ABC):
    @abstractmethod
    async def process(self, input: ProcessingInput) -> ProcessingResult: ...
```

O `CaptureService` só conhece essa interface. Trocar entre `FakeProcessor` e `IntegratedPipeline` é uma decisão de `.env` (`PIPELINE_MODE`) resolvida pela factory `build_pipeline()` em `main.py`.

```python
PIPELINE_MODE = "fake" | "integrated"   # Literal validado pelo pydantic
```

## `ProcessingInput` (dataclass)

Campos usados hoje:

- `job_id`, `image_paths` (fotos salvas no disco)
- `output_path` — destino do `.glb` final (ex.: `storage/models/<uuid>.glb`)
- `product_id` — opcional; vincula o molde universal a um produto do tenant
- `liquid_color` — string `#RRGGBB` ou `None`; repassado ao `MeshRefiner` como `--liquid-color`
- `views` — rótulos de vista enviados pelo app (`front`/`left`/`back`/`right`/`extra`); consumidos pelo `LabeledViewRouter`
- `label_image` — opcional; **não** é preenchido automaticamente pelo service. O `IntegratedPipeline` produz a label internamente via `LabelExtractor` e a passa para o `LabelProjector` no próprio fluxo.

> `template_id` foi removido junto com o `TemplateProcessor`.

## `FakeProcessor`

- Útil para desenvolvimento e testes: gera um GLB mínimo válido (cubo) via `struct` + JSON, sem dependências externas, com atraso simulado opcional.
- Ativado com `PIPELINE_MODE=fake` no `.env`.
- É o único modo que roda sem Docker, sem GPU e sem Blender.

## `Hunyuan3DProcessor`

Cliente HTTP para o serviço em contêiner. Documentado em [09b](09b-pipeline-ai-hunyuan.md). Não importa `torch` nem `transformers` — toda a inferência acontece no contêiner.

## O caminho de templates (removido em 2026-08)

Até julho de 2026 existiam um `TemplateProcessor` e um `PIPELINE_MODE=template` que customizavam um GLB pré-existente de `assets/templates/normalized/` via Blender headless. Serviam a dois propósitos, ambos hoje resolvidos de outra forma:

| Propósito antigo | Situação atual |
|---|---|
| **Fallback** quando o Hunyuan estava offline | Removido. Falha do Hunyuan levanta `ProcessingError` e o job é marcado como `error`. Mascarar a falha poluía a medição do pipeline de IA. |
| **Seed do cache** com templates pré-cadastrados | Nunca foi ativado em produção (decisão de produto). |

Removidos: a classe `TemplateProcessor`, o script `customize_template.py`, o `classifier.py` (escolhia o `template_id`), o `templates_catalog.py` e as chaves `PIPELINE_FALLBACK_TO_TEMPLATE`, `TEMPLATES_DIR` e `DEFAULT_TEMPLATE_ID`. A motivação e as medições estão em [16 - Auditoria do Blender](16-auditoria-blender.md).

**Os GLBs de `assets/templates/` continuam versionados** — ver [11 - Templates 3D](11-templates-3d.md) — porque `eval/synthetic_dataset.py` os usa como referência para gerar o dataset sintético do benchmark.

O braço **"Blander"** do benchmark comparativo não foi afetado: ele roda a partir da worktree `C:\TCC_blander`, que mantém cópia própria do código.

## O que **não** acontece em runtime

- Não há fotogrametria (Meshroom/COLMAP) no pipeline HTTP — foi descartada após validação inicial; vidro e superfícies reflexivas violam a premissa de correspondência de pontos.
- Não há geração procedural de malha no request.

## Leituras relacionadas

- [09b — Pipeline IA Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md)
- [09f — Pipeline integrado (caminho principal)](09f-pipeline-integrado.md)
- [11 — Templates 3D](11-templates-3d.md) (origem e manutenção dos GLBs, hoje usados só pelo eval)
- [16 — Auditoria do papel do Blender](16-auditoria-blender.md)
- Código: [`app/modules/captures/processor.py`](../app/modules/captures/processor.py)
