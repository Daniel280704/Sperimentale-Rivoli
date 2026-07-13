#!/usr/bin/env python3
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from groq import Groq

LAT = 45.073443
LON = 7.543472

GIORNI_IT = {0: "lunedì", 1: "martedì", 2: "mercoledì", 3: "giovedì", 4: "venerdì", 5: "sabato", 6: "domenica"}
MESI_IT = {1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno", 
           7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre"}

def scarica_dati_con_retry(url, params, max_retries=3):
    for tentativo in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if tentativo < max_retries - 1: time.sleep(10)
            else: raise e

def formatta_data_it(dt):
    return f"{GIORNI_IT[dt.weekday()]} {dt.day} {MESI_IT[dt.month]}"

def gradi_a_direzione(gradi):
    if gradi is None: return "N/A"
    dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW', 'N']
    return dirs[int(round(gradi / 45.0)) % 8]

def calcola_disagio_caldo(t_aria, dew_point):
    if t_aria >= 40 and dew_point >= 15: return "(disagio estremo 🟣 - ELEVATO PERICOLO)"
    elif t_aria >= 38 and dew_point >= 12: return "(disagio forte 🔴)"
    elif t_aria >= 36 and dew_point >= 10: return "(disagio marcato 🟠)"
    elif t_aria >= 32 and dew_point >= 8: return "(disagio lieve 🟡)"
    else: return "(nessun disagio o caldo tollerabile 🟢)"

def calcola_disagio_freddo(windchill):
    if windchill < -40: return "(disagio estremo da freddo 🥶)"
    elif windchill < -25: return "(disagio forte da freddo 🔵)"
    elif windchill < -10: return "(disagio marcato da freddo 🧊)"
    elif windchill < 0: return "(disagio lieve da freddo ❄️)"
    else: return "(nessun disagio o freddo tollerabile 🟢)"

def media_lista(lista):
    valori_validi = [v for v in lista if v is not None]
    if not valori_validi: return 0
    return int(round(sum(valori_validi) / len(valori_validi)))

def media_lista_float(lista):
    valori_validi = [v for v in lista if v is not None]
    if not valori_validi: return 0.0
    return round(sum(valori_validi) / len(valori_validi), 1)

def percentuale_superamento(lista, soglia):
    valori_validi = [v for v in lista if v is not None]
    if not valori_validi: return 0
    return (sum(1 for v in valori_validi if v >= soglia) / len(valori_validi)) * 100

def interpella_groq(dati_testuali, oggi_str):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return "Errore: GROQ_API_KEY non trovata."
        
    client = Groq(api_key=api_key)
    
    prompt = f"""
    Sei un meteorologo professionista, profondo conoscitore del microclima del Piemonte e in particolare della zona di Rivoli (TO). Il tuo compito è redigere un bollettino meteo discorsivo, elegante e autorevole, analizzando i dati orari (Medio Termine) che ti vengono forniti.

    REGOLE DI RAGIONAMENTO METEOROLOGICO (FONDAMENTALI):
    1. Analisi Precipitazioni: Valuta autonomamente il contesto.
       - Piogge pomeridiane/serali + CAPE elevato = Instabilità convettiva. Trattala probabilisticamente (es. "rischio di temporali di calore", "rovesci convettivi").
       - Precipitazioni estese + zero termico/CAPE basso = Perturbazione frontale.
    2. Stima Probabilità: Usa la "Probabilità Pioggia" indicata nei dati per definire le percentuali in caso di instabilità.
    3. Dinamiche Vento: Ignora il vento debole. Segnalalo solo se raffiche > 30 km/h. Se raffiche da Nord-Ovest (NW/W) causano un crollo del Dew Point, deduci Föhn.
    4. Sintesi del Cielo: Usa i minuti di "Sole" per dedurre la copertura nuvolosa.

    REGOLE STILISTICHE E FORMATTAZIONE:
    - TITOLO: Inizia ESATTAMENTE con: <b>Aggiornamento meteo a medio termine di {oggi_str}</b>.
    - STRUTTURA: Un paragrafo compatto per ogni giornata. Lascia una riga vuota DOPO il titolo, NON lasciare righe vuote tra un paragrafo e l'altro, vai solo a capo.
    - DIVIETI ASSOLUTI: NON elencare i dati orari. È VIETATO dire espressioni come "nuvolosità parzialmente nuvolosa". È VIETATO dire "nessuna precipitazione", usa "contesto asciutto". NON usare markdown (* o _).
    - Inserisci le temperature Minime e Massime e il relativo disagio (con emoji 🟢, 🟡, 🟠, 🔴, 🟣, 🥶).
    
    DATI GIORNALIERI DA ANALIZZARE (deduci le tendenze senza elencarli):
    {dati_testuali}
    """
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.25,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Errore AI Groq: {e}"

def main():
    mese_corrente = datetime.now().month
    estate = mese_corrente in [5, 6, 7, 8, 9]
    
    FILE_LOCK = "lock_medio_termine.txt"
    oggi_str_lock = datetime.now().strftime("%Y-%m-%d")
    
    if os.path.exists(FILE_LOCK):
        with open(FILE_LOCK, "r") as f:
            if f.read().strip() == oggi_str_lock: sys.exit(0)

    dt_oggi = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    try:
        dati_det = scarica_dati_con_retry("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON,
            "hourly": "wind_direction_10m,cape,sunshine_duration",
            "models": "meteoswiss_icon_ch2", "timezone": "Europe/Rome", 
            "start_date": (dt_oggi + timedelta(days=2)).strftime("%Y-%m-%d"),
            "end_date": (dt_oggi + timedelta(days=4)).strftime("%Y-%m-%d")
        })
        dati_eps = scarica_dati_con_retry("https://ensemble-api.open-meteo.com/v1/ensemble", params={
            "latitude": LAT, "longitude": LON,
            "hourly": "temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m,dew_point_2m,apparent_temperature",
            "models": "meteoswiss_icon_ch2_ensemble", "timezone": "Europe/Rome",
            "start_date": (dt_oggi + timedelta(days=2)).strftime("%Y-%m-%d"),
            "end_date": (dt_oggi + timedelta(days=4)).strftime("%Y-%m-%d")
        })
    except:
        print("Fallback Seamless...")
        dati_det = scarica_dati_con_retry("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT, "longitude": LON, "hourly": "wind_direction_10m,cape,sunshine_duration",
            "models": "icon_seamless", "timezone": "Europe/Rome", 
            "start_date": (dt_oggi + timedelta(days=2)).strftime("%Y-%m-%d"),
            "end_date": (dt_oggi + timedelta(days=4)).strftime("%Y-%m-%d")
        })
        dati_eps = scarica_dati_con_retry("https://ensemble-api.open-meteo.com/v1/ensemble", params={
            "latitude": LAT, "longitude": LON, "hourly": "temperature_2m,precipitation,wind_speed_10m,wind_gusts_10m,dew_point_2m,apparent_temperature",
            "models": "icon_seamless", "timezone": "Europe/Rome",
            "start_date": (dt_oggi + timedelta(days=2)).strftime("%Y-%m-%d"),
            "end_date": (dt_oggi + timedelta(days=4)).strftime("%Y-%m-%d")
        })

    h_det = dati_det.get('hourly', {})
    h_eps = dati_eps.get('hourly', {})
    orari = h_det.get('time', [])
    if not orari: return

    sintesi = {2: [], 3: [], 4: []}
    t_min = {2: 100, 3: 100, 4: 100}
    t_max = {2: -100, 3: -100, 4: -100}
    app_medie = {2: [], 3: [], 4: []}
    dew_max = {2: -100, 3: -100, 4: -100}

    for i in range(len(orari)):
        ora_dt = datetime.fromisoformat(orari[i])
        giorno_idx = (ora_dt.date() - dt_oggi.date()).days
        if giorno_idx not in sintesi or (giorno_idx == 4 and ora_dt.hour > 20): continue
        
        t_media = media_lista([h_eps[k][i] for k in h_eps if k.startswith('temperature_2m_member')])
        dew_media = media_lista([h_eps[k][i] for k in h_eps if k.startswith('dew_point_2m_member')])
        w_spd = media_lista([h_eps[k][i] for k in h_eps if k.startswith('wind_speed_10m_member')])
        w_gst = media_lista([h_eps[k][i] for k in h_eps if k.startswith('wind_gusts_10m_member')])
        prec_memb = [h_eps[k][i] for k in h_eps if k.startswith('precipitation_member')]
        prec_media = media_lista_float(prec_memb)
        prob_prec = percentuale_superamento(prec_memb, 1.0)
        
        w_dir = gradi_a_direzione(h_det.get('wind_direction_10m', [])[i] if h_det.get('wind_direction_10m') else None)
        cape = h_det.get('cape', [])[i] if h_det.get('cape') else 0
        sun = (h_det.get('sunshine_duration', [])[i] or 0) / 60

        app_media = media_lista([h_eps[k][i] for k in h_eps if k.startswith('apparent_temperature_member')])
        app_medie[giorno_idx].append(app_media)
        
        t_min[giorno_idx] = min(t_min[giorno_idx], t_media)
        t_max[giorno_idx] = max(t_max[giorno_idx], t_media)
        dew_max[giorno_idx] = max(dew_max[giorno_idx], dew_media)

        record = f"Ore {ora_dt.hour:02d}: T={t_media}°C, Dew={dew_media}°C, Pioggia={prec_media}mm (Prob:{prob_prec:.0f}%), CAPE={cape or 0:.0f}J/kg, Vento={w_spd}km/h (Raff:{w_gst}, Dir:{w_dir}), Sole={sun:.0f}min"
        sintesi[giorno_idx].append(record)

    disagio = {2: "", 3: "", 4: ""}
    for g in [2, 3, 4]:
        if estate and t_max[g] != -100: disagio[g] = calcola_disagio_caldo(t_max[g], dew_max[g])
        elif t_max[g] != -100: disagio[g] = calcola_disagio_freddo(min(app_medie[g]))

    testo_per_ia = ""
    for g in [2, 3, 4]:
        g_data = formatta_data_it(dt_oggi + timedelta(days=g))
        testo_per_ia += f"GIORNO: {g_data}\nEstremi: Min {t_min[g]}°C, Max {t_max[g]}°C {disagio[g]}\nDettaglio:\n"
        testo_per_ia += "\n".join(sintesi[g]) + "\n\n"

    oggi_str = formatta_data_it(dt_oggi)
    bollettino_finale = interpella_groq(testo_per_ia, oggi_str)
    
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if token and chat_id:
        risposta_tg = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                      data={"chat_id": chat_id, "text": bollettino_finale, "parse_mode": "HTML"})
        if risposta_tg.status_code == 200:
            with open(FILE_LOCK, "w") as f: f.write(oggi_str_lock)
    else:
        print(bollettino_finale)

if __name__ == "__main__":
    main()
