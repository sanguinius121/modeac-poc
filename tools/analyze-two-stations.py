#!/usr/bin/env python3

import argparse
import csv
import math
import statistics
from collections import Counter, defaultdict
from bisect import bisect_left


BEAST_HZ = 12_000_000.0


def percentile(values, p):
    if not values:
        return float("nan")

    x = sorted(values)

    if len(x) == 1:
        return x[0]

    pos = (len(x) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))

    if lo == hi:
        return x[lo]

    f = pos - lo
    return x[lo] * (1.0 - f) + x[hi] * f


def load_capture(path):
    rows = []
    counts = Counter()

    first_utc = None
    last_utc = None

    with open(path, newline="") as f:
        reader = csv.DictReader(f)

        required = {
            "station",
            "recv_utc_ns",
            "beast_type",
            "frame_kind",
            "timestamp_raw",
            "timestamp_corrected",
            "raw_hex",
        }

        missing = required - set(reader.fieldnames or [])

        if missing:
            raise RuntimeError(
                f"{path}: missing columns: {sorted(missing)}"
            )

        for row in reader:
            station = row["station"]
            recv_utc_ns = int(row["recv_utc_ns"])
            ts = int(row["timestamp_corrected"])
            raw_hex = row["raw_hex"].lower()
            kind = row["frame_kind"]

            if first_utc is None or recv_utc_ns < first_utc:
                first_utc = recv_utc_ns

            if last_utc is None or recv_utc_ns > last_utc:
                last_utc = recv_utc_ns

            counts[kind] += 1

            # Skip pathological timestamp=0 records.
            if ts == 0:
                counts["timestamp_zero"] += 1
                continue

            try:
                raw = bytes.fromhex(raw_hex)
            except ValueError:
                counts["bad_hex"] += 1
                continue

            df = None

            # Mode-S messages only.
            if kind in ("modes_short", "modes_long") and raw:
                df = raw[0] >> 3

            rows.append({
                "station": station,
                "utc_ns": recv_utc_ns,
                "ts": ts,
                "raw_hex": raw_hex,
                "kind": kind,
                "df": df,
            })

    return {
        "path": path,
        "rows": rows,
        "counts": counts,
        "first_utc": first_utc,
        "last_utc": last_utc,
    }


def summarize_capture(cap):
    stations = Counter(r["station"] for r in cap["rows"])

    print(f"File                  : {cap['path']}")
    print(f"Stations              : {dict(stations)}")

    if cap["first_utc"] is not None:
        duration = (
            cap["last_utc"] - cap["first_utc"]
        ) / 1e9
        print(f"UTC capture span      : {duration:.6f} s")

    print(
        f"Mode A/C              : "
        f"{cap['counts']['modeac']}"
    )
    print(
        f"Mode-S short          : "
        f"{cap['counts']['modes_short']}"
    )
    print(
        f"Mode-S long           : "
        f"{cap['counts']['modes_long']}"
    )
    print(
        f"Timestamp zero        : "
        f"{cap['counts']['timestamp_zero']}"
    )

    dfs = Counter(
        r["df"]
        for r in cap["rows"]
        if r["df"] is not None
    )

    print(f"Mode-S DF counts      : {dict(sorted(dfs.items()))}")
    print()


def build_df17_index(cap):
    index = defaultdict(list)

    count = 0

    for r in cap["rows"]:
        if r["kind"] != "modes_long":
            continue

        if r["df"] != 17:
            continue

        index[r["raw_hex"]].append(r)
        count += 1

    for values in index.values():
        values.sort(key=lambda x: x["utc_ns"])

    return index, count


def nearest_by_utc(candidates, target_ns):
    if not candidates:
        return None

    times = [x["utc_ns"] for x in candidates]

    i = bisect_left(times, target_ns)

    choices = []

    if i < len(candidates):
        choices.append(candidates[i])

    if i > 0:
        choices.append(candidates[i - 1])

    if not choices:
        return None

    return min(
        choices,
        key=lambda x: abs(x["utc_ns"] - target_ns),
    )


def pair_common_df17(cap_a, cap_b, utc_gate_ms):
    idx_a, total_a = build_df17_index(cap_a)
    idx_b, total_b = build_df17_index(cap_b)

    common_raw = set(idx_a) & set(idx_b)

    gate_ns = int(utc_gate_ms * 1e6)

    pairs = []

    used_b = set()

    for raw_hex in common_raw:
        for a in idx_a[raw_hex]:

            b = nearest_by_utc(
                idx_b[raw_hex],
                a["utc_ns"],
            )

            if b is None:
                continue

            utc_delta = b["utc_ns"] - a["utc_ns"]

            if abs(utc_delta) > gate_ns:
                continue

            # Prevent one B record pairing repeatedly.
            key_b = (
                b["utc_ns"],
                b["ts"],
                b["raw_hex"],
            )

            if key_b in used_b:
                continue

            used_b.add(key_b)

            pairs.append({
                "raw_hex": raw_hex,
                "a": a,
                "b": b,
                "utc_delta_ns": utc_delta,
            })

    pairs.sort(
        key=lambda p: p["a"]["utc_ns"]
    )

    return pairs, total_a, total_b, len(common_raw)


def linear_fit(pairs):
    """
    Fit:

        y = a*x + b

    where x/y are Beast receiver ticks.

    Values are centered first to avoid numerical precision loss.
    """

    xs = [float(p["a"]["ts"]) for p in pairs]
    ys = [float(p["b"]["ts"]) for p in pairs]

    mx = statistics.mean(xs)
    my = statistics.mean(ys)

    numerator = 0.0
    denominator = 0.0

    for x, y in zip(xs, ys):
        dx = x - mx
        dy = y - my

        numerator += dx * dy
        denominator += dx * dx

    if denominator == 0:
        raise RuntimeError("Cannot fit clock model")

    slope = numerator / denominator
    intercept = my - slope * mx

    return slope, intercept


def residual_ticks(pair, slope, intercept):
    predicted = slope * pair["a"]["ts"] + intercept

    return pair["b"]["ts"] - predicted


def robust_fit(pairs):
    if len(pairs) < 10:
        raise RuntimeError(
            f"Too few common DF17 pairs: {len(pairs)}"
        )

    current = list(pairs)

    # Broad-to-tight rejection.
    thresholds = [
        10000,  # 833 us
        5000,   # 417 us
        2500,   # 208 us
        1500,   # 125 us
    ]

    for threshold in thresholds:

        if len(current) < 10:
            break

        slope, intercept = linear_fit(current)

        residuals = [
            residual_ticks(p, slope, intercept)
            for p in current
        ]

        med = statistics.median(residuals)

        filtered = [
            p
            for p, r in zip(current, residuals)
            if abs(r - med) <= threshold
        ]

        if len(filtered) == len(current):
            continue

        current = filtered

    slope, intercept = linear_fit(current)

    residuals = [
        residual_ticks(p, slope, intercept)
        for p in current
    ]

    return current, slope, intercept, residuals


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("capture_a")
    parser.add_argument("capture_b")

    parser.add_argument(
        "--utc-gate-ms",
        type=float,
        default=200.0,
        help="Coarse UTC pairing gate for identical DF17 frames",
    )

    args = parser.parse_args()

    print("=" * 78)
    print("MODE A/C POC — TWO-STATION CLOCK CORRELATION")
    print("=" * 78)
    print()

    print("Loading captures...")
    print()

    a = load_capture(args.capture_a)
    b = load_capture(args.capture_b)

    print("CAPTURE A")
    print("---------")
    summarize_capture(a)

    print("CAPTURE B")
    print("---------")
    summarize_capture(b)

    overlap_start = max(
        a["first_utc"],
        b["first_utc"],
    )

    overlap_end = min(
        a["last_utc"],
        b["last_utc"],
    )

    overlap_s = (
        overlap_end - overlap_start
    ) / 1e9

    print("UTC OVERLAP")
    print("-----------")
    print(f"Overlap               : {overlap_s:.6f} s")
    print()

    if overlap_s <= 0:
        raise SystemExit(
            "FAIL: captures do not overlap in UTC."
        )

    print("Finding identical DF17 transmissions...")
    print()

    pairs, n17_a, n17_b, common_unique = pair_common_df17(
        a,
        b,
        args.utc_gate_ms,
    )

    print("COMMON DF17")
    print("-----------")
    print(f"DF17 in A             : {n17_a}")
    print(f"DF17 in B             : {n17_b}")
    print(f"Unique raw DF17 common: {common_unique}")
    print(f"Paired transmissions  : {len(pairs)}")
    print(
        f"UTC pairing gate      : "
        f"{args.utc_gate_ms:.1f} ms"
    )
    print()

    if len(pairs) < 10:
        raise SystemExit(
            "FAIL: not enough common DF17 transmissions."
        )

    utc_deltas_ms = [
        p["utc_delta_ns"] / 1e6
        for p in pairs
    ]

    print("COARSE UTC PAIRING")
    print("------------------")
    print(
        f"UTC delta median      : "
        f"{statistics.median(utc_deltas_ms):.3f} ms"
    )
    print(
        f"UTC delta P95 abs     : "
        f"{percentile([abs(x) for x in utc_deltas_ms], 0.95):.3f} ms"
    )
    print()

    inliers, slope, intercept, residuals = robust_fit(pairs)

    relative_ppm = (
        slope - 1.0
    ) * 1e6

    print("ROUGH BEAST CLOCK MODEL")
    print("-----------------------")
    print()
    print("Model:")
    print()
    print(
        "  T_B = slope * T_A + intercept"
    )
    print()

    print(f"Input pairs           : {len(pairs)}")
    print(f"Robust inliers        : {len(inliers)}")
    print(f"Slope                 : {slope:.12f}")
    print(f"Relative clock ppm    : {relative_ppm:.6f}")
    print(f"Intercept ticks       : {intercept:.3f}")
    print()

    abs_res = [
        abs(x)
        for x in residuals
    ]

    print("CLOCK-MODEL RESIDUAL")
    print("--------------------")

    print(
        f"Residual median       : "
        f"{statistics.median(residuals):.3f} ticks"
    )

    print(
        f"|Residual| median     : "
        f"{statistics.median(abs_res):.3f} ticks"
    )

    print(
        f"|Residual| P90        : "
        f"{percentile(abs_res, 0.90):.3f} ticks"
    )

    print(
        f"|Residual| P95        : "
        f"{percentile(abs_res, 0.95):.3f} ticks"
    )

    print(
        f"|Residual| P99        : "
        f"{percentile(abs_res, 0.99):.3f} ticks"
    )

    print()

    print(
        f"|Residual| P95        : "
        f"{percentile(abs_res, 0.95) / BEAST_HZ * 1e6:.3f} us"
    )

    print(
        f"|Residual| P99        : "
        f"{percentile(abs_res, 0.99) / BEAST_HZ * 1e6:.3f} us"
    )

    print()

    print("PHYSICAL BASELINE REFERENCE")
    print("---------------------------")
    print("T37 <-> CaiChien approx distance : 18.32 km")
    print("Max geometric TDOA magnitude     : ~61.1 us")
    print("At 12 MHz                        : ~733 ticks")
    print()

    print("INTERPRETATION")
    print("--------------")

    if len(inliers) >= 50:
        print("[PASS] Enough common DF17 for clock analysis.")
    else:
        print("[WARN] Common DF17 count is relatively low.")

    p95_ticks = percentile(abs_res, 0.95)

    if p95_ticks < 2000:
        print(
            "[PASS] Rough affine clock relationship is coherent."
        )
    else:
        print(
            "[WARN] Large residuals: pairing or clock model needs investigation."
        )

    print()
    print(
        "NOTE: This is only a rough clock-correlation test."
    )
    print(
        "DF17 propagation delay has NOT yet been corrected using decoded"
    )
    print(
        "aircraft position. Therefore these residuals are not yet TDOA errors."
    )

    print()
    print("=" * 78)
    print("END")
    print("=" * 78)


if __name__ == "__main__":
    main()
