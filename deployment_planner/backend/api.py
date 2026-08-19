"""Dependency-free HTTP/JSON and static server for the planner."""
import argparse,cgi,io,json,mimetypes
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from .models import AnalyzeRequest,Receiver,ValidationError
from .geometry_engine import analyze,analyze_4ofn
from .assessment import build_assessment
from .coverage_area import receiver_coverage_summary
from ..reception import outline_store
from ..reception.outline import MAX_UPLOAD_BYTES,OutlineError

ROOT=Path(__file__).resolve().parents[1];FRONTEND=ROOT/"frontend"
CURRENT_RECEIVERS=[
 {"id":"rx-t37","name":"T37","lat":21.485594,"lon":107.773191,"altitude_m":60,"reception_model":"simulated","max_range_km":350,"enabled":True},
 {"id":"rx-qk4","name":"QK4","lat":18.760032,"lon":105.659087,"altitude_m":20,"reception_model":"simulated","max_range_km":350,"enabled":True},
 {"id":"rx-caichien","name":"CaiChien","lat":21.320940,"lon":107.766116,"altitude_m":28,"reception_model":"simulated","max_range_km":350,"enabled":True},
 {"id":"rx-blv","name":"BachLongVi","lat":20.132285,"lon":107.724413,"altitude_m":28,"reception_model":"simulated","max_range_km":350,"enabled":True},
]
DEFAULT_POLYGON=[[21.774082,107.742854],[21.687485,110.065637],[18.911860,109.677212],[19.220238,106.142541]]


def analyze_payload(payload):
    request=AnalyzeRequest.parse(payload);result=analyze(request)
    coverage=receiver_coverage_summary(request.receivers,request.surveillance_polygon,outline_store)
    result["receiver_coverage"]=coverage
    result["summary"]["receiver_coverage"]=coverage["receivers"]
    result["assessment"]=build_assessment(result,request)
    return result
def coverage_area_payload(payload):
    if not isinstance(payload,dict):raise ValidationError("JSON request must be an object")
    raw=payload.get("receivers")
    if not isinstance(raw,list):raise ValidationError("receivers must be an array")
    receivers=tuple(Receiver.parse(value) for value in raw);ids=[receiver.id for receiver in receivers]
    if len(ids)!=len(set(ids)):raise ValidationError("Receiver ids must be unique")
    return receiver_coverage_summary(receivers,payload.get("surveillance_polygon"),outline_store)
def analyze_point_payload(payload):
    point=payload.get("point") if isinstance(payload,dict) else None
    if not isinstance(point,(list,tuple)) or len(point)!=2:raise ValidationError("point must be [lat, lon]")
    request=AnalyzeRequest.parse(payload);result=analyze_4ofn(request,include_details=True);lat,lon=map(float,point);row=min(result["grid"],key=lambda x:(x["lat"]-lat)**2+(x["lon"]-lon)**2)
    return {"requested_point":{"lat":lat,"lon":lon},"matched_grid_point":{"lat":row["lat"],"lon":row["lon"]},"subset_count":row["subset_count"],"subsets":row.get("subsets",[]),"best_subset":row.get("best_subset"),"worst_subset":row.get("worst_subset"),"n_minus_1_survivable":row.get("n_minus_1_survivable",False)}


class Handler(BaseHTTPRequestHandler):
    server_version="MLATDeploymentPlanner/3"
    def json_response(self,status,value):
        data=json.dumps(value,separators=(",",":"),allow_nan=False).encode();self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(data)
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=="/api/health":return self.json_response(200,{"status":"ok","phase":"Tool-3.6","port":self.server.server_port,"outline_resources":len(outline_store.resources)})
        if path=="/api/preset":return self.json_response(200,{"receivers":CURRENT_RECEIVERS,"surveillance_polygon":DEFAULT_POLYGON,"geometry_receiver_ids":[x["id"] for x in CURRENT_RECEIVERS]})
        if path=="/api/outlines":return self.json_response(200,{"outlines":[outline_store.public(x,False) for x in sorted(outline_store.resources)]})
        if path.startswith("/api/outlines/"):
            try:return self.json_response(200,outline_store.public(path.rsplit("/",1)[-1]))
            except OutlineError as exc:return self.json_response(404,{"error":str(exc)})
        relative="index.html" if path in ("","/") else path.lstrip("/");target=(FRONTEND/relative).resolve()
        if FRONTEND.resolve() not in target.parents or not target.is_file():return self.send_error(404)
        data=target.read_bytes();self.send_response(200);self.send_header("Content-Type",mimetypes.guess_type(target.name)[0] or "application/octet-stream");self.send_header("Content-Length",str(len(data)));self.send_header("Cache-Control","no-cache");self.end_headers();self.wfile.write(data)
    def do_POST(self):
        path=urlsplit(self.path).path
        if path=="/api/outlines":return self.upload_outline()
        if path not in ("/api/analyze","/api/analyze-point","/api/coverage-areas"):return self.send_error(404)
        try:
            length=int(self.headers.get("Content-Length","0"))
            if length>5_000_000:raise ValidationError("Request is too large")
            payload=json.loads(self.rfile.read(length));result=analyze_point_payload(payload) if path=="/api/analyze-point" else coverage_area_payload(payload) if path=="/api/coverage-areas" else analyze_payload(payload);self.json_response(200,result)
        except NotImplementedError as exc:self.json_response(501,{"error":str(exc)})
        except (ValidationError,ValueError,json.JSONDecodeError) as exc:self.json_response(422,{"error":str(exc)})
        except Exception as exc:self.json_response(500,{"error":f"Analysis failed: {exc}"})
    def upload_outline(self):
        try:
            length=int(self.headers.get("Content-Length","0"))
            if length>MAX_UPLOAD_BYTES+65_536:
                # Drain the modest rejected request so clients receive the 413
                # response instead of observing a TCP broken pipe while sending.
                remaining=length
                while remaining:
                    chunk=self.rfile.read(min(65_536,remaining))
                    if not chunk:break
                    remaining-=len(chunk)
                return self.json_response(413,{"error":f"Upload exceeds {MAX_UPLOAD_BYTES} byte file limit"})
            if "multipart/form-data" not in self.headers.get("Content-Type",""):raise OutlineError("POST /api/outlines requires multipart/form-data")
            body=self.rfile.read(length);env={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers["Content-Type"],"CONTENT_LENGTH":str(length)}
            form=cgi.FieldStorage(fp=io.BytesIO(body),headers=self.headers,environ=env,keep_blank_values=True)
            item=form["file"] if "file" in form else None
            if item is None or not getattr(item,"file",None):raise OutlineError("Missing multipart file field 'file'")
            raw=item.file.read(MAX_UPLOAD_BYTES+1);resource=outline_store.create(raw,getattr(item,"filename",None) or "outline.json")
            self.json_response(201,resource)
        except OutlineError as exc:self.json_response(422,{"error":str(exc)})
        except Exception as exc:self.json_response(500,{"error":f"Outline upload failed: {exc}"})
    def do_DELETE(self):
        path=urlsplit(self.path).path
        if not path.startswith("/api/outlines/"):return self.send_error(404)
        try:self.json_response(200,outline_store.delete(path.rsplit("/",1)[-1]))
        except OutlineError as exc:self.json_response(404,{"error":str(exc)})
    def log_message(self,fmt,*args):print(f"planner {self.address_string()} {fmt%args}")


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--host",default="0.0.0.0");p.add_argument("--port",type=int,default=8095);args=p.parse_args();server=ThreadingHTTPServer((args.host,args.port),Handler);print(f"MLAT Deployment Planner: http://{args.host}:{args.port}/",flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
