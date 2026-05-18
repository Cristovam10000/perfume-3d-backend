"""Suite de validação experimental quantitativa.

Compara abordagens de reconstrução 3D (Blender procedural, Meshroom
fotogrametria, Hunyuan IA) em métricas geométricas e visuais reprodutíveis.

Módulos:
- `metrics.geometric`: Chamfer, Hausdorff, F-Score entre malhas/nuvens.
- `synthetic_dataset`: gera 4 vistas cardeais de um GLB de referência
  (Blender headless) para alimentar os pipelines.
- (futuro) `runners/`: invoca cada pipeline e coleta o GLB resultante.
- (futuro) `benchmark`: orquestra dataset × runners × métricas → CSV.

Uso típico:

    from app.eval.metrics import geometric
    cd = geometric.chamfer_distance(mesh_gt, mesh_pred)
    f1 = geometric.f_score(mesh_gt, mesh_pred, threshold=0.01)
"""
