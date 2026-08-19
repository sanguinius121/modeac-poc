#!/usr/bin/env python3
"""Read-only sampler for a running Phase 8C acceptance window."""
import argparse,json,os,time,urllib.request
from pathlib import Path

def api(path):
    with urllib.request.urlopen("http://127.0.0.1:8090"+path,timeout=3) as response:return json.load(response)
def descendants(pid):
    result=[pid];pending=[pid]
    while pending:
        current=pending.pop()
        try:
            children=[int(x) for x in Path("/proc/%d/task/%d/children"%(current,current)).read_text().split()]
        except (OSError,ValueError):children=[]
        result.extend(children);pending.extend(children)
    return result
def proc(pid):
    ticks=rss=0;pids=descendants(pid)
    for member in pids:
        try:
            with open("/proc/%d/stat"%member) as source:fields=source.read().split()
            with open("/proc/%d/status"%member) as source:status=dict(line.split(":",1) for line in source if ":" in line)
            ticks+=int(fields[13])+int(fields[14]);rss+=int(status["VmRSS"].split()[0])
        except (OSError,KeyError):pass
    return {"cpu_ticks":ticks,"rss_kib":rss,"process_count":len(pids)}
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--pid",type=int,required=True);parser.add_argument("--duration",type=float,default=540);parser.add_argument("--interval",type=float,default=10);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args();samples=[];clock_ticks=os.sysconf("SC_CLK_TCK");previous=None;deadline=time.monotonic()+args.duration
    while time.monotonic()<deadline:
        started=time.monotonic()
        try:
            current=proc(args.pid);cpu=None
            if previous:cpu=(current["cpu_ticks"]-previous[0])/clock_ticks/(started-previous[1])*100
            previous=(current["cpu_ticks"],started);samples.append({"sample_utc":time.time(),"cpu_percent_one_core":cpu,"rss_kib":current["rss_kib"],"process_count":current["process_count"],"health":api("/health"),"modeac":api("/api/modeac/stats"),"modes":api("/api/modes/stats")})
        except Exception as exc:samples.append({"sample_utc":time.time(),"error":str(exc)})
        time.sleep(max(0,args.interval-(time.monotonic()-started)))
    good=[x for x in samples if "error" not in x];cpu=[x["cpu_percent_one_core"] for x in good if x["cpu_percent_one_core"] is not None];rss=[x["rss_kib"] for x in good]
    result={"samples":samples,"resource_summary":{"cpu_percent_one_core":{"min":min(cpu) if cpu else None,"mean":sum(cpu)/len(cpu) if cpu else None,"max":max(cpu) if cpu else None},"rss_mib":{"min":min(rss)/1024 if rss else None,"mean":sum(rss)/len(rss)/1024 if rss else None,"max":max(rss)/1024 if rss else None}},"final":good[-1] if good else None}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+"\n")
if __name__=="__main__":main()
