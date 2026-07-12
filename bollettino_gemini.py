#!/usr/bin/env python3
import os
import requests
import sys
import google.generativeai as genai
from datetime import datetime, timedelta
import locale

# Tentativo di usare l'italiano per i giorni della settimana
try:
    locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8')
except:
    pass

LAT = 45.073443
LON = 7.543472

def interpella_gemini(dati_meteo, info_giornaliere):
    api_key = os.getenv("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('models/gemini-3-flash-preview')    

    oggi_str = datetime.now().strftime("%A %d %B")
    domani_str = (datetime.now() + timedelta(days=1)).strftime("%A %d %B")

    prompt = f"""
    Sei un meteorologo professionista. Scrivi un bollettino meteo discorsivo per Rivoli (TO) per le prossime 48 ore.
    Oggi è {oggi_str}, domani sarà {domani_str}.
    
    RIFERIMENTI UFFICIALI (Usa questi valori per le temperature min/max):
    {info_giornaliere}

    REGOLE DI SCRITTURA (BOLLETTINO AVANZATO):
    1. NON usare elenchi puntati. Scrivi paragrafi fluidi e professionali.
    2. Usa le temperature min/max fornite nei riferimenti ufficiali come base della narrazione.
    
    REGOLA PRECIPITAZIONI E PROBABILITÀ (CRITICA):
    3. Analizza la colonna 'Probabilità'. Se indica 'Assente', IGNORA TOTALMENTE il tema della pioggia, non farne alcun cenno. Se invece indica probabilità:
       - STAGIONALITÀ: Tra MARZO e OTTOBRE avvisa del rischio di "rovesci" o "temporali sparsi". Tra NOVEMBRE e FEBBRAIO usa ESCLUSIVAMENTE termini come "piogge", "precipitazioni".
       - FINESTRA ORARIA: Indica sempre l'intervallo temporale in cui si concentreranno i fenomeni.
       - PROBABILITÀ: Calibra le parole in base al livello (Bassa = fenomeni isolati/possibili, Alta = fenomeni diffusi/certi).
    
    REGOLA NEVE:
    4. Se sono previste precipitazioni e in quelle stesse ore la T_Media è <= 2°C, annuncia esplicitamente la possibilità di nevicate o pioggia mista a neve.
    
    REGOLE DI DISAGIO TERMICO (BIOMETEOROLOGIA):
    5. AFA E CALDO (Basato su T_Media e Dew):
       - ASSENZA DI DISAGIO: Se non rientra nei casi sotto, non menzionare l'afa.
       - DISAGIO MODERATO: Se (T_Media >= 28°C e Dew >= 15°C) OPPURE (T_Media >= 25°C e Dew >= 20°C), segnala afa e disagio moderato.
       - FORTE DISAGIO: Se (T_Media >= 32°C e Dew >= 20°C) OPPURE (T_Media >= 30°C e Dew >= 24°C), segnala caldo opprimente e afa intensa.
       
    6. WIND CHILL (Basato su T_Media e Vento_Medio):
       - ASSENZA DI DISAGIO: Se Vento_Medio < 15 km/h o T_Media > 8°C, non menzionare il freddo percepito.
       - DISAGIO MODERATO: Se (T_Media <= 8°C e Vento_Medio >= 15 km/h), spiega che il vento renderà il freddo più pungente.
       - FORTE DISAGIO: Se T_Media <= 0°C e Vento_Medio è elevato, avvisa di condizioni gelide.
    
    REGOLA NEBBIA/BRINA:
    7. Menziona foschie o nebbie SOLO in caso di inversione termica probabile: aria stagnante (Vento_Medio < 5 km/h), T_Media notturna <= 0°C, e UR% vicina al 100%.
    
    DIVIETO ASSOLUTO SUI TERMINI TECNICI:
    8. È severamente VIETATO menzionare i nomi delle colonne della tabella (come "T_Media", "Probabilità", "UR%", "Dew"). Usa solo linguaggio meteorologico discorsivo.

    DATI ANALITICI ORARI (Ora | T_Media | UR% | Dew | Probabilità | Vento_Medio):
    {dati_meteo}
    """

    try:
        response = model.generate_content(prompt, generation_config={"temperature": 0.3})
        return response.text
    except Exception as e:
        return f"Errore AI: {e}"

def main():
    # Fetch dati deterministici (per UR e Dew Point che non sono presenti nelle Ensemble gratuite)
    dati_det = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": LAT, "longitude": LON,
        "hourly": "relative_humidity_2m,dew_point_2m",
        "models": "icon_d2",
        "timezone": "Europe/Rome", "forecast_days": 2
    }).json()

    # Fetch Ensemble (ICON-D2 EPS) - 20 scenari per Temp, Prec, Vento
    dati_eps = requests.get("https://ensemble-api.open-meteo.com/v1/ensemble", params={
        "latitude": LAT, "longitude": LON,
        "hourly": "temperature_2m,precipitation,wind_speed_10m",
        "models": "icon_d2",
        "timezone": "Europe/Rome", "forecast_days": 2
    }).json()

    hourly_eps = dati_eps.get('hourly', {})
    hourly_det = dati_det.get('hourly', {})
    orari = hourly_eps.get('time', [])
    
    report = "Ora | T_Media | UR% | Dew | Probabilità | Vento_Medio\n"
    
    temp_oggi = []
    temp_domani = []

    for i in range(48): 
        if i >= len(orari): break

        # Estrazione membri EPS per quest'ora
        temp_vals = [hourly_eps.get(f"temperature_2m_member{m:02d}", [0]*48)[i] for m in range(1, 21) if hourly_eps.get(f"temperature_2m_member{m:02d}")]
        prec_vals = [hourly_eps.get(f"precipitation_member{m:02d}", [0]*48)[i] for m in range(1, 21) if hourly_eps.get(f"precipitation_member{m:02d}")]
        wind_vals = [hourly_eps.get(f"wind_speed_10m_member{m:02d}", [0]*48)[i] for m in range(1, 21) if hourly_eps.get(f"wind_speed_10m_member{m:02d}")]

        # Calcolo Medie
        avg_temp = round(sum(temp_vals) / len(temp_vals)) if temp_vals else 0
        avg_wind = round(sum(wind_vals) / len(wind_vals)) if wind_vals else 0
        
        # Dati deterministici per umidità
        ur = hourly_det.get('relative_humidity_2m', [0]*48)[i]
        dew = hourly_det.get('dew_point_2m', [0]*48)[i]

        # Divisione temperature per estrarre min/max esatte dai 20 scenari
        if i < 24:
            temp_oggi.append(avg_temp)
        else:
            temp_domani.append(avg_temp)

        # Logica Probabilità Pioggia
        scenari_over_1mm = sum(1 for v in prec_vals if v >= 1.0)
        if scenari_over_1mm >= 15: prob = "Alta"
        elif scenari_over_1mm >= 10: prob = "Medio-Alta"
        elif scenari_over_1mm >= 5: prob = "Medio-Bassa"
        elif scenari_over_1mm >= 2: prob = "Bassa"
        else: prob = "Assente"

        report += f"{orari[i][-5:]} | {avg_temp}°C | {ur}% | {dew}°C | {prob} | {avg_wind} km/h\n"

    # Preparazione stringa Min/Max passata a Gemini
    min_oggi, max_oggi = (min(temp_oggi), max(temp_oggi)) if temp_oggi else ("N/A", "N/A")
    min_domani, max_domani = (min(temp_domani), max(temp_domani)) if temp_domani else ("N/A", "N/A")
    
    info_giornaliere = f"""
    {datetime.now().strftime("%A %d %B")}: Min {min_oggi}°C, Max {max_oggi}°C
    {(datetime.now() + timedelta(days=1)).strftime("%A %d %B")}: Min {min_domani}°C, Max {max_domani}°C
    """

    # Invia a Gemini
    bollettino = interpella_gemini(report, info_giornaliere)
    
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if token and chat_id:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                      data={"chat_id": chat_id, "text": bollettino, "parse_mode": "Markdown"})
        print("Bollettino inviato con successo!")
    else:
        print("Errore: Token o Chat ID mancanti!")

if __name__ == "__main__":
    main()