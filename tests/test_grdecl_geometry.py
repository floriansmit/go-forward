"""Tests for GRDECL geometry extraction, cell centers, and coordinate transforms."""
from __future__ import annotations

import math
from pathlib import Path
import pytest

from scripts.grdecl_utils import grdecl_cell_centers, mapaxes_transform


def test_grdecl_cell_centers_count(mini_grdecl_path: Path):
    centers = grdecl_cell_centers(mini_grdecl_path)
    # 3 x 3 x 2 = 18 cells
    assert len(centers) == 18


def test_grdecl_cell_centers_coordinates(mini_grdecl_path: Path):
    centers = grdecl_cell_centers(mini_grdecl_path)
    # Cell (0, 0, 0): local x in [0, 100], y in [0, 100], z in [1000, 1050]
    # Local center is x=50, y=50, depth=1025 -> elevation z = -1025.0
    c0 = centers[0]
    assert c0[2] == pytest.approx(-1025.0, abs=1e-3)
    # Layer 2 cell (0, 0, 1): depth in [1050, 1100] -> elevation z = -1075.0
    c_layer2 = centers[9]  # K=1, J=0, I=0 -> index 9
    assert c_layer2[2] == pytest.approx(-1075.0, abs=1e-3)


def test_mapaxes_transform_origin_and_axes():
    # MAPAXES: point on Y-axis (0, 1000), origin (0, 0), point on X-axis (1000, 0)
    mapaxes = [0.0, 1000.0, 0.0, 0.0, 1000.0, 0.0]
    transform = mapaxes_transform(mapaxes)
    
    # Origin maps to (0, 0)
    ox, oy = transform(0.0, 0.0)
    assert ox == pytest.approx(0.0)
    assert oy == pytest.approx(0.0)
    
    # Local (100, 200) maps to (100, 200)
    tx, ty = transform(100.0, 200.0)
    assert tx == pytest.approx(100.0)
    assert ty == pytest.approx(200.0)


def test_mapaxes_transform_rotated():
    # 90-degree counter-clockwise rotated grid
    # Local X is along World +Y (0, 1000), Local Y is along World -X (-1000, 0)
    mapaxes = [-1000.0, 0.0, 0.0, 0.0, 0.0, 1000.0]
    transform = mapaxes_transform(mapaxes)
    
    # Local (100, 0) along local X -> World (0, 100)
    wx, wy = transform(100.0, 0.0)
    assert wx == pytest.approx(0.0, abs=1e-5)
    assert wy == pytest.approx(100.0, abs=1e-5)
