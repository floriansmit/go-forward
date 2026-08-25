"""Tests for corner-point GRDECL cropping and subgrid geometry extraction."""
from __future__ import annotations

from pathlib import Path
import pytest

from scripts.crop_grdecl import crop_coord, crop_zcorn, crop_cells, parse


def test_parse_grdecl_blocks(mini_grdecl_path: Path):
    blocks = parse(mini_grdecl_path)
    assert "SPECGRID" in blocks
    assert "COORD" in blocks
    assert "ZCORN" in blocks
    assert "ACTNUM" in blocks
    assert "FACIES" in blocks


def test_crop_cells_dimensions():
    # 3x3x2 = 18 cells, numbered 0..17
    values = [str(i) for i in range(18)]
    # Crop to I in [0, 1], J in [0, 1], K in [0, 0] -> 2x2x1 = 4 cells: (0,0), (1,0), (0,1), (1,1) -> indices 0, 1, 3, 4
    cropped = crop_cells(values, nx=3, ny=3, i0=0, i1=1, j0=0, j1=1, k0=0, k1=0, flip_j=False)
    assert len(cropped) == 4
    assert cropped == ["0", "1", "3", "4"]


def test_crop_coord_dimensions():
    # 3x3 grid has (3+1)*(3+1) = 16 pillars, 6 coords each = 96 floats
    pillar_values = [str(i) for i in range(96)]
    # Cropping to 2x2 cells needs (2+1)*(2+1) = 9 pillars = 54 floats
    cropped_coord = crop_coord(pillar_values, nx=3, ny=3, i0=0, i1=1, j0=0, j1=1, flip_j=False, invert_z=False)
    assert len(cropped_coord) == 9 * 6


def test_crop_zcorn_dimensions():
    # 3x3x2 grid has 3*3*2*8 = 144 zcorn values
    zcorn_values = [str(100.0) for _ in range(144)]
    # Cropping to 2x2x1 cells has 2*2*1*8 = 32 zcorn values
    cropped_zcorn = crop_zcorn(zcorn_values, nx=3, ny=3, i0=0, i1=1, j0=0, j1=1, k0=0, k1=0, flip_j=False, invert_z=False)
    assert len(cropped_zcorn) == 32
