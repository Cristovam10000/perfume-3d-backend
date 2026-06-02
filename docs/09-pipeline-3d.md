# 09 — Pipeline 3D (templates — fallback)

> **O que você vai aprender neste doc**
> - A interface raiz `Processor` (`process(input) -> result`) que une os três modos.
> - O `FakeProcessor` (cubo, p/ testes) e o `TemplateProcessor` (Blender + GLB pronto).
> - **Quando** o caminho de templates entra em ação hoje: fallback do Hunyuan e modo `template`.
>
> **Pré-requisitos:** [05 - Arquitetura](05-arquitetura.md). O caminho principal (IA) está em
> [09f - Pipeline integrado](09f-pipeline-integrado.md).

O caminho principal de geração é o **`IntegratedPipeline`** baseado em Hunyuan3D + pós-processamento + cache CLIP, documentado em [09f](09f-pipeline-integrado.md). Este documento descreve a **abstração raiz `Processor`** e o **`TemplateProcessor`**, que permanecem no código por dois motivos:

1. **Fallback**: quando o contêiner Hunyuan está offline ou estoura timeout, o backend ainda devolve algo plausível usando os 6 templates GLB pré-existentes em `assets/templates/normalized/`.
2. **Seed do cache**: cada template normalizado pode ser pré-cadastrado na tabela `modelos_3d_universais` como entrada inicial (decisão de produto — atualmente desativado).

## `Processor` (ABC raiz)

Toda implementação de geração 3D — fake, template, integrada IA — herda de `Processor`:

```python
class Processor(ABC):
    @abstractmethod
    async def process(self, input: ProcessingInput) -> ProcessingResult: ...
```

O `CaptureService` só conhece essa interface. Trocar entre `FakeProcessor`, `TemplateProcessor` e `IntegratedPipeline` é uma decisão de `.env` (`PIPELINE_MODE`) resolvida pela factory `build_pipeline()` em `main.py`.

## `ProcessingInput` (dataclass)

Campos usados hoje:

- `job_id`, `image_paths` (fotos salvas no disco)
- `output_path` — destino do `.glb` final (ex.: `storage/models/<uuid>.glb`)
- `template_id` — nome base do template (ex.: `feeling_rectangular_blue`); usado pelo `TemplateProcessor`. Ignorado pelo `IntegratedPipeline` e pelo `Hunyuan3DProcessor`.
- `liquid_color` — string `#RRGGBB` ou `None`; usado pelo `TemplateProcessor`. Pode ser preenchido por metadado vindo do cache; ignorado por Hunyuan.
- `label_image` — opcional; **não** é preenchido automaticamente pelo service. O `IntegratedPipeline` produz a label internamente via `LabelExtractor` e a passa para o `LabelProjector` no próprio fluxo.

## `FakeProcessor`

- Útil para desenvolvimento e testes: gera um GLB mínimo válido (cubo) via `struct` + JSON, sem dependências externas, com atraso simulado opcional.
- Ativado com `PIPELINE_MODE=fake` no `.env`.

## `TemplateProcessor` (fallback)

- Resolve `templates_dir / f"{template_id}.glb"` — usa `default_template_id` se nenhum vier no input.
- Monta linha de comando:

  `blender --background --python <customize_template.py> -- --template <path> --output <path> [--label-image <png>] [--liquid-color #HEX]`

- O subprocess roda com `subprocess.run` dentro de `asyncio.to_thread` para **não bloquear o event loop** e evitar problemas de subprocess async em alguns loops no Windows.
- Exige exit code 0 e arquivo de saída presente; senão levanta `ProcessingError` (o pipeline integrado captura e usa o template, ou o service marca o job como `error` se o `TemplateProcessor` for o caminho ativo).

### Quando o `IntegratedPipeline` chama o `TemplateProcessor`

- Hunyuan respondeu 5xx ou estourou timeout, **e** `PIPELINE_FALLBACK_TO_TEMPLATE=true` no `.env`.
- Nesse caso, o pipeline integrado:
  1. tenta uma classificação rápida pelo `templates_catalog` (descrição-de-texto antiga) se o `CLIPClassifier` ainda estiver disponível, ou cai no `default_template_id`;
  2. invoca o `TemplateProcessor` direto;
  3. pula os stages de Hunyuan / refiner / label, mas pode aplicar a label real extraída (se houver) via `LabelProjector` sobre o template.

### Quando o `TemplateProcessor` é o caminho principal

- `PIPELINE_MODE=template` no `.env`. Útil para demos offline, ambiente sem GPU, ou quando você quer testar só os scripts Blender sem subir o Docker.
- Nesse modo o fluxo é igual ao MVP anterior: classifier opcional escolhe `template_id`, detector de cor opcional define `liquid_color`, e o `TemplateProcessor` customiza o GLB.

## Script `customize_template.py` (dentro do Blender)

- Convenção de nós no GLB: `Bottle`, `Liquid` (material `water`), `Cap`, `Label` (material `LabelMaterial`); o script é tolerante a nós ausentes.
- Aplica `Base Color` no material `water` quando `--liquid-color` é passado.
- Aplica textura no `LabelMaterial` se `--label-image` existir.
- Exporta GLB com `bpy.ops.export_scene.gltf(export_format="GLB", export_apply=True)`.

## O que **não** acontece em runtime

- Não existe geração procedural completa de malha no request: os templates são **arquivos `.glb` versionados** em `assets/templates/normalized/`. Scripts como `generate_feeling_template.py` rodam **offline** (bancada) para atualizar um template.
- Não há fotogrametria (Meshroom/COLMAP) no pipeline HTTP atual — foi descartada após validação inicial; vidro e superfícies reflexivas violam a premissa de correspondência de pontos.

## Leituras relacionadas

- [09b — Pipeline IA Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md)
- [09f — Pipeline integrado (caminho principal)](09f-pipeline-integrado.md)
- [10 — Embedder CLIP e detector de cor](10-classificador-e-cor.md)
- [11 — Templates 3D](11-templates-3d.md) (origem e manutenção dos GLBs)
- Código: [`app/modules/captures/processor.py`](../app/modules/captures/processor.py), [`app/modules/captures/blender_scripts/customize_template.py`](../app/modules/captures/blender_scripts/customize_template.py)
