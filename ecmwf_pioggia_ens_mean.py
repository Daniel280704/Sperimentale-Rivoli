import os
import requests
import metview as mv
from ecmwf.opendata import Client
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings('ignore', category=RuntimeWarning)

FILENAME = "piemonte-tp-pf.grib"
PNG_OUTPUT = "piemonte-tp-ens-mean"

def download_and_plot():
    client = Client("ecmwf", beta=False)
    
    # Run base: 23 Luglio 2026 alle 00:00 UTC.
    base_date = datetime(2026, 7, 23)
    start_date = base_date + timedelta(hours=24)
    end_date = base_date + timedelta(hours=48)
    
    # Scarichiamo i 50 spaghi per lo step 24h e 48h
    try:
        client.retrieve(
            date=base_date.strftime("%Y%m%d"),
            time=0,
            step=[24, 48],
            stream="enfo",     
            type="pf",         
            levtype="sfc",     
            param=['tp'],
            target=FILENAME
        )
    except Exception as e:
        print(f"Errore download: {e}")
        return False

    if not os.path.exists(FILENAME):
        print("Errore: GRIB non scaricato.")
        return False

    data = mv.read(FILENAME)
    
    tp_24 = data.select(step=24)
    tp_48 = data.select(step=48)
    
    # 1. Differenza in mm per ogni scenario (accumulo di 24 ore)
    tp_diff_mm = (tp_48 - tp_24) * 1000
    
    # 2. MEDIA di tutti i 50 scenari
    tp_mean_mm = mv.mean(tp_diff_mm)
    
    # CONFINI GEOGRAFICI E PROVINCE ISTAT
    coast = mv.mcoast(
        map_coastline_colour="brown",
        map_coastline_thickness=2,
        map_coastline_resolution="high",
        map_boundaries="on",
        map_boundaries_colour="brown",
        map_boundaries_thickness=2,
        map_administrative_boundaries="on", 
        map_administrative_boundaries_colour="brown",
        map_administrative_boundaries_thickness=2,
        
        # SHAPEFILE PROVINCE (Nome ufficiale ISTAT)
        map_user_layer="on",
        map_user_layer_name="ProvCM01012026_WGS84.shp", 
        map_user_layer_colour="brown",
        map_user_layer_thickness=1,
        
        map_coastline_land_shade="off", 
        map_coastline_sea_shade="off",
        map_grid="off",
        map_label="off"
    )
    
    # IMPAGINAZIONE: Mappa stretta al 75% della larghezza per far spazio alla legenda a destra
    view = mv.geoview(
        map_area_definition="corners",
        area=[43.5, 6.0, 46.8, 10.5], 
        coastlines=coast,
        subpage_x_position=5,
        subpage_y_position=12,   
        subpage_x_length=75,
        subpage_y_length=80     
    )

    # CAPOLUOGHI DI PROVINCIA (Sigle testuali)
    lats = [45.07, 44.38, 44.90, 44.91, 45.32, 45.45, 45.56, 45.92]
    lons = [7.68,  7.55,  8.20,  8.61,  8.42,  8.61,  8.05,  8.55]
    sigle = ["TO", "CN", "AT", "AL", "VC", "NO", "BI", "VB"]

    capoluoghi = mv.input_visualiser(
        input_plot_type="geo_points",
        input_longitude_values=lons,
        input_latitude_values=lats
    )

    stile_capoluoghi = mv.msymb(
        legend="off",
        symbol_type="text",
        symbol_text_list=sigle,
        symbol_text_font_colour="brown",
        symbol_text_font_size=0.5,
        symbol_text_font_style="bold"
    )

    # RIVOLI
    lat_rivoli = [45.07]
    lon_rivoli = [7.51]

    rivoli_point = mv.input_visualiser(
        input_plot_type="geo_points",
        input_longitude_values=lon_rivoli,
        input_latitude_values=lat_rivoli
    )

    stile_rivoli = mv.msymb(
        legend="off",
        symbol_type="marker",
        symbol_colour="brown",     
        symbol_height=0.4,
        symbol_marker_index=15     
    )

    # STILE PIOGGIA
    tp_style = mv.mcont(
        legend="on",                  
        contour="off",                
        contour_shade="on",           
        contour_shade_technique="polygon_shading",
        contour_level_selection_type="level_list",
        contour_level_list=[0.5, 2, 5, 10, 15, 20, 30, 40, 50, 65, 80, 100, 150, 300],
        contour_shade_colour_method="list",
        contour_shade_colour_list=[
            "RGB(0.6, 0.8, 1.0)",  
            "RGB(0.0, 0.3, 1.0)",  
            "RGB(0.4, 0.9, 0.4)",  
            "RGB(0.0, 0.6, 0.0)",  
            "RGB(1.0, 0.9, 0.0)",  
            "RGB(0.9, 0.7, 0.0)",  
            "RGB(1.0, 0.6, 0.0)",  
            "RGB(1.0, 0.4, 0.0)",  
            "RGB(1.0, 0.2, 0.2)",  
            "RGB(0.7, 0.0, 0.0)",  
            "RGB(0.8, 0.2, 1.0)",  
            "RGB(0.5, 0.0, 0.8)",  
            "RGB(0.3, 0.0, 0.5)"   
        ]
    )
    
    # LEGENDA IN VERTICALE A DESTRA
    legend = mv.mlegend(
        legend_display_type="continuous",
        legend_box_mode="positional",
        legend_box_x_position=26.5,  # Posizionata a destra nel foglio
        legend_box_y_position=3.0,   # Allineata in alto
        legend_box_x_length=1.5,     # Barra stretta
        legend_box_y_length=14.0,    # Barra lunga verticalmente
        legend_text_font_size=0.4
    )
    
    # TITOLO PERSONALIZZATO
    title_text = f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"
    title = mv.mtext(
        text_lines=[
            "ECMWF ENS - precipitazioni 24 ore",
            title_text
        ], 
        text_font_size=0.5,
        text_colour='black'
    )
    
    png = mv.png_output(
        output_name=PNG_OUTPUT,
        output_title="piemonte-tp-ens-mean",
        output_width=1200 
    )
    
    mv.setoutput(png)
    mv.plot(view, tp_mean_mm, tp_style, capoluoghi, stile_capoluoghi, rivoli_point, stile_rivoli, legend, title)
    return True

def invia_telegram():
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("Credenziali Telegram non fornite.")
        return
        
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {"chat_id": chat_id, "caption": "Media Scenari ENS (50 Spaghi) - Precipitazioni 24h"}
    
    file_path = f"{PNG_OUTPUT}.1.png"
    
    if os.path.exists(file_path):
        try:
            with open(file_path, "rb") as photo:
                requests.post(url, data=payload, files={"photo": photo})
                print("Inviato su Telegram!")
        except Exception as e:
            print(f"Errore invio Telegram: {e}")
    else:
        print(f"File {file_path} non trovato.")

if __name__ == "__main__":
    if download_and_plot():
        invia_telegram()
