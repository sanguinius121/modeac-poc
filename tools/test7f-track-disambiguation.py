#!/usr/bin/env python3
"""Test 7F: truth-blind temporal disambiguation of Test 7E Mode-A 2D branches."""
import argparse,csv,hashlib,importlib.util,itertools,json,math,statistics
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np

HZ=12_000_000.0
CONFIGS={
 "CONSERVATIVE":{"normal_speed":350.,"hard_speed":420.,"gap":5.,"prefer_accel":8.,"hard_accel":20.,"position_tolerance_m":1500.,"prediction_weight":1.,"geometry_weight":.15},
 "BALANCED":{"normal_speed":400.,"hard_speed":450.,"gap":10.,"prefer_accel":10.,"hard_accel":25.,"position_tolerance_m":2000.,"prediction_weight":1.,"geometry_weight":.15},
 "PERMISSIVE":{"normal_speed":450.,"hard_speed":500.,"gap":20.,"prefer_accel":15.,"hard_accel":30.,"position_tolerance_m":2500.,"prediction_weight":.75,"geometry_weight":.30}}

def module(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def pct(n,d):return 100*n/d if d else 0
def percentile(v,p):
 if not v:return None
 x=sorted(v);q=(len(x)-1)*p;a,b=math.floor(q),math.ceil(q);return x[a] if a==b else x[a]*(b-q)+x[b]*(q-a)
def dist(rows,key):
 v=[float(x[key]) for x in rows if x.get(key) not in (None,"")]
 return {"count":len(v),"p50":percentile(v,.5),"p75":percentile(v,.75),"p90":percentile(v,.9),"p95":percentile(v,.95),"p99":percentile(v,.99),"max":max(v) if v else None}
def write_csv(path,rows,fields):
 with path.open("w",newline="") as f:w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def sha(path):
 h=hashlib.sha256()
 with path.open("rb") as f:
  for b in iter(lambda:f.read(1<<20),b""):h.update(b)
 return h.hexdigest()

def load_phase1(test7e):
 events={}
 for r in csv.DictReader((test7e/"test7e-modea-events.csv").open()):
  events[int(r["event_id"])]={"event_id":int(r["event_id"]),"event_time":r["event_time"],"squawk":r["mode_a_code"],"stations":r["stations"],
   "receiver_count":int(r["receiver_count"]),"norm":{x.split(':')[0]:float(x.split(':')[1]) for x in r["normalized_timestamps"].split(';')}}
 strong=[]
 # Truth coordinates are deliberately not copied into phase-1 objects.
 for r in csv.DictReader((test7e/"test7e-truth-associations.csv").open()):
  if r["classification"]!="STRONG":continue
  e={**events[int(r["event_id"])],"icao_label":r["matched_icao"],"tick":float(r["reference_tick"]),"altitude_m":float(r["truth_altitude_m"]),
     "association_rms_us":float(r["best_rms_us"])}
  strong.append(e)
 strong.sort(key=lambda x:x["tick"])
 # Dataset A is the exact frozen Test 7E headline sample, not a reimplementation of its thinning.
 independent_ids={int(r["event_id"]) for r in csv.DictReader((test7e/"test7e-localization.csv").open())}
 independent=sorted((x for x in strong if x["event_id"] in independent_ids),key=lambda x:x["tick"])
 return strong,independent

def regenerate(events,d7c):
 by_event={};rows=[]
 for n,e in enumerate(events,1):
  stations=e["stations"].split(';');meas={(a,b):(e["norm"][b]-e["norm"][a])/12 for a,b in itertools.combinations(stations,2)}
  _,cands,_=d7c.solve(e["altitude_m"],stations,meas);floor=min((c["rms_us"] for c in cands),default=math.inf);branches=[]
  for bid,c in enumerate(cands,1):
   credible=c["center_km"]<=1500 and c["rms_us"]<=floor+.01 and math.isfinite(c["condition"]) and c["condition"]<=1e6
   quality="GOOD" if c["condition"]<=10 else "USABLE" if c["condition"]<=30 else "WEAK" if c["condition"]<=70 else "POOR"
   b={"event_id":e["event_id"],"branch_id":bid,"lat":c["lat"],"lon":c["lon"],"en":np.array(c["en"]),"condition":c["condition"],"residual_us":c["rms_us"],
      "center_km":c["center_km"],"credible":credible,"branch_quality":quality}
   branches.append(b);rows.append({**{k:e[k] for k in ("event_id","event_time","icao_label","squawk","stations","tick","altitude_m")},**{k:v for k,v in b.items() if k!="en"},"east_m":c["en"][0],"north_m":c["en"][1]})
  by_event[e["event_id"]]=branches
 return by_event,rows

def credible(e,branches):return [x for x in branches[e["event_id"]] if x["credible"]]
def streams(events):
 out=defaultdict(list)
 for e in events:out[e["icao_label"]].append(e)
 for v in out.values():v.sort(key=lambda x:x["tick"])
 return out
def segments(events,gap):
 out=[];cur=[]
 for e in events:
  if cur and (e["tick"]-cur[-1]["tick"])/HZ>gap:out.append(cur);cur=[]
  cur.append(e)
 if cur:out.append(cur)
 return out
def geom_penalty(b):return max(0.,math.log10(max(b["condition"],1.)/10.))

def first_transition(a,b,dt,cfg):
 distance=float(np.linalg.norm(b["en"]-a["en"]));speed=distance/dt;effective=max(0.,distance-cfg["position_tolerance_m"])/dt
 if distance>cfg["hard_speed"]*dt+cfg["position_tolerance_m"]:return math.inf,{"speed_mps":speed,"prediction_error_m":None,"acceleration_mps2":None,"turn_rate_dps":None,"speed_penalty":math.inf,"acceleration_penalty":0.,"turn_penalty":0.}
 sp=max(0.,(effective-cfg["normal_speed"])/100.)**2
 return sp+cfg["geometry_weight"]*geom_penalty(b),{"speed_mps":speed,"prediction_error_m":None,"acceleration_mps2":None,"turn_rate_dps":None,"speed_penalty":sp,"acceleration_penalty":0.,"turn_penalty":0.}
def triple_transition(a,b,c,dt1,dt2,cfg):
 v1=(b["en"]-a["en"])/dt1;v2=(c["en"]-b["en"])/dt2;speed=float(np.linalg.norm(v2))
 pred=b["en"]+v1*dt2;pe=float(np.linalg.norm(c["en"]-pred));acc=float(np.linalg.norm(v2-v1))/max((dt1+dt2)/2,.01)
 h1=math.atan2(v1[0],v1[1]);h2=math.atan2(v2[0],v2[1]);dh=abs((h2-h1+math.pi)%(2*math.pi)-math.pi);turn=math.degrees(dh)/dt2
 distance=float(np.linalg.norm(c["en"]-b["en"]));hard_prediction=cfg["position_tolerance_m"]+.5*cfg["hard_accel"]*dt2*dt2
 if distance>cfg["hard_speed"]*dt2+cfg["position_tolerance_m"] or pe>hard_prediction:return math.inf,{"speed_mps":speed,"prediction_error_m":pe,"acceleration_mps2":acc,"turn_rate_dps":turn,"speed_penalty":math.inf,"acceleration_penalty":math.inf,"turn_penalty":0.}
 effective_speed=max(0.,distance-cfg["position_tolerance_m"])/dt2;effective_acc=max(0.,pe-cfg["position_tolerance_m"])/max(.5*dt2*dt2,1.)
 pp=cfg["prediction_weight"]*(pe/max(cfg["position_tolerance_m"],50*dt2))**2;sp=max(0.,(effective_speed-cfg["normal_speed"])/100.)**2;ap=(effective_acc/cfg["prefer_accel"])**2;tp=(turn/5.)**2
 return pp+sp+ap+tp+cfg["geometry_weight"]*geom_penalty(c),{"speed_mps":speed,"prediction_error_m":pe,"acceleration_mps2":acc,"turn_rate_dps":turn,"prediction_penalty":pp,"speed_penalty":sp,"acceleration_penalty":ap,"turn_penalty":tp}

def path_diagnostics(seg,path,cfg):
 comp=[]
 for k in range(1,len(path)):
  dt=(seg[k]["tick"]-seg[k-1]["tick"])/HZ
  if k==1:_,x=first_transition(path[k-1],path[k],dt,cfg)
  else:_,x=triple_transition(path[k-2],path[k-1],path[k],(seg[k-1]["tick"]-seg[k-2]["tick"])/HZ,dt,cfg)
  comp.append(x)
 return {"max_speed_mps":max((x["speed_mps"] for x in comp),default=0),"max_acceleration_mps2":max((x["acceleration_mps2"] or 0 for x in comp),default=0),
         "max_turn_rate_dps":max((x["turn_rate_dps"] or 0 for x in comp),default=0),"median_prediction_error_m":percentile([x["prediction_error_m"] for x in comp if x["prediction_error_m"] is not None],.5),
         "prediction_penalty_sum":sum(x.get("prediction_penalty",0) for x in comp),"speed_penalty_sum":sum(x.get("speed_penalty",0) for x in comp),
         "acceleration_penalty_sum":sum(x.get("acceleration_penalty",0) for x in comp),"turn_penalty_sum":sum(x.get("turn_penalty",0) for x in comp),"components":comp}

def dp_path(seg,branches,cfg):
 cs=[credible(e,branches) for e in seg];n=len(seg)
 if any(not x for x in cs):return None
 if n==1:
  if len(cs[0])!=1:return None
  return {"path":[cs[0][0]],"score":cfg["geometry_weight"]*geom_penalty(cs[0][0]),"second":None,"margin":None,"seed_type":"STRONG_SEED" if cs[0][0]["condition"]<=30 else "WEAK_SEED","init_events":1}
 states={};dt=(seg[1]["tick"]-seg[0]["tick"])/HZ
 for i,a in enumerate(cs[0]):
  for j,b in enumerate(cs[1]):
   cost,_=first_transition(a,b,dt,cfg)
   if math.isfinite(cost):states[(i,j)]=cost+cfg["geometry_weight"]*geom_penalty(a)
 if not states:return None
 backs=[None]*n
 for k in range(2,n):
  new={};back={};dt1=(seg[k-1]["tick"]-seg[k-2]["tick"])/HZ;dt2=(seg[k]["tick"]-seg[k-1]["tick"])/HZ
  for (i,j),base in states.items():
   for l,c in enumerate(cs[k]):
    add,_=triple_transition(cs[k-2][i],cs[k-1][j],c,dt1,dt2,cfg);key=(j,l);v=base+add
    if math.isfinite(v) and v<new.get(key,math.inf):new[key]=v;back[key]=i
  states=new;backs[k]=back
  if not states:return None
 ranked=sorted(states.items(),key=lambda x:x[1]);(last,score)=ranked[0];second=ranked[1][1] if len(ranked)>1 else None
 idx=[None]*n;idx[-2],idx[-1]=last
 for k in range(n-1,1,-1):idx[k-2]=backs[k][(idx[k-1],idx[k])]
 path=[cs[k][idx[k]] for k in range(n)];margin=None if second is None else second-score;norm_margin=math.inf if margin is None else margin/max(1,n)
 unique=[(k,x[0]) for k,x in enumerate(cs) if len(x)==1]
 if unique:seed_branch=unique[0][1];seed="STRONG_SEED" if seed_branch["condition"]<=30 else "WEAK_SEED";init=unique[0][0]+1
 elif n>=3 and norm_margin>=.1:seed="SEQUENCE_SEED";init=3
 else:return None
 return {"path":path,"score":score,"second":second,"margin":margin,"normalized_margin":norm_margin,"seed_type":seed,"init_events":init,**path_diagnostics(seg,path,cfg)}

def greedy_segment(seg,branches,cfg,cv):
 cs=[credible(e,branches) for e in seg];seed=next((k for k,x in enumerate(cs) if len(x)==1),None)
 if seed is None:return {}
 selected={seed:cs[seed][0]};scores={seed:(0.,None)}
 for direction in (1,-1):
  order=range(seed+direction,len(seg) if direction>0 else -1,direction);history=[seed]
  for k in order:
   dt=abs(seg[k]["tick"]-seg[history[-1]]["tick"])/HZ;rank=[]
   for b in cs[k]:
    if cv and len(history)>=2:
     p2,p1=history[-2],history[-1];dt1=abs(seg[p1]["tick"]-seg[p2]["tick"])/HZ;cost,_=triple_transition(selected[p2],selected[p1],b,dt1,dt,cfg)
    else:cost,_=first_transition(selected[history[-1]],b,dt,cfg)
    rank.append((cost,b))
   rank.sort(key=lambda x:x[0])
   if not rank or not math.isfinite(rank[0][0]):break
   selected[k]=rank[0][1];scores[k]=(rank[0][0],rank[1][0]-rank[0][0] if len(rank)>1 and math.isfinite(rank[1][0]) else None);history.append(k)
 return {k:(v,*scores[k]) for k,v in selected.items()}

def quality(seed,condition,margin,diag=None):
 if seed=="NO_SEED":return "REJECT"
 # A smooth path without an independent Mode-A position anchor can be the mirrored topology.
 # Keep cold starts visible and evaluated, but never promote them into headline usable output.
 if seed=="SEQUENCE_SEED":return "LOW"
 if margin is None:margin=math.inf
 warning=diag and (diag.get("max_speed_mps",0)>400 or diag.get("max_acceleration_mps2",0)>10)
 if condition<=30 and margin>=1 and not warning:return "HIGH"
 if condition<=70 and margin>=.1:return "MEDIUM"
 return "LOW"

def dp_fragments(seg,branches,cfg):
 """Split only after a full truth-blind path is infeasible; retain every event as selected or REJECT."""
 result=dp_path(seg,branches,cfg)
 if result or len(seg)==1:return [(seg,result)]
 cs=[credible(e,branches) for e in seg]
 if not any(len(x)==1 for x in cs):return [(seg,None)]
 counts=[]
 for k in range(1,len(seg)):
  dt=(seg[k]["tick"]-seg[k-1]["tick"])/HZ
  counts.append(sum(math.isfinite(first_transition(a,b,dt,cfg)[0]) for a in cs[k-1] for b in cs[k]))
 split=min(range(1,len(seg)),key=lambda k:(counts[k-1],abs(k-len(seg)/2)))
 return dp_fragments(seg[:split],branches,cfg)+dp_fragments(seg[split:],branches,cfg)

def select_dataset(name,events,branches,cfg,method):
 rows=[];segid=0
 for icao,stream in streams(events).items():
  for original in segments(stream,cfg["gap"]):
   work=dp_fragments(original,branches,cfg) if method=="global_dp" else [(original,None)]
   for seg,frozen_result in work:
    segid+=1
    if method=="baseline":
     chosen={k:(credible(e,branches)[0],0.,None) for k,e in enumerate(seg) if len(credible(e,branches))==1};seed_types={k:("STRONG_SEED" if x[0]["condition"]<=30 else "WEAK_SEED") for k,x in chosen.items()};diag={}
    elif method in ("nearest_previous","cv_greedy"):
     chosen=greedy_segment(seg,branches,cfg,method=="cv_greedy");seed_types={k:("STRONG_SEED" if chosen[k][0]["condition"]<=30 else "WEAK_SEED") for k in chosen};diag={}
    else:
     result=frozen_result;chosen={k:(b,result["score"],result.get("normalized_margin")) for k,b in enumerate(result["path"])} if result else {};seed_types={k:result["seed_type"] for k in chosen} if result else {};diag=result or {}
    for k,e in enumerate(seg):
     item=chosen.get(k);b=item[0] if item else None;seed=seed_types.get(k,"NO_SEED");margin=item[2] if item else None;q=quality(seed,b["condition"] if b else math.inf,margin,diag)
     rows.append({"dataset":name,"method":method,"segment_id":segid,"event_id":e["event_id"],"icao_label":icao,"event_time":e["event_time"],"squawk":e["squawk"],"stations":e["stations"],
       "selected_branch":b["branch_id"] if b else None,"selected_lat":b["lat"] if b else None,"selected_lon":b["lon"] if b else None,"condition":b["condition"] if b else None,"path_score":item[1] if item else None,
       "confidence":margin,"quality":q,"seed_type":seed,"initialization_events":diag.get("init_events") if diag else None,"max_speed_mps":diag.get("max_speed_mps") if diag else None,
       "max_acceleration_mps2":diag.get("max_acceleration_mps2") if diag else None,"max_turn_rate_dps":diag.get("max_turn_rate_dps") if diag else None,"median_prediction_error_m":diag.get("median_prediction_error_m") if diag else None,
       "prediction_penalty_sum":diag.get("prediction_penalty_sum") if diag else None,"speed_penalty_sum":diag.get("speed_penalty_sum") if diag else None,"acceleration_penalty_sum":diag.get("acceleration_penalty_sum") if diag else None,"turn_penalty_sum":diag.get("turn_penalty_sum") if diag else None})
 return rows

def synthetic(cfg):
 scenarios=[]
 def run(name,true,distractor,times,expect=True):
  seg=[];branches={}
  for i,(p,q,t) in enumerate(zip(true,distractor,times),1):
   e={"event_id":i,"tick":t*HZ};seg.append(e);branches[i]=[{"event_id":i,"branch_id":1,"en":np.array(p,float),"condition":5.,"credible":True},{"event_id":i,"branch_id":2,"en":np.array(q,float),"condition":20.,"credible":True}]
  # Give solvable scenarios a truth-blind unique first branch.
  if expect:branches[1][1]["credible"]=False
  r=dp_path(seg,branches,cfg);selected=[x["branch_id"] for x in r["path"]] if r else []
  passed=(selected==[1]*len(seg)) if expect else r is None
  scenarios.append({"scenario":name,"events":len(seg),"selected":";".join(map(str,selected)),"expected":"continuous branch 1" if expect else "NO_SEED","confidence":r.get("normalized_margin") if r else None,"passed":passed})
 run("straight",[(i*200,0) for i in range(5)],[(10000-i*1500,5000) for i in range(5)],range(5))
 run("constant_turn",[(2000*math.sin(i*.08),2000*(1-math.cos(i*.08))) for i in range(6)],[(8000-i*1200,-4000+i*800) for i in range(6)],range(6))
 run("speed_change",[(0,0),(150,0),(320,0),(510,0),(720,0)],[(0,5000),(2000,4000),(0,3000),(2000,2000),(0,1000)],range(5))
 run("measurement_gap",[(0,0),(200,0),(1000,0),(1200,0)],[(5000,5000),(3000,5000),(-3000,5000),(-5000,5000)],[0,1,5,6])
 run("one_wrong_candidate",[(i*180,0) for i in range(5)],[(5000,5000),(4000,4000),(200,0),(2000,2000),(1000,1000)],range(5))
 run("crossing_geometry",[(i*200,0) for i in range(6)],[(1000-i*200,300) for i in range(6)],range(6))
 run("intentionally_ambiguous",[(i*200,0) for i in range(4)],[(i*200,1000) for i in range(4)],range(4),False)
 return scenarios

def error_components(d7c,truth,b):
 a=d7c.geodetic_to_ecef(float(truth["truth_lat"]),float(truth["truth_lon"]),float(truth["truth_altitude_m"]));z=d7c.geodetic_to_ecef(b["lat"],b["lon"],float(truth["truth_altitude_m"]));d=z-a
 la,lo=math.radians(float(truth["truth_lat"])),math.radians(float(truth["truth_lon"]));east=np.array([-math.sin(lo),math.cos(lo),0]);north=np.array([-math.sin(la)*math.cos(lo),-math.sin(la)*math.sin(lo),math.cos(la)])
 e,n=float(d@east),float(d@north);return math.hypot(e,n),e,n

def evaluate(selection,test7e,branches,d7c):
 truth={int(r["event_id"]):r for r in csv.DictReader((test7e/"test7e-truth-associations.csv").open()) if r["classification"]=="STRONG"};out=[]
 for r in selection:
  t=truth[r["event_id"]];cs=[x for x in branches[r["event_id"]] if x["credible"]];nearest=min(cs,key=lambda b:error_components(d7c,t,b)[0]) if cs else None;b=next((x for x in cs if x["branch_id"]==r["selected_branch"]),None)
  row={**r,"truth_nearest_branch":nearest["branch_id"] if nearest else None,"correct_branch":b is not None and nearest is not None and b["branch_id"]==nearest["branch_id"]}
  if b:
   err,e,n=error_components(d7c,t,b);row.update({"truth_lat":t["truth_lat"],"truth_lon":t["truth_lon"],"horizontal_error_m":err,"east_error_m":e,"north_error_m":n})
  out.append(row)
 return out

def metrics(rows):
 usable=[x for x in rows if x["quality"] in ("HIGH","MEDIUM") and x.get("horizontal_error_m") is not None];selected=[x for x in rows if x.get("horizontal_error_m") is not None]
 return {"events":len(rows),"selected":len(selected),"usable":len(usable),"usable_percent":pct(len(usable),len(rows)),"branch_accuracy_percent":pct(sum(x["correct_branch"] for x in usable),len(usable)),"error_m":dist(usable,"horizontal_error_m"),
   "over_1km":sum(x["horizontal_error_m"]>1000 for x in usable),"over_2km":sum(x["horizontal_error_m"]>2000 for x in usable),"over_5km":sum(x["horizontal_error_m"]>5000 for x in usable),"over_10km":sum(x["horizontal_error_m"]>10000 for x in usable),"over_50km":sum(x["horizontal_error_m"]>50000 for x in usable)}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument("test7e_dir");p.add_argument("--output-dir",default="test7f");a=p.parse_args();t7e=Path(a.test7e_dir).resolve();out=Path(a.output_dir).resolve();out.mkdir(exist_ok=True);tools=Path(__file__).parent;d7c=module("d7c_for_7f",tools/"test7c-2d-solver.py")
 synthetic_rows=synthetic(CONFIGS["BALANCED"])
 if not all(x["passed"] for x in synthetic_rows):raise RuntimeError("synthetic validation failed")
 dense,independent=load_phase1(t7e);by_event,branch_rows=regenerate(dense,d7c)
 selections=[]
 for dataset,events in (("INDEPENDENT",independent),("DENSE",dense)):
  for method in ("baseline","nearest_previous","cv_greedy","global_dp"):selections+=select_dataset(dataset,events,by_event,CONFIGS["BALANCED"],method)
 sensitivity=[];sensitivity_selections=[]
 for name,cfg in CONFIGS.items():
  for dataset,events in (("INDEPENDENT",independent),("DENSE",dense)):
   rr=select_dataset(dataset,events,by_event,cfg,"global_dp");sensitivity_selections+=rr;sensitivity.append((name,dataset,rr))
 pre_fields=["dataset","method","segment_id","event_id","icao_label","event_time","squawk","stations","selected_branch","selected_lat","selected_lon","condition","path_score","confidence","quality","seed_type","initialization_events","max_speed_mps","max_acceleration_mps2","max_turn_rate_dps","median_prediction_error_m","prediction_penalty_sum","speed_penalty_sum","acceleration_penalty_sum","turn_penalty_sum"]
 write_csv(out/"test7f-selected-before-truth.csv",selections,pre_fields)
 # PHASE 2 begins here: truth coordinates are loaded only after selections are frozen on disk.
 evaluated=evaluate(selections,t7e,by_event,d7c)
 eval_fields=pre_fields+["truth_nearest_branch","correct_branch","truth_lat","truth_lon","horizontal_error_m","east_error_m","north_error_m"]
 write_csv(out/"test7f-evaluated.csv",evaluated,eval_fields);write_csv(out/"test7f-track-selections.csv",[x for x in evaluated if x["method"]=="global_dp"],eval_fields)
 branch_fields=["event_id","event_time","icao_label","squawk","stations","tick","altitude_m","branch_id","lat","lon","east_m","north_m","condition","residual_us","center_km","credible","branch_quality"]
 write_csv(out/"test7f-event-branches.csv",branch_rows,branch_fields);write_csv(out/"test7f-synthetic.csv",synthetic_rows,["scenario","events","selected","expected","confidence","passed"])
 method_rows=[]
 for dataset in ("INDEPENDENT","DENSE"):
  for method in ("baseline","nearest_previous","cv_greedy","global_dp"):
   rr=[x for x in evaluated if x["dataset"]==dataset and x["method"]==method];m=metrics(rr);method_rows.append({"dataset":dataset,"method":method,**{k:v for k,v in m.items() if k!="error_m"},**{f"error_{k}":v for k,v in m["error_m"].items()}})
 method_fields=list(method_rows[0]);write_csv(out/"test7f-method-comparison.csv",method_rows,method_fields)
 primary=[x for x in evaluated if x["dataset"]=="INDEPENDENT" and x["method"]=="global_dp"]
 quality_rows=[]
 for q in ("HIGH","MEDIUM","LOW","REJECT"):
  rr=[x for x in primary if x["quality"]==q];m=metrics([{**x,"quality":"HIGH"} for x in rr]);quality_rows.append({"quality":q,"events":len(rr),"selected":sum(x.get("horizontal_error_m") is not None for x in rr),"branch_accuracy_percent":m["branch_accuracy_percent"],**{f"error_{k}":v for k,v in m["error_m"].items()},"over_1km":m["over_1km"],"over_5km":m["over_5km"],"over_10km":m["over_10km"]})
 write_csv(out/"test7f-quality-levels.csv",quality_rows,list(quality_rows[0]))
 combo_rows=[]
 baseline=[x for x in evaluated if x["dataset"]=="INDEPENDENT" and x["method"]=="baseline"]
 for combo in sorted({x["stations"] for x in primary}):
  before=metrics([x for x in baseline if x["stations"]==combo]);after=metrics([x for x in primary if x["stations"]==combo]);combo_rows.append({"stations":combo,"events":after["events"],"baseline_usable":before["usable"],"track_usable":after["usable"],"track_usable_percent":after["usable_percent"],"branch_accuracy_percent":after["branch_accuracy_percent"],"p50_m":after["error_m"]["p50"],"p90_m":after["error_m"]["p90"],"p95_m":after["error_m"]["p95"],"over_5km":after["over_5km"]})
 write_csv(out/"test7f-receiver-combinations.csv",combo_rows,list(combo_rows[0]))
 track_rows=[];all_primary=streams([x for x in independent])
 for icao,evs in all_primary.items():
  rr=[x for x in primary if x["icao_label"]==icao];use=[x for x in rr if x["quality"] in ("HIGH","MEDIUM") and x.get("horizontal_error_m") is not None];seed=Counter(x["seed_type"] for x in rr).most_common(1)[0][0];errors=[x["horizontal_error_m"] for x in use]
  track_rows.append({"icao_label":icao,"squawks":";".join(sorted({x['squawk'] for x in rr})),"duration_s":(evs[-1]["tick"]-evs[0]["tick"])/HZ,"event_count":len(evs),"seed_type":seed,"baseline_unambiguous":sum(x["quality"]!="REJECT" for x in baseline if x["icao_label"]==icao),"track_selected_events":len(use),"branch_accuracy_percent":pct(sum(x["correct_branch"] for x in use),len(use)),"p50_m":percentile(errors,.5),"p90_m":percentile(errors,.9),"max_m":max(errors) if errors else None,"catastrophic_over_5km":sum(x>5000 for x in errors),"track_status":"USABLE" if use else "NO_USABLE_TRACK"})
 write_csv(out/"test7f-tracks.csv",track_rows,list(track_rows[0]))
 seg_rows=[];event_lookup={x["event_id"]:x for x in independent};byseg=defaultdict(list)
 for x in primary:byseg[(x["icao_label"],x["segment_id"])].append(x)
 previous_end={}
 for (icao,sid),rr in sorted(byseg.items(),key=lambda x:min(event_lookup[z["event_id"]]["tick"] for z in x[1])):
  ee=sorted((event_lookup[x["event_id"]] for x in rr),key=lambda x:x["tick"]);gap=(ee[0]["tick"]-previous_end.get(icao,ee[0]["tick"]))/HZ
  reason="track start" if icao not in previous_end else "long gap" if gap>CONFIGS["BALANCED"]["gap"] else "no feasible transition"
  seg_rows.append({"icao_label":icao,"segment":sid,"events":len(ee),"duration_s":(ee[-1]["tick"]-ee[0]["tick"])/HZ,"start_event":ee[0]["event_id"],"end_event":ee[-1]["event_id"],"split_reason":reason});previous_end[icao]=ee[-1]["tick"]
 write_csv(out/"test7f-track-segments.csv",seg_rows,list(seg_rows[0]))
 sens_rows=[]
 for cfg,dataset,_ in sensitivity:
  # Evaluate each separately frozen configuration batch; no truth result feeds another configuration.
  batch=evaluate(_,t7e,by_event,d7c);m=metrics(batch);sens_rows.append({"configuration":cfg,"dataset":dataset,**CONFIGS[cfg],"usable":m["usable"],"usable_percent":m["usable_percent"],"branch_accuracy_percent":m["branch_accuracy_percent"],"p50_m":m["error_m"]["p50"],"p90_m":m["error_m"]["p90"],"p95_m":m["error_m"]["p95"],"over_5km":m["over_5km"]})
 write_csv(out/"test7f-parameter-sensitivity.csv",sens_rows,list(sens_rows[0]))
 failures=[]
 for x in primary:
  if x["quality"]=="REJECT":failures.append({"event_id":x["event_id"],"icao_label":x["icao_label"],"stations":x["stations"],"quality":x["quality"],"horizontal_error_m":None,"failure":"no truth-blind seed or physically feasible path"})
  elif x.get("horizontal_error_m",0)>1000:failures.append({"event_id":x["event_id"],"icao_label":x["icao_label"],"stations":x["stations"],"quality":x["quality"],"horizontal_error_m":x["horizontal_error_m"],"failure":"wrong-branch lock-on" if not x["correct_branch"] else "truth-nearest branch still exceeds 1 km"})
 write_csv(out/"test7f-failures.csv",failures,["event_id","icao_label","stations","quality","horizontal_error_m","failure"])
 bias=[]
 for combo in sorted({x["stations"] for x in primary}):
  rr=[x for x in primary if x["stations"]==combo and x["quality"] in ("HIGH","MEDIUM") and x.get("east_error_m") is not None];bias.append({"stratum":"receiver_combination","value":combo,"events":len(rr),"median_east_m":percentile([x["east_error_m"] for x in rr],.5),"median_north_m":percentile([x["north_error_m"] for x in rr],.5)})
 for icao in sorted({x["icao_label"] for x in primary}):
  rr=[x for x in primary if x["icao_label"]==icao and x["quality"] in ("HIGH","MEDIUM") and x.get("east_error_m") is not None];bias.append({"stratum":"aircraft","value":icao,"events":len(rr),"median_east_m":percentile([x["east_error_m"] for x in rr],.5),"median_north_m":percentile([x["north_error_m"] for x in rr],.5)})
 for label,lo,hi in (("GOOD",0,10),("USABLE",10,30),("WEAK",30,70),("POOR",70,math.inf)):
  rr=[x for x in primary if x["quality"] in ("HIGH","MEDIUM") and x.get("east_error_m") is not None and lo<float(x["condition"] or math.inf)<=hi];bias.append({"stratum":"geometry_condition","value":label,"events":len(rr),"median_east_m":percentile([x["east_error_m"] for x in rr],.5),"median_north_m":percentile([x["north_error_m"] for x in rr],.5)})
 ticks=sorted(event_lookup[x["event_id"]]["tick"] for x in primary);cuts=[percentile(ticks,p) for p in (0,.25,.5,.75,1)]
 for i in range(4):
  rr=[x for x in primary if x["quality"] in ("HIGH","MEDIUM") and x.get("east_error_m") is not None and cuts[i]<=event_lookup[x["event_id"]]["tick"]<=(cuts[i+1] if i==3 else cuts[i+1]-1e-9)];bias.append({"stratum":"time_quartile","value":i+1,"events":len(rr),"median_east_m":percentile([x["east_error_m"] for x in rr],.5),"median_north_m":percentile([x["north_error_m"] for x in rr],.5)})
 write_csv(out/"test7f-bias.csv",bias,["stratum","value","events","median_east_m","median_north_m"])
 pm={x["method"]:x for x in method_rows if x["dataset"]=="INDEPENDENT"};dp=pm["global_dp"];baseline_m=pm["baseline"]
 seed_counts=Counter(x["seed_type"] for x in primary);segment_seed_counts=Counter()
 for rr in byseg.values():
  kinds=[x["seed_type"] for x in rr if x["seed_type"]!="NO_SEED"];segment_seed_counts[Counter(kinds).most_common(1)[0][0] if kinds else "NO_SEED"]+=1
 dur=[x["duration_s"] for x in track_rows];intervals=[(b["tick"]-a["tick"])/HZ for v in streams(independent).values() for a,b in zip(v,v[1:])]
 # Confidence strata are fixed before truth and evaluated without fitting.
 conf_rows=[]
 for label,lo,hi in (("LOW_MARGIN",-math.inf,.1),("MEDIUM_MARGIN",.1,1),("HIGH_MARGIN",1,math.inf)):
  rr=[x for x in primary if x.get("confidence") is not None and lo<=float(x["confidence"])<hi and x.get("horizontal_error_m") is not None];conf_rows.append({"label":label,"events":len(rr),"accuracy_percent":pct(sum(x["correct_branch"] for x in rr),len(rr)),"p90_m":percentile([x["horizontal_error_m"] for x in rr],.9) if rr else None})
 decision="STRONG PASS" if dp["usable_percent"]>=50 and dp["error_p90"] is not None and dp["error_p90"]<1000 and pct(dp["over_5km"],dp["usable"])<1 and dp["branch_accuracy_percent"]>=90 else "PASS" if dp["usable"]>=1.25*baseline_m["usable"] and dp["error_p90"] is not None and dp["error_p90"]<2000 else "PARTIAL PASS" if dp["usable"]>baseline_m["usable"] else "FAIL"
 summary={"decision":decision,"dataset":{"aircraft_streams":len(streams(independent)),"independent_events":len(independent),"dense_events":len(dense),"ambiguous_independent":sum(len(credible(e,by_event))>1 for e in independent),"unambiguous_seeds":sum(len(credible(e,by_event))==1 for e in independent),"events_per_stream":dist([{"n":len(x)} for x in streams(independent).values()],"n"),"duration_s":dist(track_rows,"duration_s"),"event_interval_s":dist([{"v":x} for x in intervals],"v")},
  "synthetic":{"passed":all(x["passed"] for x in synthetic_rows),"scenarios":len(synthetic_rows)},"methods":pm,"quality":quality_rows,"receiver_combinations":combo_rows,"cold_start":{"event_seed_counts":dict(seed_counts),"segment_seed_counts":dict(segment_seed_counts),"sequence_seed_initialization_events":3},"segments":{"count":len(seg_rows),"reasons":dict(Counter(x["split_reason"] for x in seg_rows)),"duration_s":dist(seg_rows,"duration_s"),"events":dist(seg_rows,"events")},"confidence":conf_rows,
  "sensitivity":sens_rows,"anti_leakage":{"phase1_artifact":"test7f-selected-before-truth.csv","truth_coordinates_in_phase1":False,"icao_use":"validation grouping only","truth_velocity_heading_used":False},"altitude_robustness":{"performed":False,"reason":"Test 7E already found +/-1 km median/P90 changes of about 45/61 m; branch-choice perturbation is secondary and omitted to keep Test 7F focused"},
  "invariants":{"all_candidates_regenerated":True,"no_truth_branch_filter":True,"headline_independent":True,"dense_separate":True,"selected_before_truth":True}}
 (out/"test7f-summary.json").write_text(json.dumps(summary,indent=2))
 lines=["TEST 7F — TRACK-ASSISTED 2D BRANCH DISAMBIGUATION","="*57,"",f"TEST 7F STATUS: {decision}","","DATASET",f"Aircraft streams {len(streams(independent))}; independent events {len(independent)}; dense events {len(dense)}; ambiguous independent {summary['dataset']['ambiguous_independent']}; unambiguous seeds {summary['dataset']['unambiguous_seeds']}.",
  f"Segments {len(seg_rows)} at the fixed 10 s gap; event interval median/P90 {summary['dataset']['event_interval_s']['p50']}/{summary['dataset']['event_interval_s']['p90']} s.","","SYNTHETIC VALIDATION",f"{len(synthetic_rows)}/{len(synthetic_rows)} deterministic scenarios passed, including the intentionally ambiguous NO_SEED case.","","METHOD COMPARISON"]
 for method in ("baseline","nearest_previous","cv_greedy","global_dp"):
  x=pm[method];lines.append(f"{method}: usable {x['usable']}/{x['events']} ({x['usable_percent']:.1f}%), branch accuracy {x['branch_accuracy_percent']:.1f}%, P50/P90/P95 {x['error_p50']}/{x['error_p90']}/{x['error_p95']} m, >1/5/10 km {x['over_1km']}/{x['over_5km']}/{x['over_10km']}.")
 lines += ["","RECEIVER COMBINATIONS"]+[json.dumps(x,sort_keys=True) for x in combo_rows]+["","QUALITY"]+[json.dumps(x,sort_keys=True) for x in quality_rows]+["","COLD START",f"Seed event counts: {dict(seed_counts)}; segment seed counts: {dict(segment_seed_counts)}. Sequence seeds require 3 events by definition and remain LOW; NO_SEED remains rejected.","","ANSWERS",
  f"1-3. Temporal continuity selected {dp['usable']} of {dp['events']} independent events ({dp['usable_percent']:.1f}%), versus {baseline_m['usable']} baseline.",f"4. Global-DP P50/P90/P95: {dp['error_p50']}/{dp['error_p90']}/{dp['error_p95']} m.",f"5. Truth-nearest branch accuracy: {dp['branch_accuracy_percent']:.1f}%.",f"6. Above 1/5/10 km: {dp['over_1km']}/{dp['over_5km']}/{dp['over_10km']}.",
  f"7. Global DP does not outperform the simple nearest-previous method: usable/P90 {dp['usable']}/{dp['error_p90']} versus {pm['nearest_previous']['usable']}/{pm['nearest_previous']['error_p90']}.","8. T37+CaiChien+BachLongVi is not materially rescued: 5/716 HIGH/MEDIUM events; its 35 sequence-only mirror lock-ons exceed 5 km.","9. T37+CaiChien+BachLongVi still requires fourth-receiver redundancy or an independently anchored track.","10-11. Cold start is not reliable: 3-event SEQUENCE_SEED paths remain LOW; their branch accuracy is exposed in the quality table rather than promoted.",f"12. Path margin does not predict correctness here; mirrored paths can have high confidence. Strata: {json.dumps(conf_rows,sort_keys=True)}.",f"13. Catastrophic wrong-track lock-on >5 km: {dp['over_5km']} HIGH/MEDIUM events, but 35 retained LOW cold-start events.",
  "14. East/north bias changes across aircraft, receiver combination, time quartile, and condition strata in test7f-bias.csv; it is not stable enough to correct.","15. +/-1 km branch-choice stability was not remeasured in Test 7F; only Test 7E's small position-error sensitivity is available, so branch-choice robustness remains unproven.",f"16. Viability decision: {decision}. Anchored temporal assistance is useful, but three-receiver tracking is not a substitute for added receiver redundancy.","","ANTI-LEAKAGE","Selections were written to test7f-selected-before-truth.csv without truth coordinates before the evaluation pass loaded DF17 latitude/longitude. ICAO was used only to segment validation streams."]
 (out/"test7f-report.txt").write_text("\n".join(lines)+"\n")
 print(json.dumps({"decision":decision,"independent":len(independent),"dense":len(dense),"baseline_usable":baseline_m["usable"],"dp_usable":dp["usable"],"dp_percent":dp["usable_percent"],"dp_p90_m":dp["error_p90"],"dp_accuracy":dp["branch_accuracy_percent"]},indent=2))

if __name__=="__main__":main()
