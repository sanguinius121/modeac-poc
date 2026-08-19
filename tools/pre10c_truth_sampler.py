#!/usr/bin/env python3
"""Read-only ADS-B snapshots for post-hoc, time-aligned DF17 diagnostics."""
import argparse,json,time,urllib.request
from pathlib import Path

def load_json(path):
    with open(path) as source:return json.load(source)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration",type=float,required=True)
    parser.add_argument("--interval",type=float,default=0.5)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();samples=[];errors=[];deadline=time.monotonic()+args.duration
    while time.monotonic()<deadline:
        started=time.monotonic()
        try:
            payload=load_json("/run/readsb/aircraft.json");now=float(payload["now"]);positions=[]
            for aircraft in payload.get("aircraft",[]):
                if not all(key in aircraft for key in ("hex","lat","lon","seen_pos")):continue
                positions.append({"icao":aircraft["hex"].lower(),"lat":aircraft["lat"],"lon":aircraft["lon"],"measurement_epoch":now-float(aircraft["seen_pos"]),"seen_pos_s":aircraft["seen_pos"]})
            samples.append({"sample_epoch":time.time(),"readsb_now":now,"positions":positions})
        except Exception as exc:errors.append({"epoch":time.time(),"error":repr(exc)})
        time.sleep(max(0,args.interval-(time.monotonic()-started)))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps({"duration_s":args.duration,"interval_s":args.interval,"samples":samples,"errors":errors},indent=2)+"\n")

if __name__=="__main__":main()
