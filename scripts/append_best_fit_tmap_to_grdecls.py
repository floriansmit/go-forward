from __future__ import annotations

import argparse
import bisect
import math
import os
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "original_grdecl"
DEFAULT_POINTSET_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "Best-fit approach" / "02_3d_points_with_tmap_data"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "Best-fit approach" / "03_augmented_grdecls_with_tmap_data"
NO_VALUE = "-77777"
MATCH_TOLERANCE_M = 0.05
IDENTITY_COLUMNS = {"x", "y", "z", "facies", "cellindex", "point_id", "pointid", "realization", "controlcolumn"}
GRDECL_KEYWORD_ALIASES = {
    "total_porosity_mean": "POROMEAN",
    "total_porosity_stdev": "POROSTD",
    "total_porosity_p10": "PORO10",
    "total_porosity_p25": "PORO25",
    "total_porosity_p50": "PORO50",
    "total_porosity_p75": "PORO75",
    "total_porosity_p90": "PORO90",
    "permeability_mean": "PERMMEAN",
    "permeability_stdev": "PERMSTD",
    "permeability_p10": "PERM10",
    "permeability_p25": "PERM25",
    "permeability_p50": "PERM50",
    "permeability_p75": "PERM75",
    "permeability_p90": "PERM90",
    "effective_stress_mpa": "EFFSTRESS",
    "intergranular_porosity_p50": "IGPORO50",
    "quartz_cement_p50": "QUARTZCM50",
    "total_cements_p50": "TOTCEM50",
    "total_carbonate_cmt_p50": "CARBCEM50",
    "total_clay_cmt_p50": "CLAYCEM50",
    "time": "TIME",
    "temperature": "TEMP",
    "burial_depth": "BURIAL",
    "effective_stress": "EFFSTRESS",
    "overpressure": "OVERPRESS",
    "grain_size_p50": "GRNSIZE50",
    "grain_sorting_p50": "GRNSORT50",
    "grain_coating_p50": "GRNCOAT50",
    "total_porosity_p50": "PORO50",
    "permeability_p50": "PERM50",
    "permeability_geomean": "PERMGEOM",
}


def path_for_io(path: Path) -> str:
    """Return a Windows extended-length path when required for file I/O."""
    text = str(path.resolve())
    if os.name != "nt" or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def tokenize_grdecl(path: Path, wanted: set[str]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    keyword: str | None = None
    with open(path_for_io(path), "r", encoding="utf-8") as handle:
        for raw in handle:
            # Eclipse/Petrel comments can appear after a keyword/value on the
            # same line (for example `SPECGRID -- Generated : Petrel`).
            # Remove that suffix before tokenising, rather than treating the
            # comment words as numeric data.
            line = raw.split("--", 1)[0].strip()
            if not line:
                continue
            head = line.split()[0]
            if head in wanted:
                keyword = head
                values.setdefault(keyword, [])
                rest = line[len(head) :].strip()
                if rest:
                    values[keyword].extend(rest.replace("/", " ").split())
                if "/" in line:
                    keyword = None
                continue
            if keyword:
                values[keyword].extend(line.replace("/", " ").split())
                if "/" in line:
                    keyword = None
    missing = wanted.difference(values)
    if missing:
        raise ValueError(f"{path} is missing required GRDECL keyword(s): {', '.join(sorted(missing))}")
    return values


def mapaxes_transform(mapaxes: list[float]):
    # MAPAXES is point-on-Y-axis, origin, point-on-X-axis. The GRDECL local axes
    # are expressed in metres; the vectors in this data are 1000 m reference axes.
    origin_x, origin_y = mapaxes[2], mapaxes[3]
    x_unit = ((mapaxes[4] - mapaxes[2]) / 1000.0, (mapaxes[5] - mapaxes[3]) / 1000.0)
    y_unit = ((mapaxes[0] - mapaxes[2]) / 1000.0, (mapaxes[1] - mapaxes[3]) / 1000.0)

    def transform(local_x: float, local_y: float) -> tuple[float, float]:
        return (
            origin_x + local_x * x_unit[0] + local_y * y_unit[0],
            origin_y + local_x * x_unit[1] + local_y * y_unit[1],
        )

    return transform


def grdecl_cell_centers(path: Path) -> list[tuple[float, float, float]]:
    data = tokenize_grdecl(path, {"SPECGRID", "MAPAXES", "COORD", "ZCORN"})
    nx, ny, nz = (int(float(v)) for v in data["SPECGRID"][:3])

    def expand_numeric(tokens: list[str]) -> list[float]:
        values: list[float] = []
        for token in tokens:
            if "*" in token:
                count, value = token.split("*", 1)
                values.extend([float(value)] * int(float(count)))
            else:
                values.append(float(token))
        return values

    coord = expand_numeric(data["COORD"])
    zcorn = expand_numeric(data["ZCORN"])
    mapaxes = expand_numeric(data["MAPAXES"])

    expected_coord = (nx + 1) * (ny + 1) * 6
    expected_zcorn = nx * ny * nz * 8
    if len(coord) != expected_coord:
        raise ValueError(f"{path} has {len(coord)} COORD values; expected {expected_coord}")
    if len(zcorn) != expected_zcorn:
        raise ValueError(f"{path} has {len(zcorn)} ZCORN values; expected {expected_zcorn}")

    transform = mapaxes_transform(mapaxes)

    def pillar_xy(i: int, j: int) -> tuple[float, float]:
        idx = (j * (nx + 1) + i) * 6
        return coord[idx], coord[idx + 1]

    def z_value(i: int, j: int, k: int, di: int, dj: int, dk: int) -> float:
        return zcorn[(2 * k + dk) * (2 * ny) * (2 * nx) + (2 * j + dj) * (2 * nx) + (2 * i + di)]

    centers: list[tuple[float, float, float]] = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                pillars = (pillar_xy(i, j), pillar_xy(i + 1, j), pillar_xy(i, j + 1), pillar_xy(i + 1, j + 1))
                local_x = sum(x for x, _ in pillars) / 4.0
                local_y = sum(y for _, y in pillars) / 4.0
                x, y = transform(local_x, local_y)
                z = -sum(z_value(i, j, k, di, dj, dk) for dk in (0, 1) for dj in (0, 1) for di in (0, 1)) / 8.0
                centers.append((x, y, z))
    return centers


def read_pointset(path: Path) -> tuple[list[str], list[tuple[float, float, float, list[str]]]]:
    columns: list[str] = []
    rows: list[tuple[float, float, float, list[str]]] = []
    in_header = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
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
            if in_header:
                columns.append(line.split(",", 1)[-1].strip().strip('"'))
                continue
            if line.startswith("#") or line == "VERSION 1":
                continue
            parts = line.split()
            if len(parts) != len(columns):
                raise ValueError(f"{path} data row has {len(parts)} values; expected {len(columns)}")
            if columns[:3] != ["X", "Y", "Z"]:
                raise ValueError(f"{path} must begin with X,Y,Z columns")
            rows.append((float(parts[0]), float(parts[1]), float(parts[2]), parts[3:]))
    if columns[:3] != ["X", "Y", "Z"]:
        raise ValueError(f"{path} must begin with X,Y,Z columns")
    return columns[3:], rows


def bucket_key(x: float, y: float, z: float, bucket_size: float = 0.10) -> tuple[int, int, int]:
    return (round(x / bucket_size), round(y / bucket_size), round(z / bucket_size))


def assign_points_to_cells(
    centers: list[tuple[float, float, float]],
    point_rows: list[tuple[float, float, float, list[str]]],
    tolerance: float = MATCH_TOLERANCE_M,
) -> tuple[list[list[str] | None], float]:
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for index, (x, y, z) in enumerate(centers):
        buckets[bucket_key(x, y, z)].append(index)

    attrs_by_cell: list[list[str] | None] = [None] * len(centers)
    assigned: set[int] = set()
    max_distance = 0.0
    tol2 = tolerance * tolerance

    for x, y, z, attrs in point_rows:
        base = bucket_key(x, y, z)
        best: tuple[float, int] | None = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for candidate in buckets.get((base[0] + dx, base[1] + dy, base[2] + dz), []):
                        if candidate in assigned:
                            continue
                        cx, cy, cz = centers[candidate]
                        dist2 = (cx - x) ** 2 + (cy - y) ** 2 + (cz - z) ** 2
                        if dist2 <= tol2 and (best is None or dist2 < best[0]):
                            best = (dist2, candidate)
        if best is None:
            raise ValueError(f"Could not match point ({x:.2f}, {y:.2f}, {z:.2f}) within {tolerance} m")
        dist2, cell_index = best
        assigned.add(cell_index)
        attrs_by_cell[cell_index] = attrs
        max_distance = max(max_distance, dist2**0.5)

    return attrs_by_cell, max_distance


def normalized_property_key(column: str) -> str:
    label = column.split(",", 1)[1].strip() if "," in column else column
    key = re.sub(r"[^a-z0-9]+", "_", label.strip().strip('"').lower()).strip("_")
    for unit_suffix in ("_vol", "_area", "_md", "_ma", "_c", "_m", "_mpa"):
        if key.endswith(unit_suffix):
            key = key[: -len(unit_suffix)]
    return key


def grdecl_keyword(column: str) -> str:
    key = normalized_property_key(column)
    if column in GRDECL_KEYWORD_ALIASES:
        return GRDECL_KEYWORD_ALIASES[column]
    if key in GRDECL_KEYWORD_ALIASES:
        return GRDECL_KEYWORD_ALIASES[key]
    keyword = re.sub(r"[^A-Za-z0-9_]", "_", key or column).upper()
    if not keyword:
        raise ValueError(f"Cannot convert empty column name {column!r} to GRDECL keyword")
    return keyword


def write_property(handle, keyword: str, values, values_per_line: int = 6) -> None:
    handle.write(f"\n{keyword}\n")
    line: list[str] = []
    for value in values:
        line.append(value)
        if len(line) == values_per_line:
            handle.write("  ".join(line) + "\n")
            line = []
    if line:
        handle.write("  ".join(line) + "\n")
    handle.write("/\n")


def selected_property_indices(columns: list[str], include_columns: set[str] | None = None) -> list[tuple[int, str]]:
    selected = {normalized_property_key(column) for column in include_columns or set()}
    property_indices = [(index, column) for index, column in enumerate(columns) if column.lower() not in IDENTITY_COLUMNS]
    if selected:
        property_indices = [(index, column) for index, column in property_indices if normalized_property_key(column) in selected]
    return property_indices


def append_properties(grdecl_path: Path, pointset_path: Path, output_path: Path, include_columns: set[str] | None = None) -> dict[str, int]:
    columns, point_rows = read_pointset(pointset_path)
    property_indices = selected_property_indices(columns, include_columns)
    if not property_indices:
        raise ValueError(f"{pointset_path.name} has no returned T>Map properties")
    centers = grdecl_cell_centers(grdecl_path)
    cell_index_attr = next((index for index, column in enumerate(columns) if column.lower() == "cellindex"), None)
    if cell_index_attr is not None:
        attrs_by_cell: list[list[str] | None] = [None] * len(centers)
        for _, _, _, attrs in point_rows:
            cell_index = int(float(attrs[cell_index_attr]))
            if cell_index < 0 or cell_index >= len(attrs_by_cell):
                raise ValueError(f"{pointset_path.name} has CellIndex {cell_index}; valid range is 0..{len(attrs_by_cell) - 1}")
            attrs_by_cell[cell_index] = attrs
        max_distance = 0.0
    else:
        attrs_by_cell, max_distance = assign_points_to_cells(centers, point_rows)
    matched = sum(attrs is not None for attrs in attrs_by_cell)

    Path(path_for_io(output_path.parent)).mkdir(parents=True, exist_ok=True)
    with grdecl_path.open("r", encoding="utf-8") as source, open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
        out.write(source.read().rstrip() + "\n")
        out.write("\n-- Synthetic T>Map-style properties mapped from a 3D point set.\n")
        out.write(f"-- Source point set: {pointset_path.name}\n")
        out.write(f"-- Missing cells use Continuous NoValue: {NO_VALUE}\n")
        for attr_index, column in property_indices:
            keyword = grdecl_keyword(column)
            values = (attrs[attr_index] if attrs is not None else NO_VALUE for attrs in attrs_by_cell)
            write_property(out, keyword, values)

    return {"cells": len(centers), "points": len(point_rows), "matched": matched, "properties": len(property_indices), "max_distance": max_distance}


def read_tmap_table(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read a T>Map pointset while retaining its full, arbitrary header."""
    columns: list[str] = []
    rows: list[list[str]] = []
    in_header = False
    with open(path_for_io(path), "r", encoding="utf-8", errors="ignore") as handle:
        for raw in handle:
            line = raw.strip()
            if line == "BEGIN HEADER":
                in_header = True
                continue
            if line == "END HEADER":
                in_header = False
                continue
            if in_header:
                columns.append(line.split(",", 1)[-1].strip().strip('"'))
                continue
            if not line or line.startswith("#") or line == "VERSION 1":
                continue
            values = line.split()
            if len(values) != len(columns):
                raise ValueError(f"{path.name} data row has {len(values)} values; expected {len(columns)}")
            rows.append(values)
    if columns[:3] != ["X", "Y", "Z"]:
        raise ValueError(f"{path.name} must begin with X, Y, Z columns")
    return columns, rows


def append_column_interpolated_properties(
    grdecl_path: Path,
    pointset_path: Path,
    output_path: Path,
    include_columns: set[str] | None = None,
) -> None:
    """Append sparse returned T>Map values by I/J-column vertical interpolation.

    Real returns can omit original cells and may have a different facies label.
    For this MVP their X/Y/Z locations define the column and vertical sample
    positions; `Facies` and `point_id` are retained only as return metadata and
    never overwrite the original GRDECL facies property.
    """
    columns, rows = read_tmap_table(pointset_path)
    property_indices = selected_property_indices(columns, include_columns)
    if not property_indices:
        raise ValueError(f"{pointset_path.name} has no T>Map properties to append")

    spec = tokenize_grdecl(grdecl_path, {"SPECGRID"})["SPECGRID"]
    nx, ny, _ = (int(float(value)) for value in spec[:3])
    centers = grdecl_cell_centers(grdecl_path)
    # The I/J centre coordinates are invariant through K. Use 1 m buckets so
    # decimal rounding in external T>Map exports does not break a match.
    xy_buckets: dict[tuple[int, int], list[tuple[int, int, float, float]]] = defaultdict(list)
    for j in range(ny):
        for i in range(nx):
            x, y, _ = centers[j * nx + i]
            xy_buckets[(round(x), round(y))].append((i, j, x, y))

    samples: dict[tuple[int, int], list[tuple[float, list[str]]]] = defaultdict(list)
    unmatched_xy = 0
    for row in rows:
        x, y, z = (float(row[index]) for index in range(3))
        key = (round(x), round(y))
        candidates = [
            candidate
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for candidate in xy_buckets.get((key[0] + dx, key[1] + dy), [])
        ]
        if not candidates:
            unmatched_xy += 1
            continue
        i, j, cx, cy = min(candidates, key=lambda item: (item[2] - x) ** 2 + (item[3] - y) ** 2)
        if math.hypot(cx - x, cy - y) > 2.0:
            unmatched_xy += 1
            continue
        samples[(i, j)].append((z, row))
    if not samples:
        raise ValueError(f"Could not match any returned T>Map X/Y columns to {grdecl_path.name}")
    for series in samples.values():
        series.sort(key=lambda item: item[0])

    def valid_number(value: str) -> float | None:
        try:
            number = float(value)
        except ValueError:
            return None
        return number if number not in {-999.0, -77777.0} else None

    Path(path_for_io(output_path.parent)).mkdir(parents=True, exist_ok=True)
    with open(path_for_io(grdecl_path), "r", encoding="utf-8") as source, open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
        out.write(source.read().rstrip() + "\n\n-- Sparse real T>Map properties vertically interpolated within I/J columns.\n")
        out.write(f"-- Source point set: {pointset_path.name}; {len(rows) - unmatched_xy} of {len(rows)} rows matched by X/Y.\n")
        for property_index, column in property_indices:
            values: list[str] = []
            for cell_index, (_, _, z) in enumerate(centers):
                i = cell_index % nx
                j = (cell_index // nx) % ny
                series = [
                    (sample_z, value)
                    for sample_z, sample_row in samples.get((i, j), [])
                    if (value := valid_number(sample_row[property_index])) is not None
                ]
                if not series:
                    values.append(NO_VALUE)
                    continue
                pos = bisect.bisect_left([sample_z for sample_z, _ in series], z)
                if pos == 0:
                    value = series[0][1]
                elif pos == len(series):
                    value = series[-1][1]
                else:
                    z0, value0 = series[pos - 1]
                    z1, value1 = series[pos]
                    value = value0 + (z - z0) * (value1 - value0) / (z1 - z0) if z1 != z0 else value0
                values.append(f"{value:.8g}")
            write_property(out, grdecl_keyword(column), values)


def scenario_token(path: Path) -> str:
    name = path.name
    if name.endswith(".grdecl"):
        name = name[:-7]
    name = name.replace("MinSub", "MinSubs").replace("MaxSub", "MaxSubs")
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()


def find_pointset_for_grdecl(grdecl_path: Path, pointset_dir: Path, reduced: bool = False) -> Path:
    token = scenario_token(grdecl_path)
    primary_patterns = (
        ["*_3d_pointset_control_*_tmap_synthetic", "*_3d_pointset_control_*_tmap_real*"]
        if reduced
        else ["*_3d_pointset_tmap_synthetic", "*_3d_pointset_tmap_real*", "*_3d_pointset_tmap_inferred_geocosm"]
    )
    candidates = []
    for pattern in primary_patterns:
        candidates.extend(
            p for p in pointset_dir.glob(pattern)
            if scenario_token(p).replace("ss_201_cleaned_5", "ss_201_5").startswith(token)
        )
    if not candidates:
        # Legacy fallback for existing synthetic files; new exports use _3d_pointset.
        candidates = [
            p for p in pointset_dir.glob("*_tmap_*")
            if scenario_token(p).replace("ss_201_cleaned_5", "ss_201_5").startswith(token)
        ]
    if not candidates:
        # Fallback to the scenario suffix, e.g. "1_Base" or "4_MinSupply".
        parts = token.split("_fsm_fdm_")
        suffix = parts[-1] if len(parts) > 1 else token
        candidates = [p for p in pointset_dir.glob(f"*{suffix}*_3d_pointset_tmap_*")]
        if not candidates:
            candidates = [p for p in pointset_dir.glob(f"*{suffix}*_tmap_*")]
    if len(candidates) != 1:
        raise ValueError(f"Could not uniquely match {grdecl_path.name} to a point set; candidates: {[p.name for p in candidates]}")
    return candidates[0]


def append_interpolated_properties(
    grdecl_path: Path,
    pointset_path: Path,
    output_path: Path,
    facies_property: str,
    include_columns: set[str] | None = None,
) -> None:
    """Append sparse Best-fit results by vertical interpolation within facies/I/J columns."""
    raw_columns, _ = read_tmap_table(pointset_path)
    if "CellIndex" not in raw_columns:
        append_column_interpolated_properties(grdecl_path, pointset_path, output_path, include_columns)
        return
    columns, rows = read_pointset(pointset_path)
    cell_index_attr = next((index for index, column in enumerate(columns) if column.lower() == "cellindex"), None)
    if cell_index_attr is None:
        raise ValueError(f"{pointset_path.name} must retain CellIndex after Facies for reduced Best-fit interpolation")
    property_indices = selected_property_indices(columns, include_columns)
    if not property_indices:
        raise ValueError(f"{pointset_path.name} has no returned T>Map properties")
    table = defaultdict(list)
    for x, y, z, attrs in rows:
        # read_pointset returns attributes beginning with CellIndex. Facies is in
        # the original row header and is recovered below from a dedicated parse.
        pass
    raw_columns = []
    raw_rows = []
    in_header = False
    with open(path_for_io(pointset_path), "r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if line == "BEGIN HEADER": in_header = True; continue
            if line == "END HEADER": in_header = False; continue
            if in_header: raw_columns.append(line.split(",", 1)[-1].strip().strip('"')); continue
            if not line or line.startswith("#") or line == "VERSION 1": continue
            raw_rows.append(line.split())
    for parts in raw_rows:
        facies_index = next(index for index, column in enumerate(raw_columns) if column.lower() == "facies")
        x, y, z = map(float, parts[:3])
        facies = int(float(parts[facies_index]))
        table[(facies, f"{x:.2f}", f"{y:.2f}")].append((z, parts))
    for series in table.values(): series.sort(key=lambda item: item[0])
    centers = grdecl_cell_centers(grdecl_path)
    facies_values = [int(float(value)) for value in tokenize_grdecl(grdecl_path, {facies_property})[facies_property] for value in ([value.split('*', 1)[1]] * int(value.split('*', 1)[0]) if '*' in value else [value])]
    Path(path_for_io(output_path.parent)).mkdir(parents=True, exist_ok=True)
    with grdecl_path.open("r", encoding="utf-8") as source, open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
        out.write(source.read().rstrip() + "\n\n-- T>Map properties vertically interpolated from reduced Best-fit points.\n")
        for attr_index, column in property_indices:
            values = []
            for (x, y, z), facies in zip(centers, facies_values):
                series = table.get((facies, f"{x:.2f}", f"{y:.2f}"))
                if not series: values.append(NO_VALUE); continue
                zs = [item[0] for item in series]; pos = bisect.bisect_left(zs, z)
                raw_index = attr_index + 3
                if pos == 0: value = series[0][1][raw_index]
                elif pos == len(zs): value = series[-1][1][raw_index]
                else:
                    z0, a0 = series[pos - 1]; z1, a1 = series[pos]
                    value = f"{float(a0[raw_index]) + (z-z0)/(z1-z0)*(float(a1[raw_index])-float(a0[raw_index])):.6g}"
                values.append(value)
            write_property(out, grdecl_keyword(column), values)


def main() -> None:
    parser = argparse.ArgumentParser(description="Append Best-fit T>Map point-set properties to matching GRDECL grids.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--pointset-dir", type=Path, default=DEFAULT_POINTSET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--single-grdecl", type=Path, help="Append properties to only this GRDECL file.")
    parser.add_argument("--single-pointset", type=Path, help="Point set to use with --single-grdecl.")
    parser.add_argument("--vertical-interpolate", action="store_true", help="Interpolate sparse reduced Best-fit point-set results vertically within facies/I/J columns.")
    parser.add_argument("--property", default="Facies", help="Facies keyword used for reduced Best-fit interpolation.")
    parser.add_argument("--include-columns", nargs="+", help="Returned T>Map property columns to append. Defaults to all non-identity columns.")
    args = parser.parse_args()
    include_columns = set(args.include_columns) if args.include_columns else None

    if args.single_grdecl:
        if not args.single_pointset:
            raise SystemExit("--single-pointset is required with --single-grdecl")
        grdecls = [(args.single_grdecl, args.single_pointset)]
    else:
        source_grdecls = sorted(path for path in args.grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
        grdecls = [(path, find_pointset_for_grdecl(path, args.pointset_dir, args.vertical_interpolate)) for path in source_grdecls]

    for grdecl_path, pointset_path in grdecls:
        if "_tmap_synthetic" in pointset_path.name:
            provenance = "_synthetic"
        elif "_tmap_inferred_geocosm" in pointset_path.name:
            provenance = "_inferred_geocosm"
        else:
            provenance = ""
        output_name = grdecl_path.with_suffix("").name + f"_with{provenance}_tmap_properties.grdecl"
        output_path = args.output_dir / output_name
        if args.vertical_interpolate:
            append_interpolated_properties(grdecl_path, pointset_path, output_path, args.property, include_columns)
            print(f"{grdecl_path.name} <- {pointset_path.name}: vertically interpolated -> {output_path}")
            continue
        stats = append_properties(grdecl_path, pointset_path, output_path, include_columns)
        print(
            f"{grdecl_path.name} <- {pointset_path.name}: "
            f"{stats['matched']}/{stats['cells']} cells populated, {stats['properties']} properties, "
            f"max match distance {stats['max_distance']:.3f} m -> {output_path}"
        )


if __name__ == "__main__":
    main()
