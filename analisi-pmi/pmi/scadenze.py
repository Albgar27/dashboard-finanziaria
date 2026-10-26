"""Scadenze dell'azienda: ricavate dai dati (bilancio, mandati, polizze) più quelle inserite a mano."""
from __future__ import annotations

from datetime import date, timedelta

from .rischi import CATALOGO

TITOLI_RISCHI = {c["chiave"]: c["titolo"] for c in CATALOGO}


def _data(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _anno_dopo(d: date) -> date:
    try:
        return d.replace(year=d.year + 1)
    except ValueError:  # 29 febbraio
        return d.replace(year=d.year + 1, day=28)


def calcola(azienda: dict, bilanci: list[dict], sezioni: dict, p: dict, oggi: date | None = None) -> list[dict]:
    oggi = oggi or date.today()
    giorni_appr = int(p.get("giorni_approvazione_bilancio", 120))
    out = []

    chiusure = [_data(b.get("chiusura")) or date(b["anno"], 12, 31) for b in bilanci]
    c = max(chiusure) if chiusure else date(oggi.year - 1, 12, 31)
    while c + timedelta(days=giorni_appr) < oggi - timedelta(days=30):
        c = _anno_dopo(c)
    appr = c + timedelta(days=giorni_appr)
    out.append({"data": appr.isoformat(), "titolo": f"Approvazione bilancio {c.year}",
                "note": f"Entro {giorni_appr} giorni dalla chiusura (180 se lo statuto lo prevede). Occasione per rivedere TFR e TFM.",
                "origine": "bilancio"})
    out.append({"data": (appr + timedelta(days=30)).isoformat(), "titolo": f"Deposito bilancio {c.year}",
                "note": "Entro 30 giorni dall'approvazione: dopo il deposito si può caricare il nuovo XBRL.", "origine": "bilancio"})

    for a in (sezioni.get("tfm") or {}).get("amministratori", []):
        s = _data(a.get("data_scadenza_mandato"))
        if s:
            out.append({"data": s.isoformat(), "titolo": f"Scadenza mandato {a.get('nome') or 'amministratore'}",
                        "note": "La delibera sul TFM del nuovo mandato va presa, con data certa, prima della nomina.",
                        "origine": "tfm"})

    rischi = sezioni.get("rischi") or {}
    for k, v in rischi.items():
        if isinstance(v, dict) and _data(v.get("scadenza")):
            out.append({"data": v["scadenza"][:10], "titolo": f"Scadenza polizza: {TITOLI_RISCHI.get(k, k.replace('_', ' '))}",
                        "note": v.get("compagnia") or "", "origine": "rischi"})

    for i, m in enumerate((sezioni.get("scadenze") or {}).get("manuali", [])):
        if _data(m.get("data")):
            out.append({"data": m["data"][:10], "titolo": m.get("titolo") or "Scadenza", "note": m.get("note") or "",
                        "origine": "manuale", "indice": i, "fatto": bool(m.get("fatto"))})

    for e in out:
        e["giorni"] = (_data(e["data"]) - oggi).days
        e["azienda_id"] = azienda.get("id")
        e["azienda"] = azienda.get("ragione_sociale")
    out.sort(key=lambda e: e["data"])
    return out
