#!/usr/bin/env python3
"""Geometry-only grid search for a fifth receiver; no ADS-B truth or RF claims."""

import argparse,csv,itertools,json,math
from pathlib import Path
import numpy as np
from scipy.spatial import Delaunay
import sys
if __package__ in (None, ""):sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import receiver_geometry_analysis as ga


def points_grid(lat0,lat1,lon0,lon1,step):
    return [(a,b) for a in ga.grid_values(lat0,lat1,step) for b in ga.grid_values(lon0,lon1,step)]


def subset_error(point,stations,noise=.25):
    return ga.geometry_metrics(point[0],point[1],10_000,stations,noise)["linear_hrmse_m"]


def fraction_hull(points,stations):
    tri=Delaunay(np.asarray([(v[1],v[0]) for v in stations.values()]))
    return float(np.mean(tri.find_simplex(np.asarray([(p[1],p[0]) for p in points]))>=0))


def rank01(values,lower_better=False):
    a=np.asarray(values,float); order=np.argsort(a if not lower_better else -a); ranks=np.empty(len(a));ranks[order]=np.arange(len(a));return ranks/max(1,len(a)-1)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',default='geometry');p.add_argument('--candidate-step',type=float,default=.2);p.add_argument('--area-step',type=float,default=.2);p.add_argument('--rf-radius-km',type=float,default=350);args=p.parse_args()
    out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
    area=points_grid(18.0,22.0,105.0,108.6,args.area_step)
    candidates=points_grid(17.4,22.8,104.4,109.4,args.candidate_step)+[(ga.MONGCAI[0],ga.MONGCAI[1])]
    rows=[]
    fixed=ga.STATIONS
    for lat,lon in candidates:
        candidate=(lat,lon,36.0)
        is_mongcai=abs(lat-ga.MONGCAI[0])<1e-8 and abs(lon-ga.MONGCAI[1])<1e-8
        if not is_mongcai and min(ga.haversine_km(candidate,v) for v in fixed.values())<20:continue
        five={**fixed,'Candidate':candidate};subsets=[]
        for omitted in five:
            subsets.append({k:v for k,v in five.items() if k!=omitted})
        best=[];worst=[];full=[];visible4=[];visible5=[]
        for target in area:
            errors=[subset_error(target,s) for s in subsets];best.append(min(errors));worst.append(max(errors));full.append(subset_error(target,five))
            distances=[ga.haversine_km((target[0],target[1],10_000),v) for v in five.values()]
            visible4.append(sum(x<=args.rf_radius_km for x in distances)>=4);visible5.append(all(x<=args.rf_radius_km for x in distances))
        rows.append({'candidate_lat':lat,'candidate_lon':lon,'nearest_existing_km':min(ga.haversine_km(candidate,v) for v in fixed.values()),'best4_median_hrmse_0_25us_m':float(np.percentile(best,50)),'best4_p90_hrmse_0_25us_m':float(np.percentile(best,90)),'worst4_p90_hrmse_0_25us_m':float(np.percentile(worst,90)),'full5_p90_hrmse_0_25us_m':float(np.percentile(full,90)),'best4_under_1km_fraction':float(np.mean(np.asarray(best)<1000)),'inside_5rx_hull_fraction':fraction_hull(area,five),'four_visible_350km_fraction':float(np.mean(visible4)),'five_visible_350km_fraction':float(np.mean(visible5)),'is_mongcai':is_mongcai})
    # Percentile-rank composite: geometry 65%, hull 15%, conservative LOS proxy 20%.
    components=[rank01([r['best4_p90_hrmse_0_25us_m'] for r in rows],True),rank01([r['worst4_p90_hrmse_0_25us_m'] for r in rows],True),rank01([r['best4_under_1km_fraction'] for r in rows]),rank01([r['inside_5rx_hull_fraction'] for r in rows]),rank01([r['four_visible_350km_fraction'] for r in rows])]
    for i,r in enumerate(rows):r['composite_score']=float(100*(.30*components[0][i]+.20*components[1][i]+.15*components[2][i]+.15*components[3][i]+.20*components[4][i]))
    rows.sort(key=lambda r:r['composite_score'],reverse=True); 
    with (out/'receiver5-candidates.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    current_errors=[subset_error(x,fixed) for x in area]
    current={'median_hrmse_0_25us_m':float(np.percentile(current_errors,50)),'p90_hrmse_0_25us_m':float(np.percentile(current_errors,90)),'under_1km_fraction':float(np.mean(np.asarray(current_errors)<1000)),'inside_hull_fraction':fraction_hull(area,fixed)}
    mong=next(r for r in rows if r['is_mongcai']);summary={'method':{'truth_used':False,'surveillance_area':{'lat':[18,22],'lon':[105,108.6],'step_deg':args.area_step},'candidate_grid':{'lat':[17.4,22.8],'lon':[104.4,109.4],'step_deg':args.candidate_step},'altitude_m':10000,'timing_noise_us_per_receiver':.25,'rf_radius_km_is_only_a_los_proxy':args.rf_radius_km,'score_weights':{'best4_p90':.30,'worst4_p90':.20,'best4_under_1km':.15,'inside_hull':.15,'four_visible_proxy':.20}},'current_network':current,'mongcai':mong,'top20':rows[:20]}
    (out/'receiver5-optimization-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    markers=[{'name':'Candidate #%d'%(i+1),'lat':r['candidate_lat'],'lon':r['candidate_lon']} for i,r in enumerate(rows[:20])]+[{'name':'MongCai','lat':ga.MONGCAI[0],'lon':ga.MONGCAI[1]}]
    # Candidate map uses score-colored circle markers and intentionally no geometry raster.
    payload=json.dumps(rows);base=json.dumps([{'name':k,'lat':v[0],'lon':v[1]} for k,v in fixed.items()]);
    html="""<!doctype html><html><head><meta charset='utf-8'><title>Receiver 5 optimization</title><link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>html,body,#map{height:100%%;margin:0}.box{background:white;padding:8px}</style></head><body><div id='map'></div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>const rows=%s,existing=%s;const m=L.map('map').setView([20,107],6);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'OpenStreetMap'}).addTo(m);function color(s){return s>=80?'#146c43':s>=60?'#62a744':s>=40?'#d6b51f':s>=20?'#ed7d31':'#c62828'}rows.forEach((x,i)=>L.circleMarker([x.candidate_lat,x.candidate_lon],{radius:x.is_mongcai?9:5,color:x.is_mongcai?'#0066ff':color(x.composite_score),weight:x.is_mongcai?3:1,fillColor:color(x.composite_score),fillOpacity:.65}).bindTooltip(`${x.is_mongcai?'MongCai<br>':''}rank score ${x.composite_score.toFixed(1)}<br>best4 P90 ${x.best4_p90_hrmse_0_25us_m.toFixed(0)} m<br>worst4 P90 ${x.worst4_p90_hrmse_0_25us_m.toFixed(0)} m<br>hull ${(100*x.inside_5rx_hull_fraction).toFixed(1)}%%`).addTo(m));existing.forEach(x=>L.marker([x.lat,x.lon]).bindPopup('<b>'+x.name+'</b>').addTo(m));</script></body></html>"""%(payload,base)
    (out/'receiver5-optimization-map.html').write_text(html)
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
