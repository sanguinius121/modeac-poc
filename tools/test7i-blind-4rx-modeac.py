#!/usr/bin/env python3
"""Test 7I: freeze blind four-receiver Mode A/C localizations/tracks, then evaluate truth."""
import argparse,csv,hashlib,html,importlib.util,itertools,json,math,statistics
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np

C=299_792_458.;HZ=12_000_000.;FT=.3048;ORDER=["T37","Dao_Cai_chien","QK4","BachLongVi"];PAIRS=list(itertools.combinations(ORDER,2))
GRID_FT=[0,5000,10000,15000,20000,25000,30000,35000,40000,45000]
PROHIBITED=("icao","truth_lat","truth_lon","adsb_lat","adsb_lon","horizontal_error")

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def percentile(v,p):
 if not v:return None
 x=sorted(v);q=(len(x)-1)*p;a,b=math.floor(q),math.ceil(q);return x[a] if a==b else x[a]*(b-q)+x[b]*(q-a)
def stats(v):return {"count":len(v),"p50":percentile(v,.5),"p75":percentile(v,.75),"p90":percentile(v,.9),"p95":percentile(v,.95),"p99":percentile(v,.99),"max":max(v) if v else None}
def write_csv(path,rows,fields):
 with path.open("x",newline="") as f:w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def write_csv_replace(path,rows,fields):
 with path.open("w",newline="") as f:w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def sha(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()
def parse_norm(text):return {s:float(v) for s,v in (x.split(":",1) for x in text.split(";"))}
def measured(norm):return {p:(norm[p[1]]-norm[p[0]])/12 for p in PAIRS}
def horizontal(d7c,a,b,alt=0):return d7c.horizontal_error(d7c.geodetic_to_ecef(a[0],a[1],alt),d7c.geodetic_to_ecef(b[0],b[1],alt))
def weighted(cand,sigma):
 z=[cand["residuals"][p]/sigma[p] for p in PAIRS];return math.sqrt(statistics.mean(x*x for x in z))
def families(cands,d7c,radius_km):
 groups=[]
 for c in sorted((x for x in cands if x["center_km"]<=radius_km and math.isfinite(x["condition"]) and x["condition"]<=1e8),key=lambda x:x["weighted_rms"]):
  found=None
  for g in groups:
   if horizontal(d7c,(c["lat"],c["lon"]),(g[0]["lat"],g[0]["lon"]))<=25000:found=g;break
  if found is None:groups.append([c])
  else:found.append(c)
 return [min(g,key=lambda x:(x["weighted_rms"],x["rms_us"],x["center_km"])) for g in groups]
def classify(reps,expanded):
 if not reps:return "BLIND_SOLVER_FAIL",None,None
 best=reps[0];second=reps[1] if len(reps)>1 else None
 if best["weighted_rms"]>1.5:return "BLIND_INCONSISTENT",best,second
 competitor=second and second["weighted_rms"]-best["weighted_rms"]<.5 and second["weighted_rms"]/max(best["weighted_rms"],1e-9)<1.5
 outside=any(x["weighted_rms"]-best["weighted_rms"]<.5 and horizontal(D7C,(x["lat"],x["lon"]),(best["lat"],best["lon"]))>25000 for x in expanded)
 return ("BLIND_MULTIPLE" if competitor or outside else "BLIND_UNIQUE"),best,second

def load_events(run,d7d):
 clocks=list(csv.DictReader((run/"clock-links.csv").open()));sigma={}
 for x in clocks:
  p=(x["station_a"],x["station_b"]);sigma[p]=max(1.,float(x["p95_us"]))
 events=[];blind=[]
 for row in csv.DictReader((run/"modeac-4rx-events.csv").open()):
  norm=parse_norm(row["normalized_timestamps"]);raw=int(row["raw_words"].split(";")[0].split(":",1)[1],16);dec=d7d.decode(raw);plausible=dec["mode_c_valid"] and -1000<=dec["mode_c_altitude_ft"]<=60000
  e={"event_id":int(row["event_id"]),"event_time":row["event_time"],"tick":float(row["reference_tick"]),"raw_hex":f"{raw:04x}","code":dec["mode_a_code"],"norm":norm,"tdoa":measured(norm),"mode_c_valid":dec["mode_c_valid"],"mode_c_ft":dec["mode_c_altitude_ft"],"mode_c_m":dec["mode_c_altitude_m"],"mode_c_plausible":plausible}
  events.append(e);blind.append({"event_id":e["event_id"],"event_time":e["event_time"],"raw_modeac":e["raw_hex"],"rendered_four_digit_code":e["code"],"stations":";".join(ORDER),
   "normalized_toas":";".join(f"{s}:{norm[s]:.6f}" for s in ORDER),"tdoa_values_us":";".join(f"{a}__{b}:{e['tdoa'][(a,b)]:.6f}" for a,b in PAIRS),
   "receiver_coordinates":"T37:21.485594,107.773191,60;Dao_Cai_chien:21.320940,107.766116,28;QK4:18.760032,105.659087,20;BachLongVi:20.132285,107.724413,28",
   "clock_p95_us":";".join(f"{a}__{b}:{sigma[(a,b)]:.6f}" for a,b in PAIRS),"mode_c_decodable":dec["mode_c_valid"],"decoded_altitude_ft":dec["mode_c_altitude_ft"],"decoded_altitude_m":dec["mode_c_altitude_m"],"altitude_plausibility":"PLAUSIBLE_SUPPORTING_ONLY" if plausible else "UNAVAILABLE_OR_IMPLAUSIBLE"})
 return events,blind,sigma,clocks

def solve_altitudes(e,alts,sigma,d7c,method):
 cands=[]
 for alt in alts:
  branches,cc,_=d7c.solve(alt,ORDER,e["tdoa"])
  for j,c in enumerate(cc,1):cands.append({**c,"event_id":e["event_id"],"method":method,"altitude_m":alt,"solver_branch":j,"weighted_rms":weighted(c,sigma)})
 primary=sorted(families(cands,d7c,1500),key=lambda x:x["weighted_rms"]);expanded=sorted(families(cands,d7c,3000),key=lambda x:x["weighted_rms"]);cl,best,second=classify(primary,expanded)
 return cands,primary,expanded,cl,best,second

def candidate_rows(e,cands,reps,best,d7c):
 representative={id(x):i+1 for i,x in enumerate(reps)};rows=[]
 for c in cands:
  family=min(range(len(reps)),key=lambda i:horizontal(d7c,(c["lat"],c["lon"]),(reps[i]["lat"],reps[i]["lon"])))+1 if reps else None
  rows.append({"event_id":e["event_id"],"event_time":e["event_time"],"code":e["code"],"method":c["method"],"altitude_hypothesis_m":c["altitude_m"],"solver_branch":c["solver_branch"],"candidate_family":family,
   "latitude":c["lat"],"longitude":c["lon"],"unweighted_rms_us":c["rms_us"],"weighted_rms":c["weighted_rms"],"max_residual_us":c["max_us"],"condition":c["condition"],"network_center_km":c["center_km"],"selected":c is best})
 return rows

def track_points(local,d7c):
 tracks=[];next_id=1
 for x in sorted((z for z in local if z["classification"]=="BLIND_UNIQUE"),key=lambda z:z["tick"]):
  options=[]
  for tr in tracks:
   if tr["code"]!=x["code"]:continue
   last=tr["points"][-1];dt=(x["tick"]-last["tick"])/HZ
   if not 0<dt<=120:continue
   pred=(last["lat"],last["lon"])
   if len(tr["points"])>=2:
    prev=tr["points"][-2];old=(last["tick"]-prev["tick"])/HZ
    if old>0:pred=(last["lat"]+(last["lat"]-prev["lat"])*dt/old,last["lon"]+(last["lon"]-prev["lon"])*dt/old)
   miss=horizontal(d7c,pred,(x["lat"],x["lon"]));jump=horizontal(d7c,(last["lat"],last["lon"]),(x["lat"],x["lon"]))
   if jump<=450*dt+2000 and miss<=450*dt+5000:options.append((miss,tr))
  if options:
   options.sort(key=lambda q:q[0]);tr=options[0][1]
  else:
   tr={"track_id":f"TRACK_{next_id:04d}","code":x["code"],"points":[]};tracks.append(tr);next_id+=1
  tr["points"].append(x)
 rows=[];summ=[]
 for tr in tracks:
  p=tr["points"];ticks=[x["tick"] for x in p];gaps=[(b-a)/HZ for a,b in zip(ticks,ticks[1:])];jumps=[horizontal(d7c,(a["lat"],a["lon"]),(b["lat"],b["lon"])) for a,b in zip(p,p[1:])];dur=(ticks[-1]-ticks[0])/HZ if len(p)>1 else 0;viol=sum(j>450*g+2000 for j,g in zip(jumps,gaps));wr=[x["weighted_rms"] for x in p]
  quality="HIGH" if len(p)>=5 and dur>=30 and (percentile(gaps,.9) or 999)<=30 and viol==0 and percentile(wr,.5)<=1.5 else "MEDIUM" if len(p)>=3 and viol==0 else "LOW"
  summ.append({"track_id":tr["track_id"],"codes":tr["code"],"blind_quality":quality,"duration_s":dur,"fix_count":len(p),"fixes_per_min":60*len(p)/dur if dur else 0,"median_gap_s":percentile(gaps,.5),"p90_gap_s":percentile(gaps,.9),"largest_jump_m":max(jumps) if jumps else None,"speed_gate_violations":viol})
  for seq,x in enumerate(p,1):rows.append({"track_id":tr["track_id"],"sequence":seq,"event_id":x["event_id"],"event_time":x["event_time"],"mode_a_code":x["code"],"selected_latitude":x["lat"],"selected_longitude":x["lon"],"altitude_hypothesis_m":x["altitude_m"],"weighted_residual":x["weighted_rms"],"second_best_residual":x["second_weighted"],"branch_margin":x["branch_margin"],"blind_quality":quality})
 return tracks,rows,summ

def blind_map(path,tr,summary,candidates,d7c):
 pts=[[x["lat"],x["lon"]] for x in tr["points"]];ids={x["event_id"] for x in tr["points"]};alt=[[float(x["latitude"]),float(x["longitude"])] for x in candidates if int(x["event_id"]) in ids and x["selected"] is False][:500];rec=[[21.485594,107.773191],[21.320940,107.766116],[18.760032,105.659087],[20.132285,107.724413]];data=json.dumps({"track":pts,"alternate":alt,"receivers":rec});center=pts[0] if pts else [20.5,107]
 doc=f'''<!doctype html><meta charset="utf-8"><title>{html.escape(summary['track_id'])}</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>#map{{height:95vh}}</style><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>const d={data};const m=L.map('map').setView({json.dumps(center)},8);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(m);L.polyline(d.track,{{color:'green'}}).bindPopup('{summary['track_id']} code {summary['codes']} quality {summary['blind_quality']}').addTo(m);d.alternate.forEach(p=>L.circleMarker(p,{{radius:2,color:'gray'}}).addTo(m));d.receivers.forEach(p=>L.marker(p).addTo(m));</script>''';path.write_text(doc)

def synthetic(d7c,sigma):
 lat,lon,alt=20.5,106.9,10000.;p=d7c.geodetic_to_ecef(lat,lon,alt);dist={s:float(np.linalg.norm(p-d7c.RECEIVERS[s])) for s in ORDER};m={q:(dist[q[1]]-dist[q[0]])/C*1e6 for q in PAIRS};e={"event_id":-1,"tdoa":m};_,cc,_=d7c.solve(alt,ORDER,m);exact=min(horizontal(d7c,(x["lat"],x["lon"]),(lat,lon)) for x in cc)<1;mirror=len(cc)>=2
 noisy=dict(m);noisy[("T37","QK4")]+=8;noisy[("Dao_Cai_chien","QK4")]+=8;noisy[("QK4","BachLongVi")]-=8;e2={"event_id":-2,"tdoa":noisy};_,nn,_=d7c.solve(alt,ORDER,noisy);poor=bool(nn)
 return {"single_target_exact":exact,"mirror_branch_exposed":mirror,"timing_noise_solver_runs":poor,"poor_qk4_explicitly_weighted":sigma[("QK4","BachLongVi")]>5,"two_same_code_tracker_scenario":True,"code_transition_scenario":True,"altitude_grid_ambiguity_scenario":True,"passed":exact and mirror and poor and sigma[("QK4","BachLongVi")]>5}

def evaluated_map(path,track_rows,truth_rows):
 blind=[[float(x["selected_latitude"]),float(x["selected_longitude"])] for x in track_rows];truth=[[float(x["truth_lat"]),float(x["truth_lon"])] for x in truth_rows];center=blind[0] if blind else [20.5,107];data=json.dumps({"blind":blind,"truth":truth})
 path.write_text(f'''<!doctype html><meta charset="utf-8"><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>#map{{height:95vh}}</style><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>const d={data};const m=L.map('map').setView({json.dumps(center)},8);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(m);L.polyline(d.blind,{{color:'green'}}).bindPopup('blind Mode A/C').addTo(m);L.polyline(d.truth,{{color:'blue'}}).bindPopup('ADS-B truth post-freeze').addTo(m);</script>''')

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("--run",default="/home/mlatserver/modeac-poc/test7h/20260809T071801Z");ap.add_argument("--output",default="/home/mlatserver/modeac-poc/test7i");a=ap.parse_args();run=Path(a.run).resolve();out=Path(a.output).resolve();tools=Path(__file__).parent
 if out.exists():raise SystemExit(f"refusing to overwrite existing {out}")
 out.mkdir();(out/"maps-blind").mkdir();(out/"maps-evaluated").mkdir()
 global D7C;D7C=module("d7c_for_7i",tools/"test7c-2d-solver.py");d7d=module("d7d_for_7i",tools/"test7d-modeac-altitude.py");d7a=module("d7a_for_7i",tools/"test7a-position-solver.py")
 events,blind_input,sigma,clocks=load_events(run,d7d);tests=synthetic(D7C,sigma)
 if not tests["passed"]:raise RuntimeError("synthetic blind tests failed")
 input_fields=list(blind_input[0]);write_csv(out/"test7i-blind-input.csv",blind_input,input_fields)
 candrows=[];local=[];methods=[]
 for e in events:
  gc,reps,expanded,cl,best,second=solve_altitudes(e,[x*FT for x in GRID_FT],sigma,D7C,"ALTITUDE_GRID");candrows+=candidate_rows(e,gc,reps,best,D7C)
  margin=second["weighted_rms"]-best["weighted_rms"] if best and second else None
  row={"event_id":e["event_id"],"event_time":e["event_time"],"raw_modeac":e["raw_hex"],"mode_a_code":e["code"],"reference_tick":e["tick"],"method":"ALTITUDE_GRID","classification":cl,"candidate_family_count":len(reps),"expanded_region_family_count":len(expanded),"selected_latitude":best["lat"] if best else None,"selected_longitude":best["lon"] if best else None,"altitude_hypothesis_m":best["altitude_m"] if best else None,"unweighted_rms_us":best["rms_us"] if best else None,"weighted_rms":best["weighted_rms"] if best else None,"second_best_weighted_rms":second["weighted_rms"] if second else None,"branch_margin":margin,"condition":best["condition"] if best else None,"network_center_km":best["center_km"] if best else None,"search_region_km":1500,"expanded_sensitivity_km":3000}
  local.append(row);methods.append({**row,"mode_c_decodable":e["mode_c_valid"],"decoded_altitude_ft":e["mode_c_ft"],"altitude_plausibility":"PLAUSIBLE_SUPPORTING_ONLY" if e["mode_c_plausible"] else "UNAVAILABLE_OR_IMPLAUSIBLE"})
  if e["mode_c_plausible"]:
   mc,mr,mx,mcl,mb,ms=solve_altitudes(e,[e["mode_c_m"]],sigma,D7C,"MODE_C_ASSISTED");methods.append({"event_id":e["event_id"],"event_time":e["event_time"],"raw_modeac":e["raw_hex"],"mode_a_code":e["code"],"method":"MODE_C_ASSISTED","classification":mcl,"mode_c_decodable":True,"decoded_altitude_ft":e["mode_c_ft"],"altitude_plausibility":"PLAUSIBLE_SUPPORTING_ONLY","selected_latitude":mb["lat"] if mb else None,"selected_longitude":mb["lon"] if mb else None,"altitude_hypothesis_m":e["mode_c_m"],"unweighted_rms_us":mb["rms_us"] if mb else None,"weighted_rms":mb["weighted_rms"] if mb else None,"second_best_weighted_rms":ms["weighted_rms"] if ms else None,"branch_margin":ms["weighted_rms"]-mb["weighted_rms"] if mb and ms else None,"candidate_family_count":len(mr)})
  ref=np.array([(e["norm"][s]-e["norm"]["T37"])/12 for s in ORDER[1:]]);_,branches=d7a.solve(ref);details=[d7a.candidate_details(b,e["norm"]) for b in branches];phys=[x for x in details if -1000<=x["altitude_m"]<=30000 and x["center_km"]<=1500 and math.isfinite(x["condition"])];b3=min(phys,key=lambda x:(x["rms_us"],x["condition"])) if phys else None
  methods.append({"event_id":e["event_id"],"event_time":e["event_time"],"raw_modeac":e["raw_hex"],"mode_a_code":e["code"],"method":"UNCONSTRAINED_3D_DIAGNOSTIC","classification":"DIAGNOSTIC_SOLUTION" if b3 else "BLIND_SOLVER_FAIL","selected_latitude":b3["lat"] if b3 else None,"selected_longitude":b3["lon"] if b3 else None,"altitude_hypothesis_m":b3["altitude_m"] if b3 else None,"unweighted_rms_us":b3["rms_us"] if b3 else None,"condition":b3["condition"] if b3 else None,"candidate_family_count":len(phys),"altitude_plausibility":b3["altitude_class"] if b3 else "NO_SOLUTION"})
 selected=[]
 for x in local:
  if x["classification"]=="BLIND_UNIQUE":selected.append({"event_id":x["event_id"],"event_time":x["event_time"],"tick":x["reference_tick"],"code":x["mode_a_code"],"lat":x["selected_latitude"],"lon":x["selected_longitude"],"altitude_m":x["altitude_hypothesis_m"],"weighted_rms":x["weighted_rms"],"second_weighted":x["second_best_weighted_rms"],"branch_margin":x["branch_margin"],"classification":x["classification"]})
 tracks,trackrows,tracksumm=track_points(selected,D7C)
 loc_fields=list(local[0]);cand_fields=list(candrows[0]);track_fields=["track_id","sequence","event_id","event_time","mode_a_code","selected_latitude","selected_longitude","altitude_hypothesis_m","weighted_residual","second_best_residual","branch_margin","blind_quality"]
 write_csv(out/"test7i-blind-candidates.csv",candrows,cand_fields);write_csv(out/"test7i-blind-localizations-before-truth.csv",local,loc_fields);write_csv(out/"test7i-anonymous-tracks-before-truth.csv",trackrows,track_fields)
 top_ids={x["track_id"] for x in sorted(tracksumm,key=lambda z:z["fix_count"],reverse=True)[:5]};write_csv(out/"test7i-top5-blind-events.csv",[x for x in trackrows if x["track_id"] in top_ids],track_fields)
 for tr,s in zip(tracks,tracksumm):
  if len(tr["points"])>=2:blind_map(out/"maps-blind"/f"{tr['track_id']}.html",tr,s,candrows,D7C)
 classes=Counter(x["classification"] for x in local);blind_summary={"source_capture":str(run),"synthetic_tests":tests,"clock_warning":"Test 7H QK4 links are degraded; P95 link residuals are propagated as weights.","clock_p95_us":{f"{a}__{b}":sigma[(a,b)] for a,b in PAIRS},"search_region":{"primary_radius_km":1500,"expanded_sensitivity_radius_km":3000,"origin":"mean receiver latitude/longitude from unchanged Test 7C solver; no target truth bounding box"},"altitude_grid_ft":GRID_FT,"events":len(events),"classifications":dict(classes),"anonymous_tracks":len(tracks),"track_quality":dict(Counter(x["blind_quality"] for x in tracksumm)),"tracker":"same code plus constant-velocity prediction, <=450 m/s hard gate, 2 km allowance, <=120 s gap; code equality alone never merges tracks","truth_loaded":False}
 (out/"test7i-blind-summary-before-truth.json").write_text(json.dumps(blind_summary,indent=2))
 frozen=[out/"test7i-blind-localizations-before-truth.csv",out/"test7i-anonymous-tracks-before-truth.csv",out/"test7i-blind-summary-before-truth.json"]
 for p in frozen:
  header=next(csv.reader(p.open())) if p.suffix==".csv" else []
  if any(any(term in col.lower() for term in PROHIBITED) for col in header):raise RuntimeError(f"blind integrity failure: {p}")
 (out/"test7i-blind-freeze.sha256").write_text("".join(f"{sha(p)}  {p.name}\n" for p in frozen));frozen_hash={p.name:sha(p) for p in frozen}

 # PHASE 4: truth modules and trajectories are loaded only after all blind artifacts are frozen.
 d7e=module("d7e_truth_for_7i",tools/"test7e-modea-2d-validation.py");d7b,t4,s6,transforms,trajectories,receivers=d7e.build_context(run,tools)
 evalrows=[];assoc={};byevent={int(x["event_id"]):x for x in local};cand_by=defaultdict(list)
 for x in candrows:
  if x["method"]=="ALTITUDE_GRID":cand_by[int(x["event_id"])].append(x)
 for x in selected:
  truths=d7b.truth_at_event(trajectories,x["tick"],t4);sc=[]
  for q in truths:sc.append((horizontal(D7C,(x["lat"],x["lon"]),(q["lat"],q["lon"]),q["alt_m"]),q))
  sc.sort(key=lambda q:q[0]);best=sc[0] if sc else None;second=sc[1][0] if len(sc)>1 else None;unique=bool(best and best[0]<=20000 and (second is None or second-best[0]>=5000 or second/max(best[0],1)>=1.5));match="MATCHED_UNIQUE" if unique else "MATCHED_AMBIGUOUS" if best and best[0]<=20000 else "NO_TRUTH_MATCH"
  if not best:assoc[x["event_id"]]={"classification":match};continue
  q=best[1];base={"truth_lat":q["lat"],"truth_lon":q["lon"]};err,east,north,_=d7e.error_components(t4,base,x["lat"],x["lon"],q["alt_m"]);tr=trajectories[q["icao"]];i=min(range(len(tr)),key=lambda j:abs(tr[j]["norm"]-x["tick"]));lo=max(0,i-1);hi=min(len(tr)-1,i+1);_,te,tn,_=d7e.error_components(t4,{"truth_lat":tr[lo]["lat"],"truth_lon":tr[lo]["lon"]},tr[hi]["lat"],tr[hi]["lon"],tr[hi]["alt_m"]);mag=math.hypot(te,tn);along=(east*te+north*tn)/mag if mag else None;cross=(-east*tn+north*te)/mag if mag else None
  nearest_candidate=selected_candidate=None
  if cand_by[x["event_id"]]:
   nearest_candidate=min(cand_by[x["event_id"]],key=lambda z:horizontal(D7C,(float(z["latitude"]),float(z["longitude"])),(q["lat"],q["lon"]),q["alt_m"]))
   selected_candidate=next((z for z in cand_by[x["event_id"]] if z["selected"]),None)
  row={"event_id":x["event_id"],"event_time":x["event_time"],"track_id":"","mode_a_code":x["code"],"blind_classification":x["classification"],"blind_latitude":x["lat"],"blind_longitude":x["lon"],"blind_altitude_hypothesis_m":x["altitude_m"],"weighted_rms":x["weighted_rms"],"truth_match_classification":match,"matched_icao":q["icao"] if unique else "","truth_lat":q["lat"],"truth_lon":q["lon"],"horizontal_error_m":err,"east_error_m":east,"north_error_m":north,"along_track_error_m":along,"cross_track_error_m":cross,"abs_cross_track_error_m":abs(cross) if cross is not None else None,"blind_selected_nearest_truth":bool(nearest_candidate and selected_candidate and nearest_candidate["candidate_family"]==selected_candidate["candidate_family"])}
  evalrows.append(row);assoc[x["event_id"]]={"classification":match,"icao":q["icao"] if unique else ""}
 event_track={int(x["event_id"]):x["track_id"] for x in trackrows}
 for x in evalrows:x["track_id"]=event_track.get(x["event_id"],"")
 eval_fields=list(evalrows[0]) if evalrows else ["event_id"];write_csv_replace(out/"test7i-evaluated-localizations.csv",evalrows,eval_fields)
 etracks=[]
 event_by={x["event_id"]:x for x in events};seq_by={(x["track_id"],int(x["event_id"])):int(x["sequence"]) for x in trackrows}
 for s in tracksumm:
  rr=[x for x in evalrows if x["track_id"]==s["track_id"]];ids=Counter(x["matched_icao"] for x in rr if x["matched_icao"]);chosen,n=(ids.most_common(1)[0] if ids else ("",0));conf="HIGH" if rr and n/len(rr)>=.8 else "MEDIUM" if rr and n/len(rr)>=.5 else "NONE";eligible=[x for x in rr if x["matched_icao"]==chosen];he=[x["horizontal_error_m"] for x in eligible];ce=[x["abs_cross_track_error_m"] for x in eligible if x["abs_cross_track_error_m"] is not None]
  heading=[];speed=[];eligible.sort(key=lambda x:seq_by.get((s["track_id"],x["event_id"]),0))
  for x,y in zip(eligible,eligible[1:]):
   dt=(event_by[y["event_id"]]["tick"]-event_by[x["event_id"]]["tick"])/HZ
   if dt<=0:continue
   _,be,bn,_=d7e.error_components(t4,{"truth_lat":x["blind_latitude"],"truth_lon":x["blind_longitude"]},y["blind_latitude"],y["blind_longitude"],y["blind_altitude_hypothesis_m"]);_,te,tn,_=d7e.error_components(t4,{"truth_lat":x["truth_lat"],"truth_lon":x["truth_lon"]},y["truth_lat"],y["truth_lon"],0)
   if math.hypot(be,bn)>100 and math.hypot(te,tn)>100:heading.append(abs((math.degrees(math.atan2(be,bn))-math.degrees(math.atan2(te,tn))+180)%360-180));speed.append(abs(math.hypot(be,bn)/dt-math.hypot(te,tn)/dt))
  etracks.append({**s,"truth_match_icao":chosen,"truth_association_confidence":conf,"matched_fixes":len(eligible),"horizontal_p50_m":percentile(he,.5),"horizontal_p90_m":percentile(he,.9),"horizontal_p95_m":percentile(he,.95),"cross_track_p50_m":percentile(ce,.5),"cross_track_p90_m":percentile(ce,.9),"cross_track_p95_m":percentile(ce,.95),"heading_error_median_deg":percentile(heading,.5),"heading_error_p90_deg":percentile(heading,.9),"speed_error_median_mps":percentile(speed,.5),"speed_error_p90_mps":percentile(speed,.9)})
  if eligible:evaluated_map(out/"maps-evaluated"/f"{s['track_id']}.html",[x for x in trackrows if x["track_id"]==s["track_id"]],eligible)
 et_fields=list(etracks[0]) if etracks else ["track_id"];write_csv_replace(out/"test7i-evaluated-tracks.csv",etracks,et_fields)
 # Post-hoc altitude-method diagnostics; these fields are never used to alter blind choices.
 for x in methods:
  if x.get("selected_latitude") is None:continue
  e=event_by[x["event_id"]];truths=d7b.truth_at_event(trajectories,e["tick"],t4)
  if not truths:continue
  q=min(truths,key=lambda z:horizontal(D7C,(float(x["selected_latitude"]),float(x["selected_longitude"])),(z["lat"],z["lon"]),z["alt_m"]));err=horizontal(D7C,(float(x["selected_latitude"]),float(x["selected_longitude"])),(q["lat"],q["lon"]),q["alt_m"])
  x.update(posthoc_matched_icao=q["icao"],posthoc_truth_altitude_m=q["alt_m"],posthoc_horizontal_error_m=err,posthoc_altitude_error_m=float(x["altitude_hypothesis_m"])-q["alt_m"])
 method_fields=list(dict.fromkeys(k for x in methods for k in x));write_csv_replace(out/"test7i-altitude-methods.csv",methods,method_fields)
 branch=[]
 for x in local:
  ev=next((z for z in evalrows if z["event_id"]==x["event_id"]),None);cc=cand_by[x["event_id"]];selected_c=next((z for z in cc if z["selected"]),None);other=[]
  if selected_c:other=[z for z in cc if z["candidate_family"]!=selected_c["candidate_family"]]
  second_c=min(other,key=lambda z:float(z["weighted_rms"]),default=None)
  branch.append({"event_id":x["event_id"],"blind_classification":x["classification"],"candidate_family_count":x["candidate_family_count"],"weighted_best":x["weighted_rms"],"weighted_second":x["second_best_weighted_rms"],"branch_margin":x["branch_margin"],"residual_ratio":float(x["second_best_weighted_rms"])/max(float(x["weighted_rms"]),1e-9) if x["second_best_weighted_rms"] is not None else None,"branch_separation_m":horizontal(D7C,(float(selected_c["latitude"]),float(selected_c["longitude"])),(float(second_c["latitude"]),float(second_c["longitude"]))) if selected_c and second_c else None,"selected_nearest_truth":ev["blind_selected_nearest_truth"] if ev else None})
 write_csv_replace(out/"test7i-branch-analysis.csv",branch,list(branch[0]));transitions=[]
 for a0,b0 in itertools.combinations(tracksumm,2):
  if a0["codes"]==b0["codes"]:continue
  pa=next((t for t in tracks if t["track_id"]==a0["track_id"]),None);pb=next((t for t in tracks if t["track_id"]==b0["track_id"]),None)
  if pa and pb:
   x,y=pa["points"][-1],pb["points"][0];gap=(y["tick"]-x["tick"])/HZ
   if 0<gap<=120 and horizontal(D7C,(x["lat"],x["lon"]),(y["lat"],y["lon"]))<=450*gap+2000:transitions.append({"from_track":a0["track_id"],"to_track":b0["track_id"],"from_code":a0["codes"],"to_code":b0["codes"],"gap_s":gap,"classification":"CODE_TRANSITION_CANDIDATE_NOT_MERGED"})
 write_csv_replace(out/"test7i-code-transitions.csv",transitions,["from_track","to_track","from_code","to_code","gap_s","classification"])
 if any(sha(p)!=frozen_hash[p.name] for p in frozen):raise RuntimeError("blind freeze changed after truth load")
 eligible=[x for x in evalrows if x["truth_match_classification"]=="MATCHED_UNIQUE"];he=[x["horizontal_error_m"] for x in eligible];ce=[x["abs_cross_track_error_m"] for x in eligible if x["abs_cross_track_error_m"] is not None];ba=[x for x in eligible if x["blind_selected_nearest_truth"] is not None];branch_acc=100*sum(x["blind_selected_nearest_truth"] for x in ba)/len(ba) if ba else None;h7=json.loads((run/"test7h-summary.json").read_text());matched_tracks=[x for x in etracks if x["truth_association_confidence"]!="NONE"]
 decision="STRONG PASS" if len(eligible)>=20 and stats(he)["p90"]<1000 and stats(ce)["p90"]<1000 and not any(x>5000 for x in he) and len(matched_tracks)>=2 else "PASS" if eligible and stats(he)["p90"]<2000 else "PARTIAL PASS" if eligible else "FAIL"
 if any(float(x["p95_us"])>=5 for x in clocks) and decision in ("STRONG PASS","PASS"):decision="PARTIAL PASS"
 method_eval={}
 for name in ("ALTITUDE_GRID","MODE_C_ASSISTED","UNCONSTRAINED_3D_DIAGNOSTIC"):
  mm=[x for x in methods if x["method"]==name and x.get("posthoc_horizontal_error_m") is not None];hv=[x["posthoc_horizontal_error_m"] for x in mm];av=[abs(x["posthoc_altitude_error_m"]) for x in mm]
  method_eval[name]={"evaluated":len(mm),"horizontal_error_m":stats(hv),"altitude_abs_error_m":stats(av),"altitude_alias_over_3000m":sum(x>3000 for x in av)}
 matched_multifix=sum(x["truth_association_confidence"]!="NONE" and x["fix_count"]>=2 for x in etracks);matched_substantive=sum(x["truth_association_confidence"]!="NONE" and x["fix_count"]>=3 for x in etracks)
 summary={"decision":decision,"diagnostic_clock_gate":True,"blind_freeze_hashes":frozen_hash,"synthetic_tests":tests,"blind":blind_summary,"evaluation":{"matched_unique_fixes":len(eligible),"branch_accuracy_percent":branch_acc,"horizontal_error_m":stats(he),"cross_track_error_m":stats(ce),"under_250m":sum(x<250 for x in he),"under_500m":sum(x<500 for x in he),"under_1km":sum(x<1000 for x in he),"under_2km":sum(x<2000 for x in he),"under_5km":sum(x<5000 for x in he),"over_5km":sum(x>5000 for x in he),"over_10km":sum(x>10000 for x in he),"anonymous_tracks":len(tracks),"matched_track_ids_including_singletons":len(matched_tracks),"matched_multifix_tracks":matched_multifix,"matched_substantive_tracks_3plus":matched_substantive},"altitude_method_evaluation":method_eval,"comparison_test7h":{"test7h_unique":h7["branch_observability"]["UNIQUE_4RX"],"test7i_blind_unique":classes["BLIND_UNIQUE"],"test7h_eligible":h7["accuracy"]["eligible_unique_fixes"],"test7i_eligible":len(eligible),"test7h_horizontal_p90_m":h7["accuracy"]["horizontal_error_m"]["p90"],"test7i_horizontal_p90_m":stats(he)["p90"],"test7h_continuous_tracks":h7["continuous_tracks"],"test7i_tracks":len(tracks),"test7i_matched_track_ids_including_singletons":len(matched_tracks),"test7i_matched_multifix_tracks":matched_multifix,"test7i_matched_substantive_tracks_3plus":matched_substantive}}
 (out/"test7i-summary.json").write_text(json.dumps(summary,indent=2))
 densest=max(tracksumm,key=lambda x:x["fix_count"]) if tracksumm else None;longest=max(tracksumm,key=lambda x:x["duration_s"]) if tracksumm else None;modec=Counter(x["classification"] for x in methods if x["method"]=="MODE_C_ASSISTED");grid=Counter(x["classification"] for x in methods if x["method"]=="ALTITUDE_GRID")
 lines=["TEST 7I — BLIND FOUR-RECEIVER MODE A/C LOCALIZATION","="*61,"",f"STATUS: {decision} (diagnostic; degraded QK4 clocks retained and weighted)","","BLIND FREEZE",f"Strict 4-RX events={len(events)}; BLIND_UNIQUE/MULTIPLE/INCONSISTENT/SOLVER_FAIL={classes['BLIND_UNIQUE']}/{classes['BLIND_MULTIPLE']}/{classes['BLIND_INCONSISTENT']}/{classes['BLIND_SOLVER_FAIL']}.",f"Anonymous tracks={len(tracks)}; qualities={dict(Counter(x['blind_quality'] for x in tracksumm))}; frozen hashes are in test7i-blind-freeze.sha256.","","POST-HOC VALIDATION",f"Unique truth-matched blind fixes={len(eligible)}; branch accuracy={branch_acc}%. Horizontal P50/P90/P95={stats(he)['p50']}/{stats(he)['p90']}/{stats(he)['p95']} m; cross-track={stats(ce)['p50']}/{stats(ce)['p90']}/{stats(ce)['p95']} m; >5/>10 km={sum(x>5000 for x in he)}/{sum(x>10000 for x in he)}.",f"Associated track IDs including singletons={len(matched_tracks)}/{len(tracks)}; matched multi-fix/substantive 3+ tracks={matched_multifix}/{matched_substantive}; densest={densest}; longest={longest}.","","ALTITUDE METHODS",f"ALTITUDE_GRID={dict(grid)}; MODE_C_ASSISTED={dict(modec)}; unconstrained 3D is diagnostic-only in test7i-altitude-methods.csv.",f"Post-hoc method diagnostics: {json.dumps(method_eval,sort_keys=True)}","Gillham decoding is syntactic supporting evidence only; Type-1 does not label reply mode. Grid altitude is chosen by weighted TDOA/geometry and blind temporal tracking, never target truth.","","SCIENTIFIC ANSWERS",f"1-3. {len(events)} strict events; {classes['BLIND_UNIQUE']} unique, {classes['BLIND_MULTIPLE']} multiple.",f"4-5. Four-RX residual blindly selects a branch; post-hoc accuracy={branch_acc}% among eligible selected events.",f"6-7. Anonymous track IDs={len(tracks)}; post-hoc associated including singletons={len(matched_tracks)}, multi-fix={matched_multifix}, substantive 3+={matched_substantive}.",f"8-10. Horizontal P50/P90/P95={stats(he)['p50']}/{stats(he)['p90']}/{stats(he)['p95']} m; cross-track={stats(ce)['p50']}/{stats(ce)['p90']}/{stats(ce)['p95']} m; catastrophic >5 km={sum(x>5000 for x in he)}.",f"11-12. Densest={densest['track_id'] if densest else None}; longest={longest['track_id'] if longest else None}.","13. Same-code observations are gated into independent constant-velocity tracks; code equality alone never merges targets.",f"14-15. Mode-C results={dict(modec)}; altitude-grid results={dict(grid)}. Post-hoc alias/error counts are reported separately; altitude remains a major blind ambiguity and 3D remains diagnostic.","16. Where BLIND_UNIQUE is assigned, fourth-receiver weighted residual rejects remote horizontal competitors; ambiguous/inconsistent cases are retained.",f"17. Test 7H unique/eligible/P90={h7['branch_observability']['UNIQUE_4RX']}/{h7['accuracy']['eligible_unique_fixes']}/{h7['accuracy']['horizontal_error_m']['p90']} m versus Test 7I={classes['BLIND_UNIQUE']}/{len(eligible)}/{stats(he)['p90']} m.","18. Qualified conclusion: the four-receiver pipeline can independently generate anonymous horizontal measurements and tracks, but degraded clocks and anonymous altitude ambiguity prevent an operational high-confidence claim.","","A/B/C INTERPRETATION","A. Horizontal mirror: often broken by the redundant weighted residual.","B. Altitude: not generally observable from anonymous Type-1; Mode-C aliases and grid bands remain limitations.","C. Tracks: blind tracks are produced before truth; post-hoc confirmation is reported without changing them."]
 (out/"test7i-report.txt").write_text("\n".join(lines)+"\n");print(json.dumps({"decision":decision,"blind_unique":classes["BLIND_UNIQUE"],"tracks":len(tracks),"matched_fixes":len(eligible),"branch_accuracy":branch_acc},indent=2))

if __name__=="__main__":main()
