"""Build a windowed launcher and a console-capable, hidden workflow worker."""
from pathlib import Path
import subprocess
from PyInstaller.utils.hooks import collect_all, copy_metadata

root = Path(SPECPATH).parent
datas = []
binaries = []
hiddenimports = ["tkinter", "tkinter.ttk", "tkinter.messagebox"]
for package in ("streamlit", "plotly", "pandas", "numpy", "scipy"):
    package_data, package_binaries, package_imports = collect_all(
        package, include_py_files=False,
        filter_submodules=lambda name: not any(part in {"tests", "conftest"} for part in name.split(".")),
        exclude_datas=["**/tests/**", "**/test/**", "**/__pycache__/**"],
    )
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports
datas += copy_metadata("streamlit", recursive=True)
# Only tracked resources are shipped: no local projects, secrets or outputs.
tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
for name in tracked:
    path = Path(name)
    if name and (path.parts[0] in {"dashboard", "scripts", "data", "reference_examples", "external-tools"}
                 or name.startswith("docs/assets/logos/")
                 or name in {"LICENSE", "THIRD_PARTY_NOTICES.md"}):
        datas.append((str(root / path), str(path.parent)))

a = Analysis([str(root / "packaging" / "desktop_launcher.py")],
             pathex=[str(root / "scripts")], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["pytest", "_pytest", "matplotlib", "IPython", "sphinx"])
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GO-Forward",
          console=False, contents_directory="_internal")
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GO-Forward-worker",
             console=True, contents_directory="_internal")
coll = COLLECT(gui, worker, a.binaries, a.datas, name="GO-Forward")
