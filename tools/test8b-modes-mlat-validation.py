#!/usr/bin/env python3
"""Phase 8B: offline non-position Mode-S association, blind MLAT, and post-hoc truth."""
import argparse
import csv
import hashlib
import importlib.util
import itertools
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path("/home/mlatserver/modeac-poc")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from realtime.config import ORDER
from realtime.modes.association import cluster_transmissions
from realtime.modes.decoder import decode_modes
from realtime.modes.localization import PAIRS, solve_grid
from realtime.localization import D7C


PRIORITY_DF = {4, 5, 11, 20, 21}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


T8A = load_module("test8b_shared_8a", ROOT / "tools/test8a-df17-mlat-validation.py")


def sha256(path):
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def write_csv(path, rows, fields=None, exclusive=False):
    fields = fields or list(rows[0])
    with path.open("x" if exclusive else "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def known_df17_icaos(run):
    known = set()
    for station in ORDER:
        with (run / "captures" / ("modeac-%s.csv" % station)).open() as handle:
            for row in csv.DictReader(handle):
                if row["beast_type"] != "3":
                    continue
                decoded = decode_modes(bytes.fromhex(row["raw_hex"]))
                if decoded and decoded["df"] == 17:
                    known.add(decoded["icao"])
    return known


def load_observations(run, known):
    observations = []
    counts = Counter()
    identifier = 0
    for station in ORDER:
        with (run / "captures" / ("modeac-%s.csv" % station)).open() as handle:
            for source_row, row in enumerate(csv.DictReader(handle), 2):
                if row["beast_type"] not in ("2", "3") or int(row["timestamp_corrected"]) == 0:
                    continue
                decoded = decode_modes(bytes.fromhex(row["raw_hex"]))
                if not decoded or decoded["df"] not in PRIORITY_DF:
                    continue
                reliable = decoded["icao_source"] == "DIRECT" or decoded["icao"] in known
                identifier += 1
                counts[(station, decoded["df"])] += 1
                observations.append({
                    "id": identifier, "station": station, "tick": int(row["timestamp_corrected"]), "utc_ns": int(row["recv_utc_ns"]),
                    "raw_hex": decoded["raw_hex"], "df": decoded["df"], "icao": decoded["icao"] if reliable else None,
                    "icao_source": decoded["icao_source"] if reliable else "UNTRUSTED", "altitude_ft": decoded["altitude_ft"],
                    "squawk": decoded["squawk"], "message_length": decoded["message_length"], "source_row": source_row,
                })
    return observations, counts


def solve_four(task):
    event, sigma, clock_quality = task
    started = time.perf_counter()
    solution = solve_grid(event["tdoa"], sigma)
    elapsed = (time.perf_counter() - started) * 1000
    selected = solution["selected"]
    second = solution["primary"][1] if len(solution["primary"]) > 1 else None
    row = {
        "event_id": event["event_id"], "icao": event["icao"], "identity_reliable": event["icao"] is not None,
        "df": event["df"], "event_utc_ns": event["utc_ns"], "event_time": T8A.iso(event["utc_ns"]), "raw_payload": event["raw_hex"],
        "receiver_set": ";".join(ORDER), "position_source": "MODES_MLAT_4RX", "solver_status": solution["classification"],
        "candidate_count": len(solution["primary"]), "expanded_candidate_count": len(solution["expanded"]),
        "selected_lat": selected["lat"] if selected else None, "selected_lon": selected["lon"] if selected else None,
        "altitude_assumption_ft": selected["altitude_ft"] if selected else None,
        "weighted_residual": selected["weighted_rms"] if selected else None, "unweighted_residual_us": selected["rms_us"] if selected else None,
        "branch_margin": second["weighted_rms"] - selected["weighted_rms"] if selected and second else None,
        "geometry_condition": selected["condition"] if selected else None, "clock_quality": clock_quality,
        "association_latency_ms": event["association_latency_ms"], "solver_latency_ms": elapsed,
    }
    candidates = [{
        "event_id": event["event_id"], "candidate_family": index, "latitude": candidate["lat"], "longitude": candidate["lon"],
        "altitude_ft": candidate["altitude_ft"], "weighted_residual": candidate["weighted_rms"], "geometry_condition": candidate["condition"],
        "selected": bool(selected and candidate["lat"] == selected["lat"] and candidate["lon"] == selected["lon"] and candidate["altitude_ft"] == selected["altitude_ft"]),
    } for index, candidate in enumerate(solution["expanded"], 1)]
    return row, candidates


def solve_three_alt(event):
    started = time.perf_counter()
    stations = event["stations"]
    _, branches, selected = D7C.solve(event["altitude_ft"] * 0.3048, stations, event["tdoa"])
    valid = [x for x in branches if x["center_km"] <= 1500 and math.isfinite(x["condition"]) and x["condition"] <= 1e8]
    status = "ALT_3RX_UNIQUE" if len(valid) == 1 else "ALT_3RX_MULTIPLE" if valid else "ALT_3RX_INCONSISTENT"
    if not any(selected is candidate for candidate in valid):
        selected = min(valid, key=lambda x: (x["rms_us"], x["center_km"], x["condition"])) if valid else None
    return {
        "event_id": event["event_id"], "icao": event["icao"], "identity_reliable": event["icao"] is not None, "df": event["df"],
        "event_utc_ns": event["utc_ns"], "event_time": T8A.iso(event["utc_ns"]), "raw_payload": event["raw_hex"],
        "receiver_set": ";".join(stations), "position_source": "MODES_MLAT_3RX_ALT", "altitude_ft": event["altitude_ft"],
        "solver_status": status, "candidate_count": len(valid), "selected_lat": selected["lat"] if selected else None,
        "selected_lon": selected["lon"] if selected else None, "residual_us": selected["rms_us"] if selected else None,
        "geometry_condition": selected["condition"] if selected else None, "association_latency_ms": event["association_latency_ms"],
        "solver_latency_ms": (time.perf_counter() - started) * 1000,
    }


def event_from_cluster(cluster, event_id):
    stations = list(cluster["nodes"])
    tdoa = {(a, b): (cluster["norm"][b] - cluster["norm"][a]) / 12 for a, b in itertools.combinations(stations, 2)}
    first = next(iter(cluster["nodes"].values()))
    return {
        "event_id": event_id, "icao": cluster["icao"], "df": cluster["df"], "utc_ns": cluster["utc_ns"], "raw_hex": cluster["raw_hex"],
        "stations": stations, "norm": cluster["norm"], "tdoa": tdoa, "altitude_ft": first.get("altitude_ft"),
        "association_latency_ms": cluster["association_latency_ms"],
    }


def evaluate(rows, candidates, trajectories, altitude_key="altitude_assumption_ft"):
    candidate_by_event = defaultdict(list)
    for candidate in candidates:
        candidate_by_event[int(candidate["event_id"])].append(candidate)
    evaluated = []
    for row in rows:
        if row["selected_lat"] is None or not row["icao"]:
            continue
        truth = T8A.interpolate_truth(trajectories.get(row["icao"], []), int(row["event_utc_ns"]))
        if truth is None:
            continue
        altitude_ft = row.get(altitude_key)
        error = T8A.horizontal_error(truth, row["selected_lat"], row["selected_lon"], float(altitude_ft or 0) * 0.3048)
        east, north, along, cross = T8A.components(truth, float(row["selected_lat"]), float(row["selected_lon"]))
        event_candidates = candidate_by_event[int(row["event_id"])]
        selected_nearest = None
        if event_candidates:
            nearest = min(event_candidates, key=lambda x: T8A.horizontal_error(truth, x["latitude"], x["longitude"], float(x.get("altitude_ft") or 0) * 0.3048))
            selected_nearest = bool(nearest["selected"])
        evaluated.append({
            "event_id": row["event_id"], "icao": row["icao"], "df": row["df"], "event_time": row["event_time"],
            "position_source": row["position_source"], "solver_status": row["solver_status"], "truth_method": truth["method"],
            "truth_time_separation_s": truth["time_separation_s"], "mlat_lat": row["selected_lat"], "mlat_lon": row["selected_lon"],
            "truth_lat": truth["lat"], "truth_lon": truth["lon"], "horizontal_error_m": error, "east_error_m": east,
            "north_error_m": north, "along_track_error_m": along, "cross_track_error_m": cross,
            "selected_nearest_truth": selected_nearest, "candidate_count": row["candidate_count"],
        })
    return evaluated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", default=str(ROOT / "test7h/20260809T071801Z"))
    parser.add_argument("--output", default=str(ROOT / "test8b"))
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    run, output = Path(args.run).resolve(), Path(args.output).resolve()
    if output.exists():
        raise SystemExit("refusing to overwrite %s" % output)
    output.mkdir(parents=True)
    clocks, transforms, sigma = T8A.load_clocks(run)
    class_by_pair = {(x["station_a"], x["station_b"]): x["classification"] for x in clocks}
    clock_quality = T8A._worst_clock([class_by_pair[p] for p in PAIRS])
    known = known_df17_icaos(run)
    observations, frame_counts = load_observations(run, known)
    association_started = time.perf_counter()
    clusters, association_diagnostics = cluster_transmissions(observations, transforms)
    association_elapsed = time.perf_counter() - association_started
    strict_clusters = [x for x in clusters if x["receiver_count"] == 4]
    alt_three_clusters = [x for x in clusters if x["receiver_count"] == 3 and x["df"] in (4, 20) and next(iter(x["nodes"].values())).get("altitude_ft") is not None]
    if args.limit:
        strict_clusters, alt_three_clusters = strict_clusters[:args.limit], alt_three_clusters[:args.limit]
    four_events = [event_from_cluster(cluster, index) for index, cluster in enumerate(strict_clusters, 1)]
    three_events = [event_from_cluster(cluster, index) for index, cluster in enumerate(alt_three_clusters, 1)]

    four_results, candidates = [], []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        tasks = ((event, sigma, clock_quality) for event in four_events)
        for index, (row, candidate_rows) in enumerate(executor.map(solve_four, tasks, chunksize=1), 1):
            four_results.append(row);candidates.extend(candidate_rows)
            if index % 50 == 0:
                print(json.dumps({"phase": "4rx", "complete": index, "total": len(four_events)}), flush=True)
    three_results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for index, row in enumerate(executor.map(solve_three_alt, three_events, chunksize=2), 1):
            three_results.append(row)
            if index % 250 == 0:
                print(json.dumps({"phase": "3rx_alt", "complete": index, "total": len(three_events)}), flush=True)

    # Freeze every MLAT output before trajectories are loaded.
    paths = [output / "test8b-4rx-results-frozen.csv", output / "test8b-4rx-candidates-frozen.csv", output / "test8b-3rx-alt-results-frozen.csv"]
    write_csv(paths[0], four_results, exclusive=True);write_csv(paths[1], candidates, exclusive=True);write_csv(paths[2], three_results, exclusive=True)
    frozen = {path.name: sha256(path) for path in paths}
    (output / "test8b-freeze.sha256").write_text("".join("%s  %s\n" % (digest, name) for name, digest in frozen.items()))

    trajectories = T8A.build_truth_trajectories(run)
    unique_four = [x for x in four_results if x["solver_status"] == "BLIND_UNIQUE"]
    four_eval = evaluate(unique_four, candidates, trajectories)
    three_eval = evaluate(three_results, [], trajectories, "altitude_ft")
    write_csv(output / "test8b-4rx-posthoc-evaluation.csv", four_eval)
    write_csv(output / "test8b-3rx-alt-posthoc-evaluation.csv", three_eval)

    df_stats = {}
    cluster_counts = Counter((x["df"], x["receiver_count"]) for x in clusters)
    for df in sorted(PRIORITY_DF):
        evaluated = [x for x in four_eval if int(x["df"]) == df]
        errors = [x["horizontal_error_m"] for x in evaluated]
        df_stats["DF%d" % df] = {
            "receiver_observations": sum(value for (station, observed_df), value in frame_counts.items() if observed_df == df),
            "2rx_clusters": cluster_counts[(df, 2)], "3rx_clusters": cluster_counts[(df, 3)], "4rx_clusters": cluster_counts[(df, 4)],
            "blind_unique": sum(int(x["df"]) == df and x["solver_status"] == "BLIND_UNIQUE" for x in four_results),
            "truth_evaluated": len(evaluated), "horizontal_error_m": T8A.distribution(errors),
        }
    by_icao = Counter(x["icao"] for x in four_eval)
    span_s = (max(x["event_utc_ns"] for x in four_results) - min(x["event_utc_ns"] for x in four_results)) / 1e9 if len(four_results) > 1 else 0
    tracks = [{"track_id": "MS-%s" % icao.upper(), "icao": icao, "fix_count": count, "fixes_per_min": count / (span_s / 60) if span_s else None} for icao, count in by_icao.most_common()]
    write_csv(output / "test8b-icao-tracks.csv", tracks)
    errors = [x["horizontal_error_m"] for x in four_eval]
    three_errors = [x["horizontal_error_m"] for x in three_eval]
    branches = [x for x in four_eval if x["candidate_count"] > 1 and x["selected_nearest_truth"] is not None]
    integrity = all(sha256(output / name) == digest for name, digest in frozen.items())
    error_stats = T8A.distribution(errors)
    if len(four_eval) >= 30 and integrity:
        accuracy = 100 * sum(x["selected_nearest_truth"] for x in branches) / len(branches) if branches else 100
        decision = "STRONG PASS" if error_stats["p95"] < 1000 and accuracy >= 90 else "PASS" if error_stats["p95"] < 5000 else "PARTIAL PASS"
    else:
        decision = "FAIL"
    three_by_status = Counter(x["solver_status"] for x in three_results)
    summary = {
        "decision": decision, "source_capture": str(run), "known_df17_icaos": len(known),
        "association": {**association_diagnostics, "full_capture_seconds": association_elapsed},
        "message_type_performance": df_stats, "strict_4rx_results": len(four_results),
        "strict_4rx_classifications": dict(Counter(x["solver_status"] for x in four_results)), "strict_4rx_truth_evaluated": len(four_eval),
        "horizontal_error_m": error_stats, "threshold_counts": {">1km": sum(x > 1000 for x in errors), ">2km": sum(x > 2000 for x in errors), ">5km": sum(x > 5000 for x in errors), ">10km": sum(x > 10000 for x in errors)},
        "branch_accuracy": {"selected_nearest_truth": sum(x["selected_nearest_truth"] for x in branches), "evaluated": len(branches)},
        "three_rx_alt": {"attempted": len(three_results), "classifications": dict(three_by_status), "truth_evaluated": len(three_eval), "horizontal_error_m": T8A.distribution(three_errors)},
        "icao_tracks": len(tracks), "fix_rates_per_aircraft_per_min": {x["icao"]: x["fixes_per_min"] for x in tracks},
        "latency_ms": {"4rx_solver": T8A.distribution([x["solver_latency_ms"] for x in four_results]), "3rx_alt_solver": T8A.distribution([x["solver_latency_ms"] for x in three_results]), "association": T8A.distribution([x["association_latency_ms"] for x in four_results])},
        "clock_links": clocks, "frozen_hashes": frozen, "frozen_integrity_after_truth": integrity,
        "anti_leakage": "Mode-S MLAT outputs and candidate branches were frozen before DF17 trajectories were loaded.",
    }
    (output / "test8b-summary.json").write_text(json.dumps(summary, indent=2))
    best_df = max(df_stats, key=lambda key: df_stats[key]["blind_unique"])
    lines = [
        "# Phase 8B — Non-position Mode-S MLAT validation", "", "**Decision: %s**" % decision, "",
        "Exact-payload, reciprocal, physical-bound clustering produced %d strict 4RX and %d 3RX clusters for DF4/5/11/20/21. ICAO was direct for DF11; AP-recovered identities were accepted only when independently present in the capture's DF17 ICAO set." % (association_diagnostics.get("4RX", 0), association_diagnostics.get("3RX", 0)), "",
        "All Mode-S positions were frozen before post-hoc DF17 trajectory loading. Hash integrity after evaluation: **%s**. Frozen hashes: `%s`." % (integrity, json.dumps(frozen, sort_keys=True)), "",
        "## Strict 4RX", "",
        "Results/classifications/truth matches: %d / `%s` / %d. Horizontal P50/P75/P90/P95/P99/max: %s m. Counts >1/>2/>5/>10 km: %s." % (len(four_results), dict(Counter(x["solver_status"] for x in four_results)), len(four_eval), "/".join(str(error_stats[key]) for key in ("p50", "p75", "p90", "p95", "p99", "max")), "/".join(str(summary["threshold_counts"][key]) for key in (">1km", ">2km", ">5km", ">10km"))), "",
        "Frozen branch selection was nearest post-hoc truth in %d/%d multiple-candidate events. Message-type yield and accuracy: `%s`. Highest useful strict-fix yield: **%s**." % (summary["branch_accuracy"]["selected_nearest_truth"], summary["branch_accuracy"]["evaluated"], json.dumps(df_stats, sort_keys=True), best_df), "",
        "## 3RX + message altitude", "",
        "Attempted %d altitude-bearing events; classifications `%s`; truth-evaluated horizontal errors `%s`. This path remains secondary because three receivers frequently retain multiple horizontal branches." % (len(three_results), dict(three_by_status), T8A.distribution(three_errors)), "",
        "## Tracks, rates, and latency", "",
        "Reliable ICAO-linked tracks: %d. Per-aircraft fix rates are in `test8b-icao-tracks.csv` and the JSON summary. Offline 4RX and 3RX solver latency: `%s` / `%s` ms. No timestamp-valid mutability output existed in this immutable dataset, so no unsupported speed claim is made." % (len(tracks), summary["latency_ms"]["4rx_solver"], summary["latency_ms"]["3rx_alt_solver"]), "",
        "## Gate", "", "The decision above controls whether realtime Phase 8C may proceed. Historical Mode A/C behavior is tested separately and was not used or changed by this analysis.",
    ]
    (ROOT / "docs/test8b-modes-mlat-validation.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"decision": decision, "strict4": len(four_results), "truth_evaluated": len(four_eval), "errors": error_stats, "by_df": df_stats, "three_rx_alt": summary["three_rx_alt"], "tracks": len(tracks)}, indent=2))


if __name__ == "__main__":
    main()
