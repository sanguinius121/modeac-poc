# Unified standalone MLAT map

The Phase 9 map extends the existing `frontend/` application in place. It remains a static Leaflet diagnostic interface served on TCP 8088 and consumes only the Phase 8C backend on TCP 8090. It does not request `aircraft.json`, readsb aircraft state, tar1090, ADS-B position, or mutability output.

## Start and stop

From `/home/mlatserver/modeac-poc`, run these development processes in separate terminals:

```text
python3 -u -m realtime
python3 -u frontend/server.py
```

Open `http://100.100.24.4:8088/` or `http://127.0.0.1:8088/`. Stop both with Ctrl-C. No system service is installed by Phase 9.

## Architecture and semantics

One Leaflet map owns three independent layer groups: receivers, anonymous Mode A/C MLAT, and ICAO-aware Mode-S MLAT. Mode A/C uses teal diamonds and solid history lines; Mode-S uses orange directional MLAT triangles and dashed histories. Both labels and popups retain their backend source: `MODEAC_MLAT_4RX` or `MODES_MLAT_4RX`. Neither is labelled ADS-B.

`modeAcTracks` and `modeSTracks` are separate maps with separate ten-minute browser histories. No spatial merge or identifier namespace sharing occurs. Position age changes opacity below five seconds, from five to fifteen seconds, and beyond fifteen seconds; the browser does not extrapolate or animate positions forward.

The initial state is loaded once from `/api/modeac/tracks` and `/api/modes/tracks`. Independent WebSockets then consume `/ws/modeac` and `/ws/modes`, each with its own socket, status badge, reconnect counter, exponential backoff, and error handling. A failure in one stream does not disable the other. Snapshot reconciliation precedes ordered socket updates, and updates older than an existing `last_seen` timestamp are rejected.

Common health, receivers, clocks, and source-specific stats are polled every three seconds. Track endpoints are not repeatedly polled. Six shared clock links and a common degraded warning remain visible. Layer, lifecycle-state, and minimum-quality controls are independent for each track family. The combined list has explicit `[A/C]` and `[S]` source pills and can be filtered by source; selecting a row pans to its marker and opens the popup.

## Blind co-track diagnostic

Co-track analysis operates only on the two already-computed MLAT histories. It never changes track identity or position. Candidate observations must be within three seconds and five kilometres, with speed difference no more than 120 m/s and heading difference no more than 50 degrees when those fields exist. `POSSIBLE` needs at least two compatible observations. `STRONG_COTRACK` needs at least three temporally distinct observations spanning at least five seconds and mean separation no more than three kilometres.

The labels mean possible trajectory association, never identified or confirmed ICAO. A Mode A/C track remains `MAC-*`; it is not renamed. Thresholds were selected before the blind soak and are not tuned using ADS-B truth. The page records the strongest class observed for each pair for acceptance reporting, while popups show only relations involving currently active tracks.

## Diagnostics and limitations

The stats panel shows each family’s rates, active/confirmed counts, DF counts supplied by the backend, and measured P50/P95 latency. WebSocket connectivity and position freshness are intentionally separate concepts.

This is a PoC observation surface, not an operational surveillance display. Browser history is memory-only and disappears on reload. Mode A/C codes are anonymous and reusable. Co-track proximity can be coincidental, especially around dense traffic or weak geometry. No blind visual observation constitutes an accuracy or identity claim. Phase 9 does not inject positions into Beast and does not modify production services or ports 30004/30104.
