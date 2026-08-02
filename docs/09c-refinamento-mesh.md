# 09c — Refinamento de Malha: Shader de Vidro PBR

> **O que você vai aprender neste doc**
> - Por que o Hunyuan pinta vidro como superfície opaca — e como o refiner conserta isso.
> - Como o pipeline decide **se** o frasco é de vidro (CLIP zero-shot sobre as fotos) e os três `body modes` do refiner.
> - Os parâmetros do shader de vidro PBR (`IOR`, `Transmission`, `Roughness`) e o porquê de cada valor.
>
> **Pré-requisitos:** [09f - Pipeline integrado](09f-pipeline-integrado.md). É o stage (6) do pipeline.
> **Glossário:** PBR, shader, IOR — ver [15](15-glossario.md).

Pós-processador do `IntegratedPipeline` que melhora visualmente os GLBs gerados pelo `Hunyuan3DProcessor`, aplicando **vidro fisicamente correto** ao corpo do frasco **quando o frasco fotografado é transparente**. Funciona como stage `(6)` na cadeia integrada (ver [09f](09f-pipeline-integrado.md)).

## O problema visual

O Hunyuan3D-2mv produz GLBs onde o "vidro" do frasco é um material **opaco azulado** — a IA interpreta as reflexões do ambiente como cor de superfície, pintando-as como textura.

O resultado bruto tem três características:

1. **Corpo opaco**: o vidro transparente vira uma superfície sólida com aparência plástica.
2. **Label boa**: a textura da label aplicada pela IA geralmente está usável (mas é substituída pelo decal real no stage seguinte — ver [09e](09e-aplicacao-label.md)).
3. **Tampa variável**: pode vir fundida ao corpo ou razoavelmente separada, dependendo do ângulo das fotos.

Importante: nem todo frasco É de vidro transparente. Frascos opacos (ex.: Lattafa Asad, preto fosco com dourado) ficam **corretos** com a textura pintada pela IA — aplicar vidro neles pioraria. Por isso o refinamento é condicionado ao `TransparencyClassifier` (abaixo).

## Visão geral

```
fotos preprocessadas ──► TransparencyClassifier (CLIP zero-shot)
                              │ transparente? True/False/None
                              ▼
                         body_mode: glass | keep | auto
                              │
GLB do estágio anterior (cleaned.glb)
    └── BlenderMeshRefiner ◄──┘
            │  subprocess Blender headless
            │  refine_ai_mesh.py --body-mode <modo>
            │
            ├── glass: vidro PBR no corpo (preserva textura como tinte)
            ├── keep:  materiais intactos (frasco opaco)
            ├── auto:  heurística legada (vidro só em corpo SEM textura)
            ├── detectar_tampa()  → best-effort por posição Z
            └── exportar GLB refinado
            ▼
    refined.glb
```

## TransparencyClassifier: o frasco é de vidro?

Componente `app/modules/captures/transparency_classifier.py`, decidido **pelas fotos**, não pela malha. Usa o mesmo CLIP ViT-B/32 do cache/view-router em zero-shot, com ensemble de 4 prompts (2 descrevendo vidro claro/tintado, 2 descrevendo superfícies opacas). A probabilidade "transparente" de cada foto é a soma do softmax das duas classes de vidro; a média entre as fotos do job é comparada com `TRANSPARENCY_THRESHOLD`.

Calibração em fotos reais (CLIP ViT-B/32):

| Conjunto | Material real | Prob. média |
|---|---|---|
| Hinode Empire Sport | vidro azul translúcido (caso difícil) | 0.41–0.49 |
| Lattafa Asad | opaco preto fosco | ≤ 0.10 |

O default `TRANSPARENCY_THRESHOLD=0.30` separa os dois com margem; vidro claro clássico pontua bem acima. O veredito vira o `body_mode` do refiner:

| Veredito | `body_mode` | Efeito no corpo |
|---|---|---|
| transparente | `glass` | vidro PBR (textura preservada como tinte) |
| opaco | `keep` | materiais intactos |
| desconhecido (`disabled`/falha) | `auto` | heurística legada |

## Como o corpo é identificado

No modo `glass` (e `auto`), o script tenta primeiro a heurística legada:

1. **Filtra texturizados**: descarta meshes cujo material tem `Image Texture → Base Color`.
2. **Maior área**: dos candidatos restantes, seleciona o de maior área de superfície total.

**Na prática, saídas reais do Hunyuan com paint pipeline vêm como um único mesh 100% texturizado** (`geometry_0`/`Material_0` com `TEX_IMAGE` no Base Color), então a heurística legada não encontra candidato. Nesse caso:

- `auto`: exporta o GLB inalterado (comportamento legado — era o que acontecia em 100% dos jobs antes do classificador).
- `glass`: cai para `identificar_corpo_texturizado()` — o maior mesh **com** material — e aplica `aplicar_vidro_preservando_textura()`: seta `Transmission=1`, `IOR=1.45`, `Roughness=0.05` no Principled BSDF existente **sem desconectar a textura**, que passa a atuar como tinte do vidro (o azulado pintado pela IA vira cor do vidro). `Alpha` fica em 1.0 — a transparência vem da transmissão (`KHR_materials_transmission` + `KHR_materials_ior` no glTF exportado; o `model_viewer_plus` do front suporta ambas), não de alpha blend, que somado à transmissão dobraria a transparência.

### Segmentação corpo/tampa (desde 2026-08)

Antes de aplicar a transmissão, o modo `glass` chama `segmentar_corpo()`, que usa a heurística de [`segment_bottle.py`](../app/modules/captures/blender_scripts/segment_bottle.py) para separar o mesh em dois slots de material — `[0]` corpo, `[1]` tampa — pelo **pico de densidade de faces** no ombro do frasco. O vidro é então aplicado **apenas ao material do corpo**.

Sem isso, o mesh único do Hunyuan fazia a transmissão cobrir tampa, rótulo e líquido junto. Resultado no glTF exportado:

```
mat[0] Material_0        → transmission=1, IOR=1.45, roughness=0.05   (corpo)
mat[1] Material_0_Tampa  → roughness=0.9036, sem transmission          (tampa)
```

Quando o ombro não é identificado (razão de pico abaixo de 1,5), o script **cai no comportamento anterior** — material único para o frasco inteiro — em vez de falhar. Detalhes da calibração e das alternativas descartadas em [09h](09h-segmentacao-corpo-tampa.md).

## Parâmetros do shader de vidro

| Parâmetro | Valor | Justificativa |
|---|---|---|
| `IOR` | 1.45 | Índice de refração do vidro boro-silicato comum em perfumaria. |
| `Transmission Weight` | 1.0 | Transmissão total — frasco é transparente ao raio de luz. |
| `Roughness` | 0.05 | Vidro polido; valor > 0.1 produz aparência de vidro fosco. |
| `Base Color` | branco (corpo sem textura) ou textura preservada (tinte) | No caminho legado, cor vem do líquido/ambiente; no caminho texturizado, a textura tinge o vidro. |
| `Alpha` | 0.3 (legado) / 1.0 (texturizado) | No caminho texturizado a transparência vem só da transmissão — alpha < 1 somado a transmission dobraria o efeito em viewers PBR. |
| `Metallic` | 0.0 (texturizado) | Metallic > 0 anula transmissão no glTF; zerado por segurança. |

## Tampa (best-effort)

A tampa é identificada como o mesh sem textura de maior coordenada Z após a importação do glTF (que converte Y-up → Z-up no Blender). Só aplica o shader de plástico escuro se:

- O objeto está claramente acima do corpo (diferença Z > 20% da altura da bounding box).
- O material não tem textura (preserva tampas texturizadas intactas).

Se a heurística for inconclusiva, o mesh é ignorado sem erro.

## Limitações

- **Geometria não é alterada**: apenas materiais são substituídos. Imperfeições na malha (faces duplas, tampa fundida ao corpo) persistem após o refinamento. Limpeza geométrica é responsabilidade do pós-processamento no servidor Hunyuan (ver [09d](09d-preprocessamento-e-cleanup.md)).
- ~~**Vidro no mesh inteiro**~~: **resolvido** pela segmentação corpo/tampa — ver seção acima e [09h](09h-segmentacao-corpo-tampa.md).
- **Rótulo ainda recebe vidro**: a segmentação separa corpo de tampa, mas o rótulo fica **no corpo**. Aplicar transmissão ao corpo torna o rótulo translúcido junto. Separar o rótulo exigiria segmentação por região de textura, não por altura.
- **Cap detection fraca**: em frascos com tampa integrada ou muito próxima ao corpo, a heurística de posição Z não é conclusiva e a tampa é ignorada (em GLBs de mesh único nem chega a rodar).
- **Classificador zero-shot mal calibrado para vidro escuro**: medido nos 6 jobs reais, o GRAND (vidro âmbar) pontuou 0,146 e 0,072 — **abaixo** do ASAD opaco (0,089). As classes se sobrepõem, então nenhum valor de `TRANSPARENCY_THRESHOLD` acerta os dois. O problema está nos prompts, não no corte. Ver [16](16-auditoria-blender.md).
- **Sem `KHR_materials_volume`**: o GLB exporta transmissão e IOR mas não espessura, então viewers PBR renderizam película fina, sem refração com profundidade. Medido: a transmissão acrescenta apenas 3,2 sobre o efeito do `roughness`.
- **Dependência do Blender**: requer Blender 5.1+ instalado na mesma máquina que o backend. Use a variável `BLENDER_EXECUTABLE` para apontar para a instalação correta.
- **Idempotência**: rodar o refinador duas vezes no mesmo GLB produz o mesmo resultado — tanto o caminho legado (recria a árvore de nós) quanto o texturizado (seta os mesmos valores no BSDF existente).

## Encaixe no `IntegratedPipeline`

| Posição | Entrada | Saída | Falha |
|---|---|---|---|
| Stage (6) | `raw.glb` (do Hunyuan) | `refined.glb` | Degrade: pipeline mantém `raw.glb` como entrada do stage (7) e loga warning. Não derruba o job. |

`liquid_color` pode ser passado para o refiner (`--liquid-color`) se o pipeline tiver essa informação (vindo do cache ou do `AverageColorDetector` se ele estiver ativo). Sem cor, o material `water` mantém o default do template/mesh.

## Uso manual (smoke test)

```bash
# Com qualquer GLB como entrada (ex: template normalizado como stand-in):
blender --background --python app/modules/captures/blender_scripts/refine_ai_mesh.py -- \
    --input assets/templates/normalized/rectangular_basic.glb \
    --output /tmp/refined.glb

# Forçando vidro em saída texturizada do Hunyuan (frasco transparente):
blender --background --python app/modules/captures/blender_scripts/refine_ai_mesh.py -- \
    --input raw_hunyuan_output.glb \
    --output refined.glb \
    --body-mode glass

# Frasco opaco (preserva materiais):
blender --background --python app/modules/captures/blender_scripts/refine_ai_mesh.py -- \
    --input raw_hunyuan_output.glb \
    --output refined.glb \
    --body-mode keep

# Com cor de líquido:
blender --background --python app/modules/captures/blender_scripts/refine_ai_mesh.py -- \
    --input raw_hunyuan_output.glb \
    --output refined.glb \
    --liquid-color "#4466AA"
```

## Visualização comparativa

O script `scripts/blender/preview_refinement.py` renderiza antes e depois lado a lado:

```bash
blender --background --python scripts/blender/preview_refinement.py -- \
    --before raw_hunyuan_output.glb \
    --after  refined.glb \
    --output comparison_before_after.png
```

Útil para slides de defesa do TCC.

## Leituras relacionadas

- [09b — Pipeline IA: Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md) (stage anterior — gera o GLB cru)
- [09d — Pré-processamento e cleanup](09d-preprocessamento-e-cleanup.md) (stage 5 — `cleaned.glb`)
- [09e — Aplicação de label](09e-aplicacao-label.md) (stage 7 — `with_label.glb`)
- [09f — Pipeline integrado](09f-pipeline-integrado.md) (composição completa)
- [09 — Pipeline 3D — templates (fallback)](09-pipeline-3d.md)
- Código: [`app/modules/captures/mesh_refiner.py`](../app/modules/captures/mesh_refiner.py),
  [`app/modules/captures/transparency_classifier.py`](../app/modules/captures/transparency_classifier.py)
- Script Blender: [`app/modules/captures/blender_scripts/refine_ai_mesh.py`](../app/modules/captures/blender_scripts/refine_ai_mesh.py)
- Preview comparativo: [`scripts/blender/preview_refinement.py`](../scripts/blender/preview_refinement.py)
