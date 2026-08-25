"""Tests for geomechanics property assignment and dip azimuth calculations."""
from __future__ import annotations

import math
from pathlib import Path
import pytest

from scripts.assign_geomechanical_properties import horizon_smoothed_dip_azimuth, valid


def test_valid_checker():
    assert valid(0.25) is True
    assert valid(0.0) is True
    assert valid(-77777.0) is False
    assert valid(-999.0) is False
    assert valid(float("nan")) is False


def test_horizon_smoothed_dip_azimuth_flat_grid(mini_grdecl_path: Path):
    # Top horizon is completely flat at depth 1000m
    azimuths = horizon_smoothed_dip_azimuth(mini_grdecl_path, smoothing_radius_cells=2)
    assert len(azimuths) == 18  # 3 x 3 x 2
    # Flat horizontal plane has 0 depth gradient -> azimuth defaults to 0.0
    for az in azimuths:
        assert az == 0.0


def test_critical_porosity_stiffness_scaling():
    phi_c = 0.40
    m = 2.0
    e_ref = 40.0

    # Low porosity (0.10) -> stiff
    phi_low = 0.10
    compact_low = (1.0 - phi_low / phi_c) ** m
    e_low = e_ref * compact_low

    # High porosity (0.30) -> compliant
    phi_high = 0.30
    compact_high = (1.0 - phi_high / phi_c) ** m
    e_high = e_ref * compact_high

    assert e_low > e_high
    assert e_low == pytest.approx(40.0 * (0.75 ** 2))
    assert e_high == pytest.approx(40.0 * (0.25 ** 2))


def test_shale_compaction_trend():
    # Empirical depth compaction: phi(z) = phi_0 * exp(-c * z)
    phi_0 = 0.55
    c = 0.00046
    
    depth_1km = 1000.0
    phi_1km = phi_0 * math.exp(-c * depth_1km)
    
    depth_3km = 3000.0
    phi_3km = phi_0 * math.exp(-c * depth_3km)
    
    assert phi_1km > phi_3km
    assert phi_1km == pytest.approx(0.55 * math.exp(-0.46), abs=1e-3)
