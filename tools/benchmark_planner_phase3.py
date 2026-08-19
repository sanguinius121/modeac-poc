#!/usr/bin/env python3
"""Reproducible Phase Tool-3 4-of-N planner benchmark (planning only)."""
import argparse
import json

from deployment_planner.backend.api import (CURRENT_RECEIVERS, DEFAULT_POLYGON,
                                            analyze_payload, analyze_point_payload)


CANDIDATES = [
    {"id": "rx-east", "name": "RX-East (SIMULATED)", "lat": 20.0,
     "lon": 109.0, "altitude_m": 30, "reception_model": "simulated",
     "max_range_km": 350, "enabled": True},
    {"id": "rx-west", "name": "RX-West (SIMULATED)", "lat": 20.0,
     "lon": 105.5, "altitude_m": 30, "reception_model": "simulated",
     "max_range_km": 350, "enabled": True},
    {"id": "rx-north", "name": "RX-North (SIMULATED)", "lat": 22.0,
     "lon": 108.0, "altitude_m": 30, "reception_model": "simulated",
     "max_range_km": 350, "enabled": True},
]


def run(n, step):
    receivers = [dict(x) for x in CURRENT_RECEIVERS] + [dict(x) for x in CANDIDATES[:n - 4]]
    body = {
        "receivers": receivers,
        "surveillance_polygon": [list(x) for x in DEFAULT_POLYGON],
        "target_altitude_m": 2500,
        "timing_noise_us": 0.25,
        "grid_step_km": step,
        "geometry_receiver_ids": [x["id"] for x in CURRENT_RECEIVERS],
        "geometry_strategy": "best_4_of_n",
    }
    result = analyze_payload(body)
    s = result["summary"]
    return {key: s.get(key) for key in (
        "grid_points", "subset_evaluations", "maximum_subsets_per_point",
        "analysis_seconds", "four_plus_rx_coverage_percent",
        "five_plus_rx_coverage_percent", "six_plus_rx_coverage_percent",
        "good_percent", "good_acceptable_percent", "worst_good_percent",
        "n_minus_1_survivable_percent", "median_best_p95_m",
        "p90_best_p95_m", "median_worst_p95_m", "p90_worst_p95_m",
        "receiver_importance")}


def strict(step):
    body = {
        "receivers": [dict(x) for x in CURRENT_RECEIVERS],
        "surveillance_polygon": [list(x) for x in DEFAULT_POLYGON],
        "target_altitude_m": 2500,
        "timing_noise_us": 0.25,
        "grid_step_km": step,
        "geometry_receiver_ids": [x["id"] for x in CURRENT_RECEIVERS],
        "geometry_strategy": "strict_4",
    }
    s = analyze_payload(body)["summary"]
    return {key: s.get(key) for key in (
        "grid_points", "subset_evaluations", "analysis_seconds",
        "four_plus_rx_coverage_percent", "selected_strict_4_common_coverage_percent",
        "good_percent", "good_acceptable_percent", "median_predicted_p95_m",
        "p90_predicted_p95_m")}


def synthetic(n):
    if n == 5:
        points = [(19, 107), (19, 109), (21, 109), (21, 107), (20, 108)]
    else:
        points = [(22, 108), (20.62, 109.9), (18.38, 109.18),
                  (18.38, 106.82), (20.62, 106.1), (20, 108)]
    receivers = [{"id": "s%d" % (i + 1), "name": "S%d" % (i + 1),
                  "lat": lat, "lon": lon, "altitude_m": 30,
                  "reception_model": "simulated", "max_range_km": 500,
                  "enabled": True} for i, (lat, lon) in enumerate(points)]
    body = {"receivers": receivers,
            "surveillance_polygon": [[19.8, 107.8], [19.8, 108.2],
                                     [20.2, 108.2], [20.2, 107.8]],
            "target_altitude_m": 2500, "timing_noise_us": .25,
            "grid_step_km": 20,
            "geometry_receiver_ids": [x["id"] for x in receivers[:4]],
            "geometry_strategy": "best_4_of_n", "point": [20, 108]}
    detail = analyze_point_payload(body)
    rows = detail["subsets"]
    all_ids = {x["id"] for x in receivers}
    return {"layout": "4 perimeter + center" if n == 5 else "5 perimeter + center",
            "matched_grid_point": detail["matched_grid_point"],
            "subset_count": len(rows), "best": rows[0],
            "median_p95_m": sorted(x["p95_error_m"] for x in rows)[len(rows) // 2],
            "worst": max(rows, key=lambda x: x["p95_error_m"]),
            "good_count": sum(x["quality"] == "GOOD" for x in rows),
            "n_minus_1_survivable": detail["n_minus_1_survivable"],
            "leave_one_out": [{"dropped": sorted(all_ids - set(x["subset_ids"])),
                               "p95_error_m": x["p95_error_m"],
                               "quality": x["quality"]} for x in rows] if n == 5 else None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, choices=(4, 5, 6, 7))
    parser.add_argument("--step", type=int, choices=(5, 10, 20))
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--synthetic", type=int, choices=(5, 6))
    args = parser.parse_args()
    if args.synthetic is None and args.step is None:
        parser.error("--step is required unless --synthetic is used")
    result = synthetic(args.synthetic) if args.synthetic else (strict(args.step) if args.strict else run(args.n, args.step))
    print(json.dumps(result,
                     indent=2, sort_keys=True))
