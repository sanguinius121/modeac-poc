"""Test 7I-compatible blind altitude-grid four-receiver localization."""
import importlib.util,itertools,math,statistics
from .config import ROOT,ORDER,ALTITUDE_GRID_FT

def _module(path):
    s=importlib.util.spec_from_file_location("realtime_test7c",path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
D7C=_module(ROOT/"tools/test7c-2d-solver.py")

def configure_solver_geometry(stations,order):
    """Point the validated Test 7C solver at one fixed four-receiver profile.

    This changes only the receiver geometry held by the imported solver module;
    the least-squares objective, starts, weighting and branch rules are unchanged.
    It is intended to run once, before worker pools or localizers are created.
    """
    order=tuple(order)
    if len(order)!=4 or len(set(order))!=4:
        raise ValueError("realtime strict solver requires exactly four unique receivers")
    missing=[name for name in order if name not in stations]
    if missing:
        raise ValueError("receiver geometry missing: "+", ".join(missing))
    D7C.STATIONS={name:(stations[name].lat,stations[name].lon,stations[name].alt_m) for name in order}
    D7C.ORDER=list(order)
    D7C.PAIRS=list(itertools.combinations(order,2))
    D7C.ORIGIN_LAT=statistics.mean(value[0] for value in D7C.STATIONS.values())
    D7C.ORIGIN_LON=statistics.mean(value[1] for value in D7C.STATIONS.values())
    D7C.R_LON=111_320.0*math.cos(math.radians(D7C.ORIGIN_LAT))
    D7C.RECEIVERS={name:D7C.geodetic_to_ecef(*value) for name,value in D7C.STATIONS.items()}
    D7C.STARTS=D7C.starts()
    return order

def horizontal(a,b):return D7C.horizontal_error(D7C.geodetic_to_ecef(a[0],a[1],0),D7C.geodetic_to_ecef(b[0],b[1],0))
def weighted(c,sigma):return math.sqrt(statistics.mean((c["residuals"][p]/sigma[p])**2 for p in itertools.combinations(ORDER,2)))

def families(candidates,radius_km):
    groups=[]
    valid=(x for x in candidates if x["center_km"]<=radius_km and math.isfinite(x["condition"]) and x["condition"]<=1e8)
    for candidate in sorted(valid,key=lambda x:x["weighted_rms"]):
        group=next((g for g in groups if horizontal((candidate["lat"],candidate["lon"]),(g[0]["lat"],g[0]["lon"]))<=25000),None)
        if group is None:groups.append([candidate])
        else:group.append(candidate)
    return [min(g,key=lambda x:(x["weighted_rms"],x["rms_us"],x["center_km"])) for g in groups]

class BlindLocalizer:
    def __init__(self,clock):self.clock=clock
    def solve(self,event):
        sigma={p:self.clock.sigma(*p) for p in itertools.combinations(ORDER,2)};allc=[]
        for feet in ALTITUDE_GRID_FT:
            alt=feet*.3048;_,cc,_=D7C.solve(alt,ORDER,event["tdoa"])
            for c in cc:
                if c["center_km"]<=3000 and math.isfinite(c["condition"]) and c["condition"]<=1e8:allc.append({**c,"altitude_m":alt,"weighted_rms":weighted(c,sigma)})
        reps=sorted(families(allc,1500),key=lambda x:x["weighted_rms"]);expanded=sorted(families(allc,3000),key=lambda x:x["weighted_rms"])
        if not reps:return {"classification":"BLIND_INCONSISTENT","candidate_count":0}
        best=reps[0];second=reps[1] if len(reps)>1 else None
        outside=any(x["weighted_rms"]-best["weighted_rms"]<.5 and horizontal((x["lat"],x["lon"]),(best["lat"],best["lon"]))>25000 for x in expanded)
        if best["weighted_rms"]>1.5:cl="BLIND_INCONSISTENT"
        elif (second and second["weighted_rms"]-best["weighted_rms"]<.5 and second["weighted_rms"]/max(best["weighted_rms"],1e-9)<1.5) or outside:cl="BLIND_MULTIPLE"
        else:cl="BLIND_UNIQUE"
        return {"classification":cl,"candidate_count":len(reps),"lat":best["lat"],"lon":best["lon"],"altitude_hypothesis_m":best["altitude_m"],"weighted_rms":best["weighted_rms"],"unweighted_rms_us":best["rms_us"],"condition":best["condition"],"second_weighted_rms":second["weighted_rms"] if second else None,"branch_margin":second["weighted_rms"]-best["weighted_rms"] if second else None,"clock_quality":min((self.clock.model(*p).quality for p in itertools.combinations(ORDER,2)),key=lambda q:{"BAD":0,"UNAVAILABLE":1,"MARGINAL":2,"PASS":3,"STRONG":4}.get(q,0))}
