"""Generic exact-transmission N-receiver association without solver policy.

The core produces one cluster per associated physical transmission.  It never
enumerates solver quartets; Phase 10C may do that from ``receiver_ids``.
"""

from __future__ import annotations

import bisect
import hashlib
import heapq
import itertools
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np

from realtime.clock_sync import T4
from realtime.config import C


@dataclass(frozen=True)
class TransmissionCluster:
    cluster_id: str
    transmission_key: str
    observations_by_receiver: Mapping[str, Mapping]
    receiver_ids: tuple
    normalized_timestamps: Mapping[str, float]
    metadata: Mapping
    measurement_utc_ns: int
    association_latency_ms: float

    @property
    def receiver_count(self):
        return len(self.receiver_ids)

    def as_dict(self):
        """Compatibility representation for existing offline callers."""
        return {
            "cluster_id": self.cluster_id,
            "raw_hex": self.transmission_key,
            "transmission_key": self.transmission_key,
            "df": self.metadata.get("df"),
            "icao": self.metadata.get("icao"),
            "nodes": dict(self.observations_by_receiver),
            "observations_by_receiver": dict(self.observations_by_receiver),
            "receiver_ids": list(self.receiver_ids),
            "receiver_count": self.receiver_count,
            "utc_ns": self.measurement_utc_ns,
            "norm": dict(self.normalized_timestamps),
            "normalized_timestamps": dict(self.normalized_timestamps),
            "mean_norm": sum(self.normalized_timestamps.values()) / self.receiver_count,
            "metadata": dict(self.metadata),
            "association_latency_ms": self.association_latency_ms,
        }


@dataclass(frozen=True)
class AssociationResult:
    clusters: tuple
    diagnostics: Mapping
    counters: Mapping


def _position_tuple(station):
    if isinstance(station, (tuple, list)):
        return tuple(station)
    return station.lat, station.lon, station.alt_m


def physical_limits_us(receiver_ids: Sequence[str], stations: Mapping):
    ecef = {
        name: np.array(T4.geodetic_to_ecef(*_position_tuple(stations[name])))
        for name in receiver_ids
    }
    return {
        (a, b): float(np.linalg.norm(ecef[a] - ecef[b])) / C * 1e6
        for a, b in itertools.combinations(receiver_ids, 2)
    }


def _observation_tick(observation):
    if "tick" in observation:
        return observation["tick"]
    return observation["ts"]


def _observation_utc_ns(observation):
    if "utc_ns" in observation:
        return int(observation["utc_ns"])
    return int(float(observation.get("utc", 0.0)) * 1e9)


def _cluster_id(key, ordered_nodes):
    identity = key + "|" + "|".join(
        f"{station}:{ordered_nodes[station]['id']}" for station in ordered_nodes
    )
    return "NRX-" + hashlib.sha256(identity.encode()).hexdigest()[:20]


def _counters(observations, clusters):
    size = Counter(cluster.receiver_count for cluster in clusters)
    membership = Counter("+".join(cluster.receiver_ids) for cluster in clusters)
    per_df = defaultdict(Counter)
    for cluster in clusters:
        df = cluster.metadata.get("df")
        if df is not None:
            per_df[str(df)][f"{cluster.receiver_count}RX"] += 1
    return {
        "total_observations": len(observations),
        "2RX": size[2],
        "3RX": size[3],
        "4RX": size[4],
        "5RX": size[5],
        "receiver_membership": dict(sorted(membership.items())),
        "per_df": {df: dict(values) for df, values in sorted(per_df.items())},
    }


def associate_observations(
    observations: Iterable[Mapping],
    transforms: Mapping[str, tuple],
    receiver_ids: Sequence[str],
    stations: Mapping,
    margin_us: float,
    ambiguity_ticks: float = 6.0,
):
    """Batch-associate exact transmissions for an arbitrary receiver set.

    Complexity is driven by observations in each exact-payload time window and
    pairwise receiver validation.  No C(N,4) objects are created.
    """
    observations = list(observations)
    receiver_ids = tuple(receiver_ids)
    if len(receiver_ids) < 2 or len(receiver_ids) != len(set(receiver_ids)):
        raise ValueError("receiver_ids must contain at least two unique receivers")
    if any(receiver not in stations for receiver in receiver_ids):
        raise ValueError("station position missing for receiver")
    rank = {name: index for index, name in enumerate(receiver_ids)}
    limits = physical_limits_us(receiver_ids, stations)
    maximum_ticks = (max(limits.values()) + margin_us) * 12.0
    payloads = defaultdict(list)
    diagnostics = Counter()
    seen_ids = set()

    for sequence, observation in enumerate(observations):
        station = observation.get("station")
        if station not in rank:
            diagnostics["unknown_receiver"] += 1
            continue
        model = transforms.get(station)
        if model is None or model[0] is None:
            diagnostics["clock_not_ready"] += 1
            continue
        node = dict(observation)
        node.setdefault("id", f"{station}:{sequence}")
        if node["id"] in seen_ids:
            diagnostics["duplicate_observation_id"] += 1
            continue
        seen_ids.add(node["id"])
        slope, offset = model
        node["norm"] = (float(_observation_tick(node)) - float(offset)) / float(slope)
        key = node.get("transmission_key", node.get("raw_hex"))
        if key is None:
            diagnostics["missing_transmission_key"] += 1
            continue
        payloads[str(key)].append(node)

    used = set()
    clusters = []
    for key in sorted(payloads):
        nodes = payloads[key]
        nodes.sort(key=lambda node: (node["norm"], rank[node["station"]], str(node["id"])))
        times = [node["norm"] for node in nodes]
        for seed in nodes:
            seed_started = time.perf_counter()
            if seed["id"] in used:
                continue
            lo = bisect.bisect_left(times, seed["norm"] - maximum_ticks)
            hi = bisect.bisect_right(times, seed["norm"] + maximum_ticks)
            available = [node for node in nodes[lo:hi] if node["id"] not in used]
            by_receiver = defaultdict(list)
            for node in available:
                by_receiver[node["station"]].append(node)
            selected = {seed["station"]: seed}
            ambiguous = False
            for receiver in receiver_ids:
                if receiver == seed["station"] or not by_receiver.get(receiver):
                    continue
                choices = sorted(
                    by_receiver[receiver],
                    key=lambda node: (abs(node["norm"] - seed["norm"]), str(node["id"])),
                )
                if (
                    len(choices) > 1
                    and abs(choices[1]["norm"] - seed["norm"])
                    - abs(choices[0]["norm"] - seed["norm"])
                    < ambiguity_ticks
                ):
                    ambiguous = True
                    break
                selected[receiver] = choices[0]
            if ambiguous:
                diagnostics["ambiguous"] += 1
                continue

            changed = True
            while changed and len(selected) >= 2:
                changed = False
                for a, b in itertools.combinations(sorted(selected, key=rank.get), 2):
                    pair = (a, b) if rank[a] < rank[b] else (b, a)
                    if (
                        abs(selected[b]["norm"] - selected[a]["norm"]) / 12.0
                        > limits[pair] + margin_us
                    ):
                        drop = b if b != seed["station"] else a
                        del selected[drop]
                        diagnostics["physical_reject"] += 1
                        changed = True
                        break
            if len(selected) < 2:
                continue

            reciprocal = True
            for a, b in itertools.combinations(sorted(selected, key=rank.get), 2):
                nearest_b = min(
                    by_receiver[b],
                    key=lambda node: (abs(node["norm"] - selected[a]["norm"]), str(node["id"])),
                )
                nearest_a = min(
                    by_receiver[a],
                    key=lambda node: (abs(node["norm"] - selected[b]["norm"]), str(node["id"])),
                )
                if nearest_b["id"] != selected[b]["id"] or nearest_a["id"] != selected[a]["id"]:
                    reciprocal = False
                    break
            if not reciprocal:
                diagnostics["nonreciprocal"] += 1
                continue

            ordered_nodes = {
                receiver: selected[receiver] for receiver in receiver_ids if receiver in selected
            }
            used.update(node["id"] for node in ordered_nodes.values())
            metadata = {
                "df": seed.get("df"),
                "icao": seed.get("icao"),
                "family": seed.get("family"),
            }
            normalized = {receiver: node["norm"] for receiver, node in ordered_nodes.items()}
            clusters.append(
                TransmissionCluster(
                    cluster_id=_cluster_id(key, ordered_nodes),
                    transmission_key=key,
                    observations_by_receiver=MappingProxyType(ordered_nodes),
                    receiver_ids=tuple(ordered_nodes),
                    normalized_timestamps=MappingProxyType(normalized),
                    metadata=MappingProxyType(metadata),
                    measurement_utc_ns=min(_observation_utc_ns(node) for node in ordered_nodes.values()),
                    association_latency_ms=(time.perf_counter() - seed_started) * 1000.0,
                )
            )

    clusters.sort(key=lambda cluster: (cluster.measurement_utc_ns, cluster.transmission_key))
    diagnostics.update(Counter(f"{cluster.receiver_count}RX" for cluster in clusters))
    diagnostics["payloads"] = len(payloads)
    diagnostics["observations_used"] = len(used)
    counters = _counters(observations, clusters)
    return AssociationResult(
        clusters=tuple(clusters),
        diagnostics=MappingProxyType(dict(diagnostics)),
        counters=MappingProxyType(counters),
    )


class NrxAssociationBuffer:
    """Bounded settle-then-associate buffer for a generic receiver set.

    A partial 4RX candidate waits ``settle_s`` for a possible fifth receiver.
    A candidate containing every configured receiver may be emitted immediately.
    Emitted/expired rows are deleted, and consumed observation IDs are rejected.
    """

    def __init__(
        self,
        receiver_ids,
        stations,
        transforms,
        margin_us,
        minimum_receivers=2,
        settle_s=0.05,
        max_age_s=1.0,
        max_payloads=20_000,
        consumed_max=100_000,
        ambiguity_ticks=6.0,
    ):
        self.receiver_ids = tuple(receiver_ids)
        self.stations = stations
        self.transforms = transforms
        self.margin_us = margin_us
        self.minimum_receivers = minimum_receivers
        self.settle_s = settle_s
        self.max_age_s = max_age_s
        self.max_payloads = max_payloads
        self.consumed_max = consumed_max
        self.ambiguity_ticks = ambiguity_ticks
        self.rows = {}
        self.consumed = set()
        self.consumed_order = deque()
        self.settle_heap = []
        self.expiry_heap = []
        self.next_id = 1
        self.diagnostics = Counter()
        self.counters = Counter()
        self.membership = Counter()

    def add(self, observation, now=None):
        observation = dict(observation)
        station = observation.get("station")
        if station not in self.receiver_ids:
            self.diagnostics["unknown_receiver"] += 1
            return []
        if station not in self.transforms or self.transforms[station][0] is None:
            self.diagnostics["clock_not_ready"] += 1
            return []
        observation.setdefault("id", f"stream:{self.next_id}")
        self.next_id += 1
        if observation["id"] in self.consumed:
            self.diagnostics["observation_reuse_rejected"] += 1
            return []
        key = observation.get("transmission_key", observation.get("raw_hex"))
        if key is None:
            self.diagnostics["missing_transmission_key"] += 1
            return []
        now = float(now if now is not None else observation.get("mono", 0.0))
        key = str(key)
        if key not in self.rows and len(self.rows) >= self.max_payloads:
            self.flush(now=now, force_expired=True)
        if key not in self.rows and len(self.rows) >= self.max_payloads:
            oldest = min(self.rows, key=lambda item: self.rows[item]["created"])
            del self.rows[oldest]
            self.diagnostics["payload_evictions"] += 1
        row = self.rows.setdefault(
            key, {"created": now, "updated": now, "observations": []}
        )
        if not row["observations"]:
            heapq.heappush(self.expiry_heap, (now + self.max_age_s, key, now))
        row["updated"] = now
        row["observations"].append(observation)
        heapq.heappush(self.settle_heap, (now + self.settle_s, key, now))
        self.counters["total_observations"] += 1
        receivers = {item["station"] for item in row["observations"]}
        if receivers == set(self.receiver_ids):
            return self._emit_key(key)
        emitted = self.flush(now=now)
        emitted.extend(self.flush(now=now, force_expired=True))
        return emitted

    def _remember_consumed(self, observation_id):
        if observation_id in self.consumed:
            return
        self.consumed.add(observation_id)
        self.consumed_order.append(observation_id)
        while len(self.consumed_order) > self.consumed_max:
            self.consumed.discard(self.consumed_order.popleft())

    def _emit_key(self, key):
        row = self.rows.pop(key, None)
        if row is None:
            return []
        result = associate_observations(
            row["observations"],
            self.transforms,
            self.receiver_ids,
            self.stations,
            self.margin_us,
            self.ambiguity_ticks,
        )
        emitted = [
            cluster for cluster in result.clusters
            if cluster.receiver_count >= self.minimum_receivers
        ]
        for cluster in emitted:
            for node in cluster.observations_by_receiver.values():
                self._remember_consumed(node["id"])
            self.counters[f"{cluster.receiver_count}RX"] += 1
            df = cluster.metadata.get("df")
            if df is not None:
                self.counters[f"DF{df}_{cluster.receiver_count}RX"] += 1
            self.membership["+".join(cluster.receiver_ids)] += 1
        self.diagnostics.update(result.diagnostics)
        self.diagnostics["rows_emitted"] += 1
        return emitted

    def flush(self, now, force=False, force_expired=False):
        emitted = []
        if force:
            for key in sorted(list(self.rows)):
                emitted.extend(self._emit_key(key))
            return emitted
        heap = self.expiry_heap if force_expired else self.settle_heap
        while heap and heap[0][0] <= now:
            _, key, version = heapq.heappop(heap)
            row = self.rows.get(key)
            if row is None:
                continue
            current = row["created"] if force_expired else row["updated"]
            if current != version:
                continue
            emitted.extend(self._emit_key(key))
            if force_expired:
                self.diagnostics["expired_rows"] += 1
        return emitted

    def prune(self, now):
        return self.flush(now=now, force_expired=True)

    def size(self):
        return sum(len(row["observations"]) for row in self.rows.values())

    def public_counters(self):
        return {
            "total_observations": self.counters["total_observations"],
            "2RX": self.counters["2RX"],
            "3RX": self.counters["3RX"],
            "4RX": self.counters["4RX"],
            "5RX": self.counters["5RX"],
            "per_df": {
                str(df): {
                    f"{count}RX": self.counters[f"DF{df}_{count}RX"]
                    for count in range(2, 6)
                }
                for df in (0, 4, 5, 11, 16, 17, 20, 21)
            },
            "receiver_membership": dict(sorted(self.membership.items())),
        }
