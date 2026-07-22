#!/usr/bin/env python3
"""Cross-platform launcher for the GO-Forward workflow.

Runs the same steps as the Windows PowerShell launchers, but on any OS using
the interpreter that started this script (``sys.executable``), so it respects
whatever virtualenv is active.  Child scripts are invoked exactly as the
dashboard invokes them (``sys.executable scripts/<name>.py`` with ``cwd=ROOT``),
which also puts ``scripts/`` on ``sys.path[0]`` for their sibling imports.

    python workflow.py dashboard
    python workflow.py regenerate [--approach Control] [--dry-run] ...

# ponytail: the regenerate step sequence is duplicated in
# regenerate_synthetic_outputs.ps1. If the two drift, collapse the .ps1 to a
# thin shim that calls `python workflow.py regenerate @args`.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

APPROACHES = ("BestFit", "Union", "Control", "Uber")


def resolve(path_str: str) -> Path:
    """Resolve a user/default path against the repo root when it is relative."""
    path = Path(path_str)
    return path if path.is_absolute() else (ROOT / path)


def approach_commands(
    approach: str,
    *,
    source_dir: str,
    facies_property: str,
    facies_config: str,
    property_profile: str,
    control_spacing: str,
    uber_spacing: str,
) -> list[list[str]]:
    """Build the ordered ``[script, *args]`` command lists for an approach.

    ``approach`` is one of APPROACHES or ``"All"`` (which concatenates them in
    order). Output-dir names contain spaces; they stay single list elements so
    they survive without a shell.
    """
    control_spacing = str(control_spacing)
    uber_spacing = str(uber_spacing)
    commands: list[list[str]] = []

    def want(name: str) -> bool:
        return approach in ("All", name)

    if want("BestFit"):
        base = "outputs/Best-fit approach"
        commands += [
            ["scripts/grdecl_to_petrel_pointsets.py", "--grdecl-dir", source_dir,
             "--output-dir", f"{base}/01_3d_points_from_original_grdecls", "--property", facies_property],
            ["scripts/generate_tmap_pointsets.py",
             "--source-dir", f"{base}/01_3d_points_from_original_grdecls",
             "--output-dir", f"{base}/02_3d_points_with_tmap_data",
             "--glob", "*_ReservoirGrid", "--property-profile", property_profile],
            ["scripts/append_best_fit_tmap_to_grdecls.py", "--grdecl-dir", source_dir,
             "--pointset-dir", f"{base}/02_3d_points_with_tmap_data",
             "--output-dir", f"{base}/03_augmented_grdecls_with_tmap_data"],
        ]

    if want("Union"):
        base = "outputs/Multi-realization union approach"
        commands += [
            ["scripts/build_union_pointsets_by_facies.py", "--grdecl-dir", source_dir,
             "--output-dir", f"{base}/01_union_pointsets_by_facies",
             "--property", facies_property, "--facies-config", facies_config],
            ["scripts/generate_tmap_pointsets.py",
             "--source-dir", f"{base}/01_union_pointsets_by_facies",
             "--output-dir", f"{base}/02_union_pointsets_with_tmap_data",
             "--glob", "union_facies_*", "--property-profile", property_profile],
            ["scripts/append_union_tmap_to_grdecls.py", "--grdecl-dir", source_dir,
             "--pointset-dir", f"{base}/02_union_pointsets_with_tmap_data",
             "--output-dir", f"{base}/03_augmented_grdecls_from_union_lookup"],
        ]

    if want("Control"):
        base = "outputs/Multi-realization control approach"
        commands += [
            ["scripts/build_control_pointsets_by_facies.py", "--grdecl-dir", source_dir,
             "--output-dir", f"{base}/01_control_pointsets_by_facies",
             "--property", facies_property, "--max-vertical-spacing", control_spacing,
             "--facies-config", facies_config],
            ["scripts/generate_tmap_pointsets.py",
             "--source-dir", f"{base}/01_control_pointsets_by_facies",
             "--output-dir", f"{base}/02_control_pointsets_with_tmap_data",
             "--glob", "control_facies_*", "--property-profile", property_profile],
            ["scripts/append_control_tmap_to_grdecls.py", "--grdecl-dir", source_dir,
             "--pointset-dir", f"{base}/02_control_pointsets_with_tmap_data",
             "--output-dir", f"{base}/03_augmented_grdecls_from_control_interpolation",
             "--property", facies_property],
        ]

    if want("Uber"):
        base = "outputs/Multi-realization Uber approach"
        commands += [
            ["scripts/build_uber_pointsets_by_facies.py", "--grdecl-dir", source_dir,
             "--output-dir", f"{base}/01_uber_pointsets_by_facies",
             "--property", facies_property, "--vertical-spacing", uber_spacing,
             "--facies-config", facies_config],
            ["scripts/generate_tmap_pointsets.py",
             "--source-dir", f"{base}/01_uber_pointsets_by_facies",
             "--output-dir", f"{base}/02_uber_pointsets_with_tmap_data",
             "--glob", "uber_facies_*", "--property-profile", property_profile],
            ["scripts/append_uber_tmap_to_grdecls.py", "--grdecl-dir", source_dir,
             "--pointset-dir", f"{base}/02_uber_pointsets_with_tmap_data",
             "--output-dir", f"{base}/03_augmented_grdecls_from_uber_lookup",
             "--property", facies_property],
            ["scripts/write_petrel_standard_uber_grdecls.py", "--grdecl-dir", source_dir,
             "--pointset-dir", f"{base}/02_uber_pointsets_with_tmap_data",
             "--output-dir", f"{base}/04_petrel_standard_grdecls_from_uber_lookup"],
        ]

    return commands


def run_commands(commands: list[list[str]], dry_run: bool) -> None:
    for command in commands:
        full = [sys.executable, *command]
        if dry_run:
            print(" ".join(f'"{arg}"' if " " in arg else arg for arg in full))
            continue
        subprocess.run(full, cwd=ROOT, check=True)


def cmd_dashboard(args: argparse.Namespace) -> None:
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "dashboard/streamlit_app.py",
         "--server.headless", "true", "--server.port", str(args.port)],
        cwd=ROOT,
        check=True,
    )


def cmd_regenerate(args: argparse.Namespace) -> None:
    source_dir = resolve(args.source_dir)
    facies_config = resolve(args.facies_config)

    if not source_dir.is_dir():
        raise SystemExit(f"Source GRDECL directory not found: {source_dir}")
    if not any(p.is_file() and p.suffix.lower() == ".grdecl" for p in source_dir.iterdir()):
        raise SystemExit(f"No .grdecl files found in: {source_dir}")
    if not facies_config.is_file():
        raise SystemExit(f"Facies configuration not found: {facies_config}")

    commands = approach_commands(
        args.approach,
        source_dir=str(source_dir),
        facies_property=args.facies_property,
        facies_config=str(facies_config),
        property_profile=args.property_profile,
        control_spacing=args.control_vertical_spacing,
        uber_spacing=args.uber_vertical_spacing,
    )
    run_commands(commands, args.dry_run)
    if not args.dry_run:
        print("\nCompleted synthetic output generation.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Cross-platform launcher for the GO-Forward workflow.")
    sub = parser.add_subparsers(dest="command", required=True)

    dash = sub.add_parser("dashboard", help="Launch the Streamlit dashboard.")
    dash.add_argument("--port", type=int, default=8501)
    dash.set_defaults(func=cmd_dashboard)

    regen = sub.add_parser("regenerate", help="Rebuild the synthetic demonstration outputs.")
    regen.add_argument("--source-dir", default="input/source_grdecls_from_dionisosflow")
    regen.add_argument("--facies-property", default="Facies")
    regen.add_argument("--facies-config", default="dashboard/facies_config.json")
    regen.add_argument("--approach", choices=("All", *APPROACHES), default="All")
    regen.add_argument("--property-profile", choices=("all", "reservoir_quality"), default="reservoir_quality")
    regen.add_argument("--control-vertical-spacing", default="50")
    regen.add_argument("--uber-vertical-spacing", default="25")
    regen.add_argument("--dry-run", action="store_true", help="Print the commands instead of running them.")
    regen.set_defaults(func=cmd_regenerate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
