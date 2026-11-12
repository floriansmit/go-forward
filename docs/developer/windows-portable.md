# Windows portable dashboard

This optional distribution includes a Python runtime and Streamlit server. It
uses the normal default browser, not a separate embedded browser engine. Users
extract the ZIP and run GO-Forward.exe without installing Python or uv.

## Build

Build on Windows x64 from the repository root:

```powershell
uv sync --locked --all-extras
uv pip install "pyinstaller>=6.16,<7"
uv run --no-sync python -m PyInstaller --noconfirm packaging/go_forward.spec
uv run --no-sync python packaging/smoke_test.py
Compress-Archive -Path dist/GO-Forward -DestinationPath dist/GO-Forward-Windows-x64.zip -Force
```

Distribute the entire `dist/GO-Forward` folder as a ZIP, never just the executable.
Only Git-tracked example inputs and resources enter the package. Local test
projects, outputs and secrets are excluded. New resource files must be tracked
before a release build. Bundled third-party license notices remain included.

## Runtime

The launcher finds an available localhost port, starts a hidden worker, waits for
the Streamlit health endpoint and opens the default browser. Closing the launcher
stops its process tree, including any active modelling jobs. Stop ongoing jobs
before closing it. Closing only the browser does not stop the server.

The worker also dispatches bundled command-line scripts so the dashboard's
existing conversion, synthetic simulation, reattachment and DFM commands do not
require a separate Python installation. Projects are seeded once in
`%USERPROFILE%\GO-Forward\data`; existing project directories are never overwritten.
Set `GO_FORWARD_HOME` before launch to choose another workspace directory.

## Release

Run the Windows portable dashboard GitHub Actions workflow manually for a test
artifact. Publishing a `v*` Git tag builds and attaches the ZIP and checksum to a
GitHub Release. README links to Releases rather than a nonexistent fixed asset.
The build is unsigned until a signing certificate is configured; do not advise
users to disable security software. An installer can later wrap the same folder.

Before publishing, test on a Windows machine without Python: open each profile,
import a GRDECL, convert points, create synthetic T>Map data, reattach properties,
and restart to confirm saved projects persist. Also test a busy port and paths
with spaces. A health endpoint alone does not validate workflow execution.

The implementation follows the [PyInstaller runtime model](https://pyinstaller.org/en/stable/runtime-information.html)
and [Streamlit server configuration](https://docs.streamlit.io/develop/api-reference/configuration/config.toml).
