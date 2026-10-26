"""Trattamento di fine mandato (TFM) degli amministratori: simulazione e verifiche.

Riferimenti:
- art. 17, c. 1, lett. c) TUIR: tassazione separata per l'amministratore se il diritto all'indennità
  risulta da atto di data certa anteriore all'inizio del rapporto;
- art. 105, c. 4 TUIR e orientamento della Cassazione: deducibilità per competenza degli accantonamenti
  con lo stesso requisito della data certa; in mancanza, deduzione solo al pagamento (per cassa);
- congruità: nella prassi si usa come riferimento prudenziale il parametro del TFR (1/13,5 del compenso).

Tutte le aliquote sono ipotesi modificabili: il calcolo serve a confrontare le alternative, non sostituisce
la verifica del commercialista.
"""
from __future__ import annotations

from datetime import date, timedelta

PARAMETRO_TFR = 1 / 13.5


def _num(x, predefinito=0.0):
    try:
        return float(x) if x not in (None, "") else predefinito
    except (TypeError, ValueError):
        return predefinito


def _pct(x):
    return f"{x:.2%}".replace(".", ",")


def _data(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def simula(a: dict, p: dict, oggi: date | None = None) -> dict:
    oggi = oggi or date.today()
    compenso = _num(a.get("compenso"))
    perc = _num(a.get("percentuale"), _num(p.get("percentuale"), 0.0741))
    anni = max(int(_num(a.get("anni"), 3)), 1)
    r = _num(p.get("rendimento_polizza"), 0.025)
    ires = _num(p.get("ires"), 0.24)
    t_marg = _num(p.get("aliquota_marginale"), 0.45)
    t_sep = _num(p.get("aliquota_separata"), 0.33)
    gs = _num(p.get("contributi_gs"), 0.35)
    c_tfm = _num(p.get("contributi_tfm"), 0.0)

    annuo = compenso * perc
    totale = annuo * anni
    capitale_polizza = annuo * (((1 + r) ** anni - 1) / r * (1 + r) if r else anni)

    def scenario(nome, costo_lordo, deduzione, netto, nota):
        costo_netto = costo_lordo - deduzione
        return {"nome": nome, "costo_lordo": costo_lordo, "risparmio_imposte": deduzione, "costo_netto": costo_netto,
                "netto_amministratore": netto, "resa": (netto / costo_netto) if costo_netto else None, "nota": nota}

    contributi_tfm_societa = totale * c_tfm * 2 / 3
    contributi_tfm_amm = totale * c_tfm / 3
    s_tfm = scenario(
        "TFM con atto di data certa",
        totale + contributi_tfm_societa,
        (totale + contributi_tfm_societa) * ires,
        (totale - contributi_tfm_amm) * (1 - t_sep),
        "Deduzione anno per anno; tassazione separata alla liquidazione.")
    s_senza = scenario(
        "TFM senza data certa",
        totale + contributi_tfm_societa,
        (totale + contributi_tfm_societa) * ires,
        (totale - contributi_tfm_amm) * (1 - t_marg),
        "Deduzione rinviata al pagamento; tassazione ordinaria all'aliquota marginale.")
    s_comp = scenario(
        "Stessa somma come compenso",
        totale * (1 + gs * 2 / 3),
        totale * (1 + gs * 2 / 3) * ires,
        totale * (1 - gs / 3) * (1 - t_marg),
        "Imposte subito all'aliquota marginale; i contributi aumentano però la pensione futura.")

    verifiche = []
    inizio, atto, scad = _data(a.get("data_inizio_mandato")), _data(a.get("data_atto")), _data(a.get("data_scadenza_mandato"))
    if atto and inizio:
        if atto < inizio:
            verifiche.append(("verde", "Atto che prevede il TFM con data certa anteriore all'inizio del mandato."))
        else:
            verifiche.append(("rosso", "L'atto che prevede il TFM è successivo all'inizio del mandato: a rischio deducibilità per "
                                       "competenza e tassazione separata. Va deliberato prima del prossimo mandato."))
    else:
        verifiche.append(("giallo", "Indica la data dell'atto (delibera o statuto) con data certa e la data di inizio del mandato."))
    if a.get("data_certa") == "no":
        verifiche.append(("rosso", "L'atto non ha data certa (serve ad es. PEC, registrazione, verbale vidimato o notaio)."))
    if perc > PARAMETRO_TFR + 0.0005:
        verifiche.append(("giallo", f"Accantonamento al {_pct(perc)} del compenso, oltre il riferimento del 7,41% (1/13,5): "
                                    "rischio di contestazione sulla congruità."))
    elif compenso:
        verifiche.append(("verde", f"Accantonamento al {_pct(perc)} del compenso, entro il riferimento di 1/13,5."))
    if a.get("polizza") == "si":
        verifiche.append(("verde", "Accantonamento coperto da polizza intestata alla società."))
    else:
        verifiche.append(("giallo", "Nessuna polizza dedicata: l'accantonamento è solo contabile e alla cessazione servirà liquidità."))
    if scad:
        if scad < oggi:
            verifiche.append(("rosso", f"Mandato scaduto il {scad.strftime('%d/%m/%Y')}: verificare rinnovo e delibera TFM."))
        elif scad - oggi <= timedelta(days=180):
            verifiche.append(("giallo", f"Mandato in scadenza il {scad.strftime('%d/%m/%Y')}: la delibera sul TFM del nuovo "
                                        "mandato va adottata prima della nomina."))
    return {
        "nome": a.get("nome", ""), "compenso": compenso, "percentuale": perc, "anni": anni,
        "accantonamento_annuo": annuo, "totale": totale, "capitale_polizza": capitale_polizza,
        "scenari": [s_tfm, s_senza, s_comp],
        "vantaggio_netto": s_tfm["netto_amministratore"] - s_comp["netto_amministratore"],
        "differenza_costo": s_tfm["costo_netto"] - s_comp["costo_netto"],
        "verifiche": [{"colore": c, "testo": t} for c, t in verifiche],
    }


def analizza(amministratori: list[dict], p: dict, oggi: date | None = None) -> dict:
    risultati = [simula(a, p, oggi) for a in amministratori if _num(a.get("compenso")) > 0]
    return {
        "amministratori": risultati,
        "totale_accantonamento_annuo": sum(r["accantonamento_annuo"] for r in risultati),
        "vantaggio_netto_totale": sum(r["vantaggio_netto"] for r in risultati),
        "parametri": {k: p.get(k) for k in ("ires", "aliquota_marginale", "aliquota_separata", "contributi_gs",
                                             "contributi_tfm", "rendimento_polizza")},
    }
