# Validação Experimental Quantitativa

Suite de avaliação que compara as três abordagens de reconstrução 3D do
projeto em métricas reprodutíveis:

| Branch | Abordagem | Diretório |
|---|---|---|
| `Blander` | Customização procedural de templates (Blender headless) | `app/modules/captures/blender_scripts/` |
| `Meshroom` | Fotogrametria clássica (Structure-from-Motion + MVS) | dedicado |
| `IA` (atual) | Multi-view diffusion (Hunyuan3D-2mv) | `app/modules/captures/` |

## Por que existe

Avaliação visual ("ficou bom") não escala e não é defensável em uma banca.
A literatura de 3D reconstruction (ShapeNet, ScanNet, Pix2Vox, etc.) usa um
conjunto consagrado de métricas geométricas e visuais. Esta suite implementa
esse conjunto adaptado ao testbed do projeto (frascos de perfume).

## Estrutura

```
back/eval/
├── metrics/
│   └── geometric.py        # Chamfer, Hausdorff, F-Score sobre nuvens de pontos
├── blender_scripts/
│   └── render_cardinal_views.py   # Renderiza 4 vistas cardeais de um GLB
├── synthetic_dataset.py    # Wrapper Python que invoca Blender headless
└── README.md
```

## Metodologia

### 1. Ground truth sintético

Para ter um valor de referência confiável, partimos de GLBs **conhecidos**
em `assets/templates/normalized/` (rectangular_basic, cylindrical_basic,
ornamental_modernist, etc.). Para cada template:

1. `synthetic_dataset.render_synthetic_views(glb)` produz 4 PNGs cardeais
   (`front.png`, `left.png`, `back.png`, `right.png`).
2. Cada pipeline recebe essas 4 imagens como input.
3. O GLB produzido pelo pipeline é comparado **com o original** via
   `metrics.geometric.compute_all(pred, gt)`.

Isso elimina ambiguidade na referência — o ground truth É o GLB que gerou
as imagens.

### 2. Métricas

| Métrica | Direção | O que captura |
|---|---|---|
| `chamfer_l1` | ↓ | Erro médio de superfície (padrão na literatura) |
| `chamfer_l2` | ↓ | Idem, penalizando outliers |
| `hausdorff` | ↓ | Pior caso local (detecta blobs/fragmentos) |
| `f_score_001` | ↑ | % de pontos dentro de 1% da diagonal (rigoroso) |
| `f_score_005` | ↑ | Idem, 5% da diagonal (tolerante) |

Todas operam em nuvens de **30k pontos** amostrados uniformemente da
superfície de cada malha. As malhas são normalizadas (centro=origem,
diagonal-bbox=1) antes da comparação, tornando frascos de tamanhos
diferentes comparáveis entre si.

### 3. Convenção de eixos

O script `render_cardinal_views.py` segue a convenção do Hunyuan3D-2mv:

- `front` ← câmera em `-Y` olhando `+Y` (vê a face frontal do frasco)
- `right` ← câmera em `+X`
- `back`  ← câmera em `+Y`
- `left`  ← câmera em `-X`

Se um GLB não estiver alinhado (ex: a "frente" do template está em `+X` em
vez de `+Y`), passe `rotate_z_deg=90` ao `render_synthetic_views` ou ao
script Blender.

## Exemplo rápido

```python
from pathlib import Path
from eval.synthetic_dataset import render_synthetic_views
from eval.metrics.geometric import compute_all

# 1. Renderiza vistas sintéticas a partir de um template conhecido
gt_glb = Path("assets/templates/normalized/feeling_rectangular_blue.glb")
rendered = render_synthetic_views(
    glb_path=gt_glb,
    output_dir=Path("eval_outputs/synthetic/feeling_blue/"),
)
# rendered.views = {"front": ..., "left": ..., "back": ..., "right": ...}

# 2. Alimenta o pipeline IA (ou Blender, ou Meshroom) com essas 4 imagens.
# 3. Recebe o GLB predito (pred_glb).
pred_glb = Path("storage/models/<job_id>.glb")

# 4. Calcula métricas contra o ground truth original
result = compute_all(pred=pred_glb, gt=gt_glb)
print(f"Chamfer L1: {result.chamfer_l1:.4f}")
print(f"Hausdorff:  {result.hausdorff:.4f}")
print(f"F-Score @ 1%: {result.f_score_001:.3f}")
print(f"F-Score @ 5%: {result.f_score_005:.3f}")
```

## Próximos passos (não implementados)

1. **Runners por branch** — `runners/{blender,meshroom,hunyuan}.py` que
   automatizam: receber 4 PNGs → executar o pipeline → entregar GLB.
2. **Benchmark orchestrator** — `benchmark.py` que itera
   `dataset × runners`, coleta tempo/VRAM/métricas, gera CSV.
3. **Métricas visuais** — `metrics/visual.py` com SSIM/LPIPS/CLIP-sim
   comparando render do pred contra render do GT (ou fotos reais).
4. **Análise estatística** — `analysis.ipynb` com box-plots e teste de
   Wilcoxon pareado entre branches.

## Limitações

- Métricas geométricas assumem que a malha predita está **mais ou menos
  alinhada** com o GT. O Hunyuan pode girar 90° em torno de Z; nesse caso,
  o Chamfer fica artificialmente alto. Solução: aplicar ICP (Iterative
  Closest Point) antes da métrica — todo, pra v2.
- Apenas geometria. Cor/textura não é comparada aqui.
- O testbed sintético não captura efeitos do mundo real (laços, vidro
  transparente, reflexos). Esses dependem de fotos reais com `metrics/
  visual.py`.

## Testes

```powershell
cd c:\TCC\back
.\.venv\Scripts\activate
pytest tests/eval/ -v
```

25 testes cobrem amostragem, normalização, comparações com cubo/esfera
sintéticos e mock do subprocess Blender.
