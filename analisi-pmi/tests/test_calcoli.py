import io
import sys
import unittest
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aiuti import istanza  # noqa: E402
from pmi import crisi, demo, importa, indici, parametri, tfm, tfr, xbrl  # noqa: E402


class TestXBRL(unittest.TestCase):
    def test_ordinario(self):
        r = xbrl.leggi(istanza())
        self.assertEqual(r["tipo"], "ordinario")
        self.assertEqual(r["anagrafica"]["ragione_sociale"], "PROVA SRL")
        anni = {e["anno"]: e for e in r["esercizi"]}
        self.assertEqual(sorted(anni), [2024, 2025])
        self.assertTrue(anni[2025]["corrente"])
        d = anni[2025]["dati"]
        self.assertEqual(d["totale_attivo"], 1_100_000)  # il fatto con dimensione non sovrascrive
        self.assertEqual(d["tfr"], 88_000)
        self.assertEqual(d["debiti_entro"], 150_000 * 1.1 + 250_000 * 1.1)  # somma delle voci di dettaglio
        self.assertEqual(d["debiti_banche"], 407_000)
        self.assertEqual(d["ammortamenti"], 35_000)
        self.assertEqual(d["dipendenti"], 12)  # dalla tabella con dimensioni
        self.assertEqual(anni[2024]["dati"]["utile"], -20_000)

    def test_abbreviato_e_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("bilancio.xbrl", istanza(abbreviato=True))
        r = xbrl.leggi(buf.getvalue())
        self.assertEqual(r["tipo"], "abbreviato")
        d = [e for e in r["esercizi"] if e["anno"] == 2025][0]["dati"]
        self.assertEqual(d["debiti_entro"], 440_000)
        self.assertEqual(d["ammortamenti"], 35_000)  # somma a,b,c + d dell'abbreviato

    def test_file_non_valido(self):
        with self.assertRaises(xbrl.ErroreXBRL):
            xbrl.leggi(b"ciao")
        with self.assertRaises(xbrl.ErroreXBRL):
            xbrl.leggi(b"<xbrl></xbrl>")


class TestIndici(unittest.TestCase):
    def setUp(self):
        self.soglie = parametri.carica()["soglie"]

    def test_demo_2025(self):
        d = demo.BILANCI[2025]
        v = indici.calcola(d, demo.BILANCI[2024])
        self.assertAlmostEqual(v["ebitda"], 760_000)
        self.assertAlmostEqual(v["pfn"], 1_180_000)
        self.assertAlmostEqual(v["liquidita_corrente"], 3_170_000 / 2_250_000)
        self.assertAlmostEqual(v["pfn_ebitda"], 1_180_000 / 760_000)
        self.assertAlmostEqual(v["crescita_ricavi"], 6_200_000 / 5_850_000 - 1)
        ta, pn = 5_520_000, 1_650_000
        z = 6.56 * (3_170_000 - 2_250_000) / ta + 3.26 * (pn - 100_000) / ta + 6.72 * 500_000 / ta + 1.05 * pn / (ta - pn)
        self.assertAlmostEqual(v["altman_z"], z)
        self.assertEqual(indici.colore("tfr_su_liquidita", v["tfr_su_liquidita"], self.soglie), "rosso")
        self.assertEqual(indici.colore("liquidita_corrente", v["liquidita_corrente"], self.soglie), "verde")

    def test_casi_limite(self):
        v = indici.calcola({"ebit": -50, "ammortamenti": 10, "debiti_banche": 100, "liquidita": 0, "tfr": 5,
                            "oneri_finanziari": 0, "patrimonio_netto": -10})
        self.assertEqual(v["pfn_ebitda"], float("inf"))
        self.assertEqual(v["tfr_su_liquidita"], float("inf"))
        self.assertEqual(v["pfn_pn"], float("inf"))
        self.assertIsNone(v["roe"])
        v = indici.calcola({"ebit": 50, "debiti_banche": 0, "liquidita": 100})
        self.assertEqual(v["pfn_ebitda"], 0.0)  # cassa netta
        self.assertEqual(indici.analizza([], self.soglie)["giudizio"]["colore"], None)


class TestTFR(unittest.TestCase):
    def test_quota_e_rivalutazione(self):
        self.assertAlmostEqual(tfr.quota_annua(13_500), 1000 - 67.5)
        self.assertAlmostEqual(tfr.tasso_rivalutazione(0.02), 0.03)

    def test_proiezione_un_dipendente(self):
        p = {"orizzonte": 3, "inflazione": 0.02, "crescita_retribuzioni": 0.0, "turnover": 0.0, "anticipi": 0.0, "eta_pensione": 67}
        dip = [{"nome": "A", "data_nascita": "1960-06-01", "data_assunzione": "1990-01-01", "ral": 13_500, "tfr_azienda": 10_000,
                "destinazione": "azienda"}]
        r = tfr.proietta(dip, p, 2025)
        a1 = r["anni"][0]
        self.assertAlmostEqual(a1["rivalutazione"], 10_000 * 0.03 * 0.83)
        self.assertAlmostEqual(a1["debito_fine"], 10_000 + 249 + 932.5)
        # la proiezione parte dal 2026; compie 67 anni nel 2027: tutto il fondo esce in quell'anno
        self.assertEqual([a["anno"] for a in r["anni"]], [2026, 2027, 2028])
        self.assertEqual(a1["pensionamenti"], 0)
        self.assertGreater(r["anni"][1]["pensionamenti"], 12_000)
        self.assertEqual(r["anni"][1]["debito_fine"], 0)
        self.assertEqual(r["anni"][2]["uscite"], 0)

    def test_fondo_pensione_non_accumula(self):
        p = {"orizzonte": 1, "turnover": 0, "anticipi": 0}
        r = tfr.proietta([{"nome": "B", "ral": 30_000, "tfr_azienda": 5_000, "destinazione": "fondo"}], p, 2025)
        self.assertEqual(r["anni"][0]["accantonamento"], 0)

    def test_piano_polizza(self):
        uscite = [100, 0, 500, 50]
        piano = tfr.piano_polizza(uscite, 0.02)
        self.assertGreaterEqual(min(piano["saldi"]), -1e-6)
        meno = tfr.piano_polizza(uscite, 0.02)["premio_annuo"] * 0.99
        b, ok = 0.0, True
        for u in uscite:
            b = (b + meno) * 1.02 - u
            ok = ok and b >= 0
        self.assertFalse(ok)  # il premio trovato è il minimo
        self.assertEqual(tfr.piano_polizza([10], 0.0, 100)["premio_annuo"], 0)

    def test_premio_obiettivo(self):
        p = tfr.premio_per_obiettivo(10_000, 5, 0.03)
        fv = sum(p * 1.03 ** (5 - t) for t in range(5))
        self.assertAlmostEqual(fv, 10_000, places=6)

    def test_analisi_senza_dati(self):
        self.assertIsNone(tfr.analizza([], parametri.carica()["tfr"], {}, 2025)["metodo"])
        r = tfr.analizza([], parametri.carica()["tfr"], {"tfr": 100_000, "liquidita": 20_000, "accantonamento_tfr": 8_000}, 2025)
        self.assertEqual(r["metodo"], "bilancio")
        self.assertAlmostEqual(r["scopertura"], 80_000)


class TestTFM(unittest.TestCase):
    def test_scenari(self):
        p = {"ires": 0.24, "aliquota_marginale": 0.45, "aliquota_separata": 0.30, "contributi_gs": 0.30, "contributi_tfm": 0.0,
             "rendimento_polizza": 0.0}
        r = tfm.simula({"nome": "X", "compenso": 100_000, "percentuale": 0.1, "anni": 2, "data_inizio_mandato": "2025-05-01",
                        "data_atto": "2025-04-20", "polizza": "si"}, p, date(2026, 1, 1))
        self.assertAlmostEqual(r["totale"], 20_000)
        self.assertAlmostEqual(r["capitale_polizza"], 20_000)
        con, senza, comp = r["scenari"]
        self.assertAlmostEqual(con["netto_amministratore"], 14_000)
        self.assertAlmostEqual(senza["netto_amministratore"], 11_000)
        self.assertAlmostEqual(comp["costo_lordo"], 24_000)
        self.assertAlmostEqual(comp["netto_amministratore"], 20_000 * 0.9 * 0.55)
        colori = [v["colore"] for v in r["verifiche"]]
        self.assertIn("giallo", colori)  # 10% oltre 1/13,5
        self.assertNotIn("rosso", colori)

    def test_atto_tardivo(self):
        r = tfm.simula({"compenso": 50_000, "data_inizio_mandato": "2025-05-01", "data_atto": "2025-06-01"}, {}, date(2026, 1, 1))
        self.assertEqual(r["verifiche"][0]["colore"], "rosso")


class TestCrisi(unittest.TestCase):
    def test_segnali(self):
        r = crisi.analizza({"retribuzioni_scadute_30": 6_000, "monte_salari_mensile": 10_000,
                            "fornitori_scaduti_90": 50, "fornitori_non_scaduti": 100,
                            "esposizione_bancaria": 1000, "esposizione_scaduta_60": 50,
                            "segnalazione_inps": "si"}, {"patrimonio_netto": 30, "capitale": 50})
        colori = [s["colore"] for s in r["segnali"]]
        self.assertEqual(colori, ["rosso", "verde", "rosso", "rosso"])
        self.assertEqual(r["patrimonio"][0]["colore"], "giallo")
        self.assertEqual(r["segnali_presenti"], 3)

    def test_monte_salari_da_bilancio(self):
        r = crisi.analizza({"retribuzioni_scadute_30": 1}, {"salari": 120_000})
        self.assertAlmostEqual(r["monte_salari_mensile"], 10_000)


class TestImport(unittest.TestCase):
    def test_modello_csv(self):
        dati = (Path(__file__).resolve().parent.parent / "modelli" / "dipendenti_modello.csv").read_bytes()
        r = importa.leggi(dati, "x.csv")
        self.assertEqual(len(r), 3)
        self.assertEqual(r[0]["data_nascita"], "1968-03-15")
        self.assertEqual(r[0]["tfr_azienda"], 68_500)
        self.assertEqual(r[1]["destinazione"], "fondo")
        self.assertEqual(r[2]["destinazione"], "tesoreria")

    def test_numeri_italiani(self):
        self.assertEqual(importa._numero("1.234,56"), 1234.56)
        self.assertEqual(importa._numero("42.000"), 42_000)
        self.assertEqual(importa._numero("42000.5"), 42_000.5)

    def test_excel(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl non installato")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Prospetto TFR al 31/12/2025"])
        ws.append(["Matricola", "Data di nascita", "Data di assunzione", "Retribuzione annua", "TFR maturato", "Destinazione TFR"])
        ws.append(["M1", date(1970, 1, 2), date(2000, 3, 1), 40_000, 55_000.5, "Fondo pensione"])
        buf = io.BytesIO()
        wb.save(buf)
        r = importa.leggi(buf.getvalue(), "p.xlsx")
        self.assertEqual(r, [{"nome": "M1", "data_nascita": "1970-01-02", "data_assunzione": "2000-03-01", "ral": 40_000.0,
                              "tfr_azienda": 55_000.5, "destinazione": "fondo", "eta_uscita": None, "uscita_prevista": None}])

    def test_intestazioni_sconosciute(self):
        with self.assertRaises(ValueError):
            importa.leggi(b"a;b;c\n1;2;3\n", "x.csv")


if __name__ == "__main__":
    unittest.main()
