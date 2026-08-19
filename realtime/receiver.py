"""Reconnect-safe asynchronous TCP Beast listeners."""
import asyncio,time
from .beast import BeastParser,decode_frame

class ReceiverServer:
    def __init__(self,station,port,state,queue,logger):
        self.station=station;self.port=port;self.state=state;self.queue=queue;self.log=logger;self.server=None;self.writer=None

    async def start(self):
        self.server=await asyncio.start_server(self.handle,"0.0.0.0",self.port)

    async def stop(self):
        if self.writer:self.writer.close()
        if self.server:self.server.close();await self.server.wait_closed()

    async def handle(self,reader,writer):
        peer=writer.get_extra_info("peername");rs=self.state.receivers[self.station]
        if self.writer and not self.writer.is_closing():self.writer.close()
        self.writer=writer;rs.connect(peer);self.log("receiver_connected",station=self.station,remote=str(peer))
        parser=BeastParser()
        try:
            while True:
                data=await reader.read(65536)
                if not data:break
                mono=time.monotonic();utc=time.time();before=parser.parse_errors
                for typ,raw in parser.feed(data):
                    frame=decode_frame(self.station,typ,raw,mono,utc);rs.frame(frame)
                    try:self.queue.put_nowait(frame)
                    except asyncio.QueueFull:self.state.stats["frames_dropped_queue"]+=1
                rs.parse_errors+=parser.parse_errors-before
        except Exception as exc:self.log("receiver_exception",station=self.station,error=str(exc))
        finally:
            # A replaced socket can finish after the new one is already active.
            if self.writer is writer:
                rs.disconnect();self.writer=None
            self.log("receiver_disconnected",station=self.station,remote=str(peer));writer.close()
