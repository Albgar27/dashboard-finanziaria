# Analisi PMI

Piattaforma locale per analizzare le PMI in portafoglio: bilancio, TFR, TFM, rischi e coperture, segnali di crisi,
scadenze e report per l'imprenditore. Gira solo sul Mac (`127.0.0.1`): i dati dei clienti restano in
`analisi-pmi/dati/`, che è esclusa da git e non viene mai pubblicata su GitHub Pages.

> Le simulazioni fiscali e previdenziali sono indicative e vanno verificate con il commercialista e il consulente
> del lavoro. Le soglie degli indici sono uguali per tutti i settori.

## Avvio

```bash
cd analisi-pmi
python3 server.py          # apre http://127.0.0.1:8800
```

Oppure doppio clic su `avvia.command` (al primo avvio: tasto destro → Apri).
Servono Python 3.9 o successivo e, facoltativi, `PyYAML` (per leggere `config.yaml`) e `openpyxl` (per importare
dipendenti da Excel): `pip install -r requirements.txt`. Senza `openpyxl` si importa il CSV.

Per provare senza dati reali: **Portafoglio → Azienda di esempio** (dati inventati, si elimina quando vuoi).

## Cosa fa

| Sezione | Contenuto |
|---|---|
| **Portafoglio** | Tutte le aziende ordinate per priorità (azioni urgenti), solidità, TFR scoperto, coperture, scadenze dei prossimi 4 mesi |
| **Sintesi** | Indicatori chiave e **proposte operative** ordinate per urgenza |
| **Bilancio** | Import del file **XBRL** depositato al Registro Imprese (`.xbrl`, `.zip`, `.p7m`; ordinario, abbreviato, micro). Ogni file porta due esercizi. 21 indici con semaforo: liquidità, PFN/EBITDA, copertura oneri, marginalità, DSO, TFR/liquidità, Z-score di Altman per non quotate. Dati correggibili a mano |
| **TFR** | Proiezione anno per anno delle uscite (pensionamenti, dimissioni, anticipi) dall'elenco dipendenti (CSV/Excel del consulente del lavoro, modello incluso) o, in mancanza, stima dal bilancio. Scenario di stress, premio annuo in polizza per coprire le uscite o accumulare il debito |
| **TFM** | Per ogni amministratore: accantonamento, capitale in polizza, confronto TFM con data certa / senza data certa / stessa somma come compenso; verifiche su data certa, congruità (1/13,5), polizza, scadenza del mandato |
| **Rischi** | 13 voci: catastrofale obbligatoria, persona chiave (fabbisogno da EBITDA), continuità dei soci (valore quote e coperture incrociate), passaggio generazionale, D&O, cyber, RCT/RCO, RC prodotti, beni, interruzione di esercizio, crediti, welfare, previdenza del titolare |
| **Crisi** | Segnali dell'art. 3 c. 4 CCII (retribuzioni, fornitori, banche, creditori pubblici), patrimonio netto (artt. 2446-2447, 2482-bis/ter c.c.), check-list degli adeguati assetti (art. 2086 c.c.) |
| **Scadenze** | Approvazione e deposito bilancio, scadenza dei mandati (delibera TFM prima della nomina), scadenze delle polizze, promemoria manuali |
| **Report** | Documento in prima persona da stampare o salvare in PDF. "Riscrivi nel mio stile" usa Ollama in locale con `../stile_alberto.md` e scarta i paragrafi in cui il modello cambia i numeri |

## Regole di calcolo principali

- **TFR**: quota annua = retribuzione/13,5 − 0,50%; rivalutazione 1,5% + 75% dell'inflazione, meno imposta del 17%;
  anticipo fino al 70% dopo 8 anni. Con fondo pensione o Tesoreria INPS la quota annua non resta in azienda.
  Le uscite volontarie e gli anticipi sono valori attesi (probabilità annue nelle ipotesi).
- **TFM**: deducibilità per competenza e tassazione separata solo con atto di data certa anteriore all'inizio del
  mandato (art. 17 c. 1 lett. c TUIR). Le aliquote (IRES, marginale, tassazione separata, Gestione separata,
  contributi sul TFM) sono ipotesi modificabili per azienda.
- **PFN** = debiti verso banche, altri finanziatori, obbligazionisti e soci − liquidità − attività finanziarie
  correnti. Si può sostituire con un valore inserito a mano.
- **Z''** = 6,56·CCN/Attivo + 3,26·(PN − capitale)/Attivo + 6,72·EBIT/Attivo + 1,05·PN/Passività.

## Parametri

`config.yaml`: porta, Ollama, soglie del semaforo, ipotesi predefinite di TFR e TFM, parametri dei rischi.
Le ipotesi di TFR e TFM si possono poi cambiare per ogni azienda dalla pagina.

## Dati e backup

- Archivio: `analisi-pmi/dati/pmi.sqlite` (escluso da git). Copialo per il backup, oppure usa **Esporta copia (JSON)**.
- Tieni attivo FileVault sul Mac: sono dati personali e societari dei clienti.
- Nell'elenco dipendenti puoi usare codici al posto dei nomi.

## Test

```bash
cd analisi-pmi && python3 -m unittest discover -s tests
```

## File

| File | A cosa serve |
|---|---|
| `server.py` | Server locale e API |
| `pmi/xbrl.py`, `pmi/voci.py` | Lettura XBRL e corrispondenza con la tassonomia itcc-ci 2018-11-04 |
| `pmi/indici.py`, `tfr.py`, `tfm.py`, `rischi.py`, `crisi.py`, `scadenze.py` | Calcoli |
| `pmi/analisi.py`, `report.py` | Proposte operative e report |
| `pmi/db.py`, `importa.py`, `demo.py` | Archivio SQLite, import dipendenti, azienda di esempio |
| `static/` | Interfaccia (HTML, CSS, JavaScript senza librerie esterne) |
| `modelli/dipendenti_modello.csv` | Modello per l'elenco dipendenti |
