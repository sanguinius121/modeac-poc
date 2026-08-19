#!/usr/bin/env python3

import argparse
import csv
import math
import statistics
from collections import defaultdict
from bisect import bisect_left

BEAST_HZ = 12_000_000.0
C = 299_792_458.0

# Receiver coordinates
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

    values = sorted(values)

    if len(values) == 1:
        return values[0]

    pos = (len(values) - 1) * p
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))

    if lo == hi:
        return values[lo]

    frac = pos - lo

    return (
        values[lo] * (1.0 - frac)
        + values[hi] * frac
    )


def load_capture(path):
    rows = []

    with open(path, newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:

            ts = int(row["timestamp_corrected"])

            if ts == 0:
                continue

            raw_hex = row["raw_hex"].strip().lower()

            try:
                raw = bytes.fromhex(raw_hex)
            except ValueError:
                continue

            df = None

            if (
                row["frame_kind"] in ("modes_short", "modes_long")
                and raw
            ):
                df = raw[0] >> 3

            rows.append({
                "station": row["station"],
                "utc_ns": int(row["recv_utc_ns"]),
                "ts": ts,
                "kind": row["frame_kind"],
                "raw": raw,
                "raw_hex": raw_hex,
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
        key=lambda x: abs(x["utc_ns"] - target_ns),
    )


def build_common_df17(rows_a, rows_b, utc_gate_ms=200.0):

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

    output = []
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
                b["raw_hex"],
            )

            if key_b in used_b:
                continue

            used_b.add(key_b)

            output.append({
                "raw": a["raw"],
                "raw_hex": raw_hex,
                "a": a,
                "b": b,
            })

    output.sort(key=lambda x: x["a"]["utc_ns"])

    return output


# ============================================================
# ADS-B AIRBORNE POSITION
# ============================================================

def message_bits(raw):
    return "".join(f"{b:08b}" for b in raw)


def decode_airborne_position_fields(raw):

    if len(raw) != 14:
        return None

    if (raw[0] >> 3) != 17:
        return None

    bits = message_bits(raw)

    # ME = bits 33..88 in ADS-B numbering
    me = bits[32:88]

    tc = int(me[0:5], 2)

    # Airborne position:
    # TC 9-18 = barometric altitude
    # TC 20-22 = GNSS height
    #
    # For this PoC use barometric airborne positions only.
    if not (9 <= tc <= 18):
        return None

    altitude_bits = int(me[8:20], 2)

    # Q bit in 12-bit altitude field
    q = altitude_bits & 0x10

    if not q:
        # Gillham / Q=0 decoding deliberately omitted
        # for this first test.
        return None

    n = (
        ((altitude_bits & 0x0FE0) >> 1)
        | (altitude_bits & 0x000F)
    )

    altitude_ft = n * 25 - 1000

    # CPR format:
    # 0 = even
    # 1 = odd
    cpr_format = int(me[21])

    cpr_lat = int(me[22:39], 2)
    cpr_lon = int(me[39:56], 2)

    icao = raw[1:4].hex()

    return {
        "icao": icao,
        "tc": tc,
        "altitude_ft": altitude_ft,
        "odd": cpr_format,
        "lat_cpr": cpr_lat,
        "lon_cpr": cpr_lon,
    }


def cpr_nl(lat):

    lat = abs(lat)

    if lat < 1e-10:
        return 59

    if lat >= 87.0:
        if lat > 87.0:
            return 1
        return 2

    nz = 15.0

    a = 1.0 - math.cos(math.pi / (2.0 * nz))

    b = math.cos(
        math.pi / 180.0 * lat
    ) ** 2

    x = 1.0 - a / b

    # Protect acos against tiny floating point errors.
    x = max(-1.0, min(1.0, x))

    return int(
        math.floor(
            2.0 * math.pi / math.acos(x)
        )
    )


def decode_global_cpr(even, odd, use_odd):

    yz_even = even["lat_cpr"] / 131072.0
    yz_odd = odd["lat_cpr"] / 131072.0

    j = math.floor(
        59.0 * yz_even
        - 60.0 * yz_odd
        + 0.5
    )

    rlat_even = (
        360.0 / 60.0
    ) * (
        (j % 60)
        + yz_even
    )

    rlat_odd = (
        360.0 / 59.0
    ) * (
        (j % 59)
        + yz_odd
    )

    if rlat_even >= 270.0:
        rlat_even -= 360.0

    if rlat_odd >= 270.0:
        rlat_odd -= 360.0

    if cpr_nl(rlat_even) != cpr_nl(rlat_odd):
        return None

    if use_odd:
        lat = rlat_odd
        nl = cpr_nl(lat)
        ni = max(nl - 1, 1)
    else:
        lat = rlat_even
        nl = cpr_nl(lat)
        ni = max(nl, 1)

    x_even = even["lon_cpr"] / 131072.0
    x_odd = odd["lon_cpr"] / 131072.0

    m = math.floor(
        x_even * (nl - 1)
        - x_odd * nl
        + 0.5
    )

    if use_odd:
        lon = (
            360.0 / ni
        ) * (
            (m % ni) + x_odd
        )
    else:
        lon = (
            360.0 / ni
        ) * (
            (m % ni) + x_even
        )

    if lon > 180.0:
        lon -= 360.0

    if not (-90 <= lat <= 90):
        return None

    if not (-180 <= lon <= 180):
        return None

    return lat, lon


# ============================================================
# GEODESY
# ============================================================

def geodetic_to_ecef(lat_deg, lon_deg, alt_m):

    a = 6378137.0
    f = 1.0 / 298.257223563

    e2 = f * (2.0 - f)

    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)

    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)

    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)

    n = a / math.sqrt(
        1.0 - e2 * sin_lat * sin_lat
    )

    x = (n + alt_m) * cos_lat * cos_lon
    y = (n + alt_m) * cos_lat * sin_lon
    z = (
        n * (1.0 - e2) + alt_m
    ) * sin_lat

    return x, y, z


def distance_ecef(a, b):
    return math.sqrt(
        (a[0] - b[0]) ** 2
        + (a[1] - b[1]) ** 2
        + (a[2] - b[2]) ** 2
    )


# ============================================================
# CLOCK FIT
# ============================================================

def linear_fit(samples):

    xs = [float(x["ta"]) for x in samples]
    ys = [float(x["tb_corrected"]) for x in samples]

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
        raise RuntimeError("Degenerate fit")

    slope = numerator / denominator
    intercept = my - slope * mx

    return slope, intercept


def fit_with_rejection(samples):

    current = list(samples)

    thresholds = [
        2000,
        1000,
        500,
        250,
        150,
        100,
    ]

    for threshold in thresholds:

        if len(current) < 20:
            break

        slope, intercept = linear_fit(current)

        residuals = [
            x["tb_corrected"]
            - (
                slope * x["ta"]
                + intercept
            )
            for x in current
        ]

        median = statistics.median(residuals)

        new_current = [
            sample
            for sample, residual
            in zip(current, residuals)
            if abs(residual - median) <= threshold
        ]

        if len(new_current) < 20:
            break

        current = new_current

    slope, intercept = linear_fit(current)

    residuals = [
        x["tb_corrected"]
        - (
            slope * x["ta"]
            + intercept
        )
        for x in current
    ]

    return current, slope, intercept, residuals


def build_geometry_samples(common):

    # Last valid common even/odd message per ICAO.
    last_even = {}
    last_odd = {}

    samples = []

    station_a_ecef = geodetic_to_ecef(
        STATION_A["lat"],
        STATION_A["lon"],
        STATION_A["alt_m"],
    )

    station_b_ecef = geodetic_to_ecef(
        STATION_B["lat"],
        STATION_B["lon"],
        STATION_B["alt_m"],
    )

    airborne_count = 0
    q_valid_count = 0
    cpr_pairs = 0
    position_reject = 0

    for pair in common:

        decoded = decode_airborne_position_fields(
            pair["raw"]
        )

        if decoded is None:
            continue

        airborne_count += 1
        q_valid_count += 1

        icao = decoded["icao"]

        entry = {
            "decoded": decoded,
            "pair": pair,
            "utc_ns": pair["a"]["utc_ns"],
        }

        if decoded["odd"]:
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

        dt = abs(
            even["utc_ns"]
            - odd["utc_ns"]
        ) / 1e9

        # Global airborne CPR pair validity.
        if dt > 10.0:
            continue

        use_odd = (
            odd["utc_ns"]
            > even["utc_ns"]
        )

        position = decode_global_cpr(
            even["decoded"],
            odd["decoded"],
            use_odd,
        )

        if position is None:
            position_reject += 1
            continue

        lat, lon = position

        # Use altitude associated with latest CPR frame.
        if use_odd:
            altitude_ft = odd["decoded"]["altitude_ft"]
            selected_pair = odd["pair"]
        else:
            altitude_ft = even["decoded"]["altitude_ft"]
            selected_pair = even["pair"]

        altitude_m = altitude_ft * 0.3048

        # Basic geographic sanity check for this network.
        #
        # Deliberately broad; only intended to reject impossible
        # global-CPR solutions.
        if not (-10 <= lat <= 45):
            position_reject += 1
            continue

        if not (80 <= lon <= 140):
            position_reject += 1
            continue

        if not (-500 <= altitude_m <= 20000):
            position_reject += 1
            continue

        aircraft_ecef = geodetic_to_ecef(
            lat,
            lon,
            altitude_m,
        )

        da = distance_ecef(
            aircraft_ecef,
            station_a_ecef
        )

        db = distance_ecef(
            aircraft_ecef,
            station_b_ecef
        )

        geometric_seconds = (
            db - da
        ) / C

        geometric_ticks = (
            geometric_seconds * BEAST_HZ
        )

        ta = selected_pair["a"]["ts"]
        tb = selected_pair["b"]["ts"]

        #
        # Model:
        #
        # TB = clock(TA) + geometry
        #
        # Therefore remove propagation geometry from TB
        # before fitting clock relationship.
        #
        tb_corrected = (
            tb - geometric_ticks
        )

        samples.append({
            "icao": icao,
            "lat": lat,
            "lon": lon,
            "altitude_ft": altitude_ft,

            "ta": ta,
            "tb": tb,

            "da_m": da,
            "db_m": db,

            "geom_us": geometric_seconds * 1e6,
            "geom_ticks": geometric_ticks,

            "tb_corrected": tb_corrected,
        })

        cpr_pairs += 1

    return {
        "samples": samples,
        "airborne": airborne_count,
        "q_valid": q_valid_count,
        "cpr_pairs": cpr_pairs,
        "position_reject": position_reject,
    }


def print_residual_statistics(residuals):

    abs_r = [abs(x) for x in residuals]

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

    parser.add_argument("capture_a")
    parser.add_argument("capture_b")

    parser.add_argument(
        "--utc-gate-ms",
        type=float,
        default=200.0,
    )

    args = parser.parse_args()

    print("=" * 80)
    print("TEST 4 — GEOMETRY-CORRECTED DF17 CLOCK MODEL")
    print("=" * 80)
    print()

    print("Loading captures...")

    rows_a = load_capture(args.capture_a)
    rows_b = load_capture(args.capture_b)

    print(
        f"Capture A records     : {len(rows_a)}"
    )

    print(
        f"Capture B records     : {len(rows_b)}"
    )

    print()

    common = build_common_df17(
        rows_a,
        rows_b,
        args.utc_gate_ms,
    )

    print("COMMON DF17")
    print("-----------")

    print(
        f"Paired DF17           : {len(common)}"
    )

    print()

    if len(common) < 100:
        raise SystemExit(
            "FAIL: too few common DF17 messages"
        )

    result = build_geometry_samples(common)

    samples = result["samples"]

    print("ADS-B POSITION DECODING")
    print("-----------------------")

    print(
        f"Airborne-position DF17: "
        f"{result['airborne']}"
    )

    print(
        f"Decoded CPR samples   : "
        f"{len(samples)}"
    )

    print(
        f"Position rejects      : "
        f"{result['position_reject']}"
    )

    print()

    if len(samples) < 30:
        raise SystemExit(
            "FAIL: too few geometry samples"
        )

    unique_aircraft = len(
        set(x["icao"] for x in samples)
    )

    print(
        f"Unique aircraft       : "
        f"{unique_aircraft}"
    )

    geom = [
        x["geom_us"]
        for x in samples
    ]

    print()

    print("GEOMETRIC TDOA")
    print("--------------")

    print(
        f"Minimum               : "
        f"{min(geom):.3f} us"
    )

    print(
        f"Median                : "
        f"{statistics.median(geom):.3f} us"
    )

    print(
        f"Maximum               : "
        f"{max(geom):.3f} us"
    )

    print(
        f"P05                   : "
        f"{percentile(geom, 0.05):.3f} us"
    )

    print(
        f"P95                   : "
        f"{percentile(geom, 0.95):.3f} us"
    )

    print()

    #
    # Sanity:
    # absolute geometry must never exceed station baseline / c.
    #
    bad_geometry = [
        x
        for x in samples
        if abs(x["geom_us"]) > 62.0
    ]

    print(
        f"|Geometry| > 62 us    : "
        f"{len(bad_geometry)}"
    )

    print()

    #
    # Remove any impossible geometry before fitting.
    #
    samples = [
        x
        for x in samples
        if abs(x["geom_us"]) <= 62.0
    ]

    inliers, slope, intercept, residuals = (
        fit_with_rejection(samples)
    )

    relative_ppm = (
        slope - 1.0
    ) * 1e6

    print("GEOMETRY-CORRECTED CLOCK MODEL")
    print("------------------------------")

    print()
    print(
        "TB = slope * TA + intercept + geometric_delay"
    )
    print()

    print(
        f"Input samples         : "
        f"{len(samples)}"
    )

    print(
        f"Robust inliers        : "
        f"{len(inliers)}"
    )

    print(
        f"Slope                 : "
        f"{slope:.12f}"
    )

    print(
        f"Relative clock ppm    : "
        f"{relative_ppm:.6f}"
    )

    print(
        f"Intercept ticks       : "
        f"{intercept:.3f}"
    )

    print()

    print("CLOCK RESIDUAL AFTER GEOMETRY CORRECTION")
    print("----------------------------------------")

    print_residual_statistics(
        residuals
    )

    print()

    #
    # Additional cross-check:
    # compare predicted TB with actual TB including geometry.
    #
    prediction_errors = []

    for x in inliers:

        predicted_tb = (
            slope * x["ta"]
            + intercept
            + x["geom_ticks"]
        )

        error = (
            x["tb"]
            - predicted_tb
        )

        prediction_errors.append(error)

    print()
    print("END-TO-END DF17 TIMESTAMP ERROR")
    print("-------------------------------")

    print_residual_statistics(
        prediction_errors
    )

    print()
    print("SAMPLE DECODED POSITIONS")
    print("------------------------")

    # Print at most ten examples
    step = max(
        len(inliers) // 10,
        1
    )

    shown = 0

    for x in inliers[::step]:

        print(
            f"ICAO {x['icao']} | "
            f"{x['lat']:.5f}, {x['lon']:.5f} | "
            f"{x['altitude_ft']} ft | "
            f"geom {x['geom_us']:+.3f} us"
        )

        shown += 1

        if shown >= 10:
            break

    print()
    print("=" * 80)

    p95_us = (
        percentile(
            [abs(x) for x in residuals],
            0.95
        )
        / BEAST_HZ
        * 1e6
    )

    if len(inliers) >= 100 and p95_us < 10:
        print(
            "RESULT: STRONG PASS — geometry-corrected clock "
            "model is suitable for Mode A/C correlation."
        )

    elif len(inliers) >= 50 and p95_us < 20:
        print(
            "RESULT: PASS — clock model is promising; "
            "continue to Mode A/C correlation."
        )

    else:
        print(
            "RESULT: INVESTIGATE — residual is still too large "
            "for confident Mode A/C correlation."
        )

    print("=" * 80)


if __name__ == "__main__":
    main()
