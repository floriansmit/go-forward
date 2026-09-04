from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, path_for_io, tokenize_grdecl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "original_grdecl"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "Best-fit approach" / "01_3d_points_from_original_grdecls"


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


def enabled_facies(config_path: Path | None) -> set[int] | None:
    if config_path is None or not config_path.exists():
        return None
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    metadata = payload.get("facies_metadata", {})
    return {int(code) for code, item in metadata.items() if isinstance(item, dict) and item.get("tmap_enabled", True)}


def reduced_indices(centers: list[tuple[float, float, float]], properties: list[str], nx: int, ny: int, spacing: float) -> set[int]:
    groups: dict[tuple[str, int], list[tuple[int, float]]] = defaultdict(list)
    for index, (_, _, z) in enumerate(centers):
        groups[(properties[index], index % (nx * ny))].append((index, z))
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
    return selected


def write_pointset(
    grdecl_path: Path,
    output_path: Path,
    property_keyword: str,
    discrete_novalue: str | None,
    max_vertical_spacing: float | None,
    enabled_codes: set[int] | None,
) -> dict[str, int]:
    centers = grdecl_cell_centers(grdecl_path)
    properties = grdecl_property_values(grdecl_path, property_keyword)
    if len(centers) != len(properties):
        raise ValueError(f"{grdecl_path.name}: {len(centers)} cell centres but {len(properties)} {property_keyword} values")

    specgrid = tokenize_grdecl(grdecl_path, {"SPECGRID"})["SPECGRID"]
    nx, ny = int(float(specgrid[0])), int(float(specgrid[1]))
    selected = reduced_indices(centers, properties, nx, ny, max_vertical_spacing) if max_vertical_spacing else set(range(len(centers)))
    written = 0
    skipped = 0
    Path(path_for_io(output_path.parent)).mkdir(parents=True, exist_ok=True)
    with open(path_for_io(output_path), "w", encoding="utf-8", newline="\n") as out:
        out.write("# T>Map 3D point set with attributes\n")
        out.write("# Unit in X and Y direction: m\n")
        out.write("# Unit in depth: m\n")
        out.write("# Generated directly from GRDECL geometry and property arrays\n")
        out.write(f"# Source GRDECL: {grdecl_path.name}\n")
        out.write("# Workflow: Best-fit model; direct GRDECL cell-centre point export\n")
        if max_vertical_spacing:
            out.write(f"# Reduced vertical sampling: top/bottom plus maximum {max_vertical_spacing:g} m spacing per facies and I/J column\n")
        out.write("VERSION 1\n")
        out.write("BEGIN HEADER\n")
        out.write("X\n")
        out.write("Y\n")
        out.write("Z\n")
        out.write(f"INT,{property_keyword}\n")
        out.write("INT,CellIndex\n")
        out.write("END HEADER\n")
        for cell_index, ((x, y, z), property_value) in enumerate(zip(centers, properties)):
            code = int(float(property_value))
            if cell_index not in selected or (enabled_codes is not None and code not in enabled_codes) or (discrete_novalue is not None and property_value == discrete_novalue):
                skipped += 1
                continue
            out.write(f"{x:.2f} {y:.2f} {z:.2f} {int(float(property_value))} {cell_index}\n")
            written += 1
    return {"cells": len(centers), "written": written, "skipped": skipped}


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert GRDECL grid cells to T>Map 3D point-set ASCII files.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--property", default="Facies", help="GRDECL property keyword to export as INT attribute.")
    parser.add_argument("--suffix", default="_3d_pointset", help="Suffix for generated point-set filenames.")
    parser.add_argument("--discrete-novalue", default=None, help="Skip cells with this property value, e.g. 0.")
    parser.add_argument("--single-grdecl", type=Path, help="Convert only this GRDECL file.")
    parser.add_argument("--max-vertical-spacing", type=float, help="Optional reduced export: retain top/bottom and points at this maximum vertical spacing.")
    parser.add_argument("--reservoir-only", action="store_true", help="Export only facies with tmap_enabled=true in --facies-config.")
    parser.add_argument("--facies-config", type=Path, help="Project facies_config.json used with --reservoir-only.")
    args = parser.parse_args()

    grdecl_paths = [args.single_grdecl] if args.single_grdecl else sorted(
        path for path in args.grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl"
    )
    for grdecl_path in grdecl_paths:
        suffix = args.suffix if not args.max_vertical_spacing else f"{args.suffix}_control_{args.max_vertical_spacing:g}m"
        output_path = args.output_dir / output_name(grdecl_path, suffix)
        codes = enabled_facies(args.facies_config) if args.reservoir_only else None
        if args.reservoir_only and codes is None:
            raise SystemExit("--reservoir-only requires an existing --facies-config with facies_metadata.")
        stats = write_pointset(grdecl_path, output_path, args.property, args.discrete_novalue, args.max_vertical_spacing, codes)
        print(
            f"{grdecl_path.name}: wrote {stats['written']}/{stats['cells']} points"
            f" ({stats['skipped']} skipped) -> {output_path}"
        )


if __name__ == "__main__":
    main()
