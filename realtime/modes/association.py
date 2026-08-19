"""Mode-S compatibility wrapper around generic N-RX association."""

from realtime.config import ORDER, STATIONS
from realtime.nrx_association import associate_observations, physical_limits_us as _limits


def physical_limits_us(order=ORDER, stations=STATIONS):
    return _limits(tuple(order), stations)


def cluster_transmissions(
    observations,
    transforms,
    margin_us=3.0,
    ambiguity_ticks=6.0,
    order=ORDER,
    stations=STATIONS,
):
    """Return legacy dict clusters while using the generic N-RX core.

    Existing four-receiver callers retain their schema.  New callers may pass
    any deterministic ``order`` and matching station-position mapping.
    """
    result = associate_observations(
        observations,
        transforms,
        tuple(order),
        stations,
        margin_us,
        ambiguity_ticks,
    )
    return [cluster.as_dict() for cluster in result.clusters], dict(result.diagnostics)
