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
    1. INIZIO: Spiega brevemente lo stato di stress idrico stimato per STASERA (fine giornata odierna). Se hai a disposizione il doppio scenario, descrivilo; altrimenti usa semplicemente lo stress unico fornito.
    2. EVOLUZIONE DOMANI: Spiega come evolverà lo stress idrico domani. Se vedi lo scenario doppio (SE PIOVE / SE NON PIOVE), esponi chiaramente il rischio qualora non dovesse piovere. Se vedi un solo scenario, spiega banalmente cosa accadrà allo stress domani.
    3. MEMORIA IRRIGAZIONE E GIORNI TRASCORSI: Se nei dati risulta che l'utente ha bagnato l'orto OGGI, ricordalo spiegando che lo stress odierno ne ha beneficiato. INVECE, se "Giorni trascorsi" è MAGGIORE DI 0, DEVI inserire fluidamente nel testo la formula esatta "non essendo stato bagnato negli ultimi X giorni" (sostituendo X con il numero fornito) per giustificare lo stato del terreno.
    4. CONSIGLIO IRRIGAZIONE: Consiglia all'utente di bagnare l'orto NELLA SERATA in cui lo stress diventa "ALTO" o "ESTREMO" (può essere stasera, o domani sera). Se c'è un doppio scenario, decidi in base allo scenario SENZA PIOGGIA.
    5. GESTIONE PIOGGIA E DIVIETI: Se nei dati TI VIENE FORNITA la probabilità di pioggia (STASERA e/o DOMANI), raccomanda di valutare bene prima di bagnare per evitare ristagni. SE INVECE NEI DATI NON C'È SCRITTA NESSUNA PROBABILITÀ DI PIOGGIA, È ASSOLUTAMENTE VIETATO NOMINARLA. Non dire MAI frasi come "visto che non pioverà", "con probabilità 0%" o "in assenza di precipitazioni previste". Parla solo ed esclusivamente dello stress termico e consiglia l'innaffiatura.
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
    params_det = {
        "latitude": LAT_RIVOLI, "longitude": LON_RIVOLI,
        "hourly": "precipitation,et0_fao_evapotranspiration",
        "models": "icon_seamless",
        "past_days": 10, "forecast_days": 2, 
        "timezone": "Europe/Rome"
    }
    
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
    ora_attuale_str = now_rome.strftime("%Y-%m-%dT%H:00")
    
    oggi_str = now_rome.strftime("%Y-%m-%d")
    ieri_str = (now_rome - timedelta(days=1)).strftime("%Y-%m-%d")
    domani_str = (now_rome + timedelta(days=1)).strftime("%Y-%m-%d")

    data_reset_manuale = None
    ultimo_bagnato_dt = None
    
    if os.path.exists("ultima_innaffiatura.txt"):
        with open("ultima_innaffiatura.txt", "r") as f:
            data_reset_manuale = f.read().strip()
            try:
                ultimo_bagnato_dt = datetime.strptime(data_reset_manuale, "%Y-%m-%d").date()
            except ValueError:
                pass
            
    ha_bagnato_oggi = (data_reset_manuale == oggi_str)

    def get_idx(time_list, time_str):
        try: return time_list.index(time_str)
        except ValueError: return None

    p_det = dati_det["precipitation"]
    e_det = dati_det["et0_fao_evapotranspiration"]

    def calcola_eps_pioggia_e_prob(start_idx, end_idx):
        p_eps_tot = 0.0
        max_prob = 0
        trigger = False
        
        def membri_sopra_soglia_finestra(dati_eps_dict, idx, soglia=1.0, tolleranza=4):
            membri_validi = 0
            chiavi = [k for k in dati_eps_dict.keys() if k.startswith('precipitation_member')]
            for k in chiavi:
                lst = dati_eps_dict[k]
                fine = min(idx + tolleranza, len(lst))
                if any(lst[h] is not None and lst[h] >= soglia for h in range(idx, fine)):
                    membri_validi += 1
            return membri_validi

        if start_idx is not None and end_idx is not None and start_idx <= end_idx:
            for j in range(start_idx, end_idx + 1):
                spaghi_d2 = [dati_eps_d2[k][j] for k in dati_eps_d2 if k.startswith('precipitation_member') and dati_eps_d2[k][j] is not None]
                media_d2_ora = sum(spaghi_d2) / len(spaghi_d2) if spaghi_d2 else 0.0
                
                if ch2_disponibile:
                    spaghi_ch2 = [dati_eps_ch2[k][j] for k in dati_eps_ch2 if k.startswith('precipitation_member') and dati_eps_ch2[k][j] is not None]
                    media_ch2_ora = sum(spaghi_ch2) / len(spaghi_ch2) if spaghi_ch2 else 0.0
                    p_eps_tot += (media_d2_ora + media_ch2_ora) / 2.0
                else:
                    p_eps_tot += media_d2_ora
                
                membri_d2_fin = membri_sopra_soglia_finestra(dati_eps_d2, j, 1.0, 4)
                membri_ch2_fin = membri_sopra_soglia_finestra(dati_eps_ch2, j, 1.0, 4) if ch2_disponibile else 0
                
                if ch2_disponibile:
                    if membri_d2_fin >= 5 and membri_ch2_fin >= 5: trigger = True
                else:
                    if membri_d2_fin >= 8: trigger = True
                    
                pct_d2 = percentuale_superamento(spaghi_d2, 1.0)
                if ch2_disponibile:
                    pct_ch2 = percentuale_superamento(spaghi_ch2, 1.0)
                    prob_ora = (pct_d2 + pct_ch2) / 2
                else:
                    prob_ora = pct_d2
                    
                if prob_ora > max_prob: max_prob = prob_ora
                
        if not trigger: max_prob = 0
        return p_eps_tot, int(round(max_prob))

    # =========================================================================
    # 1. STORICO IN MEMORIA
    # =========================================================================
    bilancio = 0.0
    for i in range(10, 0, -1): 
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
            
            bilancio = max(min(bilancio, 0.0), -25.0)

            if p_giorno >= 2.0:
                data_storica_dt = (now_rome - timedelta(days=i)).date()
                if ultimo_bagnato_dt is None or data_storica_dt > ultimo_bagnato_dt:
                    ultimo_bagnato_dt = data_storica_dt

    # =========================================================================
    # 2. OGGI (fino a ora)
    # =========================================================================
    idx_oggi_00 = get_idx(times, f"{oggi_str}T00:00")
    idx_now = get_idx(times, ora_attuale_str)
    
    if idx_oggi_00 is not None and idx_now is not None:
        p_oggi_finora = sum(p for p in p_det[idx_oggi_00:idx_now+1] if p is not None)
        e_oggi_finora = sum(e for e in e_det[idx_oggi_00:idx_now+1] if e is not None)
        
        bilancio += (p_oggi_finora - e_oggi_finora)
        
        if ha_bagnato_oggi or p_oggi_finora >= 4.0:
            bilancio = 0.0
        elif p_oggi_finora >= 2.0:
            bilancio = bilancio / 2.0
            
        bilancio = max(min(bilancio, 0.0), -25.0)

        if p_oggi_finora >= 2.0 or ha_bagnato_oggi:
            ultimo_bagnato_dt = now_rome.date()

    if ultimo_bagnato_dt is not None:
        giorni_senza_acqua = (now_rome.date() - ultimo_bagnato_dt).days
    else:
        giorni_senza_acqua = "Sconosciuto"

    # =========================================================================
    # 3. STASERA
    # =========================================================================
    idx_now_eps = get_idx(orari_eps, ora_attuale_str)
    idx_oggi_23_eps = get_idx(orari_eps, f"{oggi_str}T23:00")
    start_stasera_eps = idx_now_eps + 1 if idx_now_eps is not None else None
    
    p_stasera_eps, prob_pioggia_stasera = calcola_eps_pioggia_e_prob(start_stasera_eps, idx_oggi_23_eps)
    
    idx_oggi_23_det = get_idx(times, f"{oggi_str}T23:00")
    start_stasera_det = idx_now + 1 if idx_now is not None else None
    
    e_stasera = 0.0
    if start_stasera_det is not None and idx_oggi_23_det is not None and start_stasera_det <= idx_oggi_23_det:
        e_stasera = sum(e for e in e_det[start_stasera_det:idx_oggi_23_det+1] if e is not None)

    bil_stasera_con_pioggia = bilancio + p_stasera_eps - e_stasera
    if p_stasera_eps >= 4.0: bil_stasera_con_pioggia = 0.0
    elif p_stasera_eps >= 2.0: bil_stasera_con_pioggia /= 2.0
    bil_stasera_con_pioggia = max(min(bil_stasera_con_pioggia, 0.0), -25.0)

    bil_stasera_senza_pioggia = bilancio - e_stasera
    bil_stasera_senza_pioggia = max(min(bil_stasera_senza_pioggia, 0.0), -25.0)

    # =========================================================================
    # 4. DOMANI
    # =========================================================================
    idx_domani_00_eps = get_idx(orari_eps, f"{domani_str}T00:00")
    idx_domani_23_eps = get_idx(orari_eps, f"{domani_str}T23:00")
    
    p_domani_eps, prob_pioggia_domani = calcola_eps_pioggia_e_prob(idx_domani_00_eps, idx_domani_23_eps)
    
    idx_domani_00_det = get_idx(times, f"{domani_str}T00:00")
    idx_domani_23_det = get_idx(times, f"{domani_str}T23:00")
    e_domani = 0.0
    if idx_domani_00_det is not None and idx_domani_23_det is not None:
        e_domani = sum(e for e in e_det[idx_domani_00_det:idx_domani_23_det+1] if e is not None)

    bil_domani_con_pioggia = bil_stasera_con_pioggia + p_domani_eps - e_domani
    if p_domani_eps >= 4.0: bil_domani_con_pioggia = 0.0
    elif p_domani_eps >= 2.0: bil_domani_con_pioggia /= 2.0
    bil_domani_con_pioggia = max(min(bil_domani_con_pioggia, 0.0), -25.0)

    bil_domani_senza_pioggia = bil_stasera_senza_pioggia - e_domani
    bil_domani_senza_pioggia = max(min(bil_domani_senza_pioggia, 0.0), -25.0)

    return {
        "stress_stasera_con_pioggia": valuta_stress(bil_stasera_con_pioggia),
        "stress_stasera_senza_pioggia": valuta_stress(bil_stasera_senza_pioggia),
        "prob_pioggia_stasera": prob_pioggia_stasera,
        "stress_domani_con_pioggia": valuta_stress(bil_domani_con_pioggia),
        "stress_domani_senza_pioggia": valuta_stress(bil_domani_senza_pioggia),
        "prob_pioggia_domani": prob_pioggia_domani,
        "ha_bagnato_oggi": "Sì" if ha_bagnato_oggi else "No",
        "giorni_senza_acqua": giorni_senza_acqua
    }

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if token:
        controlla_pulsante_telegram(token)

    FILE_LOCK = "lock_orto.txt"
    oggi_str_lock = get_rome_time().strftime("%Y-%m-%d")
    
    if os.path.exists(FILE_LOCK):
        with open(FILE_LOCK, "r") as f:
            if f.read().strip() == oggi_str_lock:
                print("✅ Bollettino idrico orto già inviato oggi. Esecuzione terminata per evitare messaggi doppi.")
                sys.exit(0)

    print("Calcolo dati del bilancio idrico in corso...")
    dati = calcola_dati_orto()
    
    # Costruzione dinamica del prompt: NASCONDIAMO I DATI SE LA PROBABILITÀ È ZERO
    testo_per_ia = "-- STASERA (fino a mezzanotte) --\n"
    if dati['prob_pioggia_stasera'] > 0:
        testo_per_ia += f"- Stress Idrico Stimato SE NON PIOVE: {dati['stress_stasera_senza_pioggia']}\n"
        testo_per_ia += f"- Stress Idrico Stimato SE PIOVE (scenario modelli): {dati['stress_stasera_con_pioggia']}\n"
        testo_per_ia += f"- Probabilità temporali/rovesci STASERA: {dati['prob_pioggia_stasera']}%\n\n"
    else:
        testo_per_ia += f"- Stress Idrico Stimato per STASERA: {dati['stress_stasera_senza_pioggia']}\n\n"

    testo_per_ia += "-- DOMANI --\n"
    if dati['prob_pioggia_domani'] > 0:
        testo_per_ia += f"- Stress Idrico Previsto SE NON PIOVE (scenario peggiore): {dati['stress_domani_senza_pioggia']}\n"
        testo_per_ia += f"- Stress Idrico Previsto SE PIOVE (scenario modelli): {dati['stress_domani_con_pioggia']}\n"
        testo_per_ia += f"- Probabilità temporali/rovesci DOMANI: {dati['prob_pioggia_domani']}%\n\n"
    else:
        testo_per_ia += f"- Stress Idrico Previsto per DOMANI: {dati['stress_domani_senza_pioggia']}\n\n"

    testo_per_ia += "-- INFO UTENTE --\n"
    testo_per_ia += f"- L'utente ha segnalato di aver innaffiato l'orto OGGI? {dati['ha_bagnato_oggi']}\n"
    testo_per_ia += f"- Giorni trascorsi dall'ultima innaffiatura o pioggia (se il valore è 0 o Sconosciuto, non inserire la frase dei giorni): {dati['giorni_senza_acqua']}\n"
    
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
                
                with open(FILE_LOCK, "w") as f:
                    f.write(oggi_str_lock)
                    
            except Exception as e:
                print(f"Errore invio Telegram: {e}")
    else:
        print("\n" + messaggio_finale)

if __name__ == "__main__":
    main()
