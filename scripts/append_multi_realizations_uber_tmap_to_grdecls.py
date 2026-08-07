from __future__ import annotations

import argparse
import bisect
from collections import defaultdict
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, grdecl_keyword, path_for_io, tokenize_grdecl, write_property


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "input" / "source_grdecls_from_dionisosflow"
DEFAULT_POINTSET_DIR = ROOT / "outputs" / "Multi-realization Uber approach" / "02_uber_pointsets_with_tmap_data"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "Multi-realization Uber approach" / "03_augmented_grdecls_from_uber_lookup"
NO_VALUE = "-77777"


def expanded_facies_values(path: Path, keyword: str = "Facies") -> list[int]:
    values = tokenize_grdecl(path, {keyword})[keyword]
    expanded: list[int] = []
    for value in values:
        if "*" in value:
            count_text, repeated = value.split("*", 1)
            expanded.extend([int(float(repeated))] * int(count_text))
        else:
            expanded.append(int(float(value)))
    return expanded


def read_uber_tmap_pointsets(pointset_dir: Path):
    property_columns: list[str] | None = None
    table = defaultdict(lambda: defaultdict(list))

    for path in sorted(pointset_dir.glob("*_tmap_synthetic")):
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
                if columns[:4] != ["X", "Y", "Z", "Facies"]:
                    raise ValueError(f"{path.name} must contain X,Y,Z,Facies before T>Map properties")
                if property_columns is None:
                    property_columns = columns[4:]
                elif property_columns != columns[4:]:
                    raise ValueError(f"{path.name} has different property columns from previous Uber point sets")
                parts = line.split()
                x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                facies = int(float(parts[3]))
                table[facies][(f"{x:.2f}", f"{y:.2f}")].append((z, parts[4:]))

    if property_columns is None:
        raise SystemExit(f"No Uber T>Map point sets found in {pointset_dir}")

    for xy_table in table.values():
        for values in xy_table.values():
            values.sort(key=lambda item: item[0])
    return property_columns, table


def interpolate(values: list[tuple[float, list[str]]], z: float, attr_index: int, no_extrapolate: bool) -> str:
    zs = [item[0] for item in values]
    pos = bisect.bisect_left(zs, z)
    if pos < len(zs) and abs(zs[pos] - z) < 1e-9:
        return values[pos][1][attr_index]
    if pos == 0:
        return NO_VALUE if no_extrapolate else values[0][1][attr_index]
    if pos == len(zs):
        return NO_VALUE if no_extrapolate else values[-1][1][attr_index]

    z0, attrs0 = values[pos - 1]
    z1, attrs1 = values[pos]
    v0 = float(attrs0[attr_index])
    v1 = float(attrs1[attr_index])
    fraction = (z - z0) / (z1 - z0)
    return f"{v0 + fraction * (v1 - v0):.6g}"


def append_to_grdecls(grdecl_dir: Path, pointset_dir: Path, output_dir: Path, no_extrapolate: bool, facies_property: str) -> None:
    property_columns, table = read_uber_tmap_pointsets(pointset_dir)
    Path(path_for_io(output_dir)).mkdir(parents=True, exist_ok=True)

    grdecls = sorted(path for path in grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
    for realization_index, grdecl_path in enumerate(grdecls, start=1):
        print(f"PROGRESS {realization_index}/{len(grdecls)} Appending to {grdecl_path.name}", flush=True)
        centers = grdecl_cell_centers(grdecl_path)
        facies_values = expanded_facies_values(grdecl_path, facies_property)
        if len(centers) != len(facies_values):
            raise ValueError(f"{grdecl_path.name}: {len(centers)} centres but {len(facies_values)} facies values")

        per_cell_series = []
        for (x, y, z), facies in zip(centers, facies_values):
            per_cell_series.append((z, table.get(facies, {}).get((f"{x:.2f}", f"{y:.2f}"))))

        output_path = output_dir / f"{grdecl_path.with_suffix('').name}_with_uber_tmap_properties.grdecl"
        Path(path_for_io(output_path.parent)).mkdir(parents=True, exist_ok=True)
        with grdecl_path.open("r", encoding="utf-8") as source, open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
            out.write(source.read().rstrip() + "\n")
            out.write("\n-- T>Map-style properties interpolated from Uber facies point sets.\n")
            out.write(f"-- Source point-set folder: {pointset_dir}\n")
            out.write(f"-- Missing cells use Continuous NoValue: {NO_VALUE}\n")
            for attr_index, column in enumerate(property_columns):
                values = (
                    interpolate(series, z, attr_index, no_extrapolate) if series else NO_VALUE
                    for z, series in per_cell_series
                )
                write_property(out, grdecl_keyword(column), values)
        missing_series = sum(1 for _, series in per_cell_series if not series)
        print(f"{grdecl_path.name}: missing XY/facies series for {missing_series}/{len(centers)} cells -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Interpolate Uber T>Map point-set properties back to source GRDECL cells.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--pointset-dir", type=Path, default=DEFAULT_POINTSET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--property", default="Facies", help="GRDECL facies property keyword (case-sensitive).")
    parser.add_argument("--no-extrapolate", action="store_true", help="Use -77777 outside Uber Z range instead of nearest-level values.")
    args = parser.parse_args()
    append_to_grdecls(args.grdecl_dir, args.pointset_dir, args.output_dir, args.no_extrapolate, args.property)


if __name__ == "__main__":
    main()
