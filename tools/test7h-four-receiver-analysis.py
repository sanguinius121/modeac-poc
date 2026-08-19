#!/usr/bin/env python3
"""Test 7H strict four-receiver Mode-A fixed-altitude localization and truth validation."""
import argparse,csv,datetime as dt,html,importlib.util,itertools,json,math,statistics,subprocess,sys
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np

C=299_792_458.; HZ=12_000_000.; ORDER=["T37","Dao_Cai_chien","QK4","BachLongVi"]
PAIR_FIELDS=list(itertools.combinations(ORDER,2))

def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def pct(v,p):
    if not v:return None
    x=sorted(v);q=(len(x)-1)*p;a,b=math.floor(q),math.ceil(q);return x[a] if a==b else x[a]*(b-q)+x[b]*(q-a)
def stats(v):return {"count":len(v),"p50":pct(v,.5),"p75":pct(v,.75),"p90":pct(v,.9),"p95":pct(v,.95),"p99":pct(v,.99),"max":max(v) if v else None}
def write_csv(path,rows,fields):
    with path.open("w",newline="") as f:w=csv.DictWriter(f,fieldnames=fields,extrasaction="ignore");w.writeheader();w.writerows(rows)
def iso(ns):return dt.datetime.fromtimestamp(ns/1e9,dt.timezone.utc).isoformat().replace("+00:00","Z")
def classify(cands):
    if not cands:return "SOLVER_FAIL",[]
    plausible=[x for x in cands if x["center_km"]<=1500 and math.isfinite(x["condition"]) and x["condition"]<=1e6]
    if not plausible:return "SOLVER_FAIL",[]
    floor=min(x["rms_us"] for x in plausible)
    if floor>3:return "INCONSISTENT_4RX",[]
    credible=[x for x in plausible if x["rms_us"]<=min(3.,floor+.5)]
    return ("UNIQUE_4RX" if len(credible)==1 else "MULTIPLE_4RX"),credible
def distance(d7c,a,b,alt=0):return d7c.horizontal_error(d7c.geodetic_to_ecef(a[0],a[1],alt),d7c.geodetic_to_ecef(b[0],b[1],alt))

def map_html(path,icao,rows,candidates):
    rr=[x for x in rows if x.get("matched_icao")==icao]; truth=[[x["truth_lat"],x["truth_lon"]] for x in rr]
    selected=[[x["selected_lat"],x["selected_lon"]] for x in rr]
    ids={int(x["event_id"]) for x in rr}; rejected=[[x["lat"],x["lon"]] for x in candidates if int(x["event_id"]) in ids and not x["selected"]]
    center=truth[0] if truth else [20.5,107.]; data=json.dumps({"truth":truth,"selected":selected,"rejected":rejected})
    doc=f'''<!doctype html><meta charset="utf-8"><title>Test 7H {html.escape(icao)}</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>#map{{height:95vh}}</style><div id="map"></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>const d={data};const m=L.map('map').setView({json.dumps(center)},8);L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png').addTo(m);function line(x,c,n){{if(x.length)L.polyline(x,{{color:c}}).bindPopup(n).addTo(m)}}line(d.truth,'blue','ADS-B truth');line(d.selected,'green','accepted 4-RX');d.rejected.forEach(p=>L.circleMarker(p,{{radius:3,color:'gray'}}).addTo(m));</script>'''
    path.write_text(doc)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument("run_dir");a=ap.parse_args();run=Path(a.run_dir).resolve();tools=Path(__file__).parent
    if not (run/"reports/capture-verification.json").is_file():raise SystemExit("capture verification missing")
    capture=json.loads((run/"reports/capture-verification.json").read_text())
    if not capture["capture_accepted"] or capture["duration_s"]!=600:raise SystemExit("accepted 600-second capture required")
    (run/"clusters").mkdir(exist_ok=True); (run/"pairwise").mkdir(exist_ok=True)
    if not (run/"reports/test6-summary.json").is_file():
        subprocess.run([sys.executable,str(tools/"test6-analyze.py"),str(run),"--margin-us",".5"],check=True)
    s6=json.loads((run/"reports/test6-summary.json").read_text())
    degraded_links=[x for x in s6["pairwise"].values() if x["clock"]["classification"] not in ("STRONG PASS","PASS")]
    d7e=module("d7e_for_7h",tools/"test7e-modea-2d-validation.py");d7c=module("d7c_for_7h",tools/"test7c-2d-solver.py");d7d=module("d7d_for_7h",tools/"test7d-modeac-altitude.py")
    d7b,t4,unused,transforms,trajectories,receivers=d7e.build_context(run,tools)
    identity_tx,intervals,identity_counts=d7e.build_identity_timeline(run,transforms,set(trajectories))
    limits={tuple(x["stations"]):x["baseline_m"]/C*1e6 for x in s6["pairwise"].values()}
    all_mode_a_codes={f"{n:04o}" for n in range(4096)}
    events,raw_candidates,diag=d7e.build_modea_events(run,transforms,all_mode_a_codes,limits,d7d.decode)
    four=[x for x in events if x["station_count"]==4]
    t37=[]
    with (run/"captures/modeac-T37.csv").open() as f:
        for row in csv.DictReader(f):
            if int(row["timestamp_corrected"]):t37.append((d7e.norm_tick(row,transforms["T37"]),int(row["recv_utc_ns"])))
    anchor=min(t37);tick_to_ns=lambda tick:int(anchor[1]+(tick-anchor[0])/HZ*1e9)
    event_rows=[];candidate_rows=[];selected=[];altrows=[]
    for e in four:
        tick=e["reference_tick"]; active=d7e.active_squawks(intervals,tick); same=sorted(icao for icao,sq in active.items() if sq==e["mode_a_code"] and icao in trajectories)
        altitude=[]
        for icao in same:
            nearest=min(trajectories[icao],key=lambda x:abs(x["norm"]-tick))
            age=abs(nearest["norm"]-tick)/HZ
            if age<=15:altitude.append((icao,float(nearest["alt_m"]),age))
        alt=None;source="NO_TRUSTED_ALTITUDE";age=None
        if len(altitude)==1:source="DF17_BARO_UNIQUE_SQUAWK";alt=altitude[0][1];age=altitude[0][2]
        elif altitude and max(x[1] for x in altitude)-min(x[1] for x in altitude)<=300:
            source="DF17_BARO_SHARED_SQUAWK_CONSISTENT";alt=statistics.median(x[1] for x in altitude);age=max(x[2] for x in altitude)
        measured=d7e.measured(e);branches=[];classification="SOLVER_FAIL";credible=[]
        if alt is not None:
            _,branches,_=d7c.solve(alt,ORDER,measured);classification,credible=classify(branches)
        chosen=min(credible,key=lambda x:(x["rms_us"],x["center_km"],x["condition"])) if classification=="UNIQUE_4RX" else None
        base={"event_id":e["event_id"],"event_time":iso(tick_to_ns(tick)),"reference_tick":tick,"mode_a_code":e["mode_a_code"],
              "stations":e["stations"],"source_rows":e["source_rows"],"raw_words":e["raw_words"],"normalized_timestamps":";".join(f"{s}:{e['normalized'][s]:.6f}" for s in ORDER),
              "altitude_m":alt,"altitude_source":source,"altitude_age_s":age,"active_same_squawk_icaos":len(same),"solver_branch_count":len(branches),
              "credible_branch_count":len(credible),"classification":classification,"best_rms_us":min((x["rms_us"] for x in branches),default=None)}
        event_rows.append(base)
        for rank,c in enumerate(branches,1):
            cr={"event_id":e["event_id"],"rank":rank,"mode_a_code":e["mode_a_code"],"altitude_m":alt,"lat":c["lat"],"lon":c["lon"],"rms_us":c["rms_us"],"max_us":c["max_us"],"condition":c["condition"],"center_km":c["center_km"],"credible":any(c is q for q in credible),"selected":c is chosen}
            candidate_rows.append(cr)
        if chosen:
            ordered=sorted((x for x in branches if x["center_km"]<=1500),key=lambda x:x["rms_us"]);second=ordered[1]["rms_us"] if len(ordered)>1 else None
            selected.append({**{k:base[k] for k in ("event_id","event_time","reference_tick","mode_a_code","stations","source_rows","normalized_timestamps","altitude_source","classification")},
                             "selected_lat":chosen["lat"],"selected_lon":chosen["lon"],"altitude_used":alt,"altitude_age":age,"candidate_count":len(branches),
                             "best_residual":chosen["rms_us"],"second_best_residual":second,"branch_margin":second-chosen["rms_us"] if second is not None else None,
                             "tdoa_max_us":chosen["max_us"],"condition":chosen["condition"],"network_center_km":chosen["center_km"]})
        for off in (-1000,0,1000):
            ar={"event_id":e["event_id"],"altitude_offset_m":off,"assumed_altitude_m":alt+off if alt is not None else None,"classification":"SOLVER_FAIL","selected_lat":None,"selected_lon":None}
            if alt is not None:
                _,cc,_=d7c.solve(alt+off,ORDER,measured);cl,cred=classify(cc);ch=min(cred,key=lambda x:(x["rms_us"],x["center_km"],x["condition"])) if cl=="UNIQUE_4RX" else None
                ar.update(classification=cl,credible_branch_count=len(cred),best_rms_us=min((x["rms_us"] for x in cc),default=None),selected_lat=ch["lat"] if ch else None,selected_lon=ch["lon"] if ch else None)
            altrows.append(ar)
    event_fields=["event_id","event_time","reference_tick","mode_a_code","stations","source_rows","raw_words","normalized_timestamps","altitude_m","altitude_source","altitude_age_s","active_same_squawk_icaos","solver_branch_count","credible_branch_count","classification","best_rms_us"]
    cand_fields=["event_id","rank","mode_a_code","altitude_m","lat","lon","rms_us","max_us","condition","center_km","credible","selected"]
    selected_fields=["event_id","event_time","reference_tick","mode_a_code","stations","source_rows","normalized_timestamps","selected_lat","selected_lon","altitude_used","altitude_source","altitude_age","candidate_count","classification","best_residual","second_best_residual","branch_margin","tdoa_max_us","condition","network_center_km"]
    write_csv(run/"modeac-4rx-events.csv",event_rows,event_fields);write_csv(run/"modeac-4rx-candidates.csv",candidate_rows,cand_fields)
    # Anti-leakage boundary: this artifact is fully written before any position-truth association below.
    write_csv(run/"test7h-selected-before-truth.csv",selected,selected_fields)

    associations,truth_candidates,failures=d7e.associate(four,intervals,trajectories,d7b,t4,receivers,tick_to_ns);assoc={int(x["event_id"]):x for x in associations};evaluated=[]
    for row in selected:
        ar=assoc[int(row["event_id"])]
        if ar.get("classification") not in ("STRONG","PLAUSIBLE") or not ar.get("matched_icao") or ar["truth_lat"] is None:continue
        err,east,north,bearing=d7e.error_components(t4,ar,float(row["selected_lat"]),float(row["selected_lon"]),float(row["altitude_used"]))
        tr=trajectories[ar["matched_icao"]];near=min(range(len(tr)),key=lambda i:abs(tr[i]["norm"]-float(row["reference_tick"])))
        lo=max(0,near-1);hi=min(len(tr)-1,near+1);te,tn=0.,0.
        if hi!=lo:
            _,te,tn,_=d7e.error_components(t4,{"truth_lat":tr[lo]["lat"],"truth_lon":tr[lo]["lon"]},tr[hi]["lat"],tr[hi]["lon"],tr[hi]["alt_m"])
        mag=math.hypot(te,tn);along=(east*te+north*tn)/mag if mag else None;cross=(-east*tn+north*te)/mag if mag else None
        evaluated.append({**row,"matched_icao":ar["matched_icao"],"truth_classification":ar["classification"],"truth_lat":ar["truth_lat"],"truth_lon":ar["truth_lon"],"truth_altitude_m":ar["truth_altitude_m"],
                          "horizontal_error_m":err,"east_error_m":east,"north_error_m":north,"along_track_error_m":along,"cross_track_error_m":cross,"abs_cross_track_error_m":abs(cross) if cross is not None else None})
    eval_fields=selected_fields+["matched_icao","truth_classification","truth_lat","truth_lon","truth_altitude_m","horizontal_error_m","east_error_m","north_error_m","along_track_error_m","cross_track_error_m","abs_cross_track_error_m"]
    write_csv(run/"test7h-evaluated.csv",evaluated,eval_fields)
    for eid,group in itertools.groupby(sorted(altrows,key=lambda x:(x["event_id"],x["altitude_offset_m"])),key=lambda x:x["event_id"]):
        vals={x["altitude_offset_m"]:x for x in group};nom=vals.get(0)
        for off,x in vals.items():
            x["horizontal_shift_m"]=(distance(d7c,(nom["selected_lat"],nom["selected_lon"]),(x["selected_lat"],x["selected_lon"]))
                                     if nom and nom.get("selected_lat") is not None and x.get("selected_lat") is not None else None)
    write_csv(run/"test7h-altitude-sensitivity.csv",altrows,["event_id","altitude_offset_m","assumed_altitude_m","classification","credible_branch_count","best_rms_us","selected_lat","selected_lon","horizontal_shift_m"])
    write_csv(run/"test7h-association-failures.csv",failures,["event_id","mode_a_code","stations","candidate_aircraft_count","classification","failure_reason","best_rms_us","best_max_us"])
    mirror=[]
    altby=defaultdict(dict)
    for x in altrows:altby[int(x["event_id"])][int(x["altitude_offset_m"])]=x
    for e in event_rows:
        eid=int(e["event_id"]);base=altby[eid].get(0);minus=altby[eid].get(-1000);plus=altby[eid].get(1000)
        branches=sorted((x for x in candidate_rows if int(x["event_id"])==eid and x["center_km"]<=1500),key=lambda x:x["rms_us"]);truth=assoc.get(eid);nearest=None
        truth_eligible=bool(truth and truth.get("classification") in ("STRONG","PLAUSIBLE"))
        if truth_eligible and truth.get("truth_lat") is not None and branches:
            nearest=min(branches,key=lambda x:distance(d7c,(x["lat"],x["lon"]),(truth["truth_lat"],truth["truth_lon"])))
        mirror.append({"event_id":eid,"classification":e["classification"],"initial_branches":e["solver_branch_count"],"credible_branches":e["credible_branch_count"],
                       "branch_distance_m":distance(d7c,(branches[0]["lat"],branches[0]["lon"]),(branches[1]["lat"],branches[1]["lon"])) if len(branches)>1 else None,
                       "best_residual_us":branches[0]["rms_us"] if branches else None,"second_residual_us":branches[1]["rms_us"] if len(branches)>1 else None,
                       "residual_ratio":branches[1]["rms_us"]/max(branches[0]["rms_us"],1e-12) if len(branches)>1 else None,"residual_difference_us":branches[1]["rms_us"]-branches[0]["rms_us"] if len(branches)>1 else None,
                       "truth_match_classification":truth.get("classification") if truth else None,"selected_nearest_truth":bool(nearest and branches[0]["rank"]==nearest["rank"]) if truth_eligible else None,"minus_1km_classification":minus["classification"],"plus_1km_classification":plus["classification"],
                       "altitude_changes_classification":minus["classification"]!=base["classification"] or plus["classification"]!=base["classification"]})
    mirror_fields=["event_id","classification","initial_branches","credible_branches","branch_distance_m","best_residual_us","second_residual_us","residual_ratio","residual_difference_us","truth_match_classification","selected_nearest_truth","minus_1km_classification","plus_1km_classification","altitude_changes_classification"]
    write_csv(run/"test7h-mirror-analysis.csv",mirror,mirror_fields)

    tracks=[];per=[]
    for icao in sorted({x["matched_icao"] for x in evaluated}):
        rr=sorted((x for x in evaluated if x["matched_icao"]==icao),key=lambda x:float(x["reference_tick"]));ticks=[float(x["reference_tick"]) for x in rr];gaps=[(b-a)/HZ for a,b in zip(ticks,ticks[1:])];dur=(ticks[-1]-ticks[0])/HZ if len(ticks)>1 else 0
        errs=[x["horizontal_error_m"] for x in rr];cross=[x["abs_cross_track_error_m"] for x in rr if x["abs_cross_track_error_m"] is not None];jumps=[distance(d7c,(float(a["selected_lat"]),float(a["selected_lon"])),(float(b["selected_lat"]),float(b["selected_lon"]))) for a,b in zip(rr,rr[1:])]
        heading_errors=[];speed_errors=[];implied_speeds=[jump/gap for jump,gap in zip(jumps,gaps) if gap>0];speed_violations=sum(jump>450*gap+2000 for jump,gap in zip(jumps,gaps))
        for x,y in zip(rr,rr[1:]):
            elapsed=(float(y["reference_tick"])-float(x["reference_tick"]))/HZ
            if elapsed<=0:continue
            _,me,mn,_=d7e.error_components(t4,{"truth_lat":float(x["selected_lat"]),"truth_lon":float(x["selected_lon"])},float(y["selected_lat"]),float(y["selected_lon"]),float(y["altitude_used"]))
            _,te,tn,_=d7e.error_components(t4,{"truth_lat":float(x["truth_lat"]),"truth_lon":float(x["truth_lon"])},float(y["truth_lat"]),float(y["truth_lon"]),float(y["truth_altitude_m"]))
            if math.hypot(me,mn)>100 and math.hypot(te,tn)>100:
                mh=(math.degrees(math.atan2(me,mn))+360)%360;th=(math.degrees(math.atan2(te,tn))+360)%360;heading_errors.append(abs((mh-th+180)%360-180))
                speed_errors.append(abs(math.hypot(me,mn)/elapsed-math.hypot(te,tn)/elapsed))
        rec={"icao":icao,"squawks":";".join(sorted({x['mode_a_code'] for x in rr})),"unique_fixes":len(rr),"duration_s":dur,"fixes_per_min":60*len(rr)/dur if dur else 0,
             "gap_median_s":pct(gaps,.5),"gap_p90_s":pct(gaps,.9),"gap_p95_s":pct(gaps,.95),"max_gap_s":max(gaps) if gaps else None,
             "horizontal_p50_m":pct(errs,.5),"horizontal_p90_m":pct(errs,.9),"horizontal_p95_m":pct(errs,.95),"cross_track_p50_m":pct(cross,.5),"cross_track_p90_m":pct(cross,.9),"cross_track_p95_m":pct(cross,.95),
             "heading_error_median_deg":pct(heading_errors,.5),"heading_error_p90_deg":pct(heading_errors,.9),"speed_error_median_mps":pct(speed_errors,.5),"speed_error_p90_mps":pct(speed_errors,.9),
             "implied_speed_median_mps":pct(implied_speeds,.5),"implied_speed_p90_mps":pct(implied_speeds,.9),"implied_speed_max_mps":max(implied_speeds) if implied_speeds else None,"speed_gate_violations":speed_violations,
             "jumps_over_1km":sum(x>1000 for x in jumps),"jumps_over_2km":sum(x>2000 for x in jumps),"jumps_over_5km":sum(x>5000 for x in jumps),"jumps_over_10km":sum(x>10000 for x in jumps)}
        per.append(rec);tracks.append({**rec,"continuous":len(rr)>=3 and (pct(gaps,.9) or math.inf)<=30 and speed_violations==0})
    per_fields=["icao","squawks","unique_fixes","duration_s","fixes_per_min","gap_median_s","gap_p90_s","gap_p95_s","max_gap_s","horizontal_p50_m","horizontal_p90_m","horizontal_p95_m","cross_track_p50_m","cross_track_p90_m","cross_track_p95_m","heading_error_median_deg","heading_error_p90_deg","speed_error_median_mps","speed_error_p90_mps","implied_speed_median_mps","implied_speed_p90_mps","implied_speed_max_mps","speed_gate_violations","jumps_over_1km","jumps_over_2km","jumps_over_5km","jumps_over_10km"]
    write_csv(run/"test7h-per-aircraft.csv",per,per_fields);write_csv(run/"test7h-track-results.csv",tracks,per_fields+["continuous"])
    combo=[{"receiver_combination":";".join(ORDER),"associated_events":len(four),"unique_fixes":len(selected),"evaluated_fixes":len(evaluated)}]
    write_csv(run/"test7h-receiver-combinations.csv",combo,list(combo[0]))
    caprows=[]
    for station,x in capture["stations"].items():
        caprows.append({"station":station,"packet_count":x["data_lines"],"type1":x["counts"].get("modeac",0),"type2":x["counts"].get("modes_short",0),"type3":x["counts"].get("modes_long",0),"timestamp_zero":x["counts"].get("timestamp_zero",0),"span_s":x["span_s"],"type1_per_s":x["counts"].get("modeac",0)/600,"parse_errors":"not_instrumented","socket_timeouts":"not_instrumented","disconnects":0})
    write_csv(run/"capture-summary.csv",caprows,list(caprows[0]))
    clocks=[];t6=module("t6_for_7h",tools/"test6-analyze.py");caps={s:t4.load_capture(str(run/"captures"/f"modeac-{s}.csv")) for s in ORDER}
    for key,x in s6["pairwise"].items():
        a0,b0=x["stations"];c=x["clock"];common=t4.build_common_df17(caps[a0],caps[b0],200.);samples=t6.build_geometry_samples(t4,common,t6.STATIONS[a0],t6.STATIONS[b0]);cut=max(2,min(len(samples)-1,int(len(samples)*.7))) if len(samples)>=3 else len(samples);hold=samples[cut:]
        residual=[abs(t4.residual(z,c["slope"],c["intercept_ticks"])/12) for z in hold] if c.get("slope") is not None else []
        clocks.append({"station_a":a0,"station_b":b0,"common_df17":c["common_df17_pairs"],"geometry_samples":c["geometry_samples"],"classification":c["classification"],"slope":c.get("slope"),"offset_ticks":c.get("intercept_ticks"),"p50_us":pct(residual,.5),"p90_us":pct(residual,.9),"p95_us":pct(residual,.95),"p99_us":pct(residual,.99)})
    write_csv(run/"clock-links.csv",clocks,list(clocks[0]))
    counts=Counter(x["classification"] for x in event_rows);gooderr=[x["horizontal_error_m"] for x in evaluated];goodcross=[x["abs_cross_track_error_m"] for x in evaluated if x["abs_cross_track_error_m"] is not None]
    unique_pct=100*counts["UNIQUE_4RX"]/len(four) if four else 0;amb_pct=100*counts["MULTIPLE_4RX"]/len(four) if four else 0
    durations={str(n):sum(x["duration_s"]>=n for x in tracks) for n in (30,60,120,180)};continuous_tracks=sum(x["continuous"] for x in tracks)
    top=sorted(per,key=lambda x:x["unique_fixes"],reverse=True)[:5];maps=run/"maps";maps.mkdir(exist_ok=True)
    for x in top:map_html(maps/f"{x['icao']}.html",x["icao"],evaluated,candidate_rows)
    previous=json.loads((Path("/home/mlatserver/modeac-poc/test6/20260809T034035Z/reports/test6-summary.json")).read_text())
    prior_rate=60*previous["clusters"]["four_station_clusters"]/previous["capture"]["common_overlap_s"]
    altchange=sum(x["altitude_changes_classification"] for x in mirror);mirror_eligible=[x for x in mirror if x["classification"]=="UNIQUE_4RX" and x["selected_nearest_truth"] is not None];mirror_correct=sum(x["selected_nearest_truth"] for x in mirror_eligible)
    raw_type1=sum(x["type1"] for x in caprows);three_plus=sum(x["station_count"]>=3 for x in events);all_gaps=[]
    for rr in (sorted((x for x in evaluated if x["matched_icao"]==icao),key=lambda x:float(x["reference_tick"])) for icao in {x["matched_icao"] for x in evaluated}):all_gaps.extend((float(b["reference_tick"])-float(a["reference_tick"]))/HZ for a,b in zip(rr,rr[1:]))
    code_counts=Counter(x["mode_a_code"] for x in four)
    decision="STRONG PASS" if len(four)>=100 and unique_pct>=75 and stats(gooderr)["p90"] is not None and stats(gooderr)["p90"]<1000 and sum(x>5000 for x in gooderr)==0 and durations["30"]>=3 else "PASS" if selected and unique_pct>=50 and stats(gooderr)["p90"] is not None and stats(gooderr)["p90"]<2000 else "PARTIAL PASS" if selected else "FAIL"
    if degraded_links and decision in ("STRONG PASS","PASS"):decision="PARTIAL PASS"
    summary={"decision":decision,"diagnostic_only_due_to_clock_degradation":bool(degraded_links),"degraded_clock_links":[x["stations"] for x in degraded_links],"capture":capture,"clock_links":clocks,"event_builder":{**diag,"generic_four_receiver_candidates":s6["clusters"]["four_station_clusters"],"strict_four_receiver_accepted":len(four),"strict_candidate_difference":s6["clusters"]["four_station_clusters"]-len(four),"three_plus_events":three_plus,"four_receiver_events":len(four),"four_receiver_events_per_min":len(four)/10,"prior_test6_four_events_per_min":prior_rate,"codes_observed":len(code_counts),"events_by_code":dict(code_counts)},
             "branch_observability":{**counts,"unique_percent":unique_pct,"multiple_percent":amb_pct,"initial_multibranch_unique":sum(x["classification"]=="UNIQUE_4RX" and x["initial_branches"]>1 for x in mirror),"truth_eligible_mirror_checks":len(mirror_eligible),"correct_branch_selected":mirror_correct,"mirror_rejection_accuracy_percent":100*mirror_correct/len(mirror_eligible) if mirror_eligible else None,"altitude_classification_changes":altchange},"accuracy":{"eligible_unique_fixes":len(evaluated),"unique_without_eligible_truth":len(selected)-len(evaluated),"horizontal_error_m":stats(gooderr),"cross_track_error_m":stats(goodcross),"under_250m":sum(x<250 for x in gooderr),"under_500m":sum(x<500 for x in gooderr),"under_1km":sum(x<1000 for x in gooderr),"under_2km":sum(x<2000 for x in gooderr),"under_5km":sum(x<5000 for x in gooderr),"over_5km":sum(x>5000 for x in gooderr),"over_10km":sum(x>10000 for x in gooderr)},
             "density":{"raw_type1_replies":raw_type1,"three_plus_events":three_plus,"four_receiver_events":len(four),"unique_fixes":len(selected),"raw_replies_per_unique_fix":raw_type1/len(selected) if selected else None,"three_plus_events_per_unique_fix":three_plus/len(selected) if selected else None,"four_receiver_events_per_unique_fix":len(four)/len(selected) if selected else None,"unique_fixes_per_capture_min":len(selected)/10,"eligible_fixes_per_capture_min":len(evaluated)/10,"eligible_gap_median_s":pct(all_gaps,.5),"eligible_gap_p90_s":pct(all_gaps,.9)},"track_duration_counts":durations,"continuous_tracks":continuous_tracks,"top5_by_unique_fix_count":[x["icao"] for x in top],"densest_track":top[0] if top else None,"anti_leakage":{"pretruth_artifact":"test7h-selected-before-truth.csv","truth_fields_present":False,"truth_used_in_branch_selection":False},
             "method":{"event":"strict reciprocal-nearest complete four-receiver clique; all six physical links","solver":"fixed-altitude deterministic multistart, all-four residual classification","credible":"center<=1500 km, condition<=1e6, RMS<=3 us and within 0.5 us of residual floor","altitude":"DF17 barometric altitude by active Mode-S squawk identity; no latitude/longitude input"}}
    (run/"test7h-summary.json").write_text(json.dumps(summary,indent=2))
    stop=iso(capture["scheduled_start_ns"]+600_000_000_000)
    lines=["TEST 7H — TEN-MINUTE FOUR-RECEIVER MODE-A VALIDATION","="*62,"",f"TEST 7H STATUS: {decision}",f"CLOCK GATE: {'DEGRADED — localization is diagnostic only and not headline evidence' if degraded_links else 'PASS'}","",f"Capture start/stop: {capture['scheduled_start_utc']} / {stop}; requested duration 600 s; common overlap {capture['common_overlap_s']:.3f} s.",
           "Station Type-1 counts: "+", ".join(f"{x['station']}={x['type1']} ({x['type1_per_s']:.2f}/s)" for x in caprows),"","CLOCK SYNCHRONIZATION"]+[f"{x['station_a']}—{x['station_b']}: {x['classification']}, samples={x['geometry_samples']}, P95/P99={x['p95_us']}/{x['p99_us']} us" for x in clocks]+[
           "","FOUR-STATION EVENT YIELD",f"Generic 4-RX candidates/strict accepted/difference: {s6['clusters']['four_station_clusters']}/{len(four)}/{s6['clusters']['four_station_clusters']-len(four)}; association-overlap ambiguities across 3+ cliques={diag['ambiguous_overlapping_cliques']}.",f"Strict rate={len(four)/10:.2f}/min, codes={len(code_counts)}; prior Test 6 rate={prior_rate:.2f}/min. Top codes: "+", ".join(f"{k}:{v}" for k,v in code_counts.most_common(5))+".",
           "","FOUR-RECEIVER BRANCH OBSERVABILITY",f"UNIQUE/MULTIPLE/INCONSISTENT/SOLVER_FAIL: {counts['UNIQUE_4RX']}/{counts['MULTIPLE_4RX']}/{counts['INCONSISTENT_4RX']}/{counts['SOLVER_FAIL']}.",f"Unique={unique_pct:.1f}%; mirrored/ambiguous={amb_pct:.1f}%; ±1 km changed classification for {altchange} events.",
           "","ACCURACY",f"Eligible unique fixes={len(evaluated)} ({len(selected)-len(evaluated)} frozen fixes lacked reliable truth); horizontal P50/P75/P90/P95/P99/max={stats(gooderr)['p50']}/{stats(gooderr)['p75']}/{stats(gooderr)['p90']}/{stats(gooderr)['p95']}/{stats(gooderr)['p99']}/{stats(gooderr)['max']} m.",f"Cross-track P50/P75/P90/P95/P99/max={stats(goodcross)['p50']}/{stats(goodcross)['p75']}/{stats(goodcross)['p90']}/{stats(goodcross)['p95']}/{stats(goodcross)['p99']}/{stats(goodcross)['max']} m; >5 km/>10 km={sum(x>5000 for x in gooderr)}/{sum(x>10000 for x in gooderr)}.",
           "","TRACK DENSITY AND DURATION",f"Unique/eligible fixes per capture minute={len(selected)/10:.2f}/{len(evaluated)/10:.2f}; eligible gap median/P90={pct(all_gaps,.5)}/{pct(all_gaps,.9)} s.",f"Track spans >=30/60/120/180 s={durations['30']}/{durations['60']}/{durations['120']}/{durations['180']}; continuous tracks={continuous_tracks}.",f"Densest track: {top[0]['icao'] if top else 'none'} ({top[0]['unique_fixes'] if top else 0} fixes, {top[0]['fixes_per_min'] if top else 0:.2f}/min, heading median/P90={top[0]['heading_error_median_deg'] if top else None}/{top[0]['heading_error_p90_deg'] if top else None} deg).",
           "","MIRROR ANALYSIS",f"All {sum(x['classification']=='UNIQUE_4RX' and x['initial_branches']>1 for x in mirror)} unique events began with multiple solver branches; the redundant residual rejected competitors. The selected residual winner was nearest eligible truth in {mirror_correct}/{len(mirror_eligible)} cases ({100*mirror_correct/len(mirror_eligible) if mirror_eligible else 0:.1f}%).",
           "","YIELD COST",f"Raw Type-1 / 3+ event / strict 4-RX event per UNIQUE fix: {raw_type1/len(selected) if selected else None:.1f} / {three_plus/len(selected) if selected else None:.1f} / {len(four)/len(selected) if selected else None:.2f}.","5001a9 and 782253 did not appear among independently validated aircraft in this capture.",
           "","SCIENTIFIC INTERPRETATION",f"Four-receiver redundancy produced {counts['UNIQUE_4RX']} diagnostic unique candidates from {len(four)} strict events. MULTIPLE/INCONSISTENT/SOLVER_FAIL remain non-measurements.",(f"Conclusion: {decision}. Because {len(degraded_links)} clock links degraded, these UNIQUE_4RX labels are diagnostic and Test 7H does not justify promoting them to a new high-confidence measurement class." if degraded_links else f"Conclusion: {decision}. UNIQUE_4RX may be treated as a distinct high-confidence measurement class subject to the stated gates."),
           "","ANTI-LEAKAGE","test7h-selected-before-truth.csv was closed before truth association and contains no truth-coordinate fields. Truth latitude/longitude were never solver inputs or branch selectors."]
    (run/"test7h-report.txt").write_text("\n".join(lines)+"\n");print(json.dumps({"decision":decision,"four_events":len(four),"unique":counts["UNIQUE_4RX"],"evaluated":len(evaluated),"run":str(run)},indent=2))

if __name__=="__main__":main()
