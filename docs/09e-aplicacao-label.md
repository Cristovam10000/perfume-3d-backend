# 09e - Aplicacao de Label Real

Fase 5 adiciona uma etapa para recuperar a parte visual mais importante do
produto: a label. A textura gerada pelo Hunyuan pode inventar texto, borrar
detalhes ou espalhar ruido no atlas. Em vez de confiar nessa textura, o backend
usa a label extraida da foto real e aplica no GLB como decal frontal.

> **Status:** componentes standalone. A composicao dentro do service/factories
> continua fora de escopo nesta fase.

## Por que nao usar a textura do Hunyuan

O Hunyuan e bom para aproximar geometria, mas texto pequeno e uma tarefa ruim
para geradores 3D. Em validacao manual, o atlas de textura veio com ruido e texto
pouco confiavel. Como perfume depende muito de marca, nome e legibilidade, a
label precisa vir da foto do usuario.

## Pipeline

```
foto preprocessada + mascara
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
        |
        v
with_label.glb
```

Se a homografia nao encontra uma label retangular, o smoke tenta um fallback por
recorte: escolhe a regiao central/direita do frasco com maior densidade de
bordas. Isso cobre perfumes em que o texto e impresso direto no vidro, sem uma
etiqueta retangular fisica. Tambem e possivel fornecer uma label manual com
`--label-image caminho\label.png`.

No smoke da Fase 5, a cadeia completa fica:

```
preprocess -> rembg -> label extract -> label upscale
           -> Hunyuan -> MeshCleaner -> MeshRefiner -> LabelProjector
```

## Lanczos vs Real-ESRGAN

| Opcao | Vantagem | Custo |
|---|---|---|
| Lanczos | Instantaneo, deterministico, usa Pillow ja presente no backend | Nao inventa detalhe fino |
| Real-ESRGAN | Pode melhorar 2-4x a nitidez aparente | ~2GB de dependencias, ~30s por label, novo container/modelo |

Lanczos foi escolhido por pragmatismo para o TCC. Se a label extraida ja tem
mais de 200 px no lado maior, a ampliacao para 2048 px preserva leitura melhor
que deixar a textura da IA. O codigo deixa a troca aberta via `LabelUpscaler`.

## Componentes

### `LabelUpscaler`

Implementacoes:

- `DisabledLabelUpscaler`: copia byte-a-byte.
- `LanczosLabelUpscaler`: redimensiona preservando aspect ratio, com lado maior
  default de 2048 px.

Contrato:

```python
await upscaler.upscale(input, output, target_size=2048)
```

### `LabelProjector`

Implementacoes:

- `DisabledLabelProjector`: copia o GLB sem label.
- `BlenderLabelProjector`: chama Blender headless com `project_label.py`.

O script Blender:

1. Importa o GLB.
2. Escolhe o corpo do frasco por maior area, preferindo material sem textura.
3. Detecta o cluster frontal usando a normal alinhada ao `front_axis`.
4. Cria `LabelMaterial` com a imagem upscalada.
5. Cria um decal planar na face frontal com UV 0..1.
6. Exporta GLB.

O decal foi escolhido porque o Hunyuan frequentemente entrega um unico material
texturizado para o frasco inteiro. Trocar poligonos internos por material de
label poderia apagar textura util ou depender de uma topologia instavel. O decal
e simples, visualmente previsivel e preserva o GLB original.

## Heuristica de face frontal

`front_axis` default:

```text
front_y_neg
```

O script calcula, para cada poligono, o produto escalar entre a normal em mundo
e o eixo de frente. Poligonos com cosseno alto entram no cluster frontal. O
threshold inicial e 0.70, com fallbacks mais permissivos para meshes irregulares.

O stdout do Blender emite:

```text
STATS:target_face_index=N,coverage_ratio=0.42
```

Isso ajuda no debug manual. Se a label aparecer na lateral ou atras, rode o
smoke com outro eixo:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_phase5.py C:\imagens_Novas --front-axis front_x_pos
```

Opcoes aceitas:

- `front_y_neg`
- `front_y_pos`
- `front_x_neg`
- `front_x_pos`
- `front_z_neg`
- `front_z_pos`

## Limitacoes

- Frascos redondos ou muito curvos podem deixar o decal parecendo plano demais.
- Labels muito pequenas na foto continuam ruins apos Lanczos.
- Se o `LabelExtractor` nao encontrar label com confidence > 0.3, o smoke tenta
  um recorte automatico central/direito; se mesmo assim falhar, roda em modo
  degradado e copia `refined.glb` para `with_label.glb`.
- O fallback por recorte e pragmatico: funciona bem quando o texto esta visivel
  na foto frontal, mas pode trazer parte do vidro/fundo junto com a label.
- O eixo frontal pode precisar de ajuste por produto, especialmente se a ordem
  das fotos nao seguir uma vista frontal clara.
- A projecao nao resolve geometria errada; ela melhora legibilidade da label.

## Quando trocar por Real-ESRGAN

Substituir Lanczos por Real-ESRGAN passa a valer quando:

- a label extraida tem menos de 200 px no lado maior;
- a defesa/demo exige leitura de texto muito pequeno;
- houver tempo para manter container/modelo dedicado;
- o custo de ~30s por job for aceitavel.

A troca deve ser feita criando outra implementacao de `LabelUpscaler`, sem
alterar `LabelProjector`.

## Uso manual

Smoke completo:

```powershell
cd C:\TCC\back
.\.venv\Scripts\python.exe scripts\smoke_phase5.py C:\imagens_Novas --hunyuan-wait-seconds 900 --max-images 6 --open
```

Reusar o GLB cru ja gerado, sem chamar Hunyuan de novo:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_phase5.py C:\imagens_Novas --reuse-raw --open
```

Usar uma label ja recortada manualmente:

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

Viewer estatico:

```text
http://localhost:8000/model_viewer.html?src=%2Fsmoke%2Fwith_label.glb
```

## Leituras relacionadas

- [09b - Pipeline IA: Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md)
- [09c - Refinamento de Malha](09c-refinamento-mesh.md)
- [09d - Preprocessamento e Cleanup](09d-preprocessamento-e-cleanup.md)
- Codigo:
  [`app/modules/captures/label_upscaler.py`](../app/modules/captures/label_upscaler.py),
  [`app/modules/captures/label_projector.py`](../app/modules/captures/label_projector.py)
- Script Blender:
  [`app/modules/captures/blender_scripts/project_label.py`](../app/modules/captures/blender_scripts/project_label.py)
- Smoke:
  [`scripts/smoke_phase5.py`](../scripts/smoke_phase5.py)
