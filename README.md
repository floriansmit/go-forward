# GO-Forward GRDECL → T>Map workflow

This repository provides a reproducible workflow for converting DionisosFlow/Eclipse GRDECL reservoir models into Petrel 3D point sets for T>Map, then returning T>Map properties to GRDECL.

It includes a Streamlit dashboard for inspecting data and running the commands, plus standalone Python scripts for batch processing and reproducible execution. The supplied example outputs are synthetic: they show the full round trip without requiring a live T>Map calculation.

## What the workflow does

1. Reads one or more GRDECL models containing geometry (`SPECGRID`, `COORD`, `ZCORN`) and an integer facies property.
2. Builds Petrel-compatible 3D point sets that preserve cell identity.
3. Sends those point sets to T>Map, or creates synthetic T>Map-style properties for demonstration/testing.
4. Appends or interpolates the returned properties back onto the original GRDECL grids.

The same source grids can be processed with four alternative approaches:

| Approach | Use case | T>Map input | Append-back method |
| --- | --- | --- | --- |
| **Best-fit** | Treat each realization independently. | Every grid cell in each realization. | Exact cell-centre match. |
| **Union** | Model all actual facies cells across the realization set. | One facies point set containing cells from every realization. | Exact lookup by realization and cell index. |
| **Control** | Reduce the number of T>Map points while retaining vertical facies structure. | Top/bottom and intermediate control cells per XY column, realization, and facies. | Vertical interpolation within matching realization, XY column, and facies. |
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
├── regenerate_synthetic_outputs.ps1   Rebuild all demonstration outputs locally
├── run_dashboard.ps1                  Start the dashboard
├── WORKFLOW.md                        Full command-by-command workflow guide
└── requirements-dashboard.txt         Dashboard Python dependencies
```

`outputs/` is intentionally excluded from Git: it can be large and is regenerated from the source data. It remains on the local machine after being removed from Git's index.

## Requirements

- Windows PowerShell
- Python with `streamlit`, `pandas`, `numpy`, and `plotly` installed
- Source GRDECL models with `SPECGRID`, `COORD`, `ZCORN`, and an integer facies property

Install the dashboard dependencies if needed:

```powershell
python -m pip install -r .\requirements-dashboard.txt
```

## Quick start

### 1. Start the dashboard

```powershell
powershell -ExecutionPolicy Bypass -File .\run_dashboard.ps1
```

Open the local URL printed by Streamlit (normally `http://localhost:8501`).

### 2. Recreate all example outputs

The supplied launcher rebuilds the Best-fit, Union, Control, and Uber example outputs using synthetic T>Map-style properties:

```powershell
powershell -ExecutionPolicy Bypass -File .\regenerate_synthetic_outputs.ps1
```

To run only one workflow:

```powershell
powershell -ExecutionPolicy Bypass -File .\regenerate_synthetic_outputs.ps1 -Approach Control
```

### 3. Run a new GRDECL data set

Point the launcher to a new folder and provide the exact facies property keyword. The keyword is case-sensitive.

```powershell
powershell -ExecutionPolicy Bypass -File .\regenerate_synthetic_outputs.ps1 `
  -SourceDir "C:\path\to\source-grdecls" `
  -FaciesProperty "FACIES"
```

For an actual T>Map project, use the individual build and append commands in [WORKFLOW.md](WORKFLOW.md): send the `01_*` point sets to T>Map, put the returned files in the matching `02_*_with_tmap_data` folder, then run that approach's append script. Do not run the synthetic generator over real returned T>Map files.

## Facies configuration

Facies codes are discovered dynamically, so scripts support new integer codes without code changes. Display labels and dashboard colours are defined in [`dashboard/facies_config.json`](dashboard/facies_config.json):

```json
{
  "facies_colors": { "101": "#4e79a7" },
  "facies_names": { "101": "Offshore" }
}
```

Unknown codes remain valid and are written with the label `facies_<code>`.

## Data and reproducibility

Generated outputs and virtual environments are excluded through `.gitignore`. This keeps the repository practical to clone and avoids GitHub's large-file restrictions.

To reproduce generated outputs, retain the source GRDECLs and run `regenerate_synthetic_outputs.ps1`. If source data are confidential or too large for GitHub, store them in the appropriate GEUS/OneDrive location and document their access path separately.

## More detail

[WORKFLOW.md](WORKFLOW.md) contains exact PowerShell commands for each stage, including real T>Map hand-off rules, input requirements, facies setup, output folders, and Petrel/Eclipse-standard Uber output.
