# GO-Forward GRDECL/T>Map Dashboard

Streamlit MVP for inspecting the DionisosFlow GRDECL to T>Map point-set workflow.

## Install

```powershell
python -m pip install -r requirements-dashboard.txt
```

## Run

```powershell
python run_dashboard.py
```

This uses the Python interpreter that starts the command and does not require a PowerShell execution-policy override.

The dashboard has three tabs:

- **1. Prepare models for diagenesis (FSM → FDM):** load source GRDECLs, inspect IJK/XYZ cell-centre views, and create 3D pointsets.
- **2. Diagenesis modelling data (T>Map):** inspect T>Map-style point sets, generate synthetic T>Map data for MVP testing, and append returned properties to GRDECL.
- **3. Review diagenesis results:** inspect augmented GRDECL outputs, including map and cross-section views of appended properties.
- **4. Prepare and run fracture modelling (FDM → FFM / DFN):** assign facies-calibrated geomechanical properties and prepare DFN-ready GRDECLs.

Rob and Linda's real T>Map outputs should replace the synthetic files in the matching `02_*_with_tmap_data` output folder before running the append step.
