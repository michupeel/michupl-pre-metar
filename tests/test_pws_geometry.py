"""Synthetic tests adapted from Qwen; corrected antipode and bbox expectations."""

import math

import pytest

from premetar.pws.geometry import bounding_boxes, haversine_km


def test_distances():
    assert haversine_km(0, 0, 0, 0) == 0
    assert haversine_km(0, 0, 0, 1) == pytest.approx(111.19508, abs=0.0001)
    assert haversine_km(0, 179.9, 0, -179.9) == pytest.approx(22.239, abs=0.001)
    assert haversine_km(0, 0, 0, 180) == pytest.approx(20015.1144, abs=0.01)


@pytest.mark.parametrize("latitude,longitude", [(math.nan, 0), (0, math.inf), (91, 0), (0, -181)])
def test_invalid_coordinates(latitude, longitude):
    with pytest.raises(ValueError):
        haversine_km(latitude, longitude, 0, 0)


@pytest.mark.parametrize("radius", [0, -1, 201, math.nan, math.inf])
def test_invalid_radius(radius):
    with pytest.raises(ValueError):
        bounding_boxes(0, 0, radius)


@pytest.mark.parametrize("longitude", [179.95, -179.95])
def test_antimeridian_bounds(longitude):
    boxes = bounding_boxes(0, longitude, 20)
    assert len(boxes) == 2
    assert all(-180 <= w <= e <= 180 and -90 <= s <= n <= 90 for w, s, e, n in boxes)
    for point in [179.99, -179.99]:
        assert any(w <= point <= e and s <= 0 <= n for w, s, e, n in boxes)


def test_polar_bounds():
    west, south, east, north = bounding_boxes(89.99, 130, 20)[0]
    assert (west, east, north) == (-180, 180, 90)
    assert south > 89
