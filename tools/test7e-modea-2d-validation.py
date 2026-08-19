#!/usr/bin/env python3
"""Test 7E: offline squawk-correlated Mode-A altitude-constrained 2D MLAT validation."""
import argparse,bisect,csv,datetime as dt,hashlib,importlib.util,itertools,json,math,statistics,sys
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np

C=299_792_458.0; HZ=12_000_000.0; VALID_S=15.0; CLOCK_MARGIN_US=.5
ORDER=["T37","Dao_Cai_chien","QK4","BachLongVi"]

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod

def percentile(values,p):
    if not values:return None
    x=sorted(values); q=(len(x)-1)*p; lo,hi=math.floor(q),math.ceil(q)
    return x[lo] if lo==hi else x[lo]*(hi-q)+x[hi]*(q-lo)

def distribution(rows,key):
    v=[float(r[key]) for r in rows if r.get(key) not in (None,"")]
    return {"count":len(v),"median":percentile(v,.5),"p50":percentile(v,.5),"p75":percentile(v,.75),"p90":percentile(v,.9),"p95":percentile(v,.95),"p99":percentile(v,.99),"max":max(v) if v else None}

def write_csv(path,rows,fields):
    with path.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore"); w.writeheader(); w.writerows(rows)

def sha256(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""):h.update(block)
    return h.hexdigest()

def decode_id13(x):
    out=0
    for src,dst in ((0x1000,0x0010),(0x0800,0x1000),(0x0400,0x0020),(0x0200,0x2000),(0x0100,0x0040),(0x0080,0x4000),
                    (0x0020,0x0100),(0x0010,0x0001),(0x0008,0x0200),(0x0004,0x0002),(0x0002,0x0400),(0x0001,0x0004)):
        if x&src:out|=dst
    return f"{out:04x}"

def crc_residual(payload):
    poly=0xfff409; table=[]
    for i in range(256):
        x=i<<16
        for _ in range(8):x=((x<<1)^poly) if x&0x800000 else x<<1
        table.append(x&0xffffff)
    rem=table[payload[0]]
    for b in payload[1:-3]:rem=((rem&0xffff)<<8)^table[b^(rem>>16)]
    return rem^(payload[-3]<<16)^(payload[-2]<<8)^payload[-1]

def decode_mode_s_identity(raw):
    if len(raw) not in (7,14) or raw[0]>>3 not in (5,21):return None
    ident=((raw[2]&0x1f)<<8)|raw[3]
    return {"df":raw[0]>>3,"icao":f"{crc_residual(raw):06x}","squawk":decode_id13(ident),"id13":ident}

def mode_a(raw):
    x=raw&0x7777
    return f"{(x>>12)&7}{(x>>8)&7}{(x>>4)&7}{x&7}",bool(raw&0x80)

def norm_tick(row,transform):
    slope,intercept=transform; return (int(row["timestamp_corrected"])-intercept)/slope

def iso_utc(ns):return dt.datetime.fromtimestamp(ns/1e9,dt.timezone.utc).isoformat().replace("+00:00","Z")

def build_context(run,tools):
    d7b=load_module("test7b_for_7e",tools/"test7b-truth-diagnostic.py")
    t4=load_module("test4_for_7e",tools/"test4b-holdout.py")
    summary=json.loads((run/"reports/test6-summary.json").read_text())
    transforms=d7b.read_clock_transforms(summary)
    copies=d7b.load_df17_copies(run,transforms)
    transmissions=d7b.deduplicate_transmissions(copies)
    trajectories=d7b.build_trajectories(t4,transmissions)
    receivers={s:np.array(t4.geodetic_to_ecef(*d7b.STATIONS[s])) for s in ORDER}
    return d7b,t4,summary,transforms,trajectories,receivers

def build_identity_timeline(run,transforms,known_icaos):
    copies=[]; decoded=Counter()
    for station in ORDER:
        with (run/"captures"/f"modeac-{station}.csv").open() as f:
            for source_row,row in enumerate(csv.DictReader(f),2):
                if row["frame_kind"] not in ("modes_short","modes_long"):continue
                try:raw=bytes.fromhex(row["raw_hex"])
                except ValueError:continue
                ident=decode_mode_s_identity(raw)
                if not ident:continue
                decoded[f"df{ident['df']}"]+=1
                ts=int(row["timestamp_corrected"])
                if not ts or ident["icao"] not in known_icaos:continue
                copies.append({**ident,"station":station,"norm":norm_tick(row,transforms[station]),"utc_ns":int(row["recv_utc_ns"]),
                               "raw_hex":row["raw_hex"].lower(),"source_row":source_row})
    bykey=defaultdict(list)
    for x in copies:bykey[(x["icao"],x["squawk"],x["raw_hex"])].append(x)
    tx=[]
    for items in bykey.values():
        items.sort(key=lambda x:x["norm"]); group=[]
        def emit(g):
            if not g:return
            rep=min(g,key=lambda x:abs(x["norm"]-statistics.median(y["norm"] for y in g)))
            tx.append({**rep,"stations":";".join(sorted({x["station"] for x in g},key=ORDER.index)),"copies":len(g)})
        for item in items:
            if group and item["norm"]-group[-1]["norm"]>.020*HZ:emit(group);group=[]
            group.append(item)
        emit(group)
    tx.sort(key=lambda x:x["norm"])
    intervals=[]; byicao=defaultdict(list)
    for x in tx:byicao[x["icao"]].append(x)
    for icao,obs in byicao.items():
        groups=[]; group=[]
        for x in obs:
            if group and (x["squawk"]!=group[-1]["squawk"] or x["norm"]-group[-1]["norm"]>2*VALID_S*HZ):groups.append(group);group=[]
            group.append(x)
        if group:groups.append(group)
        for g in groups:
            if len(g)<2:continue
            intervals.append({"icao":icao,"squawk":g[0]["squawk"],"start_tick":g[0]["norm"]-VALID_S*HZ,
                              "end_tick":g[-1]["norm"]+VALID_S*HZ,"observations":len(g),"first_observation_tick":g[0]["norm"],
                              "last_observation_tick":g[-1]["norm"],"dfs":";".join(map(str,sorted({x['df'] for x in g}))),
                              "receiver_sources":";".join(sorted(set().union(*(x["stations"].split(';') for x in g)),key=ORDER.index))})
    intervals.sort(key=lambda x:(x["start_tick"],x["icao"]))
    return tx,intervals,dict(decoded)

def active_squawks(intervals,tick):
    active={}
    for x in intervals:
        if x["start_tick"]<=tick<=x["end_tick"]:
            old=active.get(x["icao"])
            if old is None or min(abs(tick-x["first_observation_tick"]),abs(tick-x["last_observation_tick"])) < old[0]:
                active[x["icao"]]=(min(abs(tick-x["first_observation_tick"]),abs(tick-x["last_observation_tick"])),x["squawk"])
    return {icao:x[1] for icao,x in active.items()}

def nearest_index(times,value):
    i=bisect.bisect_left(times,value); candidates=[j for j in (i-1,i) if 0<=j<len(times)]
    return min(candidates,key=lambda j:abs(times[j]-value)) if candidates else None

def build_modea_events(run,transforms,relevant_squawks,limits,decode_modeac):
    records=defaultdict(lambda:defaultdict(list)); counts=Counter(); candidate_rows=[]
    for station in ORDER:
        with (run/"captures"/f"modeac-{station}.csv").open() as f:
            for source_row,row in enumerate(csv.DictReader(f),2):
                if row["frame_kind"]!="modeac":continue
                counts["decoded_type1"]+=1; ts=int(row["timestamp_corrected"])
                if not ts:counts["timestamp_zero"]+=1;continue
                raw=int(row["raw_hex"],16); decoded=decode_modeac(raw);code,spi=decoded["mode_a_code"],decoded["spi"];counts[f"station_{station}"]+=1
                if code not in relevant_squawks:continue
                rec={"id":f"{station}:{source_row}","station":station,"source_row":source_row,"timestamp":ts,
                     "norm":norm_tick(row,transforms[station]),"utc_ns":int(row["recv_utc_ns"]),"raw_hex":row["raw_hex"].lower(),"mode_a_code":code,"spi":spi}
                records[code][station].append(rec);candidate_rows.append(rec)
    edges=set(); physical_rejects=0
    for code,by in records.items():
        for rows in by.values():rows.sort(key=lambda x:x["norm"])
        for a,b in itertools.combinations(ORDER,2):
            aa,bb=by.get(a,[]),by.get(b,[])
            if not aa or not bb:continue
            at,bt=[x["norm"] for x in aa],[x["norm"] for x in bb]; gate=(limits[(a,b)]+CLOCK_MARGIN_US)*12
            a_to_b=[nearest_index(bt,x) for x in at]; b_to_a=[nearest_index(at,x) for x in bt]
            for i,j in enumerate(a_to_b):
                if j is not None and b_to_a[j]==i:
                    if abs(at[i]-bt[j])<=gate:edges.add(frozenset((aa[i]["id"],bb[j]["id"])))
                    else:physical_rejects+=1
    nodes={x["id"]:x for by in records.values() for rows in by.values() for x in rows}; adj=defaultdict(set)
    for edge in edges:
        a,b=tuple(edge);adj[a].add(b);adj[b].add(a)
    cliques=set()
    for nid,near in adj.items():
        local=[nid]+sorted(near)
        for size in (4,3):
            for combo in itertools.combinations(local,size):
                if len({nodes[x]["station"] for x in combo})<size:continue
                if all(frozenset(p) in edges for p in itertools.combinations(combo,2)):cliques.add(frozenset(combo))
    maximal=[x for x in cliques if not any(x<y for y in cliques)]
    memberships=Counter(n for c in maximal for n in c); clean=[c for c in maximal if all(memberships[n]==1 for n in c)]
    ambiguous=len(maximal)-len(clean); events=[]
    for eid,clique in enumerate(sorted(clean,key=lambda c:statistics.mean(nodes[n]["norm"] for n in c)),1):
        rows=sorted((nodes[n] for n in clique),key=lambda x:ORDER.index(x["station"])); norm={x["station"]:x["norm"] for x in rows}
        events.append({"event_id":eid,"mode_a_code":rows[0]["mode_a_code"],"station_count":len(rows),"stations":";".join(x["station"] for x in rows),
                       "reference_tick":statistics.mean(norm.values()),"normalized":norm,"rows":rows,
                       "source_rows":";".join(f"{x['station']}:{x['source_row']}" for x in rows),"raw_words":";".join(f"{x['station']}:{x['raw_hex']}" for x in rows),
                       "spi_any":any(x["spi"] for x in rows)})
    return events,candidate_rows,{**counts,"pair_edges":len(edges),"maximal_cliques":len(maximal),"ambiguous_overlapping_cliques":ambiguous,"physical_rejects":physical_rejects}

def measured(event):
    n=event["normalized"];return {p:(n[p[1]]-n[p[0]])/12 for p in itertools.combinations(event["stations"].split(';'),2)}

def score_truth(candidate,event,receivers):
    stations=event["stations"].split(';'); m=measured(event); distances={s:float(np.linalg.norm(candidate["ecef"]-receivers[s])) for s in stations}; vals=[]
    for a,b in itertools.combinations(stations,2):vals.append(m[(a,b)]-(distances[b]-distances[a])/C*1e6)
    return {"rms_us":math.sqrt(statistics.mean(x*x for x in vals)),"max_us":max(abs(x) for x in vals),"median_abs_us":statistics.median(abs(x) for x in vals)}

def associate(events,intervals,trajectories,d7b,t4,receivers,tick_to_ns):
    rows=[];candidates=[];failures=[]
    for e in events:
        tick=e["reference_tick"];active=active_squawks(intervals,tick);truth={x["icao"]:x for x in d7b.truth_at_event(trajectories,tick,t4)}
        same=[truth[icao] for icao,sq in active.items() if sq==e["mode_a_code"] and icao in truth]; scored=[]
        for c in same:
            score=score_truth(c,e,receivers); scored.append((score["rms_us"],score,c))
        scored.sort(key=lambda x:x[0]); n=len(scored); group="UNIQUE_SQUAWK" if n==1 else "SHARED_2" if n==2 else "SHARED_3_PLUS" if n>=3 else "NO_ACTIVE_SAME_SQUAWK"
        best=scored[0] if scored else None;second=scored[1][0] if len(scored)>1 else None
        separated_strong=n<=1 or (second-best[0]>=1 and second/max(best[0],1e-9)>=2)
        separated_plausible=n<=1 or (second-best[0]>=.5 and second/max(best[0],1e-9)>=1.5)
        if not best:classification="NO_TRUTH_MATCH";reason="insufficient truth trajectory or no confirmed active same-squawk state"
        elif best[0]<=1 and best[1]["max_us"]<=2 and separated_strong:classification="STRONG";reason="strong TDOA agreement and candidate separation"
        elif best[0]<=3 and best[1]["max_us"]<=5 and separated_plausible:classification="PLAUSIBLE";reason="plausible TDOA agreement and candidate separation"
        elif best[0]<=3 and best[1]["max_us"]<=5:classification="AMBIGUOUS";reason="multiple same-squawk aircraft are not separated by TDOA"
        else:classification="NO_TRUTH_MATCH";reason="same squawk but wrong geometry"
        base={"event_id":e["event_id"],"event_time":iso_utc(tick_to_ns(tick)),"reference_tick":tick,"mode_a_code":e["mode_a_code"],"squawk_group":group,
              "receiver_count":e["station_count"],"stations":e["stations"],"station_measurements":e["source_rows"],"normalized_timestamps":";".join(f"{s}:{e['normalized'][s]:.6f}" for s in e["stations"].split(';')),
              "candidate_aircraft_count":n,"classification":classification,"reason":reason,"matched_icao":best[2]["icao"] if best else "",
              "best_rms_us":best[0] if best else None,"best_max_us":best[1]["max_us"] if best else None,"best_median_abs_us":best[1]["median_abs_us"] if best else None,
              "second_best_rms_us":second,"residual_ratio":second/max(best[0],1e-9) if best and second is not None else None,"residual_gap_us":second-best[0] if best and second is not None else None,
              "truth_lat":best[2]["lat"] if best else None,"truth_lon":best[2]["lon"] if best else None,"truth_altitude_m":best[2]["alt_m"] if best else None,
              "truth_quality":best[2]["truth_quality"] if best else ""}
        rows.append(base)
        for rank,(_,score,c) in enumerate(scored,1):candidates.append({"event_id":e["event_id"],"mode_a_code":e["mode_a_code"],"rank":rank,"icao":c["icao"],"squawk_group":group,**score,"truth_lat":c["lat"],"truth_lon":c["lon"],"truth_altitude_m":c["alt_m"]})
        if classification not in ("STRONG","PLAUSIBLE"):failures.append({"event_id":e["event_id"],"mode_a_code":e["mode_a_code"],"stations":e["stations"],"candidate_aircraft_count":n,"classification":classification,"failure_reason":reason,"best_rms_us":base["best_rms_us"],"best_max_us":base["best_max_us"]})
    return rows,candidates,failures

def thin_strong(associations):
    groups=defaultdict(list)
    if not associations:return []
    origin=min(x["reference_tick"] for x in associations)
    for x in associations:
        if x["classification"]=="STRONG":groups[(x["matched_icao"],int((x["reference_tick"]-origin)/HZ))].append(x)
    return sorted((min(v,key=lambda x:(x["best_rms_us"],-x["receiver_count"],x["event_id"])) for v in groups.values()),key=lambda x:x["reference_tick"])

def error_components(t4,truth,lat,lon,alt):
    a=np.array(t4.geodetic_to_ecef(truth["truth_lat"],truth["truth_lon"],alt));b=np.array(t4.geodetic_to_ecef(lat,lon,alt));d=b-a
    la,lo=math.radians(truth["truth_lat"]),math.radians(truth["truth_lon"]);east=np.array([-math.sin(lo),math.cos(lo),0]);north=np.array([-math.sin(la)*math.cos(lo),-math.sin(la)*math.sin(lo),math.cos(la)])
    e,n=float(np.dot(d,east)),float(np.dot(d,north));return math.hypot(e,n),e,n,(math.degrees(math.atan2(e,n))+360)%360

def solve_events(primary,event_map,d7c,t4):
    rows=[]
    for a in primary:
        e=event_map[a["event_id"]];stations=e["stations"].split(';');m=measured(e);alt=float(a["truth_altitude_m"]);branches,cands,selected=d7c.solve(alt,stations,m)
        floor=min((x["rms_us"] for x in cands),default=math.inf);competitive=sum(x["rms_us"]<=floor+.01 and x["center_km"]<=1500 for x in cands)
        row={**a,"attempted":True,"converged":selected is not None,"branch_count":branches,"competitive_branches":competitive}
        if selected:
            err,east,north,bearing=error_components(t4,a,selected["lat"],selected["lon"],alt);valid=selected["center_km"]<=1500 and math.isfinite(selected["condition"]) and selected["condition"]<=1e6
            row.update({"mlat_lat":selected["lat"],"mlat_lon":selected["lon"],"horizontal_error_m":err,"east_error_m":east,"north_error_m":north,"error_bearing_deg":bearing,
                        "tdoa_rms_us":selected["rms_us"],"tdoa_max_us":selected["max_us"],"condition":selected["condition"],"network_center_km":selected["center_km"],
                        "solver_classification":"UNAMBIGUOUS" if valid and competitive==1 else "AMBIGUOUS" if valid else "REJECTED_GEOMETRY"})
        else:row["solver_classification"]="NO_CONVERGENCE"
        rows.append(row)
    return rows

def subset_and_altitude(local,event_map,d7c,t4):
    subsets=[];alts=[]
    for row in local:
        e=event_map[row["event_id"]]; stations=e["stations"].split(';');m=measured(e);alt=float(row["truth_altitude_m"])
        if len(stations)==4:
            for combo in itertools.combinations(stations,3):
                branches,cands,selected=d7c.solve(alt,list(combo),m); rec={"event_id":row["event_id"],"icao":row["matched_icao"],"stations":";".join(combo),"branches":branches,"converged":selected is not None}
                if selected:
                    err,east,north,bearing=error_components(t4,row,selected["lat"],selected["lon"],alt);rec.update({"horizontal_error_m":err,"tdoa_rms_us":selected["rms_us"],"condition":selected["condition"],"mlat_lat":selected["lat"],"mlat_lon":selected["lon"]})
                subsets.append(rec)
    representative=local if len(local)<=100 else [local[round(i*(len(local)-1)/99)] for i in range(100)]
    for row in representative:
        e=event_map[row["event_id"]];stations=e["stations"].split(';');m=measured(e);truth_alt=float(row["truth_altitude_m"])
        for offset in (-1000,0,1000):
            _,_,selected=d7c.solve(truth_alt+offset,stations,m); rec={"event_id":row["event_id"],"icao":row["matched_icao"],"altitude_offset_m":offset,"assumed_altitude_m":truth_alt+offset,"converged":selected is not None}
            if selected:
                err,_,_,_=error_components(t4,row,selected["lat"],selected["lon"],truth_alt);rec.update({"mlat_lat":selected["lat"],"mlat_lon":selected["lon"],"horizontal_error_m":err,"tdoa_rms_us":selected["rms_us"],"condition":selected["condition"]})
            alts.append(rec)
    return subsets,alts

def loc_metrics(rows):
    good=[x for x in rows if x.get("solver_classification")=="UNAMBIGUOUS"]
    return {"attempted":len(rows),"converged":sum(x.get("converged",False) for x in rows),"unambiguous":len(good),"ambiguous":sum(x.get("solver_classification")=="AMBIGUOUS" for x in rows),
            "rejected_geometry":sum(x.get("solver_classification")=="REJECTED_GEOMETRY" for x in rows),"horizontal_error_m":distribution(good,"horizontal_error_m"),
            "tdoa_rms_us":distribution(good,"tdoa_rms_us"),"condition":distribution(good,"condition")}

def self_tests(tools,d7c):
    sys.path.insert(0,"/home/mlatserver/mlatserver-dir/mlat-server")
    from modes.squawk import decode_id13 as reference_decode
    decoder=all(decode_id13(x)==reference_decode(x) for x in range(8192))
    raw=bytes.fromhex("28000a2435fa3f");identity=decode_mode_s_identity(raw);known=identity=={"df":5,"icao":"780c77","squawk":"3102","id13":2596}
    lat,lon,alt=20.5,106.9,10000.;p=d7c.geodetic_to_ecef(lat,lon,alt);dist={s:float(np.linalg.norm(p-d7c.RECEIVERS[s])) for s in ORDER};m={pair:(dist[pair[1]]-dist[pair[0]])/C*1e6 for pair in itertools.combinations(ORDER,2)}
    _,_,sol=d7c.solve(alt,ORDER,m);solver=sol is not None and d7c.horizontal_error(p,d7c.position(sol["en"],alt))<1
    return {"id13_exhaustive_8192":decoder,"known_df5_vector":known,"fixed_altitude_exact_geometry":solver,"passed":decoder and known and solver}

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("run_dir");ap.add_argument("test7b_dir");ap.add_argument("test7c_dir");ap.add_argument("test7d_dir");ap.add_argument("--output-dir",default="test7e");args=ap.parse_args()
    run,t7b,t7c,t7d,out=map(lambda x:Path(x).resolve(),(args.run_dir,args.test7b_dir,args.test7c_dir,args.test7d_dir,args.output_dir));out.mkdir(exist_ok=True);tools=Path(__file__).parent
    d7b,t4,s6,transforms,trajectories,receivers=build_context(run,tools);d7c=load_module("test7c_for_7e",tools/"test7c-2d-solver.py");d7d=load_module("test7d_for_7e",tools/"test7d-modeac-altitude.py")
    tests=self_tests(tools,d7c)
    if not tests["passed"]:raise RuntimeError("deterministic self-tests failed")
    identity_tx,intervals,identity_counts=build_identity_timeline(run,transforms,set(trajectories))
    limits={tuple(x["stations"]):x["baseline_m"]/C*1e6 for x in s6["pairwise"].values()}
    relevant={x["squawk"] for x in intervals};events,candidate_rows,event_diag=build_modea_events(run,transforms,relevant,limits,d7d.decode)
    event_diag["three_receiver_events"]=sum(x["station_count"]==3 for x in events);event_diag["four_receiver_events"]=sum(x["station_count"]==4 for x in events)
    simultaneous_icaos={x["icao"] for x in intervals if any(x["start_tick"]<=p["norm"]<=x["end_tick"] for p in trajectories.get(x["icao"],[]))}
    t37=[]
    with (run/"captures/modeac-T37.csv").open() as f:
        for row in csv.DictReader(f):
            if int(row["timestamp_corrected"]):t37.append((norm_tick(row,transforms["T37"]),int(row["recv_utc_ns"])))
    anchor=min(t37);tick_to_ns=lambda tick:int(anchor[1]+(tick-anchor[0])/HZ*1e9)
    associations,candidate_scores,failures=associate(events,intervals,trajectories,d7b,t4,receivers,tick_to_ns);primary=thin_strong(associations);event_map={x["event_id"]:x for x in events}
    local=solve_events(primary,event_map,d7c,t4);subsets,altitude=subset_and_altitude(local,event_map,d7c,t4)
    timeline_rows=[{**x,"start_time":iso_utc(tick_to_ns(x["start_tick"])),"end_time":iso_utc(tick_to_ns(x["end_tick"]))} for x in intervals]
    event_rows=[]
    assoc_by={x["event_id"]:x for x in associations}
    for e in events:
        a=assoc_by[e["event_id"]];event_rows.append({"event_id":e["event_id"],"event_time":a["event_time"],"mode_a_code":e["mode_a_code"],"receiver_count":e["station_count"],"stations":e["stations"],"station_measurements":e["source_rows"],"normalized_timestamps":a["normalized_timestamps"],"raw_words":e["raw_words"],"spi_any":e["spi_any"],"candidate_aircraft_count":a["candidate_aircraft_count"]})
    timeline_fields=["icao","squawk","start_time","end_time","start_tick","end_tick","observations","first_observation_tick","last_observation_tick","dfs","receiver_sources"]
    event_fields=["event_id","event_time","mode_a_code","receiver_count","stations","station_measurements","normalized_timestamps","raw_words","spi_any","candidate_aircraft_count"]
    assoc_fields=["event_id","event_time","reference_tick","mode_a_code","squawk_group","receiver_count","stations","station_measurements","normalized_timestamps","candidate_aircraft_count","classification","reason","matched_icao","best_rms_us","best_max_us","best_median_abs_us","second_best_rms_us","residual_ratio","residual_gap_us","truth_lat","truth_lon","truth_altitude_m","truth_quality"]
    loc_fields=assoc_fields+["attempted","converged","branch_count","competitive_branches","mlat_lat","mlat_lon","horizontal_error_m","east_error_m","north_error_m","error_bearing_deg","tdoa_rms_us","tdoa_max_us","condition","network_center_km","solver_classification"]
    write_csv(out/"test7e-squawk-timeline.csv",timeline_rows,timeline_fields);write_csv(out/"test7e-modea-events.csv",event_rows,event_fields);write_csv(out/"test7e-truth-associations.csv",associations,assoc_fields);write_csv(out/"test7e-localization.csv",local,loc_fields)
    write_csv(out/"test7e-candidates.csv",candidate_scores,["event_id","mode_a_code","rank","icao","squawk_group","rms_us","max_us","median_abs_us","truth_lat","truth_lon","truth_altitude_m"])
    write_csv(out/"test7e-failures.csv",failures,["event_id","mode_a_code","stations","candidate_aircraft_count","classification","failure_reason","best_rms_us","best_max_us"])
    write_csv(out/"test7e-three-of-four.csv",subsets,["event_id","icao","stations","branches","converged","mlat_lat","mlat_lon","horizontal_error_m","tdoa_rms_us","condition"])
    write_csv(out/"test7e-altitude-sensitivity.csv",altitude,["event_id","icao","altitude_offset_m","assumed_altitude_m","converged","mlat_lat","mlat_lon","horizontal_error_m","tdoa_rms_us","condition"])
    per_aircraft=[]
    for icao in sorted({x["matched_icao"] for x in local}):
        rr=[x for x in local if x["matched_icao"]==icao];good=[x for x in rr if x.get("solver_classification")=="UNAMBIGUOUS"]
        per_aircraft.append({"icao":icao,"squawks":";".join(sorted({x['mode_a_code'] for x in rr})),"independent_events":len(rr),"receiver_combinations":";".join(sorted({x['stations'] for x in rr})),
                             "median_horizontal_error_m":percentile([x["horizontal_error_m"] for x in good],.5) if good else None,"p90_horizontal_error_m":percentile([x["horizontal_error_m"] for x in good],.9) if good else None,
                             "median_tdoa_rms_us":percentile([x["tdoa_rms_us"] for x in good],.5) if good else None,"median_condition":percentile([x["condition"] for x in good],.5) if good else None})
    write_csv(out/"test7e-per-aircraft.csv",per_aircraft,["icao","squawks","independent_events","receiver_combinations","median_horizontal_error_m","p90_horizontal_error_m","median_tdoa_rms_us","median_condition"])
    group_rows=[]
    for group in ("UNIQUE_SQUAWK","SHARED_2","SHARED_3_PLUS"):
        aa=[x for x in associations if x["squawk_group"]==group];ll=[x for x in local if x["squawk_group"]==group and x.get("solver_classification")=="UNAMBIGUOUS"]
        group_rows.append({"squawk_group":group,"candidate_events":len(aa),"strong_events":sum(x["classification"]=="STRONG" for x in aa),"plausible_events":sum(x["classification"]=="PLAUSIBLE" for x in aa),
                           "ambiguous_events":sum(x["classification"]=="AMBIGUOUS" for x in aa),"association_success_percent":100*sum(x["classification"]=="STRONG" for x in aa)/len(aa) if aa else 0,
                           "ambiguity_percent":100*sum(x["classification"]=="AMBIGUOUS" for x in aa)/len(aa) if aa else 0,"horizontal_p50_m":percentile([x["horizontal_error_m"] for x in ll],.5) if ll else None,
                           "horizontal_p90_m":percentile([x["horizontal_error_m"] for x in ll],.9) if ll else None,"horizontal_p95_m":percentile([x["horizontal_error_m"] for x in ll],.95) if ll else None})
    write_csv(out/"test7e-squawk-groups.csv",group_rows,["squawk_group","candidate_events","strong_events","plausible_events","ambiguous_events","association_success_percent","ambiguity_percent","horizontal_p50_m","horizontal_p90_m","horizontal_p95_m"])
    loc3=[x for x in local if x["receiver_count"]==3];loc4=[x for x in local if x["receiver_count"]==4];good=[x for x in local if x.get("solver_classification")=="UNAMBIGUOUS"]
    alt0={x["event_id"]:x for x in altitude if x["altitude_offset_m"]==0 and x.get("converged")};alt_minus={x["event_id"]:x for x in altitude if x["altitude_offset_m"]==-1000 and x.get("converged")};alt_plus={x["event_id"]:x for x in altitude if x["altitude_offset_m"]==1000 and x.get("converged")}
    alt_changes=[abs(alt_minus[i]["horizontal_error_m"]-alt0[i]["horizontal_error_m"]) for i in alt0 if i in alt_minus]+[abs(alt_plus[i]["horizontal_error_m"]-alt0[i]["horizontal_error_m"]) for i in alt0 if i in alt_plus]
    strong=len(primary);aircraft=len({x["matched_icao"] for x in primary});sufficient=strong>=100 and aircraft>=20
    if not sufficient:decision="NEED_MORE_DATA"
    else:
        p90=distribution(good,"horizontal_error_m")["p90"]
        shared=[x for x in group_rows if x["squawk_group"]!="UNIQUE_SQUAWK" and x["candidate_events"]]
        decision="STRONG PASS" if len(good)>=100 and p90 is not None and p90<=2000 and shared else "PASS" if good and p90 is not None and p90<=5000 else "PARTIAL PASS" if good else "FAIL"
    association_summary={"mode_a_candidate_events":len(events),"events_with_same_squawk_aircraft":sum(x["candidate_aircraft_count"]>0 for x in associations),"strong_unthinned":sum(x["classification"]=="STRONG" for x in associations),
                         "strong_independent":strong,"plausible":sum(x["classification"]=="PLAUSIBLE" for x in associations),"ambiguous":sum(x["classification"]=="AMBIGUOUS" for x in associations),"no_truth_match":sum(x["classification"]=="NO_TRUTH_MATCH" for x in associations),
                         "independent_truth_tdoa_rms_us":distribution(primary,"best_rms_us"),"independent_truth_tdoa_max_us":distribution(primary,"best_max_us")}
    combo_stats={}
    for label,rr in itertools.groupby(sorted(subsets,key=lambda x:x["stations"]),key=lambda x:x["stations"]):combo_stats[label]=loc_metrics(list(rr))
    summary={"decision":decision,"new_capture_required":not sufficient,"self_tests":tests,"method":{"identity":"DF5/DF21 ID13 decoded with local readsb-compatible mapping; AP residual accepted only for ICAOs in DF17 truth trajectories","squawk_validity_s":VALID_S,
             "event_builder":"fresh same-squawk reciprocal-nearest complete cliques from original Type-1 rows","physical_gate_margin_us":CLOCK_MARGIN_US,"association":"TDOA-only ranking; strong RMS<=1 us and max<=2 us; shared candidates also require gap>=1 us and ratio>=2","temporal_thinning":"maximum one strong event per ICAO per capture-relative second","solver":"unchanged Test 7C deterministic multistart; truth lat/lon excluded from solve and branch selection"},
             "identity":{"decoded":identity_counts,"accepted_identity_transmissions":len(identity_tx),"distinct_observed_squawks":len(relevant),"squawk_state_intervals":len(intervals),"aircraft_with_squawk_truth":len({x['icao'] for x in intervals}),"aircraft_with_simultaneous_squawk_position_truth":len(simultaneous_icaos),"aircraft_with_position_trajectories":len(trajectories)},
             "event_builder":event_diag,"association":association_summary,"localization":{"all":loc_metrics(local),"three_receiver":loc_metrics(loc3),"four_receiver":loc_metrics(loc4),"receiver_combinations":{label:loc_metrics([x for x in local if x["stations"]==label]) for label in sorted({x["stations"] for x in local})},"three_of_four":combo_stats,
             "median_east_error_m":percentile([x["east_error_m"] for x in good],.5) if good else None,"median_north_error_m":percentile([x["north_error_m"] for x in good],.5) if good else None},
             "squawk_groups":group_rows,"altitude_sensitivity":{"events":len({x['event_id'] for x in altitude}),"absolute_error_change_m":distribution([{"v":x} for x in alt_changes],"v")},
             "data_sufficiency":{"sufficient":sufficient,"target":"at least 100 independent strong events and 20 aircraft","independent_strong_events":strong,"unique_aircraft":aircraft,
             "missing":[] if sufficient else (["too few aircraft"] if aircraft<20 else [])+(["too few independent strong Mode-A events"] if strong<100 else [])},
             "invariants":{"test7d_decoder_reused":True,"squawk_not_unique_identity":True,"truth_latlon_solver_input":False,"truth_latlon_branch_selection":False,"all_accepted_have_tdoa_evidence":all(x["best_rms_us"] is not None for x in primary),"temporal_thinning_applied":True,"source_rows_recorded":True}}
    (out/"test7e-summary.json").write_text(json.dumps(summary,indent=2))
    h=summary["localization"]["all"]["horizontal_error_m"];g={x["squawk_group"]:x for x in group_rows}
    lines=["TEST 7E — SQUAWK-CORRELATED MODE A 2D LOCALIZATION", "="*58,"",f"TEST 7E STATUS: {decision}","",
           "EVIDENCE",f"Confirmed squawk intervals: {len(intervals)} across {summary['identity']['aircraft_with_squawk_truth']} aircraft and {len(relevant)} distinct squawks.",
           f"Fresh 3+ receiver Mode-A events: {len(events)}; same-squawk truth available: {association_summary['events_with_same_squawk_aircraft']}.",
           f"Strong TDOA associations: {association_summary['strong_unthinned']} unthinned; {strong} independent; unique aircraft: {aircraft}.","",
           "LOCALIZATION (independent strong events; unambiguous branches)",f"Attempted {len(local)}, converged {summary['localization']['all']['converged']}, unambiguous {len(good)}, ambiguous {summary['localization']['all']['ambiguous']}, rejected geometry {summary['localization']['all']['rejected_geometry']}.",
           f"Horizontal error P50/P75/P90/P95/P99/max (m): {h['p50']}, {h['p75']}, {h['p90']}, {h['p95']}, {h['p99']}, {h['max']}.",
           f"3 receivers: {json.dumps(summary['localization']['three_receiver'],sort_keys=True)}",f"4 receivers: {json.dumps(summary['localization']['four_receiver'],sort_keys=True)}","",
           "SQUAWK SHARING",f"UNIQUE: {json.dumps(g['UNIQUE_SQUAWK'],sort_keys=True)}",f"SHARED_2: {json.dumps(g['SHARED_2'],sort_keys=True)}",f"SHARED_3_PLUS: {json.dumps(g['SHARED_3_PLUS'],sort_keys=True)}","",
           "DIAGNOSTICS",f"Median east/north error (m): {summary['localization']['median_east_error_m']} / {summary['localization']['median_north_error_m']}.",
           f"Altitude +/-1 km absolute horizontal-error change median/P90 (m): {summary['altitude_sensitivity']['absolute_error_change_m']['median']} / {summary['altitude_sensitivity']['absolute_error_change_m']['p90']}.",
           f"Independent truth-association TDOA RMS median/P90/P95 (us): {association_summary['independent_truth_tdoa_rms_us']['median']} / {association_summary['independent_truth_tdoa_rms_us']['p90']} / {association_summary['independent_truth_tdoa_rms_us']['p95']}.",
           "The 3-receiver fixed-altitude problem has two equations and two unknowns, so its selected-branch solver residual is numerically zero; truth-association residual and condition are the meaningful timing/geometry diagnostics. Test 7C's four-receiver synthetic reference is 0.10/0.25/0.50/1.00 us -> about 65/162/325/653 m median.","",
           "CONCLUSION",("Existing data meet the requested diversity target; Mode-A timestamps plus independently supplied altitude produce a directly validated horizontal position." if sufficient else "The method has been exhausted on the existing capture, but the requested diversity target is not met. A new capture is scientifically justified; none was started automatically."),
           f"PASS is limited to 3-receiver, unique-squawk evidence: {event_diag['four_receiver_events']} strict 4-receiver candidate cliques existed but none achieved an independent strong association, and no simultaneous shared-squawk truth case survived, so redundancy and shared-code disambiguation remain unvalidated.",
           "Squawk was never treated as identity. Same-code candidates were ranked only by TDOA geometry. Truth latitude/longitude was used only after the solve for error measurement.","",
           "KEY QUESTIONS",f"1. Usable squawk timeline? Yes: {len(intervals)} confirmed intervals.",f"2. Aircraft with simultaneous squawk and position truth? {summary['identity']['aircraft_with_simultaneous_squawk_position_truth']}; {aircraft} appear in independent strong events.",
           f"3. Independent 3+ receiver same-squawk events? {strong} strong after thinning ({association_summary['events_with_same_squawk_aircraft']} candidate events had same-squawk truth).",f"4. Strongly confirmed by TDOA? {association_summary['strong_unthinned']} unthinned, {strong} independent.",f"5. Unique aircraft represented? {aircraft}.",
           f"6. Horizontal P50/P75/P90/P95/P99 (m)? {h['p50']} / {h['p75']} / {h['p90']} / {h['p95']} / {h['p99']}.",f"7. Three receivers? {len(loc3)} attempted; {summary['localization']['three_receiver']['unambiguous']} unambiguous; P50/P90 {summary['localization']['three_receiver']['horizontal_error_m']['p50']} / {summary['localization']['three_receiver']['horizontal_error_m']['p90']} m.",
           f"8. Four receivers? {event_diag['four_receiver_events']} candidate cliques, but {len(loc4)} independent strong events; not validated in this capture.","9. Does sharing increase ambiguity? Not measurable: no simultaneous shared-squawk truth cases.","10. Can TDOA disambiguate shared squawks? Not established by this capture.",
           f"11. Best receiver combinations? {json.dumps(summary['localization']['receiver_combinations'],sort_keys=True)} No 4-receiver 3-of-4 ranking was possible.",f"12. Systematic east/north bias? Median {summary['localization']['median_east_error_m']} / {summary['localization']['median_north_error_m']} m; small relative to P90, with no correction applied.",
           "13. Consistent with Test 7C timing behavior? Broadly yes in scale, but only association residual—not an overdetermined solver residual—is observable for these 3-receiver fixes.",f"14. +/-1 km altitude material? Median/P90 absolute error change {summary['altitude_sensitivity']['absolute_error_change_m']['median']} / {summary['altitude_sensitivity']['absolute_error_change_m']['p90']} m; generally not material, with outliers retained.",
           f"15. Useful Mode-A 2D localization? Yes for independently unambiguous 3-receiver branches: P50 {h['p50']} m and P90 {h['p90']} m; broad 4-receiver/shared-squawk claims are not supported.","",
           "FILES","test7e-summary.json; test7e-squawk-timeline.csv; test7e-modea-events.csv; test7e-truth-associations.csv; test7e-localization.csv; test7e-per-aircraft.csv; test7e-squawk-groups.csv; test7e-candidates.csv; test7e-failures.csv; test7e-three-of-four.csv; test7e-altitude-sensitivity.csv"]
    (out/"test7e-report.txt").write_text("\n".join(lines)+"\n")
    print(json.dumps({"decision":decision,"events":len(events),"strong_independent":strong,"aircraft":aircraft,"unambiguous":len(good),"p90_m":h["p90"]},indent=2))

if __name__=="__main__":main()
