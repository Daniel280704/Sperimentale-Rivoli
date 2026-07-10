#!/usr/bin/env python3
"""
Bot Agronomico per Ortive Estive
Modello Unico: ICON-Seamless
Versione: Anti-Crash + Suolo in Tempo Reale + Bilancio Pioggia Storica + Planning Serale
"""

import os
import requests
from datetime import datetime
import sys

# Coordinate per Rivoli
LAT = 45.0716
LON = 7.5157

def fetch_data(url, params):
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"❌ Errore API: {e}")
        sys.exit(1)

def invia_messaggio_telegram(testo):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("⚠️ Credenziali Telegram mancanti. Stampa a video:")
        print(testo)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": testo,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, data=payload)
        print("✅ Bollettino agronomico inviato su Telegram!")
    except Exception as e:
        print(f"❌ Errore invio Telegram: {e}")

def main():
    print("🚀 Raccolta dati da ICON-Seamless...")
    
    # Aggiunto past_days=1 per recuperare la pioggia di ieri
    icon_params = {
        "latitude": LAT, "longitude": LON,
        "models": "icon_seamless",
        "hourly": "temperature_2m,relative_humidity_2m,soil_moisture_7_to_28cm",
        "daily": "temperature_2m_max,temperature_2m_min,et0_fao_evapotranspiration,precipitation_sum",
        "timezone": "Europe/Rome",
        "forecast_days": 3,
        "past_days": 1
    }
    dati = fetch_data("https://api.open-meteo.com/v1/forecast", icon_params)

    # Avendo 1 giorno di storico, "Oggi" inizia all'indice 24 per le ore e all'indice 1 per i giorni.
    
    # --- 1. MODULO FITOSANITARIO (FUNGHI) ---
    ore_rischio = 0
    # Prendiamo le 48 ore di previsione partendo da oggi (da ora 24 a 72)
    temperature = dati["hourly"]["temperature_2m"][24:72]
    umidita = dati["hourly"]["relative_humidity_2m"][24:72]
    
    for t, rh in zip(temperature, umidita):
        if t is not None and rh is not None:
            if rh >= 88 and 15 <= t <= 25:
                ore_rischio += 1
            
    if ore_rischio > 8:
        stato_funghi = f"🔴 <b>ALTO ({ore_rischio}h di bagnatura fogliare)</b>\n<i>Attenzione per Cuori di bue e Datterini (Peronospora) e Zucchine (Oidio). Valutare trattamenti preventivi.</i>"
    elif ore_rischio > 3:
        stato_funghi = f"🟡 <b>MEDIO ({ore_rischio}h di bagnatura fogliare)</b>\n<i>Arieggiare la vegetazione dei pomodori sfemminellando la parte bassa.</i>"
    else:
        stato_funghi = f"🟢 <b>BASSO ({ore_rischio}h di bagnatura fogliare)</b>\n<i>Condizioni asciutte, basso rischio fungino.</i>"

    # --- 2. MODULO IRRIGAZIONE E SUOLO ---
    # Indice 0 = Ieri, Indice 1 = Oggi, Indice 2 = Domani
    pioggia_ieri_raw = dati["daily"]["precipitation_sum"][0]
    et_oggi_raw = dati["daily"]["et0_fao_evapotranspiration"][1]
    et_domani_raw = dati["daily"]["et0_fao_evapotranspiration"][2]
    
    # Troviamo l'ora esatta di adesso (sommando le 24 ore di ieri)
    ora_attuale_index = 24 + datetime.now().hour
    umidita_raw = dati["hourly"]["soil_moisture_7_to_28cm"][ora_attuale_index]
    
    pioggia_ieri = pioggia_ieri_raw if pioggia_ieri_raw is not None else 0.0
    et_oggi = et_oggi_raw if et_oggi_raw is not None else 0.0
    et_domani = et_domani_raw if et_domani_raw is not None else 0.0
    umidita_suolo_radici = umidita_raw if umidita_raw is not None else 0.0
    
    consiglio_idrico = ""
    # Nuova logica: indicazioni specifiche per le irrigazioni serali
    if pioggia_ieri >= 5.0:
        consiglio_idrico = f"Ha piovuto abbondantemente ({pioggia_ieri} mm). <b>Stasera irrigazione sospesa</b> per non causare asfissia radicale alle zucchine e marciumi."
    elif pioggia_ieri > 1.0:
        consiglio_idrico = f"Pioggia leggera recente ({pioggia_ieri} mm). <b>Stasera controlla il terreno</b> al tatto: irriga solo se la superficie risulta polverosa."
    else:
        if et_oggi > 5.0:
            consiglio_idrico = "Forte evaporazione diurna. <b>Stasera irriga abbondantemente</b> zucchine e melanzane. Fai una bagnatura profonda sui pomodori (specialmente i cuori di bue)."
        elif et_oggi > 3.0:
            consiglio_idrico = "Evaporazione nella norma. <b>Stasera mantieni un'irrigazione regolare</b>, senza eccessi per non far spaccare i datterini e pomodorini."
        else:
            consiglio_idrico = "Evaporazione bassa. <b>Stasera puoi sospendere l'acqua</b> se il terreno risulta già umido al tatto nei primi 10cm."

    # Aggiunta di un alert per pianificare la sera successiva
    if et_domani > 5.0:
        consiglio_idrico += f"\n🕒 <i>Anticipazione: preparati per <b>domani sera</b>. Prevista forte evaporazione ({et_domani} mm), servirà parecchia acqua.</i>"
    elif et_domani <= 3.0:
        consiglio_idrico += f"\n🕒 <i>Anticipazione: per <b>domani sera</b> l'evaporazione calerà ({et_domani} mm), probabile pausa irrigazione.</i>"

    # --- 3. MODULO INSETTI (Gradi Giorno - GDD) ---
    t_max_raw = dati["daily"]["temperature_2m_max"][1]
    t_min_raw = dati["daily"]["temperature_2m_min"][1]
    
    t_max = t_max_raw if t_max_raw is not None else 25.0
    t_min = t_min_raw if t_min_raw is not None else 15.0
    
    gdd_oggi = max(0, ((t_max + t_min) / 2) - 10)
    
    if gdd_oggi > 14:
        stato_insetti = f"🔴 <b>ELEVATA ({gdd_oggi:.1f} GDD oggi)</b>\n<i>Temperature ottimali per sfarfallamento e alimentazione di Popillia japonica e afidi.</i>"
    else:
        stato_insetti = f"🟢 <b>MODERATA ({gdd_oggi:.1f} GDD oggi)</b>\n<i>Attività degli insetti nella norma.</i>"

    # --- COSTRUZIONE BOLLETTINO ---
    data_oggi = datetime.now().strftime("%d/%m/%Y alle %H:%M")
    
    messaggio = (
        f"🌱 <b>BOLLETTINO AGRONOMICO RIVOLI</b>\n"
        f"📅 <i>{data_oggi}</i>\n\n"
        
        f"💧 <b>IRRIGAZIONE E BILANCIO IDRICO</b>\n"
        f"• Pioggia ieri: <b>{pioggia_ieri} mm</b>\n"
        f"• Evapotraspirazione oggi: <b>{et_oggi} mm</b>\n"
        f"• Umidità radici attuale: <b>{umidita_suolo_radici:.3f} m³/m³</b>\n"
        f"💡 <i>{consiglio_idrico}</i>\n\n"
        
        f"🦠 <b>ALLERTA FUNGHI (Prossime 48h)</b>\n"
        f"• Rischio: {stato_funghi}\n\n"
        
        f"🪲 <b>PRESSIONE INSETTI (Sfarfallamento)</b>\n"
        f"• Attività stimata: {stato_insetti}"
    )

    invia_messaggio_telegram(messaggio)

if __name__ == "__main__":
    main()
