from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, tokenize_grdecl
from facies_config import DEFAULT_CONFIG_PATH, facies_label


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "original_grdecl"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "Multi-realization union approach" / "01_union_pointsets_by_facies"


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


def tmap_enabled_facies(config_path: Path) -> set[int]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return {int(code) for code, item in payload.get("facies_metadata", {}).items() if isinstance(item, dict) and item.get("tmap_enabled", True)}


def write_headers(handles: dict[int, object]) -> None:
    for facies, handle in handles.items():
        handle.write("# T>Map 3D point set with attributes\n")
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build union 3D point sets by facies across multiple GRDECL realizations.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--property", default="Facies")
    parser.add_argument("--grdecl", action="append", type=Path, help="Source GRDECL to include; repeat to select a subset. Defaults to all files in --grdecl-dir.")
    parser.add_argument("--facies-config", type=Path, default=DEFAULT_CONFIG_PATH, help="JSON file containing optional facies_names labels.")
    parser.add_argument("--tmap-enabled-only", action="store_true", help="Exclude facies disabled for T>Map in --facies-config.")
    parser.add_argument("--include-zero-facies", action="store_true", help="Include facies code 0 in the union outputs.")
    args = parser.parse_args()

    grdecls = args.grdecl or sorted(path for path in args.grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
    if not grdecls:
        raise SystemExit(f"No GRDECL files found in {args.grdecl_dir}")
    enabled = tmap_enabled_facies(args.facies_config) if args.tmap_enabled_only else None

    all_facies = set()
    realization_data = []
    progress_total = len(grdecls) * 2
    for realization_index, grdecl in enumerate(grdecls, start=1):
        print(f"PROGRESS {realization_index}/{progress_total} Scanning {grdecl.name}", flush=True)
        centers = grdecl_cell_centers(grdecl)
        facies_values = expanded_property_values(grdecl, args.property)
        if len(centers) != len(facies_values):
            raise ValueError(f"{grdecl.name}: {len(centers)} centres but {len(facies_values)} {args.property} values")
        valid = [value for value in facies_values if (args.include_zero_facies or value != 0) and (enabled is None or value in enabled)]
        all_facies.update(valid)
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
            print(
                f"PROGRESS {len(grdecls) + realization_index}/{progress_total} Writing {grdecl.name}",
                flush=True,
            )
            for cell_index, ((x, y, z), facies) in enumerate(zip(centers, facies_values)):
                if (facies == 0 and not args.include_zero_facies) or (enabled is not None and facies not in enabled):
                    continue
                handle = handles[facies]
                handle.write(f"{x:.2f} {y:.2f} {z:.2f} {facies} {realization_index} {cell_index}\n")
                counts[facies] += 1
    finally:
        for handle in handles.values():
            handle.close()

    print(f"Wrote {len(paths)} union facies point sets to {args.output_dir}")
    for facies in sorted(paths):
        print(f"facies {facies}: {counts[facies]} points -> {paths[facies].name}")


if __name__ == "__main__":
    main()
