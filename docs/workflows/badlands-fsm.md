# Badlands Stratigraphic Forward Modelling

The `dev-siliciclastics` branch adds **FSM · pyBadlands** before **FSM → FDM**
in the Siliciclastics profile. DionisosFlow import remains available in the
next tab. MVP, Carbonates and Crystalline profiles retain their existing routes.
The published v0.1.0 portable executable predates this stage; use this branch's
source dashboard until a new executable release is built.

## Runtime

The dashboard and converter use the normal GO-Forward environment, including
`h5py`. The numerical solver runs in a **separate Badlands Python environment**,
either directly or through WSL. Badlands is not bundled into the Windows EXE.
This separation is intentional: the current Badlands package requires NumPy <2,
whereas this dashboard uses NumPy 2. Install the solver following the
[upstream installation guide](https://badlands.readthedocs.io/en/latest/install.html).
Do not install it into GO-Forward's `.venv`.

Select WSL and enter its distribution and Linux interpreter path (for example
`/home/yourname/badlands-env/bin/python`), or select External Python and enter
the full interpreter path for a native Badlands installation. **Test runtime**
checks the actual `badlands.model.Model` import before running a simulation.
The software is also known historically as pyBadlands; the current import is
`badlands`, not `pyBadlands`.

The integration was validated with Badlands 2.3.1, Python 3.11, NumPy 1.26.4
and the upstream-recommended open-source meshplex 0.13.3 fork. For an existing
Linux/WSL installation of uv with GCC/GFortran available, an isolated setup is:

```bash
uv venv --python 3.11 ~/.venvs/go-forward-badlands
uv pip install --python ~/.venvs/go-forward-badlands/bin/python badlands==2.3.1 'git+https://github.com/kinnala/meshplex@09f25dc16501803685eea8b9a50d963a5e0169ee'
```

Use that Linux interpreter path in the dashboard. The current PyPI meshplex
package is not a substitute for this historical open-source fork. Managed
Python must include development headers for compiling Badlands; Ubuntu's base
interpreter alone may lack them. No solver installation is performed by a
dashboard button or silently added to GO-Forward's environment.

## Prepare And Run

1. Select or create a Siliciclastics project.
2. Set initial topography, time intervals, rainfall, constant sea level,
   uniform subsidence and surface-process parameters. Initial topography may
   instead be a headerless whitespace-separated `X Y elevation` DEM.
3. Prepare a run. Each run gets a unique folder; previous runs are never reused.
4. Test the external runtime and run Badlands. Refresh shows job status and
   recent logs; Stop run requests termination of the solver.
5. Select a regular `sed.timeN.hdf5` snapshot, or enter a path to one produced
   by an external Badlands run.
6. Set the depth datum, environmental facies mapping and thickness threshold,
   export a GRDECL, inspect it, and choose **Add to source GRDECLs**.
7. Continue in **FSM → FDM** using Best-fit, Union, Control or Uber as before.

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
    launcher.log
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
