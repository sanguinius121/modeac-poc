#!/usr/bin/env python3
"""Synthetic receiver spacing/layout study for this project's 2D TDOA model.

No ADS-B truth is loaded. Receiver altitude, target altitude, surveillance polygon,
timing noise, and RF-distance proxies are explicit diagnostic assumptions.
"""

import argparse,csv,itertools,json,math
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from scipy.spatial import Delaunay
import sys
if __package__ in (None, ""):sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import receiver_geometry_analysis as ga

POLYGON_LL=[(21.774082,107.742854),(21.687485,110.065637),(18.911860,109.677212),(19.220238,106.142541)]
SCALES=(50,100,150,200,250,300,400,500)
NOISES=(.1,.25,.5,1.0)
LAYOUTS=("square","diamond","rectangle_2to1","triangle_center","irregular","linear")
COLORS={"square":"#1665a8","diamond":"#00a6a6","rectangle_2to1":"#7b52ab","triangle_center":"#d98c00","irregular":"#2d9b47","linear":"#c43c39"}
RECEIVER_ALTITUDE_M=30.0


def percentile(values,q):
    """Linear percentile that preserves a degenerate +inf tail without NaN."""
    x=sorted(float(v) for v in values);pos=(len(x)-1)*q/100;lo,hi=math.floor(pos),math.ceil(pos)
    if lo==hi or x[lo]==x[hi]:return x[lo]
    if not math.isfinite(x[hi]):return float("inf")
    return x[lo]*(hi-pos)+x[hi]*(pos-lo)


def center_and_axes(polygon):
    lat0=float(np.mean([x[0] for x in polygon]));lon0=float(np.mean([x[1] for x in polygon]))
    return lat0,lon0,111.132,111.320*math.cos(math.radians(lat0))


LAT0,LON0,KM_LAT,KM_LON=center_and_axes(POLYGON_LL)


def ll_to_xy(lat,lon):return np.array(((lon-LON0)*KM_LON,(lat-LAT0)*KM_LAT))
def xy_to_ll(x,y):return LAT0+y/KM_LAT,LON0+x/KM_LON


def rotate(points,degrees):
    a=math.radians(degrees);m=np.array(((math.cos(a),-math.sin(a)),(math.sin(a),math.cos(a))))
    return np.asarray(points)@m.T


def normalize_span(points,scale):
    p=np.asarray(points,float);span=max(np.linalg.norm(a-b) for a,b in itertools.combinations(p,2));return p*(scale/span)


def layout_xy(kind,scale,rotation=0):
    if kind=="square":base=[(-1,-1),(1,-1),(1,1),(-1,1)]
    elif kind=="diamond":base=[(0,1),(1,0),(0,-1),(-1,0)]
    elif kind=="rectangle_2to1":base=[(-1,-.5),(1,-.5),(1,.5),(-1,.5)]
    elif kind=="triangle_center":base=[(0,1),(-math.sqrt(3)/2,-.5),(math.sqrt(3)/2,-.5),(0,0)]
    elif kind=="irregular":base=[(.50,.12),(-.08,.48),(-.50,-.18),(.18,-.40)]
    elif kind=="linear":base=[(-.5,0),(-1/6,0),(1/6,0),(.5,0)]
    else:raise ValueError(kind)
    return rotate(normalize_span(base,scale),rotation)


def receiver_dict(points,alt=None):
    alt=RECEIVER_ALTITUDE_M if alt is None else alt
    return {f"RX{i+1}":(*xy_to_ll(x,y),alt) for i,(x,y) in enumerate(points)}


def polygon_grid(polygon_xy,step_km):
    p=np.asarray(polygon_xy);tri=Delaunay(p);xs=np.arange(math.floor(p[:,0].min()/step_km)*step_km,math.ceil(p[:,0].max()/step_km)*step_km+.01,step_km);ys=np.arange(math.floor(p[:,1].min()/step_km)*step_km,math.ceil(p[:,1].max()/step_km)*step_km+.01,step_km)
    q=np.array([(x,y) for y in ys for x in xs]);return q[tri.find_simplex(q)>=0]


def metrics_for(points_xy,targets_xy,target_alt,noise_draws,branch=True):
    stations=receiver_dict(points_xy);ll=[xy_to_ll(*q) for q in targets_xy]
    rows=[]
    for lat,lon in ll:
        base=ga.geometry_metrics(lat,lon,target_alt,stations,.25,noise_draws)
        values={"condition":base["condition"]}
        for noise in (NOISES if branch else (.25,)):
            m=ga.geometry_metrics(lat,lon,target_alt,stations,noise,noise_draws);values[f"p95_{noise}"]=m["mc_p95_m"]
        values["visible300"]=all(ga.haversine_km((lat,lon,target_alt),r)<=300 for r in stations.values())
        values["visible350"]=all(ga.haversine_km((lat,lon,target_alt),r)<=350 for r in stations.values());rows.append(values)
    hull=Delaunay(np.asarray(points_xy)[np.unique(np.asarray(points_xy),axis=0,return_index=True)[1]]) if np.linalg.matrix_rank(np.asarray(points_xy)-np.mean(points_xy,axis=0))==2 else None
    inside=float(np.mean(hull.find_simplex(targets_xy)>=0)) if hull is not None else 0.0
    p95=np.asarray([x["p95_0.25"] for x in rows]);cond=np.asarray([x["condition"] for x in rows]);v300=np.asarray([x["visible300"] for x in rows]);v350=np.asarray([x["visible350"] for x in rows])
    output={"target_points":len(rows),"inside_hull_fraction":inside,"condition_median":percentile(cond,50),"condition_p90":percentile(cond,90),"condition_p95":percentile(cond,95),"all4_visible_300km_fraction":float(np.mean(v300)),"all4_visible_350km_fraction":float(np.mean(v350)),"geometry_good_fraction":float(np.mean((p95<=1000)&(cond<=30)))}
    for noise in (NOISES if branch else (.25,)):
        values=[x[f"p95_{noise}"] for x in rows];tag=str(noise).replace('.','_');output[f"mc_p95_{tag}us_median_m"]=percentile(values,50);output[f"mc_p95_{tag}us_p90_m"]=percentile(values,90)
    output["deployment_score_300"]=output["geometry_good_fraction"]*output["all4_visible_300km_fraction"]
    output["deployment_score_350"]=output["geometry_good_fraction"]*output["all4_visible_350km_fraction"]
    if branch:
        # A collinear array has an exact reflected solution across the receiver
        # line even when that mirror lies outside the declared target polygon.
        if np.linalg.matrix_rank(np.asarray(points_xy)-np.mean(points_xy,axis=0))<2:sep=np.zeros(len(ll))
        else:
            signatures=np.asarray([ga.tdoa_signature(lat,lon,target_alt,stations) for lat,lon in ll]);sep=ga.remote_branch_separation(ll,signatures)
        output.update(remote_branch_separation_median_us=float(np.median(sep)),remote_branch_separation_p10_us=float(np.percentile(sep,10)),remote_branch_below_0_5us_fraction=float(np.mean(sep<.5)))
        branch_safe=1-output["remote_branch_below_0_5us_fraction"]
        output["deployment_score_300"]*=branch_safe;output["deployment_score_350"]*=branch_safe
    return output


def best_rotation(kind,scale,targets,target_alt,draws):
    best=None
    for angle in range(0,180,15):
        points=layout_xy(kind,scale,angle);m=metrics_for(points,targets,target_alt,draws,False)
        # Prefer actual usable geometry; hull is a secondary tie-breaker.
        key=(m["deployment_score_350"],m["geometry_good_fraction"],m["inside_hull_fraction"],-m["mc_p95_0_25us_p90_m"])
        if best is None or key>best[0]:best=(key,angle,points,m)
    detailed=metrics_for(best[2],targets,target_alt,draws,True)
    return best[1],best[2],detailed


def write_csv(path,rows):
    with path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def write_png(path,rows):
    width,height=980,620;left,right,top,bottom=80,30,40,75;im=Image.new('RGB',(width,height),'white');d=ImageDraw.Draw(im);font=ImageFont.load_default();plotw=width-left-right;ploth=height-top-bottom
    d.text((12,10),'Deployment score = geometry-good fraction x all-4-visible fraction (350 km proxy)',fill='black',font=font)
    for tick in range(0,11):
        y=top+ploth*(1-tick/10);d.line((left,y,width-right,y),fill='#dddddd');d.text((15,y-5),f'{tick/10:.1f}',fill='black',font=font)
    for i,s in enumerate(SCALES):
        x=left+plotw*i/(len(SCALES)-1);d.line((x,top,x,top+ploth),fill='#eeeeee');d.text((x-10,top+ploth+12),str(s),fill='black',font=font)
    for kind in LAYOUTS:
        rr=sorted((r for r in rows if r['layout']==kind),key=lambda r:r['span_km']);pts=[]
        for r in rr:
            x=left+plotw*SCALES.index(r['span_km'])/(len(SCALES)-1);y=top+ploth*(1-r['deployment_score_350']);pts.append((x,y))
        d.line(pts,fill=COLORS[kind],width=3)
        for x,y in pts:d.ellipse((x-3,y-3,x+3,y+3),fill=COLORS[kind])
    for i,kind in enumerate(LAYOUTS):x=left+i*145;y=height-25;d.line((x,y,x+20,y),fill=COLORS[kind],width=3);d.text((x+25,y-5),kind,fill='black',font=font)
    d.text((width//2-70,height-48),'Maximum receiver span (km)',fill='black',font=font);im.save(path)


def write_html(path,best_rows):
    polygon=json.dumps(POLYGON_LL);items=[]
    for r in best_rows:
        points=layout_xy(r['layout'],r['span_km'],r['rotation_deg']);items.append({"layout":r['layout'],"span":r['span_km'],"score":r['deployment_score_350'],"points":[xy_to_ll(*p) for p in points]})
    html="""<!doctype html><html><head><meta charset='utf-8'><title>MLAT layout comparison</title><link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>html,body,#map{height:100%%;margin:0}.box{background:white;padding:8px}</style></head><body><div id='map'></div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>const polygon=%s,items=%s,colors=%s;const m=L.map('map').fitBounds(polygon);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'OpenStreetMap'}).addTo(m);L.polygon(polygon,{color:'#111',fillOpacity:.05}).bindTooltip('Surveillance polygon').addTo(m);items.forEach(x=>{const p=L.polygon(x.points,{color:colors[x.layout],fill:false,weight:2}).bindTooltip(`${x.layout}, span ${x.span} km, score ${x.score.toFixed(3)}`).addTo(m);x.points.forEach((q,i)=>L.circleMarker(q,{radius:5,color:colors[x.layout]}).bindTooltip(`${x.layout} RX${i+1}`).addTo(m))});</script></body></html>"""%(polygon,json.dumps(items),json.dumps(COLORS));path.write_text(html)


def generic_area_rows(draws,target_alt):
    rows=[]
    for area in (100,200,300,400):
        axis=np.linspace(-area/2,area/2,11);targets=np.array([(x,y) for y in axis for x in axis])
        for kind in LAYOUTS:
            for scale in SCALES:
                angle,_,m=best_rotation(kind,scale,targets,target_alt,draws)
                rows.append({'area_size_km':area,'layout':kind,'span_km':scale,'span_area_ratio':scale/area,'rotation_deg':angle,**m})
    return rows


def main():
    global RECEIVER_ALTITUDE_M
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',default='geometry');p.add_argument('--target-altitude-m',type=float,default=2500);p.add_argument('--receiver-altitude-m',type=float,default=30);p.add_argument('--grid-step-km',type=float,default=20);p.add_argument('--draws',type=int,default=256);args=p.parse_args()
    RECEIVER_ALTITUDE_M=args.receiver_altitude_m
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(20260811);draws=rng.normal(size=(4,args.draws))
    polygon_xy=np.asarray([ll_to_xy(*p) for p in POLYGON_LL]);targets=polygon_grid(polygon_xy,args.grid_step_km)
    rows=[]
    for kind in LAYOUTS:
        for scale in SCALES:
            angle,_,m=best_rotation(kind,scale,targets,args.target_altitude_m,draws);rows.append({'surveillance':'specified_polygon','layout':kind,'span_km':scale,'rotation_deg':angle,**m})
    write_csv(out/'layout-comparison.csv',rows);scale_rows=generic_area_rows(draws,args.target_altitude_m);write_csv(out/'layout-scale-comparison.csv',scale_rows);write_png(out/'layout-comparison.png',rows)
    best_by_layout=[max((r for r in rows if r['layout']==kind),key=lambda r:r['deployment_score_350']) for kind in LAYOUTS];write_html(out/'layout-comparison-map.html',best_by_layout)
    poly_span=max(np.linalg.norm(a-b) for a,b in itertools.combinations(polygon_xy,2));edges=[float(np.linalg.norm(polygon_xy[(i+1)%len(polygon_xy)]-polygon_xy[i])) for i in range(len(polygon_xy))]
    altitude=[]
    winner=max(rows,key=lambda r:r['deployment_score_350']);points=layout_xy(winner['layout'],winner['span_km'],winner['rotation_deg'])
    for alt in (2500,5000,10000,12000):altitude.append({'target_altitude_m':alt,**metrics_for(points,targets,alt,draws,False)})
    current_points=np.asarray([ll_to_xy(v[0],v[1]) for v in ga.STATIONS.values()])
    current={"maximum_span_km":max(float(np.linalg.norm(a-b)) for a,b in itertools.combinations(current_points,2)),**metrics_for(current_points,targets,args.target_altitude_m,draws,True)}
    generic_best={str(area):max((r for r in scale_rows if r['area_size_km']==area),key=lambda r:r['deployment_score_350']) for area in (100,200,300,400)}
    summary={'assumptions':{'truth_used':False,'receiver_altitude_m':args.receiver_altitude_m,'target_minimum_altitude_m':args.target_altitude_m,'rf_horizontal_proxies_km':[300,350],'polygon_ll':POLYGON_LL,'grid_step_km':args.grid_step_km,'scale_definition':'maximum pairwise receiver distance'},'surveillance_geometry':{'center':[LAT0,LON0],'maximum_span_km':poly_span,'edge_lengths_km':edges,'target_grid_points':len(targets)},'current_network_on_specified_polygon':current,'best_overall':winner,'best_by_layout':best_by_layout,'best_by_generic_area':generic_best,'altitude_sensitivity_of_best':altitude}
    (out/'layout-comparison-summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
