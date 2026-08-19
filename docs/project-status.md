# Mode A/C + Mode-S MLAT PoC — Project Status

Last updated: 2026-08-19

## 1. Project location

Repository:

`/home/mlatserver/modeac-poc`

Git remote:

`git@github.com:sanguinius121/modeac-poc.git`

Main branch:

`main`

---

## 2. Current objective

Dự án xây dựng PoC MLAT/TDOA cho:

- Mode A/C
- Mode-S

Dữ liệu đầu vào là Beast format từ các receiver readsb được forward về central server.

Pipeline tổng quát:

```text
readsb / Beast
    ↓
Beast parser
    ↓
timestamp correction
    ↓
clock synchronization
    ↓
multi-receiver association
    ↓
TDOA
    ↓
2D horizontal localization
    ↓
branch handling
    ↓
Mode-S / Mode A/C tracking
    ↓
REST / WebSocket
    ↓
tar1090 overlay
3. Receiver network
QK3
Name: QK3
Lat: 20.8161575
Lon: 106.6257098
Height: 32 m
Beast port: 29994
MongCai
Name: MongCai
Lat: 21.550206
Lon: 107.938978
Height: 36 m
Beast port: 29995
T37
Name: T37
Lat: 21.485594
Lon: 107.773191
Height: 60 m
Beast port: 29996
QK4
Name: QK4
Lat: 18.760032
Lon: 105.659087
Height: 20 m
Beast port: 29997
CaiChien
Name: Dao_Cai_chien
Lat: 21.320940
Lon: 107.766116
Height: 28 m
Beast port: 29998
BachLongVi
Name: BachLongVi
Lat: 20.132285
Lon: 107.724413
Height: 28 m
Beast port: 29999
Current network size:
6 receivers
Potential 4-of-6 combinations:
C(6,4) = 15
4. Important Beast / timestamp facts
Beast timestamp nominal rate:
12 MHz
Approximate tick duration:
83.333 ns
Message types:
Type 1 = Mode A/C
Type 2 = short Mode-S
Type 3 = long Mode-S
Timestamp corrections currently validated:
Mode A/C Type 1:
T_start = T_F2 - 244 ticks

Mode-S:
timestamp correction = -768 ticks
Do not change these without regression validation.
5. Clock synchronization
DF17 is the validated clock synchronization source.
Current common reference domain:
T37
Clock model maps other receiver timestamps into the T37 time domain.
Important principles:
receiver clock offset and drift must be corrected before TDOA;
physical propagation difference must be removed when fitting clock links;
DF17 position is used for clock calibration/truth validation;
Mode A/C is not used as a clock source.
Current clock quality thresholds:
P95 residual < 1 us  -> STRONG
P95 residual < 5 us  -> PASS
P95 residual < 10 us -> MARGINAL
otherwise            -> BAD
6. Mode A/C association
Mode A/C Type-1 does not provide reliable aircraft identity.
Important rule:
same raw Mode A/C code != same aircraft
Association currently relies on:
raw code candidate
+
normalized timestamp
+
physical propagation gate
+
reciprocal-nearest / uniqueness
Raw Mode A/C code must never be treated as ICAO identity.
Mode A/C localization result is converted into anonymous tracks.
7. Mode-S association
Mode-S association currently preserves:
exact payload matching
+
normalized timing
+
physical propagation bound
+
reciprocal / uniqueness checks
Important supported/observed DFs include:
DF0
DF4
DF5
DF11
DF16
DF17
DF20
DF21
DF17 remains important for clock sync and truth validation.
8. Localization architecture
The validated architecture prefers:
2D horizontal localization + trusted/assumed altitude
rather than unconstrained 3D TDOA.
Reason:
ground receiver vertical geometry is weak compared with horizontal baselines.
Historical validation showed very poor 3D conditioning, while fixed-altitude 2D was much more stable.
Solver outputs are classified into:
BLIND_UNIQUE
MULTIPLE
INCONSISTENT
Blind means ADS-B truth is not used to select the solution branch.
9. Phase 10 roadmap
Phase 10 is the migration from fixed strict-4 to generic 4-of-N.
Sub-phases:
Phase 10A
5RX capture, clock and common reception statistics.
Status:
PASS
Phase 10B
Generic N-RX association.
Status:
PASS
Phase 10C
Offline 4-of-N solver + DF17 truth validation.
Status:
NOT STARTED
Phase 10D
Mode A/C and Mode-S comparative evaluation.
Status:
NOT STARTED
Phase 10E
Realtime shadow mode + performance soak.
Status:
NOT STARTED
Phase 10F
Promotion decision / final acceptance.
Status:
NOT STARTED
10. Phase 10A results
Phase 10A used 5 receivers and demonstrated large common-reception gain.
Important results:
5/5 receivers stable
8/10 clock pairs STRONG
0 PASS/MARGINAL/BAD
2 pairs UNAVAILABLE due insufficient common DF17
T37-MongCai:
samples: 1250
P50: 0.087 us
P95: 0.251 us
quality: STRONG
Common reception:
Mode A/C fixed-4: 0
Mode A/C any-4-of-5: 748

Mode-S fixed-4: 35
Mode-S any-4-of-5: 3766
DF16:
fixed-4: 0
4-of-5: 6
Strongest observed subset:
T37 + CaiChien + BachLongVi + MongCai
Counts in Phase 10A:
Mode A/C: 748
Mode-S: 3730
DF16: 6
Important interpretation:
Phase 10A proves a large reception gain, not yet a localization gain.
11. Phase 10B results
Phase 10B generalized association from fixed-4 to N receivers.
Status:
PASS
Generic data structure:
TransmissionCluster
Fields include:
cluster_id
transmission_key
observations_by_receiver
receiver_ids
normalized_timestamps
metadata
measurement timestamp
association latency
Important behavior:
A 5RX transmission is represented as exactly one cluster:
receiver_count = 5
It is NOT expanded into five 4RX clusters at the association stage.
Duplicate protection:
cluster ID based on exact payload and ordered observation IDs;
one observation can only be consumed once;
duplicate observation IDs rejected;
streaming consumed-ID cache bounded at 100000 entries.
Buffer behavior:
settle timer
max age: 1 second
max payloads: 20000
heap-based expiry
eviction counters
Clock readiness is now receiver-centric:
A receiver does not require all pair clock links to exist.
It only needs a usable mapping into the common T37 time domain.
Fixed-4 regression:
Mode-S 35/35 exact match
Mode A/C 0/0 exact match
Tests:
125/125 PASS
12. Strict-4 realtime pre-test
Before Phase 10C, a realtime strict-4 pre-test was run using:
T37
CaiChien
BachLongVi
MongCai
This quartet is very strong in common reception.
Receiver and clock status:
4/4 receivers stable
reconnect: 0
parse errors: 0
frame drops: 0

6/6 clock pairs STRONG
clock P95 range: 0.143–0.277 us
T37-MongCai:
P50: 0.0488 us
P95: 0.1427 us
Mode A/C:
strict-4 clusters at ~249.5 s: 1201
full-run lower bound: >=1245
Solver snapshot:
107 attempts
88 BLIND_UNIQUE
15 MULTIPLE
4 INCONSISTENT
Mode-S strict-4 enqueue:
3856 events
Strict-4 DF distribution:
DF0: 471
DF4: 248
DF5: 50
DF11: 1103
DF16: 38
DF17: 1562
DF20: 338
DF21: 46
DF16:
38 strict-4
2 solver attempts
2 BLIND_UNIQUE
DF17 truth validation:
51 time-aligned samples

P50 horizontal error: 509 m
P90: 1.435 km
P95: 2.740 km
P99: 6.948 km
No gross wrong branch >25 km was observed in those 51 samples.
13. Current critical issue: realtime throughput
The strict-4 pre-test failed overall because of solver throughput and queue backlog.
Important measurements:
Mode-S:
solver P50: 1.848 s/event
solver P95: 2.648 s/event

queue max: 64
queue drops: >=1471
stale drops: 3261

end-to-end latency P50: 4.708 s
end-to-end latency P95: 5.688 s
Mode A/C:
queue max: 200
drops: >=894

latency P50: 128.6 s
latency P95: 213.4 s
System performance on current 4-core server:
CPU average: 305%
CPU peak: 357%
RSS peak: 215 MiB
This means:
Reception       PASS
Clock           PASS
Association     PASS
Localization    works
Realtime throughput FAIL
The current 4-core server is insufficient for the present sequential/limited-parallel solver workload.
14. Current production state
Production services remain independent:
readsb
mlat-server
tar1090
The PoC must not inject positions back into production Beast/readsb state.
PoC Mode-S and Mode A/C remain separate tar1090 overlays.
After the latest test:
PoC realtime stopped
ports released
production services remained active
15. Current blocker before Phase 10C
DO NOT start Phase 10C yet.
The next engineering task is:
Solver Throughput / Scheduling Optimization
Primary goals:
profile current solver;
identify exact CPU hotspots;
parallelize solve jobs;
improve scheduling/backpressure;
avoid spending CPU on already-stale events;
benchmark 1/2/4/8/16 workers on stronger hardware;
preserve localization math and regression behavior.
Do not change localization mathematics before profiling.
Potential optimization order:
profiling
↓
multi-process worker pool
↓
backpressure / stale-before-solve policy
↓
analytic Jacobian if useful
↓
precompute receiver geometry
↓
reduce allocations
↓
Numba/JIT hot numerical paths
↓
specialized solver experiment
↓
GPU batching only if justified
16. Hardware migration
The original mlatserver host has:
4 CPU cores
The repository has now been pushed to GitHub:
git@github.com:sanguinius121/modeac-poc.git
The next development host should preferably have:
16+ CPU cores
high single-core performance
32–64 GB RAM
GPU is optional at this stage.
CPU parallelization should be benchmarked before investing engineering time in GPU solver execution.
17. Important safety / regression rules
Do not change these without explicit validation:
Beast timestamp correction;
DF17 clock-sync semantics;
Mode A/C raw-code association rules;
Mode-S exact-payload association;
branch semantics;
BLIND_UNIQUE / MULTIPLE / INCONSISTENT definitions;
fixed-altitude 2D localization assumptions;
production readsb/mlat-server data path.
When optimizing performance:
same input -> same localization result within established tolerance
must remain the primary regression requirement.
18. Useful documentation
Important docs include:
docs/phase10-4ofn-plan.md
docs/phase10a-5rx-common-reception.md
docs/phase10a-acceptance.md
docs/phase10b-generic-nrx-association.md
docs/phase10b-acceptance.md
docs/pre10c-strict4-t37-caichien-blv-mongcai.md
docs/pre10c-strict4-t37-caichien-blv-mongcai-acceptance.md
Also inspect relevant historical geometry, solver and planner documents before changing localization behavior.
19. Recommended first task on a new machine
Before modifying code:
clone repo;
recreate Python environment;
run full tests;
run the same strict-4 replay/benchmark;
record baseline solver performance on the new CPU;
only then begin profiling/parallelization.
Recommended benchmark table:
Metric                    Old 4-core     New host
--------------------------------------------------
Mode-S solver P50          1.848 s       ?
Mode-S solver P95          2.648 s       ?
Mode-S queue drops         >=1471        ?
Mode-S stale drops         3261          ?
Mode-S E2E P95             5.688 s       ?
Mode A/C latency P50       128.6 s       ?
Mode A/C latency P95       213.4 s       ?
CPU usage                  305%          ?
RSS                         215 MiB        ?
Do not change code before obtaining this hardware-only baseline.
20. Immediate next step
Current recommended next phase:
Solver Performance Profiling and Parallelization
NOT:
Phase 10C
Phase 10C should begin only after realtime throughput is under control.

Sau khi lưu:

```bash
git add docs/project-status.md
git commit -m "Add current MLAT PoC project status"
git push
