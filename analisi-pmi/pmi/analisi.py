"""Analisi completa di un'azienda: mette insieme tutti i moduli e ricava le proposte operative."""
from __future__ import annotations

from datetime import date

from . import crisi, indici, rischi, scadenze, tfm, tfr


def euro(x) -> str:
    if x is None:
        return "n.d."
    return f"{x:,.0f} €".replace(",", ".")


def proposte(an: dict) -> list[dict]:
    out = []

    def add(priorita, area, titolo, dettaglio="", importo=None):
        out.append({"priorita": priorita, "area": area, "titolo": titolo, "dettaglio": dettaglio, "importo": importo})

    bil = an["bilancio_ultimo"]
    ind = an["indici"]
    r = an["rischi"]
    voci = {v["chiave"]: v for v in r["voci"]}

    if voci["catastrofale"]["colore"] == "rosso":
        add(1, "Rischi", "Mettere in regola la polizza catastrofale", "È un obbligo di legge per le imprese con sede in Italia.")
    elif voci["catastrofale"]["colore"] == "grigio":
        add(2, "Rischi", "Verificare la polizza catastrofale obbligatoria", "Controllare beni assicurati, somme e scadenza.")

    c = an["crisi"]
    rossi_crisi = [s["titolo"] for s in c["segnali"] if s["colore"] == "rosso"]
    if rossi_crisi:
        add(1, "Crisi", "Segnali di crisi presenti", "Segnali: " + "; ".join(rossi_crisi) +
            ". Valutare con il commercialista le misure previste dal Codice della crisi.")
    for p in c["patrimonio"]:
        if p["colore"] == "rosso":
            add(1, "Crisi", "Patrimonio netto negativo", p["testo"])

    g = ind["giudizio"]
    if g["rossi"]:
        nomi = ", ".join(indici.ETICHETTE.get(k, k) for k in g["rossi"])
        add(2, "Bilancio", "Indici in rosso da approfondire", nomi)

    t = an["tfr"]
    if t.get("metodo") == "bilancio":
        add(2, "TFR", "Chiedere al consulente del lavoro il prospetto TFR per dipendente",
            "Serve per proiettare le uscite reali (pensionamenti, dimissioni, anticipi) invece della stima dal bilancio.")
    if t.get("metodo") and t.get("premio_flussi", 0) > 0:
        add(2, "TFR", "Accantonare il TFR in una polizza dedicata",
            f"Premio annuo indicativo per coprire le uscite attese dei prossimi {len(t['anni'])} anni: {euro(t['premio_flussi'])}; "
            f"uscite attese nei primi 5 anni: {euro(t['uscite_5_anni'])}.", t["premio_flussi"])
    if t.get("stress") and t.get("liquidita") and t["stress"]["importo"] > 0.5 * t["liquidita"]:
        add(2, "TFR", "Proteggere la cassa dall'uscita delle persone con più anzianità",
            f"Il TFR delle {len(t['stress']['persone'])} persone con il fondo più alto vale {euro(t['stress']['importo'])}.")

    m = an["tfm"]
    comp_bil = bil.get("compensi_amministratori")
    if not m["amministratori"]:
        if comp_bil:
            add(2, "TFM", "Valutare il TFM per gli amministratori",
                f"Compensi amministratori in bilancio: {euro(comp_bil)}. Con il TFM una parte del compenso diventa "
                "deducibile anno per anno e tassata separatamente alla fine del mandato.")
        else:
            add(3, "TFM", "Raccogliere compensi e mandati degli amministratori", "Per simulare il trattamento di fine mandato.")
    for a in m["amministratori"]:
        for v in a["verifiche"]:
            if v["colore"] == "rosso":
                add(1, "TFM", f"TFM {a['nome'] or 'amministratore'}: requisito da sistemare", v["testo"])
        if not any("polizza intestata" in v["testo"] for v in a["verifiche"] if v["colore"] == "verde"):
            add(2, "TFM", f"Coprire con polizza il TFM di {a['nome'] or 'amministratore'}",
                f"Accantonamento annuo {euro(a['accantonamento_annuo'])}; capitale a fine mandato stimato {euro(a['capitale_polizza'])}.",
                a["accantonamento_annuo"])

    for k, titolo in (("persona_chiave", "Copertura persona chiave"), ("soci", "Accordo tra soci e coperture incrociate")):
        v = voci[k]
        if v["colore"] in ("rosso", "giallo") and v.get("gap"):
            add(2, "Rischi", titolo, f"Fabbisogno stimato {euro(v['fabbisogno'])}, già coperto {euro(v['coperto'])}, "
                                      f"scoperto {euro(v['gap'])}.", v["gap"])
    if voci["passaggio"]["colore"] in ("rosso", "giallo"):
        add(2 if voci["passaggio"]["colore"] == "rosso" else 3, "Rischi", "Pianificare il passaggio generazionale", voci["passaggio"]["testo"])
    scoperti = [v["titolo"] for v in r["voci"] if v["colore"] == "rosso" and not v["speciale"] and v["chiave"] != "catastrofale"]
    if scoperti:
        add(2, "Rischi", "Rischi senza copertura", ", ".join(scoperti) + ".")
    if c["assetti_mancanti"]:
        mancanti = [a["testo"] for a in c["assetti"] if a["colore"] == "rosso"]
        add(3, "Crisi", "Completare gli adeguati assetti (art. 2086 c.c.)", "; ".join(mancanti) + ".")
    out.sort(key=lambda x: x["priorita"])
    return out


def completa(archivio, aid: int, par: dict, oggi: date | None = None) -> dict | None:
    oggi = oggi or date.today()
    az = archivio.azienda(aid)
    if not az:
        return None
    bil = archivio.bilanci(aid)
    sez = archivio.sezioni(aid)
    ind = indici.analizza([{"anno": b["anno"], "dati": b["dati"]} for b in bil], par["soglie"])
    ultimo = bil[-1]["dati"] if bil else {}
    ind_ultimo = ind["anni"][-1]["valori"] if ind["anni"] else {}
    anno_base = bil[-1]["anno"] if bil else oggi.year - 1

    tfr_par = {**par["tfr"], **{k: v for k, v in (sez.get("tfr") or {}).items() if v not in (None, "")}}
    elenco = (sez.get("dipendenti") or {}).get("elenco", [])
    tfm_sez = sez.get("tfm") or {}
    tfm_par = {**par["tfm"], **{k: v for k, v in (tfm_sez.get("parametri") or {}).items() if v not in (None, "")}}

    an = {
        "azienda": az,
        "bilanci": bil,
        "sezioni": sez,
        "bilancio_ultimo": ultimo,
        "anno_ultimo": bil[-1]["anno"] if bil else None,
        "indici": ind,
        "tfr": tfr.analizza(elenco, tfr_par, ultimo, anno_base),
        "tfr_parametri": tfr_par,
        "tfm": tfm.analizza(tfm_sez.get("amministratori", []), tfm_par, oggi),
        "tfm_parametri": tfm_par,
        "rischi": rischi.analizza(sez.get("rischi"), ultimo, ind_ultimo, par["rischi"]),
        "crisi": crisi.analizza(sez.get("crisi"), ultimo),
        "scadenze": scadenze.calcola(az, bil, sez, par["scadenze"], oggi),
    }
    an["proposte"] = proposte(an)
    an["punteggio"] = sum({1: 5, 2: 2, 3: 1}[p["priorita"]] for p in an["proposte"])
    return an


def riepilogo(an: dict) -> dict:
    """Riga del portafoglio."""
    u = an["bilancio_ultimo"]
    ind = an["indici"]
    prossima = next((s for s in an["scadenze"] if s["giorni"] >= 0 and not s.get("fatto")), None)
    return {
        "id": an["azienda"]["id"],
        "ragione_sociale": an["azienda"]["ragione_sociale"],
        "ateco": an["azienda"]["ateco"],
        "esempio": bool(an["azienda"].get("esempio")),
        "anno": an["anno_ultimo"],
        "ricavi": u.get("ricavi"),
        "dipendenti": u.get("dipendenti") or (len((an["sezioni"].get("dipendenti") or {}).get("elenco", [])) or None),
        "solidita": ind["giudizio"],
        "tfr_debito": an["tfr"].get("debito"),
        "tfr_scopertura": an["tfr"].get("scopertura"),
        "rischi": an["rischi"]["conteggio"],
        "segnali_crisi": an["crisi"]["segnali_presenti"],
        "proposte": len(an["proposte"]),
        "urgenti": sum(1 for p in an["proposte"] if p["priorita"] == 1),
        "punteggio": an["punteggio"],
        "prossima_scadenza": prossima,
        "aggiornata": an["azienda"]["aggiornata"],
    }
