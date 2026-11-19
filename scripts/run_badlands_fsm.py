"""Supervise a real Badlands run in an external Python or WSL environment."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def runtime_command(run_dir: Path, backend: str, python: str, distribution: str, probe: bool = False) -> list[str]:
    arguments = ["-u", "run_model.py", "model.xml"]
    if probe:
        arguments = ["-c", "from badlands.model import Model; import importlib.metadata; print('Badlands ' + importlib.metadata.version('badlands'))"]
    if backend == "wsl":
        linux_path = subprocess.check_output(
            ["wsl.exe", "-d", distribution, "--exec", "wslpath", "-a", str(run_dir.resolve())], text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=30,
        ).strip()
        return ["wsl.exe", "-d", distribution, "--cd", linux_path, "--exec", python, *arguments]
    return [python, *arguments]


def read_status(run_dir: Path) -> dict:
    try:
        return json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_status(run_dir: Path, **values) -> None:
    temporary = run_dir / "run_status.tmp"
    temporary.write_text(json.dumps({**read_status(run_dir), **values}, indent=2) + "\n", encoding="utf-8")
    temporary.replace(run_dir / "run_status.json")


def stop_child(process: subprocess.Popen, run_dir: Path, backend: str, distribution: str) -> None:
    if backend == "wsl":
        try:
            pid = int(json.loads((run_dir / "model_pid.json").read_text())["pid"])
            if pid <= 1:
                raise ValueError("Invalid model process group")
            subprocess.run(
                ["wsl.exe", "-d", distribution, "--exec", "kill", "-TERM", "--", f"-{pid}"],
                capture_output=True, timeout=15, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, ValueError, KeyError, subprocess.SubprocessError):
            pass
    elif os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def run_model(run_dir: Path, backend: str, python: str, distribution: str) -> int:
    run_dir = run_dir.resolve()
    lock = run_dir / "runner.lock"
    # Each prepared run is single-use; duplicate dashboard clicks cannot start two models.
    with lock.open("x"):
        pass
    process = None
    try:
        if any(run_dir.glob("output*")) or (run_dir / "model_pid.json").exists():
            raise ValueError("This run already has outputs. Prepare a new run to avoid mixing snapshots.")
        write_status(run_dir, status="running", backend=backend, python=python, distribution=distribution,
                     started_utc=datetime.now(UTC).isoformat(), launcher_pid=os.getpid())
        command = runtime_command(run_dir, backend, python, distribution)
        with (run_dir / "badlands.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=run_dir, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            while process.poll() is None:
                if (run_dir / "cancel.request").exists():
                    stop_child(process, run_dir, backend, distribution)
                    write_status(run_dir, status="cancelled")
                    return 1
                time.sleep(0.5)
        code = process.returncode
        if (run_dir / "cancel.request").exists():
            write_status(run_dir, status="cancelled", returncode=code)
            return 1
        write_status(run_dir, status="completed" if code == 0 else "failed", returncode=code,
                     completed_utc=datetime.now(UTC).isoformat())
        return code
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        if process is not None and process.poll() is None:
            stop_child(process, run_dir, backend, distribution)
        write_status(run_dir, status="failed", error=str(exc))
        return 1
    finally:
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--backend", choices=["python", "wsl"], default="wsl")
    parser.add_argument("--python", default="python3", help="Interpreter in the Badlands environment, not the dashboard environment.")
    parser.add_argument("--distribution", default="Ubuntu-24.04")
    parser.add_argument("--probe", action="store_true")
    args = parser.parse_args()
    if args.probe:
        result = subprocess.run(runtime_command(args.run_dir, args.backend, args.python, args.distribution, True),
                                cwd=args.run_dir, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return result.returncode
    return run_model(args.run_dir, args.backend, args.python, args.distribution)


if __name__ == "__main__":
    raise SystemExit(main())
