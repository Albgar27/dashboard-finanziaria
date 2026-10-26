#!/usr/bin/env python3
"""Analisi PMI – server locale (solo 127.0.0.1).

Avvio:  python3 server.py   (poi apri http://127.0.0.1:8800)
I dati dei clienti restano nella cartella dati/ di questo computer e non vengono mai pubblicati.
"""
from __future__ import annotations

import json
import math
import re
import sys
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

RADICE = Path(__file__).resolve().parent
sys.path.insert(0, str(RADICE))

from pmi import analisi, demo, importa, parametri, report, voci, xbrl  # noqa: E402
from pmi.db import SEZIONI, Archivio  # noqa: E402

STATICI = RADICE / "static"
TIPI = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
        ".svg": "image/svg+xml", ".csv": "text/csv; charset=utf-8"}
MAX_CORPO = 40 * 1024 * 1024


def _pulisci(x):
    """JSON valido: infinito e NaN diventano stringhe o null."""
    if isinstance(x, float):
        if math.isinf(x):
            return "inf" if x > 0 else "-inf"
        if math.isnan(x):
            return None
        return x
    if isinstance(x, dict):
        return {k: _pulisci(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_pulisci(v) for v in x]
    return x


class Gestore(BaseHTTPRequestHandler):
    archivio: Archivio = None
    host_ammessi: set = set()
    server_version = "AnalisiPMI"

    def log_message(self, fmt, *args):
        pass

    # ---- risposte
    def _invia(self, codice, corpo: bytes, tipo, extra=None):
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def _json(self, dati, codice=200):
        self._invia(codice, json.dumps(_pulisci(dati), ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _errore(self, codice, testo):
        self._json({"errore": testo}, codice)

    def _corpo(self) -> bytes:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_CORPO:
            raise ValueError("File troppo grande")
        return self.rfile.read(n) if n else b""

    def _corpo_json(self):
        b = self._corpo()
        return json.loads(b.decode("utf-8")) if b else {}

    # ---- sicurezza: solo questo computer e solo pagine servite da questo server
    def _ammesso(self, scrittura: bool) -> bool:
        if self.headers.get("Host") not in self.host_ammessi:
            self._errore(403, "Host non ammesso")
            return False
        if scrittura:
            origine = self.headers.get("Origin")
            if self.headers.get("X-PMI") != "1" or (origine and origine.replace("http://", "") not in self.host_ammessi):
                self._errore(403, "Richiesta non consentita")
                return False
        return True

    def do_GET(self):
        if not self._ammesso(False):
            return
        self._instrada("GET")

    def do_POST(self):
        if self._ammesso(True):
            self._instrada("POST")

    def do_PUT(self):
        if self._ammesso(True):
            self._instrada("PUT")

    def do_DELETE(self):
        if self._ammesso(True):
            self._instrada("DELETE")

    def _instrada(self, metodo):
        percorso = urlparse(self.path).path
        try:
            for m, regex, fn in ROTTE:
                if m == metodo:
                    trovato = re.fullmatch(regex, percorso)
                    if trovato:
                        return fn(self, *trovato.groups())
            if metodo == "GET":
                return self._statico(percorso)
            self._errore(404, "Non trovato")
        except (ValueError, xbrl.ErroreXBRL) as e:
            self._errore(400, str(e))
        except Exception as e:  # noqa: BLE001
            self._errore(500, f"Errore interno: {e.__class__.__name__}: {e}")

    def _statico(self, percorso):
        if percorso in ("/", ""):
            percorso = "/index.html"
        f = (STATICI / percorso.lstrip("/")).resolve()
        if STATICI not in f.parents or not f.is_file():
            return self._errore(404, "Non trovato")
        self._invia(200, f.read_bytes(), TIPI.get(f.suffix, "application/octet-stream"))

    # ---- API
    def _analisi(self, aid):
        an = analisi.completa(self.archivio, int(aid), parametri.carica())
        if an is None:
            raise LookupError
        return an

    def api_parametri(self):
        p = parametri.carica()
        self._json({"voci": voci.elenco_per_interfaccia(), "sezioni_bilancio": voci.SEZIONI, "tfr": p["tfr"], "tfm": p["tfm"],
                    "soglie": p["soglie"], "rischi": p["rischi"], "oggi": date.today().isoformat(),
                    "ollama": bool(p["server"]["ollama"].get("attivo"))})

    def api_portafoglio(self):
        righe, scad = [], []
        for a in self.archivio.aziende():
            an = analisi.completa(self.archivio, a["id"], parametri.carica())
            righe.append(analisi.riepilogo(an))
            scad += [s for s in an["scadenze"] if -30 <= s["giorni"] <= 120 and not s.get("fatto")]
        righe.sort(key=lambda r: -r["punteggio"])
        scad.sort(key=lambda s: s["data"])
        self._json({"aziende": righe, "scadenze": scad})

    def api_crea(self):
        aid = self.archivio.crea_azienda(self._corpo_json())
        self._json({"id": aid}, 201)

    def api_demo(self):
        self._json({"id": demo.crea(self.archivio)}, 201)

    def api_azienda(self, aid):
        try:
            self._json(self._analisi(aid))
        except LookupError:
            self._errore(404, "Azienda non trovata")

    def api_aggiorna(self, aid):
        self.archivio.aggiorna_azienda(int(aid), self._corpo_json())
        self._json({"ok": True})

    def api_elimina(self, aid):
        self.archivio.elimina_azienda(int(aid))
        self._json({"ok": True})

    def api_xbrl(self, aid):
        aid = int(aid)
        if not self.archivio.azienda(aid):
            return self._errore(404, "Azienda non trovata")
        letto = xbrl.leggi(self._corpo())
        salvati, saltati = [], []
        for e in letto["esercizi"]:
            fonte = "xbrl" if e["corrente"] else "xbrl-precedente"
            ok = self.archivio.salva_bilancio(aid, e["anno"], e["dati"], e["chiusura"], letto["tipo"], fonte, forza=False)
            (salvati if ok else saltati).append(e["anno"])
        az = self.archivio.azienda(aid)
        an = letto["anagrafica"]
        completamento = {k: an[k] for k in ("codice_fiscale", "forma", "ateco", "sede") if an.get(k) and not az.get(k)}
        if completamento:
            self.archivio.aggiorna_azienda(aid, completamento)
        self._json({"salvati": salvati, "saltati": saltati, "tipo": letto["tipo"], "anagrafica": an,
                    "voci_lette": {e["anno"]: len(e["dati"]) for e in letto["esercizi"]}})

    def api_bilancio(self, aid, anno):
        b = self._corpo_json()
        self.archivio.salva_bilancio(int(aid), int(anno), b.get("dati", {}), b.get("chiusura"), b.get("tipo", ""), "manuale")
        self._json({"ok": True})

    def api_elimina_bilancio(self, aid, anno):
        self.archivio.elimina_bilancio(int(aid), int(anno))
        self._json({"ok": True})

    def api_sezione(self, aid, chiave):
        if chiave not in SEZIONI:
            return self._errore(404, "Sezione sconosciuta")
        if not self.archivio.azienda(int(aid)):
            return self._errore(404, "Azienda non trovata")
        self.archivio.salva_sezione(int(aid), chiave, self._corpo_json())
        self._json({"ok": True})

    def api_importa_dipendenti(self):
        nome = self.headers.get("X-Nome-File", "")
        self._json({"elenco": importa.leggi(self._corpo(), nome)})

    def api_modello_dipendenti(self):
        corpo = (RADICE / "modelli" / "dipendenti_modello.csv").read_bytes()
        self._invia(200, corpo, "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="dipendenti_modello.csv"'})

    def api_report(self, aid):
        try:
            self._json(report.genera(self._analisi(aid)))
        except LookupError:
            self._errore(404, "Azienda non trovata")

    def api_report_stile(self, aid):
        conf = parametri.carica()["server"]["ollama"]
        if not conf.get("attivo"):
            return self._errore(400, "Riscrittura disattivata in config.yaml")
        try:
            base = report.genera(self._analisi(aid))
            self._json(report.riscrivi_stile(base, conf, RADICE))
        except RuntimeError as e:
            self._errore(502, str(e))

    def api_esporta(self):
        corpo = json.dumps(_pulisci(self.archivio.esporta()), ensure_ascii=False, indent=1).encode()
        self._invia(200, corpo, "application/json; charset=utf-8",
                    {"Content-Disposition": f'attachment; filename="analisi-pmi-{date.today().isoformat()}.json"'})


ROTTE = [
    ("GET", r"/api/parametri", Gestore.api_parametri),
    ("GET", r"/api/portafoglio", Gestore.api_portafoglio),
    ("POST", r"/api/aziende", Gestore.api_crea),
    ("POST", r"/api/demo", Gestore.api_demo),
    ("GET", r"/api/aziende/(\d+)", Gestore.api_azienda),
    ("PUT", r"/api/aziende/(\d+)", Gestore.api_aggiorna),
    ("DELETE", r"/api/aziende/(\d+)", Gestore.api_elimina),
    ("POST", r"/api/aziende/(\d+)/xbrl", Gestore.api_xbrl),
    ("PUT", r"/api/aziende/(\d+)/bilanci/(\d{4})", Gestore.api_bilancio),
    ("DELETE", r"/api/aziende/(\d+)/bilanci/(\d{4})", Gestore.api_elimina_bilancio),
    ("PUT", r"/api/aziende/(\d+)/sezioni/([a-z_]+)", Gestore.api_sezione),
    ("POST", r"/api/importa-dipendenti", Gestore.api_importa_dipendenti),
    ("GET", r"/api/modello-dipendenti\.csv", Gestore.api_modello_dipendenti),
    ("GET", r"/api/aziende/(\d+)/report", Gestore.api_report),
    ("POST", r"/api/aziende/(\d+)/report/stile", Gestore.api_report_stile),
    ("GET", r"/api/esporta", Gestore.api_esporta),
]


def avvia(porta: int | None = None, archivio: Archivio | None = None, apri_browser=False):
    porta = porta if porta is not None else int(parametri.carica()["server"]["porta"])
    server = ThreadingHTTPServer(("127.0.0.1", porta), Gestore)
    porta = server.server_address[1]
    Gestore.archivio = archivio or Archivio()
    Gestore.host_ammessi = {f"127.0.0.1:{porta}", f"localhost:{porta}"}
    if apri_browser:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://127.0.0.1:{porta}")).start()
    return server


if __name__ == "__main__":
    porta = next((int(a) for a in sys.argv[1:] if a.isdigit()), None)
    srv = avvia(porta, apri_browser="--no-browser" not in sys.argv)
    print(f"Analisi PMI su http://127.0.0.1:{srv.server_address[1]}  (Ctrl+C per fermare)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
