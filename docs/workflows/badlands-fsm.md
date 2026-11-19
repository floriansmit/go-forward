# Badlands Stratigraphic Forward Modelling

The `dev-siliciclastics` branch adds **FSM · pyBadlands** before **FSM → FDM**
in the Siliciclastics profile. DionisosFlow import remains available in the
next tab. MVP, Carbonates and Crystalline profiles retain their existing routes.
The published v0.1.0 portable executable predates this stage; use this branch's
source dashboard until a new executable release is built.

## Runtime

The default is **Managed (automatic)**. End users do not enter interpreter
paths, install Python/uv manually, or open terminals. First use requires consent
to download the solver and create a local managed environment. Internet access
and several GB of disk space are needed during setup. Subsequent runs reuse the
verified environment without downloading it again.

On Windows x64, the app imports its own Ubuntu Base environment as
`GO-Forward-Badlands` under `%LOCALAPPDATA%\GO-Forward\badlands-runtime`.
Existing WSL distributions and dashboard Python packages are not modified.
If WSL 2 is disabled, the dashboard offers **Enable Windows simulation support**,
which requests Windows administrator approval. A restart or enabling hardware
virtualization may be necessary. The app never restarts Windows automatically.
After restarting, use **Retry simulation** to reuse the saved input parameters.
The WSL feature/UAC/restart path depends on Windows policy and cannot bypass
institutional administrator restrictions.
This uses Microsoft's [WSL import mechanism](https://learn.microsoft.com/en-us/windows/wsl/use-custom-distro)
and a verified [Ubuntu Base image](https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/).

The Ubuntu image and uv bootstrap archive are version-pinned and SHA256-checked
before use. Setup installs build tools only inside the dedicated Linux
environment, downloads managed Python 3.11.18, and installs Badlands 2.3.1,
NumPy 1.26.4 and the tested open-source meshplex fork. Other scientific packages
are also pinned; exact resolved packages are recorded inside the runtime.
Shared OS-backed locking prevents concurrent projects from installing the same
runtime twice. Setup can be retried safely, and failed setup never marks the
solver as ready. A pre-existing WSL distribution with the reserved name but no
GO-Forward ownership record is not changed.

The solver remains separate because Badlands requires NumPy <2 while the
dashboard uses NumPy 2. It is downloaded on first use, not embedded in the
application EXE. The same button-driven flow works from the portable application
when built from this branch. The old v0.1.0 download is unchanged.

Native Linux x64 can also prepare a managed runtime when GCC, GFortran and Git
are already available. Other architectures/platforms can use a separately
installed solver through **Advanced solver settings**. That panel retains
External Python and External WSL options for expert-managed installations.

For expert installation only, follow the
[upstream installation guide](https://badlands.readthedocs.io/en/latest/install.html).
An example Linux/WSL environment using uv is:

```bash
uv venv --python 3.11 ~/.venvs/go-forward-badlands
uv pip install --python ~/.venvs/go-forward-badlands/bin/python badlands==2.3.1 'git+https://github.com/kinnala/meshplex@09f25dc16501803685eea8b9a50d963a5e0169ee'
```

Use that interpreter path only under advanced external runtime settings. The
current PyPI meshplex package is not a substitute for the tested historical
open-source fork. Do not install the Badlands solver into GO-Forward's `.venv`.

## Prepare And Run

1. Select or create a Siliciclastics project.
2. Set initial topography, time intervals, rainfall, constant sea level,
   uniform subsidence and surface-process parameters. Initial topography may
   instead be a headerless whitespace-separated `X Y elevation` DEM.
3. Set the depth datum, environmental facies mapping and thickness threshold
   under GRDECL output, and approve first-use setup if needed.
4. Click **Run simulation**. The app saves inputs, prepares the managed runtime
   if necessary, simulates stratigraphy and automatically exports the latest
   regular HDF5 snapshot to GRDECL. Status/logs update automatically.
5. Inspect the result and choose **Add to source GRDECLs**.
6. Continue in **FSM → FDM** using Best-fit, Union, Control or Uber as before.

**Prepare run** saves inputs without executing the solver. The manual import/
export panel remains available for external `sed.timeN.hdf5` snapshots. It is
not required for a normal simulation. **Stop simulation** also cancels setup,
but an in-progress package transaction is allowed to finish safely first.

Stop an active WSL model before closing the Windows launcher: Linux processes
may outlive the Windows client. Each prepared run is single-use once the solver
starts; use a new prepared run after a failed numerical simulation.

Generated topography is a sloping upstream-to-basin surface with seeded
roughness, not a calibrated basin reconstruction. All lengths are metres and
simulation times are years. Duration must divide into whole output intervals;
each output interval must divide into whole layer intervals. The DEM needs
at least 3 x 3 nodes with equal X and Y spacing. An N x M nodal stratal grid
produces (N-1) x (M-1) GRDECL columns, not N x M cells.

The first version exposes constant climate, sea level and subsidence; it does
not yet expose all Badlands forcing histories or sediment/lithology options.
XML and model inputs are retained for reproducibility and external inspection.
No model run or large output is committed to Git.

The managed runtime is shared across projects and remains outside the source
repository and model folders. `GO_FORWARD_RUNTIME_HOME` can override its host
location for development/testing. Windows normally uses the LocalAppData path
above; Linux uses `~/.local/share/go-forward/badlands-runtime`. No application
updates or project deletion automatically unregister a Linux distribution.

## Output Layout

```text
data/<project>_siliciclastics/
  FSM pyBadlands/runs/<name>_<timestamp>/
    settings.json         # Model settings and DEM hash
    model.xml             # Generated Badlands model
    dem.csv               # Ordered SW-to-NE, X varies fastest
    tectonics.csv         # Optional cumulative vertical displacement
    run_model.py          # Versioned runner copied into the run
    run_status.json       # Supervisor status
    export_settings.json  # Immutable automatic-export parameters
    execution_settings.json # Runtime choice and first-use download permission
    launcher.log
    setup.log
    badlands.log
    runtime.json          # Actual solver/Python versions after success
    output/h5/...         # Real Badlands outputs
    grdecl/
      <model>.grdecl
      <model>.badlands.json
  original_grdecl/        # Only explicitly adopted models are copied here
```

## Geometry And Properties

The converter follows upstream
[`strataMesh.layerMesh` and `write_hdf5_stratal`](https://github.com/badlands-model/badlands/blob/master/src/badlands/underland/strataMesh.py):
`coords` supplies regular grid nodes, `layDepth` contains **basal elevations**,
`layThick` supplies thickness, and `layElev` records depositional elevation
relative to contemporaneous sea level. Despite its name, `layDepth` is not
positive-down burial depth. Each nodal quad becomes a corner-point column;
the converter does not treat nodes as cell centres or interpolate the TIN.

- GRDECL Z is `datum_elevation_m - Badlands elevation`, positive downward.
  No seismic stretch/squeeze, burial shift, CRS reprojection or unit conversion
  is inferred. Supply appropriate absolute elevations before handing to T>Map.
- K=1 is the youngest/topmost layer. `BDLLAYER` preserves the original
  oldest-first HDF5 layer index, starting at 1.
- Globally empty layers are omitted. Local pinchouts retain their true corner
  depths and become inactive when mean cell thickness is below the threshold.
  Best-fit point export honours `ACTNUM` without compacting original CellIndex
  identities; the other standard routes exclude the inactive Facies=0 cells.
- `Facies` is an explicitly selected **environmental proxy**, based on mean
  corner `layElev`: terrestrial at >=0 m, shallow marine between 0 and the
  specified palaeowater-depth threshold, offshore below it. These are not
  automatically equivalent to Gassum lithofacies or grain-size predictions.
  Map them deliberately to project codes or create a separate Badlands project.
- `BDLPALEO` retains mean depositional elevation; `BDLTHICK` records mean
  present layer thickness. `PORO`, when available, comes from `layPoro` as
  fractions in [0,1]. No permeability or T>Map diagenesis is invented.
- The manifest records source SHA256, conversion settings, datum and mapping.
  Exporting refuses to overwrite a prior grid. Adoption preserves existing
  grids and facies definitions, and rejects codes missing from an existing
  project dictionary. A new dictionary is created only for a project without one.

Only complete, regular, serial `sed.timeN.hdf5` outputs are supported. TIN
`stratal.time*`, partitioned `*.pN.hdf5`, irregular grids, inconsistent layer
bases or thicknesses, invalid porosity and empty depositional models are
rejected rather than silently resampled. Multi-lithology fractions are not
currently converted.

## Command Line

```powershell
uv run python scripts/export_badlands_to_grdecl.py path/to/sed.time10.hdf5 path/to/model.grdecl --datum-elevation 0 --shallow-depth 30 --facies-codes 8 4 1
```

The run supervisor can also be used independently:

```powershell
uv run python scripts/run_badlands_fsm.py --run-dir "path/to/prepared/run" --backend wsl --distribution Ubuntu-24.04 --python /home/yourname/badlands-env/bin/python --probe
```

Remove `--probe` to execute the prepared model. See the upstream
[XML reference](https://badlands.readthedocs.io/en/latest/xml.html) for the
meaning and units of model parameters. Badlands remains separately licensed;
this integration does not redistribute its solver source or binaries.

## Validation

A real WSL run with Badlands 2.3.1 used a 15 x 15 node DEM, 20,000 years,
10,000-year outputs, 5,000-year layer recording, erodibility 1e-5 and
subsidence 0.002 m/year (remaining settings at the dashboard defaults).
Its final snapshot exported to a 14 x 14 x 3 GRDECL containing 261 active cells.
Best-fit export produced 261 points with original CellIndex identities, and
synthetic T>Map returns reattached 30 properties to all 261 active cells.
The remaining 327 inactive cells retain the full original grid indexing.

Automated tests cover analytic layer geometry, coordinate ordering and datum,
pinchouts, missing/invalid data, non-overwrite handoff, process supervision,
cancellation, all four profile tab layouts and the dashboard's setup/export/
adoption/preview sequence. This verifies integration and geometry handling,
not geological calibration or equivalence to DionisosFlow sedimentology.

Managed first-use setup was also exercised from a clean app-owned Ubuntu Base
image on a Windows host with WSL 2 already enabled. It installed the compiler
prerequisites and solver, simulated the same test model, and automatically
exported its GRDECL. A browser-only Run simulation test and a compiled Windows
worker test (without Python/uv on PATH) also completed using the managed solver.
The Windows feature-enablement/UAC path is covered by mocked tests rather than
disabling/re-enabling WSL on the development computer. Institutional deployment
should still test that prerequisite path on a representative clean machine.
