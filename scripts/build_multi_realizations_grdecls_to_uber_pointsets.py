from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, tokenize_grdecl
from facies_config import DEFAULT_CONFIG_PATH, facies_label


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "input" / "source_grdecls_from_dionisosflow"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "Multi-realization Uber approach" / "01_uber_pointsets_by_facies"


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_")


def grid_dimensions(path: Path) -> tuple[int, int, int]:
    specgrid = tokenize_grdecl(path, {"SPECGRID"})["SPECGRID"]
    return tuple(int(float(v)) for v in specgrid[:3])


def facies_values(path: Path, keyword: str) -> set[int]:
    values = tokenize_grdecl(path, {keyword})[keyword]
    expanded: set[int] = set()
    for value in values:
        if "*" in value:
            _, repeated = value.split("*", 1)
            expanded.add(int(float(repeated)))
        else:
            expanded.add(int(float(value)))
    return expanded


def choose_spacing(z_min: float, z_max: float, n_xy: int, n_facies: int, choices: list[float], max_total_points: int) -> float:
    for spacing in sorted(choices):
        n_z = int(math.floor((z_max - z_min) / spacing)) + 1
        if n_xy * n_z * n_facies <= max_total_points:
            return spacing
    return max(choices)


def z_levels(z_min: float, z_max: float, spacing: float) -> list[float]:
    start = math.floor(z_min / spacing) * spacing
    stop = math.ceil(z_max / spacing) * spacing
    count = int(round((stop - start) / spacing)) + 1
    return [start + index * spacing for index in range(count)]


def tmap_enabled_facies(config_path: Path) -> set[int]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return {int(code) for code, item in payload.get("facies_metadata", {}).items() if isinstance(item, dict) and item.get("tmap_enabled", True)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Uber facies point sets with fixed XY grid and regular vertical sampling.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--property", default="Facies")
    parser.add_argument("--grdecl", action="append", type=Path, help="Source GRDECL to include; repeat to select a subset. Defaults to all files in --grdecl-dir.")
    parser.add_argument("--facies-config", type=Path, default=DEFAULT_CONFIG_PATH, help="JSON file containing optional facies_names labels.")
    parser.add_argument("--tmap-enabled-only", action="store_true", help="Exclude facies disabled for T>Map in --facies-config.")
    parser.add_argument("--vertical-spacing", default="auto", help="'auto' or a spacing in metres, e.g. 10, 25, 50.")
    parser.add_argument("--spacing-choices", default="10,25,50", help="Comma-separated metres used when --vertical-spacing auto.")
    parser.add_argument("--max-total-points", type=int, default=1_000_000)
    parser.add_argument("--include-zero-facies", action="store_true", help="Include facies code 0 in the Uber outputs.")
    args = parser.parse_args()

    grdecls = args.grdecl or sorted(path for path in args.grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
    if not grdecls:
        raise SystemExit(f"No GRDECL files found in {args.grdecl_dir}")
    enabled = tmap_enabled_facies(args.facies_config) if args.tmap_enabled_only else None

    nx, ny, nz = grid_dimensions(grdecls[0])
    first_centers = grdecl_cell_centers(grdecls[0])
    xy_points = [(first_centers[j * nx + i][0], first_centers[j * nx + i][1]) for j in range(ny) for i in range(nx)]

    all_centers = []
    all_facies = set()
    for grdecl in grdecls:
        all_centers.extend(grdecl_cell_centers(grdecl))
        values = facies_values(grdecl, args.property)
        all_facies.update(value for value in values if (args.include_zero_facies or value != 0) and (enabled is None or value in enabled))
    z_min = min(z for _, _, z in all_centers)
    z_max = max(z for _, _, z in all_centers)

    if args.vertical_spacing == "auto":
        choices = [float(value) for value in args.spacing_choices.split(",")]
        spacing = choose_spacing(z_min, z_max, len(xy_points), len(all_facies), choices, args.max_total_points)
    else:
        spacing = float(args.vertical_spacing)
    zs = z_levels(z_min, z_max, spacing)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for facies in sorted(all_facies):
        label = facies_label(facies, args.facies_config)
        path = args.output_dir / f"uber_facies_{facies:02d}_{safe_name(label)}_{spacing:g}m"
        with path.open("w", encoding="utf-8", newline="\n") as out:
            out.write("# T>Map 3D point set with attributes\n")
            out.write("# Unit in X and Y direction: m\n")
            out.write("# Unit in depth: m\n")
            out.write("# Uber facies point set with fixed XY grid and regular vertical sampling\n")
            out.write("VERSION 1\n")
            out.write("BEGIN HEADER\n")
            out.write("X\nY\nZ\nINT,Facies\nEND HEADER\n")
            for x, y in xy_points:
                for z in zs:
                    out.write(f"{x:.2f} {y:.2f} {z:.2f} {facies}\n")
        print(f"facies {facies}: {len(xy_points) * len(zs)} points -> {path.name}")

    print(f"XY points: {len(xy_points)}, Z levels: {len(zs)}, spacing: {spacing:g} m, total points: {len(xy_points) * len(zs) * len(all_facies)}")


if __name__ == "__main__":
    main()
