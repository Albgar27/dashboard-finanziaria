"""Azienda di esempio con dati inventati, per provare la piattaforma senza usare dati di clienti."""
from __future__ import annotations

import random
from datetime import date, timedelta

BILANCI = {
    2023: dict(ricavi=5_400_000, valore_produzione=5_450_000, materie=2_250_000, servizi=1_100_000, godimento_beni_terzi=170_000,
               costo_personale=1_300_000, salari=930_000, accantonamento_tfr=70_000, ammortamenti=240_000, costi_produzione=5_090_000,
               ebit=360_000, oneri_finanziari=70_000, gestione_finanziaria=-66_000, risultato_ante_imposte=294_000, imposte=104_000,
               utile=190_000, immobilizzazioni=2_100_000, rimanenze=820_000, crediti_clienti=1_420_000, crediti=1_500_000,
               liquidita=480_000, attivo_circolante=2_800_000, totale_attivo=4_950_000, capitale=100_000, patrimonio_netto=1_250_000,
               fondi_rischi=50_000, tfr=540_000, debiti=3_095_000, debiti_entro=2_050_000, debiti_oltre=1_045_000,
               debiti_banche=1_500_000, debiti_banche_entro=600_000, debiti_fornitori=1_020_000, debiti_tributari=120_000,
               debiti_previdenziali=80_000, totale_passivo=4_950_000, dipendenti=26, compensi_amministratori=170_000),
    2024: dict(ricavi=5_850_000, valore_produzione=5_900_000, materie=2_450_000, servizi=1_180_000, godimento_beni_terzi=175_000,
               costo_personale=1_380_000, salari=990_000, accantonamento_tfr=74_000, ammortamenti=250_000, costi_produzione=5_480_000,
               ebit=420_000, oneri_finanziari=88_000, gestione_finanziaria=-84_000, risultato_ante_imposte=336_000, imposte=106_000,
               utile=230_000, immobilizzazioni=2_200_000, rimanenze=850_000, crediti_clienti=1_500_000, crediti=1_590_000,
               liquidita=510_000, attivo_circolante=2_950_000, totale_attivo=5_200_000, capitale=100_000, patrimonio_netto=1_420_000,
               fondi_rischi=55_000, tfr=575_000, debiti=3_130_000, debiti_entro=2_100_000, debiti_oltre=1_030_000,
               debiti_banche=1_550_000, debiti_banche_entro=640_000, debiti_fornitori=1_080_000, debiti_tributari=130_000,
               debiti_previdenziali=85_000, totale_passivo=5_200_000, dipendenti=27, compensi_amministratori=175_000),
    2025: dict(ricavi=6_200_000, valore_produzione=6_280_000, materie=2_600_000, servizi=1_250_000, godimento_beni_terzi=180_000,
               costo_personale=1_450_000, salari=1_040_000, accantonamento_tfr=78_000, ammortamenti=260_000, costi_produzione=5_780_000,
               ebit=500_000, oneri_finanziari=95_000, gestione_finanziaria=-90_000, risultato_ante_imposte=410_000, imposte=120_000,
               utile=290_000, immobilizzazioni=2_300_000, rimanenze=900_000, crediti_clienti=1_650_000, crediti=1_850_000,
               liquidita=420_000, attivo_circolante=3_170_000, totale_attivo=5_520_000, capitale=100_000, patrimonio_netto=1_650_000,
               fondi_rischi=60_000, tfr=610_000, debiti=3_180_000, debiti_entro=2_250_000, debiti_oltre=930_000,
               debiti_banche=1_600_000, debiti_banche_entro=670_000, debiti_fornitori=1_150_000, debiti_tributari=140_000,
               debiti_previdenziali=90_000, totale_passivo=5_520_000, dipendenti=28, compensi_amministratori=180_000),
}


def _dipendenti(totale_tfr=610_000, n=28):
    rnd = random.Random(7)
    righe = []
    for i in range(n):
        nascita = date(rnd.randint(1960, 2000), rnd.randint(1, 12), rnd.randint(1, 28))
        min_assunzione = max(nascita.year + 19, 1988)
        assunzione = date(rnd.randint(min_assunzione, 2024), rnd.randint(1, 12), 1)
        ral = round(rnd.uniform(26_000, 52_000), -2)
        anni = 2025 - assunzione.year
        destinazione = "fondo" if rnd.random() < 0.25 else "azienda"
        anni_in_azienda = anni if destinazione == "azienda" else max(min(2010, 2025) - assunzione.year, 0)
        righe.append({"nome": f"DIP{i + 1:02d}", "data_nascita": nascita.isoformat(), "data_assunzione": assunzione.isoformat(),
                      "ral": ral, "tfr_azienda": ral * 0.069 * anni_in_azienda * 0.95, "destinazione": destinazione,
                      "eta_uscita": None, "uscita_prevista": None})
    fattore = totale_tfr / sum(r["tfr_azienda"] for r in righe)
    for r in righe:
        r["tfr_azienda"] = round(r["tfr_azienda"] * fattore, 2)
    return righe


def crea(archivio, oggi: date | None = None) -> int:
    oggi = oggi or date.today()
    aid = archivio.crea_azienda({"ragione_sociale": "Officine Esempio Srl", "forma": "SRL", "ateco": "25.62.00",
                                 "sede": "Città di esempio", "referente": "Titolare (fittizio)",
                                 "note": "Azienda di esempio con dati inventati: si può eliminare."}, esempio=True)
    for anno, dati in BILANCI.items():
        archivio.salva_bilancio(aid, anno, dati, f"{anno}-12-31", "ordinario", "manuale")
    archivio.salva_sezione(aid, "dipendenti", {"elenco": _dipendenti()})
    archivio.salva_sezione(aid, "tfr", {"capitale_polizza": 0})
    archivio.salva_sezione(aid, "tfm", {"amministratori": [
        {"nome": "Amministratore delegato", "compenso": 120_000, "percentuale": 0.0741, "anni": 3,
         "data_inizio_mandato": "2024-05-01", "data_scadenza_mandato": "2027-04-30", "data_atto": "", "data_certa": "",
         "polizza": "no"},
        {"nome": "Consigliere", "compenso": 60_000, "percentuale": 0.0741, "anni": 3,
         "data_inizio_mandato": "2024-05-01", "data_scadenza_mandato": "2027-04-30", "data_atto": "2024-04-20",
         "data_certa": "si", "polizza": "no"},
    ]})
    archivio.salva_sezione(aid, "rischi", {
        "catastrofale": {"stato": "da_verificare"},
        "persona_chiave": {"persone": [{"nome": "Amministratore delegato", "ruolo": "commerciale e rapporti con le banche",
                                        "quota_margine": 40, "anni_sostituzione": 2, "costo_sostituzione": 50_000,
                                        "capitale_assicurato": 150_000}]},
        "soci": {"accordo": "no", "valore_azienda": "", "elenco": [
            {"nome": "Socio A", "quota": 70, "eta": 61, "capitale_assicurato": 0},
            {"nome": "Socio B", "quota": 30, "eta": 55, "capitale_assicurato": 0}]},
        "passaggio": {"eta_titolare": 61, "successore": "in_corso", "strumenti": "no"},
        "do": {"stato": "scoperto"}, "cyber": {"stato": "scoperto"},
        "rc_terzi": {"stato": "protetto", "scadenza": (oggi + timedelta(days=95)).isoformat(), "compagnia": "Compagnia di esempio"},
        "rc_prodotti": {"stato": "parziale"},
        "beni": {"stato": "protetto", "scadenza": (oggi + timedelta(days=66)).isoformat()},
        "interruzione": {"stato": "scoperto"}, "credito": {"stato": "da_verificare"},
        "welfare": {"stato": "protetto"}, "previdenza_titolare": {"stato": "parziale"},
    })
    archivio.salva_sezione(aid, "crisi", {
        "retribuzioni_scadute_30": 0, "fornitori_scaduti_90": 120_000, "fornitori_non_scaduti": 830_000,
        "esposizione_bancaria": 1_600_000, "esposizione_scaduta_60": 0,
        "segnalazione_inps": "no", "segnalazione_inail": "no", "segnalazione_ade": "no", "segnalazione_ader": "no",
        "assetto_budget": "si", "assetto_tesoreria_12m": "no", "assetto_infrannuali": "si", "assetto_organigramma": "no",
        "assetto_indici": "no", "assetto_test_pratico": "no",
    })
    archivio.salva_sezione(aid, "scadenze", {"manuali": [
        {"data": (oggi + timedelta(days=21)).isoformat(), "titolo": "Presentare l'analisi al titolare", "note": "", "fatto": False}]})
    return aid
