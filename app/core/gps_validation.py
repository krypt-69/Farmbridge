from math import radians, sin, cos, sqrt, atan2
from fastapi import HTTPException, status

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in metres between two GPS coordinates."""
    R = 6371_000
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def validate_agent_location(
    agent_lat: float,
    agent_lon: float,
    target_lat: float,
    target_lon: float,
    max_distance_m: float = 5000.0,
):
    """Raise HTTPException if agent is more than max_distance_m from target."""
    distance = haversine_distance(agent_lat, agent_lon, target_lat, target_lon)
    if distance > max_distance_m:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Agent is too far from farm location ({distance:.0f}m > {max_distance_m:.0f}m allowed)",
        )