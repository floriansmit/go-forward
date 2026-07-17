# DionisosFlow GRDECL → T>Map workflow

Choose **one** approach below. The approaches are alternatives, not consecutive stages.

## Before running anything

1. Put the new source models in one folder. File names may be different from the examples; both `.grdecl` and `.GRDECL` are accepted.
2. Each file must contain `SPECGRID`, `COORD`, `ZCORN`, and a numeric, integer facies property. The grid dimensions and cell ordering must agree across realizations for the multi-realization approaches.
3. Use an empty or dedicated set of approach output folders for every new source-data set. Do not mix returned T>Map files from different source sets.
4. Set the exact facies property keyword below. It is case-sensitive (`Facies` and `FACIES` are different keywords).

Open PowerShell in this workspace and set the variables once:

```powershell
$Python = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (-not (Test-Path $Python)) { $Python = "python" }

$SourceDir = "C:\path\to\your\source-grdecls"
$FaciesProperty = "Facies"       # Change to FACIES, FaciesCode, etc. when needed.
$FaciesConfig = ".\dashboard\facies_config.json"
```

The point-set builders create folders when needed. Before starting a fresh source-data set, clear or replace the relevant `outputs\<approach>` folder so old facies point sets cannot be sent to T>Map again.

## Recreate the example outputs in one command

The repository includes `regenerate_synthetic_outputs.ps1` to recreate all current example outputs from the source GRDECLs. It runs the local **synthetic** T>Map generator, so it is suitable for a clean checkout, demonstration, and testing—not as a replacement for an actual T>Map calculation.

```powershell
powershell -ExecutionPolicy Bypass -File .\regenerate_synthetic_outputs.ps1
```

To rebuild just one workflow, for example Control:

```powershell
powershell -ExecutionPolicy Bypass -File .\regenerate_synthetic_outputs.ps1 -Approach Control
```

For a new GRDECL set or a different facies keyword:

```powershell
powershell -ExecutionPolicy Bypass -File .\regenerate_synthetic_outputs.ps1 `
  -SourceDir "C:\path\to\source-grdecls" `
  -FaciesProperty "FACIES"
```

## Facies codes and labels

The scripts do **not** require a predefined list of codes: every integer value found in `$FaciesProperty` is processed automatically. Code `0` is omitted by default from Union, Control, and Uber; add `--include-zero-facies` to include it.

Define display/output labels and dashboard colours in `dashboard\facies_config.json`:

```json
{
  "facies_colors": { "101": "#4e79a7", "205": "#f28e2b" },
  "facies_names": { "101": "Offshore", "205": "Channel sand" }
}
```

The Union, Control, and Uber builders use `facies_names` in output names. Pass another file with `--facies-config <path>` if the project needs its own label file. Unknown codes remain valid and are named `facies_<code>`.

## T>Map hand-off rule

Every approach has the same hand-off:

1. Run the **build** command to create point sets in its `01_*` folder.
2. Send those point sets to T>Map.
3. Put the returned point sets in its matching `02_*_with_tmap_data` folder, retaining the input filename and the ID columns (`CellIndex`, and where present `Realization`).
4. Run the **append** command. It writes GRDECL outputs to `03_*` (and Uber optionally writes a Petrel-standard `04_*` folder).

`generate_tmap_pointsets.py` is only an MVP/test generator. Use it when synthetic output is wanted; do **not** run it over real returned T>Map files.

Use the lean property profile unless a larger exchange is specifically needed:

```powershell
$Profile = "reservoir_quality"
```

## 1. Best-fit: one T>Map run per realization

Use when each realization should be calculated and mapped back independently.

### Build point sets

```powershell
& $Python .\scripts\grdecl_to_petrel_pointsets.py `
  --grdecl-dir $SourceDir `
  --output-dir ".\outputs\Best-fit approach\01_3d_points_from_original_grdecls" `
  --property $FaciesProperty
```

Each source model produces a point set with the same base filename plus `_ReservoirGrid`.

### Optional synthetic T>Map result

```powershell
& $Python .\scripts\generate_tmap_pointsets.py `
  --source-dir ".\outputs\Best-fit approach\01_3d_points_from_original_grdecls" `
  --output-dir ".\outputs\Best-fit approach\02_3d_points_with_tmap_data" `
  --glob "*_ReservoirGrid" `
  --property-profile $Profile
```

### Append real or synthetic results

```powershell
& $Python .\scripts\append_best_fit_tmap_to_grdecls.py `
  --grdecl-dir $SourceDir `
  --pointset-dir ".\outputs\Best-fit approach\02_3d_points_with_tmap_data" `
  --output-dir ".\outputs\Best-fit approach\03_augmented_grdecls_with_tmap_data"
```

## 2. Multi-realization Union: all actual cells by facies

Use when T>Map can process every actual facies cell across the realization set. Append-back is exact by `Realization` and `CellIndex`.

### Build facies unions

```powershell
& $Python .\scripts\build_union_pointsets_by_facies.py `
  --grdecl-dir $SourceDir `
  --output-dir ".\outputs\Multi-realization union approach\01_union_pointsets_by_facies" `
  --property $FaciesProperty `
  --facies-config $FaciesConfig
```

### Optional synthetic T>Map result

```powershell
& $Python .\scripts\generate_tmap_pointsets.py `
  --source-dir ".\outputs\Multi-realization union approach\01_union_pointsets_by_facies" `
  --output-dir ".\outputs\Multi-realization union approach\02_union_pointsets_with_tmap_data" `
  --glob "union_facies_*" `
  --property-profile $Profile
```

### Append returned properties

```powershell
& $Python .\scripts\append_union_tmap_to_grdecls.py `
  --grdecl-dir $SourceDir `
  --pointset-dir ".\outputs\Multi-realization union approach\02_union_pointsets_with_tmap_data" `
  --output-dir ".\outputs\Multi-realization union approach\03_augmented_grdecls_from_union_lookup"
```

## 3. Multi-realization Control: reduced actual-cell sample

Use to reduce the T>Map workload. For each realization, XY column, and facies, the builder retains the top/bottom cells plus intermediate controls at the requested maximum vertical spacing. Append-back interpolates vertically within the same realization, XY column, and facies.

### Build control points

```powershell
& $Python .\scripts\build_control_pointsets_by_facies.py `
  --grdecl-dir $SourceDir `
  --output-dir ".\outputs\Multi-realization control approach\01_control_pointsets_by_facies" `
  --property $FaciesProperty `
  --max-vertical-spacing 50 `
  --facies-config $FaciesConfig
```

### Optional synthetic T>Map result

```powershell
& $Python .\scripts\generate_tmap_pointsets.py `
  --source-dir ".\outputs\Multi-realization control approach\01_control_pointsets_by_facies" `
  --output-dir ".\outputs\Multi-realization control approach\02_control_pointsets_with_tmap_data" `
  --glob "control_facies_*" `
  --property-profile $Profile
```

### Append returned properties by vertical interpolation

```powershell
& $Python .\scripts\append_control_tmap_to_grdecls.py `
  --grdecl-dir $SourceDir `
  --pointset-dir ".\outputs\Multi-realization control approach\02_control_pointsets_with_tmap_data" `
  --output-dir ".\outputs\Multi-realization control approach\03_augmented_grdecls_from_control_interpolation" `
  --property $FaciesProperty
```

## 4. Multi-realization Uber: reusable regular lookup grid

Use to create one facies-specific regular XY/Z lookup library that can be reused for current or future facies realizations. It is not restricted to actual facies-cell occurrences.

### Build Uber lookup point sets

```powershell
& $Python .\scripts\build_uber_pointsets_by_facies.py `
  --grdecl-dir $SourceDir `
  --output-dir ".\outputs\Multi-realization Uber approach\01_uber_pointsets_by_facies" `
  --property $FaciesProperty `
  --vertical-spacing 25 `
  --facies-config $FaciesConfig
```

Use `--vertical-spacing auto` to choose from the default `10,25,50 m` candidates under the 1,000,000-point limit.

### Optional synthetic T>Map result

```powershell
& $Python .\scripts\generate_tmap_pointsets.py `
  --source-dir ".\outputs\Multi-realization Uber approach\01_uber_pointsets_by_facies" `
  --output-dir ".\outputs\Multi-realization Uber approach\02_uber_pointsets_with_tmap_data" `
  --glob "uber_facies_*" `
  --property-profile $Profile
```

### Append returned lookup properties

```powershell
& $Python .\scripts\append_uber_tmap_to_grdecls.py `
  --grdecl-dir $SourceDir `
  --pointset-dir ".\outputs\Multi-realization Uber approach\02_uber_pointsets_with_tmap_data" `
  --output-dir ".\outputs\Multi-realization Uber approach\03_augmented_grdecls_from_uber_lookup" `
  --property $FaciesProperty
```

### Optional Petrel/Eclipse-standard output

```powershell
& $Python .\scripts\write_petrel_standard_uber_grdecls.py `
  --grdecl-dir $SourceDir `
  --pointset-dir ".\outputs\Multi-realization Uber approach\02_uber_pointsets_with_tmap_data" `
  --output-dir ".\outputs\Multi-realization Uber approach\04_petrel_standard_grdecls_from_uber_lookup"
```

The `03_*` Uber output contains the complete reservoir-quality property profile. The `04_*` output uses Petrel/Eclipse-friendly property names (`FACIES`, `PORO`, `PERMX`, `PERMY`, `PERMZ`, etc.).

## Property profile and import notes

`reservoir_quality` returns porosity/permeability mean, standard deviation, and P10/P25/P50/P75/P90. Appended GRDECL keywords are shortened for Eclipse/Petrel compatibility. The Uber Petrel-standard writer produces the import-oriented mean/P10/P50/P90/standard-deviation subset plus `FACIES`, `SATNUM`, `ROCK`, and `FIPNUM`.

If returned T>Map files are missing an identity column or use a different row order, do not append them: recreate/return the point sets with their original headers and ID columns intact.
