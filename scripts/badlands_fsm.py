"""Badlands run preparation and regular stratal-HDF5 to GRDECL conversion.

The regular ``sed.time*.hdf5`` mesh is nodal, not cell-centred. Each quad
becomes one GRDECL column; zero-thickness layers are retained as pinches or
removed only when empty everywhere. TIN/stratal.time outputs are not accepted.
"""
from __future__ import annotations

import hashlib
import json
import math
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from grdecl_utils import write_property

DEFAULTS = {
    "nx": 31, "ny": 31, "spacing_m": 500.0,
    "origin_x": 0.0, "origin_y": 0.0,
    "upstream_elevation_m": 250.0, "basin_elevation_m": -150.0,
    "roughness_m": 2.0, "seed": 42,
    "duration_years": 100000.0, "output_interval_years": 10000.0,
    "layer_interval_years": 5000.0, "rainfall_m_year": 1.0,
    "sea_level_m": 0.0, "subsidence_m_year": 0.0005,
    "erodibility": 1e-6, "aerial_diffusion": 0.01, "marine_diffusion": 0.1,
}


def regular_grid(coords: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    coords = np.asarray(coords, dtype=float)
    if coords.ndim != 2 or coords.shape[1] < 2 or not np.isfinite(coords).all():
        raise ValueError("Coordinates must be a finite N x 2 (or N x 3) array.")
    xs, ys = np.unique(coords[:, 0]), np.unique(coords[:, 1])
    if len(xs) < 2 or len(ys) < 2 or len(xs) * len(ys) != len(coords):
        raise ValueError("Expected a complete rectangular regular stratal grid, not TIN or partitioned output.")
    for axis in (xs, ys):
        if not np.allclose(np.diff(axis), axis[1] - axis[0], rtol=1e-6, atol=1e-6):
            raise ValueError("Stratal XY spacing must be regular.")
    order = np.lexsort((coords[:, 0], coords[:, 1]))
    xx, yy = np.meshgrid(xs, ys)
    if not np.allclose(coords[order, :2], np.column_stack((xx.ravel(), yy.ravel())), rtol=0, atol=1e-6):
        raise ValueError("Duplicate or missing stratal XY nodes.")
    return xs, ys, order


def prepare_run(run_dir: Path, settings: dict, dem: np.ndarray | None = None) -> Path:
    """Write an isolated, reproducible run folder. Never overwrite an old run."""
    custom_dem = dem is not None
    config = {**DEFAULTS, **settings}
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in config.values()):
        raise ValueError("All model parameters must be finite numbers.")
    for key in ("duration_years", "output_interval_years", "layer_interval_years", "spacing_m"):
        if config[key] <= 0:
            raise ValueError(f"{key} must be positive.")
    for key in ("roughness_m", "rainfall_m_year", "erodibility", "aerial_diffusion", "marine_diffusion"):
        if config[key] < 0:
            raise ValueError(f"{key} cannot be negative.")
    duration, display, layer = (config[k] for k in ("duration_years", "output_interval_years", "layer_interval_years"))
    for ratio in (duration / display, display / layer):
        if ratio < 1 or not math.isclose(ratio, round(ratio), abs_tol=1e-8):
            raise ValueError("Duration must be divisible by output interval; output interval by layer interval.")
    if dem is None:
        nx, ny = int(config["nx"]), int(config["ny"])
        if nx != config["nx"] or ny != config["ny"] or min(nx, ny) < 3 or nx * ny > 1_000_000:
            raise ValueError("DEM dimensions must be integers >= 3, with at most 1,000,000 nodes.")
        xx, yy = np.meshgrid(
            config["origin_x"] + np.arange(nx) * config["spacing_m"],
            config["origin_y"] + np.arange(ny) * config["spacing_m"],
        )
        zz = np.linspace(config["upstream_elevation_m"], config["basin_elevation_m"], ny)[:, None]
        zz = zz + np.random.default_rng(int(config["seed"])).normal(0, config["roughness_m"], (ny, nx))
        dem = np.column_stack((xx.ravel(), yy.ravel(), zz.ravel()))
    dem = np.asarray(dem, dtype=float)
    if dem.ndim != 2 or dem.shape[1] != 3:
        raise ValueError("DEM must contain three columns: X Y elevation, in metres.")
    xs, ys, order = regular_grid(dem)
    if min(len(xs), len(ys)) < 3 or not math.isclose(xs[1] - xs[0], ys[1] - ys[0], rel_tol=1e-6):
        raise ValueError("Badlands DEM needs at least 3 x 3 nodes and equal X/Y spacing.")
    run_dir.mkdir(parents=True, exist_ok=False)
    np.savetxt(run_dir / "dem.csv", dem[order], fmt="%.10g")
    root = ET.Element("badlands")

    def section(name: str, values: dict) -> None:
        item = ET.SubElement(root, name)
        for key, value in values.items():
            ET.SubElement(item, key).text = str(value)

    section("grid", {"demfile": "dem.csv", "resfactor": 1, "boundary": "fixed"})
    section("time", {"start": 0, "end": duration, "display": display, "meshout": 1})
    section("strata", {"stratdx": float(xs[1] - xs[0]), "laytime": layer, "poro0": 0.52, "poroC": 0.47})
    section("sea", {"position": config["sea_level_m"]})
    rain = ET.SubElement(root, "precipitation")
    ET.SubElement(rain, "climates").text = "1"
    event = ET.SubElement(rain, "rain")
    for key, value in {"rstart": 0, "rend": duration, "rval": config["rainfall_m_year"]}.items():
        ET.SubElement(event, key).text = str(value)
    if config["subsidence_m_year"]:
        np.savetxt(run_dir / "tectonics.csv", np.full(len(dem), -config["subsidence_m_year"] * duration))
        tectonic = ET.SubElement(root, "tectonic")
        ET.SubElement(tectonic, "events").text = "1"
        event = ET.SubElement(tectonic, "disp")
        for key, value in {"dstart": 0, "dend": duration, "dfile": "tectonics.csv"}.items():
            ET.SubElement(event, key).text = str(value)
    section("sp_law", {"dep": 1, "m": 0.5, "n": 1.0, "erodibility": config["erodibility"]})
    section("creep", {"caerial": config["aerial_diffusion"], "cmarine": config["marine_diffusion"]})
    ET.SubElement(root, "outfolder").text = "output"
    ET.indent(root)
    xml = run_dir / "model.xml"
    ET.ElementTree(root).write(xml, encoding="utf-8", xml_declaration=True)
    shutil.copyfile(Path(__file__).with_name("run_badlands_model.py"), run_dir / "run_model.py")
    config.update({"dem_source": "uploaded" if custom_dem else "generated"})
    # Provenance records the actual grid, including custom DEM dimensions.
    config.update({"dem_nodes_x": len(xs), "dem_nodes_y": len(ys), "dem_sha256": hashlib.sha256((run_dir / "dem.csv").read_bytes()).hexdigest()})
    (run_dir / "settings.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return xml


def stratal_files(run_dir: Path) -> list[Path]:
    import re

    files = [p for p in run_dir.glob("output*/h5/sed.time*.hdf5") if re.fullmatch(r"sed\.time\d+\.hdf5", p.name)]
    return sorted(files, key=lambda p: int(re.search(r"time(\d+)", p.name).group(1)))


def _mean_corners(values: np.ndarray) -> np.ndarray:
    return (values[:-1, :-1] + values[1:, :-1] + values[:-1, 1:] + values[1:, 1:]) / 4


def install_export(export: Path, source_dir: Path) -> Path:
    """Add an exported model without replacing a source grid or facies dictionary."""
    manifest_path = export.with_suffix(".badlands.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    config_path = source_dir / "facies_config.json"
    names = {"terrestrial": "Badlands terrestrial proxy", "shallow_marine": "Badlands shallow marine proxy", "offshore": "Badlands offshore proxy"}
    codes = manifest["facies_codes"]
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))
        missing = set(map(str, codes.values())) - set(config.get("facies_names", {}))
        if missing:
            raise ValueError(f"Facies codes {sorted(missing)} are absent from the project dictionary. Map to existing codes or use a new project.")
    target = source_dir / export.name
    if target.exists() or target.with_suffix(".badlands.json").exists():
        raise FileExistsError(f"Source model already exists: {target}")
    source_dir.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as out:
        out.write(export.read_bytes())
    with target.with_suffix(".badlands.json").open("xb") as out:
        out.write(manifest_path.read_bytes())
    if not config_path.exists():
        config = {
            "facies_property": "Facies", "facies_names": {str(code): names[environment] for environment, code in codes.items()},
            "facies_colors": {str(code): color for code, color in zip(codes.values(), ("#44915c", "#e5c343", "#4676b2"), strict=True)},
            "facies_metadata": {str(code): {"tmap_enabled": True} for code in codes.values()},
        }
        with config_path.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(config, indent=2) + "\n")
    return target


def export_grdecl(
    source: Path, target: Path, *, datum_elevation_m: float = 0.0,
    shallow_depth_m: float = 30.0, facies_codes: tuple[int, int, int] = (1, 2, 3),
    min_thickness_m: float = 1e-6,
) -> dict:
    """Export regular Badlands nodal layers with K=1 youngest/topmost.

    Facies are explicit depositional-environment proxies from layElev, not
    sedimentological predictions. Elevations become depth = datum - elevation.
    """
    import h5py

    if not all(math.isfinite(v) for v in (datum_elevation_m, shallow_depth_m, min_thickness_m)) or shallow_depth_m <= 0 or min_thickness_m < 0:
        raise ValueError("Datum and thresholds must be finite; shallow depth > 0 and minimum thickness >= 0.")
    if len(facies_codes) != 3 or any(int(c) != c or c <= 0 for c in facies_codes):
        raise ValueError("Supply three positive integer facies codes (terrestrial, shallow, offshore).")
    if target.exists() or target.with_suffix(".badlands.json").exists():
        raise FileExistsError(f"Export already exists: {target}. Choose a new filename.")
    with h5py.File(source, "r") as handle:
        required = ("coords", "layDepth", "layThick", "layElev")
        if any(name not in handle for name in required):
            raise ValueError("Use the regular sed.timeN.hdf5 stratigraphy, containing coords, layDepth, layThick and layElev.")
        coords, depth, thick, paleo = (np.asarray(handle[name], dtype=float) for name in required)
        poro = np.asarray(handle["layPoro"], dtype=float) if "layPoro" in handle else None
    xs, ys, order = regular_grid(coords)
    if depth.ndim != 2 or depth.shape != thick.shape or depth.shape != paleo.shape or depth.shape[0] != len(coords):
        raise ValueError("Stratal properties must have matching [node, layer] shapes.")
    if not all(np.isfinite(a).all() for a in (depth, thick, paleo)) or np.any(thick < -min_thickness_m):
        raise ValueError("Stratal output contains non-finite values or negative thicknesses.")
    thick = np.maximum(thick, 0)
    if poro is not None and (poro.shape != thick.shape or not np.isfinite(poro).all() or np.any((poro < 0) | (poro > 1))):
        raise ValueError("layPoro must match the layers and contain fractions in [0, 1].")
    # Upstream layerMesh stores basal elevations and thicknesses, oldest first.
    if depth.shape[1] > 1 and not np.allclose(depth[:, :-1] + thick[:, :-1], depth[:, 1:], atol=0.05, rtol=0):
        raise ValueError("Layer bases/thicknesses are inconsistent; refusing to bridge gaps or invert stratigraphy.")
    layers = np.flatnonzero(np.any(thick > min_thickness_m, axis=0))[::-1]
    if not len(layers):
        raise ValueError("No deposited layers above the minimum thickness. Run a depositional model or choose a later snapshot.")
    nx, ny, nz = len(xs) - 1, len(ys) - 1, len(layers)
    surfaces = []
    properties: dict[str, list] = {"ACTNUM": [], "Facies": [], "BDLLAYER": [], "BDLPALEO": [], "BDLTHICK": []}
    if poro is not None:
        properties["PORO"] = []
    for layer in layers:
        base = depth[order, layer].reshape(ny + 1, nx + 1)
        height = thick[order, layer].reshape(base.shape)
        top_depth, base_depth = datum_elevation_m - (base + height), datum_elevation_m - base
        surfaces.append((top_depth, base_depth))
        cell_thick = _mean_corners(height)
        active = cell_thick > min_thickness_m
        cell_paleo = _mean_corners(paleo[order, layer].reshape(base.shape))
        facies = np.where(cell_paleo >= 0, facies_codes[0], np.where(cell_paleo >= -shallow_depth_m, facies_codes[1], facies_codes[2]))
        for name, values in {
            "ACTNUM": active.astype(int), "Facies": np.where(active, facies, 0),
            "BDLLAYER": np.full(active.shape, layer + 1), "BDLPALEO": cell_paleo, "BDLTHICK": cell_thick,
        }.items():
            properties[name].extend(values.ravel().tolist())
        if poro is not None:
            properties["PORO"].extend(_mean_corners(poro[order, layer].reshape(base.shape)).ravel().tolist())
    coord, zcorn = [], []
    top, bottom = surfaces[0][0], surfaces[-1][1]
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            coord.extend([float(x), float(y), float(top[j, i]), float(x), float(y), float(max(bottom[j, i], top[j, i] + 0.01))])
    for pair in surfaces:
        for surface in pair:
            for j in range(ny):
                for dj in (0, 1):
                    for i in range(nx):
                        for di in (0, 1):
                            zcorn.append(float(surface[j + dj, i + di]))
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write("-- GO-Forward Badlands stratigraphy; metres, Z positive down from declared datum.\n")
        handle.write("-- Facies are layElev-based environmental proxies; see .badlands.json manifest.\n")
        handle.write(f"SPECGRID\n{nx} {ny} {nz} 1 F /\nGRIDUNIT\nMETRES /\n")
        handle.write("MAPUNITS\nMETRES /\nMAPAXES\n0 1000 0 0 1000 0 /\n")
        write_property(handle, "COORD", (f"{v:.12g}" for v in coord))
        write_property(handle, "ZCORN", (f"{v:.12g}" for v in zcorn))
        for name, values in properties.items():
            write_property(handle, name, (f"{v:.12g}" for v in values))
    manifest = {
        "source": str(source.resolve()), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "grdecl": target.name, "dimensions": [nx, ny, nz], "active_cells": sum(properties["ACTNUM"]),
        "datum_elevation_m": datum_elevation_m, "depth_convention": "datum_elevation_m - Badlands elevation",
        "facies_method": "mean corner layElev at deposition relative to contemporaneous sea level; environmental proxies, not lithofacies",
        "facies_codes": dict(zip(("terrestrial", "shallow_marine", "offshore"), facies_codes, strict=True)),
        "shallow_depth_m": shallow_depth_m, "min_thickness_m": min_thickness_m,
        "layer_order": "top-to-bottom; BDLLAYER records original 1-based oldest-first HDF5 layer",
        "properties": list(properties), "permeability": "not modelled or inferred",
    }
    target.with_suffix(".badlands.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
