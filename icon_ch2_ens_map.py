import os
import sys
import time
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
FILE_LAST_HOUR = "ultima_ora_icon_ch2_stac.txt"

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
    
    # Innesco sapendo che ICON-CH2 dura 120 ore
    dt_run_utc = dt_end_utc - timedelta(hours=120)
    
    dt_start_local = (dt_run_utc + timedelta(hours=1)).astimezone(rome_tz)
    start_time_str = dt_start_local.strftime("%Y-%m-%dT%H:%M")
    
    try:
        start_idx = times.index(start_time_str)
    except ValueError:
        return False, "", None
        
    expected_points = 120
    actual_points = end_idx - start_idx + 1
    nome_run = dt_run_utc.strftime("%H") + "Z"
    
    if actual_points < expected_points:
        print(f"⏳ Run {nome_run} in caricamento... ({actual_points}/{expected_points} ore)")
        return False, "", None
        
    if os.path.exists(FILE_LAST_HOUR):
        with open(FILE_LAST_HOUR, "r") as f:
            ultima_ora_salvata = f.read().strip()
        if ultima_ora_valida_str <= ultima_ora_salvata:
            print(f"✅ Run ICON-CH2 {nome_run} già elaborato in precedenza.")
            return False, "", None

    with open(FILE_LAST_HOUR, "w") as f:
        f.write(ultima_ora_valida_str)

    return True, nome_run, dt_run_utc

def fetch_dati_con_retry() -> dict:
    URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": "temperature_2m",
        "models": "meteoswiss_icon_ch2_ensemble_mean",
        "timezone": "Europe/Rome",
        "past_days": 1,
        "forecast_days": 6 
    }
    for _ in range(3):
        try:
            r = requests.get(URL, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            time.sleep(15)
    return {}

def invia_telegram(file_path: str, caption: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id: return
        
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {"chat_id": chat_id, "caption": caption}
    
    if os.path.exists(file_path):
        try:
            with open(file_path, "rb") as photo:
                requests.post(url, data=payload, files={"photo": photo})
        except Exception as e:
            pass

def genera_mappe_accumuli(dt_run_utc: datetime, nome_run: str):
    rome_tz = pytz.timezone("Europe/Rome")
    dt_run_local = dt_run_utc.astimezone(rome_tz)
    end_time_local = dt_run_local + timedelta(hours=120)

    # 1. Calcolo intervalli esatti (mezzanotte-mezzanotte locale)
    intervals = []
    curr_lead = 0
    while curr_lead < 120:
        start_dt = dt_run_local + timedelta(hours=curr_lead)
        next_midnight = (start_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        if next_midnight > end_time_local:
            next_midnight = end_time_local
            
        end_lead = int((next_midnight - dt_run_local).total_seconds() / 3600)
        if end_lead > curr_lead:
            intervals.append((curr_lead, end_lead))
        curr_lead = end_lead

    unique_leads = set()
    for a, b in intervals:
        if a > 0: unique_leads.add(a)
        if b > 0: unique_leads.add(b)

    lead_times_str = [f"P{l // 24}DT{l % 24}H" for l in unique_leads]

    print(f"Scaricamento dati ICON-CH2 EPS per il run {nome_run}...")
    req = ogd_api.Request(
        collection="ogd-forecasting-icon-ch2",
        variable="TOT_PREC",
        ref_time=dt_run_utc,
        perturbed=True,
        lead_time=lead_times_str,
    )
    
    try:
        tot_prec = ogd_api.get_from_ogd(req)
    except Exception as e:
        print(f"Errore download OGD API: {e}")
        if os.path.exists(FILE_LAST_HOUR): os.remove(FILE_LAST_HOUR)
        return

    print("Calcolo media ensemble globale...")
    prec_mean = tot_prec.mean(dim="eps")

    xmin, xmax, ymin, ymax = 6.0, 10.5, 43.5, 46.8
    nx, ny = 300, 300
    destination = regrid.RegularGrid(CRS.from_string("epsg:4326"), nx, ny, xmin, xmax, ymin, ymax)

    my_levels = [1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 150, 200, 300]
    my_colors = ["#99ccff", "#004cff", "#66e666", "#009900", "#99cc00", "#ffe600", "#e6b300", "#ff9900", "#ff6600", "#ff3300", "#ff3333", "#b30000", "#cc33ff", "#8000cc", "#4d0080"]
    domain = domains.Domain.from_bbox(bbox=bounds.BoundingBox(xmin, xmax, ymin, ymax, ccrs.Geodetic()), name="Piemonte")

    # 2. Elaborazione dinamica dei confini da Shapefile
    prov_geoms = []
    
    # Ricerca dinamica del file in caso di percorsi alterati da GitHub
    shp_list = glob.glob("**/*ProvCM*.shp", recursive=True)
    
    if shp_list:
        shp_path = shp_list[0]
        print(f"Shapefile trovato in: {shp_path}")
        try:
            for record in shpreader.Reader(shp_path).records():
                # Filtra solo le province piemontesi
                if any("piemonte" in str(v).lower() for v in record.attributes.values()):
                    prov_geoms.append(record.geometry)
            if not prov_geoms:
                prov_geoms = [r.geometry for r in shpreader.Reader(shp_path).records()]
        except Exception as e:
            print(f"Errore lettura shapefile: {e}")

    # Fallback di sicurezza: se manca lo shapefile, usa i dati globali per il Piemonte
    if not prov_geoms:
        print("Fallback: Utilizzo confini regionali di Natural Earth per il Piemonte...")
        ne_path = shpreader.natural_earth(resolution='10m', category='cultural', name='admin_1_states_provinces')
        for record in shpreader.Reader(ne_path).records():
            if record.attributes.get('name', '').lower() == 'piemonte':
                prov_geoms.append(record.geometry)

    prov_feature = None
    regione_feature = None
    
    if prov_geoms:
        # ZORDER=10 forza i confini a posizionarsi SOPRA i colori della pioggia
        prov_feature = cfeature.ShapelyFeature(prov_geoms, ccrs.PlateCarree(), edgecolor='black', facecolor='none', linewidth=0.5, linestyle=':', zorder=10)
        
        regione_geom = unary_union(prov_geoms)
        # ZORDER=11 per i bordi spessi esterni
        regione_feature = cfeature.ShapelyFeature([regione_geom], ccrs.PlateCarree(), edgecolor='black', facecolor='none', linewidth=2.0, linestyle='-', zorder=11)

    lats = [45.07, 44.38, 44.90, 44.91, 45.32, 45.45, 45.56, 45.92]
    lons = [7.68,  7.55,  8.20,  8.61,  8.42,  8.61,  8.05,  8.55]
    sigle = ["TO", "CN", "AT", "AL", "VC", "NO", "BI", "VB"]

    # 3. Generazione Mappe per Giorno
    for a, b in intervals:
        print(f"Elaborazione accumulo: +{a}h -> +{b}h")
        
        if a == 0:
            prec_diff = prec_mean.sel(lead_time=np.timedelta64(b, 'h'))
        else:
            prec_diff = prec_mean.sel(lead_time=np.timedelta64(b, 'h')) - prec_mean.sel(lead_time=np.timedelta64(a, 'h'))

        prec_geo = regrid.iconremap(prec_diff, destination)

        chart = earthkit.plots.Map(domain=domain)
        chart.grid_cells(prec_geo, x="lon", y="lat", style=Style(colors=my_colors, levels=my_levels))

        # Disegna in modo esclusivo i confini del Piemonte
        if regione_feature: chart.ax.add_feature(regione_feature)
        if prov_feature: chart.ax.add_feature(prov_feature)

        # ZORDER=12 per assicurarsi che città e indicatori dominino su tutto
        chart.ax.plot(7.51, 45.07, marker='o', color='brown', markersize=6, transform=ccrs.PlateCarree(), zorder=12)

        for lon, lat, sigla in zip(lons, lats, sigle):
            chart.ax.plot(lon, lat, marker='o', color='black', markersize=3, transform=ccrs.PlateCarree(), zorder=12)
            chart.ax.text(lon + 0.05, lat + 0.05, sigla, color='black', fontsize=9, fontweight='bold', transform=ccrs.PlateCarree(), zorder=12)

        start_local = dt_run_local + timedelta(hours=a)
        end_local = dt_run_local + timedelta(hours=b)
        str_valida = f"Dalle {start_local.strftime('%H:%M del %d/%m')} alle {end_local.strftime('%H:%M del %d/%m')}"

        title = f"ICON-CH2 EPS - Accumulo Precipitazioni\nRun: {dt_run_utc.strftime('%d/%m/%Y %H:%M UTC')} | {str_valida}"
        chart.title(title)
        chart.legend(label="Precipitazioni (mm)")

        filename = f"accumulo_{a}_{b}.png"
        chart.save(filename)

        invia_telegram(filename, f"🌧 ICON-CH2 EPS: Accumulo Pioggia\n🗓 {str_valida}\n⚙️ Run {nome_run}")
        
        plt.close(chart.fig)
        time.sleep(10)

def main():
    print("Cerco l'ultimo run completo ICON-CH2 via Open-Meteo...")
    data = fetch_dati_con_retry()
    if not data: sys.exit(0)
        
    hourly = data.get("hourly", {})
    
    is_new, nome_run, dt_run_utc = estrai_limiti_run(hourly, "temperature_2m")
    
    if is_new:
        print(f"🚀 Lancio generazione mappe ICON-CH2 per il RUN {nome_run} ({dt_run_utc})")
        genera_mappe_accumuli(dt_run_utc, nome_run)
    else:
        print("Nessun nuovo run completo trovato. Uscita.")

if __name__ == "__main__":
    main()
