"""Shared, neutral geometry mathematics for offline tools and planners."""
from .coordinates import A, E2, F, geodetic_to_ecef, local_axes
from .distance import haversine_km
from .geometry import C, design_matrix, geometry_metrics, tdoa_signature
from .hull import inside_hull
from .monte_carlo import remote_branch_separation
from .quality import classify


def grid_values(start, stop, step):
    count = int(round((stop - start) / step))
    return [round(start + i * step, 10) for i in range(count + 1)]

