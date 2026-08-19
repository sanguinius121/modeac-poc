"""WGS84 coordinate conversions and local horizontal axes."""
import math
import numpy as np

A = 6_378_137.0
F = 1 / 298.257223563
E2 = F * (2 - F)


def geodetic_to_ecef(lat, lon, alt):
    latr, lonr = math.radians(lat), math.radians(lon)
    sl, cl = math.sin(latr), math.cos(latr)
    n = A / math.sqrt(1 - E2 * sl * sl)
    return np.array(((n + alt) * cl * math.cos(lonr), (n + alt) * cl * math.sin(lonr), (n * (1 - E2) + alt) * sl))


def local_axes(lat, lon):
    la, lo = math.radians(lat), math.radians(lon)
    east = np.array((-math.sin(lo), math.cos(lo), 0.0))
    north = np.array((-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo), math.cos(la)))
    return east, north

