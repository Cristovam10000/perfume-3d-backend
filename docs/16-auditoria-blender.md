# 16 — Auditoria do papel do Blender no pipeline

> **O que você vai aprender neste doc**
> - O que cada estágio Blender **realmente** fazia em produção, medido — não o que a doc dizia.
> - Por que o refinamento de vidro entregava diferença **exatamente zero** nos jobs reais.
> - Quais componentes foram removidos em consequência, e o que ficou.
>
> **Pré-requisitos:** [09f - Pipeline integrado](09f-pipeline-integrado.md).

Este documento registra uma auditoria feita em **2026-08-02** sobre o papel do Blender no pipeline. O motivo foi uma pergunta simples — *"o modelo só de IA e o modelo IA + Blender ficam diferentes?"* — e a resposta exigiu medir em vez de ler o código.

## Método

Para cada job já processado em `storage/tmp/pipeline/<job>/`, existem lado a lado o `raw.glb` (saída direta do Hunyuan) e o `refined.glb` (após o `BlenderMeshRefiner`). Ambos foram renderizados no Blender headless com **câmera, iluminação e engine idênticas**, e comparados pixel a pixel dentro da máscara do objeto (~327 mil pixels).

Escala de referência para leitura dos números: **dois frascos completamente diferentes medem 27,3** de diferença média.

## Resultado 1 — o refinamento não produzia efeito algum

| Job | Frasco | dif. média | pixels alterados | máximo |
|---|---|---|---|---|
| `56c18283` | GRAND (tijolo) | **0,000** | 0,0% | 0,0 |
| `618189c6` | GRAND (mesa) | **0,000** | 0,0% | 0,0 |
| `e2e-teste2` | ASAD | **0,000** | 0,0% | 0,0 |
| `54dbee08` | La vivacité | **0,000** | 0,0% | 0,0 |
| `f5227743` | La vivacité (2ª) | **0,000** | 0,0% | 0,0 |
| `f34cf6e0` | Feeling Sexy | **0,000** | 0,0% | 0,0 |

Não é "quase igual" — os renders são **idênticos bit a bit**. O Blender abria o arquivo, importava ~424 mil triângulos, não alterava material nenhum e reexportava, inflando o GLB de 20,5 MB para 68,0 MB.

Confirmado no glTF do job `56c18283`:

| | `raw.glb` | `refined.glb` |
|---|---|---|
| gerador | trimesh (Hunyuan) | Khronos glTF Blender I/O v5.1.19 |
| `extensionsUsed` | `[]` | `[]` |
| roughness | 0,9036020036 | 0,9036020041 |
| tamanho | 20,5 MB | **68,0 MB** |

### Por que — três causas distintas

1. **Jobs de maio (La vivacité ×2, Feeling Sexy)** — anteriores ao classificador de transparência (commits `b2e3260` e `8cac1b7`, de 10/jun). Rodaram no modo legado `auto`, que só aplica vidro em mesh **sem** textura; a saída do Hunyuan com paint vem sempre texturizada, então `auto` é no-op por construção.
2. **ASAD (junho)** — o CLIP classificou como opaco (prob. 0,089) e o `body_mode=keep` preservou a textura. **Comportamento correto**: frasco preto fosco não deve virar vidro.
3. **GRAND ×2 (julho)** — misclassificação. Vidro âmbar escuro pontuou 0,146 e 0,072, abaixo do threshold 0,30, e recebeu `keep`.

## Resultado 2 — o classificador de transparência não é calibrável só pelo threshold

Reproduzindo o `ClipTransparencyClassifier` sobre as fotos dos 6 jobs, ordenado:

```
GRAND mesa    0,072   ← é VIDRO
ASAD          0,089   ← é OPACO (correto)
GRAND tijolo  0,146   ← é VIDRO
Feeling       0,527   ← é VIDRO
vivacité b    0,819   ← é VIDRO
vivacité a    0,825   ← é VIDRO
```

O GRAND mesa (vidro) pontua **menos** que o ASAD (opaco). As classes se sobrepõem no eixo medido, portanto **nenhum valor de threshold acerta os dois**. Baixar o corte para ~0,10 conserta o GRAND tijolo e mantém o ASAD certo, mas o GRAND mesa continua errado.

A conclusão é que o problema está nos *prompts* (o sinal), não no corte. O ensemble atual descreve vidro que "deixa o líquido visível" ou que "brilha quando a luz atravessa" — nenhuma das duas coisas é visível numa foto de frasco âmbar escuro.

## Resultado 3 — o extrator de rótulo nunca funcionou

> **Resolvido.** A detecção passou de traço de borda para região preenchida; o La vivacité agora é detectado e projetado. Ver [09e](09e-aplicacao-label.md#detecção-por-região-2026-08).

Executado sobre as **21 fotos reais** dos 6 jobs: **0 detecções**. Não é o threshold de confiança — o detector não produz candidato nenhum.

Instrumentando os filtros de `HomographyLabelExtractor`:

| Etapa | La vivacité | GRAND |
|---|---|---|
| contornos Canny | 22 | 539 |
| viraram quadrilátero | 9 | 270 |
| **passaram no filtro de área** | **0** | **0** |
| maior candidato (% da máscara) | 0,034% | 0,998% |
| faixa exigida | 5% – 60% | 5% – 60% |

Causa: os contornos vêm de um **mapa de bordas Canny dilatado**, então `contourArea` mede a área do *traço* da borda (~3 px de espessura), não a região que ela delimita. A faixa de 5–60% foi calibrada como se fossem regiões preenchidas. Baixar o mínimo não resolve — a 0,001% entrariam os 270 fragmentos aleatórios do GRAND.

Consequência: nenhum job jamais produziu `with_label.glb`, e `project_label.py` **nunca executou com entrada real**. Ele não é ruim na tarefa; ele é **não testado** nela. A distinção importa.

Quando finalmente executou, apareceram dois defeitos que só entrada real revelaria: o cluster frontal incluía tampa e adereços (decal deslocado para a borda) e o offset fixo deixava o plano atrás da barriga do frasco (decal partido em manchas). Ambos corrigidos — ver [09e](09e-aplicacao-label.md#heurística-de-face-frontal).

## Resultado 4 — decomposição do efeito de vidro

Forçando `--body-mode glass` no La vivacité e isolando cada parâmetro que o refiner altera:

| Alteração | dif. média | pixels >10 |
|---|---|---|
| Só `roughness` 0,9 → 0,05 | 6,67 | 13,0% |
| Só `transmission` 0 → 1 (+IOR) | 5,95 | 18,1% |
| Ambos (refiner completo) | 6,44 | 18,2% |
| *acréscimo da transmissão sobre o roughness* | *3,23* | *10,5%* |

O `roughness` sozinho produz praticamente todo o efeito. E `roughness` é um campo `pbrMetallicRoughness.roughnessFactor` no JSON do glTF — editável em Python puro com `trimesh` (já instalado), sem subprocess e sem reabrir a malha.

A transmissão rende pouco por dois motivos verificáveis no arquivo: o GLB declara `KHR_materials_transmission` e `KHR_materials_ior` mas **não** `KHR_materials_volume` (sem espessura, todo viewer PBR trata como película fina); e o material único faz o vidro cobrir tampa e rótulo junto — corrigido depois pela [segmentação](09h-segmentacao-corpo-tampa.md).

## Resultado 5 — o `TopProjector` era o de maior potencial, e estava desligado

> **Resolvido.** O `TopProjector` foi ligado ao pipeline como stage (7.5) — ver [09h](09h-segmentacao-corpo-tampa.md#o-estágio-no-pipeline).

Na época da auditoria o `TopProjector` não estava conectado a `main.py`, `pipeline.py` nem `config.py` — código morto, sem variável de ambiente. Executado manualmente no job `e2e-teste2` (único com foto de topo):

| Comparação | dif. média |
|---|---|
| **Projeção do topo — vista de cima** | **14,80** |
| refiner de vidro forçado | 6,44 |
| refiner em produção | 0,000 |
| *escala: dois frascos diferentes* | *27,33* |

**14,80 é 54% da diferença entre dois frascos distintos.** É o maior efeito medido de qualquer estágio Blender, e resolve um problema que a IA não resolve sozinha: a vista de cima do `refined.glb` mostrava a tampa como um **disco dourado liso, sem textura** — o Hunyuan não reconstrói o topo porque as 4 vistas cardeais não o enxergam.

## Consequências no código

### Removido

| Componente | Motivo |
|---|---|
| `mesh_cleaner.py` + `blender_scripts/cleanup_mesh.py` | Desligado no `.env`; a limpeza migrou para o servidor Hunyuan (`FloaterRemover` + `DegenerateFaceRemover`, `HUNYUAN_SHAPE_POSTPROCESS=1`). |
| `TemplateProcessor` + `blender_scripts/customize_template.py` | Caminho de templates e `PIPELINE_MODE=template`. |
| Fallback `pipeline_fallback_to_template` | Falha do Hunyuan agora levanta `ProcessingError` — o job morre em vez de mascarar. |
| `classifier.py`, `templates_catalog.py` | Existiam para escolher o `template_id` do `TemplateProcessor`. |

Total: **1.571 linhas apagadas**.

> O braço "Blander" do benchmark **não foi afetado**: `eval/benchmark.py` o executa a partir da worktree `C:\TCC_blander`, que tem cópia própria do código, e os 24 GLBs de saída já estão em `TCC_eval_data/outputs/blander/`.

### Adicionado

| Componente | Ver |
|---|---|
| `blender_scripts/segment_bottle.py` | [09h](09h-segmentacao-corpo-tampa.md) |
| `blender_scripts/top_alignment.py` | [09h](09h-segmentacao-corpo-tampa.md) |
| Stage (7.5) `TopProjector` no `IntegratedPipeline` | [09f](09f-pipeline-integrado.md) |
| Segmentação no `refine_ai_mesh.py` e no `project_view_texture.py` | [09h](09h-segmentacao-corpo-tampa.md) |
| `tests/modules/captures/test_segment_bottle.py` | [14](14-testes.md) |

### Mantido apesar de não estar ligado

| Componente | Por quê |
|---|---|
| `color_detector.py` | O refiner ainda aceita `--liquid-color`; é o plug de detecção automática, não um resto. |
| `assets/templates/normalized/*.glb` | `eval/synthetic_dataset.py` usa `feeling_rectangular_blue.glb` para gerar o dataset sintético do benchmark. |
| `scripts/blender/*.py` | Ferramentas de bancada que produziram esses assets. |
| `CLASSIFIER_TYPE` no `config.py` | Não é lida por nenhum stage; fica para não quebrar `.env` antigos. |

## Pendências identificadas

1. **Alinhamento rotacional da projeção do topo** — ver [09h](09h-segmentacao-corpo-tampa.md).
2. **Prompts do classificador de transparência** — o threshold sozinho não separa as classes.
3. **Detector de rótulo** — precisa de conjunto rotulado e troca do método (região preenchida em vez de traço de borda).
4. **`KHR_materials_volume`** — sem espessura não há refração real.
5. **Degradação silenciosa** — quando o rótulo não é encontrado, `pipeline.py` loga em INFO e segue; um estágio que nunca funcionou passou despercebido por meses. Vale subir para WARNING e expor no resultado do job quais estágios efetivamente agiram.

## Leituras relacionadas

- [09c — Refinamento de malha](09c-refinamento-mesh.md)
- [09e — Aplicação de label](09e-aplicacao-label.md)
- [09h — Segmentação corpo/tampa](09h-segmentacao-corpo-tampa.md)
