"""Mappa dei rischi e delle coperture dell'azienda."""
from __future__ import annotations

STATI = {"protetto": "verde", "parziale": "giallo", "scoperto": "rosso", "da_verificare": "grigio", "non_applicabile": None}

CATALOGO = [
    {"chiave": "catastrofale", "titolo": "Polizza catastrofale (obbligatoria)", "obbligo": True,
     "perche": "Le imprese con sede in Italia devono assicurare terreni, fabbricati, impianti, macchinari e attrezzature "
               "contro sisma, alluvione, frana, inondazione ed esondazione (L. 213/2023, art. 1, commi 101–111, con scadenze "
               "scaglionate nel 2025). Senza polizza l'impresa rischia l'esclusione da contributi e agevolazioni pubbliche."},
    {"chiave": "persona_chiave", "titolo": "Persona chiave", "speciale": True,
     "perche": "Se il fatturato o le relazioni con banche e clienti dipendono da una persona, la sua perdita improvvisa "
               "riduce il margine per il tempo necessario a sostituirla."},
    {"chiave": "soci", "titolo": "Continuità della compagine sociale", "speciale": True,
     "perche": "Alla morte di un socio la quota passa agli eredi: senza accordi e liquidità per rilevarla, i soci superstiti "
               "si trovano nuovi soci o un debito da liquidare."},
    {"chiave": "passaggio", "titolo": "Passaggio generazionale", "speciale": True,
     "perche": "Successore, strumenti (patto di famiglia, testamento, holding) e liquidità per gli eredi non coinvolti."},
    {"chiave": "do", "titolo": "RC amministratori (D&O)",
     "perche": "Gli amministratori rispondono con il proprio patrimonio verso società, soci e creditori; l'obbligo di "
               "adeguati assetti (art. 2086 c.c.) ha ampliato le contestazioni possibili."},
    {"chiave": "cyber", "titolo": "Rischio informatico (cyber)",
     "perche": "Fermo dei sistemi, riscatto dei dati, responsabilità per violazione di dati personali."},
    {"chiave": "rc_terzi", "titolo": "RC verso terzi e dipendenti (RCT/RCO)",
     "perche": "Danni a terzi e infortuni dei dipendenti oltre quanto indennizza l'INAIL."},
    {"chiave": "rc_prodotti", "titolo": "RC prodotti",
     "perche": "Per chi produce o distribuisce: danni causati da prodotti difettosi, anche all'estero."},
    {"chiave": "beni", "titolo": "Danni ai beni (incendio / all risks)",
     "perche": "Fabbricati, macchinari e magazzino, oltre agli eventi catastrofali obbligatori."},
    {"chiave": "interruzione", "titolo": "Interruzione di esercizio",
     "perche": "Margine perso e costi fissi che continuano durante il fermo dopo un sinistro."},
    {"chiave": "credito", "titolo": "Assicurazione dei crediti",
     "perche": "Insolvenza dei clienti: conta con incassi lunghi o pochi clienti grandi."},
    {"chiave": "welfare", "titolo": "Sanitaria e welfare dipendenti",
     "perche": "Alcuni contratti collettivi prevedono coperture obbligatorie; è anche leva di fidelizzazione."},
    {"chiave": "previdenza_titolare", "titolo": "Previdenza e protezione del titolare",
     "perche": "Pensione complementare, invalidità e non autosufficienza di chi guida l'azienda."},
]


def _num(x, predefinito=0.0):
    try:
        return float(x) if x not in (None, "") else predefinito
    except (TypeError, ValueError):
        return predefinito


def _esito(colore, testo, fabbisogno=None, coperto=None):
    return {"colore": colore, "testo": testo, "fabbisogno": fabbisogno, "coperto": coperto,
            "gap": None if fabbisogno is None else max(fabbisogno - (coperto or 0), 0.0)}


def _persona_chiave(dati, ebitda, p):
    persone = [x for x in dati.get("persone", []) if x.get("nome") or _num(x.get("quota_margine"))]
    if not persone:
        stato = dati.get("stato")
        if stato == "non_applicabile":
            return _esito(None, "Nessuna persona chiave indicata."), []
        return _esito("grigio", "Indica chi regge fatturato o relazioni e quanto margine dipende da lui."), []
    righe, tot_f, tot_c = [], 0.0, 0.0
    for x in persone:
        anni = _num(x.get("anni_sostituzione"), p.get("anni_sostituzione_persona_chiave", 2))
        f = max(ebitda or 0, 0) * _num(x.get("quota_margine")) / 100 * anni + _num(x.get("costo_sostituzione"))
        c = _num(x.get("capitale_assicurato"))
        tot_f += f
        tot_c += c
        righe.append({"nome": x.get("nome", ""), "fabbisogno": f, "coperto": c, "gap": max(f - c, 0)})
    if tot_c >= tot_f:
        col = "verde"
    elif tot_c > 0:
        col = "giallo"
    else:
        col = "rosso"
    testo = "Fabbisogno stimato come margine operativo lordo dipendente dalla persona × anni per sostituirla, più i costi di sostituzione."
    if not ebitda or ebitda <= 0:
        testo += " EBITDA non disponibile o negativo: il fabbisogno considera solo i costi di sostituzione."
    return _esito(col, testo, tot_f, tot_c), righe


def _soci(dati, valore_auto):
    soci = [x for x in dati.get("elenco", []) if _num(x.get("quota")) > 0]
    if len(soci) < 2:
        if dati.get("stato") == "non_applicabile" or len(soci) == 1:
            return _esito(None, "Socio unico o compagine non indicata."), [], None
        return _esito("grigio", "Indica i soci con le quote per valutare la continuità."), [], None
    valore = _num(dati.get("valore_azienda")) or valore_auto
    righe, tot_f, tot_c = [], 0.0, 0.0
    for x in soci:
        f = (valore or 0) * _num(x.get("quota")) / 100
        c = _num(x.get("capitale_assicurato"))
        tot_f += f
        tot_c += c
        righe.append({"nome": x.get("nome", ""), "quota": _num(x.get("quota")), "eta": x.get("eta"),
                      "fabbisogno": f, "coperto": c, "gap": max(f - c, 0)})
    accordo = dati.get("accordo") == "si"
    if accordo and tot_c >= tot_f * 0.9:
        col = "verde"
    elif accordo or tot_c > 0:
        col = "giallo"
    else:
        col = "rosso"
    testo = ("Accordo tra soci presente. " if accordo else "Manca un accordo tra soci (patto parasociale o clausole di statuto) "
             "che regoli il riacquisto della quota. ")
    testo += "Il fabbisogno è il valore della quota di ciascun socio, da finanziare con polizze vita incrociate o a favore della società."
    return _esito(col, testo, tot_f, tot_c), righe, valore


def _passaggio(dati):
    eta = _num(dati.get("eta_titolare"), 0)
    succ = dati.get("successore")
    strumenti = dati.get("strumenti")
    if not eta and not succ:
        return _esito("grigio", "Indica età del titolare, successore e strumenti adottati.")
    problemi = []
    if succ in (None, "", "no"):
        problemi.append("successore non individuato")
    elif succ == "in_corso":
        problemi.append("successione in via di definizione")
    if strumenti != "si":
        problemi.append("nessuno strumento successorio (patto di famiglia, testamento, holding, trust)")
    if not problemi:
        return _esito("verde", "Successore individuato e strumenti successori adottati.")
    col = "rosso" if eta >= 60 and succ in (None, "", "no") else "giallo"
    return _esito(col, ("Titolare di " + f"{eta:.0f} anni: " if eta else "") + "; ".join(problemi) + ".")


def analizza(dati: dict, bilancio: dict | None, indici_ultimo: dict | None, p: dict) -> dict:
    dati = dati or {}
    bil = bilancio or {}
    ind = indici_ultimo or {}
    ebitda = ind.get("ebitda")
    pfn = ind.get("pfn") or 0
    multiplo = _num(p.get("multiplo_ebitda_valutazione"), 5)
    valore_auto = None
    if ebitda and ebitda > 0:
        valore_auto = max(ebitda * multiplo - pfn, bil.get("patrimonio_netto") or 0)
    elif bil.get("patrimonio_netto"):
        valore_auto = max(bil["patrimonio_netto"], 0)

    voci = []
    dettagli = {}
    for c in CATALOGO:
        k = c["chiave"]
        d = dati.get(k, {}) or {}
        if k == "persona_chiave":
            esito, dettagli[k] = _persona_chiave(d, ebitda, p)
        elif k == "soci":
            esito, dettagli[k], valore = _soci(d, valore_auto)
            dettagli["valore_azienda"] = valore
        elif k == "passaggio":
            esito = _passaggio(d)
        else:
            stato = d.get("stato") or "da_verificare"
            col = STATI.get(stato, "grigio")
            testo = {"protetto": "Coperto.", "parziale": "Copertura parziale o massimali da rivedere.",
                     "scoperto": "Non coperto.", "da_verificare": "Da verificare.",
                     "non_applicabile": "Non applicabile."}.get(stato, "")
            if k == "catastrofale" and stato == "scoperto":
                testo = "Non coperto: è un obbligo di legge."
            if k == "credito" and stato in ("scoperto", "da_verificare") and (ind.get("dso") or 0) > 90:
                testo += f" Incassi medi a {ind['dso']:.0f} giorni: la copertura merita attenzione."
                col = "rosso" if stato == "scoperto" else col
            if k == "interruzione" and stato in ("scoperto", "da_verificare") and bil.get("costo_personale"):
                fissi = (bil.get("costo_personale") or 0) + (bil.get("godimento_beni_terzi") or 0) + (bil.get("ammortamenti") or 0)
                testo += f" Costi fissi indicativi (personale, affitti e leasing, ammortamenti): {fissi:,.0f} € l'anno.".replace(",", ".")
            esito = _esito(col, testo)
            esito["scadenza"] = d.get("scadenza")
            esito["compagnia"] = d.get("compagnia")
        voci.append({"chiave": k, "titolo": c["titolo"], "perche": c["perche"], "obbligo": c.get("obbligo", False),
                     "speciale": c.get("speciale", False), **esito})

    conteggio = {col: sum(1 for v in voci if v["colore"] == col) for col in ("verde", "giallo", "rosso", "grigio")}
    priorita = sorted([v for v in voci if v["colore"] in ("rosso", "giallo")],
                      key=lambda v: (v["colore"] != "rosso", not v["obbligo"], -(v["gap"] or 0)))
    return {"voci": voci, "dettagli": dettagli, "conteggio": conteggio, "valore_azienda_stimato": valore_auto,
            "priorita": [{"chiave": v["chiave"], "titolo": v["titolo"], "colore": v["colore"], "gap": v["gap"]} for v in priorita]}
