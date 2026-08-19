"""Validated readsb actualRange.last24h outline resources and provider."""
import hashlib
import json
import math
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from geometry_core import haversine_km
from .base import ReceptionProvider

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_POINTS = 10_000
MAX_RESOURCES = 64


class OutlineError(ValueError):
    pass


def _orientation(a, b, c):
    return (b[1] - a[1]) * (c[0] - b[0]) - (b[0] - a[0]) * (c[1] - b[1])


def _segments_intersect(a, b, c, d):
    def sign(x):return 1 if x > 1e-12 else -1 if x < -1e-12 else 0
    return sign(_orientation(a,b,c)) != sign(_orientation(a,b,d)) and sign(_orientation(c,d,a)) != sign(_orientation(c,d,b))


def self_intersects(points):
    n = len(points)
    for i in range(n):
        a,b=points[i],points[(i+1)%n]
        for j in range(i+1,n):
            if j in (i,(i+1)%n) or (j+1)%n in (i,(i+1)%n):continue
            if _segments_intersect(a,b,points[j],points[(j+1)%n]):return True
    return False


def point_in_ring(lat, lon, ring):
    """Boundary-inclusive ray casting on normalized [lat, lon] points."""
    inside=False;j=len(ring)-1
    for i in range(len(ring)):
        yi,xi=ring[i];yj,xj=ring[j]
        cross=(lon-xi)*(yj-yi)-(lat-yi)*(xj-xi)
        if abs(cross)<1e-10 and min(xi,xj)-1e-10<=lon<=max(xi,xj)+1e-10 and min(yi,yj)-1e-10<=lat<=max(yi,yj)+1e-10:return True
        if (xi>lon)!=(xj>lon) and lat<(yj-yi)*(lon-xi)/(xj-xi)+yi:inside=not inside
        j=i
    return inside


def points_in_ring(points, ring):
    """Vectorized, boundary-inclusive equivalent of point_in_ring."""
    query=np.asarray(points,float);qy=query[:,0];qx=query[:,1];vertices=np.asarray(ring,float);inside=np.zeros(len(query),dtype=bool);boundary=np.zeros(len(query),dtype=bool);j=len(vertices)-1
    for i in range(len(vertices)):
        yi,xi=vertices[i];yj,xj=vertices[j]
        cross=(qx-xi)*(yj-yi)-(qy-yi)*(xj-xi)
        boundary|=(np.abs(cross)<1e-10)&(qx>=min(xi,xj)-1e-10)&(qx<=max(xi,xj)+1e-10)&(qy>=min(yi,yj)-1e-10)&(qy<=max(yi,yj)+1e-10)
        intersects=np.zeros(len(query),dtype=bool) if abs(xj-xi)<1e-15 else ((xi>qx)!=(xj>qx))&(qy<(yj-yi)*(qx-xi)/(xj-xi)+yi)
        inside^=intersects;j=i
    return inside|boundary


def parse_readsb_outline(raw, filename="outline.json"):
    if len(raw)>MAX_UPLOAD_BYTES:raise OutlineError(f"Upload exceeds {MAX_UPLOAD_BYTES} byte limit")
    try:data=json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc:raise OutlineError(f"Invalid readsb outline.json: {exc}")
    try:records=data["actualRange"]["last24h"]["points"]
    except (KeyError,TypeError):raise OutlineError("Missing expected actualRange.last24h.points data")
    if not isinstance(records,list):raise OutlineError("actualRange.last24h.points must be an array")
    if len(records)>MAX_POINTS:raise OutlineError(f"Outline has {len(records)} points; maximum is {MAX_POINTS}")
    points=[];third_values=[]
    for index,p in enumerate(records):
        if not isinstance(p,list) or len(p)<2:raise OutlineError(f"Malformed point record at index {index}")
        try:lat=float(p[0]);lon=float(p[1])
        except (TypeError,ValueError):raise OutlineError(f"Non-numeric coordinate at point {index}")
        if not math.isfinite(lat) or not math.isfinite(lon):raise OutlineError(f"NaN/inf coordinate at point {index}")
        if not -90<=lat<=90 or not -180<=lon<=180:raise OutlineError(f"Impossible coordinate at point {index}: [{lat}, {lon}]")
        if not points or points[-1]!=(lat,lon):points.append((lat,lon))
        if len(p)>2 and isinstance(p[2],(int,float)) and math.isfinite(float(p[2])):third_values.append(float(p[2]))
    if len(points)>1 and points[0]==points[-1]:points.pop()
    if len(set(points))<3:raise OutlineError(f"Outline contains only {len(set(points))} distinct valid points; at least 3 required")
    if any(abs(points[(i+1)%len(points)][1]-points[i][1])>180 for i in range(len(points))):raise OutlineError("Longitude wrap outline is not supported in Phase Tool-2")
    if self_intersects(points):raise OutlineError("Outline polygon self-intersects")
    metadata={
        "filename":Path(filename).name or "outline.json",
        "schema_path":"actualRange.last24h.points",
        "coordinate_order":"latitude,longitude,third_value_unused",
        "observed_period":"last24h",
        "point_count":len(points),
        "bbox":{"south":min(x[0] for x in points),"north":max(x[0] for x in points),"west":min(x[1] for x in points),"east":max(x[1] for x in points)},
    }
    if third_values:metadata["third_value"]={"minimum":min(third_values),"maximum":max(third_values),"used_for_eligibility":False}
    return [[list(x) for x in points]],metadata,data


class OutlineStore(ReceptionProvider):
    def __init__(self, root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self.resources={};self._load()

    def _load(self):
        for path in self.root.glob("outline-*/normalized.json"):
            try:
                resource=json.loads(path.read_text());self.resources[resource["outline_id"]]=resource
            except (OSError,ValueError,KeyError):pass

    def create(self, raw, filename):
        rings,metadata,original=parse_readsb_outline(raw,filename)
        with self.lock:
            if len(self.resources)>=MAX_RESOURCES:raise OutlineError(f"Outline resource limit {MAX_RESOURCES} reached")
            oid="outline-"+uuid.uuid4().hex[:12];uploaded=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
            metadata.update(uploaded=uploaded,sha256=hashlib.sha256(raw).hexdigest())
            resource={"outline_id":oid,"filename":metadata["filename"],"valid":True,"point_count":metadata["point_count"],"rings":rings,"metadata":metadata,"outline_source":"upload"}
            folder=self.root/oid;folder.mkdir(parents=False,exist_ok=False)
            (folder/"original.json").write_bytes(raw)
            (folder/"normalized.json").write_text(json.dumps(resource,separators=(",",":"))+"\n")
            self.resources[oid]=resource
            return resource

    def public(self, oid, include_rings=True):
        with self.lock:
            if oid not in self.resources:raise OutlineError(f"Unknown outline_id: {oid}")
            value=self.resources[oid]
            return value if include_rings else {k:v for k,v in value.items() if k!="rings"}

    def delete(self, oid):
        with self.lock:
            resource=self.resources.pop(oid,None)
            if resource is None:raise OutlineError(f"Unknown outline_id: {oid}")
            folder=self.root/oid
            for name in ("original.json","normalized.json"):
                try:(folder/name).unlink()
                except FileNotFoundError:pass
            try:folder.rmdir()
            except OSError:pass
            return {"outline_id":oid,"deleted":True,"receiver_action":"Frontend references reset to simulated; stale external configs will fail validation"}

    def evaluate(self, receiver, target_lat, target_lon, target_altitude_m):
        resource=self.public(receiver.outline_id)
        inside=any(point_in_ring(target_lat,target_lon,ring) for ring in resource["rings"])
        return inside,{"provider":"outline","reason":"inside observed readsb outline" if inside else "outside observed readsb outline","outline_id":receiver.outline_id,"outline_filename":resource["metadata"]["filename"]}

    def prepare(self, receiver, points, target_altitude_m):
        resource=self.public(receiver.outline_id);eligible=np.zeros(len(points),dtype=bool)
        for ring in resource["rings"]:eligible|=points_in_ring(points,ring)
        filename=resource["metadata"]["filename"]
        return [(bool(ok),{"provider":"outline","reason":"inside observed readsb outline" if ok else "outside observed readsb outline","outline_id":receiver.outline_id,"outline_filename":filename}) for ok in eligible]

    def receiver_metadata(self, receiver):
        resource=self.public(receiver.outline_id,False);meta=dict(resource["metadata"])
        ring=self.resources[receiver.outline_id]["rings"][0]
        meta["maximum_observed_range_km_from_configured_receiver"]=max(haversine_km((receiver.lat,receiver.lon),p) for p in ring)
        return meta
