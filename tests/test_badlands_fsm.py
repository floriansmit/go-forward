"""Analytic fixtures use the upstream regular stratal HDF5 schema, not a fake solver."""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

import h5py
import numpy as np
import pytest
from badlands_fsm import (
    export_grdecl,
    install_export,
    prepare_run,
    regular_grid,
    stratal_files,
)
from build_best_fit_grdecl_to_pointset import write_pointset
from grdecl_utils import grdecl_cell_centers, tokenize_grdecl
from run_badlands_fsm import read_status, run_model, runtime_command


@pytest.fixture
def stratal_snapshot(tmp_path):
    xx, yy = np.meshgrid(np.arange(3) * 100.0, np.arange(3) * 100.0)
    coords = np.column_stack((xx.ravel(), yy.ravel()))
    # Nodal basal elevation + thickness = basal elevation of the next layer.
    path = tmp_path / "sed.time2.hdf5"
    with h5py.File(path, "w") as h:
        h["coords"] = coords
        h["layDepth"] = np.tile([-30.0, -10.0, 0.0], (9, 1))
        h["layThick"] = np.tile([20.0, 10.0, 0.0], (9, 1))
        h["layElev"] = np.tile([-100.0, -5.0, 0.0], (9, 1))
        h["layPoro"] = np.tile([0.2, 0.3, 0.0], (9, 1))
    return path


def test_prepare_dem_and_xml(tmp_path):
    run = tmp_path / "run with spaces"
    xml = prepare_run(run, {"nx": 4, "ny": 3, "origin_x": 500000.0})
    tree = ET.parse(xml)
    assert tree.findtext("strata/stratdx") == "500.0"
    assert tree.findtext("grid/demfile") == "dem.csv"
    assert tree.findtext("outfolder") == "output"
    assert tree.findtext("tectonic/disp/dfile") == "tectonics.csv"
    dem = np.loadtxt(run / "dem.csv")
    assert dem.shape == (12, 3)
    assert np.allclose(dem[:4, 0], [500000, 500500, 501000, 501500])
    assert (run / "run_model.py").exists()
    with pytest.raises(FileExistsError):
        prepare_run(run, {})


@pytest.mark.parametrize("settings", [
    {"nx": 2}, {"spacing_m": 0}, {"duration_years": -1},
    {"layer_interval_years": 3000}, {"rainfall_m_year": -1}, {"sea_level_m": float("nan")},
])
def test_bad_settings_do_not_create_partial_run(tmp_path, settings):
    with pytest.raises(ValueError):
        prepare_run(tmp_path / "run", settings)
    assert not (tmp_path / "run").exists()


def test_export_geometry_facies_and_porosity(tmp_path, stratal_snapshot):
    output = tmp_path / "model.grdecl"
    summary = export_grdecl(stratal_snapshot, output, facies_codes=(8, 4, 1))
    assert summary["dimensions"] == [2, 2, 2]
    assert summary["active_cells"] == 8
    data = tokenize_grdecl(output, {"SPECGRID", "COORD", "ZCORN", "ACTNUM", "Facies", "BDLLAYER", "PORO"})
    assert len(data["COORD"]) == 54
    assert len(data["ZCORN"]) == 64
    assert list(map(float, data["Facies"])) == [4] * 4 + [1] * 4
    assert list(map(float, data["BDLLAYER"])) == [2] * 4 + [1] * 4
    assert list(map(float, data["PORO"])) == [0.3] * 4 + [0.2] * 4
    centers = grdecl_cell_centers(output)
    assert len(centers) == 8
    # Shared parser returns elevation-negative cell centres for positive-down GRDECL.
    assert [row[2] for row in centers] == [-5.0] * 4 + [-20.0] * 4
    assert output.with_suffix(".badlands.json").exists()
    with pytest.raises(FileExistsError):
        export_grdecl(stratal_snapshot, output)


def test_export_slope_shuffle_and_depth_datum(tmp_path, stratal_snapshot):
    with h5py.File(stratal_snapshot, "r+") as h:
        slope = h["coords"][:, 0] / 100
        h["layDepth"][:] += slope[:, None]
        order = np.arange(9)[::-1]
        for name in h:
            h[name][:] = np.asarray(h[name])[order]
    output = tmp_path / "sloping.grdecl"
    export_grdecl(stratal_snapshot, output, datum_elevation_m=1000)
    centers = grdecl_cell_centers(output)
    assert centers[0][:3] == (50.0, 50.0, -1004.5)
    assert centers[1][:3] == (150.0, 50.0, -1003.5)


def test_export_pinchouts_and_empty_layers(tmp_path, stratal_snapshot):
    with h5py.File(stratal_snapshot, "r+") as h:
        h["layThick"][:4, 1] = 0  # not a whole cell yet; use exact corner IDs below
        h["layThick"][:, 1] = [0, 0, 10, 0, 0, 10, 10, 10, 10]
        h["layDepth"][:, 1] = -np.asarray(h["layThick"])[:, 1]
        h["layDepth"][:, 0] = np.asarray(h["layDepth"])[:, 1] - 20
    output = tmp_path / "pinch.grdecl"
    summary = export_grdecl(stratal_snapshot, output)
    assert summary["active_cells"] == 7
    data = tokenize_grdecl(output, {"ACTNUM", "Facies"})
    assert data["ACTNUM"][0] == "0"
    assert data["Facies"][0] == "0"
    stats = write_pointset(output, tmp_path / "pointset", "Facies", None, None, None)
    assert stats["written"] == 7
    rows = (tmp_path / "pointset").read_text().split("END HEADER\n")[1].splitlines()
    assert int(rows[0].split()[-1]) == 1  # do not compact CellIndex after dropping cell 0


@pytest.mark.parametrize("problem", ["missing", "negative", "gap", "porosity", "empty"])
def test_invalid_snapshot_fails_without_output(tmp_path, stratal_snapshot, problem):
    with h5py.File(stratal_snapshot, "r+") as h:
        if problem == "missing":
            del h["layElev"]
        elif problem == "negative":
            h["layThick"][0, 0] = -2
        elif problem == "gap":
            h["layDepth"][0, 1] = 99
        elif problem == "porosity":
            h["layPoro"][0, 0] = 25
        else:
            h["layThick"][:] = 0
            h["layDepth"][:] = 0
    output = tmp_path / "invalid.grdecl"
    with pytest.raises(ValueError):
        export_grdecl(stratal_snapshot, output)
    assert not output.exists()


def test_regular_grid_rejects_duplicates():
    with pytest.raises(ValueError, match="Duplicate"):
        regular_grid(np.array([[0, 0], [1, 0], [0, 1], [0, 1]]))


def test_snapshot_numeric_sort(tmp_path):
    directory = tmp_path / "output" / "h5"
    directory.mkdir(parents=True)
    for name in ("sed.time10.hdf5", "sed.time2.hdf5", "sed.time1.p0.hdf5", "stratal.time5.hdf5"):
        (directory / name).touch()
    assert [p.name for p in stratal_files(tmp_path)] == ["sed.time2.hdf5", "sed.time10.hdf5"]


def test_handoff_preserves_sources_and_facies_dictionary(tmp_path, stratal_snapshot):
    output = tmp_path / "model.grdecl"
    export_grdecl(stratal_snapshot, output)
    source = tmp_path / "original_grdecl"
    installed = install_export(output, source)
    assert installed.read_bytes() == output.read_bytes()
    config = source / "facies_config.json"
    original = config.read_bytes()
    with pytest.raises(FileExistsError):
        install_export(output, source)
    assert config.read_bytes() == original
    second = tmp_path / "other.grdecl"
    export_grdecl(stratal_snapshot, second, facies_codes=(4, 5, 6))
    with pytest.raises(ValueError, match="absent"):
        install_export(second, source)
    assert not (source / second.name).exists()


def test_external_runner_and_failure_status(tmp_path):
    (tmp_path / "run_model.py").write_text("print('external solver stand-in for process supervision test')\n")
    assert run_model(tmp_path, "python", sys.executable, "") == 0
    assert read_status(tmp_path)["status"] == "completed"
    assert "stand-in" in (tmp_path / "badlands.log").read_text()
    assert not (tmp_path / "runner.lock").exists()
    assert run_model(tmp_path, "python", "missing-badlands-python", "") == 1
    assert read_status(tmp_path)["status"] == "failed"


def test_cancel_external_runner(tmp_path):
    (tmp_path / "run_model.py").write_text("import time\ntime.sleep(30)\n")
    (tmp_path / "cancel.request").touch()
    assert run_model(tmp_path, "python", sys.executable, "") == 1
    assert read_status(tmp_path)["status"] == "cancelled"


def test_wsl_command_preserves_paths_with_spaces(tmp_path, monkeypatch):
    monkeypatch.setattr("run_badlands_fsm.subprocess.check_output", lambda *args, **kwargs: "/mnt/d/project with spaces/run\n")
    command = runtime_command(tmp_path, "wsl", "/home/user/env/bin/python", "Ubuntu-24.04")
    assert command == ["wsl.exe", "-d", "Ubuntu-24.04", "--cd", "/mnt/d/project with spaces/run", "--exec", "/home/user/env/bin/python", "-u", "run_model.py", "model.xml"]
