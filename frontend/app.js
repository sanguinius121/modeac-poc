"use strict";

const HISTORY_MS = 10 * 60 * 1000;
const POLL_MS = 3000;
const COTRACK_MS = 5000;
const QUALITY_RANK = {LOW: 0, MEDIUM: 1, HIGH: 2};
const API_BASE = `${location.protocol}//${location.hostname}:8090`;
const SOURCE = {
  modeac: {label: "A/C", endpoint: "/api/modeac/tracks", stats: "/api/modeac/stats", ws: "/ws/modeac", source: "MODEAC_MLAT_4RX"},
  modes: {label: "S", endpoint: "/api/modes/tracks", stats: "/api/modes/stats", ws: "/ws/modes", source: "MODES_MLAT_4RX"}
};
const COTRACK = {MAX_TIME_MS: 3000, MAX_DISTANCE_M: 5000, MAX_SPEED_DIFF_MPS: 120, MAX_HEADING_DIFF_DEG: 50, POSSIBLE_POINTS: 2, STRONG_POINTS: 3, STRONG_SPAN_MS: 5000, STRONG_MEAN_DISTANCE_M: 3000};

const map = L.map("map", {zoomControl: true}).setView([20.23, 107.08], 7);
L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {maxZoom: 18, attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
const receiverLayer = L.layerGroup().addTo(map);
const modeAcLayer = L.layerGroup().addTo(map);
const modeSLayer = L.layerGroup().addTo(map);
const layers = {modeac: modeAcLayer, modes: modeSLayer};
const modeAcTracks = new Map();
const modeSTracks = new Map();
const trackMaps = {modeac: modeAcTracks, modes: modeSTracks};
const receiverMarkers = new Map();
const streams = {
  modeac: {socket: null, timer: null, attempt: 0, openedAt: 0, badge: "modeAcWsBadge"},
  modes: {socket: null, timer: null, attempt: 0, openedAt: 0, badge: "modeSWsBadge"}
};
const cotracks = new Map();
const cotrackBest = new Map();
const diagnostics = {restErrors: 0, browserErrors: 0, invalidMessages: 0, wsDisconnects: {modeac: 0, modes: 0}, observed: {modeac: new Set(), modes: new Set()}, confirmed: {modeac: new Set(), modes: new Set()}, high: {modeac: new Set(), modes: new Set()}, movement: {modeac: new Set(), modes: new Set()}, largeJumps: {modeac: new Set(), modes: new Set()}, staleRevivals: {modeac: new Set(), modes: new Set()}, maxSimultaneous: {modeac: 0, modes: 0}};

const $ = id => document.getElementById(id);
const fmt = (value, digits = 1, suffix = "") => value == null || !Number.isFinite(Number(value)) ? "—" : `${Number(value).toFixed(digits)}${suffix}`;
const safe = value => String(value == null ? "—" : value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"})[c]);
const shortStation = name => ({Dao_Cai_chien: "CaiChien", BachLongVi: "BLV"})[name] || name;
const trackKey = (kind, id) => `${kind}:${id}`;

window.addEventListener("error", () => diagnostics.browserErrors += 1);
window.addEventListener("unhandledrejection", () => diagnostics.browserErrors += 1);

function setBadge(id, text, kind) {
  const node = $(id); node.className = `badge ${kind}`; node.innerHTML = `<i></i>${safe(text)}`;
}
async function getJSON(path) {
  const response = await fetch(`${API_BASE}${path}`, {cache: "no-store"});
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}
function ageOpacity(track) {
  const age = Number(track.age_s || 0);
  if (track.state === "STALE" || age > 15) return 0.24;
  if (age > 5) return 0.55;
  return track.state === "TENTATIVE" ? 0.72 : 1;
}
function displayName(kind, track) { return kind === "modes" ? String(track.icao || track.track_id.replace(/^MS-/, "")).toUpperCase() : String(track.code || track.display_code || "????"); }
function trackIcon(kind, track) {
  const quality = String(track.quality || "LOW").toLowerCase(); const label = displayName(kind, track);
  const heading = Number.isFinite(Number(track.heading_deg)) ? Number(track.heading_deg) : 0;
  const shape = kind === "modes" ? `<span class="modes-triangle" style="transform:rotate(${heading}deg)"></span>` : '<span class="modeac-diamond"></span>';
  return L.divIcon({className: "track-icon", iconSize: [92, 28], iconAnchor: [10, 14], html: `<div class="track-glyph ${kind} ${quality}">${shape}<span class="label">${safe(label)}</span></div>`});
}
function cotrackFor(kind, trackId) {
  const candidates = [...cotracks.values()].filter(x => (kind === "modeac" ? x.modeAcId : x.modeSId) === trackId && x.classification !== "NO_MATCH");
  return candidates.sort((a,b) => b.rank-a.rank || a.meanDistanceM-b.meanDistanceM)[0] || null;
}
function popup(kind, track) {
  const modeS = kind === "modes"; const relation = cotrackFor(kind, track.track_id);
  const other = relation ? (modeS ? relation.modeAcId : relation.icao) : null;
  const relationHtml = relation ? `<div class="cotrack-note"><b>Possible co-track:</b> ${modeS ? "Mode A/C " : "Mode-S ICAO "}${safe(other)}<br>Confidence: <b>${safe(relation.classification)}</b><br><small>Blind trajectory diagnostic; not identity.</small></div>` : "";
  return `<div class="popup-title"><span class="source-pill ${kind}">${modeS ? "S" : "A/C"}</span> ${safe(displayName(kind, track))}</div>
    ${modeS ? `ICAO: <b>${safe(displayName(kind, track))}</b><br>` : "ICAO: Unknown<br>"}Track: ${safe(track.track_id)}<br>
    State: <b>${safe(track.state)}</b> · Quality: <b>${safe(track.quality)}</b><br>
    Position: ${fmt(track.lat, 6)}, ${fmt(track.lon, 6)}<br>
    Fixes: ${safe(track.fix_count)} · Receivers: ${safe(track.receiver_count)}<br>
    Speed: ${fmt(track.speed_mps, 1, " m/s")} · Heading: ${fmt(track.heading_deg, 0, "°")}<br>
    Age: ${fmt(track.age_s, 1, " s")}
    <div class="popup-source">Inferred source: <b>${safe(track.position_source)}</b><br>Not ADS-B</div>${relationHtml}`;
}
function distanceM(a, b) {
  const r=6371000,p1=a.lat*Math.PI/180,p2=b.lat*Math.PI/180,dp=(b.lat-a.lat)*Math.PI/180,dl=(b.lon-a.lon)*Math.PI/180;
  const h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2; return 2*r*Math.asin(Math.sqrt(h));
}
function addHistory(kind, entry, track) {
  const timestamp = Date.parse(track.last_seen) || Date.now(); const point={t:timestamp,lat:Number(track.lat),lon:Number(track.lon),speed:track.speed_mps==null?NaN:Number(track.speed_mps),heading:track.heading_deg==null?NaN:Number(track.heading_deg)}; const last=entry.history[entry.history.length-1];
  if (!last || last.t!==point.t || last.lat!==point.lat || last.lon!==point.lon) {
    if (last) { const jump=distanceM(last,point); if (jump>25) diagnostics.movement[kind].add(track.track_id); const seconds=Math.max(.001,(point.t-last.t)/1000); if (jump>50000 || jump/seconds>600) diagnostics.largeJumps[kind].add(track.track_id); }
    entry.history.push(point);
  }
  entry.history=entry.history.filter(x => x.t>=Date.now()-HISTORY_MS); entry.line.setLatLngs(entry.history.map(x => [x.lat,x.lon]));
}
function upsertTrack(kind, track) {
  if (!track || !track.track_id || !Number.isFinite(Number(track.lat)) || !Number.isFinite(Number(track.lon))) return;
  const expected=SOURCE[kind].source; if (track.position_source && track.position_source!==expected) { console.error("Unexpected position source",kind,track.position_source); diagnostics.invalidMessages+=1; return; }
  const tracks=trackMaps[kind]; let entry=tracks.get(track.track_id); const incoming=Date.parse(track.last_seen)||0;
  if (entry && incoming && incoming<(Date.parse(entry.track.last_seen)||0)) return;
  if (!entry) {
    const marker=L.marker([track.lat,track.lon],{icon:trackIcon(kind,track)}).addTo(layers[kind]); const line=L.polyline([],{color:kind==="modes"?"#c06b22":"#087f7b",weight:2.3,opacity:.7,dashArray:kind==="modes"?"6 4":null}).addTo(layers[kind]); entry={kind,track,marker,line,history:[]}; tracks.set(track.track_id,entry);
  } else if (entry.track.state==="STALE" && track.state!=="STALE") diagnostics.staleRevivals[kind].add(track.track_id);
  entry.track=track; diagnostics.observed[kind].add(track.track_id); if(track.state==="CONFIRMED") diagnostics.confirmed[kind].add(track.track_id); if(track.quality==="HIGH") diagnostics.high[kind].add(track.track_id); diagnostics.maxSimultaneous[kind]=Math.max(diagnostics.maxSimultaneous[kind],tracks.size);
  entry.marker.setLatLng([track.lat,track.lon]).setIcon(trackIcon(kind,track)).setOpacity(ageOpacity(track)).bindPopup(popup(kind,track)); entry.line.setStyle({opacity:Math.max(.1,ageOpacity(track)*.7),weight:track.quality==="HIGH"?3.4:2.2}); addHistory(kind,entry,track); applyFilters();
}
function removeTrack(kind,id) { const tracks=trackMaps[kind],entry=tracks.get(id); if(!entry)return; layers[kind].removeLayer(entry.marker);layers[kind].removeLayer(entry.line);tracks.delete(id);renderTrackList(); }
function visible(kind,entry) {
  const checked=document.querySelector(`input[data-source="${kind}"][data-state="${entry.track.state}"]`); const quality=$(kind==="modeac"?"modeAcQualityFilter":"modeSQualityFilter").value;
  return (!checked||checked.checked)&&QUALITY_RANK[entry.track.quality||"LOW"]>=QUALITY_RANK[quality];
}
function sourceLayerEnabled(kind) { return $(kind==="modeac"?"modeAcLayerToggle":"modeSLayerToggle").checked; }
function applyFilters() {
  let count=0;
  for (const kind of Object.keys(trackMaps)) trackMaps[kind].forEach(entry => { const show=visible(kind,entry)&&sourceLayerEnabled(kind); for(const layer of [entry.marker,entry.line]) {if(show&&!layers[kind].hasLayer(layer))layers[kind].addLayer(layer);if(!show&&layers[kind].hasLayer(layer))layers[kind].removeLayer(layer);} if(show)count+=1; });
  if ($("receiverLayerToggle").checked&&!map.hasLayer(receiverLayer))receiverLayer.addTo(map); if(!$("receiverLayerToggle").checked&&map.hasLayer(receiverLayer))map.removeLayer(receiverLayer);
  for (const kind of Object.keys(layers)) {const enabled=sourceLayerEnabled(kind);if(enabled&&!map.hasLayer(layers[kind]))layers[kind].addTo(map);if(!enabled&&map.hasLayer(layers[kind]))map.removeLayer(layers[kind]);}
  $("trackCount").textContent=`${count} visible`;$("emptyState").classList.toggle("hidden",count>0);renderTrackList();
}
function renderTrackList() {
  const filter=$("listSourceFilter").value;const entries=[];for(const kind of Object.keys(trackMaps))trackMaps[kind].forEach(entry=>{if((filter==="all"||filter===kind)&&visible(kind,entry)&&sourceLayerEnabled(kind))entries.push(entry);}); entries.sort((a,b)=>(b.track.quality||"").localeCompare(a.track.quality||"")||displayName(a.kind,a.track).localeCompare(displayName(b.kind,b.track)));
  const list=$("trackList");list.innerHTML="";if(!entries.length){list.innerHTML='<div class="no-data">No tracks match the source/layer filters.</div>';return;}
  entries.forEach(entry=>{const t=entry.track,row=document.createElement("button");row.className=`track-row ${entry.kind}`;row.innerHTML=`<span class="source-pill ${entry.kind}">${SOURCE[entry.kind].label}</span><span class="code">${safe(displayName(entry.kind,t))}<small>${safe(t.state)} · ${fmt(t.age_s,1," s")}</small></span><span class="q">${safe(t.quality)}</span>`;row.onclick=()=>{map.setView([t.lat,t.lon],Math.max(map.getZoom(),10));entry.marker.openPopup();};list.appendChild(row);});
}
function reconcileSnapshot(kind,items) { const current=new Set(items.map(x=>x.track_id));trackMaps[kind].forEach((_,id)=>{if(!current.has(id))removeTrack(kind,id);});items.forEach(x=>upsertTrack(kind,x)); }
function handleMessage(kind,message) { if(message.type==="snapshot")reconcileSnapshot(kind,message.tracks||[]);else if(["track_created","track_updated","track_state_changed","track_stale"].includes(message.type))upsertTrack(kind,message.track);else if(message.type==="track_removed"&&message.track)removeTrack(kind,message.track.track_id); }
function connectWebSocket(kind) {
  const state=streams[kind];clearTimeout(state.timer);setBadge(state.badge,`${kind==="modeac"?"Mode A/C":"Mode-S"} ${state.attempt?`reconnecting (${state.attempt})`:"connecting"}`,"warning");const protocol=location.protocol==="https:"?"wss":"ws";state.socket=new WebSocket(`${protocol}://${location.hostname}:8090${SOURCE[kind].ws}`);
  state.socket.onopen=()=>{state.attempt=0;state.openedAt=Date.now();setBadge(state.badge,`${kind==="modeac"?"Mode A/C":"Mode-S"} live`,"online");};
  state.socket.onmessage=event=>{try{handleMessage(kind,JSON.parse(event.data));}catch(error){diagnostics.invalidMessages+=1;console.error(`Invalid ${kind} WebSocket message`,error);}};
  state.socket.onerror=()=>state.socket.close();state.socket.onclose=()=>{diagnostics.wsDisconnects[kind]+=1;setBadge(state.badge,`${kind==="modeac"?"Mode A/C":"Mode-S"} disconnected`,"offline");const delay=Math.min(30000,1000*(2**Math.min(state.attempt,5)));state.attempt+=1;state.timer=setTimeout(()=>connectWebSocket(kind),delay);};
}
function renderReceivers(receivers) {
  const list=$("receiverList");list.innerHTML="";let connected=0;receivers.forEach(receiver=>{if(receiver.connected)connected+=1;const row=document.createElement("div");row.className="status-row";row.innerHTML=`<span><i class="status-dot ${receiver.connected?"online":"offline"}"></i>${safe(shortStation(receiver.station))}<small>${fmt(receiver.type1_rate_s,1," T1/s")} · ${fmt(receiver.type2_rate_s,1," T2/s")} · ${fmt(receiver.type3_rate_s,1," T3/s")}</small></span><span class="row-value">${receiver.connected?"Connected":"Offline"}<small>age ${fmt(receiver.last_frame_age_s,2," s")}</small></span>`;list.appendChild(row);if(Number.isFinite(Number(receiver.lat))&&Number.isFinite(Number(receiver.lon))){let marker=receiverMarkers.get(receiver.station);const icon=L.divIcon({className:"",html:'<div class="receiver-icon"></div>',iconSize:[16,16],iconAnchor:[8,8]});if(!marker){marker=L.marker([receiver.lat,receiver.lon],{icon}).addTo(receiverLayer).bindTooltip(shortStation(receiver.station),{permanent:true,direction:"right",offset:[8,0]});receiverMarkers.set(receiver.station,marker);}marker.setPopupContent(`<b>Receiver: ${safe(receiver.station)}</b><br>${fmt(receiver.lat,6)}, ${fmt(receiver.lon,6)}<br>Altitude: ${fmt(receiver.alt_m,0," m")}<br>Type 1/2/3: ${fmt(receiver.type1_rate_s,1)} / ${fmt(receiver.type2_rate_s,1)} / ${fmt(receiver.type3_rate_s,1)} per second`).setOpacity(receiver.connected?1:.35);}});$("receiverSummary").textContent=`${connected} / ${receivers.length} connected`;setBadge("rxBadge",`${connected} / 4 receivers`,connected===4?"online":"warning");
}
function renderClocks(links) {
  const list=$("clockList");list.innerHTML="";const okay=links.filter(x=>["STRONG","PASS"].includes(x.quality)).length;const degraded=links.some(x=>["MARGINAL","BAD","UNAVAILABLE"].includes(x.quality));const p95=links.map(x=>Number(x.p95_us)).filter(Number.isFinite);$("clockSummary").textContent=`${okay} / ${links.length} OK · worst ${fmt(p95.length?Math.max(...p95):null,2," µs")}`;$("clockWarning").classList.toggle("hidden",!degraded);setBadge("clockBadge",degraded?"Clock degraded":`${okay}/${links.length} clocks OK`,degraded?"warning":"online");links.forEach(link=>{const row=document.createElement("div");row.className="clock-row";row.innerHTML=`<span>${safe(shortStation(link.a))} ↔ ${safe(shortStation(link.b))}<small>${safe(link.samples)} samples</small></span><span class="row-value"><b>${safe(link.quality)}</b><small>P95 ${fmt(link.p95_us,3," µs")}</small></span>`;list.appendChild(row);});
}
function pairsHtml(values){return values.map(([k,v])=>`<dt>${safe(k)}</dt><dd>${safe(v==null?"—":v)}</dd>`).join("");}
function renderStats(modeac,modes){$("statsUptime").textContent=`up ${fmt(Math.max(modeac.uptime_s||0,modes.uptime_s||0)/60,1," min")}`;$("modeAcStatsGrid").innerHTML=pairsHtml([["Strict 4RX/min",modeac.strict_4rx_per_min],["BLIND_UNIQUE/min",modeac.blind_unique_per_min],["BLIND_MULTIPLE/min",modeac.blind_multiple_per_min],["BLIND_INCONSISTENT/min",modeac.blind_inconsistent_per_min],["Active",modeac.active_tracks],["Confirmed",modeac.confirmed_tracks]]);$("modeSStatsGrid").innerHTML=pairsHtml([["4RX clusters/min",modes.strict_4rx_per_min],["MLAT fixes/min",modes.mlat_fix_per_min],["Active",modes.active_tracks],["Confirmed",modes.confirmed_tracks],["DF4 / DF5",`${modes.df_distribution?.[4]||0} / ${modes.df_distribution?.[5]||0}`],["DF11",modes.df_distribution?.[11]],["DF20 / DF21",`${modes.df_distribution?.[20]||0} / ${modes.df_distribution?.[21]||0}`]]);$("latencyGrid").innerHTML=pairsHtml([["Mode A/C P50",fmt(modeac.processing_latency_ms?.p50,0," ms")],["Mode A/C P95",fmt(modeac.processing_latency_ms?.p95,0," ms")],["Mode-S P50",fmt(modes.latency_ms?.total?.p50,0," ms")],["Mode-S P95",fmt(modes.latency_ms?.total?.p95,0," ms")]]);}
function headingDiff(a,b){const d=Math.abs(a-b)%360;return Math.min(d,360-d);}
function evaluatePair(mac,ms){const matches=[];for(const a of mac.history){let b=null,delta=Infinity;for(const candidate of ms.history){const d=Math.abs(candidate.t-a.t);if(d<delta){delta=d;b=candidate;}}if(!b||delta>COTRACK.MAX_TIME_MS)continue;const distance=distanceM(a,b),speedOK=!Number.isFinite(a.speed)||!Number.isFinite(b.speed)||Math.abs(a.speed-b.speed)<=COTRACK.MAX_SPEED_DIFF_MPS,headingOK=!Number.isFinite(a.heading)||!Number.isFinite(b.heading)||headingDiff(a.heading,b.heading)<=COTRACK.MAX_HEADING_DIFF_DEG;if(distance<=COTRACK.MAX_DISTANCE_M&&speedOK&&headingOK)matches.push({t:Math.max(a.t,b.t),distance});}matches.sort((a,b)=>a.t-b.t);const distinct=[];for(const m of matches)if(!distinct.length||m.t-distinct[distinct.length-1].t>=1000)distinct.push(m);const span=distinct.length?distinct[distinct.length-1].t-distinct[0].t:0,mean=distinct.length?distinct.reduce((s,x)=>s+x.distance,0)/distinct.length:Infinity;let classification="NO_MATCH",rank=0;if(distinct.length>=COTRACK.STRONG_POINTS&&span>=COTRACK.STRONG_SPAN_MS&&mean<=COTRACK.STRONG_MEAN_DISTANCE_M){classification="STRONG_COTRACK";rank=2;}else if(distinct.length>=COTRACK.POSSIBLE_POINTS){classification="POSSIBLE";rank=1;}return{classification,rank,compatiblePoints:distinct.length,spanMs:span,meanDistanceM:mean};}
function computeCotracks(){cotracks.clear();modeAcTracks.forEach(mac=>modeSTracks.forEach(ms=>{if(!mac.history.length||!ms.history.length)return;const overlap=Math.min(mac.history.at(-1).t,ms.history.at(-1).t)-Math.max(mac.history[0].t,ms.history[0].t);if(overlap<0)return;const key=`${mac.track.track_id}|${ms.track.track_id}`,result={...evaluatePair(mac,ms),modeAcId:mac.track.track_id,modeSId:ms.track.track_id,icao:displayName("modes",ms.track)};cotracks.set(key,result);const previous=cotrackBest.get(key);if(!previous||result.rank>previous.rank||(result.rank===previous.rank&&result.compatiblePoints>previous.compatiblePoints))cotrackBest.set(key,result);}));const values=[...cotrackBest.values()];$("cotrackStats").innerHTML=pairsHtml([["Candidate pairs",values.length],["POSSIBLE",values.filter(x=>x.classification==="POSSIBLE").length],["STRONG_COTRACK",values.filter(x=>x.classification==="STRONG_COTRACK").length]]);for(const kind of Object.keys(trackMaps))trackMaps[kind].forEach(entry=>entry.marker.setPopupContent(popup(kind,entry.track)));}
async function pollStatus(){const results=await Promise.allSettled([getJSON("/health"),getJSON("/api/receivers"),getJSON("/api/clocks"),getJSON(SOURCE.modeac.stats),getJSON(SOURCE.modes.stats)]);diagnostics.restErrors+=results.filter(x=>x.status==="rejected").length;setBadge("backendBadge",results[0].status==="fulfilled"?"Backend online":"Backend offline",results[0].status==="fulfilled"?"online":"offline");if(results[1].status==="fulfilled")renderReceivers(results[1].value.receivers||[]);if(results[2].status==="fulfilled")renderClocks(results[2].value.links||[]);if(results[3].status==="fulfilled"&&results[4].status==="fulfilled")renderStats(results[3].value,results[4].value);}
function diagnosticSnapshot(){const sets=x=>Object.fromEntries(Object.entries(x).map(([k,v])=>[k,[...v]]));return{restErrors:diagnostics.restErrors,browserErrors:diagnostics.browserErrors,invalidMessages:diagnostics.invalidMessages,wsDisconnects:{...diagnostics.wsDisconnects},observed:sets(diagnostics.observed),confirmed:sets(diagnostics.confirmed),high:sets(diagnostics.high),movement:sets(diagnostics.movement),largeJumps:sets(diagnostics.largeJumps),staleRevivals:sets(diagnostics.staleRevivals),maxSimultaneous:{...diagnostics.maxSimultaneous},current:{modeac:modeAcTracks.size,modes:modeSTracks.size},cotracks:[...cotracks.values()],cotrackObserved:[...cotrackBest.values()]};}
window.phase9Diagnostics=diagnosticSnapshot;
async function start(){document.querySelectorAll('input[data-state],#modeAcLayerToggle,#modeSLayerToggle,#receiverLayerToggle').forEach(x=>x.addEventListener("change",applyFilters));$("modeAcQualityFilter").addEventListener("change",applyFilters);$("modeSQualityFilter").addEventListener("change",applyFilters);$("listSourceFilter").addEventListener("change",renderTrackList);const initial=await Promise.allSettled([getJSON(SOURCE.modeac.endpoint),getJSON(SOURCE.modes.endpoint)]);initial.forEach((result,index)=>{const kind=index?"modes":"modeac";if(result.status==="fulfilled")reconcileSnapshot(kind,result.value.tracks||[]);else{diagnostics.restErrors+=1;console.warn(`Initial ${kind} load failed; WebSocket remains independent`,result.reason);}});connectWebSocket("modeac");connectWebSocket("modes");await pollStatus();setInterval(pollStatus,POLL_MS);setInterval(computeCotracks,COTRACK_MS);setInterval(()=>{for(const kind of Object.keys(trackMaps))trackMaps[kind].forEach(entry=>{entry.track.age_s=Math.max(0,(Date.now()-(Date.parse(entry.track.last_seen)||Date.now()))/1000);entry.marker.setOpacity(ageOpacity(entry.track)).setPopupContent(popup(kind,entry.track));entry.line.setStyle({opacity:Math.max(.1,ageOpacity(entry.track)*.7)});});renderTrackList();},1000);}
start();
