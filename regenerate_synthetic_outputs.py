"""Rebuild synthetic GO-Forward demonstration outputs without PowerShell."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rebuild synthetic Best-fit, Union, Control and Uber outputs from "
            "source GRDECLs. This is a local demonstration workflow, not a "
            "replacement for a real T>Map run."
        )
    )
    parser.add_argument("--project", default="Siliciclastics_Gassum_siliciclastics")
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--facies-property", default="Facies")
    parser.add_argument("--facies-config", type=Path)
    parser.add_argument(
        "--approach", choices=("All", "BestFit", "Union", "Control", "Uber"), default="All"
    )
    parser.add_argument("--property-profile", choices=("all", "reservoir_quality"), default="reservoir_quality")
    parser.add_argument("--control-vertical-spacing", type=int, default=50)
    parser.add_argument("--uber-vertical-spacing", default="25")
    parser.add_argument("--dry-run", action="store_true", help="Print the workflow commands without running them.")
    return parser.parse_args()


def command_text(command: list[str]) -> str:
    return subprocess.list2cmdline([str(value) for value in command])


def run(command: list[str], dry_run: bool) -> None:
    full_command = [sys.executable, *command]
    print(f"\n> {command_text(full_command)}")
    if not dry_run:
        subprocess.run(full_command, cwd=ROOT, check=True)


def selected(args: argparse.Namespace, approach: str) -> bool:
    return args.approach in ("All", approach)


def main() -> int:
    args = parse_args()
    source_dir = args.source_dir or ROOT / "input" / args.project / "source_grdecls"
    source_dir = source_dir.resolve()
    facies_config = args.facies_config or source_dir / "facies_config.json"
    if not facies_config.exists():
        facies_config = ROOT / "dashboard" / "facies_config.json"

    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source GRDECL directory was not found: {source_dir}")
    if not facies_config.is_file():
        raise FileNotFoundError(f"Facies configuration was not found: {facies_config}")
    if not list(source_dir.glob("*.grdecl")):
        raise FileNotFoundError(f"No .grdecl files were found in: {source_dir}")

    outputs = ROOT / "outputs" / args.project
    facies_property = args.facies_property

    if selected(args, "BestFit"):
        print("\n=== Best-fit ===")
        workflow_root = outputs / "Best-fit approach"
        points = workflow_root / "01_3d_points_from_original_grdecls"
        returned = workflow_root / "02_3d_points_with_tmap_data"
        augmented = workflow_root / "03_augmented_grdecls_with_tmap_data"
        run(["scripts/build_best_fit_grdecl_to_pointset.py", "--grdecl-dir", str(source_dir), "--output-dir", str(points), "--property", facies_property], args.dry_run)
        run(["scripts/generate_synthetic_tmap_data.py", "--source-dir", str(points), "--output-dir", str(returned), "--glob", "*_3d_pointset", "--property-profile", args.property_profile], args.dry_run)
        run(["scripts/append_best_fit_tmap_to_grdecls.py", "--grdecl-dir", str(source_dir), "--pointset-dir", str(returned), "--output-dir", str(augmented)], args.dry_run)

    if selected(args, "Union"):
        print("\n=== Multi-realization Union ===")
        workflow_root = outputs / "Multi-realization union approach"
        points = workflow_root / "01_union_pointsets_by_facies"
        returned = workflow_root / "02_union_pointsets_with_tmap_data"
        augmented = workflow_root / "03_augmented_grdecls_from_union_lookup"
        run(["scripts/build_multi_realizations_grdecls_to_union_pointsets.py", "--grdecl-dir", str(source_dir), "--output-dir", str(points), "--property", facies_property, "--facies-config", str(facies_config), "--tmap-enabled-only"], args.dry_run)
        run(["scripts/generate_synthetic_tmap_data.py", "--source-dir", str(points), "--output-dir", str(returned), "--glob", "union_facies_*", "--property-profile", args.property_profile], args.dry_run)
        run(["scripts/append_multi_realizations_union_tmap_to_grdecls.py", "--grdecl-dir", str(source_dir), "--pointset-dir", str(returned), "--output-dir", str(augmented)], args.dry_run)

    if selected(args, "Control"):
        print("\n=== Multi-realization Control ===")
        workflow_root = outputs / "Multi-realization control approach"
        points = workflow_root / "01_control_pointsets_by_facies"
        returned = workflow_root / "02_control_pointsets_with_tmap_data"
        augmented = workflow_root / "03_augmented_grdecls_from_control_interpolation"
        run(["scripts/build_multi_realizations_grdecls_to_control_pointsets.py", "--grdecl-dir", str(source_dir), "--output-dir", str(points), "--property", facies_property, "--max-vertical-spacing", str(args.control_vertical_spacing), "--facies-config", str(facies_config), "--tmap-enabled-only"], args.dry_run)
        run(["scripts/generate_synthetic_tmap_data.py", "--source-dir", str(points), "--output-dir", str(returned), "--glob", "control_facies_*", "--property-profile", args.property_profile], args.dry_run)
        run(["scripts/append_multi_realizations_control_tmap_to_grdecls.py", "--grdecl-dir", str(source_dir), "--pointset-dir", str(returned), "--output-dir", str(augmented), "--property", facies_property], args.dry_run)

    if selected(args, "Uber"):
        print("\n=== Multi-realization Uber ===")
        workflow_root = outputs / "Multi-realization Uber approach"
        points = workflow_root / "01_uber_pointsets_by_facies"
        returned = workflow_root / "02_uber_pointsets_with_tmap_data"
        augmented = workflow_root / "03_augmented_grdecls_from_uber_lookup"
        petrel = workflow_root / "04_petrel_standard_grdecls_from_uber_lookup"
        run(["scripts/build_multi_realizations_grdecls_to_uber_pointsets.py", "--grdecl-dir", str(source_dir), "--output-dir", str(points), "--property", facies_property, "--vertical-spacing", str(args.uber_vertical_spacing), "--facies-config", str(facies_config), "--tmap-enabled-only"], args.dry_run)
        run(["scripts/generate_synthetic_tmap_data.py", "--source-dir", str(points), "--output-dir", str(returned), "--glob", "uber_facies_*", "--property-profile", args.property_profile], args.dry_run)
        run(["scripts/append_multi_realizations_uber_tmap_to_grdecls.py", "--grdecl-dir", str(source_dir), "--pointset-dir", str(returned), "--output-dir", str(augmented), "--property", facies_property], args.dry_run)
        run(["scripts/write_petrel_standard_uber_grdecls.py", "--grdecl-dir", str(source_dir), "--pointset-dir", str(returned), "--output-dir", str(petrel)], args.dry_run)

    print("\nCompleted synthetic output generation." if not args.dry_run else "\nDry run complete; no files were written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
