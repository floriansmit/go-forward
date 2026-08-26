# Testing & Verification Guide

GO-Forward uses `pytest` to test and verify background data transformations, geometry algorithms, and file I/O operations without depending on the UI.

---

## 1. Running Tests

Run the full test suite with `uv`:

```powershell
uv run pytest
```

For verbose output with code coverage:

```powershell
uv run pytest -v --cov=scripts
```

---

## 2. Test Architecture

The `tests/` directory is organized modularly by functional area:

| Test File | Focus Area | Key Assertions |
| :--- | :--- | :--- |
| [`test_grdecl_io.py`](file:///c:/git/go-forward/tests/test_grdecl_io.py) | File parsing & writing | Keyword extraction, repeat syntax expansion (`N*val`), Eclipse comments |
| [`test_grdecl_geometry.py`](file:///c:/git/go-forward/tests/test_grdecl_geometry.py) | Corner-point geometry | Cell center computation, pillar coordinates, MAPAXES coordinate projection |
| [`test_pointset_builders.py`](file:///c:/git/go-forward/tests/test_pointset_builders.py) | Point set generation | Best-fit, Union, Control envelope, and Uber regular grid generation |
| [`test_pointset_appenders.py`](file:///c:/git/go-forward/tests/test_pointset_appenders.py) | Property mapping | Header parsing, property aliasing, exact cell matching, NoValue markers |
| [`test_geomechanics.py`](file:///c:/git/go-forward/tests/test_geomechanics.py) | Rock physics formulas | Critical porosity model, shale stiffness, fallback depth compaction, dip azimuth |
| [`test_crop_grdecl.py`](file:///c:/git/go-forward/tests/test_crop_grdecl.py) | Subgrid cropping | Structural completeness, `COORD`/`ZCORN` slicing, J-reversal, Z-inversion |
| [`test_demo_generators.py`](file:///c:/git/go-forward/tests/test_demo_generators.py) | Demo models | Synthetic carbonate reef and crystalline pluton grid generation |

---

## 3. Writing New Background Tests

When adding new data transformations:
1. Use fixtures defined in [`tests/conftest.py`](file:///c:/git/go-forward/tests/conftest.py) for in-memory miniature grids.
2. Avoid asserting against UI components or Streamlit session state.
3. Test edge cases: empty strings, missing keywords, boundary porosity values ($\le 0, \ge \phi_c$), and vertical sign conventions.
