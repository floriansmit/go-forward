"""Install an isolated, pinned Badlands solver. Executed inside managed Linux."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import urllib.request
from pathlib import Path

UV_VERSION = "0.13.9"
UV_SHA256 = "a7fbaff2b9a271d85c1bdb540941090fd1ce011797b4abeb48e4dcd39c2471d5"
MESH_SOURCE = "git+https://github.com/kinnala/meshplex@09f25dc16501803685eea8b9a50d963a5e0169ee"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("home", type=Path)
    args = parser.parse_args()
    home = args.home.resolve()
    home.mkdir(parents=True, exist_ok=True)
    uv = home / "uv"
    if not uv.exists():
        url = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-x86_64-unknown-linux-gnu.tar.gz"
        archive = home / "uv.tar.gz"
        with urllib.request.urlopen(url, timeout=120) as response:
            payload = response.read(100_000_000)
        if hashlib.sha256(payload).hexdigest() != UV_SHA256:
            raise ValueError("The downloaded environment tool failed its checksum check.")
        archive.write_bytes(payload)
        with tarfile.open(archive) as tar:
            member = tar.extractfile("uv-x86_64-unknown-linux-gnu/uv")
            if member is None:
                raise ValueError("Missing uv executable in the verified archive")
            uv.write_bytes(member.read())
        uv.chmod(0o755)
    env = dict(os.environ, UV_PYTHON_INSTALL_DIR=str(home / "python"), UV_CACHE_DIR=str(home / "cache"), UV_NO_PROGRESS="1")
    python = home / "env" / "bin" / "python"
    subprocess.run([str(uv), "venv", "--managed-python", "--python", "3.11.18", "--allow-existing", str(home / "env")], env=env, check=True)
    subprocess.run([
        str(uv), "pip", "install", "--python", str(python),
        "badlands==2.3.1", "numpy==1.26.4", "scipy==1.17.1", "pandas==3.0.6",
        "h5py==3.16.0", "matplotlib==3.11.2", "scikit-image==0.26.0", MESH_SOURCE,
    ], env=env, check=True)
    subprocess.run([str(python), "-c", "from badlands.model import Model; import importlib.metadata; print('Badlands ' + importlib.metadata.version('badlands'))"], check=True)
    versions = subprocess.check_output([str(uv), "pip", "freeze", "--python", str(python)], text=True, env=env)
    (home / "installed-requirements.txt").write_text(versions, encoding="utf-8")
    (home / "ready.json").write_text(json.dumps({"badlands": "2.3.1", "python": str(python), "uv": UV_VERSION}), encoding="utf-8")


if __name__ == "__main__":
    main()
