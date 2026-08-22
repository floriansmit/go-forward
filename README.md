# GO-Forward integrated forward modelling workflow

GO-Forward is a local Streamlit dashboard and a set of reproducible Python tools for preparing corner-point GRDECL models for diagenetic and dynamic fracture modelling (DFM). It supports several geological workflow profiles from one project-level interface.

## Workflow profiles

| Project type | Dashboard path | Current purpose |
| --- | --- | --- |
| **MVP** | FSM → FDM → FFM → DFM | Demonstrates the full DionisosFlow, T>Map, geomechanics, and DFM chain. |
| **Siliciclastics** | GRDECL → 3D points → T>Map → re-appended GRDECL | Production-oriented T>Map handoff with a Fault Seal Analysis placeholder. |
| **Carbonates** | FSM GRDECL → mesh → GOLEM/PHREEQC → re-appended GRDECL → DFM | Carbonate mesh/diagenesis handoff is scaffolded; direct DionisosFlow properties can already feed geomechanics. |
| **Crystalline rocks** | GRDECL inspection → geomechanics → DFM | Uses RockType/Lithology definitions rather than sedimentary facies. |

The active profile is fixed when a project is created. Its suffix is part of the project name, for example `_siliciclastics`, `_carbonates`, or `_crystalline`.

## Repository layout

```text
input/
  <project>/
    project_config.json
    source_grdecls/
      *.grdecl
      facies_config.json             # Rock-type definitions in crystalline projects
outputs/<project>/                   # generated locally; excluded from Git
reference_examples/                  # compact T>Map and DFM reference files
scripts/                             # reusable command-line tools and DFM executable
dashboard/streamlit_app.py           # dashboard entry point
run_dashboard.py                     # dashboard launcher
WORKFLOW.md                          # detailed siliciclastic/MVP command guide
```

The repository includes four input projects so each profile is immediately visible in the dashboard:

- `MVP_Gassum_mvp` (the five Gassum realizations for exercising multi-realization routes)
- `Siliciclastics_Gassum_siliciclastics` (the Gassum Base model for the single-model T>Map route)
- `Reef_Demo_carbonates`
- `Crystalline_Pluton_Demo_crystalline`

`outputs/` is intentionally not versioned. It can be large and is recreated locally from inputs or real returned modelling data.

## Install and run

[uv](https://docs.astral.sh/uv/getting-started/installation/) is the recommended dependency manager. It creates a project-local environment using the versions recorded in `uv.lock`.

```powershell
winget install --id=astral-sh.uv -e
cd C:\GGS\go-forward
uv sync
uv run python run_dashboard.py
```

Open the local URL printed by Streamlit, normally `http://localhost:8501`.

For a conventional Python environment instead:

```powershell
python -m pip install -r requirements-dashboard.txt
python run_dashboard.py
```

## Projects and data import

Create a project in the left sidebar by entering a base name and explicitly choosing a project type. The dashboard adds the workflow suffix and creates the matching input/output structure.

Use **Import source GRDECL file(s)** in the first workflow tab to select one or more `.grdecl` files. They are copied into the selected project's `source_grdecls` folder. The project list is derived from `input/`; externally renamed or removed input folders therefore disappear from the selector after a refresh.

Define facies, carbonate facies, or rock types in the first tab. The same project configuration supplies names and discrete colours in the viewers. Only siliciclastic/MVP projects have the T>Map inclusion switch.

## Siliciclastic/MVP data handoff

1. Select source GRDECL models and a conversion approach.
2. Build 3D point sets. Every current Best-fit point includes `CellIndex`; that is the preferred stable identity for return matching.
3. Run the exported point sets in T>Map.
4. Import returned point-set files in **FDM Append & View**, or copy them directly into the indicated `02_*` folder.
5. Append returned properties to the corresponding GRDECL. Older or vertically sampled returns without full CellIndex coverage are interpolated vertically only where necessary.
6. In **FFM Geomech preparation**, write DFM-ready GRDECL properties. In **FFM Run DFM**, create and launch a reproducible DFM run; inspect implicit and explicit results in **FFM View results**.

Synthetic T>Map data is a demonstration/testing facility only. Do not overwrite real returned T>Map point sets with it.

## Carbonates and crystalline rocks

Carbonate projects currently provide a clear handoff path: inspect the FSM GRDECL, prepare a future finite-element mesh and CellIndex mapping, import GOLEM/PHREEQC results, then re-append them to the authoritative GRDECL. Until reactive-diagenesis results are available, **FFM Geomech preparation** can use porosity and mineral/cement properties exported directly from DionisosFlow.

Crystalline projects skip the 3D-point and diagenesis stages. Define `RockType`, `ROCKTYPE`, `Lithology`, or another supported integer rock classification, assign geomechanical starting values by rock type, then prepare and run DFM.

## Recreate synthetic siliciclastic example outputs

The regeneration launcher applies only to the siliciclastic/MVP T>Map workflows. By default it rebuilds Best-fit, Union, Control, and Uber outputs for the supplied MVP multi-realization Gassum project:

```powershell
uv run python regenerate_synthetic_outputs.py
```

For a different project or one approach:

```powershell
uv run python regenerate_synthetic_outputs.py --project "My_Project_siliciclastics"
uv run python regenerate_synthetic_outputs.py --approach Control
```

It stops before DFM preparation because geomechanical formulas and property choices are project decisions made in the dashboard.

## Further documentation

- [WORKFLOW.md](WORKFLOW.md) gives the command-by-command T>Map and DFM route for siliciclastic/MVP projects.
- [dashboard/README.md](dashboard/README.md) explains the dashboard navigation and project profiles.
- [dashboard/FACIES_CONFIG.md](dashboard/FACIES_CONFIG.md) explains project classification definitions and colours.
- [reference_examples/README.md](reference_examples/README.md) describes the compact external reference files.
