from __future__ import annotations

import argparse
import re
import shutil
from collections import defaultdict
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, tokenize_grdecl
from facies_config import DEFAULT_CONFIG_PATH, facies_label


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "input" / "source_grdecls_from_dionisosflow"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "Multi-realization control approach" / "01_control_pointsets_by_facies"
DEFAULT_CRS_TEMPLATE_DIR = ROOT / "original_data" / "original_data_dionisosflow_petrel" / "Petrel points with attributes format"


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")


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


def selected_indices(cells: list[tuple[int, float]], max_spacing: float) -> list[int]:
    cells = sorted(cells, key=lambda item: item[1])
    if len(cells) <= 2:
        return [cell_index for cell_index, _ in cells]

    selected = [cells[0]]
    last_index, last_z = cells[0]
    for cell_index, z in cells[1:-1]:
        if abs(z - last_z) >= max_spacing:
            selected.append((cell_index, z))
            last_index, last_z = cell_index, z
    if selected[-1][0] != cells[-1][0]:
        selected.append(cells[-1])
    return [cell_index for cell_index, _ in selected]


def copy_crs_sidecar(output_path: Path, template_dir: Path) -> None:
    templates = sorted(template_dir.glob("*.crsmeta.xml"))
    if templates:
        shutil.copy2(templates[0], output_path.with_name(output_path.name + ".crsmeta.xml"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build reduced control point sets by facies using top/bottom/max vertical spacing per x/y column.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--property", default="Facies")
    parser.add_argument("--facies-config", type=Path, default=DEFAULT_CONFIG_PATH, help="JSON file containing optional facies_names labels.")
    parser.add_argument("--max-vertical-spacing", type=float, default=50.0)
    parser.add_argument("--include-zero-facies", action="store_true", help="Include facies code 0 in the control-point outputs.")
    parser.add_argument("--crs-template-dir", type=Path, default=DEFAULT_CRS_TEMPLATE_DIR)
    parser.add_argument("--no-crsmeta", action="store_true")
    args = parser.parse_args()

    grdecls = sorted(path for path in args.grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
    if not grdecls:
        raise SystemExit(f"No GRDECL files found in {args.grdecl_dir}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_rows: dict[int, list[str]] = defaultdict(list)

    for realization_index, grdecl in enumerate(grdecls, start=1):
        nx, ny, nz = dimensions(grdecl)
        centers = grdecl_cell_centers(grdecl)
        facies_values = expanded_facies(grdecl, args.property)
        grouped: dict[tuple[int, int, int], list[tuple[int, float]]] = defaultdict(list)
        for cell_index, ((x, y, z), facies) in enumerate(zip(centers, facies_values)):
            if facies == 0 and not args.include_zero_facies:
                continue
            ij = cell_index % (nx * ny)
            grouped[(facies, ij, realization_index)].append((cell_index, z))

        for (facies, ij, realization), cells in grouped.items():
            for cell_index in selected_indices(cells, args.max_vertical_spacing):
                x, y, z = centers[cell_index]
                output_rows[facies].append(f"{x:.2f} {y:.2f} {z:.2f} {facies} {realization} {cell_index}\n")

    for facies, rows in sorted(output_rows.items()):
        label = facies_label(facies, args.facies_config)
        path = args.output_dir / f"control_facies_{facies:02d}_{safe_name(label)}_{args.max_vertical_spacing:g}m"
        with path.open("w", encoding="utf-8", newline="\n") as out:
            out.write("# Petrel Points with attributes\n")
            out.write("# Unit in X and Y direction: m\n")
            out.write("# Unit in depth: m\n")
            out.write("# Reduced control point set by facies: topmost, bottommost, and max vertical spacing controls\n")
            out.write(f"# Max vertical spacing: {args.max_vertical_spacing:g} m\n")
            out.write("VERSION 1\nBEGIN HEADER\nX\nY\nZ\nINT,Facies\nINT,Realization\nINT,CellIndex\nEND HEADER\n")
            out.writelines(rows)
        if not args.no_crsmeta:
            copy_crs_sidecar(path, args.crs_template_dir)
        print(f"facies {facies}: {len(rows)} control points -> {path.name}")


if __name__ == "__main__":
    main()
