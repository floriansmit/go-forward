"""Write a rectangular, structurally complete crop of a cornerpoint GRDECL."""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

from grdecl_utils import path_for_io


KEYWORD = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def expand(tokens: list[str]) -> list[str]:
    values: list[str] = []
    for token in tokens:
        if "*" in token:
            count, value = token.split("*", 1)
            values.extend([value] * int(count))
        else:
            values.append(token)
    return values


def parse(path: Path) -> dict[str, list[str]]:
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    with open(path_for_io(path), encoding="utf-8") as handle:
        for raw in handle:
            line = raw.split("--", 1)[0].strip()
            if not line:
                continue
            if current is None:
                if KEYWORD.fullmatch(line):
                    current = line.upper()
                    blocks[current] = []
                continue
            before, separator, _ = line.partition("/")
            blocks[current].extend(before.split())
            if separator:
                current = None
    return blocks


def write_block(handle, keyword: str, values: list[str], width: int = 8) -> None:
    handle.write(f"{keyword}\n")
    for start in range(0, len(values), width):
        handle.write(" ".join(values[start : start + width]) + "\n")
    handle.write("/\n\n")


def crop_coord(values: list[str], nx: int, ny: int, i0: int, i1: int, j0: int, j1: int, flip_j: bool, invert_z: bool) -> list[str]:
    output: list[str] = []
    for target_j in range(j1 - j0 + 2):
        j = j1 + 1 - target_j if flip_j else j0 + target_j
        for i in range(i0, i1 + 2):
            start = (j * (nx + 1) + i) * 6
            pillar = values[start : start + 6]
            if invert_z:
                pillar[2] = f"{-float(pillar[2]):.12g}"
                pillar[5] = f"{-float(pillar[5]):.12g}"
            output.extend(pillar)
    return output


def crop_zcorn(values: list[str], nx: int, ny: int, i0: int, i1: int, j0: int, j1: int, k0: int, k1: int, flip_j: bool, invert_z: bool) -> list[str]:
    output: list[str] = []
    for k in range(k0, k1 + 1):
        for dk in range(2):
            for target_j in range(j1 - j0 + 1):
                j = j1 - target_j if flip_j else j0 + target_j
                for dj in range(2):
                    source_dj = 1 - dj if flip_j else dj
                    for i in range(i0, i1 + 1):
                        for di in range(2):
                            index = (2 * k + dk) * (2 * ny) * (2 * nx) + (2 * j + source_dj) * (2 * nx) + (2 * i + di)
                            value = float(values[index])
                            output.append(f"{-value:.12g}" if invert_z else values[index])
    return output


def crop_cells(values: list[str], nx: int, ny: int, i0: int, i1: int, j0: int, j1: int, k0: int, k1: int, flip_j: bool) -> list[str]:
    output: list[str] = []
    for k in range(k0, k1 + 1):
        for target_j in range(j1 - j0 + 1):
            j = j1 - target_j if flip_j else j0 + target_j
            start = (k * ny + j) * nx + i0
            output.extend(values[start : start + i1 - i0 + 1])
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="Crop a cornerpoint GRDECL, including geometry and cell-sized properties.")
    parser.add_argument("input_grdecl", type=Path)
    parser.add_argument("output_grdecl", type=Path)
    parser.add_argument("--i", nargs=2, type=int, metavar=("START", "END"), required=True, help="Inclusive 1-based I range.")
    parser.add_argument("--j", nargs=2, type=int, metavar=("START", "END"), required=True, help="Inclusive 1-based J range.")
    parser.add_argument("--k", nargs=2, type=int, metavar=("START", "END"), required=True, help="Inclusive 1-based K range.")
    parser.add_argument(
        "--dfn-minimal",
        action="store_true",
        help="Write only geometry, active/layer fields, and DFN Generator properties for a robust standalone hand-off.",
    )
    parser.add_argument(
        "--dfn-petrel-style",
        action="store_true",
        help="For compatibility testing, write GRIDUNIT as `METRES MAP` and add Petrel's COORDSYS declaration.",
    )
    parser.add_argument("--dfn-flip-j", action="store_true", help="Reverse J indexing in the DFN handoff to match the Petrel reference-grid orientation.")
    parser.add_argument("--dfn-auto-orient", action="store_true", help="Reverse J only when MAPAXES-transformed I/J orientation differs from Michael's right-handed reference grid.")
    parser.add_argument("--dfn-invert-z", action="store_true", help="Convert the OpenFlow vertical sign convention to positive-down depth for the DFN handoff.")
    parser.add_argument("--dipazimuth-degrees-to-radians", action="store_true", help="Convert the DIPAZIMUTH property from dashboard degrees to the DFN Generator's radians.")
    args = parser.parse_args()

    blocks = parse(args.input_grdecl)
    nx, ny, nz = (int(float(value)) for value in blocks["SPECGRID"][:3])
    i0, i1 = (value - 1 for value in args.i)
    j0, j1 = (value - 1 for value in args.j)
    k0, k1 = (value - 1 for value in args.k)
    if not (0 <= i0 <= i1 < nx and 0 <= j0 <= j1 < ny and 0 <= k0 <= k1 < nz):
        raise ValueError(f"Requested ranges exceed source dimensions {nx} x {ny} x {nz}")

    expanded = {keyword: expand(values) for keyword, values in blocks.items()}
    cells = nx * ny * nz
    flip_j = args.dfn_flip_j
    if args.dfn_auto_orient:
        coord = [float(value) for value in expanded["COORD"]]
        def pillar(i: int, j: int) -> tuple[float, float]:
            start = (j * (nx + 1) + i) * 6
            return coord[start], coord[start + 1]
        x00, y00 = pillar(0, 0)
        x10, y10 = pillar(1, 0)
        x01, y01 = pillar(0, 1)
        local_determinant = (x10 - x00) * (y01 - y00) - (y10 - y00) * (x01 - x00)
        # COORD can be expressed in a local map frame. Account for MAPAXES
        # before comparing the horizontal orientation with Michael's reference.
        map_determinant = 1.0
        if "MAPAXES" in expanded:
            axes = [float(value) for value in expanded["MAPAXES"]]
            if len(axes) >= 6:
                x_axis = (axes[4] - axes[2], axes[5] - axes[3])
                y_axis = (axes[0] - axes[2], axes[1] - axes[3])
                map_determinant = x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0]
        determinant = local_determinant * map_determinant
        # In the positive-up display convention, both Michael's reference K
        # direction and its transformed I/J determinant are negative, giving a
        # right-handed I/J/K system. Reverse J only for the opposite case.
        flip_j = determinant > 0
        print(f"DFN orientation: transformed I/J determinant {determinant:.6g}; reverse J = {flip_j}")
    args.output_grdecl.parent.mkdir(parents=True, exist_ok=True)
    with open(path_for_io(args.output_grdecl), "w", encoding="utf-8", newline="\n") as handle:
        handle.write("-- Rectangular crop written by crop_grdecl.py\n\n")
        for keyword in ("MAPUNITS", "MAPAXES", "GRIDUNIT", "COORDSYS"):
            if keyword in expanded:
                if args.dfn_petrel_style and keyword == "GRIDUNIT":
                    write_block(handle, keyword, ["METRES", "MAP"])
                else:
                    write_block(handle, keyword, expanded[keyword])
        if args.dfn_petrel_style and "COORDSYS" not in expanded:
            write_block(handle, "COORDSYS", ["1", "5"])
        write_block(handle, "SPECGRID", [str(i1 - i0 + 1), str(j1 - j0 + 1), str(k1 - k0 + 1), *expanded["SPECGRID"][3:]])
        cropped_coord = crop_coord(expanded["COORD"], nx, ny, i0, i1, j0, j1, flip_j, args.dfn_invert_z)
        cropped_zcorn = crop_zcorn(expanded["ZCORN"], nx, ny, i0, i1, j0, j1, k0, k1, flip_j, args.dfn_invert_z)
        write_block(handle, "COORD", cropped_coord)
        write_block(handle, "ZCORN", cropped_zcorn)
        # DFM Generator's GRDECL reader expects an Eclipse active-cell mask.
        # DionisosFlow exports do not always carry one, in which case every
        # cropped cell is deliberately active.
        if "ACTNUM" not in expanded:
            crop_count = (i1 - i0 + 1) * (j1 - j0 + 1) * (k1 - k0 + 1)
            write_block(handle, "ACTNUM", ["1"] * crop_count)
        if args.dfn_minimal and "LAYERS" not in expanded:
            layers: list[str] = []
            for k in range(k0, k1 + 1):
                layers.extend([str(k + 1)] * ((i1 - i0 + 1) * (j1 - j0 + 1)))
            write_block(handle, "LAYERS", layers)
        dfn_fields = {
            "ACTNUM", "LAYERS", "DIPAZIMUTH", "YOUNGSMODULUS_PA",
            "POISSONSRATIO", "DFNPOROSITY", "FRICTIONCOEFFICIENT",
            "FRACTUREENERGY_J_M2", "DFNEFFECTIVESTRESS_MPA",
        }
        dfn_keyword_aliases = {
            "YOUNGSMODULUS_PA": "YOUNGSMODPA",
            "FRACTUREENERGY_J_M2": "FRACTUREENERGY",
        }
        for keyword, values in expanded.items():
            if keyword in {"MAPUNITS", "MAPAXES", "GRIDUNIT", "COORDSYS", "SPECGRID", "COORD", "ZCORN"}:
                continue
            if args.dfn_minimal and keyword not in dfn_fields:
                continue
            if len(values) == cells:
                cropped_values = crop_cells(values, nx, ny, i0, i1, j0, j1, k0, k1, flip_j)
                if keyword == "DIPAZIMUTH" and args.dipazimuth_degrees_to_radians:
                    cropped_values = [f"{math.radians(float(value)):.12g}" for value in cropped_values]
                write_block(handle, dfn_keyword_aliases.get(keyword, keyword), cropped_values)
            else:
                write_block(handle, keyword, values)
    print(f"Wrote {args.output_grdecl} ({i1 - i0 + 1} x {j1 - j0 + 1} x {k1 - k0 + 1} = {(i1 - i0 + 1) * (j1 - j0 + 1) * (k1 - k0 + 1):,} cells)")


if __name__ == "__main__":
    main()
