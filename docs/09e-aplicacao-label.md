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

Se a homografia não encontra uma label retangular, o pipeline tenta um fallback por recorte: escolhe a região central/direita do frasco com maior densidade de bordas. Isso cobre perfumes em que o texto é impresso direto no vidro, sem uma etiqueta retangular física. Também é possível fornecer uma label manual (caminho `label_image_path` no `modelos_3d_universais` ou via parâmetro do smoke).

Se mesmo o fallback falhar, o stage **degrada**: copia `refined.glb` para o output, sem label. O job conclui normalmente; o `message` indica "concluído sem label".

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
- Se o `LabelExtractor` não encontrar label com confidence > 0.3, o stage tenta um recorte automático central/direito; se mesmo assim falhar, roda em modo degradado e copia `refined.glb` para `with_label.glb`.
- O fallback por recorte é pragmático: funciona bem quando o texto está visível na foto frontal, mas pode trazer parte do vidro/fundo junto com a label.
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
