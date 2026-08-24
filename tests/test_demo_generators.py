"""Tests for synthetic demonstration model generators (Carbonate & Crystalline)."""
from __future__ import annotations

from pathlib import Path
import pytest

from scripts.create_demo_grdecl_projects import top_depth, write_model
from scripts.grdecl_utils import tokenize_grdecl, grdecl_cell_centers


def test_top_depth_mounded_geometry():
    nx, ny = 30, 30
    # Center of reef should be shallower (smaller positive depth) than the margins
    z_center = top_depth(15.0, 15.0, nx, ny, "carbonate")
    z_margin = top_depth(0.0, 0.0, nx, ny, "carbonate")
    assert z_center < z_margin  # Mounded reef crest reaches shallower depth


def test_write_model_generates_valid_carbonate_grdecl(tmp_path: Path):
    model_path = tmp_path / "test_carbonate.grdecl"
    write_model(model_path, "carbonate")
    assert model_path.exists()

    data = tokenize_grdecl(model_path, {"SPECGRID", "COORD", "ZCORN", "Facies", "PORO", "PERM"})
    nx, ny, nz = (int(float(v)) for v in data["SPECGRID"][:3])
    assert (nx, ny, nz) == (30, 30, 12)
    assert len(data["COORD"]) == (nx + 1) * (ny + 1) * 6
    assert len(data["ZCORN"]) == nx * ny * nz * 8

    centers = grdecl_cell_centers(model_path)
    assert len(centers) == nx * ny * nz


def test_write_model_generates_valid_crystalline_grdecl(tmp_path: Path):
    model_path = tmp_path / "test_crystalline.grdecl"
    write_model(model_path, "crystalline")
    assert model_path.exists()

    data = tokenize_grdecl(model_path, {"SPECGRID", "COORD", "ZCORN", "RockType", "PORO", "PERM"})
    nx, ny, nz = (int(float(v)) for v in data["SPECGRID"][:3])
    assert (nx, ny, nz) == (30, 30, 12)
    assert len(data["COORD"]) == (nx + 1) * (ny + 1) * 6
    assert len(data["ZCORN"]) == nx * ny * nz * 8

