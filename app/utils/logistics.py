def suggest_lorry_type(total_bags: int, max_distance_km: float) -> str:
    """
    Suggest a lorry type based on total quantity and maximum distance between harvests.
    Returns one of: 'small (3-ton)', 'medium (7-ton)', 'large (10-ton)'.
    """
    if total_bags <= 30 and max_distance_km <= 50:
        return "small (3-ton)"
    elif total_bags <= 50 and max_distance_km <= 80:
        return "medium (7-ton)"
    else:
        return "large (10-ton)"