# 09e - Aplicação de Label Real

> **O que você vai aprender neste doc**
> - Por que a label vem **da foto do usuário**, não da textura inventada pelo Hunyuan.
> - O mini-pipeline da label: extrair (homografia) → upscale (Lanczos) → projetar (decal no Blender).
> - Como o stage **degrada com segurança** quando não acha uma label (o job nunca quebra por isso).
>
> **Pré-requisitos:** [09f - Pipeline integrado](09f-pipeline-integrado.md) (stage 7) e
> [10b - Segmentação e label](10b-segmentacao-e-label.md) (o algoritmo do extractor).

Stage final (7) do `IntegratedPipeline`. Recupera a parte visual mais importante do produto — a **label** — diretamente da foto do usuário, em vez de confiar na textura inventada pelo Hunyuan. A label extraída é upscalada e aplicada como decal frontal no GLB refinado.

## Por que não usar a textura do Hunyuan

O Hunyuan é bom para aproximar geometria, mas texto pequeno é uma tarefa ruim para geradores 3D. Em validação manual, o atlas de textura veio com ruído e texto pouco confiável (chega a "inventar" letras). Como perfume depende muito de marca, nome e legibilidade, a label precisa vir da foto do usuário.

A textura PBR inventada pelo Hunyuan continua sendo aplicada ao mesh — o decal da label apenas **sobrescreve** a região frontal sem mexer no resto da textura.

## Pipeline interno do stage

```
foto preprocessada + máscara (do stage 1 e 2)
        |
        v
HomographyLabelExtractor
        |
        v
label_raw.png
        |
        v
LanczosLabelUpscaler
        |
        v
label_upscaled.png
        |
        v
BlenderLabelProjector
   (recebe refined.glb do stage 6)
        |
        v
with_label.glb  → output_path
```

Se nenhuma região atinge `min_score`, o stage **degrada**: copia `refined.glb` para o output, sem label. O job conclui normalmente.

> Não há mais fallback por recorte central/direito. Ele produzia um retângulo arbitrário do corpo do frasco e projetá-lo no GLB é pior do que não projetar nada.

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

### `LabelProjector`

Implementações:

- `DisabledLabelProjector`: copia o GLB sem label.
- `BlenderLabelProjector`: chama Blender headless com `project_label.py`.

O script Blender:

1. Importa o GLB refinado.
2. Escolhe o corpo do frasco por maior área, preferindo material sem textura.
3. Detecta o cluster frontal usando a normal alinhada ao `front_axis`.
4. Cria `LabelMaterial` com a imagem upscalada.
5. Cria um decal planar na face frontal com UV 0..1.
6. Exporta GLB.

O decal foi escolhido porque o Hunyuan frequentemente entrega um único material texturizado para o frasco inteiro. Trocar polígonos internos por material de label poderia apagar textura útil ou depender de uma topologia instável. O decal é simples, visualmente previsível e preserva o GLB original.

## Heurística de face frontal

`front_axis` default:

```text
front_y_neg
```

O script calcula, para cada polígono, o produto escalar entre a normal em mundo e o eixo de frente. Polígonos com cosseno alto entram no cluster frontal. O threshold inicial é 0.70, com fallbacks mais permissivos para meshes irregulares.

### Restrição ao corpo (2026-08)

O cluster é limitado a **abaixo do ombro**, usando o mesmo corte de [`segment_bottle.py`](09h-segmentacao-corpo-tampa.md). Sem isso, "voltado para a frente" incluía tampa e adereços: no La vivacité o laço lateral puxava o centroide ponderado por área para a esquerda, e a `altura_face` dava 1,88 num frasco de altura 1,9 — o cluster era o frasco inteiro. O decal saía pequeno e colado na borda.

### Profundidade do decal

O decal é um plano **plano** sobre uma superfície **curva**. Com o offset fixo anterior (0,3% da diagonal), o meio do plano ficava atrás da barriga do frasco e o decal aparecia partido em manchas laterais. Agora os vértices do cluster são projetados no eixo da normal e o plano é posto à frente do ponto mais saliente.

### Altura do decal

`ExtractedLabel.vertical_position` (0=topo da silhueta, 1=base) viaja do extrator até o script via `--vertical-position`. Sem ela o decal cai no centroide do corpo — o meio do frasco —, tipicamente abaixo de onde a label realmente está. Essa informação já era calculada na detecção e estava sendo descartada.

O stdout do Blender emite:

```text
STATS:target_face_index=N,coverage_ratio=0.42
```

Isso ajuda no debug manual. Se a label aparecer na lateral ou atrás, rode o smoke com outro eixo:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_phase5.py C:\imagens_Novas --front-axis front_x_pos
```

Opções aceitas:

- `front_y_neg`
- `front_y_pos`
- `front_x_neg`
- `front_x_pos`
- `front_z_neg`
- `front_z_pos`

O `front_axis` default vem do `.env` (`LABEL_FRONT_AXIS`); o `IntegratedPipeline` repassa ao `BlenderLabelProjector`.

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

- Frascos redondos ou muito curvos podem deixar o decal parecendo plano demais.
- Labels muito pequenas na foto continuam ruins após Lanczos.
- **Só funciona com placa física.** Frascos com o nome impresso direto no vidro (Hinode GRAND) não têm região distinta para extrair e são corretamente rejeitados. Cobrir esses casos exigiria detecção de texto, não de região.
- O `min_score=0.75` rejeita o medalhão do ASAD (0,73). É um emblema real da marca, mas não é a label — a margem é apertada e frascos com emblemas circulares grandes podem passar.
- O eixo frontal pode precisar de ajuste por produto, especialmente se a ordem das fotos não seguir uma vista frontal clara.
- A projeção não resolve geometria errada; ela melhora legibilidade da label.

## Quando trocar por Real-ESRGAN

Substituir Lanczos por Real-ESRGAN passa a valer quando:

- a label extraída tem menos de 200 px no lado maior;
- a defesa/demo exige leitura de texto muito pequeno;
- houver tempo para manter container/modelo dedicado;
- o custo de ~30s por job for aceitável.

A troca deve ser feita criando outra implementação de `LabelUpscaler`, sem alterar `LabelProjector`.

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
