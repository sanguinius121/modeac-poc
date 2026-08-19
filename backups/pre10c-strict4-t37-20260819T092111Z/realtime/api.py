"""Small dependency-free REST and WebSocket server."""
import asyncio,base64,hashlib,json,time,urllib.parse
from .config import API_HOST,API_PORT,ORDER
from .state import utc

QUALITY={"LOW":0,"MEDIUM":1,"HIGH":2}
ALLOWED_ORIGINS={
    "http://127.0.0.1",
    "http://localhost",
    "http://100.100.24.4",
    "http://127.0.0.1:8088",
    "http://localhost:8088",
    "http://100.100.24.4:8088",
    "http://127.0.0.1:8089",
    "http://localhost:8089",
    "http://100.100.24.4:8089",
}
def ws_frame(obj):
    data=json.dumps(obj,separators=(",",":")).encode();n=len(data)
    if n<126:return bytes((0x81,n))+data
    if n<65536:return bytes((0x81,126))+n.to_bytes(2,"big")+data
    return bytes((0x81,127))+n.to_bytes(8,"big")+data

def cors_header(headers):
    origin=headers.get("origin")
    return f"Access-Control-Allow-Origin: {origin}\r\nVary: Origin\r\n" if origin in ALLOWED_ORIGINS else ""

class APIServer:
    def __init__(self,state,tracker,clock,modes_tracker=None,host=API_HOST,port=API_PORT):self.state=state;self.tracker=tracker;self.clock=clock;self.modes_tracker=modes_tracker;self.host=host;self.port=port;self.server=None
    async def start(self):self.server=await asyncio.start_server(self.handle,self.host,self.port)
    async def stop(self):
        if self.server:self.server.close();await self.server.wait_closed()
    def snapshot(self,path,query):
        now=time.time()
        if path=="/health":return {"status":"ok","uptime_s":now-self.state.started,"receivers_connected":sum(x.connected for x in self.state.receivers.values()),"strict_4rx_enabled":True,"modes_strict_4rx_enabled":self.modes_tracker is not None}
        if path=="/api/receivers":return {"receivers":[self.state.receivers[s].public(now) for s in ORDER]}
        if path=="/api/clocks":return {"links":[x.public() for x in self.clock.links.values()]}
        if path=="/api/modeac/tracks":
            minimum=urllib.parse.parse_qs(query).get("min_quality",["LOW"])[0].upper();threshold=QUALITY.get(minimum,0);return {"now":utc(),"tracks":[self.tracker.public(x,now) for x in self.state.tracks.values() if QUALITY.get(x["quality"],0)>=threshold]}
        if path=="/api/modeac/stats":
            lat=sorted(self.state.latency_ms);pct=lambda p:lat[round((len(lat)-1)*p)] if lat else None
            return {"uptime_s":now-self.state.started,"type1_rate_per_receiver":{s:self.state.receivers[s].public(now)["type1_rate_s"] for s in ORDER},**self.state.rates(),"totals":{"strict_4rx":self.state.stats["strict_4rx"],"ambiguous_association":self.state.stats["ambiguous_association"],"inconsistent_association":self.state.stats["inconsistent_association"],"blind_unique":self.state.stats["blind_unique"],"blind_multiple":self.state.stats["blind_multiple"],"blind_inconsistent":self.state.stats["blind_inconsistent"]},"active_tracks":len(self.state.tracks),"confirmed_tracks":sum(x["state"]=="CONFIRMED" for x in self.state.tracks.values()),"high_quality_tracks":sum(x["quality"]=="HIGH" for x in self.state.tracks.values()),"processing_latency_ms":{"p50":pct(.5),"p90":pct(.9),"p95":pct(.95)},"buffers":{"frame_queue_depth":self.state.queue_depth,"event_queue_depth":self.state.event_queue_depth,"modeac_entries":self.state.modeac_buffer_entries,"clock_samples":self.state.clock_sample_entries},"frames_dropped_queue":self.state.stats["frames_dropped_queue"],"events_dropped_queue":self.state.stats["events_dropped_queue"]}
        if path=="/api/modes/tracks":
            if self.modes_tracker is None:return {"now":utc(),"tracks":[]}
            minimum=urllib.parse.parse_qs(query).get("min_quality",["LOW"])[0].upper();threshold=QUALITY.get(minimum,0);return {"now":utc(),"tracks":[self.modes_tracker.public(x,now) for x in self.state.modes_tracks.values() if QUALITY.get(x["quality"],0)>=threshold]}
        if path=="/api/modes/stats":
            def metrics(name):
                values=sorted(self.state.modes_latency[name]);p=lambda q:values[round((len(values)-1)*q)] if values else None
                return {"count":len(values),"p50":p(.5),"p90":p(.9),"p95":p(.95),"p99":p(.99)}
            receivers={s:self.state.receivers[s].public(now) for s in ORDER}
            return {"uptime_s":now-self.state.started,"type2_rate_per_receiver":{s:x["type2_rate_s"] for s,x in receivers.items()},"type3_rate_per_receiver":{s:x["type3_rate_s"] for s,x in receivers.items()},"df_distribution":{k[3:]:v for k,v in self.state.modes_stats.items() if k.startswith("df_")},**self.state.modes_rates(),"totals":{"clustered":self.state.modes_stats["clustered"],"strict_4rx":self.state.modes_stats["strict_4rx"],"mlat_fix":self.state.modes_stats["mlat_fix"],"three_rx_alt":self.state.modes_stats["three_rx_alt"],"ambiguous_association":self.state.modes_stats["ambiguous_association"],"inconsistent_association":self.state.modes_stats["inconsistent_association"],"clock_not_ready":self.state.modes_stats["clock_not_ready"],"untrusted_identity":self.state.modes_stats["untrusted_identity"],"events_dropped_queue":self.state.modes_stats["events_dropped_queue"],"events_dropped_stale":self.state.modes_stats["events_dropped_stale"]},"active_tracks":len(self.state.modes_tracks),"confirmed_tracks":sum(x["state"]=="CONFIRMED" for x in self.state.modes_tracks.values()),"latency_ms":{k:metrics(k) for k in self.state.modes_latency},"buffers":{"event_queue_depth":self.state.modes_event_queue_depth,"event_queue_high_water":self.state.modes_event_queue_high_water,"oldest_queued_age_s":self.state.modes_oldest_queued_age_s,"association_entries":self.state.modes_buffer_entries}}
        return None
    async def handle(self,reader,writer):
        try:
            head=await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"),5);lines=head.decode("latin1").split("\r\n");method,target,_=lines[0].split();headers={k.strip().lower():v.strip() for k,v in (x.split(":",1) for x in lines[1:] if ":" in x)};u=urllib.parse.urlsplit(target)
            if u.path=="/ws/modeac" and headers.get("upgrade","").lower()=="websocket":await self.websocket(writer,headers,False);return
            if u.path=="/ws/modes" and headers.get("upgrade","").lower()=="websocket":await self.websocket(writer,headers,True);return
            body=self.snapshot(u.path,u.query)
            if method!="GET" or body is None:status="404 Not Found";body={"error":"not found"}
            else:status="200 OK"
            raw=json.dumps(body).encode();writer.write(f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\n{cors_header(headers)}Content-Length: {len(raw)}\r\nConnection: close\r\n\r\n".encode()+raw);await writer.drain()
        except Exception:pass
        finally:
            if not writer.is_closing():writer.close()
    async def websocket(self,writer,headers,modes=False):
        key=headers.get("sec-websocket-key","");accept=base64.b64encode(hashlib.sha1((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode();writer.write(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode());await writer.drain();q=asyncio.Queue(maxsize=1000);subscribers=self.state.modes_subscribers if modes else self.state.subscribers;subscribers.add(q)
        try:
            tracker=self.modes_tracker if modes else self.tracker;tracks=self.state.modes_tracks if modes else self.state.tracks;writer.write(ws_frame({"type":"snapshot","tracks":[tracker.public(x) for x in tracks.values()] if tracker else []}));await writer.drain()
            while True:writer.write(ws_frame(await q.get()));await writer.drain()
        except Exception:pass
        finally:subscribers.discard(q)
