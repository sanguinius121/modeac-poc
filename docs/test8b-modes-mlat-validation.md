# Phase 8B — Non-position Mode-S MLAT validation

**Decision: PASS**

Exact-payload, reciprocal, physical-bound clustering produced 649 strict 4RX and 13150 3RX clusters for DF4/5/11/20/21. ICAO was direct for DF11; AP-recovered identities were accepted only when independently present in the capture's DF17 ICAO set.

All Mode-S positions were frozen before post-hoc DF17 trajectory loading. Hash integrity after evaluation: **True**. Frozen hashes: `{"test8b-3rx-alt-results-frozen.csv": "88b9bba1d142a65a8b16c8792dd9e3af0382f269a5258786c954a365c873bb9c", "test8b-4rx-candidates-frozen.csv": "30ca080d6c587a2ff046a736f6fbd793740f0776589302da1bb8586bcca5909d", "test8b-4rx-results-frozen.csv": "c5354fc3d71823b10192da3a0fe9a6749e77d60ad2e3243e6ca140d2b9dd42fe"}`.

## Strict 4RX

Results/classifications/truth matches: 649 / `{'BLIND_UNIQUE': 646, 'BLIND_MULTIPLE': 3}` / 643. Horizontal P50/P75/P90/P95/P99/max: 150.2025508471417/335.9506062665645/982.4867995127983/1323.7219789610913/1876.3671998703412/2671.9226697875492 m. Counts >1/>2/>5/>10 km: 62/5/0/0.

Frozen branch selection was nearest post-hoc truth in 643/643 multiple-candidate events. Message-type yield and accuracy: `{"DF11": {"2rx_clusters": 47434, "3rx_clusters": 9486, "4rx_clusters": 542, "blind_unique": 539, "horizontal_error_m": {"count": 537, "max": 2671.9226697875492, "p50": 152.66985574818386, "p75": 331.2270035782045, "p90": 1048.1300661910263, "p95": 1351.9493401757807, "p99": 1910.5338373926252}, "receiver_observations": 245457, "truth_evaluated": 537}, "DF20": {"2rx_clusters": 17325, "3rx_clusters": 2016, "4rx_clusters": 32, "blind_unique": 32, "horizontal_error_m": {"count": 32, "max": 881.0452576141143, "p50": 113.98729494728032, "p75": 186.8897533917715, "p90": 543.874291197319, "p95": 770.3714668667596, "p99": 873.4168713854119}, "receiver_observations": 92773, "truth_evaluated": 32}, "DF21": {"2rx_clusters": 3014, "3rx_clusters": 421, "4rx_clusters": 15, "blind_unique": 15, "horizontal_error_m": {"count": 15, "max": 1067.9755496005384, "p50": 132.8905093065442, "p75": 588.3133349598339, "p90": 976.1391233815157, "p95": 1025.056884457136, "p99": 1059.391816571858}, "receiver_observations": 16861, "truth_evaluated": 15}, "DF4": {"2rx_clusters": 5095, "3rx_clusters": 1013, "4rx_clusters": 48, "blind_unique": 48, "horizontal_error_m": {"count": 47, "max": 1628.6954359825988, "p50": 144.07326108970003, "p75": 263.55550314002085, "p90": 882.2402515925, "p95": 1026.609367465757, "p99": 1533.7276078440736}, "receiver_observations": 24142, "truth_evaluated": 47}, "DF5": {"2rx_clusters": 1219, "3rx_clusters": 214, "4rx_clusters": 12, "blind_unique": 12, "horizontal_error_m": {"count": 12, "max": 967.7820354524567, "p50": 290.9061362359675, "p75": 403.365690226787, "p90": 867.5695638748606, "p95": 940.9863745817709, "p99": 962.4229032783196}, "receiver_observations": 7010, "truth_evaluated": 12}}`. Highest useful strict-fix yield: **DF11**.

## 3RX + message altitude

Attempted 3029 altitude-bearing events; classifications `{'ALT_3RX_MULTIPLE': 3019, 'ALT_3RX_UNIQUE': 10}`; truth-evaluated horizontal errors `{'count': 3027, 'p50': 41212.14558450303, 'p75': 290773.2332540244, 'p90': 321875.55815527024, 'p95': 410874.95987978316, 'p99': 519770.3518150751, 'max': 705770.0618179314}`. This path remains secondary because three receivers frequently retain multiple horizontal branches.

## Tracks, rates, and latency

Reliable ICAO-linked tracks: 11. Per-aircraft fix rates are in `test8b-icao-tracks.csv` and the JSON summary. Offline 4RX and 3RX solver latency: `{'count': 649, 'p50': 1145.208396948874, 'p75': 1220.1606039889157, 'p90': 1264.3458796665072, 'p95': 1288.4898329153657, 'p99': 1362.9518927633762, 'max': 1465.140949934721}` / `{'count': 3029, 'p50': 105.34310573711991, 'p75': 110.67716404795647, 'p90': 117.68800364807251, 'p95': 132.16407150030136, 'p99': 173.038936387747, 'max': 2646.455219015479}` ms. No timestamp-valid mutability output existed in this immutable dataset, so no unsupported speed claim is made.

## Gate

The decision above controls whether realtime Phase 8C may proceed. Historical Mode A/C behavior is tested separately and was not used or changed by this analysis.
