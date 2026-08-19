#!/usr/bin/env python3
"""Safely preflight, schedule, collect, and verify the four Test 6 captures."""

import argparse
import csv
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path("/home/mlatserver/modeac-poc")
KEY = Path("/home/mlatserver/.ssh/modeac_test6_ed25519")
CAPTURE_SCRIPT = ROOT / "tools/test6-beast-capture.py"
STATIONS = {
    "T37": "client0125@100.102.185.43",
    "Dao_Cai_chien": "phiyb@100.74.130.53",
    "QK4": "mlat-client-1@100.119.31.100",
    "BachLongVi": "mlat-client-6@100.120.90.84",
}
SSH_OPTS = ["-i", str(KEY), "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"]


def run(command, check=True, timeout=None):
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          check=check, timeout=timeout)


def ssh(host, command, **kwargs):
    return run(["ssh", *SSH_OPTS, host, command], **kwargs)


def preflight(station, host):
    # Read-only checks. The short sample counts Beast frame start markers; escaped 0x1a
    # bytes cannot be followed by ASCII frame types and therefore do not inflate these counts.
    sample = ('import socket,time; s=socket.create_connection(("127.0.0.1",30005),5); '
              's.settimeout(.5); d=b""; end=time.time()+3; '
              'exec("while time.time()<end:\\n try:d+=s.recv(65536)\\n except socket.timeout:pass"); '
              'print(len(d),d.count(bytes((26,49))),d.count(bytes((26,50))),d.count(bytes((26,51))))')
    command = ("set -eu; printf 'ntp='; timedatectl show -p NTPSynchronized --value; "
               "python3 -c 'import socket;s=socket.create_connection((\"127.0.0.1\",30005),5);s.close();print(\"port=ok\")'; "
               "df -Pk . | tail -1; python3 -c " + shlex.quote(sample))
    proc = ssh(host, command, check=False, timeout=20)
    lines = proc.stdout.strip().splitlines()
    result = {"station": station, "host": host, "exit_code": proc.returncode, "output": proc.stdout}
    try:
        result["ntp_synchronized"] = lines[0].strip() == "ntp=yes"
        result["port_listening"] = lines[1].strip() == "port=ok"
        disk = lines[2].split()
        result["disk_available_kb"] = int(disk[3])
        sample_values = [int(x) for x in lines[3].split()]
        result.update({"sample_bytes": sample_values[0], "sample_type1": sample_values[1],
                       "sample_type2": sample_values[2], "sample_type3": sample_values[3]})
    except (IndexError, ValueError):
        result["parse_error"] = True
    result["passed"] = (proc.returncode == 0 and result.get("ntp_synchronized") and
                        result.get("port_listening") and result.get("disk_available_kb", 0) > 1_000_000 and
                        result.get("sample_type1", 0) > 0 and
                        result.get("sample_type2", 0) + result.get("sample_type3", 0) > 0)
    return result


def inspect_csv(path, expected_station):
    counts, stations, first, last, lines = Counter(), Counter(), None, None, 0
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            lines += 1; stations[row["station"]] += 1; counts[row["frame_kind"]] += 1
            if int(row["timestamp_corrected"]) == 0: counts["timestamp_zero"] += 1
            utc = int(row["recv_utc_ns"]); first = utc if first is None else min(first, utc); last = utc if last is None else max(last, utc)
    return {"path": str(path), "size_bytes": path.stat().st_size, "data_lines": lines,
            "stations": dict(stations), "station_valid": set(stations) == {expected_station},
            "first_utc_ns": first, "last_utc_ns": last, "span_s": (last-first)/1e9 if first is not None else 0,
            "counts": dict(counts)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--duration", type=int, default=300)
    p.add_argument("--lead-seconds", type=int, default=120)
    p.add_argument("--run-id")
    args = p.parse_args()
    if not KEY.is_file() or not CAPTURE_SCRIPT.is_file():
        raise SystemExit("dedicated key or capture script missing")
    run_id = args.run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = ROOT / "test6" / run_id
    for sub in ("preflight", "captures", "pairwise", "clusters", "logs", "reports"):
        (run_dir / sub).mkdir(parents=True, exist_ok=False)
    log_path = run_dir / "logs/orchestration.log"
    def log(message):
        stamp = dt.datetime.now(dt.timezone.utc).isoformat()
        with log_path.open("a") as f: f.write(f"{stamp} {message}\n")
        print(message, flush=True)

    log(f"run_id={run_id} preflight_start")
    checks = [preflight(station, host) for station, host in STATIONS.items()]
    (run_dir / "preflight/preflight.json").write_text(json.dumps(checks, indent=2))
    for check in checks: log(f"preflight {check['station']} passed={check['passed']}")
    if not all(x["passed"] for x in checks):
        (run_dir / "preflight/preflight-report.txt").write_text("\n".join(f"{x['station']}: {'PASS' if x['passed'] else 'FAIL'}\n{x['output']}" for x in checks))
        raise SystemExit("preflight failed; capture not started")

    start_ns = time.time_ns() + args.lead_seconds * 1_000_000_000
    scheduled = dt.datetime.fromtimestamp(start_ns / 1e9, dt.timezone.utc).isoformat()
    log(f"scheduled_start={scheduled} duration_s={args.duration}")
    remote = {}
    for station, host in STATIONS.items():
        script = f"modeac-test6-capture-{run_id}.py"
        csv_name = f"modeac-test6-{run_id}-{station}.csv"
        capture_log = f"modeac-test6-{run_id}-{station}.log"
        run(["scp", *SSH_OPTS, str(CAPTURE_SCRIPT), f"{host}:{script}"], timeout=30)
        command = (f"test ! -e {shlex.quote(csv_name)}; nohup python3 {shlex.quote(script)} --station {shlex.quote(station)} "
                   f"--output {shlex.quote(csv_name)} --start-at-ns {start_ns} --duration {args.duration} "
                   f"> {shlex.quote(capture_log)} 2>&1 < /dev/null & echo $!")
        pid = ssh(host, command, timeout=20).stdout.strip()
        remote[station] = {"host": host, "script": script, "csv": csv_name, "log": capture_log, "pid": pid}
        log(f"launched station={station} pid={pid} remote_csv={csv_name}")
    (run_dir / "logs/run-metadata.json").write_text(json.dumps({"run_id": run_id, "scheduled_start_ns": start_ns,
                                                                  "scheduled_start_utc": scheduled, "duration_s": args.duration,
                                                                  "remote": remote}, indent=2))
    wait_s = max(0, (start_ns - time.time_ns()) / 1e9) + args.duration + 10
    log(f"waiting_seconds={wait_s:.1f}")
    time.sleep(wait_s)

    inspections = {}
    for station, info in remote.items():
        host = info["host"]
        status = ssh(host, f"if kill -0 {shlex.quote(info['pid'])} 2>/dev/null; then echo running; else echo finished; fi; tail -20 {shlex.quote(info['log'])}", check=False, timeout=20)
        (run_dir / f"logs/{station}-remote.log").write_text(status.stdout)
        local = run_dir / "captures" / f"modeac-{station}.csv"
        transfer = run(["scp", *SSH_OPTS, f"{host}:{info['csv']}", str(local)], check=False, timeout=120)
        if transfer.returncode != 0:
            log(f"collection_failed station={station} output={transfer.stdout.strip()}")
            continue
        inspections[station] = inspect_csv(local, station)
        log(f"collected station={station} bytes={local.stat().st_size} lines={inspections[station]['data_lines']}")
    common_overlap_s = 0.0
    if len(inspections) == 4:
        common_overlap_s = (min(x["last_utc_ns"] for x in inspections.values()) - max(x["first_utc_ns"] for x in inspections.values())) / 1e9
    verification = {"run_id": run_id, "scheduled_start_ns": start_ns, "scheduled_start_utc": scheduled,
                    "duration_s": args.duration, "stations": inspections, "common_overlap_s": common_overlap_s,
                    "capture_accepted": len(inspections) == 4 and common_overlap_s >= 295 and all(x["station_valid"] for x in inspections.values())}
    (run_dir / "reports/capture-verification.json").write_text(json.dumps(verification, indent=2))
    log(f"common_overlap_s={common_overlap_s:.6f} capture_accepted={verification['capture_accepted']}")
    print(str(run_dir))
    if not verification["capture_accepted"]:
        raise SystemExit("capture verification failed; successful captures preserved")


if __name__ == "__main__":
    main()
