"""Run the GRDECL-capable DFM Generator and persist its status/logs."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def write_status(path: Path, **values: object) -> None:
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    current.update(values)
    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DFMGenerator_GRDECL.exe and write dashboard-readable status.")
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    run_dir = args.run_dir.resolve()
    status = run_dir / "run_status.json"
    log = run_dir / "dfn_generator.log"
    started = datetime.now(timezone.utc).isoformat()
    write_status(status, status="running", started_utc=started, executable=str(args.executable), config=str(args.config), stage="Starting DFN Generator")
    # Stream stdout line-by-line so the dashboard can show useful live progress
    # rather than appearing frozen for longer fracture-model runs.
    with log.open("w", encoding="utf-8", newline="\n") as handle:
        process = subprocess.Popen(
            [str(args.executable), str(args.config)],
            cwd=run_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            handle.write(line)
            handle.flush()
            message = line.strip()
            if message:
                write_status(status, status="running", stage=message, last_log_utc=datetime.now(timezone.utc).isoformat())
        returncode = process.wait()
    write_status(
        status,
        status="completed" if returncode == 0 else "failed",
        stage="Completed" if returncode == 0 else "Failed",
        returncode=returncode,
        completed_utc=datetime.now(timezone.utc).isoformat(),
        log=str(log),
    )
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
