# Realtime Mode A/C MLAT backend (Phase 1)

## Architecture and isolation

`python3 -m realtime` starts four independent inbound TCP Beast listeners, a bounded frame pipeline, rolling DF17 clock calibration, strict four-receiver Type-1 association, the Test 7I blind altitude-grid solver, anonymous tracking, and a JSON/WebSocket server. It does not connect to receivers, read from port 30004, or depend on central readsb. ADS-B position is used only to remove propagation geometry from DF17 clock samples; ADS-B identity and target truth never enter Mode A/C association, localization, tracking, or quality.

The listener mapping is:

| Station | Input | Coordinates (lat, lon, altitude m) |
|---|---:|---|
| T37 | 29996 | 21.485594, 107.773191, 60 |
| QK4 | 29997 | 18.760032, 105.659087, 20 |
| Dao_Cai_chien | 29998 | 21.320940, 107.766116, 28 |
| BachLongVi | 29999 | 20.132285, 107.724413, 28 |

The API listens on `0.0.0.0:8090`. Production ports 30004 and 30104 are outside this backend.

## Manual startup and shutdown

From `/home/mlatserver/modeac-poc`:

```bash
python3 -m realtime
```

Use Ctrl-C or send SIGTERM for an orderly shutdown. For a timed manual run, use `python3 -m realtime --duration 300`. No third-party web framework is required.

The uninstalled template at `deploy/modeac-mlat.service` can be installed only after an operator approves manual acceptance. Installing, enabling, and starting it are intentionally not part of Phase 1 implementation.

## REST API

- `GET /health` — process uptime, connected receiver count, strict-mode flag.
- `GET /api/receivers` — connection, peer, reconnect, parser, and Type-1/2/3 counters.
- `GET /api/clocks` — all six links with fit, residual percentiles, quality, and age.
- `GET /api/modeac/tracks` — inferred tracks; optional `?min_quality=HIGH` (also LOW/MEDIUM).
- `GET /api/modeac/stats` — rolling rates, cumulative classifications, latency, drops, and bounded-buffer depths.

Every public position contains `position_source: "MODEAC_MLAT_4RX"`. Altitude is null with `altitude_source: "unknown"`; a Gillham-decoded value is only exposed as an interpretation candidate.

## WebSocket protocol

Connect to `ws://HOST:8090/ws/modeac`. The first message is `{"type":"snapshot","tracks":[...]}`. Later messages are `track_created`, `track_updated`, `track_state_changed`, `track_stale`, or `track_removed`, with the current public track in `track`. Messages are sent only for valid position or lifecycle changes.

## Clock synchronization and quality

Long Mode-S DF17 copies are paired within the validated 200 ms arrival gate, decoded, and geographically propagation-corrected solely to estimate receiver clocks. Linear rolling fits contain at most 2,000 samples per link. Isolated observations more than 100 µs from an established model are rejected; three consecutive discontinuities reset that link so a real receiver-clock restart can reacquire. A link is `UNAVAILABLE` before 100 samples; afterward absolute residual P95 gives `STRONG` below 1 µs, `PASS` below 5 µs, `MARGINAL` below 10 µs, and `BAD` otherwise. Pair-specific P95 (with a 1 µs floor) weights localization, so degraded QK4 timing is not silently treated as precise.

## Association, localization, and bounded state

Type-1 timestamp correction is `T_F2 - 244` Beast ticks; Type-2/3 correction is 768 ticks. Association requires the identical raw pulse word, all four stations, physical baseline bounds plus the configured timing margin, reciprocal nearest matches, and multi-baseline consistency. Only `STRICT_4RX` reaches the blind solver. Ambiguous and inconsistent cases remain counters.

The solver evaluates 0–45,000 ft in 5,000 ft bands, groups nearby branches, uses all six weighted residuals, checks an expanded search region, and returns `BLIND_UNIQUE`, `BLIND_MULTIPLE`, or `BLIND_INCONSISTENT`. Only unique positions reach tracking.

The frame queue is capped at 50,000, the localization queue at 200, each Mode A/C code/station deque at 4,000, each clock link at 2,000 samples, latency at 5,000 values, and each WebSocket subscriber at 1,000 events. Full queues drop new work and increment diagnostic counters.

## Track lifecycle and quality

Tracks use a Mode A display code plus constant-velocity prediction, a 450 m/s hard gate, spatial allowance, and a 120-second maximum gap; code equality alone cannot merge distant targets. A new track is `TENTATIVE`, becomes `CONFIRMED` after three fixes, becomes `STALE` after 30 seconds, and is removed as expired after 120 seconds.

Track quality is `LOW`, `MEDIUM`, or `HIGH`, based on fix count, weighted residual, and clock quality. Current Phase 1 limitations are anonymous repeated-code ambiguity, altitude-band ambiguity, sparse four-station common visibility, receiver-clock degradation (especially QK4), in-memory-only state, and no frontend or persistent history.

## Tests

Run `python3 -m unittest discover -s tests -v`. The suite covers Beast chunking/escaping, receiver reconnect and bounded input, strict association, branch rejection, lifecycle, same-code separation, WebSocket serialization, and API schemas.
