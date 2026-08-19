#!/usr/bin/env python3
"""Monitor the real tar1090 overlay page, PoC backend, and production aircraft feed."""
import argparse,base64,json,os,socket,struct,time,urllib.request
from pathlib import Path

class Bidi:
    def __init__(self,port,page_prefix):
        self.socket=socket.create_connection(("127.0.0.1",port),5);self.socket.settimeout(15);self.next_id=1;self.events=[]
        key=base64.b64encode(os.urandom(16)).decode();request=("GET /session HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: webdriver-bidi\r\n\r\n"%(port,key));self.socket.sendall(request.encode());response=self.socket.recv(4096)
        if b"101 Switching Protocols" not in response:raise RuntimeError(response.decode("latin1","replace"))
        self.command("session.new",{"capabilities":{"alwaysMatch":{}}})
        tree=self.command("browsingContext.getTree",{})["contexts"];self.context=next(x["context"] for x in tree if x["url"].startswith(page_prefix))
        self.command("session.subscribe",{"events":["log.entryAdded"],"contexts":[self.context]})
    def send(self,obj):
        data=json.dumps(obj,separators=(",",":")).encode();mask=os.urandom(4);n=len(data);header=bytes((0x81,0x80|(n if n<126 else 126)))
        if n>=126:header+=struct.pack("!H",n)
        self.socket.sendall(header+mask+bytes(value^mask[index%4] for index,value in enumerate(data)))
    def receive(self):
        head=self._read(2);opcode=head[0]&15;length=head[1]&127
        if length==126:length=struct.unpack("!H",self._read(2))[0]
        elif length==127:length=struct.unpack("!Q",self._read(8))[0]
        data=self._read(length)
        if opcode==9:self.socket.sendall(bytes((0x8A,len(data)))+data);return self.receive()
        if opcode==8:raise EOFError("BiDi close frame")
        return json.loads(data)
    def _read(self,n):
        data=b""
        while len(data)<n:data+=self.socket.recv(n-len(data))
        return data
    def command(self,method,params):
        command_id=self.next_id;self.next_id+=1;self.send({"id":command_id,"method":method,"params":params})
        while True:
            result=self.receive()
            if result.get("id")==command_id:
                if result.get("type")=="error":raise RuntimeError(result)
                return result["result"]
            self.events.append(result)
    def evaluate(self,expression):
        response=self.command("script.evaluate",{"expression":expression,"target":{"context":self.context},"awaitPromise":True,"resultOwnership":"none"})
        remote=response["result"]
        if remote.get("type")=="string":return json.loads(remote["value"])
        return remote

def api(base,path):
    with urllib.request.urlopen(base+path,timeout=4) as response:return json.load(response)
def descendants(pid):
    result=[pid];pending=[pid]
    while pending:
        current=pending.pop()
        try:children=[int(x) for x in Path("/proc/%d/task/%d/children"%(current,current)).read_text().split()]
        except (OSError,ValueError):children=[]
        result.extend(children);pending.extend(children)
    return result
def resources(pid):
    ticks=rss=0;pids=descendants(pid)
    for member in pids:
        try:
            fields=Path("/proc/%d/stat"%member).read_text().split();status=dict(line.split(":",1) for line in Path("/proc/%d/status"%member).read_text().splitlines() if ":" in line);ticks+=int(fields[13])+int(fields[14]);rss+=int(status["VmRSS"].split()[0])
        except (OSError,KeyError,ValueError):pass
    return {"cpu_ticks":ticks,"rss_kib":rss,"process_count":len(pids)}
def summary(samples,key):
    values=[x[key] for x in samples if x.get(key) is not None];return {"min":min(values) if values else None,"mean":sum(values)/len(values) if values else None,"max":max(values) if values else None}

PAGE_EXPRESSION="""JSON.stringify((()=>{const titles=[];if(typeof layers_group!=='undefined')ol.control.LayerSwitcher.forEachRecursive(layers_group,l=>{if(l.get('title'))titles.push(l.get('title'));});return {overlay:window.pocMlatDiagnostics?window.pocMlatDiagnostics():null,status:document.getElementById('poc-mlat-status')?.innerText||null,layerTitles:titles,productionPlaneCount:(typeof g!=='undefined'&&g.planesOrdered)?g.planesOrdered.length:null};})())"""

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--backend-pid",type=int,required=True);parser.add_argument("--firefox-pid",type=int,required=True);parser.add_argument("--bidi-port",type=int,default=9223);parser.add_argument("--page-prefix",default="http://127.0.0.1:8089");parser.add_argument("--duration",type=float,required=True);parser.add_argument("--interval",type=float,default=10);parser.add_argument("--phase",required=True);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args();bidi=Bidi(args.bidi_port,args.page_prefix);samples=[];previous={};clock_ticks=os.sysconf("SC_CLK_TCK");deadline=time.monotonic()+args.duration;started_utc=time.time()
    while time.monotonic()<deadline:
        started=time.monotonic();sample={"sample_utc":time.time()}
        try:
            for name,pid in (("backend",args.backend_pid),("firefox",args.firefox_pid)):
                current=resources(pid);old=previous.get(name);sample[name+"_cpu_percent"]=(current["cpu_ticks"]-old[0])/clock_ticks/(started-old[1])*100 if old else None;sample[name+"_rss_mib"]=current["rss_kib"]/1024;sample[name+"_process_count"]=current["process_count"];previous[name]=(current["cpu_ticks"],started)
            sample["page"]=bidi.evaluate(PAGE_EXPRESSION);sample["health"]=api("http://127.0.0.1:8090","/health");sample["receivers"]=api("http://127.0.0.1:8090","/api/receivers");sample["clocks"]=api("http://127.0.0.1:8090","/api/clocks");sample["modeac"]=api("http://127.0.0.1:8090","/api/modeac/stats");sample["modes"]=api("http://127.0.0.1:8090","/api/modes/stats");sample["production"]=api("http://127.0.0.1/tar1090","/data/aircraft.json")
            aircraft=sample["production"].pop("aircraft",[]);sample["production"]["aircraft_count"]=len(aircraft);sample["production"]["position_count"]=sum("lat" in item and "lon" in item for item in aircraft);sample["production"]["mlat_position_count"]=sum("lat" in item.get("mlat",[]) for item in aircraft)
        except Exception as exc:sample["monitor_error"]=repr(exc)
        samples.append(sample);time.sleep(max(0,args.interval-(time.monotonic()-started)))
    good=[x for x in samples if "monitor_error" not in x];logs=[x for x in bidi.events if x.get("method")=="log.entryAdded"];errors=[x for x in logs if x.get("params",{}).get("entry",{}).get("level") in ("error","fatal")];result={"phase":args.phase,"started_utc":started_utc,"duration_s":args.duration,"sample_count":len(samples),"monitor_errors":len(samples)-len(good),"resource_summary":{"backend_cpu_percent":summary(good,"backend_cpu_percent"),"backend_rss_mib":summary(good,"backend_rss_mib"),"firefox_cpu_percent":summary(good,"firefox_cpu_percent"),"firefox_rss_mib":summary(good,"firefox_rss_mib")},"browser_log_events":len(logs),"browser_error_events":errors,"samples":samples,"final":good[-1] if good else None}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+"\n")
    try:bidi.command("session.end",{})
    except Exception:pass
if __name__=="__main__":main()
