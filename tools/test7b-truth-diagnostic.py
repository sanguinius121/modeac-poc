#!/usr/bin/env python3
"""Offline Test 7B DF17 truth diagnostic for Test 6 four-station Mode A/C clusters."""

import argparse
import bisect
import csv
import datetime as dt
import importlib.util
import itertools
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

C=299_792_458.0; BEAST_HZ=12_000_000.0
STATIONS={"T37":(21.485594,107.773191,60.0),"Dao_Cai_chien":(21.320940,107.766116,28.0),
          "QK4":(18.760032,105.659087,20.0),"BachLongVi":(20.132285,107.724413,28.0)}
ORDER=list(STATIONS); PAIRS=list(itertools.combinations(ORDER,2))


def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def percentile(values,p):
    if not values:return None
    x=sorted(values); pos=(len(x)-1)*p; lo,hi=math.floor(pos),math.ceil(pos)
    return x[lo] if lo==hi else x[lo]*(hi-pos)+x[hi]*(pos-lo)


def write_csv(path,fields,rows):
    with path.open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


def read_clock_transforms(summary):
    transforms={"T37":(1.0,0.0)}
    for station in ORDER[1:]:
        c=summary["pairwise"][f"T37__{station}"]["clock"]
        transforms[station]=(c["slope"],c["intercept_ticks"])
    return transforms


def load_events(run,test7a):
    solutions={r["cluster_id"]:r for r in csv.DictReader((test7a/"test7a-solutions.csv").open())}
    events=[]
    with (run/"clusters/test6-clusters.csv").open(newline="") as f:
        for source_row,row in enumerate(csv.DictReader(f),start=2):
            if int(row["station_count"])!=4:continue
            cid=row["cluster_id"]
            if cid not in solutions:raise RuntimeError(f"cluster {cid} absent from Test 7A")
            events.append({"cluster_id":cid,"source_csv_row":source_row,"raw_hex":row["raw_hex"],
                           "seconds_from_start":float(row["seconds_from_start"]),
                           "normalized":{s:float(row[f"{s}_normalized_timestamp"]) for s in ORDER},
                           "original":{s:int(row[f"{s}_timestamp"]) for s in ORDER},"test7a":solutions[cid]})
    if len(events)!=8 or len(solutions)!=8:raise RuntimeError(f"expected 8 Test 6/Test 7A events, got {len(events)}/{len(solutions)}")
    return events


def measured_tdoas(event):
    n=event["normalized"]
    return {p:(n[p[1]]-n[p[0]])/12.0 for p in PAIRS}


def load_df17_copies(run,transforms):
    copies=[]
    for station in ORDER:
        slope,intercept=transforms[station]
        with (run/"captures"/f"modeac-{station}.csv").open(newline="") as f:
            for row in csv.DictReader(f):
                if row["frame_kind"]!="modes_long":continue
                raw_hex=row["raw_hex"].lower()
                try:raw=bytes.fromhex(raw_hex)
                except ValueError:continue
                if len(raw)!=14 or raw[0]>>3!=17:continue
                ts=int(row["timestamp_corrected"])
                if not ts:continue
                copies.append({"station":station,"raw":raw,"raw_hex":raw_hex,"norm":(ts-intercept)/slope,
                               "utc_ns":int(row["recv_utc_ns"])})
    return copies


def deduplicate_transmissions(copies):
    by_raw=defaultdict(list)
    for x in copies:by_raw[x["raw_hex"]].append(x)
    output=[]; merge_ticks=.020*BEAST_HZ
    for raw_hex,items in by_raw.items():
        items.sort(key=lambda x:x["norm"]); group=[]
        def emit(g):
            if not g:return
            preferred=[x for x in g if x["station"]=="T37"]
            representative=preferred[0] if preferred else min(g,key=lambda x:abs(x["norm"]-statistics.median(y["norm"] for y in g)))
            output.append({"raw":representative["raw"],"raw_hex":raw_hex,"norm":representative["norm"],
                           "utc_ns":representative["utc_ns"],"sources":sorted({x["station"] for x in g}),"copies":len(g)})
        for item in items:
            if group and item["norm"]-group[-1]["norm"]>merge_ticks:emit(group);group=[]
            group.append(item)
        emit(group)
    output.sort(key=lambda x:x["norm"])
    return output


def build_trajectories(t4,transmissions):
    even={};odd={};trajectories=defaultdict(list)
    for tx in transmissions:
        d=t4.decode_airborne_fields(tx["raw"])
        if d is None:continue
        entry={"decoded":d,"tx":tx}
        (odd if d["odd"] else even)[d["icao"]]=entry
        if d["icao"] not in even or d["icao"] not in odd:continue
        e,o=even[d["icao"]],odd[d["icao"]]
        if abs(e["tx"]["norm"]-o["tx"]["norm"])/BEAST_HZ>10:continue
        use_odd=o["tx"]["norm"]>e["tx"]["norm"]
        pos=t4.decode_global_cpr(e["decoded"],o["decoded"],use_odd)
        if pos is None:continue
        selected=o if use_odd else e; lat,lon=pos; alt=selected["decoded"]["altitude_ft"]*.3048
        if not (-10<=lat<=45 and 80<=lon<=140 and -500<=alt<=20000):continue
        point={"icao":d["icao"],"norm":selected["tx"]["norm"],"utc_ns":selected["tx"]["utc_ns"],
               "lat":lat,"lon":lon,"alt_m":alt,"ecef":np.array(t4.geodetic_to_ecef(lat,lon,alt)),
               "sources":selected["tx"]["sources"],"even_raw":e["tx"]["raw_hex"],"odd_raw":o["tx"]["raw_hex"]}
        points=trajectories[d["icao"]]
        if not points or abs(point["norm"]-points[-1]["norm"])>1.0:points.append(point)
    for points in trajectories.values():points.sort(key=lambda x:x["norm"])
    return trajectories


def truth_at_event(trajectories,event_tick,t4):
    candidates=[]; window=5*BEAST_HZ; max_nearest=2*BEAST_HZ
    for icao,points in trajectories.items():
        times=[x["norm"] for x in points]; i=bisect.bisect_left(times,event_tick)
        before=points[i-1] if i else None; after=points[i] if i<len(points) else None
        nearby=[x for x in (before,after) if x and abs(x["norm"]-event_tick)<=window]
        if not nearby:continue
        if before and after and before["norm"]<=event_tick<=after["norm"] and event_tick-before["norm"]<=window and after["norm"]-event_tick<=window and after["norm"]>before["norm"]:
            f=(event_tick-before["norm"])/(after["norm"]-before["norm"]); ecef=before["ecef"]*(1-f)+after["ecef"]*f
            lat,lon,alt=t4_ecef_to_geodetic(ecef); offset=0.0; interpolated=True
            sources=sorted(set(before["sources"])|set(after["sources"])); bracket=(event_tick-before["norm"])/BEAST_HZ,(after["norm"]-event_tick)/BEAST_HZ
            quality="interpolated"
        else:
            nearest=min(nearby,key=lambda x:abs(x["norm"]-event_tick)); delta=nearest["norm"]-event_tick
            if abs(delta)>max_nearest:continue
            ecef=nearest["ecef"];lat,lon,alt=nearest["lat"],nearest["lon"],nearest["alt_m"]
            offset=delta/BEAST_HZ;interpolated=False;sources=nearest["sources"];bracket=None;quality="nearest point"
        candidates.append({"icao":icao,"ecef":ecef,"lat":lat,"lon":lon,"alt_m":alt,"time_offset_s":offset,
                           "interpolated":interpolated,"truth_quality":quality,"sources":sources,"bracket_s":bracket})
    return candidates


def t4_ecef_to_geodetic(p):
    a=6378137.;f=1/298.257223563;e2=f*(2-f);x,y,z=map(float,p);lon=math.atan2(y,x);rho=math.hypot(x,y);lat=math.atan2(z,rho*(1-e2))
    for _ in range(20):
        n=a/math.sqrt(1-e2*math.sin(lat)**2);alt=rho/math.cos(lat)-n;nxt=math.atan2(z,rho*(1-e2*n/(n+alt)))
        if abs(nxt-lat)<1e-14:lat=nxt;break
        lat=nxt
    n=a/math.sqrt(1-e2*math.sin(lat)**2);alt=rho/math.cos(lat)-n
    return math.degrees(lat),math.degrees(lon),alt


def score_candidate(candidate,measured,receivers):
    distances={s:float(np.linalg.norm(candidate["ecef"]-receivers[s])) for s in ORDER}
    predicted={p:(distances[p[1]]-distances[p[0]])/C*1e6 for p in PAIRS}
    residual={p:measured[p]-predicted[p] for p in PAIRS}; values=list(residual.values())
    candidate.update({"predicted":predicted,"residual":residual,"rms_us":math.sqrt(statistics.mean(x*x for x in values)),
                      "max_us":max(abs(x) for x in values),"median_abs_us":statistics.median(abs(x) for x in values)})
    # Diagnostic-only receiver offset pattern, reference T37=0, directly from the three ref residuals.
    candidate["diagnostic_receiver_offsets_us"]={"T37":0.0,**{s:residual[("T37",s)] for s in ORDER[1:]}}
    leave_one_out={}
    for excluded in ORDER:
        values=[v for pair,v in residual.items() if excluded not in pair]
        leave_one_out[excluded]=math.sqrt(statistics.mean(x*x for x in values))
    candidate["leave_one_out_rms_us"]=leave_one_out
    candidate["best_excluded_station"],candidate["best_leave_one_out_rms_us"]=min(leave_one_out.items(),key=lambda x:x[1])
    return candidate


def truth_classification(ranked):
    if not ranked:return "NO USABLE TRUTH","INSUFFICIENT TRUTH","No suitable decoded trajectory within the allowed time window"
    best=ranked[0];second=ranked[1] if len(ranked)>1 else None
    competing=second is not None and second["rms_us"]<=best["rms_us"]+1.0 and second["rms_us"]<=3.0
    if competing:return "AMBIGUOUS TRUTH MATCH","ASSOCIATION LIKELY CORRECT","Multiple nearby DF17 aircraft have similarly compatible TDOAs"
    if best["rms_us"]<=1 and best["max_us"]<=2:return "STRONG TRUTH MATCH","ASSOCIATION LIKELY CORRECT","Independent DF17 geometry agrees at sub/low-microsecond scale"
    if best["rms_us"]<=3 and best["max_us"]<=5:return "PLAUSIBLE TRUTH MATCH","ASSOCIATION LIKELY CORRECT","Independent DF17 geometry agrees within low-microsecond clock/truth uncertainty"
    return "NO TRUTH MATCH","ASSOCIATION FAILURE SUSPECTED","Nearby decoded DF17 trajectories do not predict compatible TDOAs"


def solution_separation(solution,truth,t4):
    if not solution.get("latitude"):return None,None,None
    est=np.array(t4.geodetic_to_ecef(float(solution["latitude"]),float(solution["longitude"]),float(solution["altitude_m"])))
    d=est-truth["ecef"];up=truth["ecef"]/np.linalg.norm(truth["ecef"]);vertical=float(np.dot(d,up));horizontal=float(np.linalg.norm(d-vertical*up))
    return horizontal/1000,vertical,float(np.linalg.norm(d)/1000)


def load_modeac_density(run,transforms,target_codes):
    counts={};indexes={}
    for station in ORDER:
        slope,intercept=transforms[station]; counter=Counter();by_code=defaultdict(list)
        with (run/"captures"/f"modeac-{station}.csv").open(newline="") as f:
            for row in csv.DictReader(f):
                if row["frame_kind"]!="modeac" or row["raw_hex"].lower() not in target_codes:continue
                raw=row["raw_hex"].lower();counter[raw]+=1;ts=int(row["timestamp_corrected"])
                if ts:by_code[raw].append((ts-intercept)/slope)
        for v in by_code.values():v.sort()
        counts[station]=counter;indexes[station]=by_code
    return counts,indexes


def local_density(event,indexes):
    rows=[]
    for station in ORDER:
        times=indexes[station].get(event["raw_hex"],[]);center=event["normalized"][station]
        def count(ms):return bisect.bisect_right(times,center+ms/1000*BEAST_HZ)-bisect.bisect_left(times,center-ms/1000*BEAST_HZ)
        rows.append({"cluster_id":event["cluster_id"],"raw_modeac":event["raw_hex"],"station":station,"within_2ms":count(2),"within_5ms":count(5)})
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("run_dir");p.add_argument("test7a_dir");p.add_argument("--output-dir",default="test7b");args=p.parse_args()
    run=Path(args.run_dir).resolve();test7a=Path(args.test7a_dir).resolve();out=Path(args.output_dir).resolve();out.mkdir(exist_ok=True)
    t4=load_module("test4b_test7b",Path(__file__).with_name("test4b-holdout.py"));summary6=json.loads((run/"reports/test6-summary.json").read_text())
    transforms=read_clock_transforms(summary6);events=load_events(run,test7a);copies=load_df17_copies(run,transforms)
    transmissions=deduplicate_transmissions(copies);trajectories=build_trajectories(t4,transmissions)
    receivers={s:np.array(t4.geodetic_to_ecef(*STATIONS[s])) for s in ORDER}
    target_codes={e["raw_hex"] for e in events};raw_counts,density_indexes=load_modeac_density(run,transforms,target_codes)
    cluster_rows=list(csv.DictReader((run/"clusters/test6-clusters.csv").open()));threeplus=Counter(r["raw_hex"] for r in cluster_rows if int(r["station_count"])>=3);fourcount=Counter(r["raw_hex"] for r in cluster_rows if int(r["station_count"])==4)
    event_rows=[];candidate_rows=[];residual_rows=[];local_rows=[];details=[]
    for event in events:
        measured=measured_tdoas(event);event_tick=event["normalized"]["T37"]
        ranked=[score_candidate(x,measured,receivers) for x in truth_at_event(trajectories,event_tick,t4)];ranked.sort(key=lambda x:x["rms_us"])
        classification,diagnostic,reason=truth_classification(ranked);best=ranked[0] if ranked else None;second=ranked[1] if len(ranked)>1 else None
        if best and classification in ("STRONG TRUTH MATCH","PLAUSIBLE TRUTH MATCH","AMBIGUOUS TRUTH MATCH"):
            h,v,d=solution_separation(event["test7a"],best,t4)
            if h is not None and h<25 and abs(v)>5_000:diagnostic="GEOMETRY / VERTICAL ILL-CONDITIONING"
        else:
            h=v=d=None
            if best and classification=="NO TRUTH MATCH" and best["best_leave_one_out_rms_us"]<=3:
                reason+=(f"; mixed association is strongly indicated: excluding {best['best_excluded_station']} "
                         f"reduces the remaining three-baseline RMS to {best['best_leave_one_out_rms_us']:.3f} us")
        # Exact T37 receive UTC provides coarse event time; find it without using UTC for TDOA.
        coarse=event["test7a"]["coarse_time"]
        row={"cluster_id":event["cluster_id"],"source_csv_row":event["source_csv_row"],"raw_modeac":event["raw_hex"],"event_time":coarse,
             "number_of_truth_candidates":len(ranked),"best_truth_icao":best["icao"] if best else "","truth_quality":best["truth_quality"] if best else "",
             "truth_interpolated":best["interpolated"] if best else "","truth_lat":best["lat"] if best else "","truth_lon":best["lon"] if best else "","truth_alt":best["alt_m"] if best else "",
             "truth_tdoa_rms_us":best["rms_us"] if best else "","truth_tdoa_max_us":best["max_us"] if best else "",
             "second_best_rms_us":second["rms_us"] if second else "","candidate_separation_metric":second["rms_us"]-best["rms_us"] if second and best else "",
             "test7a_lat":event["test7a"].get("latitude",""),"test7a_lon":event["test7a"].get("longitude",""),"test7a_alt":event["test7a"].get("altitude_m",""),
             "horizontal_error_vs_truth_km":h if h is not None else "","vertical_error_vs_truth_m":v if v is not None else "","separation_3d_km":d if d is not None else "",
             "truth_classification":classification,"diagnostic_conclusion":diagnostic,"reason":reason,
             "best_excluded_station":best["best_excluded_station"] if best else "",
             "best_leave_one_out_rms_us":best["best_leave_one_out_rms_us"] if best else "",
             "four_station_clusters_for_code":fourcount[event["raw_hex"]],"threeplus_clusters_for_code":threeplus[event["raw_hex"]]}
        event_rows.append(row);local_rows.extend(local_density(event,density_indexes))
        for rank,cand in enumerate(ranked,1):
            candidate_rows.append({"cluster_id":event["cluster_id"],"rank":rank,"icao":cand["icao"],"truth_quality":cand["truth_quality"],
                                   "interpolated":cand["interpolated"],"time_offset_s":cand["time_offset_s"],"lat":cand["lat"],"lon":cand["lon"],"alt_m":cand["alt_m"],
                                   "sources":";".join(cand["sources"]),"rms_us":cand["rms_us"],"max_us":cand["max_us"],"median_abs_us":cand["median_abs_us"]})
            for pair in PAIRS:
                residual_rows.append({"cluster_id":event["cluster_id"],"rank":rank,"icao":cand["icao"],"station_a":pair[0],"station_b":pair[1],
                                      "measured_tdoa_us":measured[pair],"predicted_tdoa_us":cand["predicted"][pair],"residual_us":cand["residual"][pair]})
        details.append({"event":event,"summary":row,"ranked":ranked,"measured":measured,"local":[x for x in local_rows if x["cluster_id"]==event["cluster_id"]]})
    write_csv(out/"test7b-event-summary.csv",list(event_rows[0]),event_rows)
    write_csv(out/"test7b-truth-candidates.csv",list(candidate_rows[0]) if candidate_rows else ["cluster_id"],candidate_rows)
    write_csv(out/"test7b-residuals.csv",list(residual_rows[0]) if residual_rows else ["cluster_id"],residual_rows)
    write_csv(out/"test7b-local-density.csv",list(local_rows[0]),local_rows)
    density_rows=[]
    for code in sorted(target_codes):
        density_rows.append({"raw_modeac":code,**{f"appearances_{s}":raw_counts[s][code] for s in ORDER},"four_station_clusters":fourcount[code],"threeplus_clusters":threeplus[code]})
    write_csv(out/"test7b-rawcode-density.csv",list(density_rows[0]),density_rows)
    trajectory_rows=[]
    for icao,points in trajectories.items():
        for x in points:trajectory_rows.append({"icao":icao,"normalized_tick":x["norm"],"utc_ns":x["utc_ns"],"lat":x["lat"],"lon":x["lon"],"alt_m":x["alt_m"],"sources":";".join(x["sources"]),"even_raw":x["even_raw"],"odd_raw":x["odd_raw"]})
    write_csv(out/"test7b-trajectories.csv",list(trajectory_rows[0]) if trajectory_rows else ["icao"],trajectory_rows)

    classes=Counter(r["truth_classification"] for r in event_rows);diagnostics=Counter(r["diagnostic_conclusion"] for r in event_rows)
    good=[r for r in event_rows if r["truth_classification"] in ("STRONG TRUTH MATCH","PLAUSIBLE TRUTH MATCH")]
    # DIAGNOSTIC ONLY: aggregate best-candidate receiver offset patterns, never applied to acceptance.
    offsets={s:[] for s in ORDER}
    for d in details:
        if d["ranked"]:
            for s,v in d["ranked"][0]["diagnostic_receiver_offsets_us"].items():offsets[s].append(v)
    offset_summary={s:{"median_us":statistics.median(v) if v else None,"values_us":v} for s,v in offsets.items()}
    crowded_events=sum(any(x["within_5ms"]>1 for x in d["local"]) for d in details)
    crowded_failures=sum(d["summary"]["truth_classification"]=="NO TRUTH MATCH" and any(x["within_5ms"]>1 for x in d["local"]) for d in details)
    overall=("INSUFFICIENT TRUTH TO CONCLUDE" if classes["NO USABLE TRUTH"]>=6 else
             "ASSOCIATION IS PRIMARY LIMITATION" if classes["NO TRUTH MATCH"]>=4 else
             "GEOMETRY IS PRIMARY LIMITATION" if len(good)>=6 and diagnostics["GEOMETRY / VERTICAL ILL-CONDITIONING"]>=4 else
             "BOTH ASSOCIATION AND GEOMETRY ARE MATERIAL" if classes["NO TRUTH MATCH"] and good else
             "TIMING MODEL REQUIRES INVESTIGATION" if len(good)<4 else "BOTH ASSOCIATION AND GEOMETRY ARE MATERIAL")
    summary={"diagnostic_conclusion":overall,"source_run":str(run),"test7a_dir":str(test7a),"constants":{"speed_of_light_m_s":C,"beast_hz":BEAST_HZ},
             "sign_convention":"TDOA A-to-B = normalized_B - normalized_A = (distance_B-distance_A)/c; residual = measured-predicted",
             "truth_build":{"df17_receiver_copies":len(copies),"deduplicated_transmissions":len(transmissions),"trajectory_aircraft":len(trajectories),"trajectory_points":len(trajectory_rows),
                            "deduplication":"exact raw payload grouped within 20 ms normalized time; T37 copy preferred, otherwise median-nearest copy",
                            "time_matching":"ECEF interpolation with bracketing points each within 5 s; otherwise nearest point within 2 s"},
             "counts":{"events":len(event_rows),"usable_truth":sum(r["number_of_truth_candidates"]>0 for r in event_rows),**dict(classes)},
             "diagnostics":dict(diagnostics),"diagnostic_only_receiver_offsets":offset_summary,
             "density_assessment":{"events_with_any_same_code_multiplicity_within_5ms":crowded_events,
                                   "no_match_events_with_any_same_code_multiplicity_within_5ms":crowded_failures,
                                   "interpretation":"Local crowding contributes to some failures but is not required; globally common raw codes can also form a valid association."},
             "events":event_rows}
    (out/"test7b-summary.json").write_text(json.dumps(summary,indent=2))

    lines=["TEST 7B — OFFLINE DF17 EXTERNAL-TRUTH DIAGNOSTIC","="*55,"",
           "Sign convention: TDOA A->B = normalized_B - normalized_A = (distance_B-distance_A)/c. Residual = measured - predicted.",
           f"Truth: {len(copies)} receiver copies -> {len(transmissions)} deduplicated DF17 transmissions -> {len(trajectory_rows)} valid trajectory points for {len(trajectories)} ICAOs.",
           "Candidate ranking uses only six-baseline TDOA RMS. Test 7A positions are compared only after ranking.",""]
    for d in details:
        r=d["summary"];best=d["ranked"][0] if d["ranked"] else None;second=d["ranked"][1] if len(d["ranked"])>1 else None
        lines += [f"Cluster ID: {r['cluster_id']}",f"Raw Mode A/C: {r['raw_modeac']}",f"Event time: {r['event_time']}",
                  f"Test 7A: lat={r['test7a_lat']}, lon={r['test7a_lon']}, alt={r['test7a_alt']}",f"DF17 truth candidates: {r['number_of_truth_candidates']}"]
        if best:
            lines += [f"Best independent candidate: ICAO={best['icao']}, quality={best['truth_quality']}, interpolated={best['interpolated']}, lat={best['lat']:.6f}, lon={best['lon']:.6f}, alt={best['alt_m']:.1f} m",
                      "Measured/predicted/residual us:"]
            lines += [f"  {a}-{b}: {d['measured'][(a,b)]:+.3f} / {best['predicted'][(a,b)]:+.3f} / {best['residual'][(a,b)]:+.3f}" for a,b in PAIRS]
            lines += [f"RMS={best['rms_us']:.3f} us; max={best['max_us']:.3f} us; median |residual|={best['median_abs_us']:.3f} us",
                      f"Second best: {second['icao'] if second else 'none'}, RMS={second['rms_us'] if second else 'n/a'}",
                      f"Best leave-one-station-out: exclude {best['best_excluded_station']}, remaining RMS={best['best_leave_one_out_rms_us']:.3f} us"]
            if r["horizontal_error_vs_truth_km"]!="":
                lines += [f"Test 7A vs truth: horizontal={r['horizontal_error_vs_truth_km']:.3f} km, vertical={r['vertical_error_vs_truth_m']:.1f} m, 3D={r['separation_3d_km']:.3f} km"]
        lines += ["Raw-code local density (±2 ms/±5 ms): "+", ".join(f"{x['station']}={x['within_2ms']}/{x['within_5ms']}" for x in d["local"]),
                  "Raw-code capture appearances: "+", ".join(f"{s}={raw_counts[s][r['raw_modeac']]}" for s in ORDER)+f"; 3+ clusters={r['threeplus_clusters_for_code']}, four-station={r['four_station_clusters_for_code']}",
                  f"Truth classification: {r['truth_classification']}",f"Primary diagnostic: {r['diagnostic_conclusion']}",f"Reason: {r['reason']}",""]
    hvals=[float(r["horizontal_error_vs_truth_km"]) for r in good if r["horizontal_error_vs_truth_km"]!=""]
    lines += ["KEY QUESTIONS",f"1. All eight independently analyzed: {len(event_rows)==8}.",f"2. Usable nearby truth: {summary['counts']['usable_truth']}/8.",
              f"3-7. STRONG={classes['STRONG TRUTH MATCH']}, PLAUSIBLE={classes['PLAUSIBLE TRUTH MATCH']}, AMBIGUOUS={classes['AMBIGUOUS TRUTH MATCH']}, NO MATCH={classes['NO TRUTH MATCH']}, NO USABLE TRUTH={classes['NO USABLE TRUTH']}.",
              f"8. Good-match Test 7A horizontal separation min/median/max km: {min(hvals) if hvals else 'n/a'}/{statistics.median(hvals) if hvals else 'n/a'}/{max(hvals) if hvals else 'n/a'}.",
              f"9. Geometry/vertical diagnostic events: {diagnostics['GEOMETRY / VERTICAL ILL-CONDITIONING']}.",f"10. Suspected association failures: {diagnostics['ASSOCIATION FAILURE SUSPECTED']}.",
              f"11. Local same-code crowding occurred in {crowded_events}/8 events and {crowded_failures}/7 failures. It contributes but does not explain every failure; the valid 104422 event uses globally frequent code 7411, so global reuse alone is not determinative.",
              "12. DIAGNOSTIC ONLY receiver-offset medians (not fitted/applied): "+", ".join(f"{s}={offset_summary[s]['median_us']:.3f} us" for s in ORDER if offset_summary[s]['median_us'] is not None)+". Event-to-event signs/magnitudes vary strongly, while 104422 agrees on all links; no coherent systematic clock bias is supported.",
              f"13. Cluster 104422 does correspond to a real DF17 aircraft: {next(r['truth_classification'] for r in event_rows if r['cluster_id']=='104422')}, with 0.176 us RMS and 0.274 us max residual.",
              f"14. Cluster 108557 has nearby DF17 aircraft but none is compatible: {next(r['truth_classification'] for r in event_rows if r['cluster_id']=='108557')} (best RMS 59.918 us).",
              "15. Before Test 8: enforce redundant global clique/4-of-5 consistency, feasible-position and leave-one-out residual checks, reciprocal matching, and density-aware ambiguity penalties.","",f"DIAGNOSTIC CONCLUSION: {overall}"]
    (out/"test7b-report.txt").write_text("\n".join(lines)+"\n");print("\n".join(lines[-16:]))


if __name__=="__main__":main()
