"""Métricas geométricas para comparar duas malhas 3D.

Todas as métricas operam em nuvens de pontos amostradas uniformemente da
superfície de cada malha. A amostragem normaliza diferenças de densidade
de vértices entre malhas (uma malha denso-tesselada vs. uma com poucos
triângulos não viesa o resultado).

Convenção:
- ↓ menor é melhor: chamfer_distance, hausdorff_distance, normal_consistency_error
- ↑ maior é melhor: f_score

Para que distâncias sejam comparáveis entre frascos de tamanhos diferentes,
normalizamos cada malha para diagonal-da-bounding-box = 1 antes da
amostragem (`normalize_meshes=True`, default). Isso é convenção em papers
de 3D reconstruction (ShapeNet, ScanNet).

Implementação:
- `trimesh` para carregar GLB e amostrar superfície (uniforme por área).
- `scipy.spatial.cKDTree` para nearest-neighbor (O(n log n)).
- Nada de open3d/torch — leve, sem GPU.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Union

import numpy as np
import trimesh
from scipy.spatial import cKDTree

# Tipo aceito: caminho pra GLB, Trimesh já carregado, ou nuvem de pontos (N,3).
MeshLike = Union[Path, str, trimesh.Trimesh, np.ndarray]


@dataclass(frozen=True)
class GeometricMetrics:
    """Bundle de métricas geométricas comparando malha predita vs. ground truth.

    Todas as distâncias estão em unidades **normalizadas** (diagonal da
    bbox = 1) quando o flag normalize_meshes=True foi usado. Caso contrário,
    nas unidades nativas do GLB.
    """

    chamfer_l1: float           # Σ médio das distâncias bidirecionais
    chamfer_l2: float           # Σ médio dos quadrados (penaliza outliers)
    hausdorff: float            # max(d(A→B), d(B→A))
    f_score_001: float          # F-score @ τ=0.01 (1% da diagonal)
    f_score_005: float          # F-score @ τ=0.05 (5% da diagonal)
    n_samples: int


def chamfer_distance(
    pred: MeshLike,
    gt: MeshLike,
    n_samples: int = 30_000,
    normalize_meshes: bool = True,
    squared: bool = False,
    seed: int = 0,
) -> float:
    """Chamfer Distance bidirecional entre duas malhas/nuvens de pontos.

    CD(A, B) = mean_{a∈A} min_{b∈B} d(a,b) + mean_{b∈B} min_{a∈A} d(a,b)

    Args:
        pred: malha predita (caminho, Trimesh ou nuvem (N,3)).
        gt: malha de referência (ground truth).
        n_samples: pontos a amostrar de cada superfície (mais = mais preciso,
            mais lento; 30k é padrão na literatura).
        normalize_meshes: se True, normaliza cada malha para diagonal=1
            antes de amostrar. Padrão recomendado para métricas comparáveis
            entre frascos de tamanhos diferentes.
        squared: se True, usa distâncias ao quadrado (penaliza outliers).
        seed: semente da amostragem para reprodutibilidade.

    Returns:
        Valor escalar não-negativo. 0 = nuvens idênticas.
    """
    pts_pred = _to_point_cloud(pred, n_samples, normalize_meshes, seed)
    pts_gt = _to_point_cloud(gt, n_samples, normalize_meshes, seed)

    tree_gt = cKDTree(pts_gt)
    tree_pred = cKDTree(pts_pred)

    d_pred_to_gt, _ = tree_gt.query(pts_pred, k=1)
    d_gt_to_pred, _ = tree_pred.query(pts_gt, k=1)

    if squared:
        d_pred_to_gt = d_pred_to_gt ** 2
        d_gt_to_pred = d_gt_to_pred ** 2

    return float(d_pred_to_gt.mean() + d_gt_to_pred.mean())


def hausdorff_distance(
    pred: MeshLike,
    gt: MeshLike,
    n_samples: int = 30_000,
    normalize_meshes: bool = True,
    seed: int = 0,
) -> float:
    """Distância de Hausdorff (max das min — pior caso).

    H(A, B) = max( max_{a∈A} min_{b∈B} d(a,b), max_{b∈B} min_{a∈A} d(a,b) )

    Sensível a outliers — captura o pior erro local. Útil para detectar
    "blobs flutuando" ou "buracos" que o Chamfer médio esconde.
    """
    pts_pred = _to_point_cloud(pred, n_samples, normalize_meshes, seed)
    pts_gt = _to_point_cloud(gt, n_samples, normalize_meshes, seed)

    tree_gt = cKDTree(pts_gt)
    tree_pred = cKDTree(pts_pred)

    d_pred_to_gt, _ = tree_gt.query(pts_pred, k=1)
    d_gt_to_pred, _ = tree_pred.query(pts_gt, k=1)

    return float(max(d_pred_to_gt.max(), d_gt_to_pred.max()))


def f_score(
    pred: MeshLike,
    gt: MeshLike,
    threshold: float = 0.01,
    n_samples: int = 30_000,
    normalize_meshes: bool = True,
    seed: int = 0,
) -> float:
    """F-Score @ τ — % de pontos "corretos" dentro do limiar.

    Definição (Tatarchenko et al., 2019; padrão em papers de 3D reconstruction):
        precision(τ) = |{p ∈ pred : d(p, gt) < τ}| / |pred|
        recall(τ)    = |{g ∈ gt   : d(g, pred) < τ}| / |gt|
        f1(τ)        = 2 · precision · recall / (precision + recall)

    Mais interpretável que Chamfer: "% da superfície reconstruída
    dentro de τ do real". Com normalize_meshes=True, τ=0.01 = 1% da
    diagonal — limiar comum.

    Returns:
        Valor em [0, 1]. 1 = todos os pontos dentro do limiar.
    """
    if threshold <= 0:
        raise ValueError("threshold deve ser positivo")

    pts_pred = _to_point_cloud(pred, n_samples, normalize_meshes, seed)
    pts_gt = _to_point_cloud(gt, n_samples, normalize_meshes, seed)

    tree_gt = cKDTree(pts_gt)
    tree_pred = cKDTree(pts_pred)

    d_pred_to_gt, _ = tree_gt.query(pts_pred, k=1)
    d_gt_to_pred, _ = tree_pred.query(pts_gt, k=1)

    precision = float((d_pred_to_gt < threshold).mean())
    recall = float((d_gt_to_pred < threshold).mean())
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def compute_all(
    pred: MeshLike,
    gt: MeshLike,
    n_samples: int = 30_000,
    normalize_meshes: bool = True,
    seed: int = 0,
) -> GeometricMetrics:
    """Calcula todas as métricas com uma só amostragem (3× mais rápido).

    Reutiliza os mesmos pontos e KDTrees para evitar amostrar 3 vezes.
    """
    pts_pred = _to_point_cloud(pred, n_samples, normalize_meshes, seed)
    pts_gt = _to_point_cloud(gt, n_samples, normalize_meshes, seed)

    tree_gt = cKDTree(pts_gt)
    tree_pred = cKDTree(pts_pred)

    d_pred_to_gt, _ = tree_gt.query(pts_pred, k=1)
    d_gt_to_pred, _ = tree_pred.query(pts_gt, k=1)

    cd_l1 = float(d_pred_to_gt.mean() + d_gt_to_pred.mean())
    cd_l2 = float((d_pred_to_gt ** 2).mean() + (d_gt_to_pred ** 2).mean())
    hd = float(max(d_pred_to_gt.max(), d_gt_to_pred.max()))

    def _fscore(tau: float) -> float:
        p = float((d_pred_to_gt < tau).mean())
        r = float((d_gt_to_pred < tau).mean())
        return 0.0 if (p + r) == 0 else 2 * p * r / (p + r)

    return GeometricMetrics(
        chamfer_l1=cd_l1,
        chamfer_l2=cd_l2,
        hausdorff=hd,
        f_score_001=_fscore(0.01),
        f_score_005=_fscore(0.05),
        n_samples=n_samples,
    )


# --------------------------------------------------------------- utilitários


def _to_point_cloud(
    src: MeshLike,
    n_samples: int,
    normalize: bool,
    seed: int,
) -> np.ndarray:
    """Resolve qualquer entrada para uma nuvem (N, 3) float64.

    - Path/str: carrega GLB com trimesh + amostra superfície.
    - Trimesh: amostra superfície direto.
    - ndarray (N, 3): trata como nuvem já amostrada (apenas normaliza se pedido).
    """
    if isinstance(src, np.ndarray):
        if src.ndim != 2 or src.shape[1] != 3:
            raise ValueError(
                f"Nuvem de pontos deve ter shape (N, 3); recebido {src.shape}"
            )
        pts = src.astype(np.float64)
        if normalize:
            pts = _normalize_points(pts)
        return pts

    if isinstance(src, (str, Path)):
        mesh = trimesh.load(str(src), force="mesh")
    else:
        mesh = src

    if not isinstance(mesh, trimesh.Trimesh):
        raise TypeError(
            f"Esperado Trimesh; recebido {type(mesh).__name__}. "
            "GLB pode estar vazio ou ser uma Scene multi-mesh sem geometria."
        )

    if normalize:
        mesh = _normalize_mesh(mesh)

    rng = np.random.default_rng(seed)
    samples, _ = trimesh.sample.sample_surface(mesh, n_samples, seed=rng)
    return np.asarray(samples, dtype=np.float64)


def _normalize_mesh(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    """Normaliza malha para centro=origem e diagonal-bbox = 1.

    Não modifica o input (copia primeiro). Importante: ambos os meshes
    sendo comparados precisam ser normalizados pelo MESMO critério
    (a diagonal-bbox individual), senão a comparação fica viciada por
    escala — exatamente o que queremos evitar.
    """
    mesh = mesh.copy()
    extents = mesh.bounding_box.extents
    diagonal = float(np.linalg.norm(extents))
    if diagonal == 0:
        return mesh
    mesh.apply_translation(-mesh.bounding_box.centroid)
    mesh.apply_scale(1.0 / diagonal)
    return mesh


def _normalize_points(pts: np.ndarray) -> np.ndarray:
    """Normaliza nuvem de pontos para centro=origem e diagonal=1."""
    bbox_min = pts.min(axis=0)
    bbox_max = pts.max(axis=0)
    centroid = (bbox_min + bbox_max) / 2
    diagonal = float(np.linalg.norm(bbox_max - bbox_min))
    if diagonal == 0:
        return pts - centroid
    return (pts - centroid) / diagonal
