from __future__ import annotations

import csv
import hashlib
import importlib
import os
import re
import stat
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import streamlit as st
except ModuleNotFoundError as exc:  # pragma: no cover - shown only when launched without deps
    raise SystemExit("Streamlit is not installed. Run: python -m pip install -r requirements-dashboard.txt") from exc

try:
    import plotly.express as px
except ModuleNotFoundError:  # pragma: no cover - handled inside UI
    px = None


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
EXTERNAL_TOOLS = ROOT / "external-tools"
DATA_ROOT = Path(os.environ.get("GO_FORWARD_DATA_ROOT", ROOT / "data"))
WORKER_CREATION_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if getattr(sys, "frozen", False) else 0
ORIGINAL_GRDECL_FOLDER = "original_grdecl"
DEFAULT_PROJECT_NAME = "MVP_Gassum_mvp"
WORKFLOW_PROFILES = {
    "MVP": {
        "suffix": "mvp",
        "label": "MVP: integrated workflow",
        "description": "Current coupled sedimentary, T>Map diagenetic, and DFM workflow.",
    },
    "Siliciclastics": {
        "suffix": "siliciclastics",
        "label": "Siliciclastics",
        "description": "T>Map workflow with a future Fault Seal Analysis handoff.",
    },
    "Carbonates": {
        "suffix": "carbonates",
        "label": "Carbonates",
        "description": "GRDECL inspection, carbonate diagenesis handoff, and DFM workflow.",
    },
    "Crystalline rocks": {
        "suffix": "crystalline",
        "label": "Crystalline rocks",
        "description": "GRDECL inspection and DFM workflow without a diagenetic conversion stage.",
    },
}
REFERENCE_EXAMPLES_DIR = ROOT / "reference_examples"
TMAP_EXAMPLE_FILE = REFERENCE_EXAMPLES_DIR / "tmap_example" / "gassum_base_tmap.txt"
MICHAEL_DFN_EXAMPLE_DIR = REFERENCE_EXAMPLES_DIR / "michael_dfn_example"
# DFM Generator is a separately developed Apache-2.0 component. It is
# temporarily bundled for the demonstrator pending its upstream release at
# https://github.com/JointFlow/DFMGenerator; see THIRD_PARTY_NOTICES.md.
DEFAULT_DFN_EXECUTABLE = EXTERNAL_TOOLS / "DFMGenerator" / "DFMGenerator_GRDECL.exe"
DFN_DEMO_GRID = MICHAEL_DFN_EXAMPLE_DIR / "FaultedGridGeometryPropertyTest.GRDECL"
DFN_DEMO_CONFIG = MICHAEL_DFN_EXAMPLE_DIR / "FaultedGridGeometryPropertyTest.txt"
DFN_DEMO_OUTPUT_DIR = MICHAEL_DFN_EXAMPLE_DIR / "FaultedGridGeometryPropertyTest_output"


def approaches_for_project(
    project_output_dir: Path,
    workflow_profile: str = "MVP",
    source_grdecl_dir: Path | None = None,
) -> dict[str, dict[str, Path | list[list[str]]]]:
    """Return the workflow folders and commands for one isolated project."""
    if workflow_profile == "Carbonates":
        root = project_output_dir / "Carbonate workflow"
        return {
            "Moose/Golem diagenesis": {
                "point_dir": root / "01_Moose_Golem_inputs",
                "tmap_dir": root / "02_Moose_Golem_results",
                "augmented_dir": root / "03_GRDECLs_with_diagenesis_results",
                "dfn_dir": root / "04_DFM_prepared_grdecls",
                "dfn_run_dir": root / "05_DFM_generator_runs",
                "build_points": [],
                "generate_tmap": [],
                "append": [],
            }
        }
    if workflow_profile == "Crystalline rocks":
        root = project_output_dir / "Crystalline rock workflow"
        return {
            "Crystalline rock model": {
                "point_dir": source_grdecl_dir or root / ORIGINAL_GRDECL_FOLDER,
                "tmap_dir": source_grdecl_dir or root / ORIGINAL_GRDECL_FOLDER,
                "augmented_dir": source_grdecl_dir or root / ORIGINAL_GRDECL_FOLDER,
                "dfn_dir": root / "01_DFM_prepared_grdecls",
                "dfn_run_dir": root / "02_DFM_generator_runs",
                "build_points": [],
                "generate_tmap": [],
                "append": [],
            }
        }

    def approach(name: str, point_folder: str, tmap_folder: str, augmented_folder: str, dfn_folder: str, build: str, append: list[str], glob: str):
        root = project_output_dir / name
        return {
            "point_dir": root / point_folder,
            "tmap_dir": root / tmap_folder,
            "augmented_dir": root / augmented_folder,
            "dfn_dir": root / dfn_folder,
            "dfn_run_dir": root / "05_DFN_generator_runs",
            "build_points": [[build]],
            "generate_tmap": [["scripts/generate_synthetic_tmap_data.py", "--source-dir", str(root / point_folder), "--output-dir", str(root / tmap_folder), "--glob", glob, "--property-profile", "reservoir_quality"]],
            "append": [[command] for command in append],
        }

    result = {
        "Best-fit model": approach("Best-fit approach", "01_3d_points_from_original_grdecls", "02_3d_points_with_tmap_data", "03_augmented_grdecls_with_tmap_data", "04_DFN_prepared_grdecls_with_tmap_data", "scripts/build_best_fit_grdecl_to_pointset.py", ["scripts/append_best_fit_tmap_to_grdecls.py"], "*_3d_pointset"),
        "Multi-realization union": approach("Multi-realization union approach", "01_union_pointsets_by_facies", "02_union_pointsets_with_tmap_data", "03_augmented_grdecls_from_union_lookup", "04_DFN_prepared_grdecls_from_union_lookup", "scripts/build_multi_realizations_grdecls_to_union_pointsets.py", ["scripts/append_multi_realizations_union_tmap_to_grdecls.py"], "union_facies_*"),
        "Multi-realization control points": approach("Multi-realization control approach", "01_control_pointsets_by_facies", "02_control_pointsets_with_tmap_data", "03_augmented_grdecls_from_control_interpolation", "04_DFN_prepared_grdecls_from_control_interpolation", "scripts/build_multi_realizations_grdecls_to_control_pointsets.py", ["scripts/append_multi_realizations_control_tmap_to_grdecls.py"], "control_facies_*"),
        "Multi-realization Uber": approach("Multi-realization Uber approach", "01_uber_pointsets_by_facies", "02_uber_pointsets_with_tmap_data", "03_augmented_grdecls_from_uber_lookup", "05_DFN_prepared_grdecls_from_uber_lookup", "scripts/build_multi_realizations_grdecls_to_uber_pointsets.py", ["scripts/append_multi_realizations_uber_tmap_to_grdecls.py", "scripts/write_petrel_standard_uber_grdecls.py"], "uber_facies_*"),
    }
    uber_root = project_output_dir / "Multi-realization Uber approach"
    result["Multi-realization Uber"]["petrel_augmented_dir"] = uber_root / "04_petrel_standard_grdecls_from_uber_lookup"
    result["Multi-realization Uber"]["dfn_run_dir"] = uber_root / "06_DFN_generator_runs"
    return result


def inject_scripts_path() -> None:
    script_path = str(SCRIPTS)
    if script_path not in sys.path:
        sys.path.insert(0, script_path)


inject_scripts_path()
import append_best_fit_tmap_to_grdecls as _grdecl_implementation  # noqa: E402
import grdecl_utils as _grdecl_utils  # noqa: E402
# Streamlit reloads this dashboard file independently from helper modules.
# Reload the shared parser as well, so updated long-path handling applies to
# a running dashboard without requiring a manual Python-process restart.
importlib.reload(_grdecl_implementation)
importlib.reload(_grdecl_utils)
from grdecl_utils import grdecl_cell_centers, path_for_io, tokenize_grdecl  # noqa: E402

import json
import plotly.graph_objects as go

ROOT_DIR = Path(__file__).resolve().parent
FACIES_CONFIG_PATH = ROOT_DIR / "facies_config.json"

DEFAULT_FACIES_COLORS = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
]

DEFAULT_FACIES_NAMES = {
    1: "FA1a Offshore",
    2: "FA1b Offshore transition",
    3: "FA2a Lower shoreface",
    4: "FA2b Middle and upper shoreface",
    5: "FA3a Lagoon",
    6: "FA3b Tidal flats and channels",
    8: "FA4a Fluvial",
    9: "FA4b Fluvial, tidal influenced",
    10: "FA5 Floodplain lacustrine",
}


def is_depth_property(property_key: str) -> bool:
    """Treat depth-like scalar properties as shallow-yellow to deep-blue/purple."""
    key = re.sub(r"[^a-z0-9]+", "_", property_key.lower()).strip("_")
    return "depth" in key or key in {"burial", "burial_m"}


def continuous_color_scale(property_key: str):
    return "Viridis_r" if is_depth_property(property_key) else "Viridis"


def default_facies_color(position: int) -> str:
    """Get a default facies color based on position."""
    return DEFAULT_FACIES_COLORS[position % len(DEFAULT_FACIES_COLORS)]


def active_facies_config_path() -> Path:
    return Path(st.session_state.get("active_facies_config", FACIES_CONFIG_PATH))


def read_facies_config(path: Path | None = None) -> dict[int, str]:
    """Read facies color configuration from JSON file."""
    path = path or active_facies_config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        palette = data.get("facies_colors", {})
        return {int(k): str(v) for k, v in palette.items()}
    except Exception as exc:
        st.warning(f"Could not read facies config: {exc}")
        return {}


def read_facies_names(path: Path | None = None) -> dict[int, str]:
    """Read facies display names; an existing JSON file is authoritative."""
    path = path or active_facies_config_path()
    names = DEFAULT_FACIES_NAMES.copy() if not path.exists() else {}
    if not path.exists():
        return names
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names.update({int(k): str(v) for k, v in data.get("facies_names", {}).items()})
    except Exception:
        pass
    return names


def facies_label(category: int) -> str:
    """Return the active categorical code with its configured geological label."""
    name = read_facies_names().get(category)
    label = "Rock type" if globals().get("active_profile") == "Crystalline rocks" else "Facies"
    return f"{label} {category} — {name}" if name else f"{label} {category}"


def write_facies_config(
    palette: dict[int, str],
    path: Path | None = None,
    names: dict[int, str] | None = None,
    metadata: dict[int, dict] | None = None,
) -> None:
    """Write facies settings, retaining names and metadata from imported project JSON."""
    path = path or active_facies_config_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        payload["facies_colors"] = {str(k): v for k, v in sorted(palette.items())}
        if names is not None:
            payload["facies_names"] = {str(k): v for k, v in sorted(names.items())}
        else:
            payload.setdefault("facies_names", {str(k): v for k, v in DEFAULT_FACIES_NAMES.items()})
        if metadata is not None:
            payload["facies_metadata"] = {str(k): v for k, v in sorted(metadata.items())}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        st.success(f"Saved {path.name}")
    except Exception as exc:
        st.error(f"Could not save facies config: {exc}")


def is_discrete_facies_property(property_key: str, values: np.ndarray) -> bool:
    """Check whether a configured categorical classification uses discrete colours.

    The shared definitions JSON is also used for crystalline projects, where
    the integer classification is normally called ``RockType`` rather than
    ``Facies``.  Treating that field as continuous made the configured
    rock-type palette invisible in the viewer.
    """
    normalised = property_key.strip().upper().replace(" ", "").replace("_", "")
    if normalised in {
        "FACIES", "FACIE", "FACIESID", "LITHOFACIES",
        "ROCKTYPE", "ROCKTYPEID", "LITHOLOGY", "LITHO",
    }:
        finite = values[np.isfinite(values)]
        return finite.size > 0 and np.allclose(finite, np.round(finite))
    return False


def preferred_classification_property(properties: list[str], profile: str | None = None) -> str:
    """Choose the geology classification before generic fields such as ACTNUM."""
    profile = profile or globals().get("active_profile", "MVP")
    if profile == "Crystalline rocks":
        preferred = ("RockType", "ROCKTYPE", "ROCK_TYPE", "Lithology", "LITHOLOGY", "LITHO", "Facies", "FACIES")
    else:
        preferred = ("Facies", "FACIES", "Lithofacies", "LITHOFACIES", "Lithology", "LITHOLOGY", "RockType", "ROCKTYPE")
    return next((name for name in preferred if name in properties), properties[0])


def get_visible_facies(values: np.ndarray) -> list[int]:
    """Get list of visible facies values from data."""
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return []
    unique = np.unique(np.round(finite).astype(int))
    return sorted(unique.tolist())


def is_cell_data(df: pd.DataFrame) -> bool:
    """Check if dataframe contains cell polygon data (corner coordinates)."""
    return all(col in df.columns for col in ["X0", "X1", "X2", "X3"])


def cell_centres_as_points(df: pd.DataFrame) -> pd.DataFrame:
    """Provide standard X/Y/Z columns when a polygon grid is viewed as points."""
    if not is_cell_data(df):
        return df
    points = df.copy()
    points["X"] = points["X_center"]
    points["Y"] = points["Y_center"]
    points["Z"] = points["Z_center"]
    return points


def facies_color_settings(categories: list[int], key_prefix: str) -> dict[int, str]:
    """UI panel for facies color settings with color pickers."""
    saved_palette = read_facies_config()
    colors: dict[int, str] = {}
    
    # Display palette controls
    palette_columns = st.columns(3)
    with palette_columns[0]:
        if st.button("Reset to defaults", key=f"{key_prefix}_reset_palette"):
            default_palette = {
                cat: default_facies_color(idx)
                for idx, cat in enumerate(categories)
            }
            write_facies_config(default_palette)
            st.rerun()
    
    with palette_columns[1]:
        if st.button("Save current colors", key=f"{key_prefix}_save_palette"):
            write_facies_config(colors if colors else {
                cat: st.session_state.get(
                    f"{key_prefix}_facies_color_{cat}",
                    saved_palette.get(cat, default_facies_color(idx))
                )
                for idx, cat in enumerate(categories)
            })
    
    with palette_columns[2]:
        palette_json = json.dumps({
            "facies_colors": {
                str(cat): st.session_state.get(
                    f"{key_prefix}_facies_color_{cat}",
                    saved_palette.get(cat, default_facies_color(idx))
                )
                for idx, cat in enumerate(categories)
            },
            "facies_names": {str(cat): read_facies_names().get(cat, "") for cat in categories},
        }, indent=2) + "\n"
        st.download_button(
            "Download JSON",
            data=palette_json,
            file_name="facies_colors.json",
            mime="application/json",
            key=f"{key_prefix}_download_palette",
        )

    uploaded_palette = st.file_uploader(
        "Load facies color JSON",
        type="json",
        key=f"{key_prefix}_upload_palette",
        help="Load a project facies_config.json or a JSON downloaded from this panel. Names, colours, and metadata are imported.",
    )
    if uploaded_palette is not None and st.button("Apply loaded colors", key=f"{key_prefix}_apply_palette"):
        try:
            uploaded = json.loads(uploaded_palette.getvalue().decode("utf-8"))
            raw_palette = uploaded.get("facies_colors", uploaded)
            loaded_palette = {int(code): str(color) for code, color in raw_palette.items()}
            raw_names = uploaded.get("facies_names", {})
            loaded_names = {int(code): str(name) for code, name in raw_names.items()}
            raw_metadata = uploaded.get("facies_metadata", {})
            loaded_metadata = {int(code): value for code, value in raw_metadata.items() if isinstance(value, dict)}
            write_facies_config(
                {**saved_palette, **loaded_palette},
                names=loaded_names or None,
                metadata=loaded_metadata or None,
            )
            for category in categories:
                if category in loaded_palette:
                    st.session_state[f"{key_prefix}_facies_color_{category}"] = loaded_palette[category]
            st.rerun()
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            st.error(f"Could not load facies color JSON: {exc}")
    
    # Display color pickers
    st.write("**Facies Colors:**")
    columns = st.columns(min(4, len(categories)))
    for position, category in enumerate(categories):
        default = saved_palette.get(category, default_facies_color(position))
        with columns[position % len(columns)]:
            colors[category] = st.color_picker(
                facies_label(category),
                value=st.session_state.get(
                    f"{key_prefix}_facies_color_{category}", default
                ),
                key=f"{key_prefix}_facies_color_{category}",
            )
    return colors


@st.cache_data(show_spinner=False)
def grdecl_cell_polygons(path: Path, property_keyword: str | None = None, k_layer: int | None = None) -> pd.DataFrame:
    """Extract cell corners and properties for polygon visualization."""
    from grdecl_utils import (
        mapaxes_transform,
        tokenize_grdecl,
    )
    
    try:
        data = tokenize_grdecl(path, {"SPECGRID", "MAPAXES", "COORD", "ZCORN"})
    except ValueError:
        return pd.DataFrame()  # Return empty if GRDECL parsing fails
    
    nx, ny, nz = (int(float(v)) for v in data["SPECGRID"][:3])
    coord = [float(v) for v in data["COORD"]]
    zcorn = [float(v) for v in data["ZCORN"]]
    mapaxes = [float(v) for v in data["MAPAXES"]]
    transform = mapaxes_transform(mapaxes)
    
    def pillar_xy(i: int, j: int) -> tuple[float, float]:
        idx = (j * (nx + 1) + i) * 6
        return coord[idx], coord[idx + 1]
    
    def z_value(i: int, j: int, k: int, di: int, dj: int, dk: int) -> float:
        return zcorn[(2 * k + dk) * (2 * ny) * (2 * nx) + (2 * j + dj) * (2 * nx) + (2 * i + di)]
    
    # Extract cells with corner coordinates
    cells = []
    k_values = range(nz) if k_layer is None else range(max(0, k_layer - 1), min(nz, k_layer))
    for k in k_values:
        for j in range(ny):
            for i in range(nx):
                # Get the 4 pillar positions (local grid coordinates)
                pillars = [
                    pillar_xy(i, j),
                    pillar_xy(i + 1, j),
                    pillar_xy(i + 1, j + 1),
                    pillar_xy(i, j + 1),
                ]
                
                # Transform to world coordinates
                corners_xy = [transform(x, y) for x, y in pillars]
                
                # Get Z values at the 8 corners
                z_corners = [
                    -z_value(i, j, k, di, dj, dk)
                    for dk in (0, 1) for dj in (0, 1) for di in (0, 1)
                ]
                
                # Compute cell center
                cx = sum(x for x, _ in corners_xy) / 4.0
                cy = sum(y for _, y in corners_xy) / 4.0
                cz = sum(z_corners) / 8.0
                
                cell = {
                    "I": i + 1, "J": j + 1, "K": k + 1,
                    "CellIndex": k * (ny * nx) + j * nx + i,
                    "X_center": cx, "Y_center": cy, "Z_center": cz,
                    "X0": corners_xy[0][0], "Y0": corners_xy[0][1],
                    "X1": corners_xy[1][0], "Y1": corners_xy[1][1],
                    "X2": corners_xy[2][0], "Y2": corners_xy[2][1],
                    "X3": corners_xy[3][0], "Y3": corners_xy[3][1],
                    "Z_top_mean": (z_corners[0] + z_corners[1] + z_corners[2] + z_corners[3]) / 4.0,
                    "Z_bot_mean": (z_corners[4] + z_corners[5] + z_corners[6] + z_corners[7]) / 4.0,
                    # Match Z corners to the XY polygon order: 0=(i0,j0),
                    # 1=(i1,j0), 2=(i1,j1), 3=(i0,j1).
                    "Z0_top": z_corners[0], "Z1_top": z_corners[1],
                    "Z2_top": z_corners[3], "Z3_top": z_corners[2],
                    "Z0_bot": z_corners[4], "Z1_bot": z_corners[5],
                    "Z2_bot": z_corners[7], "Z3_bot": z_corners[6],
                }
                cells.append(cell)
    
    df = pd.DataFrame(cells)
    
    # Add the selected cell property.  Geometry is independent of the property,
    # so this works for porosity/permeability as well as facies.
    if property_keyword:
        try:
            tokens = tokenize_grdecl(path, {property_keyword})[property_keyword]
            values = expand_values(tokens)
            all_cells = nx * ny * nz
            if len(values) == all_cells:
                if k_layer is not None:
                    start = (k_layer - 1) * nx * ny
                    values = values[start : start + nx * ny]
                numeric = pd.to_numeric(pd.Series(values), errors="coerce")
                df[property_keyword] = numeric if numeric.notna().any() else values
        except Exception:
            pass
    
    return df


def plot_map_with_cells(
    df: pd.DataFrame,
    color_column: str,
    title: str,
    colors: dict[int, str] | None = None,
    max_cells: int = 5000,
    key: str | None = None,
) -> None:
    """Plot map view with cell rectangles instead of points."""
    if len(df) > max_cells:
        st.warning(f"Too many cells ({len(df):,}). Showing first {max_cells:,}.")
        df = df.head(max_cells)
    
    values = df[color_column].values if color_column in df.columns else np.array([])
    is_discrete = is_discrete_facies_property(color_column, values)
    
    fig = go.Figure()
    
    if is_discrete and colors:
        categories = get_visible_facies(values)
        for idx, category in enumerate(categories):
            mask = np.round(values).astype(int) == category
            subset = df[mask]
            
            for i, (_, row) in enumerate(subset.iterrows()):
                fig.add_trace(
                    go.Scatter(
                        x=[row["X0"], row["X1"], row["X2"], row["X3"], row["X0"]],
                        y=[row["Y0"], row["Y1"], row["Y2"], row["Y3"], row["Y0"]],
                        fill="toself",
                        name=facies_label(category),
                        marker={"color": colors.get(category, default_facies_color(category))},
                        line={"color": "white", "width": 0.5},
                        hovertemplate=f"<b>{facies_label(category)}</b><br>I,J,K: {int(row['I'])},{int(row['J'])},{int(row['K'])}<extra></extra>",
                        showlegend=(i == 0),  # Only show legend for first item in category
                    )
                )
    else:
        # Continuous color scale
        df = df.loc[valid_continuous_mask(df[color_column])].copy()
        if df.empty:
            st.warning("No valid values are available for this property.")
            return
        numeric_values = pd.to_numeric(df[color_column], errors="coerce")
        logarithmic = "perm" in color_column.lower()
        if logarithmic:
            numeric_values = np.log10(numeric_values.clip(lower=1e-12))
        fixed_poro_scale = "porosity" in color_column.lower() or color_column.lower().startswith("poro")
        low, high = porosity_display_limits(numeric_values) if fixed_poro_scale else (float(numeric_values.min()), float(numeric_values.max()))
        if not np.isfinite(low) or not np.isfinite(high) or np.isclose(low, high):
            low, high = 0.0, 1.0
        for _, row in df.iterrows():
            color_val = float(row[color_column]) if color_column in row else 0.0
            scale_val = float(np.log10(max(color_val, 1e-12))) if logarithmic else color_val
            fraction = float(np.clip((scale_val - low) / (high - low), 0.0, 1.0))
            fig.add_trace(
                go.Scatter(
                    x=[row["X0"], row["X1"], row["X2"], row["X3"], row["X0"]],
                    y=[row["Y0"], row["Y1"], row["Y2"], row["Y3"], row["Y0"]],
                    fill="toself",
                    fillcolor=px.colors.sample_colorscale(continuous_color_scale(color_column), fraction)[0],
                    line={"color": "white", "width": 0.5},
                    hovertemplate=f"<b>{color_column}: {color_val:.2f}</b><br>I,J,K: {int(row['I'])},{int(row['J'])},{int(row['K'])}<extra></extra>",
                    showlegend=False,
                )
            )
    
    fig.update_layout(
        height=560,
        margin=dict(l=10, r=10, t=45, b=10),
        title=title,
        hovermode="closest",
        showlegend=True,
    )
    fig.update_xaxes(scaleanchor="y", scaleratio=1)
    st.plotly_chart(fig, width="stretch", key=key)


def plot_grdecl_k_mesh(
    grdecl_path: str,
    property_keyword: str,
    k_layer: int,
    title: str,
    colors: dict[int, str] | None = None,
    continuous_limits: tuple[float, float] | None = None,
    key: str | None = None,
) -> None:
    """Render one real GRDECL K-layer as a single WebGL mesh.

    Only the top faces of the selected layer are constructed. This makes a
    GRDECL visibly distinct from a point set without generating a full-volume
    mesh or one Plotly trace per cell.
    """
    cells = grdecl_cell_polygons(Path(grdecl_path), property_keyword, k_layer)
    if cells.empty or property_keyword not in cells:
        st.warning("Could not build a GRDECL cell mesh for this layer and property.")
        return
    values = pd.to_numeric(cells[property_keyword], errors="coerce")
    is_discrete = is_discrete_facies_property(property_keyword, values.to_numpy())
    if not is_discrete:
        cells = cells.loc[valid_continuous_mask(values)].copy()
        values = pd.to_numeric(cells[property_keyword], errors="coerce")
        if cells.empty:
            st.warning("No valid values are available for this GRDECL cell layer.")
            return

    # Four unshared vertices per cell preserve a constant cell value, while
    # the whole layer is still drawn with one Mesh3d WebGL trace.
    x: list[float] = []
    y: list[float] = []
    z: list[float] = []
    tri_i: list[int] = []
    tri_j: list[int] = []
    tri_k: list[int] = []
    customdata: list[list[float | int]] = []
    face_colors: list[str] = []
    intensities: list[float] = []
    for cell_number, (_, row) in enumerate(cells.iterrows()):
        base = cell_number * 4
        x.extend([float(row["X0"]), float(row["X1"]), float(row["X2"]), float(row["X3"])])
        y.extend([float(row["Y0"]), float(row["Y1"]), float(row["Y2"]), float(row["Y3"])])
        z.extend([float(row["Z0_top"]), float(row["Z1_top"]), float(row["Z2_top"]), float(row["Z3_top"])])
        tri_i.extend([base, base])
        tri_j.extend([base + 1, base + 2])
        tri_k.extend([base + 2, base + 3])
        raw_value = float(row[property_keyword])
        customdata.extend([[int(row["I"]), int(row["J"]), int(row["K"]), raw_value]] * 4)
        if is_discrete:
            category = int(round(raw_value))
            colour = (colors or {}).get(category, default_facies_color(category))
            face_colors.extend([colour, colour])
        else:
            display_value = float(np.log10(max(raw_value, 1e-12))) if "perm" in property_keyword.lower() else raw_value
            intensities.extend([display_value] * 4)

    mesh_args: dict[str, object] = {
        "x": x, "y": y, "z": z,
        "i": tri_i, "j": tri_j, "k": tri_k,
        "customdata": customdata,
        "flatshading": True,
        "hovertemplate": (f"<b>{property_keyword}: %{{customdata[3]}}</b><br>"
                          "I,J,K: %{customdata[0]}, %{customdata[1]}, %{customdata[2]}<extra></extra>"),
        "name": f"GRDECL cells, K={k_layer}",
        "showscale": not is_discrete,
    }
    if is_discrete:
        mesh_args["facecolor"] = face_colors
    else:
        low_high = continuous_limits
        if low_high is None:
            finite = np.asarray(intensities, dtype=float)
            low_high = (float(finite.min()), float(finite.max()))
        if low_high[0] == low_high[1]:
            low_high = (low_high[0] - 0.5, low_high[1] + 0.5)
        mesh_args.update({
            "intensity": intensities,
            "intensitymode": "vertex",
            "colorscale": "Viridis",
            "cmin": low_high[0],
            "cmax": low_high[1],
            "colorbar": {"title": f"{property_keyword}{' (log10 mD)' if 'perm' in property_keyword.lower() else ''}"},
        })
    fig = go.Figure(go.Mesh3d(**mesh_args))
    fig.update_layout(
        height=560,
        margin=dict(l=10, r=10, t=45, b=10),
        title=title,
        dragmode="pan",
        scene={
            "aspectmode": "data",
            "camera": {"projection": {"type": "orthographic"}, "eye": {"x": 0, "y": 0, "z": 2.2}, "up": {"x": 0, "y": 1, "z": 0}},
            "xaxis": {"title": "X"}, "yaxis": {"title": "Y"}, "zaxis": {"visible": False},
        },
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch", key=key)
    st.caption(f"True GRDECL top faces for K={k_layer}: {len(cells):,} cells rendered as one WebGL mesh.")


def plot_section_with_cells(
    df: pd.DataFrame,
    color_column: str,
    axis_mode: str,
    selector: int | float,
    colors: dict[int, str] | None = None,
    max_cells: int = 5_000,
    key: str | None = None,
) -> None:
    """Render a cell-face cross-section using the GRDECL corner depths."""
    work = df.copy()
    if axis_mode == "Grid column (I)":
        work = work[work["I"] == selector]
        axis_label = "Cell position along J"
    elif axis_mode == "Grid row (J)":
        work = work[work["J"] == selector]
        axis_label = "Cell position along I"
    elif axis_mode == "X slice":
        x_min = work[["X0", "X1", "X2", "X3"]].min(axis=1)
        x_max = work[["X0", "X1", "X2", "X3"]].max(axis=1)
        work = work[(x_min <= selector) & (x_max >= selector)]
        axis_label = "Y"
    else:
        y_min = work[["Y0", "Y1", "Y2", "Y3"]].min(axis=1)
        y_max = work[["Y0", "Y1", "Y2", "Y3"]].max(axis=1)
        work = work[(y_min <= selector) & (y_max >= selector)]
        axis_label = "X"

    if work.empty:
        st.warning("No cells intersect this section.")
        return
    if len(work) > max_cells:
        st.warning(f"Section contains {len(work):,} cells. Showing the first {max_cells:,}.")
        work = work.head(max_cells)

    def vertices(row: pd.Series) -> tuple[list[float], list[float]]:
        if axis_mode == "Grid column (I)":
            # Follow the J direction through the selected I column.  The two
            # top and bottom edges retain their true corner-derived dips.
            x = [row["J"] - 0.5, row["J"] + 0.5, row["J"] + 0.5, row["J"] - 0.5]
            z = [
                (row["Z0_top"] + row["Z1_top"]) / 2,
                (row["Z3_top"] + row["Z2_top"]) / 2,
                (row["Z3_bot"] + row["Z2_bot"]) / 2,
                (row["Z0_bot"] + row["Z1_bot"]) / 2,
            ]
        elif axis_mode == "Grid row (J)":
            x = [row["I"] - 0.5, row["I"] + 0.5, row["I"] + 0.5, row["I"] - 0.5]
            z = [
                (row["Z0_top"] + row["Z3_top"]) / 2,
                (row["Z1_top"] + row["Z2_top"]) / 2,
                (row["Z1_bot"] + row["Z2_bot"]) / 2,
                (row["Z0_bot"] + row["Z3_bot"]) / 2,
            ]
        elif axis_mode == "X slice":
            x = [min(row["Y0"], row["Y1"], row["Y2"], row["Y3"]), max(row["Y0"], row["Y1"], row["Y2"], row["Y3"])]
            x = [x[0], x[1], x[1], x[0]]
            z = [row["Z_top_mean"], row["Z_top_mean"], row["Z_bot_mean"], row["Z_bot_mean"]]
        else:
            x = [min(row["X0"], row["X1"], row["X2"], row["X3"]), max(row["X0"], row["X1"], row["X2"], row["X3"])]
            x = [x[0], x[1], x[1], x[0]]
            z = [row["Z_top_mean"], row["Z_top_mean"], row["Z_bot_mean"], row["Z_bot_mean"]]
        return x, z

    values = pd.to_numeric(work[color_column], errors="coerce").to_numpy()
    is_discrete = is_discrete_facies_property(color_column, values)
    if not is_discrete and "perm" in color_column.lower():
        values = np.log10(np.clip(values, 1e-12, None))
    fig = go.Figure()

    def add_cells(subset: pd.DataFrame, name: str, fillcolor: str, showlegend: bool) -> None:
        xs: list[float | None] = []
        zs: list[float | None] = []
        custom: list[list[float | int | None] | None] = []
        for _, row in subset.iterrows():
            x, z = vertices(row)
            metadata = [row.get("I"), row.get("J"), row.get("K"), row.get(color_column)]
            xs.extend([*x, None])
            zs.extend([*z, None])
            custom.extend([metadata] * 4 + [None])
        fig.add_trace(go.Scatter(
            x=xs, y=zs, customdata=custom, mode="lines", fill="toself",
            fillcolor=fillcolor, line={"color": "white", "width": 0.5},
            name=name, showlegend=showlegend,
            hovertemplate=(f"<b>{color_column}: %{{customdata[3]}}</b><br>"
                           "I,J,K: %{customdata[0]}, %{customdata[1]}, %{customdata[2]}<extra></extra>"),
        ))

    if is_discrete and colors:
        for category in get_visible_facies(values):
            subset = work[np.round(values).astype(int) == category]
            add_cells(subset, f"Facies {category}", colors.get(category, default_facies_color(category)), True)
    else:
        work = work.loc[valid_continuous_mask(work[color_column])].copy()
        if work.empty:
            st.warning("No valid values are available for this property in this section.")
            return
        values = pd.to_numeric(work[color_column], errors="coerce").to_numpy()
        if "perm" in color_column.lower():
            values = np.log10(np.clip(values, 1e-12, None))
        finite = values[np.isfinite(values)]
        low, high = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
        if np.isclose(low, high):
            bins = np.zeros(len(work), dtype=int)
        else:
            bins = np.clip(((values - low) / (high - low) * 127).astype(int), 0, 127)
        for bucket in np.unique(bins):
            fraction = (int(bucket) + 0.5) / 128
            color = px.colors.sample_colorscale(continuous_color_scale(color_column), fraction)[0]
            add_cells(work[bins == bucket], color_column, color, False)

    fig.update_layout(
        height=620, margin=dict(l=10, r=10, t=45, b=10),
        title=f"{axis_mode}: {selector}", hovermode="closest", showlegend=is_discrete,
        xaxis_title=axis_label, yaxis_title="Z (depth)",
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, width="stretch", key=key)


st.set_page_config(page_title="GO-Forward GRDECL/T>Map", layout="wide")


def natural_filename_key(path: Path) -> tuple[tuple[int, int | str], ...]:
    """Sort embedded numeric tokens numerically rather than lexicographically."""
    return tuple(
        (0, int(token)) if token.isdigit() else (1, token.lower())
        for token in re.split(r"(\d+)", path.name)
    )


def files_in(folder: Path, patterns: tuple[str, ...]) -> list[Path]:
    if not folder.exists():
        return []
    files: list[Path] = []
    for pattern in patterns:
        files.extend(
            path
            for path in folder.glob(pattern)
            # Windows pathlib may report False for a long OneDrive path even
            # though the glob found a valid cloud-managed file.
            if not path.is_dir()
            and not path.name.endswith(".xml")
            and path.suffix.lower() not in {".md", ".png", ".jpg", ".jpeg"}
        )
    return sorted(set(files), key=natural_filename_key)


def is_tmap_pointset_file(path: Path) -> bool:
    """Return true only for ASCII pointsets with the expected header block.

    Returned-data folders can also contain reports such as JSON diagnostics.
    Those are useful alongside the data, but must not enter the point-set
    selector or parser.
    """
    try:
        found_begin = False
        with open(path_for_io(path), "r", encoding="utf-8", errors="ignore") as handle:
            for _ in range(300):
                line = handle.readline()
                if not line:
                    break
                marker = line.strip()
                if marker == "BEGIN HEADER":
                    found_begin = True
                elif found_begin and marker == "END HEADER":
                    return True
    except OSError:
        return False
    return False


def pointset_data_row_count(path: Path) -> int | None:
    """Count data rows in a Petrel/T>Map pointset without parsing all values."""
    try:
        columns_seen = False
        count = 0
        with open(path_for_io(path), "r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                if line == "END HEADER":
                    columns_seen = True
                    continue
                if not columns_seen or line.startswith("#") or line == "VERSION 1":
                    continue
                count += 1
        return count
    except OSError:
        return None


def tmap_pointset_columns(path: Path) -> tuple[str, ...]:
    """Read the visible column names from a Petrel/T>Map pointset header."""
    columns: list[str] = []
    try:
        in_header = False
        with open(path_for_io(path), "r", encoding="utf-8", errors="ignore") as handle:
            for raw in handle:
                line = raw.strip()
                if line == "BEGIN HEADER":
                    in_header = True
                    continue
                if line == "END HEADER":
                    break
                if in_header:
                    columns.append(line.split(",", 1)[-1].strip().strip('"'))
    except OSError:
        return ()
    return tuple(columns)


def tmap_pointset_has_column(path: Path, column_name: str) -> bool:
    return any(column.lower() == column_name.lower() for column in tmap_pointset_columns(path))


def appendable_tmap_columns(paths: list[Path]) -> list[str]:
    """Return non-identity T>Map columns available for GRDECL append."""
    columns: list[str] = []
    seen: set[str] = set()
    for path in paths:
        for column in tmap_pointset_columns(path):
            key = _grdecl_implementation.normalized_property_key(column)
            if column.lower() in _grdecl_implementation.IDENTITY_COLUMNS or key in seen:
                continue
            seen.add(key)
            columns.append(column)
    return columns


def append_include_args(columns: list[str]) -> list[str]:
    return ["--include-columns", *columns] if columns else []


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def dfn_property_directive(keyword: str, property_name: str | None, default_value: str) -> list[str]:
    """Use a GRDECL property when selected, otherwise retain Michael's default."""
    executable_aliases = {
        "YOUNGSMODULUS_PA": "YOUNGSMODPA",
        "FRACTUREENERGY_J_M2": "FRACTUREENERGY",
    }
    selected = executable_aliases.get(str(property_name).upper(), property_name)
    return [f"{keyword}Property {selected}"] if selected and selected != "Use default" else [f"Default{keyword} {default_value}"]


def property_option_index(options: list[str], preferred: str) -> int:
    """Find a GRDECL property option without assuming its keyword casing."""
    return next((index for index, option in enumerate(options) if option.upper() == preferred.upper()), 0)


def initialize_tab5_property_defaults(properties: list[str]) -> None:
    """Choose available DFN fields when the selected input GRDECL changes."""
    marker = "tab5_property_defaults_v3"
    signature = tuple(sorted(name.upper() for name in properties))
    if st.session_state.get(marker) == signature:
        return
    options = ["Use default", *properties]
    for state_key, preferred in (
        ("tab5_azimuth_property", "DIPAZIMUTH"),
        ("tab5_young_prop", "YoungsModulus_Pa"),
        ("tab5_poisson_prop", "PoissonsRatio"),
        ("tab5_porosity_prop", "DFNPorosity"),
        ("tab5_friction_prop", "FrictionCoefficient"),
        ("tab5_energy_prop", "FractureEnergy_J_m2"),
    ):
        # A selected field may belong to a previously viewed GRDECL. Reset it
        # if it no longer exists, then choose the preferred field where one is
        # available. Widgets read this session value directly, so they must not
        # also be given a competing ``index=`` default.
        if st.session_state.get(state_key, "Use default") not in options:
            st.session_state[state_key] = "Use default"
        if st.session_state.get(state_key, "Use default") == "Use default":
            index = property_option_index(options, preferred)
            if index:
                st.session_state[state_key] = options[index]
    st.session_state[marker] = signature


def read_dfn_configuration(path: Path) -> dict[str, str]:
    """Read active one-value entries from a standalone DFM configuration."""
    settings: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("%"):
            continue
        key, _, value = line.partition(" ")
        if value.strip():
            settings[key] = value.strip()
    return settings


def load_dfn_configuration_into_controls(path: Path, properties: list[str]) -> None:
    """Populate the Tab 5 controls from Michael's text configuration."""
    values = read_dfn_configuration(path)

    def number(name: str, state_key: str, scale: float = 1.0) -> None:
        if name in values:
            try:
                st.session_state[state_key] = float(values[name]) * scale
            except ValueError:
                pass

    def boolean(name: str, state_key: str) -> None:
        if name in values and values[name].lower() in {"true", "false"}:
            st.session_state[state_key] = values[name].lower() == "true"

    def choice(name: str, state_key: str, allowed: set[str] | None = None) -> None:
        if name in values and (allowed is None or values[name] in allowed):
            st.session_state[state_key] = values[name]

    for config_name, state_key, scale in (
        ("HorizontalUpscalingFactor", "tab5_hup", 1.0),
        ("VerticalUpscalingFactor", "tab5_vup", 1.0),
        ("DefaultEhminAzi", "tab5_azimuth", 180.0 / np.pi),
        ("DefaultEhminRate", "tab5_ehmin", 1.0),
        ("DefaultEhmaxRate", "tab5_ehmax", 1.0),
        ("DeformationEpisodeDuration", "tab5_duration", 1.0),
        ("DefaultAppliedOverpressureRate", "tab5_overpressure", 1.0 / 1e5),
        ("DefaultAppliedTemperatureChange", "tab5_temperature", 1.0),
        ("DefaultAppliedUpliftRate", "tab5_uplift", 1.0),
        ("StressArchingFactor", "tab5_arching", 1.0),
        ("DefaultYoungsMod", "tab5_young_default", 1.0 / 1e9),
        ("DefaultPoissonsRatio", "tab5_poisson_default", 1.0),
        ("DefaultPorosity", "tab5_porosity_default", 1.0),
        ("DefaultFrictionCoefficient", "tab5_friction_default", 1.0),
        ("DefaultCrackSurfaceEnergy", "tab5_energy_default", 1.0),
        ("DefaultBiotCoefficient", "tab5_biot", 1.0),
        ("DefaultThermalExpansionCoefficient", "tab5_thermal", 1.0),
        ("DefaultInitialMicrofractureDensity", "tab5_micro_density", 1.0),
        ("DefaultInitialMicrofractureSizeDistribution", "tab5_micro_size", 1.0),
        ("DefaultInitialMicrofractureMedianRadius", "tab5_micro_radius", 1.0),
        ("DefaultSubcriticalPropIndex", "tab5_subcritical", 1.0),
        ("CriticalPropagationRate", "tab5_critical_rate", 1.0),
        ("DefaultDepthAtDeformation", "tab5_depth_deformation", 1.0),
        ("MeanOverlyingSedimentDensity", "tab5_overburden", 1.0),
        ("FluidDensity", "tab5_fluid_density", 1.0),
        ("InitialOverpressure", "tab5_initial_overpressure", 1.0 / 1e5),
        ("GeothermalGradient", "tab5_gradient", 1000.0),
        ("InitialStressRelaxation", "tab5_initial_relaxation", 1.0),
        ("NoIntermediateOutputs", "tab5_intermediates", 1.0),
        ("Mode1HMin_UniformAperture", "tab5_aperture_value", 1.0),
        ("NoLayerBoundFractureSets", "tab5_fracture_sets", 1.0),
        ("MaxTimesteps", "tab5_max_timesteps", 1.0),
        ("MaxTimestepDuration", "tab5_max_timestep_duration", 1.0),
        ("MaxTimestepMFP33Increase", "tab5_mfp33", 1.0),
        ("No_r_bins", "tab5_radius_bins", 1.0),
        ("MinimumClearZoneVolume", "tab5_clear_zone", 1.0),
        ("MaxConsistencyAngle", "tab5_consistency", 180.0 / np.pi),
        ("MinimumLayerThickness", "tab5_layer_thickness", 1.0),
        ("MaxNoFracturePatches", "tab5_patches", 1.0),
        ("MinExplicitMicrofractureRadius", "tab5_explicit_radius", 1.0),
        ("Number_uF_Points", "tab5_micro_corners", 1.0),
        ("NoUnconfinedFractureStrikeSets", "tab5_ucf_strike", 1.0),
        ("NoUnconfinedFractureDipSets", "tab5_ucf_dip", 1.0),
    ):
        number(config_name, state_key, scale)
    # The paired example originates from the earlier standalone configuration
    # naming, while Michael's current template uses the first name below.
    if "NoLayerBoundFractureSets" not in values:
        number("NoFractureSets", "tab5_fracture_sets")
    for config_name, state_key in (
        ("AverageMechanicalPropertyData", "tab5_average_mech"),
        ("AverageStressStrainData", "tab5_average_stress"),
        ("GenerateExplicitDFN", "tab5_explicit"),
        ("WriteDFNFiles", "tab5_ascii"),
        ("WriteFABFiles", "tab5_fab"),
        ("WriteImplicitDataFiles", "tab5_implicit"),
        ("OutputFractureSets", "tab5_sets"),
        ("OutputFractureSetData", "tab5_sets"),
        ("OutputFracturePorosity", "tab5_porosity_out"),
        ("OutputFracturePermeabilityTensor", "tab5_perm_out"),
        ("PopulateEmptyGridblocks", "tab5_empty"),
        ("CropAtBoundary", "tab5_crop_boundary"),
        ("LinkStressShadows", "tab5_relays"),
        ("Mode1Only", "tab5_mode1"),
        ("Mode2Only", "tab5_mode2"),
        ("FilterByProperty", "tab5_filter"),
    ):
        boolean(config_name, state_key)
    choice("ModelTimeUnits", "tab5_time_units", {"ma", "year", "second"})
    choice("InitialMicrofractureDistributionFunction", "tab5_micro_distribution", {"PowerLaw", "Exponential", "LogNormal"})
    choice("StressDistributionScenario", "tab5_stress_distribution", {"StressShadow", "EvenlyDistributedStress"})
    choice("IntermediateOutputIntervalControl", "tab5_interval", {"EqualTime", "EqualArea", "SpecifiedTime"})
    choice("FractureApertureControl", "tab5_aperture", {"Uniform", "SizeDependent", "Dynamic", "BartonBandis"})
    choice("SearchAdjacentGridblocks", "tab5_search", {"Automatic", "All", "None"})
    available = {name.upper(): name for name in properties}
    for config_name, state_key in (
        ("EhminAziProperty", "tab5_azimuth_property"),
        ("YoungsModProperty", "tab5_young_prop"),
        ("PoissonsRatioProperty", "tab5_poisson_prop"),
        ("PorosityProperty", "tab5_porosity_prop"),
        ("FrictionCoefficientProperty", "tab5_friction_prop"),
        ("CrackSurfaceEnergyProperty", "tab5_energy_prop"),
    ):
        selected = available.get(values.get(config_name, "").upper())
        # Retain the local GRDECL mapping when Michael's reference config
        # contains a placeholder or a property absent from this model.
        if selected:
            st.session_state[state_key] = selected


def dfn_config_text(model_name: str, grid_name: str, settings: dict[str, object]) -> str:
    """Create the active subset of Michael's GRDECL executable configuration."""
    def truth(key: str) -> str:
        return "true" if settings.get(key) else "false"

    lines = [
        "% Generated by the GO-Forward dashboard from the DFM Generator settings.",
        f"ModelName {model_name}",
        f"GridFileName {grid_name}",
        "StartColumnI -1", "EndColumnI -1", "StartRowJ -1", "EndRowJ -1", "TopLayerK -1", "BottomLayerK -1",
        f"HorizontalUpscalingFactor {settings['horizontal_upscale']}",
        f"VerticalUpscalingFactor {settings['vertical_upscale']}",
        f"ModelTimeUnits {settings['time_units']}",
        f"DefaultEhminRate {settings['ehmin_rate']}",
        f"DefaultEhmaxRate {settings['ehmax_rate']}",
        f"DefaultAppliedOverpressureRate {float(settings['overpressure_bar_ma']) * 1e5:.8g}",
        f"DefaultAppliedTemperatureChange {settings['temperature_change_k_ma']}",
        f"DefaultAppliedUpliftRate {settings['uplift_rate_m_ma']}",
        f"StressArchingFactor {settings['stress_arching_factor']}",
        f"DeformationEpisodeDuration {settings['episode_duration']}",
    ]
    # The dashboard stores DIPAZIMUTH in degrees clockwise from North for
    # inspection. The temporary DFN handoff converts that property to radians;
    # scalar configuration values are likewise written in radians.
    lines.append(f"DefaultEhminAzi {np.deg2rad(float(settings['ehmin_azimuth_deg'])):.8g}")
    if settings.get("ehmin_azimuth_property") and settings.get("ehmin_azimuth_property") != "Use default":
        lines.append(f"EhminAziProperty {settings['ehmin_azimuth_property']}")
    lines += dfn_property_directive("YoungsMod", settings.get("youngs_property"), f"{float(settings['youngs_default_gpa']) * 1e9:.8g}")
    lines += dfn_property_directive("PoissonsRatio", settings.get("poisson_property"), str(settings["poisson_default"]))
    lines += dfn_property_directive("Porosity", settings.get("porosity_property"), str(settings["porosity_default"]))
    lines += dfn_property_directive("FrictionCoefficient", settings.get("friction_property"), str(settings["friction_default"]))
    lines += dfn_property_directive("CrackSurfaceEnergy", settings.get("fracture_energy_property"), str(settings["fracture_energy_default"]))
    lines += [
        f"DefaultBiotCoefficient {settings['biot_default']}",
        f"DefaultThermalExpansionCoefficient {settings['thermal_expansion_default']}",
        f"DefaultRockStrainRelaxation {settings['rock_relaxation']}",
        f"DefaultFractureRelaxation {settings['fracture_relaxation']}",
        f"InitialMicrofractureDistributionFunction {settings['microfracture_distribution']}",
        f"DefaultInitialMicrofractureDensity {settings['microfracture_density']}",
        f"DefaultInitialMicrofractureSizeDistribution {settings['microfracture_size_distribution']}",
        f"DefaultInitialMicrofractureMedianRadius {settings['microfracture_median_radius']}",
        f"DefaultSubcriticalPropIndex {settings['subcritical_index']}",
        f"CriticalPropagationRate {settings['critical_rate']}",
        f"AverageMechanicalPropertyData {truth('average_mechanical')}",
        f"StressDistributionScenario {settings['stress_distribution']}",
        f"DefaultDepthAtDeformation {settings['depth_at_deformation']}",
        f"MeanOverlyingSedimentDensity {settings['overburden_density']}",
        f"FluidDensity {settings['fluid_density']}",
        f"InitialOverpressure {float(settings['initial_overpressure_bar']) * 1e5:.8g}",
        f"GeothermalGradient {float(settings['geothermal_gradient_c_km']) / 1000:.8g}",
        f"InitialStressRelaxation {settings['initial_stress_relaxation']}",
        f"AverageStressStrainData {truth('average_stress')}",
        f"WriteImplicitDataFiles {truth('write_implicit_files')}",
        f"WriteDFNFiles {truth('write_dfn_ascii')}",
        "OutputDFNFileType ASCII",
        "WriteGRDECLFiles true",
        "IncludeGridGeometryInGRDECLFiles false",
        f"WriteFABFiles {truth('write_fab')}",
        f"NoIntermediateOutputs {settings['intermediate_outputs']}",
        f"IntermediateOutputIntervalControl {settings['intermediate_control']}",
        f"OutputFractureSets {truth('output_fracture_sets')}",
        f"OutputFracturePorosity {truth('output_fracture_porosity')}",
        f"OutputFracturePermeabilityTensor {truth('output_fracture_permeability')}",
        f"PopulateEmptyGridblocks {truth('populate_empty')}",
        f"FractureApertureControl {settings['aperture_control']}",
        f"Mode1HMin_UniformAperture {settings['uniform_aperture_m']}",
        f"Mode2HMin_UniformAperture {settings['uniform_aperture_m']}",
        f"Mode1HMax_UniformAperture {settings['uniform_aperture_m']}",
        f"Mode2HMax_UniformAperture {settings['uniform_aperture_m']}",
        f"NoLayerBoundFractureSets {settings['fracture_sets']}",
        f"Mode1Only {truth('mode1_only')}",
        f"Mode2Only {truth('mode2_only')}",
        f"MaxTimestepDuration {settings['max_timestep_duration']}",
        f"MaxTimestepMFP33Increase {settings['max_mfp33_increase']}",
        f"No_r_bins {settings['radius_bins']}",
        f"MinimumClearZoneVolume {settings['minimum_clear_zone']}",
        f"MaxTimesteps {settings['max_timesteps']}",
        f"GenerateExplicitDFN {truth('generate_explicit')}",
        f"CropAtBoundary {truth('crop_boundary')}",
        f"LinkStressShadows {truth('link_stress_shadows')}",
        f"MaxConsistencyAngle {np.deg2rad(float(settings['max_consistency_angle_deg'])):.8g}",
        f"MinimumLayerThickness {settings['minimum_layer_thickness']}",
        f"MaxNoFracturePatches {settings['max_fracture_patches']}",
        f"SearchAdjacentGridblocks {settings['search_adjacent']}",
        f"MinExplicitMicrofractureRadius {settings['minimum_explicit_microfracture_radius']}",
        f"Number_uF_Points {settings['microfracture_cornerpoints']}",
        f"NoUnconfinedFractureStrikeSets {settings['unconfined_strike_sets']}",
        f"NoUnconfinedFractureDipSets {settings['unconfined_dip_sets']}",
        f"FilterByProperty {truth('filter_by_property')}",
        # Active reference controls from Michael's supplied configuration
        # that do not yet have their own dashboard widgets.
        "ProbabilisticFractureNucleationLimit -1",
        "FractureNucleationPosition -1",
        "PropagateFracturesInNucleationOrder true",
        "CheckAlluFStressShadows Automatic",
        "Active_TotalMFP30TerminationRatio -1",
        "Current_HistoricMFP33TerminationRatio -1",
        "MinImplicitMicrofractureRadius -1",
        "No_l_indexPoints 20",
        "OutputPopulationDistribution true",
        "AllowReverseFractures false",
        "MaxHMinLength 0",
        "MaxHMaxLength 0",
    ]
    if settings.get("filter_by_property") and settings.get("filter_property"):
        lines += [
            f"PropertyToFilter {settings['filter_property']}",
            f"FilterByPropertyMinCutoff {settings['filter_min']}",
            f"FilterByPropertyMaxCutoff {settings['filter_max']}",
        ]
    return "\n".join(lines) + "\n"


def dfn_run_status(run_dir: Path) -> dict[str, object]:
    path = run_dir / "run_status.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def stop_dfn_run(run_dir: Path) -> tuple[bool, str]:
    """Stop a dashboard-launched DFN runner and its executable child process."""
    status_path = run_dir / "run_status.json"
    status = dfn_run_status(run_dir)
    launcher_pid = status.get("launcher_pid")
    if not isinstance(launcher_pid, int) or launcher_pid <= 0:
        return False, "This run has no active dashboard launcher process to stop."
    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(launcher_pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, f"Could not request process termination: {exc}"
    status.update(
        {
            "status": "stopped",
            "stage": "Stopped by user from the dashboard",
            "stop_requested_utc": datetime.now(timezone.utc).isoformat(),
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "taskkill_returncode": result.returncode,
        }
    )
    status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    if result.returncode == 0:
        return True, "The DFN launcher and its executable child process were stopped."
    detail = (result.stderr or result.stdout or "The process was already gone.").strip()
    return False, detail


def delete_dfn_run(run_dir: Path) -> tuple[bool, str]:
    """Remove one completed, failed, or user-stopped dashboard run folder."""
    if not run_dir.exists():
        return False, "The selected run folder no longer exists."
    state = str(dfn_run_status(run_dir).get("status", "unknown")).lower()
    if state in {"queued", "preparing", "running"}:
        return False, "Stop the active DFN run before deleting its folder."
    try:
        shutil.rmtree(run_dir)
    except OSError as exc:
        return False, f"Could not delete the run folder: {exc}"
    return True, f"Removed {run_dir.name} and its input, log, configuration, and output files."


def dfn_elapsed_seconds(status: dict[str, object]) -> int | None:
    """Format elapsed wall-clock time from the runner's UTC status fields."""
    started = status.get("started_utc")
    if not isinstance(started, str):
        return None
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        finished = status.get("completed_utc")
        end = datetime.fromisoformat(finished.replace("Z", "+00:00")) if isinstance(finished, str) else datetime.now(timezone.utc)
    except ValueError:
        return None
    return max(0, int((end - start).total_seconds()))


def dfn_duration_text(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:d}:{seconds:02d}"


def dfn_elapsed_text(status: dict[str, object]) -> str | None:
    seconds = dfn_elapsed_seconds(status)
    return dfn_duration_text(seconds) if seconds is not None else None


def dfn_run_label(run_dir: Path) -> str:
    """Human-readable source and run-size label for the run selectors."""
    manifest_path = run_dir / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        manifest = {}
    source = Path(str(manifest.get("source_grdecl", "unknown model"))).stem
    cells = manifest.get("run_cells")
    scope = "cropped" if manifest.get("cropped") else "full model"
    cell_label = f"{int(cells):,} cells" if isinstance(cells, (int, float)) else "cell count unknown"
    return f"{source} · {scope}, {cell_label} · {run_dir.name}"


def dfn_run_name(source_grdecl: Path, cropped: bool, cells: int, sequence: int) -> str:
    """Keep run folders below Windows path limits; full source names stay in the manifest."""
    cell_tag = f"{cells // 1000}k" if cells >= 1000 and cells % 1000 == 0 else str(cells)
    sampling = f"c{cell_tag}" if cropped else f"f{cell_tag}"
    # The executable repeats this ID in its output directory and FAB names.
    # Keep it at ~21 characters so the longest FAB path stays below 260.
    # Source-model identity remains in the manifest and selector label.
    return f"r_{time.strftime('%y%m%d_%H%M%S')}_{sampling}_{sequence}"


def latest_dfn_runtime(run_root: Path, source_grdecl: Path) -> tuple[int, int] | None:
    """Return elapsed seconds and grid cells from the latest comparable completed run."""
    if not run_root.exists():
        return None
    candidates: list[tuple[str, int, int]] = []
    source_text = str(source_grdecl)
    for run_dir in run_root.iterdir():
        if not run_dir.is_dir():
            continue
        status = dfn_run_status(run_dir)
        if status.get("status") != "completed":
            continue
        manifest_path = run_dir / "run_manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        cells = manifest.get("run_cells")
        seconds = dfn_elapsed_seconds(status)
        if manifest.get("source_grdecl") == source_text and isinstance(cells, (int, float)) and cells > 0 and seconds is not None:
            candidates.append((str(status.get("completed_utc", "")), int(seconds), int(cells)))
    if not candidates:
        return None
    _, seconds, cells = max(candidates, key=lambda item: item[0])
    return seconds, cells


@st.fragment
def dfn_crop_controls(dims: tuple[int, int, int], source_path_text: str, run_root_text: str) -> tuple[bool, tuple[int, int], tuple[int, int], tuple[int, int], int]:
    """Keep crop-range changes local to the cell-count preview."""
    crop_run = st.checkbox("Create a cropped test-grid copy for this run", value=True, key="tab5_crop")
    if crop_run:
        st.caption("The crop is a Petrel-style standalone DFN hand-off: geometry, active/layer fields and required DFN properties are reduced together. Use this for configuration and runtime checks before full-scale execution.")
        crop_columns = st.columns(3)
        crop_i = crop_columns[0].slider("I range", 1, dims[0], (1, min(dims[0], 5)), key="tab5_crop_i")
        crop_j = crop_columns[1].slider("J range", 1, dims[1], (1, min(dims[1], 5)), key="tab5_crop_j")
        crop_k = crop_columns[2].slider("K range", 1, dims[2], (1, min(dims[2], 4)), key="tab5_crop_k")
        cells = (crop_i[1] - crop_i[0] + 1) * (crop_j[1] - crop_j[0] + 1) * (crop_k[1] - crop_k[0] + 1)
        cell_metric, estimate_metric = st.columns(2)
        cell_metric.metric("Cropped test cells", f"{cells:,}")
        reference = latest_dfn_runtime(Path(run_root_text), Path(source_path_text))
        if reference:
            previous_seconds, previous_cells = reference
            estimate_metric.metric("Estimated run time", f"~{dfn_duration_text(int(previous_seconds * cells / previous_cells))}")
            st.caption(f"Estimate scaled from the most recent completed {previous_cells:,}-cell run of this GRDECL. Actual DFN runtime can vary with fracture growth.")
        else:
            estimate_metric.metric("Estimated run time", "Run a crop first")
        return True, crop_i, crop_j, crop_k, cells
    crop_i, crop_j, crop_k = (1, dims[0]), (1, dims[1]), (1, dims[2])
    cells = int(np.prod(dims))
    st.caption("The full model is written as a Petrel-style standalone DFN hand-off before launch. This adds the spatial-reference fields required by the executable without changing cell geometry or DFN values.")
    st.metric("Full-model cells", f"{cells:,}")
    return False, crop_i, crop_j, crop_k, cells


@st.fragment(run_every=5)
def dfn_live_status_panel(run_dir_text: str) -> None:
    """Refresh the small run-status area without rerunning the heavy viewers."""
    run_dir = Path(run_dir_text)
    status = dfn_run_status(run_dir)
    state = str(status.get("status", "unknown")).lower()
    elapsed = dfn_elapsed_text(status)
    stage = str(status.get("stage", "Waiting for the launcher…"))
    if state in {"queued", "preparing", "running"}:
        st.info(f"**DFN Generator is running** · elapsed {elapsed or 'starting…'}\n\nCurrent step: {stage}\n\nThis panel refreshes every 5 seconds; you can keep working elsewhere in the dashboard.")
        if st.button("Stop this DFN run", key=f"stop_dfn_{run_dir.name}", type="secondary"):
            stopped, message = stop_dfn_run(run_dir)
            if stopped:
                st.success(message)
            else:
                st.warning(f"Stop request could not be confirmed: {message}")
            st.rerun(scope="fragment")
    elif state == "completed":
        st.success(f"**DFN run completed** · total time {elapsed or 'unknown'}")
    elif state == "failed":
        st.error(f"**DFN run failed** · stopped after {elapsed or 'unknown'}\n\nLast step: {stage}")
    elif state == "stopped":
        st.warning(f"**DFN run stopped by user** · elapsed {elapsed or 'unknown'}\n\nLast step: {stage}")
    else:
        st.warning("No live status has been written yet. The launch may still be starting.")
    manifest_path = run_dir / "run_manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        manifest = {}
    run_cells = manifest.get("run_cells")
    source_cells = manifest.get("source_cells")
    if isinstance(run_cells, (int, float)):
        source_text = f" of {int(source_cells):,} source-model cells" if isinstance(source_cells, (int, float)) else ""
        st.caption(f"Run grid: {int(run_cells):,} cells{source_text}.")
    elapsed_seconds = dfn_elapsed_seconds(status)
    if manifest.get("cropped") and state in {"completed", "failed"} and elapsed_seconds is not None and isinstance(run_cells, (int, float)) and isinstance(source_cells, (int, float)) and run_cells > 0:
        estimate = int(elapsed_seconds * float(source_cells) / float(run_cells))
        st.caption(f"First-order full-model estimate: ~{dfn_duration_text(estimate)} from this {int(run_cells):,}-cell crop ({float(run_cells) / float(source_cells):.1%} of the model). DFN runtime is not perfectly linear, so use this as an order-of-magnitude guide only.")
    with st.expander("Run details", expanded=state in {"failed", "unknown"}):
        st.json(status or {"status": "unknown"}, expanded=False)
    log_path = run_dir / "dfn_generator.log"
    if log_path.exists():
        st.caption("Live executable log (latest 30 lines)")
        st.code("\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]), language="text")


@st.cache_data(show_spinner=False)
def dfn_result_dataframe(input_path_text: str, result_path_text: str, max_rows: int) -> pd.DataFrame:
    """Attach property-only DFM output to the geometry of its run input GRDECL."""
    input_path, result_path = Path(input_path_text), Path(result_path_text)
    nx, ny, nz = grdecl_dimensions(input_path_text)
    centres = grdecl_cell_centers(input_path)
    df = pd.DataFrame(centres, columns=["X", "Y", "Z"])
    cell_index = np.arange(len(df))
    df["CellIndex"] = cell_index
    df["I"] = cell_index % nx + 1
    df["J"] = (cell_index // nx) % ny + 1
    df["K"] = cell_index // (nx * ny) + 1
    result_properties: dict[str, pd.Series | list[str]] = {}
    for keyword in keyword_candidates(result_path):
        try:
            values = expand_values(tokenize_grdecl(result_path, {keyword})[keyword])
        except Exception:
            continue
        if len(values) != len(df):
            continue
        numeric = pd.to_numeric(pd.Series(values), errors="coerce")
        result_properties[keyword] = numeric if numeric.notna().any() else values
    if result_properties:
        df = pd.concat([df, pd.DataFrame(result_properties, index=df.index)], axis=1)
    if len(df) > max_rows:
        return df.sample(max_rows, random_state=7).sort_values(["K", "J", "I"])
    return df


@st.cache_data(show_spinner=False)
def read_fab_fractures(path_text: str, max_fractures: int) -> tuple[dict[str, float | int], list[dict[str, object]]]:
    """Read the ASCII FAB geometry written by DFM Generator.

    A FAB record is one planar fracture (or one layer-bound fracture segment):
    identifier, number of nodes, set number, permeability, compressibility and
    aperture; followed by its XYZ nodes and a normal-vector line.  The parser
    intentionally ignores the latter, since Plotly only needs the polygon.
    """
    path = Path(path_text)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header: dict[str, float | int] = {"fracture_count": 0, "node_count": 0}
    begin = None
    for index, raw in enumerate(lines):
        line = raw.strip()
        if line.startswith("No_Fractures"):
            try:
                header["fracture_count"] = int(float(line.split("=", 1)[1]))
            except (IndexError, ValueError):
                pass
        elif line.startswith("No_Nodes ="):
            try:
                header["node_count"] = int(float(line.split("=", 1)[1]))
            except (IndexError, ValueError):
                pass
        elif line == "BEGIN FRACTURE":
            begin = index + 1
            break
    if begin is None or not header["fracture_count"]:
        return header, []

    fractures: list[dict[str, object]] = []
    index = begin
    while index < len(lines) and len(fractures) < max_fractures:
        line = lines[index].strip()
        if not line or line.startswith("END FRACTURE"):
            break
        fields = line.split()
        try:
            fracture_id, node_count = int(fields[0]), int(fields[1])
            permeability, compressibility, aperture = map(float, fields[3:6])
        except (IndexError, ValueError):
            index += 1
            continue
        index += 1
        nodes: list[tuple[float, float, float]] = []
        for _ in range(node_count):
            if index >= len(lines):
                break
            coords = lines[index].split()
            try:
                nodes.append((float(coords[1]), float(coords[2]), float(coords[3])))
            except (IndexError, ValueError):
                pass
            index += 1
        # The normal-vector record has node number 0 and is not geometry.
        index += 1
        if len(nodes) >= 2:
            fractures.append(
                {
                    "id": fracture_id,
                    "nodes": nodes,
                    "permeability": permeability,
                    "compressibility": compressibility,
                    "aperture": aperture,
                }
            )
    return header, fractures


def fab_fracture_viewer(fab_files: list[Path], key_prefix: str) -> None:
    """Show explicit DFM fracture polygons, where a run produced FAB output."""
    st.subheader("Explicit fracture geometry (FAB)")
    if not fab_files:
        st.info("No FAB files were written for this run. Explicit geometry appears here only when the DFN settings produce fractures.")
        return
    fab_file = st.selectbox("FAB fracture file", fab_files, format_func=lambda path: path.name, key=f"{key_prefix}_fab_file")
    max_fractures = st.select_slider(
        "Maximum fractures to draw",
        options=[100, 500, 1_000, 5_000, 10_000],
        value=1_000,
        key=f"{key_prefix}_fab_limit",
        help="A limit keeps large explicit DFNs responsive. The file header always reports the full fracture count.",
    )
    header, fractures = read_fab_fractures(str(fab_file), max_fractures)
    total = int(header.get("fracture_count", 0))
    if not fractures:
        st.info(f"`{fab_file.name}` contains no explicit fractures (No_Fractures = {total:,}).")
        return
    st.caption(f"Showing {len(fractures):,} of {total:,} explicit fracture polygons from `{fab_file.name}`.")
    figure = go.Figure()
    for fracture in fractures:
        nodes = fracture["nodes"]
        assert isinstance(nodes, list)
        closed = nodes + [nodes[0]]
        hover = (
            f"Fracture segment {fracture['id']}<br>"
            f"Permeability: {float(fracture['permeability']):.3g} m²<br>"
            f"Aperture: {float(fracture['aperture']):.3g} m<br>"
            f"Compressibility: {float(fracture['compressibility']):.3g}<extra></extra>"
        )
        figure.add_trace(
            go.Scatter3d(
                x=[point[0] for point in closed],
                y=[point[1] for point in closed],
                z=[point[2] for point in closed],
                mode="lines",
                line={"color": "#d62728", "width": 4},
                hovertemplate=hover,
                showlegend=False,
            )
        )
    figure.update_layout(
        height=680,
        margin={"l": 0, "r": 0, "t": 32, "b": 0},
        title="Explicit DFN fracture polygons",
        scene={
            "xaxis_title": "X (m)",
            "yaxis_title": "Y (m)",
            "zaxis_title": "Z (m)",
            "aspectmode": "data",
            "camera": {"projection": {"type": "orthographic"}},
        },
    )
    st.plotly_chart(figure, width="stretch", key=f"{key_prefix}_fab_chart")


def valid_project_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name))


def project_config_path(name: str) -> Path:
    return DATA_ROOT / name / "project_config.json"


def workflow_profile_from_project_name(name: str) -> str | None:
    """Infer a workflow from the controlled suffix used for project folders."""
    lowered = name.lower()
    for profile, details in WORKFLOW_PROFILES.items():
        if lowered.endswith("_" + str(details["suffix"]).lower()):
            return profile
    return None


def project_workflow_profile(name: str) -> str:
    """Return the folder-defined workflow, keeping legacy projects as MVP."""
    suffix_profile = workflow_profile_from_project_name(name)
    if suffix_profile is not None:
        return suffix_profile
    try:
        payload = json.loads(project_config_path(name).read_text(encoding="utf-8"))
        profile = payload.get("workflow_profile", "MVP")
        return profile if profile in WORKFLOW_PROFILES else "MVP"
    except (OSError, json.JSONDecodeError):
        return "MVP"


def write_project_workflow_profile(name: str, profile: str) -> None:
    if profile not in WORKFLOW_PROFILES:
        return
    path = project_config_path(name)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        payload = {}
    payload.update({
        "project_name": name,
        "workflow_profile": profile,
        "workflow_suffix": WORKFLOW_PROFILES[profile]["suffix"],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def project_name_for_profile(name: str, profile: str) -> str:
    """Append a controlled rock-workflow suffix to a newly created project."""
    clean = name.strip().rstrip("_-")
    suffix = "_" + str(WORKFLOW_PROFILES[profile]["suffix"])
    if clean.lower().endswith(suffix.lower()):
        return clean
    return clean + suffix


def set_profile_for_selected_project() -> None:
    """Retained as a harmless selector callback for existing sessions."""
    return None


def project_names() -> list[str]:
    """Return projects registered by their single project-data folder."""
    if not DATA_ROOT.exists():
        return []
    return sorted(
        (path.name for path in DATA_ROOT.iterdir() if path.is_dir()),
        key=str.lower,
    )


def create_project(name: str, profile: str) -> None:
    base_name = name.strip()
    if profile not in WORKFLOW_PROFILES or not valid_project_name(base_name):
        st.session_state["project_create_error"] = "Use letters, numbers, hyphens, and underscores only; begin with a letter or number."
        return
    clean = project_name_for_profile(base_name, profile)
    (DATA_ROOT / clean / ORIGINAL_GRDECL_FOLDER).mkdir(parents=True, exist_ok=True)
    write_project_workflow_profile(clean, profile)
    st.session_state["project_selector"] = clean
    st.session_state["project_workflow_selector"] = profile
    st.session_state["project_created"] = clean


def remove_folder_with_retries(target: Path, attempts: int = 4) -> str | None:
    """Remove a local/OneDrive folder, retrying transient Windows file locks."""
    last_error: OSError | None = None

    def clear_readonly_and_retry(function, path, exception_info) -> None:
        error = exception_info[1]
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            function(path)
        except OSError:
            raise error

    for attempt in range(attempts):
        try:
            shutil.rmtree(target, onerror=clear_readonly_and_retry)
            return None
        except OSError as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(0.4)
    return str(last_error) if last_error else "Unknown removal error"


def remove_project(name: str, remove_input: bool) -> None:
    """Delete generated data only, or an entire project-data folder."""
    clean = name.strip()
    if not valid_project_name(clean):
        st.session_state["project_remove_result"] = ("error", "Unsafe project name was rejected.")
        return
    project_dir = DATA_ROOT / clean
    if remove_input:
        targets = [project_dir]
    else:
        targets = [path for path in project_dir.iterdir() if path.is_dir() and path.name != ORIGINAL_GRDECL_FOLDER] if project_dir.exists() else []
    removed = []
    failures = []
    for target in targets:
        # The name validation plus this containment check prevents deletion
        # outside the single project-data root.
        resolved_target = target.resolve()
        resolved_project = project_dir.resolve()
        if resolved_target != resolved_project and not str(resolved_target).lower().startswith(str(resolved_project).lower() + "\\"):
            st.session_state["project_remove_result"] = ("error", "Unsafe project path was rejected.")
            return
        if target.exists():
            error = remove_folder_with_retries(target)
            if error:
                failures.append(f"{display_path(target)} ({error})")
            else:
                removed.append(display_path(target))
    remaining = project_names()
    next_project = clean if clean in remaining else (DEFAULT_PROJECT_NAME if DEFAULT_PROJECT_NAME in remaining else (remaining[0] if remaining else DEFAULT_PROJECT_NAME))
    # The selector itself has already been created when this dialog opens.
    # Apply the replacement key before the next rerun instead.
    st.session_state["pending_project_selector"] = next_project
    if failures:
        level = "warning" if removed else "error"
        message = (
            (f"Removed: {', '.join(removed)}. " if removed else "")
            + "Could not remove the following locked folder(s): "
            + "; ".join(failures)
            + ". Close any Explorer windows using the folder and wait for OneDrive to finish syncing, then try again."
        )
    else:
        level = "success"
        message = f"Removed " + ("all project data" if remove_input else "generated workflow data") + f" for project {clean}: " + (", ".join(removed) if removed else "no matching project folders existed.")
    st.session_state["project_remove_result"] = (level, message)


def clear_missing_workspace_file_state() -> None:
    """Remove stale file-selector values after external folder renames."""
    legacy_roots = tuple(root.resolve() for root in (ROOT / "input", ROOT / "outputs") if root.exists())
    workspace_roots = (DATA_ROOT.resolve(), *legacy_roots)
    for key, value in list(st.session_state.items()):
        if not isinstance(value, (str, Path)):
            continue
        try:
            candidate = Path(value).expanduser()
            resolved = candidate.resolve()
        except (OSError, TypeError, ValueError):
            continue
        if not candidate.is_absolute() or candidate.exists():
            continue
        if any(str(resolved).lower().startswith(str(root).lower() + "\\") for root in workspace_roots):
            del st.session_state[key]


@st.dialog("Remove selected project")
def remove_project_dialog(project_name: str) -> None:
    st.write(f"Project: `{project_name}`")
    scope = st.radio(
        "What should be deleted?",
        ["Generated workflow data", "Entire project data"],
        help="Generated workflow data keeps original_grdecl and its facies configuration. Entire project data permanently removes the complete project folder.",
    )
    if scope == "Generated workflow data":
        st.info("Deletes generated workflow folders but retains original_grdecl and its facies definitions.")
    else:
        st.warning("Permanently deletes the complete project data folder, including original_grdecl and facies definitions.")
    cancel, remove = st.columns(2)
    if cancel.button("Cancel"):
        st.rerun()
    if remove.button("Delete selected scope", type="primary"):
        remove_project(project_name, remove_input=scope == "Entire project data")
        st.rerun()


def copy_source_grdecls_into_project(
    source_text: str,
    destination_text: str,
    replace_existing: bool,
    result_key: str = "source_copy_result",
    selector_key: str = "source_grdecl_folder_choice",
    selector_value: str | None = None,
) -> None:
    """Copy an external GRDECL source set into a project's starting-data folder."""
    source_dir = Path(source_text).expanduser()
    destination_dir = Path(destination_text)
    try:
        source_files = [path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl"]
    except OSError as exc:
        st.session_state[result_key] = ("error", f"Could not read {source_dir}: {exc}")
        return
    if not source_files:
        st.session_state[result_key] = ("error", f"No .grdecl files were found in {source_dir}.")
        return
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for source in source_files:
        destination = destination_dir / source.name
        if destination.exists() and not replace_existing:
            skipped += 1
            continue
        shutil.copy2(source, destination)
        copied += 1
    source_config = source_dir / "facies_config.json"
    destination_config = destination_dir / "facies_config.json"
    config_copied = False
    if source_config.exists() and (replace_existing or not destination_config.exists()):
        shutil.copy2(source_config, destination_config)
        try:
            payload = json.loads(destination_config.read_text(encoding="utf-8"))
            payload["source_grdecl_directory"] = str(destination_dir)
            payload["source_grdecl_files"] = sorted(path.name for path in destination_dir.glob("*.grdecl"))
            destination_config.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except (OSError, json.JSONDecodeError):
            pass
        config_copied = True
    st.session_state[result_key] = (
        "success",
        f"Copied {copied} GRDECL file(s) into {destination_dir}" +
        (f"; skipped {skipped} existing file(s)" if skipped else "") +
        ("; copied facies_config.json" if config_copied else ""),
    )
    # Callbacks run before widgets are created on the next rerun, so this can
    # safely return the source selector to the project's own input folder.
    st.session_state[selector_key] = selector_value or display_path(destination_dir)


def choose_source_folder_with_windows_explorer(
    selection_key: str = "source_grdecl_folder_custom",
    error_key: str = "source_browse_error",
    title: str = "Select folder containing source GRDECL files",
) -> None:
    """Open a native Windows folder chooser for this local dashboard session."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        window = tk.Tk()
        window.withdraw()
        window.attributes("-topmost", True)
        folder = filedialog.askdirectory(title=title)
        window.destroy()
        if folder:
            st.session_state[selection_key] = folder
    except Exception as exc:
        st.session_state[error_key] = f"Could not open the Windows folder chooser: {exc}"


def choose_source_grdecl_files_with_windows_explorer(
    selection_key: str,
    error_key: str,
    title: str = "Select source GRDECL file(s)",
) -> None:
    """Open a native unrestricted multi-file chooser for source GRDECLs."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        window = tk.Tk()
        window.withdraw()
        window.attributes("-topmost", True)
        paths = filedialog.askopenfilenames(title=title, filetypes=[("All files", "*.*")])
        window.destroy()
        if paths:
            st.session_state[selection_key] = list(paths)
    except Exception as exc:
        st.session_state[error_key] = f"Could not open the file chooser: {exc}"


def copy_selected_source_grdecls_into_project(
    selected_paths: list[str],
    destination_text: str,
    replace_existing: bool,
    result_key: str,
) -> None:
    """Copy explicitly selected source GRDECLs and an optional facies JSON."""
    selected = [Path(path).expanduser() for path in selected_paths]
    grdecl_files = [path for path in selected if path.is_file() and path.suffix.lower() == ".grdecl"]
    config_files = [path for path in selected if path.is_file() and path.name.lower() == "facies_config.json"]
    ignored = [path.name for path in selected if path.is_file() and path not in grdecl_files and path not in config_files]
    if not grdecl_files:
        st.session_state[result_key] = ("error", "Select at least one `.grdecl` file. The file picker shows all formats so its folder contents remain visible.")
        return
    destination_dir = Path(destination_text)
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for source in grdecl_files:
        destination = destination_dir / source.name
        if destination.exists() and not replace_existing:
            skipped += 1
            continue
        shutil.copy2(source, destination)
        copied += 1
    config_copied = False
    if config_files:
        config_source = config_files[-1]
        destination_config = destination_dir / "facies_config.json"
        if replace_existing or not destination_config.exists():
            shutil.copy2(config_source, destination_config)
            config_copied = True
    message = f"Copied {copied} GRDECL file(s) into {destination_dir}"
    if skipped:
        message += f"; skipped {skipped} existing file(s)"
    if config_copied:
        message += "; copied facies_config.json"
    if ignored:
        message += "; ignored non-GRDECL file(s): " + ", ".join(ignored)
    st.session_state[result_key] = ("success", message)


def source_grdecl_file_import_controls(
    key_prefix: str,
    destination_dir: Path | None = None,
    select_label: str = "Select source GRDECL file(s)",
    copy_label: str | None = None,
) -> None:
    """Render the shared explicit multi-file GRDECL import control."""
    destination_dir = destination_dir or ACTIVE_SOURCE_GRDECL_DIR
    result_key = f"{key_prefix}_copy_result"
    selection_key = f"{key_prefix}_selected_paths"
    error_key = f"{key_prefix}_browse_error"
    if result := st.session_state.pop(result_key, None):
        level, message = result
        (st.success if level == "success" else st.error)(message)
    st.button(
        select_label,
        key=f"{key_prefix}_browse",
        on_click=choose_source_grdecl_files_with_windows_explorer,
        args=(selection_key, error_key),
    )
    if error := st.session_state.pop(error_key, None):
        st.error(error)
    selected_paths = st.session_state.get(selection_key, [])
    if not selected_paths:
        return
    selected = [Path(path) for path in selected_paths]
    st.caption("Selected files: " + ", ".join(path.name for path in selected))
    replace_existing = st.checkbox("Replace same-named project files", value=False, key=f"{key_prefix}_replace")
    st.button(
        copy_label or f"Copy selected files into {display_path(destination_dir)}",
        key=f"{key_prefix}_copy",
        on_click=copy_selected_source_grdecls_into_project,
        args=(selected_paths, str(destination_dir), replace_existing, result_key),
    )


def copy_selected_files_into_directory(
    selected_paths: list[str],
    destination_text: str,
    replace_existing: bool,
    result_key: str,
) -> None:
    """Copy explicitly selected external result files without imposing a format."""
    selected = [Path(path).expanduser() for path in selected_paths]
    files = [path for path in selected if path.is_file()]
    if not files:
        st.session_state[result_key] = ("error", "No readable files were selected.")
        return
    destination_dir = Path(destination_text)
    destination_dir.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for source in files:
        destination = destination_dir / source.name
        if destination.exists() and not replace_existing:
            skipped += 1
            continue
        shutil.copy2(source, destination)
        copied += 1
    message = f"Copied {copied} file(s) into {destination_dir}"
    if skipped:
        message += f"; skipped {skipped} existing file(s)"
    st.session_state[result_key] = ("success", message)


def external_file_import_controls(key_prefix: str, destination_dir: Path, select_label: str, copy_label: str) -> None:
    """Render an unrestricted multi-file importer for external modelling results."""
    result_key = f"{key_prefix}_copy_result"
    selection_key = f"{key_prefix}_selected_paths"
    error_key = f"{key_prefix}_browse_error"
    if result := st.session_state.pop(result_key, None):
        level, message = result
        (st.success if level == "success" else st.error)(message)
    st.button(
        select_label,
        key=f"{key_prefix}_browse",
        on_click=choose_source_grdecl_files_with_windows_explorer,
        args=(selection_key, error_key, select_label),
    )
    if error := st.session_state.pop(error_key, None):
        st.error(error)
    selected_paths = st.session_state.get(selection_key, [])
    if not selected_paths:
        return
    st.caption("Selected files: " + ", ".join(Path(path).name for path in selected_paths))
    replace_existing = st.checkbox("Replace same-named project files", value=False, key=f"{key_prefix}_replace")
    st.button(
        copy_label,
        key=f"{key_prefix}_copy",
        on_click=copy_selected_files_into_directory,
        args=(selected_paths, str(destination_dir), replace_existing, result_key),
    )


def choose_tmap_return_files_with_windows_explorer() -> None:
    """Open a native multi-file chooser for returned T>Map pointsets."""
    try:
        import tkinter as tk
        from tkinter import filedialog

        window = tk.Tk()
        window.withdraw()
        window.attributes("-topmost", True)
        paths = filedialog.askopenfilenames(title="Select returned T>Map pointset file(s)", filetypes=[("All files", "*.*")])
        window.destroy()
        if paths:
            st.session_state["tab2_import_tmap_selected_paths"] = list(paths)
    except Exception as exc:
        st.session_state["tab2_import_tmap_error"] = f"Could not open the file chooser: {exc}"


def tmap_return_import_rows(selected_files: list[Path], source_pointsets: list[Path]) -> tuple[list[dict[str, str]], list[Path]]:
    """Report chosen return files and retain only unambiguous source matches."""
    candidates = [path for path in selected_files if path.is_file()]
    compatible = [path for path in candidates if is_tmap_pointset_file(path)]
    matched = {path: source_pointset_for_returned(path, source_pointsets) for path in compatible}
    source_counts: dict[Path, int] = {}
    for source in matched.values():
        if source is not None:
            source_counts[source] = source_counts.get(source, 0) + 1
    rows: list[dict[str, str]] = []
    importable: list[Path] = []
    for candidate in candidates:
        if candidate not in matched:
            rows.append({
                "Returned T>Map file": candidate.name,
                "Matched source 3D pointset": "—",
                "Status": "Not a recognised T>Map pointset file",
            })
            continue
        source = matched[candidate]
        if source is None:
            status = "Unmatched"
            source_name = "—"
        elif source_counts[source] > 1:
            status = "Ambiguous: multiple returns for this source"
            source_name = source.name
        else:
            status = "Ready to copy"
            source_name = source.name
            importable.append(candidate)
        rows.append({"Returned T>Map file": candidate.name, "Matched source 3D pointset": source_name, "Status": status})
    return rows, importable


def source_folder_selector() -> Path:
    """Choose a known workspace input folder or enter another local folder."""
    known = [ACTIVE_SOURCE_GRDECL_DIR]
    labels = [display_path(path) for path in known] + ["Enter another folder path"]
    choice = st.selectbox("Source GRDECL folder", labels, key="source_grdecl_folder_choice")
    if choice == "Enter another folder path":
        folder_text = st.text_input("Local source folder path", value=str(ACTIVE_SOURCE_GRDECL_DIR), key="source_grdecl_folder_custom")
        st.button("Browse source folder in Windows Explorer", key="source_grdecl_folder_browse", on_click=choose_source_folder_with_windows_explorer)
        if error := st.session_state.pop("source_browse_error", None):
            st.error(error)
        return Path(folder_text).expanduser()
    return known[labels.index(choice)]


def enrich_ijk_from_cell_index(df: pd.DataFrame, source_dir: Path) -> pd.DataFrame:
    """Recover I/J/K from CellIndex for returned T>Map point sets."""
    if "K" in df.columns or "CellIndex" not in df.columns:
        return df
    sources = files_in(source_dir, ("*.grdecl", "*.GRDECL"))
    if not sources:
        return df
    nx, ny, _ = grdecl_dimensions(str(sources[0]))
    index = pd.to_numeric(df["CellIndex"], errors="coerce")
    if index.isna().any():
        return df
    result = df.copy()
    result["I"] = index.astype(int) % nx + 1
    result["J"] = (index.astype(int) // nx) % ny + 1
    result["K"] = index.astype(int) // (nx * ny) + 1
    return result


def normalized_pointset_name(value: str) -> str:
    """Normalise a pointset reference without losing the ``.5`` model token."""
    name = Path(value.strip().strip('"\'')).name.lower()
    if name.endswith(".txt"):
        name = name[:-4]
    elif name.endswith(".grdecl"):
        name = name[:-7]
    # Support the accidental legacy Petrel export suffix and the supplied
    # Geocosm handoff while making new pointset names the canonical form.
    name = name.replace("_reservoirgrid", "")
    name = name.replace("ss_201_cleaned.5", "ss_201.5")
    name = name.replace("ss_201_cleaned_5", "ss_201_5")
    for suffix in ("_tmap_synthetic", "_tmap_real", "_tmap_inferred_geocosm"):
        if suffix in name:
            name = name.split(suffix, 1)[0]
    return name


def tmap_header_source_pointset_names(path_text: str) -> tuple[str, ...]:
    """Extract source pointset filenames recorded in T>Map comment headers.

    This deliberately remains uncached: users may correct a returned-file
    provenance header in place, and matching must reflect that edit on the
    next Streamlit rerun without requiring a server restart.
    """
    names: list[str] = []
    try:
        with open(path_for_io(Path(path_text)), "r", encoding="utf-8", errors="ignore") as handle:
            for _ in range(120):
                line = handle.readline()
                if not line or line.strip().upper() == "VERSION 1":
                    break
                if not line.lstrip().startswith("#"):
                    continue
                # T>Map's run comments separate the TCF, pointset and mode
                # with commas. The pointset segment may be a bare dataset name
                # such as `gassum_base_3d`, not necessarily a `.txt` file.
                for segment in line[1:].split(","):
                    candidate = segment.strip().strip('"\'')
                    if candidate.lower().endswith(".txt"):
                        names.append(Path(candidate).name)
                    elif candidate and ".tcf" not in candidate.lower() and "simulate " not in candidate.lower():
                        names.append(Path(candidate).name)
    except OSError:
        return ()
    return tuple(dict.fromkeys(names))


def source_pointset_for_returned(returned: Path, source_pointsets: list[Path]) -> Path | None:
    """Match a returned T>Map file by provenance, filename, or unique row count."""
    by_identity: dict[str, list[Path]] = {}
    for pointset in source_pointsets:
        by_identity.setdefault(normalized_pointset_name(pointset.name), []).append(pointset)
    for reference in tmap_header_source_pointset_names(str(returned)):
        matches = by_identity.get(normalized_pointset_name(reference), [])
        if len(matches) == 1:
            return matches[0]
        # Legacy handoffs called the exported pointset ``*_ReservoirGrid``;
        # current names end in ``_3d_pointset``. Only use this bridge when the
        # active dataset selection leaves one unambiguous candidate.
        legacy_matches = [
            pointset for pointset in source_pointsets
            if normalized_pointset_name(pointset.name).startswith(normalized_pointset_name(reference) + "_3d_pointset")
        ]
        if len(legacy_matches) == 1:
            return legacy_matches[0]
    fallback = [pointset for pointset in source_pointsets if returned.name.startswith(pointset.name)]
    if fallback:
        return max(fallback, key=lambda path: len(path.name))
    returned_rows = pointset_data_row_count(returned)
    if returned_rows is not None:
        row_matches = [pointset for pointset in source_pointsets if pointset_data_row_count(pointset) == returned_rows]
        if len(row_matches) == 1:
            return row_matches[0]
    if len(source_pointsets) == 1 and is_tmap_pointset_file(returned):
        return source_pointsets[0]
    return None


def standardize_returned_tmap_names(returned_files: list[Path], source_pointsets: list[Path]) -> list[tuple[str, str]]:
    """Keep real T>Map return filenames intact.

    Earlier MVP builds renamed matched real exports to an internal suffix. The
    dashboard can now match arbitrary real filenames directly, which is clearer
    when Geocosm returns named files such as `gassum_base_tmap.txt`.
    """
    return []


def source_grdecl_for_pointset(pointset: Path, source_dir: Path, source_pointsets: list[Path] | None = None) -> Path | None:
    """Find a Best-fit source GRDECL using T>Map header provenance where available."""
    resolved_pointset = source_pointset_for_returned(pointset, source_pointsets or [])
    pointset_name = normalized_pointset_name((resolved_pointset or pointset).name)
    matches = [
        path for path in files_in(source_dir, ("*.grdecl", "*.GRDECL"))
        if pointset_name.startswith(normalized_pointset_name(path.name))
    ]
    return max(matches, key=lambda path: len(path.stem)) if matches else None


def pointset_batch_and_scenario(path: Path) -> tuple[str, str]:
    """Group Best-fit pointsets into source-model batches and realization scenarios."""
    stem = path.name.split("_3d_pointset", 1)[0]
    match = re.match(r"^(.*?-FSM-FDM)-\d+-(.+)$", stem, flags=re.IGNORECASE)
    if match:
        return match.group(1), match.group(2)
    return stem, "single model"


def pointset_sampling_description(path: Path) -> str:
    match = re.search(r"_control_([0-9.]+)m(?:_tmap_synthetic)?$", path.name, flags=re.IGNORECASE)
    return f"reduced {match.group(1)} m vertical spacing" if match else "full cell-centre resolution"


def related_continuous_limits(df: pd.DataFrame, column: str) -> tuple[float, float] | None:
    """Shared limits for a property family, e.g. porosity P10/P50/P90."""
    base = re.sub(r"_(mean|stdev|p10|p25|p50|p75|p90|geomean)$", "", column.lower())
    related = [name for name in df.columns if re.sub(r"_(mean|stdev|p10|p25|p50|p75|p90|geomean)$", "", name.lower()) == base]
    values = pd.concat([pd.to_numeric(df[name], errors="coerce") for name in related], ignore_index=True).dropna()
    # Eclipse/Petrel no-value placeholders are data flags, not extrema.
    values = values[~values.isin([-999.0, -77777.0])]
    if values.empty:
        return None
    if "porosity" in base or base.startswith("poro"):
        return porosity_display_limits(values)
    if "perm" in base:
        logged = np.log10(values.clip(lower=1e-12))
        return float(logged.min()), float(logged.max())
    return float(values.min()), float(values.max())


def valid_continuous_mask(values: pd.Series) -> pd.Series:
    """Exclude GRDECL/T>Map no-value placeholders from continuous displays."""
    numeric = pd.to_numeric(values, errors="coerce")
    return numeric.notna() & np.isfinite(numeric) & ~numeric.isin([-999.0, -77777.0])


def porosity_display_limits(values) -> tuple[float, float]:
    """Use a fixed, unit-aware porosity scale for comparable views.

    Dashboard/DFN porosity is a fraction (typically 0–0.4); Geocosm T>Map
    exports label porosity as vol % (typically 0–40).  The values themselves
    are retained exactly as supplied; only the display range is selected.
    """
    numeric = pd.to_numeric(pd.Series(values), errors="coerce")
    numeric = numeric[np.isfinite(numeric) & ~numeric.isin([-999.0, -77777.0])]
    return (0.0, 40.0) if not numeric.empty and float(numeric.max()) > 1.0 else (0.0, 0.4)


@st.fragment
def shale_fallback_controls(
    saved_defaults: dict, default_values: dict, crystalline: bool = False, carbonate: bool = False
) -> tuple[bool, dict[str, float]]:
    """Render fallback inputs independently from the expensive Tab 4 viewer."""
    shale_fallback = st.checkbox(
        "Use depth-compaction fallback where porosity is absent" if crystalline else "Use provisional carbonate porosity-depth fallback where diagenesis data is absent" if carbonate else "Use shale-like depth-compaction fallback where T>Map data is absent",
        key="tab4_shale_fallback",
        help=(
            "Applies to every cell without a valid value in the selected porosity property. "
            "Cells with input porosity retain it; fallback cells use their selected rock-type mechanical formula and are marked GeomechSource = 2."
            if crystalline else
            "Applies only where the selected GOLEM/PHREEQC porosity property has no valid value. It is a provisional carbonate trend, not a replacement for mineral-reaction modelling; fallback cells retain their selected carbonate-facies mechanical formula and are marked GeomechSource = 2."
            if carbonate else
            "Applies to every cell with no returned T>Map porosity. Returned T>Map values remain unchanged; fallback cells retain their selected facies mechanical formula and are marked GeomechSource = 2."
        ),
    )
    if not shale_fallback:
        return False, {}
    fallback_context = (
        "Use this only as a provisional altered/fractured-rock trend and calibrate it to local data."
        if crystalline else
        "This is a provisional bulk carbonate trend only; calibrate it to lithology, diagenetic history, and any available core or log data."
        if carbonate else
        "Starting values follow a normal-compaction-style shale trend and must be calibrated to local data."
    )
    st.caption("Reference curve: φ = φ₀ exp(−c d), where d is depth below the configured Z datum. " + fallback_context)
    fallback_columns = st.columns(3)
    values = {
        "fallback_porosity_surface": fallback_columns[0].number_input(
            "Reference φ₀" if crystalline else "Carbonate φ₀" if carbonate else "Shale φ₀", min_value=0.01, max_value=0.90,
            value=float(saved_defaults.get("fallback_porosity_surface", default_values["fallback_porosity_surface"])), step=0.01,
            key="tab4_fallback_phi0",
        ),
        "fallback_compaction_coefficient_per_m": fallback_columns[1].number_input(
            "Reference c (1/m)" if crystalline else "Carbonate c (1/m)" if carbonate else "Shale c (1/m)", min_value=0.00001, max_value=0.005,
            value=float(saved_defaults.get("fallback_compaction_coefficient_per_m", default_values["fallback_compaction_coefficient_per_m"])), format="%.6f", step=0.00001,
            key="tab4_fallback_compaction",
        ),
        "fallback_effective_stress_gradient_mpa_per_m": fallback_columns[2].number_input(
            "Effective stress gradient (MPa/m)", min_value=0.0001, max_value=0.0500,
            value=float(saved_defaults.get("fallback_effective_stress_gradient_mpa_per_m", default_values["fallback_effective_stress_gradient_mpa_per_m"])), format="%.4f", step=0.0005,
            key="tab4_fallback_stress_gradient",
        ),
    }
    source_label = "input-property cells (`1`)" if crystalline else "GOLEM/PHREEQC-derived cells (`1`)" if carbonate else "T>Map-derived cells (`1`)"
    st.caption("The output writes `DFNPorosity` and `DFNEffectiveStress_MPa` for every valid DFM cell. `GEOMECHSOURCE` identifies " + source_label + " and depth-fallback cells (`2`).")
    return True, {name: float(value) for name, value in values.items()}


@st.fragment
def geomechanics_actions(config_path_text: str, config_text: str, target_paths: list[str], output_dir_text: str, write_label: str) -> None:
    """Keep Tab 4 save/write actions independent from its model viewer."""
    def current_config_text() -> str:
        payload = json.loads(config_text)
        defaults = payload.setdefault("defaults", {})
        for config_key, state_key in (
            ("fallback_porosity_surface", "tab4_fallback_phi0"),
            ("fallback_compaction_coefficient_per_m", "tab4_fallback_compaction"),
            ("fallback_effective_stress_gradient_mpa_per_m", "tab4_fallback_stress_gradient"),
        ):
            if state_key in st.session_state:
                defaults[config_key] = float(st.session_state[state_key])
        return json.dumps(payload, indent=2) + "\n"

    save_column, write_column = st.columns(2)
    with save_column:
        if st.button("Save geomechanics configuration", key="tab4_save"):
            Path(config_path_text).parent.mkdir(parents=True, exist_ok=True)
            Path(config_path_text).write_text(current_config_text(), encoding="utf-8")
            st.success(f"Saved {display_path(Path(config_path_text))}")
    with write_column:
        if st.button(write_label, key="tab4_write", disabled=not target_paths):
            # Persist the current table first, then use that exact same
            # configuration for the selected GRDECL writer commands.
            Path(config_path_text).parent.mkdir(parents=True, exist_ok=True)
            Path(config_path_text).write_text(current_config_text(), encoding="utf-8")
            facies_property = str(st.session_state.get("tab4_facies", "Facies"))
            porosity_property = str(st.session_state.get("tab4_poro", "POROMEAN"))
            cement_property = str(st.session_state.get("tab4_cement", "None"))
            stress_property = str(st.session_state.get("tab4_stress", "None"))
            commands: list[list[str]] = []
            for target in target_paths:
                command = ["scripts/assign_geomechanical_properties.py", "--input-grdecl", target, "--output-dir", output_dir_text, "--facies-property", facies_property, "--porosity-property", porosity_property, "--config", config_path_text]
                if cement_property != "None":
                    command.extend(["--cement-property", cement_property])
                if stress_property != "None":
                    command.extend(["--stress-property", stress_property])
                if st.session_state.get("tab4_shale_fallback", False):
                    command.append("--shale-fallback")
                if st.session_state.get("tab4_write_dipazimuth", True):
                    command.extend(["--write-dipazimuth", "--dipazimuth-smoothing-cells", str(st.session_state.get("tab4_dipazimuth_smoothing_cells", 3))])
                commands.append(command)
            if run_commands(commands):
                augmented_grdecl_dataframe.clear()
                written_files = [
                    Path(output_dir_text) / f"{Path(target).stem}_with_geomechanical_properties.grdecl"
                    for target in target_paths
                ]
                available = [path for path in written_files if path.exists()]
                if available:
                    # On the automatic rerun the output folder is re-listed,
                    # then the viewer opens the first newly written model.
                    # The remaining multi-realization files stay available in
                    # its selector.
                    st.session_state["tab4_viewer_choice"] = "DFN-preparation GRDECL"
                    st.session_state["tab4_dfn_file"] = available[0]
                    st.success(f"DFN-preparation GRDECL written. Opening `{available[0].name}` in the viewer…")
                    st.rerun()
                st.success("DFN-preparation GRDECL written, but no expected output file was found to open automatically.")


def grid_layer_selector(axis: str, key: str, minimum: int, maximum: int) -> int:
    """Grid-layer slider with previous/next controls for I, J, or K."""
    if minimum == maximum:
        return minimum
    state_key = f"{key}_value"
    if state_key not in st.session_state:
        st.session_state[state_key] = minimum

    def shift(delta: int) -> None:
        st.session_state[state_key] = max(minimum, min(maximum, st.session_state[state_key] + delta))

    previous, slider, next_button = st.columns([0.16, 0.68, 0.16])
    previous.button(f"Previous {axis}", key=f"{key}_previous", on_click=shift, args=(-1,), disabled=st.session_state[state_key] <= minimum)
    with slider:
        st.slider(f"{axis} layer", minimum, maximum, key=state_key)
    next_button.button(f"Next {axis}", key=f"{key}_next", on_click=shift, args=(1,), disabled=st.session_state[state_key] >= maximum)
    return int(st.session_state[state_key])


def k_layer_selector(key: str, minimum: int, maximum: int) -> int:
    """Compatibility wrapper for map-view K navigation."""
    return grid_layer_selector("K", key, minimum, maximum)


def plot_3d_points(
    df: pd.DataFrame,
    color_column: str,
    colors: dict[int, str] | None,
    key: str,
    vertical_exaggeration: float = 1.0,
    reference_df: pd.DataFrame | None = None,
    continuous_limits: tuple[float, float] | None = None,
) -> None:
    """Interactive 3D point display for the currently loaded model dataset."""
    frame = reference_df if reference_df is not None and not reference_df.empty else df
    x_min, x_max = float(frame["X"].min()), float(frame["X"].max())
    y_min, y_max = float(frame["Y"].min()), float(frame["Y"].max())
    z_min, z_max = float(frame["Z"].min()), float(frame["Z"].max())
    values = df[color_column].to_numpy() if color_column in df.columns else np.array([])
    discrete = is_discrete_facies_property(color_column, values)
    fig = go.Figure()
    if discrete and colors:
        for category in get_visible_facies(values):
            subset = df[np.round(values).astype(int) == category]
            fig.add_trace(go.Scatter3d(
                x=subset["X"], y=subset["Y"], z=subset["Z"], mode="markers", name=facies_label(category),
                marker={"size": 2, "color": colors.get(category, default_facies_color(category))},
                customdata=subset.reindex(columns=[column for column in ("I", "J", "K", "CellIndex") if column in subset.columns]).to_numpy(),
                hovertemplate=f"<b>{facies_label(category)}</b><br>X: %{{x:.0f}}<br>Y: %{{y:.0f}}<br>Z: %{{z:.0f}}<extra></extra>",
            ))
    else:
        raw_values = pd.to_numeric(df[color_column], errors="coerce")
        colour = raw_values.copy()
        colour_title = color_column
        if "perm" in color_column.lower():
            colour = np.log10(colour.clip(lower=1e-12))
            colour_title = f"{color_column} (log10 mD)"
        marker = {
            "size": 2,
            "color": colour,
            "colorscale": continuous_color_scale(color_column),
            "showscale": True,
            "colorbar": {"title": colour_title},
        }
        if continuous_limits is not None:
            marker.update({"cmin": continuous_limits[0], "cmax": continuous_limits[1]})
        metadata_columns = [column for column in ("I", "J", "K", "CellIndex") if column in df.columns]
        customdata = np.column_stack([raw_values.to_numpy(), *[df[column].to_numpy() for column in metadata_columns]])
        hover_lines = [f"<b>{color_column}</b>: %{{customdata[0]:.6g}}", "X: %{x:.2f}", "Y: %{y:.2f}", "Z: %{z:.2f}"]
        if {"I", "J", "K"}.issubset(metadata_columns):
            hover_lines.append("I, J, K: %{customdata[1]}, %{customdata[2]}, %{customdata[3]}")
        if "CellIndex" in metadata_columns:
            cell_position = metadata_columns.index("CellIndex") + 1
            hover_lines.append(f"CellIndex: %{{customdata[{cell_position}]}}")
        fig.add_trace(go.Scatter3d(
            x=df["X"], y=df["Y"], z=df["Z"], mode="markers",
            marker=marker,
            customdata=customdata,
            hovertemplate="<br>".join(hover_lines) + "<extra></extra>",
        ))
    # A small horizontal north arrow: projected model coordinates conventionally
    # use X as easting and positive Y as northing.
    arrow_x = x_min + (x_max - x_min) * 0.08
    arrow_y = y_min + (y_max - y_min) * 0.08
    arrow_length = max((y_max - y_min) * 0.10, 1.0)
    arrow_z = z_min + (z_max - z_min) * 0.03
    fig.add_trace(go.Cone(
        x=[arrow_x], y=[arrow_y], z=[arrow_z],
        u=[0], v=[arrow_length], w=[0],
        anchor="tail", sizemode="absolute", sizeref=arrow_length * 0.25,
        colorscale=[[0, "#d62728"], [1, "#d62728"]], showscale=False,
        hovertemplate="North (+Y)<extra></extra>", name="North (+Y)",
    ))

    # Always use the complete loaded dataset as the 3D frame.  A slice must
    # not shrink its axes/aspect, otherwise Plotly treats it as a new view and
    # resets the camera.
    # Keep coordinates and axis labels in their true units; aspectratio only changes
    # their visual scale in the 3D scene.
    x_range = max(x_max - x_min, 1.0)
    y_range = max(y_max - y_min, 1.0)
    z_range = max((z_max - z_min) * vertical_exaggeration, 1.0)
    largest_range = max(x_range, y_range, z_range)
    aspect = {
        "x": max(x_range / largest_range, 0.02),
        "y": max(y_range / largest_range, 0.02),
        "z": max(z_range / largest_range, 0.02),
    }
    fig.update_layout(
        height=650,
        margin=dict(l=10, r=10, t=20, b=10),
        # A stable uirevision preserves the user's orbit, zoom and pan while
        # I/J/K controls replace the displayed slice.
        uirevision=f"{key}_camera",
        scene={
            "xaxis": {"range": [x_min, x_max]},
            "yaxis": {"range": [y_min, y_max]},
            # Z is already elevation/depth in its source sign convention
            # (negative below datum), so retain the normal upward-positive axis.
            "zaxis": {"range": [z_min, z_max]},
            "aspectmode": "manual",
            "aspectratio": aspect,
            "uirevision": f"{key}_camera",
            # Start south of the model looking toward +Y (north), with a
            # modest elevated perspective for the vertically exaggerated grid.
            "camera": {
                "eye": {"x": 0.0, "y": -1.9, "z": 0.8},
                "up": {"x": 0.0, "y": 0.0, "z": 1.0},
                "center": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
            "annotations": [{
                "x": arrow_x,
                "y": arrow_y + arrow_length * 1.12,
                "z": arrow_z,
                "text": "N",
                "showarrow": False,
                "font": {"color": "#d62728", "size": 14},
            }],
        },
    )
    st.plotly_chart(fig, width="stretch", key=key)


def slice_depth_band_below_top(df: pd.DataFrame, depth_below_top_m: float, half_thickness_m: float) -> pd.DataFrame:
    """Keep only points genuinely within a depth band below the exported model top."""
    if not {"I", "J", "Z"}.issubset(df.columns):
        return df
    work = df.copy()
    z = pd.to_numeric(work["Z"], errors="coerce")
    work = work[z.notna()].copy()
    work["DepthBelowTop_m"] = work.groupby(["I", "J"])["Z"].transform("max") - work["Z"]
    return work[(work["DepthBelowTop_m"] - depth_below_top_m).abs() <= half_thickness_m]


@st.cache_data(show_spinner=False)
def bestfit_reduced_point_count(path_text: str, property_name: str, enabled_codes: tuple[int, ...], reservoir_only: bool, spacing: float) -> int:
    """Return the exact count retained by the Best-fit reduced sampling algorithm."""
    path = Path(path_text)
    nx, ny, _ = grdecl_dimensions(path_text)
    values = [int(float(value)) for value in expand_values(tokenize_grdecl(path, {property_name})[property_name])]
    centres = grdecl_cell_centers(path)
    allowed = set(enabled_codes)
    groups: dict[tuple[int, int], list[float]] = {}
    for index, ((_, _, z), facies) in enumerate(zip(centres, values)):
        if reservoir_only and facies not in allowed:
            continue
        groups.setdefault((facies, index % (nx * ny)), []).append(z)
    retained = 0
    for depths in groups.values():
        depths.sort()
        if len(depths) <= 2:
            retained += len(depths)
            continue
        retained += 1  # top/end of sorted column
        last_depth = depths[0]
        for depth in depths[1:-1]:
            if abs(depth - last_depth) >= spacing:
                retained += 1
                last_depth = depth
        retained += 1  # bottom/end of sorted column
    return retained


@st.cache_data(show_spinner=False)
def bestfit_reduced_preview_dataframe(
    path_text: str,
    property_name: str,
    enabled_codes: tuple[int, ...],
    reservoir_only: bool,
    spacing: float,
    max_rows: int,
) -> pd.DataFrame:
    """Build a display-sized preview using the exact reduced-export selection."""
    path = Path(path_text)
    nx, ny, _ = grdecl_dimensions(path_text)
    values = [int(float(value)) for value in expand_values(tokenize_grdecl(path, {property_name})[property_name])]
    centres = grdecl_cell_centers(path)
    allowed = set(enabled_codes)
    groups: dict[tuple[int, int], list[tuple[int, float]]] = {}
    for index, ((_, _, z), facies) in enumerate(zip(centres, values)):
        if reservoir_only and facies not in allowed:
            continue
        groups.setdefault((facies, index % (nx * ny)), []).append((index, z))
    selected: set[int] = set()
    for cells in groups.values():
        cells.sort(key=lambda item: item[1])
        selected.add(cells[0][0])
        last_z = cells[0][1]
        for index, z in cells[1:-1]:
            if abs(z - last_z) >= spacing:
                selected.add(index)
                last_z = z
        selected.add(cells[-1][0])
    rows = []
    for index in sorted(selected):
        x, y, z = centres[index]
        rows.append({
            "X": x, "Y": y, "Z": z, property_name: values[index], "CellIndex": index,
            "I": index % nx + 1, "J": (index // nx) % ny + 1, "K": index // (nx * ny) + 1,
        })
    preview = pd.DataFrame(rows)
    if len(preview) > max_rows:
        preview = preview.sample(max_rows, random_state=7).sort_values(["K", "J", "I"])
    return preview


@st.cache_data(show_spinner=False)
def control_model_arrays(path_text: str, property_name: str) -> tuple[int, int, int, np.ndarray, np.ndarray, np.ndarray]:
    """Cache the compact geometry/facies arrays needed for a Control envelope."""
    path = Path(path_text)
    nx, ny, nz = grdecl_dimensions(path_text)
    centres = np.asarray(grdecl_cell_centers(path), dtype=float)
    facies = np.asarray(
        [int(float(value)) for value in expand_values(tokenize_grdecl(path, {property_name})[property_name])],
        dtype=int,
    )
    if len(centres) != len(facies):
        raise ValueError(f"{path.name}: geometry and {property_name} lengths differ")
    nxy = nx * ny
    # Only the reference XY centres, all cell depths, and facies are needed.
    return nx, ny, nz, centres[:nxy, :2], centres[:, 2], facies


def control_envelope_cache_key(paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...]) -> str:
    source = "|".join((*paths_text, property_name, *(str(code) for code in enabled_codes)))
    return f"control_envelopes::{hashlib.sha1(source.encode('utf-8')).hexdigest()}"


def shared_control_envelopes(
    paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...]
) -> tuple[int, int, int, np.ndarray, np.ndarray, dict[int, tuple[np.ndarray, np.ndarray]]]:
    """Build shared top/base arrays once, with real progress across models."""
    if not paths_text:
        return 0, 0, 0, np.empty((0, 2)), np.empty((0,)), {}
    cache_key = control_envelope_cache_key(paths_text, property_name, enabled_codes)
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    progress = st.progress(0, text=f"Scanning 0 of {len(paths_text)} realizations for the shared Control envelope…")
    nx = ny = nz = 0
    reference_xy = reference_z = None
    envelopes: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for model_number, path_text in enumerate(paths_text, start=1):
        model_nx, model_ny, model_nz, xy, z, facies = control_model_arrays(path_text, property_name)
        if model_number == 1:
            nx, ny, nz = model_nx, model_ny, model_nz
            reference_xy, reference_z = xy, z.reshape(nz, nx * ny)
            for code in enabled_codes:
                envelopes[code] = (np.full(nx * ny, -np.inf), np.full(nx * ny, np.inf))
        elif (model_nx, model_ny) != (nx, ny):
            raise ValueError(f"{Path(path_text).name} has incompatible I/J dimensions")

        for code in enabled_codes:
            indices = np.flatnonzero(facies == code)
            if not len(indices):
                continue
            columns = indices % (nx * ny)
            top, bottom = envelopes[code]
            np.maximum.at(top, columns, z[indices])
            np.minimum.at(bottom, columns, z[indices])
        progress.progress(model_number / len(paths_text), text=f"Scanning {model_number} of {len(paths_text)} realizations for the shared Control envelope…")
    progress.empty()
    result = (nx, ny, nz, reference_xy, reference_z, envelopes)
    st.session_state[cache_key] = result
    return result


def control_point_summary(
    paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...], spacing: float
) -> tuple[int, dict[int, int]]:
    """Return the exact Control point count without materialising preview rows."""
    _, _, _, _, _, envelopes = shared_control_envelopes(paths_text, property_name, enabled_codes)
    counts_by_facies: dict[int, int] = {}
    for facies, (top, bottom) in envelopes.items():
        valid = np.isfinite(top) & np.isfinite(bottom)
        counts_by_facies[facies] = int((np.ceil((top[valid] - bottom[valid]) / spacing).astype(int) + 1).sum())
    return sum(counts_by_facies.values()), counts_by_facies


def control_preview_dataframe(
    paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...], spacing: float, max_rows: int
) -> tuple[pd.DataFrame, int, dict[int, int]]:
    """Build a display-sized Control preview from the already-scanned envelope."""
    nx, ny, nz, reference_xy, reference_z, envelopes = shared_control_envelopes(paths_text, property_name, enabled_codes)
    total, counts_by_facies = control_point_summary(paths_text, property_name, enabled_codes, spacing)
    if total == 0:
        return pd.DataFrame(), 0, counts_by_facies
    rows: list[dict[str, float | int]] = []
    # Keep a bounded, representative preview. The full shared envelope is still
    # used by the actual build command; this limit affects display only.
    preview_limit = min(total, max_rows)
    stride = max(1, int(np.ceil(total / preview_limit)))
    sequence = 0
    for facies, (top, bottom) in envelopes.items():
        for column in np.flatnonzero(np.isfinite(top) & np.isfinite(bottom)):
            levels = np.arange(top[column], bottom[column] - 1e-9, -spacing)
            if not len(levels) or abs(levels[-1] - bottom[column]) > 1e-9:
                levels = np.append(levels, bottom[column])
            for z in levels:
                if sequence % stride == 0 and len(rows) < preview_limit:
                    nearest_k = int(np.abs(reference_z[:, column] - z).argmin()) + 1
                    rows.append({"X": float(reference_xy[column, 0]), "Y": float(reference_xy[column, 1]), "Z": float(z), property_name: facies, "ControlColumn": int(column), "I": int(column % nx + 1), "J": int(column // nx + 1), "K": nearest_k})
                sequence += 1
    return pd.DataFrame(rows), total, counts_by_facies


def uber_bounds_cache_key(paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...]) -> str:
    source = "|".join((*paths_text, property_name, *(str(code) for code in enabled_codes)))
    return f"uber_bounds::{hashlib.sha1(source.encode('utf-8')).hexdigest()}"


def shared_uber_bounds(
    paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...]
) -> tuple[int, int, np.ndarray, np.ndarray, np.ndarray, list[int]]:
    """Scan the multi-realization local top/base envelope once with progress."""
    if not paths_text:
        return 0, 0, np.empty((0, 2)), np.empty((0,)), np.empty((0,)), []
    cache_key = uber_bounds_cache_key(paths_text, property_name, enabled_codes)
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    progress = st.progress(0, text=f"Scanning 0 of {len(paths_text)} realizations for the Uber envelope…")
    nx = ny = 0
    xy = top = bottom = None
    facies_codes: set[int] = set()
    enabled = set(enabled_codes)
    for model_number, path_text in enumerate(paths_text, start=1):
        model_nx, model_ny, model_nz, model_xy, z, facies = control_model_arrays(path_text, property_name)
        if model_number == 1:
            nx, ny = model_nx, model_ny
            xy = model_xy
            top = np.full(nx * ny, -np.inf)
            bottom = np.full(nx * ny, np.inf)
        elif (model_nx, model_ny) != (nx, ny):
            raise ValueError(f"{Path(path_text).name} has incompatible I/J dimensions")
        z_by_column = z.reshape(model_nz, nx * ny)
        top = np.maximum(top, z_by_column.max(axis=0))
        bottom = np.minimum(bottom, z_by_column.min(axis=0))
        facies_codes.update(int(code) for code in np.unique(facies) if code != 0 and code in enabled)
        progress.progress(model_number / len(paths_text), text=f"Scanning {model_number} of {len(paths_text)} realizations for the Uber envelope…")
    progress.empty()
    result = (nx, ny, xy, top, bottom, sorted(facies_codes))
    st.session_state[cache_key] = result
    return result


def uber_point_summary(paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...], spacing: float) -> tuple[int, int, int, list[int]]:
    """Calculate exact Uber output size without materialising its potentially huge grid."""
    nx, ny, _, top, bottom, facies = shared_uber_bounds(paths_text, property_name, enabled_codes)
    if not nx or not facies:
        return 0, 0, 0, []
    z_levels = int((np.ceil((top - bottom) / spacing).astype(int) + 1).sum())
    xy_points = nx * ny
    return z_levels * len(facies), xy_points, z_levels, facies


def uber_preview_dataframe(
    paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...], spacing: float, facies: int, max_rows: int
) -> tuple[pd.DataFrame, int]:
    """Build a bounded display preview for one facies from cached Uber bounds."""
    nx, ny, xy, top, bottom, _ = shared_uber_bounds(paths_text, property_name, enabled_codes)
    if not nx:
        return pd.DataFrame(), 0
    levels_per_column = np.ceil((top - bottom) / spacing).astype(int) + 1
    total = int(levels_per_column.sum())
    preview_limit = min(total, max_rows)
    stride = max(1, int(np.ceil(total / preview_limit)))
    rows = []
    sequence = 0
    for column, number_of_levels in enumerate(levels_per_column):
        levels = top[column] - np.arange(number_of_levels) * spacing
        if abs(levels[-1] - bottom[column]) > 1e-9:
            levels[-1] = bottom[column]
        for k_index, z in enumerate(levels):
            if sequence % stride == 0 and len(rows) < preview_limit:
                rows.append({"X": float(xy[column, 0]), "Y": float(xy[column, 1]), "Z": float(z), property_name: facies, "I": int(column % nx + 1), "J": int(column // nx + 1), "K": int(k_index + 1)})
            sequence += 1
    return pd.DataFrame(rows), total


@st.fragment
def uber_sampling_control(paths: list[Path], property_name: str, enabled_codes: tuple[int, ...]) -> float:
    """Keep Uber spacing changes local instead of rerunning the dashboard."""
    spacing = st.select_slider(
        "Uber vertical sampling interval (m)",
        options=[10.0, 25.0, 50.0, 75.0, 100.0], value=50.0, key="tab1_uber_spacing",
    )
    if paths:
        uber_total, xy_count, z_count, uber_facies = uber_point_summary(
            tuple(str(path) for path in paths), property_name, enabled_codes, spacing
        )
        st.metric("Uber points exported to T>Map", f"{uber_total:,}")
        st.caption(f"{xy_count:,} XY locations with {z_count:,} local-envelope vertical controls per facies at {spacing:g} m spacing.")
    return float(spacing)


def facies_config_editor(
    codes: list[int],
    config_path: Path,
    source_dir: Path,
    facies_property: str,
    key: str,
    include_tmap_flag: bool = True,
    definition_label: str = "Facies",
) -> None:
    """Edit facies names, colours, categories, and optionally T>Map inclusion."""
    if not codes:
        return
    with st.expander(f"{definition_label} definitions", expanded=False):
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        except (OSError, json.JSONDecodeError):
            payload = {}
        # Streamlit preserves values by widget key across reruns.  Derive a
        # short key version from the loaded JSON so an externally restored or
        # newly selected configuration is reflected in the editor immediately.
        config_version = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        widget_key = f"{key}_{config_version}"
        names = payload.get("facies_names", {})
        colours = payload.get("facies_colors", {})
        metadata = payload.get("facies_metadata", {})
        edited_names, edited_colours, edited_metadata = {}, {}, {}
        st.caption(f"Editing {display_path(config_path)}")
        if include_tmap_flag:
            st.caption("Disable T>Map for non-reservoir facies. Those cells are excluded from T>Map modelling and will receive `-77777` for appended T>Map properties.")
        else:
            st.caption(f"Define the {definition_label.lower()} names, colours, and categories used by this project. This workflow does not use T>Map inclusion flags.")
        for position, code in enumerate(codes):
            item = metadata.get(str(code), {}) if isinstance(metadata.get(str(code)), dict) else {}
            columns = st.columns([0.7, 2.2, 1.0, 1.5, 1.0] if include_tmap_flag else [0.7, 2.4, 1.1, 1.7])
            columns[0].write(f"**{code}**")
            edited_names[code] = columns[1].text_input("Name", names.get(str(code), f"Facies {code}"), key=f"{widget_key}_name_{code}")
            edited_colours[code] = columns[2].color_picker("Colour", colours.get(str(code), default_facies_color(position)), key=f"{widget_key}_colour_{code}")
            category_options = ["reservoir", "non_reservoir"]
            category = str(item.get("category", "non_reservoir" if code == 0 else "reservoir"))
            edited_metadata[code] = {"category": columns[3].selectbox("Category", category_options, index=category_options.index(category) if category in category_options else 0, key=f"{widget_key}_category_{code}")}
            if include_tmap_flag:
                override_key = f"facies_tmap_override::{config_path}::{code}"

                def set_override(widget: str = f"{widget_key}_tmap_{code}", target: str = override_key, facies_code: int = code) -> None:
                    """Persist only the T>Map switch immediately so export counts stay actionable."""
                    value = bool(st.session_state[widget])
                    st.session_state[target] = value
                    try:
                        saved = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
                        saved_metadata = saved.setdefault("facies_metadata", {})
                        record = saved_metadata.setdefault(str(facies_code), {})
                        record["tmap_enabled"] = value
                        config_path.parent.mkdir(parents=True, exist_ok=True)
                        config_path.write_text(json.dumps(saved, indent=2) + "\n", encoding="utf-8")
                    except OSError as exc:
                        st.error(f"Could not save the T>Map flag: {exc}")

                edited_metadata[code]["tmap_enabled"] = columns[4].checkbox(
                    "T>Map", value=bool(item.get("tmap_enabled", code != 0)), key=f"{widget_key}_tmap_{code}", on_change=set_override
                )
        if st.button(f"Save {definition_label.lower()} definitions", key=f"{widget_key}_save"):
            # A selected realization can legitimately omit a facies that occurs
            # elsewhere in the same project. Preserve those project-level
            # definitions rather than replacing the JSON with this one file's
            # subset of codes.
            merged_names = dict(names)
            merged_colours = dict(colours)
            merged_metadata = dict(metadata)
            merged_names.update({str(code): name for code, name in edited_names.items()})
            merged_colours.update({str(code): colour for code, colour in edited_colours.items()})
            merged_metadata.update({str(code): meta for code, meta in edited_metadata.items()})
            payload.update({
                "facies_property": facies_property,
                "source_grdecl_directory": str(source_dir),
                "source_grdecl_files": [path.name for path in files_in(source_dir, ("*.grdecl", "*.GRDECL"))],
                "facies_names": merged_names,
                "facies_colors": merged_colours,
                "facies_metadata": merged_metadata,
            })
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            st.success(f"{definition_label} definitions saved.")
            st.rerun()


def enabled_tmap_codes(config: dict, config_path: Path) -> set[int]:
    """Use saved flags plus any currently edited dashboard toggles for previews."""
    enabled: set[int] = set()
    for code, item in config.get("facies_metadata", {}).items():
        key = f"facies_tmap_override::{config_path}::{code}"
        is_enabled = st.session_state.get(key, item.get("tmap_enabled", True)) if isinstance(item, dict) else True
        if is_enabled:
            enabled.add(int(code))
    return enabled


def run_commands(commands: list[list[str]], show_live_progress: bool = False) -> bool:
    output = []
    for command in commands:
        full_command = [sys.executable, *command]
        output.append(f"> {' '.join(command)}")
        if show_live_progress:
            progress = st.progress(0, text="Starting conversion…")
            live_log = st.empty()
            process = subprocess.Popen(
                full_command,
                cwd=ROOT,
                creationflags=WORKER_CREATION_FLAGS,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            command_output: list[str] = []
            for raw_line in process.stdout or []:
                line = raw_line.rstrip()
                if not line:
                    continue
                command_output.append(line)
                match = re.match(r"PROGRESS\s+(\d+)\s*/\s*(\d+)\s+(.+)", line)
                if match:
                    current, total, message = int(match.group(1)), int(match.group(2)), match.group(3)
                    progress.progress(min(current / max(total, 1), 1.0), text=f"{message} ({current}/{total})")
                live_log.code("\n".join(command_output[-12:]), language="text")
            returncode = process.wait()
            progress.empty()
            live_log.empty()
            if command_output:
                output.append("\n".join(command_output))
        else:
            result = subprocess.run(full_command, cwd=ROOT, capture_output=True, text=True, creationflags=WORKER_CREATION_FLAGS)
            returncode = result.returncode
            if result.stdout:
                output.append(result.stdout.strip())
            if result.stderr:
                output.append(result.stderr.strip())
        if returncode != 0:
            st.error(f"Command failed: {' '.join(command)}")
            st.code("\n\n".join(output), language="text")
            return False
    st.success("Workflow step completed")
    st.code("\n\n".join(output), language="text")
    return True


def commands_for_grdecl_dir(commands: list[list[str]], grdecl_dir: Path) -> list[list[str]]:
    """Pass the dashboard's selected source folder to builder/append scripts."""
    return [[*command, "--grdecl-dir", str(grdecl_dir)] for command in commands]


def append_commands_for_project(approach: dict, grdecl_dir: Path) -> list[list[str]]:
    """Pass project-specific source, returned-pointset and destination folders to append writers."""
    commands = []
    for command in commands_for_grdecl_dir(approach["append"], grdecl_dir):
        output_dir = approach.get("petrel_augmented_dir") if command[0].endswith("write_petrel_standard_uber_grdecls.py") else approach["augmented_dir"]
        commands.append([
            *command,
            "--pointset-dir", str(approach["tmap_dir"]),
            "--output-dir", str(output_dir),
        ])
    return commands


def keyword_candidates(path: Path) -> list[str]:
    keywords: list[str] = []
    active = False
    with open(path_for_io(path), "r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.split("--", 1)[0].strip()
            if not line:
                continue
            if active:
                if "/" in line:
                    active = False
                continue
            head = line.split()[0]
            if head == "/":
                continue
            keywords.append(head)
            if "/" not in line and head not in {"NOECHO", "ECHO"}:
                active = True
    return keywords


def expand_values(tokens: list[str]) -> list[str]:
    values: list[str] = []
    for token in tokens:
        if "*" in token:
            count_text, repeated = token.split("*", 1)
            values.extend([repeated] * int(float(count_text)))
        else:
            values.append(token)
    return values


@st.cache_data(show_spinner=False)
def grdecl_dimensions(path_text: str) -> tuple[int, int, int]:
    data = tokenize_grdecl(Path(path_text), {"SPECGRID"})
    return tuple(int(float(value)) for value in data["SPECGRID"][:3])


@st.cache_data(show_spinner=False)
def grdecl_dataframe(path_text: str, property_keyword: str | None, max_rows: int) -> pd.DataFrame:
    path = Path(path_text)
    nx, ny, nz = grdecl_dimensions(path_text)
    centers = grdecl_cell_centers(path)
    df = pd.DataFrame(centers, columns=["X", "Y", "Z"])
    n = len(df)
    cell_index = np.arange(n)
    df["CellIndex"] = cell_index
    df["I"] = cell_index % nx + 1
    df["J"] = (cell_index // nx) % ny + 1
    df["K"] = cell_index // (nx * ny) + 1
    if property_keyword:
        tokens = tokenize_grdecl(path, {property_keyword})[property_keyword]
        values = expand_values(tokens)
        if len(values) == n:
            numeric = pd.to_numeric(pd.Series(values), errors="coerce")
            df[property_keyword] = numeric if numeric.notna().any() else values
    if len(df) > max_rows:
        return df.sample(max_rows, random_state=7).sort_values(["K", "J", "I"])
    return df


def parse_point_header(path: Path) -> list[str]:
    columns: list[str] = []
    in_header = False
    with open(path_for_io(path), "r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if line == "BEGIN HEADER":
                in_header = True
                continue
            if line == "END HEADER":
                break
            if in_header:
                columns.append(line.split(",", 1)[-1].strip().strip('"'))
    return columns


@st.cache_data(show_spinner=False)
def pointset_dataframe(path_text: str, max_rows: int) -> pd.DataFrame:
    path = Path(path_text)
    columns = parse_point_header(path)
    if not columns:
        raise ValueError(f"{path.name} is not a T>Map point-set file (BEGIN HEADER / END HEADER not found).")
    rows: list[list[str]] = []
    in_header = False
    with open(path_for_io(path), "r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line == "BEGIN HEADER":
                in_header = True
                continue
            if line == "END HEADER":
                in_header = False
                continue
            if in_header or line.startswith("#") or line == "VERSION 1":
                continue
            rows.append(line.split())
    df = pd.DataFrame(rows, columns=columns[: len(rows[0])] if rows else columns)
    for column in df.columns:
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.notna().any():
            df[column] = numeric
    if len(df) > max_rows:
        return df.sample(max_rows, random_state=7)
    return df


def plot_map(
    df: pd.DataFrame,
    color_column: str,
    title: str,
    colors: dict[int, str] | None = None,
    key: str | None = None,
    extent: tuple[float, float, float, float] | None = None,
    continuous_limits: tuple[float, float] | None = None,
) -> None:
    if px is None:
        st.info("Install Plotly to enable interactive maps: python -m pip install plotly")
        st.dataframe(df.head(500), width="stretch")
        return
    
    # Check if this is cell polygon data
    has_cells = all(col in df.columns for col in ["X0", "Y0", "X1", "Y1", "X2", "Y2", "X3", "Y3"])
    if has_cells:
        return plot_map_with_cells(df, color_column, title, colors, key=key)
    
    # Otherwise treat as point data
    values = df[color_column].values if color_column in df.columns else np.array([])
    is_discrete = is_discrete_facies_property(color_column, values)
    
    if is_discrete and colors:
        categories = get_visible_facies(values)
        fig = go.Figure()
        for category in categories:
            mask = np.round(values).astype(int) == category
            hover_columns = ["I", "J", "K", "Z", "CellIndex", "Realization"]
            fig.add_trace(
                go.Scatter(
                    x=df[mask]["X"],
                    y=df[mask]["Y"],
                    mode="markers",
                    name=facies_label(category),
                    marker={"size": 4, "color": colors.get(category, default_facies_color(category))},
                    customdata=df.loc[mask].reindex(columns=hover_columns).to_numpy(),
                    hovertemplate=(f"<b>{facies_label(category)}</b><br>X: %{{x:.0f}}<br>Y: %{{y:.0f}}"
                                   "<br>I,J,K: %{customdata[0]}, %{customdata[1]}, %{customdata[2]}<extra></extra>"),
                )
            )
        fig.update_layout(
            height=560,
            margin=dict(l=10, r=10, t=45, b=10),
            yaxis_scaleanchor="x",
            title=title,
        )
    else:
        plot_data = df.copy()
        color_field = color_column
        if "perm" in color_column.lower():
            color_field = "_log10_permeability"
            plot_data[color_field] = np.log10(pd.to_numeric(plot_data[color_column], errors="coerce").clip(lower=1e-12))
        color_range = continuous_limits or (porosity_display_limits(plot_data[color_column]) if ("porosity" in color_column.lower() or color_column.lower().startswith("poro")) else None)
        fig = px.scatter(
            plot_data,
            x="X",
            y="Y",
            color=color_field,
            hover_data=[col for col in ("I", "J", "K", "Z", "CellIndex", "Realization", "Facies") if col in df.columns],
            render_mode="webgl",
            title=title,
            color_continuous_scale=continuous_color_scale(color_column) if pd.api.types.is_numeric_dtype(df[color_column]) else None,
            range_color=color_range,
        )
        fig.update_layout(height=560, margin=dict(l=10, r=10, t=45, b=10), yaxis_scaleanchor="x")
        if color_field != color_column:
            fig.update_coloraxes(
                colorbar=dict(
                    title=f"{color_column} (mD)",
                    tickvals=[-2, -1.699, -1.301, -1, -0.699, -0.301, 0, 0.301, 0.699, 1, 1.301, 1.699, 2, 2.301, 2.699, 3, 3.301, 3.699, 4],
                    ticktext=["0.01", "0.02", "0.05", "0.1", "0.2", "0.5", "1", "2", "5", "10", "20", "50", "100", "200", "500", "1,000", "2,000", "5,000", "10,000"],
                )
            )
    
    if extent:
        x_min, x_max, y_min, y_max = extent
        fig.update_xaxes(range=[x_min, x_max])
        fig.update_yaxes(range=[y_min, y_max])
    st.plotly_chart(fig, width="stretch", key=key)


def plot_section(df: pd.DataFrame, color_column: str, axis_mode: str, selector: int | float, colors: dict[int, str] | None = None, key: str | None = None, continuous_limits: tuple[float, float] | None = None) -> None:
    if px is None:
        st.info("Install Plotly to enable cross-section plots: python -m pip install plotly")
        return
    full_work = df.copy()
    work = df.copy()
    if axis_mode == "Grid column (I)" and "I" in work.columns:
        work = work[work["I"] == selector]
        x_axis = "J"
        x_axis_label = "Cell position along J"
    elif axis_mode == "Grid row (J)" and "J" in work.columns:
        work = work[work["J"] == selector]
        x_axis = "I"
        x_axis_label = "Cell position along I"
    elif axis_mode == "X slice":
        width = max((work["X"].max() - work["X"].min()) / 80.0, 1.0)
        work = work[(work["X"] >= selector - width) & (work["X"] <= selector + width)]
        x_axis = "Y"
        x_axis_label = "Y"
    else:
        width = max((work["Y"].max() - work["Y"].min()) / 80.0, 1.0)
        work = work[(work["Y"] >= selector - width) & (work["Y"] <= selector + width)]
        x_axis = "X"
        x_axis_label = "X"
    if work.empty:
        st.warning("No points in this section.")
        return

    # Preserve one frame across all section selectors so the viewer does not
    # zoom into the local subset when I/J or X/Y slice changes.
    full_x = pd.to_numeric(full_work[x_axis], errors="coerce")
    full_z = pd.to_numeric(full_work["Z"], errors="coerce")
    x_limits = (float(full_x.min()), float(full_x.max()))
    z_limits = (float(full_z.min()), float(full_z.max()))
    
    values = work[color_column].values if color_column in work.columns else np.array([])
    is_discrete = is_discrete_facies_property(color_column, values)
    
    if is_discrete and colors:
        categories = get_visible_facies(values)
        fig = go.Figure()
        for category in categories:
            mask = np.round(values).astype(int) == category
            fig.add_trace(
                go.Scatter(
                    x=work[mask][x_axis],
                    y=work[mask]["Z"],
                    mode="markers",
                    name=facies_label(category),
                    marker={"size": 5, "color": colors.get(category, default_facies_color(category))},
                    hovertemplate=f"<b>{facies_label(category)}</b><br>{x_axis}: %{{x:.0f}}<br>Z: %{{y:.0f}}<extra></extra>",
                )
            )
        fig.update_layout(
            height=560,
            margin=dict(l=10, r=10, t=45, b=10),
            title=f"{axis_mode}: {selector}",
            xaxis_title=x_axis_label,
            yaxis_title="Z (depth)",
        )
    else:
        plot_data = work.copy()
        color_field = color_column
        if "perm" in color_column.lower():
            color_field = "_log10_permeability"
            plot_data[color_field] = np.log10(pd.to_numeric(plot_data[color_column], errors="coerce").clip(lower=1e-12))
        color_range = continuous_limits or (porosity_display_limits(plot_data[color_column]) if ("porosity" in color_column.lower() or color_column.lower().startswith("poro")) else None)
        fig = px.scatter(
            plot_data,
            x=x_axis,
            y="Z",
            color=color_field,
            hover_data=[col for col in ("I", "J", "K", "X", "Y", "CellIndex", "Facies") if col in work.columns],
            render_mode="webgl",
            title=f"{axis_mode}: {selector}",
            color_continuous_scale=continuous_color_scale(color_column) if pd.api.types.is_numeric_dtype(work[color_column]) else None,
            range_color=color_range,
        )
        fig.update_layout(height=560, margin=dict(l=10, r=10, t=45, b=10), xaxis_title=x_axis_label, yaxis_title="Z (depth)")
        if color_field != color_column:
            fig.update_coloraxes(
                colorbar=dict(
                    title=f"{color_column} (mD)",
                    tickvals=[-2, -1.699, -1.301, -1, -0.699, -0.301, 0, 0.301, 0.699, 1, 1.301, 1.699, 2, 2.301, 2.699, 3, 3.301, 3.699, 4],
                    ticktext=["0.01", "0.02", "0.05", "0.1", "0.2", "0.5", "1", "2", "5", "10", "20", "50", "100", "200", "500", "1,000", "2,000", "5,000", "10,000"],
                )
            )
    
    fig.update_xaxes(range=x_limits)
    fig.update_yaxes(range=z_limits)
    st.plotly_chart(fig, width="stretch", key=key)


@st.fragment
def visualization_panel(
    df: pd.DataFrame,
    key: str,
    default_color: str | None = None,
    is_grdecl: bool = False,
    cell_only: bool = False,
    dynamic_continuous_scale: bool = False,
    grdecl_path: str | None = None,
) -> None:
    numeric_or_small = [
        col
        for col in df.columns
        if col not in {"X", "Y", "Z"}
        and (pd.api.types.is_numeric_dtype(df[col]) or df[col].nunique(dropna=True) <= 30)
    ]
    if not numeric_or_small:
        st.dataframe(df.head(500), width="stretch")
        return
    color_index = numeric_or_small.index(default_color) if default_color in numeric_or_small else 0
    color_column = st.selectbox("Property", numeric_or_small, index=color_index, key=f"{key}_color")
    
    # Resolve facies colours before drawing. The editor itself is deliberately
    # placed below the viewer so its controls do not shift the map/section UI.
    values = df[color_column].values if color_column in df.columns else np.array([])
    is_discrete = is_discrete_facies_property(color_column, values)
    colors: dict[int, str] = {}
    if is_discrete:
        categories = get_visible_facies(values)
        saved_palette = read_facies_config()
        colors = {category: saved_palette.get(category, default_facies_color(position)) for position, category in enumerate(categories)}
    lock_scale = False
    continuous_limits = None
    valid_value_mask: pd.Series | None = None
    if not is_discrete and color_column != "CellIndex" and pd.api.types.is_numeric_dtype(df[color_column]):
        valid_value_mask = valid_continuous_mask(df[color_column])
        valid_values = pd.to_numeric(df.loc[valid_value_mask, color_column], errors="coerce")
        if ("porosity" in color_column.lower() or color_column.lower().startswith("poro")) and not dynamic_continuous_scale:
            # Keep DFN/T>Map porosity comparable across K layers and views.
            continuous_limits = porosity_display_limits(valid_values)
            unit_caption = "0–40 vol %" if continuous_limits[1] == 40.0 else "0–0.4 fraction"
            st.caption(f"Porosity colour scale is fixed at {unit_caption} for comparison between layers and models.")
        else:
            if dynamic_continuous_scale and ("porosity" in color_column.lower() or color_column.lower().startswith("poro")):
                st.caption("DFN result colour scale follows the selected property values, so low fracture porosity remains visible.")
            lock_scale = st.checkbox("Lock colour scale across related statistics (P10/P50/P90)", key=f"{key}_lock_scale")
            if lock_scale:
                continuous_limits = related_continuous_limits(df, color_column)
            elif not valid_values.empty:
                if "perm" in color_column.lower():
                    logged = np.log10(valid_values[valid_values > 0])
                    continuous_limits = (float(logged.min()), float(logged.max())) if not logged.empty else None
                else:
                    continuous_limits = (float(valid_values.min()), float(valid_values.max()))
    
    # Check if we have cell polygon data
    has_cells = all(col in df.columns for col in ["X0", "Y0", "X1", "Y1", "X2", "Y2", "X3", "Y3"])
    
    view = st.radio("View", ["Map viewer", "Cross-section", "3D viewer", "Data table"], horizontal=True, key=f"{key}_view")
    if has_cells and is_grdecl:
        if cell_only:
            visualization_mode = "Cells"
        else:
            visualization_mode = st.radio("Viewer", ["Points", "Cells"], horizontal=True, key=f"{key}_viz_mode")
    else:
        visualization_mode = "Points"
    active_cell_mode = is_cell_data(df) and visualization_mode == "Cells"
    plot_df = df if active_cell_mode else cell_centres_as_points(df)

    if {"X", "Y"}.issubset(plot_df.columns):
        x_min, x_max = float(plot_df["X"].min()), float(plot_df["X"].max())
        y_min, y_max = float(plot_df["Y"].min()), float(plot_df["Y"].max())
        padding = max(x_max - x_min, y_max - y_min) * 0.03
        map_extent = (x_min - padding, x_max + padding, y_min - padding, y_max + padding)
    else:
        map_extent = None

    # Do not render cells without a returned continuous value as the minimum
    # of the colour scale. Their absence is clearer, and keeps the scale tied
    # to actual T>Map/DFN data rather than -77777/-999 placeholders.
    viewer_df = plot_df
    if valid_value_mask is not None and not active_cell_mode:
        viewer_df = plot_df.loc[valid_continuous_mask(plot_df[color_column])].copy()
        if viewer_df.empty:
            st.warning("No valid values are available for this property; all cells contain a no-value placeholder.")
            return

    if view == "Map viewer":
        if active_cell_mode:
            # For cell data, show one K-layer at a time
            if is_cell_data(df):
                k_min, k_max = int(df["K"].min()), int(df["K"].max())
                selected_k = k_layer_selector(f"{key}_cell_k_layer", k_min, k_max)
                df_filtered = df[df["K"] == selected_k]
                plot_map_with_cells(df_filtered, color_column, f"Map viewer (K={selected_k})", colors if is_discrete else None, key=f"{key}_cell_map")
            else:
                plot_map_with_cells(df, color_column, "Map viewer", colors if is_discrete else None, key=f"{key}_cell_map")
        else:
            # A source/augmented grid in point mode can still contain every cell.
            # Restrict it to one K layer before Plotly receives the data.
            if is_grdecl and "K" in plot_df.columns:
                k_min, k_max = int(plot_df["K"].min()), int(plot_df["K"].max())
                slice_mode = st.radio("Map slice", ["K layer", "Depth band below model top"], horizontal=True, key=f"{key}_point_slice_mode")
                show_mesh = False
                if slice_mode == "K layer":
                    selected_k = k_layer_selector(f"{key}_point_k_layer", k_min, k_max)
                    point_layer = viewer_df[viewer_df["K"] == selected_k]
                    title = f"Map viewer (points, K={selected_k})"
                    can_show_mesh = (
                        grdecl_path is not None
                        and Path(grdecl_path).is_file()
                        and color_column != "CellIndex"
                    )
                    if can_show_mesh:
                        show_mesh = st.checkbox(
                            "Show true GRDECL cells for selected K layer (experimental)",
                            key=f"{key}_k_mesh",
                            help=(
                                "Renders the top faces of this one K layer from COORD and ZCORN as a single "
                                "WebGL mesh. This is much lighter than the earlier per-cell polygon view, but "
                                "still more demanding than points."
                            ),
                        )
                    elif grdecl_path is not None and color_column == "CellIndex":
                        st.caption("True-cell view requires a GRDECL property. Select Facies or another grid property instead of CellIndex.")
                    if show_mesh:
                        plot_grdecl_k_mesh(
                            grdecl_path,
                            color_column,
                            selected_k,
                            f"Map viewer (true GRDECL cells, K={selected_k})",
                            colors if is_discrete else None,
                            continuous_limits,
                            key=f"{key}_k_mesh_plot",
                        )
                else:
                    max_depth = float((viewer_df.groupby(["I", "J"])["Z"].transform("max") - viewer_df["Z"]).max())
                    st.caption("Uses the shallowest exported point in each I/J column as the local model top. Only real points within the chosen depth band are shown; gaps reveal reduced sampling coverage.")
                    depth_below_top = st.slider("Depth below model top (m)", 0.0, max(1.0, max_depth), min(10.0, max_depth), step=1.0, key=f"{key}_point_depth_below_top")
                    half_thickness = st.slider("Depth-band half-thickness (m)", 1.0, max(1.0, max_depth / 2.0), min(5.0, max(1.0, max_depth / 2.0)), step=1.0, key=f"{key}_point_depth_band")
                    point_layer = slice_depth_band_below_top(viewer_df, depth_below_top, half_thickness)
                    title = f"Map viewer (points, {depth_below_top:g} ± {half_thickness:g} m below model top)"
                if not show_mesh:
                    plot_map(point_layer, color_column, title, colors if is_discrete else None, key=f"{key}_point_map", extent=map_extent, continuous_limits=continuous_limits)
            else:
                plot_map(viewer_df, color_column, "Map viewer", colors if is_discrete else None, key=f"{key}_point_map", extent=map_extent, continuous_limits=continuous_limits)
    elif view == "3D viewer":
        three_d_df = viewer_df
        if not is_discrete and ("porosity" in color_column.lower() or color_column.lower().startswith("poro")):
            porosity_values = pd.to_numeric(three_d_df[color_column], errors="coerce")
            three_d_df = three_d_df[porosity_values.notna() & (porosity_values > -999.0)]
            if three_d_df.empty:
                st.warning("No valid porosity values are available for the 3D viewer.")
                st.stop()
        vertical_exaggeration = st.slider(
            "Vertical exaggeration",
            min_value=1.0,
            max_value=50.0,
            value=5.0,
            step=1.0,
            help="Visually expands the Z direction only. Coordinates, values, and axis labels remain in their true units.",
            key=f"{key}_3d_vertical_exaggeration",
        )
        if {"I", "J", "K"}.issubset(plot_df.columns):
            slice_axis = st.radio("3D slice", ["Full model", "I layer", "J layer", "K layer"], horizontal=True, key=f"{key}_3d_slice_axis")
            if slice_axis != "Full model":
                axis = slice_axis[0]
                minimum, maximum = int(plot_df[axis].min()), int(plot_df[axis].max())
                selected_layer = grid_layer_selector(axis, f"{key}_3d_{axis}_layer", minimum, maximum)
                three_d_df = viewer_df[viewer_df[axis] == selected_layer]
                st.caption(f"Showing {slice_axis} = {selected_layer}: {len(three_d_df):,} points.")
        plot_3d_points(
            three_d_df,
            color_column,
            colors if is_discrete else None,
            key=f"{key}_3d",
            vertical_exaggeration=vertical_exaggeration,
            reference_df=plot_df,
            continuous_limits=continuous_limits,
        )
    elif view == "Cross-section":
        section_options = ["X slice", "Y slice"]
        if {"I", "J"}.issubset(plot_df.columns):
            section_options = ["Grid column (I)", "Grid row (J)", *section_options]
        axis_mode = st.selectbox("Section mode", section_options, key=f"{key}_section_mode")
        if axis_mode == "Grid column (I)":
            selector = st.slider("Grid column (I)", int(plot_df["I"].min()), int(plot_df["I"].max()), int(plot_df["I"].median()), key=f"{key}_i")
        elif axis_mode == "Grid row (J)":
            selector = st.slider("Grid row (J)", int(plot_df["J"].min()), int(plot_df["J"].max()), int(plot_df["J"].median()), key=f"{key}_j")
        elif axis_mode == "X slice":
            x_column = "X_center" if active_cell_mode else "X"
            selector = st.slider("X", float(plot_df[x_column].min()), float(plot_df[x_column].max()), float(plot_df[x_column].median()), key=f"{key}_x")
        else:
            y_column = "Y_center" if active_cell_mode else "Y"
            selector = st.slider("Y", float(plot_df[y_column].min()), float(plot_df[y_column].max()), float(plot_df[y_column].median()), key=f"{key}_y")

        if active_cell_mode:
            plot_section_with_cells(df, color_column, axis_mode, selector, colors if is_discrete else None, key=f"{key}_cell_section")
        else:
            plot_section(viewer_df, color_column, axis_mode, selector, colors if is_discrete else None, key=f"{key}_point_section", continuous_limits=continuous_limits)
    else:
        st.dataframe(df.head(2000), width="stretch")

    if is_discrete and categories:
        st.divider()
        facies_color_settings(categories, f"{key}_facies")


def approach_selector(key: str) -> tuple[str, dict[str, Path]]:
    name = st.selectbox("Approach", list(ACTIVE_APPROACHES), key=key)
    return name, ACTIVE_APPROACHES[name]


def file_selector(label: str, folder: Path, patterns: tuple[str, ...], key: str) -> Path | None:
    files = files_in(folder, patterns)
    if not files:
        st.warning(f"No files found in {display_path(folder)}")
        return None
    selected = st.selectbox(label, files, format_func=lambda path: path.name, key=key)
    st.caption(display_path(selected))
    return selected


def grdecl_property_selector(path: Path, key: str, classification_label: str = "Facies") -> str | None:
    property_keywords = grdecl_property_keywords(path)
    if not property_keywords:
        return None
    default = preferred_classification_property(property_keywords)
    return st.selectbox(
        f"Select {classification_label} property in GRDECL",
        property_keywords,
        index=property_keywords.index(default),
        key=key,
        help=f"Selects the {classification_label.lower()} property used for the source-cell viewer.",
    )


def grdecl_property_keywords(path: Path) -> list[str]:
    nx, ny, nz = grdecl_dimensions(str(path))
    cell_count = nx * ny * nz
    keywords = keyword_candidates(path)
    property_keywords = []
    for keyword in keywords:
        if keyword in {"MAPUNITS", "MAPAXES", "GRIDUNIT", "SPECGRID", "COORDSYS", "COORD", "ZCORN", "PINCH", "NOECHO", "ECHO"}:
            continue
        try:
            values = expand_values(tokenize_grdecl(path, {keyword})[keyword])
        except Exception:
            continue
        if len(values) == cell_count:
            property_keywords.append(keyword)
    return property_keywords


@st.cache_data(show_spinner=False)
def augmented_grdecl_dataframe(path_text: str, max_rows: int) -> pd.DataFrame:
    """Load all cell-sized properties in an augmented GRDECL for Tab 3."""
    path = Path(path_text)
    nx, ny, nz = grdecl_dimensions(path_text)
    centres = grdecl_cell_centers(path)
    df = pd.DataFrame(centres, columns=["X", "Y", "Z"])
    cell_index = np.arange(len(df))
    df["CellIndex"] = cell_index
    df["I"] = cell_index % nx + 1
    df["J"] = (cell_index // nx) % ny + 1
    df["K"] = cell_index // (nx * ny) + 1
    for keyword in grdecl_property_keywords(path):
        values = expand_values(tokenize_grdecl(path, {keyword})[keyword])
        numeric = pd.to_numeric(pd.Series(values), errors="coerce")
        df[keyword] = numeric if numeric.notna().any() else values
    if len(df) > max_rows:
        return df.sample(max_rows, random_state=7).sort_values(["K", "J", "I"])
    return df


@st.cache_data(show_spinner=False)
def grdecl_coverage_counts(path_text: str, facies_property: str, diagenetic_property: str) -> tuple[int, int]:
    """Count defined facies and populated T>Map cells from only two GRDECL properties."""
    data = tokenize_grdecl(Path(path_text), {facies_property, diagenetic_property})
    facies = pd.to_numeric(pd.Series(expand_values(data[facies_property])), errors="coerce")
    diagenetic = pd.to_numeric(pd.Series(expand_values(data[diagenetic_property])), errors="coerce")
    defined_facies = int((facies.notna() & (facies != 0) & (facies != -77777)).sum())
    defined_diagenetic = int((diagenetic.notna() & (diagenetic != -77777)).sum())
    return defined_facies, defined_diagenetic


@st.cache_data(show_spinner=False)
def facies_tmap_coverage(path_text: str, facies_property: str, tmap_property: str) -> dict[int, tuple[int, int]]:
    """Return total and populated T>Map-property cells for every facies in one GRDECL."""
    data = tokenize_grdecl(Path(path_text), {facies_property, tmap_property})
    facies = pd.to_numeric(pd.Series(expand_values(data[facies_property])), errors="coerce")
    values = pd.to_numeric(pd.Series(expand_values(data[tmap_property])), errors="coerce")
    available = values.notna() & ~values.isin([-999.0, -77777.0])
    result: dict[int, tuple[int, int]] = {}
    for code in sorted(int(value) for value in facies.dropna().unique()):
        mask = facies == code
        result[code] = (int(mask.sum()), int((mask & available).sum()))
    return result


def coverage_properties(path: Path) -> tuple[str | None, str | None]:
    """Choose a facies field and one representative appended property without validating every block."""
    keywords = keyword_candidates(path)
    facies = next((name for name in ("Facies", "FACIES") if name in keywords), None)
    ignored = {"MAPUNITS", "MAPAXES", "GRIDUNIT", "SPECGRID", "COORDSYS", "COORD", "ZCORN", "PINCH", "NOECHO", "ECHO", facies}
    candidates = [name for name in keywords if name not in ignored]
    preferred = next((name for name in candidates if "poro" in name.lower()), None)
    return facies, preferred or (candidates[0] if candidates else None)


@st.fragment
def geomechanics_property_selectors(
    properties: list[str], classification_label: str = "Facies", workflow_profile: str = "MVP"
) -> tuple[str, str, str, str]:
    """Keep Tab 4 input-property changes independent from the model viewer."""
    crystalline = classification_label == "Rock type"
    carbonate = workflow_profile == "Carbonates"
    facies_property = st.selectbox(
        f"{classification_label} property",
        properties,
        index=properties.index(preferred_classification_property(properties)),
        key="tab4_facies",
    )
    porosity_options = [name for name in properties if "poro" in name.lower()]
    cement_options = [
        name for name in properties
        if any(term in name.lower() for term in ("cement", "quartz", "calcite", "dolomite", "anhydrite", "gypsum"))
    ]
    stress_options = [name for name in properties if "stress" in name.lower()]
    porosity_property = st.selectbox(
        "Porosity property" if crystalline else "GOLEM/PHREEQC porosity property" if carbonate else "T>Map porosity property",
        porosity_options or properties,
        key="tab4_poro",
    )
    cement_property = st.selectbox(
        "Optional mineral or cement property" if carbonate else "Optional cement property",
        ["None", *(cement_options or properties)],
        key="tab4_cement",
    )
    stress_property = st.selectbox("Optional effective-stress property", ["None", *(stress_options or properties)], key="tab4_stress")
    if crystalline:
        st.caption("These choices assign geomechanical properties by rock type. The output writes `DFNPorosity` and `DFNEffectiveStress_MPa` from the selected grid properties or the explicitly enabled depth-compaction fallback.")
    elif carbonate:
        st.caption("These choices assign geomechanical properties by carbonate facies. Once available, select porosity and mineral/cement properties re-appended from GOLEM/PHREEQC; until then, the source-grid properties can be used as provisional inputs.")
    else:
        st.caption("These choices are used only when writing DFM-preparation properties. The output also writes `DFNPorosity` and `DFNEffectiveStress_MPa`: T>Map values where present, otherwise the explicitly enabled depth-compaction fallback.")
    return facies_property, porosity_property, cement_property, stress_property


GEOMECHANICS_FORMULA_DEFAULTS = {
    "clean_sandstone_critical_porosity": {"Young ref (GPa)": 35.0, "Poisson": 0.22, "Friction": 0.60, "Cohesion (MPa)": 5.0, "Tensile (MPa)": 2.0, "Fracture energy (J/m²)": 50.0},
    "shale_porosity_stress": {"Young ref (GPa)": 20.0, "Poisson": 0.33, "Friction": 0.45, "Cohesion (MPa)": 3.0, "Tensile (MPa)": 1.0, "Fracture energy (J/m²)": 30.0},
    "carbonate_chalk_critical_porosity": {"Young ref (GPa)": 45.0, "Poisson": 0.28, "Friction": 0.55, "Cohesion (MPa)": 6.0, "Tensile (MPa)": 2.5, "Fracture energy (J/m²)": 60.0},
    "crystalline_compact_framework": {"Young ref (GPa)": 60.0, "Poisson": 0.24, "Friction": 0.65, "Cohesion (MPa)": 10.0, "Tensile (MPa)": 5.0, "Fracture energy (J/m²)": 100.0},
}


def apply_geomechanics_formula_defaults() -> None:
    """Apply a formula's starting values before the facies editor is redrawn."""
    editor_state = st.session_state.get("tab4_facies_editor", {})
    row_codes = st.session_state.get("tab4_geomech_row_codes", {})
    previous_formulas = st.session_state.setdefault("tab4_geomech_formulas", {})
    for row_index, changes in editor_state.get("edited_rows", {}).items():
        formula = changes.get("Formula")
        code = row_codes.get(row_index, row_codes.get(str(row_index)))
        if formula in GEOMECHANICS_FORMULA_DEFAULTS and code is not None and previous_formulas.get(str(code)) != formula:
            changes.update(GEOMECHANICS_FORMULA_DEFAULTS[formula])
            previous_formulas[str(code)] = formula


@st.fragment
def geomechanics_facies_editor(rows: list[dict], classification_label: str = "Facies") -> pd.DataFrame:
    table = pd.DataFrame(rows)
    locked = [column for column in ("Facies", "Facies name", "T>Map data", "Diagenesis data") if column in table.columns]
    return st.data_editor(
        table,
        hide_index=True,
        key="tab4_facies_editor",
        disabled=locked,
        column_config={
            "Facies": st.column_config.NumberColumn(classification_label),
            "Facies name": st.column_config.TextColumn(f"{classification_label} name"),
            "Formula": st.column_config.SelectboxColumn("Formula", options=list(GEOMECHANICS_FORMULA_DEFAULTS)),
        },
        on_change=apply_geomechanics_formula_defaults,
    )


def build_workflow_tabs(profile: str) -> tuple[list[object], object | None, object | None]:
    """Return the six existing workflow containers plus profile-only tabs.

    The hidden containers retain the mature MVP controls for reuse by the
    applicable profiles. Their labels are hidden only inside this tab shell;
    this keeps the visible navigation focused on the selected rock workflow.
    """
    mvp_labels = [
        "FSM → FDM (GRDECL → 3D points)",
        "FDM Append & View",
        "FFM Geomech preparation",
        "FFM Run DFM",
        "FFM View results",
    ]
    inspection_tab = placeholder_tab = None
    hidden_from: int | None = None
    if profile == "Siliciclastics":
        labels = [mvp_labels[0], mvp_labels[1], "Fault Seal Analysis", "Internal FFM geomech", "Internal FFM run", "Internal FFM results"]
        mapping = [0, 1, 1, 3, 4, 5]
        placeholder_index, hidden_from = 2, 4
    elif profile == "Carbonates":
        labels = ["FSM GRDECL → Mesh", "FDM Carbonate Diagenesis", *mvp_labels[2:], "Internal model preparation", "Internal FDM append", "Internal FDM review"]
        mapping = [5, 6, 7, 2, 3, 4]
        inspection_index, placeholder_index, hidden_from = 0, 1, 6
    elif profile == "Crystalline rocks":
        labels = ["GRDECL Inspect", *mvp_labels[2:], "Internal model preparation", "Internal FDM append", "Internal FDM review"]
        mapping = [4, 5, 6, 1, 2, 3]
        inspection_index, hidden_from = 0, 5
    else:
        labels = mvp_labels
        # The FDM stage combines the existing append and appended-GRDECL
        # review containers, so both tab2 and tab3 write into one visible tab.
        mapping = [0, 1, 1, 2, 3, 4]

    with st.container(key="workflow-tabs-shell"):
        containers = st.tabs(labels)
    if hidden_from is not None:
        st.markdown(
            f"""<style>
            .st-key-workflow-tabs-shell [data-testid="stTab"]:nth-child(n + {hidden_from}) {{ display: none !important; }}
            </style>""",
            unsafe_allow_html=True,
        )
    if profile in {"Carbonates", "Crystalline rocks"}:
        inspection_tab = containers[inspection_index]
    if profile in {"Siliciclastics", "Carbonates"}:
        placeholder_tab = containers[placeholder_index]
    return [containers[index] for index in mapping], inspection_tab, placeholder_tab


def classification_property_for_profile(grdecl: Path, profile: str) -> str | None:
    """Find the categorical property used for facies or rock-type definitions."""
    available = set(keyword_candidates(grdecl))
    if profile == "Crystalline rocks":
        preferred = ["RockType", "ROCKTYPE", "ROCK_TYPE", "Lithology", "LITHOLOGY", "LITHO", "Facies", "FACIES"]
    else:
        preferred = ["Facies", "FACIES", "Lithofacies", "LITHOFACIES", "Lithology", "LITHOLOGY", "RockType", "ROCKTYPE"]
    return next((name for name in preferred if name in available), None)


def render_profile_grdecl_inspection(profile: str) -> None:
    """A lightweight source-grid loader for carbonate and crystalline profiles."""
    left, right = st.columns([0.34, 0.66])
    source_dir = ACTIVE_SOURCE_GRDECL_DIR
    grdecl: Path | None = None
    prop: str | None = None
    with left:
        st.subheader("FSM GRDECL → Mesh" if profile == "Carbonates" else "Inspect GRDECL model")
        if profile == "Carbonates":
            st.caption("Path: FSM GRDECL → finite-element mesh → GOLEM/PHREEQC carbonate diagenesis → re-appended GRDECL properties → DFM geomechanics.")
            st.info("This stage imports and inspects the corner-point GRDECL, defines rock types, and will prepare an unstructured mesh plus CellIndex-to-mesh-element mapping. The mesh conversion is the planned GOLEM handoff; the source GRDECL remains the authoritative grid for later DFM preparation.")
        else:
            st.caption("Load a GRDECL from this project's source folder and inspect its geometry, rock types, and properties. No 3D-point conversion is used in this workflow profile.")
        st.session_state["active_facies_config"] = str(source_dir / "facies_config.json")
        st.caption(f"Source folder: {display_path(source_dir)}")
        with st.expander("Import source GRDECL file(s)", expanded=not any(source_dir.glob("*.grdecl"))):
            st.caption("Select one or more source files. The file browser shows all formats; only `.grdecl` files and an optional `facies_config.json` are copied into this project.")
            source_grdecl_file_import_controls(f"{profile.lower().replace(' ', '_')}_source_import")
        grdecl = file_selector("Source GRDECL", source_dir, ("*.grdecl", "*.GRDECL"), f"{profile}_inspection_grdecl")
        if not grdecl:
            st.info("Add a GRDECL to this project's original_grdecl folder to inspect it here.")
        else:
            dims = grdecl_dimensions(str(grdecl))
            first, second = st.columns(2)
            first.metric("Grid dimensions", f"{dims[0]} × {dims[1]} × {dims[2]}")
            second.metric("Cells", f"{dims[0] * dims[1] * dims[2]:,}")
            definition_label = "Rock type" if profile == "Crystalline rocks" else "Facies"
            prop = grdecl_property_selector(grdecl, f"{profile}_inspection_property", definition_label)
            classification_key = classification_property_for_profile(grdecl, profile)
            if classification_key:
                classification_codes = sorted({int(float(value)) for value in expand_values(tokenize_grdecl(grdecl, {classification_key})[classification_key])})
                facies_config_editor(
                    classification_codes,
                    source_dir / "facies_config.json",
                    source_dir,
                    classification_key,
                    f"{profile.lower().replace(' ', '_')}_facies_editor",
                    include_tmap_flag=False,
                    definition_label=definition_label,
                )
            if profile == "Carbonates":
                mesh_dir = ACTIVE_APPROACHES["Moose/Golem diagenesis"]["point_dir"]
                st.divider()
                st.subheader("Prepare GOLEM mesh")
                st.caption(f"Output: finite-element mesh, CellIndex-to-element mapping, and case inputs in {display_path(mesh_dir)}.")
                st.button(
                    "Prepare GOLEM mesh and CellIndex mapping",
                    disabled=True,
                    key="carbonate_prepare_golem_mesh",
                    help="Scaffold only: this requires the GRDECL-to-finite-element-mesh converter and the agreed GOLEM material/boundary-condition template.",
                )
    with right:
        if grdecl and prop:
            df = grdecl_dataframe(str(grdecl), prop, max_rows)
            visualization_panel(df, f"{profile}_inspection_view", prop, is_grdecl=True, grdecl_path=str(grdecl))


def render_workflow_placeholder(profile: str) -> None:
    if profile == "Siliciclastics":
        st.subheader("Fault Seal Analysis")
        st.info("Placeholder for the siliciclastic fault-seal stage. This will receive fault surfaces, juxtaposition relationships, clay/shale indicators, and fault-rock assumptions, then return seal-risk or transmissibility modifiers for later geothermal assessment.")
    else:
        left, right = st.columns([0.34, 0.66])
        carbonate_approach = ACTIVE_APPROACHES["Moose/Golem diagenesis"]
        raw_result_dir = carbonate_approach["tmap_dir"]
        appended_dir = carbonate_approach["augmented_dir"]
        with left:
            st.subheader("FDM Carbonate Diagenesis")
            st.caption("Workflow: GOLEM/PHREEQC mesh results → import result files → CellIndex re-append to the original GRDECL → inspect appended GRDECL → FFM Geomech preparation.")
            st.markdown("""1. Run the mesh and GOLEM/PHREEQC case prepared in Tab 1 externally.
2. Import the returned GOLEM result file(s) into this project.
3. Re-append porosity, permeability and mineral results to the original GRDECL by CellIndex.
4. Inspect the appended GRDECL in the viewer.
5. Continue to FFM Geomech preparation.""")
            st.subheader("Import GOLEM/PHREEQC result file(s)")
            st.caption(f"External results are copied without format restrictions into {display_path(raw_result_dir)}.")
            external_file_import_controls(
                "carbonate_golem_results_import",
                raw_result_dir,
                "Select GOLEM/PHREEQC result file(s)",
                "Copy selected GOLEM/PHREEQC result file(s) into project",
            )
            st.button(
                "Re-append CellIndex-matched GOLEM results to GRDECL",
                disabled=True,
                key="carbonate_append_golem_results",
                help="Scaffold only: this requires a defined GOLEM result schema and an element-to-CellIndex mapping file.",
            )
            st.divider()
            st.caption(f"Re-appended GRDECLs will be written to {display_path(appended_dir)}. Tab 3, FFM Geomech preparation, reads that folder.")
        with right:
            appended_files = files_in(appended_dir, ("*.grdecl", "*.GRDECL"))
            if not appended_files:
                st.info("No carbonate-diagenesis GRDECL has been re-appended yet. Import GOLEM/PHREEQC results on the left, then use the CellIndex re-append step once its result schema is defined.")
            else:
                result_file = st.selectbox(
                    "GRDECL with re-appended carbonate-diagenesis results",
                    appended_files,
                    format_func=lambda path: path.name,
                    key="carbonate_diagenesis_result_view",
                )
                result_df = augmented_grdecl_dataframe(str(result_file), max_rows)
                default_property = "Facies" if "Facies" in result_df.columns else "FACIES" if "FACIES" in result_df.columns else None
                visualization_panel(result_df, "carbonate_diagenesis_result", default_property, is_grdecl=True, grdecl_path=str(result_file))


st.title("GO-Forward: Integrated Forward Modelling Workflow")
st.caption("Prepare geological models for diagenesis, review returned properties, and create DFN-ready fracture-modelling inputs.")

with st.sidebar:
    st.image(ROOT / "docs" / "assets" / "logos" / "GO-Forward-gros_transparent.png", width="stretch")
    st.header("Project")
    clear_missing_workspace_file_state()
    existing_projects = project_names()
    available_projects = existing_projects.copy()
    if not available_projects:
        available_projects = [DEFAULT_PROJECT_NAME]
    default_project = DEFAULT_PROJECT_NAME if DEFAULT_PROJECT_NAME in available_projects else available_projects[0]
    if pending := st.session_state.pop("pending_project_selector", None):
        st.session_state["project_selector"] = pending
    if st.session_state.get("project_selector") not in available_projects:
        st.session_state["project_selector"] = default_project
    active_project = st.selectbox("Select existing project", available_projects, key="project_selector")
    active_profile = project_workflow_profile(active_project)
    st.selectbox(
        "Rock workflow",
        list(WORKFLOW_PROFILES),
        index=list(WORKFLOW_PROFILES).index(active_profile),
        format_func=lambda profile: str(WORKFLOW_PROFILES[profile]["label"]),
        key=f"project_workflow_display_{active_project}",
        disabled=True,
        help="Existing projects use the workflow encoded in their folder suffix. Legacy projects without a suffix are MVP projects.",
    )
    st.caption(str(WORKFLOW_PROFILES[active_profile]["description"]))
    if result := st.session_state.pop("project_remove_result", None):
        level, message = result
        (st.success if level == "success" else st.warning if level == "warning" else st.error)(message)
    if active_project in existing_projects:
        if st.button("Remove project", key="project_remove_button"):
            remove_project_dialog(active_project)
    st.divider()
    st.caption("Create project")
    new_project_profile = st.selectbox(
        "Type of new project",
        ["", *WORKFLOW_PROFILES],
        index=0,
        format_func=lambda profile: "Select type of project" if not profile else str(WORKFLOW_PROFILES[profile]["label"]),
        key="project_new_workflow",
    )
    new_project_name = st.text_input("New project name", placeholder="geothermal_project", key="project_new_name")
    if new_project_profile:
        suffix = str(WORKFLOW_PROFILES[new_project_profile]["suffix"])
        st.caption(f"New project folder: `{new_project_name.strip().rstrip('_-') or 'geothermal_project'}_{suffix}`")
    else:
        st.caption("Choose a project type to set the workflow and project-folder suffix.")
    st.button(
        "Create project",
        key="project_create",
        on_click=create_project,
        args=(new_project_name, new_project_profile),
        disabled=not new_project_profile,
    )
    if error := st.session_state.pop("project_create_error", None):
        st.error(error)
    if created := st.session_state.pop("project_created", None):
        st.success(f"Created and selected project: {created}")
    st.caption(f"Project data: {display_path(DATA_ROOT / active_project)}")
    st.caption(f"Starting GRDECLs: {display_path(DATA_ROOT / active_project / ORIGINAL_GRDECL_FOLDER)}")
    st.divider()
    st.header("Display")
    max_rows = st.slider("Maximum plotted rows", 5_000, 200_000, 75_000, step=5_000)
    st.caption(f"Workspace: {ROOT}")
    if px is None:
        st.warning("Plotly is not installed; visual plots will be replaced by tables.")

ACTIVE_PROJECT_NAME = active_project
ACTIVE_PROJECT_DATA_DIR = DATA_ROOT / ACTIVE_PROJECT_NAME
ACTIVE_SOURCE_GRDECL_DIR = ACTIVE_PROJECT_DATA_DIR / ORIGINAL_GRDECL_FOLDER
ACTIVE_APPROACHES = approaches_for_project(ACTIVE_PROJECT_DATA_DIR, active_profile, ACTIVE_SOURCE_GRDECL_DIR)

workflow_tabs, inspection_tab, workflow_placeholder_tab = build_workflow_tabs(active_profile)
tab1, tab2, tab3, tab4, tab5, tab6 = workflow_tabs

if inspection_tab is not None:
    with inspection_tab:
        render_profile_grdecl_inspection(active_profile)

if workflow_placeholder_tab is not None:
    with workflow_placeholder_tab:
        render_workflow_placeholder(active_profile)

with tab1:
    left, right = st.columns([0.34, 0.66])
    with left:
        st.subheader("FSM → FDM: GRDECL → 3D points")
        st.caption("Input: source GRDECL. Action: define facies and create pointsets. Output: T>Map-ready 3D pointsets.")
        source_grdecl_dir = ACTIVE_SOURCE_GRDECL_DIR
        st.session_state["active_facies_config"] = str(source_grdecl_dir / "facies_config.json")
        st.caption(f"Project source folder: {display_path(source_grdecl_dir)}")
        with st.expander("Import source GRDECL file(s)", expanded=not any(source_grdecl_dir.glob("*.grdecl"))):
            st.caption("Select one or more source files. The file browser shows all formats; only `.grdecl` files and an optional `facies_config.json` are copied into this project.")
            source_grdecl_file_import_controls("tab1_source_import")
        facies_key = None
        if not source_grdecl_dir.is_dir():
            st.error("The project source folder is not available.")
        grdecl = file_selector("Source file", source_grdecl_dir, ("*.grdecl", "*.GRDECL"), "tab1_grdecl")
        if grdecl:
            prop = grdecl_property_selector(grdecl, "tab1_prop")
            dims = grdecl_dimensions(str(grdecl))
            st.metric("Grid dimensions", f"{dims[0]} x {dims[1]} x {dims[2]}")
            st.metric("Cells", f"{dims[0] * dims[1] * dims[2]:,}")
            facies_key = "Facies" if "Facies" in keyword_candidates(grdecl) else "FACIES" if "FACIES" in keyword_candidates(grdecl) else None
            if facies_key:
                facies_codes = sorted({int(float(value)) for value in expand_values(tokenize_grdecl(grdecl, {facies_key})[facies_key])})
                facies_config_editor(
                    facies_codes,
                    source_grdecl_dir / "facies_config.json",
                    source_grdecl_dir,
                    facies_key,
                    "tab1_facies_editor",
                )
        else:
            prop = None

        st.divider()
        st.subheader("Conversion")
        approach_name, approach = approach_selector("tab1_approach")
        bestfit_reduced = False
        bestfit_spacing = 50.0
        bestfit_reservoir_only = False
        selected_multi_models: list[Path] = []
        multi_enabled_codes: tuple[int, ...] = ()
        control_spacing = 50.0
        uber_spacing = 50.0
        if approach_name == "Best-fit model":
            export_mode = st.radio(
                "Best-fit export",
                ["Full cell-centre resolution", 'Reduced vertical sampling (select "Preview reduced T>Map points" under Viewer data)'],
                key="bestfit_export_mode",
            )
            bestfit_reduced = export_mode.startswith("Reduced vertical sampling")
            bestfit_reservoir_only = st.checkbox("Reservoir facies only", value=True, key="bestfit_reservoir_only")
            if bestfit_reduced:
                bestfit_spacing = st.select_slider("Maximum vertical sampling interval (m)", options=[10.0, 25.0, 50.0, 75.0, 100.0], value=50.0, key="bestfit_spacing")
            if grdecl and facies_key:
                values = [int(float(value)) for value in expand_values(tokenize_grdecl(grdecl, {facies_key})[facies_key])]
                try:
                    config = json.loads((source_grdecl_dir / "facies_config.json").read_text(encoding="utf-8"))
                    config_path = source_grdecl_dir / "facies_config.json"
                    enabled = enabled_tmap_codes(config, config_path)
                    reservoir_cells = sum(value in enabled for value in values)
                    eligible_count = reservoir_cells if bestfit_reservoir_only else len(values)
                    if bestfit_reduced:
                        exported_count = bestfit_reduced_point_count(
                            str(grdecl), facies_key, tuple(sorted(enabled)), bestfit_reservoir_only, bestfit_spacing
                        )
                        st.metric("Reduced points exported to T>Map", f"{exported_count:,}")
                        st.caption(f"From {eligible_count:,} eligible cells at {bestfit_spacing:g} m maximum vertical spacing.")
                        st.caption("T>Map switches save immediately and update this count and the reduced-point preview in the Viewer.")
                    else:
                        st.metric("Points eligible for T>Map", f"{eligible_count:,}")
                        st.caption("T>Map switches save immediately and update the eligible-point count.")
                except (OSError, json.JSONDecodeError):
                    st.info("Define facies metadata to calculate the reservoir-only export count.")
        else:
            available_models = files_in(source_grdecl_dir, ("*.grdecl", "*.GRDECL"))
            selected_multi_models = st.multiselect(
                "GRDECL models included in this multi-realization build",
                available_models,
                default=available_models,
                format_func=lambda path: path.name,
                key="tab1_multi_models",
                help="Only these selected source models become realizations in the generated pointsets.",
            )
            try:
                multi_config_path = source_grdecl_dir / "facies_config.json"
                multi_config = json.loads(multi_config_path.read_text(encoding="utf-8"))
                multi_enabled_codes = tuple(sorted(enabled_tmap_codes(multi_config, multi_config_path)))
            except (OSError, json.JSONDecodeError):
                st.info("Define and save Facies definitions to choose which facies are sent to T>Map.")
            if approach_name == "Multi-realization control points":
                control_spacing = st.select_slider(
                    "Maximum vertical control-point interval (m)",
                    options=[10.0, 25.0, 50.0, 75.0, 100.0], value=50.0, key="tab1_control_spacing",
                )
                if selected_multi_models and facies_key:
                    control_count, _ = control_point_summary(
                        tuple(str(path) for path in selected_multi_models), facies_key, multi_enabled_codes, control_spacing
                    )
                    st.metric("Control points exported to T>Map", f"{control_count:,}")
                    st.caption(
                        f"One shared facies envelope per I/J column: shallowest and deepest occurrence across "
                        f"{len(selected_multi_models)} selected model(s), plus {control_spacing:g} m vertical controls."
                    )
            elif approach_name == "Multi-realization Uber":
                uber_spacing = uber_sampling_control(selected_multi_models, facies_key or "Facies", multi_enabled_codes)
        if approach_name == "Best-fit model":
            st.caption(f"Best-fit conversion target: {grdecl.name}" if grdecl else "Best-fit conversion target: select a source GRDECL above.")
        else:
            st.caption(f"Multi-realization conversion target: {len(selected_multi_models)} selected GRDECL model(s).")
        st.caption(f"Conversion also creates the returned T>Map folder: {display_path(approach['tmap_dir'])}")
        can_build = source_grdecl_dir.is_dir() and (bool(grdecl) if approach_name == "Best-fit model" else bool(selected_multi_models))
        if st.button("Convert selected approach to 3D point sets", key="build_points", disabled=not can_build):
            commands = [
                [*command, "--output-dir", str(approach["point_dir"])]
                for command in commands_for_grdecl_dir(approach["build_points"], source_grdecl_dir)
            ]
            if approach_name == "Best-fit model":
                extra = ["--single-grdecl", str(grdecl), "--property", facies_key or "Facies"]
                if bestfit_reservoir_only:
                    extra.extend(["--reservoir-only", "--facies-config", str(source_grdecl_dir / "facies_config.json")])
                if bestfit_reduced:
                    extra.extend(["--max-vertical-spacing", str(bestfit_spacing)])
                commands = [[*command, *extra] for command in commands]
                st.session_state["bestfit_reduced_export"] = bestfit_reduced
            else:
                extra = ["--property", facies_key or "Facies", "--facies-config", str(source_grdecl_dir / "facies_config.json")]
                for model in selected_multi_models:
                    extra.extend(["--grdecl", str(model)])
                if approach_name == "Multi-realization control points":
                    extra.extend(["--max-vertical-spacing", str(control_spacing), "--tmap-enabled-only"])
                elif approach_name == "Multi-realization union":
                    extra.append("--tmap-enabled-only")
                elif approach_name == "Multi-realization Uber":
                    extra.extend(["--vertical-spacing", str(st.session_state.get("tab1_uber_spacing", uber_spacing)), "--tmap-enabled-only"])
                commands = [[*command, *extra] for command in commands]
            conversion_succeeded = run_commands(
                commands,
                show_live_progress=approach_name in {
                    "Multi-realization control points",
                    "Multi-realization union",
                    "Multi-realization Uber",
                },
            )
            if conversion_succeeded:
                # Create the hand-off location with the pointsets, rather than
                # waiting until a synthetic return is generated.  This makes
                # the intended destination explicit for real T>Map results.
                returned_tmap_dir = approach["tmap_dir"]
                returned_tmap_dir.mkdir(parents=True, exist_ok=True)
                handoff_note = returned_tmap_dir / "README.txt"
                if not handoff_note.exists():
                    handoff_note.write_text(
                        "Place returned T>Map point-set files for this approach in this folder.\n"
                        "Retain the original point-set filename and ID columns so the dashboard can match and append results.\n",
                        encoding="utf-8",
                    )
                # The rerun refreshes the output-folder listing, then opens the
                # actual newly written pointsets rather than leaving the user on
                # an original-model or temporary preview.
                st.session_state["tab1_viewer_source"] = "Converted 3D points"
                st.rerun()
        # A crystalline project deliberately uses its source-GRDECL folder as
        # the input to DFM preparation.  Do not mistake those GRDECL files for
        # converted 3D point sets in the shared FSM→FDM viewer.
        point_files = [
            path for path in files_in(approach["point_dir"], ("*",))
            if is_tmap_pointset_file(path)
        ]
    with right:
        viewer_options = ["Original GRDECL cells"]
        if approach_name == "Best-fit model" and bestfit_reduced and grdecl and facies_key:
            viewer_options.append("Preview reduced T>Map points")
        if approach_name == "Multi-realization control points" and selected_multi_models and facies_key:
            viewer_options.append("Preview control T>Map points")
        if approach_name == "Multi-realization Uber" and selected_multi_models and facies_key:
            viewer_options.append("Preview Uber T>Map points")
        if point_files:
            viewer_options.append("Converted 3D points")
        viewer_source = st.radio(
            "Viewer data",
            viewer_options,
            index=1 if "Converted 3D points" in viewer_options else 0,
            horizontal=True,
            key="tab1_viewer_source",
        )
        point_file = None
        if viewer_source == "Converted 3D points":
            point_file = st.selectbox(
                "Converted 3D point set",
                point_files,
                format_func=lambda path: path.name,
                key="tab1_point_file",
            )
            st.caption(display_path(point_file))

        if viewer_source == "Converted 3D points" and point_file:
            point_df = enrich_ijk_from_cell_index(pointset_dataframe(str(point_file), max_rows), source_grdecl_dir)
            visualization_panel(
                point_df,
                "tab1_point",
                "Facies" if "Facies" in point_df.columns else None,
                is_grdecl="K" in point_df.columns,
            )
        elif viewer_source == "Preview reduced T>Map points" and grdecl and facies_key:
            try:
                config = json.loads((source_grdecl_dir / "facies_config.json").read_text(encoding="utf-8"))
                enabled = enabled_tmap_codes(config, source_grdecl_dir / "facies_config.json")
                preview_df = bestfit_reduced_preview_dataframe(
                    str(grdecl), facies_key, tuple(sorted(enabled)), bestfit_reservoir_only, bestfit_spacing, max_rows
                )
                st.caption(
                    f"Preview of the current reduced Best-fit export: {len(preview_df):,} displayed points "
                    f"at {bestfit_spacing:g} m maximum vertical spacing."
                )
                visualization_panel(preview_df, "tab1_reduced_preview", facies_key, is_grdecl=True)
            except (OSError, json.JSONDecodeError, KeyError, ValueError) as exc:
                st.error(f"Could not build the reduced-point preview: {exc}")
        elif viewer_source == "Preview control T>Map points" and selected_multi_models and facies_key:
            try:
                control_df, control_total, counts_by_facies = control_preview_dataframe(
                    tuple(str(path) for path in selected_multi_models), facies_key, multi_enabled_codes, control_spacing, max_rows
                )
                preview_facies = st.selectbox(
                    "Control pointset facies to preview",
                    sorted(counts_by_facies),
                    format_func=lambda code: facies_label(int(code)),
                    key="tab1_control_preview_facies",
                )
                facies_preview_df = control_df[control_df[facies_key] == preview_facies]
                if len(facies_preview_df) > max_rows:
                    facies_preview_df = facies_preview_df.sample(max_rows, random_state=7)
                st.caption(
                    f"{facies_label(int(preview_facies))}: {counts_by_facies[preview_facies]:,} shared envelope controls, "
                    f"displaying up to {len(facies_preview_df):,} points. The envelope spans the shallowest and deepest "
                    f"occurrence across {len(selected_multi_models)} selected models in each I/J column. "
                    f"The full build creates one separate pointset file per facies ({control_total:,} points across all facies)."
                )
                st.caption("K layers in this preview are assigned from the nearest cell centre in the first selected GRDECL for visual slicing only; the exported controls use their exact shared-envelope Z values.")
                visualization_panel(facies_preview_df, "tab1_control_preview", facies_key, is_grdecl=True)
            except (OSError, ValueError, KeyError) as exc:
                st.error(f"Could not build the control-point preview: {exc}")
        elif viewer_source == "Preview Uber T>Map points" and selected_multi_models and facies_key:
            try:
                spacing = float(st.session_state.get("tab1_uber_spacing", uber_spacing))
                _, _, _, uber_facies = uber_point_summary(tuple(str(path) for path in selected_multi_models), facies_key, multi_enabled_codes, spacing)
                preview_facies = st.selectbox("Uber pointset facies to preview", uber_facies, format_func=lambda code: facies_label(int(code)), key="tab1_uber_preview_facies")
                uber_df, uber_total = uber_preview_dataframe(
                    tuple(str(path) for path in selected_multi_models), facies_key, multi_enabled_codes, spacing, int(preview_facies), max_rows
                )
                st.caption(f"{facies_label(int(preview_facies))}: {uber_total:,} regular Uber points at {spacing:g} m vertical spacing, displaying up to {len(uber_df):,}.")
                visualization_panel(uber_df, "tab1_uber_preview", facies_key, is_grdecl=True)
            except (OSError, ValueError, KeyError) as exc:
                st.error(f"Could not build the Uber-point preview: {exc}")
        elif grdecl and prop:
            df = grdecl_dataframe(str(grdecl), prop, max_rows)
            visualization_panel(df, "tab1", prop, is_grdecl=True, grdecl_path=str(grdecl))

with tab2:
    left, right = st.columns([0.34, 0.66])
    with left:
        st.subheader("FDM Append & View")
        st.caption("Input: T>Map-ready pointsets. Action: inspect returned data and append it. Output: diagenesis-enriched GRDECLs.")
        approach_name, approach = approach_selector("tab2_approach")
        pointset_files = [path for path in files_in(approach["point_dir"], ("*",)) if is_tmap_pointset_file(path)]
        tmap_files: list[Path] = []
        renamed_returns: list[tuple[str, str]] = []
        is_reduced = False
        if not pointset_files:
            st.info("No 3D pointset dataset has been created for this approach. Go to Tab 1, select this approach, and run Conversion first.")
            tmap_file = None
        else:
            st.success(f"3D pointset dataset ready: {len(pointset_files)} file(s) in {display_path(approach['point_dir'])}")
            tmap_files = [path for path in files_in(approach["tmap_dir"], ("*",)) if is_tmap_pointset_file(path)]
            if approach_name == "Best-fit model":
                available_kinds = ["Full resolution"]
                if any("_control_" in path.name for path in pointset_files):
                    available_kinds.append("Reduced vertical sampling")
                dataset_kind = st.radio("Available source 3D pointset datasets", available_kinds, horizontal=True, key="tab2_bestfit_dataset")
                is_reduced = dataset_kind == "Reduced vertical sampling"
                pointset_files = [path for path in pointset_files if ("_control_" in path.name) == is_reduced]
                renamed_returns = standardize_returned_tmap_names(tmap_files, pointset_files)
                if renamed_returns:
                    tmap_files = [path for path in files_in(approach["tmap_dir"], ("*",)) if is_tmap_pointset_file(path)]
                # A real return may have an unrelated filename, so classify it
                # from the recorded T>Map source-pointset header instead.
                tmap_files = [
                    path for path in tmap_files
                    if source_pointset_for_returned(path, pointset_files) in pointset_files
                ]
            if active_profile == "Siliciclastics":
                with st.expander("Import returned T>Map file(s)", expanded=not tmap_files):
                    st.caption(
                        "Select one or more files received from T>Map. The native file browser lets you inspect "
                        "the folder contents before choosing files. The dashboard matches each returned "
                        "pointset to this approach using its T>Map provenance header, filename, or a unique row-count match. "
                        f"Alternatively, copy returned files directly into {display_path(approach['tmap_dir'])}."
                    )
                    st.button(
                        "Select returned T>Map file(s)",
                        key="tab2_import_tmap_browse",
                        on_click=choose_tmap_return_files_with_windows_explorer,
                    )
                    if import_error := st.session_state.pop("tab2_import_tmap_error", None):
                        st.error(import_error)
                    selected_return_paths = [
                        Path(path).expanduser()
                        for path in st.session_state.get("tab2_import_tmap_selected_paths", [])
                    ]
                    if selected_return_paths:
                        import_rows, importable_files = tmap_return_import_rows(selected_return_paths, pointset_files)
                        st.dataframe(pd.DataFrame(import_rows), hide_index=True, width="stretch")
                        selected_imports = st.multiselect(
                            "Matched returned files to copy",
                            importable_files,
                            default=importable_files,
                            format_func=lambda path: path.name,
                            key="tab2_import_tmap_files",
                        )
                        replace_returns = st.checkbox(
                            "Replace same-named returned files already in the project",
                            value=False,
                            key="tab2_import_tmap_replace",
                        )
                        if st.button(
                            f"Copy {len(selected_imports)} matched T>Map return(s) into project",
                            key="tab2_import_tmap_copy",
                            disabled=not selected_imports,
                        ):
                            approach["tmap_dir"].mkdir(parents=True, exist_ok=True)
                            copied, skipped, failed = [], [], []
                            for source in selected_imports:
                                destination = approach["tmap_dir"] / source.name
                                try:
                                    same_location = source.resolve() == destination.resolve()
                                except OSError:
                                    same_location = source.parent == destination.parent
                                if same_location or (destination.exists() and not replace_returns):
                                    skipped.append(source.name)
                                    continue
                                try:
                                    shutil.copy2(source, destination)
                                    copied.append(source.name)
                                except OSError as exc:
                                    failed.append(f"{source.name}: {exc}")
                            if copied:
                                st.success(f"Copied {len(copied)} returned T>Map file(s) into {display_path(approach['tmap_dir'])}.")
                            if skipped:
                                st.warning("Skipped existing project files: " + ", ".join(skipped))
                            if failed:
                                st.error("Could not copy: " + "; ".join(failed))
                            if copied:
                                st.rerun()
                    else:
                        st.info("Select one or more returned T>Map pointset files to review and copy.")
            if renamed_returns:
                st.success("Standardized returned T>Map filename(s): " + "; ".join(f"{old} → {new}" for old, new in renamed_returns))
            if any("_tmap_inferred_geocosm" in path.name for path in tmap_files):
                st.warning("Geocosm-calibrated inferred files are a screening hypothesis trained from the supplied Base-model return. They are not a substitute for returned T>Map simulations.")
            if not tmap_files:
                tmap_file = None
                st.caption("No returned T>Map pointset is available for this source dataset yet.")
            else:
                if approach_name == "Best-fit model":
                    st.caption("Select a returned T>Map pointset to inspect. Choose one or more matching returns below to append them to their corresponding GRDECLs.")
                else:
                    st.caption("Select a returned T>Map pointset to inspect in the viewer, then append it to the selected realization workflow.")
                tmap_file = st.selectbox("Returned T>Map point-set file", tmap_files, format_func=lambda path: path.name, key="tab2_tmap_file")
                st.caption(display_path(tmap_file))
                if approach_name == "Best-fit model":
                    header_sources = tmap_header_source_pointset_names(str(tmap_file))
                    matched_source = source_pointset_for_returned(tmap_file, pointset_files)
                    if matched_source:
                        provenance = header_sources[0] if header_sources else tmap_file.name
                        st.caption(f"Matched to source 3D pointset `{matched_source.name}` from T>Map provenance `{provenance}`.")
                    else:
                        st.warning("No source 3D pointset could be matched from this file's name or T>Map header. It cannot be appended until its provenance is identifiable.")
        append_columns: list[str] = []
        if tmap_files:
            available_append_columns = appendable_tmap_columns(tmap_files)
            if available_append_columns:
                append_columns = st.multiselect(
                    "T>Map properties to append into GRDECL",
                    available_append_columns,
                    default=available_append_columns[: min(12, len(available_append_columns))],
                    key=f"tab2_append_columns_{approach_name}",
                )
                st.caption(f"{len(append_columns)} of {len(available_append_columns)} returned property column(s) selected.")
            else:
                st.warning("No returned T>Map property columns were found beyond identity columns.")
        if approach_name != "Best-fit model" and tmap_file and st.button("Append returned T>Map data back to GRDECLs", key="append_tmap", disabled=not append_columns):
            commands = [command + append_include_args(append_columns) for command in append_commands_for_project(approach, source_grdecl_dir)]
            run_commands(commands, show_live_progress=True)
        if approach_name == "Best-fit model" and tmap_files:
            st.divider()
            append_files = st.multiselect(
                "Returned T>Map pointsets to append to their corresponding GRDECLs",
                tmap_files,
                default=[tmap_file] if tmap_file else [],
                format_func=lambda path: path.name,
                key="tab2_bestfit_append_files",
            )
            if st.button("Append selected Best-fit models", key="append_bestfit_batch", disabled=not append_files):
                commands: list[list[str]] = []
                include_args = append_include_args(append_columns)
                for returned_file in append_files:
                    source_grdecl = source_grdecl_for_pointset(returned_file, source_grdecl_dir, pointset_files)
                    if source_grdecl is None:
                        st.error(f"Could not identify the source GRDECL for {returned_file.name}.")
                        continue
                    # Prefer exact CellIndex mapping for current T>Map returns.
                    # Older real exports without CellIndex use sparse X/Y/Z
                    # vertical interpolation.
                    reduced_file = "_control_" in returned_file.name or not tmap_pointset_has_column(returned_file, "CellIndex")
                    extra = ["--single-grdecl", str(source_grdecl), "--single-pointset", str(returned_file)]
                    if reduced_file:
                        extra.extend(["--vertical-interpolate", "--property", "Facies"])
                    commands.extend([[*command, *extra, *include_args] for command in append_commands_for_project(approach, source_grdecl_dir)])
                if commands:
                    run_commands(commands)
        if approach_name == "Best-fit model" and tmap_file and (is_reduced or "_tmap_real" in tmap_file.name):
            st.info(
                "This T>Map dataset has lower point resolution than the original GRDECL. When appended, each returned numerical property is matched by X/Y and linearly interpolated vertically within its I/J column to populate original GRDECL cells between returned points. "
                "The returned `Facies` and `point_id` columns are not written back, so the original GRDECL facies remain unchanged. "
                f"The augmented GRDECL is written to: {display_path(approach['augmented_dir'])}"
            )
        appended_coverage_files = files_in(approach["augmented_dir"], ("*.grdecl", "*.GRDECL"))
        if appended_coverage_files:
            st.divider()
            st.subheader("Appended GRDECL coverage")
            coverage_file = st.selectbox(
                "Appended GRDECL to count",
                appended_coverage_files,
                format_func=lambda path: path.name,
                key="tab2_coverage_grdecl",
            )
            dims = grdecl_dimensions(str(coverage_file))
            facies_coverage_property, diagenetic_coverage_property = coverage_properties(coverage_file)
            metrics = st.columns(3)
            metrics[0].metric("Grid cells", f"{dims[0] * dims[1] * dims[2]:,}")
            if facies_coverage_property and diagenetic_coverage_property:
                defined_facies, defined_diagenetic = grdecl_coverage_counts(
                    str(coverage_file), facies_coverage_property, diagenetic_coverage_property
                )
                metrics[1].metric("Defined facies", f"{defined_facies:,}")
                metrics[2].metric("Diagenetic cells", f"{defined_diagenetic:,}")
                st.caption(f"Diagenetic coverage is counted from `{diagenetic_coverage_property}`. `-77777` indicates a facies excluded from T>Map modelling.")
            else:
                metrics[1].metric("Defined facies", "—")
                metrics[2].metric("Diagenetic cells", "—")
                st.caption("No facies/T>Map property pair could be identified for this GRDECL.")
    with right:
        augmented_files = files_in(approach["augmented_dir"], ("*.grdecl", "*.GRDECL"))
        viewer_options: list[str] = []
        if pointset_files:
            viewer_options.append("Original 3D point set")
        if tmap_file:
            viewer_options.append("Appended 3D point set")
        if augmented_files:
            viewer_options.append("Appended GRDECL")
        if viewer_options:
            default_view = "Appended 3D point set" if "Appended 3D point set" in viewer_options else viewer_options[0]
            viewer_source = st.radio(
                "Viewer data",
                viewer_options,
                index=viewer_options.index(default_view),
                horizontal=True,
                key="tab2_viewer_source",
            )
        else:
            viewer_source = None
            st.info("Create source 3D point sets in FSM → FDM, then this stage can display original, appended, and augmented data.")
        if viewer_source == "Original 3D point set":
            pointset_file = st.selectbox(
                "Original 3D point set",
                pointset_files,
                format_func=lambda path: path.name,
                key="tab2_original_pointset_view",
            )
            pointset_df = enrich_ijk_from_cell_index(pointset_dataframe(str(pointset_file), max_rows), source_grdecl_dir)
            visualization_panel(
                pointset_df,
                "tab2_original_points",
                "Facies" if "Facies" in pointset_df.columns else None,
                is_grdecl="K" in pointset_df.columns,
            )
        elif viewer_source == "Appended 3D point set" and tmap_file:
            tmap_df = enrich_ijk_from_cell_index(pointset_dataframe(str(tmap_file), max_rows), source_grdecl_dir)
            default = "total_porosity_mean" if "total_porosity_mean" in tmap_df.columns else None
            visualization_panel(tmap_df, "tab2_appended_points", default, is_grdecl="K" in tmap_df.columns)
        elif viewer_source == "Appended GRDECL":
            augmented_file = st.selectbox(
                "Appended GRDECL",
                augmented_files,
                format_func=lambda path: path.name,
                key="tab2_appended_grdecl_file",
            )
            augmented_df = augmented_grdecl_dataframe(str(augmented_file), max_rows)
            default = "Facies" if "Facies" in augmented_df.columns else "FACIES" if "FACIES" in augmented_df.columns else None
            visualization_panel(augmented_df, "tab2_appended_grdecl", default, is_grdecl=True, grdecl_path=str(augmented_file))

with tab3:
    # The merged FDM Append & View tab presents coverage immediately after the
    # append action, next to the returned-file workflow above.
    pass

with tab4:
    left, right = st.columns([0.42, 0.58])
    with left:
        st.subheader("FFM Geomech preparation")
        input_stage = "source GRDECL" if active_profile == "Crystalline rocks" else "diagenesis-enriched GRDECL"
        if active_profile == "Carbonates":
            st.caption("Input: a DionisosFlow source GRDECL or a GOLEM/PHREEQC re-appended GRDECL. Action: assign geomechanical properties. Output: DFM-ready GRDECL.")
        else:
            st.caption(f"Input: {input_stage}. Action: assign geomechanical properties. Output: DFM-ready GRDECL.")
        st.caption("Empirical porosity/cement/stress estimates for DFN preparation. Calibrate all values against laboratory, log, or rock-physics constraints before use.")
        geomech_approach_name, geomech_approach = approach_selector("tab4_approach")
        geomech_input_dir = geomech_approach["augmented_dir"]
        if active_profile == "Carbonates":
            result_dir = geomech_approach["augmented_dir"]
            source_dir = ACTIVE_SOURCE_GRDECL_DIR
            available_sources = {"DionisosFlow/source GRDECL": source_dir}
            if files_in(result_dir, ("*.grdecl", "*.GRDECL")):
                available_sources["GOLEM/PHREEQC re-appended GRDECL"] = result_dir
            input_stage = st.radio(
                "Geomechanics input source",
                list(available_sources),
                horizontal=True,
                key="tab4_carbonate_input_stage",
            )
            geomech_input_dir = available_sources[input_stage]
            st.caption(
                "Use a DionisosFlow GRDECL directly when it already contains porosity or mineral/cement properties. "
                "Switch to the re-appended option once GOLEM/PHREEQC results are available."
            )
        geomech_input = file_selector(input_stage, geomech_input_dir, ("*.grdecl", "*.GRDECL"), "tab4_input")
        if geomech_input:
            classification_label = "Rock type" if active_profile == "Crystalline rocks" else "Carbonate facies" if active_profile == "Carbonates" else "Facies"
            geomech_targets = [geomech_input]
            if active_profile in {"MVP", "Siliciclastics"} and geomech_approach_name != "Best-fit model":
                available_geomech_models = files_in(geomech_input_dir, ("*.grdecl", "*.GRDECL"))
                geomech_targets = st.multiselect(
                    "Multi-realization GRDECLs to prepare for DFN",
                    available_geomech_models,
                    default=available_geomech_models,
                    format_func=lambda path: path.name,
                    key="tab4_geomech_targets",
                    help="All augmented realizations are selected by default. You may select a smaller subset.",
                )
                st.caption(f"The same {classification_label.lower()} configuration and selected input properties will be applied to {len(geomech_targets)} selected realization(s).")
            properties = grdecl_property_keywords(geomech_input)
            facies_property, porosity_property, cement_property, stress_property = geomechanics_property_selectors(
                properties, classification_label, active_profile
            )
            output_dir = geomech_approach["dfn_dir"]
            st.subheader("Model used and parameter guidance")
            st.latex(r"E=E_{ref}(1-\phi/\phi_c)^n(1+a_cC)(1+a_\sigma\sigma/\sigma_{ref})")
            st.latex(r"G=E/[2(1+\nu)],\qquad K=E/[3(1-2\nu)]")
            if active_profile == "Crystalline rocks":
                st.markdown("""**Rock-type assignment**

- **Crystalline compact framework:** a critical-porosity starting curve for low-porosity crystalline rock. It is suitable as an initial assignment for granite, gneiss, and contact-metamorphic rocks, then calibrated by rock type.
- **Shear zones or weathered rock:** assign a lower Young reference modulus and cohesion, and a higher porosity or explicit depth-compaction fallback where justified.

The starting values are deliberately transparent rather than a substitute for laboratory data: `Young ref 60 GPa`, Poisson's ratio `0.24`, friction `0.65`, cohesion `10 MPa`, tensile strength `5 MPa`, and fracture energy `100 J/m²`. Adjust each rock type to available core, log, or regional geomechanical constraints.""")
            elif active_profile == "Carbonates":
                st.markdown("""**Carbonate-facies assignment**

- **Carbonate/chalk, critical porosity:** the default, using selected porosity and an optional mineral/cement multiplier. This is the appropriate starting model for reef framework, grainstone, packstone, wackestone, and chalk-like facies.
- **Mineral or cement property:** select a re-appended GOLEM/PHREEQC field such as calcite, dolomite, anhydrite, gypsum, or cement only if its value is a meaningful fraction or percentage for the chosen multiplier. It should be calibrated before use.
- **Porosity and effective stress:** use the re-appended diagenesis porosity and any available effective-stress property. The optional fallback is deliberately provisional and is not a substitute for the reaction model.

Without Vp/Vs, Poisson's ratio is assigned rather than calculated. Initial carbonate/chalk range: `0.20–0.35`. `Young ref`, friction, cohesion, tensile strength, and fracture energy remain user-assigned DFM inputs and should be calibrated to the carbonate rock type and degree of cementation.""")
            else:
                st.markdown("""**Formula options**

- **Clean sandstone, critical porosity:** optional quartz/total-cement and effective-stress multipliers.
- **Shale, porosity and stress:** porosity/effective-stress trend; cement is not applied.
- **Carbonate/chalk, critical porosity:** critical-porosity form with independently calibrated facies values.

Without Vp/Vs, Poisson’s ratio is assigned, not calculated. Initial ranges: clean sandstone `0.15–0.30`, shale `0.25–0.40`, carbonate `0.20–0.35`, chalk `0.25–0.35`.

            `Young ref` is the zero-porosity reference modulus. Defaults are critical porosity `0.40`, porosity exponent `2`, cement factor `2`, and stress factor `0`. Friction, cohesion, tensile strength, and fracture energy are user-assigned DFM inputs, not inferred from T>Map.""")
            codes = sorted({int(float(value)) for value in expand_values(tokenize_grdecl(geomech_input, {facies_property})[facies_property])})
            # The configuration belongs to the DFN-preparation output step,
            # alongside the resulting GRDECLs, rather than the augmented
            # T>Map input folder. Read the legacy location once if present so
            # existing calibrations are not lost during this transition.
            config_path = output_dir / "geomechanics_config.json"
            legacy_config_path = geomech_input.parent / "geomechanics_config.json"
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                try:
                    config = json.loads(legacy_config_path.read_text(encoding="utf-8"))
                    st.caption(f"Loaded existing configuration from {display_path(legacy_config_path)}. Saving or writing will place it in {display_path(config_path)}.")
                except (OSError, json.JSONDecodeError):
                    config = {}
            defaults = {
                "critical_porosity": 0.40, "porosity_exponent": 2.0, "cement_factor": 2.0,
                "stress_factor": 0.0, "stress_reference_mpa": 30.0, "minimum_young_gpa": 0.01,
                "fallback_porosity_surface": 0.55,
                "fallback_compaction_coefficient_per_m": 0.00046,
                "fallback_effective_stress_gradient_mpa_per_m": 0.015,
                "fallback_depth_datum_m": 0.0,
            }
            shale_fallback, fallback_values = shale_fallback_controls(
                config.get("defaults", {}), defaults,
                crystalline=active_profile == "Crystalline rocks",
                carbonate=active_profile == "Carbonates",
            )
            defaults.update(fallback_values)
            write_dipazimuth = st.checkbox(
                "Add locally smoothed DIPAZIMUTH from the model-top horizon",
                value=True,
                key="tab4_write_dipazimuth",
                help="Fits a local smoothed depth plane around every I/J position on the top K layer, then writes its local down-dip azimuth in degrees clockwise from North through the corresponding column. This follows broad horizon contours while reducing cell-scale noise.",
            )
            if write_dipazimuth:
                dipazimuth_smoothing_cells = st.slider(
                    "DIPAZIMUTH smoothing radius (I/J cells)",
                    min_value=1,
                    max_value=10,
                    value=3,
                    help="The local neighbourhood used to estimate horizon dip. Increase it for broader, smoother structural trends; decrease it to follow more local contour changes.",
                    key="tab4_dipazimuth_smoothing_cells",
                )
                st.caption("`DIPAZIMUTH` follows the locally smoothed model-top-horizon contours and is written in degrees clockwise from North. Michael's example property values of 65–115 confirm that GRDECL property values are degrees, despite its configuration comment mentioning radians.")
            facies_names = read_facies_names()
            tmap_coverage = (
                {} if active_profile == "Crystalline rocks"
                else facies_tmap_coverage(str(geomech_input), facies_property, porosity_property)
            )
            rows = []
            for code in codes:
                p = {**defaults, **config.get("defaults", {}), **config.get("facies", {}).get(str(code), {})}
                default_formula = (
                    "crystalline_compact_framework" if active_profile == "Crystalline rocks"
                    else "carbonate_chalk_critical_porosity" if active_profile == "Carbonates"
                    else "clean_sandstone_critical_porosity"
                )
                formula = p.get("formula", default_formula)
                _, tmap_cells = tmap_coverage.get(code, (0, 0))
                tmap_status = "T>Map" if tmap_cells else "No T>Map"
                row = {"Facies": code, "Facies name": facies_names.get(code, f"{classification_label} {code}"), "Formula": formula, "Young ref (GPa)": p.get("young_reference_gpa", 60.0 if active_profile == "Crystalline rocks" else 30.0), "Poisson": p.get("poissons_ratio", 0.24 if active_profile == "Crystalline rocks" else 0.25), "Friction": p.get("friction_coefficient", 0.65 if active_profile == "Crystalline rocks" else 0.6), "Cohesion (MPa)": p.get("cohesion_mpa", 10.0 if active_profile == "Crystalline rocks" else 5.0), "Tensile (MPa)": p.get("tensile_strength_mpa", 5.0 if active_profile == "Crystalline rocks" else 2.0), "Fracture energy (J/m²)": p.get("fracture_energy_j_m2", 100.0 if active_profile == "Crystalline rocks" else 50.0)}
                if active_profile == "Carbonates":
                    row["Diagenesis data"] = "GOLEM/PHREEQC" if tmap_cells else "No diagenesis data"
                elif active_profile != "Crystalline rocks":
                    row["T>Map data"] = tmap_status
                rows.append(row)
            st.session_state["tab4_geomech_row_codes"] = {
                index: int(row["Facies"]) for index, row in enumerate(rows)
            }
            saved_formulas = st.session_state.setdefault("tab4_geomech_formulas", {})
            for row in rows:
                saved_formulas.setdefault(str(int(row["Facies"])), str(row["Formula"]))
            edited = geomechanics_facies_editor(rows, classification_label)
            if active_profile == "Crystalline rocks":
                st.caption(f"Rock types are read from `{facies_property}` and their porosity from `{porosity_property}`. The selected formula and parameters are written for every rock type into the DFM-preparation GRDECL.")
            elif active_profile == "Carbonates":
                st.caption(f"Carbonate facies are read from `{facies_property}`. `{porosity_property}` and the optional mineral/cement property are expected to come from a GOLEM/PHREEQC result re-appended to the GRDECL; the source-grid values are used provisionally until that step is available.")
            else:
                st.caption(f"`T>Map data` is read from `{porosity_property}` in the selected GRDECL. Use `No T>Map facies` to identify where the shale depth-compaction fallback is relevant.")
            edited_config = {"defaults": defaults, "facies": {str(int(row["Facies"])): {"formula": str(row["Formula"]), "young_reference_gpa": float(row["Young ref (GPa)"]), "poissons_ratio": float(row["Poisson"]), "friction_coefficient": float(row["Friction"]), "cohesion_mpa": float(row["Cohesion (MPa)"]), "tensile_strength_mpa": float(row["Tensile (MPa)"]), "fracture_energy_j_m2": float(row["Fracture energy (J/m²)"])} for _, row in edited.iterrows()}}
            write_label = (
                "Write geomechanical DFN-preparation GRDECL"
                if geomech_approach_name == "Best-fit model"
                else f"Write DFN-preparation GRDECLs for {len(geomech_targets)} selected realization(s)"
            )
            geomechanics_actions(
                str(config_path),
                json.dumps(edited_config, indent=2) + "\n",
                [str(target) for target in geomech_targets],
                str(output_dir),
                write_label,
            )
            generated_targets = [
                output_dir / f"{target.stem}_with_geomechanical_properties.grdecl"
                for target in geomech_targets
            ]
            existing_generated = [path for path in generated_targets if path.exists()]
            if existing_generated:
                st.divider()
                st.caption(f"{len(existing_generated)} generated DFN-preparation GRDECL(s) match the currently selected model(s).")
                confirm_remove_dfn = st.checkbox(
                    "Confirm removal of the selected generated DFN-preparation GRDECL(s)",
                    key="tab4_confirm_remove_dfn",
                    help="This removes only the generated files in the DFN-preparation output folder. The geomechanics configuration in that same folder is retained.",
                )
                if st.button("Remove selected DFN-preparation data", key="tab4_remove_dfn", disabled=not confirm_remove_dfn):
                    removed, failures = [], []
                    for path in existing_generated:
                        try:
                            path.unlink()
                            removed.append(path.name)
                        except OSError as exc:
                            failures.append(f"{path.name}: {exc}")
                    augmented_grdecl_dataframe.clear()
                    if removed:
                        st.success(f"Removed {len(removed)} generated DFN-preparation GRDECL(s).")
                    if failures:
                        st.error("Could not remove:\n" + "\n".join(failures))
                    if removed and not failures:
                        st.rerun()
    with right:
        if geomech_input:
            output_dir = geomech_approach["dfn_dir"]
            dfn_files = files_in(output_dir, ("*.grdecl", "*.GRDECL"))
            input_view_label = "Input GRDECL" if active_profile in {"Carbonates", "Crystalline rocks"} else "Input augmented GRDECL"
            viewer_options = [input_view_label] + (["DFN-preparation GRDECL"] if dfn_files else [])
            viewer_choice = st.radio("Viewer data", viewer_options, horizontal=True, key="tab4_viewer_choice")
            viewer_file = st.selectbox("DFN-preparation file", dfn_files, format_func=lambda path: path.name, key="tab4_dfn_file") if viewer_choice == "DFN-preparation GRDECL" else geomech_input
            viewer_df = augmented_grdecl_dataframe(str(viewer_file), max_rows)
            default_property = preferred_classification_property(list(viewer_df.columns))
            visualization_panel(viewer_df, "tab4_viewer", default_property, is_grdecl=True, grdecl_path=str(viewer_file))
            if viewer_choice == "DFN-preparation GRDECL":
                st.caption("Inspect `DFNPorosity`, `DFNEffectiveStress_MPa`, and `DIPAZIMUTH` to verify the values passed to DFN Generator. `YoungsModulus_Pa` is written in the units required by the executable; `DIPAZIMUTH` is degrees clockwise from North.")

with tab5:
    left, right = st.columns([0.42, 0.58])
    with left:
        st.subheader("FFM Run DFM")
        st.caption("Input: DFN-prepared GRDECLs. Action: write Michael's GRDECL configuration and launch the executable in the background. Output: staged fracture GRDECLs, FAB and ASCII DFNs.")
        selected_dfn_inputs: list[Path] = []
        input_mode = st.radio("DFN input", ["Project DFN-prepared GRDECL", "Michael's supplied demo grid"], horizontal=True, key="tab5_input_mode")
        demo_mode = input_mode == "Michael's supplied demo grid"
        if demo_mode:
            dfn_approach_name = "Michael demo grid"
            dfn_approach = None
            if not DFN_DEMO_GRID.exists() or not DFN_DEMO_CONFIG.exists():
                st.error("Michael's demo grid or configuration file is not available in `reference_examples/michael_dfn_example`.")
            else:
                selected_dfn_inputs = [DFN_DEMO_GRID]
                demo_properties = grdecl_property_keywords(DFN_DEMO_GRID)
                st.caption(f"Demo grid: `{DFN_DEMO_GRID.name}`. Configuration: `{DFN_DEMO_CONFIG.name}`.")
                if st.button("Load default settings from Michael's example file", key="tab5_load_demo_config"):
                    load_dfn_configuration_into_controls(DFN_DEMO_CONFIG, demo_properties)
                    st.session_state["tab5_demo_configuration_loaded"] = True
                    st.rerun()
                if st.session_state.get("tab5_demo_configuration_loaded"):
                    st.success("Michael's active configuration values are loaded below. You can adjust them before launching a separate reproducible demo run.")
                st.caption("The supplied completed demo output can also be inspected in the results panel.")
        else:
            dfn_approach_name, dfn_approach = approach_selector("tab5_approach")
            dfn_inputs = files_in(dfn_approach["dfn_dir"], ("*.grdecl", "*.GRDECL"))
            if not dfn_inputs:
                st.info("No DFN-prepared GRDECLs are available for this approach yet. Create them in Tab 4 first.")
            else:
                selected_dfn_inputs = st.multiselect(
                    "DFN-prepared GRDECLs to run",
                    dfn_inputs,
                    default=dfn_inputs if dfn_approach_name != "Best-fit model" else [dfn_inputs[0]],
                    format_func=lambda path: path.name,
                    key="tab5_dfn_inputs",
                )
                st.caption(f"Selected input folder: {display_path(dfn_approach['dfn_dir'])}")
                st.caption(f"{len(selected_dfn_inputs)} model(s) selected. Each model receives a reproducible, self-contained run folder.")
        executable_path = Path(st.text_input("DFM Generator executable", value=str(DEFAULT_DFN_EXECUTABLE), key="tab5_executable_20260807"))
        st.caption("DFM Generator is an external Apache-2.0 executable, temporarily bundled for this demonstrator. See THIRD_PARTY_NOTICES.md; future releases will be available from https://github.com/JointFlow/DFMGenerator.")
        if not executable_path.exists():
            st.warning("Executable not found at this location. Select Michael's `DFMGenerator_GRDECL.exe` before launching.")
        if selected_dfn_inputs:
            selected_input = selected_dfn_inputs[0]
            dims = grdecl_dimensions(str(selected_input))
            properties = grdecl_property_keywords(selected_input)
            # Initialise the Tab 5 selectors from the actual GRDECL keywords.
            # GRDECL keywords are uppercase, whereas the Tab 4 display names are
            # mixed case; this helper resolves that difference once per session.
            initialize_tab5_property_defaults(properties)
            st.caption(f"First selected model: `{selected_input.name}` ({dims[0]} × {dims[1]} × {dims[2]} cells).")
            if not demo_mode and DFN_DEMO_CONFIG.exists():
                if st.button("Load default settings from Michael's example file", key="tab5_load_reference_config"):
                    load_dfn_configuration_into_controls(DFN_DEMO_CONFIG, properties)
                    st.session_state["tab5_allow_cropped_intermediates"] = True
                    st.success("Michael's numerical reference settings are loaded. Local GRDECL property mappings were retained where the reference uses placeholders, including the 1,000-timestep growth limit.")
                    st.rerun()
            estimate_run_root = ACTIVE_PROJECT_DATA_DIR / "DFN demo runs" if demo_mode else Path(dfn_approach["dfn_run_dir"])
            crop_run, crop_i, crop_j, crop_k, crop_cells = dfn_crop_controls(dims, str(selected_input), str(estimate_run_root))

            settings_form = st.form("tab5_dfn_settings_form", border=False)
            # Enter the form before creating the tab containers so all their
            # widgets defer their values until Apply or Generate is pressed.
            settings_form.__enter__()
            settings_tabs = st.tabs(["Main settings", "Mechanical properties", "Microfractures", "Stress state", "Outputs", "Control parameters", "Unconfined fractures"])
            settings: dict[str, object] = {}
            with settings_tabs[0]:
                st.caption("One static deformation episode is configured here. Angles are shown in degrees and written in radians as required by the executable.")
                main_columns = st.columns(3)
                settings["time_units"] = main_columns[0].selectbox("Time units", ["ma", "year", "second"], key="tab5_time_units")
                settings["horizontal_upscale"] = main_columns[1].number_input("Horizontal upscaling factor", min_value=1, value=1, step=1, key="tab5_hup")
                settings["vertical_upscale"] = main_columns[2].number_input("Vertical upscaling factor (-1 = one amalgamated layer)", min_value=-1, value=-1, step=1, key="tab5_vup")
                deformation = st.columns(3)
                settings["ehmin_azimuth_deg"] = deformation[0].number_input("Minimum-strain azimuth (° clockwise from North)", value=0.0, key="tab5_azimuth")
                settings["ehmin_rate"] = deformation[1].number_input("Minimum horizontal strain rate", value=-0.0001, format="%.6g", key="tab5_ehmin")
                settings["ehmax_rate"] = deformation[2].number_input("Maximum horizontal strain rate", value=0.0, format="%.6g", key="tab5_ehmax")
                azimuth_options = ["Use default", *properties]
                settings["ehmin_azimuth_property"] = st.selectbox(
                    "Minimum-strain azimuth property (degrees)",
                    azimuth_options,
                    key="tab5_azimuth_property",
                    help="Select Tab 4's planar-smoothed DIPAZIMUTH field to use a grid-varying direction. Dashboard values are degrees; the temporary DFN handoff converts them to radians. If no property is selected, the scalar value above is written in radians.",
                )
                loads = st.columns(3)
                settings["episode_duration"] = loads[0].number_input("Episode duration (-1 = until saturation)", value=-1.0, key="tab5_duration")
                settings["overpressure_bar_ma"] = loads[1].number_input("Overpressure rate (bar/Ma)", value=0.0, key="tab5_overpressure")
                settings["temperature_change_k_ma"] = loads[2].number_input("Temperature change (K/Ma)", value=0.0, key="tab5_temperature")
                settings["uplift_rate_m_ma"] = st.number_input("Uplift/erosion rate (m/Ma)", value=0.0, key="tab5_uplift")
                settings["stress_arching_factor"] = st.slider("Stress arching factor", 0.0, 1.0, 0.0, key="tab5_arching")
            with settings_tabs[1]:
                st.caption("Choose a GRDECL property where available; otherwise the supplied default value is written. Young's modulus must be in Pa when a property is selected.")
                property_options = ["Use default", *properties]
                mechanical = st.columns(2)
                settings["youngs_property"] = mechanical[0].selectbox("Young's modulus property (Pa)", property_options, key="tab5_young_prop")
                settings["youngs_default_gpa"] = mechanical[1].number_input("Default Young's modulus (GPa)", min_value=0.01, value=10.0, key="tab5_young_default")
                settings["poisson_property"] = mechanical[0].selectbox("Poisson's ratio property", property_options, key="tab5_poisson_prop")
                settings["poisson_default"] = mechanical[1].number_input("Default Poisson's ratio", min_value=0.001, max_value=0.499, value=0.25, key="tab5_poisson_default")
                settings["porosity_property"] = mechanical[0].selectbox("Host-rock porosity property", property_options, key="tab5_porosity_prop")
                settings["porosity_default"] = mechanical[1].number_input("Default host-rock porosity", min_value=0.0, max_value=0.9, value=0.2, key="tab5_porosity_default")
                settings["friction_property"] = mechanical[0].selectbox("Friction coefficient property", property_options, key="tab5_friction_prop")
                settings["friction_default"] = mechanical[1].number_input("Default friction coefficient", min_value=0.0, max_value=2.0, value=0.5, key="tab5_friction_default")
                settings["fracture_energy_property"] = mechanical[0].selectbox("Crack surface-energy property", property_options, key="tab5_energy_prop")
                settings["fracture_energy_default"] = mechanical[1].number_input("Default crack surface energy (J/m²)", min_value=0.1, value=1000.0, key="tab5_energy_default")
                settings["biot_default"] = st.number_input("Biot coefficient", min_value=0.0, max_value=1.5, value=1.0, key="tab5_biot")
                settings["thermal_expansion_default"] = st.number_input("Thermal expansion coefficient (/K)", min_value=0.0, value=4e-5, format="%.2e", key="tab5_thermal")
                settings["rock_relaxation"] = 0.0
                settings["fracture_relaxation"] = 0.0
                settings["average_mechanical"] = st.checkbox("Average mechanical properties across K layers", value=True, key="tab5_average_mech")
                st.info("Tab 4 writes only the current executable inputs: `DFNPorosity`, `DFNEffectiveStress_MPa`, `YoungsModulus_Pa`, `PoissonsRatio`, `FrictionCoefficient`, and `FractureEnergy_J_m2`, plus `GeomechSource` to identify T>Map versus shale-fallback cells.")
            with settings_tabs[2]:
                micro = st.columns(2)
                settings["microfracture_distribution"] = micro[0].selectbox("Initial distribution", ["PowerLaw", "Exponential", "LogNormal"], key="tab5_micro_distribution")
                settings["microfracture_density"] = micro[1].number_input("Initial microfracture density", min_value=0.0, value=0.001, format="%.6g", key="tab5_micro_density")
                settings["microfracture_size_distribution"] = micro[0].number_input("Size-distribution coefficient", min_value=0.01, value=3.0, key="tab5_micro_size")
                settings["microfracture_median_radius"] = micro[1].number_input("Median initial radius (-1 = layer thickness / 20)", value=-1.0, key="tab5_micro_radius")
                settings["subcritical_index"] = micro[0].number_input("Subcritical propagation index", min_value=0.0, value=10.0, key="tab5_subcritical")
                settings["critical_rate"] = micro[1].number_input("Critical propagation rate (m/s)", min_value=0.0, value=2000.0, key="tab5_critical_rate")
            with settings_tabs[3]:
                stress = st.columns(2)
                settings["stress_distribution"] = stress[0].selectbox("Stress distribution", ["StressShadow", "EvenlyDistributedStress"], key="tab5_stress_distribution")
                settings["depth_at_deformation"] = stress[1].number_input("Depth at deformation (-1 = current depth)", value=-1.0, key="tab5_depth_deformation")
                settings["overburden_density"] = stress[0].number_input("Mean overburden density (kg/m³)", min_value=0.0, value=2250.0, key="tab5_overburden")
                settings["fluid_density"] = stress[1].number_input("Fluid density (kg/m³)", min_value=0.0, value=1000.0, key="tab5_fluid_density")
                settings["initial_overpressure_bar"] = stress[0].number_input("Initial fluid overpressure (bar)", value=0.0, key="tab5_initial_overpressure")
                settings["geothermal_gradient_c_km"] = stress[1].number_input("Geothermal gradient (°C/km)", min_value=0.0, value=30.0, key="tab5_gradient")
                settings["initial_stress_relaxation"] = st.slider("Initial stress relaxation", -1.0, 1.0, 0.5, key="tab5_initial_relaxation")
                settings["average_stress"] = st.checkbox("Average stress/strain data across K layers", value=False, key="tab5_average_stress")
            with settings_tabs[4]:
                output = st.columns(2)
                settings["generate_explicit"] = output[0].checkbox("Generate explicit DFN", value=True, key="tab5_explicit")
                settings["intermediate_outputs"] = output[1].number_input("Intermediate outputs", min_value=0, max_value=20, value=0, step=1, key="tab5_intermediates")
                settings["allow_cropped_intermediate_outputs"] = st.checkbox(
                    "Allow multi-timestep cropped tests and intermediate outputs",
                    value=False,
                    key="tab5_allow_cropped_intermediates",
                    help="Keeps the selected Maximum timesteps and intermediate outputs for a crop. Keep this off for a basic compatibility test: the current executable can crash when a crop produces no explicit fractures in an intermediate stage.",
                )
                settings["intermediate_control"] = output[0].selectbox("Output interval", ["EqualTime", "EqualArea", "SpecifiedTime"], key="tab5_interval")
                settings["write_dfn_ascii"] = output[1].checkbox("Write explicit ASCII DFN", value=False, key="tab5_ascii")
                settings["write_fab"] = output[0].checkbox("Write FAB files", value=True, key="tab5_fab")
                settings["write_implicit_files"] = output[1].checkbox("Write detailed implicit files", value=False, key="tab5_implicit")
                settings["output_fracture_sets"] = output[0].checkbox("Output each fracture set", value=True, key="tab5_sets")
                settings["output_fracture_porosity"] = output[1].checkbox("Output fracture porosity", value=True, key="tab5_porosity_out")
                settings["output_fracture_permeability"] = output[0].checkbox("Output permeability tensor", value=True, key="tab5_perm_out")
                settings["populate_empty"] = output[1].checkbox("Populate cells with no fractures", value=True, key="tab5_empty")
                settings["aperture_control"] = output[0].selectbox("Fracture aperture control", ["Uniform", "SizeDependent", "Dynamic", "BartonBandis"], key="tab5_aperture")
                settings["uniform_aperture_m"] = output[1].number_input("Uniform aperture (m)", min_value=0.0, value=0.0005, format="%.6f", key="tab5_aperture_value")
            with settings_tabs[5]:
                control = st.columns(2)
                settings["fracture_sets"] = control[0].number_input("Layer-bound fracture sets", min_value=1, max_value=6, value=2, step=1, key="tab5_fracture_sets")
                settings["max_timesteps"] = control[1].number_input("Maximum timesteps", min_value=1, value=1000, step=1, key="tab5_max_timesteps")
                settings["mode1_only"] = control[0].checkbox("Mode 1 only", value=False, key="tab5_mode1")
                settings["mode2_only"] = control[1].checkbox("Mode 2 only", value=False, key="tab5_mode2")
                settings["max_timestep_duration"] = control[0].number_input("Maximum timestep duration (-1 = automatic)", value=-1.0, key="tab5_max_timestep_duration")
                settings["max_mfp33_increase"] = control[1].number_input("Maximum MFP33 increase/timestep", min_value=0.00001, value=0.005, format="%.5f", key="tab5_mfp33")
                settings["radius_bins"] = control[0].number_input("Radius integration bins", min_value=2, value=10, step=1, key="tab5_radius_bins")
                settings["minimum_clear_zone"] = control[1].number_input("Minimum clear-zone volume ratio", min_value=0.0, max_value=1.0, value=0.01, key="tab5_clear_zone")
                settings["crop_boundary"] = control[0].checkbox("Crop fractures at outer boundary", value=True, key="tab5_crop_boundary")
                settings["link_stress_shadows"] = control[1].checkbox("Create relay segments", value=False, key="tab5_relays")
                settings["max_consistency_angle_deg"] = control[0].number_input("Maximum consistency angle (°)", min_value=0.0, max_value=180.0, value=45.0, key="tab5_consistency")
                settings["minimum_layer_thickness"] = control[1].number_input("Minimum layer thickness (m)", min_value=0.0, value=0.0, key="tab5_layer_thickness")
                settings["max_fracture_patches"] = control[0].number_input("Maximum fracture patches/gridblock", min_value=1, value=1000, step=1, key="tab5_patches")
                settings["search_adjacent"] = control[1].selectbox("Search adjacent cells", ["Automatic", "All", "None"], key="tab5_search")
                settings["minimum_explicit_microfracture_radius"] = control[0].number_input("Minimum explicit microfracture radius (m; 0 excludes them)", min_value=0.0, value=0.10007, format="%.5f", key="tab5_explicit_radius")
                settings["microfracture_cornerpoints"] = control[1].number_input("Microfracture polygon cornerpoints", min_value=0, value=8, step=1, key="tab5_micro_corners")
            with settings_tabs[6]:
                unconfined = st.columns(2)
                settings["unconfined_strike_sets"] = unconfined[0].number_input("Unconfined strike sets", min_value=0, value=0, step=1, key="tab5_ucf_strike")
                settings["unconfined_dip_sets"] = unconfined[1].number_input("Unconfined dip sets", min_value=0, value=0, step=1, key="tab5_ucf_dip")
                settings["filter_by_property"] = unconfined[0].checkbox("Filter cells by property", value=False, key="tab5_filter")
                settings["filter_property"] = unconfined[1].selectbox("Filter property", ["Use default", *properties], key="tab5_filter_prop")
                settings["filter_min"] = unconfined[0].number_input("Filter minimum", value=0.0, key="tab5_filter_min")
                settings["filter_max"] = unconfined[1].number_input("Filter maximum", value=1.0, key="tab5_filter_max")

            launch_dfn = st.form_submit_button("Generate configuration and run DFN", type="primary", width="stretch", disabled=not executable_path.exists())
            settings_form.__exit__(None, None, None)

            st.caption("Settings remain pending while you edit, without reloading the dashboard. Generate configuration and run DFN submits and saves the current settings in one step. Runs are detached so Streamlit stays responsive.")
            if launch_dfn:
                run_root = (
                    ACTIVE_PROJECT_DATA_DIR / "DFN demo runs"
                    if demo_mode else Path(dfn_approach["dfn_run_dir"])
                )
                run_settings = dict(settings)
                # The current executable throws a NullReferenceException while
                # creating later stages if a small cropped test generates zero
                # explicit fractures. Keep this smoke test to one final stage.
                # Full calibrated runs may use multiple timesteps and outputs.
                if crop_run:
                    safeguards: list[str] = []
                    if int(run_settings.get("intermediate_outputs", 0)) > 0 and not run_settings.get("allow_cropped_intermediate_outputs"):
                        run_settings["intermediate_outputs"] = 0
                        safeguards.append("intermediate outputs set to 0 (enable multi-timestep cropped tests under Outputs to keep them)")
                    if safeguards:
                        st.warning("Cropped test: " + "; ".join(safeguards) + ". This avoids the executable's empty-stage crash; full calibrated runs may enable them.")
                launched = []
                for number, input_grdecl in enumerate(selected_dfn_inputs, start=1):
                    source_dims = grdecl_dimensions(str(input_grdecl))
                    source_cells = int(np.prod(source_dims))
                    run_cells = crop_cells if crop_run else source_cells
                    run_id = dfn_run_name(input_grdecl, crop_run, run_cells, number)
                    run_dir = run_root / run_id
                    input_dir = run_dir / "input"
                    input_dir.mkdir(parents=True, exist_ok=False)
                    (run_dir / "run_status.json").write_text(json.dumps({"status": "preparing", "run_id": run_id}, indent=2) + "\n", encoding="utf-8")
                    # The current DFM executable has a legacy path-length
                    # limit. Every run folder is already unique, so a short
                    # internal name is both sufficient and reliable.
                    grid_path = input_dir / "grid.grdecl"
                    # The standalone reader expects Petrel-style map metadata.
                    # Preserve I/J/K geometry exactly.  DionisosFlow's
                    # I=1, J=MAX, K=MAX export is right-handed in MAPAXES
                    # coordinates, matching Michael's reference GRDECL. Its
                    # depths are already positive down, so neither J nor Z is
                    # re-indexed/inverted during the DFN hand-off.
                    crop_command = [sys.executable, str(SCRIPTS / "crop_grdecl.py"), str(input_grdecl), str(grid_path), "--i", str(crop_i[0]), str(crop_i[1]), "--j", str(crop_j[0]), str(crop_j[1]), "--k", str(crop_k[0]), str(crop_k[1]), "--dfn-minimal", "--dfn-petrel-style", "--dipazimuth-degrees-to-radians"]
                    crop_result = subprocess.run(crop_command, cwd=ROOT, capture_output=True, text=True, creationflags=WORKER_CREATION_FLAGS)
                    if crop_result.returncode != 0:
                        message = crop_result.stderr or crop_result.stdout or "Unknown hand-off preparation error"
                        (run_dir / "run_status.json").write_text(json.dumps({"status": "failed", "run_id": run_id, "stage": "prepare_dfn_input", "error": message}, indent=2) + "\n", encoding="utf-8")
                        st.error(f"Could not prepare {input_grdecl.name} for DFN Generator: {message}")
                        continue
                    config_path = run_dir / "dfn_generator_configuration.txt"
                    config_path.write_text(dfn_config_text(run_id, str(grid_path.relative_to(run_dir)).replace("\\", "/"), run_settings), encoding="utf-8")
                    # DFMGenerator_GRDECL writes into this relative folder but
                    # does not create it itself. Create it before launch so a
                    # completed calculation can persist GRDECL/FAB outputs.
                    (run_dir / f"{run_id}_output").mkdir(parents=True, exist_ok=True)
                    manifest = {"run_id": run_id, "approach": dfn_approach_name, "demo_mode": demo_mode, "source_grdecl": str(input_grdecl), "source_cells": source_cells, "run_cells": run_cells, "cropped": crop_run, "petrel_style_handoff": True, "dfn_orientation_transform": {"ijk": "preserved_from_source_grdecl", "depth": "preserved_positive_down", "dipazimuth": "degrees_to_radians"}, "run_grid": str(grid_path), "crop_ranges": {"I": crop_i, "J": crop_j, "K": crop_k}, "settings": run_settings, "executable": str(executable_path)}
                    (run_dir / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                    (run_dir / "run_status.json").write_text(json.dumps({"status": "queued", "run_id": run_id}, indent=2) + "\n", encoding="utf-8")
                    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
                    process = subprocess.Popen([sys.executable, str(SCRIPTS / "run_dfn_generator.py"), "--executable", str(executable_path), "--config", str(config_path), "--run-dir", str(run_dir)], cwd=run_dir, creationflags=flags)
                    status = dfn_run_status(run_dir)
                    status.update({"status": "running", "launcher_pid": process.pid})
                    (run_dir / "run_status.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
                    launched.append(run_id)
                if launched:
                    st.session_state["tab5_run_folder"] = run_root / launched[-1]
                    st.success(f"Launched {len(launched)} DFN run(s): {', '.join(launched)}. The status panel on the right now refreshes every 5 seconds and shows elapsed time plus the live executable log.")
    with right:
        st.subheader("FFM run status")
        result_source = st.radio("Run source", ["Dashboard run", "Michael's supplied demo output"], horizontal=True, key="tab5_result_source")
        if result_source == "Michael's supplied demo output":
            demo_results = files_in(DFN_DEMO_OUTPUT_DIR, ("*.GRDECL", "*.grdecl"))
            if not DFN_DEMO_GRID.exists() or not demo_results:
                st.info("No supplied demo GRDECL output was found yet. Run Michael's example, or select Dashboard run after launching a demo from the left.")
            else:
                st.success("The supplied demo run is available. Open Tab 6 to inspect its output GRDECL and properties.")
        else:
            run_root = (
                ACTIVE_PROJECT_DATA_DIR / "DFN demo runs"
                if demo_mode else Path(dfn_approach["dfn_run_dir"])
            )
            run_dirs = sorted([path for path in run_root.iterdir() if path.is_dir()], reverse=True) if run_root.exists() else []
            if st.button("Refresh run status", key="tab5_refresh"):
                st.rerun()
            if not run_dirs:
                st.info("No dashboard DFN runs exist yet. Generate a configuration on the left to create the first run folder.")
            else:
                selected_run = st.selectbox("Run folder", run_dirs, format_func=dfn_run_label, key="tab5_run_folder")
                status = dfn_run_status(selected_run)
                dfn_live_status_panel(str(selected_run))
                active_run = str(status.get("status", "unknown")).lower() in {"queued", "preparing", "running"}
                delete_confirmed = st.checkbox(
                    "I want to permanently delete this DFN run and its outputs",
                    key=f"tab5_delete_confirm_{selected_run.name}",
                    disabled=active_run,
                )
                if st.button(
                    "Delete selected DFN run",
                    key=f"tab5_delete_run_{selected_run.name}",
                    type="secondary",
                    disabled=active_run or not delete_confirmed,
                ):
                    deleted, message = delete_dfn_run(selected_run)
                    if deleted:
                        st.session_state.pop("tab5_run_folder", None)
                        st.rerun()
                    st.error(message)
                if active_run:
                    st.caption("Stop the active run before deleting its folder.")
                manifest_path = selected_run / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
                st.caption(f"Input grid: {display_path(Path(manifest.get('run_grid', selected_run)))}")
                if status.get("status") == "completed":
                    st.success("Run completed. Open Tab 6 to select and inspect its output GRDECL.")
        with st.expander("Executable integration notes for Michael", expanded=False):
            st.markdown("""The dashboard writes the same text configuration structure as the supplied `DFMGenerator_GRDECL_configuration.txt`, invokes `DFMGenerator_GRDECL.exe <configfilename>` through a detached Python runner, and preserves the input crop/copy, configuration, manifest, status and log together. Tab 4 supplies direct selectable GRDECL fields for Young's modulus in Pa, Poisson's ratio, friction and fracture energy. Dynamic stress loads, multiple deformation episodes, cleavages, and full unconfined-fracture settings remain future extensions pending calibration decisions.""")

with tab6:
    st.subheader("FFM View results")
    st.caption("Inspect staged DFN GRDECL output independently from the run controls. Continuous properties use their own valid data range, excluding no-value flags.")
    result_source = st.radio(
        "Result source",
        ["Project DFN run", "Dashboard-generated Michael demo run"],
        horizontal=True,
        key="tab6_result_source",
    )
    if result_source == "Dashboard-generated Michael demo run":
        review_approach_name = "Dashboard-generated Michael demo"
        run_root = ACTIVE_PROJECT_DATA_DIR / "DFN demo runs"
        result_key_prefix = "tab6_dashboard_demo"
    else:
        review_approach_name, review_approach = approach_selector("tab6_approach")
        run_root = Path(review_approach["dfn_run_dir"])
        result_key_prefix = "tab6_project"
    run_dirs = sorted([path for path in run_root.iterdir() if path.is_dir()], reverse=True) if run_root.exists() else []
    if not run_dirs:
        if result_source == "Dashboard-generated Michael demo run":
            st.info("No dashboard-generated Michael demo run is available yet. Create one in Tab 5, then return here to inspect its GRDECL and FAB outputs.")
        else:
            st.info(f"No DFN runs are available yet for {review_approach_name}.")
    else:
        selected_run = st.selectbox("DFN run folder", run_dirs, format_func=dfn_run_label, key=f"{result_key_prefix}_run_folder")
        status = dfn_run_status(selected_run)
        elapsed = dfn_elapsed_text(status)
        st.caption(f"Run status: {status.get('status', 'unknown')}{f' · elapsed {elapsed}' if elapsed else ''}")
        manifest_path = selected_run / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        result_folder = selected_run / f"{manifest.get('run_id', selected_run.name)}_output"
        result_files = files_in(result_folder, ("*.GRDECL", "*.grdecl"))
        if result_files and manifest.get("run_grid"):
            result_file = st.selectbox("DFN output GRDECL", result_files, format_func=lambda path: path.name, key=f"{result_key_prefix}_result_file")
            result_df = dfn_result_dataframe(str(manifest["run_grid"]), str(result_file), max_rows)
            visualization_panel(result_df, f"{result_key_prefix}_viewer", result_df.columns[-1] if len(result_df.columns) > 7 else None, is_grdecl=True, dynamic_continuous_scale=True, grdecl_path=str(manifest["run_grid"]))
            fab_fracture_viewer(files_in(result_folder, ("*.FAB", "*.fab")), f"{result_key_prefix}_fab")
        elif status.get("status") == "completed":
            st.warning("The run completed but no GRDECL result was found. Check the run log in Tab 5 and its output folder.")
            fab_fracture_viewer(files_in(result_folder, ("*.FAB", "*.fab")), f"{result_key_prefix}_fab")
        else:
            st.info("No result GRDECL is available yet. Monitor live execution in Tab 5.")
