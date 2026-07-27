from __future__ import annotations

import argparse
import hashlib
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "outputs" / "Best-fit approach" / "01_3d_points_from_original_grdecls"
EXAMPLE = ROOT / "original_data" / "tmap_example_data" / "run4_fluvio_estuarine_facies_8_9"
OUTPUT_DIR = ROOT / "outputs" / "Best-fit approach" / "02_3d_points_with_tmap_data"


FACIES = {
    0: ("Undefined / no depositional facies", 0.05, 0.000, 0.18, 15.0),
    1: ("FA1a Offshore", 0.09, 0.003, 0.35, 30.0),
    2: ("FA1b Offshore transition", 0.12, 0.004, 0.28, 80.0),
    3: ("FA 2a Lower shoreface", 0.18, 0.008, 0.16, 350.0),
    4: ("FA2b Middle and Upper Shoreface", 0.24, 0.012, 0.08, 1400.0),
    5: ("FA3a Lagoon", 0.10, 0.005, 0.32, 45.0),
    6: ("FA3b Tidal flats and channels", 0.15, 0.007, 0.24, 220.0),
    8: ("FA4a Fluvial", 0.25, 0.011, 0.10, 2200.0),
    9: ("FA4b Fluvial, tidal influenced", 0.21, 0.010, 0.14, 950.0),
    10: ("FA5 Floodplain, lacustrine", 0.08, 0.004, 0.40, 20.0),
}

SUMMARY_STATS = ("mean", "stdev", "p10", "p25", "p50", "p75", "p90")
RESERVOIR_QUALITY_COLUMNS = {
    "total_porosity_mean",
    "total_porosity_stdev",
    "total_porosity_p10",
    "total_porosity_p25",
    "total_porosity_p50",
    "total_porosity_p75",
    "total_porosity_p90",
    "permeability_mean",
    "permeability_stdev",
    "permeability_p10",
    "permeability_p25",
    "permeability_p50",
    "permeability_p75",
    "permeability_p90",
}


def stable_noise(*parts: object) -> float:
    text = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.blake2b(text, digest_size=8).digest()
    return int.from_bytes(digest, "big") / float(2**64 - 1)


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def tmap_header_columns(example_path: Path) -> list[str]:
    lines = example_path.read_text(encoding="utf-8").splitlines()
    start = lines.index("BEGIN HEADER") + 1
    end = lines.index("END HEADER")
    return lines[start:end]


def filter_tmap_columns(columns: list[str], property_profile: str) -> list[str]:
    if property_profile == "all":
        return columns
    if property_profile != "reservoir_quality":
        raise ValueError(f"Unknown property profile: {property_profile}")

    selected = columns[:3]
    for column in columns[3:]:
        name = column.split(",", 1)[1]
        if name in RESERVOIR_QUALITY_COLUMNS:
            selected.append(column)
    missing = RESERVOIR_QUALITY_COLUMNS.difference(column.split(",", 1)[1] for column in selected[3:])
    if missing:
        raise ValueError(f"The example file is missing reservoir-quality columns: {', '.join(sorted(missing))}")
    return selected


def source_header_columns(path: Path) -> list[str]:
    columns: list[str] = []
    in_header = False
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if line == "BEGIN HEADER":
                in_header = True
                continue
            if line == "END HEADER":
                break
            if in_header:
                columns.append(line)
    if len(columns) < 4:
        raise ValueError(f"{path} does not look like a T>Map point-set file")
    return columns


def write_header(handle, tmap_columns: list[str], passthrough_columns: list[str]) -> None:
    handle.write("# T>Map 3D point set with attributes\n")
    handle.write("# Unit in X and Y direction: m\n")
    handle.write("# Unit in depth: m\n")
    handle.write("# Synthetic T>Map-style properties generated from DionisosFlow 3D point sets\n")
    handle.write("# T>Map project file: MVP synthetic placeholder\n")
    handle.write("# T>Map run name: synthetic_diagenetic_properties\n")
    handle.write("# TCF name: synthetic_placeholder_tcf\n")
    handle.write("# Number of realizations per point per TCF: 1\n")
    handle.write("VERSION 1\n")
    handle.write("BEGIN HEADER\n")
    handle.write("X\nY\nZ\nINT,Facies\n")
    for column in passthrough_columns:
        handle.write(f"{column}\n")
    for column in tmap_columns[3:]:
        handle.write(f"{column}\n")
    handle.write("END HEADER\n")


def source_data_lines(path: Path):
    in_header = False
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if line == "BEGIN HEADER":
                in_header = True
                continue
            if line == "END HEADER":
                in_header = False
                continue
            if line.startswith("#") or line == "VERSION 1" or in_header:
                continue
            parts = line.split()
            if len(parts) >= 4:
                yield float(parts[0]), float(parts[1]), float(parts[2]), int(float(parts[3])), parts[4:]


def stat_value(mean: float, spread: float, suffix: str, lower: float, upper: float) -> float:
    values = {
        "mean": mean,
        "stdev": spread,
        "p10": mean - 1.2816 * spread,
        "p25": mean - 0.6745 * spread,
        "p50": mean,
        "p75": mean + 0.6745 * spread,
        "p90": mean + 1.2816 * spread,
    }
    return clamp(values[suffix], lower, upper)


def split_stat(column_name: str) -> tuple[str, str] | None:
    for suffix in SUMMARY_STATS:
        marker = f"_{suffix}"
        if column_name.endswith(marker):
            return column_name[: -len(marker)], suffix
    return None


def derived_means(x: float, y: float, z: float, facies: int, row_index: int) -> dict[str, tuple[float, float, float, float]]:
    depth = abs(z)
    facies_name, phi_base, cement_base, clay_base, perm_base = FACIES.get(facies, FACIES[0])
    noise = stable_noise(round(x, 2), round(y, 2), round(z, 2), facies, row_index) - 0.5
    depth_norm = clamp((depth - 1200.0) / 2200.0, 0.0, 1.0)

    porosity = clamp(phi_base - 0.085 * depth_norm + 0.018 * noise, 0.01, 0.36)
    sec_por = clamp(0.015 + 0.04 * (1.0 - depth_norm) + 0.01 * noise, 0.0, 0.09)
    quartz_cement = clamp(cement_base + 0.06 * depth_norm + 0.008 * noise, 0.0, 0.18)
    carbonate = clamp(0.015 + 0.05 * depth_norm + (0.02 if facies in {1, 2, 5, 10, 11} else 0.0), 0.0, 0.18)
    clay_cement = clamp(0.015 + 0.09 * clay_base + 0.02 * depth_norm, 0.0, 0.12)
    matrix = clamp(0.03 + 0.55 * clay_base + 0.02 * depth_norm, 0.0, 0.45)
    total_cements = clamp(quartz_cement + carbonate + clay_cement, 0.0, 0.35)
    igv = clamp(porosity + total_cements + 0.06, 0.05, 0.42)
    compaction = clamp(0.12 + 0.42 * depth_norm + 0.16 * clay_base, 0.05, 0.8)
    grain_size = clamp(0.12 + 0.55 * phi_base - 0.12 * clay_base + 0.03 * noise, 0.03, 0.65)
    permeability = clamp(perm_base * (porosity / max(phi_base, 0.01)) ** 3 * math.exp(-3.5 * clay_base), 0.01, 10000.0)

    return {
        "grain_size": (grain_size, 0.06 + 0.015 * facies, 0.01, 1.0),
        "grain_sorting": (clamp(1.1 + 1.8 * clay_base - 0.9 * phi_base, 0.5, 3.5), 0.18, 0.4, 4.0),
        "grain_coating": (clamp(0.04 + 0.55 * clay_base, 0.0, 0.7), 0.035, 0.0, 1.0),
        "intergranular_porosity": (porosity, 0.018, 0.0, 1.0),
        "q_calc": (clamp(0.55 + 0.9 * phi_base - 0.35 * clay_base, 0.25, 0.95), 0.035, 0.0, 1.0),
        "f_calc": (clamp(0.12 + 0.08 * (facies in {8, 9}) + 0.05 * noise, 0.03, 0.35), 0.025, 0.0, 1.0),
        "r_calc": (clamp(0.08 + 0.22 * clay_base + 0.03 * depth_norm, 0.02, 0.4), 0.025, 0.0, 1.0),
        "carb_undiff": (carbonate, 0.014, 0.0, 1.0),
        "illitic_pf": (clay_cement * 0.45, 0.010, 0.0, 1.0),
        "kaolinite_undiff": (clay_cement * 0.35, 0.010, 0.0, 1.0),
        "pyrite": (clamp(0.004 + 0.025 * clay_base + 0.006 * depth_norm, 0.0, 0.05), 0.006, 0.0, 1.0),
        "k_spar_cmt": (clamp(0.006 + 0.018 * depth_norm, 0.0, 0.04), 0.006, 0.0, 1.0),
        "tios": (clamp(0.004 + 0.018 * clay_base, 0.0, 0.04), 0.005, 0.0, 1.0),
        "ankerite_rp_dolomite": (clamp(0.01 + 0.05 * depth_norm + 0.025 * clay_base, 0.0, 0.12), 0.012, 0.0, 1.0),
        "total_sec_por": (sec_por, 0.012, 0.0, 1.0),
        "total_matrix": (matrix, 0.020, 0.0, 1.0),
        "total_cements": (total_cements, 0.020, 0.0, 1.0),
        "total_carbonate_cmt": (carbonate, 0.014, 0.0, 1.0),
        "total_clay_cmt": (clay_cement, 0.012, 0.0, 1.0),
        "igv": (igv, 0.025, 0.0, 1.0),
        "mapl": (clamp(0.12 + 0.45 * matrix, 0.0, 1.0), 0.025, 0.0, 1.0),
        "copl": (clamp(0.06 + 0.38 * depth_norm, 0.0, 1.0), 0.025, 0.0, 1.0),
        "cepl": (clamp(0.08 + 0.72 * total_cements, 0.0, 1.0), 0.030, 0.0, 1.0),
        "icompact": (compaction, 0.035, 0.0, 1.0),
        "quartz_cement": (quartz_cement, 0.014, 0.0, 1.0),
        "total_porosity": (porosity + sec_por, 0.020, 0.0, 1.0),
        "mpor_total": (clamp(matrix * 0.35 + clay_cement, 0.0, 1.0), 0.020, 0.0, 1.0),
        "permeability": (permeability, max(permeability * 0.35, 0.02), 0.0, 10000.0),
    }


def column_value(
    column: str,
    x: float,
    y: float,
    z: float,
    facies: int,
    row_index: int,
    means: dict[str, tuple[float, float, float, float]],
) -> float:
    name = column.split(",", 1)[1]
    depth = abs(z)
    noise = stable_noise(name, round(x, 2), round(y, 2), round(z, 2), facies, row_index) - 0.5
    if name == "temperature_c":
        return clamp(18.0 + 0.026 * depth + 2.0 * noise, 20.0, 120.0)
    if name == "burial_depth_m":
        return depth
    if name == "effective_stress_mpa":
        return clamp(0.0145 * depth + 4.0 * noise, 0.0, 60.0)
    if name == "overpressure_mpa":
        return clamp(0.3 + 0.0012 * depth + 0.7 * noise, 0.0, 8.0)
    if name == "permeability_geomean":
        mean, spread, lower, upper = means["permeability"]
        return clamp(mean * 0.78, lower, upper)

    stat = split_stat(name)
    if stat is None:
        return 0.0
    base_name, suffix = stat
    if base_name not in means:
        return 0.0
    mean, spread, lower, upper = means[base_name]
    if suffix == "mean":
        mean = clamp(mean * (1.0 + 0.05 * noise), lower, upper)
    return stat_value(mean, spread, suffix, lower, upper)


def write_pointset(source: Path, columns: list[str], output_dir: Path) -> int:
    target = output_dir / f"{source.name}_tmap_synthetic"
    passthrough_columns = source_header_columns(source)[4:]
    count = 0
    with target.open("w", encoding="utf-8", newline="\n") as out:
        write_header(out, columns, passthrough_columns)
        for count, (x, y, z, facies, passthrough_values) in enumerate(source_data_lines(source), start=1):
            if len(passthrough_values) != len(passthrough_columns):
                raise ValueError(f"{source} row {count} has {len(passthrough_values)} passthrough values; expected {len(passthrough_columns)}")
            means = derived_means(x, y, z, facies, count)
            values = [f"{x:.2f}", f"{y:.2f}", f"{z:.2f}", str(facies)]
            values.extend(passthrough_values)
            values.extend(f"{column_value(column, x, y, z, facies, count, means):.6g}" for column in columns[3:])
            out.write(" ".join(values) + "\n")
    return count


def count_facies_in_sources(source_dir: Path, glob_pattern: str) -> Counter[int]:
    counts = Counter()
    for source in sorted(source_dir.glob(glob_pattern)):
        if source.name.endswith(".crsmeta.xml"):
            continue
        for _, _, _, facies, _ in source_data_lines(source):
            counts[facies] += 1
    return counts


def write_facies_readme(output_dir: Path, facies_counts: Counter[int]) -> None:
    total_points = sum(facies_counts.values())
    lines = [
        "# Facies codes",
        "",
        "Source: `facies_codes.png` in the workspace root, read after the corrected facies-code update.",
        "",
        "| Code | Name | Percent in source point sets | N in source point sets | Synthetic property tendency |",
        "| ---: | --- | ---: | ---: | --- |",
    ]
    codes = sorted(set(FACIES).union(facies_counts))
    for code in codes:
        name, phi, cement, clay, perm = FACIES.get(code, (f"Unknown facies {code}", 0.0, 0.0, 0.0, 0.0))
        n = facies_counts.get(code, 0)
        percent = (n / total_points * 100) if total_points else 0.0
        percent_text = f"{percent:.2f}" if n else "0.00"
        tendency = (
            f"porosity baseline {phi:.2f}, cement baseline {cement:.3f}, "
            f"clay/matrix tendency {clay:.2f}, permeability baseline {perm:.0f} mD"
        )
        if code not in FACIES:
            tendency = "no synthetic property baseline defined"
        lines.append(
            f"| {code} | {name} | {percent_text} | {n} | {tendency} |"
        )
    lines.extend(
        [
            "",
            "Generated T>Map-style point sets retain the original XYZ and facies code from the source 3D point sets,",
            "then append the attributes from `original_data/tmap_example_data/run4_fluvio_estuarine_facies_8_9`.",
            "Porosity, cement, mineral, clay, matrix, and compaction fractions are written as 0-1 fractions.",
            "Permeability is written in mD and clamped to 0-10000.",
        ]
    )
    (output_dir / "FACIES_CODES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic T>Map-style properties for T>Map 3D point-set ASCII files.")
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--example", type=Path, default=EXAMPLE, help="T>Map example point-set file used for attribute names.")
    parser.add_argument("--glob", default="*_3d_pointset", help="Input point-set filename glob.")
    parser.add_argument(
        "--property-profile",
        choices=("all", "reservoir_quality"),
        default="all",
        help="Use 'reservoir_quality' to write only total porosity and permeability mean/stdev/P10/P25/P50/P75/P90.",
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    columns = filter_tmap_columns(tmap_header_columns(args.example), args.property_profile)
    totals = []
    for source in sorted(args.source_dir.glob(args.glob)):
        # Ignore stale CRS sidecars from pre-CRS-removal workflow runs.
        if source.name.endswith(".crsmeta.xml"):
            continue
        totals.append((source.name, write_pointset(source, columns, args.output_dir)))
    facies_counts = count_facies_in_sources(args.source_dir, args.glob)
    write_facies_readme(args.output_dir, facies_counts)
    print(f"Wrote {len(totals)} synthetic T>Map point sets to {args.output_dir}")
    for name, count in totals:
        print(f"{name}: {count} points")


if __name__ == "__main__":
    main()
