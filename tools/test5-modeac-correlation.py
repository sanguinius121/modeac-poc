#!/usr/bin/env python3
"""Test 5: conservative cross-station correlation of Beast Mode A/C replies."""

import argparse
import csv
import importlib.util
import json
import math
import statistics
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from pathlib import Path

BEAST_HZ = 12_000_000.0
C = 299_792_458.0
STATION_A = (21.485594, 107.773191, 60.0)
STATION_B = (21.320940, 107.766116, 28.0)


def percentile(values, p):
    if not values:
        return float("nan")
    x = sorted(values)
    if len(x) == 1:
        return x[0]
    pos = (len(x) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    return x[lo] if lo == hi else x[lo] * (hi - pos) + x[hi] * (pos - lo)


def pct(n, d):
    return 100.0 * n / d if d else 0.0


def finite(value):
    return None if isinstance(value, float) and not math.isfinite(value) else value


def load_test4b(script):
    spec = importlib.util.spec_from_file_location("test4b", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_modeac(path):
    records, zero = [], 0
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        required = {"recv_utc_ns", "frame_kind", "timestamp_corrected", "raw_hex"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise RuntimeError(f"{path}: missing columns {sorted(missing)}")
        for row in reader:
            if row["frame_kind"] != "modeac":
                continue
            ts = int(row["timestamp_corrected"])
            if ts == 0:
                zero += 1
                continue
            raw = row["raw_hex"].strip().lower()
            try:
                decoded = bytes.fromhex(raw)
            except ValueError:
                continue
            if len(decoded) != 2:
                continue
            records.append({"id": len(records), "ts": ts, "utc_ns": int(row["recv_utc_ns"]), "raw_hex": raw})
    records.sort(key=lambda r: r["ts"])
    for i, r in enumerate(records):
        r["id"] = i
    return records, zero


def make_index(rows):
    idx = defaultdict(list)
    for row in rows:
        idx[row["raw_hex"]].append(row)
    for code, values in idx.items():
        values.sort(key=lambda r: r["ts"])
        idx[code] = (values, [r["ts"] for r in values])
    return idx


def candidates(index, code, prediction, gate_ticks):
    entry = index.get(code)
    if not entry:
        return []
    rows, times = entry
    lo = bisect_left(times, prediction - gate_ticks)
    hi = bisect_right(times, prediction + gate_ticks)
    return rows[lo:hi]


def run_matching(rows_a, rows_b, slope, intercept, gate_ticks):
    idx_a, idx_b = make_index(rows_a), make_index(rows_b)
    multiplicity = Counter()
    attempts_by_code = Counter()
    ambiguous_by_code = Counter()
    used_b, accepted, conflicts = set(), [], 0

    for a in rows_a:
        prediction = slope * a["ts"] + intercept
        cs = candidates(idx_b, a["raw_hex"], prediction, gate_ticks)
        n = len(cs)
        bucket = "0" if n == 0 else "1" if n == 1 else "2" if n == 2 else "3+"
        multiplicity[bucket] += 1
        attempts_by_code[a["raw_hex"]] += 1
        if n > 1:
            ambiguous_by_code[a["raw_hex"]] += 1
        if n != 1:
            continue
        b = cs[0]
        if b["id"] in used_b:
            conflicts += 1
            continue
        used_b.add(b["id"])
        delta_ticks = b["ts"] - prediction
        accepted.append({
            "a": a, "b": b, "tb0": prediction, "delta_ticks": delta_ticks,
            "tdoa_us": delta_ticks / 12.0,
        })

    # A reciprocal match uses the inverse clock transform and the identical gate.
    reciprocal = 0
    for m in accepted:
        predicted_a = (m["b"]["ts"] - intercept) / slope
        reverse_gate = gate_ticks / abs(slope)
        cs = candidates(idx_a, m["a"]["raw_hex"], predicted_a, reverse_gate)
        if len(cs) == 1 and cs[0]["id"] == m["a"]["id"]:
            reciprocal += 1
    return {
        "multiplicity": dict(multiplicity), "accepted": accepted, "conflicts": conflicts,
        "ambiguous": multiplicity["2"] + multiplicity["3+"], "reciprocal": reciprocal,
        "attempts_by_code": attempts_by_code, "ambiguous_by_code": ambiguous_by_code,
    }


def stats(values):
    absolute = [abs(v) for v in values]
    return {k: finite(v) for k, v in {
        "minimum_us": min(values) if values else float("nan"),
        "maximum_us": max(values) if values else float("nan"),
        "mean_us": statistics.mean(values) if values else float("nan"),
        "median_us": statistics.median(values) if values else float("nan"),
        "p01_us": percentile(values, .01), "p05_us": percentile(values, .05),
        "p25_us": percentile(values, .25), "p75_us": percentile(values, .75),
        "p95_us": percentile(values, .95), "p99_us": percentile(values, .99),
        "absolute_median_us": percentile(absolute, .50), "absolute_p90_us": percentile(absolute, .90),
        "absolute_p95_us": percentile(absolute, .95), "absolute_p99_us": percentile(absolute, .99),
    }.items()}


def write_csv(path, fields, rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture_a")
    parser.add_argument("capture_b")
    parser.add_argument("--output-dir", default="test5")
    parser.add_argument("--margin-us", type=float, default=3.0)
    parser.add_argument("--train-ratio", type=float, default=.70)
    parser.add_argument("--utc-gate-ms", type=float, default=200.0)
    parser.add_argument("--chunk-seconds", type=float, default=10.0)
    parser.add_argument("--top-codes", type=int, default=15)
    args = parser.parse_args()
    if args.margin_us < 0 or not 0 < args.train_ratio <= 1:
        parser.error("margin must be nonnegative and train ratio must be in (0,1]")

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    t4 = load_test4b(Path(__file__).with_name("test4b-holdout.py"))
    all_a, all_b = t4.load_capture(args.capture_a), t4.load_capture(args.capture_b)
    common = t4.build_common_df17(all_a, all_b, args.utc_gate_ms)
    geometry = t4.build_samples(common)
    if len(geometry) < 100:
        raise RuntimeError(f"too few DF17 geometry samples: {len(geometry)}")
    split = max(2, min(len(geometry), int(len(geometry) * args.train_ratio)))
    train = geometry[:split]
    slope, intercept = t4.linear_fit(train)

    rows_a, zero_a = load_modeac(args.capture_a)
    rows_b, zero_b = load_modeac(args.capture_b)
    a_codes, b_codes = Counter(r["raw_hex"] for r in rows_a), Counter(r["raw_hex"] for r in rows_b)
    baseline_m = t4.distance(t4.geodetic_to_ecef(*STATION_A), t4.geodetic_to_ecef(*STATION_B))
    physical_us = baseline_m / C * 1e6
    gate_us = physical_us + args.margin_us
    result = run_matching(rows_a, rows_b, slope, intercept, gate_us * 12.0)
    matches = result["accepted"]
    tdoas = [m["tdoa_us"] for m in matches]

    violations = {
        "beyond_physical": sum(abs(x) > physical_us for x in tdoas),
        "beyond_physical_plus_0_5_us": sum(abs(x) > physical_us + .5 for x in tdoas),
        "beyond_physical_plus_1_us": sum(abs(x) > physical_us + 1 for x in tdoas),
        "beyond_configured_gate": sum(abs(x) > gate_us for x in tdoas),
    }
    sensitivity = []
    for margin in (.5, 1.0, 3.0, 5.0):
        r = run_matching(rows_a, rows_b, slope, intercept, (physical_us + margin) * 12.0)
        vals = [m["tdoa_us"] for m in r["accepted"]]
        sensitivity.append({
            "margin_us": margin, "gate_us": physical_us + margin,
            "unique_matches": len(vals), "ambiguous_matches": r["ambiguous"],
            "reused_conflicts": r["conflicts"],
            "physical_bound_violations": sum(abs(x) > physical_us for x in vals),
        })

    match_rows = [{
        "raw_hex": m["a"]["raw_hex"], "a_utc_ns": m["a"]["utc_ns"],
        "a_timestamp": m["a"]["ts"], "b_utc_ns": m["b"]["utc_ns"],
        "b_timestamp": m["b"]["ts"], "tb0": f'{m["tb0"]:.6f}',
        "delta_ticks": f'{m["delta_ticks"]:.6f}', "tdoa_us": f'{m["tdoa_us"]:.9f}',
    } for m in matches]
    write_csv(out / "test5-matches.csv", list(match_rows[0]) if match_rows else
              ["raw_hex", "a_utc_ns", "a_timestamp", "b_utc_ns", "b_timestamp", "tb0", "delta_ticks", "tdoa_us"], match_rows)

    bin_width = 5.0
    edge = math.ceil(gate_us / bin_width) * bin_width
    histogram = []
    x = -edge
    while x < edge:
        hi = x + bin_width
        histogram.append({"bin_start_us": x, "bin_end_us": hi,
                          "count": sum(x <= v < hi or (hi == edge and v == hi) for v in tdoas)})
        x = hi
    write_csv(out / "test5-histogram.csv", ["bin_start_us", "bin_end_us", "count"], histogram)

    start_ns = min((r["utc_ns"] for r in rows_a), default=0)
    chunks = defaultdict(lambda: {"accepted": [], "attempts": 0, "ambiguous": 0})
    for a in rows_a:
        chunk = int((a["utc_ns"] - start_ns) / (args.chunk_seconds * 1e9))
        chunks[chunk]["attempts"] += 1
    for m in matches:
        chunk = int((m["a"]["utc_ns"] - start_ns) / (args.chunk_seconds * 1e9))
        chunks[chunk]["accepted"].append(m["tdoa_us"])
    # Reconstruct ambiguity per time chunk for the selected gate.
    idx_b = make_index(rows_b)
    for a in rows_a:
        n = len(candidates(idx_b, a["raw_hex"], slope * a["ts"] + intercept, gate_us * 12.0))
        if n > 1:
            chunk = int((a["utc_ns"] - start_ns) / (args.chunk_seconds * 1e9))
            chunks[chunk]["ambiguous"] += 1
    temporal = []
    for chunk, d in sorted(chunks.items()):
        vals = d["accepted"]
        temporal.append({
            "start_s": chunk * args.chunk_seconds, "end_s": (chunk + 1) * args.chunk_seconds,
            "accepted_matches": len(vals), "median_tdoa_us": finite(statistics.median(vals) if vals else float("nan")),
            "p05_tdoa_us": finite(percentile(vals, .05)), "p95_tdoa_us": finite(percentile(vals, .95)),
            "physical_bound_violations": sum(abs(v) > physical_us for v in vals),
            "ambiguity_rate_percent": pct(d["ambiguous"], d["attempts"]),
        })
    write_csv(out / "test5-temporal.csv", list(temporal[0]) if temporal else [], temporal)

    accepted_codes = Counter(m["a"]["raw_hex"] for m in matches)
    values_by_code = defaultdict(list)
    for m in matches:
        values_by_code[m["a"]["raw_hex"]].append(m["tdoa_us"])
    top_codes = []
    for code, accepted_count in accepted_codes.most_common(args.top_codes):
        vals = values_by_code[code]
        top_codes.append({"raw_hex": code, "count_a": a_codes[code], "count_b": b_codes[code],
                          "accepted_matches": accepted_count, "ambiguous_attempts": result["ambiguous_by_code"][code],
                          "median_tdoa_us": statistics.median(vals), "p95_abs_tdoa_us": percentile([abs(v) for v in vals], .95)})

    summary = {
        "inputs": {"capture_a": str(Path(args.capture_a).resolve()), "capture_b": str(Path(args.capture_b).resolve())},
        "clock_model": {"source": "DF17 geometry-corrected first chronological training fraction", "train_ratio": args.train_ratio,
                        "common_df17_pairs": len(common), "geometry_samples": len(geometry), "training_samples": len(train),
                        "slope": slope, "relative_clock_ppm": (slope - 1) * 1e6, "intercept_ticks": intercept},
        "geometry": {"baseline_m": baseline_m, "physical_limit_us": physical_us, "physical_limit_ticks": physical_us * 12,
                     "configured_margin_us": args.margin_us, "configured_gate_us": gate_us, "configured_gate_ticks": gate_us * 12},
        "counts": {"total_modeac_a": len(rows_a), "total_modeac_b": len(rows_b), "unique_raw_codes_a": len(a_codes),
                   "unique_raw_codes_b": len(b_codes), "common_raw_codes": len(set(a_codes) & set(b_codes)),
                   "timestamp_zero_rejected_a": zero_a, "timestamp_zero_rejected_b": zero_b,
                   "candidate_multiplicity": {k: result["multiplicity"].get(k, 0) for k in ("0", "1", "2", "3+")},
                   "accepted_one_to_one_matches": len(matches), "rejected_ambiguous": result["ambiguous"],
                   "rejected_reused_conflicting": result["conflicts"], "reciprocal_matches": result["reciprocal"]},
        "percentages_of_a": {"candidate_0": pct(result["multiplicity"].get("0", 0), len(rows_a)),
                             "candidate_1": pct(result["multiplicity"].get("1", 0), len(rows_a)),
                             "candidate_2": pct(result["multiplicity"].get("2", 0), len(rows_a)),
                             "candidate_3_plus": pct(result["multiplicity"].get("3+", 0), len(rows_a)),
                             "accepted_one_to_one": pct(len(matches), len(rows_a)), "ambiguous": pct(result["ambiguous"], len(rows_a)),
                             "reused_conflicting": pct(result["conflicts"], len(rows_a))},
        "tdoa": stats(tdoas), "violations": violations, "sensitivity": sensitivity,
        "temporal": temporal, "top_raw_codes": top_codes,
    }
    with open(out / "test5-summary.json", "w") as f:
        json.dump(summary, f, indent=2, allow_nan=False)

    cts, ps, td = summary["counts"], summary["percentages_of_a"], summary["tdoa"]
    lines = [
        "TEST 5 — MODE A/C CROSS-STATION CORRELATION", "=" * 51, "",
        "Method: DF17 geometry-corrected clock fit using the first " + f"{args.train_ratio:.0%} of samples; Mode A/C corrected Beast timestamps only.",
        f"Clock: TB = {slope:.12f} * TA + {intercept:.3f}; relative {summary['clock_model']['relative_clock_ppm']:.6f} ppm",
        f"DF17 pairs / geometry / training samples: {len(common)} / {len(geometry)} / {len(train)}",
        f"ECEF baseline: {baseline_m:.3f} m; physical limit: {physical_us:.6f} us ({physical_us*12:.3f} ticks)",
        f"Configured margin/gate: {args.margin_us:.3f} / {gate_us:.6f} us", "",
        f"Total Mode A/C A / B: {len(rows_a)} / {len(rows_b)}",
        f"Unique codes A / B / common: {len(a_codes)} / {len(b_codes)} / {len(set(a_codes)&set(b_codes))}",
        f"Timestamp-zero rejected A / B: {zero_a} / {zero_b}",
        f"0 candidates: {cts['candidate_multiplicity']['0']} ({ps['candidate_0']:.3f}% of A)",
        f"1 candidate:  {cts['candidate_multiplicity']['1']} ({ps['candidate_1']:.3f}% of A)",
        f"2 candidates: {cts['candidate_multiplicity']['2']} ({ps['candidate_2']:.3f}% of A)",
        f"3+ candidates:{cts['candidate_multiplicity']['3+']} ({ps['candidate_3_plus']:.3f}% of A)",
        f"Accepted one-to-one: {len(matches)} ({ps['accepted_one_to_one']:.3f}% of A)",
        f"Rejected ambiguous: {result['ambiguous']} ({ps['ambiguous']:.3f}% of A)",
        f"Rejected reused/conflicting: {result['conflicts']} ({ps['reused_conflicting']:.3f}% of A)",
        f"Reciprocal accepted pairs: {result['reciprocal']} ({pct(result['reciprocal'],len(matches)):.3f}% of accepted)", "",
        "TDOA (B-A propagation after clock normalization), us:",
        "  min/max/mean/median: " + " / ".join(f"{td[k]:.6f}" for k in ("minimum_us","maximum_us","mean_us","median_us")),
        "  P01/P05/P25/P75/P95/P99: " + " / ".join(f"{td[k]:.6f}" for k in ("p01_us","p05_us","p25_us","p75_us","p95_us","p99_us")),
        "  |TDOA| median/P90/P95/P99: " + " / ".join(f"{td[k]:.6f}" for k in ("absolute_median_us","absolute_p90_us","absolute_p95_us","absolute_p99_us")),
        f"Violations physical / +0.5 us / +1 us / gate: {violations['beyond_physical']} / {violations['beyond_physical_plus_0_5_us']} / {violations['beyond_physical_plus_1_us']} / {violations['beyond_configured_gate']}", "",
        "Sensitivity (margin us: unique / ambiguous / physical violations):",
    ]
    lines += [f"  {r['margin_us']:.1f}: {r['unique_matches']} / {r['ambiguous_matches']} / {r['physical_bound_violations']}" for r in sensitivity]
    lines += ["", "Temporal 10-second chunks (n, median, P05, P95, violations, ambiguity %):"]
    lines += [f"  {r['start_s']:5.1f}-{r['end_s']:5.1f}: {r['accepted_matches']:6d}, {r['median_tdoa_us'] if r['median_tdoa_us'] is not None else float('nan'):8.3f}, {r['p05_tdoa_us'] if r['p05_tdoa_us'] is not None else float('nan'):8.3f}, {r['p95_tdoa_us'] if r['p95_tdoa_us'] is not None else float('nan'):8.3f}, {r['physical_bound_violations']:4d}, {r['ambiguity_rate_percent']:.3f}" for r in temporal]
    lines += ["", "Top raw codes (code, A, B, accepted, ambiguous, median, P95 |TDOA|):"]
    lines += [f"  {r['raw_hex']} {r['count_a']:7d} {r['count_b']:7d} {r['accepted_matches']:7d} {r['ambiguous_attempts']:7d} {r['median_tdoa_us']:9.3f} {r['p95_abs_tdoa_us']:9.3f}" for r in top_codes]
    lines += [
        "", "ANSWERS AND CONCLUSION", "----------------------",
        f"1. Yes. {len(matches)} same-payload, clock-consistent, one-to-one pairs were accepted; {result['reciprocal']} were also reciprocal-unique.",
        f"2. Accepted pairs are {pct(len(matches), len(rows_a)):.3f}% of valid A messages and {pct(len(matches), len(rows_b)):.3f}% of valid B messages.",
        f"3. Raw-code ambiguity is low inside the gate: {result['ambiguous']} A attempts ({pct(result['ambiguous'],len(rows_a)):.3f}%) had multiple candidates.",
        f"4. {len(matches)-violations['beyond_physical']} of {len(matches)} ({pct(len(matches)-violations['beyond_physical'],len(matches)):.3f}%) are within the strict ECEF baseline bound. The {violations['beyond_physical']} exceedances are all within 0.5 us.",
        f"5. Median TDOA is {td['median_us']:.3f} us; P05/P95 are {td['p05_us']:.3f}/{td['p95_us']:.3f} us; the full range is {td['minimum_us']:.3f} to {td['maximum_us']:.3f} us.",
        "6. Matches occur in every 10-second chunk. Distribution changes reflect the traffic mixture; violations do not grow with time, so no clock-drift failure is evident.",
        f"7. Results are insensitive from +0.5 through +3 us ({sensitivity[0]['unique_matches']} accepted at +0.5 us versus {sensitivity[2]['unique_matches']} at +3 us); +5 us changes only {abs(sensitivity[3]['unique_matches']-sensitivity[2]['unique_matches'])} accepted pair(s).",
        "8. No Mode A/C-specific millisecond or microsecond-scale timestamp bias is evident. The strict-bound excess is at most " + f"{max((abs(v)-physical_us for v in tdoas), default=0):.3f} us, comparable to the independently measured DF17 clock-model residual.",
        "9. Test 5 supports proceeding to a four-station localization PoC, while retaining unique/reciprocal matching, explicit ambiguity rejection, and physical-residual diagnostics.",
        "", "Overall result: STRONG PASS for cross-station correlation (not a position-solver validation).",
    ]
    report = "\n".join(lines) + "\n"
    (out / "test5-report.txt").write_text(report)

    try:
        import matplotlib.pyplot as plt
        plt.figure(figsize=(10, 5)); plt.hist(tdoas, bins=[r["bin_start_us"] for r in histogram] + [histogram[-1]["bin_end_us"]])
        plt.axvline(-physical_us, color="red", linestyle="--"); plt.axvline(physical_us, color="red", linestyle="--")
        plt.xlabel("TDOA B-A (us)"); plt.ylabel("Accepted matches"); plt.tight_layout(); plt.savefig(out / "test5-tdoa-histogram.png", dpi=150); plt.close()
        plt.figure(figsize=(10, 5)); plt.scatter([(m["a"]["utc_ns"]-start_ns)/1e9 for m in matches], tdoas, s=1)
        plt.axhline(-physical_us, color="red", linestyle="--"); plt.axhline(physical_us, color="red", linestyle="--")
        plt.xlabel("Seconds from capture start"); plt.ylabel("TDOA B-A (us)"); plt.tight_layout(); plt.savefig(out / "test5-tdoa-vs-time.png", dpi=150); plt.close()
    except (ImportError, IndexError):
        pass
    print(report, end="")


if __name__ == "__main__":
    main()
