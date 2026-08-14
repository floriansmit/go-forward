from __future__ import annotations

import argparse
import bisect
from collections import defaultdict
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, grdecl_keyword, path_for_io, tokenize_grdecl, write_property


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "input" / "source_grdecls_from_dionisosflow"
DEFAULT_POINTSET_DIR = ROOT / "outputs" / "Multi-realization control approach" / "02_control_pointsets_with_tmap_data"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "Multi-realization control approach" / "03_augmented_grdecls_from_control_interpolation"
NO_VALUE = "-77777"
IDENTITY_COLUMNS = {"x", "y", "z", "facies", "realization", "cellindex", "point_id", "pointid", "controlcolumn"}


def is_pointset_file(path: Path) -> bool:
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


def tmap_pointset_files(pointset_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in pointset_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() not in {".md", ".xml", ".json", ".png", ".jpg", ".jpeg"}
        and is_pointset_file(path)
    )


def dimensions(path: Path) -> tuple[int, int, int]:
    specgrid = tokenize_grdecl(path, {"SPECGRID"})["SPECGRID"]
    return tuple(int(float(v)) for v in specgrid[:3])


def expanded_facies(path: Path, keyword: str) -> list[int]:
    values = tokenize_grdecl(path, {keyword})[keyword]
    expanded: list[int] = []
    for value in values:
        if "*" in value:
            count, repeated = value.split("*", 1)
            expanded.extend([int(float(repeated))] * int(count))
        else:
            expanded.append(int(float(value)))
    return expanded


def read_control_pointsets(pointset_dir: Path):
    properties: list[str] = []
    table = defaultdict(list)
    found_any = False
    for path in tmap_pointset_files(pointset_dir):
        found_any = True
        columns: list[str] = []
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
                    columns.append(line.split(",", 1)[-1].strip().strip('"'))
                    continue
                if line.startswith("#") or line == "VERSION 1":
                    continue
                parts = line.split()
                if columns[:5] == ["X", "Y", "Z", "Facies", "ControlColumn"]:
                    property_start = 5
                    realization = 0  # shared realization-envelope control series
                elif columns[:6] == ["X", "Y", "Z", "Facies", "Realization", "CellIndex"]:
                    # Backward compatibility with pre-envelope control pointsets.
                    property_start = 6
                    realization = int(float(parts[4]))
                else:
                    raise ValueError(
                        f"{path.name} must contain X,Y,Z,Facies,ControlColumn before T>Map properties "
                        "(or the legacy Realization,CellIndex fields)"
                    )
                property_indices = [(index, column) for index, column in enumerate(columns) if index >= property_start and column.lower() not in IDENTITY_COLUMNS]
                for _, column in property_indices:
                    if column not in properties:
                        properties.append(column)
                x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                facies = int(float(parts[3]))
                key = (realization, facies, f"{x:.2f}", f"{y:.2f}")
                table[key].append((z, {column: parts[index] for index, column in property_indices}))
    if not found_any:
        raise SystemExit(f"No control T>Map point sets found in {pointset_dir}")
    for values in table.values():
        values.sort(key=lambda item: item[0])
    return properties, table


def interpolate(series, z: float, column: str, no_extrapolate: bool) -> str:
    available = [(sample_z, attrs[column]) for sample_z, attrs in series if column in attrs]
    if not available:
        return NO_VALUE
    zs = [item[0] for item in available]
    pos = bisect.bisect_left(zs, z)
    if pos < len(zs) and abs(zs[pos] - z) < 1e-9:
        return available[pos][1]
    if pos == 0:
        return NO_VALUE if no_extrapolate else available[0][1]
    if pos == len(zs):
        return NO_VALUE if no_extrapolate else available[-1][1]
    z0, value0 = available[pos - 1]
    z1, value1 = available[pos]
    if abs(z1 - z0) < 1e-12:
        return value0
    fraction = (z - z0) / (z1 - z0)
    return f"{float(value0) + fraction * (float(value1) - float(value0)):.6g}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Append reduced control-point T>Map properties to GRDECLs using vertical interpolation.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--pointset-dir", type=Path, default=DEFAULT_POINTSET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--property", default="Facies", help="GRDECL facies property keyword (case-sensitive).")
    parser.add_argument("--no-extrapolate", action="store_true")
    args = parser.parse_args()

    properties, table = read_control_pointsets(args.pointset_dir)
    Path(path_for_io(args.output_dir)).mkdir(parents=True, exist_ok=True)
    grdecls = sorted(path for path in args.grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
    for realization_index, grdecl in enumerate(grdecls, start=1):
        print(f"PROGRESS {realization_index}/{len(grdecls)} Appending to {grdecl.name}", flush=True)
        centers = grdecl_cell_centers(grdecl)
        facies_values = expanded_facies(grdecl, args.property)
        output_path = args.output_dir / f"{grdecl.with_suffix('').name}_with_control_interpolated_tmap_properties.grdecl"
        Path(path_for_io(output_path.parent)).mkdir(parents=True, exist_ok=True)
        with grdecl.open("r", encoding="utf-8") as source, open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
            out.write(source.read().rstrip() + "\n")
            out.write("\n-- T>Map properties interpolated from reduced facies control point sets.\n")
            out.write(f"-- Source point-set folder: {args.pointset_dir}\n")
            out.write(f"-- Missing cells use Continuous NoValue: {NO_VALUE}\n")
            for column in properties:
                values = []
                for (x, y, z), facies in zip(centers, facies_values):
                    # New shared-envelope controls are keyed with realization 0
                    # and apply to every source realization.  Legacy pointsets
                    # retain their realization-specific lookup as a fallback.
                    series = table.get((0, facies, f"{x:.2f}", f"{y:.2f}")) or table.get(
                        (realization_index, facies, f"{x:.2f}", f"{y:.2f}")
                    )
                    values.append(interpolate(series, z, column, args.no_extrapolate) if series else NO_VALUE)
                write_property(out, grdecl_keyword(column), values)
        print(f"{grdecl.name} -> {output_path}")


if __name__ == "__main__":
    main()
