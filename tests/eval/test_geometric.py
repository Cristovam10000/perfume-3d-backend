from __future__ import annotations

import numpy as np
import pytest
import trimesh

from eval.metrics import geometric


# ----------------------------------------------------------------- helpers


def _unit_cube_mesh() -> trimesh.Trimesh:
    return trimesh.creation.box(extents=(1.0, 1.0, 1.0))


def _unit_sphere_mesh(subdivisions: int = 3) -> trimesh.Trimesh:
    return trimesh.creation.icosphere(subdivisions=subdivisions, radius=1.0)


def _shifted_cube(dx: float) -> trimesh.Trimesh:
    m = _unit_cube_mesh()
    m.apply_translation([dx, 0, 0])
    return m


# --------------------------------------------------------- chamfer_distance


class TestChamferDistance:
    def test_identical_meshes_returns_near_zero(self):
        cube = _unit_cube_mesh()
        cd = geometric.chamfer_distance(cube, cube, n_samples=5000)
        # Não é EXATAMENTE 0 porque a amostragem é estocástica, mas amostras
        # de uma mesma malha são densas o suficiente para ficar ~1e-3.
        assert cd < 0.05

    def test_increases_with_distance(self):
        cube = _unit_cube_mesh()
        far = _shifted_cube(dx=2.0)

        # Sem normalização, distância maior = CD maior
        cd_close = geometric.chamfer_distance(
            cube, _shifted_cube(0.5), normalize_meshes=False, n_samples=5000
        )
        cd_far = geometric.chamfer_distance(
            cube, far, normalize_meshes=False, n_samples=5000
        )
        assert cd_far > cd_close

    def test_symmetric(self):
        cube = _unit_cube_mesh()
        sphere = _unit_sphere_mesh()
        a_b = geometric.chamfer_distance(cube, sphere, n_samples=5000, seed=42)
        b_a = geometric.chamfer_distance(sphere, cube, n_samples=5000, seed=42)
        # Não é EXATAMENTE simétrico pq seed=42 amostra diferente em cada chamada,
        # mas valores devem ser comparáveis (tolerância de 20%).
        assert abs(a_b - b_a) / max(a_b, b_a) < 0.2

    def test_normalize_makes_scales_comparable(self):
        small = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
        large = trimesh.creation.box(extents=(10.0, 10.0, 10.0))

        cd_norm = geometric.chamfer_distance(small, large, normalize_meshes=True)
        # Cubo pequeno vs cubo grande, após normalizar, devem ser quase idênticos.
        assert cd_norm < 0.05

    def test_squared_penalizes_outliers(self):
        # Cria duas malhas com a mesma média de distância mas perfis diferentes:
        # - A: cubo + outro cubo a 0.5 (outlier moderado, uniforme)
        # - B: cubo + cubo a 1.0 (outlier forte, mesma quantidade de área)
        cube = _unit_cube_mesh()
        moderate = trimesh.util.concatenate(
            [cube, _shifted_cube(0.5)]
        )
        strong = trimesh.util.concatenate(
            [cube, _shifted_cube(2.0)]
        )

        cd_l1_mod = geometric.chamfer_distance(
            cube, moderate, squared=False, normalize_meshes=False, n_samples=5000
        )
        cd_l2_mod = geometric.chamfer_distance(
            cube, moderate, squared=True, normalize_meshes=False, n_samples=5000
        )
        cd_l1_strong = geometric.chamfer_distance(
            cube, strong, squared=False, normalize_meshes=False, n_samples=5000
        )
        cd_l2_strong = geometric.chamfer_distance(
            cube, strong, squared=True, normalize_meshes=False, n_samples=5000
        )

        # L2 amplifica mais o aumento do outlier que L1.
        ratio_l1 = cd_l1_strong / cd_l1_mod
        ratio_l2 = cd_l2_strong / cd_l2_mod
        assert ratio_l2 > ratio_l1


# -------------------------------------------------------- hausdorff_distance


class TestHausdorffDistance:
    def test_identical_meshes_returns_small(self):
        cube = _unit_cube_mesh()
        hd = geometric.hausdorff_distance(cube, cube, n_samples=5000)
        # Hausdorff é PIOR caso, então sempre maior que CD médio, mas
        # ainda pequeno entre amostras de uma mesma malha (~0.05 norm).
        assert hd < 0.15

    def test_sensitive_to_local_outliers(self):
        cube = _unit_cube_mesh()
        # Cubo principal + um pequeno cubo "blob" longe simula fragmento flutuante
        # do Hunyuan. Concatena para gerar uma malha real com área amostrável.
        blob = trimesh.creation.box(extents=(0.2, 0.2, 0.2))
        blob.apply_translation([5.0, 0.0, 0.0])
        outlier_mesh = trimesh.util.concatenate([cube, blob])

        hd_clean = geometric.hausdorff_distance(
            cube, cube, normalize_meshes=False, n_samples=5000
        )
        hd_outlier = geometric.hausdorff_distance(
            cube, outlier_mesh, normalize_meshes=False, n_samples=5000
        )
        # Outlier a 5 unidades deve dominar — hd_outlier >> hd_clean.
        # Mesma malha vs mesma malha: hd_clean ~ 0.05 (densidade de amostra).
        # Com blob a 5 unidades: hd_outlier > 4.5 (distância do blob ao cubo).
        assert hd_outlier > 4.0
        assert hd_outlier > hd_clean * 10


# ------------------------------------------------------------------- f_score


class TestFScore:
    def test_identical_meshes_returns_one(self):
        cube = _unit_cube_mesh()
        f1 = geometric.f_score(cube, cube, threshold=0.05, n_samples=5000)
        assert f1 > 0.95

    def test_disjoint_meshes_returns_low(self):
        cube_a = _shifted_cube(0)
        cube_b = _shifted_cube(10)  # Muito longe
        # Sem normalização para preservar a distância real
        f1 = geometric.f_score(
            cube_a, cube_b, threshold=0.5, normalize_meshes=False, n_samples=5000
        )
        assert f1 < 0.1

    def test_threshold_must_be_positive(self):
        cube = _unit_cube_mesh()
        with pytest.raises(ValueError):
            geometric.f_score(cube, cube, threshold=0.0)
        with pytest.raises(ValueError):
            geometric.f_score(cube, cube, threshold=-0.1)

    def test_higher_threshold_higher_score(self):
        cube_a = _unit_cube_mesh()
        cube_b = _shifted_cube(0.1)
        f_tight = geometric.f_score(
            cube_a, cube_b, threshold=0.01, normalize_meshes=False, n_samples=5000
        )
        f_loose = geometric.f_score(
            cube_a, cube_b, threshold=0.5, normalize_meshes=False, n_samples=5000
        )
        assert f_loose >= f_tight


# --------------------------------------------------------------- compute_all


class TestComputeAll:
    def test_returns_bundle_with_all_metrics(self):
        cube = _unit_cube_mesh()
        result = geometric.compute_all(cube, cube, n_samples=5000)

        assert isinstance(result, geometric.GeometricMetrics)
        assert result.n_samples == 5000
        assert result.chamfer_l1 >= 0
        assert result.chamfer_l2 >= 0
        assert result.hausdorff >= 0
        assert 0 <= result.f_score_001 <= 1
        assert 0 <= result.f_score_005 <= 1

    def test_consistent_with_individual_functions(self):
        """compute_all deve dar os mesmos valores que as funções individuais
        quando a seed é a mesma — confirma que não há dupla amostragem com
        seeds diferentes."""
        cube = _unit_cube_mesh()
        sphere = _unit_sphere_mesh()

        bundle = geometric.compute_all(cube, sphere, n_samples=5000, seed=42)
        cd_solo = geometric.chamfer_distance(cube, sphere, n_samples=5000, seed=42)
        hd_solo = geometric.hausdorff_distance(cube, sphere, n_samples=5000, seed=42)
        f001_solo = geometric.f_score(
            cube, sphere, threshold=0.01, n_samples=5000, seed=42
        )

        assert bundle.chamfer_l1 == pytest.approx(cd_solo)
        assert bundle.hausdorff == pytest.approx(hd_solo)
        assert bundle.f_score_001 == pytest.approx(f001_solo)


# ------------------------------------------------------------- input handling


class TestInputHandling:
    def test_accepts_point_clouds(self):
        rng = np.random.default_rng(0)
        pts_a = rng.standard_normal((1000, 3))
        pts_b = pts_a.copy() + 0.01 * rng.standard_normal((1000, 3))

        cd = geometric.chamfer_distance(pts_a, pts_b)
        assert cd < 0.1

    def test_rejects_invalid_point_cloud_shape(self):
        bad = np.zeros((100, 2))  # falta z
        cube = _unit_cube_mesh()
        with pytest.raises(ValueError, match="shape"):
            geometric.chamfer_distance(bad, cube)

    def test_accepts_path_string(self, tmp_path):
        cube = _unit_cube_mesh()
        out = tmp_path / "cube.glb"
        cube.export(out)
        cd = geometric.chamfer_distance(str(out), cube)
        assert cd < 0.05
