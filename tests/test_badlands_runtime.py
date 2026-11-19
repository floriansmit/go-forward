"""Managed runtime setup is mocked here; a real WSL setup is tested manually."""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
from types import SimpleNamespace

import badlands_runtime as runtime
import pytest
import run_badlands_pipeline as pipeline
from badlands_fsm import prepare_run
from run_badlands_fsm import read_status


def test_wsl_list_decodes_windows_utf16(monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 0, "Ubuntu-24.04\r\nGO-Forward-Badlands\r\n".encode("utf-16-le")))
    assert runtime.wsl_distributions() == ["Ubuntu-24.04", "GO-Forward-Badlands"]


def test_wsl_not_enabled_is_a_guided_setup_state(monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess([], 1, b"", b"not installed"))
    with pytest.raises(runtime.WindowsSetupRequired):
        runtime.wsl_distributions()


@pytest.mark.skipif(runtime.os.name != "nt", reason="Windows UAC request")
def test_windows_support_requests_approval_without_terminal_or_reboot(monkeypatch):
    calls = []

    class Execute:
        result = 42

        def __call__(self, *args):
            calls.append(args)
            return self.result

    execute = Execute()
    monkeypatch.setattr(runtime.ctypes, "windll", SimpleNamespace(shell32=SimpleNamespace(ShellExecuteW=execute)))
    runtime.request_windows_support()
    assert calls[0][1] == "runas"
    assert calls[0][3] == "--install --no-distribution --no-launch"
    assert calls[0][-1] == 0  # Hidden window, Windows UAC remains visible.
    execute.result = 5
    with pytest.raises(OSError, match="approval"):
        runtime.request_windows_support()


def test_verified_download_and_cache(tmp_path, monkeypatch):
    data = b"verified download"
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(data))
    target = tmp_path / "image.tar.gz"
    checksum = hashlib.sha256(data).hexdigest()
    runtime.download_verified("https://example.invalid/image", target, checksum)
    assert target.read_bytes() == data
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *a, **k: pytest.fail("Cached download must not use the network"))
    runtime.download_verified("unused", target, checksum)


def test_bad_download_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"wrong"))
    target = tmp_path / "image.tar.gz"
    with pytest.raises(ValueError, match="checksum"):
        runtime.download_verified("https://example.invalid/image", target, "0" * 64)
    assert not target.exists()
    assert not target.with_suffix(".gz.part").exists()


def test_reuse_is_offline_and_does_not_reinstall(tmp_path, monkeypatch):
    ready = {"runtime_version": runtime.RUNTIME_VERSION, "backend": "wsl", "distribution": runtime.DISTRIBUTION, "python": "/managed/python"}
    (tmp_path / "ready.json").write_text(json.dumps(ready))
    monkeypatch.setattr(runtime, "probe_runtime", lambda r: True)
    monkeypatch.setattr(runtime, "wsl_distributions", lambda: pytest.fail("Already verified runtime should not reinstall"))
    with (tmp_path / "log").open("w") as log:
        assert runtime.ensure_managed_runtime(home=tmp_path, allow_setup=False, stage=lambda s: None, log=log) == ready


def test_setup_requires_explicit_download_permission(tmp_path):
    with (tmp_path / "log").open("w") as log, pytest.raises(RuntimeError, match="Approve"):
        runtime.ensure_managed_runtime(home=tmp_path, allow_setup=False, stage=lambda s: None, log=log)


def test_cancellation_before_install(tmp_path):
    (tmp_path / "cancel.request").touch()
    with (tmp_path / "log").open("w") as log, pytest.raises(runtime.SetupCancelled):
        runtime.ensure_managed_runtime(home=tmp_path, cancel_dir=tmp_path, allow_setup=True, stage=lambda s: None, log=log)


@pytest.mark.skipif(runtime.os.name != "nt", reason="Windows-specific managed WSL import")
def test_never_mutate_unowned_distribution(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "wsl_distributions", lambda: [runtime.DISTRIBUTION])
    monkeypatch.setattr(runtime, "run_setup_step", lambda *a, **k: pytest.fail("Must not change an unrelated Linux environment"))
    with (tmp_path / "log").open("w") as log, pytest.raises(RuntimeError, match="not owned"):
        runtime.ensure_managed_runtime(home=tmp_path, allow_setup=True, stage=lambda s: None, log=log)


@pytest.mark.skipif(runtime.os.name != "nt", reason="Windows-specific managed WSL import")
def test_owned_setup_publishes_ready_only_after_probe(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(runtime, "wsl_distributions", list)
    monkeypatch.setattr(runtime, "download_verified", lambda *a, **k: None)
    monkeypatch.setattr(runtime, "run_setup_step", lambda command, *a, **k: commands.append(command))
    monkeypatch.setattr(runtime.subprocess, "check_output", lambda *a, **k: "/mnt/c/bootstrap.py\n")
    monkeypatch.setattr(runtime, "probe_runtime", lambda r: False)
    with (tmp_path / "log").open("w") as log, pytest.raises(RuntimeError, match="could not be started"):
        runtime.ensure_managed_runtime(home=tmp_path, allow_setup=True, stage=lambda s: None, log=log)
    assert not (tmp_path / "ready.json").exists()
    assert commands[0][:3] == ["wsl.exe", "--import", runtime.DISTRIBUTION]
    monkeypatch.setattr(runtime, "wsl_distributions", lambda: [runtime.DISTRIBUTION])
    monkeypatch.setattr(runtime, "probe_runtime", lambda r: True)
    with (tmp_path / "log").open("w") as log:
        result = runtime.ensure_managed_runtime(home=tmp_path, allow_setup=True, stage=lambda s: None, log=log)
    assert result == runtime.cached_runtime(tmp_path)


@pytest.fixture
def pipeline_run(tmp_path):
    run = tmp_path / "simulation"
    prepare_run(run, {"nx": 3, "ny": 3})
    (run / "export_settings.json").write_text(json.dumps({"filename": "result.grdecl", "datum_elevation_m": 500.0, "facies_codes": [8, 4, 1]}))
    return run


def test_pipeline_automatically_exports_with_saved_settings(pipeline_run, stratal_snapshot, monkeypatch):
    runtime_value = {"backend": "python", "python": "managed-python", "distribution": ""}
    monkeypatch.setattr(pipeline, "ensure_managed_runtime", lambda **kwargs: runtime_value)

    def simulate(run, *args, **kwargs):
        assert kwargs["success_status"] == "simulated"
        output = run / "output" / "h5"
        output.mkdir(parents=True)
        shutil.copyfile(stratal_snapshot, output / "sed.time2.hdf5")
        return 0

    monkeypatch.setattr(pipeline, "run_model", simulate)
    assert pipeline.run_pipeline(pipeline_run, allow_setup=True) == 0
    assert (pipeline_run / "grdecl" / "result.grdecl").exists()
    manifest = json.loads((pipeline_run / "grdecl" / "result.badlands.json").read_text())
    assert manifest["datum_elevation_m"] == 500
    assert manifest["facies_codes"]["terrestrial"] == 8
    assert read_status(pipeline_run)["status"] == "completed"


def test_pipeline_surfaces_wsl_prerequisite(pipeline_run, monkeypatch):
    def missing(**kwargs):
        raise runtime.WindowsSetupRequired("Enable WSL")
    monkeypatch.setattr(pipeline, "ensure_managed_runtime", missing)
    assert pipeline.run_pipeline(pipeline_run, allow_setup=True) == 1
    assert read_status(pipeline_run)["needs_windows_support"] is True


def test_pipeline_duplicate_does_not_corrupt_running_status(pipeline_run):
    (pipeline_run / "pipeline.lock").touch()
    (pipeline_run / "run_status.json").write_text('{"status":"running"}')
    assert pipeline.run_pipeline(pipeline_run) == 2
    assert read_status(pipeline_run)["status"] == "running"


def test_pipeline_cancel_before_simulation(pipeline_run):
    (pipeline_run / "cancel.request").touch()
    assert pipeline.run_pipeline(pipeline_run, external_runtime={"backend": "python", "python": "unused"}) == 1
    assert read_status(pipeline_run)["status"] == "cancelled"
