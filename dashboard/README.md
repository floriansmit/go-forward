# GO-Forward dashboard

The dashboard is the project-level interface for inspecting GRDECL grids, preparing diagenesis handoffs, assigning geomechanics, running DFM Generator, and viewing results.

## Start it

From the repository root:

```powershell
uv sync
uv run python run_dashboard.py
```

Use `python -m pip install -r requirements-dashboard.txt` and `python run_dashboard.py` only when not using uv.

## Project profiles

The left sidebar creates and selects projects. Choose a project type explicitly; it determines the visible workflow tabs and adds a suffix to the project folder.

| Profile | Visible dashboard route |
| --- | --- |
| MVP | FSM → FDM (GRDECL → 3D points) · FDM Append & View · FFM Geomech preparation · FFM Run DFM · FFM View results |
| Siliciclastics | FSM → FDM (GRDECL → 3D points) · FDM Append & View · Fault Seal Analysis placeholder |
| Carbonates | FSM GRDECL → Mesh · FDM Carbonate Diagenesis · FFM Geomech preparation · FFM Run DFM · FFM View results |
| Crystalline rocks | GRDECL Inspect · FFM Geomech preparation · FFM Run DFM · FFM View results |

Projects are listed from `data/<project>/`. Import one or more source GRDECLs from the first relevant tab; they are copied to `data/<project>/original_grdecl/`. Generated workflow folders are created beside that starting folder and are not versioned.

## Viewer behaviour

GRDECL grids are displayed by cell centre by default for performance. Map, cross-section, and 3D views support I/J/K selection, next/previous layer controls, static extents, vertical exaggeration, and discrete categorical palettes. The experimental true-cell view renders only the selected K layer and can be slower for large models.

`Facies`, `RockType`, and common lithology names are detected as discrete integer classifications. The project definition JSON provides labels and colours.

## T>Map and DFM

MVP and siliciclastic profiles build 3D point sets with stable `CellIndex` identity. Import returned T>Map files in **FDM Append & View**; the dashboard identifies their source point set from provenance, filename, or matching information before append-back.

**FFM Geomech preparation** writes the GRDECL properties required by the DFM executable, including `DFNPorosity`, `DFNEffectiveStress_MPa`, `YoungsModulus_Pa`, `PoissonsRatio`, `FrictionCoefficient`, `FractureEnergy_J_m2`, and optionally `DIPAZIMUTH`.

**FFM Run DFM** writes a reproducible run folder with copied input grid, configuration, manifest, status, log, and output. Use cropped runs first. Explicit fracture generation can take substantially longer than implicit-property calculations.

The dashboard invokes DFM Generator as a separate external executable. The current Apache-2.0 binary is temporarily bundled in `external-tools/DFMGenerator/` pending the official upstream release at [JointFlow/DFMGenerator](https://github.com/JointFlow/DFMGenerator). See `THIRD_PARTY_NOTICES.md`.
