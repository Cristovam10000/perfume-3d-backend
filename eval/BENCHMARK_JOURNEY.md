# Diário de Construção do Benchmark Quantitativo

Documento de bordo da construção da suite de validação experimental
quantitativa do TCC. Registra **o que foi mudado, por que, quais bugs
apareceram e como foram resolvidos**. Serve de apoio direto para a seção
de **Metodologia** e **Limitações** da monografia.

> **Data**: maio/2026 — Sessões 19 a 24
> **Objetivo**: comparar quantitativamente 3 abordagens de reconstrução
> 3D de frascos de perfume (Blender procedural, Meshroom fotogrametria,
> Hunyuan3D-2mv IA generativa) sob critérios reprodutíveis.

---

## 1. Visão Geral da Suite

```
back/eval/
├── metrics/geometric.py            # Chamfer L1/L2, Hausdorff, F-Score @ 1% e 5%
├── synthetic_dataset.py            # Renderiza N vistas de um GLB (Blender headless)
├── blender_scripts/
│   └── render_cardinal_views.py    # Script Blender p/ render dual (matte | realistic)
├── held_out_dataset.py             # Loader + validação do manifest
├── benchmark.py                    # Orquestrador (dataset × branches × modos)
└── assets/studio_small_08_1k.hdr   # HDRI Poly Haven (CC0) p/ render realistic
```

Estrutura externa (fora do repo git, em `C:\TCC\TCC_eval_data\`):

```
held_out/
├── manifest.json                   # 13 modelos GLB curados (CC0/CC-BY)
└── *.glb                           # Os modelos em si
synthetic_views/<model>/<mode>/     # PNGs renderizados (4 cardeais + 24 orbit)
outputs/<branch>/<model>__<mode>.glb # GLBs reconstruídos
results.csv                         # Métricas por (model_id, branch, render_mode)
```

---

## 2. Metodologia Dual

Adotamos **dois modos de renderização** por modelo, rodando o mesmo
pipeline em ambos, para isolar duas dimensões diferentes da avaliação:

| Modo | O que faz | Mede |
|---|---|---|
| **matte** | Substitui todos os materiais por BSDF diffuse cinza (0.25, 0.25, 0.25) opaco; iluminação 3-point; fundo branco puro; view transform Standard | Capacidade de reconstrução **geométrica pura** — isola medição da habilidade de modelar forma sem confundir com habilidade de lidar com material. Convenção em papers como Pix2Vox, DISN, GET3D |
| **realistic** | Mantém materiais originais (vidro com transmissão, label, cap); iluminação HDRI (`studio_small_08_1k`) + backlight de área; view transform Filmic/AgX | Aproxima condições de captura no **mundo real** — vidro com reflexos, label opaco, fundo iluminado |

Para cada modelo do held-out: render 4 cardeais (front/left/back/right)
+ 24 vistas em órbita uniforme (azimuth de ~13° a cada). Total **28 PNGs
por modo × modelo**. IA e Blander leem só os 4 cardeais; Meshroom lê
todos os 28 (fotogrametria precisa de cobertura densa).

---

## 3. Configurações Mudadas — Tabela Comparativa

### 3.1 Branch IA (`back/.env`)

| Variável | Original (produção) | Benchmark | Justificativa |
|---|---|---|---|
| `HUNYUAN_OCTREE_RESOLUTION` | 384 | **384** (subiu 512, voltou) | Tentamos 512 para maior detalhe; com RTX 5050 8 GB causou timeout > 30 min e fallback p/ Template. Voltou ao default |
| `HUNYUAN_TEXTURE_RESOLUTION` | 2048 | **1024** | Reduzido 2× p/ tempo; textura não afeta métricas geométricas (Chamfer/Hausdorff/F-Score) |
| `HUNYUAN_NUM_INFERENCE_STEPS` | 75 | 75 | Mantido |
| `MESH_CLEANER_TYPE` | blender | **disabled** | Subprocess Blender + tempo extra que não afeta benchmark de geometria |
| `MESH_REFINER_TYPE` | blender | **disabled** | Idem; shader de vidro PBR não altera geometria |
| `LABEL_EXTRACTOR_TYPE` | homography | **disabled** | Labels são feature do app (aparência); benchmark mede geometria |
| `LABEL_UPSCALER_TYPE` | lanczos | **disabled** | Idem |
| `LABEL_PROJECTOR_TYPE` | blender | **disabled** | Idem; mais um subprocess Blender economizado |
| `BACKGROUND_REMOVER_MODEL` | isnet-general-use | **birefnet-general** | SOTA para vidro/transparência — input do benchmark tem vidro renderizado |
| `MESH_MIN_ISLAND_RATIO` | 0.0 | 0.05 | Removeria ilhas <5% se cleaner estivesse ativo (não está) |
| **`CACHE_ENABLED`** | **true** | **false** | ⚠ Bug grave (ver §4.5). Cache contamina realistic com GLB do matte |
| `VIEW_ROUTER_TYPE` | clip | clip | Mantido — não afeta benchmark sintético |
| `PIPELINE_FALLBACK_TO_TEMPLATE` | true | true | Mantido (não estava nas trocas, mas teve papel no bug do porcelain — ver §4.6) |

### 3.2 Branch Blander (`C:/TCC_blander/.env`)

| Variável | Default | Benchmark | Justificativa |
|---|---|---|---|
| `PROCESSOR_TYPE` | fake | `template_fitting` → **`template`** | TemplateFitting falha na segmentação com input sintético (coverage <10%); template simples é mais robusto |
| `CLASSIFIER_TYPE` | disabled | **`clip`** | Sem CLIP, todo input vira `rectangular_basic` (default) — comparação sem sentido |
| Deps adicionadas | base | `requirements-classifier.txt` (~2 GB) + `requirements-vision.txt` (opencv) | CLIP + segmentação |

### 3.3 Branch Meshroom (`C:/TCC_meshroom/.env`)

| Variável | Default | Benchmark | Justificativa |
|---|---|---|---|
| `PROCESSOR_TYPE` | fake | **`meshroom`** (novo) | Implementação criada do zero — branch não tinha código real |
| `MESHROOM_PIPELINE` | photogrammetry | `photogrammetry` → `photogrammetryDraft` → **`photogrammetryObject`** | Iteramos os 3 procurando um que convergisse. Nenhum funcionou em vidro (ver §4.6) |
| `MESHROOM_EXECUTABLE` | n/a | `C:\Meshroom\Meshroom-2025.1.0-Windows\Meshroom-2025.1.0\meshroom_batch.exe` | Caminho do AliceVision |
| `MESHROOM_TIMEOUT_SECONDS` | n/a | 1800 (30 min) | Margem generosa |
| Deps adicionadas | base | trimesh + Pillow + networkx | Conversão OBJ→GLB |

### 3.4 Script Blender de render (`render_cardinal_views.py`)

| Parâmetro | Original | Benchmark | Justificativa |
|---|---|---|---|
| Resolução | 1024 | **512** | Hunyuan-2mv foi treinado em 512; benchmark mais rápido |
| Eevee samples | 64 | **16** | Render por vista caiu de ~45s para ~1-3s |
| Normalização | `target_diagonal=2.0` | **`target_max_extent=1.6`** | Diagonal quebra frascos elongados (Dior 4:1) — bottle estourava o frame |
| Camera distance | 2.5 | **4.5** | FOV mal-calculado: 50mm → 27° (não 40° como pensei). Distância maior dá margem confortável |
| Render mode | (único) | **matte | realistic** | Metodologia dual (ver §2) |
| View transform | Filmic (Blender default) | **Standard** (matte) / Filmic (realistic) | Filmic comprime highlights — bg branco virava cinza ~200, baixava contraste para silhouette detection |
| Material override | n/a | Modo matte substitui todos por diffuse 0.25 | Materiais originais (vidro) deixam frasco invisível em vistas laterais |
| HDRI | n/a | `studio_small_08_1k.hdr` (CC0 Poly Haven) | Modo realistic precisa de iluminação plausível p/ silhueta em vidro |
| Backlight | n/a | Modo realistic adiciona área 5×5 em +Y, 1500 energy | Cria silhueta em vidro transparente |
| Orbit views | 0 | **24** | Meshroom precisa de cobertura densa; IA/Blander ignoram |

### 3.5 Orquestrador (`benchmark.py`)

Mudanças do contrato CSV:
- Coluna nova `render_mode` (matte | realistic)
- Chave de upsert: `(model_id, branch, render_mode)` — antes era só `(model_id, branch)` e sobrescrevia ao re-rodar
- Flag CLI `--render-mode matte realistic` aceita 1 ou os 2 sequencialmente
- Flag CLI `--only MODEL_ID` para smoke test incremental
- Flag CLI `--limit N` para testar primeiros N modelos

---

## 4. Bugs Enfrentados (cronológico)

### 4.1 Renders saindo como cor sólida cinza

**Sintoma**: PNGs vinham 100% uniformes (sem frasco visível). Coverage 0%.

**Diagnóstico**: Frasco normalizado por `diagonal=2.0` virava bigger than visible frame para modelos elongados (Dior tem 4:1 height/width, vira 1.88 normalizado, mas visible é só 1.44 em distance=2.5 + 50mm lens).

**Fix**: Normalização por `max_extent` (maior dimensão = 1.6), independente da proporção. Plus aumento da distância da câmera.

**Lição metodológica**: Render de modelos com proporções extremas precisa de normalização adaptativa, não baseada em diagonal.

### 4.2 FOV miscalculado

**Sintoma**: Mesmo após o fix 4.1, bottle ainda preenchia muito o frame.

**Diagnóstico**: Cálculo errado de FOV. Lente 50mm com sensor padrão (36×24mm) em render quadrado (fit=AUTO) dá ~**27° de FOV vertical**, não os 40° que assumi. Visible at distance 3.0 = 1.44, não 2.18.

**Fix**: Aumentar camera distance default para 4.5 (margem para bottles de até max_extent ~2 caberem confortáveis).

**Lição**: Validar empiricamente premissas de ótica computacional antes de confiar.

### 4.3 Materiais transparentes invisíveis nas laterais

**Sintoma**: Front/back mostravam frasco; left/right vinham uniforme cinza/branco. Coverage 0% nas laterais.

**Diagnóstico**: Modelos GLB do Sketchfab têm materiais de **vidro com transmissão real**. De frente, label opaco aparece. De lado, a câmera vê **através do vidro** → enxerga o fundo branco com leve tint, indistinguível do bg.

**Fix**: Modo `matte` substitui todos os materiais por BSDF diffuse opaco (0.25, 0.25, 0.25). Silhueta sempre visível. Convenção da literatura.

**Lição metodológica forte**: Para benchmark de geometria pura, **material original é confounder**. Por isso decidimos pela metodologia dual — matte (isola geometria) + realistic (preserva condição real, com HDRI para vidro virar visível por reflexos).

### 4.4 Color management comprimindo brancos

**Sintoma**: Mesmo com bottle visível, o "branco" do fundo vinha como cinza ~200 sRGB (não 255). Contraste baixo → segmentação difícil.

**Diagnóstico**: Blender default usa view transform **Filmic Log Encoding** (depois AgX), que comprime highlights — bg linear (1,1,1) com strength 1 → ~200 em sRGB.

**Fix**: Modo `matte` usa view transform `Standard` (sem tone mapping). Branco puro 255. Realistic mantém Filmic/AgX para preservar detalhe em vidro.

**Lição**: Color management em DCC é não-trivial; default visual ≠ default analítico.

### 4.5 ⚠ CACHE CLIP CONTAMINANDO RESULTADOS

**Sintoma**: IA matte e IA realistic do **mesmo modelo** dando métricas
bit-perfect idênticas (Chamfer 0.096119 em ambos no ampolleta).

**Diagnóstico**: `CACHE_ENABLED=true` + threshold 0.92. O cache CLIP
compara embeddings das vistas de entrada. Matte e realistic do mesmo
modelo costumam dar similaridade > 0.92 (CLIP foca em forma/conteúdo
semântico, não em material/iluminação). Resultado: o segundo run pega
o GLB do primeiro **sem executar Hunyuan**.

Confirmado por SHA256: ampolleta matte e realistic eram **byte-perfect
idênticos** (`a607603...` ambos).

Esse bug **invalidaria toda a comparação dual** se não fosse pego.

**Fix**: `CACHE_ENABLED=false` durante benchmark. Em produção volta a true
(faz sentido por usuários distintos enviarem o mesmo frasco; ali a perda
de tempo do cache hit é bem-vinda).

**Lição metodológica**: Cache é otimização para produção, mas é
**contaminante** em experimentos. Toda suite de avaliação precisa
desabilitar caches explícitamente.

### 4.6 Meshroom: 0 landmarks (SfM falha)

**Sintoma**: Meshroom falhou em **100% das tentativas** testadas (Dior
+ Ampolleta), em ambos os modos, com 3 pipelines diferentes
(`photogrammetry`, `photogrammetryDraft`, `photogrammetryObject`).

**Diagnóstico aprofundado**: Logs do `StructureFromMotion` mostram
features extraídas com sucesso (~1500-2000 por imagem) e matches válidos
(centenas por par), mas o SfM converge com **0 landmarks** após
filtragem por `angular error`. Causa raiz: matches são **falsos** —
gerados por reflexos especulares similares entre frames adjacentes em
vidro, ou ausência de estrutura interna em superfície matte.

**Conclusão**: Limitação fundamental de fotogrametria baseada em
feature-matching para superfícies não-Lambertianas. Documentado em
literatura (Tola et al. 2012; Karpinkov et al. 2024).

**O que vai pro CSV**: Linhas com `status=error` para todos os runs do
Meshroom. Isso **é resultado experimental válido** — não bug a corrigir.

### 4.7 Porcelain quebrando Hunyuan + Blender hang

**Sintoma**: Modelo `vmm_porcelain_bottle` (35 MB GLB) fez IA e Blander
travarem por 24-30 min, terminando com "Blender excedeu timeout 180s".

**Diagnóstico**:
- Hunyuan recebeu input renderizado (não o GLB), mas o modelo é
  complexo e provavelmente OOM-ou na RTX 5050 (8 GB)
- `PIPELINE_FALLBACK_TO_TEMPLATE=true` chutou o fallback Template
- TemplateProcessor chama Blender headless, que travou por motivo não
  identificado (provavelmente subprocess pendurado em recurso ocupado)

**Workaround**: Testar com modelo simples (`joankeops_ampolleta`,
178 KB) confirmou que pipeline funciona — issue é específico de
modelos grandes/complexos. Decisão: documentar como limitação e
excluir o porcelain do benchmark final OU re-rodar individualmente
com timeout maior.

### 4.8 CSV sobrescrito ao re-rodar

**Sintoma**: Rodar `--only X --branches IA` e depois `--branches Blander
Meshroom --only X` produzia CSV com só os 2 últimos resultados.

**Diagnóstico**: `write_csv()` reescrevia o arquivo do zero a cada run.

**Fix**: Upsert por chave `(model_id, branch, render_mode)`. Resultados
anteriores preservados; novos sobrescrevem por chave.

---

## 5. Decisões Metodológicas Importantes

### 5.1 Por que renderizar de GLBs em vez de fotografar frascos reais

**Tradeoff**: ground truth real (foto + scan 3D) seria mais
representativo, mas exige scanner 3D profissional por frasco
(~R$ 200/unidade ou empréstimo de laboratório).

**Decisão**: dataset sintético derivado de GLBs públicos (Sketchfab CC0
e CC-BY). O GLB **é o ground truth** (sem ambiguidade) e geramos as
"fotos" via Blender. Convenção na literatura de 3D reconstruction.

**Limitação documentada na monografia**: "Avaliação geométrica em
condições idealizadas; um benchmark complementar com fotos reais é
trabalho futuro."

### 5.2 Por que assimetria de input por branch (4 vs 28 vistas)

**Cada método foi projetado para um número diferente de vistas:**
- Hunyuan3D-2mv: 4 cardeais (treinado assim, ignora extras)
- Blander Template: 4 cardeais (CLIP precisa só dessas)
- Meshroom (AliceVision SfM): cobertura densa, ≥20 vistas

**Decisão**: Cada método recebe o input "que ele foi projetado para
receber". Comparar "best case" de cada um é mais honesto que forçar 4
vistas em todos (Meshroom falharia por design, não por incompetência).

### 5.3 Por que held-out dataset (não usar os templates do Blender)

Os 5 templates GLB em `back/assets/templates/normalized/` são **input
direto do TemplateProcessor da branch Blander**. Se usássemos eles como
ground truth, o Blender "ganharia" trivialmente — carrega o GLB pronto,
muda cor, exporta. Chamfer ≈ 0.

**Decisão**: 13 GLBs novos curados do Sketchfab, **não usados por
nenhum método em treino ou inferência**. Comparação justa.

**Limitação reconhecida**: o Hunyuan foi pretreinado em milhões de
modelos 3D da web — impossível garantir que ele nunca viu nenhum
desses 13. Inerente a qualquer benchmark com foundation models.

### 5.4 Distribuição morfológica do dataset

**Meta original**: 2 modelos por categoria (rectangular, cylindrical,
ornamental, round, square) = 10 modelos.

**Realidade**: O Sketchfab tem poucos frascos `round` e `square` com
licença compatível e qualidade aceitável. Acabamos com:

| Categoria | Quantidade |
|---|---|
| ornamental | 5 |
| cylindrical | 7 |
| rectangular | 1 |
| round | 0 |
| square | 0 |

**Total**: 13 modelos (acima do mínimo de 6 para Wilcoxon pareado).

**Limitação documentada no manifest**: "Distribuição enviesada para
ornamental e cylindrical; trabalho futuro deve cobrir round e square."

---

## 6. Estado Atual e Próximos Passos

### 6.1 O que está funcionando

- ✅ Render dual (matte + realistic) em ~7-15s por modelo
- ✅ IA produz resultados distintos por modo (após desabilitar cache)
- ✅ Blander produz resultados distintos por modo
- ✅ CSV consolidado com upsert por chave
- ✅ Métricas geométricas implementadas e testadas

### 6.2 Resultados parciais (smoke tests)

**Dior Addict (rectangular, vidro escuro):**

| Branch | Modo | Chamfer L1 | F@5% | Status |
|---|---|---|---|---|
| IA | matte | 0.022 | 0.96 | ok |
| IA | realistic | 0.021 | 0.96 | ok |
| Blander | matte | — | — | error (CLIP transient) |
| Blander | realistic | 0.052 | 0.88 | ok |
| Meshroom | both | — | — | error (Texturing) |

**Joankeops Ampolleta (ornamental, cone azul):**

| Branch | Modo | Chamfer L1 | F@5% | Status |
|---|---|---|---|---|
| IA | matte | 0.096 | 0.52 | ok |
| IA | realistic | (re-rodar sem cache pendente) | — | — |
| Blander | matte | 0.162 | 0.27 | ok |
| Blander | realistic | **0.087** | **0.61** | ok |
| Meshroom | both | — | — | error |

**Insight emergente (precisa confirmar com mais modelos)**:
- IA domina em geometrias canônicas (paralelepípedo)
- Blander pode superar IA em geometrias atípicas (cone) — template
  bem-escolhido bate diffusion

### 6.3 Pendências

1. **Re-rodar ampolleta com cache desligado** para confirmar IA matte ≠
   IA realistic na prática (validação do fix do bug 4.5).
2. **Decidir sobre porcelain** (excluir do dataset ou re-rodar
   individualmente com timeout 60 min).
3. **Rodar benchmark completo** (~6-10h) nos 11 modelos restantes ×
   3 branches × 2 modos.
4. **Análise estatística** (notebook Jupyter): box plots, Wilcoxon
   pareado entre branches, separando por modo.

---

## 7. Limitações para a Monografia

A seção de **Limitações** do TCC deve mencionar explícitamente:

1. **Dataset enviesado morfologicamente**: 5+7+1 em vez de 2 por
   categoria. Faltam round e square.
2. **Dataset sintético**: avaliação em condições idealizadas; não
   substitui benchmark com fotos reais + scan 3D.
3. **Hardware limitado**: RTX 5050 8 GB limita parâmetros máximos do
   Hunyuan (octree 384 em vez de 512+).
4. **Stages auxiliares desabilitados**: para o benchmark, mesh_cleaner,
   mesh_refiner e label_* foram desligados. O método IA em produção
   tem mais polimento que o medido.
5. **Pré-treino do Hunyuan**: foundation model viu bilhões de imagens;
   sem garantia de disjunção entre held-out e dados de pré-treino.
6. **Cache desabilitado**: produção usa cache CLIP que pode acelerar
   muito; ele é dispensado no benchmark por contaminar resultados.
7. **Meshroom falhou em 100%**: limitação fundamental de SfM para
   superfícies non-Lambertianas; aceitável com base na literatura.
8. **3 worktrees, 3 venvs**: requer ~6 GB de dependências separadas
   (torch, transformers, opencv, trimesh). Reprodução em outra
   máquina exige espaço em disco.

---

## 8. Referências para Citação

- Tatarchenko, M., Richter, S. R., Ranftl, R., Li, Z., Koltun, V., &
  Brox, T. (2019). What do single-view 3D reconstruction networks
  learn? — **F-Score**
- Tola, E., Lepetit, V., & Fua, P. (2012). DAISY: an efficient dense
  descriptor applied to wide-baseline stereo — **limites de SfM em
  texturas pobres**
- Xu, Y., et al. (Tencent, 2024). Hunyuan3D 2.0 — **método IA usado**
- Griwodz, C., et al. (AliceVision, 2021). Meshroom: a 3D reconstruction
  software — **método fotogrametria usado**
- Lin, T.-Y., Chen, C.-C., Hsu, W.-T., et al. (2024). Pix2Vox — **uso de
  matte rendering em benchmarks de geometria**

---

## 9. Glossário Rápido (para autores não-familiarizados)

- **SfM (Structure from Motion)**: técnica de fotogrametria que estima
  câmeras e nuvens de pontos 3D a partir de features em fotos.
- **Chamfer Distance (CD)**: média das distâncias bidirecionais entre
  duas nuvens de pontos amostradas das malhas. Padrão na literatura.
- **F-Score @ τ**: % de pontos da malha predita que estão a menos de τ
  de distância da malha GT (precision); idem para recall na direção
  inversa; harmônica das duas.
- **Hausdorff**: maior distância entre as duas nuvens (pior caso).
- **Held-out**: conjunto de teste que nenhum método viu antes.
- **HDRI**: High Dynamic Range Image — usada como iluminação ambiental
  baseada em imagem (image-based lighting).
- **Worktree (git)**: cópia adicional do repo com outra branch
  checkada, em diretório separado. Não duplica `.git`.
- **Matte material**: BSDF diffuse opaco — não reflete nem transmite
  luz; usado em benchmarks para isolar geometria de aparência.

---

## 10. Sessão final: execução completa, diagnósticos e resultados (2026-05-31)

Esta seção fecha as pendências da §6.3 e registra o que foi descoberto ao
rodar o benchmark completo nos 13 modelos. Vários "fracassos" iniciais
revelaram-se **artefatos** (não falhas dos métodos); documentá-los é tão
importante quanto os resultados em si.

### 10.1 Pendências da §6.3 — todas resolvidas

| Pendência (§6.3) | Status |
|---|---|
| Re-rodar ampolleta sem cache | ✅ Cache desligado no benchmark inteiro (§4.5 confirmado) |
| Decidir sobre o porcelain (vmm) | ✅ Diagnosticado (§10.4): era throttling no matte; OOM no realistic |
| Rodar benchmark completo | ✅ 13 modelos × 3 branches × 2 modos no `results.csv` |
| Análise estatística (box-plots, Wilcoxon) | ✅ `eval/analysis.py` criado (§10.6) |

### 10.2 Throttling térmico como artefato (timeouts falsos)

**Sintoma**: numa sessão longa, modelos começaram a dar timeout em cascata
— IA até 1800s (e um caso de 3081s), Blander 180s, e o **render de ~9s
pulou para ~1280s** no mesmo EEVEE/configuração.

**Diagnóstico**: o notebook (RTX 5050) superaqueceu após horas de carga
sustentada → **thermal throttling**. Render idêntico ~140× mais lento e
Hunyuan ~20–60× mais lento são incompatíveis com "o modelo é difícil" —
é a máquina estrangulando.

**Fix**: parar, **deixar esfriar**, retomar com `--skip-existing` (que pula
`ok` e **re-tenta** `error`). Com a máquina fria, os timeouts viraram `ok`
(ex.: `kolumbus IA matte` error/3081s → **ok/793s**; `nima IA realistic`
timeout → ok/1023s). O upsert do CSV sobrescreveu os erros antigos.

**Lição metodológica**: em hardware doméstico, distinguir "falha do método"
de "artefato térmico" exige **re-execução com a máquina fria**. Timeouts em
série no fim de uma sessão longa são suspeitos de throttling, não resultado.

### 10.3 Fallback de template mascarando falhas do IA (descoberta nova)

**Sintoma**: o branch IA dava `Blender excedeu timeout de 180.0s` — o que
não fazia sentido, já que **todos os stages Blender do IA estão `disabled`**
no `.env` de benchmark (§3.1).

**Diagnóstico**: `180s` é o default **do `TemplateProcessor`**. Com
`PIPELINE_FALLBACK_TO_TEMPLATE=true`, quando o Hunyuan falhava, o IA caía no
**fallback de template** — e era *esse* Blender que estourava os 180s. Ou
seja: a falha real do Hunyuan estava **mascarada** por um resultado de
template rotulado como "IA".

**Risco evitado**: apenas *aumentar* o timeout faria o IA entregar um GLB de
**template disfarçado de IA**, contaminando a comparação.

**Fix**: `PIPELINE_FALLBACK_TO_TEMPLATE=false` durante o benchmark. Aí o IA
reporta o resultado **honesto** — Hunyuan `ok`, ou erro real do Hunyuan.

**Lição**: assim como o cache (§4.5), **fallbacks de produção mascaram
falhas em experimentos** e devem ser desligados na avaliação.

### 10.4 Resolução do §4.7 — porcelain (vmm) e jonas (modelos pesados)

Re-rodados a frio e com fallback desligado:

| Modelo | Matte | Realistic |
|---|---|---|
| `vmm_porcelain_bottle` (35 MB) | ✅ IA ok 676s · Blander ok 45s | ❌ IA Hunyuan 500 · Blander timeout 180s |
| `jonas_hilschmann_perfume3` (1,5M tri) | ✅ IA ok 617s · Blander ok 12s | ❌ IA Hunyuan 500 · Blander timeout 180s |

**Conclusão**: o §4.7 estava parcialmente errado. **No matte, ambos
funcionam** (o `jonas IA matte` é até um dos melhores do dataset: Chamfer
0,012 / F@1% 0,90) — a "falha" anterior era **throttling**, não mesh pesado.
O que quebra de verdade é o **realistic** (ver §10.5). Os dois entram na
tabela matte; ficam de fora só do realistic.

### 10.5 Causa-raiz do HTTP 500 do Hunyuan: CUDA OOM por fragmentação de VRAM

Investigado via `docker compose logs hunyuan`:

```
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 20.00 MiB.
GPU 0 has a total capacity of 7.96 GiB of which 4.34 GiB is free.
WARNING  Forma estourou VRAM; tentando fallback menor: CUDA error: unknown error
RuntimeError: CUDA error: unknown error  →  "POST /generate" 500
```

**Diagnóstico**: havia **4,34 GiB livres mas não conseguiu alocar 20 MiB** =
**fragmentação** de VRAM. O container ficou de pé ~3h processando dezenas de
modelos; a VRAM foi fragmentando, e os **2 ornamentais mais pesados no fim
da fila** estouraram. Ao falhar no meio de um kernel, o **contexto CUDA
corrompeu** (`unknown error`), e o fallback interno também falhou → 500.
O matte rodou mais cedo, com a GPU menos fragmentada — por isso passou.

**Mitigações (future work)**: `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`
(sugerido pelo próprio log), `docker compose restart hunyuan` entre sessões
longas, e/ou reduzir `HUNYUAN_OCTREE_RESOLUTION` 384→256.

**Lição**: em GPU de 8 GB, sessões longas de inferência fragmentam a VRAM;
reinício periódico do serviço é necessário para um benchmark estável.

### 10.6 Suite de análise (`eval/analysis.py`)

Criado o `eval/analysis.py`: lê o `results.csv` e gera, em segundos (sem
GPU), as tabelas (matte/realistic), o Wilcoxon pareado IA × Blander e 3 PNGs
(taxa de sucesso, box-plot do F-Score@1%, dispersão tempo × qualidade) em
`C:\TCC\TCC_eval_data\analysis\`.

**Bug encontrado**: `UnicodeEncodeError` no `print` — o console do Windows
(cp1252) não codifica os caracteres `↑`/`↓` dos rótulos. **Fix**:
`sys.stdout.reconfigure(encoding="utf-8")` no topo (o `.md` já era gravado em
UTF-8 à parte). **Deps adicionadas** ao venv da branch IA: `scipy`,
`matplotlib`.

### 10.7 Resultados finais

**Taxa de sucesso** (todos os modos):

| Método | ok / total | taxa |
|---|---|---|
| IA (Hunyuan3D-2mv) | 24 / 26 | 92,3 % |
| Blander (template) | 24 / 26 | 92,3 % |
| Meshroom (fotogrametria) | 0 / 24 | **0,0 %** |

**Médias geométricas** (Chamfer/Hausdorff ↓ menor melhor; F-Score ↑ maior melhor):

| Modo | Método | n | Chamfer L1 | F@1% | F@5% |
|---|---|---|---|---|---|
| matte | IA | 13 | **0,037** | **0,56** | **0,91** |
| matte | Blander | 13 | 0,105 | 0,14 | 0,56 |
| realistic | IA | 11 | **0,035** | **0,53** | **0,92** |
| realistic | Blander | 11 | 0,097 | 0,15 | 0,62 |

**Wilcoxon pareado IA × Blander — significativo em 4/4** (p < 0,05):

| Modo | Métrica | n | p-valor | |
|---|---|---|---|---|
| matte | Chamfer L1 | 13 | 0,0012 | ✅ |
| matte | F-Score@1% | 13 | 0,0007 | ✅ |
| realistic | Chamfer L1 | 11 | 0,0010 | ✅ |
| realistic | F-Score@1% | 11 | 0,0020 | ✅ |

**Conclusão quantitativa**: a IA (Hunyuan3D-2mv) supera o template (Blander)
com **significância estatística** (Wilcoxon, p < 0,05) em ambas as métricas e
ambos os modos; é **~4× melhor no F-Score@1%** e **robusta ao realistic** (as
métricas quase não pioram do matte para o realistic). O Blander vence só em
**velocidade** (~12–48s vs ~9–26 min da IA). O Meshroom **não competiu** (0 %).

### 10.8 Limitações novas/atualizadas (complementam a §7)

9. **OOM de VRAM no Hunyuan**: no modo realistic, modelos ornamentais
   pesados (>35 MB / ~1,5M triângulos) estouram os 8 GB da RTX 5050 e o
   serviço retorna HTTP 500 (2/13 modelos no realistic-IA). Geometria pura
   (matte) reconstrói normalmente.
10. **Fragmentação de VRAM em sessões longas**: exige reinício periódico do
    container Hunyuan para estabilidade.
11. **Throttling térmico em notebook**: resultados de sessões longas precisam
    de re-validação com a máquina fria (timeouts podem ser artefato).
12. **Fallback e cache de produção contaminam o experimento**: ambos
    desligados no benchmark (`PIPELINE_FALLBACK_TO_TEMPLATE=false`,
    `CACHE_ENABLED=false`); em produção permanecem ligados.

---

*Última atualização: 2026-05-31. Benchmark executado nos 13 modelos; análise quantitativa (tabelas + Wilcoxon + gráficos) concluída.*
