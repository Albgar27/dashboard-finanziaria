import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server  # noqa: E402
from aiuti import istanza  # noqa: E402
from pmi.db import Archivio  # noqa: E402


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.srv = server.avvia(0, Archivio(Path(cls.tmp.name) / "t.sqlite"))
        cls.porta = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def req(self, metodo, percorso, corpo=None, intestazioni=None, grezzo=False):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        h = {"X-PMI": "1", "Origin": f"http://127.0.0.1:{self.porta}"}
        h.update(intestazioni or {})
        if corpo is not None and not isinstance(corpo, bytes):
            corpo = json.dumps(corpo).encode()
            h["Content-Type"] = "application/json"
        c.request(metodo, percorso, body=corpo, headers=h)
        r = c.getresponse()
        dati = r.read()
        c.close()
        return r.status, (dati if grezzo else json.loads(dati or b"{}"))

    def test_sicurezza(self):
        self.assertEqual(self.req("POST", "/api/aziende", {"ragione_sociale": "X"}, {"X-PMI": ""})[0], 403)
        self.assertEqual(self.req("POST", "/api/aziende", {"ragione_sociale": "X"}, {"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req("GET", "/api/portafoglio", intestazioni={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.req("GET", "/../server.py", grezzo=True)[0], 404)

    def test_flusso_completo(self):
        st, r = self.req("POST", "/api/aziende", {"ragione_sociale": "Prova"})
        self.assertEqual(st, 201)
        aid = r["id"]
        st, r = self.req("POST", f"/api/aziende/{aid}/xbrl", istanza())
        self.assertEqual(st, 200, r)
        self.assertEqual(sorted(r["salvati"]), [2024, 2025])
        # un esercizio corretto a mano non viene sovrascritto da un nuovo import
        self.req("PUT", f"/api/aziende/{aid}/bilanci/2025", {"dati": {"totale_attivo": 5, "liquidita": 0, "tfr": 10}})
        st, r = self.req("POST", f"/api/aziende/{aid}/xbrl", istanza())
        self.assertEqual(r["saltati"], [2025])
        st, an = self.req("GET", f"/api/aziende/{aid}")
        self.assertEqual(st, 200)
        self.assertEqual(an["azienda"]["codice_fiscale"], "01234567890")  # completato dall'XBRL
        self.assertEqual(an["indici"]["anni"][-1]["valori"]["tfr_su_liquidita"], "inf")  # JSON valido
        st, _ = self.req("PUT", f"/api/aziende/{aid}/sezioni/dipendenti",
                         {"elenco": [{"nome": "A", "ral": 30000, "tfr_azienda": 20000, "data_nascita": "1990-01-01"}]})
        self.assertEqual(st, 200)
        self.assertEqual(self.req("PUT", f"/api/aziende/{aid}/sezioni/sconosciuta", {})[0], 404)
        st, an = self.req("GET", f"/api/aziende/{aid}")
        self.assertEqual(an["tfr"]["metodo"], "dipendenti")
        st, rep = self.req("GET", f"/api/aziende/{aid}/report")
        self.assertEqual(st, 200)
        self.assertTrue(rep["sezioni"])
        st, port = self.req("GET", "/api/portafoglio")
        self.assertIn(aid, [a["id"] for a in port["aziende"]])
        st, testo = self.req("GET", "/api/esporta", grezzo=True)
        self.assertEqual(st, 200)
        self.assertIn(b"Prova", testo)
        self.assertEqual(self.req("DELETE", f"/api/aziende/{aid}")[0], 200)
        self.assertEqual(self.req("GET", f"/api/aziende/{aid}")[0], 404)

    def test_demo_e_statici(self):
        st, r = self.req("POST", "/api/demo", {})
        self.assertEqual(st, 201)
        st, an = self.req("GET", f"/api/aziende/{r['id']}")
        self.assertTrue(an["proposte"])
        st, html = self.req("GET", "/", grezzo=True)
        self.assertEqual(st, 200)
        self.assertIn(b"Analisi PMI", html)
        st, csv = self.req("GET", "/api/modello-dipendenti.csv", grezzo=True)
        self.assertIn(b"data nascita", csv)

    def test_errori(self):
        st, r = self.req("POST", "/api/aziende", {"ragione_sociale": " "})
        self.assertEqual(st, 400)
        st, r = self.req("POST", "/api/aziende", {"ragione_sociale": "Y"})
        st, r = self.req("POST", f"/api/aziende/{r['id']}/xbrl", b"non e' un bilancio")
        self.assertEqual(st, 400)
        self.assertIn("errore", r)


if __name__ == "__main__":
    unittest.main()
