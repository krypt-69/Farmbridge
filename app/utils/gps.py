from math import radians, sin, cos, sqrt, atan2

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two GPS coordinates."""
    R = 6371_000  # Earth radius in metres
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def is_within_radius(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    max_distance_m: float = 5000.0
) -> bool:
    """Return True if point1 and point2 are within max_distance_m metres."""
    return haversine_distance(lat1, lon1, lat2, lon2) <= max_distance_m