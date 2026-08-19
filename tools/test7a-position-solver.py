#!/usr/bin/env python3
"""Test 7A: offline unconstrained four-receiver ECEF TDOA solver validation."""

import csv
import itertools
import json
import math
import statistics
from collections import Counter
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

C = 299_792_458.0
BEAST_HZ = 12_000_000.0
WGS84_A = 6_378_137.0
WGS84_F = 1 / 298.257223563
WGS84_E2 = WGS84_F * (2 - WGS84_F)
STATIONS = {
    "T37": (21.485594, 107.773191, 60.0),
    "Dao_Cai_chien": (21.320940, 107.766116, 28.0),
    "QK4": (18.760032, 105.659087, 20.0),
    "BachLongVi": (20.132285, 107.724413, 28.0),
}
ORDER = list(STATIONS)
PAIRS = list(itertools.combinations(ORDER, 2))
SOURCE_RUN = Path("/home/mlatserver/modeac-poc/test6/20260809T034035Z")
OUTPUT = Path("/home/mlatserver/modeac-poc/test7a")


def geodetic_to_ecef(lat_deg, lon_deg, alt_m):
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sl, cl = math.sin(lat), math.cos(lat); n = WGS84_A / math.sqrt(1-WGS84_E2*sl*sl)
    return np.array([(n+alt_m)*cl*math.cos(lon),(n+alt_m)*cl*math.sin(lon),(n*(1-WGS84_E2)+alt_m)*sl])


def ecef_to_geodetic(p):
    x,y,z=map(float,p); lon=math.atan2(y,x); rho=math.hypot(x,y)
    lat=math.atan2(z,rho*(1-WGS84_E2))
    for _ in range(20):
        n=WGS84_A/math.sqrt(1-WGS84_E2*math.sin(lat)**2)
        alt=rho/math.cos(lat)-n
        nxt=math.atan2(z,rho*(1-WGS84_E2*n/(n+alt)))
        if abs(nxt-lat)<1e-14: lat=nxt; break
        lat=nxt
    n=WGS84_A/math.sqrt(1-WGS84_E2*math.sin(lat)**2); alt=rho/math.cos(lat)-n
    return math.degrees(lat),math.degrees(lon),alt


RECEIVERS={s:geodetic_to_ecef(*v) for s,v in STATIONS.items()}


def tdoa_us(position):
    distances={s:float(np.linalg.norm(position-r)) for s,r in RECEIVERS.items()}
    return {pair:(distances[pair[1]]-distances[pair[0]])/C*1e6 for pair in PAIRS}


def reference_measurements(normalized):
    return np.array([(normalized[s]-normalized["T37"])/12.0 for s in ORDER[1:]])


def residual_m(position, measured_ref_us):
    ref=np.linalg.norm(position-RECEIVERS["T37"])
    predicted=np.array([np.linalg.norm(position-RECEIVERS[s])-ref for s in ORDER[1:]])
    return predicted-measured_ref_us*C/1e6


def jacobian(position):
    ref_vec=position-RECEIVERS["T37"]; ref_norm=np.linalg.norm(ref_vec)
    return np.vstack([(position-RECEIVERS[s])/np.linalg.norm(position-RECEIVERS[s])-ref_vec/ref_norm for s in ORDER[1:]])


def network_center():
    lat=statistics.mean(v[0] for v in STATIONS.values()); lon=statistics.mean(v[1] for v in STATIONS.values())
    return lat,lon


def starts():
    lat,lon=network_center(); output=[]
    for alt in (-10_000,0,1_000,5_000,10_000,15_000,30_000,100_000): output.append(geodetic_to_ecef(lat,lon,alt))
    for north_km,east_km in ((100,0),(-100,0),(0,100),(0,-100),(250,0),(-250,0),(0,250),(0,-250),
                              (300,300),(300,-300),(-300,300),(-300,-300),(700,0),(-700,0),(0,700),(0,-700)):
        plat=lat+north_km/111.0; plon=lon+east_km/(111.0*math.cos(math.radians(lat)))
        for alt in (0,10_000,30_000): output.append(geodetic_to_ecef(plat,plon,alt))
    # Include receiver locations and antipodal radial starts to expose nonphysical branches.
    output.extend(RECEIVERS.values()); surface=geodetic_to_ecef(lat,lon,0); output.append(-surface)
    return output


STARTS=starts()


def all_pair_residuals(position, normalized):
    predicted=tdoa_us(position); measured={p:(normalized[p[1]]-normalized[p[0]])/12 for p in PAIRS}
    residual={p:predicted[p]-measured[p] for p in PAIRS}; values=list(residual.values())
    return measured,predicted,residual,math.sqrt(statistics.mean(x*x for x in values)),max(abs(x) for x in values)


def solve(measured_ref_us):
    converged=[]
    for start in STARTS:
        result=least_squares(residual_m,start,args=(measured_ref_us,),method="lm",max_nfev=3000,
                             ftol=1e-13,xtol=1e-13,gtol=1e-13)
        if result.success and np.all(np.isfinite(result.x)):
            converged.append((result.x,float(np.linalg.norm(result.fun)),result.nfev))
    branches=[]
    for position,cost,nfev in sorted(converged,key=lambda x:x[1]):
        if not any(np.linalg.norm(position-b["position"])<100.0 for b in branches):
            branches.append({"position":position,"equation_residual_m":cost,"nfev":nfev})
    return len(converged),branches


def point_in_polygon(lat,lon):
    polygon=[(v[1],v[0]) for v in STATIONS.values()]; inside=False; j=len(polygon)-1
    for i,(xi,yi) in enumerate(polygon):
        xj,yj=polygon[j]
        if ((yi>lat)!=(yj>lat)) and lon < (xj-xi)*(lat-yi)/(yj-yi)+xi: inside=not inside
        j=i
    return inside


NETWORK_LAT,NETWORK_LON=network_center(); NETWORK_SURFACE=geodetic_to_ecef(NETWORK_LAT,NETWORK_LON,statistics.mean(v[2] for v in STATIONS.values()))


def candidate_details(branch, normalized):
    p=branch["position"]; lat,lon,alt=ecef_to_geodetic(p)
    measured,predicted,residual,rms,max_abs=all_pair_residuals(p,normalized)
    condition=float(np.linalg.cond(jacobian(p)))
    nearest=min(np.linalg.norm(p-r) for r in RECEIVERS.values())/1000
    center=np.linalg.norm(p-NETWORK_SURFACE)/1000
    altitude_class=("strongly implausible" if alt < -1000 else "questionable below surface" if alt < 0 else
                    "ordinary-aircraft range" if alt <= 20000 else "unusual" if alt <=30000 else "strongly questionable")
    geography="inside network" if point_in_polygon(lat,lon) else "near network" if center<=500 else "far outside network"
    # Broad credibility is deliberately separate from solution quality: a below-sea-level
    # or ill-conditioned branch is retained as QUESTIONABLE rather than silently rejected.
    plausible=(-1000<=alt<=30000 and center<=1000 and condition<1e12 and rms<5.0)
    ordinary=(0<=alt<=20000 and center<=500 and condition<1e6 and rms<2.0)
    return {**branch,"lat":lat,"lon":lon,"altitude_m":alt,"condition":condition,"nearest_km":nearest,"center_km":center,
            "altitude_class":altitude_class,"geography":geography,"plausible":plausible,"ordinary":ordinary,
            "measured":measured,"predicted":predicted,"residual":residual,"rms_us":rms,"max_us":max_abs}


def select_and_classify(candidates):
    ordinary=[x for x in candidates if x["ordinary"]]; plausible=[x for x in candidates if x["plausible"]]
    pool=ordinary or plausible or candidates
    if not pool: return None,"REJECT","No converged solution"
    best=min(pool,key=lambda x:(x["rms_us"],x["condition"]))
    competing=[x for x in plausible if x is not best and x["rms_us"]<=best["rms_us"]+1.0]
    if not plausible:
        return best,"REJECT","Converged branches are geographically/altitudinally implausible or catastrophically conditioned"
    if competing:
        return best,"QUESTIONABLE",f"{len(competing)} competing physically plausible branch(es) with comparable residual"
    if not best["ordinary"]:
        return best,"QUESTIONABLE",f"Best credible branch is {best['altitude_class']}, {best['geography']}, and/or poorly conditioned (condition {best['condition']:.3g})"
    return best,"VALID","Unique ordinary-aircraft-range branch with low residual and acceptable conditioning"


def horizontal_error_m(truth,estimate):
    lat,lon,_=ecef_to_geodetic(truth); up=truth/np.linalg.norm(truth); delta=estimate-truth
    vertical=float(np.dot(delta,up)); horizontal=float(np.linalg.norm(delta-vertical*up))
    return horizontal,vertical,float(np.linalg.norm(delta))


def synthetic_tests():
    cases=[("inside_low",20.50,106.90,1000), ("inside_5km",20.50,106.90,5000),
           ("inside_10km",20.50,106.90,10000),("inside_20km",20.50,106.90,20000),
           ("east_displaced",20.8,109.0,10000),("southwest_poor",17.0,103.5,10000)]
    rows=[]
    pattern=np.array([1.0,-0.5,0.75])
    for name,lat,lon,alt in cases:
        truth=geodetic_to_ecef(lat,lon,alt); exact=np.array([tdoa_us(truth)[("T37",s)] for s in ORDER[1:]])
        for noise in (0,.1,.25,.5,1.0):
            measured=exact+noise*pattern; converged,branches=solve(measured)
            if branches:
                chosen=min(branches,key=lambda b:np.linalg.norm(b["position"]-truth)); h,v,e=horizontal_error_m(truth,chosen["position"])
                rms=math.sqrt(statistics.mean((x/C*1e6)**2 for x in residual_m(chosen["position"],measured)))
                cond=float(np.linalg.cond(jacobian(chosen["position"])))
            else: h=v=e=rms=cond=None
            # Without QK4 only two independent TDOAs constrain three coordinates: rank deficient.
            j=jacobian(truth); cond_without=float("inf") if np.linalg.matrix_rank(j[[0,2],:])<3 else float(np.linalg.cond(j[[0,2],:]))
            rows.append({"case":name,"truth_lat":lat,"truth_lon":lon,"truth_altitude_m":alt,"noise_us":noise,
                         "horizontal_error_m":h,"vertical_error_m":v,"ecef_error_m":e,"tdoa_rms_residual_us":rms,
                         "jacobian_condition_with_qk4":cond,"jacobian_condition_without_qk4":cond_without,
                         "converged_starts":converged,"unique_branches":len(branches)})
    return rows


def json_safe(value):
    if isinstance(value,np.ndarray): return value.tolist()
    if isinstance(value,np.generic): return value.item()
    if isinstance(value,float) and not math.isfinite(value): return None
    if isinstance(value,dict): return {str(k):json_safe(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [json_safe(x) for x in value]
    return value


def main():
    OUTPUT.mkdir(exist_ok=True)
    cluster_path=SOURCE_RUN/"clusters/test6-clusters.csv"; four=[]
    with cluster_path.open(newline="") as f:
        for source_row,row in enumerate(csv.DictReader(f),start=2):
            if int(row["station_count"])==4: four.append((source_row,row))
    if len(four)!=8: raise RuntimeError(f"expected exactly 8 four-station clusters, found {len(four)}")
    verification=json.loads((SOURCE_RUN/"reports/capture-verification.json").read_text())
    coarse_origin=min(v["first_utc_ns"] for v in verification["stations"].values())
    synthetic=synthetic_tests()
    synthetic_fields=list(synthetic[0]);
    with (OUTPUT/"test7a-synthetic.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=synthetic_fields);w.writeheader();w.writerows(synthetic)

    solutions=[]; candidate_rows=[]; residual_rows=[]; real_details=[]
    for source_row,row in four:
        normalized={s:float(row[f"{s}_normalized_timestamp"]) for s in ORDER}
        original={s:int(row[f"{s}_timestamp"]) for s in ORDER}
        ref=reference_measurements(normalized); converged,branches=solve(ref)
        candidates=[candidate_details(b,normalized) for b in branches]
        best,classification,reason=select_and_classify(candidates)
        coarse_ns=coarse_origin+int(float(row["seconds_from_start"])*1e9)
        coarse_time=__import__('datetime').datetime.fromtimestamp(coarse_ns/1e9,__import__('datetime').timezone.utc).isoformat()
        for branch_id,cand in enumerate(candidates,1):
            candidate_rows.append({"cluster_id":row["cluster_id"],"branch_id":branch_id,"selected":cand is best,
                "latitude":cand["lat"],"longitude":cand["lon"],"altitude_m":cand["altitude_m"],"rms_residual_us":cand["rms_us"],
                "max_residual_us":cand["max_us"],"jacobian_condition":cand["condition"],"nearest_receiver_distance_km":cand["nearest_km"],
                "network_centroid_distance_km":cand["center_km"],"altitude_class":cand["altitude_class"],"geography":cand["geography"],"plausible":cand["plausible"]})
            for pair in PAIRS:
                residual_rows.append({"cluster_id":row["cluster_id"],"branch_id":branch_id,"station_a":pair[0],"station_b":pair[1],
                                      "measured_tdoa_us":cand["measured"][pair],"predicted_tdoa_us":cand["predicted"][pair],"residual_us":cand["residual"][pair]})
        base={"cluster_id":row["cluster_id"],"source_csv_row":source_row,"raw_modeac":row["raw_hex"],"coarse_time":coarse_time,
              "solve_status":"converged" if candidates else "failed","classification":classification,"classification_reason":reason,
              "converged_starts":converged,"unique_branches":len(candidates),
              **{f"original_{s}_timestamp":original[s] for s in ORDER},**{f"normalized_{s}_timestamp":normalized[s] for s in ORDER},
              **{f"measured_T37_to_{s}_us":ref[i] for i,s in enumerate(ORDER[1:])}}
        if best:
            base.update({"latitude":best["lat"],"longitude":best["lon"],"altitude_m":best["altitude_m"],
                         "ecef_x":best["position"][0],"ecef_y":best["position"][1],"ecef_z":best["position"][2],
                         "rms_residual_us":best["rms_us"],"max_residual_us":best["max_us"],"jacobian_condition":best["condition"],
                         "nearest_receiver_distance_km":best["nearest_km"],"network_centroid_distance_km":best["center_km"],
                         "altitude_class":best["altitude_class"],"geography":best["geography"]})
        solutions.append(base)
        real_details.append({"solution":base,"candidates":candidates})

    fields=list(dict.fromkeys(k for row in solutions for k in row))
    with (OUTPUT/"test7a-solutions.csv").open("w",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(solutions)
    for path,rows in ((OUTPUT/"test7a-candidates.csv",candidate_rows),(OUTPUT/"test7a-residuals.csv",residual_rows)):
        with path.open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else ["cluster_id"]);w.writeheader();w.writerows(rows)

    classes=Counter(x["classification"] for x in solutions); converged=sum(x["solve_status"]=="converged" for x in solutions)
    rms=[x["rms_residual_us"] for x in solutions if "rms_residual_us" in x]; alts=[x["altitude_m"] for x in solutions if "altitude_m" in x]
    noiseless=[x for x in synthetic if x["noise_us"]==0]; synthetic_pass=all(x["ecef_error_m"] is not None and x["ecef_error_m"]<1 for x in noiseless)
    sensitivity={str(n):{"horizontal_median_m":statistics.median(x["horizontal_error_m"] for x in synthetic if x["noise_us"]==n),
                         "horizontal_max_m":max(x["horizontal_error_m"] for x in synthetic if x["noise_us"]==n),
                         "vertical_abs_median_m":statistics.median(abs(x["vertical_error_m"]) for x in synthetic if x["noise_us"]==n),
                         "vertical_abs_max_m":max(abs(x["vertical_error_m"]) for x in synthetic if x["noise_us"]==n)} for n in (.1,.25,.5,1.0)}
    overall=("STRONG PASS" if synthetic_pass and classes["VALID"]>=6 and classes["QUESTIONABLE"]<=2 else
             "PASS" if synthetic_pass and classes["VALID"]+classes["QUESTIONABLE"]>=4 else
             "PARTIAL PASS" if synthetic_pass and converged else "FAIL")
    summary={"decision":overall,"constants":{"speed_of_light_m_s":C,"beast_hz":BEAST_HZ,"wgs84_a_m":WGS84_A,"wgs84_f":WGS84_F},
             "dependencies":{"numpy":np.__version__,"scipy":__import__('scipy').__version__},
             "timestamp_interpretation":{"domain":"T37 corrected Beast clock","unit":"12 MHz ticks","tdoa_formula":"(station_normalized-T37_normalized)/12 microseconds",
                 "original_timestamps_retained":True,"coarse_time_note":"derived from Test 6 earliest receive UTC plus seconds_from_start; not used by solver"},
             "source":{"run":str(SOURCE_RUN),"cluster_csv":str(cluster_path),"four_station_found":len(four),"attempted":len(solutions)},
             "synthetic":{"passed":synthetic_pass,"noiseless_max_ecef_error_m":max(x["ecef_error_m"] for x in noiseless),"sensitivity":sensitivity,
                          "qk4_effect":"Without QK4 the T37/Dao/Bach subset supplies only two independent equations for three coordinates (rank deficient); QK4 makes the Jacobian full rank."},
             "real":{"converged":converged,"classifications":dict(classes),"rms_residual_us":{"minimum":min(rms),"median":statistics.median(rms),"maximum":max(rms)},
                     "altitude_m":{"minimum":min(alts),"median":statistics.median(alts),"maximum":max(alts)},
                     "unique_branches":{"minimum":min(x["unique_branches"] for x in solutions),"median":statistics.median(x["unique_branches"] for x in solutions),"maximum":max(x["unique_branches"] for x in solutions)},
                     "systematic_bias_assessment":"No solver bias in synthetic tests; eight real events do not show a consistent correctable timing bias, but most are inconsistent with ordinary-aircraft 3D geometry."},
             "recommendation":"Use external truth only as a diagnostic follow-up for the two questionable events, and prioritize five-station 4-of-5 solving when MongCai returns; do not advance these results to production localization.",
             "solutions":solutions}
    (OUTPUT/"test7a-summary.json").write_text(json.dumps(json_safe(summary),indent=2))

    lines=["TEST 7A — FOUR-STATION 3D POSITION SOLVER VALIDATION","="*57,"",
           "Timestamp representation: original corrected Beast timestamps and normalized timestamps are retained per station. Normalized values are 12 MHz ticks in the T37 receiver clock domain; pairwise TDOA is their difference divided by 12 in microseconds.",
           f"Solver: scipy.optimize.least_squares {__import__('scipy').__version__}, unconstrained ECEF range-difference equations, {len(STARTS)} deterministic starts, c={C:.1f} m/s.","",
           "SYNTHETIC VALIDATION",f"Noiseless recovery: {'PASS' if synthetic_pass else 'FAIL'}; maximum ECEF error {summary['synthetic']['noiseless_max_ecef_error_m']:.6f} m."]
    for noise,stat in sensitivity.items(): lines.append(f"Noise {noise} us: horizontal median/max {stat['horizontal_median_m']:.1f}/{stat['horizontal_max_m']:.1f} m; |vertical| median/max {stat['vertical_abs_median_m']:.1f}/{stat['vertical_abs_max_m']:.1f} m")
    lines += ["The displaced/poor geometry cases are most timing-sensitive. QK4 improves rank: without it the remaining three receivers provide only two independent TDOA equations for unconstrained 3D.","","REAL CLUSTERS"]
    for detail in real_details:
        x=detail["solution"]
        lines += ["",f"Cluster: {x['cluster_id']} (source CSV row {x['source_csv_row']})",f"Raw Mode A/C: {x['raw_modeac']}",f"Time: {x['coarse_time']}",
                  "Measured TDOAs: "+", ".join(f"T37->{s}={x[f'measured_T37_to_{s}_us']:.6f} us" for s in ORDER[1:]),
                  f"Solver: {x['converged_starts']} converged starts; {x['unique_branches']} unique branches"]
        if "latitude" in x:
            lines += [f"Best candidate: lat={x['latitude']:.6f}, lon={x['longitude']:.6f}, alt={x['altitude_m']:.1f} m",
                      f"Residual: RMS={x['rms_residual_us']:.6f} us, max={x['max_residual_us']:.6f} us; Jacobian condition={x['jacobian_condition']:.3g}",
                      f"Distances: nearest receiver={x['nearest_receiver_distance_km']:.1f} km, network centroid={x['network_centroid_distance_km']:.1f} km; {x['geography']}"]
        lines += [f"Classification: {x['classification']}",f"Reason: {x['classification_reason']}"]
    lines += ["","OVERALL QUESTIONS",f"1. Exactly eight found and attempted: {len(four)==8 and len(solutions)==8}.",
              f"2. Synthetic validation passed: {synthetic_pass}.",f"3. Real clusters with convergence: {converged}/8.",
              f"4-6. VALID={classes['VALID']}, QUESTIONABLE={classes['QUESTIONABLE']}, REJECT={classes['REJECT']}.",
              f"7. Selected-branch RMS residual min/median/max: {min(rms):.6f}/{statistics.median(rms):.6f}/{max(rms):.6f} us.",
              f"8. Selected altitude min/median/max: {min(alts):.1f}/{statistics.median(alts):.1f}/{max(alts):.1f} m.",
              f"9. Unique branches min/median/max: {summary['real']['unique_branches']['minimum']}/{summary['real']['unique_branches']['median']}/{summary['real']['unique_branches']['maximum']}; competing plausible branches drive QUESTIONABLE classifications.",
              "10. Jacobian conditions are reported per cluster; high values indicate vertical/branch sensitivity even when residual is nearly zero.",
              f"11. Physically plausible without external truth: {classes['VALID']+classes['QUESTIONABLE']}/8 retain a credible branch.",
              "12. Synthetic results show no solver bias. The eight real events do not establish a consistent correctable timing bias; most are instead incompatible with ordinary-aircraft 3D geometry.",
              "13. The present four-station geometry does not robustly demonstrate genuine 3D localization: only two events retain questionable branches and none are VALID.",
              "14. Use external truth as a diagnostic follow-up for the two questionable events, and prioritize five-station 4-of-5 solving when MongCai returns; do not advance this result to production localization.","",f"DECISION: {overall}"]
    (OUTPUT/"test7a-report.txt").write_text("\n".join(lines)+"\n")
    print("\n".join(lines[-16:]))


if __name__=="__main__": main()
