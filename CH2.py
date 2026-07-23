import os
import sys
import time
import requests
import metview as mv
from datetime import datetime, timedelta
import warnings

warnings.filterwarnings('ignore', category=RuntimeWarning)

LATITUDE = 45.07347491421504
LONGITUDE = 7.543461388723449

FILE_LAST_HOUR = "ultima_ora_icon_ch2_evento.txt"
PNG_OUTPUT = "icon_ch2_evento"

# Regole fisse per ICON-CH2
RUN_DURATION = 120
START_DELAY = 1

def estrai_limiti_run(hourly_data: dict, ref_param: str, utc_offset_sec: int):
    # Logica di convalida Run basata su Open-Meteo Ensemble 
    times = hourly_data.get("time", [])
    mean_vals = hourly_data.get(ref_param, [])

    if not times or not mean_vals: return False, "", None

    end_idx = -1
    for i in range(len(mean_vals) - 1, -1, -1):
        if mean_vals[i] is not None:
            end_idx = i
            break

    if end_idx == -1: return False, "", None

    ultima_ora_valida_str = times[end_idx]

    dt_end_local = datetime.fromisoformat(ultima_ora_valida_str)
    dt_end_utc = dt_end_local - timedelta(seconds=utc_offset_sec)
    
    # Calcolo a ritroso per ottenere il base_time del Run
    dt_run_utc = dt_end_utc - timedelta(hours=RUN_DURATION)
    dt_start_utc = dt_run_utc + timedelta(hours=START_DELAY)

    nome_run = dt_run_utc.strftime("%H") + "Z"

    expected_points = RUN_DURATION - START_DELAY + 1
    
    dt_start_local = dt_start_utc + timedelta(seconds=utc_offset_sec)
    start_time_str = dt_start_local.strftime("%Y-%m-%dT%H:%M")
    
    try:
        start_idx = times.index(start_time_str)
        actual_points = end_idx - start_idx + 1
    except ValueError:
        actual_points = 0

    if actual_points < expected_points:
        print(f"⏳ Run ICON-CH2 {nome_run} in caricamento... ({actual_points}/{expected_points} ore)")
        return False, "", None

    if os.path.exists(FILE_LAST_HOUR):
        with open(FILE_LAST_HOUR, "r") as f:
            ultima_ora_salvata = f.read().strip()
        if ultima_ora_valida_str <= ultima_ora_salvata:
            print(f"✅ Run ICON-CH2 {nome_run} già elaborato per questo evento.")
            return False, "", None

    with open(FILE_LAST_HOUR, "w") as f:
        f.write(ultima_ora_valida_str)

    return True, nome_run, dt_run_utc

def fetch_dati_openmeteo() -> dict:
    URL = "https://ensemble-api.open-meteo.com/v1/ensemble"
    var_list = ["temperature_2m"]
    params = {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "hourly": ",".join(var_list),
        "models": "meteoswiss_icon_ch2_ensemble_mean",
        "timezone": "Europe/Rome",
        "past_days": 1,
        "forecast_days": 6 
    }
    headers = {"User-Agent": "MeteoBot-ICONCH2-Semaforo/3.0"}

    for tentativo in range(3):
        try:
            response = requests.get(URL, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"⚠️ Errore API Open-Meteo: {e}", file=sys.stderr)
            time.sleep(15)
    return {}

def scarica_grib_stac(dt_run_utc: datetime, target_start: datetime, target_end: datetime):
    search_url = "https://data.geo.admin.ch/api/stac/v1/search"
    
    # Payload ufficiale MeteoSvizzera per interrogazione Run specifico e Variabile Pioggia
    payload = {
        "collections": ["ch.meteoschweiz.ogd-forecasting-icon-ch2"],
        "forecast:reference_datetime": dt_run_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
        "forecast:variable": "TOT_PREC",
        "limit": 5000
    }
    headers = {"Content-Type": "application/json"}
    
    print(f"Ricerca GRIB tramite STAC per il run {dt_run_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}...")
    
    try:
        res = requests.post(search_url, json=payload, headers=headers, timeout=30)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f"⚠️ Errore STAC Search: {e}")
        return []

    features = data.get("features", [])
    if not features:
        print("Nessun file trovato nel catalogo STAC per questo run e variabile.")
        return []

    grib_urls = []
    
    for feat in features:
        props = feat.get("properties", {})
        dt_valida_str = props.get("datetime")
        
        if dt_valida_str:
            # Estrazione sicura della data formattata
            clean_str = dt_valida_str.split(".")[0].replace("Z", "")
            dt_valida = datetime.strptime(clean_str, "%Y-%m-%dT%H:%M:%S")
            
            # Selezioniamo in modo chirurgico solo l'orario d'inizio o di fine dell'evento
            if dt_valida == target_start or dt_valida == target_end:
                assets = feat.get("assets", {})
                for key, asset in assets.items():
                    href = asset.get("href")
                    if href and href.upper().endswith(".GRIB2"):
                        grib_urls.append(href)

    if not grib_urls:
        print(f"File GRIB non trovati per le ore target ({target_start} e {target_end}).")
        return []

    grib_files = []
    print(f"Trovati {len(grib_urls)} pacchetti. Inizio download GRIB2 da MeteoSvizzera...")
    for i, url in enumerate(grib_urls):
        local_filename = f"icon_ch2_precip_{i}.grib2"
        try:
            r = requests.get(url, stream=True, timeout=60)
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            grib_files.append(local_filename)
        except Exception as e:
            print(f"Errore download GRIB: {e}")

    return grib_files

def invia_telegram(file_path, caption):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("Credenziali Telegram mancanti.")
        return
        
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {"chat_id": chat_id, "caption": caption}
    
    if os.path.exists(file_path):
        try:
            with open(file_path, "rb") as photo:
                requests.post(url, data=payload, files={"photo": photo})
                print("📸 Mappa evento inviata con successo su Telegram!")
        except Exception as e:
            print(f"Errore invio Telegram: {e}")
    else:
        print(f"File {file_path} non trovato.")

def genera_mappe_metview(dt_run_utc, nome_run, grib_files, target_start, target_end):
    step_start = int((target_start - dt_run_utc).total_seconds() / 3600)
    step_end = int((target_end - dt_run_utc).total_seconds() / 3600)
    
    print(f"Elaborazione mappa evento: 25/07 12:00 - 26/07 12:00 (Step run: +{step_start}h / +{step_end}h)")
    
    # Lettura aggregata dei GRIB scaricati in precedenza
    data = mv.read(grib_files)
    
    coast = mv.mcoast(
        map_coastline_colour="brown", map_coastline_thickness=2, map_coastline_resolution="high",
        map_boundaries="on", map_boundaries_colour="brown", map_boundaries_thickness=2,
        map_administrative_boundaries="on", map_administrative_boundaries_colour="brown",
        map_administrative_boundaries_thickness=1, map_coastline_land_shade="off", 
        map_coastline_sea_shade="off", map_grid="off", map_label="off"
    )
    
    view = mv.geoview(
        map_area_definition="corners", area=[43.5, 6.0, 46.8, 10.5], coastlines=coast,
        subpage_x_position=5, subpage_y_position=12, subpage_x_length=75, subpage_y_length=80     
    )

    lats = [45.07, 44.38, 44.90, 44.91, 45.32, 45.45, 45.56, 45.92]
    lons = [7.68,  7.55,  8.20,  8.61,  8.42,  8.61,  8.05,  8.55]
    sigle = ["TO", "CN", "AT", "AL", "VC", "NO", "BI", "VB"]

    capoluoghi = mv.input_visualiser(
        input_plot_type="geo_points", input_longitude_values=lons, input_latitude_values=lats
    )
    stile_capoluoghi = mv.msymb(
        legend="off", symbol_type="text", symbol_text_list=sigle,
        symbol_text_font_colour="brown", symbol_text_font_size=0.5, symbol_text_font_style="bold"
    )

    rivoli_point = mv.input_visualiser(
        input_plot_type="geo_points", input_longitude_values=[7.51], input_latitude_values=[45.07]
    )
    stile_rivoli = mv.msymb(
        legend="off", symbol_type="marker", symbol_colour="brown", symbol_height=0.4, symbol_marker_index=15     
    )

    tp_style = mv.mcont(
        legend="on", contour="off", contour_shade="on",           
        contour_shade_technique="polygon_shading", contour_shade_method="area_fill",
        contour_level_selection_type="level_list",
        contour_level_list=[1, 2, 5, 10, 15, 20, 25, 30, 40, 50, 60, 80, 100, 150, 200, 300],
        contour_shade_colour_method="list",
        contour_shade_colour_list=[
            "RGB(0.6, 0.8, 1.0)", "RGB(0.0, 0.3, 1.0)", "RGB(0.4, 0.9, 0.4)", "RGB(0.0, 0.6, 0.0)",  
            "RGB(0.6, 0.8, 0.0)", "RGB(1.0, 0.9, 0.0)", "RGB(0.9, 0.7, 0.0)", "RGB(1.0, 0.6, 0.0)",  
            "RGB(1.0, 0.4, 0.0)", "RGB(1.0, 0.2, 0.0)", "RGB(1.0, 0.2, 0.2)", "RGB(0.7, 0.0, 0.0)",  
            "RGB(0.8, 0.2, 1.0)", "RGB(0.5, 0.0, 0.8)", "RGB(0.3, 0.0, 0.5)"   
        ]
    )
    
    legend = mv.mlegend(
        legend_display_type="continuous", legend_box_mode="positional",
        legend_box_x_position=26.5, legend_box_y_position=3.0,   
        legend_box_x_length=1.5, legend_box_y_length=14.0, legend_text_font_size=0.4
    )

    # Estrazione mirata per step temporale
    tp_start = data.select(step=step_start)
    tp_end = data.select(step=step_end)
    
    if len(tp_start) == 0 or len(tp_end) == 0:
        print(f"Errore: GRIB incompleti in lettura per gli step {step_start} o {step_end}.")
        return
        
    tp_diff = tp_end - tp_start
    tp_mean = mv.mean(tp_diff)

    max_val = mv.maxvalue(tp_mean)
    if max_val < 5.0 and max_val > 0.001:
        tp_mean_mm = tp_mean * 1000
    else:
        tp_mean_mm = tp_mean

    str_run = dt_run_utc.strftime('%d/%m/%Y %H:%M')
    str_valida = "25/07/2026 12:00 - 26/07/2026 12:00 UTC"

    title = mv.mtext(
        text_lines=[
            f"ICON-CH2-EPS - Accumulo Precipitativo (Run: {str_run} UTC)", 
            str_valida
        ], 
        text_font_size=0.5, text_colour='black'
    )
    
    png = mv.png_output(output_name=PNG_OUTPUT, output_width=1200)
    mv.setoutput(png)
    mv.plot(view, tp_mean_mm, tp_style, capoluoghi, stile_capoluoghi, rivoli_point, stile_rivoli, legend, title)
    
    file_generato = f"{PNG_OUTPUT}.1.png"
    caption_foto = f"🌧 EVENTO (24h)\n📅 {str_valida}\n⚙️ Media Ensemble MeteoSvizzera\n🕒 Run: {str_run} UTC"
    
    invia_telegram(file_generato, caption_foto)

    # Eliminazione totale file temporanei
    if os.path.exists(file_generato):
        os.remove(file_generato)
    for f in grib_files:
        if os.path.exists(f):
            os.remove(f)

def main():
    print("Verifica stato Run ICON-CH2 via Open-Meteo...")
    openmeteo_data = fetch_dati_openmeteo()
    
    if not openmeteo_data:
        sys.exit(0)
        
    hourly = openmeteo_data.get("hourly", {})
    utc_offset = openmeteo_data.get("utc_offset_seconds", 0)
    
    is_new, nome_run, dt_run_utc = estrai_limiti_run(hourly, "temperature_2m", utc_offset)
    
    if is_new:
        target_start = datetime(2026, 7, 25, 12, 0)
        target_end = datetime(2026, 7, 26, 12, 0)
        
        # Blocco di sicurezza temporale
        step_end = int((target_end - dt_run_utc).total_seconds() / 3600)
        if step_end > 120:
            print(f"L'evento esce dalla coda di previsione a 120h (+{step_end}h). Uscita.")
            sys.exit(0)
        
        grib_files = scarica_grib_stac(dt_run_utc, target_start, target_end)
        if grib_files:
            print(f"🚀 Generazione mappa per il RUN {nome_run} ({dt_run_utc})")
            genera_mappe_metview(dt_run_utc, nome_run, grib_files, target_start, target_end)
    else:
        print("Uscita.")

if __name__ == "__main__":
    main()
