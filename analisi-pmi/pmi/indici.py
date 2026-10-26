"""Indici di bilancio, semaforo e giudizio di solidità."""
from __future__ import annotations

# (chiave, etichetta, unità, direzione: "alto" = più alto è meglio, "basso" = più basso è meglio, None = solo informativo, spiegazione)
INDICI = [
    ("ebitda", "EBITDA (margine operativo lordo)", "€", None,
     "Risultato operativo più ammortamenti, svalutazioni e accantonamenti: la cassa che la gestione caratteristica genera prima di interessi e imposte."),
    ("pfn", "Posizione finanziaria netta", "€", None,
     "Debiti finanziari (banche, altri finanziatori, obbligazioni, soci) meno liquidità e attività finanziarie a breve. Negativa = cassa netta."),
    ("liquidita_corrente", "Liquidità corrente", "x", "alto",
     "Attivo circolante su debiti a breve: quante volte le attività a breve coprono i debiti a breve."),
    ("liquidita_immediata", "Liquidità immediata (acid test)", "x", "alto",
     "Come la liquidità corrente ma senza magazzino, che non si trasforma subito in cassa."),
    ("indipendenza_finanziaria", "Indipendenza finanziaria", "%", "alto",
     "Patrimonio netto sul totale attivo: quota dell'azienda finanziata con mezzi propri."),
    ("pfn_ebitda", "PFN / EBITDA", "x", "basso",
     "Anni di margine operativo lordo necessari a ripagare il debito finanziario netto. È l'indice che le banche guardano per primo."),
    ("pfn_pn", "PFN / Patrimonio netto", "x", "basso",
     "Debito finanziario netto rispetto ai mezzi propri."),
    ("copertura_oneri", "EBITDA / Oneri finanziari", "x", "alto",
     "Quante volte il margine operativo lordo copre gli interessi."),
    ("oneri_su_ricavi", "Oneri finanziari / Ricavi", "%", "basso",
     "Peso degli interessi sul fatturato."),
    ("ebitda_margin", "EBITDA margin", "%", "alto",
     "EBITDA sul valore della produzione. Dipende molto dal settore."),
    ("ros", "ROS", "%", "alto", "Risultato operativo sui ricavi."),
    ("roe", "ROE", "%", "alto", "Utile netto sul patrimonio netto."),
    ("roi", "ROI", "%", None, "Risultato operativo sul totale attivo."),
    ("crescita_ricavi", "Crescita dei ricavi", "%", None, "Variazione dei ricavi rispetto all'esercizio precedente."),
    ("dso", "Giorni medi di incasso (DSO)", "gg", "basso",
     "Crediti verso clienti su ricavi ×1,22 (i crediti comprendono l'IVA), per 365."),
    ("dpo", "Giorni medi di pagamento (DPO)", "gg", None,
     "Debiti verso fornitori su acquisti, servizi e godimento beni di terzi ×1,22, per 365."),
    ("dio", "Giorni di magazzino", "gg", None, "Rimanenze su costi della produzione, per 365."),
    ("costo_personale_su_vp", "Costo del personale / Valore della produzione", "%", None, ""),
    ("tfr_su_liquidita", "Fondo TFR / Liquidità", "x", "basso",
     "Debito TFR verso i dipendenti rispetto alla cassa disponibile. Sopra 1 la liquidità non basta a pagare il TFR maturato."),
    ("tfr_su_pn", "Fondo TFR / Patrimonio netto", "%", None, ""),
    ("altman_z", "Z-score di Altman (Z'', imprese non quotate)", "x", "alto",
     "6,56·CCN/Attivo + 3,26·(PN − capitale)/Attivo + 6,72·EBIT/Attivo + 1,05·PN/Passività. "
     "Sopra 2,6 zona sicura, tra 1,1 e 2,6 zona grigia, sotto 1,1 zona di rischio. Le riserve approssimano gli utili accumulati."),
]

ETICHETTE = {k: e for k, e, *_ in INDICI}


def _div(a, b):
    if a is None or b is None or b == 0:
        return None
    return a / b


def _somma(*valori):
    valori = [v for v in valori if v is not None]
    return sum(valori) if valori else None


def calcola(d: dict, prec: dict | None = None) -> dict:
    g = d.get
    ebit = g("ebit")
    if ebit is None and g("valore_produzione") is not None and g("costi_produzione") is not None:
        ebit = g("valore_produzione") - g("costi_produzione")
    ebitda = None if ebit is None else ebit + (g("ammortamenti") or 0) + (g("accantonamenti") or 0)

    debiti_fin = _somma(g("debiti_banche"), g("debiti_altri_finanziatori"), g("obbligazioni"), g("debiti_soci"))
    if g("pfn_manuale") is not None:
        pfn = g("pfn_manuale")
    elif debiti_fin is None and g("liquidita") is None:
        pfn = None
    else:
        pfn = (debiti_fin or 0) - (g("liquidita") or 0) - (g("attivita_finanziarie") or 0)

    debiti_entro = g("debiti_entro")
    circolante = g("attivo_circolante")
    if circolante is not None and g("crediti_oltre"):
        circolante -= g("crediti_oltre")  # i crediti oltre l'esercizio non sono a breve

    r = {"ebitda": ebitda, "pfn": pfn}
    r["liquidita_corrente"] = _div(circolante, debiti_entro)
    r["liquidita_immediata"] = _div(None if circolante is None else circolante - (g("rimanenze") or 0), debiti_entro)
    r["indipendenza_finanziaria"] = _div(g("patrimonio_netto"), g("totale_attivo"))

    if pfn is None:
        r["pfn_ebitda"] = None
    elif pfn <= 0:
        r["pfn_ebitda"] = 0.0
    elif ebitda is not None and ebitda <= 0:
        r["pfn_ebitda"] = float("inf")
    else:
        r["pfn_ebitda"] = _div(pfn, ebitda)
    pn = g("patrimonio_netto")
    if pfn is not None and pn is not None and pn <= 0:
        r["pfn_pn"] = float("inf") if pfn > 0 else 0.0
    else:
        r["pfn_pn"] = None if pfn is None else max(_div(pfn, pn) or 0.0, 0.0)

    oneri = g("oneri_finanziari")
    if oneri == 0 and ebitda is not None:
        r["copertura_oneri"] = float("inf") if ebitda > 0 else 0.0
    else:
        r["copertura_oneri"] = _div(ebitda, oneri)
    r["oneri_su_ricavi"] = _div(oneri, g("ricavi"))
    r["ebitda_margin"] = _div(ebitda, g("valore_produzione") or g("ricavi"))
    r["ros"] = _div(ebit, g("ricavi"))
    r["roe"] = _div(g("utile"), pn) if (pn or 0) > 0 else None
    r["roi"] = _div(ebit, g("totale_attivo"))
    r["crescita_ricavi"] = None
    if prec and prec.get("ricavi"):
        r["crescita_ricavi"] = _div(g("ricavi"), prec["ricavi"])
        if r["crescita_ricavi"] is not None:
            r["crescita_ricavi"] -= 1
    r["dso"] = None if g("crediti_clienti") is None else _div(g("crediti_clienti") * 365, (g("ricavi") or 0) * 1.22)
    acquisti = _somma(g("materie"), g("servizi"), g("godimento_beni_terzi"))
    r["dpo"] = None if g("debiti_fornitori") is None else _div(g("debiti_fornitori") * 365, (acquisti or 0) * 1.22)
    r["dio"] = None if g("rimanenze") is None else _div(g("rimanenze") * 365, g("costi_produzione"))
    r["costo_personale_su_vp"] = _div(g("costo_personale"), g("valore_produzione"))

    tfr = g("tfr")
    if tfr is not None and (g("liquidita") or 0) == 0:
        r["tfr_su_liquidita"] = float("inf") if tfr > 0 else None
    else:
        r["tfr_su_liquidita"] = _div(tfr, g("liquidita"))
    r["tfr_su_pn"] = _div(tfr, pn) if (pn or 0) > 0 else None

    ta = g("totale_attivo")
    r["altman_z"] = None
    if ta and circolante is not None and debiti_entro is not None and pn is not None and ebit is not None:
        passivita = ta - pn
        x1 = (circolante - debiti_entro) / ta
        x2 = (pn - (g("capitale") or 0)) / ta
        x3 = ebit / ta
        x4 = pn / passivita if passivita > 0 else 10.0
        r["altman_z"] = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
    return r


def colore(chiave: str, valore, soglie: dict) -> str | None:
    """verde / giallo / rosso, oppure None se l'indice è informativo o manca."""
    direzione = next((x[3] for x in INDICI if x[0] == chiave), None)
    s = soglie.get(chiave)
    if direzione is None or s is None or valore is None:
        return None
    if direzione == "alto":
        return "verde" if valore >= s["verde"] else "giallo" if valore >= s["giallo"] else "rosso"
    return "verde" if valore <= s["verde"] else "giallo" if valore <= s["giallo"] else "rosso"


def giudizio(colori: dict) -> dict:
    """Sintesi della solidità a partire dai colori degli indici dell'ultimo esercizio."""
    rossi = [k for k, c in colori.items() if c == "rosso"]
    gialli = [k for k, c in colori.items() if c == "giallo"]
    valutati = [c for c in colori.values() if c]
    if not valutati:
        return {"colore": None, "testo": "Dati insufficienti", "rossi": [], "gialli": []}
    critici = {"liquidita_corrente", "pfn_ebitda", "altman_z", "copertura_oneri"}
    if len(rossi) >= 3 or len(critici.intersection(rossi)) >= 2:
        c, t = "rosso", "Fragile"
    elif rossi or len(gialli) >= 3:
        c, t = "giallo", "Da presidiare"
    else:
        c, t = "verde", "Solida"
    return {"colore": c, "testo": t, "rossi": rossi, "gialli": gialli}


def analizza(bilanci: list[dict], soglie: dict) -> dict:
    """bilanci: lista di {"anno", "dati"} in qualsiasi ordine. Restituisce indici per anno e giudizio sull'ultimo."""
    ordinati = sorted(bilanci, key=lambda b: b["anno"])
    anni = []
    prec = None
    for b in ordinati:
        valori = calcola(b["dati"], prec)
        colori = {k: colore(k, v, soglie) for k, v in valori.items()}
        anni.append({"anno": b["anno"], "valori": valori, "colori": colori})
        prec = b["dati"]
    ultimo = anni[-1] if anni else None
    return {
        "definizioni": [{"chiave": k, "etichetta": e, "unita": u, "direzione": d, "spiegazione": s} for k, e, u, d, s in INDICI],
        "anni": anni,
        "giudizio": giudizio(ultimo["colori"]) if ultimo else giudizio({}),
    }
