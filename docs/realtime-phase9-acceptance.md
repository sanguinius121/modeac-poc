# Phase 9 unified standalone map acceptance

**Decision: PASS for routine PoC observation, with a Mode A/C burst-latency limitation.**

The unified backend, static frontend, and real Firefox 136 page ran together for an uninterrupted 1,800-second monitored interval on 2026-08-10. WebDriver BiDi sampled the page and backend every ten seconds: 180/180 samples succeeded. The backend was deliberately given extra runtime so the final acceptance sample occurred while the page, both WebSockets, and all receivers were live.

## Browser result

- Page REST errors: 0; JavaScript/window errors: 0; invalid track/source messages: 0; subscribed browser error log events: 0.
- Mode A/C WebSocket disconnects: 0; Mode-S WebSocket disconnects: 0.
- Tracks observed: 28 Mode A/C and 22 Mode-S.
- Tracks that reached CONFIRMED: 7 Mode A/C and 20 Mode-S. Tracks that reached HIGH: 3 and 8.
- Maximum simultaneous tracks: 5 Mode A/C and 7 Mode-S.
- Tracks with more than 25 m of browser-observed movement: 12 Mode A/C and 21 Mode-S.
- Automated large-jump flags (over 50 km or over 600 m/s between browser history points): 2 Mode A/C and 11 Mode-S. These are coherence warnings, not truth comparisons; sparse/out-of-order inferred fixes can trigger them.
- Tracks observed reviving after STALE: 3 Mode A/C and 15 Mode-S.
- Both layers were rendered simultaneously with independent namespaces, histories, controls, sockets, source labels, and age opacity. A Firefox-captured live artifact is `frontend/phase9-live.png`.

Firefox parent-process CPU averaged 2.55% (maximum 4.30%). Sampled RSS rose from 368.4 MiB to 409.8 MiB, averaged 380.8 MiB, and remained below 410 MiB. Ten-minute point pruning was active. Thirty minutes cannot prove absence of a long-term leak, but no error or accelerating UI symptom was observed.

## Receivers, clocks, and backend

All four receivers stayed connected with zero reconnects and zero parse errors. Final frame totals were T37 3,387,734; Dao_Cai_chien 1,101,964; QK4 478,298; and BachLongVi 731,943.

All six clock links were acceptable at the final sample: four STRONG and two PASS. Worst P95 was 4.336 microseconds on QK4–BachLongVi. Every link held 2,000 bounded samples, with zero discontinuity rejection and zero reset.

Mode-S final totals were 737 strict 4RX solver events and 733 unique fixes. Its queue high-water was 7/64, final depth was one, and there were zero queue-full or stale drops. Arrival-to-publication P50/P90/P95/P99 was 0.888/1.786/2.274/3.224 seconds. DF11 dominated the received distribution (553,765 observations), followed by DF17 545,880 and DF20 223,969; DF17 remained diagnostic/non-public by default.

Mode A/C final-sample totals were 142 strict events, 87 unique, one multiple, and nine inconsistent results. A late burst had 44 events pending at the exact final sample; the queue subsequently drained to zero before shutdown, reaching 146 strict and 134 unique fixes. That burst raised the later aggregate Mode A/C P95 to 58.7 seconds. This is the existing serialized Mode A/C solver throughput limitation previously seen in Phase 2—not load caused by browser rendering—but it materially affects freshness and must remain visible to operators. No frame or event was dropped.

Backend parent-plus-worker CPU averaged 61.1% of one core and peaked at 327.7% across four cores. Aggregate RSS averaged 206.5 MiB, increased from 202.4 to 209.8 MiB, and remained bounded during the interval.

## Blind co-track observation

The page considered 86 temporally overlapping Mode A/C/Mode-S pairs. The strongest frozen class per pair yielded 3 POSSIBLE and 6 STRONG_COTRACK pairs. Strong relations covered three Mode-S ICAOs:

- `MAC-000007` and `MAC-000009` with `8880AD`: five compatible points each, 157–190 s span, 249–284 m mean separation.
- `MAC-000010` with `888164`: five points, 61.9 s span, 220 m mean separation.
- `MAC-000024`, `MAC-000025`, and `MAC-000027` with `888268`: four to nine points, 14–71 s span, 62–187 m mean separation.

Multiple anonymous Mode A/C fragments can relate to the same ICAO over time; no Mode A/C track was renamed or identified. Results were frozen to `test9/phase9-cotracks-frozen.json`; SHA256 is `295e40dd9257f8f6af10c7aff5b3ebff4715ea48f7ebda7c238c09c28e967802`. No ADS-B/readsb post-hoc validation was performed, so correctness frequency is unknown and thresholds were not truth-tuned.

## Regression and isolation

- All 18 frontend/realtime tests pass.
- Existing `/api/modeac/*` and `/ws/modeac` contracts remain in use; new Mode-S interfaces remain additive.
- Position sources remain exactly `MODEAC_MLAT_4RX` and `MODES_MLAT_4RX`.
- Mode-S 4RX remains enabled; 3RX plus altitude remains disabled; DF17 public MLAT remains false by default.
- Raw/full Test 7H remains `a645efd9add55f250cada5c657e35f357a359ebd169002fe6946a0285058d9bb`; Phase 8 frozen hashes also remain unchanged.
- Production readsb, mlat-server, and tar1090 stayed active; ports 30004/30104 remained listening. No production service, forwarding path, web file, or generated Beast position was modified.
- The PoC backend, frontend, and browser were stopped after verification.

## Explicit questions

1. **Is the map stable enough for routine PoC observation?** Yes. Both layers survived 30 minutes with zero page/API/stream errors. Operators must still interpret position age and the Mode A/C burst-latency warning.
2. **Are Mode-S tracks visually coherent over time?** Often, but not uniformly: 21/22 showed movement, while 11 triggered the conservative large-jump detector. This is a diagnostic observation, not accuracy validation.
3. **Does Mode A/C behave as before Phase 9?** Yes. Anonymous IDs, source, lifecycle, filters, history, and solver output remain unchanged. The known burst queue behavior also remains.
4. **Does rendering both layers cause a performance issue?** No frontend-induced issue was measured: Firefox averaged 2.55% CPU, both WebSockets had zero disconnects, and Mode-S stayed bounded. The separate existing Mode A/C solver did accumulate a late 44-event burst and high latency; rendering was not its cause.
5. **Were strong blind co-tracks observed?** Yes: six strong pairs involving three Mode-S ICAOs, always labelled possible diagnostic relations.
6. **How often were strong co-tracks correct post-hoc?** Unknown. No post-hoc truth evaluation was performed.
7. **Ready for Phase 10 tar1090 overlay?** Technically yes for a separately scoped diagnostic overlay with explicit inferred-source semantics. Address or prominently expose Mode A/C burst freshness before treating the overlay as continuously current. Phase 9 did not implement tar1090 integration.
