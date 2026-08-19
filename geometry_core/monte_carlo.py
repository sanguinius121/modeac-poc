"""Remote-branch comparison used by the existing diagnostic."""
import numpy as np


def remote_branch_separation(points, signatures, min_distance_km=25.0, chunk=128):
    result = np.full(len(points), np.inf)
    lat = np.radians(np.asarray([x[0] for x in points])); lon = np.radians(np.asarray([x[1] for x in points]))
    for start in range(0, len(points), chunk):
        stop = min(len(points), start + chunk)
        dlat = lat[start:stop, None] - lat[None, :]; dlon = lon[start:stop, None] - lon[None, :]
        q = np.sin(dlat / 2) ** 2 + np.cos(lat[start:stop, None]) * np.cos(lat[None, :]) * np.sin(dlon / 2) ** 2
        distance = 2 * 6371.0088 * np.arcsin(np.minimum(1, np.sqrt(q)))
        delta = signatures[start:stop, None, :] - signatures[None, :, :]
        rms = np.sqrt(np.mean(delta * delta, axis=2)); rms[distance < min_distance_km] = np.inf
        result[start:stop] = np.min(rms, axis=1)
    return result

