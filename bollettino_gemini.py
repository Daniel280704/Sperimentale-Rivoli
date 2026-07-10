#!/usr/bin/env python3
import os
import requests
import sys
import google.generativeai as genai
from datetime import datetime, timedelta

LAT = 45.0716
LON = 7.5157

def interpella_gemini(dati_meteo):
    api_key = os.getenv("GEMINI_API_KEY")
    genai.configure(api_key=api_key)
    # Usiamo il modello confermato dal tuo test[cite: 1]
    model = genai.GenerativeModel('models/gemini-3.5-flash')
    
    # Calcolo date per il prompt
    oggi = datetime.now().strftime("%d %B")
    domani = (datetime.now() + timedelta(days=1)).strftime("%d %B")
    
    prompt = f"""
    Sei un meteorologo professionista. Scrivi un bollettino meteo coeso e discorsivo per Rivoli (TO) per le prossime 48 ore ({oggi} e {domani}).
    
    REGOLE DI SCRITTURA:
    1. NON usare elenchi puntati o tabelle nel testo. Scrivi paragrafi fluidi.
    2. Stile richiesto (Esempio): "La giornata di sabato comincerà con cielo parzialmente nuvoloso e una temperatura minima notturna di X°C, seguirà una massima di Y°C; nel pomeriggio, tra le 16 e le 18, non sono esclusi rovesci con raffiche di vento fino a ZZ km/h. Migliora in serata."
    3. Include T-min, T-max (calcolale dai dati), nuvolosità, vento/raffiche e rischio precipitazioni.
    4. Focalizzati su eventi rilevanti: se il meteo è stabile, sintetizza brevemente. Se ci sono temporali o vento forte, sii preciso sull'orario.
    
    DATI ANALITICI (Ora | T | Prec.D2 | EPS-Max | Vento | Raffica):
    {dati_meteo}
    """

    try:
        response = model.generate_content(prompt, generation_config={"temperature": 0.3})
        return response.text
    except Exception as e:
        return f"Errore AI: {e}"

def main():
    # Fetch dati 48 ore (forecast_days=2)
    dati = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": LAT, "longitude": LON,
        "hourly": "temperature_2m,precipitation,cloud_cover,wind_speed_10m,wind_gusts_10m",
        "models": "icon_d2",
        "timezone": "Europe/Rome", "forecast_days": 2
    }).json()
    
    dati_eps = requests.get("https://ensemble-api.open-meteo.com/v1/ensemble", params={
        "latitude": LAT, "longitude": LON,
        "hourly": "precipitation",
        "models": "icon_d2",
        "timezone": "Europe/Rome", "forecast_days": 2
    }).json()

    # Preparazione report 48 ore
    report = "Ora | T | Prec.D2 | EPS-Max | Vento | Raffica\n"
    hourly = dati.get('hourly', {})
    orari = hourly.get('time', [])
    
    for i in range(48): # 48 ore
        if i >= len(orari): break
        
        eps_vals = [dati_eps['hourly'].get(f"precipitation_member{m:02d}", [0]*48)[i] or 0 for m in range(1,21)]
        eps_max = max(eps_vals) if eps_vals else 0.0
            
        t = hourly.get('temperature_2m', [0]*48)[i]
        p_d2 = hourly.get('precipitation', [0]*48)[i] or 0
        v_vel = hourly.get('wind_speed_10m', [0]*48)[i]
        v_raf = hourly.get('wind_gusts_10m', [0]*48)[i]
        
        report += f"{orari[i][-5:]} | {t}°C | {p_d2} | {eps_max:.1f} | {v_vel}km/h | {v_raf}km/h\n"

    # Invio
    bollettino = interpella_gemini(report)
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if token and chat_id:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                      data={"chat_id": chat_id, "text": bollettino, "parse_mode": "Markdown"})
    else:
        print(bollettino)

if __name__ == "__main__":
    main()
