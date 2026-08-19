# tar1090 PoC MLAT overlay

## Installed production layout

This host uses the upstream source installer, not a Debian package.

- Install root: `/usr/local/share/tar1090`
- Production web root: `/usr/local/share/tar1090/html`
- Main entry: `/usr/local/share/tar1090/html/index.html`
- Web server: lighttpd 1.4.55 on TCP 80
- Public path: `/tar1090/`
- lighttpd mapping: `/etc/lighttpd/conf-available/88-tar1090.conf`
- tar1090 service: `/lib/systemd/system/tar1090.service`
- history process: `/usr/local/share/tar1090/tar1090.sh /run/tar1090 /run/readsb`
- readsb JSON alias: `/tar1090/data/` to `/run/readsb/`
- compressed history alias: `/tar1090/chunks/` to `/run/tar1090/`

The entry page loads cache-busted upstream files. `script_b0f58f28592f8ca593d4a390cbbb6387.js` owns `initialize()`, `initMapEarly()`, `initMap()`, and `ol_map_init()`. `layers_fb2fbccdac7be63a35d62f25f6689ba2.js` constructs the base-layer collection and the OpenLayers layer switcher consumes that collection.

The upstream source contains explicit `CSS_ANCHOR`, `JS_ANCHOR*`, and other extension anchors, but this installation has no automatic user JS/CSS loader. Phase 10 therefore uses the CSS anchor and one post-core script tag. All behavior lives in isolated files:

- `poc-mlat-overlay.js`
- `poc-mlat-overlay.css`

The source installer builds a temporary HTML tree and atomically replaces the production web root. It preserves `config.js` and `upintheair.json`, but not these Phase 10 files or the index hook. Re-run the reviewed Phase 10 deployment after a tar1090 update; never blindly overwrite a newly updated index.

## Architecture and isolation

The overlay waits for the existing OpenLayers map, then appends two native overlay layers:

- `PoC Mode-S MLAT`, enabled by default
- `PoC Mode A/C MLAT`, enabled by default

It maintains `pocModeSTracks` and `pocModeAcTracks` as independent `Map` registries. It never calls `PlaneObject`, writes `g.planes`, or adds PoC features to `PlaneIconFeatures`. An ICAO can therefore have both an unchanged production aircraft marker and an independent PoC Mode-S marker.

Phase 10A is deliberately REST-only. It polls `/api/modes/tracks` and `/api/modeac/tracks` every 1.5 seconds. Health, receivers, and clocks are polled every four seconds. The backend remains the sole authority for association, synchronization, solving, quality, lifecycle, and identity.

## Marker and popup semantics

PoC Mode-S uses a cyan directional triangle and label such as `△ 8881F5`. PoC Mode A/C uses an amber diamond and code label such as `◇ 1720`. Neither uses tar1090's production aircraft icon.

Popups identify the PoC source and expose the backend fields without inventing values. They include identity/code, anonymous track ID, coordinates, altitude or `Unknown`, state, quality, fix and receiver counts, speed, heading, measurement time, measurement age (`Last seen`), local REST receipt age (`Received`), and the exact `position_source`.

Measurement age is always computed as:

```text
browser Date.now() - Date.parse(track.last_seen)
```

It is never reset from the REST receipt time or backend `age_s` snapshot field. Receipt age is separately derived from the local time at which the snapshot was received.

Frontend opacity is 1.0 through 15 seconds, 0.75 through 30 seconds, 0.5 through 60 seconds, and 0.25 through 120 seconds. The current marker is removed beyond 120 seconds. This does not alter the backend track. Per-namespace trails retain only measurement points from the last ten minutes, reject duplicate timestamps, and reject out-of-order position regression.

## Status and warnings

The compact map status reports backend state, connected receivers, and the count of the six clock links in `PASS` or `STRONG`. Any missing, `UNAVAILABLE`, `MARGINAL`, or `BAD` link produces the visible `PoC MLAT CLOCK DEGRADED` warning. Status polling is independent of production tar1090 refreshes.

## API and origin dependency

The overlay reads the PoC backend directly on TCP 8090. `realtime/api.py` allows only the known standalone and tar1090 origins on this host, including `http://100.100.24.4`. No lighttpd reverse proxy, Beast output, readsb input, mlat-server input, or production receiver-forwarding change is involved.

## Deployment and operation

The reviewed Phase 10A deployment is:

```bash
/home/mlatserver/modeac-poc/tar1090-overlay/deploy-phase10a.sh
```

It requires sudo because `/usr/local/share/tar1090/html` is root-owned. It verifies that the production index still matches either the original backup or the reviewed staged index before writing. Static files require no service restart. Hard-refresh `http://100.100.24.4/tar1090/` afterward.

Start the PoC backend from the repository without enabling DF17 publication:

```bash
cd /home/mlatserver/modeac-poc
python3 -m realtime
```

Stop that foreground PoC process with `Ctrl-C`. This does not stop readsb, mlat-server, tar1090, lighttpd, or receiver forwarding.

## Rollback

See `docs/tar1090-phase10-backup.md`. The prepared rollback is:

```bash
/home/mlatserver/modeac-poc/backups/tar1090-phase10-20260810T091313Z/rollback.sh
```

It hash-checks both originals, restores the original index and API CORS file, and removes only the two new overlay assets. No production service is stopped or reconfigured.

## Known limitations and phase gate

Production deployment requires an interactive sudo credential that is not available to the automation account. Until the deployment script is run, the production web root remains byte-identical to its backup and the validated overlay is available only in the production-faithful staged webroot on TCP 8089.

Phase 10B WebSockets and Phase 10C live comparisons are intentionally not added before production Phase 10A passes its required soak. This preserves the task's explicit stop gate. Co-track hints are also unavailable because the current backend exposes no live `STRONG_COTRACK` association API; no identity inference is recreated in tar1090.
