# Cruscotto mercati e notizie

Pagina HTML statica (un solo file, `docs/index.html`) con mercati, notizie, video dei TG finanziari,
link istituzionali e stato delle fonti. Si aggiorna da sola due volte al giorno nei giorni feriali
sul Mac (servizi launchd) e viene pubblicata gratis con GitHub Pages. Nessuna chiave API, nessun database,
nessun servizio a pagamento.

> I dati sono in ritardo (alcuni sono medie mensili) e non costituiscono consulenza.

## Struttura

| File | A cosa serve |
|---|---|
| `build_dashboard.py` | Scarica i dati e scrive `docs/index.html` |
| `config.yaml` | Feed, serie di mercato, canali video, link: si modifica senza toccare il codice |
| `glossario_eventi.yaml` | Spiegazioni degli eventi del calendario macro |
| `assets/` | Modello HTML, CSS e JavaScript che lo script inserisce nella pagina |
| `docs/index.html` | La pagina generata (si apre anche con doppio clic) |
| `aggiorna.sh` | Genera la pagina e la pubblica su GitHub Pages (usato dai servizi automatici del Mac) |
| `requirements.txt` | Dipendenze Python (`feedparser`, `requests`, `PyYAML`) |

## Da dove arrivano i dati

- **Mercati live (widget gratuiti TradingView, aggiornati di continuo):** cambi EUR/USD, GBP, CHF, JPY;
  future Eurex sui titoli di Stato (BTP lungo, medio e breve, Bund, Bobl, Schatz, OAT) e CFD sul Treasury
  10 anni; indici e cripto; energia (Brent, WTI, gas naturale, benzina, gasolio da riscaldamento), metalli
  e materie prime agricole; nastro scorrevole in alto. Lo script non scarica nulla da TradingView (non c'è
  un'API gratuita e i termini lo vietano): i valori li mostra TradingView. «(CFD)» indica un contratto che
  replica lo strumento. I future sono prezzi, non rendimenti.
- **Tassi ufficiali (aggiornati dallo script 2 volte al giorno):** €STR (BCE), Treasury 10 anni (Tesoro USA),
  BTP e Bund come media mensile (BCE) e relativo spread. Non possono essere live: TradingView vieta di
  mostrare fuori dal suo sito i rendimenti dei titoli di Stato, l'€STR e gli spread.
- **Calendario macro:** widget calendario economico di TradingView (paesi e importanza in
  `tradingview.calendar`), più i link ai calendari ufficiali di BCE, Fed, Eurostat, ISTAT, BLS e BEA.
  Accanto c'è la **guida agli eventi** (`glossario_eventi.yaml`): scrivi il nome che vedi nel calendario e
  si apre la spiegazione. Il widget non permette di intercettare i clic sui suoi eventi (è un riquadro di un
  altro sito), per questo la descrizione sta nella guida. Per aggiungere una voce copia un blocco nel file
  (nome, chiavi in minuscolo, descrizione) e rigenera la pagina.
  Il widget di Investing.com è stato provato e scartato: incorporato in un'altra pagina resta bianco,
  perché il loro controllo anti-bot richiede cookie che i browser bloccano nei riquadri di altri siti.
  Investing.com non offre API gratuite.

Simboli e sezioni si cambiano in `tradingview:` dentro `config.yaml` (codice «BORSA:SIMBOLO» preso da
tradingview.com); con `autoload: false` i widget partono solo premendo un pulsante.

## Pubblicazione online (GitHub Pages)

La pagina viene generata sul Mac (serve per il report con Ollama e per gli avvisi) e, dopo ogni
aggiornamento, `aggiorna.sh` la carica nel ramo `gh-pages` del repository GitHub, che GitHub Pages
pubblica su `https://UTENTE.github.io/dashboard-finanziaria/` (Brief: `.../brief.html`).
Il ramo `gh-pages` contiene sempre un solo commit, così il repository non cresce a ogni aggiornamento.
Il repository è **pubblico**: chiunque abbia il link vede pagina, watchlist e codice.

- Pubblicare subito: `./aggiorna.sh --solo-notizie`
- Smettere di pubblicare: in GitHub → Settings → Pages → «Unpublish site», oppure `git remote remove origin`
  (gli aggiornamenti continuano solo sul Mac).
- Il Mac deve essere acceso: se è spento la pagina online resta all'ultimo aggiornamento (in alto compare
  l'avviso se i dati hanno più di 36 ore).

## Uso in locale

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python build_dashboard.py
open docs/index.html
```

Aperta come file locale la pagina funziona, ma YouTube può rifiutare i video incorporati (errore 153,
manca l'indirizzo di provenienza): usa «Apri su YouTube» oppure la versione pubblicata.

### Aggiornamento automatico senza GitHub

**Mac (configurazione attiva su questo computer)** – tre servizi in `~/Library/LaunchAgents/`:

| Servizio | Cosa fa |
|---|---|
| `it.dashboard-finanziaria` | aggiornamento completo (tassi ufficiali, notizie, video) alle 07:30 e 17:45, lun-ven |
| `it.dashboard-finanziaria.notizie` | solo notizie e video ogni 30 minuti, dalle 6 alle 23 (i tassi restano quelli dell'ultimo aggiornamento completo) |
| `it.dashboard-finanziaria.web` | piccolo server raggiungibile solo dal Mac: la pagina è su http://127.0.0.1:8799/ |

Il collegamento «Cruscotto finanziario» sulla Scrivania apre http://127.0.0.1:8799/. Servita così, la pagina
riproduce i video YouTube e mostra un avviso «Dati aggiornati» quando arrivano dati nuovi; se non la stai
usando da 5 minuti e non c'è un video aperto si ricarica da sola. Se un'esecuzione è saltata perché il Mac era
in stop, parte al risveglio. L'esito di ogni esecuzione è in `build.log`.
- Aggiornare subito: `launchctl kickstart gui/$(id -u)/it.dashboard-finanziaria`
- Disattivare un servizio: `launchctl bootout gui/$(id -u)/NOME_SERVIZIO`
- Riattivarlo: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/NOME_SERVIZIO.plist`
- Cambiare orario: modifica `Hour`/`Minute` (o `StartInterval` in secondi) nel file `.plist`, poi disattiva e riattiva.

**Avvisi sul Mac** – configurati in `avvisi:` dentro `config.yaml`: notifica per le notizie nuove che
contengono le parole scelte o i nomi della watchlist, per ogni comunicato delle fonti indicate (IVASS, BCE,
Fed) e quando un tasso ufficiale supera una soglia (`soglie:`). Al massimo 5 notifiche per aggiornamento. Se non le vedi,
in Impostazioni di Sistema → Notifiche abilita «Script Editor». Lo stato delle notizie già segnalate è in
`.stato_avvisi.json` (si può cancellare: al giro successivo si riparte senza notifiche arretrate).

**Watchlist** – in `watchlist:` dentro `config.yaml`: ogni titolo/ETF compare per primo nei Mercati (riquadro
live) e le notizie che lo citano nel titolo hanno la stella ★ e un filtro dedicato. I titoli inseriti sono esempi.

**Report del giorno (nel Brief)** – «Il punto del giorno»: le principali notizie delle ultime 24 ore riassunte
da un modello linguistico che gira sul Mac con [Ollama](https://ollama.com) (gratuito, nessun dato esce dal
computer). Installazione già fatta: `brew install ollama`, `brew services start ollama`, `ollama pull gemma3:12b`
(circa 8 GB; il modello più piccolo qwen2.5:7b è stato provato e scartato perché inventava dettagli).
Come funziona: il modello riceve solo titolo e breve sommario di circa 30 notizie scelte (watchlist, banche
centrali, mercati, Italia, notizie riprese da più testate), sceglie le più importanti e scrive **una frase per
notizia**, con la fonte linkata. Lo script scarta ogni frase che contiene numeri o nomi propri assenti dalla
notizia di partenza. Restano possibili imprecisioni di tono o di tema: è una sintesi automatica, da verificare
sull'articolo prima di usarla con un cliente.
Si rigenera negli aggiornamenti completi (07:30 e 17:45) e al massimo ogni 3 ore in quelli «solo notizie»;
richiede circa 2–3 minuti. Impostazioni in `report:` dentro `config.yaml`.
Rigenerarlo subito: `.venv/bin/python build_dashboard.py --solo-notizie --report`.
Fermare Ollama: `brew services stop ollama` (il Brief resta senza report finché non lo riavvii).

**Brief del mattino** – pulsante «Brief» in alto: pagina A4 con «Il punto del giorno», quotazioni e prossimi eventi macro (TradingView).
Se il report non è disponibile (Ollama spento) al suo posto compare l'elenco delle notizie delle ultime 24 ore. «Stampa / salva PDF» per stamparla.

**Linux (cron)** – `crontab -e` e aggiungi (l'ora è quella del computer):
```
30 7 * * 1-5  cd /percorso/dashboard-finanziaria && .venv/bin/python build_dashboard.py >> build.log 2>&1
45 17 * * 1-5 cd /percorso/dashboard-finanziaria && .venv/bin/python build_dashboard.py >> build.log 2>&1
```

**Windows (Utilità di pianificazione)** – Crea attività di base → Giornaliera → ora 07:30 →
Avvio programma: `C:\percorso\dashboard-finanziaria\.venv\Scripts\python.exe`, argomenti
`build_dashboard.py`, «Inizia in»: `C:\percorso\dashboard-finanziaria`. Ripeti per le 17:45.
Nelle proprietà, scheda Trigger, puoi limitare ai giorni feriali con la ripetizione settimanale.

## Aggiungere un feed di notizie

In `config.yaml`, sezione `news_feeds`, aggiungi una riga:
```yaml
  - {name: "Nome fonte", url: "https://…/feed.xml", category: "Mercati"}
```
Categorie: `Italia`, `Mercati`, `Macro/Banche centrali`, `Mondo`, `Previdenza e assicurazioni`.
Opzioni: `summary: false` (niente sommario, es. siti a pagamento), `paywall: true`,
`max_age_hours: 168` (finestra più lunga per fonti che pubblicano poco). Prima di aggiungerlo controlla
che il `robots.txt` del sito non vieti quell'indirizzo e che le condizioni d'uso consentano l'uso.
Sono accettati solo link `https://`.

Per una serie di mercato aggiungi una voce in `markets` con `sources` (tipi `ecb`, `frankfurter`,
`treasury`, `fred`). Per FRED usa solo serie con la dicitura «Public Domain».

Per un canale YouTube aggiungi `{name: "…", id: "UC…"}` in `youtube_channels` (l'ID si trova
nell'indirizzo del canale o in «Condividi canale → Copia ID canale»).

## Cambiare l'orario

Gli orari sono nei file `.plist` in `~/Library/LaunchAgents/` (vedi «Uso in locale»): `Hour`/`Minute` per
l'aggiornamento completo, `StartInterval` (secondi) per quello delle notizie. Dopo la modifica disattiva e
riattiva il servizio con `launchctl bootout` / `launchctl bootstrap`.

## Provare un guasto

```bash
DASH_SIMULATE_FAIL=data-api.ecb.europa.eu,ansa.it .venv/bin/python build_dashboard.py
```
Le fonti su quegli host risultano in errore: la pagina mostra «n.d.» con la data dell'ultimo dato
valido e l'errore in «Stato delle fonti». Rilancia senza la variabile per tornare ai dati reali.

## Sicurezza

- Tutto il contenuto dei feed è inserito con `textContent`, mai con `innerHTML`; i dati incorporati
  sono codificati in modo che nessun testo possa chiudere il blocco `<script>`.
- Sono accettati solo link `https://`; i link esterni hanno `target="_blank" rel="noopener noreferrer"`.
- Content-Security-Policy: script consentiti solo con hash (più `s3.tradingview.com` per i widget di
  TradingView), iframe solo da `youtube-nocookie.com` e TradingView, nessuna connessione diretta dalla pagina ad altre API.
- Nessuna chiave o token nel repository: l'accesso a GitHub è gestito sul Mac da `gh auth login`.
