"""Rolling geometry-corrected DF17 receiver clock calibration only."""
import importlib.util,itertools,math,statistics,time
from collections import defaultdict,deque
import numpy as np
from .config import ROOT,ORDER,STATIONS,BEAST_HZ,C,CLOCK_SAMPLES_PER_LINK,CLOCK_MIN_SAMPLES

def _module(path):
    s=importlib.util.spec_from_file_location("realtime_test4",path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
T4=_module(ROOT/"tools/test4b-holdout.py")

def percentile(v,p):
    if not v:return None
    x=sorted(v);q=(len(x)-1)*p;a,b=math.floor(q),math.ceil(q);return x[a] if a==b else x[a]*(b-q)+x[b]*(q-a)

class Link:
    def __init__(self,a,b):
        self.a=a;self.b=b;self.samples=deque(maxlen=CLOCK_SAMPLES_PER_LINK);self.slope=None;self.offset=None;self.residuals=[];self.updated=None;self.quality="UNAVAILABLE";self.outlier_streak=0;self.rejected=0;self.resets=0
    def add(self,ta,tb_clock):
        if self.slope is not None and abs(float(tb_clock)-(self.slope*float(ta)+self.offset))/12>100:
            self.outlier_streak+=1;self.rejected+=1
            if self.outlier_streak<3:return
            self.samples.clear();self.slope=None;self.offset=None;self.residuals=[];self.quality="UNAVAILABLE";self.resets+=1
        else:self.outlier_streak=0
        self.samples.append((float(ta),float(tb_clock)));self.updated=time.time()
        if len(self.samples)>=20:self.fit()
    def fit(self):
        x=np.array([z[0] for z in self.samples]);y=np.array([z[1] for z in self.samples]);xm=float(np.mean(x));ym=float(np.mean(y));den=float(np.sum((x-xm)**2))
        if den<=0:return
        self.slope=float(np.sum((x-xm)*(y-ym))/den);self.offset=ym-self.slope*xm;self.residuals=list((y-(self.slope*x+self.offset))/12)
        p95=percentile([abs(x) for x in self.residuals],.95)
        if len(self.samples)<CLOCK_MIN_SAMPLES:self.quality="UNAVAILABLE"
        elif p95<1:self.quality="STRONG"
        elif p95<5:self.quality="PASS"
        elif p95<10:self.quality="MARGINAL"
        else:self.quality="BAD"
    def public(self):
        a=[abs(x) for x in self.residuals];now=time.time()
        return {"a":self.a,"b":self.b,"quality":self.quality,"samples":len(self.samples),"slope":self.slope,"offset":self.offset,"p50_us":percentile(a,.5),"p90_us":percentile(a,.9),"p95_us":percentile(a,.95),"p99_us":percentile(a,.99),"last_update":self.updated,"updated_age_s":now-self.updated if self.updated else None,"rejected_discontinuities":self.rejected,"model_resets":self.resets}

class ClockSynchronizer:
    def __init__(self,state,logger,stations=None,order=None,reference="T37"):
        self.state=state;self.log=logger;self.stations=stations or STATIONS;self.order=tuple(order or ORDER);self.reference=reference
        if reference not in self.order:raise ValueError("clock reference must be in receiver order")
        self._rank={name:index for index,name in enumerate(self.order)};self.links={p:Link(*p) for p in itertools.combinations(self.order,2)};self.pending=defaultdict(list);self.even={};self.odd={};self.ecef={s:np.array(T4.geodetic_to_ecef(self.stations[s].lat,self.stations[s].lon,self.stations[s].alt_m)) for s in self.order};self._quality={}
        state.clock_links=self.links
    def canonical(self,a,b):return (a,b) if self._rank[a]<self._rank[b] else (b,a)
    def model(self,a,b):return self.links[self.canonical(a,b)]
    def receiver_ready(self,station):
        if station not in self._rank:return False
        return station==self.reference or self.model(self.reference,station).slope is not None
    def usable_receivers(self,receiver_ids=None):
        return tuple(s for s in (receiver_ids or self.order) if self.receiver_ready(s))
    def ready(self,receiver_ids=None,minimum_receivers=None):
        receiver_ids=tuple(receiver_ids or self.order);usable=self.usable_receivers(receiver_ids)
        return len(usable)>=minimum_receivers if minimum_receivers is not None else len(usable)==len(receiver_ids)
    def normalize(self,station,tick):
        if station==self.reference:return float(tick)
        if not self.receiver_ready(station):return None
        link=self.model(self.reference,station)
        return (float(tick)-link.offset)/link.slope if link.slope is not None else None
    def sigma(self,a,b):
        p=percentile([abs(x) for x in self.model(a,b).residuals],.95)
        return max(1.,p or 10.)
    def process(self,frame):
        if frame.frame_type!=0x33 or not frame.payload or frame.payload[0]>>3!=17 or not frame.timestamp_corrected:return
        d=T4.decode_airborne_fields(frame.payload)
        if d is None:return
        now=frame.arrival_monotonic;icao=d["icao"]
        (self.odd if d["odd"] else self.even)[icao]=(d,now)
        if icao not in self.even or icao not in self.odd:return
        ev,te=self.even[icao];od,to=self.odd[icao]
        if abs(te-to)>10:return
        use_odd=to>te;ll=T4.decode_global_cpr(ev,od,use_odd)
        if ll is None:return
        selected=od if use_odd else ev
        lat,lon=ll;alt=selected["altitude_ft"]*.3048
        if not (-10<=lat<=45 and 80<=lon<=140 and -500<=alt<=20000):return
        pos=np.array(T4.geodetic_to_ecef(lat,lon,alt));key=frame.payload.hex();groups=self.pending[key];group=None
        eligible=[g for g in groups if now-g["created"]<=.2 and frame.station not in g["copies"]]
        if eligible:group=min(eligible,key=lambda g:abs(now-g["created"]))
        if group is None:group={"created":now,"copies":{},"pairs":set(),"position":pos};groups.append(group)
        group["copies"][frame.station]=frame
        for a,b in itertools.combinations(sorted(group["copies"],key=self._rank.get),2):
            if (a,b) in group["pairs"]:continue
            fa,fb=group["copies"][a],group["copies"][b];geom=(np.linalg.norm(pos-self.ecef[b])-np.linalg.norm(pos-self.ecef[a]))/C*BEAST_HZ
            self.model(a,b).add(fa.timestamp_corrected,fb.timestamp_corrected-geom);group["pairs"].add((a,b))
            link=self.model(a,b)
            if self._quality.get((a,b))!=link.quality:
                if link.quality!="UNAVAILABLE":self.log("clock_quality",a=a,b=b,quality=link.quality,samples=len(link.samples))
                self._quality[(a,b)]=link.quality
        cutoff=now-2
        for raw in list(self.pending):
            self.pending[raw]=[g for g in self.pending[raw] if g["created"]>=cutoff]
            if not self.pending[raw]:del self.pending[raw]

    def prune(self,now=None,max_age_s=30.0):
        now=time.monotonic() if now is None else now;cutoff=now-max_age_s
        self.even={k:v for k,v in self.even.items() if v[1]>=cutoff};self.odd={k:v for k,v in self.odd.items() if v[1]>=cutoff}
        for raw in list(self.pending):
            self.pending[raw]=[g for g in self.pending[raw] if g["created"]>=now-2]
            if not self.pending[raw]:del self.pending[raw]
