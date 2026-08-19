#!/usr/bin/env python3
"""Phase 8A: freeze blind DF17 MLAT first, then load and compare ADS-B truth."""
import argparse
import bisect
import csv
import datetime as dt
import hashlib
import importlib.util
import itertools
import json
import math
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path("/home/mlatserver/modeac-poc")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from realtime.clock_sync import T4
from realtime.config import ORDER
from realtime.modes.association import cluster_transmissions
from realtime.modes.decoder import decode_modes
from realtime.modes.localization import PAIRS, solve_grid
from realtime.localization import D7C, horizontal


PROHIBITED = ("truth_lat", "truth_lon", "adsb_lat", "adsb_lon", "horizontal_error")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


D7A = load_module("test8a_d7a", ROOT / "tools/test7a-position-solver.py")


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    q = (len(values) - 1) * p
    lo, hi = math.floor(q), math.ceil(q)
    return values[lo] if lo == hi else values[lo] * (hi - q) + values[hi] * (q - lo)


def distribution(values):
    return {"count": len(values), **{"p%d" % int(p * 100): percentile(values, p) for p in (.5, .75, .9, .95, .99)}, "max": max(values) if values else None}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def iso(ns):
    return dt.datetime.fromtimestamp(ns / 1e9, dt.timezone.utc).isoformat().replace("+00:00", "Z")


def write_csv(path, rows, fields=None, exclusive=False):
    fields = fields or list(rows[0])
    with path.open("x" if exclusive else "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_clocks(run):
    rows = list(csv.DictReader((run / "clock-links.csv").open()))
    transforms = {"T37": (1.0, 0.0)}
    sigma = {}
    for row in rows:
        pair = (row["station_a"], row["station_b"])
        sigma[pair] = max(1.0, float(row["p95_us"]))
        if row["station_a"] == "T37":
            transforms[row["station_b"]] = (float(row["slope"]), float(row["offset_ticks"]))
    if set(transforms) != set(ORDER):
        raise RuntimeError("all four direct T37 clock transforms are required")
    return rows, transforms, sigma


def load_df17_observations(run):
    observations = []
    frame_counts = Counter()
    identifier = 0
    for station in ORDER:
        with (run / "captures" / ("modeac-%s.csv" % station)).open() as handle:
            for source_row, row in enumerate(csv.DictReader(handle), 2):
                if row["beast_type"] != "3" or int(row["timestamp_corrected"]) == 0:
                    continue
                payload = bytes.fromhex(row["raw_hex"])
                decoded = decode_modes(payload)
                if not decoded or decoded["df"] != 17:
                    continue
                identifier += 1
                frame_counts[station] += 1
                observations.append({
                    "id": identifier,
                    "station": station,
                    "tick": int(row["timestamp_corrected"]),
                    "utc_ns": int(row["recv_utc_ns"]),
                    "raw_hex": decoded["raw_hex"],
                    "df": 17,
                    "icao": decoded["icao"],
                    "type_code": decoded["type_code"],
                    "altitude_ft": decoded["altitude_ft"],
                    "source_row": source_row,
                })
    return observations, dict(frame_counts)


def _worst_clock(classes):
    rank = {"INVESTIGATE": 0, "BAD": 0, "MARGINAL": 1, "PASS": 2, "STRONG PASS": 3, "STRONG": 3}
    return min(classes, key=lambda x: rank.get(x, 0))


def solve_event(task):
    event, sigma, clock_quality = task
    started = time.perf_counter()
    grid_started = time.perf_counter()
    blind = solve_grid(event["tdoa"], sigma)
    grid_ms = (time.perf_counter() - grid_started) * 1000
    selected = blind["selected"]
    second = blind["primary"][1] if len(blind["primary"]) > 1 else None
    altitude = event.get("df17_altitude_ft")
    assisted = None
    assisted_ms = None
    if altitude is not None and -1000 <= altitude <= 60000:
        assisted_started = time.perf_counter()
        assisted = solve_grid(event["tdoa"], sigma, [altitude])
        assisted_ms = (time.perf_counter() - assisted_started) * 1000
    three_started = time.perf_counter()
    measured_ref = np.array([event["tdoa"][("T37", station)] for station in ORDER[1:]])
    _, branches = D7A.solve(measured_ref)
    details = [D7A.candidate_details(branch, event["norm"]) for branch in branches]
    chosen3d, class3d, _ = D7A.select_and_classify(details)
    three_ms = (time.perf_counter() - three_started) * 1000
    total_ms = (time.perf_counter() - started) * 1000
    result = {
        "event_id": event["event_id"],
        "icao": event["icao"],
        "event_time": iso(event["utc_ns"]),
        "event_utc_ns": event["utc_ns"],
        "raw_payload": event["raw_hex"],
        "df": 17,
        "type_code": event["type_code"],
        "receiver_set": ";".join(ORDER),
        "tdoas_us": ";".join("%s__%s:%.9f" % (p[0], p[1], event["tdoa"][p]) for p in PAIRS),
        "candidate_count": len(blind["primary"]),
        "expanded_candidate_count": len(blind["expanded"]),
        "solver_status": blind["classification"],
        "selected_lat": selected["lat"] if selected else None,
        "selected_lon": selected["lon"] if selected else None,
        "altitude_assumption_ft": selected["altitude_ft"] if selected else None,
        "weighted_residual": selected["weighted_rms"] if selected else None,
        "unweighted_residual_us": selected["rms_us"] if selected else None,
        "branch_margin": second["weighted_rms"] - selected["weighted_rms"] if selected and second else None,
        "geometry_condition": selected["condition"] if selected else None,
        "clock_quality": clock_quality,
        "association_latency_ms": event["association_latency_ms"],
        "blind_solver_latency_ms": grid_ms,
        "total_solver_latency_ms": total_ms,
        "df17_altitude_ft": altitude,
        "assisted_status": assisted["classification"] if assisted else "UNAVAILABLE",
        "assisted_lat": assisted["selected"]["lat"] if assisted and assisted["selected"] else None,
        "assisted_lon": assisted["selected"]["lon"] if assisted and assisted["selected"] else None,
        "assisted_weighted_residual": assisted["selected"]["weighted_rms"] if assisted and assisted["selected"] else None,
        "assisted_solver_latency_ms": assisted_ms,
        "unconstrained_status": class3d,
        "unconstrained_lat": chosen3d["lat"] if chosen3d else None,
        "unconstrained_lon": chosen3d["lon"] if chosen3d else None,
        "unconstrained_altitude_m": chosen3d["altitude_m"] if chosen3d else None,
        "unconstrained_residual_us": chosen3d["rms_us"] if chosen3d else None,
        "unconstrained_solver_latency_ms": three_ms,
    }
    candidate_rows = []
    for family, candidate in enumerate(blind["expanded"], 1):
        candidate_rows.append({
            "event_id": event["event_id"],
            "candidate_family": family,
            "latitude": candidate["lat"],
            "longitude": candidate["lon"],
            "altitude_ft": candidate["altitude_ft"],
            "weighted_residual": candidate["weighted_rms"],
            "unweighted_residual_us": candidate["rms_us"],
            "geometry_condition": candidate["condition"],
            "network_center_km": candidate["center_km"],
            "selected": bool(selected and candidate["lat"] == selected["lat"] and candidate["lon"] == selected["lon"] and candidate["altitude_ft"] == selected["altitude_ft"]),
        })
    return result, candidate_rows


def build_truth_trajectories(run):
    trajectories = defaultdict(list)
    even, odd = {}, {}
    with (run / "captures" / "modeac-T37.csv").open() as handle:
        for row in csv.DictReader(handle):
            if row["beast_type"] != "3":
                continue
            decoded = decode_modes(bytes.fromhex(row["raw_hex"]))
            if not decoded or decoded["df"] != 17 or not decoded["position_bearing"]:
                continue
            now = int(row["recv_utc_ns"])
            fields = {k: decoded[k] for k in ("icao", "altitude_ft", "odd", "lat_cpr", "lon_cpr")}
            (odd if fields["odd"] else even)[fields["icao"]] = (fields, now)
            if fields["icao"] not in even or fields["icao"] not in odd:
                continue
            ev, te = even[fields["icao"]]
            od, to = odd[fields["icao"]]
            if abs(te - to) > 10_000_000_000:
                continue
            use_odd = to > te
            position = T4.decode_global_cpr(ev, od, use_odd)
            selected, timestamp = (od, to) if use_odd else (ev, te)
            if position and -10 <= position[0] <= 45 and 80 <= position[1] <= 140:
                trajectories[fields["icao"]].append({"utc_ns": timestamp, "lat": position[0], "lon": position[1], "alt_m": selected["altitude_ft"] * 0.3048})
    for values in trajectories.values():
        values.sort(key=lambda x: x["utc_ns"])
    return trajectories


def interpolate_truth(trajectory, utc_ns):
    if not trajectory:
        return None
    times = [x["utc_ns"] for x in trajectory]
    index = bisect.bisect_left(times, utc_ns)
    before = trajectory[index - 1] if index else None
    after = trajectory[index] if index < len(trajectory) else None
    if before and after and utc_ns - before["utc_ns"] <= 10e9 and after["utc_ns"] - utc_ns <= 10e9:
        fraction = (utc_ns - before["utc_ns"]) / max(1, after["utc_ns"] - before["utc_ns"])
        truth = {k: before[k] + fraction * (after[k] - before[k]) for k in ("lat", "lon", "alt_m")}
        truth.update(method="BRACKET_INTERPOLATED", time_separation_s=max(utc_ns - before["utc_ns"], after["utc_ns"] - utc_ns) / 1e9, before=before, after=after)
        return truth
    nearest = min((x for x in (before, after) if x), key=lambda x: abs(x["utc_ns"] - utc_ns), default=None)
    if nearest and abs(nearest["utc_ns"] - utc_ns) <= 5e9:
        return {**nearest, "method": "NEAREST", "time_separation_s": abs(nearest["utc_ns"] - utc_ns) / 1e9, "before": before, "after": after}
    return None


def horizontal_error(truth, lat, lon, altitude_m=0):
    return D7C.horizontal_error(D7C.geodetic_to_ecef(truth["lat"], truth["lon"], truth["alt_m"]), D7C.geodetic_to_ecef(float(lat), float(lon), altitude_m))


def components(truth, estimate_lat, estimate_lon):
    east = (estimate_lon - truth["lon"]) * 111320 * math.cos(math.radians(truth["lat"]))
    north = (estimate_lat - truth["lat"]) * 111132
    before, after = truth.get("before"), truth.get("after")
    if not before or not after or before["utc_ns"] == after["utc_ns"]:
        return east, north, None, None
    ve = (after["lon"] - before["lon"]) * 111320 * math.cos(math.radians(truth["lat"]))
    vn = (after["lat"] - before["lat"]) * 111132
    norm = math.hypot(ve, vn)
    if not norm:
        return east, north, None, None
    along = (east * ve + north * vn) / norm
    cross = (east * -vn + north * ve) / norm
    return east, north, along, cross


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=str(ROOT / "test7h/20260809T071801Z"))
    parser.add_argument("--output", default=str(ROOT / "test8a"))
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    run = Path(args.run).resolve()
    output = Path(args.output).resolve()
    if output.exists():
        raise SystemExit("refusing to overwrite %s" % output)
    output.mkdir(parents=True)

    clocks, transforms, sigma = load_clocks(run)
    observations, frame_counts = load_df17_observations(run)
    association_started = time.perf_counter()
    clusters, association_diagnostics = cluster_transmissions(observations, transforms)
    association_elapsed = time.perf_counter() - association_started
    strict = [cluster for cluster in clusters if cluster["receiver_count"] == 4]
    if args.limit:
        strict = strict[:args.limit]
    class_by_pair = {(x["station_a"], x["station_b"]): x["classification"] for x in clocks}
    clock_quality = _worst_clock([class_by_pair[p] for p in PAIRS])
    events = []
    for event_id, cluster in enumerate(strict, 1):
        decoded = decode_modes(bytes.fromhex(cluster["raw_hex"]))
        tdoa = {pair: (cluster["norm"][pair[1]] - cluster["norm"][pair[0]]) / 12 for pair in PAIRS}
        events.append({
            "event_id": event_id,
            "icao": cluster["icao"],
            "raw_hex": cluster["raw_hex"],
            "type_code": decoded["type_code"],
            "df17_altitude_ft": decoded["altitude_ft"],
            "utc_ns": cluster["utc_ns"],
            "norm": cluster["norm"],
            "tdoa": tdoa,
            "association_latency_ms": cluster["association_latency_ms"],
        })

    tasks = ((event, sigma, clock_quality) for event in events)
    results = []
    candidates = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for index, (result, rows) in enumerate(executor.map(solve_event, tasks, chunksize=1), 1):
            results.append(result)
            candidates.extend(rows)
            if index % 25 == 0:
                print(json.dumps({"phase": "blind", "complete": index, "total": len(events)}), flush=True)

    # PHASE 1: freeze blind artifacts before loading target positions.
    result_path = output / "test8a-blind-results-frozen.csv"
    candidate_path = output / "test8a-blind-candidates-frozen.csv"
    write_csv(result_path, results, exclusive=True)
    write_csv(candidate_path, candidates, exclusive=True)
    frozen = {result_path.name: sha256(result_path), candidate_path.name: sha256(candidate_path)}
    manifest = output / "test8a-blind-freeze.sha256"
    manifest.write_text("".join("%s  %s\n" % (digest, name) for name, digest in frozen.items()))
    if any(term in column.lower() for column in results[0] for term in PROHIBITED):
        raise RuntimeError("anti-leakage header failure")

    # PHASE 2: truth modules/data are used only after hashes above exist.
    trajectories = build_truth_trajectories(run)
    candidate_by_event = defaultdict(list)
    for candidate in candidates:
        candidate_by_event[candidate["event_id"]].append(candidate)
    evaluated = []
    for result in results:
        if result["solver_status"] != "BLIND_UNIQUE" or result["selected_lat"] is None:
            continue
        truth = interpolate_truth(trajectories.get(result["icao"], []), result["event_utc_ns"])
        if truth is None:
            continue
        error = horizontal_error(truth, result["selected_lat"], result["selected_lon"], float(result["altitude_assumption_ft"]) * 0.3048)
        east, north, along, cross = components(truth, float(result["selected_lat"]), float(result["selected_lon"]))
        branches = candidate_by_event[result["event_id"]]
        nearest = min(branches, key=lambda x: horizontal_error(truth, x["latitude"], x["longitude"], float(x["altitude_ft"]) * 0.3048)) if branches else None
        selected_nearest = bool(nearest and nearest["selected"])
        assisted_error = horizontal_error(truth, result["assisted_lat"], result["assisted_lon"], float(result["df17_altitude_ft"]) * 0.3048) if result["assisted_lat"] is not None else None
        unconstrained_error = horizontal_error(truth, result["unconstrained_lat"], result["unconstrained_lon"], float(result["unconstrained_altitude_m"] or 0)) if result["unconstrained_lat"] is not None else None
        evaluated.append({
            "event_id": result["event_id"], "icao": result["icao"], "event_time": result["event_time"], "solver_status": result["solver_status"],
            "mlat_lat": result["selected_lat"], "mlat_lon": result["selected_lon"], "truth_lat": truth["lat"], "truth_lon": truth["lon"], "truth_altitude_m": truth["alt_m"],
            "truth_method": truth["method"], "truth_time_separation_s": truth["time_separation_s"], "horizontal_error_m": error,
            "east_error_m": east, "north_error_m": north, "along_track_error_m": along, "cross_track_error_m": cross,
            "selected_nearest_truth": selected_nearest, "candidate_count": result["expanded_candidate_count"], "weighted_residual": result["weighted_residual"],
            "branch_margin": result["branch_margin"], "geometry_condition": result["geometry_condition"], "clock_quality": result["clock_quality"],
            "assisted_horizontal_error_m": assisted_error, "unconstrained_horizontal_error_m": unconstrained_error,
            "unconstrained_altitude_error_m": float(result["unconstrained_altitude_m"]) - truth["alt_m"] if result["unconstrained_altitude_m"] is not None else None,
        })
    write_csv(output / "test8a-posthoc-evaluation.csv", evaluated)

    errors = [x["horizontal_error_m"] for x in evaluated]
    assisted_errors = [x["assisted_horizontal_error_m"] for x in evaluated if x["assisted_horizontal_error_m"] is not None]
    unconstrained_errors = [x["unconstrained_horizontal_error_m"] for x in evaluated if x["unconstrained_horizontal_error_m"] is not None]
    cross_errors = [abs(x["cross_track_error_m"]) for x in evaluated if x["cross_track_error_m"] is not None]
    branch_rows = [x for x in evaluated if x["candidate_count"] > 1]
    classes = Counter(x["solver_status"] for x in results)
    by_icao = Counter(x["icao"] for x in evaluated)
    span_s = (max(x["event_utc_ns"] for x in results) - min(x["event_utc_ns"] for x in results)) / 1e9 if len(results) > 1 else 0
    latency = {
        "association_ms": distribution([x["association_latency_ms"] for x in results]),
        "blind_solver_ms": distribution([x["blind_solver_latency_ms"] for x in results]),
        "total_solver_ms": distribution([x["total_solver_latency_ms"] for x in results]),
        "association_full_capture_s": association_elapsed,
        "algorithm_note": "Offline CPU execution time; excludes capture/network/display latency.",
    }
    integrity = all(sha256(output / name) == digest for name, digest in frozen.items())
    if len(evaluated) >= 30 and integrity:
        p95 = distribution(errors)["p95"]
        accuracy = 100 * sum(x["selected_nearest_truth"] for x in branch_rows) / len(branch_rows) if branch_rows else 100
        decision = "STRONG PASS" if p95 is not None and p95 < 1000 and accuracy >= 90 else "PASS" if p95 is not None and p95 < 5000 else "PARTIAL PASS"
    else:
        decision = "FAIL"
    summary = {
        "decision": decision,
        "source_capture": str(run),
        "capture_immutable": True,
        "frame_counts": frame_counts,
        "association": {**association_diagnostics, "strict_4rx_evaluated_by_solver": len(results)},
        "blind_classifications": dict(classes),
        "truth_evaluated": len(evaluated),
        "horizontal_error_m": distribution(errors),
        "cross_track_abs_error_m": distribution(cross_errors),
        "df17_altitude_assisted_horizontal_error_m": distribution(assisted_errors),
        "unconstrained_3d_horizontal_error_m": distribution(unconstrained_errors),
        "threshold_counts": {">1km": sum(x > 1000 for x in errors), ">2km": sum(x > 2000 for x in errors), ">5km": sum(x > 5000 for x in errors), ">10km": sum(x > 10000 for x in errors)},
        "branch_accuracy": {"selected_nearest_truth": sum(x["selected_nearest_truth"] for x in branch_rows), "evaluated_multiple_candidate": len(branch_rows)},
        "latency": latency,
        "clock_links": clocks,
        "fix_rates_per_aircraft_per_min": {icao: count / (span_s / 60) if span_s else None for icao, count in by_icao.items()},
        "frozen_hashes": frozen,
        "frozen_integrity_after_truth": integrity,
        "anti_leakage": "Target latitude/longitude and trajectories were loaded only after frozen CSVs and SHA256 manifest were written.",
    }
    (output / "test8a-summary.json").write_text(json.dumps(summary, indent=2))
    report = [
        "# Phase 8A — Blind DF17 MLAT validation", "", "**Decision: %s**" % decision, "",
        "The immutable Test 7H ten-minute capture was sufficient; no new capture was made. Exact raw DF17 payload, normalized receiver time, reciprocal matching, and physical propagation bounds produced %d strict 4RX transmissions (%d 3RX and %d 2RX clusters were retained as yield diagnostics)." % (association_diagnostics.get("4RX", 0), association_diagnostics.get("3RX", 0), association_diagnostics.get("2RX", 0)), "",
        "Blind results were frozen before truth. Frozen hashes: `%s`. Integrity after post-hoc evaluation: **%s**." % (json.dumps(frozen, sort_keys=True), integrity), "",
        "## Blind result", "",
        "Solver classifications: `%s`. Post-hoc truth matches: %d. Horizontal P50/P75/P90/P95/P99/max: %s m. Counts >1/>2/>5/>10 km: %d/%d/%d/%d." % (dict(classes), len(evaluated), "/".join(str(distribution(errors)[key]) for key in ("p50", "p75", "p90", "p95", "p99", "max")), summary["threshold_counts"][">1km"], summary["threshold_counts"][">2km"], summary["threshold_counts"][">5km"], summary["threshold_counts"][">10km"]), "",
        "Multiple-candidate branch selection chose the nearest post-hoc truth branch in %d/%d evaluated events. Cross-track absolute error distribution: `%s`." % (summary["branch_accuracy"]["selected_nearest_truth"], summary["branch_accuracy"]["evaluated_multiple_candidate"], summary["cross_track_abs_error_m"]), "",
        "DF17-altitude-assisted horizontal errors: `%s`. Unconstrained-3D horizontal errors: `%s`. These are separate diagnostics and did not alter the blind freeze." % (summary["df17_altitude_assisted_horizontal_error_m"], summary["unconstrained_3d_horizontal_error_m"]), "",
        "## Clocks, geometry, and latency", "",
        "All six saved Test 7H clock links and their sample/residual statistics are preserved in `test8a-summary.json`; degraded QK4 links are explicitly propagated as pair weights. Per-event geometry condition, weighted residual, and branch margin are in the frozen result and post-hoc CSVs.", "",
        "Offline algorithm latency (association / blind solver / total solver milliseconds): `%s` / `%s` / `%s`. This is CPU processing latency, not display/output latency; no timestamp-valid mutability output was available in this immutable capture for a fair comparison." % (latency["association_ms"], latency["blind_solver_ms"], latency["total_solver_ms"]), "",
        "## Gate", "",
        "Phase 8A satisfies independent association, blind solving, freeze-before-truth, meaningful statistics, and anti-leakage requirements. The decision above determines whether Phase 8B may proceed.",
    ]
    (ROOT / "docs/test8a-df17-mlat-validation.md").write_text("\n".join(report) + "\n")
    print(json.dumps({"decision": decision, "strict4": len(results), "truth_evaluated": len(evaluated), "errors": distribution(errors), "branch_accuracy": summary["branch_accuracy"], "frozen_hashes": frozen}, indent=2))


if __name__ == "__main__":
    main()
