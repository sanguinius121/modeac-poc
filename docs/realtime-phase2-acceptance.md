# Phase 2 standalone map acceptance

Acceptance date: 2026-08-10. A headless Firefox browser, the standalone frontend server, and the Phase 1 backend ran together for an uninterrupted 600-second interval after a separate reconnect exercise.

## Results

- Frontend: `http://100.100.24.4:8088/`; backend: TCP 8090; four dedicated Beast listeners: 29996–29999.
- A deliberate backend stop/start before the timed interval removed the browser WebSocket and the loaded page automatically reconnected to the replacement backend. WebSocket disconnects during the subsequent timed interval: zero.
- 239 successful four-endpoint API monitor samples; API polling errors: zero.
- Tracks observed: 57 unique track IDs; 15 reached CONFIRMED; 8 reached HIGH quality; maximum simultaneous tracks: 28.
- Seventeen tracks had more than 25 m of sampled position movement. Their visible sequences moved coherently enough to exercise marker reuse and polylines; this is a continuity observation, not an ADS-B accuracy claim.
- Final backend totals were 194 strict four-receiver events, 180 BLIND_UNIQUE, 0 BLIND_MULTIPLE, and 14 BLIND_INCONSISTENT. Current counts legitimately varied as tracks became stale and expired.
- All four receiver indicators stayed connected. All six clock links stayed STRONG during the timed interval.
- Frontend/application errors: zero observed. Firefox emitted headless graphics/telemetry and HTTP/3 ECN warnings, none from application JavaScript. Backend structured exceptions: zero observed. Frame/event queue drops: zero.
- Backend sampled CPU/RSS: 51.2% / 69,468 KiB. Static frontend server: 0.0% / 17,088 KiB. Headless Firefox: 7.6% / 425,076 KiB.
- Backend latency P50/P90/P95 at the final sample was 4.41/14.12/15.65 seconds. Both bounded processing queues were zero at the sample, but burst latency remains a Phase 1 throughput limitation visible in the UI.

## Visual artifacts

- `frontend/phase2-live.png`: early live state with four receivers, clock acquisition warning, stats, and four tracks.
- `frontend/phase2-live-tracks.png`: live state with all six clocks STRONG, receiver/status panels, multiple quality levels, track list, and inferred-position warning.

Both screenshots contain live Mode A/C MLAT output. No mock data or ADS-B truth overlay was used.

## Regression and isolation

- Tests: 14 passed (`python3 -m unittest discover -s tests -v`).
- Tests 6–7I aggregate hash remained `d0fea2fc25754d7d6df90a21c14d50ad47f11270b820c7c144d424f1684cf21e`.
- Raw Test 7H hash remained `a645efd9add55f250cada5c657e35f357a359ebd169002fe6946a0285058d9bb`.
- Production readsb, mlat-server, and tar1090 remained active. No production web files, forwarding services, ports 30004/30104, or scientific algorithms were modified.

## Readiness

The standalone map is ready for PoC operational observation: it makes inferred semantics, quality, clocks, receiver health, lifecycle, and disconnection state explicit. It is not an operational surveillance or separation system.

The interfaces and standalone UI are technically ready to consider a separately scoped Phase 3 tar1090 overlay. Before any operational deployment, address burst localization latency, persistent history, packaging/service supervision, and broader browser testing.
