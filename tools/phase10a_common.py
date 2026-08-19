"""Reusable, offline-only helpers for Phase 10A five-receiver diagnostics.

This module deliberately does not import or mutate realtime.config.  It mirrors the
validated association gates while allowing an arbitrary receiver set.
"""

from __future__ import annotations

import bisect
import csv
import importlib.util
import itertools
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from realtime.clock_sync import Link
from realtime.config import BEAST_HZ, C
from realtime.nrx_association import associate_observations


@dataclass(frozen=True)
class DiagnosticStation:
    name: str
    port: int
    lat: float
    lon: float
    alt_m: float


STATIONS = {
    "T37": DiagnosticStation("T37", 29996, 21.485594, 107.773191, 60.0),
    "Dao_Cai_chien": DiagnosticStation("Dao_Cai_chien", 29998, 21.320940, 107.766116, 28.0),
    "QK4": DiagnosticStation("QK4", 29997, 18.760032, 105.659087, 20.0),
    "BachLongVi": DiagnosticStation("BachLongVi", 29999, 20.132285, 107.724413, 28.0),
    "MongCai": DiagnosticStation("MongCai", 29995, 21.550206, 107.938978, 36.0),
}
ORDER = tuple(STATIONS)
BASELINE_SUBSET = ("T37", "Dao_Cai_chien", "QK4", "BachLongVi")
SUBSETS = (
    BASELINE_SUBSET,
    ("T37", "Dao_Cai_chien", "QK4", "MongCai"),
    ("T37", "Dao_Cai_chien", "BachLongVi", "MongCai"),
    ("T37", "QK4", "BachLongVi", "MongCai"),
    ("Dao_Cai_chien", "QK4", "BachLongVi", "MongCai"),
)
MODEAC_MARGIN_US = 10.0
MODES_MARGIN_US = 3.0
AMBIGUITY_TICKS = 6.0


def _load_test_module(name: str, filename: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


T4 = _load_test_module("phase10a_test4b", "test4b-holdout.py")
T6 = _load_test_module("phase10a_test6", "test6-analyze.py")


def station_position(name: str):
    station = STATIONS[name]
    return station.lat, station.lon, station.alt_m


def load_capture(path: Path):
    """Load the Test-6-compatible capture CSV and retain globally stable IDs."""
    rows = T4.load_capture(str(path))
    for index, row in enumerate(rows):
        row["id"] = f"{row['station']}:{index}"
        if row["df"] in (11, 17) and len(row["raw"]) >= 4:
            row["icao"] = row["raw"][1:4].hex()
        else:
            row["icao"] = None
    return rows


def physical_limits_us(order: Iterable[str] = ORDER):
    order = tuple(order)
    ecef = {
        name: np.array(T4.geodetic_to_ecef(*station_position(name)))
        for name in order
    }
    return {
        (a, b): float(np.linalg.norm(ecef[a] - ecef[b])) / C * 1e6
        for a, b in itertools.combinations(order, 2)
    }


def calibrate_pair(a: str, b: str, rows_a, rows_b):
    """Fit the same rolling Link model and quality thresholds used by realtime."""
    common = T4.build_common_df17(rows_a, rows_b, 200.0)
    samples = T6.build_geometry_samples(
        T4, common, station_position(a), station_position(b)
    )
    link = Link(a, b)
    for sample in samples:
        link.add(sample["ta"], sample["tb_clock"])
    public = link.public()
    result = {
        "station_a": a,
        "station_b": b,
        "common_df17_pairs": len(common),
        "geometry_samples_total": len(samples),
        "unique_aircraft": len({sample["icao"] for sample in samples}),
        "samples": public["samples"],
        "slope": public["slope"],
        "offset_ticks": public["offset"],
        "relative_clock_ppm": (
            (public["slope"] - 1.0) * 1e6 if public["slope"] is not None else None
        ),
        "p50_us": public["p50_us"],
        "p90_us": public["p90_us"],
        "p95_us": public["p95_us"],
        "p99_us": public["p99_us"],
        "quality": public["quality"],
        "rejected_discontinuities": public["rejected_discontinuities"],
        "model_resets": public["model_resets"],
    }
    return result


def calibrate_all(records):
    pairs = []
    models = {}
    for a, b in itertools.combinations(ORDER, 2):
        result = calibrate_pair(a, b, records[a], records[b])
        pairs.append(result)
        if result["slope"] is not None:
            models[(a, b)] = (result["slope"], result["offset_ticks"])
    transforms = {"T37": (1.0, 0.0)}
    for station in ORDER[1:]:
        model = models.get(("T37", station))
        if model is not None:
            transforms[station] = model
    return pairs, transforms


def cluster_transmissions(
    observations,
    transforms,
    order=ORDER,
    margin_us=MODES_MARGIN_US,
    ambiguity_ticks=AMBIGUITY_TICKS,
):
    """Compatibility wrapper around the Phase 10B generic association core."""
    result = associate_observations(
        observations,
        transforms,
        tuple(order),
        STATIONS,
        margin_us,
        ambiguity_ticks,
    )
    return [cluster.as_dict() for cluster in result.clusters], dict(result.diagnostics)


def strict_subset_clusters(observations, transforms, subset, margin_us):
    clusters, diagnostics = cluster_transmissions(
        observations, transforms, order=subset, margin_us=margin_us
    )
    return [cluster for cluster in clusters if cluster["receiver_count"] == 4], diagnostics


def unique_any4(subset_clusters):
    """Deduplicate strict subset results by shared receiver observations."""
    clusters = [cluster for values in subset_clusters.values() for cluster in values]
    parent = list(range(len(clusters)))

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    owners = {}
    for index, cluster in enumerate(clusters):
        for node in cluster["nodes"].values():
            previous = owners.get(node["id"])
            if previous is not None:
                union(index, previous)
            else:
                owners[node["id"]] = index
    components = defaultdict(list)
    for index, cluster in enumerate(clusters):
        components[find(index)].append(cluster)
    return list(components.values())


def subset_name(subset):
    return "+".join(subset)


def percentage_increase(baseline: int, candidate: int):
    if baseline == 0:
        return None
    return (candidate - baseline) / baseline * 100.0


def summarize_family(observations, transforms, margin_us):
    full, diagnostics = cluster_transmissions(
        observations, transforms, order=ORDER, margin_us=margin_us
    )
    receiver_counts = Counter(cluster["receiver_count"] for cluster in full)
    subset_results = {}
    subset_diagnostics = {}
    for subset in SUBSETS:
        name = subset_name(subset)
        subset_results[name], subset_diagnostics[name] = strict_subset_clusters(
            observations, transforms, subset, margin_us
        )
    components = unique_any4(subset_results)
    baseline_name = subset_name(BASELINE_SUBSET)
    baseline = len(subset_results[baseline_name])
    any4 = len(components)
    strict5 = receiver_counts[5]
    return {
        "observations": len(observations),
        "two_rx": receiver_counts[2],
        "three_rx": receiver_counts[3],
        "four_rx": receiver_counts[4],
        "five_rx": receiver_counts[5],
        "any_4_of_5": any4,
        "strict_5rx": strict5,
        "baseline_fixed_4rx": baseline,
        "absolute_increase": any4 - baseline,
        "percent_increase": percentage_increase(baseline, any4),
        "subset_counts": {
            name: len(clusters) for name, clusters in subset_results.items()
        },
        "association_diagnostics": diagnostics,
        "subset_diagnostics": subset_diagnostics,
        "_full_clusters": full,
        "_subset_clusters": subset_results,
    }


def public_family(summary):
    return {key: value for key, value in summary.items() if not key.startswith("_")}


def write_csv(path: Path, rows):
    rows = list(rows)
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
