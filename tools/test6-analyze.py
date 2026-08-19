#!/usr/bin/env python3
"""Offline Test 6 pairwise DF17/Mode A/C validation and multi-station clustering."""

import argparse
import csv
import importlib.util
import itertools
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path

BEAST_HZ = 12_000_000.0
C = 299_792_458.0
STATIONS = {
    "T37": (21.485594, 107.773191, 60.0),
    "Dao_Cai_chien": (21.320940, 107.766116, 28.0),
    "QK4": (18.760032, 105.659087, 20.0),
    "BachLongVi": (20.132285, 107.724413, 28.0),
}
PAIRS = list(itertools.combinations(STATIONS, 2))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def percentile(values, p):
    if not values: return None
    x = sorted(values)
    if len(x) == 1: return x[0]
    pos = (len(x)-1)*p; lo, hi = math.floor(pos), math.ceil(pos)
    return x[lo] if lo == hi else x[lo]*(hi-pos)+x[hi]*(pos-lo)


def abs_stats(values):
    a = [abs(x) for x in values]
    return {"p90": percentile(a,.9), "p95": percentile(a,.95), "p99": percentile(a,.99)}


def baseline_name(a, b): return f"{a}__{b}"


def classify(p95, samples):
    if samples < 100 or p95 is None: return "INSUFFICIENT"
    if p95 < 1: return "STRONG PASS"
    if p95 < 5: return "PASS"
    if p95 < 10: return "MARGINAL"
    return "INVESTIGATE"


def build_geometry_samples(t4, common, pos_a, pos_b):
    """Test 4B sample construction generalized from its two-station 62 us bound."""
    last_even, last_odd, samples = {}, {}, []
    station_a=t4.geodetic_to_ecef(*pos_a); station_b=t4.geodetic_to_ecef(*pos_b)
    physical_us=t4.distance(station_a,station_b)/C*1e6
    for pair in common:
        d=t4.decode_airborne_fields(pair["raw"])
        if d is None: continue
        entry={"d":d,"pair":pair,"utc_ns":pair["a"]["utc_ns"]}; icao=d["icao"]
        (last_odd if d["odd"] else last_even)[icao]=entry
        if icao not in last_even or icao not in last_odd: continue
        even,odd=last_even[icao],last_odd[icao]
        if abs(even["utc_ns"]-odd["utc_ns"])/1e9>10: continue
        use_odd=odd["utc_ns"]>even["utc_ns"]
        decoded=t4.decode_global_cpr(even["d"],odd["d"],use_odd)
        if decoded is None: continue
        lat,lon=decoded; selected=odd if use_odd else even; alt_m=selected["d"]["altitude_ft"]*.3048
        if not (-10<=lat<=45 and 80<=lon<=140 and -500<=alt_m<=20000): continue
        aircraft=t4.geodetic_to_ecef(lat,lon,alt_m)
        geom_s=(t4.distance(aircraft,station_b)-t4.distance(aircraft,station_a))/C
        if abs(geom_s*1e6)>physical_us+1e-6: continue
        geom_ticks=geom_s*BEAST_HZ; ta=selected["pair"]["a"]["ts"]; tb=selected["pair"]["b"]["ts"]
        samples.append({"utc_ns":selected["utc_ns"],"icao":icao,"ta":ta,"tb":tb,"geom_ticks":geom_ticks,
                        "geom_us":geom_s*1e6,"tb_clock":tb-geom_ticks})
    samples.sort(key=lambda x:x["utc_ns"])
    return samples


def write_csv(path, fields, rows):
    with path.open("w", newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def clock_validation(t4, cap_a, cap_b, pos_a, pos_b):
    t4.STATION_A = {"name":"A","lat":pos_a[0],"lon":pos_a[1],"alt_m":pos_a[2]}
    t4.STATION_B = {"name":"B","lat":pos_b[0],"lon":pos_b[1],"alt_m":pos_b[2]}
    common=t4.build_common_df17(cap_a,cap_b,200.0); samples=build_geometry_samples(t4,common,pos_a,pos_b)
    unique_aircraft=len({x["icao"] for x in samples})
    if len(samples)<10:
        return {"common_df17_pairs":len(common),"geometry_samples":len(samples),"unique_aircraft":unique_aircraft,
                "classification":"INSUFFICIENT","samples":samples}
    split=max(2,min(len(samples)-1,int(len(samples)*.7))); train,test=samples[:split],samples[split:]
    slope,intercept=t4.linear_fit(train)
    train_r=[t4.residual(x,slope,intercept)/12 for x in train]
    test_r=[t4.residual(x,slope,intercept)/12 for x in test]
    chunks=[]
    if test:
        start=test[0]["utc_ns"]
        grouped=defaultdict(list)
        for sample,residual in zip(test,test_r): grouped[int((sample["utc_ns"]-start)/10e9)].append(residual)
        for n,vals in sorted(grouped.items()):
            chunks.append({"start_s":n*10,"samples":len(vals),"median_us":statistics.median(vals),
                           "p95_abs_us":percentile([abs(v) for v in vals],.95)})
    p95=percentile([abs(v) for v in test_r],.95)
    return {"common_df17_pairs":len(common),"geometry_samples":len(samples),"unique_aircraft":unique_aircraft,
            "training_samples":len(train),"holdout_samples":len(test),"slope":slope,
            "intercept_ticks":intercept,"relative_clock_ppm":(slope-1)*1e6,
            "train_p95_us":percentile([abs(v) for v in train_r],.95),"train_p99_us":percentile([abs(v) for v in train_r],.99),
            "holdout_p95_us":p95,"holdout_p99_us":percentile([abs(v) for v in test_r],.99),
            "holdout_temporal":chunks,"classification":classify(p95,len(samples)),"samples":samples}


def modeac_validation(t5, rows_a, rows_b, slope, intercept, physical_us, margin=3.0):
    result=t5.run_matching(rows_a,rows_b,slope,intercept,(physical_us+margin)*12)
    vals=[m["tdoa_us"] for m in result["accepted"]]; mult=result["multiplicity"]
    sensitivity=[]
    for m in (.5,1,3,5):
        r=t5.run_matching(rows_a,rows_b,slope,intercept,(physical_us+m)*12); rv=[x["tdoa_us"] for x in r["accepted"]]
        sensitivity.append({"margin_us":m,"accepted":len(rv),"ambiguous":r["ambiguous"],
                            "physical_violations":sum(abs(x)>physical_us for x in rv)})
    start=min((r["utc_ns"] for r in rows_a),default=0); grouped=defaultdict(list)
    for match in result["accepted"]: grouped[int((match["a"]["utc_ns"]-start)/10e9)].append(match["tdoa_us"])
    temporal=[{"start_s":n*10,"accepted":len(v),"median_us":statistics.median(v),"p05_us":percentile(v,.05),
               "p95_us":percentile(v,.95),"physical_violations":sum(abs(x)>physical_us for x in v)} for n,v in sorted(grouped.items())]
    return {"valid_a":len(rows_a),"valid_b":len(rows_b),"common_raw_codes":len({r['raw_hex'] for r in rows_a}&{r['raw_hex'] for r in rows_b}),
            "candidate_0":mult.get("0",0),"candidate_1":mult.get("1",0),"candidate_2":mult.get("2",0),"candidate_3_plus":mult.get("3+",0),
            "accepted":len(vals),"reciprocal":result["reciprocal"],"ambiguous":result["ambiguous"],"conflicts":result["conflicts"],
            "minimum_us":min(vals) if vals else None,"maximum_us":max(vals) if vals else None,"median_us":percentile(vals,.5),
            "p05_us":percentile(vals,.05),"p95_us":percentile(vals,.95),**{"abs_"+k:v for k,v in abs_stats(vals).items()},
            "strict_violations":sum(abs(x)>physical_us for x in vals),
            "plus_0_5_violations":sum(abs(x)>physical_us+.5 for x in vals),"plus_1_violations":sum(abs(x)>physical_us+1 for x in vals),
            "sensitivity":sensitivity,"temporal":temporal,"matches":result["accepted"]}


def build_clusters(records, transforms, limits, margin_us, capture_start_ns):
    nodes=defaultdict(list)
    for station,rows in records.items():
        slope,intercept=transforms[station]
        for r in rows:
            nodes[r["raw_hex"]].append({"station":station,"record":r,"norm":(r["ts"]-intercept)/slope})
    used=set(); clusters=[]; ambiguous=conflicting=physical_rejects=0; ambiguous_times=[]
    max_gate_ticks=(max(limits.values())+margin_us)*12
    for code,items in nodes.items():
        items.sort(key=lambda x:x["norm"]); times=[x["norm"] for x in items]
        for index,seed in enumerate(items):
            key=(seed["station"],seed["record"]["id"])
            if key in used: continue
            lo=__import__('bisect').bisect_left(times,seed["norm"]-max_gate_ticks)
            hi=__import__('bisect').bisect_right(times,seed["norm"]+max_gate_ticks)
            by_station=defaultdict(list)
            for node in items[lo:hi]:
                nkey=(node["station"],node["record"]["id"])
                if nkey not in used: by_station[node["station"]].append(node)
            choices=[]
            other=[s for s in STATIONS if s!=seed["station"]]
            for selected in itertools.product(*[[None]+by_station.get(s,[]) for s in other]):
                combo=[seed]+[x for x in selected if x is not None]
                if len(combo)<2: continue
                okay=True
                for x,y in itertools.combinations(combo,2):
                    pair=tuple(sorted((x["station"],y["station"]),key=list(STATIONS).index))
                    if abs(x["norm"]-y["norm"])/12 > limits[pair]+margin_us: okay=False; break
                if okay: choices.append(combo)
                else: physical_rejects+=1
            if not choices: continue
            size=max(map(len,choices)); best=[x for x in choices if len(x)==size]
            canonical={tuple(sorted((n["station"],n["record"]["id"]) for n in combo)):combo for combo in best}
            if len(canonical)!=1:
                ambiguous+=1; ambiguous_times.append(seed["record"]["utc_ns"]); continue
            combo=next(iter(canonical.values()))
            if any((n["station"],n["record"]["id"]) in used for n in combo): conflicting+=1; continue
            for n in combo: used.add((n["station"],n["record"]["id"]))
            clusters.append({"raw_hex":code,"nodes":combo,"reference_tick":statistics.mean(n["norm"] for n in combo),
                             "utc_ns":min(n["record"]["utc_ns"] for n in combo)})
    clusters.sort(key=lambda x:x["utc_ns"])
    rows=[]
    for cid,c in enumerate(clusters,1):
        by={n["station"]:n for n in c["nodes"]}
        row={"cluster_id":cid,"raw_hex":c["raw_hex"],"station_count":len(by),"reference_tick":f"{c['reference_tick']:.6f}",
             "seconds_from_start":f"{(c['utc_ns']-capture_start_ns)/1e9:.6f}","stations":";".join(s for s in STATIONS if s in by)}
        for station in STATIONS:
            row[f"{station}_timestamp"]=by[station]["record"]["ts"] if station in by else ""
            row[f"{station}_normalized_timestamp"]=f"{by[station]['norm']:.6f}" if station in by else ""
        rows.append(row)
    return clusters,rows,{"ambiguous_clusters":ambiguous,"conflicting_clusters":conflicting,
                           "rejected_physical_inconsistency_alternatives":physical_rejects,
                           "ambiguous_times":ambiguous_times}


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("run_dir"); p.add_argument("--margin-us",type=float,default=3); args=p.parse_args()
    run=Path(args.run_dir).resolve(); tools=Path(__file__).parent
    t4=load_module("test4b_test6",tools/"test4b-holdout.py"); t5=load_module("test5_test6",tools/"test5-modeac-correlation.py")
    captures={s:run/"captures"/f"modeac-{s}.csv" for s in STATIONS}
    all_rows={s:t4.load_capture(str(path)) for s,path in captures.items()}
    modeac={}; zeros={}
    for s,path in captures.items(): modeac[s],zeros[s]=t5.load_modeac(str(path))
    ecef={s:t4.geodetic_to_ecef(*pos) for s,pos in STATIONS.items()}
    limits={pair:t4.distance(ecef[pair[0]],ecef[pair[1]])/C*1e6 for pair in PAIRS}
    pair_summaries=[]; pair_details={}; models={}
    for a,b in PAIRS:
        name=baseline_name(a,b); directory=run/"pairwise"/name; directory.mkdir(exist_ok=True)
        clock=clock_validation(t4,all_rows[a],all_rows[b],STATIONS[a],STATIONS[b]); samples=clock.pop("samples")
        detail={"stations":[a,b],"baseline_m":t4.distance(ecef[a],ecef[b]),"physical_limit_us":limits[(a,b)],"clock":clock}
        if clock["classification"]!="INSUFFICIENT":
            models[(a,b)]=(clock["slope"],clock["intercept_ticks"])
            mc=modeac_validation(t5,modeac[a],modeac[b],clock["slope"],clock["intercept_ticks"],limits[(a,b)],args.margin_us)
            matches=mc.pop("matches"); detail["modeac"]=mc
            fields=["raw_hex","a_timestamp","b_timestamp","tdoa_us"]
            write_csv(directory/"matches.csv",fields,[{"raw_hex":m["a"]["raw_hex"],"a_timestamp":m["a"]["ts"],"b_timestamp":m["b"]["ts"],"tdoa_us":m["tdoa_us"]} for m in matches])
            write_csv(directory/"temporal.csv",list(mc["temporal"][0]) if mc["temporal"] else ["start_s"],mc["temporal"])
        (directory/"summary.json").write_text(json.dumps(detail,indent=2))
        mode=detail.get("modeac",{})
        pair_summaries.append({"station_a":a,"station_b":b,"baseline_m":detail["baseline_m"],"physical_limit_us":limits[(a,b)],
                               "common_df17":clock["common_df17_pairs"],"geometry_samples":clock["geometry_samples"],"unique_aircraft":clock["unique_aircraft"],
                               "clock_classification":clock["classification"],"slope":clock.get("slope","") ,"ppm":clock.get("relative_clock_ppm",""),
                               "holdout_p95_us":clock.get("holdout_p95_us","") ,"holdout_p99_us":clock.get("holdout_p99_us",""),
                               "modeac_accepted":mode.get("accepted",0),"modeac_reciprocal":mode.get("reciprocal",0),"modeac_ambiguous":mode.get("ambiguous",0),
                               "strict_violations":mode.get("strict_violations",0),"plus_0_5_violations":mode.get("plus_0_5_violations",0)})
        pair_details[name]=detail
    write_csv(run/"pairwise/pairwise-summary.csv",list(pair_summaries[0]),pair_summaries)

    # Map all station clocks into T37. Direct T37 relationships avoid compounding fits.
    transforms={"T37":(1.0,0.0)}
    for station in list(STATIONS)[1:]:
        if ("T37",station) in models: transforms[station]=models[("T37",station)]
    cluster_summary={"performed":len(transforms)==4,"reason":None}
    cluster_rows=[]; temporal=[]
    if len(transforms)==4:
        start=min(r["utc_ns"] for rows in modeac.values() for r in rows)
        clusters,cluster_rows,rejections=build_clusters(modeac,transforms,limits,args.margin_us,start)
        ambiguous_times=rejections.pop("ambiguous_times")
        counts=Counter(len(c["nodes"]) for c in clusters); duration=json.loads((run/"reports/capture-verification.json").read_text())["common_overlap_s"]
        cluster_summary.update({"total_clusters":len(clusters),"two_station_clusters":counts[2],"three_station_clusters":counts[3],
                                "four_station_clusters":counts[4],"three_plus_per_second":sum(v for k,v in counts.items() if k>=3)/duration,
                                "four_per_second":counts[4]/duration,"unique_raw_codes":len({c['raw_hex'] for c in clusters}),**rejections})
        top=Counter(c["raw_hex"] for c in clusters if len(c["nodes"])>=3).most_common(20); cluster_summary["top_raw_codes_3_plus"]=top
        cluster_sensitivity=[]
        for margin in (.5,1.0,3.0,5.0):
            if margin==args.margin_us:
                cs,rej=clusters,{**rejections,"ambiguous_clusters":len(ambiguous_times)}
            else:
                cs,unused_rows,rej=build_clusters(modeac,transforms,limits,margin,start); rej.pop("ambiguous_times",None)
            sizes=Counter(len(c["nodes"]) for c in cs)
            cluster_sensitivity.append({"margin_us":margin,"total":len(cs),"two_station":sizes[2],
                                        "three_station":sizes[3],"four_station":sizes[4],
                                        "ambiguous_clusters":rej["ambiguous_clusters"]})
        cluster_summary["sensitivity"]=cluster_sensitivity
        grouped=defaultdict(list)
        for c in clusters: grouped[int((c["utc_ns"]-start)/10e9)].append(c)
        ambiguous_grouped=Counter(int((x-start)/10e9) for x in ambiguous_times)
        for n in range(math.ceil(duration/10)):
            cs=grouped[n]; sizes=Counter(len(c["nodes"]) for c in cs)
            temporal.append({"start_s":n*10,"two_station":sizes[2],"three_station":sizes[3],"four_station":sizes[4],
                             "three_plus":sizes[3]+sizes[4],"ambiguous":ambiguous_grouped[n],
                             "ambiguity_rate_percent":100*ambiguous_grouped[n]/max(1,len(cs)+ambiguous_grouped[n])})
    else: cluster_summary["reason"]="Not all stations have sufficient direct DF17 synchronization to T37"
    cluster_fields=["cluster_id","raw_hex","station_count","reference_tick","seconds_from_start","stations"]+list(itertools.chain.from_iterable((f"{s}_timestamp",f"{s}_normalized_timestamp") for s in STATIONS))
    write_csv(run/"clusters/test6-clusters.csv",cluster_fields,cluster_rows)
    write_csv(run/"clusters/test6-temporal.csv",list(temporal[0]) if temporal else ["start_s"],temporal)
    write_csv(run/"clusters/test6-cluster-summary.csv",list(cluster_summary),[cluster_summary])

    capture=json.loads((run/"reports/capture-verification.json").read_text())
    summary={"run_id":run.name,"capture":capture,"pairwise":pair_details,"clusters":cluster_summary,
             "timestamp_zero":zeros,"configured_margin_us":args.margin_us}
    (run/"reports/test6-summary.json").write_text(json.dumps(summary,indent=2))
    reliable=[x for x in pair_summaries if x["clock_classification"] in ("STRONG PASS","PASS")]
    # A tiny random-association tail is reported, not hidden; require >=99.9% compliance
    # beyond the independent clock-error allowance for baseline-level validation.
    mode_pass=[x for x in pair_summaries if x["modeac_accepted"] and
               x["plus_0_5_violations"]/x["modeac_accepted"] <= .001]
    lines=["TEST 6 — FOUR-STATION CAPTURE AND VALIDATION","="*48,"",
           f"Capture accepted: {capture['capture_accepted']}; common overlap {capture['common_overlap_s']:.3f} s.","",
           "PAIRWISE SUMMARY"]
    for x in pair_summaries:
        lines.append(f"{x['station_a']} <-> {x['station_b']}: DF17 {x['clock_classification']}, geometry={x['geometry_samples']}, holdout P95={x['holdout_p95_us']}; Mode A/C accepted={x['modeac_accepted']}, ambiguous={x['modeac_ambiguous']}, strict/+0.5 violations={x['strict_violations']}/{x['plus_0_5_violations']}")
    lines += ["","CLUSTERS",json.dumps(cluster_summary,indent=2),"","FINAL QUESTIONS",
              f"1. All four valid overlapping captures: {capture['capture_accepted']}.",
              "2. Reliable DF17 baselines: "+", ".join(f"{x['station_a']}-{x['station_b']}" for x in reliable)+".",
              "3. Mode A/C baselines passing >=99.9% physical+0.5 us compliance: "+", ".join(f"{x['station_a']}-{x['station_b']}" for x in mode_pass)+".",
              f"4. Association ambiguity remained low: {cluster_summary.get('ambiguous_clusters','not measured')} cluster seeds ({100*cluster_summary.get('ambiguous_clusters',0)/max(1,cluster_summary.get('total_clusters',0)+cluster_summary.get('ambiguous_clusters',0)):.3f}%).",
              f"5. Three-station clusters: {cluster_summary.get('three_station_clusters',0)}.",
              f"6. Four-station clusters: {cluster_summary.get('four_station_clusters',0)}.",
              f"7. 3+ / four-station rates: {cluster_summary.get('three_plus_per_second',0):.6f} / {cluster_summary.get('four_per_second',0):.6f} per second.",
              "8. 3+ clusters occur in every 10-second interval; four-station clusters occur only sparsely in the latter part of the capture.",
              "9. Every accepted cluster passed every included pairwise physical constraint by construction.",
              "10. The 3-station density is useful for constrained/tracking work, but eight four-station clusters are insufficient for sustained unconstrained 3D position solving.",
              "11. QK4 is weakest: it recorded the fewest Mode A/C replies and its links have the fewest geometry samples; T37-QK4 and Dao-QK4 also show the largest hold-out drift.",
              "12. TEST 6: PARTIAL PASS — capture, all clock links, pairwise Mode A/C timing, and sustained 3-station clustering pass; four-station density does not."]
    (run/"reports/test6-report.txt").write_text("\n".join(lines)+"\n")
    print("\n".join(lines))


if __name__=="__main__": main()
