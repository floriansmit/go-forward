from __future__ import annotations

import csv
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
        "build_points": [["scripts/grdecl_to_petrel_pointsets.py"]],
        "generate_tmap": [["scripts/generate_tmap_pointsets.py", "--property-profile", "reservoir_quality"]],
        "append": [["scripts/append_best_fit_tmap_to_grdecls.py"]],
    },
    "Multi-realization union": {
        "point_dir": ROOT / "outputs" / "Multi-realization union approach" / "01_union_pointsets_by_facies",
        "tmap_dir": ROOT / "outputs" / "Multi-realization union approach" / "02_union_pointsets_with_tmap_data",
        "augmented_dir": ROOT / "outputs" / "Multi-realization union approach" / "03_augmented_grdecls_from_union_lookup",
        "build_points": [["scripts/build_union_pointsets_by_facies.py"]],
        "generate_tmap": [[
            "scripts/generate_tmap_pointsets.py",
            "--source-dir",
            "outputs/Multi-realization union approach/01_union_pointsets_by_facies",
            "--output-dir",
            "outputs/Multi-realization union approach/02_union_pointsets_with_tmap_data",
            "--glob",
            "union_facies_*",
            "--property-profile",
            "reservoir_quality",
        ]],
        "append": [["scripts/append_union_tmap_to_grdecls.py"]],
    },
    "Multi-realization control points": {
        "point_dir": ROOT / "outputs" / "Multi-realization control approach" / "01_control_pointsets_by_facies",
        "tmap_dir": ROOT / "outputs" / "Multi-realization control approach" / "02_control_pointsets_with_tmap_data",
        "augmented_dir": ROOT / "outputs" / "Multi-realization control approach" / "03_augmented_grdecls_from_control_interpolation",
        "build_points": [["scripts/build_control_pointsets_by_facies.py"]],
        "generate_tmap": [[
            "scripts/generate_tmap_pointsets.py",
            "--source-dir",
            "outputs/Multi-realization control approach/01_control_pointsets_by_facies",
            "--output-dir",
            "outputs/Multi-realization control approach/02_control_pointsets_with_tmap_data",
            "--glob",
            "control_facies_*",
            "--property-profile",
            "reservoir_quality",
        ]],
        "append": [["scripts/append_control_tmap_to_grdecls.py"]],
    },
    "Multi-realization Uber": {
        "point_dir": ROOT / "outputs" / "Multi-realization Uber approach" / "01_uber_pointsets_by_facies",
        "tmap_dir": ROOT / "outputs" / "Multi-realization Uber approach" / "02_uber_pointsets_with_tmap_data",
        "augmented_dir": ROOT / "outputs" / "Multi-realization Uber approach" / "03_augmented_grdecls_from_uber_lookup",
        "petrel_augmented_dir": ROOT / "outputs" / "Multi-realization Uber approach" / "04_petrel_standard_grdecls_from_uber_lookup",
        "build_points": [["scripts/build_uber_pointsets_by_facies.py"]],
        "generate_tmap": [[
            "scripts/generate_tmap_pointsets.py",
            "--source-dir",
            "outputs/Multi-realization Uber approach/01_uber_pointsets_by_facies",
            "--output-dir",
            "outputs/Multi-realization Uber approach/02_uber_pointsets_with_tmap_data",
            "--glob",
            "uber_facies_*",
            "--property-profile",
            "reservoir_quality",
        ]],
        "append": [["scripts/append_uber_tmap_to_grdecls.py"], ["scripts/write_petrel_standard_uber_grdecls.py"]],
    },
}


def inject_scripts_path() -> None:
    script_path = str(SCRIPTS)
    if script_path not in sys.path:
        sys.path.insert(0, script_path)


inject_scripts_path()
from grdecl_utils import grdecl_cell_centers, tokenize_grdecl  # noqa: E402

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


def read_facies_config(path: Path = FACIES_CONFIG_PATH) -> dict[int, str]:
    """Read facies color configuration from JSON file."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        palette = data.get("facies_colors", {})
        return {int(k): str(v) for k, v in palette.items()}
    except Exception as exc:
        st.warning(f"Could not read facies config: {exc}")
        return {}


def read_facies_names(path: Path = FACIES_CONFIG_PATH) -> dict[int, str]:
    """Read optional display names while retaining the built-in facies labels."""
    names = DEFAULT_FACIES_NAMES.copy()
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


def write_facies_config(palette: dict[int, str], path: Path = FACIES_CONFIG_PATH) -> None:
    """Write facies color configuration to JSON file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        payload["facies_colors"] = {str(k): v for k, v in sorted(palette.items())}
        payload.setdefault("facies_names", {str(k): v for k, v in DEFAULT_FACIES_NAMES.items()})
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
        help="Load a JSON file previously downloaded from this panel. Colors for codes not in the file keep their defaults.",
    )
    if uploaded_palette is not None and st.button("Apply loaded colors", key=f"{key_prefix}_apply_palette"):
        try:
            uploaded = json.loads(uploaded_palette.getvalue().decode("utf-8"))
            raw_palette = uploaded.get("facies_colors", uploaded)
            loaded_palette = {int(code): str(color) for code, color in raw_palette.items()}
            write_facies_config({**saved_palette, **loaded_palette})
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


def grdecl_cell_polygons(path: Path, property_keyword: str | None = None) -> pd.DataFrame:
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
    for k in range(nz):
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
            if len(values) == len(df):
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
        for _, row in df.iterrows():
            color_val = row[color_column] if color_column in row else 0
            fig.add_trace(
                go.Scatter(
                    x=[row["X0"], row["X1"], row["X2"], row["X3"], row["X0"]],
                    y=[row["Y0"], row["Y1"], row["Y2"], row["Y3"], row["Y0"]],
                    fill="toself",
                    marker={"color": color_val},
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
    st.plotly_chart(fig, use_container_width=True)


def plot_section_with_cells(
    df: pd.DataFrame,
    color_column: str,
    axis_mode: str,
    selector: int | float,
    colors: dict[int, str] | None = None,
    max_cells: int = 5_000,
) -> None:
    """Render a cell-face cross-section using the GRDECL corner depths."""
    work = df.copy()
    if axis_mode == "I section":
        work = work[work["I"] == selector]
        axis_label = "J index"
    elif axis_mode == "J section":
        work = work[work["J"] == selector]
        axis_label = "I index"
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
        if axis_mode == "I section":
            # Follow the J direction through the selected I column.  The two
            # top and bottom edges retain their true corner-derived dips.
            x = [row["J"] - 0.5, row["J"] + 0.5, row["J"] + 0.5, row["J"] - 0.5]
            z = [
                (row["Z0_top"] + row["Z1_top"]) / 2,
                (row["Z3_top"] + row["Z2_top"]) / 2,
                (row["Z3_bot"] + row["Z2_bot"]) / 2,
                (row["Z0_bot"] + row["Z1_bot"]) / 2,
            ]
        elif axis_mode == "J section":
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
    st.plotly_chart(fig, use_container_width=True)


st.set_page_config(page_title="GO-Forward GRDECL/T>Map", layout="wide")


def files_in(folder: Path, patterns: tuple[str, ...]) -> list[Path]:
    if not folder.exists():
        return []
    files: list[Path] = []
    for pattern in patterns:
        files.extend(
            path
            for path in folder.glob(pattern)
            if path.is_file()
            and not path.name.endswith(".xml")
            and path.suffix.lower() not in {".md", ".png", ".jpg", ".jpeg"}
        )
    return sorted(set(files), key=lambda path: path.name.lower())


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def run_commands(commands: list[list[str]]) -> None:
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
            return
    st.success("Workflow step completed")
    st.code("\n\n".join(output), language="text")


def commands_for_grdecl_dir(commands: list[list[str]], grdecl_dir: Path) -> list[list[str]]:
    """Pass the dashboard's selected source folder to builder/append scripts."""
    return [[*command, "--grdecl-dir", str(grdecl_dir)] for command in commands]


def keyword_candidates(path: Path) -> list[str]:
    keywords: list[str] = []
    active = False
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
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
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
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
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
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


def plot_map(df: pd.DataFrame, color_column: str, title: str, colors: dict[int, str] | None = None) -> None:
    if px is None:
        st.info("Install Plotly to enable interactive maps: python -m pip install plotly")
        st.dataframe(df.head(500), use_container_width=True)
        return
    
    # Check if this is cell polygon data
    has_cells = all(col in df.columns for col in ["X0", "Y0", "X1", "Y1", "X2", "Y2", "X3", "Y3"])
    if has_cells:
        return plot_map_with_cells(df, color_column, title, colors)
    
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
        fig = px.scatter(
            df,
            x="X",
            y="Y",
            color=color_column,
            hover_data=[col for col in ("I", "J", "K", "Z", "CellIndex", "Realization", "Facies") if col in df.columns],
            render_mode="webgl",
            title=title,
            color_continuous_scale="Viridis" if pd.api.types.is_numeric_dtype(df[color_column]) else None,
        )
        fig.update_layout(height=560, margin=dict(l=10, r=10, t=45, b=10), yaxis_scaleanchor="x")
    
    st.plotly_chart(fig, use_container_width=True)


def plot_section(df: pd.DataFrame, color_column: str, axis_mode: str, selector: int | float, colors: dict[int, str] | None = None) -> None:
    if px is None:
        st.info("Install Plotly to enable cross-section plots: python -m pip install plotly")
        return
    work = df.copy()
    if axis_mode == "I section" and "I" in work.columns:
        work = work[work["I"] == selector]
        x_axis = "J"
    elif axis_mode == "J section" and "J" in work.columns:
        work = work[work["J"] == selector]
        x_axis = "I"
    elif axis_mode == "X slice":
        width = max((work["X"].max() - work["X"].min()) / 80.0, 1.0)
        work = work[(work["X"] >= selector - width) & (work["X"] <= selector + width)]
        x_axis = "Y"
    else:
        width = max((work["Y"].max() - work["Y"].min()) / 80.0, 1.0)
        work = work[(work["Y"] >= selector - width) & (work["Y"] <= selector + width)]
        x_axis = "X"
    if work.empty:
        st.warning("No points in this section.")
        return
    
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
            xaxis_title=x_axis,
            yaxis_title="Z (depth)",
        )
    else:
        fig = px.scatter(
            work,
            x=x_axis,
            y="Z",
            color=color_column,
            hover_data=[col for col in ("I", "J", "K", "X", "Y", "CellIndex", "Facies") if col in work.columns],
            render_mode="webgl",
            title=f"{axis_mode}: {selector}",
            color_continuous_scale="Viridis" if pd.api.types.is_numeric_dtype(work[color_column]) else None,
        )
        fig.update_layout(height=560, margin=dict(l=10, r=10, t=45, b=10))
    
    st.plotly_chart(fig, use_container_width=True)


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
    
    # Check if property is discrete facies and set up color customization
    values = df[color_column].values if color_column in df.columns else np.array([])
    is_discrete = is_discrete_facies_property(color_column, values)
    colors: dict[int, str] = {}
    
    if is_discrete:
        categories = get_visible_facies(values)
        if categories:
            st.divider()
            colors = facies_color_settings(categories, f"{key}_facies")
            st.divider()
    
    # Check if we have cell polygon data
    has_cells = all(col in df.columns for col in ["X0", "Y0", "X1", "Y1", "X2", "Y2", "X3", "Y3"])
    
    if has_cells and is_grdecl:
        if cell_only:
            visualization_mode = "Cells"
        else:
            viz_options = ["Points", "Cells"]
            visualization_mode = st.radio("Visualization", viz_options, horizontal=True, key=f"{key}_viz_mode")
    else:
        visualization_mode = "Points"

    active_cell_mode = is_cell_data(df) and visualization_mode == "Cells"
    plot_df = df if active_cell_mode else cell_centres_as_points(df)
    
    view = st.radio("View", ["Map viewer", "Cross-section", "Data table"], horizontal=True, key=f"{key}_view")
    if view == "Map viewer":
        if active_cell_mode:
            # For cell data, show one K-layer at a time
            if is_cell_data(df):
                k_min, k_max = int(df["K"].min()), int(df["K"].max())
                selected_k = st.slider("K layer", k_min, k_max, k_min, key=f"{key}_k_layer")
                df_filtered = df[df["K"] == selected_k]
                plot_map_with_cells(df_filtered, color_column, f"Map viewer (K={selected_k})", colors if is_discrete else None)
            else:
                plot_map_with_cells(df, color_column, "Map viewer", colors if is_discrete else None)
        else:
            # A source/augmented grid in point mode can still contain every cell.
            # Restrict it to one K layer before Plotly receives the data.
            if is_grdecl and "K" in plot_df.columns:
                k_min, k_max = int(plot_df["K"].min()), int(plot_df["K"].max())
                selected_k = st.slider("K layer", k_min, k_max, k_min, key=f"{key}_point_k_layer")
                point_layer = plot_df[plot_df["K"] == selected_k]
                plot_map(point_layer, color_column, f"Map viewer (points, K={selected_k})", colors if is_discrete else None)
            else:
                plot_map(plot_df, color_column, "Map viewer", colors if is_discrete else None)
    elif view == "Cross-section":
        section_options = ["X slice", "Y slice"]
        if {"I", "J"}.issubset(plot_df.columns):
            section_options = ["I section", "J section", *section_options]
        axis_mode = st.selectbox("Section mode", section_options, key=f"{key}_section_mode")
        if axis_mode == "I section":
            selector = st.slider("I", int(plot_df["I"].min()), int(plot_df["I"].max()), int(plot_df["I"].median()), key=f"{key}_i")
        elif axis_mode == "J section":
            selector = st.slider("J", int(plot_df["J"].min()), int(plot_df["J"].max()), int(plot_df["J"].median()), key=f"{key}_j")
        elif axis_mode == "X slice":
            x_column = "X_center" if active_cell_mode else "X"
            selector = st.slider("X", float(plot_df[x_column].min()), float(plot_df[x_column].max()), float(plot_df[x_column].median()), key=f"{key}_x")
        else:
            y_column = "Y_center" if active_cell_mode else "Y"
            selector = st.slider("Y", float(plot_df[y_column].min()), float(plot_df[y_column].max()), float(plot_df[y_column].median()), key=f"{key}_y")

        if active_cell_mode:
            plot_section_with_cells(df, color_column, axis_mode, selector, colors if is_discrete else None)
        else:
            plot_section(plot_df, color_column, axis_mode, selector, colors if is_discrete else None)
    else:
        st.dataframe(df.head(2000), use_container_width=True)


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
    if not property_keywords:
        return None
    default = "Facies" if "Facies" in property_keywords else "FACIES" if "FACIES" in property_keywords else property_keywords[0]
    return st.selectbox("GRDECL property", property_keywords, index=property_keywords.index(default), key=key)


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
        source_folder_text = st.text_input(
            "Source GRDECL folder",
            value=str(SOURCE_GRDECL_DIR),
            key="source_grdecl_folder",
            help="Local folder containing the GRDECL realizations to inspect, convert, and append back to.",
        )
        source_grdecl_dir = Path(source_folder_text).expanduser()
        if not source_grdecl_dir.is_dir():
            st.error("Choose an existing local folder containing GRDECL files.")
        grdecl = file_selector("Source file", source_grdecl_dir, ("*.grdecl", "*.GRDECL"), "tab1_grdecl")
        if grdecl:
            prop = grdecl_property_selector(grdecl, "tab1_prop")
            dims = grdecl_dimensions(str(grdecl))
            st.metric("Grid dimensions", f"{dims[0]} x {dims[1]} x {dims[2]}")
            st.metric("Cells", f"{dims[0] * dims[1] * dims[2]:,}")
        else:
            prop = None

        st.divider()
        st.subheader("Conversion")
        approach_name, approach = approach_selector("tab1_approach")
        if st.button("Convert selected approach to 3D point sets", key="build_points", disabled=not source_grdecl_dir.is_dir()):
            run_commands(commands_for_grdecl_dir(approach["build_points"], source_grdecl_dir))
        point_files = files_in(approach["point_dir"], ("*",))
        if point_files:
            point_file = st.selectbox(
                "Converted 3D point set",
                point_files,
                format_func=lambda path: path.name,
                key="tab1_point_file",
            )
            st.caption(display_path(point_file))
        else:
            point_file = None
            st.caption("No converted point sets for this approach yet.")
    with right:
        if point_file:
            viewer_source = st.radio(
                "Viewer data",
                ["Original GRDECL cells", "Converted 3D points"],
                index=1,
                horizontal=True,
                key="tab1_viewer_source",
            )
        else:
            viewer_source = "Original GRDECL cells"

        if viewer_source == "Converted 3D points" and point_file:
            point_df = pointset_dataframe(str(point_file), max_rows)
            visualization_panel(point_df, "tab1_point", "Facies" if "Facies" in point_df.columns else None)
        elif grdecl and prop:
            # Cell-centre points are intentionally used here: polygon traces make
            # Streamlit/Plotly unresponsive for realistic GRDECL grid sizes.
            df = grdecl_dataframe(str(grdecl), prop, max_rows)
            visualization_panel(df, "tab1", prop, is_grdecl=True)

with tab2:
    left, right = st.columns([0.34, 0.66])
    with left:
        st.subheader("T>Map output folder")
        approach_name, approach = approach_selector("tab2_approach")
        st.caption(display_path(approach["tmap_dir"]))
        if st.button("Generate synthetic T>Map data for selected approach", key="generate_tmap"):
            run_commands(approach["generate_tmap"])
        if st.button("Append T>Map data back to GRDECLs", key="append_tmap"):
            run_commands(commands_for_grdecl_dir(approach["append"], source_grdecl_dir))
        tmap_file = file_selector("T>Map point-set file", approach["tmap_dir"], ("*",), "tab2_tmap_file")
    with right:
        if tmap_file:
            tmap_df = pointset_dataframe(str(tmap_file), max_rows)
            default = "total_porosity_mean" if "total_porosity_mean" in tmap_df.columns else None
            visualization_panel(tmap_df, "tab2", default)

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
            prop = grdecl_property_selector(augmented_file, "tab3_prop")
            dims = grdecl_dimensions(str(augmented_file))
            st.metric("Grid dimensions", f"{dims[0]} x {dims[1]} x {dims[2]}")
            st.metric("Cells", f"{dims[0] * dims[1] * dims[2]:,}")
    with right:
        if augmented_file and prop:
            df = grdecl_dataframe(str(augmented_file), prop, max_rows)
            visualization_panel(df, "tab3", prop, is_grdecl=True)
