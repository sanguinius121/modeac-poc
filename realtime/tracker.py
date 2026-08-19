"""Anonymous constant-velocity Mode A/C track lifecycle manager."""
import math,time
from .config import TRACK_CONFIRM_FIXES,TRACK_STALE_S,TRACK_EXPIRE_S,TRACK_MAX_GAP_S,TRACK_HARD_SPEED_MPS,TRACK_GATE_ALLOWANCE_M
from .localization import horizontal
from .modeac import decode

def display_code(raw):
    x=int(raw,16)&0x7777;return f"{(x>>12)&7}{(x>>8)&7}{(x>>4)&7}{x&7}"
def bearing(a,b):
    lat1,lat2=math.radians(a[0]),math.radians(b[0]);dl=math.radians(b[1]-a[1]);y=math.sin(dl)*math.cos(lat2);x=math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(dl);return (math.degrees(math.atan2(y,x))+360)%360

class TrackManager:
    def __init__(self,state,logger):self.state=state;self.log=logger;self.next_id=1;self.history={}
    def public(self,t,now=None):
        now=now or time.time()
        result={k:t.get(k) for k in ("track_id","code","lat","lon","altitude_ft","altitude_source","quality","state","receiver_count","fix_count","first_seen","last_seen","speed_mps","heading_deg","position_source","raw_code","display_code","gillham_decodable","mode_c_candidate","decoded_altitude_candidate","mode_interpretation","code_stability","weighted_rms","branch_margin","clock_quality")}
        result["age_s"]=now-t["last_seen_epoch"]
        return result
    async def update(self,event,solution):
        metadata=decode(event["raw_hex"]);code=metadata["display_code"];now=event["utc"];options=[]
        for t in self.state.tracks.values():
            if t["code"]!=code or t["state"]=="EXPIRED":continue
            dt=now-t["last_seen_epoch"]
            if not 0<dt<=TRACK_MAX_GAP_S:continue
            pred=(t["lat"],t["lon"])
            if t.get("velocity_lat_s") is not None:pred=(t["lat"]+t["velocity_lat_s"]*dt,t["lon"]+t["velocity_lon_s"]*dt)
            miss=horizontal(pred,(solution["lat"],solution["lon"]));jump=horizontal((t["lat"],t["lon"]),(solution["lat"],solution["lon"]))
            if jump<=TRACK_HARD_SPEED_MPS*dt+TRACK_GATE_ALLOWANCE_M and miss<=TRACK_HARD_SPEED_MPS*dt+5000:options.append((miss,t))
        created=not options
        if created:
            tid=f"MAC-{self.next_id:06d}";self.next_id+=1;t={"track_id":tid,"code":code,**metadata,"lat":solution["lat"],"lon":solution["lon"],"altitude_ft":None,"altitude_source":"unknown","quality":"LOW","state":"TENTATIVE","receiver_count":4,"fix_count":0,"first_seen":event["utc_iso"],"last_seen":event["utc_iso"],"first_seen_epoch":now,"last_seen_epoch":now,"speed_mps":None,"heading_deg":None,"position_source":"MODEAC_MLAT_4RX","velocity_lat_s":None,"velocity_lon_s":None,"code_stability":1.0,"branch_margin":solution.get("branch_margin"),"weighted_rms":solution.get("weighted_rms"),"clock_quality":solution.get("clock_quality")};self.state.tracks[tid]=t;self.history[tid]=[]
        else:t=min(options,key=lambda x:x[0])[1]
        old_state=t["state"];dt=now-t["last_seen_epoch"]
        if t["fix_count"] and dt>0:
            old=(t["lat"],t["lon"]);new=(solution["lat"],solution["lon"]);t["speed_mps"]=horizontal(old,new)/dt;t["heading_deg"]=bearing(old,new);t["velocity_lat_s"]=(new[0]-old[0])/dt;t["velocity_lon_s"]=(new[1]-old[1])/dt
        t.update(lat=solution["lat"],lon=solution["lon"],last_seen=event["utc_iso"],last_seen_epoch=now,receiver_count=4,branch_margin=solution.get("branch_margin"),weighted_rms=solution.get("weighted_rms"),clock_quality=solution.get("clock_quality"));t["fix_count"]+=1;t["state"]="CONFIRMED" if t["fix_count"]>=TRACK_CONFIRM_FIXES else "TENTATIVE"
        if t["fix_count"]>=5 and solution.get("weighted_rms",99)<=1.0 and solution.get("clock_quality") in ("STRONG","PASS"):t["quality"]="HIGH"
        elif t["fix_count"]>=3 and solution.get("weighted_rms",99)<=1.5:t["quality"]="MEDIUM"
        else:t["quality"]="LOW"
        self.history[t["track_id"]].append((now,t["lat"],t["lon"]));self.history[t["track_id"]]=self.history[t["track_id"]][-20:]
        kind="track_created" if created else "track_updated";self.log(kind,track_id=t["track_id"],code=code,lat=t["lat"],lon=t["lon"],quality=t["quality"],fix_count=t["fix_count"]);await self.state.publish({"type":kind,"track":self.public(t)})
        if old_state!=t["state"]:await self.state.publish({"type":"track_state_changed","track":self.public(t)})
        return t
    async def expire(self):
        now=time.time()
        for tid,t in list(self.state.tracks.items()):
            age=now-t["last_seen_epoch"]
            if age>=TRACK_EXPIRE_S:
                t["state"]="EXPIRED";await self.state.publish({"type":"track_removed","track":self.public(t,now)});self.log("track_removed",track_id=tid);del self.state.tracks[tid]
            elif age>=TRACK_STALE_S and t["state"]!="STALE":t["state"]="STALE";await self.state.publish({"type":"track_stale","track":self.public(t,now)});self.log("track_stale",track_id=tid)
