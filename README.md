# GO-Forward GRDECL → T>Map workflow

This repository provides a reproducible workflow for converting DionisosFlow/Eclipse GRDECL reservoir models into T>Map 3D point sets, then returning T>Map properties to GRDECL.

It includes a Streamlit dashboard for inspecting data and running the commands, plus standalone Python scripts for batch processing and reproducible execution. The supplied example outputs are synthetic: they show the full round trip without requiring a live T>Map calculation.

## What the workflow does

1. Reads one or more GRDECL models containing geometry (`SPECGRID`, `COORD`, `ZCORN`) and an integer facies property.
2. Builds T>Map 3D point sets that preserve cell identity.
3. Sends those point sets to T>Map, or creates synthetic T>Map-style properties for demonstration/testing.
4. Appends or interpolates the returned properties back onto the original GRDECL grids.

The same source grids can be processed with four alternative approaches:

| Approach | Use case | T>Map input | Append-back method |
| --- | --- | --- | --- |
| **Best-fit** | Treat each realization independently. | Every grid cell in each realization. | Exact cell-centre match. |
| **Union** | Model all actual facies cells across the realization set. | One facies point set containing cells from every realization. | Exact lookup by realization and cell index. |
| **Control** | Reduce the number of T>Map points while retaining the multi-realization facies envelope. | One shared facies envelope per XY column: shallowest/deepest occurrence across selected realizations plus regular vertical controls. | Interpolate the shared facies/XY control series back into every realization. |
| **Uber** | Build a reusable regular facies lookup grid. | Regular XY/Z point sets by facies. | Vertical lookup/interpolation back to grid cells. |

The approaches are alternatives; they are not stages that must be run one after another.

## Repository layout

```text
.
├── dashboard/                         Streamlit dashboard and facies configuration
│   ├── streamlit_app.py               Dashboard entry point
│   └── facies_config.json             Facies labels and colours
├── input/
│   └── source_grdecls_from_dionisosflow/
│                                      Source GRDECL realizations
├── scripts/                           Reusable command-line workflow scripts
├── outputs/                           Generated point sets and augmented GRDECLs (not versioned)
├── workflow.py                        Cross-platform launcher (dashboard, regenerate)
├── regenerate_synthetic_outputs.ps1   Windows wrapper: rebuild all demonstration outputs
├── run_dashboard.ps1                  Windows wrapper: start the dashboard
├── WORKFLOW.md                        Full command-by-command workflow guide
└── requirements-dashboard.txt         Dashboard Python dependencies
```

`outputs/` is intentionally excluded from Git: it can be large and is regenerated from the source data. It remains on the local machine after being removed from Git's index.

All generated 3D point-set filenames use the suffix `_3d_pointset`; this distinguishes the exported points from the source GRDECL grid.

## Requirements

- Python 3 on Linux, macOS, or Windows — the `python workflow.py` launcher is cross-platform; the `*.ps1` launchers are Windows-only convenience wrappers
- Source GRDECL models with `SPECGRID`, `COORD`, `ZCORN`, and an integer facies property

The pipeline itself (`python workflow.py regenerate` and everything under `scripts/`) uses only the Python standard library — no install needed. Only the **dashboard** requires third-party packages (`streamlit`, `pandas`, `numpy`, `plotly`). Install them into a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate                  # Windows: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dashboard.txt
```

Because `workflow.py` runs everything through the active interpreter, `python workflow.py dashboard` uses this environment once it is activated. Leave it with `deactivate`.

## Quick start

### 1. Start the dashboard

```bash
python workflow.py dashboard
```

On Windows you can instead run:
```powershell
`powershell -ExecutionPolicy Bypass -File .\run_dashboard.ps1`
```

Open the local URL printed by Streamlit (normally `http://localhost:8501`).

### 2. Recreate all example outputs

The launcher rebuilds the Best-fit, Union, Control, and Uber example outputs using synthetic T>Map-style properties:

```bash
python workflow.py regenerate
```

To run only one workflow:

```bash
python workflow.py regenerate --approach Control
```

On Windows the equivalent is `powershell -ExecutionPolicy Bypass -File .\regenerate_synthetic_outputs.ps1 [-Approach Control]`.

### 3. Run a new GRDECL data set

Point the launcher to a new folder and provide the exact facies property keyword. The keyword is case-sensitive.

```bash
python workflow.py regenerate \
  --source-dir /path/to/source-grdecls \
  --facies-property FACIES
```

On Windows: `.\regenerate_synthetic_outputs.ps1 -SourceDir "C:\path\to\source-grdecls" -FaciesProperty "FACIES"`.

For an actual T>Map project, use the individual build and append commands in [WORKFLOW.md](WORKFLOW.md): send the `01_*` point sets to T>Map, put the returned files in the matching `02_*_with_tmap_data` folder, then run that approach's append script. Do not run the synthetic generator over real returned T>Map files.

## Facies configuration

Facies codes are discovered dynamically, so scripts support new integer codes without code changes. For each new DionisosFlow model, create a source-specific configuration by scanning its GRDECLs and entering the meaning of every observed integer:

```powershell
& $Python .\scripts\initialize_facies_config.py `
  --grdecl-dir "C:\path\to\source-grdecls" `
  --property "FACIES"
```

This writes `facies_config.json` beside the source GRDECLs. Pass that file to multi-realization builders with `--facies-config`; `regenerate_synthetic_outputs.ps1` selects it automatically when present. The dashboard can import the same file through **Load facies color JSON**.

The configuration records labels, colours, and hand-off metadata:

```json
{
  "facies_colors": { "101": "#4e79a7" },
  "facies_names": { "101": "Offshore" },
  "facies_metadata": {
    "101": { "category": "non_reservoir", "tmap_enabled": false }
  }
}
```

If a different model reuses an existing number with another geological meaning, use a separate source folder/configuration, or run the initializer with `--redefine --replace`. Unknown codes remain valid and are written with the label `facies_<code>` until they are defined.

## Data and reproducibility

Generated outputs and virtual environments are excluded through `.gitignore`. This keeps the repository practical to clone and avoids GitHub's large-file restrictions.

To reproduce generated outputs, retain the source GRDECLs and run `python workflow.py regenerate` (or `regenerate_synthetic_outputs.ps1` on Windows). If source data are confidential or too large for GitHub, store them in the appropriate GEUS/OneDrive location and document their access path separately.

## More detail

[WORKFLOW.md](WORKFLOW.md) contains exact PowerShell commands for each stage, including real T>Map hand-off rules, input requirements, facies setup, output folders, and Petrel/Eclipse-standard Uber output.
