#!/usr/bin/env python3
"""Independent geometry-only diagnostic for the current MLAT receiver network.

This tool does not read ADS-B truth and does not import or modify realtime state.
It evaluates the fixed-altitude horizontal TDOA Jacobian used by the accepted
2D/altitude-grid solver and writes reproducible CSV, PNG, HTML, and JSON output.
"""

import argparse
import csv
import itertools
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import sys
if __package__ in (None, ""):sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from geometry_core import classify, geometry_metrics, grid_values, haversine_km, inside_hull, remote_branch_separation, tdoa_signature

STATIONS = {
    "T37": (21.485594, 107.773191, 60.0),
    "QK4": (18.760032, 105.659087, 20.0),
    "Dao_Cai_chien": (21.320940, 107.766116, 28.0),
    "BachLongVi": (20.132285, 107.724413, 28.0),
}
MONGCAI = (21.550206, 107.938978, 36.0)
COLORS = {"GOOD": "#21a366", "ACCEPTABLE": "#d6b51f", "POOR": "#ed7d31", "VERY POOR": "#c62828"}


def percentile(values, q):
    return float(np.percentile(np.asarray(values, dtype=float), q))


def write_csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def write_png(path, rows, lats, lons):
    scale, left, top, bottom = 12, 92, 28, 90
    width, height = left + len(lons) * scale + 20, top + len(lats) * scale + bottom
    image = Image.new("RGB", (width, height), "white"); draw = ImageDraw.Draw(image); font = ImageFont.load_default()
    lookup = {(r["lat"], r["lon"]): r for r in rows}
    for iy, lat in enumerate(reversed(lats)):
        for ix, lon in enumerate(lons):
            row = lookup[(lat, lon)]; x, y = left + ix * scale, top + iy * scale
            draw.rectangle((x, y, x + scale, y + scale), fill=COLORS[row["class"]])
    for name, (lat, lon, _) in STATIONS.items():
        x = left + (lon - lons[0]) / (lons[-1] - lons[0]) * ((len(lons) - 1) * scale)
        y = top + (lats[-1] - lat) / (lats[-1] - lats[0]) * ((len(lats) - 1) * scale)
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="white", outline="black", width=2); draw.text((x + 7, y - 5), name, fill="black", font=font)
    draw.text((8, 8), "Current 4RX geometry @ 10 km; MC P95 for 0.25 us/receiver", fill="black", font=font)
    for i, (name, color) in enumerate(COLORS.items()):
        x, y = left + i * 120, height - 38; draw.rectangle((x, y, x + 14, y + 14), fill=color); draw.text((x + 19, y + 2), name, fill="black", font=font)
    draw.text((8, top), f"{lats[-1]:.1f} N", fill="black", font=font); draw.text((8, top + (len(lats)-1)*scale), f"{lats[0]:.1f} N", fill="black", font=font)
    draw.text((left, height - 62), f"{lons[0]:.1f} E", fill="black", font=font); draw.text((left + (len(lons)-1)*scale - 30, height - 62), f"{lons[-1]:.1f} E", fill="black", font=font)
    image.save(path)


def write_html(path, rows, title, extra_markers=None):
    cells = [{"lat":r["lat"],"lon":r["lon"],"class":r["class"],"p95":round(r["mc_p95_0_25us_m"],1),"condition":round(r["condition"],2),"branch":round(r["remote_branch_separation_us"],3)} for r in rows]
    markers = [{"name":k,"lat":v[0],"lon":v[1]} for k,v in STATIONS.items()] + (extra_markers or [])
    html = """<!doctype html><html><head><meta charset='utf-8'><title>%s</title><link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'><style>html,body,#map{height:100%%;margin:0}.legend{background:white;padding:8px;line-height:1.5}.sw{display:inline-block;width:12px;height:12px;margin-right:5px}</style></head><body><div id='map'></div><script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script><script>
const colors=%s,cells=%s,markers=%s;const map=L.map('map').setView([20,107],6);L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'OpenStreetMap'}).addTo(map);
cells.forEach(x=>L.circleMarker([x.lat,x.lon],{radius:5,weight:0,fillOpacity:.55,fillColor:colors[x.class]}).bindTooltip(`${x.class}<br>P95@0.25us: ${x.p95} m<br>condition: ${x.condition}<br>remote TDOA separation: ${x.branch} us`).addTo(map));
markers.forEach(x=>L.marker([x.lat,x.lon]).bindPopup(`<b>${x.name}</b><br>${x.lat}, ${x.lon}`).addTo(map));
const legend=L.control({position:'bottomright'});legend.onAdd=()=>{const d=L.DomUtil.create('div','legend');d.innerHTML='<b>%s</b><br>'+Object.entries(colors).map(([k,v])=>`<span class="sw" style="background:${v}"></span>${k}`).join('<br>');return d};legend.addTo(map);
</script></body></html>""" % (title, json.dumps(COLORS), json.dumps(cells), json.dumps(markers), title)
    path.write_text(html)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="geometry")
    parser.add_argument("--lat-min", type=float, default=17.5); parser.add_argument("--lat-max", type=float, default=22.5)
    parser.add_argument("--lon-min", type=float, default=104.5); parser.add_argument("--lon-max", type=float, default=109.0)
    parser.add_argument("--step", type=float, default=0.1); parser.add_argument("--altitude-m", type=float, default=10_000)
    parser.add_argument("--draws", type=int, default=256); parser.add_argument("--seed", type=int, default=20260811)
    args = parser.parse_args(); out = Path(args.output_dir); out.mkdir(parents=True, exist_ok=True)
    lats, lons = grid_values(args.lat_min,args.lat_max,args.step), grid_values(args.lon_min,args.lon_max,args.step)
    points = [(lat,lon) for lat in lats for lon in lons]
    rng=np.random.default_rng(args.seed); draws=rng.normal(size=(len(STATIONS),args.draws))
    signatures=np.asarray([tdoa_signature(lat,lon,args.altitude_m,STATIONS) for lat,lon in points])
    branch=remote_branch_separation(points,signatures); hull=inside_hull(points,STATIONS)
    rows=[]
    for i,(lat,lon) in enumerate(points):
        base=geometry_metrics(lat,lon,args.altitude_m,STATIONS,.25,draws)
        row={"lat":lat,"lon":lon,"altitude_m":args.altitude_m,"inside_receiver_hull":bool(hull[i]),"condition":base["condition"],"linear_hrmse_0_25us_m":base["linear_hrmse_m"],"remote_branch_separation_us":float(branch[i])}
        for noise in (.1,.25,.5,1.0):
            metric=geometry_metrics(lat,lon,args.altitude_m,STATIONS,noise,draws)
            label=str(noise).replace('.','_'); row[f"mc_p50_{label}us_m"]=metric["mc_p50_m"]; row[f"mc_p95_{label}us_m"]=metric["mc_p95_m"]
        row["class"]=classify(row["mc_p95_0_25us_m"],row["condition"],row["remote_branch_separation_us"]);rows.append(row)
    write_csv(out/"current-network.csv",rows);write_png(out/"current-network-heatmap.png",rows,lats,lons);write_html(out/"current-network-map.html",rows,"Current 4RX geometry")
    distances=[]
    for a,b in itertools.combinations(STATIONS,2):distances.append({"a":a,"b":b,"distance_km":haversine_km(STATIONS[a],STATIONS[b])})
    altitude=[]
    for alt in (1000,3000,10000,12000):
        vals=[geometry_metrics(lat,lon,alt,STATIONS,.25)["linear_hrmse_m"] for lat,lon in points]
        altitude.append({"altitude_m":alt,"median_linear_hrmse_0_25us_m":percentile(vals,50),"p90_linear_hrmse_0_25us_m":percentile(vals,90),"p95_linear_hrmse_0_25us_m":percentile(vals,95)})
    counts={name:sum(r["class"]==name for r in rows) for name in COLORS}
    region_filters={
        "central_18.8_21.6N_105.5_108E":lambda r:18.8<=r["lat"]<=21.6 and 105.5<=r["lon"]<=108.0,
        "gulf_core_19_21.5N_106_108E":lambda r:19.0<=r["lat"]<=21.5 and 106.0<=r["lon"]<=108.0,
        "north_21.5N_plus":lambda r:r["lat"]>=21.5,
        "south_19.2N_minus":lambda r:r["lat"]<=19.2,
        "east_107.8E_plus":lambda r:r["lon"]>=107.8,
        "west_106E_minus":lambda r:r["lon"]<=106.0,
    }
    regions={}
    for name,fn in region_filters.items():
        selected=[r for r in rows if fn(r)]
        regions[name]={"points":len(selected),"good_fraction":sum(r["class"]=="GOOD" for r in selected)/len(selected),"good_or_acceptable_fraction":sum(r["class"] in ("GOOD","ACCEPTABLE") for r in selected)/len(selected),"median_condition":percentile([r["condition"] for r in selected],50),"median_mc_p95_0_25us_m":percentile([r["mc_p95_0_25us_m"] for r in selected],50),"p90_mc_p95_0_25us_m":percentile([r["mc_p95_0_25us_m"] for r in selected],90)}
    summary={"method":{"truth_used":False,"grid":{"lat":[args.lat_min,args.lat_max],"lon":[args.lon_min,args.lon_max],"step_deg":args.step},"altitude_m":args.altitude_m,"monte_carlo_draws":args.draws,"seed":args.seed,"classification_thresholds":{"GOOD":"P95@0.25us <=500m, condition <=10, remote separation >=1us","ACCEPTABLE":"<=1500m, condition <=30, separation >=0.5us","POOR":"<=5000m, condition <=100, separation >=0.2us","VERY POOR":"otherwise"}},"pair_distances":distances,"class_counts":counts,"class_fraction":{k:v/len(rows) for k,v in counts.items()},"inside_hull_fraction":sum(hull)/len(hull),"p95_0_25us_m":{"median":percentile([r['mc_p95_0_25us_m'] for r in rows],50),"p90":percentile([r['mc_p95_0_25us_m'] for r in rows],90),"p95":percentile([r['mc_p95_0_25us_m'] for r in rows],95)},"altitude_sensitivity":altitude}
    summary["regional_summary"]=regions
    (out/"current-network-summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":main()
