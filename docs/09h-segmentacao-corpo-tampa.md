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

`project_view_texture.py` usa o corte para restringir a coleta de faces, e recorta a foto do topo pela bounding box dos pixels opacos antes de projetar. A foto vem do `BackgroundRemover`, então o frasco ocupa só parte do quadro — sem recorte, a tampa recebia majoritariamente área transparente esticada.

## O estágio no pipeline

O `TopProjector` é o **stage (7.5)** do `IntegratedPipeline`, entre a projeção do rótulo e o `ModelCache.store`.

**Por que ele existe:** o Hunyuan3D-2mv reconstrói a partir de 4 vistas cardeais (frente, esquerda, trás, direita). Nenhuma delas enxerga o topo do frasco, então a tampa sai como um **disco liso sem textura**. Este estágio cola a foto real de cima sobre as faces da tampa.

**Como a foto do topo chega até ele:**

1. O app envia `views=["front","left","back","right","top"]` no `POST /captures`
2. `LabeledViewRouter` reconhece `top` e o coloca em `assignments["top"]` — **fora** de `ordered`, porque o Hunyuan só consome as 4 cardeais e ignoraria a quinta
3. O pipeline lê `routing.assignments.get("top")` e passa a foto **mascarada** (pós-rembg) ao projetor — o recorte por alpha depende do canal de transparência

**Degradação:** sem foto rotulada como `top`, o estágio é no-op e loga em INFO — não é erro. Se o Blender falhar, o GLB do estágio anterior segue e loga warning.

**Configuração:**

| Chave | Default | Papel |
|---|---|---|
| `TOP_PROJECTOR_TYPE` | `blender` | `disabled` desliga o estágio |
| `TOP_COSINE_THRESHOLD` | `0.45` | Cosseno mínimo entre a normal da face e o eixo Z |

> **Mudança de contrato HTTP:** `top` passou a ser um rótulo de vista válido. Antes o endpoint rejeitava com 422 — havia inclusive um teste afirmando isso, que foi atualizado. Rótulos desconhecidos continuam sendo rejeitados.

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

## Alinhamento rotacional: implementado, mas bloqueado pelo gerador

A projeção ortográfica mapeia XY do mundo para UV e nada amarra a **rotação em torno de Z**: a foto foi tirada numa orientação qualquer e a malha tem a sua. Sem corrigir, o logo da tampa sai girado.

### A abordagem

[`top_alignment.py`](../app/modules/captures/blender_scripts/top_alignment.py) estima o ângulo por **máxima sobreposição (IoU) entre silhuetas**: a da foto (canal alpha do rembg) contra a da tampa projetada em XY. A silhueta da tampa raramente é circular — a do ASAD é um triângulo arredondado, a do La vivacité é quadrada —, então em princípio há sinal suficiente.

O módulo é numpy puro (não importa `bpy`) e normaliza translação e escala, sobrando só a rotação. Reporta `confianca` = razão entre o melhor IoU e a mediana de todos os ângulos testados: **1,0 significa curva plana**, ou seja, rotação indeterminada.

Validado por 16 testes com formas sintéticas de rotação conhecida — recupera o ângulo em triângulos e quadrados dentro de 4°, é invariante a escala, detecta espelhamento em formas quirais e identifica corretamente a ambiguidade do círculo.

### Por que não funciona nos dados atuais

No único job com foto de topo (ASAD), o estimador **recusa aplicar rotação** — e está certo. As duas silhuetas não têm a mesma forma:

```
MALHA (tampa vista de cima)          FOTO (alpha do rembg)
   .........########.........          ..............##..............
   ....##################....          .........###########..........
   ..######################..          ......#################.......
   ##########################          ...#######################....
   ##########################          #########################.....
   ..######################..          ###########################...
   ....##################....          ..########################....
   .........########.........          .......################.......
        (círculo)                          (triângulo arredondado)
```

**O Hunyuan arredondou a seção triangular da tampa.** Testei limiares de normal de 0,45 a 0,99 e faixas de 2%, 5% e 10% do topo em altura: a silhueta da malha é um círculo em todos. A informação de forma simplesmente não está no mesh.

Resultado medido: `IoU=0,881`, `confiança=1,009` → abaixo do limiar de 1,08, rotação não aplicada.

Isso é uma limitação de **fidelidade do gerador**, não do algoritmo. E o comportamento é seguro: na dúvida, não gira, em vez de girar aleatoriamente.

### Caminho para resolver

A alternativa que não depende da fidelidade do mesh é uma **convenção de captura**: o app instrui o usuário a fotografar o topo com a frente do frasco apontando para uma direção conhecida (a base do enquadramento, por exemplo). Aí a rotação é dada por construção — zero estimativa. Custa uma mudança no fluxo guiado do app, mas é robusta e gratuita.

O estimador por silhueta continua útil como caminho automático para frascos cuja tampa o gerador reconstrua com forma fiel, e a `confiança` decide qual dos dois vale em cada job.

## Testes

`tests/modules/captures/test_top_alignment.py` — 16 testes da estimativa de rotação, com formas sintéticas de ângulo conhecido. Documenta duas armadilhas encontradas ao escrever os testes: espelhar um **polígono regular** equivale a girá-lo (simetria diedral), e espelhar um **"L" de braços iguais** também (simetria diagonal) — só uma forma de braços desiguais é quiral de verdade.

`tests/modules/captures/test_segment_bottle.py` — 10 testes.

O script importa `bpy`, mas `encontrar_corte` é Python puro (recebe lista de alturas, devolve o corte). O teste injeta stubs de `bpy` e `mathutils` em `sys.modules` e carrega o módulo via `importlib`, o que permite exercitar a heurística calibrada **sem exigir Blender instalado**.

Cobertura: pico detectado na faixa; picos de topo e de fundo ignorados; perfil uniforme rejeitado; razão no limite rejeitada; corte posicionado acima do pico; mesh degenerado tratado; e travas nas constantes calibradas.

## Leituras relacionadas

- [09c — Refinamento de malha](09c-refinamento-mesh.md)
- [09f — Pipeline integrado](09f-pipeline-integrado.md)
- [14 — Testes](14-testes.md)
- Código: [`segment_bottle.py`](../app/modules/captures/blender_scripts/segment_bottle.py), [`refine_ai_mesh.py`](../app/modules/captures/blender_scripts/refine_ai_mesh.py), [`project_view_texture.py`](../app/modules/captures/blender_scripts/project_view_texture.py)
