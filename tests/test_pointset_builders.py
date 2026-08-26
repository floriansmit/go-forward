"""Tests for T>Map pointset builder algorithms (Best-fit, Union, Control, Uber)."""
from __future__ import annotations

from pathlib import Path
import pytest

from scripts.build_best_fit_grdecl_to_pointset import write_pointset as write_best_fit
from scripts.build_multi_realizations_grdecls_to_control_pointsets import control_levels
from scripts.build_multi_realizations_grdecls_to_uber_pointsets import z_levels, choose_spacing


def test_build_best_fit_pointset_complete(tmp_path: Path, mini_grdecl_path: Path):
    out_file = tmp_path / "best_fit_points.txt"
    stats = write_best_fit(
        grdecl_path=mini_grdecl_path,
        output_path=out_file,
        property_keyword="FACIES",
        discrete_novalue=None,
        max_vertical_spacing=None,
        enabled_codes=None,
    )
    assert stats["cells"] == 18
    assert stats["written"] == 18
    assert stats["skipped"] == 0
    assert out_file.exists()

    content = out_file.read_text(encoding="utf-8")
    assert "BEGIN HEADER" in content
    assert "INT,FACIES" in content
    assert "INT,CellIndex" in content
    assert "END HEADER" in content


def test_build_best_fit_pointset_reservoir_filter(tmp_path: Path, mini_grdecl_path: Path):
    out_file = tmp_path / "best_fit_filtered.txt"
    # Filter only facies 1 (9 cells out of 18)
    stats = write_best_fit(
        grdecl_path=mini_grdecl_path,
        output_path=out_file,
        property_keyword="FACIES",
        discrete_novalue=None,
        max_vertical_spacing=None,
        enabled_codes={1},
    )
    assert stats["cells"] == 18
    assert stats["written"] == 9
    assert stats["skipped"] == 9


def test_control_levels_spacing():
    # Top at -1000m, bottom at -1200m with 50m max spacing
    levels = control_levels(bottom_z=-1200.0, top_z=-1000.0, max_spacing=50.0)
    assert levels[0] == -1000.0
    assert levels[-1] == -1200.0
    assert len(levels) == 5  # -1000, -1050, -1100, -1150, -1200


def test_control_levels_single_point():
    levels = control_levels(bottom_z=-1000.0, top_z=-1000.0, max_spacing=50.0)
    assert levels == [-1000.0]


def test_uber_z_levels():
    levels = z_levels(z_min=-1100.0, z_max=-1000.0, spacing=25.0)
    assert levels == [-1000.0, -1025.0, -1050.0, -1075.0, -1100.0]


def test_uber_choose_spacing_under_limit():
    bounds = [(-1100.0, -1000.0)] * 9  # 9 columns
    spacing = choose_spacing(bounds=bounds, n_facies=2, choices=[10.0, 25.0, 50.0], max_total_points=1000)
    assert spacing == 10.0
