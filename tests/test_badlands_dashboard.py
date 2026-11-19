"""Exercise the new profile tab with a real Streamlit session and HDF5 input."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import h5py
import numpy as np
import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def dashboard_workspace(tmp_path, mini_grdecl_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("GO_FORWARD_DATA_ROOT", str(data))

    def create(profile, suffix):
        project = data / ("Smoke_" + suffix)
        source = project / "original_grdecl"
        source.mkdir(parents=True)
        shutil.copyfile(mini_grdecl_path, source / "mini.grdecl")
        (source / "facies_config.json").write_text(json.dumps({
            "facies_property": "FACIES", "facies_names": {"1": "Offshore", "4": "Shallow", "8": "Land"},
            "facies_colors": {"1": "#4477aa", "4": "#ddcc77", "8": "#228833"},
        }))
        (project / "project_config.json").write_text(json.dumps({"workflow_profile": profile}))
        return project

    return create


@pytest.mark.parametrize("profile,suffix,first_tab", [
    ("Siliciclastics", "siliciclastics", "FSM · pyBadlands"),
    ("MVP", "mvp", "FSM → FDM (GRDECL → 3D points)"),
    ("Carbonates", "carbonates", "FSM GRDECL → Mesh"),
    ("Crystalline rocks", "crystalline", "GRDECL Inspect"),
])
def test_profile_navigation(dashboard_workspace, profile, suffix, first_tab):
    dashboard_workspace(profile, suffix)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "streamlit_app.py"), default_timeout=60).run()
    assert not app.exception
    assert app.tabs[0].label == first_tab
    if profile != "Siliciclastics":
        assert "FSM · pyBadlands" not in [t.label for t in app.tabs]


def test_prepare_export_and_handoff(dashboard_workspace, tmp_path):
    project = dashboard_workspace("Siliciclastics", "siliciclastics")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "streamlit_app.py"), default_timeout=60).run()
    next(button for button in app.button if button.label == "Prepare run").click().run()
    assert not app.exception
    run = next((project / "FSM pyBadlands" / "runs").iterdir())
    assert (run / "model.xml").exists()
    snapshot = tmp_path / "sed.time1.hdf5"
    with h5py.File(snapshot, "w") as h:
        xx, yy = np.meshgrid(np.arange(3) * 100.0, np.arange(3) * 100.0)
        h["coords"] = np.column_stack((xx.ravel(), yy.ravel()))
        h["layDepth"] = np.tile([-10.0, 0.0], (9, 1))
        h["layThick"] = np.tile([10.0, 0.0], (9, 1))
        h["layElev"] = np.tile([-5.0, 0.0], (9, 1))
    key = "badlands::Smoke_siliciclastics::external"
    app.text_input(key=key).set_value(str(snapshot)).run()
    next(button for button in app.button if button.label == "Export GRDECL").click().run()
    assert not app.exception
    assert (run / "grdecl" / "badlands_fsm.grdecl").exists()
    next(button for button in app.button if button.label == "Add to source GRDECLs").click().run()
    assert not app.exception
    assert (project / "original_grdecl" / "badlands_fsm.grdecl").exists()
    assert (project / "original_grdecl" / "mini.grdecl").exists()
    app.checkbox(key="badlands::Smoke_siliciclastics::preview").check().run()
    assert not app.exception
