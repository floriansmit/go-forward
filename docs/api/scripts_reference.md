# CLI Scripts & Tools Reference

The `scripts/` directory contains standalone, batch-capable CLI tools for each stage of the GO-Forward workflow.

---

## 1. Point Set Builders

### `build_best_fit_grdecl_to_pointset.py`
Exports every cell center (or reduced vertical samples) from a GRDECL file to a T>Map ASCII 3D point set.

```powershell
uv run python scripts/build_best_fit_grdecl_to_pointset.py `
  --grdecl-dir <path-to-source-grdecls> `
  --output-dir <path-to-pointsets> `
  --property Facies
```

### `build_multi_realizations_grdecls_to_union_pointsets.py`
Aggregates cells across all source realizations into separate point sets for each active facies code, recording `Realization` and `CellIndex`.

### `build_multi_realizations_grdecls_to_control_pointsets.py`
Extracts a shared vertical top/bottom occurrence envelope for each $(I, J)$ column across realizations and samples regular control points.

### `build_multi_realizations_grdecls_to_uber_pointsets.py`
Constructs a regular $(X, Y, Z)$ 3D lookup point set across the entire vertical span for each facies.

---

## 2. Property Appenders

### `append_best_fit_tmap_to_grdecls.py`
Maps returned T>Map property columns back to the original source GRDECL by exact `CellIndex` or column-wise vertical interpolation.

### `append_multi_realizations_union_tmap_to_grdecls.py`
Populates each source realization from the multi-realization union results using `(Realization, CellIndex)` lookup.

### `append_multi_realizations_control_tmap_to_grdecls.py`
Interpolates returned control series vertically into each source realization's cells.

### `append_multi_realizations_uber_tmap_to_grdecls.py`
Interpolates regular 3D lookup grid properties back to grid cells by facies and position.

---

## 3. Geomechanics & DFM Preparation

### `assign_geomechanical_properties.py`
Calculates linear elastic moduli ($E$ in Pa, $\nu$), friction ($\mu$), and fracture energy ($G_c$) from porosity, cement, and effective stress. Optionally appends locally smoothed top-horizon down-dip azimuth (`DIPAZIMUTH`).

### `crop_grdecl.py`
Extracts a rectangular subgrid from a corner-point GRDECL while preserving valid `COORD`, `ZCORN`, and cell properties. Supports J-flipping (`--dfn-flip-j`) and Z-inversion (`--dfn-invert-z`).

### `run_dfn_generator.py`
Executes `DFMGenerator_GRDECL.exe` as a managed subprocess, streaming logs and tracking lifecycle status in `run_status.json`.
