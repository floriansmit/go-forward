"""Start the GO-Forward Streamlit dashboard without PowerShell."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> int:
    """Run Streamlit with the Python interpreter that launched this file."""
    try:
        import streamlit  # noqa: F401
    except ModuleNotFoundError:
        print("Streamlit is not installed for this Python interpreter. Install the dashboard requirements first:")
        print(f'  "{sys.executable}" -m pip install -r requirements-dashboard.txt')
        return 1

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ROOT / "dashboard" / "streamlit_app.py"),
        "--server.headless",
        "true",
        "--server.port",
        "8501",
    ]
    try:
        return subprocess.call(command, cwd=ROOT)
    except FileNotFoundError:
        print("Python could not start Streamlit.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
