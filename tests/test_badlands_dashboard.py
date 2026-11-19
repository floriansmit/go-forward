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
    monkeypatch.setenv("GO_FORWARD_RUNTIME_HOME", str(tmp_path / "runtime"))

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


def test_first_run_requires_setup_consent(dashboard_workspace):
    project = dashboard_workspace("Siliciclastics", "siliciclastics")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "streamlit_app.py"), default_timeout=60).run()
    next(b for b in app.button if b.label == "Run simulation").click().run()
    assert not app.exception
    assert not (project / "FSM pyBadlands").exists()
    assert any("Approve" in item.value for item in app.error)
    assert not any(field.label == "Badlands Python interpreter" for field in app.text_input)


def test_one_click_prepares_simulates_and_exports(dashboard_workspace, stratal_snapshot, monkeypatch):
    import run_badlands_pipeline as pipeline

    project = dashboard_workspace("Siliciclastics", "siliciclastics")
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "streamlit_app.py"), default_timeout=60).run()
    monkeypatch.setattr(pipeline, "ensure_managed_runtime", lambda **k: {"backend": "python", "python": "managed"})

    def simulate(run, *args, **kwargs):
        output = run / "output" / "h5"
        output.mkdir(parents=True)
        shutil.copyfile(stratal_snapshot, output / "sed.time2.hdf5")
        return 0

    monkeypatch.setattr(pipeline, "run_model", simulate)

    def start(command, **kwargs):
        run = Path(command[command.index("--run-dir") + 1])
        assert "--allow-setup" in command
        assert pipeline.run_pipeline(run, allow_setup=True) == 0

    monkeypatch.setattr("badlands_tab.subprocess.Popen", start)
    app.checkbox(key="badlands::Smoke_siliciclastics::consent").check()
    app.number_input(key="badlands::Smoke_siliciclastics::datum").set_value(1000.0)
    next(b for b in app.button if b.label == "Run simulation").click().run()
    assert not app.exception
    run = next((project / "FSM pyBadlands" / "runs").iterdir())
    assert (run / "grdecl" / "badlands_fsm.grdecl").exists()
    manifest = json.loads((run / "grdecl" / "badlands_fsm.badlands.json").read_text())
    assert manifest["datum_elevation_m"] == 1000


def test_retry_after_windows_setup_preserves_inputs(dashboard_workspace, monkeypatch):
    from badlands_fsm import prepare_run
    from run_badlands_fsm import read_status, write_status

    project = dashboard_workspace("Siliciclastics", "siliciclastics")
    run = project / "FSM pyBadlands" / "runs" / "saved_run"
    prepare_run(run, {"nx": 7, "ny": 7})
    saved = (run / "settings.json").read_bytes()
    (run / "export_settings.json").write_text('{"filename":"saved.grdecl"}')
    (run / "execution_settings.json").write_text('{"allow_setup":true,"external":null}')
    write_status(run, status="failed", needs_windows_support=True)
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "dashboard" / "streamlit_app.py"), default_timeout=60).run()
    requests = []
    monkeypatch.setattr("badlands_tab.request_windows_support", lambda: requests.append("UAC"))
    next(b for b in app.button if b.label == "Enable Windows simulation support").click().run()
    assert requests == ["UAC"]

    def start(command, **kwargs):
        assert Path(command[command.index("--run-dir") + 1]) == run
        assert "--allow-setup" in command
        write_status(run, status="completed", stage="GRDECL ready")

    monkeypatch.setattr("badlands_tab.subprocess.Popen", start)
    next(b for b in app.button if b.label == "Retry simulation").click().run()
    assert not app.exception
    assert read_status(run)["status"] == "completed"
    assert (run / "settings.json").read_bytes() == saved


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
