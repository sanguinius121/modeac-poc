"""Small dependency-free request models and validation."""
from dataclasses import dataclass


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Receiver:
    id: str
    name: str
    lat: float
    lon: float
    altitude_m: float
    reception_model: str
    max_range_km: float
    outline_id: str
    outline_filename: str
    outline_source: str
    enabled: bool

    @classmethod
    def parse(cls, value):
        if not isinstance(value, dict):raise ValidationError("Each receiver must be an object")
        try:
            rid=str(value["id"]).strip();name=str(value["name"]).strip();lat=float(value["lat"]);lon=float(value["lon"]);alt=float(value.get("altitude_m",0));model=str(value.get("reception_model","simulated"));raw_range=value.get("max_range_km",350);rng=None if raw_range is None else float(raw_range);outline_id=str(value.get("outline_id") or "").strip();outline_filename=str(value.get("outline_filename") or "").strip();outline_source=str(value.get("outline_source") or "upload");enabled=value.get("enabled",True)
        except (KeyError,TypeError,ValueError) as exc:raise ValidationError(f"Invalid receiver: {exc}")
        if not rid or not name:raise ValidationError("Receiver id and name are required")
        if not -90<=lat<=90 or not -180<=lon<=180:raise ValidationError(f"Receiver {rid} has invalid coordinates")
        if not -500<=alt<=20_000:raise ValidationError(f"Receiver {rid} altitude is out of range")
        if not isinstance(enabled,bool):raise ValidationError(f"Receiver {rid} enabled must be boolean")
        if model not in ("simulated","outline"):raise ValidationError(f"Receiver {rid} has unknown reception model")
        if model=="simulated" and (rng is None or not 0<rng<=2_000):raise ValidationError(f"Receiver {rid} max range must be 0–2000 km")
        if model=="outline" and not outline_id:raise ValidationError(f"Receiver {rid} references missing outline")
        if rng is not None and not 0<rng<=2_000:raise ValidationError(f"Receiver {rid} comparison range must be 0–2000 km")
        if outline_source not in ("upload","automatic"):raise ValidationError(f"Receiver {rid} has invalid outline_source")
        if outline_source=="automatic":raise ValidationError(f"Receiver {rid}: automatic outline fetch is not implemented in Phase Tool-2")
        return cls(rid,name,lat,lon,alt,model,rng,outline_id,outline_filename,outline_source,enabled)

    def public(self):return self.__dict__.copy()


@dataclass(frozen=True)
class AnalyzeRequest:
    receivers: tuple
    surveillance_polygon: tuple
    target_altitude_m: float
    timing_noise_us: float
    grid_step_km: float
    geometry_receiver_ids: tuple
    geometry_strategy: str
    failed_receiver_id: str
    allow_high_subset_count: bool

    @classmethod
    def parse(cls,value):
        if not isinstance(value,dict):raise ValidationError("JSON request must be an object")
        raw=value.get("receivers")
        if not isinstance(raw,list) or len(raw)<4:raise ValidationError("At least four receivers are required")
        receivers=tuple(Receiver.parse(x) for x in raw);ids=[x.id for x in receivers]
        if len(ids)!=len(set(ids)):raise ValidationError("Receiver ids must be unique")
        polygon=value.get("surveillance_polygon")
        if not isinstance(polygon,list) or len(polygon)<3:raise ValidationError("Surveillance polygon needs at least three vertices")
        points=[]
        for p in polygon:
            if not isinstance(p,(list,tuple)) or len(p)!=2:raise ValidationError("Polygon vertices must be [lat, lon]")
            try:lat,lon=float(p[0]),float(p[1])
            except (TypeError,ValueError):raise ValidationError("Polygon coordinates must be numeric")
            if not -90<=lat<=90 or not -180<=lon<=180:raise ValidationError("Polygon coordinate is out of range")
            points.append((lat,lon))
        try:alt=float(value.get("target_altitude_m",2500));noise=float(value.get("timing_noise_us",.25));step=float(value.get("grid_step_km",10))
        except (TypeError,ValueError):raise ValidationError("Altitude, timing noise and grid step must be numeric")
        if not 0<=alt<=30_000:raise ValidationError("Target altitude must be 0–30000 m")
        if not 0<noise<=100:raise ValidationError("Timing noise must be positive and <=100 us")
        if step not in (5.,10.,20.):raise ValidationError("Grid step must be 5, 10 or 20 km")
        gids=tuple(str(x) for x in value.get("geometry_receiver_ids",()))
        strategy=str(value.get("geometry_strategy","strict_4"))
        if strategy not in ("strict_4","best_4_of_n","worst_4_of_n","full_n_diagnostic"):raise ValidationError("Unknown geometry_strategy")
        if strategy=="strict_4" and (len(gids)!=4 or len(set(gids))!=4):raise ValidationError("Select exactly four distinct geometry receivers")
        if strategy!="strict_4" and not gids:gids=tuple(x.id for x in receivers if x.enabled)[:4]
        if len(gids)!=len(set(gids)):raise ValidationError("geometry_receiver_ids must be distinct")
        by_id={x.id:x for x in receivers}
        if any(x not in by_id for x in gids):raise ValidationError("Geometry receiver id does not exist")
        if strategy=="strict_4" and any(not by_id[x].enabled for x in gids):raise ValidationError("All geometry receivers must be enabled")
        failed=str(value.get("failed_receiver_id") or "")
        if failed and failed not in by_id:raise ValidationError("failed_receiver_id does not exist")
        allow=value.get("allow_high_subset_count",False)
        if not isinstance(allow,bool):raise ValidationError("allow_high_subset_count must be boolean")
        return cls(receivers,tuple(points),alt,noise,step,gids,strategy,failed,allow)
