(function () {
  'use strict';
  // Tutto il testo che arriva da feed e API viene inserito solo con textContent / createTextNode.
  var DATA;
  try {
    DATA = JSON.parse(document.getElementById('dashboard-data').textContent);
  } catch (e) {
    document.getElementById('updated').textContent = 'Errore: dati della pagina non leggibili.';
    return;
  }
  var TZ = DATA.timezone || 'Europe/Rome';
  var SVGNS = 'http://www.w3.org/2000/svg';
  var MONTHS = ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic'];
  var CATS = DATA.categories || [];
  var root = document.documentElement;

  // ---------- utilità ----------
  function el(tag, attrs) {
    var n = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (k) {
        var v = attrs[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') n.className = v;
        else n.setAttribute(k, v === true ? '' : String(v));
      });
    }
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined || c === '') continue;
      n.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
    }
    return n;
  }
  function svgEl(tag, attrs) {
    var n = document.createElementNS(SVGNS, tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function safeUrl(u) { return (typeof u === 'string' && /^https:\/\//i.test(u)) ? u : null; }
  function extLink(url, content, cls, label) {
    var u = safeUrl(url);
    if (!u) return el('span', { class: cls }, content);
    return el('a', { href: u, target: '_blank', rel: 'noopener noreferrer', class: cls, 'aria-label': label }, content);
  }
  function fmtDateTime(iso) {
    var d = new Date(iso);
    if (isNaN(d)) return 'n.d.';
    return new Intl.DateTimeFormat('it-IT', { timeZone: TZ, day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit' }).format(d);
  }
  function fmtObsDate(s) {
    if (!s) return 'n.d.';
    var m = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/.exec(s);
    if (!m) return s;
    return m[3] ? m[3] + '/' + m[2] + '/' + m[1] : MONTHS[+m[2] - 1] + ' ' + m[1];
  }
  function relTime(iso) {
    var mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (isNaN(mins)) return '';
    if (mins < 1) return 'ora';
    if (mins < 60) return mins + ' min fa';
    var h = Math.floor(mins / 60);
    if (h < 24) return h + (h === 1 ? ' ora fa' : ' ore fa');
    var d = Math.floor(h / 24);
    return d + (d === 1 ? ' giorno fa' : ' giorni fa');
  }
  var nfCache = {};
  function fmtNum(v, dec) {
    if (!nfCache[dec]) {
      var opts = { minimumFractionDigits: dec, maximumFractionDigits: dec };
      try { nfCache[dec] = new Intl.NumberFormat('it-IT', Object.assign({ useGrouping: 'always' }, opts)); }
      catch (e) { nfCache[dec] = new Intl.NumberFormat('it-IT', opts); }
    }
    return nfCache[dec].format(v);
  }
  function decimalsOf(item) {
    if (item.decimals !== null && item.decimals !== undefined) return item.decimals;
    if (item.kind === 'spread') return 0;
    return item.kind === 'rate' ? 2 : (Math.abs(item.value) >= 1000 ? 2 : 4);
  }
  function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, ''); }
  function cssVar(name) { return getComputedStyle(root).getPropertyValue(name).trim(); }
  function catIndex(c) { var i = CATS.indexOf(c); return i < 0 ? 0 : i % 5; }

  // ---------- tema ----------
  var themeBtn = document.getElementById('theme');
  var themeListeners = [];
  function currentTheme() {
    var t = root.getAttribute('data-theme');
    if (t) return t;
    return (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) ? 'dark' : 'light';
  }
  function applyTheme(t) {
    root.setAttribute('data-theme', t);
    var dark = t === 'dark';
    themeBtn.setAttribute('aria-pressed', dark ? 'true' : 'false');
    themeBtn.setAttribute('aria-label', dark ? 'Passa al tema chiaro' : 'Passa al tema scuro');
    themeBtn.title = dark ? 'Tema chiaro' : 'Tema scuro';
  }
  try { var saved = localStorage.getItem('dash-theme'); if (saved === 'dark' || saved === 'light') root.setAttribute('data-theme', saved); } catch (e) {}
  applyTheme(currentTheme());
  themeBtn.addEventListener('click', function () {
    var t = currentTheme() === 'dark' ? 'light' : 'dark';
    applyTheme(t);
    try { localStorage.setItem('dash-theme', t); } catch (e) {}
    themeListeners.forEach(function (fn) { fn(t); });
  });

  // ---------- intestazione ----------
  var hasOfficial = (DATA.markets || []).some(function (g) { return (g.items || []).length; });
  document.getElementById('updated').textContent = 'Notizie aggiornate il ' + fmtDateTime(DATA.generated_at) +
    (hasOfficial && DATA.markets_at && DATA.markets_at !== DATA.generated_at ? ' · dati ufficiali il ' + fmtDateTime(DATA.markets_at) : '') + ' · ora di Roma';

  // ---------- pagina aperta come file: rimanda alla versione servita dal Mac ----------
  var LOCAL = 'http://127.0.0.1:8799/';
  if (location.protocol === 'file:') {
    var bb = document.querySelector('.brief-btn');
    if (bb) bb.setAttribute('href', LOCAL + 'brief.html');
    var fb = document.getElementById('fresh');
    document.getElementById('fresh-text').textContent = 'Stai usando la pagina aperta come file: video, Brief e aggiornamenti automatici funzionano solo dalla versione locale.';
    var go = document.getElementById('fresh-btn');
    go.textContent = 'Apri la versione locale';
    go.addEventListener('click', function () { location.href = LOCAL; });
    fb.hidden = false;
  }

  // ---------- nuova versione disponibile (solo se la pagina è servita da http://127.0.0.1) ----------
  var lastActivity = Date.now();
  ['pointerdown', 'keydown', 'scroll', 'wheel', 'touchstart'].forEach(function (ev) {
    window.addEventListener(ev, function () { lastActivity = Date.now(); }, { passive: true });
  });
  function videoPlaying() { return !!document.querySelector('.vframe iframe'); }
  if (/^https?:$/.test(location.protocol)) {
    var fresh = document.getElementById('fresh');
    document.getElementById('fresh-btn').addEventListener('click', function () { location.reload(); });
    setInterval(function () {
      fetch('version.json', { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; }).then(function (v) {
        if (!v || !v.generated_at || v.generated_at === DATA.generated_at) return;
        document.getElementById('fresh-text').textContent = 'Dati aggiornati alle ' + fmtDateTime(v.generated_at).slice(-5) + '.';
        fresh.hidden = false;
        // ricarica da sola se non stai usando la pagina e non c'è un video aperto
        if (Date.now() - lastActivity > 5 * 60000 && !videoPlaying()) location.reload();
      }).catch(function () {});
    }, 120000);
  }
  var clock = document.getElementById('clock');
  var clockFmt = new Intl.DateTimeFormat('it-IT', { timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit', second: '2-digit' });
  function tick() { clock.textContent = clockFmt.format(new Date()) + ' · Roma'; }
  tick(); setInterval(tick, 1000);
  var ageH = (Date.now() - new Date(DATA.generated_at).getTime()) / 36e5;
  if (ageH > 36) {
    var st = document.getElementById('stale');
    st.textContent = 'Attenzione: notizie e video non vengono aggiornati da ' + Math.round(ageH) + ' ore (controlla build.log).';
    st.hidden = false;
  }

  // ---------- comparsa animata ----------
  var revealIO = 'IntersectionObserver' in window ? new IntersectionObserver(function (entries) {
    entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('in'); revealIO.unobserve(en.target); } });
  }, { rootMargin: '0px 0px -40px 0px' }) : null;
  function reveal(node) { node.classList.add('reveal'); if (revealIO) revealIO.observe(node); else node.classList.add('in'); }

  // ---------- riquadri dei dati ufficiali ----------
  var tip = document.getElementById('tip');
  function deltaPill(item, v, label) {
    if (v === null || v === undefined || !isFinite(v)) return el('span', { class: 'pill flat' }, 'n.d.');
    var pct = item.kind === 'level';
    var dec = pct ? 2 : 0;
    var r = Math.round(v * Math.pow(10, dec)) / Math.pow(10, dec);
    var dir = r > 0 ? 'up' : (r < 0 ? 'down' : 'flat');
    var arrow = r > 0 ? '▲' : (r < 0 ? '▼' : '■');
    var sign = r > 0 ? '+' : (r < 0 ? '−' : '');
    var txt = sign + fmtNum(Math.abs(r), dec) + (pct ? ' %' : ' p.b.');
    var word = r > 0 ? 'in rialzo' : (r < 0 ? 'in calo' : 'invariato');
    return el('span', { class: 'pill ' + dir, title: label, 'aria-label': label + ': ' + word + ' ' + txt }, arrow + ' ' + txt);
  }
  function sparkline(item, wrap) {
    var pts = item.spark || [];
    if (pts.length < 2) return;
    var vals = pts.map(function (p) { return p[1]; });
    var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    var span = (max - min) || 1, W = 100, H = 40, pad = 4;
    var dec = decimalsOf(item), unit = item.unit ? ' ' + item.unit : '';
    function X(i) { return i * W / (vals.length - 1); }
    function Y(v) { return H - pad - (v - min) / span * (H - 2 * pad); }
    var label = 'Andamento dal ' + fmtObsDate(pts[0][0]) + ' (' + fmtNum(vals[0], dec) + unit + ') al ' +
      fmtObsDate(pts[pts.length - 1][0]) + ' (' + fmtNum(vals[vals.length - 1], dec) + unit + ')';
    var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, preserveAspectRatio: 'none', class: 'spark', role: 'img', 'aria-label': label });
    var t = svgEl('title', {}); t.textContent = label; svg.appendChild(t);
    var line = vals.map(function (v, i) { return X(i).toFixed(2) + ',' + Y(v).toFixed(2); }).join(' ');
    svg.appendChild(svgEl('polygon', { class: 'area', points: '0,' + H + ' ' + line + ' ' + W + ',' + H }));
    svg.appendChild(svgEl('polyline', { class: 'line', points: line }));
    var cross = svgEl('line', { class: 'cross', x1: 0, x2: 0, y1: 0, y2: H, visibility: 'hidden' });
    svg.appendChild(cross);
    var dot = el('span', { class: 'spark-dot' });
    function place(i) {
      dot.style.left = (X(i) / W * 100) + '%';
      dot.style.top = (Y(vals[i]) / H * 100) + '%';
    }
    place(vals.length - 1);
    svg.addEventListener('pointermove', function (ev) {
      var r = svg.getBoundingClientRect();
      var i = Math.max(0, Math.min(vals.length - 1, Math.round((ev.clientX - r.left) / r.width * (vals.length - 1))));
      cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('visibility', 'visible');
      place(i);
      tip.textContent = fmtObsDate(pts[i][0]) + ' · ' + fmtNum(vals[i], dec) + unit;
      tip.style.left = (r.left + X(i) / W * r.width) + 'px';
      tip.style.top = (r.top + Y(vals[i]) / H * r.height) + 'px';
      tip.hidden = false;
    });
    svg.addEventListener('pointerleave', function () {
      cross.setAttribute('visibility', 'hidden'); place(vals.length - 1); tip.hidden = true;
    });
    wrap.appendChild(svg); wrap.appendChild(dot);
  }
  function renderKpis() {
    var box = document.getElementById('kpis');
    if (!box) return;
    var n = 0;
    (DATA.markets || []).forEach(function (g) {
      var row = el('div', { class: 'kpis-row' });
      (g.items || []).forEach(function (it) {
        var ok = it.status === 'ok' && it.value !== null && it.value !== undefined;
        var monthly = it.freq === 'M';
        var dir = ok && isFinite(it.chg) ? (it.chg > 0 ? 'up' : (it.chg < 0 ? 'down' : '')) : '';
        var card = el('article', { class: 'kpi ' + dir, 'aria-label': it.name });
        card.style.setProperty('--i', n++);
        card.appendChild(el('div', { class: 'kpi-top' }, el('span', { class: 'kpi-name' }, it.name),
          ok ? el('span', { class: 'kpi-freq' }, monthly ? 'media mensile' : 'giornaliero') : null));
        if (ok) {
          var unit = it.unit ? el('small', null, it.unit) : null;
          card.appendChild(el('div', { class: 'kpi-val' }, fmtNum(it.value, decimalsOf(it)), unit));
          card.appendChild(el('div', { class: 'kpi-delta' },
            el('span', { class: 'ytd' }, monthly ? 'sul mese' : 'sul giorno'),
            deltaPill(it, it.chg, monthly ? 'Variazione sul mese precedente' : 'Variazione sulla rilevazione precedente'),
            el('span', { class: 'ytd' }, 'da inizio anno'), deltaPill(it, it.ytd, 'Variazione da inizio anno')));
          var wrap = el('div', { class: 'spark-wrap' });
          card.appendChild(wrap);
          sparkline(it, wrap);
          card.appendChild(el('div', { class: 'kpi-foot' },
            extLink(it.source_url, it.source, null, 'Fonte: ' + it.source + ' (nuova scheda)'),
            el('span', { title: 'Scaricato il ' + fmtDateTime(it.fetched_at) }, 'dato del ' + fmtObsDate(it.date))));
        } else {
          card.appendChild(el('div', { class: 'kpi-val nd', title: it.reason || '' }, 'n.d.'));
          var lv = it.last_valid;
          card.appendChild(el('div', { class: 'kpi-foot' }, el('span', null, lv
            ? 'Fonte non disponibile. Ultimo dato valido: ' + fmtObsDate(lv.date) + (lv.fetched_at ? ' (scaricato ' + fmtDateTime(lv.fetched_at) + ')' : '')
            : 'Fonte non disponibile.')));
        }

        row.appendChild(card);
      });
      var grp = el('div', { class: 'kgroup' },
        el('div', { class: 'kgroup-head' }, el('h3', null, g.group), g.note ? el('p', { class: 'kgroup-note' }, g.note) : null), row);
      box.appendChild(grp);
    });
  }

  // ---------- TradingView: widget gratuiti, caricati dalla pagina (lo script non scarica nulla da TradingView) ----------
  var TV = DATA.tradingview || {};
  function mountTV(slot, file, configFn) {
    function render() {
      slot.replaceChildren();
      slot.classList.add('loading');
      var c = el('div', { class: 'tradingview-widget-container' }, el('div', { class: 'tradingview-widget-container__widget' }));
      var s = document.createElement('script');
      s.src = 'https://s3.tradingview.com/external-embedding/' + file;
      s.async = true;
      s.textContent = JSON.stringify(configFn(currentTheme()));
      c.appendChild(s);
      slot.appendChild(c);
      var mo = new MutationObserver(function () {
        var f = slot.querySelector('iframe');
        if (!f) return;
        mo.disconnect();
        f.addEventListener('load', function () { slot.classList.remove('loading'); });
      });
      mo.observe(slot, { childList: true, subtree: true });
      setTimeout(function () { slot.classList.remove('loading'); }, 9000);
    }
    render();
    themeListeners.push(render);
  }
  function whenVisible(node, fn) {
    if (!('IntersectionObserver' in window)) { fn(); return; }
    var io = new IntersectionObserver(function (en) {
      if (en.some(function (e) { return e.isIntersecting; })) { io.disconnect(); fn(); }
    }, { rootMargin: '300px 0px' });
    io.observe(node);
  }
  function overviewConfig(tabs) { return function (theme) {
    return {
      colorTheme: theme, dateRange: '1M', showChart: true, locale: 'it', width: '100%', height: 620,
      largeChartUrl: '', isTransparent: true, showSymbolLogo: true, showFloatingTooltip: true,
      plotLineColorGrowing: cssVar('--up'), plotLineColorFalling: cssVar('--down'),
      belowLineFillColorGrowing: cssVar('--up-soft'), belowLineFillColorFalling: cssVar('--down-soft'),
      belowLineFillColorGrowingBottom: 'rgba(0,0,0,0)', belowLineFillColorFallingBottom: 'rgba(0,0,0,0)',
      gridLineColor: 'rgba(0,0,0,0)', scaleFontColor: cssVar('--muted'),
      symbolActiveColor: cssVar('--accent-soft'),
      tabs: (tabs || []).map(function (t) {
        return { title: t.title, originalTitle: t.title, symbols: (t.symbols || []).map(function (x) { return { s: x.s, d: x.d }; }) };
      })
    };
  }; }
  function quoteConfig(sym) {
    return function (theme) { return { symbol: sym.s, width: '100%', isTransparent: true, colorTheme: theme, locale: 'it' }; };
  }
  function miniConfig(sym) {
    return function (theme) {
      return { symbol: sym.s, width: '100%', height: '100%', locale: 'it', dateRange: '1M', colorTheme: theme,
        isTransparent: true, autosize: true, largeChartUrl: '', noTimeScale: true, chartOnly: false,
        trendLineColor: cssVar('--accent'), underLineColor: cssVar('--accent-soft'), underLineBottomColor: 'rgba(0,0,0,0)' };
    };
  }
  function tickerConfig(theme) {
    return {
      symbols: (TV.ticker || []).map(function (x) { return { proName: x.s, title: x.d }; }),
      showSymbolLogo: true, isTransparent: true, displayMode: 'adaptive', colorTheme: theme, locale: 'it'
    };
  }
  function renderTradingView() {
    var ticker = document.getElementById('ticker');
    var live = document.getElementById('live');
    if (!TV.enabled) { ticker.remove(); live.remove(); return; }
    if (TV.autoload && (TV.ticker || []).length) mountTV(ticker, 'embed-widget-ticker-tape.js', tickerConfig);
    else ticker.remove();
    (TV.sections || []).forEach(function (sec) {
      var box = el('section', { class: 'live-sec card' + (sec.watchlist ? ' watch' : ''), 'aria-label': sec.title },
        el('div', { class: 'sec-head' }, el('h3', null, sec.title)));
      if (sec.note) box.appendChild(el('p', { class: 'kgroup-note sec-note' }, sec.note));
      var mounts = [];
      if (sec.type === 'overview') {
        var slot = el('div', { class: 'tv-slot' });
        box.appendChild(slot);
        mounts.push(function () { mountTV(slot, 'embed-widget-market-overview.js', overviewConfig(sec.tabs)); });
        whenVisibleOrButton(slot, mounts[0]);
      } else {
        (sec.groups || []).forEach(function (g) {
          var grid = el('div', { class: 'tile-grid' });
          (g.symbols || []).forEach(function (sym) {
            var slot = el('div', { class: 'tv-q' });
            var tile = el('div', { class: 'tv-tile', role: 'group', 'aria-label': sym.d + ' (TradingView)' },
              el('div', { class: 'tv-cap' }, sym.d), slot);
            grid.appendChild(tile);
            whenVisibleOrButton(slot, function () { mountTV(slot, 'embed-widget-single-quote.js', quoteConfig(sym)); });
          });
          box.appendChild(el('div', { class: 'lgroup' }, g.name ? el('h4', null, g.name) : null, grid));
        });
      }
      box.appendChild(el('p', { class: 'fine' }, 'Valori forniti da ',
        extLink('https://it.tradingview.com/', 'TradingView'), ': possono essere in ritardo; «(CFD)» indica un contratto che replica lo strumento.'));
      live.appendChild(box);
    });
  }
  function whenVisibleOrButton(slot, mount) {
    if (TV.autoload) { whenVisible(slot, mount); return; }
    var b = el('button', { type: 'button', class: 'btn' }, 'Carica');
    b.addEventListener('click', mount);
    slot.appendChild(el('div', { class: 'tv-start' }, b));
  }

  // ---------- notizie ----------
  var activeCat = null, newsItems = [], chipEls = [];
  function renderNews() {
    var list = document.getElementById('news');
    var filters = document.getElementById('news-filters');
    var counts = {};
    (DATA.news || []).forEach(function (n) { (n.categories || []).forEach(function (c) { counts[c] = (counts[c] || 0) + 1; }); });
    var watchN = (DATA.news || []).filter(function (n) { return n.watch && n.watch.length; }).length;
    var chipList = [null].concat(watchN ? ['__watch'] : []).concat(CATS);
    chipList.forEach(function (c) {
      var isW = c === '__watch';
      var b = el('button', { type: 'button', class: 'chip', 'aria-pressed': c === null ? 'true' : 'false' },
        c === null ? null : (isW ? el('span', { class: 'star', 'aria-hidden': 'true' }, '★') : el('span', { class: 'dot k' + catIndex(c), 'aria-hidden': 'true' })),
        c === null ? 'Tutte' : (isW ? 'Watchlist' : c),
        el('span', { class: 'n' }, c === null ? (DATA.news || []).length : (isW ? watchN : (counts[c] || 0))));
      b.addEventListener('click', function () {
        activeCat = c;
        chipEls.forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
        filterNews();
      });
      chipEls.push(b);
      filters.appendChild(b);
    });
    (DATA.news || []).forEach(function (n) {
      var link = safeUrl(n.link);
      if (!link) return;
      var cats = n.categories || [];
      var main = cats[0] || '';
      var time = el('time', { datetime: n.date, title: fmtDateTime(n.date) }, relTime(n.date));
      var meta = el('div', { class: 'ni-meta' },
        el('span', { class: 'cat' }, el('span', { class: 'dot k' + catIndex(main), 'aria-hidden': 'true' }), main),
        el('span', { class: 'src' }, n.source), time);
      var ageMin = (Date.now() - new Date(n.date).getTime()) / 60000;
      if (ageMin < 180) meta.appendChild(el('span', { class: 'new' }, 'Nuovo'));
      if (n.paywall) meta.appendChild(el('span', { class: 'pay' }, 'a pagamento'));
      if (n.watch && n.watch.length) meta.insertBefore(el('span', { class: 'star' }, '★ ' + n.watch.join(', ')), meta.firstChild);
      var li = el('li', { class: 'ni k' + catIndex(main) }, meta,
        el('a', { href: link, target: '_blank', rel: 'noopener noreferrer' }, n.title));
      if (n.summary) li.appendChild(el('p', { class: 'ni-sum' }, n.summary));
      var others = cats.slice(1);
      var also = [];
      if (others.length) also.push('anche in: ' + others.join(', '));
      if (n.also && n.also.length) also.push('ripresa da: ' + n.also.join(', '));
      if (also.length) li.appendChild(el('div', { class: 'ni-also' }, also.join(' · ')));
      list.appendChild(li);
      newsItems.push({ li: li, time: time, date: n.date, watch: !!(n.watch && n.watch.length), cats: cats, hay: norm(n.title + ' ' + (n.summary || '') + ' ' + n.source) });
    });
    list.appendChild(el('li', { class: 'empty', id: 'news-empty', hidden: true }, 'Nessuna notizia corrisponde al filtro.'));
    filterNews();
    setInterval(function () { newsItems.forEach(function (n) { n.time.textContent = relTime(n.date); }); }, 60000);
  }
  function filterNews() {
    var q = norm(document.getElementById('search').value).trim();
    var words = q ? q.split(/\s+/) : [];
    var shown = 0;
    newsItems.forEach(function (n) {
      var ok = (!activeCat || (activeCat === '__watch' ? n.watch : n.cats.indexOf(activeCat) >= 0)) && words.every(function (w) { return n.hay.indexOf(w) >= 0; });
      n.li.hidden = !ok;
      if (ok) shown++;
    });
    document.getElementById('news-empty').hidden = shown > 0;
    document.getElementById('news-count').textContent = shown + ' notizie · ultime ' + (DATA.news_window_hours || 48) + ' ore';
  }
  document.getElementById('search').addEventListener('input', filterNews);

  // ---------- video ----------
  var YT = 'https://www.youtube-nocookie.com/embed/';
  function ytFrame(src, title) {
    return el('iframe', { src: src, title: title, referrerpolicy: 'strict-origin-when-cross-origin',
      allow: 'autoplay; encrypted-media; picture-in-picture; fullscreen', allowfullscreen: true });
  }
  function playIcon() {
    var s = svgEl('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' });
    s.appendChild(svgEl('path', { d: 'M6 4l14 8-14 8z' }));
    return s;
  }
  function validId(v) { return /^[A-Za-z0-9_-]{11}$/.test(v.video_id || '') ? v.video_id : null; }
  function renderVideos() {
    if (location.protocol === 'file:') document.getElementById('video-local').hidden = false;
    var vids = (DATA.videos || []).filter(function (v) { return /^UC[A-Za-z0-9_-]{22}$/.test(v.channel_id || ''); });
    var player = document.getElementById('player');
    var rail = document.getElementById('rail');
    if (!vids.length) { player.appendChild(el('p', { class: 'empty' }, 'Nessun canale disponibile.')); return; }
    var railBtns = [];
    function show(idx) {
      var v = vids[idx], vid = validId(v);
      railBtns.forEach(function (b, i) { b.setAttribute('aria-pressed', i === idx ? 'true' : 'false'); });
      var frame = el('div', { class: 'vframe' });
      function playLatest() { frame.replaceChildren(ytFrame(YT + vid + '?autoplay=1&rel=0', 'Ultimo video di ' + v.name)); }
      function playRecent() { frame.replaceChildren(ytFrame(YT + 'videoseries?list=UU' + v.channel_id.slice(2), 'Video recenti di ' + v.name)); }
      function playLive() { frame.replaceChildren(ytFrame(YT + 'live_stream?channel=' + v.channel_id + '&autoplay=1', 'Diretta di ' + v.name)); }
      if (vid) {
        frame.appendChild(el('img', { src: 'https://i.ytimg.com/vi/' + vid + '/hqdefault.jpg',
          alt: 'Anteprima dell\'ultimo video di ' + v.name + (v.video_title ? ': ' + v.video_title : '') }));
        frame.appendChild(el('div', { class: 'shade' }));
      } else {
        frame.appendChild(el('div', { class: 'placeholder' }, 'Anteprima non disponibile'));
      }
      var canPlay = vid && v.embeddable !== false;
      if (canPlay || !vid) {
        var big = el('button', { type: 'button', class: 'play', 'aria-label': canPlay ? 'Riproduci l\'ultimo video di ' + v.name : 'Riproduci i video recenti di ' + v.name }, playIcon());
        big.addEventListener('click', canPlay ? playLatest : playRecent);
        frame.appendChild(big);
      }
      var acts = el('div', { class: 'acts' });
      if (canPlay) {
        var b1 = el('button', { type: 'button', class: 'btn btn-primary' }, '▶ Ultimo video');
        b1.addEventListener('click', playLatest); acts.appendChild(b1);
      } else if (!vid) {
        var b0 = el('button', { type: 'button', class: 'btn btn-primary' }, '▶ Video recenti');
        b0.addEventListener('click', playRecent); acts.appendChild(b0);
      }
      var b2 = el('button', { type: 'button', class: 'btn', 'aria-label': 'Prova la diretta di ' + v.name },
        el('span', { class: 'live-dot', 'aria-hidden': 'true' }), 'Diretta');
      b2.addEventListener('click', playLive); acts.appendChild(b2);
      acts.appendChild(extLink(vid ? 'https://www.youtube.com/watch?v=' + vid : 'https://www.youtube.com/channel/' + v.channel_id,
        'Apri su YouTube ↗', 'btn', 'Apri ' + v.name + ' su YouTube (nuova scheda)'));
      var info = el('div', { class: 'pinfo' }, el('h3', null, v.name),
        el('p', { class: 'vt' }, v.video_title || (vid ? 'Ultimo video caricato' : 'Ultimo video non individuato')), acts);
      if (v.embeddable === false) info.appendChild(el('p', { class: 'fine' }, 'L\'editore non consente la riproduzione di questo video fuori da YouTube.'));
      player.replaceChildren(frame, info);
    }
    vids.forEach(function (v, i) {
      var vid = validId(v);
      var th = el('div', { class: 'th' }, vid ? el('img', { src: 'https://i.ytimg.com/vi/' + vid + '/mqdefault.jpg', alt: '', loading: 'lazy' }) : null);
      var b = el('button', { type: 'button', class: 'ch', 'aria-pressed': 'false', 'aria-label': 'Mostra ' + v.name }, th, el('span', null, v.name));
      b.addEventListener('click', function () { show(i); });
      railBtns.push(b);
      rail.appendChild(b);
    });
    show(0);
  }

  // ---------- link, calendario, stato ----------
  function monogram(name) {
    var words = String(name).replace(/[–-].*$/, '').replace(/[^A-Za-zÀ-ÿ' ]/g, ' ').split(/[\s']+/).filter(function (w) { return w.length > 1; });
    if (words.length === 1) {
      var w = words[0], caps = w.match(/[A-Z]/g) || [];
      if (w === w.toUpperCase() && w.length <= 6) return w;
      if (caps.length >= 2) return caps.join('').slice(0, 4);
      return w.charAt(0).toUpperCase() + w.charAt(1);
    }
    return words.filter(function (w) { return w[0] === w[0].toUpperCase(); }).slice(0, 2).map(function (w) { return w[0]; }).join('').toUpperCase() || words[0].slice(0, 2).toUpperCase();
  }
  function renderLinks() {
    var ul = document.getElementById('links');
    (DATA.quick_links || []).forEach(function (l) {
      var u = safeUrl(l.url); if (!u) return;
      var li = el('li', null, el('a', { href: u, target: '_blank', rel: 'noopener noreferrer' },
        el('span', { class: 'mono', 'aria-hidden': 'true' }, monogram(l.name)),
        el('span', null, el('strong', null, l.name), el('small', null, l.desc || '')),
        el('span', { class: 'arr', 'aria-hidden': 'true' }, '→')));
      reveal(li);
      ul.appendChild(li);
    });
    var cal = document.getElementById('calendar');
    (DATA.calendar_links || []).forEach(function (l) {
      var u = safeUrl(l.url); if (!u) return;
      cal.appendChild(el('li', null, el('a', { href: u, target: '_blank', rel: 'noopener noreferrer' },
        el('span', null, l.name), el('span', { class: 'arr', 'aria-hidden': 'true' }, '↗'))));
    });
  }
  function renderCalendarWidget() {
    var cal = TV.calendar || {};
    var box = document.getElementById('cal-widget');
    if (!TV.enabled || !cal.enabled) { box.parentElement.remove(); return; }
    box.style.height = (cal.height || 560) + 'px';
    whenVisibleOrButton(box, function () {
      mountTV(box, 'embed-widget-events.js', function (theme) {
        return { colorTheme: theme, isTransparent: true, width: '100%', height: cal.height || 560, locale: 'it',
          importanceFilter: cal.importance || '0,1', countryFilter: cal.countries || 'it,eu,us' };
      });
    });
  }
  function renderGuide() {
    var box = document.getElementById('guide');
    var input = document.getElementById('guide-q');
    var items = (DATA.glossary || []).map(function (g) {
      var d = el('details', null, el('summary', null, g.nome), el('p', null, g.descrizione));
      box.appendChild(d);
      return { d: d, hay: norm(g.nome + ' ' + (g.chiavi || []).join(' ') + ' ' + g.descrizione), keys: (g.chiavi || []).map(norm), name: norm(g.nome) };
    });
    var empty = el('p', { class: 'empty', hidden: true }, 'Nessuna voce trovata: prova con una parola più corta (es. «CPI»).');
    box.appendChild(empty);
    if (!items.length) { box.closest('.cal-side').querySelector('.guide-search').remove(); box.remove(); return; }
    var NOISE = ['mm', 'yy', 'qq', 'sa', 'nsa', 'final', 'flash', 'prel', 'preliminary', 'f', 'p', 'rev'];
    function score(it, words) {
      var s = 0;
      words.forEach(function (w) {
        if (it.keys.some(function (k) { return k === w || k.indexOf(w + ' ') === 0 || w.indexOf(k) === 0; })) s += 3;
        else if (it.name.indexOf(w) >= 0) s += 2;
        else if (it.hay.indexOf(w) >= 0) s += 1;
      });
      return s;
    }
    input.addEventListener('input', function () {
      var q = norm(input.value).replace(/[*()]/g, ' ').trim();
      var words = q ? q.split(/\s+/) : [];
      var useful = words.filter(function (w) {
        return NOISE.indexOf(w) < 0 && (w.length >= 3 || items.some(function (it) { return it.keys.indexOf(w) >= 0; }));
      });
      if (!useful.length) useful = words;
      var best = null, bestScore = 0, shown = 0;
      items.forEach(function (it) {
        var s = useful.length ? score(it, useful) : 1;
        it.d.hidden = s === 0;
        it.d.open = false;
        if (s > 0) shown++;
        if (s > bestScore) { bestScore = s; best = it; }
      });
      empty.hidden = shown > 0;
      if (q.length >= 2 && best) best.d.open = true;
    });
  }
  function renderStatus() {
    var rows = DATA.status || [];
    var okN = rows.filter(function (r) { return r.ok; }).length;
    var sum = document.getElementById('status-summary');
    sum.replaceChildren(el('span', { class: okN === rows.length ? 'ok' : 'ko' }, okN === rows.length ? '✓' : '!'),
      okN + ' fonti su ' + rows.length + ' hanno risposto · ' + fmtDateTime(DATA.generated_at));
    if (okN < rows.length) document.getElementById('status-box').open = true;
    var table = el('table');
    table.appendChild(el('caption', { class: 'sr-only' }, 'Esito dell\'ultimo aggiornamento per ogni fonte'));
    table.appendChild(el('thead', null, el('tr', null, el('th', { scope: 'col' }, 'Fonte'), el('th', { scope: 'col' }, 'Sezione'),
      el('th', { scope: 'col' }, 'Esito'), el('th', { scope: 'col' }, 'Dettaglio'), el('th', { scope: 'col' }, 'Ultimo esito positivo'))));
    var tb = el('tbody');
    rows.forEach(function (r) {
      tb.appendChild(el('tr', null,
        el('th', { scope: 'row' }, extLink(r.url, r.name)),
        el('td', null, r.kind),
        el('td', null, el('span', { class: r.ok ? 'ok' : 'ko' }, r.ok ? '✓ OK' : '✗ Errore')),
        el('td', { class: 'small' }, r.detail || ''),
        el('td', { class: 'small' }, r.last_ok ? fmtDateTime(r.last_ok) : 'mai')));
    });
    table.appendChild(tb);
    document.getElementById('status').appendChild(el('div', { class: 'tablewrap' }, table));
    var ul = document.getElementById('discarded');
    (DATA.discarded || []).forEach(function (d) { ul.appendChild(el('li', null, el('strong', null, d.name + ': '), d.reason)); });
  }

  [renderKpis, renderTradingView, renderNews, renderVideos, renderLinks, renderCalendarWidget, renderGuide, renderStatus].forEach(function (fn) {
    try { fn(); } catch (e) { if (window.console) console.error(fn.name, e); }
  });
  Array.prototype.forEach.call(document.querySelectorAll('.reveal'), function (n) { if (revealIO) revealIO.observe(n); else n.classList.add('in'); });
})();
