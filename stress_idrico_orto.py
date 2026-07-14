#!/usr/bin/env python3
import os
import requests
import sys
import json
from datetime import datetime, timedelta
from groq import Groq

try:
    from zoneinfo import ZoneInfo
except ImportError:
    pass

LAT_RIVOLI = 45.06212957744542
LON_RIVOLI = 7.5336149995703625

def get_rome_time():
    try:
        return datetime.now(ZoneInfo("Europe/Rome"))
    except:
        return datetime.utcnow() + timedelta(hours=2)

def controlla_pulsante_telegram(token):
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
                        cb_id = update["callback_query"]["id"]
                        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", 
                                      data={"callback_query_id": cb_id, "text": "Memoria irrigazione aggiornata!"})
                        
                        with open("ultima_innaffiatura.txt", "w") as f:
                            f.write(get_rome_time().strftime("%Y-%m-%d"))
            
            with open("tg_offset_orto.txt", "w") as f:
                f.write(str(offset))
    except Exception as e:
        print(f"Errore lettura Telegram API: {e}")

def valuta_stress(bilancio):
    deficit = -bilancio 
    if deficit < 5.0: return "SCARSO/NULLO 🟢"
    elif deficit <= 15.0: return "MODERATO 🟡"
    elif deficit <= 20.0: return "ALTO 🔴"
    else: return "ESTREMO 🟣"

def percentuale_superamento(lista, soglia):
    valori_validi = [v for v in lista if v is not None]
    if not valori_validi: return 0
    return (sum(1 for v in valori_validi if v >= soglia) / len(valori_validi)) * 100

def scarica_dati_con_retry(url, params, max_retries=3):
    for tentativo in range(max_retries):
        try:
            resp = requests.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            if tentativo < max_retries - 1:
                import time
                time.sleep(5)
            else:
                raise e

def interpella_groq(dati_testuali):
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key: return "Errore: GROQ_API_KEY non trovata."
        
    client = Groq(api_key=api_key)
    
    prompt = f"""
    Sei un assistente agrometeorologico personale. Il tuo compito è scrivere UN UNICO PARAGRAFO fluido e discorsivo 
    (massimo 5-6 frasi) per consigliare all'utente se e quando innaffiare il suo orto a Rivoli (TO).

    DATI TECNICI ATTUALI DA ELABORARE:
    {dati_testuali}

    REGOLE FERREE E LOGICA DECISIONALE:
    1. INIZIO: Spiega brevemente lo stato di stress idrico stimato per fine giornata odierna.
    2. DOPPIO SCENARIO PER DOMANI: Spiega come evolverà lo stress idrico domani in base ai due scenari forniti. Se lo scenario peggiorativo (assenza di pioggia) aggrava la situazione rispetto a quello previsto, esponi chiaramente il rischio (es. "Domani lo stress previsto è MODERATO in caso di pioggia, ma qualora non dovesse piovere salirà a livello ALTO"). Se i due scenari sono identici, citane logicamente solo uno.
    3. MEMORIA IRRIGAZIONE: Se nei dati risulta che l'utente ha bagnato l'orto ieri o oggi, ricordalo nel testo spiegando che lo stress odierno ne ha beneficiato.
    4. CONSIGLIO IRRIGAZIONE: Consiglia all'utente di bagnare l'orto basandoti sullo SCENARIO SENZA PIOGGIA. Se in assenza di pioggia lo stress diventerà "ALTO" o "ESTREMO", avvisa che potrebbe essere necessario irrigare stasera o domani sera.
    5. GESTIONE PROBABILITA' PIOGGIA: Se la probabilità di temporali è MAGGIORE O UGUALE AL 15%, modera il consiglio inserendo un avviso di prudenza. Esempio: "...tuttavia, poiché nelle prossime ore non sono esclusi temporali (probabilità 40%), valuta attentamente la situazione prima di bagnare per evitare ristagni idrici". Ignora del tutto la probabilità se è inferiore al 15%.
    6. FORMATTAZIONE: È SEVERAMENTE VIETATO usare asterischi (*) o underscore (_) per il grassetto o corsivo, Telegram andrà in crash. Usa solo il tag HTML <b>testo in grassetto</b> per evidenziare le parole chiave (come i livelli di stress <b>ALTO</b>, <b>ESTREMO</b>, ecc). Inserisci le emoji dei livelli di stress fornite.

    Scrivi direttamente il bollettino senza convenevoli o frasi introduttive.
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

def calcola_dati_orto():
    # 1. Determinismo per ET0
    params_det = {
        "latitude": LAT_RIVOLI, "longitude": LON_RIVOLI,
        "hourly": "precipitation,et0_fao_evapotranspiration",
        "models": "icon_seamless",
        "past_days": 10, "forecast_days": 2, 
        "timezone": "Europe/Rome"
    }
    
    # 2. Ensemble per probabilità inneschi e media mm pioggia (D2 e CH2)
    params_eps_base = {
        "latitude": LAT_RIVOLI, "longitude": LON_RIVOLI,
        "hourly": "precipitation",
        "timezone": "Europe/Rome", "forecast_days": 2
    }
    
    try:
        dati_det = scarica_dati_con_retry("https://api.open-meteo.com/v1/forecast", params_det)["hourly"]
        dati_eps_d2 = scarica_dati_con_retry("https://ensemble-api.open-meteo.com/v1/ensemble", {**params_eps_base, "models": "icon_d2"})["hourly"]
        
        ch2_disponibile = True
        try:
            dati_eps_ch2 = scarica_dati_con_retry("https://ensemble-api.open-meteo.com/v1/ensemble", {**params_eps_base, "models": "meteoswiss_icon_ch2_ensemble"})["hourly"]
        except:
            ch2_disponibile = False
            dati_eps_ch2 = {}
            
    except Exception as e:
        print(f"Errore download dati: {e}")
        sys.exit(1)

    times = dati_det["time"]
    orari_eps = dati_eps_d2.get("time", [])
    now_rome = get_rome_time()
    
    oggi_str = now_rome.strftime("%Y-%m-%d")
    ieri_str = (now_rome - timedelta(days=1)).strftime("%Y-%m-%d")
    domani_str = (now_rome + timedelta(days=1)).strftime("%Y-%m-%d")

    data_reset_manuale = None
    if os.path.exists("ultima_innaffiatura.txt"):
        with open("ultima_innaffiatura.txt", "r") as f:
            data_reset_manuale = f.read().strip()
            
    ha_bagnato_ieri = (data_reset_manuale == ieri_str)
    ha_bagnato_oggi = (data_reset_manuale == oggi_str)

    def get_idx(time_list, time_str):
        try: return time_list.index(time_str)
        except ValueError: return None

    p_det = dati_det["precipitation"]
    e_det = dati_det["et0_fao_evapotranspiration"]

    # --- SIMULATORE STORICO IN MEMORIA ---
    bilancio = 0.0
    for i in range(10, -1, -1): 
        data_storica = (now_rome - timedelta(days=i)).strftime("%Y-%m-%d")
        idx_s = get_idx(times, f"{data_storica}T00:00")
        idx_e = get_idx(times, f"{data_storica}T23:00")
        
        if idx_s is not None and idx_e is not None:
            p_giorno = sum(p for p in p_det[idx_s:idx_e+1] if p is not None)
            e_giorno = sum(e for e in e_det[idx_s:idx_e+1] if e is not None)
            
            bilancio += (p_giorno - e_giorno)
            
            if data_storica == data_reset_manuale or p_giorno >= 4.0:
                bilancio = 0.0
            elif p_giorno >= 2.0:
                bilancio = bilancio / 2.0
            
            if bilancio > 0.0: bilancio = 0.0
            bilancio = max(bilancio, -25.0)

            if data_storica == oggi_str:
                bil_oggi_fine_giornata = bilancio
                
    # --- PREVISIONE DOMANI A DOPPIO SCENARIO ---
    idx_domani_s = get_idx(times, f"{domani_str}T00:00")
    idx_domani_e = get_idx(times, f"{domani_str}T23:00")
    
    idx_eps_domani_s = get_idx(orari_eps, f"{domani_str}T00:00")
    idx_eps_domani_e = get_idx(orari_eps, f"{domani_str}T23:00")
    
    bil_domani_con_pioggia = bil_oggi_fine_giornata
    bil_domani_senza_pioggia = bil_oggi_fine_giornata
    
    if idx_domani_s is not None and idx_domani_e is not None and idx_eps_domani_s is not None and idx_eps_domani_e is not None:
        e_domani = sum(e for e in e_det[idx_domani_s:idx_domani_e+1] if e is not None)
        
        # Calcolo Pioggia EPS prevista per domani (Media della media tra D2 e CH2)
        p_domani_eps = 0.0
        for j in range(idx_eps_domani_s, idx_eps_domani_e + 1):
            spaghi_d2 = [dati_eps_d2[k][j] for k in dati_eps_d2 if k.startswith('precipitation_member') and dati_eps_d2[k][j] is not None]
            media_d2_ora = sum(spaghi_d2) / len(spaghi_d2) if spaghi_d2 else 0.0
            
            if ch2_disponibile:
                spaghi_ch2 = [dati_eps_ch2[k][j] for k in dati_eps_ch2 if k.startswith('precipitation_member') and dati_eps_ch2[k][j] is not None]
                media_ch2_ora = sum(spaghi_ch2) / len(spaghi_ch2) if spaghi_ch2 else 0.0
                pioggia_oraria = (media_d2_ora + media_ch2_ora) / 2.0
            else:
                pioggia_oraria = media_d2_ora
                
            p_domani_eps += pioggia_oraria
        
        # SCENARIO 1: Modello Ensemble (con pioggia prevista)
        bil_domani_con_pioggia += (p_domani_eps - e_domani)
        if p_domani_eps >= 4.0: 
            bil_domani_con_pioggia = 0.0
        elif p_domani_eps >= 2.0:
            bil_domani_con_pioggia = bil_domani_con_pioggia / 2.0
            
        if bil_domani_con_pioggia > 0.0: bil_domani_con_pioggia = 0.0
        bil_domani_con_pioggia = max(bil_domani_con_pioggia, -25.0)

        # SCENARIO 2: Peggiorativo (0.0 mm di pioggia caduti)
        bil_domani_senza_pioggia -= e_domani
        if bil_domani_senza_pioggia > 0.0: bil_domani_senza_pioggia = 0.0
        bil_domani_senza_pioggia = max(bil_domani_senza_pioggia, -25.0)


    # --- CALCOLO PROBABILITA' PIOGGIA NELLE PROSSIME 24-30h ---
    max_prob_pioggia = 0
    trigger_pioggia_scattato = False
    ora_attuale_str = now_rome.strftime("%Y-%m-%dT%H:00")
    
    idx_eps_start = get_idx(orari_eps, ora_attuale_str)
    idx_eps_end = get_idx(orari_eps, f"{domani_str}T23:00")
    
    def membri_sopra_soglia_finestra(dati_eps_dict, start_idx, soglia=1.0, tolleranza=4):
        membri_validi = 0
        chiavi_membri = [k for k in dati_eps_dict.keys() if k.startswith('precipitation_member')]
        for k in chiavi_membri:
            lst = dati_eps_dict[k]
            fine_finestra = min(start_idx + tolleranza, len(lst))
            if any(lst[h] is not None and lst[h] >= soglia for h in range(start_idx, fine_finestra)):
                membri_validi += 1
        return membri_validi

    if idx_eps_start is not None and idx_eps_end is not None:
        max_pct_media = 0
        
        for j in range(idx_eps_start, idx_eps_end + 1):
            
            membri_d2_finestra = membri_sopra_soglia_finestra(dati_eps_d2, j, 1.0, 4)
            membri_ch2_finestra = membri_sopra_soglia_finestra(dati_eps_ch2, j, 1.0, 4) if ch2_disponibile else 0
            
            if ch2_disponibile:
                if membri_d2_finestra >= 5 and membri_ch2_finestra >= 5:
                    trigger_pioggia_scattato = True
            else:
                if membri_d2_finestra >= 8:
                    trigger_pioggia_scattato = True

            spaghi_d2 = [dati_eps_d2[k][j] for k in dati_eps_d2 if k.startswith('precipitation_member')]
            pct_d2 = percentuale_superamento(spaghi_d2, 1.0)
            
            if ch2_disponibile:
                spaghi_ch2 = [dati_eps_ch2[k][j] for k in dati_eps_ch2 if k.startswith('precipitation_member')]
                pct_ch2 = percentuale_superamento(spaghi_ch2, 1.0)
                prob_media_ora = (pct_d2 + pct_ch2) / 2
            else:
                prob_media_ora = pct_d2
                
            if prob_media_ora > max_pct_media:
                max_pct_media = prob_media_ora
                
        if trigger_pioggia_scattato:
            max_prob_pioggia = int(round(max_pct_media))

    return {
        "stress_oggi": valuta_stress(bil_oggi_fine_giornata),
        "stress_domani_con_pioggia": valuta_stress(bil_domani_con_pioggia),
        "stress_domani_senza_pioggia": valuta_stress(bil_domani_senza_pioggia),
        "ha_bagnato_ieri": "Sì" if ha_bagnato_ieri else "No",
        "ha_bagnato_oggi": "Sì" if ha_bagnato_oggi else "No",
        "probabilita_pioggia": max_prob_pioggia
    }

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if token:
        controlla_pulsante_telegram(token)

    print("Calcolo dati del bilancio idrico in corso...")
    dati = calcola_dati_orto()
    
    testo_per_ia = f"""
    - Stress Idrico Stimato (a fine giornata odierna): {dati['stress_oggi']}
    - Stress Idrico Previsto (Domani a fine giornata) SE PIOVE come previsto dai modelli: {dati['stress_domani_con_pioggia']}
    - Stress Idrico Previsto (Domani a fine giornata) SE NON PIOVE (scenario peggiore): {dati['stress_domani_senza_pioggia']}
    - L'utente ha segnalato di aver innaffiato l'orto IERI? {dati['ha_bagnato_ieri']}
    - L'utente ha segnalato di aver innaffiato l'orto OGGI? {dati['ha_bagnato_oggi']}
    - Probabilità massima stimata di temporali/rovesci tra stasera e domani sera: {dati['probabilita_pioggia']}%
    """
    
    print("Elaborazione del bollettino tramite Groq AI...")
    bollettino_ai = interpella_groq(testo_per_ia)
    
    messaggio_finale = f"🌱 <b>BOLLETTINO ORTO E SUOLO</b>\n\n{bollettino_ai}"
    
    if token and chat_id:
        if bollettino_ai.startswith("Errore"):
            print(f"Blocco l'invio su Telegram a causa di un errore API: {bollettino_ai}")
        else:
            tastiera = {
                "inline_keyboard": [
                    [{"text": "💦 Ho bagnato l'orto! (Azzera siccità)", "callback_data": "reset_idrico"}]
                ]
            }
            try:
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage", 
                              data={"chat_id": chat_id, "text": messaggio_finale, "parse_mode": "HTML", "reply_markup": json.dumps(tastiera)})
                print("Bollettino agrometeorologico inviato con successo!")
            except Exception as e:
                print(f"Errore invio Telegram: {e}")
    else:
        print("\n" + messaggio_finale)

if __name__ == "__main__":
    main()
