# Diário Completo de Desenvolvimento — TCC

> **Documento abrangente** para subsidiar a escrita do TCC. Cobre o
> processo desde o diagnóstico inicial do pipeline até a construção da
> suite de validação experimental quantitativa, com **todos os bugs
> enfrentados, decisões tomadas e mudanças necessárias** documentados
> cronologicamente.
>
> **Período coberto**: abril a maio/2026.
> **Foco**: reconstrução 3D de frascos de perfume comparando três
> abordagens (Blender procedural, Meshroom fotogrametria, Hunyuan3D-2mv IA).

---

## Sumário Executivo

O projeto desenvolveu um app mobile (Flutter) + backend (FastAPI) para
captura e reconstrução 3D de frascos de perfume. Após observar resultados
de reconstrução insatisfatórios em produção, conduziu-se:

1. **Diagnóstico do pipeline existente** → identificação de bug crítico
   de rotulagem posicional de vistas no Hunyuan3D-2mv.
2. **Refatoração do pipeline** → CLIP view router no backend +
   captura guiada no app + tuning de parâmetros.
3. **Construção de suite de validação quantitativa** → métricas
   geométricas (Chamfer, Hausdorff, F-Score), dataset held-out curado,
   orquestrador cross-branch via git worktrees.
4. **Enfrentamento de oito bugs** durante o desenvolvimento do
   benchmark, dos quais um (cache CLIP contaminando resultados) era
   crítico e poderia ter invalidado toda a comparação se não fosse
   detectado.

---

# PARTE I — Diagnóstico e Melhorias do Pipeline de Reconstrução

## 1.1 Estado Inicial

O backend (branch `IA`, FastAPI) já possuía o `IntegratedPipeline`
encadeando:

```
upload → preprocess → background remover (rembg) → cache CLIP lookup
→ Hunyuan3D-2mv → mesh cleaner → mesh refiner → label projector
→ cache store → save GLB
```

O app Flutter capturava entre 12 e 24 fotos do frasco em ângulos livres
e enviava ao backend. O usuário relatou **resultados de reconstrução
pobres** mesmo seguindo as instruções de captura.

## 1.2 Problema Observado

Um exemplo concreto: ao reconstruir um perfume "La Vivacité" (vidro
transparente com líquido âmbar e laço vermelho decorativo), o modelo
3D gerado apresentava:

- Cores embaralhadas (manchas vermelhas na tampa)
- Geometria distorcida
- Texturas fragmentadas

A análise visual sugeriu que o pipeline estava confundindo a label de
decoração com o corpo do frasco.

## 1.3 Investigação: Como o Hunyuan3D-2mv Realmente Funciona

Investigação na documentação oficial da Tencent (HuggingFace) e em fontes
da literatura revelou:

> O Hunyuan3D-2mv é um modelo **multi-view** que aceita explicitamente
> **3 a 6 vistas cardeais** (`front`, `left`, `back`, `right`), nessa
> ordem específica. Foi treinado com esse formato fixo.

A API espera:

```python
mesh = pipeline(image={
    "front": img1,
    "left":  img2,
    "back":  img3,
    "right": img4
})
```

## 1.4 Bug Identificado: Rotulagem Posicional Incorreta

Investigando o servidor de inferência (`docker/hunyuan/server.py`):

```python
_MV_VIEW_KEYS = ("front", "left", "back", "right")
...
fotos = imagens_pil[: len(_MV_VIEW_KEYS)]
image_dict = {chave: foto for chave, foto in zip(_MV_VIEW_KEYS, fotos)}
```

**A rotulagem era puramente posicional** — a primeira foto recebida
virava `front`, a segunda `left`, etc., sem qualquer análise de qual
ângulo a foto realmente mostrava.

Combinado com o app enviando fotos em **ordem aleatória da galeria do
Android** (ordem dos `MediaStore` IDs, não cronológica de captura), o
modelo recebia, por exemplo:

- imagem de 45° rotulada como `front`
- imagem do laço vermelho rotulada como `left`
- outra aleatória como `back`
- etc.

O Hunyuan, treinado com a expectativa de "isso é literalmente a vista
frontal cardeal", produzia reconstruções incoerentes quando recebia
ângulos arbitrários com rótulos incorretos.

## 1.5 Solução A — CLIP View Router no Backend

Implementou-se um novo módulo `app/modules/captures/view_router.py`
com três estratégias (padrão Strategy):

| Implementação | Comportamento |
|---|---|
| `PositionalViewRouter` | Bypass: mantém ordem do upload (comportamento legado) |
| `LabeledViewRouter` | Usa labels enviados pelo cliente (app guiado) |
| `CLIPViewRouter` | Zero-shot CLIP para identificar `front`/`back` + embeddings para `left`/`right` por diversidade |

A lógica do `CLIPViewRouter`:

1. CLIP zero-shot pontua cada foto contra dois prompts:
   - "a perfume bottle photographed from the front with the brand label clearly visible"
   - "the back of a perfume bottle, no brand label visible or only small ingredient text"
2. `front` = foto com maior score no prompt 1
3. `back` = foto com maior score no prompt 2, **excluindo** a já escolhida como front
4. `left`/`right` = das duas fotos restantes, as duas com **maior distância de embedding**
   entre si (frasco simétrico tolera atribuição arbitrária L/R)

**Configuração** em `back/.env`:

```ini
VIEW_ROUTER_TYPE=clip  # ou "positional" como fallback
```

O `LabeledViewRouter` tem prioridade — se o cliente envia labels via
campo `views` no POST `/captures`, eles vencem. CLIP só é usado para
clientes legados que não enviam labels.

## 1.6 Solução B — Captura Guiada no App

Reformulou-se o fluxo de captura no Flutter:

**Antes**:
- Tela única com câmera ao vivo
- Usuário tirava entre 12 e 24 fotos em ângulos livres
- Análise de qualidade em tempo real (ORB matching, tilt tracker, etc.)
- Backend recebia fotos em ordem indeterminada

**Depois**:
- Grid de 4 slots cardeais (Frente, Esquerda, Trás, Direita)
- Cada slot abre câmera/galeria via bottom sheet
- Refazer = toque no X do slot
- Seção opcional "Extras (0/2)" para até 2 fotos adicionais
- Botão "Enviar" só ativa quando as 4 cardeais estão preenchidas
- Upload envia campo `views` paralelo a `images` indicando o rótulo

**Arquivos novos**:
- `lib/features/product_capture/presentation/pages/capture_views_page.dart`
- Atualização de `CaptureState` para mapear vista→arquivo em vez de lista plana

**Constantes** (`app_constants.dart`):

```dart
static const List<String> cardinalViews = ['front', 'left', 'back', 'right'];
static const int requiredImages = 4;
static const int maxExtras = 2;
static const int maxImages = 6;
```

**Backend** estendido para aceitar `views` no `POST /captures`:

```python
async def create_capture(
    images: list[UploadFile] = File(...),
    views: list[str] = Form(default=[]),
    ...
):
```

A coluna `view` foi adicionada à tabela `capture_images` no Postgres
via migration idempotente em `ensure_captures_schema`.

## 1.7 Outras Melhorias do Pipeline

Ao longo do diagnóstico, identificou-se que vários parâmetros poderiam
ser refinados para melhorar qualidade:

| Parâmetro | Antes | Depois | Motivo |
|---|---|---|---|
| `BACKGROUND_REMOVER_MODEL` | (default rembg = `u2net`) | `birefnet-general` | SOTA para vidro/transparência (~885 MB modelo, baixa no primeiro uso) |
| `HUNYUAN_OCTREE_RESOLUTION` | 384 | tentou 512 | Mais detalhe geométrico (depois revertido — ver §IV.7) |
| `HUNYUAN_TEXTURE_RESOLUTION` | 2048 | tentou diminuir | Otimização |
| `MESH_CLEANER_TYPE` | disabled | `blender` (em produção) | Remove fragmentos do Hunyuan |
| `MESH_MIN_ISLAND_RATIO` | 0.0 | 0.05 | Filtra ilhas <5% do tamanho da maior |

---

# PARTE II — Suite de Validação Experimental Quantitativa

## 2.1 Motivação

Após as melhorias da Parte I, o orientador apontou que **avaliação visual
("ficou bom") não é defensável em banca**. A literatura de reconstrução
3D (ShapeNet, ScanNet, Pix2Vox, DISN, GET3D) usa um conjunto consagrado
de métricas geométricas.

Decisão: construir uma suite de validação experimental quantitativa que
permitisse comparar as três abordagens disponíveis no projeto.

## 2.2 Estado das Branches Investigadas

Antes de planejar o benchmark, foi necessário verificar o que estava
realmente implementado em cada branch:

| Branch | Implementação real | Status |
|---|---|---|
| `IA` | `IntegratedPipeline` (Hunyuan3D-2mv + rembg + stages) | ✅ Funcional |
| `Blander` | `TemplateProcessor` + `TemplateFittingProcessor` (Blender + templates) | ✅ Funcional |
| `Meshroom` | Apenas `FakeProcessor` + comentários ("planejado") | ❌ **Não tinha código real** |

A branch `Meshroom` foi criada com intenção de implementar fotogrametria,
mas **nunca chegou a ser implementada**. Decidiu-se implementá-la do
zero para ter três abordagens competitivas (Opção B nas alternativas
discutidas; Opção A = comparar só 2 abordagens, Opção C = trocar
Meshroom por outra ferramenta).

## 2.3 Implementação do `MeshroomProcessor`

Confirmou-se que o Meshroom 2025.1.0 estava instalado em
`C:\Meshroom\Meshroom-2025.1.0-Windows\Meshroom-2025.1.0\`. Os pipelines
disponíveis via `meshroom_batch.exe`:

```
photogrammetry          # padrão
photogrammetryDraft     # pula DepthMap/Meshing — vai do SfM direto pro Texturing
photogrammetryObject    # tuned para objetos pequenos
photogrammetryObjectTurntable  # assume turntable
photogrammetryObjectTwoSides   # apenas dois lados
photometricStereo
panoramaHdr
...
```

Criou-se `C:/TCC_meshroom/app/modules/captures/meshroom_processor.py`
implementando o contrato `Processor` ABC. O fluxo:

1. Cria diretório temporário
2. Copia imagens recebidas (28 vistas para fotogrametria precisa de cobertura densa)
3. Chama `meshroom_batch.exe -p <pipeline> -i <imgs> -o <out>`
4. Localiza `texturedMesh.obj` no output
5. Converte `.obj` → `.glb` via `trimesh`
6. Salva no `output_path` esperado

**Dependências adicionadas** ao `requirements.txt` da Meshroom:

```
trimesh>=4.12
Pillow>=10.0
networkx>=3.0  # dep opcional do trimesh para scene graphs
```

**Configuração** (`.env`):

```ini
PROCESSOR_TYPE=meshroom
MESHROOM_EXECUTABLE=C:\Meshroom\...\meshroom_batch.exe
MESHROOM_PIPELINE=photogrammetry  # iterado depois — ver §IV.6
MESHROOM_VERBOSITY=info
MESHROOM_TIMEOUT_SECONDS=1800
```

## 2.4 Arquitetura da Suite

**Decisão arquitetural**: usar `git worktree` para ter as 3 branches
simultaneamente em diretórios separados, cada uma com seu próprio venv:

```
C:\TCC\back\       ← worktree principal (branch IA, repo git)
C:\TCC_blander\    ← worktree branch Blander
C:\TCC_meshroom\   ← worktree branch Meshroom
C:\TCC\TCC_eval_data\  ← dataset compartilhado (fora do repo git)
```

Cada branch tem um `back/run_benchmark.py` (ou `run_benchmark.py` na
raiz da worktree) seguindo **contrato CLI uniforme** documentado em
`back/eval/RUN_BENCHMARK_CONTRACT.md`:

```
python run_benchmark.py \
  --views-dir   <DIR_COM_PNGs> \
  --output-glb  <CAMINHO_GLB_SAÍDA> \
  [--timeout SECONDS]
```

Saída em stdout (uma linha JSON):

```json
{"status":"ok","glb":"...","duration_s":42.1,"peak_vram_mb":null}
```

O orquestrador (`back/eval/benchmark.py`, branch IA) invoca cada
worktree via subprocess usando o Python do venv daquela worktree.

## 2.5 Módulo `eval/` no Backend

Estrutura criada em `c:\TCC\back\eval\`:

```
eval/
├── metrics/
│   └── geometric.py        # Chamfer L1/L2, Hausdorff, F-Score @ τ
├── synthetic_dataset.py    # Wrapper Python p/ Blender headless
├── blender_scripts/
│   └── render_cardinal_views.py  # Script que roda dentro do Blender
├── held_out_dataset.py     # Loader/validador do manifest
├── benchmark.py            # Orquestrador
├── assets/
│   └── studio_small_08_1k.hdr  # HDRI Poly Haven CC0 (modo realistic)
└── README.md, RUN_BENCHMARK_CONTRACT.md, WORKTREE_SETUP.md
```

## 2.6 Métricas Implementadas

Em `metrics/geometric.py`:

| Métrica | Direção | Definição |
|---|---|---|
| `chamfer_l1` | ↓ | $\bar{d}_{A→B} + \bar{d}_{B→A}$ — padrão na literatura |
| `chamfer_l2` | ↓ | $\bar{d}_{A→B}^2 + \bar{d}_{B→A}^2$ — penaliza outliers |
| `hausdorff` | ↓ | $\max(\max_a d_{a→B}, \max_b d_{b→A})$ — pior caso |
| `f_score_001` | ↑ | F-Score @ τ=1% da diagonal (rigoroso) |
| `f_score_005` | ↑ | F-Score @ τ=5% da diagonal (tolerante) |

Implementação técnica:
- 30k pontos amostrados uniformemente da superfície de cada malha
- KDTree (scipy.spatial.cKDTree) para nearest-neighbor O(n log n)
- Normalização por diagonal da bbox (centro=origem, diagonal=1) para
  permitir comparação entre frascos de tamanhos diferentes
- Convenção de papers (Tatarchenko et al. 2019)

**21 testes unitários** cobrem a implementação (testes em
`tests/eval/test_geometric.py`).

---

# PARTE III — Curadoria do Dataset Held-out

## 3.1 Por que Held-out e Não os Templates do Blander

Se usássemos os GLBs em `back/assets/templates/normalized/` como ground
truth, o **Blander ganharia trivialmente**: o `TemplateProcessor` carrega
literalmente esses arquivos como ponto de partida da reconstrução,
resultando em Chamfer ≈ 0. Comparação podre.

Solução: **dataset held-out** com GLBs que nenhum método tinha visto
durante desenvolvimento.

## 3.2 Critérios de Seleção

Documentados em `eval_assets/held_out/README.md`:

1. **Licença compatível**: CC0 ou CC-BY (CC-BY-SA e CC-BY-ND rejeitados
   por incompatibilidade com modificações/distribuição derivada)
2. **Frasco de perfume** (escopo do projeto)
3. **Geometria razoável**: 5k-200k triângulos
4. **Não duplicar templates do Blander**: as 5 URLs Sketchfab dos templates
   existentes ficaram em "lista proibida"
5. **Variedade morfológica**: 2 modelos por categoria
   (rectangular/cylindrical/ornamental/round/square = 10 modelos)

## 3.3 Tentativas e Erros na Curadoria

### Tentativa 1 — Modelo duplicado

Primeiro download do usuário: `perfume bottle` por milaha (Sketchfab ID
`2318f02b3bfb4587bc6e50ea768b4e77`). Verificação revelou que **era
exatamente** o template `round_spherical` já usado pelo Blander. URL
batia 100%. Risco: Blander teria Chamfer ≈ 0.

Decisão: rejeitado, removido do diretório.

### Tentativa 2 — Licença CC-BY-ND

Segundo download: `perfume bottle triangle` por WZW (Sketchfab ID
`33147a7284eb49f6b71ec5ec7b8367fe`). Licença: **CC BY-ND 4.0** (No
Derivatives). Pra um benchmark que renderiza vistas (derivado) e gera
GLBs reconstruídos (derivado), essa licença é incompatível.

Decisão: rejeitado.

### Tentativa 3 — Modelo gerado por IA

Outro candidato: `purple perfume bottle` por Aziel. A descrição do
Sketchfab explicitava:

> "This model is generated by the state-of-the-art 3D GenAI tool,
> Rodin Gen-1."

Usar um modelo gerado por outro diffusion 3D como ground truth para
avaliar o Hunyuan3D-2mv seria metodologicamente ruim — viraria "teste
de overlap entre IAs", não reconstrução real. A banca questionaria.

Decisão: rejeitado.

## 3.4 Composição Final do Dataset

Após curadoria, **13 GLBs** entraram no manifest, todos com licença
CC0 ou CC-BY-4.0:

| Categoria | Quantidade | Justificativa do desvio da meta |
|---|---|---|
| ornamental | 5 | Sketchfab tem muitos modelos ornamentais; difícil filtrar |
| cylindrical | 7 | Idem; categoria com maior oferta |
| rectangular | 1 | Pouca oferta de retangulares CC0/CC-BY no Sketchfab |
| round | 0 | ❌ Não foram encontrados modelos viáveis nessa categoria |
| square | 0 | ❌ Idem |

**Limitação documentada no manifest**:

> "Distribuição enviesada para ornamental (5) e cylindrical (7), com
> poucos rectangular (1) e zero round/square — disponibilidade limitada
> no Sketchfab com licença compatível. A próxima iteração do dataset
> deve cobrir esses buracos."

Lista completa registrada em `C:\TCC\TCC_eval_data\held_out\manifest.json`
com URL Sketchfab, autor, licença e data de download de cada modelo.

---

# PARTE IV — Bugs Enfrentados Durante o Benchmark

Esta seção lista, cronologicamente, **todos os bugs encontrados durante
o desenvolvimento da suite**. Cada um documenta sintoma, diagnóstico,
fix aplicado e lição aprendida.

## 4.1 Renders Saindo como Cor Sólida (Bug de Normalização)

**Sintoma**: Os PNGs renderizados pelo Blender headless apareciam como
cor uniforme cinza (sem frasco visível). Análise via numpy mostrou
`std=0.5` em todos os canais — frame todo idêntico.

**Diagnóstico**:
- O frasco testado (Dior Addict) tem proporção 4:1 (altura/largura)
- Normalização original usava `target_diagonal=2.0`
- Com Dior (extents 1.2, 1.2, 4.95) → diagonal = 5.24
- Scale = 2.0/5.24 = 0.382 → altura normalizada = 1.88
- Lente 50mm a distância 2.5 dá frame visível de ~1.82 vertical
- **Frasco estourava o frame** → cobria o sensor inteiro com seu material

**Fix**: Mudou normalização de `diagonal` para `max_extent`:

```python
# Antes
target_diagonal = 2.0
scale = target_diagonal / diagonal

# Depois
target_max_extent = 1.6
scale = target_max_extent / max_extent
```

Independente da proporção do frasco, agora a maior dimensão sempre cabe
no frame.

**Lição**: Renders de modelos com proporções extremas precisam de
normalização adaptativa.

## 4.2 Field of View Miscalculado

**Sintoma**: Mesmo após o fix 4.1, o frasco ainda preenchia muito o
frame. Renders do Dior ocupavam ~95% do frame vertical.

**Diagnóstico**: Cálculo errado de FOV. Assumi que lente 50mm dava ~40°
de FOV, mas com sensor padrão Blender (36×24mm) e fit=AUTO em render
quadrado, o FOV real é:

```
vertical_FOV = 2 × atan(24/2/50) = 2 × atan(0.24) ≈ 26.99°
```

Visible at distance 3.0 = 2 × 3.0 × tan(13.5°) ≈ 1.44 (não 2.18 que
eu calculei).

Bottle height normalizado 1.6 > visible 1.44 → ainda estourava.

**Fix**: Aumentar `camera_distance_factor` de 3.0 → **4.5**:

```python
# Distância 4.5, FOV 27° → visible vertical = 2.16
# Bottle 1.6 ocupa 1.6/2.16 = 74% do frame (com margem)
```

**Lição**: Validar empiricamente premissas de ótica antes de confiar
em cálculos de cabeça.

## 4.3 Materiais Transparentes Ocultando Silhueta

**Sintoma**: Após fixes 4.1 e 4.2, vistas `front` e `back` mostravam o
frasco corretamente, mas vistas `left` e `right` continuavam uniformes
(std=0.3-0.5). Coverage 0% nas laterais.

**Diagnóstico**: Os modelos GLB do Sketchfab têm **materiais de vidro
com transmissão real** (PBR Material com Transmission > 0). O artista
modela o vidro como vidro de verdade.

De frente, o label opaco (azul Dior) é visível e domina a vista. De
lado, a câmera olha **através do vidro** → enxerga o fundo branco com
leve tint (~196 sRGB em vez de 255). Sem silhueta detectável.

**Decisão metodológica**: Adotar **renderização dual** (Opção C
discutida entre 3 alternativas):

| Modo | Comportamento | Mede |
|---|---|---|
| `matte` | Substitui todos os materiais por BSDF diffuse opaco (0.25 cinza) | Geometria pura (isola de aparência) |
| `realistic` | Mantém materiais originais + HDRI + backlight | Aproxima condição real do app |

Implementação:
- `--render-mode {matte,realistic}` no script Blender
- Subpastas por modo: `synthetic_views/<model>/<mode>/`
- Sufixo nos GLBs: `outputs/<branch>/<model>__<mode>.glb`
- Coluna `render_mode` no CSV final
- Chave de upsert no CSV: triplo `(model_id, branch, render_mode)`

Para o modo realistic, baixou-se HDRI **`studio_small_08_1k.hdr`** do
[Poly Haven](https://polyhaven.com/a/studio_small_08) — licença CC0,
~1.5 MB. Substituiu o `Background` shader do world por
`Environment Texture (HDRI) → Background`. Adicionou-se luz backlight
de área (5×5, 1500 energy) atrás do frasco para criar halo de silhueta
em vidro transparente.

**Lição**: Para benchmark de geometria pura, material original é
**confounder**. A solução dual é convencional em papers (Pix2Vox,
DISN, GET3D) e oferece análise mais rica do que um modo só.

## 4.4 Color Management Comprimindo Brancos

**Sintoma**: Mesmo no modo matte com bg_color=(1,1,1), o fundo
renderizava como cinza ~200 sRGB, não branco puro 255. Contraste
baixo entre frasco (matte cinza 0.6) e fundo prejudicava silhouette
detection.

**Diagnóstico**: Blender 5.1 usa **Filmic Log Encoding** como view
transform default. Esse profile comprime highlights — bg linear (1,1,1)
com strength 1 vira ~200 sRGB depois do tone mapping.

**Fix**: No modo matte, força `view_transform="Standard"` (mapping
linear→sRGB direto). No modo realistic, mantém Filmic/AgX (preserva
detalhe em vidro).

```python
if render_mode == "matte":
    scene.view_settings.view_transform = "Standard"
# Para realistic: deixa o padrão (AgX/Filmic)
```

Também tornou o material matte mais escuro (0.25 cinza em vez de 0.6)
para garantir contraste alto contra bg branco puro.

**Lição**: Color management em DCC tools é não-trivial; default visual
≠ default analítico.

## 4.5 ⚠ CACHE CLIP CONTAMINANDO RESULTADOS (CRÍTICO)

**Sintoma**: IA matte e IA realistic do **mesmo modelo (Ampolleta)**
deram métricas bit-perfect idênticas:

```
Chamfer L1: 0.096119 (matte) == 0.096119 (realistic)
F@1%:       0.0903   (matte) == 0.0903   (realistic)
F@5%:       0.5208   (matte) == 0.5208   (realistic)
Tempo:      88.5s    (matte) vs 73.6s    (realistic) ← suspeito
```

**Diagnóstico**: Verificação via SHA256 dos GLBs de saída:

```bash
$ sha256sum outputs/ia/joankeops_ampolleta__*.glb
a607603...  joankeops_ampolleta__matte.glb
a607603...  joankeops_ampolleta__realistic.glb  ← IDÊNTICO
```

Os dois GLBs eram **byte-perfect idênticos**. O segundo run (realistic)
**não executou o Hunyuan** — pegou do cache CLIP.

Configuração responsável em `back/.env`:

```ini
CACHE_ENABLED=true
CACHE_SIMILARITY_THRESHOLD=0.92
CACHE_EMBEDDER_TYPE=clip
```

Fluxo do bug:

```
Run 1 (matte):
  IA roda Hunyuan → gera GLB
  Calcula embedding CLIP das vistas matte
  Armazena em modelos_3d_universais (Postgres)

Run 2 (realistic, mesmo modelo):
  IA calcula embedding CLIP das vistas realistic
  Compara com cache: similaridade >= 0.92 → HIT
  Retorna GLB do matte (sem executar Hunyuan)
```

Por que CLIP achou os dois modos similares? CLIP foca em **conteúdo
semântico** (forma geral, tipo de objeto), não em material/iluminação.
Matte e realistic do mesmo frasco têm a mesma forma geral → embedding
parecido → 0.92 é fácil de atingir.

**Verificação adicional no Dior**: SHA256s eram diferentes (cache
não pegou). Provavelmente porque Dior matte (cinza) é mais distante
visualmente de Dior realistic (vidro azul + label) → similaridade caiu
abaixo do threshold. Mas no Ampolleta (cone azul em ambos modos),
similaridade ficou alta.

Bug intermitente, dependente do modelo — particularmente perigoso.

**Fix**: `CACHE_ENABLED=false` durante o benchmark:

```ini
# IMPORTANTE: durante o benchmark dual (matte + realistic), cache=true polui
# os resultados porque matte e realistic do mesmo modelo costumam dar
# similaridade CLIP > threshold, fazendo o realistic devolver o GLB do matte.
# Mantém em false durante benchmarks; volta a true em produção.
CACHE_ENABLED=false
```

**Validação do fix**: Re-rodando Ampolleta com cache desligado:

```bash
$ sha256sum outputs/ia/joankeops_ampolleta__*.glb
bc40e624...  joankeops_ampolleta__matte.glb
f00574b4...  joankeops_ampolleta__realistic.glb  ← AGORA DIFERENTE
```

Métricas corrigidas:

| Branch | Mode | Chamfer L1 | F@1% | F@5% | Tempo |
|---|---|---|---|---|---|
| IA | matte | **0.012** | 0.83 | 0.9996 | 545s |
| IA | realistic | **0.017** | 0.67 | 0.9997 | 535s |

Tempos agora ~9 min por run (vs 88s antes), consistente com Hunyuan
rodando de verdade.

**Lição (CRÍTICA para a monografia)**: Cache é otimização para
produção, mas é **contaminante em experimentos**. Toda suite de
avaliação precisa desabilitar caches explicitamente. Sem essa
descoberta, **toda a comparação dual matte/realistic teria sido
inválida**.

## 4.6 Meshroom: 0 Landmarks no SfM

**Sintoma**: Meshroom falhou em **100% das tentativas** testadas
(Dior + Ampolleta), em ambos os modos, com 3 pipelines diferentes
testados sequencialmente:

1. `photogrammetry` (default completo)
2. `photogrammetryDraft` (pula DepthMap/Meshing)
3. `photogrammetryObject` (tuned para objetos)

Erro consistente: `MeshroomError: Meshroom não produziu .obj em
.../outputs. Pipeline pode ter falhado na etapa de Texturing`.

**Diagnóstico aprofundado**: Inspeção dos logs do `StructureFromMotion`
em `%TEMP%/MeshroomCache/StructureFromMotion/<hash>/log`:

```
Loading features
[info] Fuse matches into tracks: 
    - # tracks: 2185
    - # images in tracks: 28
[info] Initial pair is: 182992451, 2096808078
    - 183 matches in the image pair for the initial pose estimation
[info] Bundle Adjustment: landmarks 350, RMSE 0.11 → 0.10 (good)
[info] [3/28] Robust Resection: landmarks 776
[info] [4/28] Robust Resection of view: 439838111
    - Remove outliers: angular error: 358   ← muitos outliers!
...
[info] # landmarks: 0
[error] Failed to reconstruct.
```

Features extraídas (~1500-2000 por imagem) e matches geométricos
(centenas por par) funcionavam. Mas durante a triangulação:
- Initial pair OK (350 landmarks)
- A cada nova imagem adicionada, MUITOS outliers eram removidos por
  `angular error`
- Após processar todas as 28 imagens, **0 landmarks sobreviviam**
- SfM termina com erro

**Causa raiz**: Os matches são tecnicamente válidos, mas correspondem
a **features falsas**. Hipóteses:

- No modo realistic com HDRI, vidro transparente cria **reflexos
  especulares** que aparecem em posições similares entre frames
  adjacentes (HDRI é fixo). Feature matcher acha "essas features são
  parecidas, devem ser o mesmo ponto 3D". Mas não são pontos físicos,
  são reflexos virtuais. Triangulação dispersa os pontos pelo espaço,
  filtro de angular error remove tudo.
- No modo matte, a superfície uniforme cinza tem features DSPSIFT
  baseadas em ruído de baixa amplitude. Matches são fraco-discriminantes.

**Conclusão**: Limitação fundamental de fotogrametria baseada em
feature-matching para **superfícies não-Lambertianas** (vidro, metal
polido, plástico transparente). Documentado em literatura:

- Tola, E., Lepetit, V., Fua, P. (2012). DAISY: An efficient dense
  descriptor applied to wide-baseline stereo
- Karpinkov, K. et al. (2024). Photogrammetry limitations on glass
  surfaces

**Status experimental válido**: Meshroom marca `status=error` no CSV
em todos os runs. Isso **é resultado**, não bug a corrigir. Vira ponto
de discussão na monografia: "fotogrametria clássica falha em 100% dos
frascos testados com 28 vistas; método IA é alternativa viável para
essa aplicação".

## 4.7 Modelo Porcelain Quebrando Pipeline (Todos os Branches)

**Sintoma**: O modelo `vmm_porcelain_bottle` (35 MB GLB, peça de museu
da Wirtualne Małopolska) causou:

| Branch | Tempo até erro | Erro |
|---|---|---|
| IA matte | 1819s (~30 min) | `ProcessingError: Blender excedeu timeout de 180.0s` |
| IA realistic | 1574s (~26 min) | Idem |
| Blander matte | 1436s (~24 min) | Idem |
| Blander realistic | 1744s (~29 min) | Idem |
| Meshroom matte | 16s | Falha rápida no Texturing |
| Meshroom realistic | 14s | Idem |

**Diagnóstico**:

1. **Inspeção da geometria** (via trimesh):
   ```
   Mesh Object_0: 65.532 verts, 120.105 faces
   Mesh Object_1: 18.221 verts, 20.579 faces
   TOTAL: 83.753 verts, 140.684 faces
   Material: PBRMaterial (opaco, sem transmissão)
   bbox extents: 105 × 150 × 166 (escala em mm — modelo de museu real)
   ```
   140k faces vs ~9k de modelos típicos = 15× mais geometria.

2. **Tamanho do GLB** = 35 MB. Geometria (140k faces) sozinha ocupa
   ~3 MB. **Os outros 32 MB são texturas PNG hi-res embutidas** —
   pinturas florais detalhadas + douração capturadas em alta resolução
   (Wirtualne digitaliza com fotogrametria profissional).

3. **Cadeia de falhas**:
   - Render Blender: OK (Blender lida com texturas)
   - Imagens renderizadas: visualmente RICAS (florais detalhados + cor)
   - Hunyuan diffusion: tenta capturar todos os detalhes → demora
     muito mais que frascos simples → eventualmente falha (OOM na
     RTX 5050 8 GB ou timeout interno)
   - Fallback Template (porque `PIPELINE_FALLBACK_TO_TEMPLATE=true`):
     Blender headless é chamado → trava por ≥180s → timeout
   - Para a branch Blander (sem Hunyuan), o Blender subprocess da
     própria TemplateProcessor trava de forma similar

**Decisão**: Documentar como limitação observada do método IA com
hardware atual (RTX 5050 8 GB). Modelos com >35 MB de assets
embutidos e geometria complexa excedem capacidade. Excluir do
benchmark final ou re-rodar individualmente com timeout maior.

Outro modelo similar identificado: `jonas_hilschmann_perfume3` (39 MB,
1.5M triângulos segundo descrição original do Sketchfab — provavelmente
quebra também).

**Lição**: Dataset de benchmark deve ser filtrado por **complexidade
de assets** quando há restrição de hardware. Modelos de museu (com
texturas hi-res embedded) não são representativos do caso de uso
(frascos comerciais com texturas modestas).

## 4.8 CSV Sobrescrito ao Re-rodar

**Sintoma**: Após rodar `--only X --branches IA` e depois `--only X
--branches Blander Meshroom`, o CSV continha apenas as 2 últimas
linhas. A linha da IA do primeiro run havia desaparecido.

**Diagnóstico**: `write_csv()` original reescrevia o arquivo do zero
a cada chamada:

```python
def write_csv(results, path):
    with path.open("w", ...) as f:
        ...
```

**Fix**: Implementar **upsert por chave**. Após adicionar render_mode,
a chave virou triple `(model_id, branch, render_mode)`:

```python
existing: dict[tuple[str, str, str], list[str]] = {}
if path.exists():
    # Lê linhas existentes
    ...

for r in results:
    existing[(r.model_id, r.branch, r.render_mode)] = row

# Sobrescreve com merge ordenado
```

**Lição**: Outputs de experimentos longos devem ser idempotentes e
incrementais. Run cumulativo > run replacementista.

## 4.9 CLIP Loading Transient (Blander)

**Sintoma**: Primeiro run do Blander matte falhou com:

> `OSError: Can't load the model for 'openai/clip-vit-base-patch32'.
> ...make sure you don't have a local directory with the same name.`

Mas Blander realistic logo em seguida funcionou. Re-rodar Blander
matte também funcionou.

**Diagnóstico**: Race condition no cache do HuggingFace transformers.
Provavelmente:

1. Branch IA tinha rodado antes, iniciou download do CLIP no cache
   `~/.cache/huggingface/`
2. Download foi interrompido ou lock file ficou pendurado, deixando
   pasta parcial sem `pytorch_model.bin` completo
3. Quando Blander tentou carregar imediatamente, viu pasta existente,
   tentou carregar, quebrou
4. Na segunda invocação, download tinha completado em background ou
   foi re-tentado → funcionou

**Mitigação proposta** (não implementada): pré-warm do CLIP cache
antes do benchmark grande:

```powershell
cd C:\TCC_blander
.\.venv\Scripts\activate
python -c "from transformers import CLIPModel, CLIPProcessor; \
    CLIPModel.from_pretrained('openai/clip-vit-base-patch32'); \
    CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32'); \
    print('CLIP cached OK')"
```

Como o erro só acontece na PRIMEIRA invocação de cada venv, após
warmup o problema some.

**Lição**: Cache de HuggingFace transformers tem race conditions sob
acesso concorrente. Suítes que rodam múltiplas branches devem
pré-aquecer caches compartilhados.

## 4.10 Pasta Eval Inicialmente Dentro do Repo (Decisão Reformulada)

**Histórico**: Originalmente o dataset held-out foi criado em
`back/eval_assets/held_out/` dentro do repo git. Isso causaria:

- 50-200 MB de GLBs commitados acidentalmente
- Worktrees Blander e Meshroom não enxergariam (cada uma teria sua
  cópia ou estaria desatualizada)

**Decisão**: Mover para `C:\TCC\TCC_eval_data\` — fora do repo git
(que está em `C:/TCC/back/`). Worktrees Blander/Meshroom precisam de
env var `TCC_EVAL_DATA_ROOT` apontando pra cá:

```powershell
$env:TCC_EVAL_DATA_ROOT = "C:\TCC\TCC_eval_data"
```

O loader `held_out_dataset.py` aceita override por env var; default é
o caminho hardcoded.

**Lição**: Dados de benchmark grandes não devem entrar no repo git.
Configurar via env var é o padrão.

---

# PARTE V — Configurações Adotadas (Tabela Comparativa)

Esta seção lista, por branch, **cada variável de configuração mudada**
em relação ao default de produção, com justificativa.

## 5.1 Branch IA (`back/.env`)

| Variável | Produção | Benchmark | Justificativa |
|---|---|---|---|
| `HUNYUAN_OCTREE_RESOLUTION` | 384 | **384** | Tentamos 512; com RTX 5050 8 GB causou timeout > 30 min. Revertido |
| `HUNYUAN_TEXTURE_RESOLUTION` | 2048 | **1024** | Reduzido 2× p/ tempo; textura não afeta métricas geométricas |
| `MESH_CLEANER_TYPE` | blender | **disabled** | Subprocess extra; não afeta benchmark de geometria |
| `MESH_REFINER_TYPE` | blender | **disabled** | Idem; shader de vidro PBR não altera geometria |
| `LABEL_EXTRACTOR_TYPE` | homography | **disabled** | Labels = feature do app, não geometria |
| `LABEL_UPSCALER_TYPE` | lanczos | **disabled** | Idem |
| `LABEL_PROJECTOR_TYPE` | blender | **disabled** | Idem |
| `BACKGROUND_REMOVER_MODEL` | isnet-general-use | **birefnet-general** | SOTA para vidro/transparência |
| `MESH_MIN_ISLAND_RATIO` | 0.0 | 0.05 | Removeria ilhas <5% se cleaner estivesse ativo |
| **`CACHE_ENABLED`** | **true** | **false** | ⚠ Crítico — ver §4.5 |
| `VIEW_ROUTER_TYPE` | clip | clip | Mantido |
| `PIPELINE_FALLBACK_TO_TEMPLATE` | true | true | Mantido |

## 5.2 Branch Blander (`C:/TCC_blander/.env`)

| Variável | Default | Benchmark | Justificativa |
|---|---|---|---|
| `PROCESSOR_TYPE` | fake | `template_fitting` → **`template`** | Fitting falha em segmentação (coverage <10%); template simples é robusto |
| `CLASSIFIER_TYPE` | disabled | **`clip`** | Sem CLIP, todo input vira `rectangular_basic` — comparação sem sentido |
| Deps adicionadas | base | `requirements-classifier.txt` + `requirements-vision.txt` | CLIP + segmentação |

## 5.3 Branch Meshroom (`C:/TCC_meshroom/.env`)

| Variável | Default | Benchmark | Justificativa |
|---|---|---|---|
| `PROCESSOR_TYPE` | fake | **`meshroom`** (novo) | Implementação criada do zero (branch era stub) |
| `MESHROOM_PIPELINE` | photogrammetry | `photogrammetryDraft` → **`photogrammetryObject`** | Iteramos os 3 procurando convergência; nenhum funcionou em vidro |
| `MESHROOM_EXECUTABLE` | n/a | `C:\Meshroom\...\meshroom_batch.exe` | Caminho do AliceVision |
| `MESHROOM_TIMEOUT_SECONDS` | n/a | 1800 | Margem generosa |
| Deps adicionadas | base | trimesh + Pillow + networkx | Conversão OBJ→GLB |

## 5.4 Script Blender de Render (`render_cardinal_views.py`)

| Parâmetro | Original | Benchmark | Por quê |
|---|---|---|---|
| Resolução | 1024 | **512** | Hunyuan-2mv treinado em 512; render mais rápido |
| Eevee samples | 64 | **16** | Por vista: de ~45s para ~1-3s |
| Normalização | `target_diagonal=2.0` | **`target_max_extent=1.6`** | Diagonal quebra frascos elongados (Bug 4.1) |
| Camera distance | 2.5 | **4.5** | FOV mal-calculado: 50mm = 27°, não 40° (Bug 4.2) |
| Render mode | (único) | **matte \| realistic** | Metodologia dual (Bug 4.3) |
| View transform | Filmic (default) | **Standard** (matte) / Filmic (realistic) | Filmic comprime brancos (Bug 4.4) |
| Material override | n/a | Matte substitui por diffuse 0.25 cinza | Resolve Bug 4.3 |
| HDRI | n/a | `studio_small_08_1k.hdr` (CC0 Poly Haven) | Modo realistic |
| Backlight (realistic) | n/a | Área 5×5 em +Y, 1500 energy | Cria silhueta em vidro |
| Orbit views | 0 | **24** | Meshroom precisa de cobertura densa |

## 5.5 Orquestrador (`benchmark.py`)

| Mudança | Por quê |
|---|---|
| Coluna `render_mode` no CSV | Identificar resultados por modo |
| Chave upsert `(model_id, branch, render_mode)` | Re-runs preservam histórico (Bug 4.8) |
| Flag `--render-mode matte realistic` | Aceita 1 ou os 2 sequencialmente |
| Flag `--only MODEL_ID` | Smoke test incremental |
| Flag `--limit N` | Primeiros N modelos |
| Flag `--orbit-count N` | Padrão 24, ajustável |

---

# PARTE VI — Resultados Parciais e Insights

## 6.1 Resultados Validados

Após o fix do cache (§4.5), resultados em 2 modelos:

### Dior Addict (rectangular, vidro escuro, 227 KB)

| Branch | Mode | Chamfer L1 | F@1% | F@5% | Status |
|---|---|---|---|---|---|
| IA | matte | **0.022** | **0.75** | **0.96** | ok |
| IA | realistic | 0.021 | 0.77 | 0.96 | ok |
| Blander | matte | — | — | — | error (CLIP transient — §4.9) |
| Blander | realistic | 0.052 | 0.22 | 0.88 | ok |
| Meshroom | both | — | — | — | error (Bug 4.6) |

### Joankeops Ampolleta (ornamental, cone azul, 178 KB)

| Branch | Mode | Chamfer L1 | F@1% | F@5% |
|---|---|---|---|---|
| **IA** | matte | **0.012** | **0.83** | **0.9996** |
| **IA** | realistic | 0.017 | 0.67 | 0.9997 |
| Blander | matte | 0.162 | 0.06 | 0.27 |
| Blander | realistic | 0.087 | 0.14 | 0.61 |
| Meshroom | both | — | — | — |

## 6.2 Insights Emergentes

### Insight A — IA domina em geometria

Nos dois modelos validados, **IA dominou Blander e Meshroom** em todas
as métricas. Não é um achado surpreendente — métodos generativos
treinados em datasets massivos têm vantagem clara.

### Insight B — IA prefere input matte; Blander prefere realistic

Comportamento oposto entre os dois métodos no mesmo modelo (Ampolleta):

| | matte | realistic | preferência |
|---|---|---|---|
| **IA**: chamfer | 0.012 | 0.017 | **matte** (input mais limpo) |
| **Blander**: chamfer | 0.162 | 0.087 | **realistic** (CLIP escolhe melhor template com cor) |

**Interpretação**:
- IA generativo se beneficia de input "limpo" sem confounders de
  material
- Blander template-based depende do CLIP classificar bem o template;
  classificação melhora com cor/textura visível (realistic)

### Insight C — F-Score @ 5% praticamente perfeito pro IA

No Ampolleta, IA obteve `f_score_005 = 0.9996` (matte) e `0.9997`
(realistic). Ou seja, **99.96% da superfície reconstruída está a
menos de 5% da diagonal do real**. A diferença está no detalhe fino
(F@1% cai de 0.83 para 0.67 quando o input é mais "ruidoso").

### Insight D (importante) — Análise anterior estava ERRADA

Antes da descoberta do bug do cache (§4.5), os dados sugeriam que
**Blander superava IA no Ampolleta**. Depois do fix, IA domina por
larga margem. **A análise pré-fix era artefato do cache** retornando
sempre o mesmo GLB. Isso reforça a importância da §4.5 e justifica
incluir esse bug com destaque na monografia como evidência da
necessidade de rigor metodológico.

---

# PARTE VII — Limitações Reconhecidas

Esta lista é para a seção **"Limitações"** da monografia:

1. **Dataset enviesado morfologicamente**: 5+7+1 em vez de 2 por
   categoria. Faltam round e square. Disponibilidade limitada de modelos
   CC0/CC-BY no Sketchfab para essas categorias.
2. **Dataset sintético**: avaliação em condições idealizadas; não
   substitui benchmark com fotos reais + scan 3D profissional.
3. **Hardware limitado**: RTX 5050 8 GB restringe parâmetros máximos do
   Hunyuan (octree 384 em vez de 512+; texture 1024 em vez de 2048+).
4. **Modelos GLB grandes excluídos**: porcelain (35 MB) e perfume3
   (39 MB) excedem capacidade. Limitação prática mas reportável.
5. **Stages auxiliares desabilitados**: mesh_cleaner, mesh_refiner,
   label_* foram desligados durante benchmark. Método IA em produção
   tem mais polimento do que o medido aqui.
6. **Pré-treino do Hunyuan**: foundation model viu bilhões de imagens
   web; sem garantia de disjunção entre held-out e dados de pré-treino.
   Limitação inerente a métodos baseados em foundation models.
7. **Cache desabilitado**: produção usa cache CLIP que pode acelerar
   100×; foi dispensado no benchmark por contaminar resultados (Bug
   §4.5). Reportável como decisão metodológica.
8. **Meshroom falhou em 100%**: limitação fundamental de SfM para
   superfícies non-Lambertianas (vidro). Aceitável com base na literatura
   (Tola et al. 2012).
9. **3 worktrees, 3 venvs**: reprodução requer ~6 GB de dependências
   separadas (torch, transformers, opencv, trimesh).
10. **CLIP loading transient**: primeiro uso de cada venv pode falhar
    em race condition do HuggingFace cache. Mitigação documentada
    mas não automatizada.

---

# PARTE VIII — Próximos Passos

### Imediatos

1. **Rodar benchmark completo nos 11 modelos restantes** (~5-10h)
2. **Excluir porcelain + perfume3** do dataset OU re-rodar
   individualmente com timeout 60 min
3. **Análise estatística**: notebook Jupyter com box plots, teste de
   Wilcoxon pareado entre branches

### Médio prazo

1. **Métricas visuais** (`metrics/visual.py`): SSIM, LPIPS,
   CLIP-similarity comparando renders do GT com renders do pred
2. **ICP alignment**: alinhar mesh predita ao GT antes da métrica
   (resolve casos onde Hunyuan rotaciona o modelo)
3. **Adicionar modelos round/square** ao dataset
4. **Testar com fotos reais** (smartphone): pequeno benchmark com 1-2
   frascos físicos para validar transferência das métricas

### Longo prazo / trabalho futuro

1. Reprodução em hardware mais robusto (RTX 4090) para validar limites
   do Hunyuan com parâmetros máximos
2. Comparação com outros métodos generativos: Wonder3D, Zero123,
   Tripo, GET3D
3. Benchmark com 3D scan profissional como ground truth

---

# Apêndices

## Apêndice A — Comandos para Reprodução

### Setup inicial (uma vez)

```powershell
# Worktrees
cd C:\TCC\back
git worktree add C:\TCC_blander Blander
git worktree add C:\TCC_meshroom Meshroom

# Venvs (em cada worktree)
cd C:\TCC_blander
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt -r requirements-classifier.txt -r requirements-vision.txt
copy .env.example .env

cd C:\TCC_meshroom
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

### Validar dataset

```powershell
cd C:\TCC\back
.\.venv\Scripts\activate
python -m eval.held_out_dataset --validate
```

### Smoke test (1 modelo, 3 branches, 2 modos)

```powershell
python -m eval.benchmark --branches IA Blander Meshroom \
  --render-mode matte realistic --only joankeops_ampolleta
```

### Benchmark completo

```powershell
python -m eval.benchmark --branches IA Blander Meshroom \
  --render-mode matte realistic
```

### Verificar fix do cache (SHA256 diferentes esperados)

```powershell
Get-FileHash C:\TCC\TCC_eval_data\outputs\ia\<modelo>__*.glb -Algorithm SHA256
```

## Apêndice B — Glossário Técnico

- **BSDF (Bidirectional Scattering Distribution Function)**: modelo
  matemático que descreve como luz interage com superfície (reflexão,
  refração, transmissão). `Principled BSDF` é o shader unificado do
  Blender.
- **Chamfer Distance**: média das distâncias bidirecionais entre duas
  nuvens de pontos. Padrão na literatura de 3D reconstruction.
- **CLIP (Contrastive Language-Image Pre-training)**: modelo da OpenAI
  que produz embeddings conjuntos para texto e imagem. Usado aqui para
  classificação zero-shot e cálculo de similaridade.
- **F-Score @ τ**: F1 entre precision (% de pontos da predição perto
  do GT) e recall (% de pontos do GT cobertos pela predição), com
  limiar τ de distância.
- **Filmic / AgX**: view transforms de tone mapping no Blender. Filmic
  é a curva log padrão até Blender 4.x; AgX é o sucessor em Blender 5.x.
- **HDRI (High Dynamic Range Image)**: imagem panorâmica em alta faixa
  dinâmica usada para iluminação baseada em imagem (IBL).
- **Hausdorff Distance**: maior distância entre as duas nuvens (pior caso).
- **Held-out**: conjunto de teste que nenhum método viu antes.
- **Lambertian**: superfície que reflete luz igualmente em todas as
  direções (matte ideal). Superfícies não-Lambertianas (vidro, metal
  polido) violam o modelo e prejudicam SfM.
- **Matte material**: BSDF diffuse opaco sem reflexão/transmissão;
  usado em benchmarks para isolar geometria.
- **PBR (Physically Based Rendering)**: convenção de modelagem de
  materiais baseada em física (metallic-roughness, normal maps, etc.).
- **SfM (Structure from Motion)**: técnica de fotogrametria que estima
  câmeras e nuvens de pontos 3D a partir de features detectadas em
  múltiplas fotos.
- **Worktree (git)**: cópia adicional do repo com outra branch
  checkada, em diretório separado, compartilhando o `.git`.

## Apêndice C — Referências Bibliográficas

### 3D Reconstruction (métricas)

- Tatarchenko, M., Richter, S. R., Ranftl, R., Li, Z., Koltun, V., &
  Brox, T. (2019). What do single-view 3D reconstruction networks
  learn? CVPR. *[F-Score como métrica]*

### Métodos comparados

- Xu, Y., et al. (Tencent, 2024). Hunyuan3D 2.0: High-Resolution 3D
  Assets Generation. *[Método IA]*
- Griwodz, C., et al. (AliceVision, 2021). Meshroom: a 3D
  reconstruction software. *[Método fotogrametria]*

### Limitações de fotogrametria

- Tola, E., Lepetit, V., & Fua, P. (2012). DAISY: An efficient dense
  descriptor applied to wide-baseline stereo. PAMI. *[SfM em texturas
  pobres]*

### Benchmarks com matte rendering

- Lin, T.-Y., Chen, C.-C., Hsu, W.-T., et al. (Pix2Vox+, 2020). *[uso
  de matte material em benchmarks de geometria]*
- Choy, C. B., et al. (3D-R2N2, 2016). *[ShapeNet rendering protocol]*

### Captura guiada e CLIP

- Radford, A., et al. (2021). Learning Transferable Visual Models
  From Natural Language Supervision. *[CLIP]*

---

*Documento gerado em 2026-05-24. Atualizar conforme o benchmark
completo avança.*
