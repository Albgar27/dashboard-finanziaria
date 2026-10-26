"""Import dell'elenco dipendenti da CSV o Excel (ad esempio il prospetto TFR del consulente del lavoro)."""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

COLONNE = {
    "nome": ["nome", "codice", "matricola", "dipendente", "cognome e nome", "nominativo"],
    "data_nascita": ["data nascita", "data di nascita", "nascita", "nato il"],
    "data_assunzione": ["data assunzione", "data di assunzione", "assunzione", "assunto il"],
    "ral": ["ral", "retribuzione", "retribuzione annua", "retribuzione utile tfr", "imponibile tfr", "retribuzione lorda"],
    "tfr_azienda": ["tfr", "tfr azienda", "tfr in azienda", "fondo tfr", "tfr maturato", "tfr maturato in azienda", "fondo"],
    "destinazione": ["destinazione", "destinazione tfr", "scelta tfr"],
    "eta_uscita": ["eta uscita", "età uscita", "eta pensione", "età pensione"],
    "uscita_prevista": ["uscita prevista", "data uscita", "data pensione"],
}


def _norm(s: str) -> str:
    s = str(s or "").strip().lower().replace("_", " ")
    return re.sub(r"\s+", " ", s)


def _mappa_intestazioni(intestazioni):
    mappa = {}
    for i, h in enumerate(intestazioni):
        n = _norm(h)
        for campo, alias in COLONNE.items():
            if campo not in mappa.values() and (n == campo.replace("_", " ") or n in alias):
                mappa[i] = campo
                break
    return mappa


def _numero(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("€", "").replace(" ", "")
    if "," in s:  # formato italiano 1.234,56
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):  # 42.000 = quarantaduemila
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _data(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return None


def _destinazione(v):
    n = _norm(v)
    if not n or "azienda" in n:
        return "azienda"
    if "tesoreria" in n or "inps" in n:
        return "tesoreria"
    if "fondo" in n or "previdenza" in n or "pension" in n:
        return "fondo"
    return "azienda"


def _righe(intestazioni, righe):
    mappa = _mappa_intestazioni(intestazioni)
    if "ral" not in mappa.values() and "tfr_azienda" not in mappa.values():
        raise ValueError("Non trovo le colonne della retribuzione o del TFR: usa il modello CSV.")
    out = []
    for r in righe:
        if not any(c not in (None, "") for c in r):
            continue
        d = {campo: (r[i] if i < len(r) else None) for i, campo in mappa.items()}
        out.append({
            "nome": str(d.get("nome") or f"Dipendente {len(out) + 1}").strip(),
            "data_nascita": _data(d.get("data_nascita")),
            "data_assunzione": _data(d.get("data_assunzione")),
            "ral": _numero(d.get("ral")) or 0.0,
            "tfr_azienda": _numero(d.get("tfr_azienda")) or 0.0,
            "destinazione": _destinazione(d.get("destinazione")),
            "eta_uscita": _numero(d.get("eta_uscita")),
            "uscita_prevista": _data(d.get("uscita_prevista")),
        })
    return out


def leggi(dati: bytes, nome_file: str = "") -> list[dict]:
    if dati[:2] == b"PK" or nome_file.lower().endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl
        except ImportError:
            raise ValueError("Per leggere Excel serve openpyxl (pip install openpyxl), oppure salva il file come CSV.") from None
        wb = openpyxl.load_workbook(io.BytesIO(dati), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        righe = [list(r) for r in ws.iter_rows(values_only=True)]
        wb.close()
    else:
        testo = None
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                testo = dati.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        delim = ";" if testo.count(";") >= testo.count(",") else ","
        righe = list(csv.reader(io.StringIO(testo), delimiter=delim))
    # la riga di intestazione è la prima che contiene almeno due nomi di colonna riconosciuti
    for i, r in enumerate(righe[:15]):
        if len(_mappa_intestazioni(r)) >= 2:
            return _righe(r, righe[i + 1:])
    raise ValueError("Intestazioni non riconosciute: usa il modello CSV (nome; data nascita; data assunzione; RAL; TFR azienda; destinazione).")
