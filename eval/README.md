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
│   └── geometric.py            # Chamfer, Hausdorff, F-Score
├── blender_scripts/
│   └── render_cardinal_views.py    # Renderiza 4 vistas de um GLB
├── synthetic_dataset.py        # Wrapper Python p/ Blender headless
├── held_out_dataset.py         # Loader + validador do manifest
├── benchmark.py                # Orquestrador (dataset × branches → CSV)
├── RUN_BENCHMARK_CONTRACT.md   # Interface CLI de run_benchmark.py
├── WORKTREE_SETUP.md           # Como configurar as 3 worktrees
└── README.md                   # este arquivo
```

Diretórios externos relevantes:

```
back/assets/templates/normalized/   ← dataset IN-DISTRIBUTION (atenção ao bias!)
C:\TCC\TCC_eval_data\held_out\      ← dataset HELD-OUT (comparação justa)
C:\TCC\TCC_eval_data\outputs\       ← GLBs reconstruídos por branch
C:\TCC\TCC_eval_data\results.csv    ← saída final do benchmark
```

> **Importante**: o held-out vive em `C:\TCC\TCC_eval_data\` por decisão
> do projeto (2026-05-21). Está **fora do repo git** (o git só rastreia
> o `back/`), então sem risco de commit acidental. Worktrees Blander e
> Meshroom (que ficam em `C:\TCC_blander\` e `C:\TCC_meshroom\`) precisam
> da env var `TCC_EVAL_DATA_ROOT=C:\TCC\TCC_eval_data` para alcançar o
> dataset. Veja [WORKTREE_SETUP.md](./WORKTREE_SETUP.md).

## Metodologia

### Por que dois datasets

O dataset escolhido **viesa o resultado**. Se usássemos apenas os GLBs de
`assets/templates/normalized/`, o método **Blender** teria vantagem
desonesta: o `TemplateProcessor` carrega esses mesmos arquivos como ponto
de partida e só customiza cor/label. Resultado: Chamfer ≈ 0 para Blender,
não porque ele é melhor, mas porque está fazendo cópia.

Para uma comparação defensável diante de uma banca, separamos em **dois
datasets** e reportamos métricas independentes:

#### Dataset A — In-distribution (sanity check)

- **O que é**: os GLBs em `back/assets/templates/normalized/` (rectangular_basic,
  cylindrical_basic, ornamental_modernist, round_spherical, square_compact,
  feeling_rectangular_blue).
- **O que mede**: limite superior teórico do método **Blender**. É o
  cenário em que o `TemplateProcessor` está jogando em casa.
- **O que NÃO mede**: comparação justa. Hunyuan e Meshroom reconstroem do
  zero; Blender carrega o GLB pronto.
- **Por que rodar mesmo assim**: serve de sanity check (Blender deve dar
  Chamfer ≈ 0 nesses casos — se não der, há bug). E mostra o **gap**
  entre cada método e a referência sintética.

#### Dataset B — Held-out (comparação justa)

- **O que é**: ~8-10 GLBs **não vistos por nenhum método**, em
  `back/eval_assets/held_out/`.
- **Critério de seleção**:
  1. Não pode estar em `assets/templates/` (raw ou normalized).
  2. Frasco de perfume (escopo do projeto).
  3. Licença CC0 ou CC-BY (atribuição em `manifest.json`).
  4. Variedade morfológica: 2 retangulares, 2 cilíndricos, 2 ornamentais,
     2 esféricos, 2 quadrados.
- **O que mede**: comparação **legítima** entre os 3 métodos diante de
  geometrias inéditas.
- **Limitação conhecida**: o Hunyuan foi pré-treinado em milhões de
  modelos 3D da web; impossível garantir que ele nunca viu um determinado
  frasco. Mas Blender e Meshroom estão na mesma situação ("modelo novo"),
  então a comparação **entre os métodos** é justa.

Na monografia, isso vira capítulo distinto: **Tabela in-distribution** +
**Tabela held-out** + análise do gap entre os dois.

### Métricas

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

### Convenção de eixos

O script `render_cardinal_views.py` segue a convenção do Hunyuan3D-2mv:

- `front` ← câmera em `-Y` olhando `+Y` (vê a face frontal do frasco)
- `right` ← câmera em `+X`
- `back`  ← câmera em `+Y`
- `left`  ← câmera em `-X`

Se um GLB não estiver alinhado (ex: a "frente" do template está em `+X` em
vez de `+Y`), passe `rotate_z_deg=90` ao `render_synthetic_views` ou ao
script Blender. O `manifest.json` do held-out registra a rotação por
modelo, garantindo reprodutibilidade.

## Exemplo rápido

```python
from pathlib import Path
from eval.synthetic_dataset import render_synthetic_views
from eval.metrics.geometric import compute_all

# 1. Renderiza vistas sintéticas a partir de um GLB held-out
gt_glb = Path("eval_assets/held_out/perfume_001_rectangular.glb")
rendered = render_synthetic_views(
    glb_path=gt_glb,
    output_dir=Path("eval_outputs/held_out/perfume_001/"),
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
4. **ICP alignment** — antes do `compute_all`, alinhar a malha predita ao
   GT para evitar penalização por rotação aleatória do Hunyuan.
5. **Análise estatística** — `analysis.ipynb` com box-plots e teste de
   Wilcoxon pareado entre branches, separando in-distribution e held-out.

## Limitações conhecidas

- **Alinhamento**: o Hunyuan pode girar 90° em torno de Z na saída. O
  Chamfer atual penaliza isso. **TODO**: aplicar ICP antes da métrica
  (5 linhas com `trimesh.registration.icp`).
- **Apenas geometria**: cor/textura não é comparada (próximo passo:
  `metrics/visual.py`).
- **Pré-treino do Hunyuan**: foundation models viram bilhões de imagens
  durante pré-treino. Não é possível garantir disjunção total entre o
  held-out e os dados de pré-treino. Isso é **limitação inerente** a
  qualquer método baseado em foundation model e é aceito pela literatura
  (citar: GET3D, Wonder3D, Zero123 fazem o mesmo).
- **Tamanho do held-out**: 8-10 frascos é o mínimo para estatística
  decente (Wilcoxon pareado precisa de N ≥ 6 para detectar efeito médio).
  Ideal seria 20+, mas a curadoria manual no Sketchfab limita.

## Testes

```powershell
cd c:\TCC\back
.\.venv\Scripts\activate
pytest tests/eval/ -v
```

25 testes cobrem amostragem, normalização, comparações com cubo/esfera
sintéticos e mock do subprocess Blender.
