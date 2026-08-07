# GO-Forward integrated forward modelling workflow

This repository provides a reproducible workflow from DionisosFlow/Eclipse GRDECL models through T>Map diagenesis modelling, DFN-property preparation, and the future DFM/DFN Generator handoff.

It includes a Streamlit dashboard for inspecting data and running the commands, plus standalone Python scripts for batch processing and reproducible execution. The supplied example outputs are synthetic: they show the full round trip without requiring a live T>Map calculation.

## What the workflow does

1. Reads one or more GRDECL models containing geometry (`SPECGRID`, `COORD`, `ZCORN`) and an integer facies property.
2. Builds T>Map 3D point sets that preserve cell identity.
3. Sends those point sets to T>Map, or creates synthetic T>Map-style properties for demonstration/testing.
4. Appends or interpolates the returned properties back onto the original GRDECL grids.
5. Creates facies-aware DFN-preparation geomechanical GRDECLs.
6. Prepares a reproducible handoff to a GRDECL-capable DFM/DFN Generator executable.

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
│   └── <project-name>/
│       ├── source_grdecls/            Source GRDECL realizations
│       └── facies_config.json         Project-specific facies definitions
├── scripts/                           Reusable command-line workflow scripts
├── outputs/<project-name>/            Generated point sets, augmented and DFN-prepared GRDECLs (not versioned)
├── regenerate_synthetic_outputs.py    Rebuild all demonstration outputs locally
├── run_dashboard.py                   Start the dashboard
├── WORKFLOW.md                        Full command-by-command workflow guide
└── requirements-dashboard.txt         Dashboard Python dependencies
```

`outputs/` is intentionally excluded from Git: it can be large and is regenerated from the source data. It remains on the local machine after being removed from Git's index.

All generated 3D point-set filenames use the suffix `_3d_pointset`; this distinguishes the exported points from the source GRDECL grid.

## Projects

The dashboard starts with a **Project** control in the left sidebar. Select an existing project or enter a new name and choose **Create project**. A project keeps its input and output data separate:

```text
input/<project-name>/source_grdecls/
input/<project-name>/facies_config.json
outputs/<project-name>/<approach>/
```

The supplied SS-201 examples are in project `SS_201_Gassum_V0`. Copy new GRDECL files into the selected project's `source_grdecls` folder, then define its facies in Tab 1.

To delete the currently selected project, use **Remove selected project** in the sidebar. Its confirmation dialog lets you either delete only `outputs/<project-name>` while keeping source inputs, or permanently delete both `input/<project-name>` and `outputs/<project-name>`.

For a new project, Tab 1 accepts an external local source folder. Select **Enter another folder path**, use **Browse source folder in Windows Explorer**, then choose **Copy source GRDECLs into project**. This copies the `.grdecl` files and, where available, its `facies_config.json` into the active project's input folder.

## Requirements

- Python 3.10+ with `streamlit`, `pandas`, `numpy`, and `plotly` installed
- Source GRDECL models with `SPECGRID`, `COORD`, `ZCORN`, and an integer facies property

Install the dashboard dependencies if needed:

```text
python -m pip install -r requirements-dashboard.txt
```

## Quick start

### 1. Start the dashboard

```text
python run_dashboard.py
```

Open the local URL printed by Streamlit (normally `http://localhost:8501`).

### 2. Recreate all example outputs

The supplied launcher rebuilds the Best-fit, Union, Control, and Uber example outputs using synthetic T>Map-style properties:

```text
python regenerate_synthetic_outputs.py
```

To target another project:

```text
python regenerate_synthetic_outputs.py --project "My_Project"
```

To run only one workflow:

```text
python regenerate_synthetic_outputs.py --approach Control
```

### Regeneration defaults versus dashboard options

`regenerate_synthetic_outputs.py` is a reproducible demonstration launcher, not a record of every selection available in the dashboard. It uses every GRDECL in the source folder, creates full-resolution Best-fit pointsets, and uses its `--control-vertical-spacing` and `--uber-vertical-spacing` parameters. The dashboard additionally supports selecting models, reduced/reservoir-only Best-fit exports, and interactive sampling previews. Add `--dry-run` to inspect the commands without writing files.

Before regenerating the **Control** approach, clear or replace its three `outputs\Multi-realization control approach\0*` folders. The current Control workflow creates shared facies-envelope controls and honours enabled T>Map facies; old pointsets or returned synthetic files can otherwise remain in those folders. The launcher should be run with the current source `facies_config.json`; it is intentionally not a substitute for a real T>Map run. It recreates synthetic pointsets and augmented GRDECLs through the diagenesis review stage, but not Tab 4 DFN-prepared GRDECLs because those depend on chosen formulas, property inputs, and optional fallback settings.

### 3. Run a new GRDECL data set

Point the launcher to a new folder and provide the exact facies property keyword. The keyword is case-sensitive.

```text
python regenerate_synthetic_outputs.py --source-dir "C:\path\to\source-grdecls" --facies-property "FACIES"
```

For an actual T>Map project, use the individual build and append commands in [WORKFLOW.md](WORKFLOW.md): send the `01_*` point sets to T>Map, put the returned files in the matching `02_*_with_tmap_data` folder, then run that approach's append script. Do not run the synthetic generator over real returned T>Map files.

## Facies configuration

Facies codes are discovered dynamically, so scripts support new integer codes without code changes. For each new DionisosFlow model, create a source-specific configuration by scanning its GRDECLs and entering the meaning of every observed integer:

```text
python scripts\initialize_facies_config.py --grdecl-dir "C:\path\to\source-grdecls" --property "FACIES"
```

This writes `facies_config.json` beside the source GRDECLs. Pass that file to multi-realization builders with `--facies-config`; `regenerate_synthetic_outputs.py` selects it automatically when present. The dashboard can import the same file through **Load facies color JSON**.

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

Generated `outputs/` are deliberately not versioned. They can be recreated from the included example GRDECLs by running `regenerate_synthetic_outputs.py`, which produces synthetic sample T>Map data and the corresponding augmented GRDECLs. For a real project, replace the synthetic return files with the actual T>Map results. If source data are confidential or too large for GitHub, store them in the appropriate GEUS/OneDrive location and document their access path separately.

## Fracture-modelling stages

**Tab 4, Prepare DFN inputs**, reads an augmented GRDECL and writes an approach-specific DFN-prepared GRDECL folder. The output retains geometry, facies, and appended T>Map data, and adds `DFNPorosity`, `DFNEffectiveStress_MPa`, `YoungsModulus_Pa`, `PoissonsRatio`, `FrictionCoefficient`, `FractureEnergy_J_m2`, and `GEOMECHSOURCE`. It can also add `DIPAZIMUTH`: a locally smoothed top-horizon down-dip azimuth at each I/J column, in degrees clockwise from North. `GEOMECHSOURCE` identifies T>Map-derived values (`1`) and the optional depth-compaction fallback (`2`).

**Tab 5, Run DFN Generator**, writes a GRDECL-capable `DFMGenerator_GRDECL.exe` configuration, optionally creates a structurally valid cropped GRDECL test grid, and launches the executable as a detached background process. Each run retains its copied/cropped input, configuration, manifest, status, log, and output files in the approach-specific next workflow folder: `05_DFN_generator_runs` for Best-fit, Union, and Control, and `06_DFN_generator_runs` for Uber. Property-only DFN-output GRDECLs are displayed against their run-input geometry in the Tab 5 viewer. Start with a cropped grid and a small timestep limit: explicit DFN generation can take substantially longer than the preceding GRDECL workflow.

## More detail

[WORKFLOW.md](WORKFLOW.md) contains the command-by-command workflow, including real T>Map hand-off rules, input requirements, facies setup, output folders, and Petrel/Eclipse-standard Uber output. The standard dashboard and regeneration routes use Python only and do not require a PowerShell execution-policy override.
