#!/usr/bin/env python3
"""Capture a scheduled interval from a local Beast TCP stream into validated CSV."""

import argparse
import csv
import json
import socket
import sys
import time
from pathlib import Path

FRAME_LENGTH = {0x31: 9, 0x32: 14, 0x33: 21}  # bytes after type, unescaped
CORRECTION = {0x31: 244, 0x32: 768, 0x33: 768}
KIND = {0x31: "modeac", 0x32: "modes_short", 0x33: "modes_long"}
HEADER = ["station", "recv_utc_ns", "recv_monotonic_ns", "beast_type", "frame_kind",
          "timestamp_raw", "timestamp_corrected", "signal", "raw_hex"]


class BeastParser:
    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while True:
            try:
                start = self.buffer.index(0x1A)
            except ValueError:
                self.buffer.clear()
                break
            if start:
                del self.buffer[:start]
            if len(self.buffer) < 2:
                break
            frame_type = self.buffer[1]
            if frame_type == 0x1A:
                del self.buffer[:2]
                continue
            needed = FRAME_LENGTH.get(frame_type)
            if needed is None:
                del self.buffer[0]
                continue
            decoded = bytearray()
            i = 2
            incomplete = False
            while len(decoded) < needed:
                if i >= len(self.buffer):
                    incomplete = True
                    break
                byte = self.buffer[i]
                if byte == 0x1A:
                    if i + 1 >= len(self.buffer):
                        incomplete = True
                        break
                    if self.buffer[i + 1] != 0x1A:
                        # Truncated/corrupt frame; resynchronize at this marker.
                        del self.buffer[:i]
                        incomplete = True
                        break
                    i += 2
                else:
                    i += 1
                decoded.append(byte)
            if incomplete:
                break
            del self.buffer[:i]
            frames.append((frame_type, bytes(decoded)))
        return frames


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--station", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--start-at-ns", type=int, required=True)
    p.add_argument("--duration", type=float, default=300.0)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=30005)
    args = p.parse_args()
    if args.duration <= 0:
        p.error("duration must be positive")

    while time.time_ns() < args.start_at_ns:
        time.sleep(min(0.25, (args.start_at_ns - time.time_ns()) / 1e9))
    deadline_ns = args.start_at_ns + int(args.duration * 1e9)
    output = Path(args.output)
    parser = BeastParser()
    counts = {"modeac": 0, "modes_short": 0, "modes_long": 0, "timestamp_zero": 0}
    first_utc_ns = last_utc_ns = None

    with socket.create_connection((args.host, args.port), timeout=10) as sock, output.open("x", newline="") as f:
        sock.settimeout(1.0)
        writer = csv.writer(f)
        writer.writerow(HEADER)
        while time.time_ns() < deadline_ns:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                raise RuntimeError("Beast TCP stream closed before capture completed")
            recv_utc_ns, recv_monotonic_ns = time.time_ns(), time.monotonic_ns()
            if first_utc_ns is None:
                first_utc_ns = recv_utc_ns
            last_utc_ns = recv_utc_ns
            for frame_type, payload in parser.feed(chunk):
                timestamp_raw = int.from_bytes(payload[:6], "big")
                timestamp_corrected = 0 if timestamp_raw == 0 else timestamp_raw - CORRECTION[frame_type]
                if timestamp_corrected == 0:
                    counts["timestamp_zero"] += 1
                signal = payload[6]
                raw = payload[7:]
                kind = KIND[frame_type]
                counts[kind] += 1
                writer.writerow([args.station, recv_utc_ns, recv_monotonic_ns, frame_type - 0x30, kind,
                                 timestamp_raw, timestamp_corrected, signal, raw.hex()])
        f.flush()

    result = {"station": args.station, "output": str(output), "scheduled_start_ns": args.start_at_ns,
              "duration_s": args.duration, "first_recv_utc_ns": first_utc_ns, "last_recv_utc_ns": last_utc_ns,
              "counts": counts}
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"capture failed: {exc}", file=sys.stderr)
        raise
