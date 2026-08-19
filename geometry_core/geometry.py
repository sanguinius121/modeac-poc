"""Horizontal TDOA design matrix and error metrics."""
import itertools
import math
import numpy as np
from .coordinates import geodetic_to_ecef, local_axes

C = 299_792_458.0


def design_matrix(lat, lon, alt, stations):
    p = geodetic_to_ecef(lat, lon, alt); east, north = local_axes(lat, lon)
    rows = []
    for value in stations.values():
        delta = p - geodetic_to_ecef(*value); unit = delta / np.linalg.norm(delta)
        rows.append((float(np.dot(unit, east)), float(np.dot(unit, north))))
    h = np.asarray(rows)
    projector = np.eye(len(rows)) - np.ones((len(rows), len(rows))) / len(rows)
    return projector @ h, projector


def geometry_metrics(lat, lon, alt, stations, noise_us=0.25, draws=None):
    g, projector = design_matrix(lat, lon, alt, stations)
    singular = np.linalg.svd(g, compute_uv=False)
    if len(singular) < 2 or singular[-1] < 1e-10:
        return {"condition": float("inf"), "linear_hrmse_m": float("inf"), "mc_p50_m": float("inf"), "mc_p95_m": float("inf")}
    condition = float(singular[0] / singular[-1])
    covariance_unit = np.linalg.inv(g.T @ g)
    sigma_m = C * noise_us * 1e-6
    hrmse = sigma_m * math.sqrt(float(np.trace(covariance_unit)))
    if draws is None:
        p50 = hrmse * math.sqrt(math.log(2)); p95 = hrmse * math.sqrt(-math.log(0.05))
    else:
        estimator = np.linalg.pinv(g) @ projector
        errors = (estimator @ (draws[:len(stations)] * sigma_m)).T
        radial = np.linalg.norm(errors, axis=1)
        p50, p95 = map(float, np.percentile(radial, (50, 95)))
    return {"condition": condition, "linear_hrmse_m": hrmse, "mc_p50_m": p50, "mc_p95_m": p95}


def tdoa_signature(lat, lon, alt, stations):
    p = geodetic_to_ecef(lat, lon, alt)
    ranges = {name: np.linalg.norm(p - geodetic_to_ecef(*value)) for name, value in stations.items()}
    return np.asarray([(ranges[b] - ranges[a]) / C * 1e6 for a, b in itertools.combinations(stations, 2)])

