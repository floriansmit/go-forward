"""Convert a Badlands regular stratigraphy snapshot to corner-point GRDECL."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from badlands_fsm import export_grdecl


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Regular sed.timeN.hdf5 output")
    parser.add_argument("output", type=Path)
    parser.add_argument("--datum-elevation", type=float, default=0.0)
    parser.add_argument("--shallow-depth", type=float, default=30.0)
    parser.add_argument("--facies-codes", type=int, nargs=3, default=[1, 2, 3], metavar=("LAND", "SHALLOW", "OFFSHORE"))
    parser.add_argument("--minimum-thickness", type=float, default=1e-6)
    args = parser.parse_args()
    print(json.dumps(export_grdecl(
        args.source, args.output, datum_elevation_m=args.datum_elevation,
        shallow_depth_m=args.shallow_depth, facies_codes=tuple(args.facies_codes),
        min_thickness_m=args.minimum_thickness,
    ), indent=2))


if __name__ == "__main__":
    main()
