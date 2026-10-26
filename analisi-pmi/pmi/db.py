"""Archivio locale SQLite (cartella dati/, esclusa da git)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .parametri import RADICE

CARTELLA_DATI = RADICE / "dati"
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS aziende (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ragione_sociale TEXT NOT NULL,
  codice_fiscale TEXT DEFAULT '', forma TEXT DEFAULT '', ateco TEXT DEFAULT '', sede TEXT DEFAULT '',
  referente TEXT DEFAULT '', note TEXT DEFAULT '', esempio INTEGER DEFAULT 0,
  creata TEXT, aggiornata TEXT
);
CREATE TABLE IF NOT EXISTS bilanci (
  azienda_id INTEGER NOT NULL REFERENCES aziende(id) ON DELETE CASCADE,
  anno INTEGER NOT NULL, chiusura TEXT, tipo TEXT DEFAULT '', fonte TEXT DEFAULT 'manuale',
  dati TEXT NOT NULL DEFAULT '{}', aggiornato TEXT,
  PRIMARY KEY (azienda_id, anno)
);
CREATE TABLE IF NOT EXISTS sezioni (
  azienda_id INTEGER NOT NULL REFERENCES aziende(id) ON DELETE CASCADE,
  chiave TEXT NOT NULL, dati TEXT NOT NULL DEFAULT '{}', aggiornata TEXT,
  PRIMARY KEY (azienda_id, chiave)
);
"""
CAMPI_AZIENDA = ("ragione_sociale", "codice_fiscale", "forma", "ateco", "sede", "referente", "note")
SEZIONI = ("dipendenti", "tfr", "tfm", "rischi", "crisi", "scadenze")
# priorità delle fonti: un dato inserito a mano non viene sovrascritto da un import
PRIORITA_FONTE = {"xbrl-precedente": 1, "xbrl": 2, "manuale": 3}


def _ora():
    return datetime.now().isoformat(timespec="seconds")


class Archivio:
    def __init__(self, percorso: Path | None = None):
        self.percorso = Path(percorso) if percorso else CARTELLA_DATI / "pmi.sqlite"
        self.percorso.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(self.percorso, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.executescript(SCHEMA)

    def _q(self, sql, args=()):
        with self._lock:
            cur = self._con.execute(sql, args)
            self._con.commit()
            return cur

    # ---- aziende
    def aziende(self):
        return [dict(r) for r in self._q("SELECT * FROM aziende ORDER BY ragione_sociale COLLATE NOCASE")]

    def azienda(self, aid):
        r = self._q("SELECT * FROM aziende WHERE id = ?", (aid,)).fetchone()
        return dict(r) if r else None

    def crea_azienda(self, dati: dict, esempio=False) -> int:
        valori = {k: str(dati.get(k) or "").strip() for k in CAMPI_AZIENDA}
        if not valori["ragione_sociale"]:
            raise ValueError("La ragione sociale è obbligatoria")
        cur = self._q(f"INSERT INTO aziende ({', '.join(CAMPI_AZIENDA)}, esempio, creata, aggiornata) "
                      f"VALUES ({', '.join('?' * len(CAMPI_AZIENDA))}, ?, ?, ?)",
                      (*valori.values(), 1 if esempio else 0, _ora(), _ora()))
        return cur.lastrowid

    def aggiorna_azienda(self, aid, dati: dict):
        campi = [k for k in CAMPI_AZIENDA if k in dati]
        if "ragione_sociale" in campi and not str(dati["ragione_sociale"]).strip():
            raise ValueError("La ragione sociale è obbligatoria")
        if campi:
            self._q(f"UPDATE aziende SET {', '.join(k + ' = ?' for k in campi)}, aggiornata = ? WHERE id = ?",
                    (*[str(dati[k] or "").strip() for k in campi], _ora(), aid))

    def elimina_azienda(self, aid):
        self._q("DELETE FROM aziende WHERE id = ?", (aid,))

    def tocca(self, aid):
        self._q("UPDATE aziende SET aggiornata = ? WHERE id = ?", (_ora(), aid))

    # ---- bilanci
    def bilanci(self, aid):
        out = []
        for r in self._q("SELECT * FROM bilanci WHERE azienda_id = ? ORDER BY anno", (aid,)):
            d = dict(r)
            d["dati"] = json.loads(d["dati"])
            out.append(d)
        return out

    def salva_bilancio(self, aid, anno: int, dati: dict, chiusura=None, tipo="", fonte="manuale", forza=True) -> bool:
        """Salva un esercizio. Con forza=False non sovrascrive un esercizio con fonte di priorità maggiore."""
        esistente = self._q("SELECT fonte FROM bilanci WHERE azienda_id = ? AND anno = ?", (aid, anno)).fetchone()
        if esistente and not forza and PRIORITA_FONTE.get(esistente["fonte"], 0) > PRIORITA_FONTE.get(fonte, 0):
            return False
        pulito = {k: float(v) for k, v in dati.items() if v not in (None, "") and _numero(v)}
        self._q("INSERT INTO bilanci (azienda_id, anno, chiusura, tipo, fonte, dati, aggiornato) VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(azienda_id, anno) DO UPDATE SET chiusura = excluded.chiusura, tipo = excluded.tipo, "
                "fonte = excluded.fonte, dati = excluded.dati, aggiornato = excluded.aggiornato",
                (aid, int(anno), chiusura or f"{int(anno)}-12-31", tipo, fonte, json.dumps(pulito), _ora()))
        self.tocca(aid)
        return True

    def elimina_bilancio(self, aid, anno):
        self._q("DELETE FROM bilanci WHERE azienda_id = ? AND anno = ?", (aid, anno))

    # ---- sezioni (dipendenti, TFR, TFM, rischi, crisi, scadenze)
    def sezioni(self, aid) -> dict:
        return {r["chiave"]: json.loads(r["dati"]) for r in self._q("SELECT chiave, dati FROM sezioni WHERE azienda_id = ?", (aid,))}

    def salva_sezione(self, aid, chiave, dati):
        if chiave not in SEZIONI:
            raise ValueError("Sezione sconosciuta")
        self._q("INSERT INTO sezioni (azienda_id, chiave, dati, aggiornata) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(azienda_id, chiave) DO UPDATE SET dati = excluded.dati, aggiornata = excluded.aggiornata",
                (aid, chiave, json.dumps(dati, ensure_ascii=False), _ora()))
        self.tocca(aid)

    def esporta(self) -> dict:
        return {"esportato": _ora(), "aziende": [
            {**a, "bilanci": self.bilanci(a["id"]), "sezioni": self.sezioni(a["id"])} for a in self.aziende()]}


def _numero(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False
