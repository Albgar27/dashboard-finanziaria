"""Lettura dei bilanci XBRL depositati al Registro Imprese (tassonomia itcc-ci).

Accetta il file .xbrl/.xml, un .zip che lo contiene oppure il file firmato .p7m.
Restituisce l'anagrafica e, per ogni esercizio presente (di solito corrente e precedente), le voci
definite in voci.py. Usa solo i fatti senza dimensioni, salvo le voci di nota integrativa che stanno
in tabelle (numero dipendenti, compensi).
"""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
import zipfile
import xml.etree.ElementTree as ET

from .voci import VOCI

XBRLI = "{http://www.xbrl.org/2003/instance}"
XBRLDI = "{http://xbrl.org/2006/xbrldi}"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"


class ErroreXBRL(ValueError):
    pass


def _estrai_xml(dati: bytes) -> bytes:
    """Trova il documento XBRL dentro zip o p7m."""
    if dati[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(dati)) as z:
            nomi = [n for n in z.namelist() if n.lower().endswith((".xbrl", ".xml", ".p7m"))]
            if not nomi:
                raise ErroreXBRL("Lo zip non contiene file .xbrl")
            nomi.sort(key=lambda n: (not n.lower().endswith(".xbrl"), n))
            return _estrai_xml(z.read(nomi[0]))
    testa = dati[:2048].lstrip(b"\xef\xbb\xbf \r\n\t")
    if testa.startswith(b"<"):
        return dati
    # file firmato (.p7m): prima openssl, se c'è; altrimenti si cerca il testo XML nei byte
    if shutil.which("openssl"):
        with tempfile.NamedTemporaryFile(suffix=".p7m") as f:
            f.write(dati)
            f.flush()
            r = subprocess.run(["openssl", "smime", "-verify", "-noverify", "-inform", "DER", "-in", f.name],
                               capture_output=True, timeout=30)
            if r.returncode == 0 and r.stdout.lstrip().startswith(b"<"):
                return r.stdout
    inizio = dati.find(b"<?xml")
    fine = dati.rfind(b"</xbrl>")
    if fine < 0:
        fine = dati.rfind(b"</xbrli:xbrl>")
        chiusura = len(b"</xbrli:xbrl>")
    else:
        chiusura = len(b"</xbrl>")
    if inizio >= 0 and fine > inizio:
        return dati[inizio:fine + chiusura]
    raise ErroreXBRL("Formato non riconosciuto: serve il file XBRL del bilancio (.xbrl, .zip o .p7m)")


def _tipo_bilancio(root) -> str:
    for el in root.iter("{http://www.xbrl.org/2003/linkbase}schemaRef"):
        href = (el.get(XLINK_HREF) or "").lower()
        if "-micr" in href:
            return "micro"
        if "-abb" in href:
            return "abbreviato"
        if "itcc-ci" in href:
            return "ordinario"
    return "non indicato"


def leggi(dati: bytes) -> dict:
    try:
        root = ET.fromstring(_estrai_xml(dati))
    except ET.ParseError as e:
        raise ErroreXBRL(f"Il file non è un XML valido ({e})") from None

    contesti = {}
    for c in root.iter(f"{XBRLI}context"):
        per = c.find(f"{XBRLI}period")
        if per is None:
            continue
        nodo = per.find(f"{XBRLI}instant")
        if nodo is None:
            nodo = per.find(f"{XBRLI}endDate")
        if nodo is None or not (nodo.text or "").strip():
            continue
        con_dim = any(e.tag in (f"{XBRLDI}explicitMember", f"{XBRLDI}typedMember") for e in c.iter())
        contesti[c.get("id")] = (nodo.text.strip()[:10], con_dim)

    semplici, dimensionali, anagrafica = {}, {}, {}
    for el in root:
        tag = el.tag
        if not isinstance(tag, str) or not tag.startswith("{"):
            continue
        ns, nome = tag[1:].split("}", 1)
        if "/itcc/ci" not in ns:
            continue
        ctx = contesti.get(el.get("contextRef"))
        if ctx is None:
            continue
        fine, con_dim = ctx
        testo = (el.text or "").strip()
        if el.get("unitRef") is not None:
            if el.get(XSI_NIL) == "true" or not testo:
                continue
            try:
                valore = float(testo)
            except ValueError:
                continue
            if con_dim:
                dimensionali.setdefault((nome, fine), valore)
            else:
                semplici[(nome, fine)] = valore
        elif nome.startswith("DatiAnagrafici") and not con_dim and testo:
            anagrafica[nome[len("DatiAnagrafici"):]] = testo

    date = sorted({fine for (_, fine) in semplici})
    if not date:
        raise ErroreXBRL("Nel file non ci sono valori di bilancio leggibili")
    # tengo solo le date che hanno almeno il totale attivo o il valore della produzione
    date = [d for d in date if (("TotaleAttivo", d) in semplici or ("TotaleValoreProduzione", d) in semplici)] or date

    esercizi = []
    for d in date:
        dati_anno = {}
        for chiave, _et, _sez, preferiti, somma, accetta_dim in VOCI:
            valore = None
            for nome in preferiti:
                if (nome, d) in semplici:
                    valore = semplici[(nome, d)]
                    break
                if accetta_dim and (nome, d) in dimensionali:
                    valore = dimensionali[(nome, d)]
                    break
            if valore is None and somma is not None:
                if isinstance(somma, list):
                    pezzi = [semplici[(n, d)] for n in somma if (n, d) in semplici]
                else:
                    pezzi = [v for (n, dd), v in semplici.items() if dd == d and somma.match(n)]
                if pezzi:
                    valore = sum(pezzi)
            if valore is not None:
                dati_anno[chiave] = valore
        esercizi.append({"chiusura": d, "anno": int(d[:4]), "dati": dati_anno})

    corrente = max(date)
    for e in esercizi:
        e["corrente"] = e["chiusura"] == corrente
    return {
        "tipo": _tipo_bilancio(root),
        "anagrafica": {
            "ragione_sociale": anagrafica.get("Denominazione", ""),
            "codice_fiscale": anagrafica.get("CodiceFiscale", ""),
            "partita_iva": anagrafica.get("PartitaIva", ""),
            "forma": anagrafica.get("FormaGiuridica", ""),
            "sede": anagrafica.get("Sede", ""),
            "ateco": anagrafica.get("SettoreAttivitaPrevalenteAteco", ""),
        },
        "esercizi": esercizi,
    }
