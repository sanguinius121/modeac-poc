(function () {
  "use strict";

  const CONFIG = Object.freeze({
    apiBase: `${window.location.protocol}//${window.location.hostname}:8090`,
    trackPollMs: 1500,
    statusPollMs: 4000,
    historyMs: 10 * 60 * 1000,
    staleRemoveMs: 120 * 1000,
    startTimeoutMs: 30 * 1000,
    reconnectInitialMs: 1000,
    reconnectMaxMs: 30000,
  });
  const SOURCE = Object.freeze({
    modes: { title: "PoC Mode-S MLAT", positionSource: "MODES_MLAT_4RX", color: "#38bdf8", points: 3 },
    modeac: { title: "PoC Mode A/C MLAT", positionSource: "MODEAC_MLAT_4RX", color: "#f59e0b", points: 4 },
  });
  const MARKER_ICON = Object.freeze({
    modes: `data:image/svg+xml;charset=utf-8,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -18 36 36"><path d="M0-15L13 13 0 7-13 13Z" fill="#38bdf8" stroke="#f8fafc" stroke-width="2.5"/></svg>')}`,
    modeac: `data:image/svg+xml;charset=utf-8,${encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="-18 -18 36 36"><path d="M0-14L14 0 0 14-14 0Z" fill="#f59e0b" stroke="#f8fafc" stroke-width="2.5"/></svg>')}`,
  });
  const registries = { modes: new Map(), modeac: new Map() };
  const diagnostics = {
    phase: "10B_WEBSOCKET",
    initialized: false,
    restErrors: 0,
    invalidTracks: 0,
    outOfOrderDrops: 0,
    received: { modes: 0, modeac: 0 },
    maxima: { modes: 0, modeac: 0 },
    statusPolls: 0,
    clockDegradationEvents: 0,
    delayedMeasurementExamples: [],
    streams: {
      modes: { status: "STARTING", connected: false, lastMessageTime: null, reconnectCount: 0 },
      modeac: { status: "STARTING", connected: false, lastMessageTime: null, reconnectCount: 0 },
    },
    lastError: null,
  };
  const sources = {};
  const layersByKind = {};
  let popupOverlay;
  let popupElement;
  let selectedEntry = null;
  let statusElement;
  let lastClockDegraded = null;
  let statusSnapshot = null;
  const socketStates = {
    modes: { socket: null, timer: null, backoffMs: CONFIG.reconnectInitialMs },
    modeac: { socket: null, timer: null, backoffMs: CONFIG.reconnectInitialMs },
  };

  function escapeHtml(value) {
    return String(value == null ? "Unknown" : value).replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  }

  function number(value, digits = 1, suffix = "") {
    return Number.isFinite(Number(value)) ? `${Number(value).toFixed(digits)}${suffix}` : "Unknown";
  }

  function timestampMs(track) {
    const parsed = Date.parse(track.last_seen || "");
    return Number.isFinite(parsed) ? parsed : NaN;
  }

  function ageMs(entry, now = Date.now()) {
    return Math.max(0, now - entry.measurementMs);
  }

  function ageText(milliseconds) {
    if (!Number.isFinite(milliseconds)) return "Unknown";
    const seconds = Math.max(0, milliseconds / 1000);
    if (seconds < 10) return `${seconds.toFixed(1)} s ago`;
    if (seconds < 120) return `${Math.round(seconds)} s ago`;
    return `${(seconds / 60).toFixed(1)} min ago`;
  }

  function opacityForAge(milliseconds) {
    if (milliseconds <= 15000) return 1;
    if (milliseconds <= 30000) return 0.75;
    if (milliseconds <= 60000) return 0.5;
    if (milliseconds <= 120000) return 0.25;
    return 0;
  }

  function validTrack(kind, track) {
    const valid = track && typeof track.track_id === "string" && Number.isFinite(Number(track.lat)) &&
      Number.isFinite(Number(track.lon)) && track.position_source === SOURCE[kind].positionSource &&
      Number.isFinite(timestampMs(track));
    if (!valid) diagnostics.invalidTracks += 1;
    return valid;
  }

  function trackLabel(kind, track) {
    return kind === "modes" ? `△ ${track.icao || "UNKNOWN"}` : `◇ ${track.code || track.display_code || "----"}`;
  }

  function pointStyle(kind, entry) {
    const source = SOURCE[kind];
    const opacity = opacityForAge(ageMs(entry));
    const heading = Number(entry.track.heading_deg);
    return new ol.style.Style({
      image: new ol.style.Icon({
        src: MARKER_ICON[kind],
        anchor: [0.5, 0.5],
        anchorXUnits: "fraction",
        anchorYUnits: "fraction",
        scale: 1.15,
        rotation: kind === "modes" && Number.isFinite(heading) ? heading * Math.PI / 180 : 0,
        rotateWithView: true,
        opacity,
      }),
      text: new ol.style.Text({
        text: trackLabel(kind, entry.track),
        offsetY: -25,
        font: "bold 14px system-ui, sans-serif",
        fill: new ol.style.Fill({ color: source.color }),
        stroke: new ol.style.Stroke({ color: "rgba(15,23,42,0.95)", width: 3 }),
        backgroundFill: new ol.style.Fill({ color: "rgba(15,23,42,0.78)" }),
        padding: [2, 4, 2, 4],
      }),
      zIndex: 230,
    });
  }

  function trailStyle(kind) {
    return new ol.style.Style({
      stroke: new ol.style.Stroke({ color: SOURCE[kind].color, width: 2 }),
      zIndex: 220,
    });
  }

  function removeCurrent(entry) {
    if (entry.point) {
      sources[entry.kind].removeFeature(entry.point);
      entry.point = null;
    }
  }

  function removeTrack(kind, trackId) {
    const entry = registries[kind].get(trackId);
    if (!entry) return;
    removeCurrent(entry);
    if (entry.trail) sources[kind].removeFeature(entry.trail);
    registries[kind].delete(trackId);
  }

  function updateTrail(entry, coordinate, measurementMs) {
    const cutoff = Date.now() - CONFIG.historyMs;
    entry.history = entry.history.filter(point => point.time >= cutoff);
    if (measurementMs >= cutoff && !entry.history.some(point => point.time === measurementMs)) {
      entry.history.push({ time: measurementMs, coordinate });
      entry.history.sort((a, b) => a.time - b.time);
    }
    if (entry.history.length > 1) {
      const coordinates = entry.history.map(point => point.coordinate);
      if (!entry.trail) {
        entry.trail = new ol.Feature({ geometry: new ol.geom.LineString(coordinates), pocKind: entry.kind, pocTrail: true });
        entry.trail.setStyle(trailStyle(entry.kind));
        sources[entry.kind].addFeature(entry.trail);
      } else {
        entry.trail.getGeometry().setCoordinates(coordinates);
      }
    }
  }

  function upsertTrack(kind, track, receivedMs = Date.now()) {
    if (!validTrack(kind, track)) return;
    const measurementMs = timestampMs(track);
    let entry = registries[kind].get(track.track_id);
    const isNewMeasurement = !entry || measurementMs > entry.measurementMs;
    if (entry && measurementMs < entry.measurementMs) {
      diagnostics.outOfOrderDrops += 1;
      return;
    }
    const coordinate = ol.proj.fromLonLat([Number(track.lon), Number(track.lat)]);
    if (!entry) {
      entry = { kind, track, measurementMs, receivedMs, history: [], point: null, trail: null };
      registries[kind].set(track.track_id, entry);
    }
    entry.track = track;
    entry.measurementMs = measurementMs;
    entry.receivedMs = receivedMs;
    updateTrail(entry, coordinate, measurementMs);
    if (!entry.point) {
      entry.point = new ol.Feature({ geometry: new ol.geom.Point(coordinate), pocKind: kind, pocTrackId: track.track_id });
      sources[kind].addFeature(entry.point);
    } else {
      entry.point.getGeometry().setCoordinates(coordinate);
    }
    entry.point.setStyle(() => pointStyle(kind, entry));
    entry.point.changed();
    if (isNewMeasurement && receivedMs - measurementMs >= 30000 && diagnostics.delayedMeasurementExamples.length < 20) {
      diagnostics.delayedMeasurementExamples.push({
        kind,
        trackId: track.track_id,
        measurementTime: track.last_seen,
        ageAtReceiptS: (receivedMs - measurementMs) / 1000,
      });
    }
    diagnostics.received[kind] += 1;
    diagnostics.maxima[kind] = Math.max(diagnostics.maxima[kind], registries[kind].size);
    if (statusElement) renderStatus();
  }

  function reconcile(kind, tracks, receivedMs) {
    const present = new Set();
    for (const track of tracks || []) {
      if (track && track.track_id) present.add(track.track_id);
      upsertTrack(kind, track, receivedMs);
    }
    for (const trackId of registries[kind].keys()) {
      if (!present.has(trackId)) removeTrack(kind, trackId);
    }
  }

  async function getJson(path) {
    const response = await fetch(`${CONFIG.apiBase}${path}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
    return response.json();
  }

  async function pollTracks() {
    const settled = await Promise.allSettled([
      getJson("/api/modes/tracks"),
      getJson("/api/modeac/tracks"),
    ]);
    const receivedMs = Date.now();
    settled.forEach((result, index) => {
      const kind = index === 0 ? "modes" : "modeac";
      if (result.status === "fulfilled") reconcile(kind, result.value.tracks, receivedMs);
      else {
        diagnostics.restErrors += 1;
        diagnostics.lastError = String(result.reason);
      }
    });
  }

  function renderStatus() {
    const snapshot = statusSnapshot;
    const healthStatus = snapshot ? String(snapshot.health.status || "unknown").toUpperCase() : "CHECKING";
    const connected = snapshot ? snapshot.receivers.filter(receiver => receiver.connected).length : 0;
    const receiverTotal = snapshot ? snapshot.receivers.length : 4;
    const clocksOk = snapshot ? snapshot.clocks.filter(qualityIsOk).length : 0;
    const clockTotal = snapshot ? snapshot.clocks.length : 6;
    const degraded = snapshot ? clockTotal !== 6 || clocksOk !== clockTotal : false;
    const modeSCount = [...registries.modes.values()].filter(entry => entry.point).length;
    const modeAcCount = [...registries.modeac.values()].filter(entry => entry.point).length;
    statusElement.innerHTML = `<strong>PoC MLAT</strong>` +
      `<span class='${healthStatus === "OK" ? "poc-online" : "poc-offline"}'>Backend: ${escapeHtml(healthStatus)}</span>` +
      `<span>Receivers: ${connected} / ${receiverTotal}</span>` +
      `<span>Clock: ${clocksOk} / ${clockTotal} OK</span>` +
      `<span class='${diagnostics.streams.modes.connected ? "poc-live" : "poc-reconnecting"}'>Mode-S PoC: ${escapeHtml(diagnostics.streams.modes.status)}</span>` +
      `<span class='${diagnostics.streams.modeac.connected ? "poc-live" : "poc-reconnecting"}'>Mode A/C PoC: ${escapeHtml(diagnostics.streams.modeac.status)}</span>` +
      `<span>Targets: Mode-S ${modeSCount} · Mode A/C ${modeAcCount}</span>` +
      `<button type='button' class='poc-fit-button' ${modeSCount + modeAcCount ? "" : "disabled"}>Zoom to PoC</button>` +
      (degraded ? "<span class='poc-clock-warning'>PoC MLAT CLOCK DEGRADED</span>" : "");
    const fitButton = statusElement.querySelector(".poc-fit-button");
    if (fitButton) fitButton.addEventListener("click", fitPocTracks);
  }

  function fitPocTracks() {
    const extent = [Infinity, Infinity, -Infinity, -Infinity];
    let count = 0;
    for (const kind of ["modes", "modeac"]) {
      for (const entry of registries[kind].values()) {
        if (!entry.point) continue;
        const coordinate = entry.point.getGeometry().getCoordinates();
        extent[0] = Math.min(extent[0], coordinate[0]);
        extent[1] = Math.min(extent[1], coordinate[1]);
        extent[2] = Math.max(extent[2], coordinate[0]);
        extent[3] = Math.max(extent[3], coordinate[1]);
        count += 1;
      }
    }
    if (count) {
      const minimumSpan = 50000;
      if (extent[2] - extent[0] < minimumSpan) {
        const center = (extent[0] + extent[2]) / 2;
        extent[0] = center - minimumSpan / 2;
        extent[2] = center + minimumSpan / 2;
      }
      if (extent[3] - extent[1] < minimumSpan) {
        const center = (extent[1] + extent[3]) / 2;
        extent[1] = center - minimumSpan / 2;
        extent[3] = center + minimumSpan / 2;
      }
      OLMap.getView().fit(extent, { padding: [70, 380, 70, 70], maxZoom: 9, duration: 350 });
    }
  }

  function qualityIsOk(link) {
    return link && (link.quality === "PASS" || link.quality === "STRONG");
  }

  async function pollStatus() {
    diagnostics.statusPolls += 1;
    const settled = await Promise.allSettled([getJson("/health"), getJson("/api/receivers"), getJson("/api/clocks")]);
    if (settled.some(result => result.status === "rejected")) {
      diagnostics.restErrors += settled.filter(result => result.status === "rejected").length;
      diagnostics.lastError = "PoC status endpoint unavailable";
      statusSnapshot = null;
      renderStatus();
      return;
    }
    const health = settled[0].value;
    const receivers = settled[1].value.receivers || [];
    const clocks = settled[2].value.links || [];
    const connected = receivers.filter(receiver => receiver.connected).length;
    const clocksOk = clocks.filter(qualityIsOk).length;
    const degraded = clocks.length !== 6 || clocksOk !== clocks.length;
    if (degraded && lastClockDegraded === false) diagnostics.clockDegradationEvents += 1;
    lastClockDegraded = degraded;
    statusSnapshot = { health, receivers, clocks };
    renderStatus();
  }

  function websocketUrl(kind) {
    const base = new URL(CONFIG.apiBase);
    base.protocol = base.protocol === "https:" ? "wss:" : "ws:";
    base.pathname = kind === "modes" ? "/ws/modes" : "/ws/modeac";
    base.search = "";
    return base.toString();
  }

  function handleSocketMessage(kind, message, receivedMs) {
    if (!message || typeof message.type !== "string") {
      diagnostics.invalidTracks += 1;
      return;
    }
    if (message.type === "snapshot") {
      reconcile(kind, message.tracks || [], receivedMs);
      return;
    }
    if (message.type === "track_removed") {
      if (message.track && message.track.track_id) removeTrack(kind, message.track.track_id);
      return;
    }
    if (["track_created", "track_updated", "track_state_changed", "track_stale"].includes(message.type)) {
      upsertTrack(kind, message.track, receivedMs);
    }
  }

  async function connectSocket(kind) {
    const state = socketStates[kind];
    const stream = diagnostics.streams[kind];
    state.timer = null;
    stream.status = "RECONNECTING";
    stream.connected = false;
    renderStatus();
    try {
      const snapshot = await getJson(kind === "modes" ? "/api/modes/tracks" : "/api/modeac/tracks");
      reconcile(kind, snapshot.tracks || [], Date.now());
    } catch (error) {
      diagnostics.restErrors += 1;
      diagnostics.lastError = String(error);
    }
    const socket = new WebSocket(websocketUrl(kind));
    state.socket = socket;
    socket.onopen = () => {
      if (state.socket !== socket) return;
      stream.connected = true;
      stream.status = "LIVE";
      state.backoffMs = CONFIG.reconnectInitialMs;
      renderStatus();
    };
    socket.onmessage = event => {
      if (state.socket !== socket) return;
      const receivedMs = Date.now();
      stream.lastMessageTime = new Date(receivedMs).toISOString();
      try { handleSocketMessage(kind, JSON.parse(event.data), receivedMs); }
      catch (error) {
        diagnostics.invalidTracks += 1;
        diagnostics.lastError = String(error);
      }
    };
    socket.onclose = () => {
      if (state.socket !== socket) return;
      state.socket = null;
      stream.connected = false;
      stream.status = "RECONNECTING";
      stream.reconnectCount += 1;
      renderStatus();
      const delay = state.backoffMs;
      state.backoffMs = Math.min(CONFIG.reconnectMaxMs, state.backoffMs * 2);
      state.timer = setTimeout(() => connectSocket(kind), delay);
    };
    socket.onerror = () => socket.close();
  }

  async function startTransport() {
    await pollTracks();
    connectSocket("modes");
    connectSocket("modeac");
  }

  function row(label, value) {
    return `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(value)}</td></tr>`;
  }

  function popupHtml(entry) {
    const track = entry.track;
    const isModeS = entry.kind === "modes";
    const altitude = track.altitude_ft == null ? "Unknown" : number(track.altitude_ft, 0, " ft");
    return `<button class='poc-mlat-popup-close' title='Close'>×</button>` +
      `<h3>${escapeHtml(trackLabel(entry.kind, track))}</h3><table>` +
      row("Source", isModeS ? "PoC Mode-S MLAT" : "PoC Mode A/C MLAT") +
      row(isModeS ? "ICAO" : "Code", isModeS ? (track.icao || "Unknown") : (track.code || track.display_code || "Unknown")) +
      row("Track ID", track.track_id) + row("Latitude", number(track.lat, 6)) + row("Longitude", number(track.lon, 6)) +
      row("Altitude", altitude) + row("State", track.state || "Unknown") + row("Quality", track.quality || "Unknown") +
      row("Fix count", number(track.fix_count, 0)) + row("Receiver count", number(track.receiver_count, 0)) +
      row("Speed", number(track.speed_mps, 1, " m/s")) + row("Heading", number(track.heading_deg, 1, "°")) +
      row("Measurement time", track.last_seen || "Unknown") + row("Last seen", ageText(ageMs(entry))) +
      row("Received", ageText(Date.now() - entry.receivedMs)) + row("Position source", track.position_source || "Unknown") +
      `</table>`;
  }

  function openPopup(entry, coordinate) {
    selectedEntry = entry;
    popupElement.className = `poc-mlat-popup ${entry.kind}`;
    popupElement.innerHTML = popupHtml(entry);
    popupElement.querySelector(".poc-mlat-popup-close").addEventListener("click", () => {
      selectedEntry = null;
      popupOverlay.setPosition(undefined);
    });
    popupOverlay.setPosition(coordinate);
  }

  function addMapLayers() {
    for (const kind of ["modes", "modeac"]) {
      sources[kind] = new ol.source.Vector({ wrapX: false });
      layersByKind[kind] = new ol.layer.Vector({
        name: `poc_${kind}`,
        title: SOURCE[kind].title,
        type: "overlay",
        source: sources[kind],
        visible: true,
        zIndex: kind === "modes" ? 1001 : 1002,
        renderBuffer: 100,
      });
      layers.push(layersByKind[kind]);
      layersByKind[kind].on("change:visible", event => {
        try { localStorage.setItem(`layer_poc_${kind}`, event.target.getVisible()); } catch (_) {}
      });
      try {
        const stored = localStorage.getItem(`layer_poc_${kind}`);
        if (stored === "false") layersByKind[kind].setVisible(false);
      } catch (_) {}
    }
  }

  function addUi() {
    statusElement = document.createElement("div");
    statusElement.id = "poc-mlat-status";
    statusElement.className = "poc-mlat-status";
    statusElement.innerHTML = "<strong>PoC MLAT</strong><span class='poc-reconnecting'>Backend: CHECKING</span>";
    document.getElementById("map_container").appendChild(statusElement);
    popupElement = document.createElement("div");
    popupOverlay = new ol.Overlay({ element: popupElement, positioning: "bottom-center", offset: [0, -14], stopEvent: true });
    OLMap.addOverlay(popupOverlay);
    OLMap.on("singleclick", event => {
      let matched = null;
      OLMap.forEachFeatureAtPixel(event.pixel, feature => {
        if (!matched && feature.get("pocTrackId")) matched = feature;
      }, { hitTolerance: 8 });
      if (!matched) return;
      const kind = matched.get("pocKind");
      const entry = registries[kind].get(matched.get("pocTrackId"));
      if (entry) openPopup(entry, matched.getGeometry().getCoordinates());
    });
  }

  function lifecycleTick() {
    const now = Date.now();
    for (const kind of ["modes", "modeac"]) {
      for (const entry of registries[kind].values()) {
        entry.history = entry.history.filter(point => point.time >= now - CONFIG.historyMs);
        if (entry.trail) {
          if (entry.history.length > 1) entry.trail.getGeometry().setCoordinates(entry.history.map(point => point.coordinate));
          else { sources[kind].removeFeature(entry.trail); entry.trail = null; }
        }
        if (ageMs(entry, now) > CONFIG.staleRemoveMs) removeCurrent(entry);
        else if (entry.point) entry.point.changed();
      }
    }
    if (popupOverlay.getPosition() && selectedEntry) openPopup(selectedEntry, popupOverlay.getPosition());
  }

  function publicDiagnostics() {
    const now = Date.now();
    const detail = {};
    for (const kind of ["modes", "modeac"]) {
      const entries = [...registries[kind].values()];
      detail[kind] = {
        registrySize: entries.length,
        visibleMarkers: entries.filter(entry => entry.point).length,
        historyPoints: entries.reduce((sum, entry) => sum + entry.history.length, 0),
        oldestMeasurementAgeS: entries.length ? Math.max(...entries.map(entry => ageMs(entry, now) / 1000)) : null,
        newestReceiptAgeS: entries.length ? Math.min(...entries.map(entry => (now - entry.receivedMs) / 1000)) : null,
      };
    }
    return { ...diagnostics, tracks: detail, config: CONFIG, productionPlaneCount: typeof g !== "undefined" && g.planesOrdered ? g.planesOrdered.length : null };
  }

  function initializeOverlay() {
    if (!window.ol || typeof OLMap === "undefined" || !OLMap || typeof layers === "undefined" || !layers) return false;
    addMapLayers();
    addUi();
    diagnostics.initialized = true;
    window.pocModeSTracks = registries.modes;
    window.pocModeAcTracks = registries.modeac;
    window.pocMlatDiagnostics = publicDiagnostics;
    startTransport();
    pollStatus();
    setInterval(pollStatus, CONFIG.statusPollMs);
    setInterval(lifecycleTick, 1000);
    return true;
  }

  const started = Date.now();
  const waiter = setInterval(() => {
    if (initializeOverlay()) clearInterval(waiter);
    else if (Date.now() - started > CONFIG.startTimeoutMs) {
      clearInterval(waiter);
      diagnostics.lastError = "tar1090 map initialization timeout";
      console.error("PoC MLAT overlay could not find the initialized tar1090 map");
    }
  }, 100);
})();
