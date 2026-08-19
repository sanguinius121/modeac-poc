#!/usr/bin/env python3
"""Summarize one frozen pre-10C backend log and post-hoc ADS-B snapshots."""
import argparse,collections,datetime as dt,json,math,statistics
from pathlib import Path

R=6371000.0
def epoch(value):return dt.datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()
def distance(a,b):
    p1,p2=math.radians(a[0]),math.radians(b[0]);dp=math.radians(b[0]-a[0]);dl=math.radians(b[1]-a[1]);h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2;return 2*R*math.asin(math.sqrt(h))
def percentile(values,q):
    if not values:return None
    x=sorted(values);k=(len(x)-1)*q;a=math.floor(k);b=math.ceil(k);return x[a] if a==b else x[a]*(b-k)+x[b]*(k-a)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("log",type=Path);parser.add_argument("truth",type=Path);parser.add_argument("--output",type=Path,required=True);args=parser.parse_args()
    events=[]
    for line in args.log.read_text(errors="replace").splitlines():
        try:events.append(json.loads(line))
        except json.JSONDecodeError:pass
    strict=[x for x in events if x.get("event")=="modes_strict_4rx"]
    solved=[x for x in events if x.get("event")=="modes_solver_result"]
    modeac_unique=[x for x in events if x.get("event")=="blind_unique"]
    strict_df=collections.Counter(str(x["df"]) for x in strict)
    solver_df={}
    for item in solved:
        row=solver_df.setdefault(str(item["df"]),collections.Counter());row["attempts"]+=1;row[item["classification"]]+=1
    truth=json.loads(args.truth.read_text());by_icao=collections.defaultdict(list)
    for sample in truth.get("samples",[]):
        for position in sample["positions"]:by_icao[position["icao"]].append(position)
    matches=[]
    for item in solved:
        if item.get("df")!=17 or item.get("classification")!="BLIND_UNIQUE" or item.get("lat") is None or not item.get("icao"):continue
        measurement=epoch(item["measurement_time"]);candidates=by_icao.get(item["icao"].lower(),[])
        if not candidates:continue
        reference=min(candidates,key=lambda x:abs(x["measurement_epoch"]-measurement));delta=abs(reference["measurement_epoch"]-measurement)
        if delta>2.0:continue
        matches.append({"event_id":item["event_id"],"icao":item["icao"],"time_delta_s":delta,"horizontal_error_m":distance((item["lat"],item["lon"]),(reference["lat"],reference["lon"])),"mlat_lat":item["lat"],"mlat_lon":item["lon"],"truth_lat":reference["lat"],"truth_lon":reference["lon"]})
    errors=[x["horizontal_error_m"] for x in matches]
    result={"event_count":len(events),"modeac":{"strict_4rx":sum(x.get("event")=="strict_4rx" for x in events),"blind_unique":len(modeac_unique),"blind_multiple":sum(x.get("event")=="blind_multiple" for x in events),"blind_inconsistent":sum(x.get("event")=="blind_inconsistent" for x in events)},"modes":{"strict_4rx":len(strict),"strict_by_df":dict(sorted(strict_df.items(),key=lambda x:int(x[0]))),"solver_by_df":{k:dict(v) for k,v in sorted(solver_df.items(),key=lambda x:int(x[0]))},"solver_attempts":len(solved),"classifications":dict(collections.Counter(x["classification"] for x in solved))},"df17_truth":{"matched_count":len(matches),"time_tolerance_s":2.0,"horizontal_error_m":{"p50":percentile(errors,.5),"p90":percentile(errors,.9),"p95":percentile(errors,.95),"p99":percentile(errors,.99)},"matches":matches}}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+"\n")

if __name__=="__main__":main()
