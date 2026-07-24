import os
import sys
import time
import json
import glob
import requests
import urllib3
import pytz
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone
import warnings

import cartopy.crs as ccrs
import cartopy.feature as cfeature
import cartopy.io.shapereader as shpreader
from shapely.ops import unary_union

import earthkit.plots
from earthkit.plots.geo import bounds, domains
from earthkit.plots.styles import Style
from earthkit.data import config

from meteodatalab import ogd_api
from meteodatalab.operators import regrid
from rasterio.crs import CRS

warnings.filterwarnings('ignore')
urllib3.disable_warnings()
config.set("cache-policy", "temporary")

LATITUDE = 45.07
LONGITUDE = 7.54
FILE_LAST_HOUR = "ultima_ora_icon_ch2_cape.txt"

def estrai_limiti_run(hourly_data: dict, ref_param: str) -> tuple[bool, str, datetime]:
    times = hourly_data.get("time", [])
    mean_vals = hourly_data.get(ref_param, [])
    if not times or not mean_vals: return False, "", None
    
    end_idx = -1
    for i in range(len(mean_vals) - 1, -1, -1):
        if mean_vals[i] is not None:
            end_idx = i
            break
            
    if end_idx == -1: return False, "", None
    
    rome_tz = pytz.timezone("Europe/Rome")
    ultima_ora_valida_str = times[end_idx]
    
    dt_end_local = rome_tz.localize(datetime.fromisoformat(ultima_ora_valida_str))
    dt_end_utc = dt_end_local.astimezone(timezone.utc)
    
    dt_run_utc = dt_end_utc - timedelta(hours=120)
    
    if os.path.exists(FILE_LAST_HOUR):
        with open(FILE_LAST_HOUR, "r") as f:
            ultima_ora_salvata = f.read().strip()
        if ultima_ora_valida_str <= ultima_ora_salvata:
            return False, "", None

    with open(FILE_LAST_HOUR, "w") as f:
        f.write(ultima_ora_valida_str)

    return True, dt_run_utc.strftime("%H") + "Z", dt_run_utc

def invia_album_telegram(file_paths: list, caption: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return
    
    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    media = []
    files = {}
    
    for idx, path in enumerate(file_paths):
        media.append({"type": "photo", "media": f"attach://photo_{idx}", "caption": caption if idx == 0 else ""})
        files[f"photo_{idx}"] = open(path, "rb")

    try:
        requests.post(url, data={"chat_id": chat_id, "media": json.dumps(media)}, files=files)
    except: pass
    finally:
        for f in files.values(): f.close()

def raggruppa_in_blocchi(dt_run_local: datetime) -> dict:
    blocchi = {}
    for h in range(1, 121):
        dt_target = dt_run_local + timedelta(hours=h)
        date_str = dt_target.date().strftime("%Y-%m-%d")
        hour = dt_target.hour
        
        if hour == 0: b_name = "18-24" # semplificazione
        elif 1 <= hour <= 6: b_name = "00-06"
        elif 7 <= hour <= 12: b_name = "06-12"
        elif 13 <= hour <= 18: b_name = "12-18"
        else: b_name = "18-24"
            
        key = f"{date_str} ({b_name})"
        if key not in blocchi: blocchi[key] = []
        blocchi[key].append(h)
    return blocchi

def genera_album_cape(dt_run_utc: datetime, nome_run: str):
    rome_tz = pytz.timezone("Europe/Rome")
    dt_run_local = dt_run_utc.astimezone(rome_tz)
    blocchi = raggruppa_in_blocchi(dt_run_local)

    xmin, xmax, ymin, ymax = 6.0, 10.5, 43.5, 46.8
    destination = regrid.RegularGrid(CRS.from_string("epsg:4326"), 300, 300, xmin, xmax, ymin, ymax)

    # Scala colori CAPE: giallo -> arancio -> rosso -> viola (J/kg)
    my_levels = [500, 750, 1000, 1250, 1500, 2000, 2500, 3000]
    my_colors = ["#fff7bc", "#fee391", "#fec44f", "#fe9929", "#ec7014", "#cc4c02", "#8c2d04", "#7a0177"]
    domain = domains.Domain.from_bbox(bbox=bounds.BoundingBox(xmin, xmax, ymin, ymax, ccrs.Geodetic()), name="Piemonte")

    # Confini (zorder=10/11 per stare sopra la mappa)
    prov_geoms = []
    for s in glob.glob("**/*ProvCM*.shp", recursive=True):
        for r in shpreader.Reader(s).records():
            if any("piemonte" in str(v).lower() for v in r.attributes.values()): prov_geoms.append(r.geometry)
    
    prov_feature = cfeature.ShapelyFeature(prov_geoms, ccrs.PlateCarree(), edgecolor='black', facecolor='none', linewidth=0.5, linestyle=':', zorder=10) if prov_geoms else None
    regione_feature = cfeature.ShapelyFeature([unary_union(prov_geoms)], ccrs.PlateCarree(), edgecolor='black', facecolor='none', linewidth=2.0, linestyle='-', zorder=11) if prov_geoms else None

    for block_name, ore_list in blocchi.items():
        req = ogd_api.Request(collection="ogd-forecasting-icon-ch2", variable="CAPE_MU", ref_time=dt_run_utc, perturbed=True, lead_time=[f"P{l // 24}DT{l % 24}H" for l in ore_list])
        
        try:
            cape_raw = ogd_api.get_from_ogd(req)
            cape_mean = cape_raw.mean(dim="eps")
        except: continue

        percorsi_foto = []
        for h in ore_list:
            cape_geo = regrid.iconremap(cape_mean.sel(lead_time=np.timedelta64(h, 'h')), destination)
            chart = earthkit.plots.Map(domain=domain)
            chart.grid_cells(cape_geo, x="lon", y="lat", style=Style(colors=my_colors, levels=my_levels))

            if regione_feature: chart.ax.add_feature(regione_feature)
            if prov_feature: chart.ax.add_feature(prov_feature)
            chart.coastlines(linewidth=0.5, zorder=10)

            # Rivoli e Capoluoghi (zorder 12)
            chart.ax.plot(7.51, 45.07, marker='o', color='brown', markersize=6, transform=ccrs.PlateCarree(), zorder=12)
            for lon, lat, sigla in zip([7.68, 7.55, 8.20, 8.61, 8.42, 8.61, 8.05, 8.55], [45.07, 44.38, 44.90, 44.91, 45.32, 45.45, 45.56, 45.92], ["TO", "CN", "AT", "AL", "VC", "NO", "BI", "VB"]):
                chart.ax.plot(lon, lat, marker='o', color='black', markersize=3, transform=ccrs.PlateCarree(), zorder=12)
                chart.ax.text(lon + 0.05, lat + 0.05, sigla, color='black', fontsize=9, fontweight='bold', transform=ccrs.PlateCarree(), zorder=12)

            chart.title(f"ICON-CH2 EPS - CAPE MU (J/kg)\nRun: {dt_run_utc.strftime('%Y-%m-%d %H:%M UTC')} | {block_name}")
            chart.legend(label="CAPE MU (J/kg)")
            
            f_name = f"cape_{h}.png"
            chart.save(f_name)
            percorsi_foto.append(f_name)
            plt.close(chart.fig)
        
        invia_album_telegram(percorsi_foto, f"⚡ ICON-CH2 EPS: CAPE MU (Instabilità)\n🗓 {block_name}")
        for f in percorsi_foto: os.remove(f)

def main():
    data = fetch_dati_con_retry()
    if data:
        is_new, nome_run, dt_run_utc = estrai_limiti_run(data.get("hourly", {}), "temperature_2m")
        if is_new: genera_album_cape(dt_run_utc, nome_run)

if __name__ == "__main__": main()