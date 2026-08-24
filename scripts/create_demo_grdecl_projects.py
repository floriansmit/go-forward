#!/usr/bin/env python3
"""Create compact carbonate and crystalline GRDECL demonstration projects.

The models are intentionally synthetic but contain valid corner-point geometry,
an interpretable categorical property, porosity/permeability placeholders and
project-specific definitions. They are useful for testing the Carbonates and
Crystalline rocks dashboard profiles without reusing siliciclastic facies.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data"
ORIGINAL_GRDECL_FOLDER = "0_original_grdecl"


def write_values(handle, values: list[float | int], per_line: int = 8) -> None:
    for start in range(0, len(values), per_line):
        chunk = values[start : start + per_line]
        handle.write(" ".join(f"{value:.6g}" if isinstance(value, float) else str(value) for value in chunk) + "\n")


def write_property(handle, keyword: str, values: list[float | int]) -> None:
    handle.write(f"\n{keyword}\n")
    write_values(handle, values)
    handle.write("/\n")


def top_depth(x: float, y: float, nx: int, ny: int, kind: str) -> float:
    """Return a gently mounded reef or domed pluton top in positive depth."""
    dx = (x - nx / 2) / nx
    dy = (y - ny / 2) / ny
    radial = dx * dx + dy * dy
    amplitude = 170.0 if kind == "carbonate" else 240.0
    return 1900.0 - amplitude * pow(2.718281828, -radial / 0.045) + 35.0 * dx


def write_model(path: Path, kind: str) -> None:
    nx, ny, nz = 30, 30, 12
    dx, dy, layer_thickness = 200.0, 200.0, 25.0
    total_thickness = nz * layer_thickness

    coord: list[float] = []
    for j in range(ny + 1):
        for i in range(nx + 1):
            x, y = i * dx, j * dy
            top = top_depth(i, j, nx, ny, kind)
            coord.extend([x, y, top, x, y, top + total_thickness])

    zcorn: list[float] = []
    for kk in range(2 * nz):
        boundary = (kk + 1) // 2
        for jj in range(2 * ny):
            for ii in range(2 * nx):
                top = top_depth(ii / 2, jj / 2, nx, ny, kind)
                zcorn.append(top + boundary * layer_thickness)

    classes: list[int] = []
    porosity: list[float] = []
    permeability: list[float] = []
    for k in range(nz):
        for j in range(ny):
            for i in range(nx):
                x, y = i + 0.5, j + 0.5
                radius = ((x - nx / 2) ** 2 + (y - ny / 2) ** 2) ** 0.5
                if kind == "carbonate":
                    if radius < 3.2:
                        code, phi, perm = 1, 0.26, 800.0  # reef framework
                    elif radius < 6.5:
                        code, phi, perm = 2, 0.22, 350.0  # reef flank grainstone
                    elif y > ny / 2 and radius < 11.5:
                        code, phi, perm = 3, 0.14, 40.0   # protected lagoon
                    elif y <= ny / 2 and radius < 12.5:
                        code, phi, perm = 4, 0.17, 90.0   # fore-reef slope
                    else:
                        code, phi, perm = 5, 0.07, 2.0    # basinal mudstone/marl
                    phi *= 1.0 - 0.012 * k
                    perm *= 1.0 - 0.025 * k
                else:
                    # A circular granite pluton, contact aureole, gneissic host
                    # and a diagonal shear zone cutting the model.
                    shear_zone = abs((j - ny / 2) - 0.45 * (i - nx / 2)) < 0.75
                    if shear_zone and radius > 4.0:
                        code, phi, perm = 4, 0.075, 15.0
                    elif radius < 5.0:
                        code, phi, perm = 1, 0.018, 0.03
                    elif radius < 7.5:
                        code, phi, perm = 2, 0.035, 0.3
                    else:
                        code, phi, perm = 3, 0.012, 0.01
                    phi *= 1.0 - 0.006 * k
                    perm *= 1.0 - 0.01 * k
                classes.append(code)
                porosity.append(phi)
                permeability.append(perm)

    path.parent.mkdir(parents=True, exist_ok=True)
    grid_name = "Carbonate_Reef_Demo" if kind == "carbonate" else "Crystalline_Pluton_Demo"
    property_name = "Facies" if kind == "carbonate" else "RockType"
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(f"-- {grid_name}: synthetic GO-Forward demonstration grid\n")
        handle.write("-- Positive ZCORN values are depth below datum; dashboard centres use elevation sign convention.\n\n")
        handle.write("MAPUNITS\nMETRES /\n\n")
        handle.write("MAPAXES\n0 0 0 6000 6000 6000 /\n\n")
        handle.write("GRIDUNIT\nMETRES /\n\n")
        handle.write(f"SPECGRID\n{nx} {ny} {nz} 1 F /\n\n")
        handle.write("COORD\n")
        write_values(handle, coord, per_line=6)
        handle.write("/\n\nZCORN\n")
        write_values(handle, zcorn, per_line=12)
        handle.write("/\n")
        write_property(handle, "ACTNUM", [1] * (nx * ny * nz))
        write_property(handle, property_name, classes)
        write_property(handle, "PORO", porosity)
        write_property(handle, "PERM", permeability)


def write_project(name: str, profile: str, filename: str, kind: str, names: dict[str, str], colours: dict[str, str]) -> None:
    project_dir = DATA_ROOT / name
    source_dir = project_dir / ORIGINAL_GRDECL_FOLDER
    write_model(source_dir / filename, kind)
    (project_dir / "project_config.json").write_text(
        json.dumps({"project_name": name, "workflow_profile": profile, "workflow_suffix": "carbonates" if profile == "Carbonates" else "crystalline"}, indent=2) + "\n",
        encoding="utf-8",
    )
    property_name = "Facies" if kind == "carbonate" else "RockType"
    config = {
        "facies_property": property_name,
        "source_grdecl_directory": str(source_dir.relative_to(ROOT)).replace("\\", "/"),
        "source_grdecl_files": [filename],
        "facies_names": names,
        "facies_colors": colours,
        "facies_metadata": {code: {"category": "reservoir" if code in {"1", "2"} else "non_reservoir"} for code in names},
    }
    (source_dir / "facies_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    write_project(
        "Reef_Demo_carbonates",
        "Carbonates",
        "carbonate_reef_demo.grdecl",
        "carbonate",
        {
            "1": "Reef crest framework boundstone",
            "2": "Reef flank grainstone-packstone",
            "3": "Back-reef lagoonal wackestone",
            "4": "Fore-reef slope packstone",
            "5": "Basinal mudstone-marl",
        },
        {"1": "#d62728", "2": "#ffbf00", "3": "#66c2a5", "4": "#8da0cb", "5": "#6b6b6b"},
    )
    write_project(
        "Crystalline_Pluton_Demo_crystalline",
        "Crystalline rocks",
        "crystalline_pluton_demo.grdecl",
        "crystalline",
        {
            "1": "Granite pluton",
            "2": "Contact metamorphic aureole",
            "3": "Gneissic basement host rock",
            "4": "Fractured shear zone",
        },
        {"1": "#d73027", "2": "#fc8d59", "3": "#4575b4", "4": "#7b3294"},
    )
    print("Created Carbonate_Reef_Demo_carbonates and Crystalline_Pluton_Demo_crystalline.")


if __name__ == "__main__":
    main()
