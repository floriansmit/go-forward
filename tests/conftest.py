"""Pytest configuration and shared fixtures for GO-Forward background tests."""
from __future__ import annotations

import json
from pathlib import Path
import pytest


def generate_mini_grdecl_text(nx: int = 3, ny: int = 3, nz: int = 2, dx: float = 100.0, dy: float = 100.0, dz: float = 50.0) -> str:
    """Generate syntactically valid Eclipse corner-point GRDECL text."""
    coord_values: list[float] = []
    for j in range(ny + 1):
        for i in range(nx + 1):
            x, y = i * dx, j * dy
            top_z, bot_z = 1000.0, 1000.0 + nz * dz
            coord_values.extend([x, y, top_z, x, y, bot_z])

    zcorn_values: list[float] = []
    for k in range(nz):
        for dk in (0, 1):
            z_layer = 1000.0 + (k + dk) * dz
            for j in range(ny):
                for dj in (0, 1):
                    for i in range(nx):
                        for di in (0, 1):
                            zcorn_values.append(z_layer)

    n_cells = nx * ny * nz
    facies_values = [1 if i < n_cells // 2 else 2 for i in range(n_cells)]
    poro_values = [0.25 if f == 1 else 0.12 for f in facies_values]
    perm_values = [500.0 if f == 1 else 20.0 for f in facies_values]

    lines = [
        "-- Miniature test GRDECL grid",
        "MAPUNITS",
        "METRES /",
        "",
        "MAPAXES",
        f"0 0 0 {nx * dx:.1f} {ny * dy:.1f} {nx * dx:.1f} /",
        "",
        "GRIDUNIT",
        "METRES /",
        "",
        f"SPECGRID\n {nx} {ny} {nz} 1 F /",
        "",
        "COORD",
    ]
    for start in range(0, len(coord_values), 6):
        lines.append(" " + " ".join(f"{v:.1f}" for v in coord_values[start : start + 6]))
    lines.append("/\n\nZCORN")
    for start in range(0, len(zcorn_values), 12):
        lines.append(" " + " ".join(f"{v:.1f}" for v in zcorn_values[start : start + 12]))
    lines.append("/\n\nACTNUM")
    lines.append(f" {n_cells}*1 /")
    lines.append("\nFACIES")
    lines.append(" " + " ".join(str(v) for v in facies_values) + " /")
    lines.append("\nPORO")
    lines.append(" " + " ".join(f"{v:.4f}" for v in poro_values) + " /")
    lines.append("\nPERM")
    lines.append(" " + " ".join(f"{v:.1f}" for v in perm_values) + " /")
    return "\n".join(lines) + "\n"


@pytest.fixture
def mini_grdecl_path(tmp_path: Path) -> Path:
    path = tmp_path / "mini_model.grdecl"
    path.write_text(generate_mini_grdecl_text(), encoding="utf-8")
    return path


@pytest.fixture
def mini_facies_config_path(tmp_path: Path) -> Path:
    config = {
        "facies_property": "FACIES",
        "facies_names": {"1": "Channel Sand", "2": "Overbank Mudstone"},
        "facies_colors": {"1": "#f28e2b", "2": "#4e79a7"},
        "facies_metadata": {
            "1": {"category": "reservoir", "tmap_enabled": True},
            "2": {"category": "non_reservoir", "tmap_enabled": False},
        },
    }
    path = tmp_path / "facies_config.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def mini_geomechanics_config_path(tmp_path: Path) -> Path:
    config = {
        "defaults": {
            "young_reference_gpa": 40.0,
            "poissons_ratio": 0.25,
            "critical_porosity": 0.40,
            "porosity_exponent": 2.0,
            "friction_coefficient": 0.6,
            "cohesion_mpa": 10.0,
            "tensile_strength_mpa": 3.0,
            "fracture_energy_j_m2": 50.0,
            "cement_factor": 2.0,
            "stress_factor": 0.1,
            "stress_reference_mpa": 20.0,
            "minimum_young_gpa": 0.01,
            "fallback_depth_datum_m": 0.0,
            "fallback_porosity_surface": 0.55,
            "fallback_compaction_coefficient_per_m": 0.00046,
            "fallback_effective_stress_gradient_mpa_per_m": 0.015,
        },
        "facies": {
            "1": {"formula": "clean_sandstone_critical_porosity", "young_reference_gpa": 45.0},
            "2": {"formula": "shale_porosity_stress", "young_reference_gpa": 25.0, "porosity_exponent": 4.0},
        },
    }
    path = tmp_path / "geomechanics_config.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def mini_tmap_pointset_path(tmp_path: Path) -> Path:
    content = """# T>Map 3D point set with attributes
VERSION 1
BEGIN HEADER
X
Y
Z
INT,Facies
INT,CellIndex
FLOAT,total_porosity_p50
FLOAT,permeability_p50
END HEADER
50.00 50.00 -1025.00 1 0 24.50 480.0
150.00 50.00 -1025.00 1 1 25.10 510.0
250.00 50.00 -1025.00 1 2 23.80 460.0
"""
    path = tmp_path / "mini_pointset_tmap_data.txt"
    path.write_text(content, encoding="utf-8")
    return path
