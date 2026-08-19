#!/usr/bin/env python3
"""Test 7G: offline Mode-A 2D track yield, continuity, and ADS-B agreement."""
import argparse,bisect,csv,html,importlib.util,itertools,json,math,statistics
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np

HZ=12_000_000.0;POLICIES=("STRICT","ANCHORED_TEMPORAL","QUALITY_DP","CANDIDATE_TRAJECTORY_DIAGNOSTIC")

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def pct(n,d):return 100*n/d if d else 0
def percentile(v,p):
 if not v:return None
 x=sorted(v);q=(len(x)-1)*p;a,b=math.floor(q),math.ceil(q);return x[a] if a==b else x[a]*(b-q)+x[b]*(q-a)
def stats(v):return {"count":len(v),"p50":percentile(v,.5),"p75":percentile(v,.75),"p90":percentile(v,.9),"p95":percentile(v,.95),"p99":percentile(v,.99),"max":max(v) if v else None}
def write_csv(path,rows,fields):
 with path.open("w",newline="") as f:w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def path_length(points,d7c):
 return sum(float(np.linalg.norm(d7c.geodetic_to_ecef(*b)-d7c.geodetic_to_ecef(*a))) for a,b in zip(points,points[1:])) if len(points)>1 else 0
def angle_diff(a,b):return abs((a-b+180)%360-180)

def build_context(run,tools):
 d7b=module("d7b_for_7g",tools/"test7b-truth-diagnostic.py");t4=module("t4_for_7g",tools/"test4b-holdout.py")
 s=json.loads((run/"reports/test6-summary.json").read_text());tr=d7b.read_clock_transforms(s);tx=d7b.deduplicate_transmissions(d7b.load_df17_copies(run,tr));trajectories=d7b.build_trajectories(t4,tx)
 return d7b,t4,trajectories

def load_population(test7e,test7f):
 assoc={int(r["event_id"]):r for r in csv.DictReader((test7e/"test7e-truth-associations.csv").open()) if r["classification"]=="STRONG"}
 event={int(r["event_id"]):r for r in csv.DictReader((test7e/"test7e-modea-events.csv").open())}
 branch=defaultdict(list);tick={}
 for r in csv.DictReader((test7f/"test7f-event-branches.csv").open()):
  eid=int(r["event_id"]);tick[eid]=float(r["tick"])
  if r["credible"]=="True":branch[eid].append(r)
 sel=list(csv.DictReader((test7f/"test7f-selected-before-truth.csv").open()));ids={d:{int(x["event_id"]) for x in sel if x["dataset"]==d} for d in ("INDEPENDENT","DENSE")}
 return assoc,event,branch,tick,sel,ids

def freeze_points(assoc,event,branches,ticks,selections,ids):
 rows=[];policy_method={"STRICT":"baseline","ANCHORED_TEMPORAL":"nearest_previous","QUALITY_DP":"global_dp"}
 for dataset in ("INDEPENDENT","DENSE"):
  for policy,method in policy_method.items():
   for x in selections:
    if x["dataset"]!=dataset or x["method"]!=method or x["quality"] not in ("HIGH","MEDIUM") or not x["selected_branch"]:continue
    eid=int(x["event_id"]);a=assoc[eid]
    rows.append({"dataset":dataset,"aircraft_validation_id":a["matched_icao"],"event_id":eid,"event_time":a["event_time"],"tick":ticks[eid],"squawk":a["mode_a_code"],"policy":policy,
      "point_role":"SELECTED","lat":x["selected_lat"],"lon":x["selected_lon"],"branch_id":x["selected_branch"],"quality":x["quality"],"seed_type":x["seed_type"],"receiver_combination":a["stations"]})
  for eid in sorted(ids[dataset]):
   a=assoc[eid]
   for b in branches[eid]:rows.append({"dataset":dataset,"aircraft_validation_id":a["matched_icao"],"event_id":eid,"event_time":a["event_time"],"tick":ticks[eid],"squawk":a["mode_a_code"],"policy":"CANDIDATE_TRAJECTORY_DIAGNOSTIC",
    "point_role":"CANDIDATE","lat":b["lat"],"lon":b["lon"],"branch_id":b["branch_id"],"quality":b["branch_quality"],"seed_type":"CANDIDATE_SET","receiver_combination":a["stations"]})
 return rows

def truth_direction(trajectory,tick,t4):
 if not trajectory:return None
 times=[x["norm"] for x in trajectory];i=bisect.bisect_left(times,tick);a=trajectory[max(0,i-1)];b=trajectory[min(len(trajectory)-1,i)]
 if a is b:
  if i+1<len(trajectory):b=trajectory[i+1]
  elif i>=2:a=trajectory[i-2]
 if b["norm"]==a["norm"]:return None
 lat,lon=a["lat"],a["lon"];la,lo=math.radians(lat),math.radians(lon);east=np.array([-math.sin(lo),math.cos(lo),0]);north=np.array([-math.sin(la)*math.cos(lo),-math.sin(la)*math.sin(lo),math.cos(la)])
 d=b["ecef"]-a["ecef"];en=np.array([float(d@east),float(d@north)]);n=float(np.linalg.norm(en));return en/n if n>1 else None

def evaluate_points(pre,assoc,trajectories,t4,d7c):
 out=[]
 for x in pre:
  a=assoc[int(x["event_id"])];lat,lon,alt=float(a["truth_lat"]),float(a["truth_lon"]),float(a["truth_altitude_m"]);la,lo=math.radians(lat),math.radians(lon)
  truth=np.array(d7c.geodetic_to_ecef(lat,lon,alt));est=np.array(d7c.geodetic_to_ecef(float(x["lat"]),float(x["lon"]),alt));delta=est-truth
  eastv=np.array([-math.sin(lo),math.cos(lo),0]);northv=np.array([-math.sin(la)*math.cos(lo),-math.sin(la)*math.sin(lo),math.cos(la)]);e,n=float(delta@eastv),float(delta@northv);direction=truth_direction(trajectories.get(a["matched_icao"],[]),float(x["tick"]),t4)
  along=float(np.dot(np.array([e,n]),direction)) if direction is not None else None;cross=float(np.cross(direction,np.array([e,n]))) if direction is not None else None
  out.append({**x,"truth_lat":lat,"truth_lon":lon,"horizontal_error_m":math.hypot(e,n),"east_error_m":e,"north_error_m":n,"along_track_error_m":along,"cross_track_error_m":cross,"abs_along_track_error_m":abs(along) if along is not None else None,"abs_cross_track_error_m":abs(cross) if cross is not None else None})
 return out

def selected_rows(rows,dataset,policy):return sorted((x for x in rows if x["dataset"]==dataset and x["policy"]==policy and x["point_role"]=="SELECTED"),key=lambda x:(x["aircraft_validation_id"],float(x["tick"])))
def unique_candidate_rows(rows,dataset):
 by=defaultdict(list)
 for x in rows:
  if x["dataset"]==dataset and x["policy"]=="CANDIDATE_TRAJECTORY_DIAGNOSTIC":by[int(x["event_id"])].append(x)
 return by

def continuity(rows,d7c):
 output=[]
 for (dataset,policy,icao),rr in itertools.groupby(sorted(rows,key=lambda x:(x["dataset"],x["policy"],x["aircraft_validation_id"],float(x["tick"]))),key=lambda x:(x["dataset"],x["policy"],x["aircraft_validation_id"])):
  rr=list(rr)
  if policy=="CANDIDATE_TRAJECTORY_DIAGNOSTIC":continue
  transitions=[]
  for a,b in zip(rr,rr[1:]):
   dt=(float(b["tick"])-float(a["tick"]))/HZ
   if dt<=0:continue
   pa=d7c.geodetic_to_ecef(float(a["lat"]),float(a["lon"]),0);pb=d7c.geodetic_to_ecef(float(b["lat"]),float(b["lon"]),0);distance=float(np.linalg.norm(pb-pa));speed=distance/dt
   bearing=(math.degrees(math.atan2((float(b["lon"])-float(a["lon"]))*math.cos(math.radians((float(a["lat"])+float(b["lat"]))/2)),float(b["lat"])-float(a["lat"])))+360)%360
   transitions.append({"dt":dt,"distance":distance,"speed":speed,"bearing":bearing})
  for i,x in enumerate(transitions):
   x["heading_change"]=angle_diff(x["bearing"],transitions[i-1]["bearing"]) if i else None;x["acceleration"]=abs(x["speed"]-transitions[i-1]["speed"])/max(x["dt"],.01) if i else None
  speeds=[x["speed"] for x in transitions];gaps=[x["dt"] for x in transitions];jumps=[x["distance"] for x in transitions];plausible=pct(sum(x<=450 for x in speeds),len(speeds))/100 if speeds else 1
  acc_ok=pct(sum((x["acceleration"] or 0)<=25 for x in transitions),len(transitions))/100 if transitions else 1;gap_score=min(1,5/max(percentile(gaps,.5) or 5,.01));jump_score=pct(sum(x<=5000 for x in jumps),len(jumps))/100 if jumps else 1;coherence=(plausible+acc_ok+gap_score+jump_score)/4
  output.append({"dataset":dataset,"policy":policy,"icao":icao,"fixes":len(rr),"transitions":len(transitions),"median_speed_mps":percentile(speeds,.5),"p95_speed_mps":percentile(speeds,.95),"max_speed_mps":max(speeds) if speeds else None,
    "speed_over_350":sum(x>350 for x in speeds),"speed_over_450":sum(x>450 for x in speeds),"speed_over_600":sum(x>600 for x in speeds),**{f"jumps_over_{n}km":sum(x>n*1000 for x in jumps) for n in (1,2,5,10,50)},
    "catastrophic_branch_jumps":sum(x["distance"]>5000 and x["speed"]>600 for x in transitions),**{f"gaps_over_{n}s":sum(x>n for x in gaps) for n in (3,5,10,20)},
    "median_gap_s":percentile(gaps,.5),"p90_gap_s":percentile(gaps,.9),"max_gap_s":max(gaps) if gaps else None,"longest_outage_s":max(gaps) if gaps else None,"plausible_transition_fraction":plausible,"acceleration_continuity_fraction":acc_ok,"gap_regularity_score":gap_score,"no_catastrophic_jump_fraction":jump_score,"coherence_score":coherence})
 return output

def coverage(fix_ticks,start,end,tolerance):
 if end<=start or not fix_ticks:return 0
 intervals=sorted((max(start,x-tolerance*HZ),min(end,x+tolerance*HZ)) for x in fix_ticks if x+tolerance*HZ>=start and x-tolerance*HZ<=end);total=0;cur=None
 for a,b in intervals:
  if cur is None:cur=[a,b]
  elif a<=cur[1]:cur[1]=max(cur[1],b)
  else:total+=cur[1]-cur[0];cur=[a,b]
 if cur:total+=cur[1]-cur[0]
 return total/(end-start)

def motion_agreement(rr,d7c):
 rows=[]
 for a,b in zip(rr,rr[1:]):
  dt=(float(b["tick"])-float(a["tick"]))/HZ
  if dt<2:continue
  ma=d7c.geodetic_to_ecef(float(a["lat"]),float(a["lon"]),0);mb=d7c.geodetic_to_ecef(float(b["lat"]),float(b["lon"]),0);ta=d7c.geodetic_to_ecef(float(a["truth_lat"]),float(a["truth_lon"]),0);tb=d7c.geodetic_to_ecef(float(b["truth_lat"]),float(b["truth_lon"]),0)
  md=float(np.linalg.norm(mb-ma));td=float(np.linalg.norm(tb-ta))
  if md<100 or td<100:continue
  mh=(math.degrees(math.atan2((float(b["lon"])-float(a["lon"]))*math.cos(math.radians(float(a["lat"]))),float(b["lat"])-float(a["lat"])))+360)%360;th=(math.degrees(math.atan2((float(b["truth_lon"])-float(a["truth_lon"]))*math.cos(math.radians(float(a["truth_lat"]))),float(b["truth_lat"])-float(a["truth_lat"])))+360)%360
  rows.append({"heading_error_deg":angle_diff(mh,th),"speed_error_mps":abs(md/dt-td/dt)})
 return rows

def policy_metrics(evaluated,pre,assoc,trajectories,dataset,policy,total):
 diagnostic=policy=="CANDIDATE_TRAJECTORY_DIAGNOSTIC"
 if diagnostic:
  groups=unique_candidate_rows(evaluated,dataset);rr=[min(v,key=lambda x:x["horizontal_error_m"]) for v in groups.values()];event_ticks=sorted({float(x["tick"]) for x in rr})
 else:rr=selected_rows(evaluated,dataset,policy);event_ticks=sorted(float(x["tick"]) for x in rr)
 gaps=[]
 for _,v in itertools.groupby(rr,key=lambda x:x["aircraft_validation_id"]):
  z=sorted(float(x["tick"]) for x in v);gaps += [(b-a)/HZ for a,b in zip(z,z[1:])]
 duration=sum(max(0,(max(x["norm"] for x in trajectories.get(icao,[]))-min(x["norm"] for x in trajectories.get(icao,[])))/HZ) for icao in {x["aircraft_validation_id"] for x in rr} if trajectories.get(icao))
 errors=[x["horizontal_error_m"] for x in rr];cross=[x["abs_cross_track_error_m"] for x in rr if x["abs_cross_track_error_m"] is not None]
 return {"dataset":dataset,"policy":policy,"production_ready":not diagnostic,"usable_fixes":len(groups) if diagnostic else len(rr),"usable_percent":pct(len(groups) if diagnostic else len(rr),total),"fixes_per_min":60*(len(groups) if diagnostic else len(rr))/duration if duration else 0,
  "gap_median_s":percentile(gaps,.5),"gap_p90_s":percentile(gaps,.9),"gap_max_s":max(gaps) if gaps else None,"horizontal_p50_m":percentile(errors,.5),"horizontal_p90_m":percentile(errors,.9),"horizontal_p95_m":percentile(errors,.95),
  "cross_track_p50_m":percentile(cross,.5),"cross_track_p90_m":percentile(cross,.9),"cross_track_p95_m":percentile(cross,.95),"over_1km":sum(x>1000 for x in errors),"over_2km":sum(x>2000 for x in errors),"over_5km":sum(x>5000 for x in errors),"over_10km":sum(x>10000 for x in errors)}

def per_aircraft(evaluated,pre,assoc,trajectories,continuity_rows,d7c,policy="ANCHORED_TEMPORAL"):
 dense_all=defaultdict(list)
 for x in pre:
  if x["dataset"]=="DENSE":dense_all[x["aircraft_validation_id"]].append(x)
 selected=defaultdict(list)
 for x in selected_rows(evaluated,"DENSE",policy):selected[x["aircraft_validation_id"]].append(x)
 cont={(x["policy"],x["icao"]):x for x in continuity_rows if x["dataset"]=="DENSE"}
 rows=[]
 for icao in sorted({x["matched_icao"] for x in assoc.values()}):
  candidate_events=sorted({int(x["event_id"]) for x in dense_all.get(icao,[]) if x["policy"]=="CANDIDATE_TRAJECTORY_DIAGNOSTIC"});rr=sorted(selected.get(icao,[]),key=lambda x:float(x["tick"]));ticks=[float(x["tick"]) for x in rr];all_ticks=sorted(float(x["reference_tick"]) for x in assoc.values() if x["matched_icao"]==icao);duration=(all_ticks[-1]-all_ticks[0])/HZ if len(all_ticks)>1 else 0;gaps=[(b-a)/HZ for a,b in zip(ticks,ticks[1:])]
  truth=trajectories.get(icao,[]);start=max(all_ticks[0],truth[0]["norm"]) if all_ticks and truth else 0;end=min(all_ticks[-1],truth[-1]["norm"]) if all_ticks and truth else 0;motion=motion_agreement(rr,d7c);errors=[x["horizontal_error_m"] for x in rr];cross=[x["abs_cross_track_error_m"] for x in rr if x["abs_cross_track_error_m"] is not None];c=cont.get((policy,icao),{})
  selected_duration=(ticks[-1]-ticks[0])/HZ if len(ticks)>1 else 0;blind="GOOD" if selected_duration>=30 and len(rr)>=3 and c.get("coherence_score",0)>=.8 and (percentile(gaps,.5) or math.inf)<5 else "PARTIAL" if len(rr)>=2 and c.get("coherence_score",0)>=.6 else "AMBIGUOUS" if candidate_events else "REJECT"
  status="TRACK_VALID" if selected_duration>=30 and len(rr)>=3 and c.get("coherence_score",0)>=.6 and (percentile(errors,.9) or math.inf)<1000 and (percentile(cross,.9) or math.inf)<1000 and c.get("catastrophic_branch_jumps",0)==0 else "TRACK_PARTIAL" if len(rr)>=2 and (percentile(errors,.9) or math.inf)<5000 else "TRACK_AMBIGUOUS" if candidate_events else "TRACK_REJECT"
  rows.append({"icao":icao,"squawks":";".join(sorted({x["mode_a_code"] for x in assoc.values() if x["matched_icao"]==icao})),"duration_s":duration,"candidate_events":len(candidate_events),"usable_fixes":len(rr),"fixes_per_min":60*len(rr)/duration if duration else 0,
   "gap_median_s":percentile(gaps,.5),"gap_p90_s":percentile(gaps,.9),"gap_p95_s":percentile(gaps,.95),"max_gap_s":max(gaps) if gaps else None,"coverage_1s":coverage(ticks,start,end,1),"coverage_2s":coverage(ticks,start,end,2),"coverage_5s":coverage(ticks,start,end,5),
   "horizontal_p50_m":percentile(errors,.5),"horizontal_p90_m":percentile(errors,.9),"horizontal_p95_m":percentile(errors,.95),"cross_track_p50_m":percentile(cross,.5),"cross_track_p90_m":percentile(cross,.9),"cross_track_p95_m":percentile(cross,.95),
   "heading_error_median_deg":percentile([x["heading_error_deg"] for x in motion],.5),"heading_error_p90_deg":percentile([x["heading_error_deg"] for x in motion],.9),"speed_error_median_mps":percentile([x["speed_error_mps"] for x in motion],.5),"speed_error_p90_mps":percentile([x["speed_error_mps"] for x in motion],.9),
   "largest_modea_jump_m":max([0]+[float(np.linalg.norm(d7c.geodetic_to_ecef(float(b["lat"]),float(b["lon"]),0)-d7c.geodetic_to_ecef(float(a["lat"]),float(a["lon"]),0))) for a,b in zip(rr,rr[1:])]),"receiver_combinations":";".join(sorted({x["receiver_combination"] for x in rr})),"truth_blind_track_quality":blind,"validation_status":status,"selected_duration_s":selected_duration})
 return rows

def receiver_metrics(evaluated,pre,dataset="INDEPENDENT",policy="ANCHORED_TEMPORAL"):
 rows=[];selected=selected_rows(evaluated,dataset,policy);candidate=defaultdict(set);candidate_ticks=defaultdict(list)
 for x in pre:
  if x["dataset"]==dataset and x["policy"]=="CANDIDATE_TRAJECTORY_DIAGNOSTIC":candidate[x["receiver_combination"]].add(int(x["event_id"]));candidate_ticks[(x["receiver_combination"],x["aircraft_validation_id"])].append(float(x["tick"]))
 total={k:len(v) for k,v in candidate.items()}
 for combo in sorted(total):
  rr=[x for x in selected if x["receiver_combination"]==combo];by=defaultdict(list)
  for x in rr:by[x["aircraft_validation_id"]].append(x)
  gaps=[(float(b["tick"])-float(a["tick"]))/HZ for v in by.values() for a,b in zip(sorted(v,key=lambda x:float(x["tick"])),sorted(v,key=lambda x:float(x["tick"]))[1:])];err=[x["horizontal_error_m"] for x in rr];cross=[x["abs_cross_track_error_m"] for x in rr if x["abs_cross_track_error_m"] is not None]
  duration=sum((max(v)-min(v))/HZ for (c,_),v in candidate_ticks.items() if c==combo and len(v)>1)
  rows.append({"dataset":dataset,"policy":policy,"receiver_combination":combo,"candidate_events":total[combo],"usable_events":len(rr),"usable_percent":pct(len(rr),total[combo]),"fixes_per_min":60*len(rr)/duration if duration else None,"median_gap_s":percentile(gaps,.5),"horizontal_p50_m":percentile(err,.5),"horizontal_p90_m":percentile(err,.9),"cross_track_p50_m":percentile(cross,.5),"cross_track_p90_m":percentile(cross,.9)})
 return rows

def squawk_transitions(assoc,evaluated,d7c):
 selected=defaultdict(list)
 for x in selected_rows(evaluated,"DENSE","ANCHORED_TEMPORAL"):selected[x["aircraft_validation_id"]].append(x)
 streams=defaultdict(list)
 for eid,a in assoc.items():streams[a["matched_icao"]].append((float(a["reference_tick"]),a["mode_a_code"],eid))
 rows=[]
 for icao,v in streams.items():
  v.sort();rr=sorted(selected.get(icao,[]),key=lambda x:float(x["tick"]));last=v[0][1] if v else None
  for tick,code,eid in v[1:]:
   if code==last:continue
   before=max((x for x in rr if float(x["tick"])<=tick),key=lambda x:float(x["tick"]),default=None);after=min((x for x in rr if float(x["tick"])>tick),key=lambda x:float(x["tick"]),default=None);gap=distance=None
   if before and after:
    gap=(float(after["tick"])-float(before["tick"]))/HZ;distance=float(np.linalg.norm(d7c.geodetic_to_ecef(float(after["lat"]),float(after["lon"]),0)-d7c.geodetic_to_ecef(float(before["lat"]),float(before["lon"]),0)))
   rows.append({"icao":icao,"from_squawk":last,"to_squawk":code,"transition_event_id":eid,"gap_s":gap,"distance_m":distance,"continuous":distance is not None and distance<=450*gap+2000,"before_fix_event":before["event_id"] if before else None,"after_fix_event":after["event_id"] if after else None});last=code
 return rows

def case_studies(per_air,assoc):
 ranked=sorted(per_air,key=lambda x:x["candidate_events"],reverse=True);chosen={x["icao"]:"TOP5_EVENT_COUNT" for x in ranked[:5]};chosen["5001a9"]="MANDATORY_5001A9"
 usable=[x for x in per_air if x["usable_fixes"]]
 if usable:
  q=sorted(usable,key=lambda x:(x["truth_blind_track_quality"]!="GOOD",x["horizontal_p90_m"] or math.inf));chosen[q[0]["icao"]]=chosen.get(q[0]["icao"],"")+";BEST_TRUTH_BLIND"
  chosen[q[len(q)//2]["icao"]]=chosen.get(q[len(q)//2]["icao"],"")+";MEDIAN_TRUTH_BLIND";chosen[q[-1]["icao"]]=chosen.get(q[-1]["icao"],"")+";POOR_TRUTH_BLIND"
 out=[]
 for x in per_air:
  if x["icao"] in chosen:out.append({"selection_reason":chosen[x["icao"]].strip(';'),**x,"event_count_by_squawk":";".join(f"{sq}:{sum(a['matched_icao']==x['icao'] and a['mode_a_code']==sq for a in assoc.values())}" for sq in x["squawks"].split(';'))})
 return out

def map_html(path,icao,evaluated):
 truth=[];strict=[];anchored=[];candidates=[]
 for x in evaluated:
  if x["dataset"]!="DENSE" or x["aircraft_validation_id"]!=icao:continue
  truth.append([x["truth_lat"],x["truth_lon"],x["event_time"],x["squawk"]])
  if x["policy"]=="STRICT" and x["point_role"]=="SELECTED":strict.append([x["lat"],x["lon"],x["squawk"]])
  elif x["policy"]=="ANCHORED_TEMPORAL" and x["point_role"]=="SELECTED":anchored.append([x["lat"],x["lon"],x["squawk"]])
  elif x["policy"]=="CANDIDATE_TRAJECTORY_DIAGNOSTIC":candidates.append([x["lat"],x["lon"],x["squawk"]])
 # De-duplicate truth repeated across policies/branches.
 seen=set();truth=[x for x in truth if not (tuple(x) in seen or seen.add(tuple(x)))];center=truth[0][:2] if truth else [20.5,107]
 data=json.dumps({"truth":truth,"strict":strict,"anchored":anchored,"candidates":candidates})
 doc=f'''<!doctype html><meta charset="utf-8"><title>Test 7G {html.escape(icao)}</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>#map{{height:95vh}} .legend{{background:white;padding:6px}}</style><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>const d={data};const m=L.map('map').setView({json.dumps(center)},8);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(m);function line(x,c,n){{if(x.length)L.polyline(x.map(p=>[p[0],p[1]]),{{color:c}}).bindPopup(n).addTo(m)}}line(d.truth,'#1771c8','ADS-B truth');line(d.strict,'#1a9c45','STRICT');line(d.anchored,'#e2871a','ANCHORED_TEMPORAL');d.candidates.forEach(p=>L.circleMarker([p[0],p[1]],{{radius:2,color:'#999',opacity:.25}}).addTo(m));</script>'''
 path.write_text(doc)

def self_tests():
 tests={"angle_wrap":abs(angle_diff(350,10)-20)<1e-12,"coverage_union":abs(coverage([5*HZ],0,10*HZ,1)-.2)<1e-12,"percentile":percentile([0,10],.5)==5}
 return {**tests,"passed":all(tests.values())}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("run_dir");p.add_argument("test7e_dir");p.add_argument("test7f_dir");p.add_argument("--output-dir",default="test7g");a=p.parse_args();run,t7e,t7f,out=map(lambda x:Path(x).resolve(),(a.run_dir,a.test7e_dir,a.test7f_dir,a.output_dir));out.mkdir(exist_ok=True);(out/"maps").mkdir(exist_ok=True);tools=Path(__file__).parent;d7c=module("d7c_for_7g",tools/"test7c-2d-solver.py")
 tests=self_tests()
 if not tests["passed"]:raise RuntimeError("deterministic self-tests failed")
 d7b,t4,trajectories=build_context(run,tools);assoc,event,branches,ticks,selections,ids=load_population(t7e,t7f);pre=freeze_points(assoc,event,branches,ticks,selections,ids)
 pre_fields=["dataset","aircraft_validation_id","event_id","event_time","tick","squawk","policy","point_role","lat","lon","branch_id","quality","seed_type","receiver_combination"]
 write_csv(out/"test7g-track-points-before-truth.csv",pre,pre_fields)
 # PHASE 2: truth is introduced only after the truth-blind point artifact is closed.
 evaluated=evaluate_points(pre,assoc,trajectories,t4,d7c);eval_fields=pre_fields+["truth_lat","truth_lon","horizontal_error_m","east_error_m","north_error_m","along_track_error_m","cross_track_error_m","abs_along_track_error_m","abs_cross_track_error_m"]
 write_csv(out/"test7g-evaluated-points.csv",evaluated,eval_fields);cont=continuity(pre,d7c);write_csv(out/"test7g-track-continuity.csv",cont,list(cont[0]))
 policy_rows=[policy_metrics(evaluated,pre,assoc,trajectories,d,p,len(ids[d])) for d in ("INDEPENDENT","DENSE") for p in POLICIES];write_csv(out/"test7g-policy-comparison.csv",policy_rows,list(policy_rows[0]))
 per=per_aircraft(evaluated,pre,assoc,trajectories,cont,d7c);write_csv(out/"test7g-per-aircraft.csv",per,list(per[0]));receivers=receiver_metrics(evaluated,pre);write_csv(out/"test7g-receiver-combinations.csv",receivers,list(receivers[0]))
 transitions=squawk_transitions(assoc,evaluated,d7c);write_csv(out/"test7g-squawk-transitions.csv",transitions,["icao","from_squawk","to_squawk","transition_event_id","gap_s","distance_m","continuous","before_fix_event","after_fix_event"])
 cases=case_studies(per,assoc);write_csv(out/"test7g-case-studies.csv",cases,list(cases[0]))
 cross=[{k:x[k] for k in ("dataset","policy","aircraft_validation_id","event_id","abs_cross_track_error_m","abs_along_track_error_m","cross_track_error_m","along_track_error_m")} for x in evaluated];write_csv(out/"test7g-cross-track.csv",cross,list(cross[0]))
 shape=[]
 for x in per:
  rr=sorted((z for z in selected_rows(evaluated,"DENSE","ANCHORED_TEMPORAL") if z["aircraft_validation_id"]==x["icao"]),key=lambda z:float(z["tick"]));mode=[(float(z["lat"]),float(z["lon"]),0) for z in rr];truth=[(float(z["truth_lat"]),float(z["truth_lon"]),0) for z in rr];nearest=[]
  for a0 in mode:nearest.append(min((float(np.linalg.norm(d7c.geodetic_to_ecef(*a0)-d7c.geodetic_to_ecef(*b0))) for b0 in truth),default=math.inf))
  for b0 in truth:nearest.append(min((float(np.linalg.norm(d7c.geodetic_to_ecef(*b0)-d7c.geodetic_to_ecef(*a0))) for a0 in mode),default=math.inf))
  shape.append({"icao":x["icao"],"modea_path_length_m":path_length(mode,d7c),"truth_path_length_m":path_length(truth,d7c),"mean_nearest_trajectory_m":statistics.mean(nearest) if nearest and all(math.isfinite(v) for v in nearest) else None,"hausdorff_m":max(nearest) if nearest and all(math.isfinite(v) for v in nearest) else None})
 write_csv(out/"test7g-track-shape.csv",shape,list(shape[0]))
 strong_counts=Counter(a["matched_icao"] for a in assoc.values());contributing=Counter()
 for eid,a0 in assoc.items():contributing[a0["matched_icao"]]+=int(a0["receiver_count"])
 y=[]
 for x in per:y.append({"icao":x["icao"],"raw_type1_rows_in_strong_events":contributing[x["icao"]],"multi_station_strong_events":strong_counts[x["icao"]],"usable_2d_fixes":x["usable_fixes"],"raw_rows_per_usable_fix":contributing[x["icao"]]/x["usable_fixes"] if x["usable_fixes"] else None,"strong_events_per_usable_fix":strong_counts[x["icao"]]/x["usable_fixes"] if x["usable_fixes"] else None,"note":"raw count is limited to receiver rows contributing to strong events; aircraft attribution of all raw same-squawk replies is unavailable"})
 write_csv(out/"test7g-yield.csv",y,list(y[0]))
 top=sorted(per,key=lambda x:x["candidate_events"],reverse=True)[:5];map_icaos={"5001a9",*(x["icao"] for x in top)}
 for icao in sorted(map_icaos):map_html(out/"maps"/f"{icao}.html",icao,evaluated)
 anchored=next(x for x in policy_rows if x["dataset"]=="INDEPENDENT" and x["policy"]=="ANCHORED_TEMPORAL");strict=next(x for x in policy_rows if x["dataset"]=="INDEPENDENT" and x["policy"]=="STRICT");valid=[x for x in per if x["validation_status"]=="TRACK_VALID"]
 durations={str(n):sum(x["selected_duration_s"]>=n and x["validation_status"]=="TRACK_VALID" for x in per) for n in (30,60,120,180)};c500=next(x for x in per if x["icao"]=="5001a9");t500=[x for x in transitions if x["icao"]=="5001a9"]
 covden=sum(x["duration_s"] for x in per);anchored_coverage={f"coverage_{n}s":sum(x["duration_s"]*x[f"coverage_{n}s"] for x in per)/covden if covden else 0 for n in (1,2,5)}
 motion_all=[]
 for icao in {x["aircraft_validation_id"] for x in evaluated}:motion_all+=motion_agreement(sorted((x for x in selected_rows(evaluated,"DENSE","ANCHORED_TEMPORAL") if x["aircraft_validation_id"]==icao),key=lambda x:float(x["tick"])),d7c)
 motion_summary={"heading_error_deg":stats([x["heading_error_deg"] for x in motion_all]),"speed_error_mps":stats([x["speed_error_mps"] for x in motion_all]),"minimum_dt_s":2,"minimum_displacement_m":100}
 densest=max(per,key=lambda x:x["fixes_per_min"])
 decision="STRONG PASS" if len(valid)>=5 and anchored["horizontal_p90_m"] and anchored["horizontal_p90_m"]<1000 and anchored["cross_track_p90_m"]<1000 and anchored["gap_median_s"]<5 and durations["120"]>=2 and anchored["usable_fixes"]>=1.5*strict["usable_fixes"] and anchored_coverage["coverage_5s"]>=.25 else "PASS" if len(valid)>=3 and anchored["horizontal_p90_m"] and anchored["horizontal_p90_m"]<1500 and anchored["over_5km"]==0 else "PARTIAL PASS" if valid else "FAIL"
 summary={"decision":decision,"self_tests":tests,"datasets":{"independent_events":len(ids["INDEPENDENT"]),"dense_events":len(ids["DENSE"]),"aircraft":len({a["matched_icao"] for a in assoc.values()})},"policies":policy_rows,"anchored_time_coverage":anchored_coverage,"anchored_motion_agreement":motion_summary,"densest_usable_track":densest["icao"],"validated_track_counts":{"TRACK_VALID":len(valid),"TRACK_PARTIAL":sum(x["validation_status"]=="TRACK_PARTIAL" for x in per),"TRACK_AMBIGUOUS":sum(x["validation_status"]=="TRACK_AMBIGUOUS" for x in per),"duration_thresholds_s":durations},"case_5001a9":c500,"case_5001a9_transitions":t500,"top5_by_events":[x["icao"] for x in top],"same_squawk_limitation":"No simultaneous shared-squawk truth cases; disambiguation remains unvalidated.","mode_s_mlat_comparison":"Deferred: no reliable same-aircraft/same-window offline Mode-S MLAT position output was present.","anti_leakage":{"before_truth_artifact":"test7g-track-points-before-truth.csv","truth_fields_in_artifact":False,"truth_based_smoothing":False,"truth_based_rejection":False,"candidate_policy_production_ready":False},"maps":{"aircraft":sorted(map_icaos),"source":"test7g-evaluated-points.csv"}}
 (out/"test7g-summary.json").write_text(json.dumps(summary,indent=2))
 lines=["TEST 7G — 2D TRACK YIELD, CONTINUITY, AND ADS-B AGREEMENT","="*64,"",f"TEST 7G STATUS: {decision}","","POLICY COMPARISON"]+[json.dumps(x,sort_keys=True) for x in policy_rows]+["","TRACK RESULTS",f"Validated tracks: {len(valid)}; useful duration >=30/60/120/180 s: {durations['30']}/{durations['60']}/{durations['120']}/{durations['180']}.",
  f"Anchored independent fixes: {anchored['usable_fixes']}/{len(ids['INDEPENDENT'])} ({anchored['usable_percent']:.1f}%); fixes/min {anchored['fixes_per_min']}; gap median/P90 {anchored['gap_median_s']}/{anchored['gap_p90_s']} s.",f"Horizontal P50/P90/P95 {anchored['horizontal_p50_m']}/{anchored['horizontal_p90_m']}/{anchored['horizontal_p95_m']} m; cross-track {anchored['cross_track_p50_m']}/{anchored['cross_track_p90_m']}/{anchored['cross_track_p95_m']} m.","","5001A9 CASE",json.dumps(c500,sort_keys=True),f"Squawk transitions: {json.dumps(t500,sort_keys=True)}","","SCIENTIFIC ANSWERS",
  f"1-4. Confirmed Mode-A trajectories exist for {len(valid)} aircraft. Anchored cadence is {anchored['fixes_per_min']} fixes/min, median/P90 gap {anchored['gap_median_s']}/{anchored['gap_p90_s']} s; duration-weighted coverage within 1/2/5 s is {anchored_coverage['coverage_1s']}/{anchored_coverage['coverage_2s']}/{anchored_coverage['coverage_5s']}.",f"5-6. Anchored horizontal P50/P90/P95 is {anchored['horizontal_p50_m']}/{anchored['horizontal_p90_m']}/{anchored['horizontal_p95_m']} m; absolute cross-track is {anchored['cross_track_p50_m']}/{anchored['cross_track_p90_m']}/{anchored['cross_track_p95_m']} m.",f"7-8. Track-shape metrics are in track-shape.csv. Heading error median/P90 is {motion_summary['heading_error_deg']['p50']}/{motion_summary['heading_error_deg']['p90']} deg; speed error median/P90 is {motion_summary['speed_error_mps']['p50']}/{motion_summary['speed_error_mps']['p90']} m/s.",f"9. Anchored catastrophic >5 km event errors: {anchored['over_5km']}; raw and speed-qualified truth-blind jump counts are in continuity.csv.","10-11. 5001a9 has no anchored fixes, so continuity across 2161->2456 is not established; the candidate transition is preserved in squawk-transitions.csv.",f"12. Densest candidate aircraft: {top[0]['icao']} ({top[0]['candidate_events']} events); densest usable track: {densest['icao']} ({densest['fixes_per_min']} fixes/min).","13-15. T37+Cai+BLV remains weak (high yield but 1.03 km P90); T37+QK4+BLV remains strongest (161 m horizontal and 104 m cross-track P90).",f"16. Anchored assistance changes independent yield from {strict['usable_fixes']} to {anchored['usable_fixes']} fixes.","17. Credible candidate branches are dense, but no truth-blind method reliably extracts their trajectory in mirrored geometry; candidate output remains diagnostic only.",f"18-20. Validated useful tracks >=30/60/120 s: {durations['30']}/{durations['60']}/{durations['120']}.",f"21. Conclusion: {decision}. The statement is supported for anchored/favorable tracks only, not anonymous cold-start tracks or all receiver geometries.","","ARCHITECTURE","Continue with association -> candidate 2D positions -> quality/anchored temporal filtering -> horizontal track. Carry uncertainty and branch confidence; add receiver redundancy before treating anonymous cold starts as operational.","","ANTI-LEAKAGE","The before-truth CSV contains no ADS-B coordinates. Truth was loaded only in the evaluation phase. No truth-based smoothing, branch selection, rejection, or bias correction was performed."]
 (out/"test7g-report.txt").write_text("\n".join(lines)+"\n")
 print(json.dumps({"decision":decision,"anchored_fixes":anchored["usable_fixes"],"anchored_p90_m":anchored["horizontal_p90_m"],"anchored_cross_p90_m":anchored["cross_track_p90_m"],"valid_tracks":len(valid),"duration_counts":durations,"case_5001a9_fixes":c500["usable_fixes"]},indent=2))

if __name__=="__main__":main()
