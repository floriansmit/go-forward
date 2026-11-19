"""One-click managed runtime, real simulation, and automatic GRDECL export."""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path

from badlands_fsm import export_grdecl, stratal_files
from badlands_runtime import (
    SetupCancelled,
    WindowsSetupRequired,
    checkpoint,
    ensure_managed_runtime,
)
from run_badlands_fsm import run_model, write_status

ACTIVE_STATUSES = {"queued", "preparing", "launching", "running", "simulated", "exporting"}


def run_pipeline(run_dir: Path, *, allow_setup: bool = False, external_runtime: dict | None = None) -> int:
    run_dir = run_dir.resolve()
    lock = run_dir / "pipeline.lock"
    try:
        with lock.open("x") as handle:
            handle.write(str(os.getpid()))
    except FileExistsError:
        return 2  # Do not change the status of another active worker.
    try:
        options = json.loads((run_dir / "export_settings.json").read_text(encoding="utf-8"))
        filename = options.pop("filename")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*\.grdecl", filename):
            raise ValueError("The output must be a simple .grdecl filename.")
        write_status(run_dir, status="preparing", stage="Checking solver", needs_windows_support=False,
                     pipeline_pid=os.getpid(), pipeline_started_utc=datetime.now(UTC).isoformat())

        def stage(message):
            write_status(run_dir, status="preparing", stage=message)

        with (run_dir / "setup.log").open("a", encoding="utf-8") as log:
            runtime = external_runtime or ensure_managed_runtime(allow_setup=allow_setup, stage=stage, log=log, cancel_dir=run_dir)
        checkpoint(run_dir)
        write_status(run_dir, status="running", stage="Simulating stratigraphy")
        code = run_model(run_dir, runtime["backend"], runtime["python"], runtime.get("distribution", ""), success_status="simulated")
        if code:
            return code
        checkpoint(run_dir)
        write_status(run_dir, status="exporting", stage="Generating GRDECL")
        snapshots = stratal_files(run_dir)
        if not snapshots:
            raise ValueError("Badlands finished without regular stratigraphy outputs. Inspect the solver log.")
        target = run_dir / "grdecl" / filename
        result = export_grdecl(snapshots[-1], target, **options)
        write_status(run_dir, status="completed", stage="GRDECL ready", grdecl=str(target), active_cells=result["active_cells"],
                     completed_utc=datetime.now(UTC).isoformat())
        return 0
    except WindowsSetupRequired as exc:
        write_status(run_dir, status="failed", stage="Windows setup required", error=str(exc), needs_windows_support=True)
        return 1
    except SetupCancelled:
        write_status(run_dir, status="cancelled", stage="Stopped")
        return 1
    except Exception as exc:  # noqa: BLE001 - report unexpected background-worker failures in the dashboard.
        write_status(run_dir, status="failed", error=str(exc))
        return 1
    finally:
        lock.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--allow-setup", action="store_true")
    parser.add_argument("--backend", choices=["python", "wsl"])
    parser.add_argument("--python", default="python3")
    parser.add_argument("--distribution", default="Ubuntu-24.04")
    args = parser.parse_args()
    runtime = {"backend": args.backend, "python": args.python, "distribution": args.distribution} if args.backend else None
    return run_pipeline(args.run_dir, allow_setup=args.allow_setup, external_runtime=runtime)


if __name__ == "__main__":
    raise SystemExit(main())
