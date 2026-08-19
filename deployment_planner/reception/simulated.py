"""Circular horizontal max-range reception provider."""
from geometry_core import haversine_km
from .base import ReceptionProvider


class SimulatedProvider(ReceptionProvider):
    def evaluate(self, receiver, target_lat, target_lon, target_altitude_m):
        distance = haversine_km((receiver.lat, receiver.lon), (target_lat, target_lon))
        eligible = distance <= receiver.max_range_km
        return eligible, {
            "provider": "simulated",
            "reason": f"{distance:.1f} km {'<=' if eligible else '>'} simulated {receiver.max_range_km:.1f} km",
            "distance_km": distance,
            "max_range_km": receiver.max_range_km,
        }

