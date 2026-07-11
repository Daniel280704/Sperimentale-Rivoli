#!/usr/bin/env python3
import os
import requests
import sys
from datetime import datetime, timezone

LAT_RIVOLI = 45.06212957744542
LON_RIVOLI = 7.5336149995703625

def calcola_bilancio_idrico():
    print("Scaricamento dati agrometeorologici orari (ICON-D2) in corso...")
    try:
        res = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT_RIVOLI,
            "longitude": LON_RIVOLI,
            "hourly": "precipitation,et0_fao_evapotranspiration,temperature_2m",
            "models": "icon_d2",
            "past_days": 4,  
            "forecast_days": 3, 
            "timezone": "UTC"
        }, timeout=30)
        res.raise_for_status()
        dati = res.json()["hourly"]
    except Exception as e:
        print(f"❌ Errore nel download dei dati: {e}")
        sys.exit(1)

    now_utc = datetime.now(timezone.utc)
    current_time_str = now_utc.strftime("%Y-%m-%dT%H:00")
    
    times = dati["time"]
    try:
        current_idx = times.index(current_time_str)
    except ValueError:
        print("⚠️ Ora attuale non trovata, uso approssimazione.")
        current_idx = 4 * 24 
    
    pioggia = dati["precipitation"]
    et0 = dati["et0_fao_evapotranspiration"]
    temp = dati["temperature_2m"]

    start_72h = max(0, current_idx - 72)
    end_48h = min(len(pioggia), current_idx + 48)

    # DATI PASSATI STORICI (Ultime 72h)
    pioggia_72h = sum(pioggia[start_72h:current_idx])
    et0_72h = sum(et0[start_72h:current_idx]) 
    bilancio_passato = pioggia_72h - et0_72h

    # DATI PREVISTI (Prossime 48h)
    pioggia_prevista_48h = sum(pioggia[current_idx:end_48h])
    et0_prevista_48h = sum(et0[current_idx:end_48h])
    
    array_temp_future = temp[current_idx:end_48h]
    t_max_prevista = max(array_temp_future) if array_temp_future else 0

    # BILANCIO TOTALE STIMATO A FINE PERIODO
    bilancio_totale = bilancio_passato + pioggia_prevista_48h - et0_prevista_48h

    return bilancio_totale, bilancio_passato, pioggia_72h, et0_72h, pioggia_prevista_48h, et0_prevista_48h, t_max_prevista

def genera_messaggio(bilancio_totale, bilancio_passato, pioggia_72h, et0_72h, pioggia_prevista, et0_prevista, t_max_prevista):
    
    # Classificazione essenziale dello stress idrico previsto a fine periodo
    if bilancio_totale <= -15:
        stato = "🔴 **ALTO STRESS IDRICO PREVISTO**"
    elif bilancio_totale <= -5:
        stato = "🟡 **STRESS IDRICO INTERMEDIO PREVISTO**"
    else:
        stato = "🟢 **SCARSO O NULLO STRESS IDRICO PREVISTO**"

    # Calcolo della tendenza dello stress
    differenza = bilancio_totale - bilancio_passato
    if differenza > 0.5:
        tendenza_stress = "📉 **In calo** (miglioramento delle condizioni)"
    elif differenza < -0.5:
        tendenza_stress = "📈 **In aumento** (peggioramento del deficit)"
    else:
        tendenza_stress = "⏸️ **Stabile** (nessuna variazione netta)"

    avviso_calore = ""
    if t_max_prevista >= 32:
        avviso_calore = f"\n\n⚠️ **Allerta Calore:** Previsti picchi fino a {t_max_prevista:.1f}°C nelle prossime 48 ore."

    messaggio = f"""🌱 **BOLLETTINO SUOLO (ICON-D2)** 🌱
📍 Rivoli (TO)

{stato}

🔙 **STORICO RECENTE:**
🌧️ Pioggia caduta (ultime 72h): {pioggia_72h:.1f} mm
☀️ Evaporazione suolo (ultime 72h): {et0_72h:.1f} mm
⚖️ Bilancio effettivo attuale: {bilancio_passato:.1f} mm

🔜 **PROSSIME 48 ORE:**
🌧️ Pioggia prevista: {pioggia_prevista:.1f} mm
☀️ Evaporazione prevista: {et0_prevista:.1f} mm
📈 Bilancio Totale Stimato: {bilancio_totale:.1f} mm

📊 **TENDENZA STRESS IDRICO:** {tendenza_stress}{avviso_calore}"""

    return messaggio

def invia_telegram(messaggio):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("⚠️ Token o Chat ID mancanti.")
        return

    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                      data={"chat_id": chat_id, "text": messaggio, "parse_mode": "Markdown"})
        print("✅ Bollettino agrometeorologico inviato!")
    except Exception as e:
        print(f"❌ Errore invio Telegram: {e}")

def main():
    bilancio_totale, bilancio_passato, pioggia_72h, et0_72h, pioggia_prevista, et0_prevista, t_max_prevista = calcola_bilancio_idrico()
    messaggio = genera_messaggio(bilancio_totale, bilancio_passato, pioggia_72h, et0_72h, pioggia_prevista, et0_prevista, t_max_prevista)
    print(messaggio)
    invia_telegram(messaggio)

if __name__ == "__main__":
    main()
