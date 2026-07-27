from __future__ import annotations

import argparse
import bisect
import os
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "input" / "source_grdecls_from_dionisosflow"
DEFAULT_POINTSET_DIR = ROOT / "outputs" / "Best-fit approach" / "02_3d_points_with_tmap_data"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "Best-fit approach" / "03_augmented_grdecls_with_tmap_data"
NO_VALUE = "-77777"
MATCH_TOLERANCE_M = 0.05
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
            line = raw.strip()
            if not line or line.startswith("--"):
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
    coord = [float(v) for v in data["COORD"]]
    zcorn = [float(v) for v in data["ZCORN"]]
    mapaxes = [float(v) for v in data["MAPAXES"]]

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
    with path.open("r", encoding="utf-8") as handle:
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
                columns.append(line.split(",", 1)[-1])
                continue
            if line.startswith("#") or line == "VERSION 1":
                continue
            parts = line.split()
            if len(parts) != len(columns):
                raise ValueError(f"{path} data row has {len(parts)} values; expected {len(columns)}")
            rows.append((float(parts[0]), float(parts[1]), float(parts[2]), parts[4:]))
    if columns[:4] != ["X", "Y", "Z", "Facies"]:
        raise ValueError(f"{path} has unexpected leading columns: {columns[:4]}")
    return columns[4:], rows


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


def grdecl_keyword(column: str) -> str:
    if column in GRDECL_KEYWORD_ALIASES:
        return GRDECL_KEYWORD_ALIASES[column]
    keyword = re.sub(r"[^A-Za-z0-9_]", "_", column).upper()
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


def append_properties(grdecl_path: Path, pointset_path: Path, output_path: Path) -> dict[str, int]:
    columns, point_rows = read_pointset(pointset_path)
    centers = grdecl_cell_centers(grdecl_path)
    attrs_by_cell, max_distance = assign_points_to_cells(centers, point_rows)
    matched = sum(attrs is not None for attrs in attrs_by_cell)

    Path(path_for_io(output_path.parent)).mkdir(parents=True, exist_ok=True)
    with grdecl_path.open("r", encoding="utf-8") as source, open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
        out.write(source.read().rstrip() + "\n")
        out.write("\n-- Synthetic T>Map-style properties mapped from a 3D point set.\n")
        out.write(f"-- Source point set: {pointset_path.name}\n")
        out.write(f"-- Missing cells use Continuous NoValue: {NO_VALUE}\n")
        for attr_index, column in enumerate(columns):
            keyword = grdecl_keyword(column)
            values = (attrs[attr_index] if attrs is not None else NO_VALUE for attrs in attrs_by_cell)
            write_property(out, keyword, values)

    return {"cells": len(centers), "points": len(point_rows), "matched": matched, "properties": len(columns), "max_distance": max_distance}


def scenario_token(path: Path) -> str:
    name = path.name
    if name.endswith(".grdecl"):
        name = name[:-7]
    name = name.replace("MinSub", "MinSubs").replace("MaxSub", "MaxSubs")
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()


def find_pointset_for_grdecl(grdecl_path: Path, pointset_dir: Path, reduced: bool = False) -> Path:
    token = scenario_token(grdecl_path)
    candidates = [
        p
        for p in pointset_dir.glob("*_3d_pointset_control_*_tmap_synthetic" if reduced else "*_3d_pointset_tmap_synthetic")
        if scenario_token(p).replace("ss_201_cleaned_5", "ss_201_5").startswith(token)
    ]
    if not candidates:
        # Legacy fallback for existing synthetic files; new exports use _3d_pointset.
        candidates = [p for p in pointset_dir.glob("*_tmap_synthetic") if scenario_token(p).replace("ss_201_cleaned_5", "ss_201_5").startswith(token)]
    if not candidates:
        # Fallback to the scenario suffix, e.g. "1_Base" or "4_MinSupply".
        parts = token.split("_fsm_fdm_")
        suffix = parts[-1] if len(parts) > 1 else token
        candidates = [p for p in pointset_dir.glob(f"*{suffix}*_3d_pointset_tmap_synthetic")]
        if not candidates:
            candidates = [p for p in pointset_dir.glob(f"*{suffix}*_tmap_synthetic")]
    if len(candidates) != 1:
        raise ValueError(f"Could not uniquely match {grdecl_path.name} to a point set; candidates: {[p.name for p in candidates]}")
    return candidates[0]


def append_interpolated_properties(grdecl_path: Path, pointset_path: Path, output_path: Path, facies_property: str) -> None:
    """Append sparse Best-fit results by vertical interpolation within facies/I/J columns."""
    columns, rows = read_pointset(pointset_path)
    if not columns or columns[0] != "CellIndex":
        raise ValueError(f"{pointset_path.name} must retain CellIndex after Facies for reduced Best-fit interpolation")
    properties = columns[1:]
    if not properties:
        raise ValueError(f"{pointset_path.name} has no returned T>Map properties")
    table = defaultdict(list)
    for x, y, z, attrs in rows:
        # read_pointset returns attributes beginning with CellIndex. Facies is in
        # the original row header and is recovered below from a dedicated parse.
        pass
    raw_columns = []
    raw_rows = []
    in_header = False
    with pointset_path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line == "BEGIN HEADER": in_header = True; continue
            if line == "END HEADER": in_header = False; continue
            if in_header: raw_columns.append(line.split(",", 1)[-1]); continue
            if not line or line.startswith("#") or line == "VERSION 1": continue
            raw_rows.append(line.split())
    for parts in raw_rows:
        facies = int(float(parts[3])); x, y, z = map(float, parts[:3])
        table[(facies, f"{x:.2f}", f"{y:.2f}")].append((z, parts[5:]))
    for series in table.values(): series.sort(key=lambda item: item[0])
    centers = grdecl_cell_centers(grdecl_path)
    facies_values = [int(float(value)) for value in tokenize_grdecl(grdecl_path, {facies_property})[facies_property] for value in ([value.split('*', 1)[1]] * int(value.split('*', 1)[0]) if '*' in value else [value])]
    Path(path_for_io(output_path.parent)).mkdir(parents=True, exist_ok=True)
    with grdecl_path.open("r", encoding="utf-8") as source, open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
        out.write(source.read().rstrip() + "\n\n-- T>Map properties vertically interpolated from reduced Best-fit points.\n")
        for attr_index, column in enumerate(properties):
            values = []
            for (x, y, z), facies in zip(centers, facies_values):
                series = table.get((facies, f"{x:.2f}", f"{y:.2f}"))
                if not series: values.append(NO_VALUE); continue
                zs = [item[0] for item in series]; pos = bisect.bisect_left(zs, z)
                if pos == 0: value = series[0][1][attr_index]
                elif pos == len(zs): value = series[-1][1][attr_index]
                else:
                    z0, a0 = series[pos - 1]; z1, a1 = series[pos]
                    value = f"{float(a0[attr_index]) + (z-z0)/(z1-z0)*(float(a1[attr_index])-float(a0[attr_index])):.6g}"
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
    args = parser.parse_args()

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
            append_interpolated_properties(grdecl_path, pointset_path, output_path, args.property)
            print(f"{grdecl_path.name} <- {pointset_path.name}: vertically interpolated -> {output_path}")
            continue
        stats = append_properties(grdecl_path, pointset_path, output_path)
        print(
            f"{grdecl_path.name} <- {pointset_path.name}: "
            f"{stats['matched']}/{stats['cells']} cells populated, {stats['properties']} properties, "
            f"max match distance {stats['max_distance']:.3f} m -> {output_path}"
        )


if __name__ == "__main__":
    main()
