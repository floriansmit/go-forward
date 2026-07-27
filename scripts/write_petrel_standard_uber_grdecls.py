from __future__ import annotations

import argparse
from pathlib import Path

from append_multi_realizations_uber_tmap_to_grdecls import (
    DEFAULT_GRDECL_DIR,
    DEFAULT_POINTSET_DIR,
    NO_VALUE,
    expanded_facies_values,
    interpolate,
    read_uber_tmap_pointsets,
)
from grdecl_utils import grdecl_cell_centers, path_for_io


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "Multi-realization Uber approach" / "04_petrel_standard_grdecls_from_uber_lookup"
PETREL_PROPERTY_COLUMNS = (
    ("total_porosity_mean", "PORO", "total_porosity_mean"),
    ("total_porosity_stdev", "POROSTD", "total_porosity_stdev"),
    ("total_porosity_p10", "PORO10", "total_porosity_p10"),
    ("total_porosity_p50", "PORO50", "total_porosity_p50"),
    ("total_porosity_p90", "PORO90", "total_porosity_p90"),
    ("permeability_mean", "PERMMEAN", "permeability_mean"),
    ("permeability_stdev", "PERMSTD", "permeability_stdev"),
    ("permeability_p10", "PERM10", "permeability_p10"),
    ("permeability_p50", "PERM50", "permeability_p50"),
    ("permeability_p90", "PERM90", "permeability_p90"),
)
PERMEABILITY_MEAN_COLUMN = "permeability_mean"


def write_petrel_property(handle, keyword: str, property_name: str, values, values_per_line: int = 6) -> None:
    handle.write(f"\n{keyword:<39}-- Generated : Petrel-compatible export\n")
    handle.write(f"-- Property name in Petrel : {property_name}\n")
    line: list[str] = []
    for value in values:
        line.append(value)
        if len(line) == values_per_line:
            handle.write("  ".join(line) + "\n")
            line = []
    if line:
        handle.write("  ".join(line) + "\n")
    handle.write("/\n")


def without_keyword_block(text: str, keyword: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        head = stripped.split()[0] if stripped else ""
        if not skipping and head == keyword:
            skipping = "/" not in stripped
            continue
        if skipping:
            if "/" in stripped:
                skipping = False
            continue
        kept.append(line)
    return "\n".join(kept).rstrip()


def interpolated_property_values(
    centers: list[tuple[float, float, float]],
    facies_values: list[int],
    table,
    property_columns: list[str],
    no_extrapolate: bool,
) -> tuple[dict[str, list[str]], int]:
    attr_indices = {column: property_columns.index(column) for column, _, _ in PETREL_PROPERTY_COLUMNS}
    values_by_column = {column: [] for column, _, _ in PETREL_PROPERTY_COLUMNS}
    missing_series = 0

    for (x, y, z), facies in zip(centers, facies_values):
        series = table.get(facies, {}).get((f"{x:.2f}", f"{y:.2f}"))
        if not series:
            for values in values_by_column.values():
                values.append(NO_VALUE)
            missing_series += 1
            continue
        for column, values in values_by_column.items():
            values.append(interpolate(series, z, attr_indices[column], no_extrapolate))

    return values_by_column, missing_series


def write_petrel_standard_grdecls(grdecl_dir: Path, pointset_dir: Path, output_dir: Path, no_extrapolate: bool) -> None:
    property_columns, table = read_uber_tmap_pointsets(pointset_dir)
    required_columns = [column for column, _, _ in PETREL_PROPERTY_COLUMNS]
    missing_columns = [column for column in required_columns if column not in property_columns]
    if missing_columns:
        raise ValueError(f"Uber T>Map point sets are missing required column(s): {', '.join(missing_columns)}")

    Path(path_for_io(output_dir)).mkdir(parents=True, exist_ok=True)
    for grdecl_path in sorted(grdecl_dir.glob("*.grdecl")):
        centers = grdecl_cell_centers(grdecl_path)
        facies_values = expanded_facies_values(grdecl_path)
        if len(centers) != len(facies_values):
            raise ValueError(f"{grdecl_path.name}: {len(centers)} centres but {len(facies_values)} facies values")

        values_by_column, missing_series = interpolated_property_values(
            centers, facies_values, table, property_columns, no_extrapolate
        )
        permeability_mean_values = values_by_column[PERMEABILITY_MEAN_COLUMN]

        output_path = output_dir / f"{grdecl_path.with_suffix('').name}_with_uber_petrel_standard_properties.grdecl"
        with grdecl_path.open("r", encoding="utf-8") as source, open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
            out.write(without_keyword_block(source.read(), "Facies") + "\n")
            out.write("\n-- Petrel/Eclipse-standard properties interpolated from Uber facies point sets.\n")
            out.write("-- FACIES is copied from the original DionisosFlow/Petrel Facies keyword.\n")
            out.write("-- PORO is total_porosity_mean; PORO10/PORO50/PORO90 and POROSTD carry uncertainty summaries.\n")
            out.write("-- PERMMEAN is permeability_mean; PERM10/PERM50/PERM90 and PERMSTD carry uncertainty summaries.\n")
            out.write("-- PERMX, PERMY, and PERMZ are permeability_mean copied into each principal direction for Petrel/Eclipse compatibility.\n")
            out.write(f"-- Source point-set folder: {pointset_dir}\n")
            out.write(f"-- Missing cells use Continuous NoValue: {NO_VALUE}\n")
            facies_text = [str(value) for value in facies_values]
            write_petrel_property(out, "FACIES", "Facies", facies_text)
            write_petrel_property(out, "SATNUM", "Facies_as_SATNUM", facies_text)
            write_petrel_property(out, "ROCK", "Facies_as_ROCK", facies_text)
            write_petrel_property(out, "FIPNUM", "Facies_as_FIPNUM", facies_text)
            for column, keyword, property_name in PETREL_PROPERTY_COLUMNS:
                write_petrel_property(out, keyword, property_name, values_by_column[column])
            write_petrel_property(out, "PERMX", "permeability_mean_X", permeability_mean_values)
            write_petrel_property(out, "PERMY", "permeability_mean_Y", permeability_mean_values)
            write_petrel_property(out, "PERMZ", "permeability_mean_Z", permeability_mean_values)

        print(f"{grdecl_path.name}: missing XY/facies series for {missing_series}/{len(centers)} cells -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write Petrel/Eclipse-standard Uber GRDECLs with mean, P10/P50/P90, and standard-deviation properties."
    )
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--pointset-dir", type=Path, default=DEFAULT_POINTSET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-extrapolate", action="store_true", help="Use -77777 outside Uber Z range instead of nearest-level values.")
    args = parser.parse_args()
    write_petrel_standard_grdecls(args.grdecl_dir, args.pointset_dir, args.output_dir, args.no_extrapolate)


if __name__ == "__main__":
    main()
