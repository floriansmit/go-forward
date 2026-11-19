"""Siliciclastic FSM stage; numerical and runtime code lives in scripts/."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import streamlit as st
from badlands_fsm import (
    DEFAULTS,
    export_grdecl,
    install_export,
    prepare_run,
    stratal_files,
)
from run_badlands_fsm import read_status, write_status


def render_badlands_tab(project_dir, source_dir, root, load_dataframe, visualize, max_rows):
    key = f"badlands::{project_dir.name}::"
    st.subheader("FSM · pyBadlands")
    st.warning("Facies are environmental proxies. Calibrate the facies mapping and absolute depth datum before T>Map.")
    left, right = st.columns([0.38, 0.62])
    runs_root = project_dir / "FSM pyBadlands" / "runs"
    with left:
        with st.form(key + "setup", border=False):
            st.markdown("**New model setup**")
            run_name = st.text_input("Run name", value="badlands_fsm", key=key + "name")
            dem_upload = st.file_uploader("Initial DEM (optional, headerless X Y elevation in metres)", type=["csv", "txt", "xyz"], key=key + "dem")
            cfg = {}
            cols = st.columns(2)
            for column, field, label in (
                (cols[0], "nx", "DEM nodes X"), (cols[1], "ny", "DEM nodes Y"),
            ):
                cfg[field] = column.number_input(label, min_value=3, max_value=1000, value=DEFAULTS[field], step=1, key=key + field)
            cfg["spacing_m"] = st.number_input("Node spacing (m)", min_value=1.0, value=DEFAULTS["spacing_m"], key=key + "spacing")
            with st.expander("Initial topography"):
                for field, label in (
                    ("origin_x", "Origin X (m)"), ("origin_y", "Origin Y (m)"),
                    ("upstream_elevation_m", "Upstream elevation (m)"), ("basin_elevation_m", "Basin elevation (m)"),
                    ("roughness_m", "Initial roughness (m)"),
                ):
                    cfg[field] = st.number_input(label, value=float(DEFAULTS[field]), key=key + field)
                cfg["seed"] = st.number_input("Random seed", min_value=0, value=42, key=key + "seed")
            with st.expander("Time and forcing", expanded=True):
                for field, label in (
                    ("duration_years", "Duration (years)"), ("output_interval_years", "Output interval (years)"),
                    ("layer_interval_years", "Layer interval (years)"), ("rainfall_m_year", "Rainfall (m/year)"),
                    ("sea_level_m", "Sea level elevation (m)"), ("subsidence_m_year", "Subsidence rate (m/year, positive down)"),
                ):
                    cfg[field] = st.number_input(label, value=float(DEFAULTS[field]), format="%.6g", key=key + field)
            with st.expander("Surface processes"):
                for field, label in (
                    ("erodibility", "Stream-power erodibility"), ("aerial_diffusion", "Aerial diffusion (m²/year)"),
                    ("marine_diffusion", "Marine diffusion (m²/year)"),
                ):
                    cfg[field] = st.number_input(label, min_value=0.0, value=DEFAULTS[field], format="%.6g", key=key + field)
            prepare = st.form_submit_button("Prepare run", icon=":material/save:")
        if prepare:
            try:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_name):
                    raise ValueError("Run name must start with a letter/number and contain only letters, numbers, underscores or hyphens.")
                dem = np.loadtxt(dem_upload) if dem_upload is not None else None
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
                run_dir = runs_root / f"{run_name}_{stamp}"
                cfg["uploaded_dem"] = dem_upload is not None
                prepare_run(run_dir, cfg, dem)
                st.session_state[key + "run"] = str(run_dir)
                st.success("Run prepared")
            except (OSError, ValueError) as exc:
                st.error(str(exc))

        runs = sorted((p for p in runs_root.glob("*") if (p / "model.xml").exists()), reverse=True)
        if not runs:
            st.info("No Badlands runs in this project.")
            return
        run = Path(st.selectbox("Run", [str(p) for p in runs], format_func=lambda p: Path(p).name, key=key + "run"))
        with st.expander("Saved model settings"):
            st.json(json.loads((run / "settings.json").read_text(encoding="utf-8")))
        st.download_button("Download model XML", (run / "model.xml").read_bytes(), "model.xml", mime="application/xml", icon=":material/download:", key=key + "xml")
        st.markdown("**Badlands runtime**")
        state = read_status(run)
        backend_default = "WSL" if state.get("backend", "wsl" if os.name == "nt" else "python") == "wsl" else "External Python"
        backend_label = st.segmented_control("Environment", ["WSL", "External Python"], default=backend_default, key=key + "backend")
        backend = "wsl" if backend_label == "WSL" else "python"
        distribution = st.text_input("WSL distribution", state.get("distribution", "Ubuntu-24.04"), key=key + "distribution") if backend == "wsl" else ""
        default_python = state.get("python") if state.get("backend") == backend else None
        interpreter = st.text_input("Badlands Python interpreter", default_python or ("python3" if backend == "wsl" else "python"), key=key + "python::" + backend)
        command = [str(root / "scripts" / "run_badlands_fsm.py"), "--run-dir", str(run), "--backend", backend, "--python", interpreter, "--distribution", distribution]
        busy = state.get("status") in {"launching", "running"}
        controls = st.columns(2)
        if controls[0].button("Test runtime", icon=":material/check_circle:", key=key + "probe", disabled=busy):
            try:
                result = subprocess.run([sys.executable, *command, "--probe"], cwd=root, capture_output=True, text=True,
                                        timeout=60, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                (st.success if result.returncode == 0 else st.error)((result.stdout + result.stderr).strip() or f"Runtime exit code: {result.returncode}")
            except (OSError, subprocess.SubprocessError) as exc:
                st.error(str(exc))
        if controls[1].button("Run Badlands", icon=":material/play_arrow:", key=key + "start", disabled=busy or any(run.glob("output*")) or (run / "model_pid.json").exists()):
            try:
                write_status(run, status="launching")
                with (run / "launcher.log").open("a", encoding="utf-8") as log:
                    subprocess.Popen([sys.executable, *command], cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                st.rerun()
            except OSError as exc:
                write_status(run, status="failed", error=str(exc))
                st.error(str(exc))
        with st.container(horizontal=True):
            if st.button("Refresh", icon=":material/refresh:", key=key + "refresh"):
                st.rerun()
            if st.button("Stop run", icon=":material/stop:", key=key + "stop", disabled=not busy):
                (run / "cancel.request").touch()
                st.rerun()
        if state:
            st.metric("Run status", state.get("status", "prepared"))
            if state.get("error"):
                st.error(state["error"])
        with st.expander("Run log", expanded=state.get("status") == "failed"):
            for name in ("launcher.log", "badlands.log"):
                if (run / name).exists():
                    with (run / name).open("rb") as handle:
                        handle.seek(max(0, (run / name).stat().st_size - 12000))
                        st.code(handle.read().decode("utf-8", errors="replace"), language="text")

    with right:
        st.markdown("**Stratigraphy → GRDECL**")
        files = stratal_files(run)
        snapshot = st.selectbox("Regular stratigraphy snapshot", files, index=len(files) - 1 if files else None,
                                format_func=lambda p: p.name, key=key + "snapshot")
        external = st.text_input("External sed.timeN.hdf5 file (optional)", key=key + "external")
        source = Path(external.strip()) if external.strip() else snapshot
        with st.form(key + "export", border=False):
            filename = st.text_input("GRDECL filename", "badlands_fsm.grdecl", key=key + "filename")
            datum = st.number_input("Depth datum elevation (m)", value=0.0, key=key + "datum",
                                    help="GRDECL Z = datum elevation minus Badlands elevation. No burial shift or seismic stretch/squeeze is applied.")
            shallow = st.number_input("Shallow-marine maximum palaeowater depth (m)", min_value=0.1, value=30.0, key=key + "shallow")
            minimum = st.number_input("Minimum active mean cell thickness (m)", min_value=0.0, value=0.000001, format="%.6g", key=key + "minimum")
            config_path = source_dir / "facies_config.json"
            facies_names = json.loads(config_path.read_text(encoding="utf-8")).get("facies_names", {}) if config_path.exists() else {}
            codes = []
            for label, default in (("Terrestrial", 8), ("Shallow marine", 4), ("Offshore", 1)):
                if facies_names:
                    options = sorted(map(int, facies_names))
                    code = st.selectbox(f"{label} facies code", options, index=options.index(default) if default in options else 0,
                                        format_func=lambda c: f"{c}: {facies_names[str(c)]}", key=key + label)
                else:
                    code = st.number_input(f"{label} facies code", min_value=1, value=default, key=key + label)
                codes.append(int(code))
            export = st.form_submit_button("Export GRDECL", icon=":material/file_export:", disabled=source is None or busy)
        if export:
            try:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*\.[gG][rR][dD][eE][cC][lL]", filename):
                    raise ValueError("Use a simple .grdecl filename containing letters, numbers, hyphens or underscores.")
                result = export_grdecl(source, run / "grdecl" / filename, datum_elevation_m=datum,
                                       shallow_depth_m=shallow, facies_codes=tuple(codes), min_thickness_m=minimum)
                st.success(f"Exported {result['active_cells']:,} active cells")
            except (OSError, ValueError, ImportError) as exc:
                st.error(str(exc))
        exports = sorted((run / "grdecl").glob("*.grdecl"))
        if exports:
            selected = st.selectbox("Exported GRDECL", exports, format_func=lambda p: p.name, key=key + "result")
            st.download_button("Download GRDECL", selected.read_bytes(), selected.name, icon=":material/download:", key=key + "download")
            if st.button("Add to source GRDECLs", icon=":material/arrow_forward:", key=key + "adopt"):
                try:
                    install_export(selected, source_dir)
                    st.success(f"Added {selected.name} to this project's source models")
                    st.rerun()
                except (OSError, ValueError) as exc:
                    st.error(str(exc))
            with st.expander("Export provenance"):
                st.json(json.loads(selected.with_suffix(".badlands.json").read_text(encoding="utf-8")))
            with st.expander("Model preview", expanded=False):
                if st.checkbox("Show model", key=key + "preview"):
                    df = load_dataframe(str(selected), max_rows)
                    if "ACTNUM" in df:
                        df = df.loc[df["ACTNUM"].astype(float) > 0].copy()
                    visualize(df, key + "viewer", "Facies", is_grdecl=True, grdecl_path=str(selected))
