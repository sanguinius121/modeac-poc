"""Realtime unified Mode A/C and Mode-S MLAT backend entry point."""
import argparse,asyncio,datetime as dt,json,signal,time
from concurrent.futures import ThreadPoolExecutor,ProcessPoolExecutor
from .config import STATIONS,FRAME_QUEUE_SIZE,API_PORT,MODES_EVENT_QUEUE_SIZE,MODES_SOLVER_WORKERS,MODES_EVENT_STALE_S,PUBLISH_DF17_MLAT
from .state import StateStore,utc
from .receiver import ReceiverServer
from .clock_sync import ClockSynchronizer
from .association import StrictAssociator
from .localization import BlindLocalizer
from .tracker import TrackManager
from .api import APIServer
from .modes import RealtimeModeSAssociator,RealtimeModeSLocalizer,ModeSTrackManager
from .modes.localization import PAIRS,solve_realtime_payload

def log(event,**fields):print(json.dumps({"time":utc(),"event":event,**fields},separators=(",",":")),flush=True)

class Backend:
    def __init__(self,api_port=API_PORT,publish_df17_mlat=PUBLISH_DF17_MLAT):
        self.state=StateStore(STATIONS);self.frames=asyncio.Queue(maxsize=FRAME_QUEUE_SIZE);self.events=asyncio.Queue(maxsize=200);self.modes_events=asyncio.Queue(maxsize=MODES_EVENT_QUEUE_SIZE);self.clock=ClockSynchronizer(self.state,log);self.association=StrictAssociator(self.clock,self.state);self.localizer=BlindLocalizer(self.clock);self.tracker=TrackManager(self.state,log);self.modes_association=RealtimeModeSAssociator(self.clock,self.state);self.modes_localizer=RealtimeModeSLocalizer(self.clock);self.modes_tracker=ModeSTrackManager(self.state,log);self.publish_df17_mlat=publish_df17_mlat;self.modeac_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="modeac-mlat");self.modes_executor=ProcessPoolExecutor(max_workers=MODES_SOLVER_WORKERS);self.receivers=[ReceiverServer(x.name,x.port,self.state,self.frames,log) for x in STATIONS.values()];self.api=APIServer(self.state,self.tracker,self.clock,self.modes_tracker,port=api_port);self.tasks=[];self.stop_event=asyncio.Event()
    async def start(self):
        for x in self.receivers:await x.start()
        await self.api.start();self.tasks=[asyncio.create_task(self.frame_worker()),asyncio.create_task(self.localization_worker()),*[asyncio.create_task(self.modes_localization_worker(i)) for i in range(MODES_SOLVER_WORKERS)],asyncio.create_task(self.housekeeping())];log("backend_started",receiver_ports=[x.port for x in STATIONS.values()],api_port=self.api.port,modes_workers=MODES_SOLVER_WORKERS,publish_df17_mlat=self.publish_df17_mlat)
    async def stop(self):
        self.stop_event.set()
        for x in self.receivers:await x.stop()
        await self.api.stop()
        for t in self.tasks:t.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True);self.modeac_executor.shutdown(wait=True);self.modes_executor.shutdown(wait=True);log("backend_stopped")
    async def frame_worker(self):
        while True:
            f=await self.frames.get();self.state.queue_depth=self.frames.qsize();self.clock.process(f)
            if f.kind=="modeac":
                event,cl=self.association.add(f)
                if event:
                    self.state.mark("strict_4rx");event["utc_iso"]=utc(event["utc"])
                    try:self.events.put_nowait(event);log("strict_4rx",event_id=event["event_id"],raw=event["raw_hex"])
                    except asyncio.QueueFull:self.state.stats["events_dropped_queue"]+=1
                elif cl!="INSUFFICIENT_RECEIVERS":self.state.stats[cl.lower()]+=1
            else:
                event,cl=self.modes_association.add(f)
                if event:
                    self.state.modes_mark("clustered")
                    if event["df"]==17:self.state.modes_stats["df17_strict_4rx"]+=1
                    if event.get("icao") is None:self.state.modes_stats["untrusted_identity"]+=1
                    if event["df"] in (4,5,11,20,21) or (event["df"]==17 and self.publish_df17_mlat):
                        self.state.modes_mark("strict_4rx");event["utc_iso"]=utc(event["utc"]);event["queued_mono"]=time.monotonic()
                        try:self.modes_events.put_nowait(event);self.state.modes_event_queue_high_water=max(self.state.modes_event_queue_high_water,self.modes_events.qsize());log("modes_strict_4rx",event_id=event["event_id"],df=event["df"],icao=event.get("icao"))
                        except asyncio.QueueFull:self.state.modes_stats["events_dropped_queue"]+=1
                elif cl not in ("INSUFFICIENT_RECEIVERS","UNSUPPORTED"):
                    self.state.modes_stats[cl.lower()]+=1
            self.state.event_queue_depth=self.events.qsize()
            self.state.modes_event_queue_depth=self.modes_events.qsize()
            self.frames.task_done()
    async def localization_worker(self):
        loop=asyncio.get_running_loop()
        while True:
            e=await self.events.get()
            try:
                sol=await loop.run_in_executor(self.modeac_executor,self.localizer.solve,e);cl=sol["classification"];self.state.mark({"BLIND_UNIQUE":"blind_unique","BLIND_MULTIPLE":"blind_multiple","BLIND_INCONSISTENT":"blind_inconsistent"}[cl])
                if cl=="BLIND_UNIQUE":
                    await self.tracker.update(e,sol);self.state.latency_ms.append((time.monotonic()-e["latest_arrival_mono"])*1000);log("blind_unique",event_id=e["event_id"],lat=sol["lat"],lon=sol["lon"],weighted_rms=sol["weighted_rms"],clock_quality=sol["clock_quality"])
            except Exception as exc:log("localization_exception",event_id=e.get("event_id"),error=str(exc))
            finally:self.state.event_queue_depth=self.events.qsize();self.events.task_done()
    async def modes_localization_worker(self,worker):
        loop=asyncio.get_running_loop()
        while True:
            e=await self.modes_events.get();started=time.monotonic();age=started-e["queued_mono"]
            self.state.modes_latency["association"].append(e["association_latency_ms"]);self.state.modes_latency["queue"].append(age*1000)
            try:
                if age>MODES_EVENT_STALE_S:self.state.modes_stats["events_dropped_stale"]+=1;continue
                sigma={pair:self.clock.sigma(*pair) for pair in PAIRS};clock_quality=min((self.clock.model(*p).quality for p in PAIRS),key=lambda q:{"BAD":0,"UNAVAILABLE":1,"MARGINAL":2,"PASS":3,"STRONG":4}.get(q,0));solve_started=time.monotonic();sol=await loop.run_in_executor(self.modes_executor,solve_realtime_payload,e["tdoa"],sigma,clock_quality);solve_complete=time.monotonic();self.state.modes_latency["solver"].append((solve_complete-solve_started)*1000);cl=sol["classification"];self.state.modes_stats[cl.lower()]+=1
                if cl=="BLIND_UNIQUE":
                    track_started=time.monotonic();track=await self.modes_tracker.update(e,sol);published=time.monotonic();self.state.modes_latency["track"].append((published-track_started)*1000);self.state.modes_latency["total"].append((published-e["latest_arrival_mono"])*1000);self.state.modes_mark("mlat_fix");log("modes_blind_unique",event_id=e["event_id"],df=e["df"],icao=e.get("icao"),lat=sol["lat"],lon=sol["lon"],tracked=track is not None,worker=worker)
            except Exception as exc:log("modes_localization_exception",event_id=e.get("event_id"),error=str(exc),worker=worker)
            finally:self.state.modes_event_queue_depth=self.modes_events.qsize();self.modes_events.task_done()
    async def housekeeping(self):
        while True:
            await asyncio.sleep(1);await self.tracker.expire();await self.modes_tracker.expire()
            self.association.prune();self.modes_association.prune();self.clock.prune()
            self.state.queue_depth=self.frames.qsize();self.state.event_queue_depth=self.events.qsize();self.state.modes_event_queue_depth=self.modes_events.qsize()
            self.state.modes_oldest_queued_age_s=max(0,time.monotonic()-self.modes_events._queue[0]["queued_mono"]) if self.modes_events.qsize() else 0
            self.state.modeac_buffer_entries=sum(len(d) for rows in self.association.rows.values() for d in rows.values())
            self.state.modes_buffer_entries=self.modes_association.size()
            self.state.clock_sample_entries=sum(len(x.samples) for x in self.clock.links.values())

async def run(duration=None,api_port=API_PORT,publish_df17_mlat=PUBLISH_DF17_MLAT):
    b=Backend(api_port,publish_df17_mlat);await b.start();loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT,signal.SIGTERM):
        try:loop.add_signal_handler(sig,b.stop_event.set)
        except NotImplementedError:pass
    try:
        if duration:await asyncio.wait_for(b.stop_event.wait(),duration)
        else:await b.stop_event.wait()
    except asyncio.TimeoutError:pass
    finally:await b.stop()

def main():
    p=argparse.ArgumentParser();p.add_argument("--duration",type=float);p.add_argument("--api-port",type=int,default=API_PORT);p.add_argument("--publish-df17-mlat",action="store_true",default=PUBLISH_DF17_MLAT);a=p.parse_args();asyncio.run(run(a.duration,a.api_port,a.publish_df17_mlat))
if __name__=="__main__":main()
