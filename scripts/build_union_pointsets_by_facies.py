from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, tokenize_grdecl
from facies_config import DEFAULT_CONFIG_PATH, facies_label


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "input" / "source_grdecls_from_dionisosflow"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "Multi-realization union approach" / "01_union_pointsets_by_facies"
DEFAULT_CRS_TEMPLATE_DIR = ROOT / "original_data" / "original_data_dionisosflow_petrel" / "Petrel points with attributes format"


def expanded_property_values(path: Path, keyword: str) -> list[int]:
    values = tokenize_grdecl(path, {keyword})[keyword]
    expanded: list[int] = []
    for value in values:
        if "*" in value:
            count_text, repeated = value.split("*", 1)
            expanded.extend([int(float(repeated))] * int(count_text))
        else:
            expanded.append(int(float(value)))
    return expanded


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")


def write_headers(handles: dict[int, object]) -> None:
    for facies, handle in handles.items():
        handle.write("# Petrel Points with attributes\n")
        handle.write("# Unit in X and Y direction: m\n")
        handle.write("# Unit in depth: m\n")
        handle.write("# Union point set by facies aggregated from source GRDECL realizations\n")
        handle.write("VERSION 1\n")
        handle.write("BEGIN HEADER\n")
        handle.write("X\n")
        handle.write("Y\n")
        handle.write("Z\n")
        handle.write("INT,Facies\n")
        handle.write("INT,Realization\n")
        handle.write("INT,CellIndex\n")
        handle.write("END HEADER\n")


def copy_crs_sidecar(output_path: Path, template_dir: Path) -> None:
    templates = sorted(template_dir.glob("*.crsmeta.xml"))
    if templates:
        shutil.copy2(templates[0], output_path.with_name(output_path.name + ".crsmeta.xml"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build union 3D point sets by facies across multiple GRDECL realizations.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--property", default="Facies")
    parser.add_argument("--facies-config", type=Path, default=DEFAULT_CONFIG_PATH, help="JSON file containing optional facies_names labels.")
    parser.add_argument("--include-zero-facies", action="store_true", help="Include facies code 0 in the union outputs.")
    parser.add_argument("--crs-template-dir", type=Path, default=DEFAULT_CRS_TEMPLATE_DIR)
    parser.add_argument("--no-crsmeta", action="store_true")
    args = parser.parse_args()

    grdecls = sorted(path for path in args.grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
    if not grdecls:
        raise SystemExit(f"No GRDECL files found in {args.grdecl_dir}")

    all_facies = set()
    realization_data = []
    for realization_index, grdecl in enumerate(grdecls, start=1):
        centers = grdecl_cell_centers(grdecl)
        facies_values = expanded_property_values(grdecl, args.property)
        if len(centers) != len(facies_values):
            raise ValueError(f"{grdecl.name}: {len(centers)} centres but {len(facies_values)} {args.property} values")
        all_facies.update(facies_values if args.include_zero_facies else [value for value in facies_values if value != 0])
        realization_data.append((realization_index, grdecl, centers, facies_values))

    args.output_dir.mkdir(parents=True, exist_ok=True)
    handles = {}
    paths = {}
    try:
        for facies in sorted(all_facies):
            label = facies_label(facies, args.facies_config)
            path = args.output_dir / f"union_facies_{facies:02d}_{safe_name(label)}"
            paths[facies] = path
            handles[facies] = path.open("w", encoding="utf-8", newline="\n")
        write_headers(handles)

        counts = {facies: 0 for facies in handles}
        for realization_index, grdecl, centers, facies_values in realization_data:
            for cell_index, ((x, y, z), facies) in enumerate(zip(centers, facies_values)):
                if facies == 0 and not args.include_zero_facies:
                    continue
                handle = handles[facies]
                handle.write(f"{x:.2f} {y:.2f} {z:.2f} {facies} {realization_index} {cell_index}\n")
                counts[facies] += 1
    finally:
        for handle in handles.values():
            handle.close()

    if not args.no_crsmeta:
        for path in paths.values():
            copy_crs_sidecar(path, args.crs_template_dir)

    print(f"Wrote {len(paths)} union facies point sets to {args.output_dir}")
    for facies in sorted(paths):
        print(f"facies {facies}: {counts[facies]} points -> {paths[facies].name}")


if __name__ == "__main__":
    main()
