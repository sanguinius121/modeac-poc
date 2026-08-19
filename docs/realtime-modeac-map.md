# Standalone realtime Mode A/C MLAT map

## Start and stop

The map depends on the Phase 1 REST/WebSocket backend. In separate terminals from `/home/mlatserver/modeac-poc`, run:

```bash
python3 -m realtime
python3 frontend/server.py
```

Open `http://100.100.24.4:8088/` (or `http://127.0.0.1:8088/` locally). Stop either process with Ctrl-C. These are manual development processes; no frontend or backend service is installed by Phase 2.

The frontend serves only HTML, CSS, and JavaScript on TCP 8088. It calls the backend on TCP 8090 using `/health`, `/api/receivers`, `/api/clocks`, `/api/modeac/stats`, `/api/modeac/tracks`, and `/ws/modeac`. The backend permits REST CORS only from localhost, 127.0.0.1, and 100.100.24.4 on port 8088.

## Map semantics

Receiver sites use circular station markers. Anonymous Mode A/C MLAT tracks deliberately do not use aircraft icons:

- HIGH quality: filled diamond.
- MEDIUM quality: hollow diamond.
- LOW quality: small dot.
- TENTATIVE and age 5–15 seconds: reduced opacity.
- STALE or age over 15 seconds: strongly faded.

The Mode A/C code is the primary marker label. Clicking a marker or track-list row opens the track details, including position, lifecycle, quality, speed, heading, age, source, and available solver diagnostics. Altitude remains `Unknown` when the backend has no trustworthy altitude.

The browser retains and draws the last 10 minutes of fixes per track. History resets on page refresh and is deleted when the backend sends `track_removed`. No interpolation or artificial movement is applied.

## Controls and status

Checkboxes independently show or hide CONFIRMED, TENTATIVE, and STALE tracks. Minimum quality selects LOW/all, MEDIUM, or HIGH. Filtering hides both marker and history without deleting browser state.

Receiver status refreshes every three seconds and includes connection, frame age, and Type-1 rate. Clock status shows all six backend-provided link qualities and a visible warning whenever any link is MARGINAL, BAD, or UNAVAILABLE. Statistics show rolling strict/localization rates and track counts. Backend health is polled independently of WebSocket status.

The WebSocket applies `snapshot`, `track_created`, `track_updated`, `track_state_changed`, `track_stale`, and `track_removed`. On disconnect the page remains loaded, shows the disconnected state, and retries with exponential backoff capped at 30 seconds.

## Limitations

This UI displays inferred four-receiver TDOA products, not ADS-B positions. It does not load aircraft.json, readsb, tar1090, DF17 tracks, target identity, or truth data. Browser history is memory-only. OpenStreetMap and Leaflet assets require browser network access. Sparse four-receiver traffic can legitimately leave the map empty, and clock degradation is surfaced rather than hidden. This standalone observation UI is not an operational separation or safety system.
