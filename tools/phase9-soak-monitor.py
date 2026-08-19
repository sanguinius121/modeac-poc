#!/usr/bin/env python3
"""Monitor the real Phase 9 Firefox page and unified backend via WebDriver BiDi."""
import argparse,base64,hashlib,json,os,socket,struct,time,urllib.request
from pathlib import Path

class Bidi:
    def __init__(self,host="127.0.0.1",port=9222):
        self.socket=socket.create_connection((host,port),5);self.socket.settimeout(10);self.next_id=1;self.events=[]
        key=base64.b64encode(os.urandom(16)).decode();request=("GET /session HTTP/1.1\r\nHost: %s:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: webdriver-bidi\r\nOrigin: http://%s:%d\r\n\r\n"%(host,port,key,host,port));self.socket.sendall(request.encode());response=self.socket.recv(4096)
        if b"101 Switching Protocols" not in response:raise RuntimeError(response.decode("latin1","replace"))
        self.command("session.new",{"capabilities":{"alwaysMatch":{}}})
        tree=self.command("browsingContext.getTree",{})["contexts"];self.context=next(x["context"] for x in tree if x["url"].startswith("http://127.0.0.1:8088"))
        self.command("session.subscribe",{"events":["log.entryAdded"],"contexts":[self.context]})
    def send(self,obj):
        data=json.dumps(obj,separators=(",",":")).encode();mask=os.urandom(4);n=len(data);header=bytes((0x81,0x80|(n if n<126 else 126)))
        if n>=126:header+=struct.pack("!H",n)
        self.socket.sendall(header+mask+bytes(value^mask[index%4] for index,value in enumerate(data)))
    def receive(self):
        head=self.socket.recv(2)
        if not head:raise EOFError("BiDi closed")
        opcode=head[0]&15;length=head[1]&127
        if length==126:length=struct.unpack("!H",self._read(2))[0]
        elif length==127:length=struct.unpack("!Q",self._read(8))[0]
        data=self._read(length)
        if opcode==9:self._pong(data);return self.receive()
        if opcode==8:raise EOFError("BiDi close frame")
        return json.loads(data)
    def _read(self,n):
        data=b""
        while len(data)<n:data+=self.socket.recv(n-len(data))
        return data
    def _pong(self,data):self.socket.sendall(bytes((0x8A,len(data)))+data)
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

def api(path):
    with urllib.request.urlopen("http://127.0.0.1:8090"+path,timeout=3) as response:return json.load(response)
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
        except (OSError,KeyError):pass
    return {"cpu_ticks":ticks,"rss_kib":rss,"process_count":len(pids)}
def summary(samples,key):
    values=[x[key] for x in samples if x.get(key) is not None];return {"min":min(values) if values else None,"mean":sum(values)/len(values) if values else None,"max":max(values) if values else None}

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--backend-pid",type=int,required=True);parser.add_argument("--firefox-pid",type=int,required=True);parser.add_argument("--duration",type=float,default=1800);parser.add_argument("--interval",type=float,default=10);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args();bidi=Bidi();samples=[];previous={};clock_ticks=os.sysconf("SC_CLK_TCK");deadline=time.monotonic()+args.duration
    while time.monotonic()<deadline:
        started=time.monotonic();sample={"sample_utc":time.time()}
        try:
            for name,pid in (("backend",args.backend_pid),("firefox",args.firefox_pid)):
                current=resources(pid);old=previous.get(name);sample[name+"_cpu_percent"]=(current["cpu_ticks"]-old[0])/clock_ticks/(started-old[1])*100 if old else None;sample[name+"_rss_mib"]=current["rss_kib"]/1024;sample[name+"_process_count"]=current["process_count"];previous[name]=(current["cpu_ticks"],started)
            sample["page"]=bidi.evaluate("JSON.stringify(window.phase9Diagnostics ? window.phase9Diagnostics() : {notReady:true})")
            sample["health"]=api("/health");sample["receivers"]=api("/api/receivers");sample["clocks"]=api("/api/clocks");sample["modeac"]=api("/api/modeac/stats");sample["modes"]=api("/api/modes/stats")
        except Exception as exc:sample["monitor_error"]=repr(exc)
        samples.append(sample);time.sleep(max(0,args.interval-(time.monotonic()-started)))
    good=[x for x in samples if "monitor_error" not in x];logs=[x for x in bidi.events if x.get("method")=="log.entryAdded"];errors=[x for x in logs if x.get("params",{}).get("entry",{}).get("level") in ("error","fatal")];result={"duration_s":args.duration,"sample_count":len(samples),"monitor_errors":len(samples)-len(good),"resource_summary":{"backend_cpu_percent":summary(good,"backend_cpu_percent"),"backend_rss_mib":summary(good,"backend_rss_mib"),"firefox_cpu_percent":summary(good,"firefox_cpu_percent"),"firefox_rss_mib":summary(good,"firefox_rss_mib")},"browser_log_events":len(logs),"browser_error_events":errors,"samples":samples,"final":good[-1] if good else None}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+"\n")
    frozen=args.output.parent/"phase9-cotracks-frozen.json";frozen.write_text(json.dumps((result.get("final") or {}).get("page",{}).get("cotrackObserved",[]),indent=2,sort_keys=True)+"\n");digest=hashlib.sha256(frozen.read_bytes()).hexdigest();(args.output.parent/"phase9-cotracks-freeze.sha256").write_text(digest+"  "+frozen.name+"\n")
    try:bidi.command("session.end",{})
    except Exception:pass
if __name__=="__main__":main()
