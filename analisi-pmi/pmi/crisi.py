"""Segnali di crisi (art. 3, c. 4 del Codice della crisi, D.Lgs. 14/2019 come modificato dal D.Lgs. 83/2022),
verifiche sul patrimonio netto (artt. 2446-2447 e 2482-bis/ter c.c.) e check-list degli adeguati assetti (art. 2086 c.c.)."""
from __future__ import annotations

def _num(x):
    try:
        return float(x) if x not in (None, "") else None
    except (TypeError, ValueError):
        return None


ASSETTI = [
    ("budget", "Budget economico e finanziario annuale"),
    ("tesoreria_12m", "Piano di tesoreria a 12 mesi (sostenibilità dei debiti, art. 3 c. 3 CCII)"),
    ("infrannuali", "Situazioni contabili infrannuali (almeno trimestrali)"),
    ("organigramma", "Organigramma, deleghe e responsabilità scritte"),
    ("indici", "Monitoraggio periodico di indici e scaduti"),
    ("test_pratico", "Test pratico per la verifica della ragionevole perseguibilità del risanamento (composizione negoziata)"),
]

CREDITORI_PUBBLICI = [("inps", "INPS"), ("inail", "INAIL"), ("ade", "Agenzia delle Entrate"), ("ader", "Agenzia delle Entrate-Riscossione")]


def analizza(dati: dict, bilancio: dict | None) -> dict:
    d = dati or {}
    b = bilancio or {}
    segnali = []

    monte = _num(d.get("monte_salari_mensile"))
    if monte is None and b.get("salari"):
        monte = b["salari"] / 12
    scad_retr = _num(d.get("retribuzioni_scadute_30"))
    if scad_retr is None or not monte:
        segnali.append(("grigio", "a) Retribuzioni", "Indica i debiti per retribuzioni scaduti da almeno 30 giorni."))
    elif scad_retr > monte / 2:
        segnali.append(("rosso", "a) Retribuzioni", f"Retribuzioni scadute da 30 giorni oltre la metà del monte salari mensile "
                                                     f"({scad_retr:,.0f} € contro {monte / 2:,.0f} €).".replace(",", ".")))
    else:
        segnali.append(("verde", "a) Retribuzioni", "Retribuzioni scadute entro la soglia (metà del monte salari mensile)."))

    f90, fns = _num(d.get("fornitori_scaduti_90")), _num(d.get("fornitori_non_scaduti"))
    if f90 is None or fns is None:
        segnali.append(("grigio", "b) Fornitori", "Indica i debiti verso fornitori scaduti da almeno 90 giorni e quelli non scaduti."))
    elif f90 > fns:
        segnali.append(("rosso", "b) Fornitori", "Debiti verso fornitori scaduti da oltre 90 giorni superiori a quelli non scaduti."))
    else:
        segnali.append(("verde", "b) Fornitori", "Scaduto verso fornitori inferiore al non scaduto."))

    tot_b, sc_b = _num(d.get("esposizione_bancaria")), _num(d.get("esposizione_scaduta_60"))
    if tot_b is None or sc_b is None:
        segnali.append(("grigio", "c) Banche", "Indica l'esposizione bancaria totale e la parte scaduta o sconfinata da oltre 60 giorni."))
    elif tot_b > 0 and sc_b >= 0.05 * tot_b:
        segnali.append(("rosso", "c) Banche", f"Esposizioni scadute o sconfinate da oltre 60 giorni pari al {sc_b / tot_b:.1%} del totale (soglia 5%)."))
    else:
        segnali.append(("verde", "c) Banche", "Esposizioni bancarie scadute sotto il 5%."))

    risposte = {k: d.get("segnalazione_" + k) for k, _ in CREDITORI_PUBBLICI}
    segnalati = [nome for k, nome in CREDITORI_PUBBLICI if risposte[k] == "si"]
    if segnalati:
        segnali.append(("rosso", "d) Creditori pubblici", "Segnalazioni ricevute da: " + ", ".join(segnalati) + " (art. 25-novies CCII)."))
    elif all(risposte[k] == "no" for k, _ in CREDITORI_PUBBLICI):
        segnali.append(("verde", "d) Creditori pubblici", "Nessuna segnalazione da INPS, INAIL, Agenzia delle Entrate o Riscossione."))
    else:
        segnali.append(("grigio", "d) Creditori pubblici", "Indica se sono arrivate segnalazioni da INPS, INAIL, Agenzia delle Entrate o Riscossione."))

    patrimonio = []
    pn, cap = b.get("patrimonio_netto"), b.get("capitale")
    if pn is not None:
        if pn < 0:
            patrimonio.append(("rosso", "Patrimonio netto negativo: obbligo di ricapitalizzare o trasformare/liquidare (artt. 2447, 2482-ter c.c.)."))
        elif cap and pn < cap * 2 / 3:
            patrimonio.append(("giallo", "Perdite oltre un terzo del capitale: vanno portate in assemblea (artt. 2446, 2482-bis c.c.)."))
        else:
            patrimonio.append(("verde", "Patrimonio netto superiore ai due terzi del capitale."))
        if b.get("utile") is not None and b["utile"] < 0:
            patrimonio.append(("giallo", "Ultimo esercizio chiuso in perdita."))

    assetti = []
    for k, testo in ASSETTI:
        v = d.get("assetto_" + k)
        assetti.append({"chiave": k, "testo": testo, "colore": "verde" if v == "si" else "rosso" if v == "no" else "grigio"})

    rossi = sum(1 for s in segnali if s[0] == "rosso") + sum(1 for s in patrimonio if s[0] == "rosso")
    return {
        "segnali": [{"colore": c, "titolo": t, "testo": x} for c, t, x in segnali],
        "patrimonio": [{"colore": c, "testo": t} for c, t in patrimonio],
        "assetti": assetti,
        "assetti_mancanti": sum(1 for a in assetti if a["colore"] == "rosso"),
        "segnali_presenti": rossi,
        "monte_salari_mensile": monte,
    }
