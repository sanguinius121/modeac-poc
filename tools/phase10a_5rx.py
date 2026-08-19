#!/usr/bin/env python3
"""Phase 10A isolated five-receiver Beast capture and common-reception analysis."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
import resource
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from realtime.beast import BeastParser, decode_frame
from tools.phase10a_common import (
    BASELINE_SUBSET,
    MODEAC_MARGIN_US,
    MODES_MARGIN_US,
    ORDER,
    STATIONS,
    SUBSETS,
    calibrate_all,
    load_capture,
    public_family,
    subset_name,
    summarize_family,
    write_csv,
)


HEADER = [
    "station",
    "recv_utc_ns",
    "recv_monotonic_ns",
    "beast_type",
    "frame_kind",
    "timestamp_raw",
    "timestamp_corrected",
    "signal",
    "raw_hex",
]
REQUIRED_DFS = (0, 4, 5, 11, 16, 17, 20, 21)
MAX_DURATION_S = 600.0


def utc_text(timestamp=None):
    value = datetime.fromtimestamp(timestamp or time.time(), timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CaptureSession:
    def __init__(self, run_dir: Path, duration_s: float, queue_size: int):
        self.run_dir = run_dir
        self.duration_s = duration_s
        self.queue_size = queue_size
        self.queue = None
        self.stats = {
            name: {
                "port": station.port,
                "connections": 0,
                "reconnects": 0,
                "disconnects": 0,
                "bytes": 0,
                "frames": 0,
                "type1": 0,
                "type2": 0,
                "type3": 0,
                "timestamp_zero": 0,
                "parse_errors": 0,
                "df": Counter(),
                "first_recv_utc_ns": None,
                "last_recv_utc_ns": None,
            }
            for name, station in STATIONS.items()
        }
        self.servers = []
        self.clients = set()
        self.handler_tasks = set()
        self.stop_event = None
        self.writer_stop = None
        self.all_connected = None
        self.connected_stations = set()
        self.queue_high_water = 0
        self.queue_drops = 0
        self.log_handle = None
        self.files = {}
        self.writers = {}
        self.cpu_samples = []
        self.rss_samples = []

    def log(self, event, **fields):
        record = {"time": utc_text(), "event": event, **fields}
        self.log_handle.write(json.dumps(record, sort_keys=True) + "\n")
        self.log_handle.flush()

    async def handle(self, station, reader, writer):
        stats = self.stats[station]
        if stats["connections"]:
            stats["reconnects"] += 1
        stats["connections"] += 1
        peer = writer.get_extra_info("peername")
        self.clients.add(writer)
        self.connected_stations.add(station)
        if len(self.connected_stations) == len(ORDER):
            self.all_connected.set()
        self.log("receiver_connected", station=station, peer=str(peer))
        parser = BeastParser()
        try:
            while not self.stop_event.is_set():
                data = await reader.read(65536)
                if not data:
                    break
                stats["bytes"] += len(data)
                utc = time.time()
                mono = time.monotonic()
                utc_ns = time.time_ns()
                mono_ns = time.monotonic_ns()
                before = parser.parse_errors
                frames = parser.feed(data)
                stats["parse_errors"] += parser.parse_errors - before
                for typ, raw in frames:
                    frame = decode_frame(station, typ, raw, mono, utc)
                    stats["frames"] += 1
                    stats[f"type{typ - 0x30}"] += 1
                    if frame.timestamp_corrected == 0:
                        stats["timestamp_zero"] += 1
                    if frame.kind.startswith("modes") and frame.payload:
                        stats["df"][str(frame.payload[0] >> 3)] += 1
                    if stats["first_recv_utc_ns"] is None:
                        stats["first_recv_utc_ns"] = utc_ns
                    stats["last_recv_utc_ns"] = utc_ns
                    row = (
                        station,
                        utc_ns,
                        mono_ns,
                        typ - 0x30,
                        frame.kind,
                        frame.timestamp_raw,
                        frame.timestamp_corrected,
                        frame.signal,
                        frame.payload.hex(),
                    )
                    try:
                        self.queue.put_nowait(row)
                        self.queue_high_water = max(self.queue_high_water, self.queue.qsize())
                    except asyncio.QueueFull:
                        self.queue_drops += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.log("receiver_error", station=station, error=str(exc))
        finally:
            stats["disconnects"] += 1
            self.clients.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            self.log("receiver_disconnected", station=station, peer=str(peer))

    def accept(self, station, reader, writer):
        task = asyncio.create_task(self.handle(station, reader, writer))
        self.handler_tasks.add(task)
        task.add_done_callback(self.handler_tasks.discard)

    async def writer_loop(self):
        while not self.writer_stop.is_set() or not self.queue.empty():
            try:
                row = await asyncio.wait_for(self.queue.get(), timeout=0.2)
            except asyncio.TimeoutError:
                continue
            self.writers[row[0]].writerow(row)
            self.queue.task_done()

    async def monitor_loop(self):
        previous_wall = time.monotonic()
        previous_cpu = time.process_time()
        while not self.stop_event.is_set():
            await asyncio.sleep(1.0)
            wall = time.monotonic()
            cpu = time.process_time()
            elapsed = max(wall - previous_wall, 1e-9)
            self.cpu_samples.append((cpu - previous_cpu) / elapsed * 100.0)
            previous_wall, previous_cpu = wall, cpu
            self.rss_samples.append(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

    async def run(self):
        # Python 3.8 binds asyncio primitives to the current loop.  Construct
        # them here, not in __init__ before asyncio.run creates that loop.
        self.queue = asyncio.Queue(maxsize=self.queue_size)
        self.stop_event = asyncio.Event()
        self.writer_stop = asyncio.Event()
        self.all_connected = asyncio.Event()
        captures = self.run_dir / "captures"
        reports = self.run_dir / "reports"
        logs = self.run_dir / "logs"
        for directory in (captures, reports, logs):
            directory.mkdir(parents=True, exist_ok=False)
        self.log_handle = (logs / "capture.jsonl").open("x")
        for station in ORDER:
            handle = (captures / f"beast-{station}.csv").open("x", newline="")
            self.files[station] = handle
            writer = csv.writer(handle)
            writer.writerow(HEADER)
            self.writers[station] = writer

        started_utc = time.time()
        started_mono = time.monotonic()
        self.log("capture_start", duration_s=self.duration_s, pid=os.getpid())
        try:
            for station in ORDER:
                server = await asyncio.start_server(
                    lambda reader, writer, name=station: self.accept(name, reader, writer),
                    "0.0.0.0",
                    STATIONS[station].port,
                )
                self.servers.append(server)
                self.log("listener_started", station=station, port=STATIONS[station].port)
            writer_task = asyncio.create_task(self.writer_loop())
            monitor_task = asyncio.create_task(self.monitor_loop())
            try:
                await asyncio.wait_for(self.all_connected.wait(), timeout=60.0)
                self.log("all_receivers_connected", warmup_s=time.monotonic() - started_mono)
            except asyncio.TimeoutError:
                self.log(
                    "receiver_warmup_timeout",
                    connected=sorted(self.connected_stations),
                    missing=sorted(set(ORDER) - self.connected_stations),
                )
            await asyncio.sleep(self.duration_s)
            self.stop_event.set()
            for server in self.servers:
                server.close()
            await asyncio.gather(*(server.wait_closed() for server in self.servers))
            for client in list(self.clients):
                client.close()
            if self.handler_tasks:
                await asyncio.gather(*list(self.handler_tasks), return_exceptions=True)
            await self.queue.join()
            self.writer_stop.set()
            await writer_task
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
        finally:
            self.stop_event.set()
            for handle in self.files.values():
                handle.flush()
                handle.close()

        ended_utc = time.time()
        overlap_start = max(
            (values["first_recv_utc_ns"] or 2**63) for values in self.stats.values()
        )
        overlap_end = min(
            (values["last_recv_utc_ns"] or 0) for values in self.stats.values()
        )
        overlap_s = max(0.0, (overlap_end - overlap_start) / 1e9)
        station_stats = {}
        for station, values in self.stats.items():
            station_stats[station] = {**values, "df": dict(values["df"])}
        metadata = {
            "schema": "phase10a-capture-v1",
            "started_utc": utc_text(started_utc),
            "ended_utc": utc_text(ended_utc),
            "requested_duration_s": self.duration_s,
            "actual_duration_s": time.monotonic() - started_mono,
            "common_overlap_s": overlap_s,
            "capture_accepted": all(v["frames"] > 0 for v in self.stats.values()) and overlap_s > 0,
            "stations": station_stats,
            "queue": {
                "configured_max": self.queue.maxsize,
                "high_water": self.queue_high_water,
                "final": self.queue.qsize(),
                "dropped": self.queue_drops,
            },
            "process": {
                "cpu_average_percent": (
                    sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else None
                ),
                "cpu_peak_percent": max(self.cpu_samples, default=None),
                "rss_peak_kib": max(self.rss_samples, default=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            },
            "capture_sha256": {
                station: sha256(captures / f"beast-{station}.csv") for station in ORDER
            },
        }
        (reports / "capture-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        self.log("capture_stop", accepted=metadata["capture_accepted"], overlap_s=overlap_s)
        self.log_handle.close()
        return metadata


def flatten_family_row(name, summary):
    return {
        "family": name,
        **{key: value for key, value in public_family(summary).items() if key not in ("subset_counts", "association_diagnostics", "subset_diagnostics")},
    }


def analyze(run_dir: Path):
    reports = run_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    capture = None
    capture_path = reports / "capture-metadata.json"
    if capture_path.exists():
        capture = json.loads(capture_path.read_text())
    records = {
        station: load_capture(run_dir / "captures" / f"beast-{station}.csv")
        for station in ORDER
    }
    analysis_window = None
    if capture is not None:
        window_start_ns = max(
            values["first_recv_utc_ns"] for values in capture["stations"].values()
        )
        window_end_ns = min(
            values["last_recv_utc_ns"] for values in capture["stations"].values()
        )
        records = {
            station: [
                row for row in rows if window_start_ns <= row["utc_ns"] <= window_end_ns
            ]
            for station, rows in records.items()
        }
        analysis_window = {
            "start_utc": utc_text(window_start_ns / 1e9),
            "end_utc": utc_text(window_end_ns / 1e9),
            "duration_s": max(0.0, (window_end_ns - window_start_ns) / 1e9),
            "policy": "intersection of first/last receive timestamps across all five receivers",
        }
    clock_pairs, transforms = calibrate_all(records)
    write_csv(reports / "clock-pairs.csv", clock_pairs)
    missing = [station for station in ORDER if station not in transforms]
    if missing:
        summary = {
            "schema": "phase10a-analysis-v1",
            "analysis_performed": False,
            "reason": "Missing direct DF17 clock model(s) to T37: " + ", ".join(missing),
            "clock_pairs": clock_pairs,
        }
        (reports / "phase10a-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    modeac = [row for values in records.values() for row in values if row["kind"] == "modeac"]
    modes = [row for values in records.values() for row in values if row["kind"].startswith("modes")]
    modeac_summary = summarize_family(modeac, transforms, MODEAC_MARGIN_US)
    modes_summary = summarize_family(modes, transforms, MODES_MARGIN_US)

    dfs = sorted(set(REQUIRED_DFS) | {row["df"] for row in modes if row["df"] is not None})
    df_summaries = {}
    for df in dfs:
        observations = [row for row in modes if row["df"] == df]
        df_summaries[str(df)] = summarize_family(observations, transforms, MODES_MARGIN_US)

    family_rows = [flatten_family_row("ModeAC", modeac_summary), flatten_family_row("ModeS_all", modes_summary)]
    family_rows.extend(flatten_family_row(f"DF{df}", df_summaries[str(df)]) for df in dfs)
    write_csv(reports / "common-reception.csv", family_rows)

    subset_rows = []
    all_summaries = [("ModeAC", modeac_summary), ("ModeS_all", modes_summary)] + [
        (f"DF{df}", df_summaries[str(df)]) for df in dfs
    ]
    for family, family_summary in all_summaries:
        for subset in SUBSETS:
            name = subset_name(subset)
            subset_rows.append(
                {
                    "family": family,
                    "subset": name,
                    "is_current_baseline": subset == BASELINE_SUBSET,
                    "strict_4rx": family_summary["subset_counts"][name],
                }
            )
    write_csv(reports / "subset-counts.csv", subset_rows)

    df16 = public_family(df_summaries["16"])
    summary = {
        "schema": "phase10a-analysis-v1",
        "generated_utc": utc_text(),
        "analysis_performed": True,
        "receiver_order": list(ORDER),
        "clock_reference": "T37",
        "clock_pairs": clock_pairs,
        "timestamp_mapping": {
            station: {"slope": transforms[station][0], "offset_ticks": transforms[station][1]}
            for station in ORDER
        },
        "association": {
            "exact_payload_required": True,
            "normalized_time_required": True,
            "physical_baseline_bound_required": True,
            "reciprocal_nearest_required": True,
            "ambiguity_ticks": 6.0,
            "modeac_margin_us": MODEAC_MARGIN_US,
            "modes_margin_us": MODES_MARGIN_US,
        },
        "modeac": public_family(modeac_summary),
        "modes_all": public_family(modes_summary),
        "modes_by_df": {key: public_family(value) for key, value in df_summaries.items()},
        "df16": df16,
        "capture": capture,
        "analysis_window": analysis_window,
    }
    (reports / "phase10a-summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    mong_pair = next(
        pair for pair in clock_pairs if {pair["station_a"], pair["station_b"]} == {"T37", "MongCai"}
    )
    lines = [
        "PHASE 10A — FIVE-RECEIVER COMMON-RECEPTION DIAGNOSTIC",
        "=" * 61,
        "",
        f"Clock reference: T37; direct timestamp mappings available: {len(transforms)}/5.",
        "T37-MongCai: samples={samples}, P50={p50}, P95={p95} us, quality={quality}, slope={slope}, offset={offset}.".format(
            samples=mong_pair["samples"], p50=mong_pair["p50_us"], p95=mong_pair["p95_us"],
            quality=mong_pair["quality"], slope=mong_pair["slope"], offset=mong_pair["offset_ticks"]
        ),
        "",
        "COMMON RECEPTION",
    ]
    for row in family_rows:
        percent = row["percent_increase"]
        percent_text = f"{percent}%" if percent is not None else "n/a"
        lines.append(
            f"{row['family']}: observations={row['observations']}; 2/3/4/5RX="
            f"{row['two_rx']}/{row['three_rx']}/{row['four_rx']}/{row['five_rx']}; "
            f"baseline={row['baseline_fixed_4rx']}; any4of5={row['any_4_of_5']}; "
            f"increase={row['absolute_increase']} ({percent_text})."
        )
    lines += ["", "DF16 SPECIAL", json.dumps(df16, indent=2), ""]
    (reports / "phase10a-report.txt").write_text("\n".join(lines))
    return summary


def validate_duration(parser, value):
    duration = float(value)
    if duration <= 0 or duration > MAX_DURATION_S:
        parser.error(f"duration must be >0 and <= {MAX_DURATION_S:g} seconds")
    return duration


def default_run_dir():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("test10a") / stamp


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("capture", "run"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--output", type=Path, default=None)
        sub.add_argument("--duration", type=float, default=300.0)
        sub.add_argument("--queue-size", type=int, default=100_000)
    analysis_parser = subparsers.add_parser("analyze")
    analysis_parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    if args.command == "analyze":
        summary = analyze(args.run_dir.resolve())
        print(json.dumps({"analysis_performed": summary["analysis_performed"], "run_dir": str(args.run_dir.resolve())}))
        return

    args.duration = validate_duration(parser, args.duration)
    if args.queue_size <= 0:
        parser.error("queue-size must be positive")
    run_dir = (args.output or default_run_dir()).resolve()
    if run_dir.exists():
        parser.error(f"output already exists: {run_dir}")
    metadata = asyncio.run(CaptureSession(run_dir, args.duration, args.queue_size).run())
    result = {"run_dir": str(run_dir), "capture_accepted": metadata["capture_accepted"]}
    if args.command == "run":
        result["analysis_performed"] = analyze(run_dir)["analysis_performed"]
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
