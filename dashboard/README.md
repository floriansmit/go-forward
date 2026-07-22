# GO-Forward GRDECL/T>Map Dashboard

Streamlit MVP for inspecting the DionisosFlow GRDECL to T>Map point-set workflow.

## Install

```bash
python -m pip install -r requirements-dashboard.txt
```

## Run

```bash
python workflow.py dashboard        # or: streamlit run dashboard/streamlit_app.py
```

The dashboard has three tabs:

- **Tab 1:** load source GRDECLs, inspect IJK/XYZ cell-centre views, and run GRDECL-to-point-set builders.
- **Tab 2:** inspect T>Map-style point sets, generate synthetic T>Map data for MVP testing, and append returned point-set properties to GRDECL.
- **Tab 3:** inspect augmented GRDECL outputs, including map and cross-section views of appended properties.

Rob and Linda's real T>Map outputs should replace the synthetic files in the matching `02_*_with_tmap_data` output folder before running the append step.
