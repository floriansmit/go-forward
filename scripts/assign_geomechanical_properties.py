"""Append transparent facies-calibrated geomechanical estimates to a GRDECL."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np

from grdecl_utils import grdecl_cell_centers, grdecl_keyword, path_for_io, tokenize_grdecl, write_property

NO_VALUE = -77777.0


def expand(tokens: list[str]) -> list[float]:
    values: list[float] = []
    for token in tokens:
        if "*" in token:
            count, value = token.split("*", 1)
            values.extend([float(value)] * int(float(count)))
        else:
            values.append(float(token))
    return values


def valid(value: float) -> bool:
    return value not in {-999.0, -77777.0} and value == value


def horizon_smoothed_dip_azimuth(path: Path, smoothing_radius_cells: int = 3) -> list[float]:
    """Return local down-dip azimuths from a smoothed model-top horizon.

    At each I/J column, a Gaussian-weighted local plane is fitted to the
    model-top depth. Its X/Y depth gradient gives the down-dip direction,
    clockwise from North. This follows broad horizon contours while avoiding
    cell-scale noise. The resulting I/J field is repeated through K.
    """
    data = tokenize_grdecl(path, {"SPECGRID"})
    nx, ny, nz = (int(float(value)) for value in data["SPECGRID"][:3])
    centres = grdecl_cell_centers(path)
    top = np.asarray(centres[: nx * ny], dtype=float).reshape(ny, nx, 3)
    x, y, depth = top[:, :, 0], top[:, :, 1], -top[:, :, 2]
    radius = max(1, int(smoothing_radius_cells))
    sigma = max(radius / 1.5, 0.5)
    azimuth = np.zeros((ny, nx), dtype=float)
    for j in range(ny):
        for i in range(nx):
            j0, j1 = max(0, j - radius), min(ny, j + radius + 1)
            i0, i1 = max(0, i - radius), min(nx, i + radius + 1)
            jj, ii = np.mgrid[j0:j1, i0:i1]
            # Smooth in grid neighbourhood, but fit the slope in real projected
            # coordinates so rotated or irregular grids retain correct azimuth.
            distance2 = (ii - i) ** 2 + (jj - j) ** 2
            weights = np.exp(-distance2 / (2.0 * sigma * sigma)).ravel()
            local_x, local_y, local_depth = x[j0:j1, i0:i1].ravel(), y[j0:j1, i0:i1].ravel(), depth[j0:j1, i0:i1].ravel()
            design = np.column_stack((np.ones_like(local_x), local_x, local_y))
            coefficients, *_ = np.linalg.lstsq(design * np.sqrt(weights)[:, None], local_depth * np.sqrt(weights), rcond=None)
            _, depth_east_gradient, depth_north_gradient = coefficients
            azimuth[j, i] = (
                math.degrees(math.atan2(depth_east_gradient, depth_north_gradient)) % 360.0
                if math.hypot(depth_east_gradient, depth_north_gradient) >= 1e-12
                else 0.0
            )
    return np.tile(azimuth.ravel(), nz).tolist()


def main() -> None:
    parser = argparse.ArgumentParser(description="Append facies-calibrated porosity/cement/stress geomechanical estimates to a GRDECL.")
    parser.add_argument("--input-grdecl", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--facies-property", default="Facies")
    parser.add_argument("--porosity-property", required=True, help="T>Map porosity property in vol %% or fraction.")
    parser.add_argument("--cement-property", default=None, help="Optional quartz or total cement property in vol %% or fraction.")
    parser.add_argument("--stress-property", default=None, help="Optional effective-stress property in MPa.")
    parser.add_argument("--shale-fallback", action="store_true", help="For shale_porosity_stress facies without T>Map porosity, use the configured depth-compaction fallback.")
    parser.add_argument("--write-dipazimuth", action="store_true", help="Append a locally smoothed, top-horizon-derived DIPAZIMUTH property, in degrees clockwise from North.")
    parser.add_argument("--dipazimuth-smoothing-cells", type=int, default=3, help="Local top-horizon smoothing radius in I/J cells for DIPAZIMUTH.")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    defaults = config.get("defaults", {})
    facies_parameters = config.get("facies", {})
    wanted = {args.facies_property, args.porosity_property}
    if args.cement_property:
        wanted.add(args.cement_property)
    if args.stress_property:
        wanted.add(args.stress_property)
    fields = {name: expand(tokens) for name, tokens in tokenize_grdecl(args.input_grdecl, wanted).items()}
    facies = [int(value) for value in fields[args.facies_property]]
    porosity = fields[args.porosity_property]
    cement = fields.get(args.cement_property, [0.0] * len(facies))
    # An unselected/absent stress field is missing data, not zero effective
    # stress.  Using NO_VALUE lets the explicit depth fallback populate it.
    stress = fields.get(args.stress_property, [NO_VALUE] * len(facies))
    centers = grdecl_cell_centers(args.input_grdecl) if args.shale_fallback else [(0.0, 0.0, 0.0)] * len(facies)
    # Write only fields directly selectable by the GRDECL-capable DFM Generator
    # plus the porosity/stress provenance needed to audit shale fallback cells.
    results = {name: [] for name in (
        "DFNPorosity", "DFNEffectiveStress_MPa",
        "YoungsModulus_Pa",
        "PoissonsRatio", "FrictionCoefficient", "FractureEnergy_J_m2", "GeomechSource",
    )}
    for code, phi_raw, cement_raw, stress_raw, (_, _, z) in zip(facies, porosity, cement, stress, centers):
        params = {**defaults, **facies_parameters.get(str(code), {})}
        required = ("young_reference_gpa", "poissons_ratio", "critical_porosity", "porosity_exponent", "friction_coefficient", "cohesion_mpa", "tensile_strength_mpa", "fracture_energy_j_m2")
        formula = str(params.get("formula", "clean_sandstone_critical_porosity"))
        source = 1.0 if valid(phi_raw) else 0.0
        # The dashboard option is an explicit opt-in for cells that were not
        # sent to T>Map (or have no returned value). Apply the depth trend to
        # every such cell, while retaining its selected facies mechanics below.
        # This prevents opaque -77777 gaps in DFN input grids; GeomechSource=2
        # distinguishes these estimates from returned T>Map data.
        if not valid(phi_raw) and args.shale_fallback:
            depth = max(0.0, float(params.get("fallback_depth_datum_m", 0.0)) - z)
            phi_raw = float(params.get("fallback_porosity_surface", 0.55)) * math.exp(
                -float(params.get("fallback_compaction_coefficient_per_m", 0.00046)) * depth
            )
            if not valid(stress_raw):
                stress_raw = float(params.get("fallback_effective_stress_gradient_mpa_per_m", 0.015)) * depth
            source = 2.0
        if not valid(phi_raw) or any(name not in params for name in required):
            for values in results.values(): values.append(NO_VALUE)
            continue
        phi = phi_raw / 100.0 if phi_raw > 1 else phi_raw
        cement_fraction = cement_raw / 100.0 if valid(cement_raw) and cement_raw > 1 else (cement_raw if valid(cement_raw) else 0.0)
        phi_c = max(float(params["critical_porosity"]), 1e-6)
        if formula == "shale_porosity_stress":
            # Empirical shale trend: porosity loss and effective stress stiffen
            # the framework; calibrate the exponent per source/facies.
            compact = math.exp(-float(params["porosity_exponent"]) * phi)
            cement_factor = 1.0
        else:
            # Critical-porosity form, suitable as a transparent starting point
            # for clean sandstone, chalk, and carbonate parameterisations.
            compact = max(0.0, 1.0 - phi / phi_c) ** float(params["porosity_exponent"])
            cement_factor = 1.0 + float(params.get("cement_factor", 0.0)) * cement_fraction
        stress_factor = 1.0
        if valid(stress_raw):
            stress_factor += float(params.get("stress_factor", 0.0)) * max(0.0, stress_raw) / max(float(params.get("stress_reference_mpa", 1.0)), 1e-6)
        young = max(float(params.get("minimum_young_gpa", 0.01)), float(params["young_reference_gpa"]) * compact * cement_factor * stress_factor)
        nu = min(max(float(params["poissons_ratio"]), 0.001), 0.499)
        dfn_stress = stress_raw if valid(stress_raw) else NO_VALUE
        for name, value in (
            ("DFNPorosity", phi), ("DFNEffectiveStress_MPa", dfn_stress),
            ("YoungsModulus_Pa", young * 1e9),
            ("PoissonsRatio", nu), ("FrictionCoefficient", params["friction_coefficient"]),
            ("FractureEnergy_J_m2", params["fracture_energy_j_m2"]), ("GeomechSource", source),
        ):
            results[name].append(float(value))
    if args.write_dipazimuth:
        results["DIPAZIMUTH"] = horizon_smoothed_dip_azimuth(args.input_grdecl, args.dipazimuth_smoothing_cells)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{args.input_grdecl.stem}_with_geomechanical_properties.grdecl"
    # ACTNUM is optional in DionisosFlow GRDECL exports.  The shared tokenizer
    # intentionally raises for a missing requested keyword, so treat that one
    # case as an absent active-cell mask and add an all-active field below.
    try:
        has_actnum = "ACTNUM" in tokenize_grdecl(args.input_grdecl, {"ACTNUM"})
    except ValueError as exc:
        if "ACTNUM" not in str(exc):
            raise
        has_actnum = False
    with open(path_for_io(args.input_grdecl), "r", encoding="utf-8") as source, open(path_for_io(output), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(source.read().rstrip() + "\n\n-- Facies-calibrated empirical geomechanical estimates for DFN preparation.\n")
        if not has_actnum:
            # Required by the standalone DFM Generator. DionisosFlow GRDECLs
            # may omit it; these workflows treat all source cells as active.
            write_property(handle, "ACTNUM", ["1"] * len(facies))
        if args.write_dipazimuth:
            handle.write(f"-- DIPAZIMUTH is derived from locally smoothed model-top-horizon gradients (radius {max(1, args.dipazimuth_smoothing_cells)} I/J cells), in degrees clockwise from North.\n")
        for name, values in results.items():
            write_property(handle, grdecl_keyword(name), [f"{value:.8g}" for value in values])
    print(output)


if __name__ == "__main__":
    main()
