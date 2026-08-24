"""Tests for GRDECL tokenization, repeat expansion, and property writing."""
from __future__ import annotations

import io
from pathlib import Path
import pytest

from scripts.grdecl_utils import tokenize_grdecl, write_property
from scripts.initialize_facies_config import expand_integer_values


def test_tokenize_grdecl_single_keyword(mini_grdecl_path: Path):
    data = tokenize_grdecl(mini_grdecl_path, {"SPECGRID"})
    assert "SPECGRID" in data
    assert data["SPECGRID"][:3] == ["3", "3", "2"]


def test_tokenize_grdecl_multiple_keywords(mini_grdecl_path: Path):
    data = tokenize_grdecl(mini_grdecl_path, {"SPECGRID", "COORD", "ZCORN", "FACIES"})
    assert "SPECGRID" in data
    assert "COORD" in data
    assert "ZCORN" in data
    assert "FACIES" in data
    assert len(data["COORD"]) == (3 + 1) * (3 + 1) * 6
    assert len(data["ZCORN"]) == 3 * 3 * 2 * 8


def test_tokenize_grdecl_missing_keyword_raises(mini_grdecl_path: Path):
    with pytest.raises(ValueError, match="missing required GRDECL keyword"):
        tokenize_grdecl(mini_grdecl_path, {"NON_EXISTENT_KEYWORD"})


def test_expand_integer_values_literal_and_repeat(tmp_path: Path):
    tokens = ["1", "2", "3*4", "5", "2*10"]
    dummy_path = tmp_path / "dummy.grdecl"
    expanded = expand_integer_values(tokens, dummy_path, "FACIES")
    assert expanded == [1, 2, 4, 4, 4, 5, 10, 10]


def test_expand_integer_values_non_integer_raises(tmp_path: Path):
    tokens = ["1", "2.5", "3"]
    dummy_path = tmp_path / "dummy.grdecl"
    with pytest.raises(ValueError, match="non-integer value"):
        expand_integer_values(tokens, dummy_path, "FACIES")


def test_write_property_formatting():
    buf = io.StringIO()
    values = ["1.0", "2.0", "3.0", "4.0", "5.0", "6.0", "7.0"]
    write_property(buf, "PORO", values, values_per_line=4)
    output = buf.getvalue()
    assert "\nPORO\n" in output
    assert output.endswith("/\n")
    lines = [line.strip() for line in output.strip().splitlines() if line.strip() and line.strip() != "PORO" and line.strip() != "/"]
    assert len(lines) == 2
    assert lines[0] == "1.0  2.0  3.0  4.0"
    assert lines[1] == "5.0  6.0  7.0"
