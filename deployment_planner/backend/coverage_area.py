"""Geodesic/equal-area coverage metrics for receiver reception models.

Coordinates use the project-wide ``[latitude, longitude]`` convention.  The
implementation is dependency-free: a spherical Lambert azimuthal equal-area
projection supplies polygon and intersection areas in square kilometres.
"""
import math

from .models import Receiver, ValidationError

EARTH_RADIUS_KM = 6371.0088
_EPSILON = 1e-10


def _normalized_ring(ring):
    points=[]
    for value in ring:
        if not isinstance(value,(list,tuple)) or len(value)!=2:raise ValidationError("Polygon vertices must be [lat, lon]")
        try:lat,lon=float(value[0]),float(value[1])
        except (TypeError,ValueError):raise ValidationError("Polygon coordinates must be numeric")
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:raise ValidationError("Polygon coordinate is out of range")
        point=(lat,lon)
        if not points or points[-1]!=point:points.append(point)
    if len(points)>1 and points[0]==points[-1]:points.pop()
    if len(set(points))<3:raise ValidationError("Polygon needs at least three distinct vertices")
    if any(abs(points[(i+1)%len(points)][1]-points[i][1])>180 for i in range(len(points))):raise ValidationError("Longitude-wrap polygons are not supported")
    return points


def _projection_center(*rings):
    x=y=z=0.0
    for ring in rings:
        for lat,lon in ring:
            lat=math.radians(lat);lon=math.radians(lon);cl=math.cos(lat)
            x+=cl*math.cos(lon);y+=cl*math.sin(lon);z+=math.sin(lat)
    length=math.sqrt(x*x+y*y+z*z)
    if length<=_EPSILON:raise ValidationError("Cannot determine an equal-area projection center")
    return math.atan2(z,math.hypot(x,y)),math.atan2(y,x)


def _project_laea(ring,center):
    lat0,lon0=center;s0,c0=math.sin(lat0),math.cos(lat0);points=[]
    for lat,lon in ring:
        lat=math.radians(lat);lon=math.radians(lon);sl,cl=math.sin(lat),math.cos(lat);dl=lon-lon0
        denominator=1+s0*sl+c0*cl*math.cos(dl)
        if denominator<=_EPSILON:raise ValidationError("Polygon reaches the antipode of the area projection")
        k=math.sqrt(2/denominator)
        points.append((EARTH_RADIUS_KM*k*cl*math.sin(dl),EARTH_RADIUS_KM*k*(c0*sl-s0*cl*math.cos(dl))))
    return points


def _signed_area(points):
    return .5*sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points)))


def polygon_area_km2(ring):
    """Area of a normalized geographic polygon using a spherical equal-area projection."""
    ring=_normalized_ring(ring)
    return abs(_signed_area(_project_laea(ring,_projection_center(ring))))


def geodesic_circle_area_km2(radius_km):
    """Exact spherical-cap area bounded by a geodesic circle."""
    radius=float(radius_km)
    if not math.isfinite(radius) or not 0<radius<=2000:raise ValidationError("Receiver max range must be 0–2000 km")
    return 2*math.pi*EARTH_RADIUS_KM**2*(1-math.cos(radius/EARTH_RADIUS_KM))


def _geodesic_circle_ring(lat,lon,radius_km,samples=360):
    lat1=math.radians(lat);lon1=math.radians(lon);distance=radius_km/EARTH_RADIUS_KM
    sd,cd=math.sin(distance),math.cos(distance);s1,c1=math.sin(lat1),math.cos(lat1);ring=[]
    for index in range(samples):
        bearing=2*math.pi*index/samples;lat2=math.asin(s1*cd+c1*sd*math.cos(bearing))
        lon2=lon1+math.atan2(math.sin(bearing)*sd*c1,cd-s1*math.sin(lat2))
        lon2=(lon2+math.pi)%(2*math.pi)-math.pi
        ring.append((math.degrees(lat2),math.degrees(lon2)))
    return ring


def _cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _clean_xy(points):
    result=[]
    for point in points:
        if not result or abs(point[0]-result[-1][0])>_EPSILON or abs(point[1]-result[-1][1])>_EPSILON:result.append(point)
    if len(result)>1 and abs(result[0][0]-result[-1][0])<=_EPSILON and abs(result[0][1]-result[-1][1])<=_EPSILON:result.pop()
    changed=True
    while changed and len(result)>3:
        changed=False
        for i in range(len(result)):
            if abs(_cross(result[i-1],result[i],result[(i+1)%len(result)]))<=_EPSILON:
                result.pop(i);changed=True;break
    return result


def _point_in_triangle(point,a,b,c):
    return _cross(a,b,point)>=-_EPSILON and _cross(b,c,point)>=-_EPSILON and _cross(c,a,point)>=-_EPSILON


def _is_convex(points):
    return all(_cross(points[i-1],points[i],points[(i+1)%len(points)])>=-_EPSILON for i in range(len(points)))


def _triangulate(points):
    points=_clean_xy(points)
    if len(points)<3:return []
    if _signed_area(points)<0:points.reverse()
    if _is_convex(points):return [(points[0],points[i],points[i+1]) for i in range(1,len(points)-1)]
    indices=list(range(len(points)));triangles=[];guard=0
    while len(indices)>3:
        found=False
        for slot,current in enumerate(indices):
            previous=indices[slot-1];following=indices[(slot+1)%len(indices)]
            a,b,c=points[previous],points[current],points[following]
            if _cross(a,b,c)<=_EPSILON:continue
            if any(index not in (previous,current,following) and _point_in_triangle(points[index],a,b,c) for index in indices):continue
            triangles.append((a,b,c));indices.pop(slot);found=True;break
        guard+=1
        if not found or guard>len(points)*2:raise ValidationError("Coverage polygon could not be triangulated")
    triangles.append(tuple(points[index] for index in indices))
    return triangles


def _line_intersection(a,b,c,d):
    ab=(b[0]-a[0],b[1]-a[1]);cd=(d[0]-c[0],d[1]-c[1]);den=ab[0]*cd[1]-ab[1]*cd[0]
    if abs(den)<=_EPSILON:return b
    t=((c[0]-a[0])*cd[1]-(c[1]-a[1])*cd[0])/den
    return (a[0]+t*ab[0],a[1]+t*ab[1])


def _clip_convex(subject,clip):
    output=list(subject)
    if _signed_area(clip)<0:clip=tuple(reversed(clip))
    for index,c1 in enumerate(clip):
        c2=clip[(index+1)%len(clip)];source=output;output=[]
        if not source:break
        previous=source[-1];previous_inside=_cross(c1,c2,previous)>=-_EPSILON
        for current in source:
            current_inside=_cross(c1,c2,current)>=-_EPSILON
            if current_inside:
                if not previous_inside:output.append(_line_intersection(previous,current,c1,c2))
                output.append(current)
            elif previous_inside:output.append(_line_intersection(previous,current,c1,c2))
            previous,previous_inside=current,current_inside
    return output


def polygon_intersection_area_km2(first_ring,second_ring):
    """Intersection area of two simple regional polygons in a common LAEA plane."""
    first=_normalized_ring(first_ring);second=_normalized_ring(second_ring);center=_projection_center(first,second)
    first_xy=_project_laea(first,center);second_xy=_project_laea(second,center)
    first_triangles=_triangulate(first_xy);second_triangles=_triangulate(second_xy);area=0.0
    for first_triangle in first_triangles:
        for second_triangle in second_triangles:
            clipped=_clip_convex(first_triangle,second_triangle)
            if len(clipped)>=3:area+=abs(_signed_area(clipped))
    return area


def parse_optional_surveillance_polygon(value):
    if value is None or value==[]:return None
    if not isinstance(value,(list,tuple)):raise ValidationError("Surveillance polygon must be an array")
    return tuple(_normalized_ring(value))


def receiver_coverage_summary(receivers,surveillance_polygon,outline_store):
    """Return total and surveillance-intersection areas for each receiver."""
    polygon=parse_optional_surveillance_polygon(surveillance_polygon)
    surveillance_area=polygon_area_km2(polygon) if polygon else None;rows=[]
    for raw_receiver in receivers:
        receiver=raw_receiver if isinstance(raw_receiver,Receiver) else Receiver.parse(raw_receiver)
        if receiver.reception_model=="simulated":
            coverage_area=geodesic_circle_area_km2(receiver.max_range_km)
            coverage_ring=_geodesic_circle_ring(receiver.lat,receiver.lon,receiver.max_range_km)
            source="simulated";source_label="Vùng thu giả định"
        else:
            resource=outline_store.public(receiver.outline_id)
            rings=resource["rings"]
            if len(rings)!=1:raise ValidationError("Phase Tool-3.6 supports one normalized outline ring per receiver")
            coverage_ring=rings[0];coverage_area=polygon_area_km2(coverage_ring)
            source="outline";source_label="Vùng thu quan sát từ readsb"
        inside=None;percent=None
        if polygon:
            inside=polygon_intersection_area_km2(coverage_ring,polygon)
            inside=min(max(inside,0.0),coverage_area,surveillance_area)
            percent=inside/surveillance_area*100 if surveillance_area>0 else None
        rows.append({"receiver_id":receiver.id,"receiver_name":receiver.name,"reception_model":source,"source_label_vi":source_label,"coverage_area_km2":coverage_area,"coverage_inside_surveillance_km2":inside,"surveillance_coverage_percent":percent})
    return {"surveillance_area_km2":surveillance_area,"receivers":rows,"area_method":"spherical_lambert_azimuthal_equal_area","coordinate_order":"latitude,longitude"}
