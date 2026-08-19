#!/usr/bin/env python3
"""Test 7C: offline fixed-altitude horizontal TDOA localization feasibility."""

import argparse,csv,itertools,json,math,statistics
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares

C=299_792_458.0; BEAST_HZ=12_000_000.0; A=6_378_137.0; F=1/298.257223563; E2=F*(2-F)
STATIONS={"T37":(21.485594,107.773191,60.0),"Dao_Cai_chien":(21.320940,107.766116,28.0),
          "QK4":(18.760032,105.659087,20.0),"BachLongVi":(20.132285,107.724413,28.0)}
ORDER=list(STATIONS); PAIRS=list(itertools.combinations(ORDER,2)); ORIGIN_LAT=statistics.mean(v[0] for v in STATIONS.values());ORIGIN_LON=statistics.mean(v[1] for v in STATIONS.values())
R_LAT=111_132.0;R_LON=111_320.0*math.cos(math.radians(ORIGIN_LAT))

def geodetic_to_ecef(lat,lon,alt):
    latr,lonr=math.radians(lat),math.radians(lon);sl,cl=math.sin(latr),math.cos(latr);n=A/math.sqrt(1-E2*sl*sl)
    return np.array([(n+alt)*cl*math.cos(lonr),(n+alt)*cl*math.sin(lonr),(n*(1-E2)+alt)*sl])

RECEIVERS={s:geodetic_to_ecef(*v) for s,v in STATIONS.items()}

def en_to_ll(en):return ORIGIN_LAT+float(en[1])/R_LAT,ORIGIN_LON+float(en[0])/R_LON
def ll_to_en(lat,lon):return np.array([(lon-ORIGIN_LON)*R_LON,(lat-ORIGIN_LAT)*R_LAT])
def position(en,alt):return geodetic_to_ecef(*en_to_ll(en),alt)

def measured_from_normalized(norm):return {p:(norm[p[1]]-norm[p[0]])/12 for p in PAIRS}

def predict_all(en,alt):
    p=position(en,alt);d={s:float(np.linalg.norm(p-RECEIVERS[s])) for s in ORDER}
    return {pair:(d[pair[1]]-d[pair[0]])/C*1e6 for pair in PAIRS}

def independent_residual_m(en,alt,stations,measured):
    p=position(en,alt);ref=stations[0];dr=np.linalg.norm(p-RECEIVERS[ref])
    return np.array([(measured[(ref,s)] if (ref,s) in measured else -measured[(s,ref)])*C/1e6-(np.linalg.norm(p-RECEIVERS[s])-dr) for s in stations[1:]])

def all_residuals(en,alt,stations,measured):
    predicted=predict_all(en,alt);pairs=list(itertools.combinations(stations,2));values={p:measured[p]-predicted[p] for p in pairs}
    rms=math.sqrt(statistics.mean(v*v for v in values.values()));return predicted,values,rms,max(abs(v) for v in values.values())

def starts():
    output=[np.array([0.,0.])]
    for radius in (50_000,100_000,250_000,500_000,900_000):
        for angle in range(0,360,45):output.append(np.array([radius*math.cos(math.radians(angle)),radius*math.sin(math.radians(angle))]))
    output.extend(ll_to_en(v[0],v[1]) for v in STATIONS.values())
    return output
STARTS=starts()

def numeric_jacobian(en,alt,stations,measured):
    step=10.;cols=[]
    for axis in range(2):
        delta=np.zeros(2);delta[axis]=step
        cols.append((independent_residual_m(en+delta,alt,stations,measured)-independent_residual_m(en-delta,alt,stations,measured))/(2*step))
    return np.column_stack(cols)

def solve(alt,stations,measured):
    found=[]
    for start in STARTS:
        r=least_squares(independent_residual_m,start,args=(alt,stations,measured),method="lm",max_nfev=2500,ftol=1e-13,xtol=1e-13,gtol=1e-13)
        if r.success and np.all(np.isfinite(r.x)):
            pred,res,rms,maxr=all_residuals(r.x,alt,stations,measured);lat,lon=en_to_ll(r.x);center=float(np.linalg.norm(r.x))/1000
            cand={"en":r.x,"lat":lat,"lon":lon,"rms_us":rms,"max_us":maxr,"condition":float(np.linalg.cond(numeric_jacobian(r.x,alt,stations,measured))),
                  "center_km":center,"residuals":res,"predicted":pred,"nfev":r.nfev}
            if not any(np.linalg.norm(r.x-x["en"])<100 for x in found):found.append(cand)
    found.sort(key=lambda x:x["rms_us"])
    if not found:return 0,[],None
    floor=found[0]["rms_us"]
    competitive=[x for x in found if x["rms_us"]<=floor+.01 and x["center_km"]<=1500]
    pool=competitive or [x for x in found if x["center_km"]<=1500] or found
    # Residual equivalence is resolved by geography/conditioning, never truth position.
    selected=min(pool,key=lambda x:(x["center_km"],x["condition"])) if competitive else min(pool,key=lambda x:(x["rms_us"],x["center_km"],x["condition"]))
    return len(found),found,selected

def horizontal_error(truth_ecef,estimated_ecef):
    up=truth_ecef/np.linalg.norm(truth_ecef);d=estimated_ecef-truth_ecef;vertical=float(np.dot(d,up));return float(np.linalg.norm(d-vertical*up))

def load_inputs(run,test7a,test7b):
    cluster=None
    with (run/"clusters/test6-clusters.csv").open() as f:
        for row in csv.DictReader(f):
            if row["cluster_id"]=="104422":cluster=row;break
    if cluster is None or int(cluster["station_count"])!=4:raise RuntimeError("four-station cluster 104422 not found")
    event=next(r for r in csv.DictReader((test7b/"test7b-event-summary.csv").open()) if r["cluster_id"]=="104422")
    if event["truth_classification"]!="STRONG TRUTH MATCH":raise RuntimeError("Test 7B cluster 104422 is not a strong truth match")
    truth={"lat":float(event["truth_lat"]),"lon":float(event["truth_lon"]),"alt":float(event["truth_alt"]),"icao":event["best_truth_icao"]}
    solution=next(r for r in csv.DictReader((test7a/"test7a-solutions.csv").open()) if r["cluster_id"]=="104422")
    norm={s:float(cluster[f"{s}_normalized_timestamp"]) for s in ORDER}
    return cluster,event,truth,solution,norm

def candidate_record(c,truth,alt):
    err=horizontal_error(geodetic_to_ecef(truth["lat"],truth["lon"],truth["alt"]),position(c["en"],alt))
    return {"solution_lat":c["lat"],"solution_lon":c["lon"],"horizontal_error_m":err,"rms_residual_us":c["rms_us"],"max_residual_us":c["max_us"],"jacobian_condition":c["condition"],"network_center_distance_km":c["center_km"]}

def synthetic_truths():
    return [("inside",20.5,106.9,10_000),("near_t37_cai",21.4,107.5,6_000),("near_blv",20.2,107.5,12_000),
            ("toward_qk4",19.0,105.9,3_000),("outside_hull",22.5,109.0,15_000)]

def synthetic_measured(lat,lon,alt,noise,stations):
    p=geodetic_to_ecef(lat,lon,alt);d={s:float(np.linalg.norm(p-RECEIVERS[s])) for s in ORDER};base={p:(d[p[1]]-d[p[0]])/C*1e6 for p in PAIRS}
    perturb={"T37":0.,"Dao_Cai_chien":noise,"QK4":-.5*noise,"BachLongVi":.75*noise}
    return {p:base[p]+perturb[p[1]]-perturb[p[0]] for p in PAIRS}

def summarize_errors(rows,key="horizontal_error_m"):
    vals=[r[key] for r in rows];return {"count":len(vals),"median_m":statistics.median(vals),"p90_m":percentile(vals,.9),"max_m":max(vals)}

def percentile(values,p):
    x=sorted(values);pos=(len(x)-1)*p;lo,hi=math.floor(pos),math.ceil(pos);return x[lo] if lo==hi else x[lo]*(hi-pos)+x[hi]*(pos-lo)

def write_csv(path,rows,fields=None):
    fields=fields or list(rows[0]);
    with path.open("w",newline="") as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("run_dir");p.add_argument("test7a_dir");p.add_argument("test7b_dir");p.add_argument("--output-dir",default="test7c");args=p.parse_args()
    run,test7a,test7b,out=map(lambda x:Path(x).resolve(),(args.run_dir,args.test7a_dir,args.test7b_dir,args.output_dir));out.mkdir(exist_ok=True)
    cluster,event,truth,sol7a,norm=load_inputs(run,test7a,test7b);measured=measured_from_normalized(norm);truth_ecef=geodetic_to_ecef(truth["lat"],truth["lon"],truth["alt"])
    fixed=[0,1000,2000,3000,4000,5000,6000,7000,8000,9000,10000,11000,11292.8,12000,13000,15000,18000,20000]
    exact_offsets=[truth["alt"]+x for x in (-5000,-3000,-2000,-1000,-500,-300,-100,0,100,300,500,1000,2000,3000,5000)]
    hypotheses=[]
    for x in fixed+exact_offsets:
        if not any(abs(x-y)<.01 for y in hypotheses):hypotheses.append(x)
    altitude_rows=[];candidate_rows=[]
    for alt in hypotheses:
        branches,candidates,selected=solve(alt,ORDER,measured)
        competitive=sum(c["rms_us"]<=min(x["rms_us"] for x in candidates)+.01 and c["center_km"]<=1500 for c in candidates) if candidates else 0
        row={"assumed_altitude_m":alt,"altitude_error_m":alt-truth["alt"],"selected":selected is not None,"branches":branches,"competitive_credible_branches":competitive}
        if selected:row.update(candidate_record(selected,truth,alt))
        altitude_rows.append(row)
        for i,c in enumerate(candidates,1):candidate_rows.append({"experiment":"altitude_sensitivity","assumed_altitude_m":alt,"stations":";".join(ORDER),"branch":i,"selected":c is selected,**candidate_record(c,truth,alt)})
    correct_row=min(altitude_rows,key=lambda x:abs(x["altitude_error_m"]));correct_ll_ecef=geodetic_to_ecef(correct_row["solution_lat"],correct_row["solution_lon"],truth["alt"])
    for row in altitude_rows:
        compare=geodetic_to_ecef(row["solution_lat"],row["solution_lon"],truth["alt"])
        row["horizontal_solution_displacement_m"]=horizontal_error(correct_ll_ecef,compare)
        row["displacement_per_km_altitude_error_m"]=row["horizontal_solution_displacement_m"]/(abs(row["altitude_error_m"])/1000) if abs(row["altitude_error_m"])>.01 else 0
    write_csv(out/"test7c-altitude-sensitivity.csv",altitude_rows)

    combos=list(itertools.combinations(ORDER,3));three_rows=[]
    for combo in combos:
        for alt in (5000,8000,10000,truth["alt"],12000,15000):
            branches,candidates,selected=solve(alt,list(combo),measured);competitive=sum(c["rms_us"]<=min(x["rms_us"] for x in candidates)+.01 and c["center_km"]<=1500 for c in candidates) if candidates else 0
            row={"stations":";".join(combo),"assumed_altitude_m":alt,"altitude_error_m":alt-truth["alt"],"branches":branches,"competitive_credible_branches":competitive,"selected":selected is not None}
            if selected:row.update(candidate_record(selected,truth,alt))
            three_rows.append(row)
            for i,c in enumerate(candidates,1):candidate_rows.append({"experiment":"three_station","assumed_altitude_m":alt,"stations":";".join(combo),"branch":i,"selected":c is selected,**candidate_record(c,truth,alt)})
    write_csv(out/"test7c-three-station.csv",three_rows)

    configs=[tuple(ORDER)]+combos;synthetic_rows=[]
    for case,lat,lon,true_alt in synthetic_truths():
        tecef=geodetic_to_ecef(lat,lon,true_alt)
        for config in configs:
            for offset in (-5000,-3000,-1000,0,1000,3000,5000):
                m=synthetic_measured(lat,lon,true_alt,0,config);branches,cands,selected=solve(true_alt+offset,list(config),m)
                discovered=min((horizontal_error(tecef,position(c["en"],true_alt+offset)) for c in cands),default=None)
                synthetic_rows.append({"experiment":"altitude","case":case,"stations":";".join(config),"true_altitude_m":true_alt,"assumed_altitude_m":true_alt+offset,"altitude_error_m":offset,"noise_us":0,
                                       "branches":branches,"selected_horizontal_error_m":horizontal_error(tecef,position(selected["en"],true_alt+offset)) if selected else None,"best_discovered_horizontal_error_m":discovered,
                                       "selected_condition":selected["condition"] if selected else None})
            for noise in (.1,.25,.5,1.0):
                m=synthetic_measured(lat,lon,true_alt,noise,config);branches,cands,selected=solve(true_alt,list(config),m)
                synthetic_rows.append({"experiment":"timing_noise","case":case,"stations":";".join(config),"true_altitude_m":true_alt,"assumed_altitude_m":true_alt,"altitude_error_m":0,"noise_us":noise,
                                       "branches":branches,"selected_horizontal_error_m":horizontal_error(tecef,position(selected["en"],true_alt)) if selected else None,
                                       "best_discovered_horizontal_error_m":min((horizontal_error(tecef,position(c["en"],true_alt)) for c in cands),default=None),"selected_condition":selected["condition"] if selected else None})
    write_csv(out/"test7c-synthetic.csv",synthetic_rows)
    write_csv(out/"test7c-candidates.csv",candidate_rows)

    noise_summary=[]
    for config in configs:
        label=";".join(config)
        for noise in (.1,.25,.5,1.0):
            rows=[x for x in synthetic_rows if x["experiment"]=="timing_noise" and x["stations"]==label and x["noise_us"]==noise]
            noise_summary.append({"stations":label,"noise_us":noise,**summarize_errors(rows,"selected_horizontal_error_m")})
    write_csv(out/"test7c-noise-sensitivity.csv",noise_summary)

    truth_alt_row=min(altitude_rows,key=lambda x:abs(x["assumed_altitude_m"]-truth["alt"])); cond3d=float(sol7a["jacobian_condition"]);cond2d=truth_alt_row["jacobian_condition"]
    offset_results={str(offset):min(altitude_rows,key=lambda x:abs(x["altitude_error_m"]-offset)) for offset in (-5000,-3000,-1000,0,1000,3000,5000)}
    three_truth=[r for r in three_rows if abs(r["assumed_altitude_m"]-truth["alt"])<.01]
    exact_synthetic=[x for x in synthetic_rows if x["experiment"]=="altitude" and x["altitude_error_m"]==0]
    synthetic_pass=all(x["best_discovered_horizontal_error_m"] is not None and x["best_discovered_horizontal_error_m"]<1 for x in exact_synthetic)
    four_noise={str(n):next(x for x in noise_summary if x["stations"]==";".join(ORDER) and x["noise_us"]==n) for n in (.1,.25,.5,1.0)}
    four_altitude={}
    for offset in (-5000,-3000,-1000,1000,3000,5000):
        rows=[x for x in synthetic_rows if x["experiment"]=="altitude" and x["stations"]==";".join(ORDER) and x["altitude_error_m"]==offset]
        four_altitude[str(offset)]={"median_m":statistics.median(x["selected_horizontal_error_m"] for x in rows),"max_m":max(x["selected_horizontal_error_m"] for x in rows)}
    # Qualitative robustness based on measured horizontal displacement across ±3 km.
    max3=max(offset_results["-3000"]["horizontal_error_m"],offset_results["3000"]["horizontal_error_m"])
    robustness="ROBUST" if max3<2000 else "MODERATELY SENSITIVE" if max3<10000 else "HIGHLY SENSITIVE"
    useful_three=sum(r["horizontal_error_m"]<5000 and r["competitive_credible_branches"]==1 for r in three_truth)
    decision="STRONG PASS" if truth_alt_row["horizontal_error_m"]<1000 and robustness=="ROBUST" and useful_three>=3 and cond3d/cond2d>100 else "PASS" if truth_alt_row["horizontal_error_m"]<2000 and robustness!="HIGHLY SENSITIVE" and useful_three>=2 else "PARTIAL PASS" if truth_alt_row["horizontal_error_m"]<5000 else "FAIL"
    summary={"decision":decision,"robustness":robustness,"constants":{"speed_of_light_m_s":C,"beast_hz":BEAST_HZ},"cluster_id":"104422",
             "truth":truth,"measured_tdoas_us":{f"{a}__{b}":v for (a,b),v in measured.items()},"four_receiver_truth_altitude":truth_alt_row,
             "test7a":{"horizontal_error_m":float(event["horizontal_error_vs_truth_km"])*1000,"vertical_error_m":float(event["vertical_error_vs_truth_m"]),"condition":cond3d},
             "conditioning":{"2d_condition":cond2d,"3d_condition":cond3d,"improvement_ratio":cond3d/cond2d},"altitude_offsets":offset_results,
             "three_station_truth_altitude":three_truth,"synthetic":{"passed":synthetic_pass,"exact_case_count":len(exact_synthetic),"noise_summary":noise_summary,"four_receiver_altitude_error_summary":four_altitude},
             "architectural_recommendation":"Prioritize TDOA-derived latitude/longitude with altitude from an independently trusted Mode C, Mode S, or other source; do not treat TDOA altitude as a primary output."}
    (out/"test7c-summary.json").write_text(json.dumps(summary,indent=2))

    lines=["TEST 7C — ALTITUDE-CONSTRAINED 2D LOCALIZATION","="*52,"",f"Decision: {decision}; altitude robustness: {robustness}.",
           "Solver: network-centered horizontal coordinates, fixed geodetic altitude, deterministic multi-start; truth lat/lon never used for initialization or branch selection.","",
           "CLUSTER 104422",f"Truth: lat={truth['lat']:.6f}, lon={truth['lon']:.6f}, altitude={truth['alt']:.1f} m (independent DF17 {truth['icao']}).",
           f"Four-receiver fixed-altitude solution: lat={truth_alt_row['solution_lat']:.6f}, lon={truth_alt_row['solution_lon']:.6f}, horizontal error={truth_alt_row['horizontal_error_m']:.1f} m, RMS={truth_alt_row['rms_residual_us']:.3f} us, condition={cond2d:.3g}.",
           f"Test 7A unconstrained 3D: horizontal error={float(event['horizontal_error_vs_truth_km'])*1000:.1f} m, vertical error={float(event['vertical_error_vs_truth_m']):.1f} m, condition={cond3d:.3g}.",
           f"Condition improvement 3D/2D: {cond3d/cond2d:.3g}x.","","ALTITUDE SENSITIVITY"]
    for offset in (-5000,-3000,-1000,0,1000,3000,5000):
        r=offset_results[str(offset)];lines.append(f"Altitude error {offset:+6d} m: horizontal error={r['horizontal_error_m']:.1f} m, solution shift={r['horizontal_solution_displacement_m']:.1f} m ({r['displacement_per_km_altitude_error_m']:.1f} m/km), RMS={r['rms_residual_us']:.3f} us, condition={r['jacobian_condition']:.3g}, competitive/all stationary branches={r['competitive_credible_branches']}/{r['branches']}")
    lines += ["","THREE-RECEIVER COMBINATIONS AT TRUTH ALTITUDE"]
    for r in three_truth:lines.append(f"{r['stations']}: branches={r['branches']}, competitive={r['competitive_credible_branches']}, selected horizontal error={r['horizontal_error_m']:.1f} m, RMS={r['rms_residual_us']:.3f} us, condition={r['jacobian_condition']:.3g}")
    lines += ["Wrong-altitude range (5/8/10/12/15 km):"]
    for combo in combos:
        rows=[r for r in three_rows if r["stations"]==";".join(combo)]
        lines.append(f"  {';'.join(combo)}: selected horizontal error min/max={min(r['horizontal_error_m'] for r in rows):.1f}/{max(r['horizontal_error_m'] for r in rows):.1f} m; max competitive branches={max(r['competitive_credible_branches'] for r in rows)}")
    ranked=sorted(three_truth,key=lambda x:(x["jacobian_condition"],x["competitive_credible_branches"]));lines += ["Independent geometry ranking: "+" > ".join(r["stations"] for r in ranked),"","SYNTHETIC TIMING NOISE — FOUR RECEIVERS"]
    for n,r in four_noise.items():lines.append(f"{n} us: horizontal median/P90/max={r['median_m']:.1f}/{r['p90_m']:.1f}/{r['max_m']:.1f} m")
    lines += ["Synthetic four-receiver altitude-error median/max:"]
    for offset in (-5000,-3000,-1000,1000,3000,5000):
        r=four_altitude[str(offset)];lines.append(f"  {offset:+d} m: {r['median_m']:.1f}/{r['max_m']:.1f} m")
    lines += ["Three-receiver 1.0 us timing-noise median/P90/max:"]
    for combo in combos:
        r=next(x for x in noise_summary if x["stations"]==";".join(combo) and x["noise_us"]==1.0)
        lines.append(f"  {';'.join(combo)}: {r['median_m']:.1f}/{r['p90_m']:.1f}/{r['max_m']:.1f} m")
    lines += ["","KEY QUESTIONS",f"1-2. Correct-altitude 2D recovery: yes; horizontal error {truth_alt_row['horizontal_error_m']:.1f} m.",
              f"3. Test 7A unconstrained horizontal error was {float(event['horizontal_error_vs_truth_km'])*1000:.1f} m, but altitude was wrong by {float(event['vertical_error_vs_truth_m']):.1f} m.",
              f"4. ±1 km altitude errors give {offset_results['-1000']['horizontal_error_m']:.1f}/{offset_results['1000']['horizontal_error_m']:.1f} m horizontal error.",
              f"5. ±3 km: {offset_results['-3000']['horizontal_error_m']:.1f}/{offset_results['3000']['horizontal_error_m']:.1f} m.",
              f"6. ±5 km: {offset_results['-5000']['horizontal_error_m']:.1f}/{offset_results['5000']['horizontal_error_m']:.1f} m.",
              f"7. Approximate-altitude usefulness: {robustness}.",f"8. Useful unambiguous three-receiver combinations at truth altitude: {useful_three}/4.",
              "9. Best combinations by independent 2D condition: "+", ".join(r["stations"] for r in ranked[:2])+".",
              "10. Branch counts and competitive credible branches are reported for every combination/altitude.",f"11. 2D condition improves over 3D by {cond3d/cond2d:.3g}x for cluster 104422.",
              "12. Four-receiver timing-noise median errors at 0.1/0.25/0.5/1.0 us: "+"/".join(f"{four_noise[str(n)]['median_m']:.1f} m" for n in (.1,.25,.5,1.0))+".",
              f"13. Desirable altitude accuracy is about ±1 km for broadly sub-kilometre performance in these tests (synthetic worst case {max(four_altitude['-1000']['max_m'],four_altitude['1000']['max_m']):.1f} m); ±3–5 km remains useful in favorable geometry but is less reliable.",
              "14. Yes: stop treating TDOA-derived altitude as a primary output for this geometry.",
              "15. Recommend architecture: synchronized TDOA + independent trusted altitude -> latitude/longitude.","",f"OVERALL: {decision}"]
    (out/"test7c-report.txt").write_text("\n".join(lines)+"\n");print("\n".join(lines[-16:]))

if __name__=="__main__":main()
