"""Prepare current and returned T>Map point sets for a CellIndex-based hand-off.

Geocosm's historical export contains a T>Map-internal ``point_id`` rather
than the GRDECL ``CellIndex``.  This utility reconstructs CellIndex from XYZ
and Facies without rerunning T>Map, then writes a complete source point set
that Geocosm can use for future runs.
"""

from __future__ import annotations

import argparse
import math
from collections import defaultdict
from pathlib import Path

from grdecl_utils import grdecl_cell_centers, path_for_io, tokenize_grdecl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRDECL = ROOT / "input" / "source_grdecls_from_dionisosflow" / "SS_201.5_1xBath_1xThSub_ConS_FSM-FDM-1-Base.grdecl"
DEFAULT_EXPORT = ROOT / "reference_examples" / "tmap_example" / "gassum_base_tmap.txt"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "geocosm_handoff"


def decode_text(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8", "cp1252"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    raise ValueError(f"Could not decode {path}")


def column_name(header_line: str) -> str:
    return header_line.split(",", 1)[-1].strip().strip('"').strip()


def normalize(name: str) -> str:
    return " ".join(name.lower().replace("_", " ").split())


def expand_property(path: Path, keyword: str) -> list[int]:
    values = tokenize_grdecl(path, {keyword})[keyword]
    expanded: list[int] = []
    for value in values:
        if "*" in value:
            count, repeated = value.split("*", 1)
            expanded.extend([int(float(repeated))] * int(count))
        else:
            expanded.append(int(float(value)))
    return expanded


def bucket_key(x: float, y: float, z: float, size: float = 0.10) -> tuple[int, int, int]:
    return round(x / size), round(y / size), round(z / size)


def match_cell_indices(
    centers: list[tuple[float, float, float]],
    facies_values: list[int],
    exported_rows: list[list[str]],
    x_index: int,
    y_index: int,
    z_index: int,
    facies_index: int,
    tolerance: float,
    require_facies_match: bool,
) -> tuple[list[int], float, int]:
    buckets: dict[tuple[int, int, int], list[int]] = defaultdict(list)
    for cell_index, (x, y, z) in enumerate(centers):
        buckets[bucket_key(x, y, z)].append(cell_index)

    assigned: set[int] = set()
    matched: list[int] = []
    max_distance = 0.0
    facies_mismatches = 0
    tolerance_squared = tolerance * tolerance
    for row_number, row in enumerate(exported_rows, start=1):
        x, y, z = float(row[x_index]), float(row[y_index]), float(row[z_index])
        facies = int(float(row[facies_index]))
        base = bucket_key(x, y, z)
        best: tuple[float, int] | None = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for candidate in buckets.get((base[0] + dx, base[1] + dy, base[2] + dz), []):
                        if candidate in assigned or (require_facies_match and facies_values[candidate] != facies):
                            continue
                        cx, cy, cz = centers[candidate]
                        distance_squared = (cx - x) ** 2 + (cy - y) ** 2 + (cz - z) ** 2
                        if distance_squared <= tolerance_squared and (best is None or distance_squared < best[0]):
                            best = distance_squared, candidate
        if best is None:
            raise ValueError(
                f"Export row {row_number} ({x:.2f}, {y:.2f}, {z:.2f}, facies {facies}) "
                f"could not be uniquely matched within {tolerance:g} m"
            )
        distance_squared, cell_index = best
        assigned.add(cell_index)
        matched.append(cell_index)
        if facies_values[cell_index] != facies:
            facies_mismatches += 1
        max_distance = max(max_distance, math.sqrt(distance_squared))
    return matched, max_distance, facies_mismatches


def write_complete_pointset(path: Path, centers: list[tuple[float, float, float]], facies_values: list[int]) -> None:
    Path(path_for_io(path.parent)).mkdir(parents=True, exist_ok=True)
    with open(path_for_io(path), "w", encoding="utf-8", newline="\n") as out:
        out.write("# T>Map 3D point set with attributes\n")
        out.write("# Complete GRDECL cell-centre point set with stable CellIndex for T>Map hand-off.\n")
        out.write("# CellIndex is zero-based in GRDECL K, J, I traversal order.\n")
        out.write("# Unit in X and Y direction: m\n# Unit in depth: m\n")
        out.write("VERSION 1\nBEGIN HEADER\nX\nY\nZ\nINT,Facies\nINT,CellIndex\nEND HEADER\n")
        for cell_index, ((x, y, z), facies) in enumerate(zip(centers, facies_values)):
            out.write(f"{x:.2f} {y:.2f} {z:.2f} {facies} {cell_index}\n")


def write_handoff_spec(path: Path) -> None:
    requested_columns = (
        "FLOAT,total_porosity_mean",
        "FLOAT,total_porosity_stdev",
        "FLOAT,total_porosity_p10",
        "FLOAT,total_porosity_p50",
        "FLOAT,total_porosity_p90",
        "FLOAT,permeability_mean",
        "FLOAT,permeability_stdev",
        "FLOAT,permeability_p10",
        "FLOAT,permeability_p50",
        "FLOAT,permeability_p90",
    )
    with open(path_for_io(path), "w", encoding="utf-8", newline="\n") as out:
        out.write("# Geocosm T>Map point-set hand-off\n\n")
        out.write("## Input columns — retain exactly\n\n")
        out.write("The first five output columns must remain in this order and retain their values exactly:\n\n")
        out.write("```text\nX\nY\nZ\nINT,Facies\nINT,CellIndex\n```\n\n")
        out.write("`CellIndex` is zero-based and identifies the corresponding cell in the supplied GRDECL. "
                  "Do not replace it with a T>Map-generated `point_id`.\n\n")
        out.write("## Requested T>Map output columns\n\n")
        out.write("Append the following columns after `CellIndex`, in this order, for PyThermogis-compatible porosity and permeability uncertainty summaries:\n\n```text\n")
        out.write("\n".join(requested_columns))
        out.write("\n```\n\n")
        out.write("Other useful T>Map fields may follow these columns. Use `-77777` where no simulation result exists; "
                  "this is the no-value marker used directly by the GRDECL append workflow.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add GRDECL CellIndex to an existing Geocosm T>Map export and create a future hand-off point set.")
    parser.add_argument("--grdecl", type=Path, default=DEFAULT_GRDECL)
    parser.add_argument("--facies-property", default="Facies", help="GRDECL facies keyword (case-sensitive).")
    parser.add_argument("--geocosm-export", type=Path, default=DEFAULT_EXPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--tolerance", type=float, default=0.05, help="XYZ matching tolerance in metres.")
    parser.add_argument("--require-facies-match", action="store_true", help="Fail if Geocosm Facies differs from the current GRDECL at a matched XYZ.")
    args = parser.parse_args()

    centers = grdecl_cell_centers(args.grdecl)
    facies_values = expand_property(args.grdecl, args.facies_property)
    if len(centers) != len(facies_values):
        raise ValueError(f"{args.grdecl.name}: {len(centers)} cell centres but {len(facies_values)} facies values")

    text, encoding = decode_text(args.geocosm_export)
    lines = text.splitlines()
    try:
        header_start = lines.index("BEGIN HEADER")
        header_end = lines.index("END HEADER")
    except ValueError as exc:
        raise ValueError(f"{args.geocosm_export} is not a T>Map point-set file") from exc
    header = lines[header_start + 1 : header_end]
    names = [column_name(line) for line in header]
    index_by_name = {normalize(name): index for index, name in enumerate(names)}
    required = {"x", "y", "z", "facies", "point id"}
    missing = required.difference(index_by_name)
    if missing:
        raise ValueError(f"{args.geocosm_export.name} is missing required column(s): {', '.join(sorted(missing))}")

    data_line_indices: list[int] = []
    exported_rows: list[list[str]] = []
    for line_index, line in enumerate(lines[header_end + 1 :], start=header_end + 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped == "VERSION 1":
            continue
        values = stripped.split()
        if len(values) != len(header):
            raise ValueError(f"{args.geocosm_export.name} line {line_index + 1} has {len(values)} values; expected {len(header)}")
        data_line_indices.append(line_index)
        exported_rows.append(values)

    matched_indices, max_distance, facies_mismatches = match_cell_indices(
        centers,
        facies_values,
        exported_rows,
        index_by_name["x"],
        index_by_name["y"],
        index_by_name["z"],
        index_by_name["facies"],
        args.tolerance,
        args.require_facies_match,
    )

    cell_index_column = index_by_name["point id"]
    core_indices = [index_by_name["x"], index_by_name["y"], index_by_name["z"], index_by_name["facies"], cell_index_column]
    ordered_indices = core_indices + [index for index in range(len(header)) if index not in core_indices]
    replacement_header = ["X", "Y", "Z", "INT,Facies", "INT,CellIndex"] + [header[index] for index in ordered_indices[5:]]
    rewritten = list(lines)
    rewritten[header_start + 1 : header_end] = replacement_header
    for line_index, row, cell_index in zip(data_line_indices, exported_rows, matched_indices):
        reordered_row = [row[index] for index in ordered_indices]
        reordered_row[4] = str(cell_index)
        rewritten[line_index] = " ".join(reordered_row)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = args.grdecl.with_suffix("").name
    returned_output = args.output_dir / f"{stem}_3d_pointset_tmap_geocosm.txt"
    complete_output = args.output_dir / f"{stem}_3d_pointset.txt"
    specification_output = args.output_dir / "GEOCOSM_HANDOFF_SPEC.md"
    with open(path_for_io(returned_output), "w", encoding=encoding, newline="\n") as out:
        out.write("# CellIndex reconstructed from XYZ against the supplied GRDECL.\n")
        if facies_mismatches:
            out.write(f"# WARNING: Geocosm Facies differs from the supplied GRDECL for {facies_mismatches} returned rows.\n")
        out.write("\n".join(rewritten) + "\n")
    write_complete_pointset(complete_output, centers, facies_values)
    write_handoff_spec(specification_output)

    print(f"Mapped {len(matched_indices)}/{len(exported_rows)} Geocosm rows to CellIndex; max XYZ distance {max_distance:.3f} m")
    print(f"Facies mismatches against the supplied GRDECL: {facies_mismatches}")
    print(f"Returned export with CellIndex: {returned_output}")
    print(f"Complete future hand-off point set ({len(centers)} cells): {complete_output}")
    print(f"Geocosm hand-off specification: {specification_output}")


if __name__ == "__main__":
    main()
