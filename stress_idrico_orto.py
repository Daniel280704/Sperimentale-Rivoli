#!/usr/bin/env python3
import os
import requests
import sys

LAT_RIVOLI = 45.0716
LON_RIVOLI = 7.5157

def calcola_bilancio_idrico():
    print("Scaricamento dati agrometeorologici (ICON-D2) in corso...")
    try:
        res = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": LAT_RIVOLI,
            "longitude": LON_RIVOLI,
            "daily": "precipitation_sum,et0_fao_evapotranspiration_sum,temperature_2m_max",
            "models": "icon_d2",  # FORZATURA SU ICON-D2
            "past_days": 3,
            "forecast_days": 3,
            "timezone": "Europe/Rome"
        }, timeout=30)
        res.raise_for_status()
        dati = res.json()["daily"]
    except Exception as e:
        print(f"❌ Errore nel download dei dati: {e}")
        sys.exit(1)

    pioggia = dati["precipitation_sum"]
    evapotraspirazione = dati["et0_fao_evapotranspiration_sum"]
    t_max = dati["temperature_2m_max"]

    # Passato (ieri, l'altroieri, e 3 giorni fa)
    pioggia_passata = sum(pioggia[0:3])
    et0_passata = sum(evapotraspirazione[0:3])
    bilancio_passato = pioggia_passata - et0_passata

    # Futuro (oggi e domani)
    pioggia_prevista = sum(pioggia[3:5])
    et0_prevista = sum(evapotraspirazione[3:5])
    t_max_prevista = max(t_max[3:5])

    # Bilancio totale stimato
    bilancio_totale = bilancio_passato + pioggia_prevista - et0_prevista

    return bilancio_totale, bilancio_passato, pioggia_prevista, t_max_prevista

def genera_messaggio(bilancio_totale, bilancio_passato, pioggia_prevista, t_max_prevista):
    
    if bilancio_totale <= -15:
        stato = "🔴 **STRESS IDRICO ELEVATO**"
        consiglio = "Il terreno ha accumulato un forte deficit. Le colture ad alta richiesta idrica e a pieno sviluppo (come pomodori, zucchine e peperoncini) necessitano di irrigazioni profonde e abbondanti. Fai molta attenzione anche alle piante a radice più superficiale (come basilico e lattuga), che rischiano di disidratarsi o andare a seme rapidamente."
    elif bilancio_totale <= -5:
        stato = "🟡 **STRESS IDRICO MODERATO**"
        consiglio = "Il bilancio è in negativo. Consigliata un'irrigazione di mantenimento mirata alla base delle piante, utile specialmente per i fagioli e le colture da foglia, da effettuare preferibilmente la sera tardi o all'alba."
    elif bilancio_totale < 5:
        stato = "🟢 **EQUILIBRIO IDRICO**"
        consiglio = "L'umidità del suolo è su livelli adeguati. Non sono necessarie irrigazioni abbondanti, al massimo leggeri interventi di soccorso se la superficie appare visivamente molto secca."
    else:
        stato = "🔵 **SURPLUS IDRICO**"
        consiglio = "Il terreno è ben bagnato dalle precipitazioni. Sospendere le irrigazioni per evitare marciumi radicali e malattie fungine."

    avviso_calore = ""
    if t_max_prevista >= 32:
        avviso_calore = f"\n\n⚠️ **Allerta Calore:** Previste massime fino a {t_max_prevista}°C. Aumenta lo spessore della pacciamatura, se possibile, per limitare l'evaporazione dal suolo."

    messaggio = f"""🌱 **BOLLETTINO ORTO E SUOLO (ICON-D2)** 🌱
📍 Rivoli (TO)

{stato}

💧 **Bilancio ultimi 3 giorni:** {bilancio_passato:.1f} mm
🌧️ **Pioggia prevista (48h):** {pioggia_prevista:.1f} mm
📊 **Deficit/Surplus Totale:** {bilancio_totale:.1f} mm

🧑‍🌾 **Consigli Operativi:**
{consiglio}{avviso_calore}"""

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
    bilancio_totale, bilancio_passato, pioggia_prevista, t_max_prevista = calcola_bilancio_idrico()
    messaggio = genera_messaggio(bilancio_totale, bilancio_passato, pioggia_prevista, t_max_prevista)
    print(messaggio)
    invia_telegram(messaggio)

if __name__ == "__main__":
    main()