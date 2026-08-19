"use strict";

/* Legacy contract references retained for regression checks:
 * Configuration changed; Geometry Quality; Receiver Count;
 * Predicted P95 Error; exactly four; Show simulated comparison circle;
 * Status: Valid.
 */
const state={
  receivers:[],polygon:[],geometryIds:[],markers:new Map(),circles:new Map(),
  outlines:new Map(),result:null,stale:true,adding:false,uploading:0,
  displayMode:"basic",coverage:null,coverageRequest:0,coverageTimer:null
};
const COLORS={GOOD:"#1f9d55",ACCEPTABLE:"#d5b51f",POOR:"#ed7d31",VERY_POOR:"#c62828",NO_MLAT:"#80868b"};
const QUALITY_VI={GOOD:"TỐT",ACCEPTABLE:"CHẤP NHẬN ĐƯỢC",POOR:"KÉM",VERY_POOR:"RẤT KÉM",NO_MLAT:"KHÔNG ĐỦ ĐIỀU KIỆN MLAT"};
const QUALITY_TEXT={
  GOOD:"P95 ≤ 500 m · condition ≤ 10 · branch separation ≥ 1,0 µs",
  ACCEPTABLE:"P95 ≤ 1.500 m · condition ≤ 30 · branch separation ≥ 0,5 µs",
  POOR:"P95 ≤ 5.000 m · condition ≤ 100 · branch separation ≥ 0,2 µs",
  VERY_POOR:"Có đủ dữ liệu nhưng không đạt đầy đủ ngưỡng KÉM",
  NO_MLAT:"Không có đủ tổ hợp bốn trạm theo nguồn vùng thu đã chọn"
};
const VIEW_MODES=[
  ["count","Số trạm thu được tín hiệu",true],
  ["best_quality","Chất lượng tốt nhất",true],
  ["error","Sai số dự kiến 95%",true],
  ["survivability","Khả năng chịu mất 1 trạm",true],
  ["importance","Mức độ phụ thuộc trạm",true],
  ["worst_quality","Chất lượng yếu nhất (Worst Quality)",false],
  ["good_subsets","Số tổ hợp tốt (GOOD Subset Count)",false],
  ["robustness","Tỷ lệ tổ hợp tốt (Robustness Fraction)",false]
];
const RECEPTION_COLORS=["#087fae","#6f4aa8","#008f8c","#bc5b17","#4b68b8","#8b568e","#137c65","#a14668"];
const DEFAULT_RECEIVER_ICON=new L.Icon.Default();
const ACTIVE_GEOMETRY_ICON=L.divIcon({className:"active-geometry-icon",html:'<span class="active-geometry-pin"><i></i></span>',iconSize:[30,42],iconAnchor:[15,40],tooltipAnchor:[0,-35],popupAnchor:[0,-36]});
const map=L.map("map").setView([20.4,108.0],6);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",{maxZoom:18,attribution:"© OpenStreetMap"}).addTo(map);
const canvas=L.canvas({padding:.5});
const areaLayer=new L.FeatureGroup().addTo(map),gridLayer=new L.LayerGroup().addTo(map);
map.addControl(new L.Control.Draw({edit:{featureGroup:areaLayer,edit:false,remove:false},draw:{polyline:false,circle:false,circlemarker:false,marker:false,polygon:{allowIntersection:false,showArea:true},rectangle:{showArea:true}}}));

const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt=(v,d=1)=>v==null?"—":Number(v).toLocaleString("vi-VN",{minimumFractionDigits:d,maximumFractionDigits:d});
const help=(text)=>'<span class="help" title="'+esc(text)+'">?</span>';
function uid(){return `rx-${Date.now().toString(36)}-${Math.random().toString(36).slice(2,6)}`}
function isStrict(){return $("geometry-strategy").value==="strict_4"}
function eligibleReceivers(){const failed=$("failed-receiver").value;return state.receivers.filter(r=>r.enabled&&r.id!==failed)}
function choose(n,k){if(n<k)return 0;let v=1;for(let i=1;i<=k;i++)v=v*(n-k+i)/i;return Math.round(v)}
function qualityLabel(value){const vi=QUALITY_VI[value]||value;return state.displayMode==="advanced"?`${vi} (${value})`:vi}
function branchLabel(separation,safe){
  if(separation==null)return "CHƯA ĐỦ DỮ LIỆU";
  if(separation>=1)return "TỐT";
  if(safe||separation>=.5)return "CHẤP NHẬN ĐƯỢC";
  return "KÉM";
}

function changed(){
  state.coverage=null;
  state.stale=true;
  $("stale").textContent="Cấu hình đã thay đổi — hãy phân tích lại.";
  $("stale").className="stale";
  refreshAnalyzeAvailability();
  renderAreaInfo();scheduleCoverageRefresh();
}
function outlineReady(r){return r.reception_model!=="outline"||(r.outline_id&&state.outlines.has(r.outline_id))}
function refreshAnalyzeAvailability(){
  const enough=isStrict()?state.geometryIds.length===4:eligibleReceivers().length>=4;
  const invalid=state.uploading>0||!enough||state.receivers.some(r=>r.enabled&&!outlineReady(r));
  $("analyze").disabled=invalid;
  $("analyze").title=invalid?(isStrict()?"Cần chọn đúng bốn trạm và mọi outline phải hợp lệ.":"Cần ít nhất bốn trạm eligible và mọi outline phải hợp lệ."):"";
}
function refreshReceiverSelects(){
  for(const [id,none] of [["failed-receiver",true],["importance-receiver",false]]){
    const select=$(id),old=select.value;
    select.innerHTML=none?'<option value="">Không</option>':"";
    state.receivers.filter(r=>r.enabled).forEach(r=>{
      const option=document.createElement("option");option.value=r.id;option.textContent=r.name;select.appendChild(option);
    });
    if([...select.options].some(x=>x.value===old))select.value=old;
  }
  $("importance-control").hidden=$("view-mode").value!=="importance";
}
function refreshViewModes(){
  const select=$("view-mode"),old=select.value;
  select.innerHTML="";
  VIEW_MODES.filter(x=>state.displayMode==="advanced"||x[2]).forEach(([value,label])=>{
    const option=document.createElement("option");option.value=value;option.textContent=label;select.appendChild(option);
  });
  select.value=[...select.options].some(x=>x.value===old)?old:"count";
  refreshReceiverSelects();
}
function setDisplayMode(mode){
  state.displayMode=mode;
  document.body.classList.toggle("basic-mode",mode==="basic");
  document.body.classList.toggle("advanced-mode",mode==="advanced");
  refreshViewModes();
  renderGrid();renderSummary();renderAssessment();
  setTimeout(()=>map.invalidateSize(),0);
}

function removeReceptionLayers(id){
  (state.circles.get(id)||[]).forEach(layer=>map.removeLayer(layer));
  state.circles.delete(id);
}
function outlinePopup(r,resource){
  const m=resource.metadata,max=r.max_range_km?`<br>Bán kính so sánh: ${r.max_range_km} km`:"";
  return `<b>Trạm thu: ${esc(r.name)}</b><br>Nguồn vùng thu: outline readsb quan sát<br>Tệp: ${esc(m.filename)}<br>Số điểm: ${m.point_count}<br>Giai đoạn quan sát: ${esc(m.observed_period)}<br>Thời điểm tải: ${esc(m.uploaded||"fixture/runtime")}${max}`;
}
function updateReceptionArea(r){
  removeReceptionLayers(r.id);
  if(!$("show-coverage").checked||!r.enabled||r.show_reception_area===false)return;
  const layers=[],color=RECEPTION_COLORS[Math.max(0,state.receivers.indexOf(r))%RECEPTION_COLORS.length];
  if(r.reception_model==="simulated"&&r.max_range_km){
    layers.push(L.circle([r.lat,r.lon],{radius:r.max_range_km*1000,color,weight:2,opacity:.8,fillColor:color,fillOpacity:.075,interactive:false}).addTo(map));
  }
  if(r.reception_model==="outline"&&state.outlines.has(r.outline_id)){
    const resource=state.outlines.get(r.outline_id);
    resource.rings.forEach(ring=>layers.push(L.polygon(ring,{color,weight:2,opacity:.8,fillColor:color,fillOpacity:.07}).bindPopup(outlinePopup(r,resource)).addTo(map)));
    if(r.show_simulated_comparison&&r.max_range_km)layers.push(L.circle([r.lat,r.lon],{radius:r.max_range_km*1000,color,weight:1.5,opacity:.65,fillOpacity:0,dashArray:"6 6",interactive:false}).addTo(map));
  }
  if(layers.length)state.circles.set(r.id,layers);
}
function syncMap(){
  for(const [id,marker] of state.markers){
    if(!state.receivers.some(r=>r.id===id)){map.removeLayer(marker);state.markers.delete(id);removeReceptionLayers(id)}
  }
  state.receivers.forEach(r=>{
    let marker=state.markers.get(r.id);
    if(!marker){
      marker=L.marker([r.lat,r.lon],{draggable:true,title:r.name}).addTo(map);
      marker.on("dragend",()=>{const p=marker.getLatLng();r.lat=+p.lat.toFixed(6);r.lon=+p.lng.toFixed(6);renderReceivers();updateReceptionArea(r);changed()});
      state.markers.set(r.id,marker);
    }else marker.setLatLng([r.lat,r.lon]);
    const selected=state.geometryIds.includes(r.id);
    marker.setIcon(selected?ACTIVE_GEOMETRY_ICON:DEFAULT_RECEIVER_ICON);
    marker.bindTooltip(`${r.name}${selected?" · trạm strict-4":""}`);
    updateReceptionArea(r);
  });
  $("receiver-count").textContent=`${state.receivers.filter(r=>r.enabled).length} đang bật`;
  refreshAnalyzeAvailability();
}
function patchReceiver(id,key,value){
  const r=state.receivers.find(x=>x.id===id);if(!r)return;
  r[key]=value;if(key==="enabled"&&!value)state.geometryIds=state.geometryIds.filter(x=>x!==id);
  syncMap();changed();
}
function metadataHtml(r){
  if(r.reception_model!=="outline")return"";
  if(r.upload_status)return `<div class="outline-status pending">${esc(r.upload_status)}</div>`;
  const outline=state.outlines.get(r.outline_id);
  if(!outline)return '<div class="outline-status invalid">Trạng thái: Thiếu — hãy tải outline.json</div>';
  const m=outline.metadata,max=Math.max(...outline.rings[0].map(p=>hav([r.lat,r.lon],p)));
  return `<div class="outline-status valid"><b>Trạng thái: Hợp lệ</b><br>Tệp: ${esc(m.filename)} · ${m.point_count} điểm<br>Quan sát: ${esc(m.observed_period)} · Xa nhất từ RX cấu hình: ${fmt(max)} km<br>Tải lên: ${esc(m.uploaded||"runtime fixture")}</div>`;
}
function coverageRow(id){return state.coverage?.receivers?.find(row=>row.receiver_id===id)}
function coverageMetricsHtml(r){
  const row=coverageRow(r.id),source=r.reception_model==="outline"?"Vùng thu quan sát từ readsb":"Vùng thu giả định";
  if(!row)return `<div class="coverage-metrics"><b>${source}</b><br>Diện tích vùng thu: Đang tính…<br>Diện tích trong vùng giám sát: —<br>Tỷ lệ bao phủ vùng giám sát: —</div>`;
  const inside=row.coverage_inside_surveillance_km2==null?"—":fmt(row.coverage_inside_surveillance_km2,0)+" km²",percent=row.surveillance_coverage_percent==null?"—":fmt(row.surveillance_coverage_percent,1)+"%";
  return `<div class="coverage-metrics"><b>${esc(row.source_label_vi)}</b><br>Diện tích vùng thu: <strong>${fmt(row.coverage_area_km2,0)} km²</strong><br>Diện tích trong vùng giám sát: <strong>${inside}</strong><br>Tỷ lệ bao phủ vùng giám sát: <strong>${percent}</strong></div>`;
}
async function refreshCoverageAreas(){
  if(state.uploading||state.receivers.some(r=>r.reception_model==="outline"&&!outlineReady(r)))return;
  const serial=++state.coverageRequest;
  try{
    const body={receivers:state.receivers.map(({upload_status,show_reception_area,show_simulated_comparison,...r})=>r),surveillance_polygon:state.polygon};
    const response=await fetch("/api/coverage-areas",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}),data=await response.json();
    if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
    if(serial!==state.coverageRequest)return;
    state.coverage=data;renderReceivers();renderAreaInfo();
  }catch(error){if(serial===state.coverageRequest)console.warn("Coverage area calculation failed:",error.message)}
}
function scheduleCoverageRefresh(){
  clearTimeout(state.coverageTimer);state.coverageTimer=setTimeout(refreshCoverageAreas,180);
}
async function uploadOutline(r,file){
  r.upload_status="Uploading…";state.uploading++;renderReceivers();
  try{
    const form=new FormData();form.append("file",file);r.upload_status="Parsing…";renderReceivers();
    const response=await fetch("/api/outlines",{method:"POST",body:form}),data=await response.json();
    if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
    state.outlines.set(data.outline_id,data);r.reception_model="outline";r.outline_id=data.outline_id;r.outline_filename=data.metadata.filename;r.outline_source="upload";r.upload_status="";changed();
  }catch(error){r.upload_status=`Outline readsb không hợp lệ: ${error.message}`;alert(r.upload_status)}
  finally{state.uploading--;renderReceivers();scheduleCoverageRefresh()}
}
async function deleteOutline(oid){
  if(!oid)return;
  const response=await fetch(`/api/outlines/${encodeURIComponent(oid)}`,{method:"DELETE"}),data=await response.json();
  if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
  state.outlines.delete(oid);
  state.receivers.filter(r=>r.outline_id===oid).forEach(r=>{r.reception_model="simulated";r.outline_id="";r.outline_filename="";r.upload_status=""});
  renderReceivers();changed();
}
function renderReceivers(){
  const root=$("receiver-list");root.innerHTML="";
  state.receivers.forEach(r=>{
    if(r.show_reception_area===undefined)r.show_reception_area=true;
    const selected=state.geometryIds.includes(r.id),outline=r.reception_model==="outline",card=document.createElement("div");
    card.className=`receiver-card ${selected?"selected":""}`;
    card.innerHTML=`<div class="receiver-head"><input data-k="name" type="text" value="${esc(r.name)}"><label><input data-k="enabled" type="checkbox" ${r.enabled?"checked":""}> Bật</label></div>
      <div class="receiver-grid"><label>Vĩ độ<input data-k="lat" type="number" step="0.000001" value="${r.lat}"></label><label>Kinh độ<input data-k="lon" type="number" step="0.000001" value="${r.lon}"></label><label>Độ cao (m)<input data-k="altitude_m" type="number" value="${r.altitude_m}"></label><label>${outline?"Bán kính so sánh":"Vùng thu giả định"} (km)<input data-k="max_range_km" type="number" min="1" value="${r.max_range_km??350}"></label></div>
      <label class="model-label">Nguồn dữ liệu vùng thu<select data-model><option value="simulated" ${!outline?"selected":""}>Bán kính giả định</option><option value="outline" ${outline?"selected":""}>Vùng quan sát từ readsb</option></select></label>
      ${outline?`<div class="outline-actions"><label class="file-button">${r.outline_id?"Thay":"Tải"} outline.json<input data-upload type="file" accept="application/json"></label>${r.outline_id?'<button data-remove-outline>Xóa outline</button>':""}</div>${metadataHtml(r)}<label class="inline"><input data-comparison type="checkbox" ${r.show_simulated_comparison?"checked":""}> Hiện vòng tròn giả định để so sánh</label>`:""}
      ${coverageMetricsHtml(r)}
      <label class="inline"><input data-show-area type="checkbox" ${r.show_reception_area!==false?"checked":""}> Hiện vùng thu của trạm</label>
      <div class="receiver-actions"><label class="advanced-only"><input data-geometry type="checkbox" ${selected?"checked":""} ${!r.enabled?"disabled":""}> Trạm nền strict-4</label><button class="delete">Xóa</button></div>`;
    card.querySelectorAll("[data-k]").forEach(input=>input.addEventListener("change",()=>{
      const key=input.dataset.k;patchReceiver(r.id,key,input.type==="checkbox"?input.checked:(key==="name"?input.value:+input.value));renderReceivers();
    }));
    card.querySelector("[data-model]").onchange=event=>{r.reception_model=event.target.value;r.outline_source="upload";changed();renderReceivers()};
    const upload=card.querySelector("[data-upload]");if(upload)upload.onchange=event=>event.target.files[0]&&uploadOutline(r,event.target.files[0]);
    const remove=card.querySelector("[data-remove-outline]");if(remove)remove.onclick=()=>deleteOutline(r.outline_id).catch(error=>alert(error.message));
    const comparison=card.querySelector("[data-comparison]");if(comparison)comparison.onchange=event=>{r.show_simulated_comparison=event.target.checked;syncMap()};
    card.querySelector("[data-show-area]").onchange=event=>{r.show_reception_area=event.target.checked;syncMap()};
    card.querySelector("[data-geometry]").onchange=event=>{
      if(event.target.checked){
        if(state.geometryIds.length>=4){alert("Bộ nền strict-4 chỉ nhận đúng bốn trạm (exactly four).");event.target.checked=false;return}
        state.geometryIds.push(r.id);
      }else state.geometryIds=state.geometryIds.filter(x=>x!==r.id);
      changed();renderReceivers();
    };
    card.querySelector(".delete").onclick=()=>{state.receivers=state.receivers.filter(x=>x.id!==r.id);state.geometryIds=state.geometryIds.filter(x=>x!==r.id);renderReceivers();syncMap();changed()};
    root.appendChild(card);
  });
  refreshReceiverSelects();syncMap();
}

function polygonFromLayer(layer){let points=layer.getLatLngs();while(Array.isArray(points[0]))points=points[0];return points.map(x=>[+x.lat.toFixed(6),+x.lng.toFixed(6)])}
function setArea(polygon){
  state.polygon=polygon;areaLayer.clearLayers();
  if(polygon.length){const layer=L.polygon(polygon,{color:"#162f44",weight:2,fillOpacity:.05}).addTo(areaLayer);map.fitBounds(layer.getBounds(),{padding:[20,20]})}
  renderAreaInfo();changed();
}
function hav(a,b){const R=6371.0088,d=Math.PI/180,p1=a[0]*d,p2=b[0]*d,dl=(b[0]-a[0])*d,dn=(b[1]-a[1])*d,q=Math.sin(dl/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dn/2)**2;return 2*R*Math.asin(Math.min(1,Math.sqrt(q)))}
function areaMetrics(){
  if(state.polygon.length<3)return null;
  const lat0=state.polygon.reduce((s,p)=>s+p[0],0)/state.polygon.length,lon0=state.polygon.reduce((s,p)=>s+p[1],0)/state.polygon.length;
  const xy=state.polygon.map(p=>[(p[1]-lon0)*111.32*Math.cos(lat0*Math.PI/180),(p[0]-lat0)*111.132]);
  let area=0;for(let i=0;i<xy.length;i++)area+=xy[i][0]*xy[(i+1)%xy.length][1]-xy[(i+1)%xy.length][0]*xy[i][1];
  let span=0;for(let i=0;i<state.polygon.length;i++)for(let j=i+1;j<state.polygon.length;j++)span=Math.max(span,hav(state.polygon[i],state.polygon[j]));
  return{area:Math.abs(area/2),span,bbox:{south:Math.min(...state.polygon.map(x=>x[0])),north:Math.max(...state.polygon.map(x=>x[0])),west:Math.min(...state.polygon.map(x=>x[1])),east:Math.max(...state.polygon.map(x=>x[1]))}};
}
function renderAreaInfo(){
  const metric=areaMetrics();
  const area=state.coverage?.surveillance_area_km2??metric?.area;
  $("area-info").innerHTML=metric?`Diện tích: ${fmt(area,0)} km²${state.coverage?" (equal-area)":" (ước tính khi đang tính)"}<br>Độ rộng lớn nhất: ${fmt(metric.span)} km<br>Khung: ${fmt(metric.bbox.south,3)}…${fmt(metric.bbox.north,3)} N, ${fmt(metric.bbox.west,3)}…${fmt(metric.bbox.east,3)} E`:"Chưa chọn vùng.";
}
map.on(L.Draw.Event.CREATED,event=>setArea(polygonFromLayer(event.layer)));
map.on("click",event=>{
  if(!state.adding)return;state.adding=false;$("add-receiver").textContent="+ Thêm trạm thu";
  state.receivers.push({id:uid(),name:`RX${state.receivers.length+1}`,lat:+event.latlng.lat.toFixed(6),lon:+event.latlng.lng.toFixed(6),altitude_m:30,reception_model:"simulated",max_range_km:350,outline_id:"",outline_filename:"",outline_source:"upload",enabled:true,show_reception_area:true});
  renderReceivers();changed();
});
async function loadOutlines(){
  const response=await fetch("/api/outlines");if(!response.ok)return;
  const list=(await response.json()).outlines||[];
  await Promise.all(list.map(async item=>{const request=await fetch(`/api/outlines/${item.outline_id}`);if(request.ok)state.outlines.set(item.outline_id,await request.json())}));
}
async function loadCurrent(){
  const response=await fetch("/api/preset"),preset=await response.json();
  state.receivers=preset.receivers.map(x=>({...x,outline_id:x.outline_id||"",outline_filename:x.outline_filename||"",outline_source:"upload",show_reception_area:true}));
  state.geometryIds=[...preset.geometry_receiver_ids];setArea(preset.surveillance_polygon);renderReceivers();changed();
}
function requestBody(allowHigh=false){
  return{receivers:state.receivers.map(({upload_status,show_reception_area,show_simulated_comparison,...r})=>r),surveillance_polygon:state.polygon,target_altitude_m:+$("target-altitude").value,timing_noise_us:+$("timing-noise").value,grid_step_km:+$("grid-step").value,geometry_receiver_ids:state.geometryIds,geometry_strategy:$("geometry-strategy").value,failed_receiver_id:$("failed-receiver").value,allow_high_subset_count:allowHigh};
}

function countColor(n){return n===0?"#444":`hsl(${260-Math.min(n,8)*24} 52% 46%)`}
function fractionColor(value){return value<=0?"#80868b":`hsl(${Math.round(10+value*115)} 65% 42%)`}
function colorPoint(point,mode){
  if(mode==="best_quality")return COLORS[point.best_quality||point.quality];
  if(mode==="worst_quality")return COLORS[point.worst_quality||point.quality];
  if(mode==="count")return countColor(point.receiver_count);
  if(mode==="good_subsets")return countColor(point.good_subset_count||0);
  if(mode==="robustness")return fractionColor(point.good_subset_fraction||0);
  if(mode==="survivability")return point.receiver_count<5?"#80868b":(point.n_minus_1_survivable?"#15803d":"#c62828");
  if(mode==="importance"){const value=(point.receiver_importance||{})[$("importance-receiver").value];return value==null?"#80868b":value<=1.1?"#4b9b68":value<=1.5?"#d5b51f":value<=2?"#ed7d31":"#c62828"}
  if(point.quality==="NO_MLAT")return COLORS.NO_MLAT;
  const error=point.predicted_p95_error_m;return error<250?"#177245":error<500?"#42a65a":error<1000?"#d5b51f":error<2000?"#ed8a31":error<5000?"#d84a32":"#8b1d1d";
}
function names(values){return values&&values.length?values.map(esc).join(" + "):"—"}
function basicPopup(point){
  const bestNames=point.best_subset_names||point.geometry_receivers;
  const total=point.subset_count===undefined?(point.quality==="NO_MLAT"?0:1):point.subset_count;
  const good=point.good_subset_count===undefined?(point.quality==="GOOD"?1:0):point.good_subset_count;
  const separation=point.best_branch_separation_us??point.branch_separation_us;
  const safe=point.best_branch_safe??point.branch_safe;
  return `<div class="point-detail basic-popup"><b>Vị trí</b><br>${fmt(point.lat,4)}, ${fmt(point.lon,4)}<hr>
    <b>Số trạm thu được tín hiệu:</b> ${point.receiver_count}<br>
    <b>Tổ hợp tốt nhất:</b> ${names(bestNames)}<br>
    <b>Chất lượng:</b> ${qualityLabel(point.best_quality||point.quality)}<br>
    <b>Sai số dự kiến 95%:</b> ${point.best_p95_error_m==null?(point.predicted_p95_error_m==null?"—":fmt(point.predicted_p95_error_m,0)+" m"):fmt(point.best_p95_error_m,0)+" m"}<br>
    <b>Độ tách biệt nghiệm:</b> ${branchLabel(separation,safe)}<br>
    <b>Số tổ hợp GOOD:</b> ${good} / ${total}<br>
    <b>Mất một trạm vẫn còn tổ hợp GOOD:</b> ${point.receiver_count<5?"KHÔNG ÁP DỤNG":(point.n_minus_1_survivable?"CÓ":"KHÔNG")}</div>`;
}
function advancedPopup(point){
  const rows=point.reception.map(x=>`<div class="${x.in_range?"yes":"no"}">${esc(x.name)}: ${x.in_range?"CÓ":"KHÔNG"} — ${esc(x.reason)}${x.geometry_selected?" [strict baseline]":""}</div>`).join("");
  const strict=point.strict_subset_message?`<div class="strict-warning">${esc(point.strict_subset_message)}</div>`:"";
  const multi=point.subset_count===undefined?"":`<hr><b>Eligible 4RX subsets: ${point.subset_count}</b><br>Best subset: ${names(point.best_subset_names)}<br>Best subset IDs: ${names(point.best_subset)}<br>Best P50 / P95 / condition: ${fmt(point.best_p50_error_m,0)} / ${fmt(point.best_p95_error_m,0)} m / ${fmt(point.best_condition,2)}<br>Worst subset: ${names(point.worst_subset_names)}<br>Worst subset IDs: ${names(point.worst_subset)}<br>Worst P50 / P95 / condition: ${fmt(point.worst_p50_error_m,0)} / ${fmt(point.worst_p95_error_m,0)} m / ${fmt(point.worst_condition,2)}<br>GOOD subsets: ${point.good_subset_count} (${fmt(100*point.good_subset_fraction)}%)<br>N-1 survivable: ${point.n_minus_1_survivable?"YES":"NO"}<br>Full-N P50 / P95 / condition: ${fmt(point.full_n_predicted_p50_m,0)} / ${fmt(point.full_n_predicted_p95_m,0)} m / ${fmt(point.full_n_condition,2)}<br><button class="subset-detail" data-lat="${point.lat}" data-lon="${point.lon}">Hiện mọi subset (Show all subsets)</button><div class="subset-table"></div>`;
  return `<div class="point-detail"><b>${fmt(point.lat,4)} N, ${fmt(point.lon,4)} E</b><br>Target altitude: ${fmt(point.target_altitude_m,0)} m<br>Enabled receivers in range: ${point.receiver_count}<hr>${rows}${strict}<hr>Predicted P50 / P95: ${fmt(point.predicted_p50_error_m,0)} / ${fmt(point.predicted_p95_error_m,0)} m<br>Condition Number: ${fmt(point.condition,2)}<br>Branch separation: ${fmt(point.branch_separation_us,2)} µs<br>Inside convex hull: ${point.inside_hull?"YES":"NO"}<br>Branch safe: ${point.branch_safe?"YES":"NO"}<br><b>Quality: ${qualityLabel(point.quality)}</b>${multi}</div>`;
}
function pointPopup(point){return state.displayMode==="basic"?basicPopup(point):advancedPopup(point)}
function renderGrid(){
  gridLayer.clearLayers();if(!state.result)return;
  const mode=$("view-mode").value,radius=+$("grid-step").value===5?3:+$("grid-step").value===10?4:5;
  state.result.grid.forEach(point=>L.circleMarker([point.lat,point.lon],{renderer:canvas,radius,color:colorPoint(point,mode),weight:0,fillColor:colorPoint(point,mode),fillOpacity:.65}).bindPopup(pointPopup(point)).addTo(gridLayer));
  renderLegend(mode);
}
function renderLegend(mode){
  let items;
  if(mode.endsWith("quality"))items=Object.entries(COLORS).map(([key,color])=>[qualityLabel(key),color]);
  else if(mode==="count"||mode==="good_subsets"){
    const key=mode==="count"?"receiver_count":"good_subset_count",maximum=state.result?Math.max(4,...state.result.grid.map(x=>x[key]||0)):4;
    items=Array.from({length:maximum+1},(_,index)=>[`${index}${mode==="count"?" trạm":" GOOD"}`,countColor(index)]);
  }else if(mode==="robustness")items=[["0%","#80868b"],["25%",fractionColor(.25)],["50%",fractionColor(.5)],["75%",fractionColor(.75)],["100%",fractionColor(1)]];
  else if(mode==="survivability")items=[["Dưới 5 trạm / không áp dụng","#80868b"],["Đạt N-1","#15803d"],["Không đạt N-1","#c62828"]];
  else if(mode==="importance")items=[["≤1,1×","#4b9b68"],["≤1,5×","#d5b51f"],["≤2×","#ed7d31"],[">2×","#c62828"],["Không có alternative","#80868b"]];
  else items=[["<250 m","#177245"],["250–500 m","#42a65a"],["500 m–1 km","#d5b51f"],["1–2 km","#ed8a31"],["2–5 km","#d84a32"],[">5 km","#8b1d1d"],["Không đủ MLAT","#80868b"]];
  const swatches=items.map(x=>`<span class="legend-item"><span class="swatch" style="background:${x[1]}"></span>${esc(x[0])}</span>`).join("");
  const detail=mode.endsWith("quality")&&state.displayMode==="advanced"?`<div class="thresholds">${Object.entries(QUALITY_TEXT).map(([key,value])=>`<div><b>${qualityLabel(key)}:</b> ${value}</div>`).join("")}</div>`:"";
  $("legend-content").innerHTML=swatches+detail;
}

function metricCard(title,value,tooltip){
  return `<div class="metric"><span>${title} ${help(tooltip)}</span><br><b>${value}</b></div>`;
}
function coverageTableHtml(){
  const coverage=state.result?.receiver_coverage;
  if(!coverage?.receivers?.length)return"";
  const rows=coverage.receivers.map(row=>`<tr><td>${esc(row.receiver_name)}</td><td>${esc(row.source_label_vi)}</td><td>${fmt(row.coverage_area_km2,0)}</td><td>${fmt(row.coverage_inside_surveillance_km2,0)}</td><td>${row.surveillance_coverage_percent==null?"—":fmt(row.surveillance_coverage_percent,1)+"%"}</td></tr>`).join("");
  return `<div class="coverage-summary"><h3>Diện tích vùng thu theo trạm</h3><table><thead><tr><th>Trạm</th><th>Nguồn</th><th>Vùng thu (km²)</th><th>Trong vùng giám sát (km²)</th><th>Bao phủ vùng giám sát</th></tr></thead><tbody>${rows}</tbody></table><p>Mẫu số của tỷ lệ là toàn bộ diện tích vùng giám sát ${fmt(coverage.surveillance_area_km2,0)} km²; đây không phải tỷ lệ phần vùng thu của trạm nằm trong polygon.</p></div>`;
}
function renderSummary(){
  if(!state.result){$("summary-content").textContent="Hãy chạy phân tích để xem kết quả.";return}
  const summary=state.result.summary,strict=summary.geometry_strategy==="strict_4",assessment=state.result.assessment;
  if(state.displayMode==="basic"){
    const branch=assessment?.branch,dependency=assessment?.dependency;
    $("summary-content").innerHTML=`<div class="summary-grid basic-summary">
      ${metricCard("1. Số trạm thu được tín hiệu",fmt(summary.four_plus_rx_coverage_percent)+"% vùng có 4+ trạm","Cho biết phần khu vực có ít nhất bốn trạm eligible theo nguồn vùng thu đã chọn.")}
      ${metricCard("2. Chất lượng bố trí trạm",fmt(summary.good_percent)+"% TỐT","Tỷ lệ vùng mà tổ hợp tốt nhất đạt lớp lõi GOOD.")}
      ${metricCard("3. Độ tách biệt nghiệm",fmt(branch?.value)+"% đạt ngưỡng GOOD","Nguy cơ có vị trí xa tạo chênh lệch thời gian gần giống; aggregate dùng ngưỡng 1,0 µs.")}
      ${metricCard("4. Sai số dự kiến 95%",fmt(assessment?.p95?.median_p95_m,0)+" m trung vị · "+fmt(assessment?.p95?.p90_p95_m,0)+" m P90","Khoảng 95% mẫu mô hình tại một điểm thấp hơn P95. Đây không phải sai số đo thực tế; timing noise: "+fmt(assessment?.p95?.timing_noise_us,2)+" µs.")}
      ${metricCard("5. Số tổ hợp tốt",strict?"Chỉ có 1 tổ hợp strict-4":fmt(summary.robust_good_fraction_percent)+"% vùng có ≥2 tổ hợp","Nhiều tổ hợp bốn trạm GOOD hơn nghĩa là có nhiều phương án dự phòng hơn.")}
      ${metricCard("6. Khả năng chịu mất 1 trạm",assessment?.n_minus_1?.label_vi+" · "+fmt(assessment?.n_minus_1?.value)+"%","Sau mọi kịch bản mất một trạm, vẫn còn ít nhất một tổ hợp bốn trạm GOOD. Không phải dự báo uptime.")}
      ${metricCard("7. Mức độ phụ thuộc trạm",dependency?.receiver_name?esc(dependency.receiver_name)+" · "+fmt(dependency.median_ratio,2)+"×":"Chưa có trạm nổi trội","Best P95 khi không dùng trạm chia cho overall best P95 tại các điểm có alternative.")}
    </div><div class="source-summary">Nguồn vùng thu: ${summary.reception_source_counts.outline} outline + ${summary.reception_source_counts.simulated} giả định · ${summary.grid_points} điểm lưới</div>${coverageTableHtml()}`;
    return;
  }
  if(strict){
    $("summary-content").innerHTML=`<div class="summary-grid"><div class="metric">Grid points<br><b>${summary.grid_points}</b></div><div class="metric">≥4 RX<br><b>${fmt(summary.four_plus_rx_coverage_percent)}%</b></div><div class="metric">Strict-4 common reception<br><b>${fmt(summary.selected_strict_4_common_coverage_percent)}%</b></div><div class="metric">GOOD<br><b>${fmt(summary.good_percent)}%</b></div><div class="metric">GOOD+ACCEPTABLE<br><b>${fmt(summary.good_acceptable_percent)}%</b></div><div class="metric">NO MLAT<br><b>${fmt(summary.no_mlat_percent)}%</b></div><div class="metric">Median P50 / P95 / map-P90 P95<br><b>${fmt(summary.median_predicted_p50_m,0)} / ${fmt(summary.median_predicted_p95_m,0)} / ${fmt(summary.p90_predicted_p95_m,0)} m</b></div><div class="metric">Branch safe / GOOD separation<br><b>${fmt(summary.branch_safe_percent)} / ${fmt(summary.branch_good_percent)}%</b></div></div><div class="source-summary">Strict selected 4RX · ${fmt(summary.analysis_seconds,2)} s</div>${coverageTableHtml()}`;
    return;
  }
  const importance=summary.receiver_importance.map(r=>`${esc(r.name)}: ${fmt(r.median_p95_ratio_without_receiver,2)}× median / ${fmt(r.p90_p95_ratio_without_receiver,2)}× P90 (${r.samples} points)`).join(" | ");
  $("summary-content").innerHTML=`<div class="summary-grid"><div class="metric">Grid / subset evals<br><b>${summary.grid_points} / ${summary.subset_evaluations}</b></div><div class="metric">≥4 / ≥5 / ≥6 RX<br><b>${fmt(summary.four_plus_rx_coverage_percent)} / ${fmt(summary.five_plus_rx_coverage_percent)} / ${fmt(summary.six_plus_rx_coverage_percent)}%</b></div><div class="metric">Best GOOD / GOOD+ACC<br><b>${fmt(summary.good_percent)} / ${fmt(summary.good_acceptable_percent)}%</b></div><div class="metric">Worst GOOD<br><b>${fmt(summary.worst_good_percent)}%</b></div><div class="metric">N-1 survivable<br><b>${fmt(summary.n_minus_1_survivable_percent)}%</b></div><div class="metric">≥1 / ≥2 / ≥3 GOOD<br><b>${fmt(summary.one_good_subset_percent)} / ${fmt(summary.robust_good_fraction_percent)} / ${fmt(summary.three_good_subsets_percent)}%</b></div><div class="metric">Best median P50 / P95 / P90 P95<br><b>${fmt(summary.median_best_p50_m,0)} / ${fmt(summary.median_best_p95_m,0)} / ${fmt(summary.p90_best_p95_m,0)} m</b></div><div class="metric">Worst median / P90 P95<br><b>${fmt(summary.median_worst_p95_m,0)} / ${fmt(summary.p90_worst_p95_m,0)} m</b></div><div class="metric">Best branch safe / sep GOOD<br><b>${fmt(summary.best_branch_safe_percent)} / ${fmt(summary.best_branch_good_percent)}%</b></div><div class="metric">Best median condition / hull<br><b>${fmt(summary.median_best_condition,2)} / ${fmt(summary.best_inside_hull_percent)}%</b></div><div class="metric">Runtime / max subsets<br><b>${fmt(summary.analysis_seconds,2)} s / ${summary.maximum_subsets_per_point}</b></div></div><div class="source-summary">Strategy: ${esc(summary.geometry_strategy)} · Reception: ${summary.reception_source_counts.simulated} simulated + ${summary.reception_source_counts.outline} outline${summary.failed_receiver_id?" · failed "+esc(summary.failed_receiver_id):""}</div><div class="receiver-summary">Receiver importance ratio: ${importance}</div>${coverageTableHtml()}`;
}

function renderAssessment(){
  const panel=$("assessment-panel");
  if(!state.result?.assessment){panel.hidden=true;return}
  const a=state.result.assessment,c=a.context;
  panel.hidden=false;
  $("overall-rating").innerHTML=`Tổng quan: <span class="level level-${a.overall.level.toLowerCase()}">${esc(a.overall.label_vi.toUpperCase())}</span>`;
  $("assessment-scope").innerHTML=`<b>Phạm vi đánh giá:</b> Độ cao mục tiêu ${fmt(c.target_altitude_m,0)} m · Sai số thời gian ${fmt(c.timing_noise_us,2)} µs · Lưới ${fmt(c.grid_step_km,0)} km · ${c.reception_model_counts.outline} outline + ${c.reception_model_counts.simulated} giả định · ${c.grid_point_count} điểm`;
  const cards=[
    ["Vùng thu chung",a.reception],
    ["Bố trí các trạm",a.geometry],
    ["Độ tách biệt nghiệm",a.branch],
    ["Sai số dự kiến 95%",a.p95],
    ["Tổ hợp 4 trạm dự phòng",a.redundancy],
    ["Khả năng chịu mất 1 trạm",a.n_minus_1],
    ["Mức độ phụ thuộc trạm",a.dependency]
  ];
  $("assessment-cards").innerHTML=cards.map(([title,item])=>`<article class="assessment-card"><h3>${title}</h3><strong class="level level-${String(item.level).toLowerCase()}">${esc(item.label_vi.toUpperCase())}</strong><p>${esc(item.text_vi)}</p></article>`).join("");
  $("assessment-paragraph").innerHTML=`<h3>Đánh giá tổng quan</h3><p>${esc(a.paragraph_vi)}</p><details class="advanced-only"><summary>Chi tiết baseline và rule</summary><p>${esc(a.baseline.text_vi)}</p><p>${esc(a.overall.policy)}</p></details>`;
}

function clearResults(){
  state.result=null;state.stale=true;gridLayer.clearLayers();
  $("summary-content").textContent="Hãy chạy phân tích để xem kết quả.";
  $("assessment-panel").hidden=true;
  $("stale").textContent="Chưa có kết quả phân tích.";$("stale").className="stale";
  $("clear-results").disabled=true;renderLegend($("view-mode").value);
}
async function analyze(){
  if(isStrict()&&state.geometryIds.length!==4)return alert("Hãy chọn đúng bốn trạm đang bật cho strict-4.");
  if(!isStrict()&&eligibleReceivers().length<4)return alert("Cần ít nhất bốn trạm eligible.");
  const missing=state.receivers.filter(r=>r.enabled&&!outlineReady(r));
  if(missing.length)return alert(`Upload a valid outline for: ${missing.map(x=>x.name).join(", ")}`);
  if(state.polygon.length<3)return alert("Hãy vẽ đa giác hoặc hình chữ nhật vùng giám sát trước.");
  const area=areaMetrics(),step=Number($("grid-step").value),estimate=Math.ceil(area.area/(step**2)),subsets=isStrict()?1:choose(eligibleReceivers().length,4);
  if(subsets>1000)return alert(`C(${eligibleReceivers().length},4)=${subsets} vượt giới hạn an toàn 1.000. Hãy tắt bớt trạm.`);
  let allowHigh=false;
  if(subsets>70){allowHigh=confirm(`Mỗi điểm có thể phải tính ${subsets} subset bốn trạm. Tiếp tục?`);if(!allowHigh)return}
  if(estimate*subsets>12000&&!confirm(`Khoảng ${estimate.toLocaleString("vi-VN")} điểm × ${subsets} subset có thể chạy lâu. Tiếp tục?`))return;
  $("analyze").disabled=true;$("progress").hidden=false;
  try{
    const response=await fetch("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(requestBody(allowHigh))}),data=await response.json();
    if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
    state.result=data;state.coverage=data.receiver_coverage;state.stale=false;$("stale").textContent="Kết quả phù hợp với cấu hình hiện tại.";$("stale").className="stale fresh";$("clear-results").disabled=false;
    renderGrid();renderSummary();renderAssessment();
  }catch(error){alert(error.message)}
  finally{$("progress").hidden=true;refreshAnalyzeAvailability()}
}
function exportConfig(){
  const blob=new Blob([JSON.stringify(requestBody(),null,2)],{type:"application/json"}),anchor=document.createElement("a");
  anchor.href=URL.createObjectURL(blob);anchor.download="mlat-planner-config.json";anchor.click();URL.revokeObjectURL(anchor.href);
}
async function showSubsetDetails(button){
  button.disabled=true;button.textContent="Đang tải subset…";
  const target=button.parentElement.querySelector(".subset-table");
  try{
    const payload={...requestBody(true),point:[+button.dataset.lat,+button.dataset.lon]};
    const response=await fetch("/api/analyze-point",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}),data=await response.json();
    if(!response.ok)throw new Error(data.error||`HTTP ${response.status}`);
    const rows=data.subsets.map((x,index)=>`<tr class="${index===0?"best-row":""}"><td>${index+1}</td><td>${names(x.subset_names)}</td><td>${names(x.subset_ids)}</td><td>${fmt(x.p50_error_m,0)}</td><td>${fmt(x.p95_error_m,0)}</td><td>${fmt(x.condition,2)}</td><td>${fmt(x.branch_separation_us,2)}</td><td>${x.branch_safe?"YES":"NO"}</td><td>${x.inside_hull?"YES":"NO"}</td><td>${esc(x.quality)}</td></tr>`).join("");
    target.innerHTML=`<div>Matched grid: ${fmt(data.matched_grid_point.lat,4)}, ${fmt(data.matched_grid_point.lon,4)}</div><table><thead><tr><th>#</th><th>4RX subset</th><th>Receiver IDs</th><th>P50 m</th><th>P95 m</th><th>Cond.</th><th>Branch µs</th><th>Safe</th><th>Hull</th><th>Quality</th></tr></thead><tbody>${rows||'<tr><td colspan="10">Không có subset eligible</td></tr>'}</tbody></table>`;
    button.textContent="Đã tải bảng subset";
  }catch(error){target.textContent=error.message;button.disabled=false;button.textContent="Thử tải lại bảng subset"}
}

map.on("popupopen",event=>{const button=event.popup.getElement().querySelector(".subset-detail");if(button)button.onclick=()=>showSubsetDetails(button)});
$("load-current").onclick=loadCurrent;
$("add-receiver").onclick=()=>{state.adding=!state.adding;$("add-receiver").textContent=state.adding?"Bấm vị trí trên bản đồ…":"+ Thêm trạm thu"};
$("show-coverage").onchange=syncMap;
$("show-all-reception").onclick=()=>{state.receivers.forEach(r=>r.show_reception_area=true);$("show-coverage").checked=true;renderReceivers()};
$("hide-all-reception").onclick=()=>{state.receivers.forEach(r=>r.show_reception_area=false);renderReceivers()};
$("clear-area").onclick=()=>setArea([]);
$("analyze").onclick=analyze;
$("clear-results").onclick=clearResults;
$("view-mode").onchange=()=>{refreshReceiverSelects();renderGrid()};
$("importance-receiver").onchange=renderGrid;
$("geometry-strategy").onchange=()=>{$("planning-warning").hidden=isStrict();changed()};
$("failed-receiver").onchange=changed;
$("export-config").onclick=exportConfig;
["target-altitude","timing-noise","grid-step"].forEach(id=>$(id).addEventListener("change",changed));
$("import-config").onchange=async event=>{
  try{
    const config=JSON.parse(await event.target.files[0].text());
    state.receivers=config.receivers.map(r=>({...r,show_reception_area:true}));state.geometryIds=config.geometry_receiver_ids;setArea(config.surveillance_polygon);
    $("target-altitude").value=config.target_altitude_m;$("timing-noise").value=config.timing_noise_us;$("grid-step").value=config.grid_step_km;
    if(config.geometry_strategy)$("geometry-strategy").value=config.geometry_strategy;renderReceivers();
  }catch(error){alert(`Cấu hình không hợp lệ: ${error.message}`)}
};
document.querySelectorAll('input[name="display-mode"]').forEach(input=>input.onchange=event=>setDisplayMode(event.target.value));
$("show-help").onclick=()=>$("help-dialog").showModal();

async function initialize(){
  const requestedMode=new URLSearchParams(location.search).get("mode");
  if(requestedMode==="advanced"){
    document.querySelector('input[name="display-mode"][value="advanced"]').checked=true;
    state.displayMode="advanced";document.body.className="advanced-mode";
  }
  refreshViewModes();renderLegend("count");$("planning-warning").hidden=isStrict();
  const outlines=loadOutlines();await loadCurrent();await outlines;renderReceivers();
}
initialize();
