"""Managed solver setup, isolated from the dashboard and existing WSL distros."""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

RUNTIME_VERSION = 1
DISTRIBUTION = "GO-Forward-Badlands"
LINUX_HOME = "/opt/go-forward/badlands-v1"
ROOTFS_NAME = "ubuntu-base-24.04.5-base-amd64.tar.gz"
ROOTFS_URL = "https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/" + ROOTFS_NAME
ROOTFS_SHA256 = "e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86"
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class WindowsSetupRequired(RuntimeError):
    pass


class SetupCancelled(RuntimeError):
    pass


def runtime_home() -> Path:
    if override := os.environ.get("GO_FORWARD_RUNTIME_HOME"):
        return Path(override)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "GO-Forward" / "badlands-runtime"
    return Path.home() / ".local" / "share" / "go-forward" / "badlands-runtime"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def cached_runtime(home: Path | None = None) -> dict:
    result = read_json((home or runtime_home()) / "ready.json")
    return result if result.get("runtime_version") == RUNTIME_VERSION else {}


def checkpoint(cancel_dir: Path | None):
    if cancel_dir is not None and (cancel_dir / "cancel.request").exists():
        raise SetupCancelled("Simulation stopped")


def decode_wsl(data: bytes) -> str:
    return data.decode("utf-16-le" if b"\x00" in data else "utf-8", errors="replace").replace("\ufeff", "").strip()


def wsl_distributions() -> list[str]:
    try:
        result = subprocess.run(["wsl.exe", "--list", "--quiet"], capture_output=True, timeout=30, creationflags=FLAGS, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise WindowsSetupRequired("Windows simulation support (WSL 2) must be enabled first.") from exc
    if result.returncode:
        raise WindowsSetupRequired("Windows simulation support (WSL 2) needs installation or a restart. Enable it below, restart if requested, then retry.")
    return [line.strip() for line in decode_wsl(result.stdout).splitlines() if line.strip()]


def request_windows_support() -> None:
    """Request UAC approval without opening a terminal; never reboot automatically."""
    if os.name != "nt":
        raise RuntimeError("This prerequisite is only applicable on Windows.")
    executable = str(Path(os.environ["SystemRoot"]) / "System32" / "wsl.exe")
    execute = ctypes.windll.shell32.ShellExecuteW
    execute.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_int]
    execute.restype = ctypes.c_void_p
    result = execute(None, "runas", executable, "--install --no-distribution --no-launch", None, 0)
    if not result or result <= 32:
        raise OSError("Windows setup was not started. Administrator approval is required.")


@contextlib.contextmanager
def setup_lock(home: Path, cancel_dir: Path | None = None):
    """OS-backed lock: concurrent projects share one installer; crashes release it."""
    home.mkdir(parents=True, exist_ok=True)
    with (home / "setup.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        deadline = time.monotonic() + 1800
        while True:
            checkpoint(cancel_dir)
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise TimeoutError("Another simulation is still preparing the shared runtime. Retry after it finishes.") from None
                time.sleep(1)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)


def download_verified(url: str, target: Path, checksum: str, cancel_dir: Path | None = None) -> None:
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == checksum:
        return
    temporary = target.with_suffix(target.suffix + ".part")
    digest = hashlib.sha256()
    try:
        with urllib.request.urlopen(url, timeout=120) as response, temporary.open("wb") as out:
            while block := response.read(1024 * 1024):
                checkpoint(cancel_dir)
                digest.update(block)
                out.write(block)
        if digest.hexdigest() != checksum:
            raise ValueError("Downloaded Linux image failed its checksum check; setup has been stopped.")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def run_setup_step(command: list[str], log, cancel_dir: Path | None, timeout: int = 1800) -> None:
    checkpoint(cancel_dir)
    # Let a package transaction finish safely before honouring cancellation.
    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=timeout, creationflags=FLAGS, check=False)
    checkpoint(cancel_dir)
    if result.returncode:
        raise RuntimeError("Solver setup failed. See the setup log for details; retry is safe and existing projects are unchanged.")


def probe_runtime(runtime: dict) -> bool:
    command = [runtime["python"], "-c", "from badlands.model import Model"]
    if runtime["backend"] == "wsl":
        command = ["wsl.exe", "-d", runtime["distribution"], "--exec", *command]
    try:
        return subprocess.run(command, capture_output=True, timeout=60, creationflags=FLAGS, check=False).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_managed_runtime(*, allow_setup: bool, stage, log, cancel_dir: Path | None = None, home: Path | None = None) -> dict:
    home = home or runtime_home()
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("The managed Badlands runtime currently supports x64 computers. Use an advanced external runtime on other architectures.")
    with setup_lock(home, cancel_dir):
        ready = cached_runtime(home)
        if ready and probe_runtime(ready):
            checkpoint(cancel_dir)
            stage("Solver ready")
            return ready
        if not allow_setup:
            raise RuntimeError("Approve the one-time solver setup checkbox, or enable 'Allow managed runtime repair downloads' under Advanced solver settings, then retry.")
        stage("Preparing isolated solver environment")
        bootstrap = Path(__file__).with_name("bootstrap_badlands_linux.py")
        if os.name == "nt":
            distributions = wsl_distributions()
            ownership = home / "ownership.json"
            if DISTRIBUTION in distributions and read_json(ownership).get("distribution") != DISTRIBUTION:
                raise RuntimeError(f"A WSL distribution named {DISTRIBUTION} already exists but is not owned by this setup. It has not been changed.")
            if DISTRIBUTION not in distributions:
                stage("Downloading verified Linux environment")
                archive = home / ROOTFS_NAME
                download_verified(ROOTFS_URL, archive, ROOTFS_SHA256, cancel_dir)
                ownership.write_text(json.dumps({"distribution": DISTRIBUTION, "rootfs_sha256": ROOTFS_SHA256}), encoding="utf-8")
                stage("Registering managed Linux environment")
                (home / "wsl").mkdir(exist_ok=True)
                try:
                    run_setup_step(["wsl.exe", "--import", DISTRIBUTION, str(home / "wsl"), str(archive), "--version", "2"], log, cancel_dir)
                except RuntimeError as exc:
                    raise WindowsSetupRequired("Windows could not start the managed WSL 2 environment. Enable Windows simulation support, restart if requested, and check the setup log. Hardware virtualization must be enabled.") from exc
            stage("Installing Linux build prerequisites")
            prefix = ["wsl.exe", "-d", DISTRIBUTION, "-u", "root", "--exec", "env", "DEBIAN_FRONTEND=noninteractive"]
            run_setup_step([*prefix, "apt-get", "update"], log, cancel_dir)
            run_setup_step([*prefix, "apt-get", "install", "-y", "--no-install-recommends", "python3", "ca-certificates", "build-essential", "gfortran", "git", "pkg-config"], log, cancel_dir)
            script_path = subprocess.check_output(["wsl.exe", "-d", DISTRIBUTION, "--exec", "wslpath", "-a", str(bootstrap.resolve())], text=True, encoding="utf-8", timeout=30, creationflags=FLAGS).strip()
            stage("Downloading Python and building Badlands")
            run_setup_step(["wsl.exe", "-d", DISTRIBUTION, "--exec", "python3", script_path, LINUX_HOME], log, cancel_dir)
            runtime = {"backend": "wsl", "distribution": DISTRIBUTION, "python": LINUX_HOME + "/env/bin/python"}
        else:
            if not sys.platform.startswith("linux") or any(shutil.which(tool) is None for tool in ("gcc", "gfortran", "git")):
                raise RuntimeError("Managed setup requires Linux with GCC, GFortran and Git, or Windows with WSL 2. An external solver can be selected under advanced settings.")
            stage("Downloading Python and building Badlands")
            run_setup_step([sys.executable, str(bootstrap), str(home / "linux-v1")], log, cancel_dir)
            runtime = {"backend": "python", "distribution": "", "python": str(home / "linux-v1" / "env" / "bin" / "python")}
        stage("Validating solver")
        if not probe_runtime(runtime):
            raise RuntimeError("Badlands was installed but could not be started. See the setup log and retry.")
        ready = {**runtime, "runtime_version": RUNTIME_VERSION, "badlands_version": "2.3.1"}
        temporary = home / "ready.tmp"
        temporary.write_text(json.dumps(ready, indent=2), encoding="utf-8")
        temporary.replace(home / "ready.json")
        return ready
