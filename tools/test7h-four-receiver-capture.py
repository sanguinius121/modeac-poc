#!/usr/bin/env python3
"""Preflight and passively capture one synchronized Test 7H window at four receivers."""
import argparse,csv,datetime as dt,importlib.util,json,shlex,subprocess,time
from collections import Counter
from pathlib import Path

ROOT=Path("/home/mlatserver/modeac-poc")
KEY=Path("/home/mlatserver/.ssh/modeac_test6_ed25519")
CAPTURE=ROOT/"tools/test6-beast-capture.py"
STATIONS={"T37":"client0125@100.102.185.43","Dao_Cai_chien":"phiyb@100.74.130.53",
          "QK4":"mlat-client-1@100.119.31.100","BachLongVi":"mlat-client-6@100.120.90.84"}
SSH=["-i",str(KEY),"-o","BatchMode=yes","-o","ConnectTimeout=10","-o","StrictHostKeyChecking=accept-new"]

def run(cmd,check=True,timeout=None):
    return subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=check,timeout=timeout)

def ssh(host,command,**kw): return run(["ssh",*SSH,host,command],**kw)

def preflight(station,host):
    sample=('import socket,time; s=socket.create_connection(("127.0.0.1",30005),5); '
            's.settimeout(.5); d=b""; end=time.time()+3; '
            'exec("while time.time()<end:\\n try:d+=s.recv(65536)\\n except socket.timeout:pass"); '
            'print(len(d),d.count(bytes((26,49))),d.count(bytes((26,50))),d.count(bytes((26,51))))')
    command=("set -eu; printf 'ntp='; timedatectl show -p NTPSynchronized --value; "
             "python3 -c 'import socket;s=socket.create_connection((\"127.0.0.1\",30005),5);s.close();print(\"port=ok\")'; "
             "df -Pk . | tail -1; python3 -c "+shlex.quote(sample))
    p=ssh(host,command,check=False,timeout=20); lines=p.stdout.strip().splitlines()
    out={"station":station,"host":host,"exit_code":p.returncode,"output":p.stdout}
    try:
        disk=lines[2].split(); vals=[int(x) for x in lines[3].split()]
        out.update(ntp_synchronized=lines[0].strip()=="ntp=yes",port_listening=lines[1].strip()=="port=ok",
                   disk_available_kb=int(disk[3]),sample_bytes=vals[0],sample_type1=vals[1],sample_type2=vals[2],sample_type3=vals[3])
    except (IndexError,ValueError): out["parse_error"]=True
    out["passed"]=(p.returncode==0 and out.get("ntp_synchronized") and out.get("port_listening") and
                   out.get("disk_available_kb",0)>1_000_000 and out.get("sample_type1",0)>0 and
                   out.get("sample_type2",0)+out.get("sample_type3",0)>0)
    return out

def inspect(path,station):
    counts=Counter(); names=Counter(); first=last=None; lines=0
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            lines+=1; names[row["station"]]+=1; counts[row["frame_kind"]]+=1
            if int(row["timestamp_corrected"])==0: counts["timestamp_zero"]+=1
            now=int(row["recv_utc_ns"]); first=now if first is None else min(first,now); last=now if last is None else max(last,now)
    return {"path":str(path),"size_bytes":path.stat().st_size,"data_lines":lines,"stations":dict(names),
            "station_valid":set(names)=={station},"first_utc_ns":first,"last_utc_ns":last,
            "span_s":(last-first)/1e9 if first is not None else 0,"counts":dict(counts)}

def collect_existing(run_id,series_dir):
    run_dir=ROOT/series_dir/run_id; metadata=json.loads((run_dir/"logs/run-metadata.json").read_text());remote=metadata["remote"]
    log_path=run_dir/"logs/orchestration.log"
    def log(msg):
        stamp=dt.datetime.now(dt.timezone.utc).isoformat();log_path.open("a").write(f"{stamp} {msg}\n");print(msg,flush=True)
    results={}
    for station,info in remote.items():
        status=ssh(info["host"],f"if kill -0 {shlex.quote(info['pid'])} 2>/dev/null; then echo running; else echo finished; fi; tail -20 {shlex.quote(info['log'])}",check=False,timeout=20)
        (run_dir/f"logs/{station}-remote.log").write_text(status.stdout);local=run_dir/"captures"/f"modeac-{station}.csv"
        transfer=run(["scp",*SSH,f"{info['host']}:{info['csv']}",str(local)],check=False,timeout=900)
        if transfer.returncode:log(f"collection_failed station={station} output={transfer.stdout.strip()}");continue
        results[station]=inspect(local,station);log(f"collected station={station} lines={results[station]['data_lines']}")
    overlap=(min(x["last_utc_ns"] for x in results.values())-max(x["first_utc_ns"] for x in results.values()))/1e9 if len(results)==4 else 0
    accepted=(len(results)==4 and overlap>=595 and all(x["station_valid"] and x["counts"].get("modeac",0)>0 for x in results.values()))
    verification={"run_id":run_id,"scheduled_start_ns":metadata["scheduled_start_ns"],"scheduled_start_utc":metadata["scheduled_start_utc"],"duration_s":600,
                  "stations":results,"common_overlap_s":overlap,"capture_accepted":accepted}
    (run_dir/"reports/capture-verification.json").write_text(json.dumps(verification,indent=2));log(f"common_overlap_s={overlap:.6f} capture_accepted={accepted}")
    print(run_dir)
    if not accepted:raise SystemExit("capture verification failed; completed remote captures preserved")

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--duration",type=int,default=600)
    p.add_argument("--lead-seconds",type=int,default=45); p.add_argument("--run-id");p.add_argument("--collect-run-id");p.add_argument("--series-dir",default="test7h");args=p.parse_args()
    if Path(args.series_dir).name!=args.series_dir or args.series_dir in (".",".."):p.error("--series-dir must be one directory name")
    if args.collect_run_id:collect_existing(args.collect_run_id,args.series_dir);return
    if args.duration!=600: p.error("Test 7H requires exactly --duration 600")
    if not KEY.is_file() or not CAPTURE.is_file(): raise SystemExit("dedicated key or capture helper missing")
    run_id=args.run_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ"); run_dir=ROOT/args.series_dir/run_id
    for sub in ("preflight","captures","pairwise","logs","reports","maps"): (run_dir/sub).mkdir(parents=True,exist_ok=False)
    log_path=run_dir/"logs/orchestration.log"
    def log(msg):
        stamp=dt.datetime.now(dt.timezone.utc).isoformat(); log_path.open("a").write(f"{stamp} {msg}\n"); print(msg,flush=True)
    log(f"run_id={run_id} preflight_start")
    checks=[preflight(s,h) for s,h in STATIONS.items()]; (run_dir/"preflight/preflight.json").write_text(json.dumps(checks,indent=2))
    for x in checks: log(f"preflight {x['station']} passed={x['passed']} type1={x.get('sample_type1',0)} modes={x.get('sample_type2',0)+x.get('sample_type3',0)}")
    if not all(x["passed"] for x in checks): raise SystemExit("preflight failed; capture not started")
    start_ns=time.time_ns()+args.lead_seconds*1_000_000_000; scheduled=dt.datetime.fromtimestamp(start_ns/1e9,dt.timezone.utc).isoformat()
    log(f"scheduled_start={scheduled} duration_s={args.duration}"); remote={}
    for station,host in STATIONS.items():
        script=f"modeac-test7h-capture-{run_id}.py"; name=f"modeac-test7h-{run_id}-{station}.csv"; rlog=f"modeac-test7h-{run_id}-{station}.log"
        run(["scp",*SSH,str(CAPTURE),f"{host}:{script}"],timeout=30)
        command=(f"test ! -e {shlex.quote(name)}; nohup python3 {shlex.quote(script)} --station {shlex.quote(station)} "
                 f"--output {shlex.quote(name)} --start-at-ns {start_ns} --duration 600 > {shlex.quote(rlog)} 2>&1 < /dev/null & echo $!")
        pid=ssh(host,command,timeout=20).stdout.strip(); remote[station]={"host":host,"script":script,"csv":name,"log":rlog,"pid":pid}; log(f"launched station={station} pid={pid}")
    metadata={"run_id":run_id,"scheduled_start_ns":start_ns,"scheduled_start_utc":scheduled,"duration_s":600,"remote":remote}
    (run_dir/"logs/run-metadata.json").write_text(json.dumps(metadata,indent=2))
    wait=max(0,(start_ns-time.time_ns())/1e9)+610; log(f"waiting_seconds={wait:.1f}"); time.sleep(wait)
    results={}
    for station,info in remote.items():
        status=ssh(info["host"],f"if kill -0 {shlex.quote(info['pid'])} 2>/dev/null; then echo running; else echo finished; fi; tail -20 {shlex.quote(info['log'])}",check=False,timeout=20)
        (run_dir/f"logs/{station}-remote.log").write_text(status.stdout); local=run_dir/"captures"/f"modeac-{station}.csv"
        transfer=run(["scp",*SSH,f"{info['host']}:{info['csv']}",str(local)],check=False,timeout=900)
        if transfer.returncode: log(f"collection_failed station={station} output={transfer.stdout.strip()}"); continue
        results[station]=inspect(local,station); log(f"collected station={station} lines={results[station]['data_lines']}")
    overlap=(min(x["last_utc_ns"] for x in results.values())-max(x["first_utc_ns"] for x in results.values()))/1e9 if len(results)==4 else 0
    accepted=(len(results)==4 and overlap>=595 and all(x["station_valid"] and x["counts"].get("modeac",0)>0 for x in results.values()))
    verification={"run_id":run_id,"scheduled_start_ns":start_ns,"scheduled_start_utc":scheduled,"duration_s":600,
                  "stations":results,"common_overlap_s":overlap,"capture_accepted":accepted}
    (run_dir/"reports/capture-verification.json").write_text(json.dumps(verification,indent=2)); log(f"common_overlap_s={overlap:.6f} capture_accepted={accepted}")
    print(run_dir)
    if not accepted: raise SystemExit("capture verification failed; successful captures preserved")

if __name__=="__main__": main()
