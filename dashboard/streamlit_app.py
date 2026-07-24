from __future__ import annotations

import csv
import hashlib
import importlib
import re
import subprocess
import sys
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
SOURCE_GRDECL_DIR = ROOT / "input" / "source_grdecls_from_dionisosflow"

APPROACHES = {
    "Best-fit model": {
        "point_dir": ROOT / "outputs" / "Best-fit approach" / "01_3d_points_from_original_grdecls",
        "tmap_dir": ROOT / "outputs" / "Best-fit approach" / "02_3d_points_with_tmap_data",
        "augmented_dir": ROOT / "outputs" / "Best-fit approach" / "03_augmented_grdecls_with_tmap_data",
        "build_points": [["scripts/build_best_fit_grdecl_to_pointset.py"]],
        "generate_tmap": [["scripts/generate_synthetic_tmap_data.py", "--property-profile", "reservoir_quality"]],
        "append": [["scripts/append_best_fit_tmap_to_grdecls.py"]],
    },
    "Multi-realization union": {
        "point_dir": ROOT / "outputs" / "Multi-realization union approach" / "01_union_pointsets_by_facies",
        "tmap_dir": ROOT / "outputs" / "Multi-realization union approach" / "02_union_pointsets_with_tmap_data",
        "augmented_dir": ROOT / "outputs" / "Multi-realization union approach" / "03_augmented_grdecls_from_union_lookup",
        "build_points": [["scripts/build_multi_realizations_grdecls_to_union_pointsets.py"]],
        "generate_tmap": [[
            "scripts/generate_synthetic_tmap_data.py",
            "--source-dir",
            "outputs/Multi-realization union approach/01_union_pointsets_by_facies",
            "--output-dir",
            "outputs/Multi-realization union approach/02_union_pointsets_with_tmap_data",
            "--glob",
            "union_facies_*",
            "--property-profile",
            "reservoir_quality",
        ]],
        "append": [["scripts/append_multi_realizations_union_tmap_to_grdecls.py"]],
    },
    "Multi-realization control points": {
        "point_dir": ROOT / "outputs" / "Multi-realization control approach" / "01_control_pointsets_by_facies",
        "tmap_dir": ROOT / "outputs" / "Multi-realization control approach" / "02_control_pointsets_with_tmap_data",
        "augmented_dir": ROOT / "outputs" / "Multi-realization control approach" / "03_augmented_grdecls_from_control_interpolation",
        "build_points": [["scripts/build_multi_realizations_grdecls_to_control_pointsets.py"]],
        "generate_tmap": [[
            "scripts/generate_synthetic_tmap_data.py",
            "--source-dir",
            "outputs/Multi-realization control approach/01_control_pointsets_by_facies",
            "--output-dir",
            "outputs/Multi-realization control approach/02_control_pointsets_with_tmap_data",
            "--glob",
            "control_facies_*",
            "--property-profile",
            "reservoir_quality",
        ]],
        "append": [["scripts/append_multi_realizations_control_tmap_to_grdecls.py"]],
    },
    "Multi-realization Uber": {
        "point_dir": ROOT / "outputs" / "Multi-realization Uber approach" / "01_uber_pointsets_by_facies",
        "tmap_dir": ROOT / "outputs" / "Multi-realization Uber approach" / "02_uber_pointsets_with_tmap_data",
        "augmented_dir": ROOT / "outputs" / "Multi-realization Uber approach" / "03_augmented_grdecls_from_uber_lookup",
        "petrel_augmented_dir": ROOT / "outputs" / "Multi-realization Uber approach" / "04_petrel_standard_grdecls_from_uber_lookup",
        "build_points": [["scripts/build_multi_realizations_grdecls_to_uber_pointsets.py"]],
        "generate_tmap": [[
            "scripts/generate_synthetic_tmap_data.py",
            "--source-dir",
            "outputs/Multi-realization Uber approach/01_uber_pointsets_by_facies",
            "--output-dir",
            "outputs/Multi-realization Uber approach/02_uber_pointsets_with_tmap_data",
            "--glob",
            "uber_facies_*",
            "--property-profile",
            "reservoir_quality",
        ]],
        "append": [["scripts/append_multi_realizations_uber_tmap_to_grdecls.py"], ["scripts/write_petrel_standard_uber_grdecls.py"]],
    },
}


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
    """Return the facies code with its configured geological label, if known."""
    name = read_facies_names().get(category)
    return f"Facies {category} — {name}" if name else f"Facies {category}"


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
    """Check if a property should be treated as discrete facies."""
    if property_key.strip().upper() in {"FACIES", "FACIE", "FACIESID"}:
        finite = values[np.isfinite(values)]
        return finite.size > 0 and np.allclose(finite, np.round(finite))
    return False


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
        numeric_values = pd.to_numeric(df[color_column], errors="coerce")
        logarithmic = "perm" in color_column.lower()
        if logarithmic:
            numeric_values = np.log10(numeric_values.clip(lower=1e-12))
        fixed_poro_scale = "porosity" in color_column.lower() or color_column.lower().startswith("poro")
        low, high = (0.0, 0.4) if fixed_poro_scale else (float(numeric_values.min()), float(numeric_values.max()))
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
                    fillcolor=px.colors.sample_colorscale("Viridis", fraction)[0],
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
    st.plotly_chart(fig, use_container_width=True, key=key)


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
        finite = values[np.isfinite(values)]
        low, high = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
        if np.isclose(low, high):
            bins = np.zeros(len(work), dtype=int)
        else:
            bins = np.clip(((values - low) / (high - low) * 15).astype(int), 0, 15)
        for bucket in np.unique(bins):
            fraction = (int(bucket) + 0.5) / 16
            color = px.colors.sample_colorscale("Viridis", fraction)[0]
            add_cells(work[bins == bucket], color_column, color, False)

    fig.update_layout(
        height=620, margin=dict(l=10, r=10, t=45, b=10),
        title=f"{axis_mode}: {selector}", hovermode="closest", showlegend=is_discrete,
        xaxis_title=axis_label, yaxis_title="Z (depth)",
    )
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(fig, use_container_width=True, key=key)


st.set_page_config(page_title="GO-Forward GRDECL/T>Map", layout="wide")


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
    return sorted(set(files), key=lambda path: path.name.lower())


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def source_folder_selector() -> Path:
    """Choose a known workspace input folder or enter another local folder."""
    known = [SOURCE_GRDECL_DIR]
    input_dir = ROOT / "input"
    if input_dir.exists():
        known.extend(path for path in input_dir.iterdir() if path.is_dir() and path not in known)
    labels = [display_path(path) for path in known] + ["Enter another folder path"]
    choice = st.selectbox("Source GRDECL folder", labels, key="source_grdecl_folder_choice")
    if choice == "Enter another folder path":
        folder_text = st.text_input("Local source folder path", value=str(SOURCE_GRDECL_DIR), key="source_grdecl_folder_custom")
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


def source_grdecl_for_pointset(pointset: Path, source_dir: Path) -> Path | None:
    """Find the source GRDECL whose stem prefixes a returned Best-fit point-set name."""
    matches = [path for path in files_in(source_dir, ("*.grdecl", "*.GRDECL")) if pointset.name.startswith(path.stem)]
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
    if values.empty:
        return None
    if "porosity" in base or base.startswith("poro"):
        return (0.0, 0.4)
    if "perm" in base:
        logged = np.log10(values.clip(lower=1e-12))
        return float(logged.min()), float(logged.max())
    return float(values.min()), float(values.max())


def k_layer_selector(key: str, minimum: int, maximum: int) -> int:
    """K-layer slider with previous/next controls that work in a fragment rerun."""
    if minimum == maximum:
        return minimum
    state_key = f"{key}_value"
    if state_key not in st.session_state:
        st.session_state[state_key] = minimum

    def shift(delta: int) -> None:
        st.session_state[state_key] = max(minimum, min(maximum, st.session_state[state_key] + delta))

    previous, slider, next_button = st.columns([0.16, 0.68, 0.16])
    previous.button("Previous K", key=f"{key}_previous", on_click=shift, args=(-1,), disabled=st.session_state[state_key] <= minimum)
    with slider:
        st.slider("K layer", minimum, maximum, key=state_key)
    next_button.button("Next K", key=f"{key}_next", on_click=shift, args=(1,), disabled=st.session_state[state_key] >= maximum)
    return int(st.session_state[state_key])


def plot_3d_points(
    df: pd.DataFrame,
    color_column: str,
    colors: dict[int, str] | None,
    key: str,
    vertical_exaggeration: float = 1.0,
    reference_df: pd.DataFrame | None = None,
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
        colour = pd.to_numeric(df[color_column], errors="coerce")
        colour_title = color_column
        if "perm" in color_column.lower():
            colour = np.log10(colour.clip(lower=1e-12))
            colour_title = f"{color_column} (log10 mD)"
        fig.add_trace(go.Scatter3d(
            x=df["X"], y=df["Y"], z=df["Z"], mode="markers",
            marker={"size": 2, "color": colour, "colorscale": "Viridis", "showscale": True, "colorbar": {"title": colour_title}},
            hovertemplate=f"X: %{{x:.0f}}<br>Y: %{{y:.0f}}<br>Z: %{{z:.0f}}<extra></extra>",
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
    st.plotly_chart(fig, use_container_width=True, key=key)


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
def control_preview_dataframe(
    paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...], spacing: float, max_rows: int
) -> tuple[pd.DataFrame, int, dict[int, int]]:
    """Return shared facies-envelope controls matching the multi-realization builder."""
    if not paths_text:
        return pd.DataFrame(), 0, {}
    reference_path = Path(paths_text[0])
    nx, ny, nz = grdecl_dimensions(str(reference_path))
    reference_centres = grdecl_cell_centers(reference_path)
    enabled = set(enabled_codes)
    envelopes: dict[tuple[int, int], list[float]] = {}
    for path_text in paths_text:
        path = Path(path_text)
        model_nx, model_ny, _ = grdecl_dimensions(path_text)
        if (model_nx, model_ny) != (nx, ny):
            raise ValueError(f"{path.name} has incompatible I/J dimensions")
        values = [int(float(value)) for value in expand_values(tokenize_grdecl(path, {property_name})[property_name])]
        centres = grdecl_cell_centers(path)
        for index, ((_, _, z), facies) in enumerate(zip(centres, values)):
            if facies == 0 or facies not in enabled:
                continue
            envelopes.setdefault((facies, index % (nx * ny)), []).append(z)
    rows: list[dict[str, float | int]] = []
    counts_by_facies: dict[int, int] = {}
    for (facies, column), zs in envelopes.items():
        top_z, bottom_z = max(zs), min(zs)
        x, y, _ = reference_centres[column]
        levels = [top_z]
        z = top_z - spacing
        while z > bottom_z:
            levels.append(z)
            z -= spacing
        if abs(levels[-1] - bottom_z) > 1e-9:
            levels.append(bottom_z)
        counts_by_facies[facies] = counts_by_facies.get(facies, 0) + len(levels)
        for z in levels:
            # Shared controls have regular Z values rather than a literal grid
            # cell. Assign the nearest reference-model K only for dashboard
            # slicing; the exported pointset retains its true control Z.
            nearest_k = min(
                range(nz),
                key=lambda k: abs(reference_centres[column + k * nx * ny][2] - z),
            ) + 1
            rows.append({"X": x, "Y": y, "Z": z, property_name: facies, "ControlColumn": column,
                         "I": column % nx + 1, "J": column // nx + 1, "K": nearest_k})
    # Keep the complete control set here so a subsequently selected facies is
    # never absent merely because another facies consumed the display sample.
    return pd.DataFrame(rows), len(rows), counts_by_facies


@st.cache_data(show_spinner=False)
def uber_point_summary(paths_text: tuple[str, ...], property_name: str, enabled_codes: tuple[int, ...], spacing: float) -> tuple[int, int, int, list[int]]:
    """Calculate exact Uber output size without materialising its potentially huge grid."""
    paths = [Path(path_text) for path_text in paths_text]
    if not paths:
        return 0, 0, 0, []
    nx, ny, _ = grdecl_dimensions(str(paths[0]))
    facies: set[int] = set()
    z_min, z_max = float("inf"), float("-inf")
    for path in paths:
        values = [int(float(value)) for value in expand_values(tokenize_grdecl(path, {property_name})[property_name])]
        facies.update(value for value in values if value != 0 and value in set(enabled_codes))
        centres = grdecl_cell_centers(path)
        z_min = min(z_min, min(z for _, _, z in centres))
        z_max = max(z_max, max(z for _, _, z in centres))
    z_start = np.floor(z_min / spacing) * spacing
    z_stop = np.ceil(z_max / spacing) * spacing
    z_levels = int(round((z_stop - z_start) / spacing)) + 1
    xy_points = nx * ny
    return xy_points * z_levels * len(facies), xy_points, z_levels, sorted(facies)


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
        st.caption(f"{xy_count:,} XY locations × {z_count:,} Z levels × {len(uber_facies)} facies at {spacing:g} m spacing.")
    return float(spacing)


def facies_config_editor(codes: list[int], config_path: Path, source_dir: Path, facies_property: str, key: str) -> None:
    """Edit names, colours, and T>Map flags for codes visible in the selected model."""
    if not codes:
        return
    with st.expander("Facies definitions", expanded=False):
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
        st.caption("Disable T>Map for non-reservoir facies. Those cells are excluded from T>Map modelling and will receive `-77777` for appended T>Map properties.")
        for position, code in enumerate(codes):
            item = metadata.get(str(code), {}) if isinstance(metadata.get(str(code)), dict) else {}
            columns = st.columns([0.7, 2.2, 1.0, 1.5, 1.0])
            columns[0].write(f"**{code}**")
            edited_names[code] = columns[1].text_input("Name", names.get(str(code), f"Facies {code}"), key=f"{widget_key}_name_{code}")
            edited_colours[code] = columns[2].color_picker("Colour", colours.get(str(code), default_facies_color(position)), key=f"{widget_key}_colour_{code}")
            category_options = ["reservoir", "non_reservoir"]
            category = str(item.get("category", "non_reservoir" if code == 0 else "reservoir"))
            edited_metadata[code] = {"category": columns[3].selectbox("Category", category_options, index=category_options.index(category) if category in category_options else 0, key=f"{widget_key}_category_{code}")}
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
        if st.button("Save facies definitions", key=f"{widget_key}_save"):
            payload.update({
                "facies_property": facies_property,
                "source_grdecl_directory": str(source_dir),
                "source_grdecl_files": [path.name for path in files_in(source_dir, ("*.grdecl", "*.GRDECL"))],
                "facies_names": {str(code): name for code, name in edited_names.items()},
                "facies_colors": {str(code): colour for code, colour in edited_colours.items()},
                "facies_metadata": {str(code): meta for code, meta in edited_metadata.items()},
            })
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            st.success("Facies definitions saved.")
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


def run_commands(commands: list[list[str]]) -> bool:
    output = []
    for command in commands:
        full_command = [sys.executable, *command]
        result = subprocess.run(full_command, cwd=ROOT, capture_output=True, text=True)
        output.append(f"> {' '.join(command)}")
        if result.stdout:
            output.append(result.stdout.strip())
        if result.stderr:
            output.append(result.stderr.strip())
        if result.returncode != 0:
            st.error(f"Command failed: {' '.join(command)}")
            st.code("\n\n".join(output), language="text")
            return False
    st.success("Workflow step completed")
    st.code("\n\n".join(output), language="text")
    return True


def commands_for_grdecl_dir(commands: list[list[str]], grdecl_dir: Path) -> list[list[str]]:
    """Pass the dashboard's selected source folder to builder/append scripts."""
    return [[*command, "--grdecl-dir", str(grdecl_dir)] for command in commands]


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
                columns.append(line.split(",", 1)[-1])
    return columns


@st.cache_data(show_spinner=False)
def pointset_dataframe(path_text: str, max_rows: int) -> pd.DataFrame:
    path = Path(path_text)
    columns = parse_point_header(path)
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
        st.dataframe(df.head(500), use_container_width=True)
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
        color_range = continuous_limits or ((0.0, 0.4) if ("porosity" in color_column.lower() or color_column.lower().startswith("poro")) else None)
        fig = px.scatter(
            plot_data,
            x="X",
            y="Y",
            color=color_field,
            hover_data=[col for col in ("I", "J", "K", "Z", "CellIndex", "Realization", "Facies") if col in df.columns],
            render_mode="webgl",
            title=title,
            color_continuous_scale="Viridis" if pd.api.types.is_numeric_dtype(df[color_column]) else None,
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
    st.plotly_chart(fig, use_container_width=True, key=key)


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
        color_range = continuous_limits or ((0.0, 0.4) if ("porosity" in color_column.lower() or color_column.lower().startswith("poro")) else None)
        fig = px.scatter(
            plot_data,
            x=x_axis,
            y="Z",
            color=color_field,
            hover_data=[col for col in ("I", "J", "K", "X", "Y", "CellIndex", "Facies") if col in work.columns],
            render_mode="webgl",
            title=f"{axis_mode}: {selector}",
            color_continuous_scale="Viridis" if pd.api.types.is_numeric_dtype(work[color_column]) else None,
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
    st.plotly_chart(fig, use_container_width=True, key=key)


@st.fragment
def visualization_panel(
    df: pd.DataFrame,
    key: str,
    default_color: str | None = None,
    is_grdecl: bool = False,
    cell_only: bool = False,
) -> None:
    numeric_or_small = [
        col
        for col in df.columns
        if col not in {"X", "Y", "Z"}
        and (pd.api.types.is_numeric_dtype(df[col]) or df[col].nunique(dropna=True) <= 30)
    ]
    if not numeric_or_small:
        st.dataframe(df.head(500), use_container_width=True)
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
    if not is_discrete and color_column != "CellIndex" and pd.api.types.is_numeric_dtype(df[color_column]):
        lock_scale = st.checkbox("Lock colour scale across related statistics (P10/P50/P90)", key=f"{key}_lock_scale")
        if lock_scale:
            continuous_limits = related_continuous_limits(df, color_column)
    
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
                if slice_mode == "K layer":
                    selected_k = k_layer_selector(f"{key}_point_k_layer", k_min, k_max)
                    point_layer = plot_df[plot_df["K"] == selected_k]
                    title = f"Map viewer (points, K={selected_k})"
                else:
                    max_depth = float((plot_df.groupby(["I", "J"])["Z"].transform("max") - plot_df["Z"]).max())
                    st.caption("Uses the shallowest exported point in each I/J column as the local model top. Only real points within the chosen depth band are shown; gaps reveal reduced sampling coverage.")
                    depth_below_top = st.slider("Depth below model top (m)", 0.0, max(1.0, max_depth), min(10.0, max_depth), step=1.0, key=f"{key}_point_depth_below_top")
                    half_thickness = st.slider("Depth-band half-thickness (m)", 1.0, max(1.0, max_depth / 2.0), min(5.0, max(1.0, max_depth / 2.0)), step=1.0, key=f"{key}_point_depth_band")
                    point_layer = slice_depth_band_below_top(plot_df, depth_below_top, half_thickness)
                    title = f"Map viewer (points, {depth_below_top:g} ± {half_thickness:g} m below model top)"
                plot_map(point_layer, color_column, title, colors if is_discrete else None, key=f"{key}_point_map", extent=map_extent, continuous_limits=continuous_limits)
            else:
                plot_map(plot_df, color_column, "Map viewer", colors if is_discrete else None, key=f"{key}_point_map", extent=map_extent, continuous_limits=continuous_limits)
    elif view == "3D viewer":
        three_d_df = plot_df
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
                if minimum == maximum:
                    selected_layer = minimum
                else:
                    selected_layer = st.slider(f"{axis} layer", minimum, maximum, minimum, key=f"{key}_3d_{axis}_layer")
                three_d_df = plot_df[plot_df[axis] == selected_layer]
                st.caption(f"Showing {slice_axis} = {selected_layer}: {len(three_d_df):,} points.")
        plot_3d_points(
            three_d_df,
            color_column,
            colors if is_discrete else None,
            key=f"{key}_3d",
            vertical_exaggeration=vertical_exaggeration,
            reference_df=plot_df,
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
            plot_section(plot_df, color_column, axis_mode, selector, colors if is_discrete else None, key=f"{key}_point_section", continuous_limits=continuous_limits)
    else:
        st.dataframe(df.head(2000), use_container_width=True)

    if is_discrete and categories:
        st.divider()
        facies_color_settings(categories, f"{key}_facies")


def approach_selector(key: str) -> tuple[str, dict[str, Path]]:
    name = st.selectbox("Approach", list(APPROACHES), key=key)
    return name, APPROACHES[name]


def file_selector(label: str, folder: Path, patterns: tuple[str, ...], key: str) -> Path | None:
    files = files_in(folder, patterns)
    if not files:
        st.warning(f"No files found in {display_path(folder)}")
        return None
    selected = st.selectbox(label, files, format_func=lambda path: path.name, key=key)
    st.caption(display_path(selected))
    return selected


def grdecl_property_selector(path: Path, key: str) -> str | None:
    property_keywords = grdecl_property_keywords(path)
    if not property_keywords:
        return None
    default = "Facies" if "Facies" in property_keywords else "FACIES" if "FACIES" in property_keywords else property_keywords[0]
    return st.selectbox(
        "Select Facies property in GRDECL",
        property_keywords,
        index=property_keywords.index(default),
        key=key,
        help="Selects the facies property used for the source-cell viewer and pointset generation.",
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
def grdecl_novalue_summary(path_text: str) -> pd.DataFrame:
    path = Path(path_text)
    rows = []
    for keyword in grdecl_property_keywords(path):
        values = pd.to_numeric(pd.Series(expand_values(tokenize_grdecl(path, {keyword})[keyword])), errors="coerce")
        rows.append({"Property": keyword, "-77777 cells": int((values == -77777).sum()), "Total cells": len(values)})
    return pd.DataFrame(rows)


st.title("GO-Forward GRDECL to T>Map workflow")
st.caption("MVP dashboard for GRDECL inspection, point-set generation, T>Map-style outputs, and augmented GRDECL review.")

with st.sidebar:
    st.header("Data")
    max_rows = st.slider("Maximum plotted rows", 5_000, 200_000, 75_000, step=5_000)
    st.caption(f"Workspace: {ROOT}")
    if px is None:
        st.warning("Plotly is not installed; visual plots will be replaced by tables.")

tab1, tab2, tab3 = st.tabs(["1. Source GRDECL to point sets", "2. T>Map data and append", "3. Augmented GRDECLs"])

with tab1:
    left, right = st.columns([0.34, 0.66])
    with left:
        st.subheader("Source GRDECL")
        source_grdecl_dir = source_folder_selector()
        st.session_state["active_facies_config"] = str(source_grdecl_dir / "facies_config.json")
        st.caption(display_path(source_grdecl_dir))
        facies_key = None
        if not source_grdecl_dir.is_dir():
            st.error("Choose an existing local folder containing GRDECL files.")
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
                    _, control_count, _ = control_preview_dataframe(
                        tuple(str(path) for path in selected_multi_models), facies_key, multi_enabled_codes, control_spacing, 1
                    )
                    st.metric("Control points exported to T>Map", f"{control_count:,}")
                    st.caption(
                        f"One shared facies envelope per I/J column: shallowest and deepest occurrence across "
                        f"{len(selected_multi_models)} selected model(s), plus {control_spacing:g} m vertical controls."
                    )
            elif approach_name == "Multi-realization Uber":
                uber_spacing = uber_sampling_control(selected_multi_models, facies_key or "Facies", multi_enabled_codes)
        can_build = source_grdecl_dir.is_dir() and (approach_name == "Best-fit model" or bool(selected_multi_models))
        if st.button("Convert selected approach to 3D point sets", key="build_points", disabled=not can_build):
            commands = commands_for_grdecl_dir(approach["build_points"], source_grdecl_dir)
            if approach_name == "Best-fit model":
                extra = ["--property", facies_key or "Facies"]
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
            run_commands(commands)
        point_files = files_in(approach["point_dir"], ("*",))
    with right:
        viewer_options = ["Original GRDECL cells"]
        if approach_name == "Best-fit model" and bestfit_reduced and grdecl and facies_key:
            viewer_options.append("Preview reduced T>Map points")
        if approach_name == "Multi-realization control points" and selected_multi_models and facies_key:
            viewer_options.append("Preview control T>Map points")
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
        elif grdecl and prop:
            df = grdecl_dataframe(str(grdecl), prop, max_rows)
            visualization_panel(df, "tab1", prop, is_grdecl=True)

with tab2:
    left, right = st.columns([0.34, 0.66])
    with left:
        st.subheader("T>Map output folder")
        approach_name, approach = approach_selector("tab2_approach")
        pointset_files = files_in(approach["point_dir"], ("*",))
        tmap_files: list[Path] = []
        is_reduced = False
        if not pointset_files:
            st.info("No 3D pointset dataset has been created for this approach. Go to Tab 1, select this approach, and run Conversion first.")
            tmap_file = None
        else:
            st.success(f"3D pointset dataset ready: {len(pointset_files)} file(s) in {display_path(approach['point_dir'])}")
            tmap_files = files_in(approach["tmap_dir"], ("*",))
            if approach_name == "Best-fit model":
                available_kinds = ["Full resolution"]
                if any("_control_" in path.name for path in pointset_files):
                    available_kinds.append("Reduced vertical sampling")
                dataset_kind = st.radio("Available source 3D pointset datasets", available_kinds, horizontal=True, key="tab2_bestfit_dataset")
                is_reduced = dataset_kind == "Reduced vertical sampling"
                pointset_files = [path for path in pointset_files if ("_control_" in path.name) == is_reduced]
                tmap_files = [path for path in tmap_files if ("_control_" in path.name) == is_reduced]
            else:
                selected_pointsets = pointset_files
            status_rows = []
            for pointset in pointset_files:
                matching_returns = [returned for returned in tmap_files if returned.name == pointset.name or returned.name.startswith(pointset.name)]
                has_synthetic = any("_tmap_synthetic" in returned.name for returned in matching_returns)
                has_real = any("_tmap_synthetic" not in returned.name for returned in matching_returns)
                tmap_status = "Synthetic & real" if has_synthetic and has_real else "Synthetic" if has_synthetic else "Real" if has_real else "None"
                status_rows.append({
                    "Source 3D pointset": pointset.name,
                    "T>Map data": tmap_status,
                })
            st.caption("Source 3D pointsets and matching returned T>Map data")
            st.dataframe(pd.DataFrame(status_rows), hide_index=True, use_container_width=True)
            st.info(
                f"Run the selected source pointsets from {display_path(approach['point_dir'])} through T>Map. "
                f"After T>Map has run, place its returned point-set file(s) in {display_path(approach['tmap_dir'])}, retaining the input filename and ID columns."
            )
            if not tmap_files:
                st.info("No returned T>Map data are available yet. For MVP testing only, synthetic placeholder data can be generated below. They use deterministic facies/depth rules and the sample T>Map column schema; they are not calibrated from a real T>Map run.")
            if approach_name == "Best-fit model":
                selected_pointsets = st.multiselect(
                    "Pointset models to generate synthetic T>Map data for",
                    pointset_files,
                    default=pointset_files,
                    format_func=lambda path: f"{pointset_batch_and_scenario(path)[0]} — {pointset_batch_and_scenario(path)[1]}",
                    key="tab2_bestfit_pointset_models",
                )
            st.caption(f"Selected input dataset: {len(selected_pointsets)} of {len(pointset_files)} 3D pointset file(s).")
            if st.button("Generate synthetic T>Map data for selected dataset", key="generate_tmap", disabled=not selected_pointsets):
                commands = approach["generate_tmap"]
                if approach_name == "Best-fit model":
                    commands = [
                        [*command, "--source-dir", str(approach["point_dir"]), "--glob", path.name]
                        for path in selected_pointsets
                        for command in commands
                    ]
                if run_commands(commands):
                    st.rerun()
            if not tmap_files:
                tmap_file = None
            else:
                st.info("Select a returned T>Map point-set file below, inspect it in the viewer, then click Append selected T>Map data back to GRDECL.")
                tmap_file = st.selectbox("Returned T>Map point-set file", tmap_files, format_func=lambda path: path.name, key="tab2_tmap_file")
                st.caption(display_path(tmap_file))
        if tmap_file and st.button("Append selected T>Map data back to GRDECL", key="append_tmap"):
            commands = commands_for_grdecl_dir(approach["append"], source_grdecl_dir)
            if approach_name == "Best-fit model":
                source_grdecl = source_grdecl_for_pointset(tmap_file, source_grdecl_dir)
                if source_grdecl is None:
                    st.error("Could not identify the source GRDECL for this selected Best-fit point set.")
                else:
                    extra = ["--single-grdecl", str(source_grdecl), "--single-pointset", str(tmap_file)]
                    if is_reduced:
                        extra.extend(["--vertical-interpolate", "--property", "Facies"])
                    commands = [[*command, *extra] for command in commands]
                    run_commands(commands)
            else:
                run_commands(commands)
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
                for returned_file in append_files:
                    source_grdecl = source_grdecl_for_pointset(returned_file, source_grdecl_dir)
                    if source_grdecl is None:
                        st.error(f"Could not identify the source GRDECL for {returned_file.name}.")
                        continue
                    reduced_file = "_control_" in returned_file.name
                    extra = ["--single-grdecl", str(source_grdecl), "--single-pointset", str(returned_file)]
                    if reduced_file:
                        extra.extend(["--vertical-interpolate", "--property", "Facies"])
                    commands.extend([[*command, *extra] for command in commands_for_grdecl_dir(approach["append"], source_grdecl_dir)])
                if commands:
                    run_commands(commands)
        if approach_name == "Best-fit model" and tmap_file and is_reduced:
            st.info(
                "Appending reduced T>Map points linearly interpolates each returned property vertically within its I/J/facies column to populate original GRDECL cells between control points. "
                "Top and bottom control points are retained, so this is interpolation within the sampled interval rather than unconstrained extrapolation. "
                f"The augmented GRDECL is written to: {display_path(approach['augmented_dir'])}"
            )
    with right:
        if tmap_file:
            tmap_df = enrich_ijk_from_cell_index(pointset_dataframe(str(tmap_file), max_rows), source_grdecl_dir)
            default = "total_porosity_mean" if "total_porosity_mean" in tmap_df.columns else None
            visualization_panel(tmap_df, "tab2", default, is_grdecl="K" in tmap_df.columns)

with tab3:
    left, right = st.columns([0.34, 0.66])
    with left:
        st.subheader("Augmented GRDECL")
        approach_name, approach = approach_selector("tab3_approach")
        folder_options = {"Full augmented GRDECLs": approach["augmented_dir"]}
        if "petrel_augmented_dir" in approach:
            folder_options["Petrel-standard GRDECLs"] = approach["petrel_augmented_dir"]
        folder_label = st.radio("Output set", list(folder_options), key="tab3_output_set")
        augmented_file = file_selector("Augmented file", folder_options[folder_label], ("*.grdecl", "*.GRDECL"), "tab3_augmented")
        if augmented_file:
            dims = grdecl_dimensions(str(augmented_file))
            st.metric("Grid dimensions", f"{dims[0]} x {dims[1]} x {dims[2]}")
            st.metric("Cells", f"{dims[0] * dims[1] * dims[2]:,}")
            st.caption("All cell-sized GRDECL properties are available in the Property viewer.")
            st.caption("A `-77777` value indicates that the facies was toggled non-reservoir in Tab 1 Facies definitions, was therefore excluded from T>Map modelling, and has no appended T>Map value.")
            st.dataframe(grdecl_novalue_summary(str(augmented_file)), hide_index=True, use_container_width=True)
    with right:
        if augmented_file:
            df = augmented_grdecl_dataframe(str(augmented_file), max_rows)
            default_property = "Facies" if "Facies" in df.columns else "FACIES" if "FACIES" in df.columns else None
            visualization_panel(df, "tab3", default_property, is_grdecl=True)
