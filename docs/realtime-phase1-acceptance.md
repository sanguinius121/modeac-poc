# Realtime Mode A/C MLAT Phase 1 acceptance

Accepted manually on 2026-08-10 (Asia/Ho_Chi_Minh). The final corrected backend ran from 03:06:12Z through 03:11:22Z: 310 seconds.

## Live result

- All four forwarders connected once and stayed connected: T37 `100.102.185.43:29996`, QK4 `100.119.31.100:29997`, Dao_Cai_chien `100.74.130.53:29998`, and BachLongVi `100.120.90.84:29999`.
- At the 142-second sample, parsed Type-1 rates were T37 1,356.82/s, Dao_Cai_chien 426.62/s, QK4 182.68/s, and BachLongVi 201.93/s. Type-2/3 counters increased continuously. Type-3 counts at that sample were 36,679 / 12,258 / 7,191 / 8,434 respectively.
- Parser errors, reconnects, frame-queue drops, and event-queue drops were all zero.
- All six clock links reached STRONG. At 220 seconds their maximum P95 was 0.509 µs; no discontinuity rejection or model reset occurred. This is better than degraded-QK4 Test 7H/7I, but the backend still weights each live pair independently and does not assume QK4 is always strong.
- The one-second Mode A/C cache remained near 2.1–2.5k entries; frame and localization queues remained at zero. Clock samples were capped and measured 5,465 total at 220 seconds. There was no increasing lag or memory trend.
- Final structured logs recorded 5 `STRICT_4RX` events and 5 `BLIND_UNIQUE` fixes; no `BLIND_MULTIPLE` or `BLIND_INCONSISTENT` fix was observed. The last sampled association diagnostics contained one ambiguous and one inconsistent rejected association.
- Three anonymous tracks existed near the end: MAC-000001 code 4637 reached three fixes/CONFIRMED, then became STALE after its configured gap; its last position was 19.652936, 106.726685 with about 265.3 m/s and heading 156.4 degrees. MAC-000002 code 1014 and MAC-000003 code 1414 each had one tentative fix at 19.629937, 106.735850 and 19.631430, 106.734037. All were LOW/MEDIUM during their short histories, used four receivers, and carried `MODEAC_MLAT_4RX` as their position source.
- Log-derived end-to-end association-to-publication latency for the five fixes was P50 1,022 ms, P90 1,658 ms, and P95 1,850 ms. Four fixes completed near one second; one waited behind another localization and completed in 2,042 ms. Queue depth returned to zero, so lag did not accumulate.
- Observed process CPU was 14.6–16.6%; peak sampled RSS was 67,560 KiB (66.0 MiB).

All five REST endpoints returned valid JSON. A raw RFC6455 client received `101 Switching Protocols`, a snapshot, and a live `track_updated` event with `position_source: MODEAC_MLAT_4RX`.

## Regression and isolation

- The aggregate Tests 6–7I tree hash remained `d0fea2fc25754d7d6df90a21c14d50ad47f11270b820c7c144d424f1684cf21e` before and after implementation.
- The raw Test 7H tree hash remained `a645efd9add55f250cada5c657e35f357a359ebd169002fe6946a0285058d9bb`.
- Production readsb, mlat-server, and tar1090 were active after the run. Ports 30004 and 30104 remained listening and were never opened or altered by this backend.
- The service template was not copied to `/etc/systemd/system`; `modeac-mlat.service` is neither installed nor enabled. The existing `socat-beast.service` state was not changed.
- `python3 -m unittest discover -s tests -v` passed all 10 tests.

## Known issues and Phase 2 decision

The backend remains a PoC: localization costs about one second per event on this host, bursts serialize in the single bounded localization worker, state is memory-only, altitude is deliberately unknown, and repeated Mode A codes plus sparse four-receiver visibility remain fundamental limitations. Track quality should not be presented as ADS-B truth.

Phase 1 is ready for a standalone Phase 2 Leaflet visualization consuming the documented REST/WebSocket interfaces. Operational deployment and any stronger accuracy claim remain separate decisions.
