from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, path_for_io, tokenize_grdecl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "input" / "source_grdecls_from_dionisosflow"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "Best-fit approach" / "01_3d_points_from_original_grdecls"
DEFAULT_CRS_TEMPLATE_DIR = ROOT / "original_data" / "original_data_dionisosflow_petrel" / "Petrel points with attributes format"


def grdecl_property_values(path: Path, keyword: str) -> list[str]:
    values = tokenize_grdecl(path, {keyword})[keyword]
    expanded: list[str] = []
    for value in values:
        if "*" in value:
            count_text, repeated = value.split("*", 1)
            expanded.extend([repeated] * int(count_text))
        else:
            expanded.append(value)
    return expanded


def output_name(grdecl_path: Path, suffix: str) -> str:
    return f"{grdecl_path.with_suffix('').name}{suffix}"


def write_pointset(
    grdecl_path: Path,
    output_path: Path,
    property_keyword: str,
    discrete_novalue: str | None,
) -> dict[str, int]:
    centers = grdecl_cell_centers(grdecl_path)
    properties = grdecl_property_values(grdecl_path, property_keyword)
    if len(centers) != len(properties):
        raise ValueError(f"{grdecl_path.name}: {len(centers)} cell centres but {len(properties)} {property_keyword} values")

    written = 0
    skipped = 0
    Path(path_for_io(output_path.parent)).mkdir(parents=True, exist_ok=True)
    with open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
        out.write("# Petrel Points with attributes\n")
        out.write("# Unit in X and Y direction: m\n")
        out.write("# Unit in depth: m\n")
        out.write("# Generated directly from GRDECL geometry and property arrays\n")
        out.write(f"# Source GRDECL: {grdecl_path.name}\n")
        out.write("# Workflow: Best-fit model; direct GRDECL cell-centre point export\n")
        out.write("VERSION 1\n")
        out.write("BEGIN HEADER\n")
        out.write("X\n")
        out.write("Y\n")
        out.write("Z\n")
        out.write(f"INT,{property_keyword}\n")
        out.write("INT,CellIndex\n")
        out.write("END HEADER\n")
        for cell_index, ((x, y, z), property_value) in enumerate(zip(centers, properties)):
            if discrete_novalue is not None and property_value == discrete_novalue:
                skipped += 1
                continue
            out.write(f"{x:.2f} {y:.2f} {z:.2f} {int(float(property_value))} {cell_index}\n")
            written += 1
    return {"cells": len(centers), "written": written, "skipped": skipped}


def copy_crs_template(grdecl_path: Path, output_path: Path, template_dir: Path) -> bool:
    suffixes = (
        "_ReservoirGrid.crsmeta.xml",
        "_ReservoirGrid_tmap_synthetic.crsmeta.xml",
        ".crsmeta.xml",
    )
    candidates = []
    stem = grdecl_path.with_suffix("").name
    for suffix in suffixes:
        candidates.extend(template_dir.glob(f"{stem}*{suffix}"))
    if not candidates:
        return False
    shutil.copy2(candidates[0], output_path.with_name(output_path.name + ".crsmeta.xml"))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert GRDECL grid cells to Petrel Points with attributes ASCII files.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--property", default="Facies", help="GRDECL property keyword to export as INT attribute.")
    parser.add_argument("--suffix", default="_ReservoirGrid", help="Suffix for generated point-set filenames.")
    parser.add_argument("--discrete-novalue", default=None, help="Skip cells with this property value, e.g. 0.")
    parser.add_argument("--single-grdecl", type=Path, help="Convert only this GRDECL file.")
    parser.add_argument("--crs-template-dir", type=Path, default=DEFAULT_CRS_TEMPLATE_DIR)
    parser.add_argument("--no-crsmeta", action="store_true", help="Do not copy CRS companion XML files.")
    args = parser.parse_args()

    grdecl_paths = [args.single_grdecl] if args.single_grdecl else sorted(
        path for path in args.grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl"
    )
    for grdecl_path in grdecl_paths:
        output_path = args.output_dir / output_name(grdecl_path, args.suffix)
        stats = write_pointset(grdecl_path, output_path, args.property, args.discrete_novalue)
        copied_crs = False if args.no_crsmeta else copy_crs_template(grdecl_path, output_path, args.crs_template_dir)
        print(
            f"{grdecl_path.name}: wrote {stats['written']}/{stats['cells']} points"
            f" ({stats['skipped']} skipped) -> {output_path}"
            f"{' + CRS XML' if copied_crs else ''}"
        )


if __name__ == "__main__":
    main()
