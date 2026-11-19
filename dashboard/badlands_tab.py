"""Siliciclastic FSM setup, managed execution, and model handoff."""
from __future__ import annotations

import json
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
from badlands_runtime import cached_runtime, request_windows_support
from run_badlands_fsm import read_status, write_status
from run_badlands_pipeline import ACTIVE_STATUSES


def launch_pipeline(run: Path, root: Path, allow_setup: bool, external: dict | None):
    command = [sys.executable, str(root / "scripts" / "run_badlands_pipeline.py"), "--run-dir", str(run)]
    if allow_setup:
        command.append("--allow-setup")
    if external:
        command.extend(["--backend", external["backend"], "--python", external["python"], "--distribution", external["distribution"]])
    (run / "execution_settings.json").write_text(json.dumps({"allow_setup": allow_setup, "external": external}), encoding="utf-8")
    write_status(run, status="queued", stage="Preparing simulation", error="")
    with (run / "launcher.log").open("a", encoding="utf-8") as log:
        try:
            subprocess.Popen(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            write_status(run, status="failed", error=str(exc))
            raise


def show_run_progress(run: Path, key: str):
    state = read_status(run)
    status = state.get("status", "prepared")
    previous = st.session_state.get(key + "observed")
    st.session_state[key + "observed"] = status
    if previous in ACTIVE_STATUSES and status not in ACTIVE_STATUSES:
        st.rerun(scope="app")
    st.metric("Run status", status)
    if state.get("stage"):
        st.caption(state["stage"])
    if state.get("error"):
        st.error(state["error"])
    if status in ACTIVE_STATUSES:
        st.status(state.get("stage", "Simulation in progress"), state="running", expanded=False)
    if st.button("Stop simulation", icon=":material/stop:", key=key + "stop", disabled=status not in ACTIVE_STATUSES):
        (run / "cancel.request").touch()
        st.info("Stopping after the current setup transaction, if one is in progress.")
    with st.expander("Run logs", expanded=status == "failed"):
        for name in ("launcher.log", "setup.log", "badlands.log"):
            if (run / name).exists():
                with (run / name).open("rb") as handle:
                    handle.seek(max(0, (run / name).stat().st_size - 12000))
                    content = handle.read().decode("utf-8", errors="replace")
                if content:
                    st.text(name)
                    st.code(content, language="text")


def export_controls(source_dir: Path, key: str, defaults: dict | None = None) -> dict:
    defaults = defaults or {}
    datum = st.number_input("Depth datum elevation (m)", value=float(defaults.get("datum_elevation_m", 0)), key=key + "datum",
                            help="GRDECL Z = datum elevation minus Badlands elevation. No seismic stretch/squeeze is inferred.")
    shallow = st.number_input("Shallow-marine maximum palaeowater depth (m)", min_value=0.1, value=float(defaults.get("shallow_depth_m", 30)), key=key + "shallow")
    minimum = st.number_input("Minimum active mean cell thickness (m)", min_value=0.0, value=float(defaults.get("min_thickness_m", 1e-6)), format="%.6g", key=key + "minimum")
    path = source_dir / "facies_config.json"
    names = json.loads(path.read_text(encoding="utf-8")).get("facies_names", {}) if path.exists() else {}
    codes = []
    for label, default in zip(("Terrestrial", "Shallow marine", "Offshore"), defaults.get("facies_codes", [8, 4, 1]), strict=True):
        if names:
            options = sorted(map(int, names))
            code = st.selectbox(f"{label} facies code", options, index=options.index(default) if default in options else 0,
                                format_func=lambda c: f"{c}: {names[str(c)]}", key=key + label)
        else:
            code = st.number_input(f"{label} facies code", min_value=1, value=default, key=key + label)
        codes.append(int(code))
    return {"datum_elevation_m": datum, "shallow_depth_m": shallow, "min_thickness_m": minimum, "facies_codes": codes}


def render_badlands_tab(project_dir, source_dir, root, load_dataframe, visualize, max_rows):
    key = f"badlands::{project_dir.name}::"
    st.subheader("FSM · pyBadlands")
    st.warning("Facies are environmental proxies. Calibrate the facies mapping and absolute depth datum before T>Map.")
    runs_root = project_dir / "FSM pyBadlands" / "runs"
    runs = sorted((p for p in runs_root.glob("*") if (p / "model.xml").exists()), reverse=True)
    busy = any(read_status(p).get("status") in ACTIVE_STATUSES for p in runs)
    installed = bool(cached_runtime())
    if not installed and any(read_status(p).get("needs_windows_support") for p in runs) and st.button("Enable Windows simulation support", icon=":material/admin_panel_settings:", key=key + "enable_wsl", disabled=busy):
        try:
            request_windows_support()
            st.info("Approve the Windows administrator prompt. Restart Windows if requested, then run the simulation again. No terminal commands are needed.")
        except (OSError, RuntimeError) as exc:
            st.error(str(exc))
    with st.expander("Advanced solver settings"):
        mode = st.selectbox("Solver environment", ["Managed (automatic)", "External Python", "External WSL"], key=key + "mode")
        external = None
        if mode != "Managed (automatic)":
            python = st.text_input("Badlands Python interpreter", "python3", key=key + "python")
            distro = st.text_input("WSL distribution", "Ubuntu-24.04", key=key + "distribution") if mode == "External WSL" else ""
            external = {"backend": "wsl" if mode == "External WSL" else "python", "python": python, "distribution": distro}
        allow_repair = st.checkbox("Allow managed runtime repair downloads", key=key + "repair") if installed else False

    with st.form(key + "setup", border=False):
        left, right = st.columns([0.5, 0.5])
        cfg = {}
        with left:
            st.markdown("**New model setup**")
            run_name = st.text_input("Run name", value="badlands_fsm", key=key + "name")
            dem_upload = st.file_uploader("Initial DEM (optional, headerless X Y elevation in metres)", type=["csv", "txt", "xyz"], key=key + "dem")
            cols = st.columns(2)
            for column, field, label in ((cols[0], "nx", "DEM nodes X"), (cols[1], "ny", "DEM nodes Y")):
                cfg[field] = column.number_input(label, min_value=3, max_value=1000, value=DEFAULTS[field], step=1, key=key + field)
            cfg["spacing_m"] = st.number_input("Node spacing (m)", min_value=1.0, value=DEFAULTS["spacing_m"], key=key + "spacing")
            with st.expander("Initial topography"):
                for field, label in (("origin_x", "Origin X (m)"), ("origin_y", "Origin Y (m)"),
                                     ("upstream_elevation_m", "Upstream elevation (m)"), ("basin_elevation_m", "Basin elevation (m)"),
                                     ("roughness_m", "Initial roughness (m)")):
                    cfg[field] = st.number_input(label, value=float(DEFAULTS[field]), key=key + field)
                cfg["seed"] = st.number_input("Random seed", min_value=0, value=42, key=key + "seed")
            with st.expander("Time and forcing", expanded=True):
                for field, label in (("duration_years", "Duration (years)"), ("output_interval_years", "Output interval (years)"),
                                     ("layer_interval_years", "Layer interval (years)"), ("rainfall_m_year", "Rainfall (m/year)"),
                                     ("sea_level_m", "Sea level elevation (m)"), ("subsidence_m_year", "Subsidence rate (m/year, positive down)")):
                    cfg[field] = st.number_input(label, value=float(DEFAULTS[field]), format="%.6g", key=key + field)
            with st.expander("Surface processes"):
                for field, label in (("erodibility", "Stream-power erodibility"), ("aerial_diffusion", "Aerial diffusion (m²/year)"),
                                     ("marine_diffusion", "Marine diffusion (m²/year)")):
                    cfg[field] = st.number_input(label, min_value=0.0, value=DEFAULTS[field], format="%.6g", key=key + field)
        with right:
            st.markdown("**GRDECL output**")
            options = export_controls(source_dir, key)
        consent = st.checkbox("Allow the one-time solver download and managed Linux installation (internet and several GB of disk space required)", key=key + "consent") if not installed and external is None else False
        execute = st.form_submit_button("Run simulation", icon=":material/play_arrow:", type="primary", disabled=busy)
        prepare = st.form_submit_button("Prepare run", icon=":material/save:", disabled=busy)
    if execute or prepare:
        try:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", run_name):
                raise ValueError("Run name must start with a letter/number and contain only letters, numbers, underscores or hyphens.")
            if execute and external is None and not installed and not consent:
                raise ValueError("Approve the one-time solver setup checkbox before starting the first simulation.")
            dem = np.loadtxt(dem_upload) if dem_upload is not None else None
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
            run = runs_root / f"{run_name}_{stamp}"
            prepare_run(run, cfg, dem)
            (run / "export_settings.json").write_text(json.dumps({"filename": run_name + ".grdecl", **options}, indent=2), encoding="utf-8")
            st.session_state[key + "run"] = str(run)
            if execute:
                launch_pipeline(run, root, consent or allow_repair, external)
            st.rerun()
        except (OSError, ValueError) as exc:
            st.error(str(exc))

    runs = sorted((p for p in runs_root.glob("*") if (p / "model.xml").exists()), reverse=True)
    if not runs:
        return
    run = Path(st.selectbox("Run", [str(p) for p in runs], format_func=lambda p: Path(p).name, key=key + "run"))
    interval = 2 if read_status(run).get("status") in ACTIVE_STATUSES else None
    st.fragment(run_every=interval)(show_run_progress)(run, key + str(run))
    retryable = read_status(run).get("status") == "failed" and (run / "execution_settings.json").exists() and not any(run.glob("output*")) and not (run / "model_pid.json").exists()
    if retryable and st.button("Retry simulation", icon=":material/replay:", key=key + "retry", disabled=busy):
        try:
            execution = json.loads((run / "execution_settings.json").read_text(encoding="utf-8"))
            launch_pipeline(run, root, execution.get("allow_setup", False) or allow_repair, execution.get("external"))
            st.rerun()
        except (OSError, ValueError) as exc:
            st.error(str(exc))
    with st.expander("Saved model settings"):
        st.json(json.loads((run / "settings.json").read_text(encoding="utf-8")))
        st.download_button("Download model XML", (run / "model.xml").read_bytes(), "model.xml", mime="application/xml", icon=":material/download:", key=key + "xml")
    with st.expander("Manual stratigraphy import or export"):
        files = stratal_files(run)
        snapshot = st.selectbox("Regular stratigraphy snapshot", files, index=len(files) - 1 if files else None, format_func=lambda p: p.name, key=key + "snapshot")
        path = st.text_input("External sed.timeN.hdf5 file (optional)", key=key + "external")
        source = Path(path.strip()) if path.strip() else snapshot
        filename = st.text_input("GRDECL filename", "badlands_fsm.grdecl", key=key + "filename")
        saved_options = json.loads((run / "export_settings.json").read_text(encoding="utf-8")) if (run / "export_settings.json").exists() else {}
        manual_options = export_controls(source_dir, key + str(run) + "::manual::", saved_options)
        if st.button("Export GRDECL", icon=":material/file_export:", key=key + "manual_export", disabled=source is None or busy):
            try:
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*\.grdecl", filename):
                    raise ValueError("Use a simple .grdecl filename.")
                export_grdecl(source, run / "grdecl" / filename, **manual_options)
                st.rerun()
            except (OSError, ValueError, ImportError) as exc:
                st.error(str(exc))
    exports = sorted((run / "grdecl").glob("*.grdecl"))
    if exports:
        selected = st.selectbox("Exported GRDECL", exports, format_func=lambda p: p.name, key=key + "result")
        st.download_button("Download GRDECL", selected.read_bytes(), selected.name, icon=":material/download:", key=key + "download")
        if st.button("Add to source GRDECLs", icon=":material/arrow_forward:", key=key + "adopt"):
            try:
                install_export(selected, source_dir)
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
        with st.expander("Export provenance"):
            st.json(json.loads(selected.with_suffix(".badlands.json").read_text(encoding="utf-8")))
        with st.expander("Model preview"):
            if st.checkbox("Show model", key=key + "preview"):
                df = load_dataframe(str(selected), max_rows)
                if "ACTNUM" in df:
                    df = df.loc[df["ACTNUM"].astype(float) > 0].copy()
                visualize(df, key + "viewer", "Facies", is_grdecl=True, grdecl_path=str(selected))
