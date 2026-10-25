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


EQUITYLAB_ORIGIN = "http://127.0.0.1:8000"  # Equity Lab locale: il pannello lo interroga solo da 127.0.0.1:8799
SYNC_WATCHLIST = ROOT / "sync" / "equitylab_watchlist.json"


def equitylab_watchlist(own: list) -> list:
    """Titoli aggiunti alla watchlist in Equity Lab (scritti da Equity Lab in sync/), senza duplicati."""
    try:
        rows = json.loads(SYNC_WATCHLIST.read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        return []
    have = {str(w.get("s", "")).upper() for w in own}
    out = []
    for r in rows:
        s = str(r.get("s", "")).upper()
        if re.match(r"^[A-Z]+:[A-Z0-9.\-]+$|^[A-Z0-9.\-]+$", s) and s not in have:
            out.append({"s": s, "d": clean_text(str(r.get("d") or s), 80),
                        "parole": [clean_text(str(x), 60) for x in (r.get("parole") or [])][:3], "da_equitylab": True})
            have.add(s)
    return out


def render(data: dict, title: str) -> str:
    js = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    csp = "; ".join([
        "default-src 'none'",
        f"script-src 'sha256-{sha256_b64(js)}' https://s3.tradingview.com",
        "style-src 'unsafe-inline'",
        "img-src 'self' data: https://i.ytimg.com",
        "frame-src https://www.youtube-nocookie.com https://www.tradingview-widget.com https://s.tradingview.com",
        f"connect-src 'self' {EQUITYLAB_ORIGIN}",
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


WATCHLIST_PATH = ROOT / "watchlist.yaml"
SYMBOL_RE = re.compile(r"^[A-Z0-9_]{1,20}:[A-Z0-9._!\-]{1,30}$")


def normalize_watch_item(r: dict) -> dict | None:
    """Voce di watchlist valida: simbolo TradingView BORSA:SIMBOLO, nome, fino a 5 parole per le notizie."""
    if not isinstance(r, dict):
        return None
    s = str(r.get("s", "")).strip().upper()
    if not SYMBOL_RE.match(s):
        return None
    d = clean_text(str(r.get("d") or s), 60) or s
    parole = r.get("parole") or []
    if isinstance(parole, str):
        parole = parole.split(",")
    parole = [clean_text(str(p), 40) for p in parole if str(p).strip()][:5]
    return {"s": s, "d": d, "parole": parole}


def own_watchlist(cfg: dict) -> list:
    """La tua watchlist: watchlist.yaml (modificabile dalla dashboard) o, se manca, quella in config.yaml."""
    rows = cfg.get("watchlist") or []
    if WATCHLIST_PATH.exists():
        try:
            rows = yaml.safe_load(WATCHLIST_PATH.read_text(encoding="utf-8")) or []
        except (OSError, yaml.YAMLError) as exc:
            print(f"  watchlist.yaml non leggibile, uso config.yaml: {exc}", file=sys.stderr)
    out, seen = [], set()
    for r in rows if isinstance(rows, list) else []:
        w = normalize_watch_item(r)
        if w and w["s"] not in seen:
            out.append(w)
            seen.add(w["s"])
    return out


def save_watchlist(items: list) -> list:
    clean = []
    for r in items[:60]:
        w = normalize_watch_item(r)
        if w and w["s"] not in {x["s"] for x in clean}:
            clean.append(w)
    head = ("# La tua watchlist, modificabile dalla dashboard (pulsante «Modifica watchlist» sulla versione del Mac).\n"
            "# s: simbolo TradingView BORSA:SIMBOLO · d: nome mostrato · parole: per riconoscere il titolo nelle notizie\n")
    write_atomic(WATCHLIST_PATH, head + yaml.safe_dump(clean, allow_unicode=True, sort_keys=False))
    return clean


def apply_watchlist(cfg: dict, news: list) -> tuple[list, dict]:
    """Calcola la watchlist (tua + Equity Lab), segna le notizie e prepara le sezioni TradingView."""
    own = own_watchlist(cfg)
    cfg["watchlist"] = own
    watchlist = own + equitylab_watchlist(own)
    for n in news:
        n.pop("watch", None)
    tag_watchlist(news, watchlist)
    tv = dict(cfg.get("tradingview") or {"enabled": False})
    if watchlist:
        tv["sections"] = [{"title": "La mia watchlist", "type": "tiles", "watchlist": True,
                           "groups": [{"name": "", "symbols": [{"s": w["s"], "d": w["d"]} for w in watchlist]}]}] + list(tv.get("sections", []))
    return watchlist, tv


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
STYLE = """Scrivi in italiano come __FIRMA__, consulente finanziario, nella sua newsletter "InfoMercati" per i clienti
(privati e famiglie). Stile giornalistico e personale, concreto: fatti, numeri, nomi, conseguenze per chi ha dei
risparmi. Spiega in poche parole i termini tecnici. Vietate le formule vuote ("monitorare attentamente",
"contesto complesso", "navigare", "è fondamentale diversificare"). Non citare "il modello", "le notizie fornite" o
le testate. Usa SOLO i fatti e i numeri delle notizie ricevute: niente valori, nomi, eventi o previsioni inventati,
nessun dato attribuito a un paese o a un'azienda diversi da quelli della fonte. Dopo ogni frase con un fatto metti
il numero della notizia, es. [4] o [2][7]. __MOMENTO__ Rispondi SOLO con JSON."""

SELECT_SYSTEM = """Sei il caporedattore di "InfoMercati", newsletter quotidiana di un consulente finanziario italiano per
i suoi clienti. Ricevi notizie numerate con un punteggio di rilevanza e il numero di testate che le riprendono.
Scegli ciò che conta davvero per chi ha risparmi investiti in Italia (mercati, tassi e spread, banche centrali,
grandi operazioni societarie, banche e assicurazioni, conti pubblici, fisco, pensioni). Ignora cronaca,
curiosità, lifestyle e piccole notizie aziendali estere. Non usare la stessa notizia in due posti.
Rispondi SOLO con JSON:
{"principale": n, "correlate": [n, ...],
 "approfondimenti": [{"n": n, "correlate": [n, ...]}],
 "numero": n,
 "in_breve": [n, ...]}
"principale": la notizia più importante; "correlate": fino a 3 notizie sullo stesso argomento.
"approfondimenti": 1 o 2 temi diversi dalla principale. "numero": una notizia che contiene un dato numerico
significativo, diversa dalle precedenti. "in_breve": 3 o 4 altre notizie utili."""

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
lei loro voi vostro vostra vostri vostre ritengo credo penso borsa btp bund spread fed bce
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


KEY_TOPICS_RE = re.compile(r"\b(spread|btp|bund|bce|fed|lagarde|powell|tass[io]|rendiment|inflazion|pil|borsa|borse|ftse|"
                           r"piazza affari|wall street|petrolio|brent|gas|oro|euro|dollaro|manovra|legge di bilancio|fisco|tasse|"
                           r"irpef|pension|previdenz|assicura|banche|banca|opa|ops|acquisizion|fusion|utili|trimestral|rating|"
                           r"moody|s&p|fitch|debito|deficit|dazi|recessione|occupazione|disoccupazione)", re.I)


def _report_score(n: dict) -> int:
    """Rilevanza per un risparmiatore italiano: watchlist, copertura su più testate, temi chiave, fonti istituzionali."""
    s = 6 if n.get("watch") else 0
    s += 3 * len(n.get("also", []))
    s += 4 if "Macro/Banche centrali" in n["categories"] else 0
    s += 3 if "Previdenza e assicurazioni" in n["categories"] else 0
    s += 2 if "Mercati" in n["categories"] else 0
    s += 2 if "Italia" in n["categories"] else 0
    s += 3 if KEY_TOPICS_RE.search(n["title"]) else 0
    s += 2 if n["source"].startswith(("BCE", "Fed", "IVASS")) else 0
    return s


def _select_for_report(news: list, now: dt.datetime, hours: int, limit: int) -> list:
    cutoff = now - dt.timedelta(hours=hours)
    pool = [n for n in news if dt.datetime.fromisoformat(n["date"]) >= cutoff and not FIRST_PERSON_RE.match(n["title"])]

    score = _report_score
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
            if it.get("value") is None or it.get("freq") == "M":
                continue  # le medie mensili verrebbero scambiate per valori attuali
            try:
                if (dt.date.today() - dt.date.fromisoformat(it.get("date", ""))).days > 5:
                    continue
            except ValueError:
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
    # "[1, 2]" o "[1; 2]" -> "[1][2]"
    text = re.sub(r"\[(\d+(?:\s*[,;]\s*\d+)+)\]", lambda m: "".join(f"[{x}]" for x in re.findall(r"\d+", m.group(1))), text)
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


def _ollama_json(rc: dict, system: str, user: str, temperature: float = 0.4) -> dict:
    url = rc.get("indirizzo", "http://127.0.0.1:11434").rstrip("/") + "/api/chat"
    r = requests.post(url, timeout=rc.get("timeout", 600), json={
        "model": rc.get("modello", "gemma3:12b"), "stream": False, "format": "json", "keep_alive": "2m",
        "options": {"temperature": temperature, "num_ctx": 8192},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    r.raise_for_status()
    out = json.loads(r.json()["message"]["content"])
    if not isinstance(out, dict):
        raise ValueError("JSON non valido")
    return out


CLICHE_RE = re.compile(r"(navigare|scenario (complesso|incerto)|contesto (complesso|incerto|di incertezza)|"
                       r"monitorare (attentamente|da vicino|con attenzione|costantemente)|monitoraggio costante|le armi migliori|"
                       r"è fondamentale (rivedere|mantenere|diversificare)|prudenza e (la )?consapevolezza|"
                       r"diversificare (gli investimenti|il portafoglio) per (proteggere|mitigare)|richiede(ndo)? un'attenta|"
                       r"la volatilità dei mercati è una costante)", re.I)


def _short_title(titolo: str, limit: int = 90) -> str:
    """Accorcia un titolo troppo lungo a una parte compiuta (prima di due punti, virgola o trattino), mai con i puntini."""
    troncato = titolo.endswith("…")
    titolo = titolo.rstrip("…").strip()
    # un titolo che finisce con una preposizione o un articolo è stato tagliato a metà
    troncato = troncato or bool(re.search(r"\s(di|del|della|dei|delle|il|la|lo|le|gli|e|a|al|per|con|in|su|da|l'|dell')$", titolo, re.I))
    if len(titolo) <= limit and not troncato:
        return titolo
    for sep in (":", ",", " – ", " - ", ";"):
        head = titolo.split(sep)[0].strip()
        if 25 <= len(head) <= limit:
            return head
    return titolo[:limit].rsplit(" ", 1)[0]


def build_report(cfg: dict, news: list, markets: list, now: dt.datetime, status: list) -> dict | None:
    """InfoMercati a passaggi: scelta delle notizie, poi ogni pezzo scritto vedendo solo le sue fonti."""
    rc = cfg.get("report") or {}
    if not rc.get("attivo"):
        return None
    items = _select_for_report(news, now, rc.get("ore", 24), rc.get("max_notizie", 40))
    if len(items) < 3:
        return None
    N = len(items)
    loc = now.astimezone(ZoneInfo("Europe/Rome"))
    fase = "mattina" if loc.hour < 13 else ("pomeriggio" if loc.hour < 18 else "sera")
    momento = (f"Oggi è {loc:%d/%m/%Y}, ore {loc:%H:%M} ({fase}): "
               + ("è mattina, le notizie di ieri sono di ieri e non scrivere che la giornata si è chiusa." if fase == "mattina"
                  else "puoi parlare della giornata di oggi."))
    style = STYLE.replace("__FIRMA__", rc.get("firma") or "un consulente").replace("__MOMENTO__", momento)
    try:
        stile = (ROOT / rc.get("stile_file", "stile_alberto.md")).read_text(encoding="utf-8")
        stile = re.sub(r"^#.*$", "", stile, flags=re.M).strip()
        style += "\n\nSTILE PERSONALE DA SEGUIRE (sono indicazioni di forma, gli esempi non sono fatti):\n" + stile
    except OSError:
        pass
    name = f"Report – Ollama {rc.get('modello')}"
    t0 = time.monotonic()
    dropped = 0
    seen: set = set()

    def line(i):
        n = items[i - 1]
        summ = f" — {n['summary']}" if n.get("summary") else ""
        extra = f" [watchlist: {', '.join(n['watch'])}]" if n.get("watch") else ""
        return f"[{i}]{extra} {n['title']}{summ}"

    def check_on(text, ids):
        """Controlla il testo solo sulle notizie ids e toglie i riferimenti ad altre notizie."""
        nonlocal dropped
        src = "\n".join(items[i - 1]["title"] + " " + items[i - 1].get("summary", "") for i in ids)
        out, d = _check_free_text(text, src, _strip_accents(src), _num_forms(src) | {str(i) for i in ids}, N, seen)
        dropped += d
        out = re.sub(r"\[(\d+)\]", lambda m: m.group(0) if int(m.group(1)) in ids else "", out)
        sents = _sentences(out)
        keep = [s for s in sents if not CLICHE_RE.search(s)
                and not (fase == "mattina" and re.search(r"(giornata|seduta)[^.]{0,30}si è (chius|conclus)", s, re.I))]
        dropped += len(sents) - len(keep)
        return " ".join(keep)

    def valid(ns, exclude=()):
        out = []
        for x in ns if isinstance(ns, list) else [ns]:
            try:
                k = int(x)
            except (TypeError, ValueError):
                continue
            if 1 <= k <= N and k not in exclude and k not in out:
                out.append(k)
        return out

    try:
        # 1) scelta
        listing = "\n".join(f"[{i}] (rilevanza {_report_score(n)}; testate {1 + len(n.get('also', []))}; {', '.join(n['categories'])}) "
                            f"{n['title']}" for i, n in enumerate(items, 1))
        pick = _ollama_json(rc, SELECT_SYSTEM, "NOTIZIE:\n" + listing, 0.2)
        used: list[int] = []
        main = valid(pick.get("principale"))[:1] or [1]
        used += main
        def related(base, cands):
            """Solo notizie che condividono almeno due parole significative con la notizia di riferimento."""
            bt = norm_tokens(items[base - 1]["title"] + " " + items[base - 1].get("summary", ""))
            return [c for c in cands if len(bt & norm_tokens(items[c - 1]["title"] + " " + items[c - 1].get("summary", ""))) >= 2]
        main_rel = related(main[0], valid(pick.get("correlate"), used))[:3]
        used += main_rel
        apps = []
        for ap in (pick.get("approfondimenti") or [])[:2]:
            if isinstance(ap, dict):
                k = valid(ap.get("n"), used)[:1]
                if k:
                    rel = related(k[0], valid(ap.get("correlate"), used + k))[:2]
                    apps.append(k + rel)
                    used += k + rel
        num_n = valid(pick.get("numero"), used)[:1]
        used += num_n
        brevi = valid(pick.get("in_breve"), used)[:4]

        def write_section(ids, lunghezza):
            out = _ollama_json(rc, style, f"Notizie su questo tema:\n" + "\n".join(line(i) for i in ids)
                               + f'\n\nScrivi questo pezzo della newsletter: {lunghezza}. JSON: {{"titolo": "titolo specifico che dica cosa è successo", "testo": "..."}}'
                               + ' (paragrafi separati da \\n\\n).')
            paras = [check_on(p, ids) for p in str(out.get("testo", "")).split("\n\n")]
            testo = "\n\n".join(p for p in paras if p)
            if not testo:
                return None
            titolo = _short_title(clean_text(str(out.get("titolo", "")), 200))
            if any(len(k) >= 3 and w[0].isupper() and k not in COMMON_CAPS and not re.search(r"\b" + re.escape(k[:5]), _strip_accents(testo))
                   for i, w in enumerate(WORD_RE.findall(titolo)) if i > 0 for k in [_strip_accents(w.strip(".-'’:"))]):
                titolo = re.split(r"[:–-]", titolo)[0].strip()
            return {"titolo": titolo, "testo": testo}

        # 2) pezzi, ognuno con le sole sue fonti
        apertura = write_section(main + main_rel, "è l'apertura, la notizia più importante del giorno: 2 o 3 paragrafi su cosa è "
                                 "successo, perché conta e quali effetti può avere per chi investe o risparmia")
        approfondimenti = [s for s in (write_section(ids, "un approfondimento di un solo paragrafo da 3-5 frasi, con un taglio "
                                                     "diverso da una cronaca: spiega il perché e le conseguenze") for ids in apps) if s]
        numero = None
        if num_n:
            out = _ollama_json(rc, style, "Notizia:\n" + line(num_n[0]) + '\n\nScegli il dato numerico più significativo di questa '
                               'notizia per la rubrica "Il numero del giorno". JSON: {"valore": "il numero con unità, es. 3,5%", '
                               '"testo": "2 frasi: cosa misura e perché conta"}')
            val = clean_text(str(out.get("valore", "")), 40)
            txt = check_on(out.get("testo", ""), num_n)
            txt = " ".join(s for s in _sentences(txt) if not re.match(r"^(Il )?numero del giorno", s, re.I))
            if val and txt and NUM_RE.search(val) and all(
                    m.replace(".", "").replace(",", "") in _num_forms(items[num_n[0] - 1]["title"] + " " + items[num_n[0] - 1].get("summary", ""))
                    for m in NUM_RE.findall(val)):
                numero = {"valore": val, "testo": txt}
        in_breve = []
        if brevi:
            out = _ollama_json(rc, style, "Notizie:\n" + "\n".join(line(i) for i in brevi)
                               + '\n\nPer la rubrica "In breve" scrivi UNA frase per notizia. JSON: {"frasi": [{"n": numero, "frase": "..."}]}')
            for ent in out.get("frasi", []) if isinstance(out.get("frasi"), list) else []:
                if isinstance(ent, dict):
                    k = valid(ent.get("n"))
                    if k and k[0] in brevi:
                        x = check_on(str(ent.get("frase", "")).rstrip() + f" [{k[0]}]", k)
                        if x:
                            in_breve.append(x)
        if not apertura:
            raise ValueError("apertura vuota")
        # 3) titolo, sommario e punto di vista, a partire dall'articolo già scritto e verificato
        written = "\n\n".join([f"{apertura['titolo']}\n{apertura['testo']}"] + [f"{s['titolo']}\n{s['testo']}" for s in approfondimenti]
                              + ([f"Il numero del giorno: {numero['valore']} — {numero['testo']}"] if numero else []))
        all_ids = sorted(set(main + main_rel + [i for ids in apps for i in ids] + num_n))
        out = _ollama_json(rc, style.replace("Dopo ogni frase con un fatto metti il numero della notizia, es. [4] o [2][7].", ""),
                           "Articolo già scritto:\n" + written
                           + '\n\nScrivi: "titolo" (forte e specifico, max 12 parole, sul tema principale), "sommario" (1-2 frasi '
                             'sotto il titolo) e "punto_di_vista" (4-5 frasi in prima persona: la tua lettura concreta di cosa '
                             'significano questi fatti per i risparmi e i portafogli dei clienti, citando i fatti dell\'articolo; '
                             'niente frasi generiche). Usa solo fatti presenti nell\'articolo. JSON: {"titolo": "...", '
                             '"sommario": "...", "punto_di_vista": "..."}', 0.5)
        art_src = written
        art_norm = _strip_accents(art_src)

        def check_art(text):
            nonlocal dropped
            o, d = _check_free_text(text, art_src, art_norm, _num_forms(art_src), N, seen)
            dropped += d
            sents = _sentences(re.sub(r"\s*\[\d+\]", "", o))
            keep = [s for s in sents if not CLICHE_RE.search(s)]
            dropped += len(sents) - len(keep)
            return " ".join(keep)
        titolo = clean_text(str(out.get("titolo", "")), 140)
        if titolo and not check_art(titolo.rstrip(".") + "."):
            titolo = apertura["titolo"]
        sommario = check_art(out.get("sommario", ""))
        punto = check_art(out.get("punto_di_vista", ""))
    except Exception as exc:
        status.append(status_row(name, "Report", "", False,
                                 "risposta non valida" if isinstance(exc, ValueError) else short_error(exc), now))
        return None
    status.append(status_row(name, "Report", "", True,
                             f"{N} notizie esaminate, principale [{main[0]}], {time.monotonic() - t0:.0f} s, "
                             f"{dropped} frasi scartate dai controlli", now))
    return {"tipo": "infomercati", "generated_at": now.isoformat(), "modello": rc.get("modello"), "ore": rc.get("ore", 24),
            "titolo": titolo or apertura["titolo"], "sommario": sommario,
            "apertura": apertura, "approfondimenti": approfondimenti, "numero": numero,
            "in_breve": in_breve, "punto_di_vista": punto,
            "firma": rc.get("firma", ""), "ruolo": rc.get("ruolo", ""), "nota_legale": rc.get("nota_legale", ""),
            "fonti": [{"n": i, "title": n["title"], "link": n["link"], "source": n["source"]} for i, n in enumerate(items, 1)]}


def revalidate_report(rep: dict | None) -> dict | None:
    """Riusa solo report nel formato attuale (sistemando i titoli troncati)."""
    if not (rep and rep.get("tipo") == "infomercati" and rep.get("apertura")):
        return None
    for s in [rep["apertura"]] + rep.get("approfondimenti", []):
        s["titolo"] = _short_title(s.get("titolo", ""))
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
    if rep and rep.get("tipo") == "infomercati":
        gen = dt.datetime.fromisoformat(rep["generated_at"]).astimezone(tz)
        report_html = ('<section class=report>'
                       f'<p class=m>InfoMercati scritto sul tuo Mac dal modello {e(str(rep.get("modello")))} alle {gen:%H:%M}. '
                       'I numeri in apice portano alla fonte; la versione per i clienti è nel link «InfoMercati».</p>'
                       + infomercati_html(rep, cite_links=True) + "</section>")
    # l'elenco completo delle notizie compare solo se il report non è disponibile (es. Ollama spento)
    news_html = "" if report_html else (
        "<section><h2>Notizie delle ultime 24 ore</h2><p class=m>Report automatico non disponibile: elenco delle notizie.</p>"
        + ("".join(blocks) or "<p>Nessuna notizia.</p>") + "</section>")
    body = f"""
<header><div><h1>Brief del mattino</h1><p>{e(when)} · ora di Roma</p></div>
<div class=noprint><button id=print type=button>Stampa / salva PDF</button> <a href="infomercati.html">InfoMercati</a> <a href="index.html">← Dashboard</a></div></header>
{report_html}
<section><h2>Quotazioni</h2><p class=m>Valori forniti da TradingView al momento dell'apertura della pagina (possono essere in ritardo; «CFD» = contratto che replica lo strumento).</p>
{quotes_html}</section>
{calendar}
{news_html}
<footer>Generato automaticamente da fonti pubbliche il {e(when)}. Solo a scopo informativo.</footer>"""
    tpl = (ROOT / "assets" / "brief.html").read_text(encoding="utf-8")
    return tpl.replace("__CSP__", html.escape(csp, quote=True)).replace("__JS__", js).replace("__BODY__", body)


def infomercati_html(rep: dict, cite_links: bool) -> str:
    """Corpo dell'articolo. Con cite_links=True i riferimenti [n] diventano link in apice, altrimenti vengono tolti."""
    e = html.escape
    links = {f["n"]: f for f in rep.get("fonti", [])}

    def fmt(txt):
        out = e(txt or "")
        if not cite_links:
            return re.sub(r"\s*\[\d+\]", "", out)
        return re.sub(r"\[(\d+)\]", lambda m: (
            f'<sup><a class=ref href="{e(links[int(m[1])]["link"])}" title="{e(links[int(m[1])]["source"] + ": " + links[int(m[1])]["title"])}">{m[1]}</a></sup>'
            if int(m[1]) in links else ""), out)

    def paras(txt):
        return "".join(f"<p>{fmt(p)}</p>" for p in (txt or "").split("\n\n") if p.strip())
    parts = [f'<h1 class=im-title>{e(rep.get("titolo") or "InfoMercati")}</h1>']
    if rep.get("sommario"):
        parts.append(f"<p class=dek>{fmt(rep['sommario'])}</p>")
    if rep.get("firma"):
        parts.append(f'<p class=byline>di {e(rep["firma"])}' + (f' · {e(rep["ruolo"])}' if rep.get("ruolo") else "") + "</p>")
    ap = rep.get("apertura")
    if ap:
        parts.append(f"<h2 class=lead-h>{e(ap['titolo'])}</h2><div class=lead>{paras(ap['testo'])}</div>")
    if rep.get("numero"):
        parts.append(f'<aside class=num><div class=num-v>{e(rep["numero"]["valore"])}</div>'
                     f'<div class=num-l>Il numero del giorno</div><p>{fmt(rep["numero"]["testo"])}</p></aside>')
    for s in rep.get("approfondimenti", []):
        parts.append(f"<h2>{e(s['titolo'])}</h2>{paras(s['testo'])}")
    if rep.get("in_breve"):
        parts.append("<h2>In breve</h2><ul class=brief>" + "".join(f"<li>{fmt(x)}</li>" for x in rep["in_breve"]) + "</ul>")
    if rep.get("punto_di_vista"):
        parts.append(f"<div class=pov><h2>Il mio punto di vista</h2><p>{fmt(rep['punto_di_vista'])}</p></div>")
    if cite_links:
        used = sorted({int(x) for x in re.findall(r"\[(\d+)\]", json.dumps(rep, ensure_ascii=False)) if int(x) in links})
        if used:
            parts.append("<details class=refs><summary>Fonti</summary><ol>" + "".join(
                f'<li value="{n}"><a href="{e(links[n]["link"])}">{e(links[n]["title"])}</a> <span class=src>{e(links[n]["source"])}</span></li>'
                for n in used) + "</ol></details>")
    return "".join(parts)


def _plain_infomercati(rep: dict, when: str) -> str:
    strip = lambda s: re.sub(r"\s*\[\d+\]", "", s or "").strip()
    out = ["INFOMERCATI – " + when, "", rep.get("titolo", ""), ""]
    if rep.get("sommario"):
        out += [strip(rep["sommario"]), ""]
    if rep.get("firma"):
        out += ["di " + rep["firma"] + (" · " + rep["ruolo"] if rep.get("ruolo") else ""), ""]
    if rep.get("apertura"):
        out += [rep["apertura"]["titolo"].upper(), strip(rep["apertura"]["testo"]), ""]
    if rep.get("numero"):
        out += ["IL NUMERO DEL GIORNO: " + rep["numero"]["valore"], strip(rep["numero"]["testo"]), ""]
    for s in rep.get("approfondimenti", []):
        out += [s["titolo"].upper(), strip(s["testo"]), ""]
    if rep.get("in_breve"):
        out += ["IN BREVE"] + ["– " + strip(x) for x in rep["in_breve"]] + [""]
    if rep.get("punto_di_vista"):
        out += ["IL MIO PUNTO DI VISTA", strip(rep["punto_di_vista"]), ""]
    return "\n".join(out)


EDITS_PATH = ROOT / "modifiche" / "infomercati.json"
ALLOWED_TAGS = {"p", "h1", "h2", "h3", "ul", "ol", "li", "strong", "b", "em", "i", "u", "br", "aside", "div", "span"}
ALLOWED_CLASSES = {"im-title", "dek", "byline", "lead-h", "lead", "num", "num-v", "num-l", "brief", "pov"}


def sanitize_article(raw: str) -> str:
    """Tiene solo testo e tag di formattazione semplici (niente script, link, stili o attributi)."""
    from html.parser import HTMLParser

    class S(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.out, self.skip, self.stack = [], 0, []

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "iframe", "object", "svg", "math", "template"):
                self.skip += 1
                return
            if self.skip or tag not in ALLOWED_TAGS:
                return
            if tag == "br":
                self.out.append("<br>")
                return
            cls = " ".join(c for c in (dict(attrs).get("class") or "").split() if c in ALLOWED_CLASSES)
            self.out.append(f'<{tag} class="{cls}">' if cls else f"<{tag}>")
            self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in ("script", "style", "iframe", "object", "svg", "math", "template"):
                self.skip = max(0, self.skip - 1)
                return
            if self.skip or tag not in ALLOWED_TAGS or tag == "br" or tag not in self.stack:
                return
            while self.stack:
                t = self.stack.pop()
                self.out.append(f"</{t}>")
                if t == tag:
                    break

        def handle_data(self, data):
            if not self.skip:
                self.out.append(html.escape(data, quote=False))
    s = S()
    s.feed(raw or "")
    s.close()
    s.out += [f"</{t}>" for t in reversed(s.stack)]
    return "".join(s.out)


def load_edits(rep: dict) -> dict | None:
    """Modifiche salvate a mano per questo InfoMercati (stesso generated_at), già ripulite."""
    try:
        ed = json.loads(EDITS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not rep or ed.get("generated_at") != rep.get("generated_at") or not ed.get("html"):
        return None
    return {"html": sanitize_article(ed["html"]), "saved_at": ed.get("saved_at")}


def render_infomercati(data: dict, tz: ZoneInfo) -> str:
    """Pagina InfoMercati per i clienti: articolo senza riferimenti numerici, firma e nota in calce."""
    e = html.escape
    rep = data.get("report") or {}
    now = dt.datetime.fromisoformat(rep.get("generated_at") or data["generated_at"]).astimezone(tz)
    mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
            "settembre", "ottobre", "novembre", "dicembre"]
    giorni = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
    when = f"{giorni[now.weekday()]} {now.day} {mesi[now.month - 1]} {now.year}"
    ok = rep.get("tipo") == "infomercati"
    links = {f["n"]: f for f in rep.get("fonti", [])}
    used = sorted({int(x) for x in re.findall(r"\[(\d+)\]", json.dumps(rep, ensure_ascii=False)) if int(x) in links})
    testate = sorted({re.sub(r"\s*[–-].*$", "", links[n]["source"]) for n in used})
    edits = load_edits(rep) if ok else None
    body = (edits["html"] if edits else infomercati_html(rep, cite_links=False)) if ok else "<p>InfoMercati di oggi non è ancora disponibile.</p>"
    body = f'<div id=im-body data-gen="{e(rep.get("generated_at", ""))}">{body}</div>'
    foot = []
    if ok and testate:
        foot.append("Fonti: " + ", ".join(testate) + ".")
    if ok and rep.get("nota_legale"):
        foot.append(rep["nota_legale"])
    body += ("<footer>" + "".join(f"<p>{e(x)}</p>" for x in foot) + "</footer>") if foot else ""
    plain = (_plain_infomercati(rep, when) + "\n" + "\n".join(foot)) if ok else ""
    saved_note = ""
    if edits and edits.get("saved_at"):
        try:
            saved_note = "Modificato da te il " + dt.datetime.fromisoformat(edits["saved_at"]).astimezone(tz).strftime("%d/%m alle %H:%M")
        except ValueError:
            saved_note = "Modificato da te"
    js = """(function(){
var body=document.getElementById('im-body'),art=document.querySelector('article'),bar=document.querySelector('.bar');
var local=location.protocol==='http:'&&/^(127\\.0\\.0\\.1|localhost)$/.test(location.hostname);
var bEdit=document.getElementById('edit'),bSave=document.getElementById('save'),bCancel=document.getElementById('cancel'),
    bReset=document.getElementById('reset'),msg=document.getElementById('msg');
var original=body.innerHTML;
function say(s){msg.textContent=s;msg.hidden=!s;}
function editing(on){body.contentEditable=on?'true':'false';document.body.classList.toggle('editing',on);
  bEdit.hidden=on;bSave.hidden=!on;bCancel.hidden=!on;if(on){body.focus();}}
bEdit.addEventListener('click',function(){editing(true);
  say(local?'Modifica il testo direttamente. Cmd+B grassetto, Cmd+I corsivo. Poi Salva.':
    'Stai modificando solo questa copia (per copiarla o stamparla): per salvarla apri InfoMercati dal Mac.');});
bCancel.addEventListener('click',function(){body.innerHTML=original;editing(false);say('');});
bSave.addEventListener('click',function(){
  if(!local){editing(false);say('Modifiche tenute in questa pagina: ora puoi copiarla o stamparla.');return;}
  bSave.disabled=true;say('Salvataggio e pubblicazione in corso…');
  fetch('/api/salva-infomercati',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({generated_at:body.getAttribute('data-gen'),html:body.innerHTML})})
  .then(function(r){return r.json();}).then(function(res){bSave.disabled=false;
    if(res.ok){original=body.innerHTML;editing(false);location.reload();}else{say('Non salvato: '+(res.errore||'errore'));}})
  .catch(function(){bSave.disabled=false;say('Il servizio del Mac non risponde.');});});
if(bReset){bReset.addEventListener('click',function(){
  if(!confirm('Tornare al testo originale generato in automatico?'))return;
  fetch('/api/ripristina-infomercati',{method:'POST'}).then(function(r){return r.json();})
  .then(function(res){if(res.ok)location.reload();else say('Non riuscito: '+(res.errore||'errore'));});});}
if(!local&&bReset)bReset.hidden=true;
document.getElementById('print').addEventListener('click',function(){window.print();});
document.getElementById('copy').addEventListener('click',function(){
  var b=this;function ok(s){b.textContent=s;setTimeout(function(){b.textContent='Copia per email';},2500);}
  var t=art.innerText;
  function bySelection(){var r=document.createRange();r.selectNodeContents(art);var s=window.getSelection();s.removeAllRanges();s.addRange(r);
    var done=false;try{done=document.execCommand('copy');}catch(e){}
    if(done){s.removeAllRanges();ok('Copiato!');}else{ok('Testo selezionato: premi Cmd+C');}}
  if(window.ClipboardItem&&navigator.clipboard&&navigator.clipboard.write){
    navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([art.innerHTML],{type:'text/html'}),
      'text/plain':new Blob([t],{type:'text/plain'})})]).then(function(){ok('Copiato!');},bySelection);
  }else{bySelection();}});
})();"""
    csp = "; ".join(["default-src 'none'", f"script-src 'sha256-{sha256_b64(js)}'", "style-src 'unsafe-inline'",
                     "connect-src 'self'", "img-src 'self' data:", "base-uri 'none'", "form-action 'none'", "object-src 'none'"])
    title = rep.get("titolo") or "InfoMercati"
    return f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{e(csp, quote=True)}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>InfoMercati – {e(when)}</title>
<style>
  body {{ margin: 0; background: #eef1f5; color: #1b2230; font: 17px/1.65 Georgia, "Times New Roman", serif; }}
  .bar {{ position: sticky; top: 0; display: flex; gap: .6rem; justify-content: flex-end; flex-wrap: wrap; padding: .6rem 16px;
          background: #ffffffe6; border-bottom: 1px solid #dfe3ea; font: 14px system-ui, -apple-system, sans-serif; z-index: 2; }}
  .bar button, .bar a {{ font: inherit; padding: .45rem .9rem; border-radius: 999px; border: 1px solid #1d4ed8; background: #fff; color: #1d4ed8; cursor: pointer; text-decoration: none; }}
  .bar button.primary {{ background: #1d4ed8; color: #fff; }}
  article {{ max-width: 720px; margin: 24px auto 40px; background: #fff; padding: 40px 56px 48px; border-radius: 6px; box-shadow: 0 6px 24px -12px rgba(0,0,0,.25); }}
  .mast {{ display: flex; justify-content: space-between; align-items: baseline; border-bottom: 3px solid #1b2230; padding-bottom: .5rem; margin-bottom: 1.4rem;
           font: 600 13px/1.2 system-ui, -apple-system, sans-serif; letter-spacing: .04em; text-transform: uppercase; color: #6b7585; }}
  .mast b {{ font: 800 22px/1 system-ui, -apple-system, sans-serif; letter-spacing: -.01em; text-transform: none; color: #1b2230; }}
  .mast b span {{ color: #1d4ed8; }}
  .im-title {{ font-size: 2rem; line-height: 1.18; margin: 0 0 .6rem; font-weight: 700; letter-spacing: -.01em; }}
  .dek {{ font-size: 1.15rem; line-height: 1.45; color: #3b4558; margin: 0 0 .8rem; font-style: italic; }}
  .byline {{ font: 13px system-ui, -apple-system, sans-serif; color: #6b7585; margin: 0 0 1.6rem; }}
  h2 {{ font: 700 1.12rem/1.3 system-ui, -apple-system, sans-serif; margin: 1.8rem 0 .4rem; color: #1b2230; }}
  h2.lead-h {{ font-size: 1.3rem; margin-top: .4rem; }}
  .lead p:first-child::first-letter {{ float: left; font-size: 3.1em; line-height: .9; padding: .06em .08em 0 0; font-weight: 700; color: #1d4ed8; }}
  p {{ margin: 0 0 1rem; text-align: justify; hyphens: auto; }}
  .num {{ float: right; width: 210px; margin: .3rem 0 1rem 1.4rem; padding: .9rem 1rem; background: #f3f6fc; border-left: 4px solid #1d4ed8; border-radius: 4px; }}
  .num-v {{ font: 800 1.7rem/1.1 system-ui, -apple-system, sans-serif; color: #1d4ed8; }}
  .num-l {{ font: 600 11px system-ui, -apple-system, sans-serif; text-transform: uppercase; letter-spacing: .06em; color: #6b7585; margin: .2rem 0 .5rem; }}
  .num p {{ font-size: .9rem; line-height: 1.5; text-align: left; margin: 0; }}
  ul.brief {{ list-style: none; padding: 0; margin: 0 0 1rem; clear: both; }}
  ul.brief li {{ padding: .45rem 0 .45rem 1.1rem; border-bottom: 1px solid #eceff4; position: relative; font-size: .97rem; }}
  ul.brief li::before {{ content: "›"; position: absolute; left: 0; color: #1d4ed8; font-weight: 700; }}
  .pov {{ clear: both; margin-top: 1.8rem; padding: 1rem 1.2rem .3rem; background: #f8f5ef; border-radius: 6px; }}
  .pov h2 {{ margin-top: 0; }}
  footer {{ clear: both; margin-top: 2.2rem; padding-top: .8rem; border-top: 1px solid #e3e6ec; font: 11.5px/1.5 system-ui, -apple-system, sans-serif; color: #6b7585; }}
  footer p {{ text-align: left; margin-bottom: .4rem; }}
  .bar .note {{ margin-right: auto; align-self: center; color: #6b7585; font-size: 12.5px; }}
  .bar button[hidden] {{ display: none; }}
  .msg {{ max-width: 720px; margin: 12px auto 0; padding: .55rem .9rem; background: #fff7dc; border: 1px solid #f1d98e; border-radius: 8px; font: 13.5px system-ui, -apple-system, sans-serif; color: #5d4500; }}
  .msg[hidden] {{ display: none; }}
  body.editing #im-body {{ outline: 2px dashed #1d4ed8; outline-offset: 10px; border-radius: 2px; }}
  body.editing #im-body:focus {{ outline-color: #f59e0b; }}
  @page {{ size: A4; margin: 16mm; }}
  @media print {{ body {{ background: #fff; font-size: 12pt; }} .bar, .msg {{ display: none; }} article {{ box-shadow: none; margin: 0; padding: 0; max-width: none; }} }}
  @media (max-width: 640px) {{ article {{ padding: 24px 18px; margin: 0; border-radius: 0; }} p {{ text-align: left; }}
    .num {{ float: none; width: auto; margin: 0 0 1rem; }} .im-title {{ font-size: 1.6rem; }} }}
</style></head>
<body>
<div class=bar><a href="brief.html">← Brief</a><span class=note>{e(saved_note)}</span>
<button id=edit type=button>Modifica</button><button id=save class=primary type=button hidden>Salva</button><button id=cancel type=button hidden>Annulla</button>
{'<button id=reset type=button>Ripristina originale</button>' if edits else ''}
<button id=copy type=button>Copia per email</button><button id=print class=primary type=button>Stampa / salva PDF</button></div>
<p id=msg class=msg hidden></p>
<article>
<div class=mast><b>Info<span>Mercati</span></b><span>{e(when)}</span></div>
{body}
</article>
<script>{js}</script>
</body></html>"""


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    if "--solo-pagine" in sys.argv:
        # rigenera solo le pagine (es. dopo una modifica di InfoMercati), senza scaricare nulla
        cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
        tz = ZoneInfo(cfg["settings"].get("timezone", "Europe/Rome"))
        data = load_previous()
        if not data:
            print("Nessuna pagina precedente da rigenerare.", file=sys.stderr)
            return 1
        watchlist, tv = apply_watchlist(cfg, data.get("news", []))
        data["tradingview"] = tv
        data["watchlist_own"] = cfg["watchlist"]
        data["watchlist_equitylab"] = [w["d"] for w in watchlist if w.get("da_equitylab")]
        write_atomic(OUT_PATH, render(data, cfg["settings"].get("title", "Cruscotto finanziario")))
        write_atomic(OUT_PATH.parent / "infomercati.html", render_infomercati(data, tz))
        write_atomic(OUT_PATH.parent / "brief.html", render_brief(data, cfg, tz))
        print("Pagine rigenerate (dashboard, InfoMercati, Brief).")
        return 0
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

    watchlist, tv = apply_watchlist(cfg, sections["news"])
    report = revalidate_report(prev.get("report"))
    every = (cfg.get("report") or {}).get("rigenera_ogni_ore", 3)
    stale = not report or now - dt.datetime.fromisoformat(report["generated_at"]) >= dt.timedelta(hours=every)
    # InfoMercati modificato a mano oggi: resta quello fino a domattina (salvo --report)
    locked = bool(report and load_edits(report)
                  and dt.datetime.fromisoformat(report["generated_at"]).astimezone(tz).date() == now.astimezone(tz).date())
    if "--report" in sys.argv or (not locked and (not news_only or stale)):
        try:
            report = build_report(cfg, sections["news"], sections.get("markets", []), now, status) or report
        except Exception:
            traceback.print_exc()
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
        "equitylab_url": EQUITYLAB_ORIGIN,
        "watchlist_own": cfg["watchlist"],
        "watchlist_equitylab": [w["d"] for w in watchlist if w.get("da_equitylab")],
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(OUT_PATH, render(data, st.get("title", "Cruscotto finanziario")))
    try:
        write_atomic(OUT_PATH.parent / "brief.html", render_brief(data, cfg, tz))
        write_atomic(OUT_PATH.parent / "infomercati.html", render_infomercati(data, tz))
        (OUT_PATH.parent / "lettera.html").unlink(missing_ok=True)
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
