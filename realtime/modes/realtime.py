"""Bounded streaming exact-transmission Mode-S association."""
import itertools,time
from collections import defaultdict,deque
from realtime.config import ORDER,C,STATIONS,MODES_BUFFER_AGE_S,MODES_MAX_PAYLOADS
from realtime.clock_sync import T4
from .decoder import decode_modes
import numpy as np

class RealtimeModeSAssociator:
    def __init__(self,clock,state,margin_us=3.0):
        self.clock=clock;self.state=state;self.margin_us=margin_us;self.rows={};self.next_id=1;self.known_icao={}
        ecef={s:np.array(T4.geodetic_to_ecef(STATIONS[s].lat,STATIONS[s].lon,STATIONS[s].alt_m)) for s in ORDER}
        self.limits={p:float(np.linalg.norm(ecef[p[0]]-ecef[p[1]]))/C*1e6 for p in itertools.combinations(ORDER,2)}
    def add(self,frame):
        started=time.monotonic();metadata=decode_modes(frame.payload)
        if metadata is None or not frame.timestamp_corrected:return None,"UNSUPPORTED"
        df=metadata["df"];self.state.modes_stats["df_%d"%df]+=1
        now=frame.arrival_monotonic
        if metadata["icao_source"]=="DIRECT":self.known_icao[metadata["icao"]]=now
        elif metadata["icao"] not in self.known_icao:
            metadata["icao"]=None;metadata["icao_source"]="UNTRUSTED_PARITY"
        norm=self.clock.normalize(frame.station,frame.timestamp_corrected)
        if norm is None:return None,"CLOCK_NOT_READY"
        raw=metadata["raw_hex"]
        if raw not in self.rows:
            if len(self.rows)>=MODES_MAX_PAYLOADS:self.prune(now,0.2)
            if len(self.rows)>=MODES_MAX_PAYLOADS:
                oldest=min(self.rows,key=lambda k:self.rows[k]["created"]);del self.rows[oldest];self.state.modes_stats["payload_buffers_evicted"]+=1
            self.rows[raw]={"created":now,"stations":defaultdict(lambda:deque(maxlen=8))}
        node={"id":self.next_id,"station":frame.station,"norm":norm,"tick":frame.timestamp_corrected,"utc":frame.arrival_utc,"mono":now,"signal":frame.signal};self.next_id+=1
        row=self.rows[raw];row["stations"][frame.station].append(node)
        if any(not row["stations"].get(s) for s in ORDER):return None,"INSUFFICIENT_RECEIVERS"
        selected={}
        for s in ORDER:
            choices=sorted(row["stations"][s],key=lambda x:abs(x["norm"]-norm))
            if len(choices)>1 and abs(choices[1]["norm"]-norm)-abs(choices[0]["norm"]-norm)<6:return None,"AMBIGUOUS_ASSOCIATION"
            selected[s]=choices[0]
        for a,b in itertools.combinations(ORDER,2):
            if abs(selected[b]["norm"]-selected[a]["norm"])/12>self.limits[(a,b)]+self.margin_us:return None,"INCONSISTENT_ASSOCIATION"
            if min(row["stations"][b],key=lambda x:abs(x["norm"]-selected[a]["norm"]))["id"]!=selected[b]["id"]:return None,"AMBIGUOUS_ASSOCIATION"
            if min(row["stations"][a],key=lambda x:abs(x["norm"]-selected[b]["norm"]))["id"]!=selected[a]["id"]:return None,"AMBIGUOUS_ASSOCIATION"
        del self.rows[raw]
        complete=time.monotonic();event={"event_id":self.state.modes_stats["strict_4rx"]+1,"raw_hex":raw,"df":df,"icao":metadata["icao"],"icao_source":metadata["icao_source"],"metadata":metadata,"nodes":selected,"receiver_count":4,"tdoa":{p:(selected[p[1]]["norm"]-selected[p[0]]["norm"])/12 for p in itertools.combinations(ORDER,2)},"utc":sorted(x["utc"] for x in selected.values())[2],"latest_arrival_mono":max(x["mono"] for x in selected.values()),"association_complete_mono":complete,"association_latency_ms":(complete-started)*1000}
        return event,"STRICT_4RX"
    def prune(self,now=None,max_age_s=MODES_BUFFER_AGE_S):
        now=time.monotonic() if now is None else now
        for raw,row in list(self.rows.items()):
            if row["created"]<now-max_age_s:del self.rows[raw]
        for icao,seen in list(self.known_icao.items()):
            if seen<now-600:del self.known_icao[icao]
    def size(self):return sum(sum(len(x) for x in r["stations"].values()) for r in self.rows.values())
