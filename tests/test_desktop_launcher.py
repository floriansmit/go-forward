"""Portable startup helpers without opening windows or starting servers."""
import importlib.util
import socket
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "desktop_launcher", Path(__file__).resolve().parents[1] / "packaging" / "desktop_launcher.py"
)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_workspace_seeds_examples_without_overwriting(tmp_path, monkeypatch):
    root = tmp_path / "bundle"
    example = root / "data" / "example"
    example.mkdir(parents=True)
    (example / "project_config.json").write_text("original")
    home = tmp_path / "user workspace"
    monkeypatch.setenv("GO_FORWARD_HOME", str(home))
    monkeypatch.delenv("GO_FORWARD_DATA_ROOT", raising=False)
    assert launcher.configure_workspace(root) == home
    saved = home / "data" / "example" / "project_config.json"
    assert saved.read_text() == "original"
    saved.write_text("edited")
    launcher.configure_workspace(root)
    assert saved.read_text() == "edited"
    assert launcher.os.environ["GO_FORWARD_DATA_ROOT"] == str(home / "data")


def test_available_port_is_bindable():
    port = launcher.available_port()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", port))


def test_dispatch_rejects_scripts_outside_bundle(tmp_path):
    with pytest.raises(ValueError, match="bundled workflow scripts"):
        launcher.dispatch_script(tmp_path, ["../other.py"])


def test_dispatch_preserves_script_arguments(tmp_path, monkeypatch, capsys):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    script = scripts / "example.py"
    script.write_text("import sys\nprint(sys.argv[1])\n")
    monkeypatch.setattr(launcher.sys, "argv", [])
    monkeypatch.setattr(launcher.sys, "path", list(launcher.sys.path))
    assert launcher.dispatch_script(tmp_path, [str(script), "path with spaces"]) == 0
    assert capsys.readouterr().out.strip() == "path with spaces"
