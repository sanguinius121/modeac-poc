# Phase 8A — Blind DF17 MLAT validation

**Decision: STRONG PASS**

The immutable Test 7H ten-minute capture was sufficient; no new capture was made. Exact raw DF17 payload, normalized receiver time, reciprocal matching, and physical propagation bounds produced 540 strict 4RX transmissions (9685 3RX and 48879 2RX clusters were retained as yield diagnostics).

Blind results were frozen before truth. Frozen hashes: `{"test8a-blind-candidates-frozen.csv": "c488d1d645ea3d92b628c05b2b0f0c76e40f01d7f77bf7726f04bb589f260c10", "test8a-blind-results-frozen.csv": "31a134f150a1d72f8392ddc5f952e67f50ea9aa5a574a43e40e814221838f2c2"}`. Integrity after post-hoc evaluation: **True**.

## Blind result

Solver classifications: `{'BLIND_UNIQUE': 535, 'BLIND_MULTIPLE': 5}`. Post-hoc truth matches: 529. Horizontal P50/P75/P90/P95/P99/max: 146.12689263793993/274.2559961509266/600.8383087352197/991.5202132404542/1588.3734108986532/2449.241741720069 m. Counts >1/>2/>5/>10 km: 25/2/0/0.

Multiple-candidate branch selection chose the nearest post-hoc truth branch in 529/529 evaluated events. Cross-track absolute error distribution: `{'count': 521, 'p50': 93.75102512421101, 'p75': 166.22524231804695, 'p90': 486.05893920037096, 'p95': 824.8382972123829, 'p99': 1576.2326386497384, 'max': 2421.2848826080904}`.

DF17-altitude-assisted horizontal errors: `{'count': 190, 'p50': 113.4673670922576, 'p75': 184.5406247166847, 'p90': 704.3662168709805, 'p95': 1151.9369491528023, 'p99': 1886.4269251864507, 'max': 2425.5319364776387}`. Unconstrained-3D horizontal errors: `{'count': 529, 'p50': 652.2998586294514, 'p75': 3543.81714351746, 'p90': 15931.409534315644, 'p95': 27110.248818576365, 'p99': 39109.688697822116, 'max': 80925.21608568757}`. These are separate diagnostics and did not alter the blind freeze.

## Clocks, geometry, and latency

All six saved Test 7H clock links and their sample/residual statistics are preserved in `test8a-summary.json`; degraded QK4 links are explicitly propagated as pair weights. Per-event geometry condition, weighted residual, and branch margin are in the frozen result and post-hoc CSVs.

Offline algorithm latency (association / blind solver / total solver milliseconds): `{'count': 540, 'p50': 0.018198974430561066, 'p75': 0.019019702449440956, 'p90': 0.02040686085820198, 'p95': 0.021543493494391438, 'p99': 0.025209682062268264, 'max': 0.06946129724383354}` / `{'count': 540, 'p50': 1122.3480550106615, 'p75': 1195.4167203512043, 'p90': 1243.3283771388233, 'p95': 1267.4674696521834, 'p99': 1337.4311475083232, 'max': 1480.252088047564}` / `{'count': 540, 'p50': 1874.3343220558017, 'p75': 2064.4813670078292, 'p90': 2255.8852629270405, 'p95': 2412.368584633805, 'p99': 2687.0700021646917, 'max': 2843.8458340242505}`. This is CPU processing latency, not display/output latency; no timestamp-valid mutability output was available in this immutable capture for a fair comparison.

## Gate

Phase 8A satisfies independent association, blind solving, freeze-before-truth, meaningful statistics, and anti-leakage requirements. The decision above determines whether Phase 8B may proceed.
