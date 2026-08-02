# 09h — Segmentação corpo/tampa

> **O que você vai aprender neste doc**
> - Por que um GLB do Hunyuan **não pode** receber alterações de material sem segmentação prévia.
> - Qual sinal geométrico separa corpo e tampa, e por que os dois candidatos óbvios (raio e cor) foram descartados **por medição**.
> - Onde a segmentação é usada hoje: refinamento de vidro e projeção da textura do topo.
> - O que ainda não funciona (alinhamento rotacional) e por quê.
>
> **Pré-requisitos:** [09c - Refinamento de malha](09c-refinamento-mesh.md) e [09f - Pipeline integrado](09f-pipeline-integrado.md).

## O problema

O Hunyuan3D-2mv entrega **um mesh com um único material**. Verificado nos GLBs reais do projeto:

```
meshes=1  materiais=1  texturas=1  imagens=1
```

Consequência prática: qualquer alteração de material atinge o frasco inteiro. Aplicar `KHR_materials_transmission=1` para simular vidro torna transparentes também a tampa, o rótulo e o líquido — fisicamente errado, e visualmente o efeito se dilui.

O mesmo vale para a projeção da textura do topo: sem saber onde a tampa começa, o script coleta **toda** face voltada para cima do frasco (incluindo ombro e ressaltos do corpo) e a projeção ortográfica acaba usando a bounding box XY do frasco inteiro.

A malha também não ajuda: depois de fundir duplicatas de costura UV (313k → 212k vértices no La vivacité), o GLB tem **2 componentes conexos** — o frasco (99,99% das faces) e um fragmento de 24 triângulos. Separar por *loose parts* ou por material não produz nada útil.

## O sinal: pico de densidade de faces

Uma superfície horizontal — o "ombro" onde o corpo termina — concentra muitas faces numa faixa estreita de Z. Perfilando os GLBs em 24 fatias:

| Frasco | baseline (faces/fatia) | pico | `z_rel` | razão |
|---|---|---|---|---|
| Hinode GRAND | ~22.000 | 48.289 | 0,67 | 2,11× |
| La vivacité | ~16.000 | 42.272 | 0,67 | 2,22× |
| Lattafa ASAD | ~20.000 | 58.358 | 0,75 | 2,28× |

O pico é procurado apenas na faixa `[0.40, 0.88]` de altura relativa: o fundo do frasco e a face superior da tampa também são horizontais e produzem picos maiores, que não interessam.

### Alternativas descartadas por medição

Duas heurísticas mais óbvias foram testadas antes e **falham em pelo menos um frasco real**:

| Candidato | Por que falha |
|---|---|
| **Raio mediano por fatia** (procurar o gargalo) | O ASAD tem perfil praticamente plano de `z_rel` 0,12 a 0,92 — a tampa tem o mesmo diâmetro do corpo. Não existe gargalo geométrico para achar. No La vivacité, a largura máxima cai sobre o **laço**, não sobre o ombro. |
| **Cor da textura por fatia** | O ASAD é preto no corpo e na tampa, e tem faixas douradas decorativas em várias alturas (`z_rel` 0,29–0,58 e 0,71–0,75). Múltiplos candidatos ambíguos, sem critério para escolher. |

O registro dessas duas tentativas está no docstring de `segment_bottle.py` — elas são parte do resultado, não ruído.

## Implementação

`app/modules/captures/blender_scripts/segment_bottle.py` roda dentro do Blender headless.

```
blender.exe --background --python segment_bottle.py -- \
    --input  raw.glb \
    --output segmented.glb \
    [--debug-colors]
```

Constantes calibradas:

| Constante | Valor | Papel |
|---|---|---|
| `N_FATIAS` | 24 | Mais fatias fragmentam o pico; menos borram a posição. |
| `Z_MIN_BUSCA` / `Z_MAX_BUSCA` | 0,40 / 0,88 | Exclui fundo e topo do frasco. |
| `RAZAO_MINIMA` | 1,5 | Abaixo disso o frasco não tem ombro discernível e a segmentação é **abortada** (o chamador segue com material único). |

O corte fica no **topo da fatia do pico**: o ombro pertence ao corpo, o que está acima é tampa/gargalo.

Resultado: o objeto passa a ter dois slots de material — `[0]` corpo, `[1]` tampa. A tampa recebe uma **cópia** do material original, então a aparência não muda até que algum stage altere um dos dois. O GLB exportado mantém **uma única imagem** de textura compartilhada, sem inflar o arquivo.

### Validação visual

A flag `--debug-colors` pinta corpo de vermelho e tampa de azul. Nos três frascos o corte cai exatamente no ombro. No La vivacité o laço fica classificado como tampa — correto: ele prende no gargalo e não faz parte do corpo de vidro.

## Onde é usada

### 1. Refinamento de vidro ([09c](09c-refinamento-mesh.md))

Em `body_mode=glass`, `refine_ai_mesh.py` segmenta antes de aplicar a transmissão e altera apenas o material do corpo. GLB resultante:

```
mat[0] Material_0        → transmission=1, IOR=1.45, roughness=0.05   (corpo)
mat[1] Material_0_Tampa  → roughness=0.9036, sem transmission          (tampa)
```

Quando o ombro não é identificado, o script cai no comportamento anterior (material único) em vez de falhar.

### 2. Projeção da textura do topo

`project_top_texture.py` usa o corte como `z_minimo` para restringir a coleta de faces, e recorta a foto do topo pela bounding box dos pixels opacos antes de projetar. A foto vem do `BackgroundRemover`, então o frasco ocupa só parte do quadro — sem recorte, a tampa recebia majoritariamente área transparente esticada.

## Medições

Método: render pareado no Blender (mesma câmera, luz e engine) e diferença pixel a pixel restrita à máscara do objeto. Escala de referência: **dois frascos completamente diferentes medem 27,3**.

**Vidro (La vivacité):**

| Variante | dif. média |
|---|---|
| Vidro global (sem segmentação) | 6,44 |
| Vidro segmentado (só no corpo) | 4,02 |

O número cai porque a alteração atinge menos área. O ganho aqui é de **correção**, não de magnitude — antes tampa, rótulo e laço viravam transparentes junto.

**Projeção do topo (ASAD):**

| Versão | dif. no topo | vazamento no corpo (vista 3/4) |
|---|---|---|
| v1 — original | 14,80 | 2,66 |
| v2 — + segmentação | 13,88 | **1,40** (−47%) |
| v3 — + recorte alpha | **12,56** | 1,40 |

O recorte reduziu a imagem de 1200×1600 para 685×644 — a foto tinha apenas **23% de conteúdo útil**.

## Limitação conhecida: alinhamento rotacional

Com segmentação e recorte, a foto do topo cai na região certa e na escala certa, mas ainda **girada**. A projeção ortográfica mapeia XY do mundo para UV e não há nada que amarre a rotação da foto em torno de Z à rotação da malha — o logo aparece deslocado em vez de centralizado.

Resolver isso exige estimar o ângulo entre foto e malha (casamento de features, ou uma convenção de captura imposta pelo app). **Não é ajuste de constante** e está fora do escopo desta etapa.

## Testes

`tests/modules/captures/test_segment_bottle.py` — 10 testes.

O script importa `bpy`, mas `encontrar_corte` é Python puro (recebe lista de alturas, devolve o corte). O teste injeta stubs de `bpy` e `mathutils` em `sys.modules` e carrega o módulo via `importlib`, o que permite exercitar a heurística calibrada **sem exigir Blender instalado**.

Cobertura: pico detectado na faixa; picos de topo e de fundo ignorados; perfil uniforme rejeitado; razão no limite rejeitada; corte posicionado acima do pico; mesh degenerado tratado; e travas nas constantes calibradas.

## Leituras relacionadas

- [09c — Refinamento de malha](09c-refinamento-mesh.md)
- [09f — Pipeline integrado](09f-pipeline-integrado.md)
- [14 — Testes](14-testes.md)
- Código: [`segment_bottle.py`](../app/modules/captures/blender_scripts/segment_bottle.py), [`refine_ai_mesh.py`](../app/modules/captures/blender_scripts/refine_ai_mesh.py), [`project_top_texture.py`](../app/modules/captures/blender_scripts/project_top_texture.py)
