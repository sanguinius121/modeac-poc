#!/usr/bin/env python3

import argparse
import csv
import math
import statistics
from collections import defaultdict
from bisect import bisect_left

BEAST_HZ = 12_000_000.0
C = 299_792_458.0

STATION_A = {
    "name": "T37",
    "lat": 21.485594,
    "lon": 107.773191,
    "alt_m": 60.0,
}

STATION_B = {
    "name": "Dao_Cai_chien",
    "lat": 21.320940,
    "lon": 107.766116,
    "alt_m": 28.0,
}


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
    return x[lo] * (1 - f) + x[hi] * f


def load_capture(path):
    rows = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            ts = int(row["timestamp_corrected"])

            if ts == 0:
                continue

            try:
                raw = bytes.fromhex(row["raw_hex"])
            except ValueError:
                continue

            kind = row["frame_kind"]

            df = None

            if kind in ("modes_short", "modes_long") and raw:
                df = raw[0] >> 3

            rows.append({
                "station": row["station"],
                "utc_ns": int(row["recv_utc_ns"]),
                "ts": ts,
                "kind": kind,
                "raw": raw,
                "raw_hex": row["raw_hex"].lower(),
                "df": df,
            })

    return rows


def nearest_by_utc(items, target_ns):
    if not items:
        return None

    times = [x["utc_ns"] for x in items]

    i = bisect_left(times, target_ns)

    choices = []

    if i < len(items):
        choices.append(items[i])

    if i > 0:
        choices.append(items[i - 1])

    if not choices:
        return None

    return min(
        choices,
        key=lambda x: abs(x["utc_ns"] - target_ns)
    )


def build_common_df17(rows_a, rows_b, utc_gate_ms):

    idx_a = defaultdict(list)
    idx_b = defaultdict(list)

    for r in rows_a:
        if r["kind"] == "modes_long" and r["df"] == 17:
            idx_a[r["raw_hex"]].append(r)

    for r in rows_b:
        if r["kind"] == "modes_long" and r["df"] == 17:
            idx_b[r["raw_hex"]].append(r)

    for values in idx_a.values():
        values.sort(key=lambda r: r["utc_ns"])

    for values in idx_b.values():
        values.sort(key=lambda r: r["utc_ns"])

    common_raw = set(idx_a) & set(idx_b)

    gate_ns = int(utc_gate_ms * 1e6)

    pairs = []
    used_b = set()

    for raw_hex in common_raw:

        for a in idx_a[raw_hex]:

            b = nearest_by_utc(
                idx_b[raw_hex],
                a["utc_ns"]
            )

            if b is None:
                continue

            if abs(b["utc_ns"] - a["utc_ns"]) > gate_ns:
                continue

            key_b = (
                b["utc_ns"],
                b["ts"],
                raw_hex,
            )

            if key_b in used_b:
                continue

            used_b.add(key_b)

            pairs.append({
                "raw": a["raw"],
                "raw_hex": raw_hex,
                "a": a,
                "b": b,
            })

    pairs.sort(key=lambda x: x["a"]["utc_ns"])

    return pairs


# ==========================================================
# ADS-B / CPR
# ==========================================================

def message_bits(raw):
    return "".join(
        f"{b:08b}"
        for b in raw
    )


def decode_airborne_fields(raw):

    if len(raw) != 14:
        return None

    if (raw[0] >> 3) != 17:
        return None

    bits = message_bits(raw)

    me = bits[32:88]

    tc = int(me[0:5], 2)

    if not (9 <= tc <= 18):
        return None

    altitude_bits = int(
        me[8:20],
        2
    )

    q = altitude_bits & 0x10

    if not q:
        return None

    n = (
        ((altitude_bits & 0x0FE0) >> 1)
        | (altitude_bits & 0x000F)
    )

    altitude_ft = n * 25 - 1000

    odd = int(me[21])

    lat_cpr = int(
        me[22:39],
        2
    )

    lon_cpr = int(
        me[39:56],
        2
    )

    return {
        "icao": raw[1:4].hex(),
        "altitude_ft": altitude_ft,
        "odd": odd,
        "lat_cpr": lat_cpr,
        "lon_cpr": lon_cpr,
    }


def cpr_nl(lat):

    lat = abs(lat)

    if lat < 1e-10:
        return 59

    if lat >= 87:
        if lat > 87:
            return 1
        return 2

    nz = 15.0

    a = 1.0 - math.cos(
        math.pi / (2.0 * nz)
    )

    b = math.cos(
        math.radians(lat)
    ) ** 2

    x = 1.0 - a / b

    x = max(
        -1.0,
        min(1.0, x)
    )

    return int(
        math.floor(
            2.0 * math.pi
            / math.acos(x)
        )
    )


def decode_global_cpr(even, odd, use_odd):

    yz_even = (
        even["lat_cpr"]
        / 131072.0
    )

    yz_odd = (
        odd["lat_cpr"]
        / 131072.0
    )

    j = math.floor(
        59 * yz_even
        - 60 * yz_odd
        + 0.5
    )

    lat_even = (
        360.0 / 60.0
    ) * (
        (j % 60)
        + yz_even
    )

    lat_odd = (
        360.0 / 59.0
    ) * (
        (j % 59)
        + yz_odd
    )

    if lat_even >= 270:
        lat_even -= 360

    if lat_odd >= 270:
        lat_odd -= 360

    if cpr_nl(lat_even) != cpr_nl(lat_odd):
        return None

    if use_odd:
        lat = lat_odd
        nl = cpr_nl(lat)
        ni = max(nl - 1, 1)
    else:
        lat = lat_even
        nl = cpr_nl(lat)
        ni = max(nl, 1)

    x_even = (
        even["lon_cpr"]
        / 131072.0
    )

    x_odd = (
        odd["lon_cpr"]
        / 131072.0
    )

    m = math.floor(
        x_even * (nl - 1)
        - x_odd * nl
        + 0.5
    )

    if use_odd:
        lon = (
            360.0 / ni
        ) * (
            (m % ni)
            + x_odd
        )
    else:
        lon = (
            360.0 / ni
        ) * (
            (m % ni)
            + x_even
        )

    if lon > 180:
        lon -= 360

    if not (-90 <= lat <= 90):
        return None

    if not (-180 <= lon <= 180):
        return None

    return lat, lon


# ==========================================================
# GEODESY
# ==========================================================

def geodetic_to_ecef(lat_deg, lon_deg, alt_m):

    a = 6378137.0
    f = 1.0 / 298.257223563
    e2 = f * (2.0 - f)

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)

    n = a / math.sqrt(
        1.0
        - e2 * sin_lat * sin_lat
    )

    return (
        (n + alt_m)
        * cos_lat
        * math.cos(lon),

        (n + alt_m)
        * cos_lat
        * math.sin(lon),

        (
            n * (1.0 - e2)
            + alt_m
        )
        * sin_lat,
    )


def distance(a, b):
    return math.sqrt(
        (a[0] - b[0]) ** 2
        + (a[1] - b[1]) ** 2
        + (a[2] - b[2]) ** 2
    )


# ==========================================================
# BUILD GEOMETRY SAMPLES
# ==========================================================

def build_samples(common):

    last_even = {}
    last_odd = {}

    station_a = geodetic_to_ecef(
        STATION_A["lat"],
        STATION_A["lon"],
        STATION_A["alt_m"],
    )

    station_b = geodetic_to_ecef(
        STATION_B["lat"],
        STATION_B["lon"],
        STATION_B["alt_m"],
    )

    samples = []

    for pair in common:

        d = decode_airborne_fields(
            pair["raw"]
        )

        if d is None:
            continue

        icao = d["icao"]

        entry = {
            "d": d,
            "pair": pair,
            "utc_ns": pair["a"]["utc_ns"],
        }

        if d["odd"]:
            last_odd[icao] = entry
        else:
            last_even[icao] = entry

        if (
            icao not in last_even
            or icao not in last_odd
        ):
            continue

        even = last_even[icao]
        odd = last_odd[icao]

        age = abs(
            even["utc_ns"]
            - odd["utc_ns"]
        ) / 1e9

        if age > 10.0:
            continue

        use_odd = (
            odd["utc_ns"]
            > even["utc_ns"]
        )

        pos = decode_global_cpr(
            even["d"],
            odd["d"],
            use_odd,
        )

        if pos is None:
            continue

        lat, lon = pos

        if use_odd:
            selected = odd
        else:
            selected = even

        altitude_ft = (
            selected["d"]["altitude_ft"]
        )

        alt_m = (
            altitude_ft
            * 0.3048
        )

        # broad sanity gate
        if not (-10 <= lat <= 45):
            continue

        if not (80 <= lon <= 140):
            continue

        if not (-500 <= alt_m <= 20000):
            continue

        aircraft = geodetic_to_ecef(
            lat,
            lon,
            alt_m,
        )

        da = distance(
            aircraft,
            station_a
        )

        db = distance(
            aircraft,
            station_b
        )

        geom_s = (
            db - da
        ) / C

        geom_ticks = (
            geom_s
            * BEAST_HZ
        )

        ta = selected["pair"]["a"]["ts"]
        tb = selected["pair"]["b"]["ts"]

        if abs(
            geom_s * 1e6
        ) > 62.0:
            continue

        samples.append({
            "utc_ns": selected["utc_ns"],
            "icao": icao,

            "ta": ta,
            "tb": tb,

            "geom_ticks": geom_ticks,
            "geom_us": geom_s * 1e6,

            # Remove RF propagation difference.
            "tb_clock": (
                tb - geom_ticks
            ),
        })

    samples.sort(
        key=lambda x: x["utc_ns"]
    )

    return samples


# ==========================================================
# CLOCK MODEL
# ==========================================================

def linear_fit(samples):

    xs = [
        float(x["ta"])
        for x in samples
    ]

    ys = [
        float(x["tb_clock"])
        for x in samples
    ]

    mx = statistics.mean(xs)
    my = statistics.mean(ys)

    numerator = 0.0
    denominator = 0.0

    for x, y in zip(xs, ys):

        dx = x - mx
        dy = y - my

        numerator += dx * dy
        denominator += dx * dx

    slope = (
        numerator
        / denominator
    )

    intercept = (
        my
        - slope * mx
    )

    return slope, intercept


def residual(sample, slope, intercept):

    predicted_tb = (
        slope * sample["ta"]
        + intercept
        + sample["geom_ticks"]
    )

    return (
        sample["tb"]
        - predicted_tb
    )


def print_stats(title, residuals):

    abs_r = [
        abs(x)
        for x in residuals
    ]

    print()
    print(title)
    print("-" * len(title))

    print(
        f"Samples               : "
        f"{len(residuals)}"
    )

    print(
        f"Residual median       : "
        f"{statistics.median(residuals):.3f} ticks"
    )

    print(
        f"|Residual| median     : "
        f"{statistics.median(abs_r):.3f} ticks"
    )

    print(
        f"|Residual| P90        : "
        f"{percentile(abs_r, 0.90):.3f} ticks"
    )

    print(
        f"|Residual| P95        : "
        f"{percentile(abs_r, 0.95):.3f} ticks"
    )

    print(
        f"|Residual| P99        : "
        f"{percentile(abs_r, 0.99):.3f} ticks"
    )

    print()

    print(
        f"|Residual| median     : "
        f"{statistics.median(abs_r) / BEAST_HZ * 1e6:.3f} us"
    )

    print(
        f"|Residual| P95        : "
        f"{percentile(abs_r, 0.95) / BEAST_HZ * 1e6:.3f} us"
    )

    print(
        f"|Residual| P99        : "
        f"{percentile(abs_r, 0.99) / BEAST_HZ * 1e6:.3f} us"
    )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "capture_a"
    )

    parser.add_argument(
        "capture_b"
    )

    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.70,
    )

    parser.add_argument(
        "--utc-gate-ms",
        type=float,
        default=200.0,
    )

    args = parser.parse_args()

    print("=" * 80)
    print("TEST 4B — OUT-OF-SAMPLE CLOCK VALIDATION")
    print("=" * 80)
    print()

    print(
        f"Train ratio           : "
        f"{args.train_ratio:.2f}"
    )

    print()

    rows_a = load_capture(
        args.capture_a
    )

    rows_b = load_capture(
        args.capture_b
    )

    common = build_common_df17(
        rows_a,
        rows_b,
        args.utc_gate_ms,
    )

    print(
        f"Common DF17 pairs     : "
        f"{len(common)}"
    )

    samples = build_samples(
        common
    )

    print(
        f"Geometry samples      : "
        f"{len(samples)}"
    )

    if len(samples) < 100:
        raise SystemExit(
            "FAIL: too few geometry samples"
        )

    split_index = int(
        len(samples)
        * args.train_ratio
    )

    train = samples[:split_index]
    test = samples[split_index:]

    print()
    print("TIME SPLIT")
    print("----------")

    print(
        f"Train samples         : "
        f"{len(train)}"
    )

    print(
        f"Test samples          : "
        f"{len(test)}"
    )

    train_duration = (
        train[-1]["utc_ns"]
        - train[0]["utc_ns"]
    ) / 1e9

    test_duration = (
        test[-1]["utc_ns"]
        - test[0]["utc_ns"]
    ) / 1e9

    gap = (
        test[0]["utc_ns"]
        - train[-1]["utc_ns"]
    ) / 1e9

    print(
        f"Train time span       : "
        f"{train_duration:.3f} s"
    )

    print(
        f"Test time span        : "
        f"{test_duration:.3f} s"
    )

    print(
        f"Train->test gap       : "
        f"{gap:.6f} s"
    )

    #
    # Fit ONLY on training data.
    #
    slope, intercept = linear_fit(
        train
    )

    ppm = (
        slope - 1.0
    ) * 1e6

    print()
    print("CLOCK MODEL — TRAIN ONLY")
    print("------------------------")

    print(
        "TB = slope * TA + intercept + geometric_delay"
    )

    print()

    print(
        f"Slope                 : "
        f"{slope:.12f}"
    )

    print(
        f"Relative clock ppm    : "
        f"{ppm:.6f}"
    )

    print(
        f"Intercept ticks       : "
        f"{intercept:.3f}"
    )

    train_residuals = [
        residual(
            x,
            slope,
            intercept
        )
        for x in train
    ]

    test_residuals = [
        residual(
            x,
            slope,
            intercept
        )
        for x in test
    ]

    print_stats(
        "TRAIN RESIDUAL",
        train_residuals
    )

    print_stats(
        "HOLD-OUT TEST RESIDUAL",
        test_residuals
    )

    #
    # Examine whether error drifts through test interval.
    #
    if len(test) >= 10:

        chunks = 5
        chunk_size = max(
            len(test) // chunks,
            1
        )

        print()
        print("TEST RESIDUAL OVER TIME")
        print("-----------------------")

        for i in range(chunks):

            start = (
                i * chunk_size
            )

            if i == chunks - 1:
                subset = test[start:]
            else:
                subset = test[
                    start:
                    start + chunk_size
                ]

            if not subset:
                continue

            r = [
                residual(
                    x,
                    slope,
                    intercept
                )
                for x in subset
            ]

            median_ticks = (
                statistics.median(r)
            )

            p95_ticks = percentile(
                [abs(v) for v in r],
                0.95
            )

            print(
                f"Chunk {i+1}: "
                f"n={len(subset):4d} | "
                f"median={median_ticks:+8.3f} ticks | "
                f"P95={p95_ticks:8.3f} ticks | "
                f"P95={p95_ticks / BEAST_HZ * 1e6:7.3f} us"
            )

    test_abs = [
        abs(x)
        for x in test_residuals
    ]

    p95_us = (
        percentile(
            test_abs,
            0.95
        )
        / BEAST_HZ
        * 1e6
    )

    p99_us = (
        percentile(
            test_abs,
            0.99
        )
        / BEAST_HZ
        * 1e6
    )

    print()
    print("=" * 80)
    print("RESULT")
    print("=" * 80)

    if p95_us < 1.0:

        print(
            "STRONG PASS"
        )

        print(
            "Out-of-sample P95 clock error "
            f"is {p95_us:.3f} us."
        )

        print(
            "Clock model is suitable for proceeding "
            "to Mode A/C cross-station correlation."
        )

    elif p95_us < 5.0:

        print(
            "PASS"
        )

        print(
            "Out-of-sample P95 clock error "
            f"is {p95_us:.3f} us."
        )

        print(
            "Proceed to Mode A/C correlation, "
            "but retain conservative timing gates."
        )

    elif p95_us < 10.0:

        print(
            "MARGINAL PASS"
        )

        print(
            "Clock model is usable for PoC, "
            "but clock tracking should be improved."
        )

    else:

        print(
            "INVESTIGATE"
        )

        print(
            "Out-of-sample clock error is too large "
            "for reliable Mode A/C correlation."
        )

    print()
    print(
        f"Hold-out P95          : "
        f"{p95_us:.3f} us"
    )

    print(
        f"Hold-out P99          : "
        f"{p99_us:.3f} us"
    )

    print("=" * 80)


if __name__ == "__main__":
    main()
