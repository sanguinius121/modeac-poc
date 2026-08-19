"""Strict reciprocal-nearest four-station Mode A/C transmission association."""
import itertools,math,time
from collections import defaultdict,deque
import numpy as np
from .config import ORDER,STATIONS,C,BEAST_HZ,MODEAC_PER_STATION,ASSOCIATION_MARGIN_US
from .clock_sync import T4

class StrictAssociator:
    def __init__(self,clock,state):
        self.clock=clock;self.state=state;self.rows={s:defaultdict(lambda:deque(maxlen=MODEAC_PER_STATION)) for s in ORDER};self.next_id=1;self.used=set();self.ecef={s:np.array(T4.geodetic_to_ecef(STATIONS[s].lat,STATIONS[s].lon,STATIONS[s].alt_m)) for s in ORDER};self.limit={p:float(np.linalg.norm(self.ecef[p[0]]-self.ecef[p[1]]))/C*1e6 for p in itertools.combinations(ORDER,2)}
    def add(self,frame):
        if frame.kind!="modeac" or not frame.timestamp_corrected:return None,"INSUFFICIENT_RECEIVERS"
        norm=self.clock.normalize(frame.station,frame.timestamp_corrected)
        if norm is None:return None,"INSUFFICIENT_RECEIVERS"
        raw=frame.payload.hex();node={"id":self.next_id,"station":frame.station,"raw":raw,"tick":frame.timestamp_corrected,"norm":norm,"utc":frame.arrival_utc,"mono":frame.arrival_monotonic,"signal":frame.signal};self.next_id+=1;self.rows[frame.station][raw].append(node)
        selected={frame.station:node};gate=max(self.limit.values())+ASSOCIATION_MARGIN_US
        for s in ORDER:
            if s==frame.station:continue
            candidates=[x for x in self.rows[s][raw] if x["id"] not in self.used and abs(x["norm"]-norm)<=gate*12]
            if not candidates:return None,"INSUFFICIENT_RECEIVERS"
            candidates.sort(key=lambda x:abs(x["norm"]-norm))
            if len(candidates)>1 and abs(candidates[1]["norm"]-norm)-abs(candidates[0]["norm"]-norm)<6:return None,"AMBIGUOUS_ASSOCIATION"
            selected[s]=candidates[0]
        for a,b in itertools.combinations(ORDER,2):
            if abs(selected[b]["norm"]-selected[a]["norm"])/12>self.limit[(a,b)]+ASSOCIATION_MARGIN_US:return None,"INCONSISTENT_ASSOCIATION"
        # Reciprocal nearest check for every pair.
        for a,b in itertools.combinations(ORDER,2):
            aa=[x for x in self.rows[a][raw] if x["id"] not in self.used];bb=[x for x in self.rows[b][raw] if x["id"] not in self.used]
            if not aa or not bb:return None,"INSUFFICIENT_RECEIVERS"
            nearest_b=min(bb,key=lambda x:abs(x["norm"]-selected[a]["norm"]));nearest_a=min(aa,key=lambda x:abs(x["norm"]-selected[b]["norm"]))
            if nearest_b["id"]!=selected[b]["id"] or nearest_a["id"]!=selected[a]["id"]:return None,"AMBIGUOUS_ASSOCIATION"
        for x in selected.values():self.used.add(x["id"])
        event={"event_id":self.state.stats["strict_4rx"]+1,"raw_hex":raw,"nodes":selected,"norm":{s:selected[s]["norm"] for s in ORDER},"tdoa":{p:(selected[p[1]]["norm"]-selected[p[0]]["norm"])/12 for p in itertools.combinations(ORDER,2)},"utc":statistics_median([x["utc"] for x in selected.values()]),"latest_arrival_mono":max(x["mono"] for x in selected.values())}
        return event,"STRICT_4RX"

    def prune(self,now=None,max_age_s=1.0):
        """Discard observations far older than the millisecond-scale match window."""
        cutoff=(now if now is not None else time.monotonic())-max_age_s
        active=set()
        for station_rows in self.rows.values():
            for raw,items in list(station_rows.items()):
                while items and items[0]["mono"]<cutoff:items.popleft()
                if items:active.update(x["id"] for x in items)
                else:del station_rows[raw]
        self.used.intersection_update(active)

def statistics_median(v):
    x=sorted(v);n=len(x);return (x[n//2] if n%2 else (x[n//2-1]+x[n//2])/2)
