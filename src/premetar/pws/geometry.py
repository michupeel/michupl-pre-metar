"""Reviewed Qwen haversine proposal; corrected spherical bounds and antipodes."""

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if not all(math.isfinite(x) for x in (lat1, lon1, lat2, lon2)):
        raise ValueError("Coordinates must be finite")
    if not (
        -90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180
    ):
        raise ValueError("Invalid WGS84 coordinates")
    a, b = math.radians(lat1), math.radians(lat2)
    h = (
        math.sin((b - a) / 2) ** 2
        + math.cos(a) * math.cos(b) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.asin(math.sqrt(min(1, max(0, h))))


def bounding_boxes(
    latitude: float, longitude: float, radius_km: float
) -> list[tuple[float, float, float, float]]:
    haversine_km(latitude, longitude, latitude, longitude)
    if not math.isfinite(radius_km) or not 0 < radius_km <= 200:
        raise ValueError("Radius must be in (0, 200] km")
    delta = radius_km / EARTH_RADIUS_KM
    south = max(-90, latitude - math.degrees(delta))
    north = min(90, latitude + math.degrees(delta))
    if south == -90 or north == 90:
        return [(-180, south, 180, north)]
    dx = math.degrees(math.asin(math.sin(delta) / math.cos(math.radians(latitude))))
    west, east = longitude - dx, longitude + dx
    if west < -180:
        return [(west + 360, south, 180, north), (-180, south, east, north)]
    if east > 180:
        return [(west, south, 180, north), (-180, south, east - 360, north)]
    return [(west, south, east, north)]
