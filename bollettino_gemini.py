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
    # Nota: Ho lasciato il modello che avevi inserito, ma se dovesse dare errore 
    # ti consiglio di usare 'models/gemini-1.5-flash' o 'models/gemini-1.5-pro'
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
    3. Analizza la colonna 'Probabilità'. Se indica 'Assente', IGNORA TOTALMENTE il tema della pioggia. Se invece è presente:
       - STAGIONALITÀ: Tra MARZO e OTTOBRE usa "rovesci" o "temporali". Tra NOVEMBRE e FEBBRAIO usa "piogge" o "precipitazioni".
       - Includi sempre la finestra oraria dei fenomeni e riporta letteralmente il livello di rischio e l'intensità indicati nella tabella.
    
    REGOLA NEVE:
    4. Se sono previste precipitazioni e in quelle stesse ore la T_Media è <= 2°C, annuncia la possibilità di nevicate o pioggia mista a neve.
    
    REGOLE DI DISAGIO TERMICO (BIOMETEOROLOGIA):
    5. AFA E CALDO (Valuta in base ai dati della giornata):
       - DISAGIO MODERATO: (T_Max >= 28°C e Dew >= 15°C) OPPURE (T_Max >= 25°C e Dew >= 20°C).
       - FORTE DISAGIO: (T_Max >= 32°C e Dew >= 20°C) OPPURE (T_Max >= 30°C e Dew >= 24°C).
       ATTENZIONE: NON spiegare nel bollettino i motivi del disagio. Limitati ESCLUSIVAMENTE ad aggiungere il livello tra parentesi subito dopo aver menzionato la temperatura massima. 
       Esempio corretto: "...con una massima di 33°C (Forte Disagio)." Se non c'è disagio, non inserire nulla.
       
    6. WIND CHILL (Basato su T_Media e Vento_Medio):
       - Se (T_Media <= 8°C e Vento_Medio >= 15 km/h), spiega che il vento renderà il freddo più pungente.
    
    REGOLA NEBBIA/BRINA:
    7. Menziona foschie/nebbie SOLO per: aria stagnante (Vento_Medio < 5 km/h), T_Media notturna <= 0°C, e UR% vicina al 100%.
    
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

def calcola_prob_pioggia(prec_d2, prec_ch2):
    if not prec_d2 or not prec_ch2:
        return "Assente"

    # Funzione interna per calcolare la percentuale di scenari che vedono la soglia
    def pct(vals, th):
        return (sum(1 for v in vals if v >= th) / len(vals)) * 100

    p1_d2, p3_d2, p5_d2 = pct(prec_d2, 1), pct(prec_d2, 3), pct(prec_d2, 5)
    p1_ch, p3_ch, p5_ch = pct(prec_ch2, 1), pct(prec_ch2, 3), pct(prec_ch2, 5)

    # REQUISITO BASE: Devono essere concordi almeno sul 10% per la soglia di 1mm
    if p1_d2 >= 10 and p1_ch >= 10:
        
        # Una volta concordi, per le intensità basta che uno dei due modelli veda la percentuale
        max5 = max(p5_d2, p5_ch)
        max3 = max(p3_d2, p3_ch)
        max1 = max(p1_d2, p1_ch)

        def livello(p):
            if p >= 30: return "Serio rischio"
            if p >= 20: return "Probabile"
            return "Minima possibilità"

        # Valutiamo dall'intensità maggiore a quella minore
        if max5 >= 10:
            return f"{livello(max5)} pioggia intensa o instabilità diffusa"
        if max3 >= 10:
            return f"{livello(max3)} pioggia moderata o instabilità sparsa"
        if max1 >= 10:
            return f"{livello(max1)} pioggia debole o instabilità isolata"

    return "Assente"

def estrai_membri(hourly_data, prefisso_variabile, indice_ora):
    # Raccoglie dinamicamente tutti i membri disponibili per una certa variabile a una certa ora
    valori = []
    for key, lst in hourly_data.items():
        if key.startswith(prefisso_variabile):
            if indice_ora < len(lst) and lst[indice_ora] is not None:
                valori.append(lst[indice_ora])
    return valori

def main():
    # 1. Fetch Dati Deterministici D2 (include Temperature per la media a 3 vie)
    dati_det = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": LAT, "longitude": LON,
        "hourly": "temperature_2m,relative_humidity_2m,dew_point_2m",
        "models": "icon_d2",
        "timezone": "Europe/Rome", "forecast_days": 2
    }).json()

    # 2. Fetch Ensemble ICON-D2
    dati_eps_d2 = requests.get("https://ensemble-api.open-meteo.com/v1/ensemble", params={
        "latitude": LAT, "longitude": LON,
        "hourly": "temperature_2m,precipitation,wind_speed_10m",
        "models": "icon_d2",
        "timezone": "Europe/Rome", "forecast_days": 2
    }).json()

    # 3. Fetch Ensemble ICON-CH2
    dati_eps_ch2 = requests.get("https://ensemble-api.open-meteo.com/v1/ensemble", params={
        "latitude": LAT, "longitude": LON,
        "hourly": "temperature_2m,precipitation,wind_speed_10m",
        "models": "icon_ch2",
        "timezone": "Europe/Rome", "forecast_days": 2
    }).json()

    hourly_det = dati_det.get('hourly', {})
    hourly_d2 = dati_eps_d2.get('hourly', {})
    hourly_ch2 = dati_eps_ch2.get('hourly', {})
    orari = hourly_det.get('time', [])
    
    report = "Ora | T_Media | UR% | Dew | Probabilità | Vento_Medio\n"
    
    temp_oggi = []
    temp_domani = []

    for i in range(48): 
        if i >= len(orari): break

        # Estrazione membri temperatura
        t_d2_mem = estrai_membri(hourly_d2, "temperature_2m_member", i)
        t_ch2_mem = estrai_membri(hourly_ch2, "temperature_2m_member", i)
        t_det = hourly_det.get('temperature_2m', [0]*48)[i]

        # Estrazione membri vento e precipitazioni
        w_d2_mem = estrai_membri(hourly_d2, "wind_speed_10m_member", i)
        w_ch2_mem = estrai_membri(hourly_ch2, "wind_speed_10m_member", i)
        prec_d2 = estrai_membri(hourly_d2, "precipitation_member", i)
        prec_ch2 = estrai_membri(hourly_ch2, "precipitation_member", i)

        # ---------------------------------------------------------
        # CALCOLI MEDIE
        # ---------------------------------------------------------
        avg_t_d2 = sum(t_d2_mem) / len(t_d2_mem) if t_d2_mem else 0
        avg_t_ch2 = sum(t_ch2_mem) / len(t_ch2_mem) if t_ch2_mem else 0
        
        # Temperatura finale: media arrotondata all'intero (D2 EPS, CH2 EPS, D2 Det)
        temp_finale = round((avg_t_d2 + avg_t_ch2 + t_det) / 3)
        
        # Vento finale: media delle due medie ensemble
        avg_w_d2 = sum(w_d2_mem) / len(w_d2_mem) if w_d2_mem else 0
        avg_w_ch2 = sum(w_ch2_mem) / len(w_ch2_mem) if w_ch2_mem else 0
        vento_finale = round((avg_w_d2 + avg_w_ch2) / 2)
        
        # Dati deterministici per umidità
        ur = hourly_det.get('relative_humidity_2m', [0]*48)[i]
        dew = hourly_det.get('dew_point_2m', [0]*48)[i]

        # Archiviazione temperature per calcolo Min/Max giornaliero
        if i < 24:
            temp_oggi.append(temp_finale)
        else:
            temp_domani.append(temp_finale)

        # ---------------------------------------------------------
        # CALCOLO PROBABILITÀ PIOGGIA
        # ---------------------------------------------------------
        prob = calcola_prob_pioggia(prec_d2, prec_ch2)

        report += f"{orari[i][-5:]} | {temp_finale}°C | {ur}% | {dew}°C | {prob} | {vento_finale} km/h\n"

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
