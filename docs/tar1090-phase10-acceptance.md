# tar1090 Phase 10 acceptance

## Overall result

**BLOCKED at the production Phase 10A deployment gate.**

The REST-only overlay passed a 900-second production-faithful staged-browser soak using the exact installed tar1090 assets, live production readsb JSON, and the live four-receiver PoC backend. It was not written into `/usr/local/share/tar1090/html` because that directory is root-owned and the automation account's sudo requires an interactive password. The production index remains byte-identical to the verified original backup.

Following the task's explicit phase gate, Phase 10B and Phase 10C were not started. This report does not claim a full Phase 10 PASS.

## Phase results

- Phase 10A implementation: PASS in staged webroot; production acceptance BLOCKED pending the prepared sudo deployment.
- Phase 10B WebSockets: NOT STARTED; gated on production Phase 10A.
- Phase 10C comparison diagnostics: NOT STARTED; gated on Phase 10B.
- Full 10A–10C production soak: NOT RUN.

The staged Phase 10A soak artifact is `test10/phase10a-soak.json`; screenshots are in `test10/phase10a-staged-after-soak.png` and `test10/phase10a-staged.png`.

## Phase 10A soak evidence

- Duration: 900 seconds, 90 samples at ten-second intervals
- Monitor errors: 0
- Overlay REST errors: 0
- Invalid track payloads: 0
- Out-of-order update drops: 0
- Browser error/fatal events: 0
- Production aircraft count: 77–88 (mean 82.84)
- Production aircraft with positions: 73–84 (mean 78.24)
- Maximum simultaneous PoC Mode A/C registry: 13
- Maximum simultaneous PoC Mode-S registry: 6
- Maximum Mode A/C trail points: 22
- Maximum Mode-S trail points: 121
- Four receivers connected throughout: yes
- Receiver reconnects: 0
- Receiver parser errors: 0
- Mode A/C frame/event queue high-water observed: 0 / 0
- Mode-S event queue high-water: 8; sampled current depth maximum: 5; final depth: 0
- Mode A/C queue drops: 0
- Mode-S stale event drops: 1 at first sample, 2 at final sample
- Firefox CPU: mean 4.65%, maximum 54.56%
- Firefox RSS: 321.69–430.63 MiB; first 405.41 MiB, final 365.29 MiB
- Backend CPU: mean 53.64%, burst maximum 307.73% across the parent and three solver workers
- Backend RSS: 210.50–212.54 MiB

There was no monotonic frontend-memory growth across the soak. This is a staged observation rather than a before/after production-overlay performance comparison.

## Measurement-age validation

The overlay derives position age from `last_seen`, never REST receipt time. It recorded delayed-at-ingest examples including:

- `MAC-000001`: 50.939 seconds old at browser receipt
- `MAC-000003`: 61.098 seconds old at browser receipt
- `MAC-000004`: 71.199 seconds old at browser receipt
- `MS-88820F`: 87.763 seconds old at browser receipt

At the final sample, the oldest displayed Mode-S measurement was 72.564 seconds old while the newest REST receipt was 1.450 seconds old. This directly validates the required `Last seen` versus `Received` distinction.

## Clock behavior

All six clock links began in `PASS` or `STRONG`. During the soak one degradation transition occurred; the final state was three `STRONG`, one `PASS`, one `MARGINAL`, and one `BAD` link. The UI immediately and visibly reported:

```text
Clock: 4 / 6 OK
PoC MLAT CLOCK DEGRADED
```

The degradation was not hidden or used by the frontend to alter any backend result.

## Production status

At the end of the soak:

- `readsb.service`: active/running, restart count 0
- `mlat-server.service`: active/running, restart count 0
- `tar1090.service`: active/running, restart count 0
- `lighttpd.service`: active/running, restart count 0
- TCP 30004: listening on IPv4 and IPv6
- TCP 30104: listening on IPv4 and IPv6
- Production warning-or-higher journal entries during the soak: 0
- Production index SHA256: `1c616be3ca30ada8aa25bb7bcb5bdc0f4ad956b50985563365e258f38de65e59` (unchanged original)

No Beast output, readsb input, mlat-server input, `socat-beast.service`, receiver mapping, or station path was changed.

## Files and hashes

Production tar1090 files modified: **none yet**.

Reviewed deployment targets:

| Target | Original SHA256 | Reviewed Phase 10A SHA256 |
|---|---|---|
| `/usr/local/share/tar1090/html/index.html` | `1c616be3ca30ada8aa25bb7bcb5bdc0f4ad956b50985563365e258f38de65e59` | `20a0c5d6eee17218866f0923aadb6838a597038f5138daeddde64becc51f11ae` |
| `/usr/local/share/tar1090/html/poc-mlat-overlay.js` | new | `49cc4367c503ccd03109897bbb112c81160d7a7a7c575143109a966aa97a8cd2` |
| `/usr/local/share/tar1090/html/poc-mlat-overlay.css` | new | `e8e6c8f8683d44fdc7b6ffeee07202cd54195faa607825597123c8cc44578688` |
| `/home/mlatserver/modeac-poc/realtime/api.py` | `8b16731a08d0af80baecd8c89fbf96ce396a8044485ed6442b3c4aae34faf354` | `cd8041d07a8673eca9566c740690ef7ad60abd9948934718c2d9d05629549b5d` |

The CORS edit is limited to allowing the known tar1090 and staged origins. It changes no synchronization, association, solver, tracking, or publication logic.

## Regression checks

- Existing plus Phase 10 contract tests: 22/22 passing
- 3RX plus altitude publication: still disabled (`three_rx_alt` total 0)
- DF17 MLAT publication: still disabled by default; backend started with `publish_df17_mlat=false`
- Phase 8A frozen manifest: verified
- Phase 8B frozen manifest: verified
- Phase 9 frozen manifest: verified
- Test 7I frozen manifest: verified
- Raw/full Test 7H tree: `a645efd9add55f250cada5c657e35f357a359ebd169002fe6946a0285058d9bb`, unchanged
- Existing `/api/modeac/*`, `/api/modes/*`, `/ws/modeac`, and `/ws/modes` tests: passing

No historical Test 6–7I data file was modified.

## Rollback readiness

The timestamped backup exists and both copies match their original SHA256 values. `rollback.sh` passes shell syntax validation and hash guards. It restores the original index and API file and removes only the two new overlay files. The deployment script also refuses to overwrite an unexpected production index hash.

Rollback is prepared but cannot be execution-tested without the same interactive sudo credential that blocks deployment. See `docs/tar1090-phase10-backup.md`.

## Completion questions

1. Is modified production tar1090 stable? **Not yet established; production deployment is blocked. The staged Phase 10A build was stable for 15 minutes.**
2. Are production ADS-B and mutability MLAT unchanged? **They remained operational and untouched, but no modified-production comparison is possible yet.**
3. Are PoC targets visually distinct? **Yes in the staged build: cyan triangles for Mode-S, amber diamonds for anonymous Mode A/C, versus production aircraft icons.**
4. Does `Last seen` represent measurement age? **Yes; delayed 31–88 second events retained their measurement age at receipt.**
5. Can same-ICAO production and PoC Mode-S coexist? **The registries are structurally independent, but Phase 10C live production comparison was not started.**
6. Are comparison vectors useful without clutter? **Not evaluated; Phase 10C was gated.**
7. Are co-track hints useful and non-authoritative? **Not evaluated. The backend exposes no live `STRONG_COTRACK` API, so no hint was invented.**
8. Was measurable degradation introduced? **No accumulation was seen in staged Phase 10A, but a production before/after conclusion is not yet justified.**
9. Is rollback fully prepared? **The files, hashes, guards, and commands are prepared; execution still requires interactive sudo.**
10. Is this ready for routine daily observation? **No. Production 10A, WebSocket 10B, comparison 10C, and the final production soak remain required.**
