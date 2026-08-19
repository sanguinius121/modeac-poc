"""Blind four-receiver Mode-S localization, sharing the Test 7I solver."""
import itertools
import math
import statistics

from realtime.config import ALTITUDE_GRID_FT, ORDER
from realtime.localization import D7C, families, horizontal


PAIRS = list(itertools.combinations(ORDER, 2))


def _weighted(candidate, sigma):
    return math.sqrt(statistics.mean((candidate["residuals"][pair] / sigma[pair]) ** 2 for pair in PAIRS))


def solve_grid(tdoa, sigma, altitude_grid_ft=None):
    candidates = []
    solver_calls = 0
    for feet in altitude_grid_ft or ALTITUDE_GRID_FT:
        solver_calls += 1
        _, branches, _ = D7C.solve(feet * 0.3048, ORDER, tdoa)
        for branch_number, candidate in enumerate(branches, 1):
            candidates.append({
                **candidate,
                "altitude_ft": feet,
                "solver_branch": branch_number,
                "weighted_rms": _weighted(candidate, sigma),
            })
    primary = sorted(families(candidates, 1500), key=lambda x: x["weighted_rms"])
    expanded = sorted(families(candidates, 3000), key=lambda x: x["weighted_rms"])
    if not primary:
        return {"classification": "BLIND_INCONSISTENT", "selected": None, "primary": [], "expanded": expanded, "solver_calls": solver_calls}
    best = primary[0]
    second = primary[1] if len(primary) > 1 else None
    outside = any(
        x["weighted_rms"] - best["weighted_rms"] < 0.5
        and horizontal((x["lat"], x["lon"]), (best["lat"], best["lon"])) > 25000
        for x in expanded
    )
    if best["weighted_rms"] > 1.5:
        classification = "BLIND_INCONSISTENT"
    elif (second and second["weighted_rms"] - best["weighted_rms"] < 0.5 and second["weighted_rms"] / max(best["weighted_rms"], 1e-9) < 1.5) or outside:
        classification = "BLIND_MULTIPLE"
    else:
        classification = "BLIND_UNIQUE"
    return {"classification": classification, "selected": best, "primary": primary, "expanded": expanded, "solver_calls": solver_calls}

class RealtimeModeSLocalizer:
    """Clock-weighted blind 4RX solver; target message position is never decoded."""
    def __init__(self,clock):self.clock=clock
    def solve(self,event):
        sigma={pair:self.clock.sigma(*pair) for pair in PAIRS}
        result=solve_grid(event["tdoa"],sigma)
        if result["selected"]:
            best=result["selected"]
            result.update(lat=best["lat"],lon=best["lon"],altitude_hypothesis_ft=best["altitude_ft"],weighted_rms=best["weighted_rms"],unweighted_rms_us=best["rms_us"],condition=best["condition"],branch_margin=(result["primary"][1]["weighted_rms"]-best["weighted_rms"] if len(result["primary"])>1 else None))
        result["clock_quality"]=min((self.clock.model(*p).quality for p in PAIRS),key=lambda q:{"BAD":0,"UNAVAILABLE":1,"MARGINAL":2,"PASS":3,"STRONG":4}.get(q,0))
        return result

def solve_realtime_payload(tdoa,sigma,clock_quality):
    """Pickle-safe entry point used by the isolated Mode-S process pool."""
    result=solve_grid(tdoa,sigma)
    if result["selected"]:
        best=result["selected"]
        result.update(lat=best["lat"],lon=best["lon"],altitude_hypothesis_ft=best["altitude_ft"],weighted_rms=best["weighted_rms"],unweighted_rms_us=best["rms_us"],condition=best["condition"],branch_margin=(result["primary"][1]["weighted_rms"]-best["weighted_rms"] if len(result["primary"])>1 else None))
    result["clock_quality"]=clock_quality
    return result
