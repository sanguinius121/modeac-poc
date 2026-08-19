"""ICAO-keyed track state for inferred Mode-S MLAT positions."""
import time
from realtime.config import TRACK_CONFIRM_FIXES,TRACK_STALE_S,TRACK_EXPIRE_S,TRACK_MAX_GAP_S,TRACK_HARD_SPEED_MPS,TRACK_GATE_ALLOWANCE_M
from realtime.localization import horizontal
from realtime.tracker import bearing

class ModeSTrackManager:
    def __init__(self,state,logger):self.state=state;self.log=logger
    def public(self,t,now=None):
        now=now or time.time();keys=("track_id","icao","lat","lon","altitude_ft","altitude_source","quality","state","receiver_count","fix_count","first_seen","last_seen","speed_mps","heading_deg","position_source","df","weighted_rms","branch_margin","clock_quality")
        out={k:t.get(k) for k in keys};out["age_s"]=now-t["last_seen_epoch"];return out
    async def update(self,event,solution):
        icao=event.get("icao")
        if not icao:return None
        tid="MS-"+icao.upper();now=event["utc"];t=self.state.modes_tracks.get(tid);created=t is None
        if created:
            t={"track_id":tid,"icao":icao.upper(),"lat":solution["lat"],"lon":solution["lon"],"altitude_ft":event["metadata"].get("altitude_ft"),"altitude_source":"MODE_S_MESSAGE" if event["metadata"].get("altitude_ft") is not None else "MLAT_HYPOTHESIS","quality":"LOW","state":"TENTATIVE","receiver_count":4,"fix_count":0,"first_seen":event["utc_iso"],"last_seen":event["utc_iso"],"first_seen_epoch":now,"last_seen_epoch":now,"speed_mps":None,"heading_deg":None,"position_source":"MODES_MLAT_4RX","df":event["df"],"weighted_rms":solution.get("weighted_rms"),"branch_margin":solution.get("branch_margin"),"clock_quality":solution.get("clock_quality")};self.state.modes_tracks[tid]=t
        else:
            dt=now-t["last_seen_epoch"]
            if dt<=0:return None
            jump=horizontal((t["lat"],t["lon"]),(solution["lat"],solution["lon"]))
            if dt<=TRACK_MAX_GAP_S and jump>TRACK_HARD_SPEED_MPS*dt+TRACK_GATE_ALLOWANCE_M:self.state.modes_stats["track_gate_reject"]+=1;return None
            t["speed_mps"]=jump/dt;t["heading_deg"]=bearing((t["lat"],t["lon"]),(solution["lat"],solution["lon"]))
        old=t["state"];t.update(lat=solution["lat"],lon=solution["lon"],last_seen=event["utc_iso"],last_seen_epoch=now,receiver_count=4,df=event["df"],weighted_rms=solution.get("weighted_rms"),branch_margin=solution.get("branch_margin"),clock_quality=solution.get("clock_quality"));t["fix_count"]+=1;t["state"]="CONFIRMED" if t["fix_count"]>=TRACK_CONFIRM_FIXES else "TENTATIVE"
        if t["fix_count"]>=5 and solution.get("weighted_rms",99)<=1.0 and solution.get("clock_quality") in ("STRONG","PASS"):t["quality"]="HIGH"
        elif t["fix_count"]>=3 and solution.get("weighted_rms",99)<=1.5:t["quality"]="MEDIUM"
        else:t["quality"]="LOW"
        kind="track_created" if created else "track_updated";self.log("modes_"+kind,track_id=tid,icao=icao,lat=t["lat"],lon=t["lon"],quality=t["quality"],fix_count=t["fix_count"]);await self.state.publish_modes({"type":kind,"track":self.public(t)})
        if old!=t["state"]:await self.state.publish_modes({"type":"track_state_changed","track":self.public(t)})
        return t
    async def expire(self):
        now=time.time()
        for tid,t in list(self.state.modes_tracks.items()):
            age=now-t["last_seen_epoch"]
            if age>=TRACK_EXPIRE_S:
                t["state"]="EXPIRED";await self.state.publish_modes({"type":"track_removed","track":self.public(t,now)});del self.state.modes_tracks[tid]
            elif age>=TRACK_STALE_S and t["state"]!="STALE":t["state"]="STALE";await self.state.publish_modes({"type":"track_stale","track":self.public(t,now)})
