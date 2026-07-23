import os
import requests
import metview as mv
from ecmwf.opendata import Client
import warnings

warnings.filterwarnings('ignore', category=RuntimeWarning)

FILENAME = "piemonte-z925-t925.grib"
PNG_OUTPUT = "piemonte-z925-t925"

def download_and_plot():
    client = Client("ecmwf", beta=False)
    
    try:
        # Scarica Geopotenziale (gh) e Temperatura (t) a 925 hPa
        client.retrieve(
            time=0,
            step=12,
            stream="oper",
            type="fc",
            levtype="pl",
            levelist=[925],
            param=['gh', 't'],
            target=FILENAME
        )
    except Exception as e:
        print(f"Errore download: {e}")
        return False

    if not os.path.exists(FILENAME):
        print("Errore: GRIB non scaricato.")
        return False

    data = mv.read(FILENAME)
    
    t925 = data.select(shortName='t', level=925)
    gh925 = data.select(shortName='gh', level=925)
    
    # Converti geopotenziale in decametri
    gh925 /= 10
    
    # Visuale focalizzata sul Piemonte
    coast = mv.mcoast(
        map_coastline_colour="charcoal",
        map_coastline_resolution="high",  # Risoluzione alta per mappe regionali
        map_coastline_land_shade="on",
        map_coastline_land_shade_colour="cream",
        map_coastline_sea_shade="off",
        map_boundaries="on",
        map_boundaries_colour="charcoal",
        map_boundaries_thickness=1,
        map_disputed_boundaries="off",
        map_grid_colour="tan",
        map_label_height=0.35,
    )
    
    view = mv.geoview(
        map_area_definition="corners",
        area=[44.0, 6.5, 46.5, 9.5], # Sud, Ovest, Nord, Est
        coastlines=coast
    )

    # Stile Temperatura 925 hPa (Dettaglio: 1°C)
    t925_shade = mv.mcont(
        legend="on",
        contour="off",
        contour_shade="on",
        contour_shade_technique="polygon_shading",
        contour_level_selection_type="interval",
        contour_interval=1.0,
        contour_shade_colour_method="calculate",
        contour_shade_min_level=-25.0,
        contour_shade_max_level=35.0,
        contour_shade_min_level_colour="purple",
        contour_shade_max_level_colour="red",
        contour_shade_colour_direction="clockwise"
    )
    
    # Stile Geopotenziale 925 hPa (Isolinee ogni 2 dam per cogliere le sfumature locali)
    gh925_shade = mv.mcont(
        legend="on",
        contour_line_colour="black",
        contour_line_thickness=2,
        contour_highlight="off",
        contour_level_selection_type="interval",
        contour_interval=2.0,
        contour_label_height=0.3
    )
    
    title = mv.mtext(
        text_lines=["Geopotenziale e Temperatura 925 hPa - Piemonte"],
        text_font_size=0.4,
        text_colour='charcoal'
    )
    
    png = mv.png_output(
        output_name=PNG_OUTPUT,
        output_title="piemonte-z925-t925",
        output_width=1000
    )
    
    mv.setoutput(png)
    mv.plot(view, t925, t925_shade, gh925, gh925_shade, title)
    return True

def invia_telegram():
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("Credenziali Telegram non fornite.")
        return
        
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    payload = {"chat_id": chat_id, "caption": "ECMWF T925 + Z925 - Zoom Piemonte (Ris. 1°C)"}
    
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