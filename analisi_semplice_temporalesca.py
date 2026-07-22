import os
import sys
import math
import requests
from datetime import datetime
from groq import Groq

# Coordinate - Rivoli (TO)
LAT = 45.0734521841099
LON = 7.543386286825349

def scomposizione_vettoriale(speed_kmh, direction_deg):
    """Converte velocità e direzione di provenienza in vettori U e V (m/s)."""
    if speed_kmh is None or direction_deg is None:
        return 0.0, 0.0
    speed_ms = speed_kmh / 3.6
    rad = math.radians(direction_deg)
    u = -speed_ms * math.sin(rad)
    v = -speed_ms * math.cos(rad)
    return u, v

def calcola_vettore_traslazione(u, v):
    """Calcola velocità (km/h) e direzione VERSO CUI punta il vettore (gradi)."""
    speed_ms = math.sqrt(u**2 + v**2)
    speed_kmh = speed_ms * 3.6
    direction_deg = (math.degrees(math.atan2(u, v)) + 360) % 360
    return speed_kmh, direction_deg

def classificazione_traslazione(kmh):
    if kmh < 15: return "molto lenta, originando fenomeni quasi stazionari"
    if kmh < 30: return "lenta"
    if kmh < 50: return "rapida"
    return "molto rapida"

def formatta_direzione_bussola(gradi):
    direzioni = ["nord", "nord-est", "est", "sud-est", "sud", "sud-ovest", "ovest", "nord-ovest"]
    indice = round(gradi / 45) % 8
    return direzioni[indice]

def check_probabilita_precipitazione():
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": LAT, "longitude": LON,
        "daily": "precipitation_probability_max",
        "models": "dwd_icon_d2,meteoswiss_icon_ch2",
        "timezone": "Europe/Rome",
        "forecast_days": 3
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily", {})
        times = daily.get("time", [])
        prob_d2 = daily.get("precipitation_probability_max_dwd_icon_d2", [])
        prob_ch2 = daily.get("precipitation_probability_max_meteoswiss_icon_ch2", [])
        giorni_validi = []
        for i in range(min(2, len(times))):
            d2_val = prob_d2[i] if len(prob_d2) > i and prob_d2[i] is not None else 0
            ch2_val = prob_ch2[i] if len(prob_ch2) > i and prob_ch2[i] is not None else 0
            if (d2_val >= 15 or ch2_val >= 15) or (d2_val >= 10 and ch2_val >= 10):
                giorni_validi.append(times[i])
        return giorni_validi
    except: 
        return []

def fetch_dati_termodinamici():
    url = "https://api.open-meteo.com/v1/forecast"
    hourly_params = "precipitation_probability,temperature_2m,dew_point_2m,wind_gusts_10m,lightning_potential,updraft,convective_cloud_base,convective_cloud_top,cape,freezing_level_height,wind_speed_1000hPa,wind_direction_1000hPa,wind_speed_850hPa,wind_direction_850hPa,wind_speed_700hPa,wind_direction_700hPa,wind_speed_500hPa,wind_direction_500hPa"
    params = {"latitude": LAT, "longitude": LON, "models": "dwd_icon_d2,meteoswiss_icon_ch2", "hourly": hourly_params, "timezone": "Europe/Rome", "forecast_days": 3}
    return requests.get(url, params=params, timeout=40).json()['hourly']

def max_sicuro(lista):
    valori = [x for x in lista if x is not None]
    return max(valori) if valori else 0

def min_sicuro(lista):
    valori = [x for x in lista if x is not None]
    return min(valori) if valori else 0

def stima_grandine(cape, updraft, spessore):
    if cape > 2500 or updraft > 15: return "potenzialmente di grandi dimensioni (> 5 cm)"
    if cape > 1500: return "di medie dimensioni (3 - 5 cm)"
    if cape > 800: return "di piccole dimensioni (1.5 - 3 cm)"
    if cape > 400: return "molto piccola o assente (< 1.5 cm)"
    return "assente"

def stima_downburst(gust):
    if gust > 80: return "molto intenso (oltre 80 km/h)"
    if gust > 60: return "intenso (fino a 80 km/h)"
    if gust > 50: return "moderato (fino a 70 km/h)"
    return "debole"

def ora_con_articolo(ora):
    if ora == 0: return "la mezzanotte"
    elif ora == 1: return "l'una"
    else: return f"le {ora}"

def formatta_fascia_oraria(ora_str):
    ora_centrale = int(ora_str.split(":")[0])
    ora_prima = (ora_centrale - 1) % 24
    ora_dopo = (ora_centrale + 1) % 24
    return f"tra {ora_con_articolo(ora_prima)} e {ora_con_articolo(ora_dopo)}"

def interpella_groq_semplice(report, giorno_str, fascia, traslazione_kmh, traslazione_dir, grandine):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return "Errore: Manca la chiave API di Groq."
    client = Groq(api_key=api_key)
    
    velocita_str = classificazione_traslazione(traslazione_kmh)
    dir_testuale = formatta_direzione_bussola(traslazione_dir)
    max_vento = report.split('Max Gust: ')[1].split(' ')[0]
    
    prompt = f"""
    Sei un meteorologo che parla al pubblico. Il {giorno_str} a Rivoli sono previsti fenomeni.

    REGOLE:
    1. INIZIA ESATTAMENTE COSÌ E NON CAMBIARE UNA VIRGOLA DELL'INCIPIT: "Dagli ultimi aggiornamenti sembrerebbero possibili rovesci o temporali {fascia}, potenzialmente accompagnati da pioggia forte e raffiche di vento fino a {max_vento} km/h."
    2. CONTINUAZIONE: Aggiungi "La grandine dovrebbe risultare {grandine}." 
    3. TRASLAZIONE: Aggiungi "Il sistema temporalesco traslerà in modo {velocita_str} verso {dir_testuale}."
    4. CONCLUSIONE OBBLIGATORIA (Copia e incolla testualmente): "Attenzione: considera che si tratta di fenomenologia localizzata e difficilmente prevedibile, non è dunque da escludere che le precipitazioni interessino maggiormente i comuni limitrofi o lascino addirittura completamente all'asciutto la tua zona."
    5. NON SCRIVERE ALTRO. Assicurati che il risultato sia un paragrafo coeso e fluido. NO HTML, NO JARGON TECNICO (no celle, no downburst, no updraft, no cape), NO LISTE.
    """
    try:
        return client.chat.completions.create(messages=[{"role":"user","content":prompt}], model="llama-3.3-70b-versatile", temperature=0.25).choices[0].message.content
    except Exception as e:
        return f"Errore AI Groq: {e}"

def main():
    FILE_LOCK = "lock_temporali_semplice.txt"
    oggi = datetime.now().strftime("%Y-%m-%d")
    
    if os.path.exists(FILE_LOCK):
        with open(FILE_LOCK, "r") as f:
            if f.read().strip() == oggi: 
                print("✅ Analisi temporali già inviata oggi. Esecuzione terminata per evitare spam.")
                sys.exit(0)

    giorni = check_probabilita_precipitazione()
    if not giorni: return
    
    hourly = fetch_dati_termodinamici()
    
    for data_str in giorni:
        idx_g = [i for i, t in enumerate(hourly['time']) if t.startswith(data_str)]
        idx_picco = -1
        
        for i in idx_g:
            p_d2 = hourly.get('precipitation_probability_dwd_icon_d2', [])
            p_ch2 = hourly.get('precipitation_probability_meteoswiss_icon_ch2', [])
            
            val_d2 = p_d2[i] if len(p_d2) > i and p_d2[i] is not None else 0
            val_ch2 = p_ch2[i] if len(p_ch2) > i and p_ch2[i] is not None else 0
            
            if (val_d2 >= 15 or val_ch2 >= 15) or (val_d2 >= 10 and val_ch2 >= 10):
                idx_picco = i
                break
        
        idx_picco = idx_picco if idx_picco != -1 else [i for i in idx_g if hourly['time'][i].endswith("16:00")][0]
        indici = [idx for idx in range(idx_picco - 3, idx_picco + 1) if 0 <= idx < len(hourly['time'])]
        
        cape = max_sicuro([hourly['cape_dwd_icon_d2'][i] for i in indici])
        gust = max_sicuro([hourly['wind_gusts_10m_dwd_icon_d2'][i] for i in indici])
        gust = int(gust) if gust else 0
        updraft = max_sicuro([hourly['updraft_dwd_icon_d2'][i] for i in indici])
        min_base = min_sicuro([hourly['convective_cloud_base_dwd_icon_d2'][i] for i in indici])
        max_top = max_sicuro([hourly['convective_cloud_top_dwd_icon_d2'][i] for i in indici])
        spessore = (max_top - min_base) if min_base and max_top else 0
        
        # Filtro "Safe" per prevenire i TypeErrors sul vento
        w_speed_850 = hourly['wind_speed_850hPa_dwd_icon_d2'][idx_picco] if hourly['wind_speed_850hPa_dwd_icon_d2'][idx_picco] is not None else 0
        w_dir_850 = hourly['wind_direction_850hPa_dwd_icon_d2'][idx_picco] if hourly['wind_direction_850hPa_dwd_icon_d2'][idx_picco] is not None else 0
        w_speed_700 = hourly['wind_speed_700hPa_dwd_icon_d2'][idx_picco] if hourly['wind_speed_700hPa_dwd_icon_d2'][idx_picco] is not None else 0
        w_dir_700 = hourly['wind_direction_700hPa_dwd_icon_d2'][idx_picco] if hourly['wind_direction_700hPa_dwd_icon_d2'][idx_picco] is not None else 0
        w_speed_500 = hourly['wind_speed_500hPa_dwd_icon_d2'][idx_picco] if hourly['wind_speed_500hPa_dwd_icon_d2'][idx_picco] is not None else 0
        w_dir_500 = hourly['wind_direction_500hPa_dwd_icon_d2'][idx_picco] if hourly['wind_direction_500hPa_dwd_icon_d2'][idx_picco] is not None else 0
        
        u_850, v_850 = scomposizione_vettoriale(w_speed_850, w_dir_850)
        u_700, v_700 = scomposizione_vettoriale(w_speed_700, w_dir_700)
        u_500, v_500 = scomposizione_vettoriale(w_speed_500, w_dir_500)
        trasl_kmh, trasl_dir = calcola_vettore_traslazione((u_850+u_700+u_500)/3, (v_850+v_700+v_500)/3)
        
        grandine_str = stima_grandine(cape, updraft, spessore)
        report_dati = f"Max Gust: {gust} km/h, CAPE: {cape}"
        
        ora_stringa = datetime.fromisoformat(hourly['time'][idx_picco]).strftime('%H:%M')
        fascia = formatta_fascia_oraria(ora_stringa)
        
        testo = interpella_groq_semplice(report_dati, data_str, fascia, trasl_kmh, trasl_dir, grandine_str)
        
        if not testo.startswith("Errore AI Groq"):
            testo = testo.replace('<', '&lt;').replace('>', '&gt;')
        
        messaggio = f"⛈ <b>Avviso per possibili temporali</b>\n\n📅 {datetime.strptime(data_str, '%Y-%m-%d').strftime('%d/%m/%Y')}\n\n{testo}"
        
        token = os.getenv('TELEGRAM_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if token and chat_id:
            requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data={
                "chat_id": chat_id, "text": messaggio, "parse_mode": "HTML"
            })
            with open(FILE_LOCK, "w") as f: f.write(oggi)

if __name__ == "__main__":
    main()
