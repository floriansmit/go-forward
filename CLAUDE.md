# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A reproducible round-trip workflow: DionisosFlow/Eclipse **GRDECL** reservoir models → Petrel 3D **point sets** → **T>Map** → properties appended back onto GRDECL. Plain Python scripts do the batch processing; a Streamlit dashboard inspects data and runs the commands. There is no build step, no test suite, and no linter configured.

`WORKFLOW.md` has the exact per-stage PowerShell commands; `README.md` has the overview. Read those before changing a pipeline.

## Commands

```bash
# Run the dashboard (cross-platform; serves http://localhost:8501)
python workflow.py dashboard

# Rebuild all synthetic example outputs from the source GRDECLs
python workflow.py regenerate
python workflow.py regenerate --approach Control    # one approach only
python workflow.py regenerate --dry-run             # print the step sequence, run nothing
python test_workflow.py                             # launcher self-check (no framework)
```

Windows equivalents: `powershell -ExecutionPolicy Bypass -File .\run_dashboard.ps1` and `.\regenerate_synthetic_outputs.ps1 [-Approach Control]`.

Run an individual script **from the repo root as a file path**, not as a module:

```bash
python scripts/grdecl_to_petrel_pointsets.py --grdecl-dir <dir> --output-dir <dir> --property Facies
```

This matters: scripts import siblings directly (`from grdecl_utils import ...`), which only resolves because running `python scripts/foo.py` puts `scripts/` on `sys.path[0]`. The dashboard runs them the same way — `subprocess.run([sys.executable, "scripts/foo.py", ...], cwd=ROOT)`. `python -m scripts.foo` will break the imports.

`workflow.py` (repo root) is the cross-platform entry point — `dashboard` and `regenerate` subcommands mirror the two `.ps1` wrappers, running every child script through `sys.executable` (the interpreter/venv you launch it with). The `.ps1` wrappers are Windows-only and duplicate the `regenerate` step sequence, so keep the two in sync if you change the pipeline.

## Architecture

**Four alternative approaches, not sequential stages** (Best-fit, Union, Control, Uber — see the table in `README.md`). Each is a numbered 3-stage pipeline sharing the same T>Map hand-off:

1. `01_*` **build** — a `build_*`/`grdecl_to_petrel_pointsets.py` script writes Petrel point sets.
2. `02_*` **T>Map** — send `01_*` to T>Map, put returned files here. `generate_tmap_pointsets.py` writes *synthetic* stand-ins for demos/tests only — **never run it over real returned T>Map files.**
3. `03_*` **append** — the matching `append_*` script maps `02_*` properties back onto the GRDECL grids. Uber also has an optional `04_*` Petrel/Eclipse-standard writer.

**Append-back is keyed by identity columns, and the key differs per approach:** Best-fit matches point↔cell-centre by coordinate within `MATCH_TOLERANCE_M = 0.05` m (bucketed nearest-neighbour); Union does exact lookup by `Realization` + `CellIndex`; Control interpolates vertically within matching realization/XY-column/facies; Uber does vertical lookup on a regular grid. Returned T>Map files that lose their `CellIndex`/`Realization` columns or reorder rows cannot be appended.

**Shared code lives in two modules imported by the scripts:**
- `scripts/grdecl_utils.py` re-exports the real implementations from `append_best_fit_tmap_to_grdecls.py` (GRDECL tokenizing, `grdecl_cell_centers`, `mapaxes_transform`, `write_property`, and `path_for_io` for Windows extended-length paths). The Best-fit append script is the actual home of the GRDECL parsing/geometry; treat it as the shared core.
- `scripts/facies_config.py` reads display labels from `dashboard/facies_config.json`.

**Point-set format** is Petrel "Points with attributes" ASCII: `BEGIN HEADER`/`END HEADER` block declaring columns, leading `X Y Z Facies`, then approach-specific ID columns.

## Conventions and gotchas

- **Facies codes are discovered dynamically** from the property array — no hardcoded code list, new integer codes need no code changes. Unknown codes get the label `facies_<code>`.
- **The facies property keyword is case-sensitive** (`Facies` ≠ `FACIES`). It's a CLI arg on every script; default is `Facies`.
- **Code 0 is excluded by default** from Union/Control/Uber outputs; pass `--include-zero-facies` to keep it.
- **`outputs/` is gitignored** and regenerated — never rely on it being present, and don't commit it. Use a fresh/dedicated `outputs/<approach>` folder per source-data set so stale point sets aren't sent to T>Map.
- The coordinate transform (`mapaxes_transform`) assumes MAPAXES vectors describe **1000 m reference axes** — a property of this dataset, not general GRDECL.
