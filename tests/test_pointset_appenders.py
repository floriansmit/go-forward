"""Tests for T>Map property appenders and lookup functions."""
from __future__ import annotations

from pathlib import Path
import pytest

from scripts.append_best_fit_tmap_to_grdecls import (
    grdecl_keyword,
    normalized_property_key,
    read_pointset,
    append_properties,
)


def test_normalized_property_key():
    assert normalized_property_key("total_porosity_p50 (vol %)") == "total_porosity_p50"
    assert normalized_property_key("permeability_mean (mD)") == "permeability_mean"
    assert normalized_property_key("effective_stress_mpa") == "effective_stress"


def test_grdecl_keyword_aliases():
    assert grdecl_keyword("total_porosity_p50") == "PORO50"
    assert grdecl_keyword("permeability_mean") == "PERMMEAN"
    assert grdecl_keyword("total_porosity_mean") == "POROMEAN"
    assert grdecl_keyword("custom_property_name") == "CUSTOM_PROPERTY_NAME"


def test_read_pointset_parses_header_and_data(mini_tmap_pointset_path: Path):
    columns, rows = read_pointset(mini_tmap_pointset_path)
    assert "Facies" in columns
    assert "CellIndex" in columns
    assert "total_porosity_p50" in columns
    assert len(rows) == 3
    assert rows[0][0] == 50.0  # X
    assert rows[0][1] == 50.0  # Y
    assert rows[0][2] == -1025.0  # Z


def test_append_properties_to_grdecl(tmp_path: Path, mini_grdecl_path: Path, mini_tmap_pointset_path: Path):
    output_grdecl = tmp_path / "augmented.grdecl"
    stats = append_properties(mini_grdecl_path, mini_tmap_pointset_path, output_grdecl)
    assert stats["cells"] == 18
    assert stats["points"] == 3
    assert stats["matched"] == 3
    assert stats["properties"] == 2  # total_porosity_p50, permeability_p50
    assert output_grdecl.exists()

    content = output_grdecl.read_text(encoding="utf-8")
    assert "PORO50" in content
    assert "PERM50" in content
