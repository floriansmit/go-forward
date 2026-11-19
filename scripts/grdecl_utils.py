"""Shared GRDECL parsing and geometry helpers.

The implementations live with the Best-fit append command because that script
also owns the complete point-set-to-GRDECL append workflow.  Keeping this
neutral module means all other workflows have a stable, descriptive import
path and do not depend on a legacy command filename.
"""

from append_best_fit_tmap_to_grdecls import (
    grdecl_cell_centers,
    grdecl_keyword,
    mapaxes_transform,
    path_for_io,
    tokenize_grdecl,
    write_property,
)

__all__ = [
    "grdecl_active_mask",
    "grdecl_cell_centers",
    "grdecl_keyword",
    "mapaxes_transform",
    "path_for_io",
    "tokenize_grdecl",
    "write_property",
]


def grdecl_active_mask(path, cell_count: int) -> list[bool]:
    """Read optional ACTNUM while preserving full-grid CellIndex positions."""
    data = tokenize_grdecl(path, {"ACTNUM"}, allow_missing=True)
    if "ACTNUM" not in data:
        return [True] * cell_count
    values = []
    for token in data["ACTNUM"]:
        if "*" in token:
            count, value = token.split("*", 1)
            values.extend([float(value)] * int(count))
        else:
            values.append(float(token))
    if len(values) != cell_count or any(value not in (0, 1) for value in values):
        raise ValueError(f"{path}: ACTNUM must contain {cell_count} binary cell values")
    return [bool(value) for value in values]
