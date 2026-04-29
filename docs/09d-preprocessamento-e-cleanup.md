# 09d — Pré-processamento de Imagem e Limpeza de Malha

Camadas defensivas adicionadas na Fase 4 para lidar com a realidade do MVP:
fotos cruas de smartphone com iluminação ruim e GLBs do Hunyuan3D com pequenos
artefatos geométricos. Ambas seguem o padrão Strategy do módulo (ABC + bypass +
implementação real).

> **Status:** disponíveis como componentes standalone (Fase 4). Composição
> dentro do `CaptureService` chega na Fase 7.

## Onde encaixam no pipeline

```
Foto crua  ──►  ImagePreprocessor  ──►  BackgroundRemover  ──►  Hunyuan3DProcessor
                                                                       │
                                                                       ▼
                                                               GLB cru (raw.glb)
                                                                       │
                                                                       ▼
                                                                MeshCleaner  ──►  cleaned.glb
                                                                                       │
                                                                                       ▼
                                                                                BlenderMeshRefiner
                                                                                       │
                                                                                       ▼
                                                                                  refined.glb
```

## ImagePreprocessor

Corrige problemas comuns de fotos de smartphone *antes* da remoção de fundo,
para que o `BackgroundRemover` e o Hunyuan3D recebam entradas mais consistentes.

### O que faz, em ordem

| # | Etapa | Justificativa |
|---|---|---|
| 1 | EXIF auto-rotate | Fotos do iPhone/Android vêm com a tag de orientação; sem isso, frasco aparece deitado. Usa `PIL.ImageOps.exif_transpose` — solução canônica e barata. |
| 2 | White balance gray-world | Compensa tinte amarelo de luz incandescente, azul de sombra etc. Multiplica cada canal por (média_global / média_canal). Robusto, sem modelos. |
| 3 | CLAHE no canal L do LAB | Corrige sub-/superexposição local sem saturar cores. Aplicar CLAHE no RGB direto satura — em LAB, só o componente de luminância é tocado. |
| 4 | Sharpen condicional | Calcula Laplacian variance; se < `sharpen_threshold` (default 100), aplica unsharp mask. Foto já nítida não recebe sharpening (evita ruído amplificado). |
| 5 | Resize máx 2048 px | Hunyuan3D-2mv não consome mais que isso. Reduzir antes economiza VRAM e largura de banda. Mantém aspect ratio. |
| 6 | Save | PNG sem compressão se a saída terminar em `.png`; JPEG quality 95 caso contrário. |

### Parâmetros configuráveis

| Parâmetro | Default | Função |
|---|---|---|
| `white_balance` | `True` | Liga/desliga a etapa 2. Útil quando a luz já é controlada (estúdio). |
| `clahe_clip_limit` | `2.0` | Quanto mais alto, mais agressivo o CLAHE. Acima de 4.0 começa a "queimar" highlights. |
| `sharpen_threshold` | `100.0` | Variância de Laplacian abaixo disso = borrada → sharpen. Empírico: fotos de produto bem feitas dão >300, borradas dão <50. |
| `max_resolution` | `2048` | Lado maior do output. Reduzir para 1024 acelera o Hunyuan ao custo de detalhe. |

### Justificativa científica

Pré-processamento clássico (não neural) foi escolhido por três razões:

1. **Determinismo**: dois runs com a mesma foto produzem byte-igual. Importante
   para reproduzir resultados em defesa do TCC.
2. **Sem dependência de modelos**: nada para baixar, treinar ou versionar; o
   código depende só do OpenCV/Pillow.
3. **Custo computacional**: < 200 ms por foto no CPU. AWB neural ou deblur
   neural exigiriam GPU dedicada e adicionariam ~2–5 s por foto.

Onde isto falha — iluminação muito heterogênea (parte da foto na sombra forte,
parte no sol), motion blur severo (>5 px), foco fora — uma rede neural ajudaria.
Para o cenário de TCC (frasco fotografado em mesa com luz ambiente), a
heurística é defensável.

## MeshCleaner

Pós-processador entre `Hunyuan3DProcessor` e `BlenderMeshRefiner`. Remove
artefatos típicos de saída de IA: ilhas soltas (a "bolinha" de canto), furos
pequenos no topo da tampa, normais invertidas, polígonos com sombreamento flat.

### Heurística de ilhas

```
1. Separa o mesh por componentes conexos (loose parts).
2. Calcula o volume da bounding box de cada componente.
3. Encontra o maior componente.
4. Remove componentes cujo volume < min_island_ratio × maior_volume.
5. Reagrupa o que sobrou em um único objeto (join).
```

`min_island_ratio` default = 0.0 na chamada Python atual. Nesse modo o wrapper
copia o GLB byte-a-byte e nao invoca Blender. A decisao veio da validacao
manual: o Hunyuan pode gerar a superficie como milhares de "ilhas" adjacentes,
e qualquer limpeza cega (separar loose parts, preencher furos, recalcular
normais) abriu microfuros visiveis ou demorou demais em meshes reais.

Para artefatos claramente soltos, use valores baixos como 0.005 ou 0.01 em
smoke/debug. Qualquer valor maior que zero reativa o caminho Blender.

Volume de bounding box é proxy barato. Usar volume real (soma de tetraedros)
seria mais preciso, mas a diferença é inferior à variabilidade da heurística.

### Limpeza por mesh

Quando a limpeza Blender e ativada (`min_island_ratio > 0`), para cada mesh
sobrevivente:

| Etapa | Operador Blender | Comentário |
|---|---|---|
| Fechar furos | `mesh.fill_holes(sides=4)` | Só fecha furos de até 4 vértices — preserva aberturas legítimas (gargalo do frasco). |
| Recalcular normais | `mesh.normals_make_consistent(inside=False)` | Orienta todas as faces para fora; corrige sombreamento invertido. |
| Shade smooth | `object.shade_smooth()` | Suavização global. |
| Auto Smooth 30° | `object.shade_auto_smooth(angle=30°)` (Blender ≥ 4.1) | Preserva arestas vivas em quinas. |

O script **não faz remesh agressivo** (Voxel Remesh, Quad Remesher). Remesh
muda topologia inteira e perderia detalhes da label. Limpeza aqui é
conservadora.

### Stats de retorno

O wrapper Python parseia uma linha do stdout do Blender:

```
STATS:islands=N,holes=M,faces=K
```

E retorna `MeshCleanupResult(output_glb, islands_removed, holes_filled, final_face_count)`.
Útil para logs do worker e para o smoke validar que a limpeza fez algo.

## Trade-offs

| Decisão | Alternativa | Por que essa? |
|---|---|---|
| Gray-world WB | Modelo de Retinex, AWB neural | Suficiente para luz mista comum; zero dependências adicionais. |
| CLAHE em L do LAB | CLAHE em RGB | LAB preserva matiz; RGB satura cores em fotos quentes. |
| Sharpen condicional via Laplacian | Sempre aplicar unsharp | Evita ruído amplificado em fotos já nítidas. |
| Cleanup desativado por default (`min_island_ratio=0`) | Rodar Blender sempre | Preserva GLB cru do Hunyuan; evita timeout e microfuros quando a malha vem fragmentada. |
| Min-island por bbox volume | Volume real (mesh) | Disponivel quando `min_island_ratio > 0`; bbox e barato e suficiente para artefatos soltos claros. |
| `fill_holes(sides=4)` | `fill_holes(sides=8)` ou genérico | Preserva o gargalo do frasco (loop de borda grande). |
| Sem remesh | Voxel Remesh | Remesh apaga texturas e perde detalhes da label. |

## Limitações

- **Foto pré-processada não é foto de estúdio**: gray-world ainda erra em luz
  ambiente colorida (LED RGB, etc.). Para resultado profissional, usar AWB
  neural na Fase 5+.
- **`fill_holes(sides=4)` não fecha furos médios**: aberturas com 5–10 vértices
  ficam abertas. Aceitável para artefatos típicos do Hunyuan, mas não cobre
  todos os casos.
- **Heurística de ilhas usa volume de bbox**: dois objetos sobrepostos na bbox
  podem ser fundidos em um cálculo errado (raro em saídas de Hunyuan).
- **Dependência do Blender**: igual ao refiner — requer Blender 5.1+ via
  `BLENDER_EXECUTABLE`.

## Uso manual

```bash
# Pré-processamento standalone (Python):
python -c "
import asyncio
from app.modules.captures.image_preprocessor import StandardImagePreprocessor
from pathlib import Path

async def main():
    p = StandardImagePreprocessor()
    await p.preprocess(Path('foto.jpg'), Path('foto_clean.jpg'))

asyncio.run(main())
"

# Limpeza de mesh standalone (Blender direto):
blender --background --python app/modules/captures/blender_scripts/cleanup_mesh.py -- \
    --input  raw.glb \
    --output cleaned.glb \
    --min-island-ratio 0
```

Smoke completo da Fase 4 (preprocess + rembg + Hunyuan + cleanup + refiner):

```bash
python scripts/smoke_phase4.py C:\imagens_Novas --open
```

Salva os artefatos intermediários em `storage/smoke/`:

- `preprocessed/*.jpg` — fotos após pré-processamento
- `masked/*.png` — após rembg
- `raw.glb` — saída do Hunyuan
- `cleaned.glb` — após mesh cleaner
- `refined.glb` — final

Útil para abrir no model_viewer e validar etapa por etapa.

## Próximas fases

- **Fase 5**: Texture refinement / re-projection (label nítida com perspective rectification).
- **Fase 6**: Material/HDRI customizado por template.
- **Fase 7**: `CaptureService` orquestra `ImagePreprocessor` → `BackgroundRemover` →
  `Hunyuan3DProcessor` → `MeshCleaner` → `BlenderMeshRefiner`, integrando ao
  worker e às factories de `Settings`.

## Leituras relacionadas

- [09b — Pipeline IA: Hunyuan3D-2mv](09b-pipeline-ai-hunyuan.md)
- [09c — Refinamento de Malha (Shader de Vidro)](09c-refinamento-mesh.md)
- [10b — Segmentação e Label](10b-segmentacao-e-label.md)
- Código:
  [`app/modules/captures/image_preprocessor.py`](../app/modules/captures/image_preprocessor.py),
  [`app/modules/captures/mesh_cleaner.py`](../app/modules/captures/mesh_cleaner.py)
- Script Blender:
  [`app/modules/captures/blender_scripts/cleanup_mesh.py`](../app/modules/captures/blender_scripts/cleanup_mesh.py)
- Smoke:
  [`scripts/smoke_phase4.py`](../scripts/smoke_phase4.py)
