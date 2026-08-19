"""Asyncio-owned realtime state and bounded rolling metrics."""
import time,datetime as dt
from collections import Counter,deque

def utc(ts=None):return dt.datetime.fromtimestamp(ts or time.time(),dt.timezone.utc).isoformat().replace("+00:00","Z")

class ReceiverState:
    def __init__(self,station,port,lat=None,lon=None,alt_m=None):
        self.station=station;self.port=port;self.lat=lat;self.lon=lon;self.alt_m=alt_m;self.connected=False;self.remote_address=None;self.connected_since=None;self.last_frame_time=None;self.frames_total=0;self.type1_total=0;self.type2_total=0;self.type3_total=0;self.parse_errors=0;self.reconnect_count=0;self._type1_times=deque(maxlen=100000);self._type2_times=deque(maxlen=100000);self._type3_times=deque(maxlen=100000)
    def connect(self,peer):
        if self.connected or self.connected_since is not None:self.reconnect_count+=1
        self.connected=True;self.remote_address=peer[0] if peer else None;self.connected_since=time.time()
    def disconnect(self):self.connected=False
    def frame(self,f):
        self.frames_total+=1;self.last_frame_time=f.arrival_utc
        if f.frame_type==0x31:self.type1_total+=1;self._type1_times.append(f.arrival_monotonic)
        elif f.frame_type==0x32:self.type2_total+=1;self._type2_times.append(f.arrival_monotonic)
        elif f.frame_type==0x33:self.type3_total+=1;self._type3_times.append(f.arrival_monotonic)
    def public(self,now):
        cutoff=time.monotonic()-60
        for d in (self._type1_times,self._type2_times,self._type3_times):
            while d and d[0]<cutoff:d.popleft()
        return {"station":self.station,"port":self.port,"lat":self.lat,"lon":self.lon,"alt_m":self.alt_m,"connected":self.connected,"remote_address":self.remote_address,"connected_since":utc(self.connected_since) if self.connected_since else None,"last_frame_age_s":now-self.last_frame_time if self.last_frame_time else None,"frames_total":self.frames_total,"type1_total":self.type1_total,"type2_total":self.type2_total,"type3_total":self.type3_total,"type1_rate_s":len(self._type1_times)/60,"type2_rate_s":len(self._type2_times)/60,"type3_rate_s":len(self._type3_times)/60,"parse_errors":self.parse_errors,"reconnect_count":self.reconnect_count}

class StateStore:
    def __init__(self,stations):
        self.started=time.time();self.receivers={x.name:ReceiverState(x.name,x.port,x.lat,x.lon,x.alt_m) for x in stations.values()};self.clock_links={};self.tracks={};self.modes_tracks={};self.stats=Counter();self.modes_stats=Counter();self.latency_ms=deque(maxlen=5000);self.modes_latency={k:deque(maxlen=5000) for k in ("association","queue","solver","track","total")};self.event_times={k:deque(maxlen=10000) for k in ("strict_4rx","blind_unique","blind_multiple","blind_inconsistent")};self.modes_event_times={k:deque(maxlen=10000) for k in ("clustered","strict_4rx","mlat_fix","three_rx_alt")};self.subscribers=set();self.modes_subscribers=set();self.queue_depth=0;self.event_queue_depth=0;self.modes_event_queue_depth=0;self.modes_event_queue_high_water=0;self.modes_oldest_queued_age_s=0;self.modeac_buffer_entries=0;self.modes_buffer_entries=0;self.clock_sample_entries=0
    async def publish(self,event):
        dead=[]
        for q in self.subscribers:
            try:q.put_nowait(event)
            except Exception:dead.append(q)
        for q in dead:self.subscribers.discard(q)
    async def publish_modes(self,event):
        dead=[]
        for q in self.modes_subscribers:
            try:q.put_nowait(event)
            except Exception:dead.append(q)
        for q in dead:self.modes_subscribers.discard(q)
    def mark(self,key,now=None):self.event_times[key].append(now or time.monotonic());self.stats[key]+=1
    def rates(self):
        now=time.monotonic();out={}
        for k,d in self.event_times.items():
            while d and d[0]<now-60:d.popleft()
            out[k+"_per_min"]=len(d)
        return out
    def modes_mark(self,key,now=None):self.modes_event_times[key].append(now or time.monotonic());self.modes_stats[key]+=1
    def modes_rates(self):
        now=time.monotonic();out={}
        for k,d in self.modes_event_times.items():
            while d and d[0]<now-60:d.popleft()
            out[k+"_per_min"]=len(d)
        return out
