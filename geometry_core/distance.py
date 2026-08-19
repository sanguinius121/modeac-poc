"""Geodesic-distance helpers shared by planning tools."""
import math


def haversine_km(a, b):
    lat1, lon1 = map(math.radians, a[:2]); lat2, lon2 = map(math.radians, b[:2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    q = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(q)))

