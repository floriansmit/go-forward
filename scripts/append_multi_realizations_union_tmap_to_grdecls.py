from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from grdecl_utils import grdecl_keyword, path_for_io, tokenize_grdecl, write_property


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "input" / "source_grdecls_from_dionisosflow"
DEFAULT_POINTSET_DIR = ROOT / "outputs" / "Multi-realization union approach" / "02_union_pointsets_with_tmap_data"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "Multi-realization union approach" / "03_augmented_grdecls_from_union_lookup"
NO_VALUE = "-77777"


def cell_count(grdecl_path: Path) -> int:
    specgrid = tokenize_grdecl(grdecl_path, {"SPECGRID"})["SPECGRID"]
    nx, ny, nz = (int(float(v)) for v in specgrid[:3])
    return nx * ny * nz


def read_union_tmap_pointsets(pointset_dir: Path) -> tuple[list[str], dict[int, dict[int, list[str]]]]:
    attrs_by_realization: dict[int, dict[int, list[str]]] = defaultdict(dict)
    property_columns: list[str] | None = None

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
                    columns.append(line.split(",", 1)[-1])
                    continue
                if line.startswith("#") or line == "VERSION 1":
                    continue

                if columns[:6] != ["X", "Y", "Z", "Facies", "Realization", "CellIndex"]:
                    raise ValueError(f"{path.name} must contain X,Y,Z,Facies,Realization,CellIndex before T>Map properties")
                if property_columns is None:
                    property_columns = columns[6:]
                elif property_columns != columns[6:]:
                    raise ValueError(f"{path.name} has different property columns from previous union point sets")

                parts = line.split()
                realization = int(float(parts[4]))
                cell_index = int(float(parts[5]))
                attrs_by_realization[realization][cell_index] = parts[6:]

    if property_columns is None:
        raise SystemExit(f"No union T>Map point sets found in {pointset_dir}")
    return property_columns, attrs_by_realization


def append_to_grdecls(grdecl_dir: Path, pointset_dir: Path, output_dir: Path) -> None:
    grdecls = sorted(path for path in grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
    property_columns, attrs_by_realization = read_union_tmap_pointsets(pointset_dir)
    Path(path_for_io(output_dir)).mkdir(parents=True, exist_ok=True)

    for realization_index, grdecl_path in enumerate(grdecls, start=1):
        print(f"PROGRESS {realization_index}/{len(grdecls)} Appending to {grdecl_path.name}", flush=True)
        n_cells = cell_count(grdecl_path)
        attrs_by_cell = attrs_by_realization.get(realization_index, {})
        output_path = output_dir / f"{grdecl_path.with_suffix('').name}_with_union_tmap_properties.grdecl"
        with grdecl_path.open("r", encoding="utf-8") as source, open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
            out.write(source.read().rstrip() + "\n")
            out.write("\n-- T>Map-style properties mapped from union facies point sets.\n")
            out.write(f"-- Source point-set folder: {pointset_dir}\n")
            out.write(f"-- Missing cells use Continuous NoValue: {NO_VALUE}\n")
            for attr_index, column in enumerate(property_columns):
                values = (
                    attrs_by_cell[cell_index][attr_index] if cell_index in attrs_by_cell else NO_VALUE
                    for cell_index in range(n_cells)
                )
                write_property(out, grdecl_keyword(column), values)
        print(f"{grdecl_path.name}: populated {len(attrs_by_cell)}/{n_cells} cells -> {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Append T>Map properties from union facies point sets back to source GRDECLs.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--pointset-dir", type=Path, default=DEFAULT_POINTSET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    append_to_grdecls(args.grdecl_dir, args.pointset_dir, args.output_dir)


if __name__ == "__main__":
    main()
