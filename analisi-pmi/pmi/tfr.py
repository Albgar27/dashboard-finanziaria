"""Proiezione del TFR in azienda e piano di accantonamento in polizza.

Regole (art. 2120 c.c. e norme collegate):
- quota annua = retribuzione utile / 13,5, meno lo 0,50% della retribuzione (contributo L. 297/1982);
- rivalutazione annua del fondo al 31/12 precedente = 1,5% + 75% dell'inflazione, meno l'imposta
  sostitutiva del 17% sulla rivalutazione;
- anticipo: dopo 8 anni di anzianità, fino al 70% del maturato;
- con destinazione "fondo pensione" o "Tesoreria INPS" la quota annua non resta in azienda: in azienda
  rimane solo il fondo già maturato (che continua a rivalutarsi).

La proiezione è un valore atteso: le uscite per dimissioni e anticipi sono pesate con le probabilità
annue indicate; il pensionamento avviene nell'anno in cui si raggiunge l'età di uscita.
"""
from __future__ import annotations

from datetime import date

IMPOSTA_RIVALUTAZIONE = 0.17
CONTRIBUTO_FPLD = 0.005


def _data(s):
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _num(x, predefinito=0.0):
    try:
        return float(x) if x not in (None, "") else predefinito
    except (TypeError, ValueError):
        return predefinito


def quota_annua(ral: float) -> float:
    return ral / 13.5 - CONTRIBUTO_FPLD * ral


def tasso_rivalutazione(inflazione: float) -> float:
    return 0.015 + 0.75 * inflazione


def proietta(dipendenti: list[dict], p: dict, anno_base: int) -> dict:
    """Proiezione anno per anno a partire dal 31/12 di anno_base."""
    orizzonte = int(_num(p.get("orizzonte"), 10))
    inflazione = _num(p.get("inflazione"), 0.02)
    crescita = _num(p.get("crescita_retribuzioni"), 0.02)
    turnover = _num(p.get("turnover"), 0.05)
    anticipi = _num(p.get("anticipi"), 0.02)
    quota_ant = _num(p.get("quota_anticipo"), 0.70)
    eta_def = _num(p.get("eta_pensione"), 67)
    tasso_netto = tasso_rivalutazione(inflazione) * (1 - IMPOSTA_RIVALUTAZIONE)

    anni = [{"anno": anno_base + t, "pensionamenti": 0.0, "dimissioni": 0.0, "anticipi": 0.0,
             "accantonamento": 0.0, "rivalutazione": 0.0, "debito_fine": 0.0} for t in range(1, orizzonte + 1)]
    dettaglio = []
    debito_iniziale = 0.0
    for d in dipendenti:
        fondo = _num(d.get("tfr_azienda"))
        ral = _num(d.get("ral"))
        nascita = _data(d.get("data_nascita"))
        assunzione = _data(d.get("data_assunzione"))
        eta_uscita = _num(d.get("eta_uscita"), eta_def) or eta_def
        in_azienda = (d.get("destinazione") or "azienda") == "azienda"
        debito_iniziale += fondo
        anno_pensione = None
        if nascita:
            anno_pensione = nascita.year + int(eta_uscita)
        if d.get("uscita_prevista"):
            u = _data(d.get("uscita_prevista"))
            if u:
                anno_pensione = min(anno_pensione or u.year, u.year)
        s = 1.0  # probabilità di essere ancora in azienda
        for t, riga in enumerate(anni, start=1):
            anno = riga["anno"]
            if s <= 0:
                break
            rival = fondo * tasso_netto
            quota = quota_annua(ral) if in_azienda else 0.0
            fondo_fine = fondo + rival + quota
            riga["rivalutazione"] += s * rival
            riga["accantonamento"] += s * quota
            if anno_pensione is not None and anno >= anno_pensione:
                riga["pensionamenti"] += s * fondo_fine
                s = 0.0
                fondo = 0.0
                break
            uscita = s * turnover * fondo_fine
            riga["dimissioni"] += uscita
            anzianita = (anno - assunzione.year) if assunzione else 0
            ant = 0.0
            if anzianita >= 8:
                ant = s * (1 - turnover) * anticipi * quota_ant * fondo_fine
                riga["anticipi"] += ant
                fondo_fine *= (1 - anticipi * quota_ant)
            s *= (1 - turnover)
            fondo = fondo_fine
            riga["debito_fine"] += s * fondo
            ral *= (1 + crescita)
        dettaglio.append({
            "id": d.get("id") or d.get("nome"), "nome": d.get("nome") or d.get("id") or "",
            "tfr_azienda": _num(d.get("tfr_azienda")), "anno_pensione": anno_pensione,
            "destinazione": d.get("destinazione") or "azienda",
            "quota_annua": quota_annua(_num(d.get("ral"))) if in_azienda else 0.0,
        })
    for r in anni:
        r["uscite"] = r["pensionamenti"] + r["dimissioni"] + r["anticipi"]
    return {"debito_iniziale": debito_iniziale, "anni": anni, "dipendenti": dettaglio,
            "tasso_rivalutazione_netto": tasso_netto}


def stima_aggregata(fondo: float, accantonamento: float, p: dict, anno_base: int) -> dict:
    """Stima grezza quando manca l'elenco dei dipendenti: si usa solo il bilancio."""
    orizzonte = int(_num(p.get("orizzonte"), 10))
    turnover = _num(p.get("turnover"), 0.05)
    anni_pens = max(_num(p.get("anni_medi_pensione"), 15), 1)
    tasso_netto = tasso_rivalutazione(_num(p.get("inflazione"), 0.02)) * (1 - IMPOSTA_RIVALUTAZIONE)
    anni = []
    for t in range(1, orizzonte + 1):
        rival = fondo * tasso_netto
        fondo_fine = fondo + rival + accantonamento
        pens = fondo_fine / anni_pens
        dim = (fondo_fine - pens) * turnover
        fondo = fondo_fine - pens - dim
        anni.append({"anno": anno_base + t, "pensionamenti": pens, "dimissioni": dim, "anticipi": 0.0,
                     "accantonamento": accantonamento, "rivalutazione": rival, "debito_fine": fondo,
                     "uscite": pens + dim})
    return {"anni": anni}


def piano_polizza(uscite: list[float], rendimento: float, capitale_iniziale: float = 0.0) -> dict:
    """Premio annuo costante (versato a inizio anno) che, con il capitale già accantonato, copre le uscite
    previste di ogni anno (pagate a fine anno) senza mai andare sotto zero."""
    def saldi(premio):
        b, out = capitale_iniziale, []
        for u in uscite:
            b = (b + premio) * (1 + rendimento) - u
            out.append(b)
        return out

    if not uscite or min(saldi(0.0)) >= 0:
        premio = 0.0
    else:
        lo, hi = 0.0, max(sum(uscite), 1.0)
        for _ in range(60):
            mid = (lo + hi) / 2
            if min(saldi(mid)) >= 0:
                hi = mid
            else:
                lo = mid
        premio = hi
    return {"premio_annuo": premio, "saldi": saldi(premio)}


def premio_per_obiettivo(obiettivo: float, anni: int, rendimento: float, capitale_iniziale: float = 0.0) -> float:
    """Premio annuo (inizio anno) per accumulare l'obiettivo in N anni."""
    if anni <= 0:
        return 0.0
    residuo = obiettivo - capitale_iniziale * (1 + rendimento) ** anni
    if residuo <= 0:
        return 0.0
    if rendimento == 0:
        return residuo / anni
    fattore = ((1 + rendimento) ** anni - 1) / rendimento * (1 + rendimento)
    return residuo / fattore


def analizza(dipendenti: list[dict], parametri: dict, bilancio: dict | None, anno_base: int) -> dict:
    p = dict(parametri)
    liquidita = (bilancio or {}).get("liquidita")
    fondo_bilancio = (bilancio or {}).get("tfr")
    capitale_polizza = _num(p.get("capitale_polizza"))
    rendimento = _num(p.get("rendimento_polizza"), 0.025)
    orizzonte = int(_num(p.get("orizzonte"), 10))

    if dipendenti:
        pr = proietta(dipendenti, p, anno_base)
        metodo = "dipendenti"
        debito = pr["debito_iniziale"]
        n = max(int(_num(p.get("stress_persone"), 3)), 0)
        top = sorted(pr["dipendenti"], key=lambda x: x["tfr_azienda"], reverse=True)[:n]
        stress = {"persone": [x["nome"] for x in top], "importo": sum(x["tfr_azienda"] for x in top)}
        fuori_azienda = sum(1 for x in pr["dipendenti"] if x["destinazione"] != "azienda")
    elif fondo_bilancio:
        pr = stima_aggregata(fondo_bilancio, _num((bilancio or {}).get("accantonamento_tfr")), p, anno_base)
        metodo = "bilancio"
        debito = fondo_bilancio
        stress = None
        fuori_azienda = None
    else:
        return {"metodo": None, "messaggio": "Servono l'elenco dei dipendenti o almeno un bilancio con il fondo TFR."}

    uscite = [a["uscite"] for a in pr["anni"]]
    piano = piano_polizza(uscite, rendimento, capitale_polizza)
    debito_finale = pr["anni"][-1]["debito_fine"] if pr["anni"] else debito
    # alternativa: la polizza non paga le uscite intermedie e accumula un capitale pari al debito a fine orizzonte
    premio_debito = premio_per_obiettivo(debito_finale, orizzonte, rendimento, capitale_polizza)
    for a, s in zip(pr["anni"], piano["saldi"]):
        a["saldo_polizza"] = s

    uscite_5 = sum(uscite[:5])
    copertura = None
    if liquidita is not None and debito:
        copertura = (liquidita + capitale_polizza) / debito
    scopertura = max(debito - (liquidita or 0) - capitale_polizza, 0.0) if debito else 0.0
    avvisi = []
    if liquidita is not None and uscite_5 > liquidita + capitale_polizza:
        avvisi.append("Le uscite TFR attese nei prossimi 5 anni superano la liquidità di fine esercizio più quanto già accantonato.")
    if stress and liquidita is not None and stress["importo"] > 0.5 * liquidita:
        avvisi.append(f"L'uscita contemporanea delle {len(stress['persone'])} persone con il TFR più alto assorbirebbe "
                      f"{stress['importo'] / liquidita:.0%} della liquidità." if liquidita else
                      "L'uscita delle persone con il TFR più alto non sarebbe coperta dalla liquidità.")
    if dipendenti and fondo_bilancio and abs(debito - fondo_bilancio) > 0.1 * fondo_bilancio:
        avvisi.append("Il TFR dell'elenco dipendenti differisce di oltre il 10% dal fondo in bilancio: controlla date e importi.")
    return {
        "metodo": metodo,
        "anno_base": anno_base,
        "debito": debito,
        "fondo_bilancio": fondo_bilancio,
        "liquidita": liquidita,
        "capitale_polizza": capitale_polizza,
        "copertura": copertura,
        "scopertura": scopertura,
        "uscite_5_anni": uscite_5,
        "uscite_orizzonte": sum(uscite),
        "stress": stress,
        "fuori_azienda": fuori_azienda,
        "anni": pr["anni"],
        "dipendenti": pr.get("dipendenti", []),
        "premio_flussi": piano["premio_annuo"],
        "premio_debito": premio_debito,
        "debito_fine_orizzonte": debito_finale,
        "tasso_rivalutazione_netto": tasso_rivalutazione(_num(p.get("inflazione"), 0.02)) * (1 - IMPOSTA_RIVALUTAZIONE),
        "avvisi": avvisi,
    }
