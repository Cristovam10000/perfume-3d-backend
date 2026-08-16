# 09e - Aplicação de Label Real

> **O que você vai aprender neste doc**
> - Por que a label vem **da foto do usuário**, não da textura inventada pelo Hunyuan.
> - O mini-pipeline da label: escolher a região → recortar → upscale → projetar **na malha**.
> - As três origens de erro que a versão de 2026-08-06 corrigiu, cada uma medida.
> - Como o stage **degrada com segurança** quando não acha uma label (o job nunca quebra por isso).
>
> **Pré-requisitos:** [09f - Pipeline integrado](09f-pipeline-integrado.md) (stage 7) e
> [10b - Segmentação e label](10b-segmentacao-e-label.md) (o algoritmo do extractor).

Stage (7) do `IntegratedPipeline`. Recupera a parte visual mais importante do produto — a **label** — diretamente da foto do usuário, em vez de confiar na textura inventada pelo Hunyuan. A região vem da marcação do app ou do detector automático, é recortada na maior resolução disponível e projetada nas faces frontais do GLB.

## Os três defeitos corrigidos em 2026-08-06

No job `15ef21e9` (Camille) a label saiu como uma **mancha bege flutuando** na frente do frasco. Eram três problemas independentes empilhados:

| | Defeito | Correção |
|---|---|---|
| **o quê** | O recorte era um close borrado da base do frasco, não a label | Portão de conteúdo + portão de posição vertical |
| **onde** | O recorte veio da foto **lateral** — o pipeline varria as 5 fotos e ficava com a primeira aceita | Só a foto frontal é consultada |
| **como** | O decal era um plano de **4 vértices** flutuando, que não acompanhava a curvatura | Projeção nas faces reais via `project_view_texture.py --axis y_neg --window` |

Somado a isso, a marcação manual (`labelBox`) resolve a classe de frascos que nenhum detector alcança: nome gravado direto no vidro, sem região para segmentar.

## Por que não usar a textura do Hunyuan

O Hunyuan é bom para aproximar geometria, mas texto pequeno é uma tarefa ruim para geradores 3D. Em validação manual, o atlas de textura veio com ruído e texto pouco confiável (chega a "inventar" letras). Como perfume depende muito de marca, nome e legibilidade, a label precisa vir da foto do usuário.

A textura PBR inventada pelo Hunyuan continua sendo aplicada ao mesh — o decal da label apenas **sobrescreve** a região frontal sem mexer no resto da textura.

## Pipeline interno do stage

```
      SÓ a foto frontal (routing.assignments["front"])
                    |
        +-----------+-----------+
        |                       |
  labelBox do app        HomographyLabelExtractor
  (marcação manual)      (3 portões; None se reprovar)
        |                       |
        +-----------+-----------+
                    |
              caixa em pixels
                    |
                    v
        recorte na melhor resolução
        (upload original quando existe)
                    |
                    v
             label_raw.png
                    |
                    v
        LanczosLabelUpscaler (+ unsharp)
                    |
                    v
           label_upscaled.png
                    |
                    v
     caixa -> janela normalizada na silhueta
                    |
                    v
     BlenderViewTextureProjector (axis=y_neg, window)
        (recebe refined.glb do stage 6)
                    |
                    v
        with_label.glb  → próximo stage
```

Se não houver região confiável — ou se a marcação cair fora da silhueta — o stage **degrada**: devolve `refined.glb` e o job conclui normalmente, com o motivo na `message` quando é uma marcação inválida.

> Não há mais fallback por recorte central/direito. Ele produzia um retângulo arbitrário do corpo do frasco e projetá-lo no GLB é pior do que não projetar nada.

### Por que só a foto frontal

A label vive na frente e a projeção usa o eixo `-Y`. Varrer as outras vistas só pode gerar falso positivo — e gerou: no Camille, os scores por foto foram

| foto | melhor score | altura na silhueta | o que era |
|---|---|---|---|
| `01_front` | 0,484 (reprovado) | 0,22 | a tampa |
| `02_left` | **0,855** | 0,82 | base lisa do vidro |
| `03_back` | 0,831 | 0,82 | base lisa do vidro |
| `04_right` | 0,862 | 0,83 | base lisa do vidro |

O laço parava na primeira foto acima do limiar, então venceu a lateral. Restringir à frontal já elimina o caso: a frontal não produz candidato aprovado.

## Detecção por região (2026-08)

A implementação anterior procurava quadriláteros nos contornos de um mapa de bordas **Canny dilatado**. Medido nas fotos reais dos 6 jobs do projeto: **0 detecções em 25 fotos**.

A causa é que `contourArea` de um contorno de traço mede a área do **risco** (~3 px de espessura), não a região que ele delimita. O maior candidato ficava em 0,03%–1,0% da máscara, contra um mínimo exigido de 5%.

Os 12 testes unitários passavam porque a entrada era um retângulo branco perfeito sobre fundo preto (`cv2.rectangle(..., thickness=3)`), onde o Canny fecha o contorno e a área bate. **O teste validava a premissa do código, não a realidade.** Dois deles ainda chamavam `pytest.skip(...)` quando a detecção falhava, convertendo falha real em "pulado".

A implementação atual usa **regiões preenchidas**:

1. Ensemble de binarizações — Otsu em duas polaridades (placa clara sobre corpo escuro e vice-versa) mais fechamentos morfológicos de 15 e 31 px, que unem letras soltas num bloco.
2. Cada região vira candidato; um score 0..1 combina área, proporção, centralização e retangularidade.
3. `cv2.minAreaRect` dá os 4 cantos — sempre 4, ao contrário de `approxPolyDP`, que só às vezes fecha em quadrilátero.

### Resultado medido

| Frasco | Antes | Depois |
|---|---|---|
| La vivacité (placa prateada) | não detectava | **detecta, score 0,78** |
| La vivacité 2ª captura | não detectava | **detecta, score 0,78** |
| ASAD (texto + medalhão) | não detectava | rejeitado (score 0,73 < 0,75) |
| Feeling Sexy (script diagonal) | não detectava | rejeitado |
| GRAND ×2 (texto no vidro) | não detectava | rejeitado |

**2 de 25 fotos**, ambas no único frasco com placa física real. O default `min_score=0.75` é deliberadamente conservador: projetar um recorte errado é pior do que não projetar. Frascos com texto impresso direto no vidro não têm região para extrair, e devolver None neles é o comportamento correto.

## Os três portões (2026-08-06)

O score original é **puramente geométrico** — área, proporção, centralização, retangularidade. Uma superfície lisa pontua igual a uma placa impressa, e foi assim que a base do vidro do Camille (0,86) venceu a placa real da vivacité (0,78). Dois portões novos medem coisas que a forma não vê.

### 1. Posição vertical

Label vive no corpo. Candidato com centro fora de **0,30 – 0,92** da altura da silhueta é rejeitado.

Sem esse corte, a tampa transparente da vivacité (altura 0,10) vencia a label real dela (0,53): o Otsu enxerga ali o azulejo do fundo **através** do vidro, e aquilo tem bordas de sobra.

### 2. Conteúdo

Medido no ROI do candidato vencedor: variância do laplaciano ≥ **250** *e* densidade de bordas Canny ≥ **0,06**. Impressão gera alta frequência; vidro e plástico lisos não.

| candidato | densidade de bordas | laplaciano | é label? |
|---|---|---|---|
| La vivacité, placa com texto | 0,115 | 1833 | **sim** |
| vivacité, tampa transparente | 0,129 | 1427 | não — cortado pela posição |
| Camille, lateral (vidro liso) | 0,014 | 60 | não |
| Camille, traseira (vidro liso) | 0,032 | 96 | não |
| Camille, direita (vidro liso) | 0,010 | 28 | não |

Quinze vezes de margem no laplaciano entre a placa real e o vidro liso. Os dois sinais são exigidos juntos porque um brilho especular isolado infla só o laplaciano.

O portão roda **uma vez**, no candidato vencedor: se o melhor não tem detalhe, nenhum dos piores teria.

### 3. Resultado nas 54 fotos reais

Rodando o extrator corrigido em todas as fotos dos 12 jobs do projeto, **sobrevivem exatamente 2 candidatos** — as duas capturas da La vivacité, ambas na placa metálica correta. Todos os falsos positivos do Camille desapareceram.

## Nitidez da label

Três ganhos, nenhum com dependência nova.

**Recorte na resolução original.** A detecção roda na preprocessada (barata), mas o warp final busca os pixels no upload. Medido: Camille tem upload de 6120×8160 contra 1536×2048 preprocessada — **4× linear, 16× em pixels** que se jogava fora. `cv2.imread` aplica o EXIF, igual ao preprocessador, e a escala é validada nos dois eixos antes de usar (proporção diferente ⇒ cai para a preprocessada, porque um fator não-uniforme deslocaria o recorte).

**`target_width` virou piso, não teto.** Antes o warp saía sempre em 1024 px, então pixels reais eram descartados para depois serem reinventados pelo Lanczos. Agora usa o que existe, até o teto de 2048.

**Unsharp mask** no `LanczosLabelUpscaler`, aplicado só nos canais de cor (o alpha é preservado, senão a borda do recorte serrilha).

## Projeção na malha, não em plano flutuante

O decal era um plano de 4 vértices posto à frente do frasco. Num corpo curvo isso lê como **adesivo colado**, e foi o que apareceu no Camille.

A label passou a usar o mesmo `project_view_texture.py` do topo e do verso, no eixo novo `y_neg`, com um argumento novo `--window u0,v0,u1,v1`:

- **Seleção de faces**: normal·(-Y) ≥ threshold **e** centro da face dentro da janela.
- **UV**: normalizado pela **janela**, não pela bbox das faces coletadas. As faces dentro da janela nunca a preenchem exatamente (a malha é discreta), e normalizar por elas esticaria a label alguns por cento a cada job.

A janela vem da caixa em pixels convertida para a bounding box da silhueta na máscara — com `v` invertido, porque em foto o `y` desce e no mundo o `z` sobe.

Medido na La vivacité: **16.302 faces** recebem a label, contra 4 vértices do plano antigo.

### Roda também em frasco de vidro

Diferente do verso, que é pulado em vidro para não matar a transmissão: a janela limita a projeção à placa, e placa de perfume é opaca na vida real — a La vivacité é exatamente isso, placa metálica sobre vidro.

## Lanczos vs Real-ESRGAN

| Opção | Vantagem | Custo |
|---|---|---|
| Lanczos | Instantâneo, determinístico, usa Pillow já presente no backend | Não inventa detalhe fino |
| Real-ESRGAN | Pode melhorar 2-4x a nitidez aparente | ~2GB de dependências, ~30s por label, novo container/modelo |

Lanczos foi escolhido por pragmatismo para o TCC. Se a label extraída já tem mais de 200 px no lado maior, a ampliação para 2048 px preserva leitura melhor que deixar a textura da IA. O código deixa a troca aberta via `LabelUpscaler`.

## Componentes

### `LabelUpscaler`

Implementações:

- `DisabledLabelUpscaler`: copia byte-a-byte.
- `LanczosLabelUpscaler`: redimensiona preservando aspect ratio, com lado maior default de 2048 px.

Contrato:

```python
await upscaler.upscale(input, output, target_size=2048)
```

### Projetor

`app/modules/captures/label_projector.py` e `blender_scripts/project_label.py` foram **removidos**. A label usa `ViewTextureProjector` com `axis="y_neg"` e `window` — o mesmo componente do topo e do verso. `LABEL_PROJECTOR_TYPE=disabled` continua desligando o stage.

`LABEL_FRONT_AXIS` virou chave legada (não lida). A convenção "frente = `-Y`" agora mora no dicionário `EIXOS` de `project_view_texture.py`.

## Marcação manual (`labelBox`)

Campo opcional do `POST /captures`: `x,y,w,h` normalizados em `[0,1]` **relativos à foto inteira**, não à silhueta — o app não tem a máscara, quem sabe onde o frasco está é o backend.

Quando vem, o detector nem roda. É o caminho para os frascos que nenhum algoritmo resolve: nome gravado direto no vidro, sem região para segmentar.

Validação no router (422 em qualquer violação): 4 componentes numéricos, dentro de `[0,1]`, lado mínimo de 2%, e `x+w ≤ 1` / `y+h ≤ 1`. Persistido em `capture_jobs.label_box`.

No app é opcional e não trava o envio — a marcação fica numa seção própria da tela de captura, habilitada depois que a foto frontal existe. Trocar a foto frontal **limpa** a marcação: as coordenadas são de uma foto específica, e mantê-las projetaria a label em qualquer lugar.


## Encaixe no `IntegratedPipeline`

| Posição | Entradas | Saída | Falha |
|---|---|---|---|
| Stage (7) | `refined.glb` + fotos preprocessadas + máscaras | `with_label.glb` (ou cópia de `refined.glb` se não achou label) | Degrade silencioso: copia `refined.glb` para o output e marca no log. Nunca aborta o job. |

## Persistência no cache

Quando o pipeline conclui com sucesso, o `ClipSimilarityCache.store(...)` (stage 8) persiste:

- O GLB final em `storage/cache/<id>.glb`.
- O caminho da `label_upscaled.png` em `modelos_3d_universais.label_path` (opcional — usado para audit/debug).
- O embedding CLIP das fotos pré-processadas.

Num cache hit subsequente, o GLB cacheado já contém a label projetada; o stage (7) é totalmente pulado.

## Limitações

- **O detector automático só acha placa física.** Frascos com o nome impresso direto no vidro (GRAND, Camille) não têm região distinta para extrair e são corretamente rejeitados — é para eles que existe a marcação manual.
- O `min_score=0.75` rejeita o medalhão do ASAD (0,73). É um emblema real da marca, mas não é a label; a margem é apertada e frascos com emblemas circulares grandes podem passar. O portão de conteúdo não ajuda aqui: um medalhão em relevo *tem* alta frequência.
- O portão de conteúdo pode reprovar uma placa real fotografada fora de foco. A falha é segura (não projeta), mas o caminho é remarcar à mão.
- Labels muito pequenas na foto continuam limitadas, mesmo com o recorte no original.
- A projeção não resolve geometria errada; ela melhora legibilidade da label.

## Quando trocar por Real-ESRGAN

Os três ganhos de nitidez descritos acima vieram primeiro justamente para adiar essa decisão. Substituir Lanczos passa a valer quando, **depois deles**, a placa ainda não estiver legível.

Caminho aprovado: o binário standalone `realesrgan-ncnn-vulkan` chamado por subprocess — mesmo padrão de integração do Blender —, plugado na ABC `LabelUpscaler` existente (`LABEL_UPSCALER_TYPE=realesrgan`). **Evitar o pacote pip** `realesrgan`/`basicsr`: ele depende de uma API do `torchvision` que não existe mais nas versões usadas aqui.

Custo a aceitar: ~2 GB de modelo e ~30 s por job.

## Uso manual

Smoke completo (cobertura legada — `scripts/smoke_phase5.py`):

```powershell
cd C:\TCC\perfume-3d-backend
.\.venv\Scripts\python.exe scripts\smoke_phase5.py C:\imagens_Novas --hunyuan-wait-seconds 900 --max-images 6 --open
```

Reusar o GLB cru já gerado, sem chamar Hunyuan de novo:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_phase5.py C:\imagens_Novas --reuse-raw --open
```

Usar uma label já recortada manualmente:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_phase5.py C:\imagens_Novas --label-image C:\tmp\label.png --open
```

Artefatos em `storage/smoke/`:

- `label_raw.png`
- `label_upscaled.png`
- `raw.glb`
- `cleaned.glb`
- `refined.glb`
- `with_label.glb`

Viewer estático:

```text
http://localhost:8000/model_viewer.html?src=%2Fsmoke%2Fwith_label.glb
```

## Leituras relacionadas

- [09b - Pipeline IA: Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md)
- [09c - Refinamento de Malha](09c-refinamento-mesh.md)
- [09d - Pré-processamento e Cleanup](09d-preprocessamento-e-cleanup.md)
- [09f - Pipeline integrado](09f-pipeline-integrado.md) (composição completa)
- [09g - Cache de similaridade CLIP](09g-cache-similaridade-clip.md) (persistência do `with_label.glb`)
- [10b - Segmentação e extração de label](10b-segmentacao-e-label.md) (algoritmo do `LabelExtractor`)
- Código:
  [`app/modules/captures/label_upscaler.py`](../app/modules/captures/label_upscaler.py),
  [`app/modules/captures/label_projector.py`](../app/modules/captures/label_projector.py)
- Script Blender:
  [`app/modules/captures/blender_scripts/project_label.py`](../app/modules/captures/blender_scripts/project_label.py)
- Smoke histórico:
  [`scripts/smoke_phase5.py`](../scripts/smoke_phase5.py)
