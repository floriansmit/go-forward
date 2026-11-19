"""Copied into a run folder and executed by the external Badlands interpreter."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("xml", type=Path)
    args = parser.parse_args()
    if Path("cancel.request").exists():
        raise SystemExit(130)
    if os.name == "posix" and os.getpgrp() != os.getpid():
        os.setsid()
    Path("model_pid.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
    from badlands.model import Model

    model = Model()
    model.load_xml(str(args.xml), verbose=True)
    model.run_to_time(model.input.tEnd, verbose=True)
    Path("runtime.json").write_text(json.dumps({
        "python": platform.python_version(), "badlands": importlib.metadata.version("badlands"),
        "end_time_years": model.input.tEnd, "output_folder": str(model.input.outDir),
    }, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
