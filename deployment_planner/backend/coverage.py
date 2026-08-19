"""Phase Tool-1 circular ground-range reception model."""
from geometry_core import haversine_km


def ground_distance_km(a_lat,a_lon,b_lat,b_lon):
    return haversine_km((a_lat,a_lon),(b_lat,b_lon))


def reception(receiver,lat,lon):
    distance=ground_distance_km(receiver.lat,receiver.lon,lat,lon)
    return distance,distance<=receiver.max_range_km
