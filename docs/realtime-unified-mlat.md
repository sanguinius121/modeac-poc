# Realtime unified Mode A/C + Mode-S MLAT

Acceptance date: 2026-08-10 (Asia/Ho_Chi_Minh). Phase 8C was gated on Phase 8A **STRONG PASS** and Phase 8B **PASS**. The accepted unified backend ran uninterrupted for 657.7 seconds on the four existing Beast inputs; no duplicate receiver connection was created.

## Gate evidence

Phase 8A used immutable capture `test7h/20260809T071801Z`. Exact-payload/normalized-time/physical-bound association produced 540 strict four-receiver DF17 transmissions. The blind solver classified 535 unique and five multiple. Post-hoc truth existed for 529 events: horizontal P50/P90/P95/P99 was 146/601/992/1,588 m, no event exceeded 5 km, and the frozen branch was nearest truth in 529/529 evaluations. The frozen result and candidate hashes remain `31a134f150a1d72f8392ddc5f952e67f50ea9aa5a574a43e40e814221838f2c2` and `c488d1d645ea3d92b628c05b2b0f0c76e40f01d7f77bf7726f04bb589f260c10`.

Phase 8B associated 649 strict four-receiver DF4/5/11/20/21 transmissions and obtained truth for 643. Overall horizontal P50/P90/P95/P99 was 150/982/1,324/1,876 m; none exceeded 5 km, and frozen selection was nearest truth in 643/643 evaluations. DF11 supplied 542 of 649 strict events, followed by DF4 48, DF20 32, DF21 15, and DF5 12. The three-receiver altitude diagnostic failed practically: 3,019/3,029 events retained multiple branches and its P50/P95 error was 41/411 km. It is disabled in realtime. Frozen hashes remain `c5354fc3d71823b10192da3a0fe9a6749e77d60ad2e3243e6ca140d2b9dd42fe`, `30ca080d6c587a2ff046a736f6fbd793740f0776589302da1bb8586bcca5909d`, and `88b9bba1d142a65a8b16c8792dd9e3af0382f269a5258786c954a365c873bb9c`.

In both phases, target position/trajectory was loaded only after MLAT CSVs and SHA256 manifests were written. ICAO and message-derived metadata were allowed; ADS-B latitude, longitude, velocity, heading, trajectory, readsb position, and mutability output were excluded from solving.

## Implementation

The original parser/listeners remain the common ingest. Type 1 follows the unchanged Mode A/C association, blind solver, anonymous tracker, REST API, and WebSocket. Type 2/3 is decoded by `realtime.modes`, is also offered to the existing DF17 clock synchronizer, and enters a bounded exact-payload Mode-S associator. AP-recovered identities are accepted only after that ICAO has been observed directly; otherwise the event remains anonymous.

Only strict 4RX DF4/5/11/20/21 events are public by default. Mode-S work uses a bounded 64-event queue, a three-process solver pool on this four-core host, a three-second stale-work policy, and independent ICAO track state/subscribers. This leaves the main process available to Mode A/C. An initial threaded acceptance attempt demonstrated contention (Mode A/C P50/P95 10.9/14.4 s and Mode-S 2.31/8.91 s); it was rejected. The isolated process design below is the accepted result.

Added interfaces are `GET /api/modes/tracks`, `GET /api/modes/stats`, and `/ws/modes`. Existing `/api/modeac/*` and `/ws/modeac` behavior remains compatible. Mode-S outputs declare `MODES_MLAT_4RX`; Mode A/C remains `MODEAC_MLAT_4RX`. `PUBLISH_DF17_MLAT` and `--publish-df17-mlat` default false. No position is injected into Beast/readsb, and the frontend was not redesigned.

## Live acceptance

All four receivers stayed connected without reconnects or parse errors. Final one-minute rates in messages/s were:

| Receiver | Type 1 | Type 2 | Type 3 |
|---|---:|---:|---:|
| T37 | 1,359.8 | 254.9 | 251.4 |
| Dao_Cai_chien | 308.1 | 82.2 | 75.8 |
| QK4 | 237.0 | 47.2 | 75.8 |
| BachLongVi | 221.3 | 50.2 | 47.1 |

All clock links reached STRONG or PASS. Link P95 residuals ranged from 0.142 to 1.866 microseconds, with no discontinuity rejection or reset.

Mode-S produced 1,203 exact four-receiver clusters including diagnostic DF17 clusters. Five hundred non-position clusters entered the realtime solver and 499 produced `BLIND_UNIQUE` fixes. At the final sample, three Mode-S tracks were active and two confirmed. The observed DF totals were DF0 49,343; DF4 28,696; DF5 6,501; DF11 190,904; DF16 7,352; DF17 184,008; DF20 78,976; and DF21 15,378.

Mode A/C produced 48 strict events: 43 unique fixes and five inconsistent solver results. Its original single solver queue and tracker semantics were unchanged.

| Pipeline stage | P50 ms | P90 ms | P95 ms | P99 ms |
|---|---:|---:|---:|---:|
| Mode-S association | 0.042 | 0.077 | 0.095 | 0.137 |
| Mode-S queue | 3.8 | 878.7 | 1,479.0 | 2,573.6 |
| Mode-S solver | 866.2 | 1,157.3 | 1,298.0 | 1,538.4 |
| Mode-S total arrival-to-publication | 883.8 | 2,016.2 | 2,526.0 | 3,629.4 |
| Mode A/C arrival-to-publication | 1,277.1 | 3,974.8 | 4,490.2 | not exposed |

The Mode-S event high-water was 10/64. One event was deliberately dropped stale after three seconds during a burst; no event was dropped because the queue was full. Both event queues and the common frame queue ended empty. The exact-association cache ended at 773 bounded observations. Across 58 resource samples, aggregate parent-plus-three-worker CPU averaged 97.4% of one core (minimum 19.1%, peak 321.0% across four cores). Aggregate RSS averaged 208.1 MiB and peaked at 208.8 MiB.

Both WebSockets returned `101 Switching Protocols` and independent snapshots with the correct position-source labels. The accepted live measurements are preserved in `test8c/live-acceptance.json`.

## Regression and isolation

Seventeen realtime/frontend tests pass. The prior Tests 6–7I aggregate baseline remains `d0fea2fc25754d7d6df90a21c14d50ad47f11270b820c7c144d424f1684cf21e`. The raw/full Test 7H tree recomputed as `a645efd9add55f250cada5c657e35f357a359ebd169002fe6946a0285058d9bb`. Production readsb, mlat-server, and tar1090 remained active; ports 30004/30104 stayed listening. No production program, service, forwarding path, or web file was modified. The PoC listeners and API were released after acceptance.

## Scientific questions

1. **Can blind DF17 be MLATed accurately?** Yes for this dataset: 529 truth comparisons yielded 146/601/992 m P50/P90/P95 without position leakage.
2. **Can non-position replies be localized?** Yes. DF4/5/11/20/21 produced 643 post-hoc comparisons with 150/982/1,324 m P50/P90/P95.
3. **Which DF has the highest useful rate?** DF11 by a wide margin: 542/649 offline strict fixes and the dominant live source. DF20 was second in observation volume but yielded 32 offline strict fixes.
4. **Does 4RX avoid the 3RX branch problem?** Yes in the validated capture: frozen selection was nearest truth in 643/643 non-position evaluations; only 3/649 events were classified multiple.
5. **Is 3RX plus message altitude useful?** No for this geometry/solver. Almost all events remained multiple and errors were unacceptable, so it is disabled.
6. **Measured errors?** Blind DF17: 146/601/992 m P50/P90/P95. Non-position Mode-S: 150/982/1,324 m.
7. **Fix rates per aircraft?** Offline non-position rates ranged 0.10–28.44 fixes/min across 11 ICAOs; the largest were `8881f5` 28.44/min and `888264` 15.34/min. All values are in `test8b/test8b-icao-tracks.csv`.
8. **Is it measurably faster than mutability MLAT?** Not proven. No timestamp-valid mutability output existed for the immutable validation window, so no speed claim is made. The new engine's own measured live P95 was 2.526 s.
9. **Does Mode-S degrade Mode A/C?** The rejected threaded design did. The accepted isolated design reduced Mode A/C P95 to 4.49 s during unified operation, below the earlier standalone Phase 2 observation of 15.65 s, with an empty final queue. Traffic windows differ, so this supports isolation but is not a controlled same-traffic yield comparison.
10. **Ready for a later tar1090 overlay?** Yes as a separate PoC diagnostic layer with explicit source semantics. It is not ready to replace mutability or serve operational surveillance; longer soak tests, controlled side-by-side timestamp capture, and deployment supervision remain future work.
