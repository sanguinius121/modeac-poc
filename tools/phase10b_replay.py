#!/usr/bin/env python3
"""Replay Phase 10A through the generic Phase 10B N-RX association core."""

import argparse
import csv
import datetime as dt
import gc
import tempfile
import zlib
import json
import resource
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from realtime.nrx_association import associate_observations
from tools.phase10a_common import (
    BASELINE_SUBSET,
    MODEAC_MARGIN_US,
    MODES_MARGIN_US,
    ORDER,
    STATIONS,
)


REQUIRED_DFS = (0, 4, 5, 11, 16, 17, 20, 21)


def epoch_ns(value):
    return int(dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1e9)


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position); upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def partitioned_family(run, start, end, family, transforms, margin_us, bucket_count=64):
    """Associate exact-payload partitions without changing payload semantics."""
    membership = Counter(); per_df_membership = defaultdict(Counter)
    sizes = Counter(); diagnostics = Counter(); total_observations = 0; latencies = []
    with tempfile.TemporaryDirectory(prefix=f"phase10b-{family}-") as temporary:
        directory = Path(temporary)
        handles = [(directory / f"{index:03d}.csv").open("w", newline="") for index in range(bucket_count)]
        writers = [csv.writer(handle) for handle in handles]
        for writer in writers:
            writer.writerow(("id", "station", "tick", "utc_ns", "raw_hex", "df", "family"))
        try:
            for station in ORDER:
                path = run / "captures" / f"beast-{station}.csv"
                with path.open(newline="") as source:
                    for index, row in enumerate(csv.DictReader(source)):
                        utc_ns = int(row["recv_utc_ns"])
                        if utc_ns < start or utc_ns > end:
                            continue
                        kind = row["frame_kind"]
                        if family == "modeac" and kind != "modeac":
                            continue
                        if family == "modes" and not kind.startswith("modes"):
                            continue
                        if int(row["timestamp_corrected"]) == 0:
                            continue
                        raw_hex = row["raw_hex"].lower()
                        df = int(raw_hex[:2], 16) >> 3 if family == "modes" and raw_hex else ""
                        bucket = zlib.crc32(raw_hex.encode()) % bucket_count
                        writers[bucket].writerow((f"{station}:{index}", station, row["timestamp_corrected"], utc_ns, raw_hex, df, family))
                        total_observations += 1
        finally:
            for handle in handles:
                handle.close()

        for index in range(bucket_count):
            observations = []
            with (directory / f"{index:03d}.csv").open(newline="") as handle:
                for row in csv.DictReader(handle):
                    observations.append({
                        "id": row["id"], "station": row["station"],
                        "tick": int(row["tick"]), "utc_ns": int(row["utc_ns"]),
                        "raw_hex": row["raw_hex"],
                        "df": int(row["df"]) if row["df"] else None,
                        "family": row["family"],
                    })
            result = associate_observations(
                observations, transforms, ORDER, STATIONS, margin_us
            )
            diagnostics.update(result.diagnostics)
            for cluster in result.clusters:
                latencies.append(cluster.association_latency_ms)
                sizes[cluster.receiver_count] += 1
                name = "+".join(cluster.receiver_ids)
                membership[name] += 1
                df = cluster.metadata.get("df")
                if df is not None:
                    per_df_membership[str(df)][name] += 1
            del result, observations
            gc.collect()

    counters = {
        "total_observations": total_observations,
        **{f"{count}RX": sizes[count] for count in range(2, 6)},
        "receiver_membership": dict(sorted(membership.items())),
        "per_df": {},
    }
    for df in REQUIRED_DFS:
        df_membership = per_df_membership[str(df)]
        df_sizes = Counter()
        for name, count in df_membership.items():
            df_sizes[name.count("+") + 1] += count
        counters["per_df"][str(df)] = {
            f"{count}RX": df_sizes[count] for count in range(2, 6)
        }
    by_df = {}
    for df in REQUIRED_DFS:
        values = counters["per_df"][str(df)]
        by_df[str(df)] = {
            **values,
            "memberships": dict(sorted(per_df_membership[str(df)].items())),
        }
    return {
        "counters": counters,
        "diagnostics": dict(diagnostics),
        "cluster_count": sum(counters[f"{count}RX"] for count in range(2, 6)),
        "memberships": dict(sorted(membership.items())),
        "per_df": by_df,
        "partition_buckets": bucket_count,
        "association_latency_ms": {
            "p50": percentile(latencies, 0.5),
            "p95": percentile(latencies, 0.95),
            "maximum": max(latencies, default=None),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("test10b"))
    args = parser.parse_args()
    run = args.run_dir.resolve()
    phase10a = json.loads((run / "reports/phase10a-summary.json").read_text())
    start = epoch_ns(phase10a["analysis_window"]["start_utc"])
    end = epoch_ns(phase10a["analysis_window"]["end_utc"])
    transforms = {
        station: (
            phase10a["timestamp_mapping"][station]["slope"],
            phase10a["timestamp_mapping"][station]["offset_ticks"],
        )
        for station in ORDER
    }
    wall_start = time.perf_counter()
    cpu_start = time.process_time()
    modeac_report = partitioned_family(
        run, start, end, "modeac", transforms, MODEAC_MARGIN_US
    )
    modeac_cluster_count = modeac_report["cluster_count"]
    gc.collect()
    modes_report = partitioned_family(
        run, start, end, "modes", transforms, MODES_MARGIN_US
    )
    modes_cluster_count = modes_report["cluster_count"]
    wall_s = time.perf_counter() - wall_start
    cpu_s = time.process_time() - cpu_start
    baseline_name = "+".join(BASELINE_SUBSET)
    fixed_expected = {
        "modeac": phase10a["modeac"]["baseline_fixed_4rx"],
        "modes_all": phase10a["modes_all"]["baseline_fixed_4rx"],
        "modes_by_df": {
            df: phase10a["modes_by_df"][df]["baseline_fixed_4rx"]
            for df in map(str, REQUIRED_DFS)
        },
    }
    fixed_actual = {
        "modeac": modeac_report["memberships"].get(baseline_name, 0),
        "modes_all": modes_report["memberships"].get(baseline_name, 0),
        "modes_by_df": {
            df: modes_report["per_df"][df]["memberships"].get(baseline_name, 0)
            for df in map(str, REQUIRED_DFS)
        },
    }
    fixed_match = fixed_actual == fixed_expected
    output = {
        "schema": "phase10b-replay-v1",
        "source_run": str(run),
        "analysis_window": phase10a["analysis_window"],
        "receiver_ids": list(ORDER),
        "cluster_semantics": "one N-RX cluster per associated transmission; no quartet enumeration",
        "modeac": modeac_report,
        "modes": modes_report,
        "fixed4_regression": {
            "baseline_membership": baseline_name,
            "expected": fixed_expected,
            "actual": fixed_actual,
            "match": fixed_match,
        },
        "phase10a_comparison": {
            "modeac_old_any4": phase10a["modeac"]["any_4_of_5"],
            "modeac_generic_full_4rx": modeac_report["counters"]["4RX"],
            "modes_old_any4": phase10a["modes_all"]["any_4_of_5"],
            "modes_generic_full_4rx": modes_report["counters"]["4RX"],
        },
        "performance": {
            "wall_s": wall_s,
            "cpu_s": cpu_s,
            "cpu_equivalent_percent": cpu_s / max(wall_s, 1e-9) * 100.0,
            "rss_peak_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "clusters_per_second": (
                modeac_cluster_count + modes_cluster_count
            ) / max(wall_s, 1e-9),
            "queue": "not applicable: bounded offline replay; source capture queue metrics retained in Phase 10A",
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "phase10b-replay.json").write_text(json.dumps(output, indent=2) + "\n")
    rows = []
    for family, report in (("ModeAC", modeac_report), ("ModeS", modes_report)):
        rows.append({"family": family, **{key: report["counters"][key] for key in ("total_observations", "2RX", "3RX", "4RX", "5RX")}})
        if family == "ModeS":
            for df, values in report["per_df"].items():
                rows.append({"family": f"DF{df}", "total_observations": "", **{key: values[key] for key in ("2RX", "3RX", "4RX", "5RX")}})
    with (args.output_dir / "phase10b-cluster-counters.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)
    membership_rows = []
    for family, report in (("ModeAC", modeac_report), ("ModeS", modes_report)):
        for membership, count in report["memberships"].items():
            membership_rows.append({"family": family, "receiver_membership": membership, "count": count})
    with (args.output_dir / "phase10b-memberships.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("family", "receiver_membership", "count"))
        writer.writeheader(); writer.writerows(membership_rows)
    print(json.dumps({"output": str(args.output_dir.resolve()), "fixed4_match": fixed_match, "wall_s": wall_s}))
    if not fixed_match:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
