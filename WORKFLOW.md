# GO-Forward workflow guide

This guide describes the current command-line and dashboard routes. The dashboard is the recommended route for normal use; the commands are useful for batch processing and reproducible runs.

## 1. Start from a project

Projects keep their own source data and outputs:

```text
input/<project>/source_grdecls/
outputs/<project>/
```

Create a project in the dashboard sidebar, select its rock-workflow profile, and import one or more source GRDECL files in the first tab. The four included examples are:

- `MVP_Gassum_mvp` (five Gassum realizations for the multi-realization demonstration)
- `Siliciclastics_Gassum_siliciclastics` (Gassum Base only for the single-model route)
- `Reef_Demo_carbonates`
- `Crystalline_Pluton_Demo_crystalline`

The project suffix fixes its workflow profile. Do not mix GRDECLs or returned modelling files from different projects in the same output folder.

## 2. Install and run the dashboard

Run these commands from the repository root:

```powershell
uv sync
uv run python run_dashboard.py
```

`uv` installs the Python version and packages recorded in `uv.lock`. If it is not installed, see the [README](README.md#install-and-run).

## 3. Define the geological classes

In the first relevant dashboard tab, select the integer classification property and open the definitions editor:

- MVP and Siliciclastics: **Facies definitions**
- Carbonates: **Carbonate facies definitions**
- Crystalline rocks: **Rock type definitions**

Only MVP and siliciclastic projects have a T>Map switch. Enable it only for classes that should be sent to T>Map; excluded cells later receive the no-value marker `-77777` for returned properties.

The definitions are saved at:

```text
input/<project>/source_grdecls/facies_config.json
```

For a scripted initialisation of a new siliciclastic source set:

```powershell
$Project = "My_Project_siliciclastics"
$SourceDir = ".\input\$Project\source_grdecls"
uv run python .\scripts\initialize_facies_config.py --grdecl-dir $SourceDir --property "Facies"
```

The property name is case-sensitive. Use the exact GRDECL keyword, for example `Facies`, `FACIES`, or `RockType`.

## 4. MVP and siliciclastic route: GRDECL to T>Map and back

The dashboard route is:

1. **FSM → FDM (GRDECL → 3D points):** choose source models and a Best-fit, Union, Control, or Uber approach, then create 3D point sets.
2. **FDM Append & View:** send the `01_*` point sets to T>Map, import its returned point-set files into the matching `02_*` folder, inspect them, then append the returned properties to GRDECL.
3. **FFM Geomech preparation:** assign geomechanical properties to the augmented GRDECL.
4. **FFM Run DFM:** create a reproducible DFM Generator run.
5. **FFM View results:** inspect implicit properties and, where produced, explicit fracture output.

### CellIndex and returned T>Map data

Best-fit 3D point sets contain a stable `CellIndex`, derived from the original GRDECL cell order. This is the preferred identity for T>Map return matching and avoids coordinate-rounding ambiguity. Ask T>Map to retain `CellIndex` and all identity columns when it writes the return file.

If an older return is vertically sampled rather than full resolution, the append step can linearly interpolate returned properties vertically within the original grid columns. It only fills cells between returned control points; it does not invent a spatial interpolation across unrelated columns.

### Best-fit commands

```powershell
$Project = "Siliciclastics_Gassum_siliciclastics"
$SourceDir = ".\input\$Project\source_grdecls"
$Out = ".\outputs\$Project\Best-fit approach"

uv run python .\scripts\build_best_fit_grdecl_to_pointset.py `
  --grdecl-dir $SourceDir `
  --output-dir "$Out\01_3d_points_from_original_grdecls" `
  --property Facies

# Put returned T>Map files in: $Out\02_3d_points_with_tmap_data
uv run python .\scripts\append_best_fit_tmap_to_grdecls.py `
  --grdecl-dir $SourceDir `
  --pointset-dir "$Out\02_3d_points_with_tmap_data" `
  --output-dir "$Out\03_augmented_grdecls_with_tmap_data" `
  --property Facies
```

For a vertically reduced Best-fit point set, use the dashboard conversion controls. When appending its returned file, use the dashboard’s vertical interpolation option or add `--vertical-interpolate` to the append command.

### Multi-realization commands

All selected source models must have compatible grid dimensions and cell ordering. The builders use the project `facies_config.json` and, by default, export only classes with T>Map enabled.

```powershell
$Project = "MVP_Gassum_mvp"
$SourceDir = ".\input\$Project\source_grdecls"
$Config = "$SourceDir\facies_config.json"
$Out = ".\outputs\$Project"

# 1. Union: one point-set family per facies across selected realizations.
uv run python .\scripts\build_multi_realizations_grdecls_to_union_pointsets.py `
  --grdecl-dir $SourceDir --output-dir "$Out\Multi-realization Union approach\01_union_pointsets_by_facies" `
  --property Facies --facies-config $Config --tmap-enabled-only

# Put returned files in the matching 02_union_pointsets_with_tmap_data folder.
uv run python .\scripts\append_multi_realizations_union_tmap_to_grdecls.py `
  --grdecl-dir $SourceDir `
  --pointset-dir "$Out\Multi-realization Union approach\02_union_pointsets_with_tmap_data" `
  --output-dir "$Out\Multi-realization Union approach\03_augmented_grdecls_from_union_interpolation"

# 2. Control: top and base of every selected facies envelope, plus points at the chosen vertical interval.
uv run python .\scripts\build_multi_realizations_grdecls_to_control_pointsets.py `
  --grdecl-dir $SourceDir --output-dir "$Out\Multi-realization control approach\01_control_pointsets_by_facies" `
  --property Facies --facies-config $Config --tmap-enabled-only --max-vertical-spacing 50

uv run python .\scripts\append_multi_realizations_control_tmap_to_grdecls.py `
  --grdecl-dir $SourceDir `
  --pointset-dir "$Out\Multi-realization control approach\02_control_pointsets_with_tmap_data" `
  --output-dir "$Out\Multi-realization control approach\03_augmented_grdecls_from_control_interpolation" `
  --property Facies

# 3. Uber: per-I/J vertical envelopes across selected models at the chosen spacing.
uv run python .\scripts\build_multi_realizations_grdecls_to_uber_pointsets.py `
  --grdecl-dir $SourceDir --output-dir "$Out\Multi-realization Uber approach\01_uber_pointsets_by_facies" `
  --property Facies --facies-config $Config --tmap-enabled-only --vertical-spacing 50

uv run python .\scripts\append_multi_realizations_uber_tmap_to_grdecls.py `
  --grdecl-dir $SourceDir `
  --pointset-dir "$Out\Multi-realization Uber approach\02_uber_pointsets_with_tmap_data" `
  --output-dir "$Out\Multi-realization Uber approach\03_augmented_grdecls_from_uber_interpolation" `
  --property Facies
```

Use the dashboard to select the source models, preview point density, choose vertical spacing, and monitor long multi-realization conversions.

## 5. Synthetic demonstration data

Synthetic T>Map data is intended only for demonstrations and dashboard testing. It uses placeholder relationships and must not be confused with returned T>Map simulations. The supplied MVP project contains all five Gassum realizations and is the appropriate demonstration source for Union, Control, and Uber.

To recreate the supplied siliciclastic/MVP example output set:

```powershell
uv run python regenerate_synthetic_outputs.py
```

To run one approach or another project:

```powershell
uv run python regenerate_synthetic_outputs.py --approach Control
uv run python regenerate_synthetic_outputs.py --project "My_Project_siliciclastics"
```

## 6. Carbonate and crystalline routes

### Carbonates

The current dashboard scaffolds this route:

```text
FSM GRDECL → mesh and CellIndex mapping → Moose GOLEM/PHREEQC → re-appended GRDECL → FFM geomechanics → DFM
```

The first tab imports and inspects the source GRDECL. The second tab provides the result-import/re-append location but does not yet impose a GOLEM/PHREEQC result schema. Before reactive-diagenesis output is available, geomechanical preparation can use porosity and mineral/cement properties exported directly from DionisosFlow.

### Crystalline rocks

The current route is:

```text
GRDECL inspection → RockType definitions → FFM geomechanics → DFM
```

Crystalline projects do not use 3D point conversion or a T>Map handoff. Use RockType/Lithology classes to assign initial geomechanical relationships.

## 7. FFM geomechanics and DFM Generator

In **FFM Geomech preparation**, choose the augmented or direct source GRDECL and property inputs. The dashboard writes DFM-ready properties, including Young’s modulus in Pa, Poisson’s ratio, friction coefficient, fracture energy, effective stress, and optional `DIPAZIMUTH` in radians.

Use **FFM Run DFM** to create a separate run folder under the current approach’s `05_DFM_generator_runs` directory. It copies the input grid, writes the configuration and manifest, records a log and status, and preserves generated output. Start with a cropped run and implicit output before requesting an expensive explicit fracture calculation.

`DFMGenerator_GRDECL.exe` is distributed in `scripts/` for the Windows dashboard workflow. Its configuration controls model behaviour; consult the executable reference examples and the DFM settings panel before changing stress or timestep parameters.

## 8. Important conventions

- Keep `outputs/` local. It is excluded from Git because it can be large and is reproducible from source data or real returned files.
- Preserve GRDECL geometry and cell ordering when appending properties. Do not use a returned point set from a different source model.
- `-77777` is the no-value marker. For T>Map properties, it normally means that a class was excluded from T>Map or no return value could be assigned.
- Keep `MAPAXES`, `COORD`, `ZCORN`, `SPECGRID`, and original geometry keywords when supplying a GRDECL to DFM Generator.
- Keep DFM input/output on a local drive during long runs where possible; cloud-sync folders can cause executable output-file locking.
