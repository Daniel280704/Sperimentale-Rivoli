#!/usr/bin/env python3
import os
import requests
import sys
import json
from datetime import datetime, timedelta
import locale

# Tentativo di usare l'italiano per i nomi dei giorni
try:
    locale.setlocale(locale.LC_TIME, 'it_IT.UTF-8')
except:
    pass

LAT_RIVOLI = 45.06212957744542
LON_RIVOLI = 7.5336149995703625

def controlla_pulsante_telegram(token):
    """Controlla se l'utente ha premuto il tasto di innaffiatura dall'ultimo avvio."""
    reset_effettuato = False
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    
    offset = 0
    if os.path.exists("tg_offset_orto.txt"):
        with open("tg_offset_orto.txt", "r") as f:
            try:
                offset = int(f.read().strip())
            except ValueError:
                pass

    try:
        res = requests.get(url, params={"offset": offset, "timeout": 5})
        data = res.json()
        
        if data.get("ok"):
            for update in data["result"]:
                offset = update["update_id"] + 1
                if "callback_query" in update:
                    if update["callback_query"]["data"] == "reset_idrico":
                        reset_effettuato = True
                        # Diciamo a Telegram di fermare la rotellina di caricamento sul pulsante
                        cb_id = update["callback_query"]["id"]
                        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", 
                                      data={"callback_query_id": cb_id, "text": "💦 Orto bagnato! Memoria aggiornata."})
                        
                        # Salviamo il momento esatto in cui ha premuto
                        with open("ultima_innaffiatura.txt", "w") as f:
                            f.write(datetime.now().isoformat())
            
            # Salviamo l'offset per non rileggere i vecchi click
            with open("tg_offset_orto.txt", "w") as f:
                f.write(str(offset))
    except Exception as e:
        print(f"Errore lettura Telegram API: {e}")

def valuta_stress(bilancio, pioggia_reale):
    """Funzione secca per calcolare il bollino di stress."""
    if pioggia_reale >= 5.0:
        return "🟢 **SCARSO O NULLO**"
    elif bilancio <= -15:
        return "🔴 **ALTO**"
    elif bilancio <= -5:
        return "🟡 **INTERMEDIO**"
    else:
        return "🟢 **SCARSO O NULLO**"

def calcola_dati_orto(forza_azzeramento):
    print("Scaricamento dati agrometeorologici (DETERMINISTICO + ENSEMBLE) in corso...")
    
    # Usiamo il fuso orario di Roma per allineare perfettamente le mezzanotti
    api_params_det = {
        "latitude": LAT_RIVOLI, "longitude": LON_RIVOLI,
        "hourly": "precipitation,et0_fao_evapotranspiration",
        "models": "icon_seamless",
        "past_days": 3, "forecast_days": 3, 
        "timezone": "Europe/Rome"
    }
    
    api_params_eps = dict(api_params_det)
    api_params_eps["hourly"] = "precipitation"
    
    try:
        dati_det = requests.get("https://api.open-meteo.com/v1/forecast", params=api_params_det, timeout=30).json()["hourly"]
        dati_eps = requests.get("https://ensemble-api.open-meteo.com/v1/ensemble", params=api_params_eps, timeout=30).json()["hourly"]
    except Exception as e:
        print(f"Errore download dati: {e}")
        sys.exit(1)

    ora_attuale_locale = datetime.now().strftime("%Y-%m-%dT%H:00")
    times = dati_det["time"]
    
    try:
        idx_now = times.index(ora_attuale_locale)
    except:
        idx_now = 3 * 24 

    # --- RICERCA INDICI GIORNALIERI ---
    oggi = datetime.now()
    str_domani = (oggi + timedelta(days=1)).strftime("%Y-%m-%d")
    str_dopodomani = (oggi + timedelta(days=2)).strftime("%Y-%m-%d")
    
    idx_start_domani = times.index(f"{str_domani}T00:00")
    idx_end_domani = times.index(f"{str_domani}T23:00") + 1
    
    idx_start_dopo = times.index(f"{str_dopodomani}T00:00")
    idx_end_dopo = times.index(f"{str_dopodomani}T23:00") + 1

    idx_start_48h = max(0, idx_now - 48)
    idx_start_24h = max(0, idx_now - 24)

    # --- DATI PASSATI (Deterministico) ---
    p_det = dati_det["precipitation"]
    e_det = dati_det["et0_fao_evapotranspiration"]

    # Fetta 48h -> 24h fa (Ieri l'altro)
    p_ieri_altro = sum(p for p in p_det[idx_start_48h:idx_start_24h] if p is not None)
    e_ieri_altro = sum(e for e in e_det[idx_start_48h:idx_start_24h] if e is not None)
    bil_ieri_altro = p_ieri_altro - e_ieri_altro

    # Fetta ultime 24h (Ieri)
    p_ieri = sum(p for p in p_det[idx_start_24h:idx_now] if p is not None)
    e_ieri = sum(e for e in e_det[idx_start_24h:idx_now] if e is not None)
    bil_ieri = bil_ieri_altro + p_ieri - e_ieri # Il bilancio si accumula nel tempo

    # SE L'UTENTE HA PREMUTO IL TASTO RECENTEMENTE, AZZERIAMO LO STORICO
    if forza_azzeramento:
        bil_ieri_altro = 0
        bil_ieri = 0
        p_ieri = 10.0 # Simuliamo una forte irrigazione per forzare il bollino verde

    stress_48h = valuta_stress(bil_ieri_altro, p_ieri_altro)
    stress_24h = valuta_stress(bil_ieri, p_ieri)

    # --- DATI FUTURI (Ensemble Media) ---
    membri_eps = [k for k in dati_eps.keys() if "precipitation_member" in k]
    
    def calcola_eps_giorno(start, end):
        p_media = 0.0
        if membri_eps:
            for i in range(start, end):
                vals = [dati_eps[m][i] for m in membri_eps if dati_eps[m][i] is not None]
                if vals:
                    p_media += sum(vals) / len(vals)
        else:
            p_media = sum(p for p in p_det[start:end] if p is not None)
        return p_media

    # DOMANI
    p_domani = calcola_eps_giorno(idx_start_domani, idx_end_domani)
    e_domani = sum(e for e in e_det[idx_start_domani:idx_end_domani] if e is not None)
    bil_domani = bil_ieri + p_domani - e_domani
    stress_domani = valuta_stress(bil_domani, p_domani)

    # DOPODOMANI
    p_dopo = calcola_eps_giorno(idx_start_dopo, idx_end_dopo)
    e_dopo = sum(e for e in e_det[idx_start_dopo:idx_end_dopo] if e is not None)
    bil_dopo = bil_domani + p_dopo - e_dopo
    stress_dopo = valuta_stress(bil_dopo, p_dopo)

    nome_domani = (oggi + timedelta(days=1)).strftime("%A %d")
    nome_dopo = (oggi + timedelta(days=2)).strftime("%A %d")

    return {
        "ieri_altro_nome": "Tra 48h e 24h fa", "ieri_altro_stress": stress_48h, "ieri_altro_bil": bil_ieri_altro,
        "ieri_nome": "Ultime 24 ore", "ieri_stress": stress_24h, "ieri_bil": bil_ieri,
        "domani_nome": nome_domani.capitalize(), "domani_stress": stress_domani, "domani_bil": bil_domani, "domani_p": p_domani, "domani_e": e_domani,
        "dopo_nome": nome_dopo.capitalize(), "dopo_stress": stress_dopo, "dopo_bil": bil_dopo, "dopo_p": p_dopo, "dopo_e": e_dopo,
        "azzerato": forza_azzeramento
    }

def genera_messaggio(d):
    nota_reset = "\n*(Il calcolo dello storico include l'ultima irrigazione manuale)*\n" if d["azzerato"] else ""
    
    messaggio = f"""🌱 **BOLLETTINO SUOLO** 
Rivoli (TO)
{nota_reset}
🔙 **STORICO RECENTE:**
- {d['ieri_altro_nome']}: {d['ieri_altro_stress']} (Bilancio: {d['ieri_altro_bil']:.1f} mm)
- {d['ieri_nome']}: {d['ieri_stress']} (Bilancio: {d['ieri_bil']:.1f} mm)

🔜 **PREVISIONI:**
📅 **Domani ({d['domani_nome']})**
Stato Previsto: {d['domani_stress']}
- Pioggia prevista (EPS): {d['domani_p']:.1f} mm
- Evaporazione attesa: {d['domani_e']:.1f} mm
- Bilancio stimato a fine giornata: {d['domani_bil']:.1f} mm

📅 **Dopodomani ({d['dopo_nome']})**
Stato Previsto: {d['dopo_stress']}
- Pioggia prevista (EPS): {d['dopo_p']:.1f} mm
- Evaporazione attesa: {d['dopo_e']:.1f} mm
- Bilancio stimato a fine giornata: {d['dopo_bil']:.1f} mm"""
    return messaggio

def invia_telegram(messaggio, token, chat_id):
    if not token or not chat_id:
        print("Token o Chat ID mancanti.")
        return

    # Aggiungiamo la tastiera inline (Il bottone)
    tastiera = {
        "inline_keyboard": [
            [{"text": "💧 Ho bagnato l'orto! (Azzera)", "callback_data": "reset_idrico"}]
        ]
    }

    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                      data={"chat_id": chat_id, "text": messaggio, "parse_mode": "Markdown", "reply_markup": json.dumps(tastiera)})
        print("Bollettino agrometeorologico inviato!")
    except Exception as e:
        print(f"Errore invio Telegram: {e}")

def verifica_irrigazione_manuale():
    """Controlla se c'è un file di reset valido (non più vecchio di 48 ore)."""
    if os.path.exists("ultima_innaffiatura.txt"):
        with open("ultima_innaffiatura.txt", "r") as f:
            try:
                data_reset = datetime.fromisoformat(f.read().strip())
                if datetime.now() - data_reset < timedelta(hours=48):
                    return True
            except:
                pass
    return False

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    # 1. Controlliamo se hai premuto il tasto su Telegram nel frattempo
    if token:
        controlla_pulsante_telegram(token)

    # 2. Vediamo se il file di reset ci autorizza ad azzerare il bilancio
    forza_azzeramento = verifica_irrigazione_manuale()

    # 3. Calcoli e invio
    dati = calcola_dati_orto(forza_azzeramento)
    messaggio = genera_messaggio(dati)
    print(messaggio)
    invia_telegram(messaggio, token, chat_id)

if __name__ == "__main__":
    main()
