"""Receiver convex-hull diagnostics."""
import numpy as np
from scipy.spatial import Delaunay


def inside_hull(points, stations):
    hull_points = np.asarray([(v[1], v[0]) for v in stations.values()])
    tri = Delaunay(hull_points)
    return tri.find_simplex(np.asarray([(lon, lat) for lat, lon in points])) >= 0

