#!/usr/bin/env python3
"""Genera docs/index.html: cruscotto statico con mercati, notizie e video.

Uso:
    python build_dashboard.py                # scarica i dati e scrive docs/index.html
    DASH_SIMULATE_FAIL=ecb.europa.eu,ansa.it python build_dashboard.py
                                             # simula il guasto delle fonti su quegli host

Regole seguite:
  * solo fonti gratuite e senza chiave, solo feed RSS e API pubbliche (niente scraping HTML);
  * nessun dato inventato: se una fonte non risponde la voce resta "n.d." e si conserva
    soltanto la data dell'ultimo dato valido (letta dalla pagina generata in precedenza);
  * ogni fonte è isolata: un errore viene registrato in "Stato delle fonti" e non ferma le altre.
"""

from __future__ import annotations

import base64
import calendar
import csv
import datetime as dt
import hashlib
import html
import io
import json
import os
import re
import sys
import time
import traceback
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.yaml"
OUT_PATH = ROOT / "docs" / "index.html"
DATA_TAG_RE = re.compile(
    r'<script id="dashboard-data" type="application/json">(.*?)</script>', re.S
)
SIMULATE_FAIL = [h.strip() for h in os.environ.get("DASH_SIMULATE_FAIL", "").split(",") if h.strip()]
UTC = dt.timezone.utc


# ---------------------------------------------------------------------------
# Rete
# ---------------------------------------------------------------------------
class SourceError(Exception):
    pass


class Fetcher:
    """Sessione HTTP con User-Agent dichiarato, pause per host e un nuovo tentativo."""

    def __init__(self, settings: dict):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = settings["user_agent"]
        self.session.headers["Accept-Language"] = "it-IT,it;q=0.9,en;q=0.6"
        self.timeout = settings.get("request_timeout", 30)
        self.pause = settings.get("pause_between_requests", 1.0)
        self._last_call: dict[str, float] = {}

    def get(self, url: str, attempts: int = 2) -> requests.Response:
        host = urlparse(url).hostname or ""
        if any(h in host for h in SIMULATE_FAIL):
            raise SourceError(f"guasto simulato (DASH_SIMULATE_FAIL) per {host}")
        last_exc: Exception | None = None
        for attempt in range(attempts):
            wait = self.pause - (time.monotonic() - self._last_call.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            try:
                r = self.session.get(url, timeout=self.timeout)
                self._last_call[host] = time.monotonic()
                if r.status_code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                    time.sleep(3 * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    raise SourceError(f"HTTP {r.status_code}")
                return r
            except requests.RequestException as exc:
                self._last_call[host] = time.monotonic()
                last_exc = exc
                if attempt + 1 < attempts:
                    time.sleep(3 * (attempt + 1))
        raise SourceError(short_error(last_exc))


def short_error(exc: Exception | None) -> str:
    if exc is None:
        return "errore sconosciuto"
    if isinstance(exc, requests.Timeout):
        return "tempo scaduto (timeout)"
    if isinstance(exc, requests.ConnectionError):
        return "connessione non riuscita"
    return f"{type(exc).__name__}: {str(exc)[:160]}"


def to_float(s: str) -> float | None:
    s = (s or "").strip()
    if not s or s == ".":
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Fonti per i mercati: ognuna restituisce (serie, meta)
# serie = lista ordinata di (data "AAAA-MM-GG" o "AAAA-MM", valore)
# ---------------------------------------------------------------------------
def src_ecb(f: Fetcher, spec: dict, today: dt.date):
    flow, key = spec["key"].split("/", 1)
    monthly = key.startswith("M.")
    start = f"{today.year - 3}-01" if monthly else (today - dt.timedelta(days=400)).isoformat()
    url = (f"https://data-api.ecb.europa.eu/service/data/{flow}/{key}"
           f"?startPeriod={start}&format=csvdata")
    r = f.get(url)
    rows = csv.DictReader(io.StringIO(r.text))
    series = []
    for row in rows:
        d, v = (row.get("TIME_PERIOD") or "").strip(), to_float(row.get("OBS_VALUE"))
        if d and v is not None:
            series.append((d, v))
    return series, {
        "source": "BCE – Data Portal",
        "source_url": f"https://data.ecb.europa.eu/data/datasets/{flow}/{flow}.{key}",
        "freq": "M" if monthly else "D",
    }


def src_frankfurter(f: Fetcher, spec: dict, today: dt.date):
    sym = spec["symbol"]
    start = (today - dt.timedelta(days=400)).isoformat()
    r = f.get(f"https://api.frankfurter.dev/v1/{start}..?base=EUR&symbols={quote(sym)}")
    rates = r.json().get("rates", {})
    series = sorted((d, float(v[sym])) for d, v in rates.items() if sym in v)
    return series, {"source": "Frankfurter (cambi BCE)", "source_url": "https://frankfurter.dev/", "freq": "D"}


def src_treasury(f: Fetcher, spec: dict, today: dt.date):
    col = spec["column"]
    series = []
    for year in (today.year - 1, today.year):
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
               f"daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
               f"&field_tdr_date_value={year}&page&_format=csv")
        try:
            r = f.get(url)
        except SourceError:
            if year == today.year:
                raise
            continue  # l'anno precedente serve solo per la variazione da inizio anno
        for row in csv.DictReader(io.StringIO(r.text)):
            v = to_float(row.get(col, ""))
            try:
                d = dt.datetime.strptime(row["Date"], "%m/%d/%Y").date().isoformat()
            except (KeyError, ValueError):
                continue
            if v is not None:
                series.append((d, v))
    series.sort()
    return series, {
        "source": "U.S. Department of the Treasury",
        "source_url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve",
        "freq": "D",
    }


def src_fred(f: Fetcher, spec: dict, today: dt.date):
    sid = spec["id"]
    start = (today - dt.timedelta(days=400)).isoformat()
    r = f.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={quote(sid)}&cosd={start}")
    reader = csv.reader(io.StringIO(r.text))
    header = next(reader, None)
    if not header or len(header) < 2:
        raise SourceError("CSV FRED non valido")
    series = [(row[0], v) for row in reader if len(row) >= 2 and (v := to_float(row[1])) is not None]
    return series, {"source": "FRED – St. Louis Fed", "source_url": f"https://fred.stlouisfed.org/series/{sid}", "freq": "D"}


SOURCES = {"ecb": src_ecb, "frankfurter": src_frankfurter, "treasury": src_treasury, "fred": src_fred}


def summarize(series, kind: str, year: int, spark_points: int) -> dict:
    """Calcola ultimo valore, variazione sull'osservazione precedente e da inizio anno."""
    last_d, last_v = series[-1]

    def change(base):
        if base is None:
            return None
        if kind == "level":
            return None if base == 0 else (last_v / base - 1) * 100
        if kind == "rate":
            return (last_v - base) * 100  # punti base
        return last_v - base  # spread: già in punti base

    prev = series[-2][1] if len(series) > 1 else None
    ytd_base = None
    for d, v in series:
        if d < f"{year}-01-01":
            ytd_base = v
    return {
        "value": last_v,
        "date": last_d,
        "prev_date": series[-2][0] if len(series) > 1 else None,
        "chg": change(prev),
        "ytd": change(ytd_base),
        "spark": [[d, v] for d, v in series[-spark_points:]],
    }


def build_markets(cfg, f: Fetcher, prev_items: dict, now: dt.datetime, status: list):
    today = now.date()
    spark_points = cfg["settings"].get("sparkline_points", 90)
    computed: dict[str, dict] = {}
    groups = []
    for group in cfg["markets"]:
        items = []
        for it in group["items"]:
            item = {
                "id": it["id"], "name": it["name"], "kind": it.get("kind", "level"),
                "unit": it.get("unit", ""), "decimals": it.get("decimals"),
                "link": it.get("link"), "value": None, "status": "nd", "reason": "",
                "fetched_at": now.isoformat(),
            }
            errors = []
            for spec in it.get("sources", []):
                stype = spec.get("type")
                if stype == "none":
                    item["reason"] = "nessuna fonte gratuita con riuso consentito"
                    item["status"] = "nosource"
                    break
                if stype == "derived":
                    a, b = (computed.get(x) for x in spec["minus"])
                    if not (a and b):
                        errors.append("dati di base non disponibili")
                        continue
                    bmap = dict(b["series"])
                    series = [(d, round((v - bmap[d]) * 100, 1)) for d, v in a["series"] if d in bmap]
                    if not series:
                        errors.append("nessuna data in comune")
                        continue
                    meta = {"source": "Calcolo su dati BCE", "source_url": a["source_url"], "freq": a["freq"]}
                else:
                    fn = SOURCES.get(stype)
                    label = f"{it['name']} ← {stype}"
                    if fn is None:
                        errors.append(f"tipo di fonte sconosciuto: {stype}")
                        continue
                    try:
                        series, meta = fn(f, spec, today)
                        if not series:
                            raise SourceError("nessuna osservazione nella risposta")
                    except Exception as exc:  # fonte isolata: si registra e si prova la successiva
                        msg = exc.args[0] if isinstance(exc, SourceError) else short_error(exc)
                        errors.append(f"{stype}: {msg}")
                        status.append(status_row(label, "Mercati", meta_url(stype, spec), False, msg, now))
                        continue
                    status.append(status_row(label, "Mercati", meta["source_url"], True,
                                             f"{len(series)} osservazioni, ultima {series[-1][0]}", now))
                item.update(summarize(series, item["kind"], today.year, spark_points))
                item.update(source=meta["source"], source_url=meta["source_url"], freq=meta["freq"], status="ok")
                computed[it["id"]] = {"series": series, **meta}
                break
            if item["status"] != "ok":
                if errors:
                    item["reason"] = "; ".join(errors)
                    item["status"] = "error"
                prev = prev_items.get(it["id"]) or {}
                lv = prev.get("last_valid") if prev.get("value") is None else {
                    "date": prev.get("date"), "fetched_at": prev.get("fetched_at"), "source": prev.get("source")}
                if lv and lv.get("date"):
                    item["last_valid"] = lv
            items.append(item)
        groups.append({"group": group["group"], "note": group.get("note", ""), "items": items})
    return groups


def meta_url(stype, spec):
    if stype == "ecb":
        flow, key = spec["key"].split("/", 1)
        return f"https://data.ecb.europa.eu/data/datasets/{flow}/{flow}.{key}"
    if stype == "fred":
        return f"https://fred.stlouisfed.org/series/{spec['id']}"
    if stype == "treasury":
        return "https://home.treasury.gov/"
    if stype == "frankfurter":
        return "https://frankfurter.dev/"
    return ""


def status_row(name, kind, url, ok, detail, now):
    return {"name": name, "kind": kind, "url": url, "ok": ok, "detail": detail, "checked_at": now.isoformat()}


# ---------------------------------------------------------------------------
# Notizie
# ---------------------------------------------------------------------------
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
STOP = set("""il lo la i gli le un una uno di da del della dei delle degli al alla ai alle in con su per tra fra
e ed o a che non piu più come dopo sono è the a an of to in on for and or with by at from is are as its it
""".split())


def clean_text(s: str, limit: int | None = None) -> str:
    s = WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", s or ""))).strip()
    if limit and len(s) > limit:
        cut = s[:limit].rsplit(" ", 1)[0]
        s = cut.rstrip(",;:.") + "…"
    return s


def norm_tokens(title: str) -> set[str]:
    t = unicodedata.normalize("NFKD", title.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2 and w not in STOP}


def similar(a: set, b: set) -> bool:
    if not a or not b:
        return False
    inter = len(a & b)
    return inter / len(a | b) >= 0.6 or (inter >= 5 and inter / min(len(a), len(b)) >= 0.85)


def build_news(cfg, f: Fetcher, now: dt.datetime, status: list):
    st = cfg["settings"]
    default_age = st.get("news_max_age_hours", 48)
    kw = {cat: re.compile(rx, re.I) for cat, rx in (cfg.get("category_keywords") or {}).items()}
    items = []
    for feed in cfg["news_feeds"]:
        name = feed["name"]
        try:
            r = f.get(feed["url"])
            parsed = feedparser.parse(r.content)
            if not parsed.entries:
                raise SourceError("feed vuoto o non valido")
            max_age = dt.timedelta(hours=feed.get("max_age_hours", default_age))
            kept = skipped_link = skipped_old = 0
            newest = None
            for e in parsed.entries:
                link = (e.get("link") or "").strip()
                if not link.lower().startswith("https://"):
                    skipped_link += 1
                    continue
                tt = e.get("published_parsed") or e.get("updated_parsed")
                if not tt:
                    skipped_old += 1
                    continue
                when = dt.datetime.fromtimestamp(calendar.timegm(tt), UTC)
                newest = max(newest or when, when)
                if when > now + dt.timedelta(hours=1) or now - when > max_age:
                    skipped_old += 1
                    continue
                title = clean_text(e.get("title"), 300)
                if not title:
                    continue
                summary = ""
                if feed.get("summary", True):
                    summary = clean_text(e.get("summary") or e.get("description") or "", 220)
                    if summary and norm_tokens(summary) <= norm_tokens(title):
                        summary = ""
                cats = [feed["category"]]
                cats += [c for c, rx in kw.items() if c not in cats and rx.search(title)]
                items.append({
                    "title": title, "link": link, "source": name, "date": when.isoformat(),
                    "summary": summary, "categories": cats, "paywall": bool(feed.get("paywall")),
                })
                kept += 1
            if kept == 0 and newest and now - newest > max_age:
                raise SourceError(f"feed non aggiornato: notizia più recente del {newest.date().isoformat()}")
            detail = f"{kept} notizie nella finestra"
            if skipped_link:
                detail += f", {skipped_link} scartate (link non https)"
            status.append(status_row(name, "Notizie", feed["url"], True, detail, now))
        except Exception as exc:
            msg = exc.args[0] if isinstance(exc, SourceError) else short_error(exc)
            status.append(status_row(name, "Notizie", feed["url"], False, msg, now))

    items.sort(key=lambda x: x["date"], reverse=True)
    out: list[dict] = []
    toks: list[set] = []
    for it in items:
        tk = norm_tokens(it["title"])
        dup = next((i for i, t in enumerate(toks) if similar(tk, t)), None)
        if dup is not None:
            also = out[dup].setdefault("also", [])
            if it["source"] != out[dup]["source"] and it["source"] not in also:
                also.append(it["source"])
            for c in it["categories"]:
                if c not in out[dup]["categories"]:
                    out[dup]["categories"].append(c)
            continue
        out.append(it)
        toks.append(tk)
    return out[: st.get("news_max_items", 300)]


# ---------------------------------------------------------------------------
# Video: ultimo caricamento via oEmbed (API pubblica di YouTube, nessuna chiave)
# ---------------------------------------------------------------------------
VIDEO_ID_RE = re.compile(r"^https://i\.ytimg\.com/vi/([A-Za-z0-9_-]{11})/")
CHANNEL_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")


def build_videos(cfg, f: Fetcher, now: dt.datetime, status: list):
    out = []
    for ch in cfg.get("youtube_channels", []):
        cid = ch["id"]
        if not CHANNEL_RE.match(cid):
            status.append(status_row(ch["name"], "Video", "", False, "ID canale non valido", now))
            continue
        v = {"name": ch["name"], "channel_id": cid, "video_id": None, "video_title": "", "embeddable": None}
        uploads = f"https://www.youtube.com/playlist?list=UU{cid[2:]}"
        try:
            r = f.get(f"https://www.youtube.com/oembed?url={quote(uploads, safe='')}&format=json")
            m = VIDEO_ID_RE.match(r.json().get("thumbnail_url", ""))
            if not m:
                raise SourceError("ultimo video non individuato")
            v["video_id"] = m.group(1)
            try:
                watch = f"https://www.youtube.com/watch?v={v['video_id']}"
                rv = f.get(f"https://www.youtube.com/oembed?url={quote(watch, safe='')}&format=json", attempts=1)
                v["video_title"] = clean_text(rv.json().get("title", ""), 200)
                v["embeddable"] = True
            except SourceError as exc:
                # oEmbed risponde 401/403 quando l'editore vieta l'incorporamento
                v["embeddable"] = False if re.search(r"HTTP 40[13]", str(exc)) else None
            status.append(status_row(f"YouTube – {ch['name']}", "Video", f"https://www.youtube.com/channel/{cid}",
                                     True, "ultimo video individuato" + ("" if v["embeddable"] is not False
                                                                         else " (incorporamento vietato dall'editore)"), now))
        except Exception as exc:
            msg = exc.args[0] if isinstance(exc, SourceError) else short_error(exc)
            status.append(status_row(f"YouTube – {ch['name']}", "Video", f"https://www.youtube.com/channel/{cid}", False, msg, now))
        out.append(v)
    return out


# ---------------------------------------------------------------------------
# Pagina
# ---------------------------------------------------------------------------
def load_previous() -> dict:
    try:
        m = DATA_TAG_RE.search(OUT_PATH.read_text(encoding="utf-8"))
        return json.loads(m.group(1)) if m else {}
    except (OSError, ValueError):
        return {}


def json_for_html(data) -> str:
    s = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # impedisce che un testo dei feed chiuda il blocco <script>
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026") \
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def sha256_b64(s: str) -> str:
    return base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()


def load_glossary() -> list:
    path = ROOT / "glossario_eventi.yaml"
    try:
        rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError) as exc:
        print(f"  glossario non letto: {exc}", file=sys.stderr)
        return []
    return [{"nome": str(r.get("nome", "")), "chiavi": [str(k).lower() for k in r.get("chiavi", [])],
             "descrizione": " ".join(str(r.get("descrizione", "")).split())}
            for r in rows if isinstance(r, dict) and r.get("nome")]


def safe_links(rows):
    return [r for r in rows if str(r.get("url", "")).startswith("https://")]


def render(data: dict, title: str) -> str:
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    csp = "; ".join([
        "default-src 'none'",
        f"script-src 'sha256-{sha256_b64(js)}' https://s3.tradingview.com",
        "style-src 'unsafe-inline'",
        "img-src 'self' data: https://i.ytimg.com",
        "frame-src https://www.youtube-nocookie.com https://www.tradingview-widget.com https://s.tradingview.com",
        "connect-src 'self'",
        "font-src 'none'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
    ])
    tpl = (ROOT / "assets" / "template.html").read_text(encoding="utf-8")
    return (tpl.replace("__CSP__", html.escape(csp, quote=True))
               .replace("__TITLE__", html.escape(title))
               .replace("__CSS__", css)
               .replace("__JS__", js)
               .replace("__DATA__", json_for_html(data)))  # per ultimo: i testi dei feed non vengono più toccati


# ---------------------------------------------------------------------------
# Watchlist e avvisi
# ---------------------------------------------------------------------------
def word_regex(word: str) -> re.Pattern:
    flags = 0 if any(c.isupper() for c in word) else re.I
    return re.compile(r"(?<![\w])" + re.escape(word) + r"(?![\w])", flags)


def tag_watchlist(news: list, watchlist: list) -> None:
    rules = [(w["d"], [word_regex(p) for p in w.get("parole", []) if p]) for w in watchlist]
    for n in news:
        hits = [name for name, rxs in rules if any(rx.search(n["title"]) for rx in rxs)]
        if hits:
            n["watch"] = hits


STATE_PATH = ROOT / ".stato_avvisi.json"


def notify(title: str, body: str) -> None:
    import subprocess
    # testo passato come argomenti, non dentro lo script AppleScript: nessuna possibilità di iniezione
    subprocess.run(["osascript", "-e", "on run argv", "-e",
                    "display notification (item 2 of argv) with title (item 1 of argv)", "-e", "end run",
                    title[:120], body[:240]], check=False, timeout=15, capture_output=True)


def run_alerts(cfg: dict, data: dict) -> int:
    conf = cfg.get("avvisi") or {}
    if not conf.get("attivi") or sys.platform != "darwin" or os.environ.get("CI"):
        return 0
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = None
    first_run = state is None
    state = state or {"visti": [], "soglie": {}}
    seen = set(state.get("visti", []))
    words = list(conf.get("parole", [])) + [p for w in cfg.get("watchlist", []) for p in w.get("parole", [])]
    rxs = [word_regex(w) for w in words if w]
    sources = set(conf.get("fonti", []))
    alerts = []
    for n in data.get("news", []):
        if n["link"] in seen:
            continue
        seen.add(n["link"])
        if n["source"] in sources or n.get("watch") or any(rx.search(n["title"]) for rx in rxs):
            alerts.append((("★ " + ", ".join(n["watch"]) + " · " if n.get("watch") else "") + n["source"], n["title"]))
    items = {i["id"]: i for g in data.get("markets", []) for i in g.get("items", [])}
    for rule in conf.get("soglie", []):
        it = items.get(rule.get("id"))
        if not it or it.get("value") is None:
            continue
        v, key = it["value"], f"{rule.get('id')}:{it.get('date')}"
        hit = ("sopra" in rule and v > rule["sopra"]) or ("sotto" in rule and v < rule["sotto"])
        if hit and key not in state["soglie"]:
            soglia = f"sopra {rule['sopra']}" if "sopra" in rule else f"sotto {rule['sotto']}"
            alerts.append((f"Soglia: {it['name']}", f"{it['name']} = {v} {it.get('unit', '')} ({soglia}), dato del {it.get('date')}"))
            state["soglie"][key] = data["generated_at"]
    state["visti"] = list(seen)[-3000:]
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    if first_run:
        return 0  # al primo avvio si memorizza solo cosa c'è già, senza notifiche a raffica
    limit = int(conf.get("max_per_aggiornamento", 5))
    for title, body in alerts[:limit]:
        notify("Cruscotto · " + title, body)
    if len(alerts) > limit:
        notify("Cruscotto", f"Altri {len(alerts) - limit} avvisi: apri la dashboard.")
    return len(alerts)


# ---------------------------------------------------------------------------
# Report del giorno: sintesi con un modello locale (Ollama)
# ---------------------------------------------------------------------------
REPORT_SYSTEM = """Sei un analista macro e di mercato italiano. Scrivi il report del mattino per un consulente finanziario:
un'analisi unica e ragionata, non un elenco di notizie. Hai a disposizione un blocco DATI (valori ufficiali) e
notizie numerate [n] (titolo e breve sommario).
Come scrivere:
- Collega le notizie tra loro: cause, contesto, cosa significano per mercati, tassi, valute, materie prime,
  banche e assicurazioni, risparmio e portafogli. Esprimi valutazioni e giudizi motivati.
- Usa i dati: cita livelli e variazioni presenti nel blocco DATI o nelle notizie.
- I fatti e i numeri devono venire SOLO dai dati e dalle notizie forniti: non inventare valori, date, nomi o eventi
  e non attribuire un dato a un paese o a un'azienda diversi da quelli della fonte.
- Dopo ogni frase che riporta un fatto preso da una notizia metti il suo numero, es. [4] o [2][7]. Per i valori
  del blocco DATI non mettere riferimenti. Le frasi di sola valutazione possono non avere riferimento.
- Ogni "testo" è un paragrafo di prosa (stringa), mai un elenco. Nella sezione "Aziende in watchlist" racconta
  cosa dicono le notizie sulle aziende segnate [watchlist].
- Italiano chiaro e professionale, paragrafi di 3-6 frasi, niente elenchi puntati, niente ripetizioni.
Rispondi SOLO con JSON:
{"titolo": "titolo del report (max 12 parole)",
 "sintesi": "paragrafo iniziale con il quadro della giornata",
 "sezioni": [{"titolo": "...", "testo": "..."}],
 "da_monitorare": ["3-5 punti di attenzione per i prossimi giorni, una frase ciascuno"]}
Sezioni, nell'ordine e solo se c'è materiale: "Mercati azionari e materie prime", "Tassi, spread e banche centrali",
"Italia", "Scenario internazionale", "Banche, assicurazioni e risparmio", "Aziende in watchlist", "Valutazione"."""

NUM_RE = re.compile(r"\d+(?:[.,]\d+)*")
FIRST_PERSON_RE = re.compile(r"^[‘'\"«]?(I[’']m|I am|I |My |We[’']re|We |Our |Some people)", re.I)


def _num_forms(s: str) -> set:
    out = set()
    for m in NUM_RE.findall(s):
        out.add(m.replace(".", "").replace(",", ""))
    return out


# parole che in italiano possono avere la maiuscola senza essere nomi propri della notizia
COMMON_CAPS = set("""il lo la i gli le un una uno in nel nella negli nelle per con da dal dalla dei delle degli del
e ed o ma se che non piu più anche oggi ieri domani dopo mentre secondo stato stati paese paesi governo borsa borse
pil inflazione tassi tasso banca banche banca centrale mercati mercato titoli euro dollaro area zona eurozona europa
europea europeo italia italiano italiana usa stati uniti cina regno unito francia germania giappone""".split())
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ][\w'’&.-]*")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def _check_sentence(frase: str, item: dict) -> str | None:
    """Accetta la frase solo se numeri e nomi propri che contiene compaiono nella notizia a cui è legata."""
    frase = clean_text(str(frase), 400)
    if not frase:
        return None
    source = item["title"] + " " + item.get("summary", "")
    allowed = _num_forms(source)
    for m in NUM_RE.findall(frase):
        if m.replace(".", "").replace(",", "") not in allowed:
            return None
    src_norm = _strip_accents(source)
    words = WORD_RE.findall(frase)
    for i, w in enumerate(words):
        if i == 0 or not w[0].isupper():
            continue
        key = _strip_accents(w.strip(".-'’"))
        if len(key) < 3 or key in COMMON_CAPS:
            continue
        if key[:5] not in src_norm:  # radice del nome: tollera plurali e piccole variazioni
            return None
    return frase


def _select_for_report(news: list, now: dt.datetime, hours: int, limit: int) -> list:
    cutoff = now - dt.timedelta(hours=hours)
    pool = [n for n in news if dt.datetime.fromisoformat(n["date"]) >= cutoff and not FIRST_PERSON_RE.match(n["title"])]

    def score(n):
        s = 6 if n.get("watch") else 0
        s += 2 * len(n.get("also", []))
        s += 4 if "Macro/Banche centrali" in n["categories"] else 0
        s += 3 if "Previdenza e assicurazioni" in n["categories"] else 0
        s += 2 if "Mercati" in n["categories"] else 0
        s += 2 if "Italia" in n["categories"] else 0
        return s
    pool.sort(key=lambda n: (score(n), n["date"]), reverse=True)
    # quote per categoria principale, per non avere solo un tipo di notizie
    quota = {"Italia": 12, "Mercati": 10, "Macro/Banche centrali": 8, "Mondo": 8, "Previdenza e assicurazioni": 5}
    used, out = {}, []
    for n in pool:
        main = n["categories"][0] if n["categories"] else "Mondo"
        if n.get("watch") or used.get(main, 0) < quota.get(main, 5):
            out.append(n)
            used[main] = used.get(main, 0) + 1
        if len(out) >= limit:
            break
    return out


def _data_block(markets: list) -> str:
    lines = []
    for g in markets or []:
        for it in g.get("items", []):
            if it.get("value") is None:
                continue
            dec = it.get("decimals") if it.get("decimals") is not None else (0 if it.get("kind") == "spread" else 2)
            unit = " p.b." if it.get("kind") in ("rate", "spread") else " %"
            chg = it.get("chg")
            chg_s = "" if chg is None else f", variazione {'+' if chg >= 0 else ''}{fmt_it(chg, 0 if unit == ' p.b.' else 2)}{unit}"
            per = "media mensile " if it.get("freq") == "M" else ""
            lines.append(f"- {it['name']}: {fmt_it(it['value'], dec)} {it.get('unit', '')} ({per}dato del {it.get('date')}{chg_s}; fonte {it.get('source')})")
    return "\n".join(lines)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?…])\s+(?=[A-ZÀ-Ý«\"“(])", str(text).strip()) if s.strip()]


def _check_free_text(text: str, source_text: str, src_norm: str, allowed_nums: set, n_items: int, seen: set) -> tuple[str, int]:
    """Tiene le frasi i cui numeri e nomi propri compaiono nei dati/notizie forniti; toglie ripetizioni e citazioni errate."""
    kept, dropped = [], 0
    if not isinstance(text, str):
        return "", 0
    text = re.sub(r"\s*\[(?:DATI|dati|Dati|fonte|\D[^\]]{0,20})\]", "", text)
    for sent in _sentences(clean_text(text, 4000)):
        sent = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if 1 <= int(m.group(1)) <= n_items else "", sent)
        body = re.sub(r"\[\d+\]", "", sent)
        key = _strip_accents(re.sub(r"\W+", " ", body)).strip()
        if not key or key in seen:
            dropped += bool(key)
            continue
        bad = any(m.replace(".", "").replace(",", "") not in allowed_nums for m in NUM_RE.findall(body))
        if not bad:
            words = WORD_RE.findall(body)
            for i, w in enumerate(words):
                if i == 0 or not w[0].isupper():
                    continue
                k = _strip_accents(w.strip(".-'’"))
                if len(k) >= 3 and k not in COMMON_CAPS and k[:5] not in src_norm:
                    bad = True
                    break
        if bad:
            dropped += 1
            continue
        seen.add(key)
        kept.append(sent)
    return " ".join(kept), dropped


def build_report(cfg: dict, news: list, markets: list, now: dt.datetime, status: list) -> dict | None:
    rc = cfg.get("report") or {}
    if not rc.get("attivo"):
        return None
    items = _select_for_report(news, now, rc.get("ore", 24), rc.get("max_notizie", 40))
    if not items:
        return None
    data_block = _data_block(markets)
    lines = []
    for i, n in enumerate(items, 1):
        extra = f" [watchlist: {', '.join(n['watch'])}]" if n.get("watch") else ""
        summ = f" — {n['summary']}" if n.get("summary") else ""
        lines.append(f"[{i}] ({n['source']}; {', '.join(n['categories'])}){extra} {n['title']}{summ}")
    user = (f"Data: {now.astimezone(ZoneInfo('Europe/Rome')):%d/%m/%Y}\n\nDATI:\n{data_block or '(nessun dato ufficiale)'}\n\n"
            "NOTIZIE:\n" + "\n".join(lines))
    url = rc.get("indirizzo", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    name = f"Report – Ollama {rc.get('modello')}"
    t0 = time.monotonic()
    try:
        r = requests.post(url, timeout=rc.get("timeout", 600), json={
            "model": rc.get("modello", "gemma3:12b"), "stream": False, "format": "json", "keep_alive": "1m",
            "options": {"temperature": 0.3, "num_ctx": 8192},
            "messages": [{"role": "system", "content": REPORT_SYSTEM}, {"role": "user", "content": user}]})
        r.raise_for_status()
        raw = json.loads(r.json()["message"]["content"])
    except Exception as exc:
        status.append(status_row(name, "Report", "", False,
                                 "risposta non valida" if isinstance(exc, ValueError) else short_error(exc), now))
        return None
    source_text = data_block + "\n" + "\n".join(n["title"] + " " + n.get("summary", "") for n in items)
    src_norm = _strip_accents(source_text)
    allowed = _num_forms(source_text) | {str(i) for i in range(1, len(items) + 1)}
    seen: set = set()
    dropped = 0

    def check(text):
        nonlocal dropped
        out, d = _check_free_text(text, source_text, src_norm, allowed, len(items), seen)
        dropped += d
        return out
    sintesi = check(raw.get("sintesi", ""))
    sezioni = []
    raw_sez = raw.get("sezioni") or []
    if isinstance(raw_sez, dict):
        raw_sez = [{"titolo": k, "testo": v} for k, v in raw_sez.items()]
    for sec in raw_sez[:8]:
        if isinstance(sec, dict):
            txt = check(sec.get("testo", ""))
            if txt:
                sezioni.append({"titolo": clean_text(str(sec.get("titolo", "")), 70), "testo": txt})
    monitor = [x for x in (check(m) for m in (raw.get("da_monitorare") or [])[:6]) if x]
    if not (sintesi or sezioni):
        status.append(status_row(name, "Report", "", False, "il modello non ha prodotto testo verificabile", now))
        return None
    status.append(status_row(name, "Report", "", True,
                             f"{len(items)} notizie e {len(data_block.splitlines())} dati forniti, {time.monotonic() - t0:.0f} s, "
                             f"{dropped} frasi scartate dai controlli", now))
    return {"tipo": "analisi", "generated_at": now.isoformat(), "modello": rc.get("modello"), "ore": rc.get("ore", 24),
            "titolo": clean_text(str(raw.get("titolo", "")), 120), "sintesi": sintesi, "sezioni": sezioni,
            "da_monitorare": monitor,
            "fonti": [{"n": i, "title": n["title"], "link": n["link"], "source": n["source"]} for i, n in enumerate(items, 1)]}


def revalidate_report(rep: dict | None) -> dict | None:
    """Riusa solo report nel formato attuale, ripulendo riferimenti non numerici e sezioni malformate."""
    if not rep or rep.get("tipo") != "analisi":
        return None
    clean = lambda s: re.sub(r"\s*\[(?:DATI|dati|Dati|fonte|\D[^\]]{0,20})\]", "", s) if isinstance(s, str) else ""
    rep = dict(rep)
    rep["sintesi"] = clean(rep.get("sintesi"))
    rep["sezioni"] = [dict(s, testo=clean(s.get("testo"))) for s in rep.get("sezioni", [])
                      if isinstance(s.get("testo"), str) and not s["testo"].lstrip().startswith("[")]
    rep["da_monitorare"] = [clean(m) for m in rep.get("da_monitorare", []) if isinstance(m, str)]
    return rep


# ---------------------------------------------------------------------------
# Brief del mattino (pagina stampabile)
# ---------------------------------------------------------------------------
def fmt_it(v: float, dec: int) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def render_brief(data: dict, cfg: dict, tz: ZoneInfo) -> str:
    e = html.escape
    now = dt.datetime.fromisoformat(data["generated_at"]).astimezone(tz)
    giorni = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
            "settembre", "ottobre", "novembre", "dicembre"]
    when = f"{giorni[now.weekday()]} {now.day} {mesi[now.month - 1]} {now.year}, ore {now:%H:%M}"

    def obs(d):
        m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$", d or "")
        if not m:
            return d or "n.d."
        return f"{m[3]}/{m[2]}/{m[1]}" if m[3] else f"{mesi[int(m[2]) - 1][:3]} {m[1]}"

    rows = []
    for g in data.get("markets", []):
        for it in g.get("items", []):
            dec = it.get("decimals") if it.get("decimals") is not None else (0 if it["kind"] == "spread" else 2)
            if it.get("value") is None:
                rows.append(f"<tr><th>{e(it['name'])}</th><td>n.d.</td><td></td><td></td><td></td></tr>")
                continue
            unit = " p.b." if it["kind"] in ("rate", "spread") else " %"
            def ch(v):
                if v is None:
                    return "n.d."
                r = round(v, 0 if unit == " p.b." else 2)
                return ("▲ +" if r > 0 else "▼ −" if r < 0 else "■ ") + fmt_it(abs(r), 0 if unit == " p.b." else 2) + unit
            rows.append(f"<tr><th>{e(it['name'])}</th><td class=n>{fmt_it(it['value'], dec)} {e(it.get('unit', ''))}</td>"
                        f"<td class=n>{ch(it.get('chg'))}</td><td class=n>{ch(it.get('ytd'))}</td>"
                        f"<td>{e(obs(it.get('date')))} · {e(it.get('source', ''))}</td></tr>")

    cutoff = dt.datetime.fromisoformat(data["generated_at"]) - dt.timedelta(hours=24)
    recent = [n for n in data.get("news", []) if dt.datetime.fromisoformat(n["date"]) >= cutoff]

    def news_li(n):
        t = dt.datetime.fromisoformat(n["date"]).astimezone(tz)
        star = f"<b>★ {e(', '.join(n['watch']))}</b> · " if n.get("watch") else ""
        return (f"<li>{star}<a href=\"{e(n['link'])}\">{e(n['title'])}</a>"
                f"<span class=src>{e(n['source'])} · {t:%d/%m %H:%M}</span></li>")

    blocks = []
    watch = [n for n in recent if n.get("watch")][:8]
    if watch:
        blocks.append("<h3>Watchlist</h3><ul>" + "".join(news_li(n) for n in watch) + "</ul>")
    for cat in data.get("categories", []):
        items = [n for n in recent if n["categories"] and n["categories"][0] == cat][:5]
        if items:
            blocks.append(f"<h3>{e(cat)}</h3><ul>" + "".join(news_li(n) for n in items) + "</ul>")

    tv = cfg.get("tradingview") or {}
    groups = []
    if cfg.get("watchlist"):
        groups.append({"name": "Watchlist", "symbols": [{"name": w["s"], "displayName": w["d"]} for w in cfg["watchlist"]]})
    for sec in tv.get("sections", []):
        if sec.get("type") == "tiles":
            groups.append({"name": sec["title"], "symbols": [{"name": x["s"], "displayName": x["d"]}
                                                              for g in sec.get("groups", []) for x in g.get("symbols", [])]})
        else:
            for tab in sec.get("tabs", []):
                groups.append({"name": tab["title"], "symbols": [{"name": x["s"], "displayName": x["d"]} for x in tab.get("symbols", [])]})
    def quote_tile(sym):
        qc = json.dumps({"symbol": sym["name"], "width": "100%", "isTransparent": True, "colorTheme": "light",
                         "locale": "it"}, ensure_ascii=False).replace("<", "\\u003c")
        return (f'<div class=q><div class=qn>{e(sym["displayName"])}</div><div class="tradingview-widget-container">'
                '<div class="tradingview-widget-container__widget"></div>'
                f'<script src="https://s3.tradingview.com/external-embedding/embed-widget-single-quote.js" async>{qc}</script>'
                '</div></div>')
    quotes_html = "".join(f'<div class=qg><h3>{e(g["name"])}</h3><div class=qgrid>' + "".join(quote_tile(s) for s in g["symbols"])
                          + "</div></div>" for g in groups)
    js = ("document.getElementById('print').addEventListener('click',function(){window.print();});"
          "window.addEventListener('beforeprint',function(){document.querySelectorAll('details').forEach(function(d){d.open=true;});});")
    csp = "; ".join(["default-src 'none'", f"script-src 'sha256-{sha256_b64(js)}' https://s3.tradingview.com",
                     "style-src 'unsafe-inline'", "frame-src https://www.tradingview-widget.com https://s.tradingview.com",
                     "img-src 'self' data:", "base-uri 'none'", "form-action 'none'", "object-src 'none'"])
    cal = tv.get("calendar") or {}
    cal_cfg = json.dumps({"colorTheme": "light", "isTransparent": True, "width": "100%", "height": 600, "locale": "it",
                          "importanceFilter": cal.get("importance", "0,1"),
                          "countryFilter": cal.get("countries", "it,eu,us")}).replace("<", "\\u003c")
    calendar = ("""<section class=cal><h2>Prossimi eventi macro</h2>
<p class=m>Eventi in arrivo a partire da adesso (TradingView, orari nel fuso del computer; il widget non permette di limitarli a oggi). Colonne: ora · paese · importanza · evento · attuale · previsione · precedente.</p>
<div class=calwrap><div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div>
<script src="https://s3.tradingview.com/external-embedding/embed-widget-events.js" async>""" + cal_cfg + "</script></div></div></section>") if cal.get("enabled") else ""
    rep = data.get("report")
    report_html = ""
    if rep and rep.get("tipo") == "analisi" and (rep.get("sintesi") or rep.get("sezioni")):
        links = {f["n"]: f for f in rep.get("fonti", [])}

        def cite(txt):
            out = e(txt)
            return re.sub(r"\[(\d+)\]", lambda m: (
                f'<sup><a class=ref href="{e(links[int(m[1])]["link"])}" title="{e(links[int(m[1])]["source"] + ": " + links[int(m[1])]["title"])}">{m[1]}</a></sup>'
                if int(m[1]) in links else ""), out)
        used = sorted({int(x) for txt in [rep.get("sintesi", "")] + [s["testo"] for s in rep.get("sezioni", [])] + rep.get("da_monitorare", [])
                       for x in re.findall(r"\[(\d+)\]", txt) if int(x) in links})
        gen = dt.datetime.fromisoformat(rep["generated_at"]).astimezone(tz)
        report_html = ('<section class=report><h2>' + e(rep.get("titolo") or "Il punto del giorno") + '</h2>'
                       f'<p class=m>Report automatico sulle notizie delle ultime {rep.get("ore", 24)} ore e sui dati ufficiali, '
                       f'scritto sul tuo Mac dal modello {e(str(rep.get("modello")))} alle {gen:%H:%M}. I numeri in apice portano alla fonte.</p>'
                       + (f'<p class=lead>{cite(rep["sintesi"])}</p>' if rep.get("sintesi") else "")
                       + "".join(f"<h3>{e(s['titolo'])}</h3><p>{cite(s['testo'])}</p>" for s in rep.get("sezioni", []))
                       + ("<h3>Da monitorare</h3><ul class=keys>" + "".join(f"<li>{cite(m)}</li>" for m in rep["da_monitorare"]) + "</ul>"
                          if rep.get("da_monitorare") else "")
                       + ("<details class=refs><summary>Fonti</summary><ol>" + "".join(
                           f'<li value="{n}"><a href="{e(links[n]["link"])}">{e(links[n]["title"])}</a> <span class=src>{e(links[n]["source"])}</span></li>'
                           for n in used) + "</ol></details>" if used else "")
                       + "</section>")
    # l'elenco completo delle notizie compare solo se il report non è disponibile (es. Ollama spento)
    news_html = "" if report_html else (
        "<section><h2>Notizie delle ultime 24 ore</h2><p class=m>Report automatico non disponibile: elenco delle notizie.</p>"
        + ("".join(blocks) or "<p>Nessuna notizia.</p>") + "</section>")
    body = f"""
<header><div><h1>Brief del mattino</h1><p>{e(when)} · ora di Roma</p></div>
<div class=noprint><button id=print type=button>Stampa / salva PDF</button> <a href="index.html">← Dashboard</a></div></header>
{report_html}
<section><h2>Quotazioni</h2><p class=m>Valori forniti da TradingView al momento dell'apertura della pagina (possono essere in ritardo; «CFD» = contratto che replica lo strumento).</p>
{quotes_html}</section>
{calendar}
{news_html}
<footer>Generato automaticamente da fonti pubbliche il {e(when)}. Solo a scopo informativo.</footer>"""
    tpl = (ROOT / "assets" / "brief.html").read_text(encoding="utf-8")
    return tpl.replace("__CSP__", html.escape(csp, quote=True)).replace("__JS__", js).replace("__BODY__", body)


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    news_only = "--solo-notizie" in sys.argv
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    st = cfg["settings"]
    tz = ZoneInfo(st.get("timezone", "Europe/Rome"))
    now = dt.datetime.now(UTC).replace(microsecond=0)
    if news_only and not 6 <= now.astimezone(tz).hour < 23:
        print("Fuori orario (06-23): aggiornamento notizie saltato.")
        return 0
    f = Fetcher(st)
    prev = load_previous()
    prev_items = {i["id"]: i for g in prev.get("markets", []) for i in g.get("items", [])}
    prev_ok = {s["name"]: s.get("last_ok") for s in prev.get("status", [])}

    status: list[dict] = []
    sections = {}
    jobs = [("news", lambda: build_news(cfg, f, now, status)),
            ("videos", lambda: build_videos(cfg, f, now, status))]
    if news_only and prev.get("markets"):
        sections["markets"] = prev["markets"]  # i dati ufficiali restano quelli dell'ultimo aggiornamento completo
        status.extend(s for s in prev.get("status", []) if s.get("kind") == "Mercati")
        markets_at = prev.get("markets_at", prev.get("generated_at"))
    else:
        jobs.insert(0, ("markets", lambda: build_markets(cfg, f, prev_items, now, status)))
        markets_at = now.isoformat()
    for key, fn in jobs:
        try:
            sections[key] = fn()
        except Exception:  # un errore di programmazione in una sezione non blocca le altre
            traceback.print_exc()
            sections[key] = prev.get(key, [])
            status.append(status_row(f"Sezione {key}", "Interno", "", False, "errore interno, mostrati i dati precedenti", now))

    for s in status:
        if s.get("kind") == "Mercati" and news_only:
            continue
        s["last_ok"] = s["checked_at"] if s["ok"] else prev_ok.get(s["name"])

    watchlist = [w for w in (cfg.get("watchlist") or []) if w.get("s")]
    tag_watchlist(sections["news"], watchlist)
    report = revalidate_report(prev.get("report"))
    every = (cfg.get("report") or {}).get("rigenera_ogni_ore", 3)
    stale = not report or now - dt.datetime.fromisoformat(report["generated_at"]) >= dt.timedelta(hours=every)
    if not news_only or stale or "--report" in sys.argv:
        try:
            report = build_report(cfg, sections["news"], sections.get("markets", []), now, status) or report
        except Exception:
            traceback.print_exc()
    tv = dict(cfg.get("tradingview") or {"enabled": False})
    if watchlist:
        tv["sections"] = [{"title": "La mia watchlist", "type": "tiles", "watchlist": True,
                           "groups": [{"name": "", "symbols": [{"s": w["s"], "d": w["d"]} for w in watchlist]}]}] + list(tv.get("sections", []))

    data = {
        "generated_at": now.isoformat(),
        "markets_at": markets_at,
        "timezone": str(tz),
        "markets": sections["markets"],
        "tradingview": tv,
        "news": sections["news"],
        "news_window_hours": st.get("news_max_age_hours", 48),
        "categories": ["Italia", "Mercati", "Macro/Banche centrali", "Mondo", "Previdenza e assicurazioni"],
        "videos": sections["videos"],
        "quick_links": safe_links(cfg.get("quick_links", [])),
        "calendar_links": safe_links(cfg.get("calendar_links", [])),
        "discarded": cfg.get("discarded_sources", []),
        "glossary": load_glossary(),
        "report": report,
        "status": status,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(OUT_PATH, render(data, st.get("title", "Cruscotto finanziario")))
    try:
        write_atomic(OUT_PATH.parent / "brief.html", render_brief(data, cfg, tz))
    except Exception:
        traceback.print_exc()
    write_atomic(OUT_PATH.parent / "version.json", json.dumps({"generated_at": data["generated_at"]}))
    try:
        n_alerts = run_alerts(cfg, data)
    except Exception:
        traceback.print_exc()
        n_alerts = 0

    ok = sum(1 for s in status if s["ok"])
    print(f"Scritto {OUT_PATH.relative_to(ROOT)}{' (solo notizie)' if news_only else ''}: {ok}/{len(status)} fonti ok, "
          f"{len(data['news'])} notizie, {len(data['videos'])} canali video, {n_alerts} avvisi.")
    for s in status:
        if not s["ok"]:
            print(f"  ERRORE {s['name']}: {s['detail']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
