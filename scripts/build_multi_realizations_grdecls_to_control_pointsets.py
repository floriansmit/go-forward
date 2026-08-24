from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, tokenize_grdecl
from facies_config import DEFAULT_CONFIG_PATH, facies_label


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "0_original_grdecl"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "MVP_Gassum_mvp" / "Multi-realization control approach" / "01_control_pointsets_by_facies"


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


def control_levels(bottom_z: float, top_z: float, max_spacing: float) -> list[float]:
    """Regular shared controls from the shallow envelope top to its base."""
    if abs(top_z - bottom_z) < 1e-9:
        return [top_z]
    levels = [top_z]
    z = top_z - max_spacing
    while z > bottom_z:
        levels.append(z)
        z -= max_spacing
    if abs(levels[-1] - bottom_z) > 1e-9:
        levels.append(bottom_z)
    return levels


def tmap_enabled_facies(config_path: Path) -> set[int]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    metadata = payload.get("facies_metadata", {})
    return {int(code) for code, item in metadata.items() if isinstance(item, dict) and item.get("tmap_enabled", True)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build shared facies-envelope control point sets across selected GRDECL realizations.")
    parser.add_argument("--grdecl-dir", type=Path, default=DEFAULT_GRDECL_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--property", default="Facies")
    parser.add_argument("--grdecl", action="append", type=Path, help="Source GRDECL to include; repeat to select a subset. Defaults to all files in --grdecl-dir.")
    parser.add_argument("--facies-config", type=Path, default=DEFAULT_CONFIG_PATH, help="JSON file containing optional facies_names labels.")
    parser.add_argument("--max-vertical-spacing", type=float, default=50.0)
    parser.add_argument("--tmap-enabled-only", action="store_true", help="Exclude facies disabled for T>Map in --facies-config.")
    parser.add_argument("--include-zero-facies", action="store_true", help="Include facies code 0 in the control-point outputs.")
    args = parser.parse_args()

    grdecls = args.grdecl or sorted(path for path in args.grdecl_dir.iterdir() if path.is_file() and path.suffix.lower() == ".grdecl")
    if not grdecls:
        raise SystemExit(f"No GRDECL files found in {args.grdecl_dir}")
    enabled_facies = tmap_enabled_facies(args.facies_config) if args.tmap_enabled_only else None

    args.output_dir.mkdir(parents=True, exist_ok=True)
    nx, ny, _ = dimensions(grdecls[0])
    reference_centers = grdecl_cell_centers(grdecls[0])
    envelopes: dict[tuple[int, int], list[float]] = defaultdict(list)
    for model_index, grdecl in enumerate(grdecls, start=1):
        print(f"PROGRESS {model_index}/{len(grdecls)} Scanning {grdecl.name}", flush=True)
        model_dims = dimensions(grdecl)
        if model_dims[:2] != (nx, ny):
            raise ValueError(f"{grdecl.name}: grid I/J dimensions {model_dims[:2]} do not match {grdecls[0].name}: {(nx, ny)}")
        centers = grdecl_cell_centers(grdecl)
        facies_values = expanded_facies(grdecl, args.property)
        for cell_index, ((x, y, z), facies) in enumerate(zip(centers, facies_values)):
            if (facies == 0 and not args.include_zero_facies) or (enabled_facies is not None and facies not in enabled_facies):
                continue
            ij = cell_index % (nx * ny)
            envelopes[(facies, ij)].append(z)

    output_rows: dict[int, list[str]] = defaultdict(list)
    for (facies, ij), zs in envelopes.items():
        # The envelope is shared across all selected realizations: the highest
        # occurrence and lowest occurrence define the T>Map control interval.
        top_z, bottom_z = max(zs), min(zs)
        x, y, _ = reference_centers[ij]
        for z in control_levels(bottom_z, top_z, args.max_vertical_spacing):
            output_rows[facies].append(f"{x:.2f} {y:.2f} {z:.2f} {facies} {ij}\n")

    for facies_index, (facies, rows) in enumerate(sorted(output_rows.items()), start=1):
        print(
            f"Writing control pointset {facies_index}/{len(output_rows)} for facies {facies}",
            flush=True,
        )
        label = facies_label(facies, args.facies_config)
        path = args.output_dir / f"control_facies_{facies:02d}_{safe_name(label)}_{args.max_vertical_spacing:g}m"
        with path.open("w", encoding="utf-8", newline="\n") as out:
            out.write("# T>Map 3D point set with attributes\n")
            out.write("# Unit in X and Y direction: m\n")
            out.write("# Unit in depth: m\n")
            out.write("# Shared multi-realization facies envelope: topmost and bottommost occurrence across selected realizations, with regular vertical controls\n")
            out.write(f"# Max vertical spacing: {args.max_vertical_spacing:g} m\n")
            out.write("# ControlColumn is the zero-based I/J column identifier; controls are shared across realizations.\n")
            out.write("VERSION 1\nBEGIN HEADER\nX\nY\nZ\nINT,Facies\nINT,ControlColumn\nEND HEADER\n")
            out.writelines(rows)
        print(f"facies {facies}: {len(rows)} shared envelope control points -> {path.name}")


if __name__ == "__main__":
    main()
