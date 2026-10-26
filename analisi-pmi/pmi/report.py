"""Report per l'imprenditore: testo a regole, in prima persona, con riscrittura facoltativa nello stile personale (Ollama locale)."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .analisi import euro
from .indici import ETICHETTE


def _pct(x):
    return "n.d." if x is None else f"{x:.1%}".replace(".", ",")


def _pct2(x):
    return f"{x:.2%}".replace(".", ",")


def _x(x):
    if x is None:
        return "n.d."
    if x == float("inf"):
        return "non significativo"
    return f"{x:.2f}".replace(".", ",")


def genera(an: dict) -> dict:
    az = an["azienda"]
    u = an["bilancio_ultimo"]
    ind = an["indici"]
    v = ind["anni"][-1]["valori"] if ind["anni"] else {}
    g = ind["giudizio"]
    sezioni = []

    # --- Sintesi
    if an["anno_ultimo"]:
        p = [f"Ho analizzato il bilancio {an['anno_ultimo']} di {az['ragione_sociale']}"
             + (f" e il confronto con gli esercizi precedenti" if len(ind["anni"]) > 1 else "") + "."]
        p.append(f"Il giudizio complessivo sulla solidità è: {g['testo'].lower()}." if g["colore"] else "")
        if u.get("ricavi") is not None:
            frase = f"I ricavi sono stati {euro(u['ricavi'])}"
            if v.get("crescita_ricavi") is not None:
                frase += f" ({'+' if v['crescita_ricavi'] >= 0 else ''}{_pct(v['crescita_ricavi'])} sull'anno precedente)"
            frase += f", con un margine operativo lordo di {euro(v.get('ebitda'))} ({_pct(v.get('ebitda_margin'))} del valore della produzione)."
            p.append(frase)
    else:
        p = [f"Per {az['ragione_sociale']} non ho ancora un bilancio caricato: l'analisi si basa sulle informazioni raccolte."]
    sezioni.append({"titolo": "Sintesi", "paragrafi": [x for x in p if x]})

    # --- Bilancio
    if ind["anni"]:
        p = []
        p.append(f"La posizione finanziaria netta è {euro(v.get('pfn'))}"
                 + (f", pari a {_x(v.get('pfn_ebitda'))} volte il margine operativo lordo." if v.get("pfn") and v["pfn"] > 0
                    else ": l'azienda ha più liquidità che debiti finanziari."))
        p.append(f"La liquidità corrente è {_x(v.get('liquidita_corrente'))} e il patrimonio netto finanzia il "
                 f"{_pct(v.get('indipendenza_finanziaria'))} dell'attivo.")
        if v.get("altman_z") is not None:
            zona = "sicura" if v["altman_z"] > 2.6 else "grigia" if v["altman_z"] >= 1.1 else "di rischio"
            p.append(f"Lo Z-score di Altman per le imprese non quotate è {_x(v['altman_z'])}: zona {zona}.")
        if g["rossi"]:
            p.append("Gli indici che richiedono attenzione sono: " + ", ".join(ETICHETTE.get(k, k) for k in g["rossi"]) + ".")
        sezioni.append({"titolo": "Equilibrio economico e finanziario", "paragrafi": p})

    # --- TFR
    t = an["tfr"]
    if t.get("metodo"):
        p = [f"Il debito TFR verso i dipendenti ammonta a {euro(t['debito'])}"
             + (f", a fronte di una liquidità di {euro(t['liquidita'])}" if t.get("liquidita") is not None else "") + "."]
        p.append(f"Nei prossimi cinque anni prevedo uscite per circa {euro(t['uscite_5_anni'])} tra pensionamenti, "
                 "dimissioni e anticipi." + (" La stima viene dal bilancio: con il prospetto per dipendente diventa più precisa."
                                              if t["metodo"] == "bilancio" else ""))
        if t.get("stress"):
            p.append(f"Se uscissero insieme le {len(t['stress']['persone'])} persone con il fondo più alto, l'azienda dovrebbe "
                     f"pagare subito {euro(t['stress']['importo'])}.")
        if t.get("premio_flussi", 0) > 0:
            p.append(f"Un accantonamento in polizza di circa {euro(t['premio_flussi'])} l'anno copre le uscite attese anno per anno, "
                     "senza togliere liquidità alla gestione nel momento in cui il TFR va pagato.")
        p += t.get("avvisi", [])
        sezioni.append({"titolo": "Trattamento di fine rapporto", "paragrafi": p})

    # --- TFM
    m = an["tfm"]
    if m["amministratori"]:
        p = []
        for a in m["amministratori"]:
            s_tfm, _, s_comp = a["scenari"]
            nome = a["nome"] or "l'amministratore"
            p.append(f"Per {nome}, un TFM pari al {_pct2(a['percentuale'])} del compenso vale "
                     f"{euro(a['accantonamento_annuo'])} l'anno e {euro(a['totale'])} in {a['anni']} anni. "
                     f"Rispetto a erogare la stessa somma come compenso, all'amministratore arrivano netti {euro(s_tfm['netto_amministratore'])} "
                     f"invece di {euro(s_comp['netto_amministratore'])}, con un costo netto per la società di {euro(s_tfm['costo_netto'])} "
                     f"invece di {euro(s_comp['costo_netto'])}.")
            for ver in a["verifiche"]:
                # le istruzioni per il consulente ("Indica ...") non vanno nel report al cliente
                if ver["colore"] != "verde" and not ver["testo"].startswith("Indica"):
                    p.append(ver["testo"])
        p.append("Le aliquote sono ipotesi da verificare con il commercialista; il compenso, a differenza del TFM, alimenta anche la pensione.")
        sezioni.append({"titolo": "Trattamento di fine mandato", "paragrafi": p})

    # --- Rischi
    r = an["rischi"]
    p = []
    rossi = [x for x in r["voci"] if x["colore"] == "rosso"]
    gialli = [x for x in r["voci"] if x["colore"] == "giallo"]
    if rossi:
        p.append("I rischi oggi senza protezione sono: " + "; ".join(x["titolo"] for x in rossi) + ".")
    if gialli:
        p.append("Coperti solo in parte: " + "; ".join(x["titolo"] for x in gialli) + ".")
    for x in r["voci"]:
        if x["colore"] in ("rosso", "giallo") and x.get("gap"):
            p.append(f"{x['titolo']}: fabbisogno stimato {euro(x['fabbisogno'])}, scoperto {euro(x['gap'])}.")
    if not p:
        p.append("Dalle informazioni raccolte non emergono rischi rilevanti senza copertura.")
    sezioni.append({"titolo": "Rischi e coperture", "paragrafi": p})

    # --- Crisi
    c = an["crisi"]
    p = [s["testo"] for s in c["segnali"] if s["colore"] == "rosso"] + [x["testo"] for x in c["patrimonio"] if x["colore"] != "verde"]
    if c["assetti_mancanti"]:
        p.append("Per gli adeguati assetti richiesti dall'art. 2086 c.c. mancano: "
                 + "; ".join(a["testo"] for a in c["assetti"] if a["colore"] == "rosso") + ".")
    if p:
        sezioni.append({"titolo": "Prevenzione della crisi", "paragrafi": p})

    proposte = [{"titolo": x["titolo"], "dettaglio": x["dettaglio"], "priorita": x["priorita"]} for x in an["proposte"]]
    return {"titolo": f"Analisi di {az['ragione_sociale']}", "sezioni": sezioni, "proposte": proposte,
            "nota": "Analisi basata su bilanci depositati e informazioni fornite dall'azienda. Le simulazioni fiscali e "
                    "previdenziali sono indicative e vanno verificate con il commercialista e il consulente del lavoro."}


NUMERI = re.compile(r"\d[\d.,]*")


def _numeri(testo: str) -> set:
    return {n.rstrip(".,") for n in NUMERI.findall(testo)}


def riscrivi_stile(report: dict, conf: dict, radice: Path) -> dict:
    """Riscrive i paragrafi con Ollama nello stile di stile_alberto.md. Tiene l'originale se il modello
    cambia o inventa numeri. Solo rete locale: i dati non escono dal Mac."""
    import requests

    stile = ""
    percorso = (radice / conf.get("stile", "../stile_alberto.md")).resolve()
    if percorso.exists():
        stile = percorso.read_text(encoding="utf-8")
    system = ("Riscrivi in italiano i paragrafi di un report per un imprenditore, in prima persona, seguendo questo stile:\n"
              + stile + "\nRegole: non aggiungere fatti né numeri; usa esattamente i numeri presenti; niente enfasi commerciale. "
              'Rispondi in JSON: {"paragrafi": ["...", "..."]} con lo stesso numero di paragrafi ricevuti.')
    url = conf.get("indirizzo", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    nuovo = json.loads(json.dumps(report))
    sostituiti = 0
    for sez in nuovo["sezioni"]:
        orig = sez["paragrafi"]
        try:
            r = requests.post(url, timeout=conf.get("timeout", 600), json={
                "model": conf.get("modello", "gemma3:12b"), "stream": False, "format": "json", "keep_alive": "2m",
                "options": {"temperature": 0.3, "num_ctx": 8192},
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": json.dumps({"titolo": sez["titolo"], "paragrafi": orig}, ensure_ascii=False)}]})
            r.raise_for_status()
            out = json.loads(r.json()["message"]["content"]).get("paragrafi", [])
        except Exception as e:  # noqa: BLE001 - qualsiasi errore: si tiene il testo originale
            raise RuntimeError(f"Ollama non raggiungibile o risposta non valida ({e.__class__.__name__})") from None
        if isinstance(out, list) and len(out) == len(orig):
            for i, (o, n) in enumerate(zip(orig, out)):
                if isinstance(n, str) and n.strip() and _numeri(n) <= _numeri(o):
                    sez["paragrafi"][i] = n.strip()
                    sostituiti += 1
    nuovo["riscritti"] = sostituiti
    return nuovo
