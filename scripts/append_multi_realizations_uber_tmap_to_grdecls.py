from __future__ import annotations

import argparse
import bisect
from collections import defaultdict
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, grdecl_keyword, path_for_io, tokenize_grdecl, write_property
from append_best_fit_tmap_to_grdecls import normalized_property_key


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "0_original_grdecl"
DEFAULT_POINTSET_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "Multi-realization Uber approach" / "02_uber_pointsets_with_tmap_data"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "Multi-realization Uber approach" / "03_augmented_grdecls_from_uber_lookup"
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


def selected_property_indices(columns: list[str], include_columns: set[str] | None = None) -> list[tuple[int, str]]:
    selected = {normalized_property_key(column) for column in include_columns or set()}
    property_indices = [(index, column) for index, column in enumerate(columns) if column.lower() not in IDENTITY_COLUMNS]
    if selected:
        property_indices = [(index, column) for index, column in property_indices if normalized_property_key(column) in selected]
    return property_indices


def read_uber_tmap_pointsets(pointset_dir: Path, include_columns: set[str] | None = None):
    property_columns: list[str] = []
    table = defaultdict(lambda: defaultdict(list))
    found_any = False
    file_facies: dict[str, set[int]] = {}

    for path in tmap_pointset_files(pointset_dir):
        found_any = True
        columns: list[str] = []
        in_header = False
        facies_in_file: set[int] = set()
        with open(path_for_io(path), "r", encoding="utf-8", errors="replace") as handle:
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
                if columns[:3] != ["X", "Y", "Z"] or "Facies" not in columns:
                    raise ValueError(f"{path.name} must contain X,Y,Z and a Facies column")
                facies_index = columns.index("Facies")
                property_indices = selected_property_indices(columns, include_columns)
                for _, column in property_indices:
                    if column not in property_columns:
                        property_columns.append(column)
                parts = line.split()
                x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                facies = int(float(parts[facies_index]))
                facies_in_file.add(facies)
                table[facies][(f"{x:.2f}", f"{y:.2f}")].append((z, {column: parts[index] for index, column in property_indices}))
        file_facies[path.name] = facies_in_file

    if not found_any:
        raise SystemExit(f"No Uber T>Map point sets found in {pointset_dir}")

    for filename, facies_codes in file_facies.items():
        if len(facies_codes) > 1:
            facies_text = ", ".join(str(code) for code in sorted(facies_codes))
            print(f"{filename}: detected combined Uber T>Map export with facies {facies_text}", flush=True)
        elif facies_codes:
            facies = next(iter(facies_codes))
            print(f"{filename}: detected single-facies Uber T>Map export for facies {facies}", flush=True)
        else:
            print(f"{filename}: no data rows found", flush=True)

    for xy_table in table.values():
        for values in xy_table.values():
            values.sort(key=lambda item: item[0])
    return property_columns, table


def interpolate(values: list[tuple[float, dict[str, str]]], z: float, column: str, no_extrapolate: bool) -> str:
    available = [(sample_z, attrs[column]) for sample_z, attrs in values if column in attrs]
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
    v0 = float(value0)
    v1 = float(value1)
    fraction = (z - z0) / (z1 - z0)
    return f"{v0 + fraction * (v1 - v0):.6g}"


def append_to_grdecls(
    grdecl_dir: Path,
    pointset_dir: Path,
    output_dir: Path,
    no_extrapolate: bool,
    facies_property: str,
    include_columns: set[str] | None = None,
) -> None:
    property_columns, table = read_uber_tmap_pointsets(pointset_dir, include_columns)
    if not property_columns:
        raise ValueError("No selected Uber T>Map properties were found")
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
            for column in property_columns:
                values = (
                    interpolate(series, z, column, no_extrapolate) if series else NO_VALUE
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
    parser.add_argument("--include-columns", nargs="+", help="Returned T>Map property columns to append. Defaults to all non-identity columns.")
    args = parser.parse_args()
    append_to_grdecls(
        args.grdecl_dir,
        args.pointset_dir,
        args.output_dir,
        args.no_extrapolate,
        args.property,
        set(args.include_columns) if args.include_columns else None,
    )


if __name__ == "__main__":
    main()
