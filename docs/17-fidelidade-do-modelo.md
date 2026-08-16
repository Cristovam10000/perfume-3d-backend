# 17 — Fidelidade do modelo: material, foto de topo, verso e entrega

Correção de três defeitos que ficaram visíveis quando o job `3901ff83` (Lattafa Fakhar, 02/08/2026) foi o primeiro a rodar o pipeline completo — com segmentação corpo/tampa e projeção de topo já ligadas. Renderizando os três estágios (`raw.glb` → `refined.glb` → `with_top.glb`) lado a lado, os três apareceram de uma vez.

Nenhum é regressão do trabalho anterior. São defeitos antigos que só se tornaram observáveis quando o resto do pipeline passou a funcionar.

O job seguinte (`15ef21e9`, Camille, 05/08/2026) validou as três correções e expôs um quarto defeito, este na **entrega**: o modelo ficava pronto e o app não o via. Ver [Defeito 4](#defeito-4--o-modelo-ficava-pronto-e-o-produto-não-sabia).

---

## Defeito 1 — frasco opaco classificado como vidro

### Sintoma

O `refined.glb` recebeu `KHR_materials_transmission: {transmissionFactor: 1}`, `ior 1.45` e `roughness 0.05` num frasco branco opaco. O medalhão do verso, legível no `raw.glb`, virou mancha escura. **O refino piorou o modelo.**

### Causa

Não é o valor do threshold. A [auditoria](16-auditoria-blender.md#resultado-2--o-classificador-de-transparência-não-é-calibrável-só-pelo-threshold) já havia medido o `ClipTransparencyClassifier` nos 6 jobs anteriores:

```
0,072  GRAND mesa     ← é VIDRO
0,089  ASAD           ← é OPACO (único opaco da amostra)
0,146  GRAND tijolo   ← é VIDRO
0,527  Feeling        ← é VIDRO
0,82   vivacité a/b   ← é VIDRO
```

O único frasco opaco está **espremido entre dois de vidro** na reta numérica. Um threshold é um corte nessa reta; para acertar, precisaria de todo o vidro de um lado e todo o opaco do outro. Como o item mais à esquerda já é vidro, não existe posição válida:

| corte | resultado |
|---|---|
| 0,30 (era o valor em uso) | acerta ASAD, erra os dois GRAND |
| 0,10 | acerta GRAND tijolo, **passa a errar o ASAD** |
| 0,05 | acerta os dois GRAND, erra o ASAD |

Ajustar o número só troca qual frasco erra. O sinal medido é que está errado: os prompts descrevem vidro que "deixa o líquido visível" ou que "brilha quando a luz atravessa", e nada disso aparece na foto de um frasco âmbar escuro sobre uma mesa.

### Correção — o app pergunta

Campo `material` no `POST /captures`, com `glass`, `opaque` ou `auto`. Resposta explícita vence; `auto` (ou ausência) mantém o CLIP.

```
POST /captures
  material=opaque  → body_mode=keep    (CLIP não é chamado)
  material=glass   → body_mode=glass   (CLIP não é chamado)
  material=auto/—  → ClipTransparencyClassifier decide
```

`auto` colapsa para `NULL` no banco: os dois significam a mesma coisa para o pipeline, e guardar um valor só evita tratar dois casos equivalentes em toda leitura.

| camada | mudança |
|---|---|
| [`router.py`](../app/modules/captures/router.py) | `material` no form + `_normalize_material` (422 em valor desconhecido) |
| [`models.py`](../app/modules/captures/models.py) | `CaptureJob.material` (`varchar(16)`, nullable) |
| [`modelos_universais.py`](../app/modules/captures/modelos_universais.py) | `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` em `ensure_captures_schema` — **não há Alembic no projeto**, é esse o mecanismo |
| [`service.py`](../app/modules/captures/service.py) | `_JobPreparado` (a tupla de retorno virou dataclass ao chegar no 5º campo) |
| [`pipeline.py`](../app/modules/captures/pipeline.py) | `_safe_classify_transparency` curto-circuita com material explícito |

No app, um `ChoiceChip` de dois valores acima do grid de vistas. Tocar na opção marcada desmarca, voltando para `auto`. Não entra em `canSubmit` — é opcional.

### Correção secundária — o topo poluía o voto

`_safe_classify_transparency` recebia **todas** as fotos preprocessadas, incluindo a do topo. A foto de cima é tirada contra uma tampa metálica e vem cheia de reflexo — exatamente o tipo de imagem que empurra a média do ensemble para "vidro". Agora só as 4 cardeais votam, via `_fotos_cardeais`.

O mapeamento volta de `masked` para `preprocessed` pelo índice: as duas listas são paralelas por construção, e o CLIP precisa do fundo, que a máscara removeu.

---

## Defeito 2 — a foto do topo não era uma foto do topo

### Sintoma

O `05_top_*.jpg` do job era um ângulo oblíquo do frasco inteiro, com o reflexo do celular na tampa dourada. O estágio 7.5 recortou por alpha e projetou — fez exatamente o que deve fazer, com a entrada errada.

O ponto que importa: **o projetor não procura a tampa dentro da foto.** Ele recorta no contorno do que não é fundo e estica esse recorte inteiro sobre as faces da tampa. Uma foto do frasco de lado não gera erro nenhum; ela vira o frasco inteiro amassado no topo do modelo.

O app **já exibia** a instrução escrita ("posicione a câmera perpendicular à tampa") e a foto saiu errada mesmo assim. Texto sozinho não resolve.

### O sinal — elongação PCA da silhueta

Razão entre os dois eixos principais dos pixels opacos da máscara. Medido nas **34 fotos reais** de todos os jobs do projeto:

| | elongação |
|---|---|
| topo correto (ASAD, perpendicular) | **1,03** |
| topo incorreto (Fakhar, oblíquo) | **2,06** |
| 32 fotos cardeais | **1,50 – 4,23** |

O corte de **1,35** fica folgado entre o topo correto e a cardeal mais compacta.

A justificativa é geométrica, não estatística: de cima o frasco apresenta a **pegada** (largura × profundidade), que é compacta; de lado apresenta o **perfil** (largura × altura), que num frasco de perfume é sempre alongado.

**Por que PCA e não a razão da bounding box:** PCA é invariante a rotação. Uma foto de perfil enquadrada a 45° tem bbox quase quadrada e passaria batido no teste da bbox; os eixos principais continuam denunciando a elongação real. Há um teste dedicado a essa propriedade em [`test_top_photo_check.py`](../tests/modules/captures/test_top_photo_check.py).

**Ressalva honesta:** há **um** exemplo positivo no projeto. O que sustenta o corte é o argumento geométrico mais o fato de o modo de falha ser seguro — reprovar apenas pula um estágio opcional.

### Correção

[`top_photo_check.py`](../app/modules/captures/top_photo_check.py), numpy + PIL puros (sem `bpy`), para ser importável e testável fora do Blender. `_safe_apply_top` mede antes de invocar o projetor e, ao reprovar, pula o estágio e registra o motivo.

O aviso viaja até a `message` do job em vez de morrer no log:

```
Modelo gerado via Hunyuan3D-2mv a partir de 5 imagem(ns) — foto de topo
ignorada (elongação 2.06; fotografe a tampa de cima, perpendicular)
```

A lista de avisos é **local do `process()`**, não estado da instância: o pipeline é construído uma vez e compartilhado entre jobs.

Falha ao abrir ou medir **aprova**. A guarda protege contra foto oblíqua, não é um validador de arquivo; reprovar por não conseguir medir transformaria um problema de leitura em perda silenciosa de funcionalidade.

No app, um comparativo visual certo/errado ao lado do slot — duas silhuetas, uma compacta e uma alongada. É a mesma forma que o backend mede, então a orientação comunica o critério em vez de descrevê-lo.

---

## Defeito 3 — o verso do frasco era inventado

### Sintoma

A foto de costas do job está **correta**: mostra o relevo de escamas e a tampa esférica texturizada, completamente diferente da frente. Mesmo assim o `raw.glb` pintou o medalhão da frente no verso.

### Causa — confirmada no log do container

[`docker/hunyuan/server.py`](../docker/hunyuan/server.py), função `_texturizar_com_fallback`. O log do `tcc-hunyuan-1` mostra o mesmo comportamento em **todas as execuções** — 23/07 (duas) e 02/08:

```
INFO    Montando entrada multi-view com 4 vista(s): ['front','left','back','right']
INFO    Tentando texturizacao multi-view com 4 imagem(ns), texture=1024...
WARNING Textura multi-view indisponivel/falhou; usando primeira vista:
        'list' object has no attribute 'mode'
```

`Hunyuan3DPaintPipeline` (repo `tencent/Hunyuan3D-2`) aceita **uma** imagem de referência. Passar uma lista quebra em `.mode`, o `except Exception` engole e cai em `imagens_pil[0]` — a foto da frente.

E o log de carga do container mostra `texturemultiview_modelunet (UNet2p5DConditionModel)`: o pipeline **sintetiza** as outras vistas a partir da referência única. O verso não é copiado por engano — é **alucinado por projeto**, que é o comportamento normal de um modelo generativo.

> **Geometria vem de 4 vistas. Textura vem de 1.** Vale para todo modelo já gerado neste projeto.

### Correção — projetar a foto real

Trocar o palpite pelo pixel medido. É a mesma operação que já funcionava na tampa, em outro eixo — por isso a correção foi generalizar o script existente em vez de escrever um novo.

Trocar um modelo generativo por outro não resolveria: o defeito **é** uma IA inventando o que não viu. Nós temos a fotografia do verso; o que falta é copiá-la para os triângulos certos, o que é aritmética, não inferência.

**Escopo: só o verso.** A frente já é fiel (é a referência única que o Hunyuan usou) e as laterais deste formato de frasco são estreitas.

#### Generalização

| antes | depois |
|---|---|
| `blender_scripts/project_top_texture.py` | [`project_view_texture.py`](../app/modules/captures/blender_scripts/project_view_texture.py) com `--axis {z_pos,y_pos}` |
| `top_projector.py` | [`view_texture_projector.py`](../app/modules/captures/view_texture_projector.py) com `axis` no input |

Para cada eixo, a tabela `EIXOS` define a direção da normal, quais coordenadas de mundo viram `(u, v)`, se o `u` inverte e qual faixa de altura é o alvo.

**Convenção de eixos:** frente é `-Y` (`FRONT_AXES["front_y_neg"]` em `project_label.py`), logo **verso é `+Y`**.

#### Duas armadilhas encontradas rodando de verdade

**1. Espelhamento.** Olhando o frasco de trás para a frente, o `+X` do mundo aparece à **esquerda** do observador — igual a olhar alguém de costas, cuja mão direita está do seu lado esquerdo. Sem inverter o `u`, o verso sai espelhado. Está no `inverter_u` do eixo `y_pos`.

**2. A extensão da foto tem que casar com a extensão das faces.** A projeção estica a imagem inteira sobre o alvo, então:

- **topo**: a foto mostra só a tampa → alvo só acima do ombro (`faixa="acima"`)
- **verso**: a foto mostra o frasco inteiro → alvo é o frasco inteiro (`faixa="tudo"`)

A primeira versão restringia o verso ao corpo, por analogia com o topo. O resultado medido: a tampa da foto caiu sobre a parte de cima do corpo e o relevo escorregou para baixo. O corte no ombro serve ao topo por um motivo específico, não é uma regra geral.

#### Bug antigo descoberto no caminho

Ao dar UV explícito à nova projeção, o GLB antigo revelou o problema:

```
with_top.glb (versão anterior)
  TopTextureMaterial: baseColorTexture={'index': 2}     ← sem texCoord = 0
  TEXCOORD_0 = UV original do Hunyuan
  TEXCOORD_1 = TopProjectionUV
```

Sem um nó `UV Map` explícito no material, o exportador glTF grava `texCoord: 0` — **o decal do topo estava amostrando o UV original do Hunyuan**, e toda a matemática da projeção era descartada. O material agora nomeia sua camada:

```
com_costas_e_topo.glb (atual)
  Material_0:          baseColorTexture={'index': 0}                  ← UV original
  BackTextureMaterial: baseColorTexture={'index': 2, 'texCoord': 1}   ← BackProjectionUV
  TopTextureMaterial:  baseColorTexture={'index': 3, 'texCoord': 2}   ← TopProjectionUV
```

#### O estágio no pipeline

`_safe_apply_back` entra como **(7.4)**, entre o rótulo e o topo. A cadeia fica `refined → with_label → with_back → with_top`.

Consome `routing.assignments["back"]`, que já é a versão **mascarada** — o roteamento roda sobre `masked`, então o alpha para o recorte já existe.

**Só roda em frasco opaco** (`body_mode == "keep"`). Num frasco de vidro o verso é visto *através* da frente, e colar uma foto opaca ali mataria a transmissão — o resultado seria pior do que o palpite do gerador. As duas correções se compõem: com o defeito 1 resolvido, essa decisão passa a ser confiável.

---

## Defeito 4 — o modelo ficava pronto e o produto não sabia

### Sintoma

No job `15ef21e9` (Camille) o usuário gerou o molde a partir de um produto do estoque. O job concluiu, o GLB de 73,5 MB foi para o disco — e a tela do produto continuou mostrando a ilustração vetorial genérica, sob um selo verde escrito "3D disponivel".

### Diagnóstico

```
capture_jobs         status=completed, product_id=11, model_path preenchido  ✓
modelos_3d_produto   0 linhas                                                ✗
produtos.possui_modelo_3d (Camille)   false                                  ✗
```

O `/sales` faz `LEFT JOIN modelos_3d_produto` e devolve `caminho_arquivo_modelo` como `modelo_3d_path`. Sem linha, o campo vem nulo e o app cai no placeholder.

O UPSERT em `modelos_3d_produto` morava **dentro do `ModelCache.store()`**. O `.env` tem `CACHE_ENABLED=false` (desligado de propósito para não poluir benchmark), o que faz `build_model_cache` devolver `DisabledModelCache`, cujo `store()` é no-op. Resultado: **desligar o cache desligava, junto e em silêncio, o salvamento do modelo no produto.**

### Correção

Persistir o modelo do produto não é trabalho do cache. O vínculo passou para `CaptureRepository.vincular_produto()`, chamado de `CaptureService._mark_completed()` — o único ponto por onde todo job concluído passa, com cache ligado, desligado ou em hit. Também liga `produtos.possui_modelo_3d`.

Transação própria, antes do status: se o vínculo falhar (produto apagado no meio do job), o GLB continua válido e o job conclui mesmo assim, com o motivo na `message` em vez de sumir no log. Falhar dentro da mesma transação do status deixaria o job preso em `processing`.

### Segundo defeito, latente, encontrado junto

O `_upsert_modelo_produto` gravava `str(glb_path)` — um caminho de disco, tipo `C:\TCC\...\storage\cache\<uuid>.glb` — numa coluna que o app resolve como **URL** (`AppConstants.resolveBackendUrl`). Nunca tinha aparecido porque o cache nunca rodou. Teria quebrado no instante em que `CACHE_ENABLED` virasse `true`.

Agora as duas escritas usam `model_public_path(job_id)` (`/files/models/<job>.glb`). Vale inclusive em cache hit, porque o pipeline copia o GLB cacheado para `storage/models/<job>.glb` antes de concluir. O `modelo_universal_id` fica de fora do UPDATE do service — essa coluna é do cache, que roda antes.

### No app

O selo "3D disponivel" era `const`, renderizado sempre. Passou a seguir `produto.modelo3DPath != null`, mostrando "Sem modelo 3D" em âmbar quando não há.

---

## Testes

| arquivo | cobre |
|---|---|
| [`test_top_photo_check.py`](../tests/modules/captures/test_top_photo_check.py) | elongação de silhuetas sintéticas, invariância a rotação, degradação segura |
| [`test_view_texture_projector.py`](../tests/modules/captures/test_view_texture_projector.py) | argumentos por eixo, validação, tradução de falha |
| [`test_glb_optimizer.py`](../tests/modules/captures/test_glb_optimizer.py) | quantização repassada, saída ausente, bypass copia sem comprimir |
| [`test_preview_renderer.py`](../tests/modules/captures/test_preview_renderer.py) | resolução repassada, PNG ausente, bypass sinaliza por exceção |
| [`test_pipeline.py`](../tests/modules/captures/test_pipeline.py) | material curto-circuita o CLIP, topo rejeitado, verso por `body_mode`, GLB entregue é o comprimido, falha em compressão/preview degrada |
| [`test_service.py`](../tests/modules/captures/test_service.py) | vínculo produto→modelo independe do cache, preview persistido, `COALESCE` preserva o preview anterior |
| [`test_router.py`](../tests/modules/captures/test_router.py) | `material` válido / inválido / ausente / `auto` |

O comportamento geométrico não é testável sem Blender; foi verificado rodando os scripts sobre os GLBs reais dos jobs `3901ff83` e `15ef21e9`, inspecionando o `texCoord` do GLB resultante e comparando renders pixel a pixel.

O `vincular_produto` também foi rodado contra o Postgres real — os testes usam SQLite, que não pega diferenças de dialeto no `ON CONFLICT`.

---

## Peso do arquivo — compressão Draco

O GLB chegou a **77 MB** no job `15ef21e9`, baixado pelo celular por Wi-Fi a cada abertura do produto. Medindo onde estavam os bytes:

| | raw.glb | with_top.glb |
|---|---|---|
| vértices | 389.733 | 1.583.847 (4,06×) |
| triângulos | 530.544 | 530.546 (iguais) |
| POSITION | 4,7 MB | 19,0 MB |
| NORMAL | ausente | 19,0 MB |
| TEXCOORD_0 | 3,1 MB | 12,7 MB |
| TEXCOORD_1 | ausente | 12,7 MB |
| imagens | 4,7 MB | 7,4 MB |

Malha = 90% do arquivo. O estágio 7.9 (`optimize_glb.py`) comprime com `KHR_draco_mesh_compression`:

```
original .................... 77,08 MB
reexportado sem mudança ..... 77,08 MB   (a ida e volta pelo Blender é neutra)
sem normais ................. 58,07 MB
Draco ....................... 13,92 MB   ← 5,5×
Draco + sem normais ......... 12,99 MB
```

**Perda: nenhuma medível.** Render do comprimido contra o do original nas 10 vistas do showcase: RMS **0,549** numa escala de 0–255 (0,2%), com 0,13–0,20% dos pixels diferindo mais de 2 níveis. `extents` e contagem de faces idênticos.

### Duas otimizações medidas e descartadas

Ambas estavam registradas aqui como "cabe fazer". A medição mostrou que não cabe:

- **Remover as normais** economiza 0,9 MB depois do Draco. Mas a malha não é toda plana — 510.207 de 530.544 polígonos são flat, ~20 mil são suavizados. Sem o atributo, o visualizador calcula normais planas e o sombreamento desses 20 mil muda. Não vale 0,9 MB.

- **Limitar o `TEXCOORD_1` às faces que o usam.** A camada é escrita para a malha inteira, inclusive o corpo (1,38M vértices), que não a amostra — 12,7 MB de dado morto **no arquivo sem compressão**. Depois do Draco custa **48 bytes**: `d_draco.glb` = 13.924.452 bytes com a camada, `f_draco_uv_limpo.glb` = 13.924.404 bytes sem ela. O codificador reduz um atributo praticamente constante a quase nada. Separar a malha por material para eliminar 48 bytes não paga o risco de mexer no grafo de cena.

> A versão anterior deste documento estimava "~10 MB de dado morto" no `TEXCOORD_1` e recomendava limitá-lo. O número estava certo para o arquivo sem compressão; com Draco ligado, a recomendação deixa de fazer sentido.

### O decodificador precisa ser local

`KHR_draco_mesh_compression` exige que o visualizador carregue um decodificador WASM. O `model-viewer` empacotado no `model_viewer_plus` busca em `https://www.gstatic.com/draco/versioned/decoders/1.5.6/` — **na internet**. Numa rede local sem saída (laboratório, sala de apresentação) o GLB comprimido não abriria: falha pior que o arquivo grande que a compressão veio resolver.

Por isso o backend versiona os três arquivos em `assets/draco/` e os serve em `/draco/`, e o app redireciona o decodificador via `relatedJs` (`AppConstants.dracoRelatedJs`). Custo: ~1 MB baixado uma vez, cacheado pelo WebView.

---

## Preview do card do produto

`modelos_3d_produto.caminho_imagem_preview` existia desde o schema original e **nunca era preenchida**: o `/sales` a devolvia como `previewImg`, o app já a lia no modelo, e ela era sempre nula — o card caía num gradiente genérico da cor do frasco. Faltava só quem gerasse a imagem.

O estágio 7.95 (`render_preview.py`) renderiza o GLB final em EEVEE e grava `storage/models/<job>.png`. Decisões:

- **Fundo transparente**, para o PNG assentar sobre a cor do card sem moldura branca.
- **Sem HDRI** — mundo em gradiente por nodes e quatro area lights. Evita depender de `eval/assets/*.hdr`, que é material de benchmark, e deixa o resultado determinístico.
- **Ângulo de catálogo** (3/4, 12° de elevação), enquadrando ~80% da altura.
- **Opcional por contrato**: falhar aqui não reprova um job cujo GLB ficou pronto; o card volta ao gradiente.

No UPSERT, `caminho_imagem_preview` usa `COALESCE(EXCLUDED..., modelos_3d_produto....)`: se o primeiro job rendeu preview e o segundo falhou nesse estágio, o card mantém o render antigo em vez de regredir.

---

## Configuração

| variável | default | efeito |
|---|---|---|
| `GLB_OPTIMIZER_TYPE` | `blender` | `disabled` entrega o GLB sem comprimir |
| `GLB_POSITION_QUANTIZATION` | `14` | bits por eixo (~6 µm num frasco de 10 cm) |
| `GLB_TEXCOORD_QUANTIZATION` | `12` | bits por eixo de UV |
| `PREVIEW_RENDERER_TYPE` | `blender` | `disabled` deixa o card no visual genérico |
| `PREVIEW_RESOLUTION` | `512` | lado do PNG quadrado |

---

## Fora de escopo (registrado, não corrigido)

- ~~**A label pode ser um falso positivo.**~~ **Corrigido em 2026-08-06** — ver [09e](09e-aplicacao-label.md#os-três-defeitos-corrigidos-em-2026-08-06). Eram três defeitos empilhados: o recorte errado (score puramente geométrico, resolvido com portões de conteúdo e de posição), a foto errada (varria as 5 vistas; agora só a frontal) e o plano flutuante de 4 vértices (agora projeção nas faces reais). Somou-se a marcação manual `labelBox`, para os frascos com texto gravado no vidro que nenhum detector alcança.
- **`HUNYUAN_TEXTURE_RESOLUTION` é configuração morta.** O log diz `texture-single nao aceita texture_resolution; omitindo` em toda execução.
- **`ProcessingResult.message` conta imagens erradas.** Usa `len(masked)` (inclui o topo) enquanto o Hunyuan recebeu só as 4 cardeais.
