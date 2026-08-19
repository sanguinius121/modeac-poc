"""Reusable Phase Tool-1 grid, coverage, and four-receiver geometry engine."""
import hashlib,itertools,math,time
from collections import Counter
import numpy as np
from scipy.spatial import Delaunay,cKDTree
from scipy.spatial import QhullError
import geometry_core as core
from .coverage import ground_distance_km
from ..reception import provider_for,outline_store

MAX_GRID_POINTS=25_000
MC_DRAWS=256
MC_SEED=20260811
QUALITY_CLASSES=("GOOD","ACCEPTABLE","POOR","VERY_POOR","NO_MLAT")
THRESHOLDS={
    "GOOD":"P95 <= 500 m, condition <= 10, remote branch separation >= 1.0 us",
    "ACCEPTABLE":"P95 <= 1500 m, condition <= 30, separation >= 0.5 us",
    "POOR":"P95 <= 5000 m, condition <= 100, separation >= 0.2 us",
    "VERY_POOR":"Otherwise when all four selected receivers are in range",
    "NO_MLAT":"One or more selected geometry receivers are out of simulated range",
}


def projection(polygon):
    lat0=float(np.mean([x[0] for x in polygon]));lon0=float(np.mean([x[1] for x in polygon]));km_lat=111.132;km_lon=111.320*math.cos(math.radians(lat0))
    return lat0,lon0,km_lat,km_lon


def to_xy(lat,lon,proj):lat0,lon0,km_lat,km_lon=proj;return np.array(((lon-lon0)*km_lon,(lat-lat0)*km_lat))
def to_ll(x,y,proj):lat0,lon0,km_lat,km_lon=proj;return lat0+y/km_lat,lon0+x/km_lon


def point_in_polygon(x,y,vertices):
    inside=False;j=len(vertices)-1
    for i in range(len(vertices)):
        xi,yi=vertices[i];xj,yj=vertices[j]
        if (yi>y)!=(yj>y) and x<(xj-xi)*(y-yi)/(yj-yi)+xi:inside=not inside
        j=i
    return inside


def surveillance_grid(polygon,step_km):
    proj=projection(polygon);vertices=np.asarray([to_xy(*x,proj) for x in polygon]);xmin,ymin=vertices.min(axis=0);xmax,ymax=vertices.max(axis=0)
    xs=np.arange(math.floor(xmin/step_km)*step_km,math.ceil(xmax/step_km)*step_km+.001,step_km);ys=np.arange(math.floor(ymin/step_km)*step_km,math.ceil(ymax/step_km)*step_km+.001,step_km)
    points=[]
    for y in ys:
        for x in xs:
            if point_in_polygon(x,y,vertices):points.append((*to_ll(x,y,proj),float(x),float(y)))
    if not points:raise ValueError("Surveillance grid is empty")
    if len(points)>MAX_GRID_POINTS:raise ValueError(f"Analysis has {len(points)} grid points; maximum is {MAX_GRID_POINTS}")
    area=abs(sum(vertices[i,0]*vertices[(i+1)%len(vertices),1]-vertices[(i+1)%len(vertices),0]*vertices[i,1] for i in range(len(vertices)))/2)
    span=max(ground_distance_km(*a,*b) for a,b in itertools.combinations(polygon,2))
    return points,{"area_km2":area,"bounding_box":{"south":min(x[0] for x in polygon),"north":max(x[0] for x in polygon),"west":min(x[1] for x in polygon),"east":max(x[1] for x in polygon)},"maximum_span_km":span}


def receiver_stations(receivers):return {r.id:(r.lat,r.lon,r.altitude_m) for r in receivers}


def collinear(receivers):
    proj=projection([(r.lat,r.lon) for r in receivers]);xy=np.asarray([to_xy(r.lat,r.lon,proj) for r in receivers]);return np.linalg.matrix_rank(xy-xy.mean(axis=0))<2


def fast_branch_separation(points,signatures,min_distance_km=25.0):
    n=len(points)
    if n<2:return np.full(n,np.inf)
    tree=cKDTree(signatures);k=min(n,96);dist,index=tree.query(signatures,k=k)
    if k==1:dist,index=dist[:,None],index[:,None]
    result=np.full(n,np.inf);dim=signatures.shape[1]
    for i in range(n):
        for d,j in zip(dist[i],index[i]):
            if i==j:continue
            if ground_distance_km(points[i][0],points[i][1],points[j][0],points[j][1])>=min_distance_km:
                result[i]=float(d)/math.sqrt(dim);break
        if not math.isfinite(result[i]):
            delta=signatures-signatures[i];rms=np.sqrt(np.mean(delta*delta,axis=1));rms[[ground_distance_km(points[i][0],points[i][1],p[0],p[1])<min_distance_km for p in points]]=np.inf;result[i]=float(np.min(rms))
    return result


def quality_class(p95,condition,separation):return core.classify(p95,condition,separation).replace(" ","_")


def percentile(values,q):return float(np.percentile(np.asarray(values,float),q)) if values else None


def analyze_strict(request):
    started=time.perf_counter();grid,area=surveillance_grid(request.surveillance_polygon,request.grid_step_km);by_id={r.id:r for r in request.receivers};selected=[by_id[x] for x in request.geometry_receiver_ids];stations=receiver_stations(selected);enabled=[r for r in request.receivers if r.enabled and r.id!=request.failed_receiver_id]
    for r in request.receivers:
        if r.reception_model=="outline":
            try:outline_store.public(r.outline_id,False)
            except ValueError as exc:raise ValueError(f"Receiver {r.name}: {exc}")
    rng=np.random.default_rng(MC_SEED);draws=rng.normal(size=(4,MC_DRAWS));linear=collinear(selected)
    all_points=[(x[0],x[1]) for x in grid];signatures=np.asarray([core.tdoa_signature(lat,lon,request.target_altitude_m,stations) for lat,lon in all_points]);separations=np.zeros(len(grid)) if linear else fast_branch_separation(all_points,signatures)
    prepared={};cache={}
    for r in enabled:
        key=(r.reception_model,r.outline_id) if r.reception_model=="outline" else (r.reception_model,r.id)
        if key not in cache:cache[key]=provider_for(r).prepare(r,all_points,request.target_altitude_m)
        prepared[r.id]=cache[key]
    hull=None
    if not linear:
        try:hull=Delaunay(np.asarray([(r.lon,r.lat) for r in selected]))
        except QhullError:linear=True;separations=np.zeros(len(grid))
    results=[];counts=Counter();conditions=[];p50_errors=[];errors=[];contribution=Counter()
    for i,(lat,lon,_,_) in enumerate(grid):
        reception_rows=[];in_range=[]
        for r in enabled:
            ok,detail=prepared[r.id][i]
            if ok:in_range.append(r.id);contribution[r.id]+=1
            reception_rows.append({"id":r.id,"name":r.name,"reception_model":r.reception_model,"in_range":ok,"geometry_selected":r.id in request.geometry_receiver_ids,**detail})
        selected_ok=all(r.id in in_range for r in selected)
        unavailable=[r.name for r in selected if r.id not in in_range]
        row={"lat":lat,"lon":lon,"receiver_count":len(in_range),"receivers":[by_id[x].name for x in in_range],"geometry_receivers":[r.name for r in selected],"reception":reception_rows,"target_altitude_m":request.target_altitude_m,"strict_subset_message":None if selected_ok else f"{len(in_range)} enabled receiver(s) observe this point, but selected strict-4 has unavailable: {', '.join(unavailable)}. Phase Tool-2 does not substitute another receiver."}
        if not selected_ok:
            row.update(condition=None,predicted_p50_error_m=None,predicted_p95_error_m=None,inside_hull=False,branch_safe=False,branch_separation_us=None,quality="NO_MLAT")
        else:
            metric=core.geometry_metrics(lat,lon,request.target_altitude_m,stations,request.timing_noise_us,draws);condition=metric["condition"];p50=metric["mc_p50_m"];p95=metric["mc_p95_m"];sep=float(separations[i]);inside=bool(hull.find_simplex(np.asarray([[lon,lat]]))[0]>=0) if hull is not None else False
            measurable=math.isfinite(condition) and math.isfinite(p95) and math.isfinite(sep);q=quality_class(p95,condition,sep) if measurable else "VERY_POOR"
            row.update(condition=condition if math.isfinite(condition) else None,predicted_p50_error_m=p50 if math.isfinite(p50) else None,predicted_p95_error_m=p95 if math.isfinite(p95) else None,inside_hull=inside,branch_safe=bool(measurable and sep>=.5 and not linear),branch_separation_us=sep if math.isfinite(sep) else None,quality=q)
            if math.isfinite(condition):conditions.append(condition)
            if math.isfinite(p50):p50_errors.append(p50)
            if math.isfinite(p95):errors.append(p95)
        counts[row["quality"]]+=1;results.append(row)
    total=len(results);available=total-counts["NO_MLAT"]
    source_counts=Counter(r.reception_model for r in enabled)
    summary={"grid_points":total,"mlat_available_points":available,"at_least_1_rx_percent":100*sum(x["receiver_count"]>=1 for x in results)/total,"at_least_2_rx_percent":100*sum(x["receiver_count"]>=2 for x in results)/total,"at_least_3_rx_percent":100*sum(x["receiver_count"]>=3 for x in results)/total,"four_plus_rx_coverage_percent":100*sum(x["receiver_count"]>=4 for x in results)/total,"selected_strict_4_common_coverage_percent":100*available/total,"good_percent":100*counts["GOOD"]/total,"good_acceptable_percent":100*(counts["GOOD"]+counts["ACCEPTABLE"])/total,"poor_percent":100*counts["POOR"]/total,"very_poor_percent":100*counts["VERY_POOR"]/total,"no_mlat_percent":100*counts["NO_MLAT"]/total,"quality_counts":{x:counts[x] for x in QUALITY_CLASSES},"median_predicted_p50_m":percentile(p50_errors,50),"median_predicted_p95_m":percentile(errors,50),"p90_predicted_p95_m":percentile(errors,90),"median_condition":percentile(conditions,50),"p90_condition":percentile(conditions,90),"branch_safe_percent":100*sum(x["branch_safe"] for x in results)/total,"branch_good_percent":100*sum((x["branch_separation_us"] or -math.inf)>=1.0 for x in results)/total,"inside_hull_percent":100*sum(x["inside_hull"] for x in results)/total,"analysis_seconds":time.perf_counter()-started,"area":area,"geometry_receiver_ids":list(request.geometry_receiver_ids),"reception_source_counts":{"simulated":source_counts["simulated"],"outline":source_counts["outline"]},"receiver_contribution":[{"id":r.id,"name":r.name,"reception_model":r.reception_model,"coverage_percent":100*contribution[r.id]/total,"range_km":r.max_range_km,"altitude_m":r.altitude_m,"enabled":r.enabled,"outline_metadata":outline_store.receiver_metadata(r) if r.reception_model=="outline" else None} for r in request.receivers]}
    summary["geometry_strategy"]="strict_4";summary["subset_evaluations"]=available
    return {"summary":summary,"grid":results,"quality_thresholds":THRESHOLDS,"semantics":{"simulated_reception":"horizontal great-circle ground distance","outline_reception":"observed horizontal readsb actualRange.last24h footprint; target altitude does not scale it","subset":"Exactly the four user-selected geometry receivers; no automatic 4-of-N substitution","monte_carlo_draws":MC_DRAWS,"monte_carlo_seed":MC_SEED}}


def _prepared_reception(request,enabled,points):
    for r in enabled:
        if r.reception_model=="outline":
            try:outline_store.public(r.outline_id,False)
            except ValueError as exc:raise ValueError(f"Receiver {r.name}: {exc}")
    prepared={};cache={}
    for r in enabled:
        key=(r.reception_model,r.outline_id) if r.reception_model=="outline" else (r.reception_model,r.id)
        if key not in cache:cache[key]=provider_for(r).prepare(r,points,request.target_altitude_m)
        prepared[r.id]=cache[key]
    return prepared


def _subset_diagnostic(receivers,points,altitude):
    stations=receiver_stations(receivers);linear=collinear(receivers);signatures=np.asarray([core.tdoa_signature(lat,lon,altitude,stations) for lat,lon in points]);separation=np.zeros(len(points)) if linear else fast_branch_separation(points,signatures);hull=None
    if not linear:
        try:hull=Delaunay(np.asarray([(r.lon,r.lat) for r in receivers]))
        except QhullError:linear=True;separation=np.zeros(len(points))
    return {"receivers":receivers,"ids":tuple(r.id for r in receivers),"names":tuple(r.name for r in receivers),"stations":stations,"linear":linear,"separation":separation,"hull":hull}


def _metric(sd,index,lat,lon,request,draws_by_id):
    draws=np.vstack([draws_by_id[x] for x in sd["ids"]]);m=core.geometry_metrics(lat,lon,request.target_altitude_m,sd["stations"],request.timing_noise_us,draws);condition=m["condition"];p50=m["mc_p50_m"];p95=m["mc_p95_m"];sep=float(sd["separation"][index]);inside=bool(sd["hull"].find_simplex(np.asarray([[lon,lat]]))[0]>=0) if sd["hull"] is not None else False;measurable=math.isfinite(condition) and math.isfinite(p95) and math.isfinite(sep);safe=bool(measurable and sep>=.5 and not sd["linear"]);quality=quality_class(p95,condition,sep) if measurable else "VERY_POOR"
    return {"subset_ids":list(sd["ids"]),"subset_names":list(sd["names"]),"p50_error_m":p50 if math.isfinite(p50) else None,"p95_error_m":p95 if math.isfinite(p95) else None,"condition":condition if math.isfinite(condition) else None,"inside_hull":inside,"branch_safe":safe,"branch_separation_us":sep if math.isfinite(sep) else None,"quality":quality}


def _best_key(x):return (0 if x["branch_safe"] else 1,x["p95_error_m"] if x["p95_error_m"] is not None else math.inf,x["condition"] if x["condition"] is not None else math.inf,0 if x["inside_hull"] else 1,tuple(x["subset_ids"]))
def _worst_key(x):return (1 if not x["branch_safe"] else 0,x["p95_error_m"] if x["p95_error_m"] is not None else math.inf,x["condition"] if x["condition"] is not None else math.inf,1 if not x["inside_hull"] else 0,tuple(x["subset_ids"]))


def _receiver_draws(receiver_id):
    """Stable common-random-number stream, unaffected by adding another site."""
    digest=hashlib.sha256(f"{MC_SEED}:{receiver_id}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8],"big")).normal(size=MC_DRAWS)


def analyze_4ofn(request,include_details=False,only_point=None):
    started=time.perf_counter();grid,area=surveillance_grid(request.surveillance_polygon,request.grid_step_km);by_id={r.id:r for r in request.receivers};enabled=sorted((r for r in request.receivers if r.enabled and r.id!=request.failed_receiver_id),key=lambda r:r.id);n=len(enabled);max_subsets=math.comb(n,4) if n>=4 else 0
    if max_subsets>1000:raise ValueError(f"C({n},4)={max_subsets} exceeds hard limit 1000")
    if max_subsets>70 and not request.allow_high_subset_count:raise ValueError(f"{n} enabled receivers can generate up to C({n},4)={max_subsets} subsets per grid point; confirm allow_high_subset_count to continue")
    points=[(x[0],x[1]) for x in grid];prepared=_prepared_reception(request,enabled,points);all_subsets=[]
    for combo in itertools.combinations(enabled,4):all_subsets.append(_subset_diagnostic(combo,points,request.target_altitude_m))
    draws_by_id={r.id:_receiver_draws(r.id) for r in enabled};results=[];counts=Counter();best_errors=[];worst_errors=[];best_conditions=[];worst_conditions=[];subset_evals=0;importance={r.id:[] for r in enabled};contribution=Counter()
    for i,(lat,lon,_,_) in enumerate(grid):
        reception_rows=[];available=[]
        for r in enabled:
            ok,detail=prepared[r.id][i]
            if ok:available.append(r.id);contribution[r.id]+=1
            reception_rows.append({"id":r.id,"name":r.name,"reception_model":r.reception_model,"in_range":ok,**detail})
        aset=set(available);valid=[sd for sd in all_subsets if set(sd["ids"])<=aset];metrics=[_metric(sd,i,lat,lon,request,draws_by_id) for sd in valid];subset_evals+=len(metrics)
        row={"lat":lat,"lon":lon,"receiver_count":len(available),"available_receiver_count":len(available),"available_receiver_ids":available,"receivers":[by_id[x].name for x in available],"reception":reception_rows,"target_altitude_m":request.target_altitude_m,"subset_count":len(metrics),"failed_receiver_id":request.failed_receiver_id or None}
        if not metrics:
            row.update(condition=None,predicted_p50_error_m=None,predicted_p95_error_m=None,inside_hull=False,branch_safe=False,branch_separation_us=None,quality="NO_MLAT",best_subset=None,worst_subset=None,best_p50_error_m=None,best_p95_error_m=None,worst_p50_error_m=None,worst_p95_error_m=None,best_condition=None,worst_condition=None,best_branch_safe=False,best_branch_separation_us=None,best_inside_hull=False,best_quality="NO_MLAT",worst_quality="NO_MLAT",good_subset_count=0,acceptable_subset_count=0,poor_subset_count=0,very_poor_subset_count=0,good_subset_fraction=0,n_minus_1_survivable=False,full_n_condition=None,full_n_predicted_p50_m=None,full_n_predicted_p95_m=None,receiver_importance={})
        else:
            ranked=sorted(metrics,key=_best_key);best=ranked[0];worst=max(metrics,key=_worst_key);qc=Counter(x["quality"] for x in metrics);nminus=len(available)>=5 and all(any(x["quality"]=="GOOD" and lost not in x["subset_ids"] for x in metrics) for lost in available);chosen=worst if request.geometry_strategy=="worst_4_of_n" else best
            full_condition=full_p50=full_p95=None
            if len(available)>=5:
                full_receivers=[by_id[x] for x in available];stations=receiver_stations(full_receivers);draws=np.vstack([draws_by_id[x] for x in available]);fm=core.geometry_metrics(lat,lon,request.target_altitude_m,stations,request.timing_noise_us,draws);full_condition=fm["condition"] if math.isfinite(fm["condition"]) else None;full_p50=fm["mc_p50_m"] if math.isfinite(fm["mc_p50_m"]) else None;full_p95=fm["mc_p95_m"] if math.isfinite(fm["mc_p95_m"]) else None
            impact={}
            for rid in available:
                alternatives=[x for x in metrics if rid not in x["subset_ids"]]
                alternative=min(alternatives,key=_best_key) if alternatives else None
                ratio=None if alternative is None or alternative["p95_error_m"] is None or not best["p95_error_m"] else alternative["p95_error_m"]/best["p95_error_m"]
                impact[rid]=ratio
                if ratio is not None and math.isfinite(ratio):importance[rid].append(ratio)
            row.update(condition=chosen["condition"],predicted_p50_error_m=chosen["p50_error_m"],predicted_p95_error_m=chosen["p95_error_m"],inside_hull=chosen["inside_hull"],branch_safe=chosen["branch_safe"],branch_separation_us=chosen["branch_separation_us"],quality=chosen["quality"],best_subset=best["subset_ids"],best_subset_names=best["subset_names"],worst_subset=worst["subset_ids"],worst_subset_names=worst["subset_names"],best_p50_error_m=best["p50_error_m"],best_p95_error_m=best["p95_error_m"],worst_p50_error_m=worst["p50_error_m"],worst_p95_error_m=worst["p95_error_m"],best_condition=best["condition"],worst_condition=worst["condition"],best_branch_safe=best["branch_safe"],best_branch_separation_us=best["branch_separation_us"],best_inside_hull=best["inside_hull"],best_quality=best["quality"],worst_quality=worst["quality"],good_subset_count=qc["GOOD"],acceptable_subset_count=qc["ACCEPTABLE"],poor_subset_count=qc["POOR"],very_poor_subset_count=qc["VERY_POOR"],good_subset_fraction=qc["GOOD"]/len(metrics),n_minus_1_survivable=bool(nminus),full_n_condition=full_condition,full_n_predicted_p50_m=full_p50,full_n_predicted_p95_m=full_p95,receiver_importance=impact)
            if best["p95_error_m"] is not None:best_errors.append(best["p95_error_m"])
            if worst["p95_error_m"] is not None:worst_errors.append(worst["p95_error_m"])
            if best["condition"] is not None:best_conditions.append(best["condition"])
            if worst["condition"] is not None:worst_conditions.append(worst["condition"])
            if include_details:row["subsets"]=ranked
        counts[row["quality"]]+=1;results.append(row)
    total=len(results);best_p50s=[x["best_p50_error_m"] for x in results if x.get("best_p50_error_m") is not None];good_fractions=[x["good_subset_fraction"] for x in results if x.get("subset_count",0)>0];summary={"geometry_strategy":request.geometry_strategy,"grid_points":total,"subset_evaluations":subset_evals,"maximum_subsets_per_point":max_subsets,"four_plus_rx_coverage_percent":100*sum(x["receiver_count"]>=4 for x in results)/total,"five_plus_rx_coverage_percent":100*sum(x["receiver_count"]>=5 for x in results)/total,"six_plus_rx_coverage_percent":100*sum(x["receiver_count"]>=6 for x in results)/total,"good_percent":100*sum(x["best_quality"]=="GOOD" for x in results)/total,"good_acceptable_percent":100*sum(x["best_quality"] in ("GOOD","ACCEPTABLE") for x in results)/total,"worst_good_percent":100*sum(x["worst_quality"]=="GOOD" for x in results)/total,"no_mlat_percent":100*sum(x["subset_count"]==0 for x in results)/total,"n_minus_1_survivable_percent":100*sum(x["n_minus_1_survivable"] for x in results)/total,"one_good_subset_percent":100*sum(x["good_subset_count"]>=1 for x in results)/total,"robust_good_fraction_percent":100*sum(x["good_subset_count"]>=2 for x in results)/total,"three_good_subsets_percent":100*sum(x["good_subset_count"]>=3 for x in results)/total,"median_good_subset_fraction":percentile(good_fractions,50),"median_best_p50_m":percentile(best_p50s,50),"median_best_p95_m":percentile(best_errors,50),"p90_best_p95_m":percentile(best_errors,90),"median_worst_p95_m":percentile(worst_errors,50),"p90_worst_p95_m":percentile(worst_errors,90),"median_best_condition":percentile(best_conditions,50),"median_worst_condition":percentile(worst_conditions,50),"best_branch_safe_percent":100*sum(x.get("best_branch_safe",False) for x in results)/total,"best_branch_good_percent":100*sum((x.get("best_branch_separation_us") or -math.inf)>=1.0 for x in results)/total,"best_inside_hull_percent":100*sum(x.get("best_inside_hull",False) for x in results)/total,"analysis_seconds":time.perf_counter()-started,"area":area,"failed_receiver_id":request.failed_receiver_id or None,"reception_source_counts":{"simulated":sum(r.reception_model=="simulated" for r in enabled),"outline":sum(r.reception_model=="outline" for r in enabled)},"receiver_importance":[{"id":r.id,"name":r.name,"median_p95_ratio_without_receiver":percentile(importance[r.id],50),"p90_p95_ratio_without_receiver":percentile(importance[r.id],90),"samples":len(importance[r.id]),"sample_fraction_percent":100*len(importance[r.id])/total} for r in enabled]}
    return {"summary":summary,"grid":results,"quality_thresholds":THRESHOLDS,"ranking_policy":["branch-safe preferred","lowest predicted P95","lowest condition","inside subset hull preferred","lexical receiver IDs"],"semantics":{"primary":"best 4-of-N unless worst strategy selected; full-N is diagnostic only","n_minus_1":"for every currently available single receiver loss, at least one remaining GOOD 4RX subset","realtime_warning":"The operational realtime MLAT backend currently uses four fixed receivers; this is planning-only"}}


def analyze(request):
    return analyze_strict(request) if request.geometry_strategy=="strict_4" else analyze_4ofn(request)
