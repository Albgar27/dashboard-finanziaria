/* Analisi PMI – interfaccia (JavaScript senza librerie). */
(function () {
  'use strict';

  var main = document.getElementById('main');
  var P = null;          // parametri dal server
  var AN = null;         // analisi dell'azienda aperta
  var sporco = false;    // modifiche non salvate

  // ---------- utilità ----------
  function el(tag, attrs) {
    var n = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null || v === false) return;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k.slice(0, 2) === 'on') n.addEventListener(k.slice(2), v);
      else if (k === 'value') n.value = v;
      else n.setAttribute(k, v === true ? '' : v);
    });
    for (var i = 2; i < arguments.length; i++) add(n, arguments[i]);
    return n;
  }
  function add(n, c) {
    if (c == null || c === false) return;
    if (Array.isArray(c)) { c.forEach(function (x) { add(n, x); }); return; }
    n.appendChild(typeof c === 'string' || typeof c === 'number' ? document.createTextNode(String(c)) : c);
  }
  function svg(tag, attrs) {
    var n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function inf(v) { return v === 'inf' || v === Infinity; }
  var nf0 = new Intl.NumberFormat('it-IT', { maximumFractionDigits: 0 });
  var nf2 = new Intl.NumberFormat('it-IT', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  // separatore delle migliaia anche sotto 10.000 (Intl in italiano non lo mette)
  function intero(v) { var n = Math.round(Math.abs(v)).toString().replace(/\B(?=(\d{3})+(?!\d))/g, '.'); return (v < 0 && Math.round(v) !== 0 ? '-' : '') + n; }
  function euro(v) { return v == null ? 'n.d.' : intero(v) + ' €'; }
  function euroK(v) {
    if (v == null) return 'n.d.';
    var a = Math.abs(v);
    if (a >= 1e6) return nf2.format(v / 1e6) + ' mln €';
    if (a >= 1e4) return nf0.format(v / 1e3) + ' mila €';
    return euro(v);
  }
  function pct(v, d) { return v == null ? 'n.d.' : (v * 100).toLocaleString('it-IT', { minimumFractionDigits: d == null ? 1 : d, maximumFractionDigits: d == null ? 1 : d }) + '%'; }
  function fmtIndice(v, u) {
    if (v == null) return 'n.d.';
    if (inf(v)) return u === 'x' ? 'n.s.' : '∞';
    if (u === '€') return euroK(v);
    if (u === '%') return pct(v);
    if (u === 'gg') return nf0.format(v) + ' gg';
    return nf2.format(v);
  }
  function data(s) { if (!s) return ''; var p = String(s).slice(0, 10).split('-'); return p.length === 3 ? p[2] + '/' + p[1] + '/' + p[0] : s; }
  function numero(s) {
    if (s == null) return null;
    if (typeof s === 'number') return s;
    s = String(s).replace(/[€\s]/g, '');
    if (!s) return null;
    if (s.indexOf(',') >= 0) s = s.replace(/\./g, '').replace(',', '.');
    else if (/^-?\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '');
    var n = Number(s);
    return isFinite(n) ? n : null;
  }
  function inNumero(v, dec) {
    if (v == null || v === '') return '';
    return Number(v).toLocaleString('it-IT', { maximumFractionDigits: dec == null ? 2 : dec, useGrouping: true });
  }
  function toast(t, err) {
    var m = el('div', { class: 'msg' + (err ? ' err' : ''), text: t });
    document.getElementById('toast').appendChild(m);
    setTimeout(function () { m.remove(); }, err ? 7000 : 3500);
  }
  function api(metodo, percorso, corpo, extra) {
    var opz = { method: metodo, headers: { 'X-PMI': '1' } };
    if (corpo instanceof ArrayBuffer || corpo instanceof Blob) { opz.body = corpo; opz.headers['Content-Type'] = 'application/octet-stream'; }
    else if (corpo !== undefined) { opz.body = JSON.stringify(corpo); opz.headers['Content-Type'] = 'application/json'; }
    Object.assign(opz.headers, extra || {});
    return fetch(percorso, opz).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok) throw new Error(j.errore || ('Errore ' + r.status));
        return j;
      });
    });
  }
  function pill(colore, testo) { return el('span', { class: 'pill ' + (colore || 'grigio') }, el('span', { class: 'dot ' + (colore || 'grigio') }), testo); }
  function dot(colore, titolo) { return colore ? el('span', { class: 'dot ' + colore, title: titolo || colore, 'aria-label': titolo || colore }) : null; }
  function tile(et, val, det, colore) {
    return el('div', { class: 'tile' }, el('div', { class: 'et' }, et),
      el('div', { class: 'val' }, colore ? [dot(colore), ' '] : null, val), det ? el('div', { class: 'det' }, det) : null);
  }
  var NOMI_COLORE = { verde: 'buono', giallo: 'attenzione', rosso: 'critico', grigio: 'da completare' };

  // tooltip condiviso
  var tip = document.getElementById('tip');
  function mostraTip(ev, titolo, righe) {
    tip.replaceChildren(el('b', null, titolo), righe.map(function (r) { return el('div', null, r); }));
    tip.hidden = false;
    var x = Math.min(ev.clientX + 14, window.innerWidth - tip.offsetWidth - 8), y = ev.clientY + 14;
    if (y + tip.offsetHeight > window.innerHeight - 8) y = ev.clientY - tip.offsetHeight - 10;
    tip.style.left = x + 'px'; tip.style.top = y + 'px';
  }
  function nascondiTip() { tip.hidden = true; }

  // ---------- campi di form ----------
  // spec: {k, et, tipo: num|pct|text|date|select|area, opz: [[val, et]], dec, aiuto}
  function campo(spec, obj, onCambio) {
    var v = obj[spec.k], inp;
    if (spec.tipo === 'select') {
      inp = el('select', null, spec.opz.map(function (o) { return el('option', { value: o[0], selected: String(v == null ? '' : v) === String(o[0]) }, o[1]); }));
      inp.addEventListener('change', function () { obj[spec.k] = inp.value; segna(onCambio); });
    } else if (spec.tipo === 'area') {
      inp = el('textarea', { rows: 2 }); inp.value = v || '';
      inp.addEventListener('input', function () { obj[spec.k] = inp.value; segna(onCambio); });
    } else if (spec.tipo === 'date') {
      inp = el('input', { type: 'date', value: v ? String(v).slice(0, 10) : '' });
      inp.addEventListener('change', function () { obj[spec.k] = inp.value; segna(onCambio); });
    } else if (spec.tipo === 'num' || spec.tipo === 'pct') {
      var mostra = spec.tipo === 'pct' ? (v == null || v === '' ? '' : inNumero(Number(v) * 100, 3)) : inNumero(v, spec.dec);
      inp = el('input', { type: 'text', inputmode: 'decimal', value: mostra, placeholder: spec.ph || '' });
      inp.addEventListener('input', function () {
        var n = numero(inp.value);
        obj[spec.k] = n == null ? '' : (spec.tipo === 'pct' ? n / 100 : n);
        segna(onCambio);
      });
    } else {
      inp = el('input', { type: 'text', value: v == null ? '' : v, placeholder: spec.ph || '' });
      inp.addEventListener('input', function () { obj[spec.k] = inp.value; segna(onCambio); });
    }
    if (spec.nolabel) { inp.setAttribute('aria-label', spec.et); return inp; }
    return el('label', { class: 'campo' + (spec.largo ? ' largo' : '') }, spec.et + (spec.tipo === 'pct' ? ' (%)' : ''), inp,
      spec.aiuto ? el('span', { class: 'fine' }, spec.aiuto) : null);
  }
  function segna(cb) { sporco = true; if (cb) cb(); }
  function form(specs, obj) { return el('div', { class: 'form' }, specs.map(function (s) { return campo(s, obj); })); }
  function bottoneSalva(testo, fn) {
    var b = el('button', { type: 'button', class: 'btn btn-pri' }, testo || 'Salva e ricalcola');
    b.addEventListener('click', function () {
      b.disabled = true;
      Promise.resolve(fn()).then(function () { sporco = false; }).catch(function (e) { toast(e.message, true); })
        .finally(function () { b.disabled = false; });
    });
    return b;
  }
  function salvaSezione(chiave, dati) {
    return api('PUT', '/api/aziende/' + AN.azienda.id + '/sezioni/' + chiave, dati).then(function () {
      toast('Salvato'); sporco = false; return ricarica();
    });
  }
  function leggiFile(input, fn) {
    input.addEventListener('change', function () {
      var f = input.files[0]; if (!f) return;
      f.arrayBuffer().then(function (buf) { return fn(f, buf); }).catch(function (e) { toast(e.message, true); })
        .finally(function () { input.value = ''; });
    });
  }
  function bottoneFile(testo, accept, fn) {
    var inp = el('input', { type: 'file', accept: accept });
    leggiFile(inp, fn);
    return el('label', { class: 'btn file-in' }, testo, inp);
  }
  function SN() { return [['', '—'], ['si', 'Sì'], ['no', 'No']]; }

  // ---------- router ----------
  function rotta() {
    var h = location.hash.replace(/^#\/?/, '').split('/');
    if (h[0] === 'azienda' && h[1]) return { vista: 'azienda', id: h[1], tab: h[2] || 'sintesi' };
    return { vista: 'portafoglio' };
  }
  var hashPrima = location.hash, saltaGuardia = false;
  window.addEventListener('hashchange', function () {
    if (saltaGuardia) { saltaGuardia = false; return; }
    if (sporco && !confirm('Ci sono modifiche non salvate. Uscire senza salvare?')) {
      saltaGuardia = true; location.hash = hashPrima; return;
    }
    hashPrima = location.hash;
    render();
  });
  window.addEventListener('beforeunload', function (e) { if (sporco) { e.preventDefault(); e.returnValue = ''; } });

  function render() {
    nascondiTip();
    var r = rotta();
    if (r.vista === 'azienda') return vistaAzienda(r.id, r.tab);
    return vistaPortafoglio();
  }
  function ricarica() {
    var r = rotta();
    return api('GET', '/api/aziende/' + r.id).then(function (an) { AN = an; disegnaAzienda(r.tab); });
  }

  // ---------- portafoglio ----------
  function vistaPortafoglio() {
    sporco = false;
    document.title = 'Analisi PMI';
    main.replaceChildren(el('p', { class: 'caricamento' }, 'Caricamento…'));
    api('GET', '/api/portafoglio').then(function (d) {
      var testa = el('div', { class: 'testa' },
        el('div', null, el('h1', null, 'Portafoglio aziende'),
          el('p', { class: 'muted' }, 'Ordinate per priorità: prima le aziende con più azioni urgenti da proporre.')),
        el('div', { class: 'azioni' },
          el('button', { type: 'button', class: 'btn btn-pri', onclick: nuovaAzienda }, '+ Nuova azienda'),
          el('button', { type: 'button', class: 'btn', onclick: function () {
            api('POST', '/api/demo', {}).then(function (r) { location.hash = '#/azienda/' + r.id; });
          } }, 'Azienda di esempio'),
          el('a', { class: 'btn', href: '/api/esporta' }, 'Esporta copia (JSON)')));
      if (!d.aziende.length) {
        main.replaceChildren(testa, el('div', { class: 'card vuoto' },
          el('h2', null, 'Nessuna azienda'),
          el('p', null, 'Crea un\'azienda e carica il suo bilancio XBRL, oppure apri l\'azienda di esempio (dati inventati) per vedere come funziona.')));
        return;
      }
      var righe = d.aziende.map(function (a) {
        var s = a.solidita || {}, ps = a.prossima_scadenza;
        var tr = el('tr', { class: 'link', tabindex: '0', onclick: function () { location.hash = '#/azienda/' + a.id; },
          onkeydown: function (e) { if (e.key === 'Enter') location.hash = '#/azienda/' + a.id; } },
          el('td', null, el('a', { href: '#/azienda/' + a.id }, a.ragione_sociale), a.esempio ? el('span', { class: 'fine' }, ' (esempio)') : null,
            a.ateco ? el('div', { class: 'fine' }, 'ATECO ' + a.ateco) : null),
          el('td', { class: 'num' }, a.anno || '—'),
          el('td', { class: 'num' }, a.ricavi == null ? '—' : euroK(a.ricavi)),
          el('td', { class: 'num' }, a.dipendenti == null ? '—' : nf0.format(a.dipendenti)),
          el('td', null, s.colore ? pill(s.colore, s.testo) : el('span', { class: 'fine' }, 'manca bilancio')),
          el('td', { class: 'num' }, a.tfr_scopertura ? euroK(a.tfr_scopertura) : '—'),
          el('td', null, a.rischi.rosso ? pill('rosso', a.rischi.rosso + ' scoperti') : null, ' ', a.rischi.giallo ? pill('giallo', a.rischi.giallo + ' parziali') : null),
          el('td', { class: 'num' }, a.segnali_crisi ? pill('rosso', String(a.segnali_crisi)) : '0'),
          el('td', { class: 'num' }, a.proposte, a.urgenti ? el('span', { class: 'fine' }, ' (' + a.urgenti + ' urgenti)') : null),
          el('td', null, ps ? [el('div', null, data(ps.data)), el('div', { class: 'fine' }, ps.titolo)] : '—'));
        return tr;
      });
      var tabella = el('div', { class: 'card' }, el('div', { class: 'tab-scroll' }, el('table', null,
        el('thead', null, el('tr', null, ['Azienda', 'Anno', 'Ricavi', 'Dip.', 'Solidità', 'TFR scoperto', 'Coperture', 'Segnali crisi', 'Proposte', 'Prossima scadenza']
          .map(function (h, i) { return el('th', { class: [1, 2, 3, 5, 7, 8].indexOf(i) >= 0 ? 'num' : null, scope: 'col' }, h); }))),
        el('tbody', null, righe))),
        el('p', { class: 'fine' }, 'TFR scoperto = debito TFR meno liquidità e polizze già accantonate.'));
      main.replaceChildren(testa, tabella, listaScadenze(d.scadenze, true));
    }).catch(function (e) { main.replaceChildren(el('div', { class: 'card' }, 'Errore: ' + e.message)); });
  }

  function listaScadenze(sc, conAzienda) {
    var box = el('div', { class: 'card' }, el('h2', null, conAzienda ? 'Scadenze dei prossimi 4 mesi' : 'Scadenze'));
    if (!sc.length) { box.appendChild(el('p', { class: 'muted' }, 'Nessuna scadenza.')); return box; }
    box.appendChild(el('div', { class: 'tab-scroll' }, el('table', null,
      el('thead', null, el('tr', null, el('th', null, 'Data'), el('th', { class: 'num' }, 'Giorni'), conAzienda ? el('th', null, 'Azienda') : null, el('th', null, 'Cosa'), el('th', null, 'Note'))),
      el('tbody', null, sc.map(function (s) {
        var col = s.fatto ? 'verde' : s.giorni < 0 ? 'rosso' : s.giorni <= 30 ? 'giallo' : null;
        return el('tr', null, el('td', null, dot(col, NOMI_COLORE[col]), ' ', data(s.data)),
          el('td', { class: 'num' }, s.fatto ? 'fatto' : s.giorni),
          conAzienda ? el('td', null, el('a', { href: '#/azienda/' + s.azienda_id + '/scadenze' }, s.azienda)) : null,
          el('td', null, s.titolo), el('td', { class: 'fine' }, s.note || ''));
      })))));
    return box;
  }

  function nuovaAzienda() {
    var obj = {};
    var dlg = el('dialog', null, el('h2', null, 'Nuova azienda'),
      el('p', { class: 'fine' }, 'Basta la ragione sociale: codice fiscale, forma e ATECO si completano dal bilancio XBRL.'),
      form([{ k: 'ragione_sociale', et: 'Ragione sociale', largo: true }, { k: 'codice_fiscale', et: 'Codice fiscale' },
        { k: 'referente', et: 'Referente' }], obj),
      el('div', { class: 'barra-salva' },
        el('button', { type: 'button', class: 'btn btn-pri', onclick: function () {
          api('POST', '/api/aziende', obj).then(function (r) { dlg.close(); dlg.remove(); sporco = false; location.hash = '#/azienda/' + r.id + '/bilancio'; })
            .catch(function (e) { toast(e.message, true); });
        } }, 'Crea'),
        el('button', { type: 'button', class: 'btn', onclick: function () { dlg.close(); dlg.remove(); sporco = false; } }, 'Annulla')));
    document.body.appendChild(dlg);
    dlg.showModal();
  }

  // ---------- azienda ----------
  var TABS = [['sintesi', 'Sintesi'], ['bilancio', 'Bilancio'], ['tfr', 'TFR'], ['tfm', 'TFM'], ['rischi', 'Rischi'],
    ['crisi', 'Crisi'], ['scadenze', 'Scadenze'], ['report', 'Report']];

  function vistaAzienda(id, tab) {
    if (AN && String(AN.azienda.id) === String(id)) { disegnaAzienda(tab); return; }
    main.replaceChildren(el('p', { class: 'caricamento' }, 'Caricamento…'));
    api('GET', '/api/aziende/' + id).then(function (an) { AN = an; disegnaAzienda(tab); })
      .catch(function (e) { main.replaceChildren(el('div', { class: 'card' }, e.message, ' ', el('a', { href: '#/' }, 'Torna al portafoglio'))); });
  }

  function disegnaAzienda(tab) {
    sporco = false;
    var az = AN.azienda;
    document.title = az.ragione_sociale + ' – Analisi PMI';
    var info = [az.forma, az.ateco ? 'ATECO ' + az.ateco : '', az.codice_fiscale ? 'CF ' + az.codice_fiscale : '', az.sede].filter(Boolean).join(' · ');
    var testa = el('div', { class: 'testa' },
      el('div', null, el('h1', null, az.ragione_sociale), el('p', { class: 'muted' }, info || 'Anagrafica da completare'),
        az.esempio ? el('p', { class: 'fine' }, 'Azienda di esempio con dati inventati.') : null),
      el('div', { class: 'azioni' },
        el('button', { type: 'button', class: 'btn btn-sm', onclick: modificaAnagrafica }, 'Anagrafica'),
        el('button', { type: 'button', class: 'btn btn-sm btn-peri', onclick: function () {
          if (!confirm('Eliminare ' + az.ragione_sociale + ' e tutti i suoi dati? L\'operazione non si annulla.')) return;
          api('DELETE', '/api/aziende/' + az.id).then(function () { AN = null; location.hash = '#/'; });
        } }, 'Elimina')));
    var nav = el('nav', { class: 'tabs', 'aria-label': 'Sezioni' }, TABS.map(function (t) {
      return el('a', { href: '#/azienda/' + az.id + '/' + t[0], 'aria-current': t[0] === tab ? 'page' : null }, t[1]);
    }));
    var corpo = el('div');
    main.replaceChildren(testa, nav, corpo);
    var fn = { sintesi: tabSintesi, bilancio: tabBilancio, tfr: tabTfr, tfm: tabTfm, rischi: tabRischi, crisi: tabCrisi, scadenze: tabScadenze, report: tabReport }[tab] || tabSintesi;
    fn(corpo);
  }

  function modificaAnagrafica() {
    var obj = Object.assign({}, AN.azienda);
    var dlg = el('dialog', null, el('h2', null, 'Anagrafica'),
      form([{ k: 'ragione_sociale', et: 'Ragione sociale', largo: true }, { k: 'codice_fiscale', et: 'Codice fiscale' }, { k: 'forma', et: 'Forma giuridica' },
        { k: 'ateco', et: 'Codice ATECO' }, { k: 'sede', et: 'Sede' }, { k: 'referente', et: 'Referente' }, { k: 'note', et: 'Note', tipo: 'area', largo: true }], obj),
      el('div', { class: 'barra-salva' },
        el('button', { type: 'button', class: 'btn btn-pri', onclick: function () {
          api('PUT', '/api/aziende/' + AN.azienda.id, obj).then(function () { dlg.close(); dlg.remove(); toast('Salvato'); return ricarica(); })
            .catch(function (e) { toast(e.message, true); });
        } }, 'Salva'),
        el('button', { type: 'button', class: 'btn', onclick: function () { dlg.close(); dlg.remove(); sporco = false; } }, 'Annulla')));
    document.body.appendChild(dlg);
    dlg.showModal();
  }

  function ultimoIndici() { var a = AN.indici.anni; return a.length ? a[a.length - 1] : null; }

  // ---------- sintesi ----------
  function tabSintesi(box) {
    var u = AN.bilancio_ultimo, ui = ultimoIndici(), g = AN.indici.giudizio, t = AN.tfr, r = AN.rischi.conteggio;
    var v = ui ? ui.valori : {};
    box.appendChild(el('div', { class: 'tiles' },
      tile('Solidità ' + (AN.anno_ultimo || ''), g.colore ? g.testo : 'n.d.', g.colore ? (g.rossi.length + (g.rossi.length === 1 ? ' indice' : ' indici') + ' in rosso, ' + g.gialli.length + ' in giallo') : 'Carica un bilancio', g.colore),
      tile('Ricavi', euroK(u.ricavi), v.crescita_ricavi != null ? ((v.crescita_ricavi >= 0 ? '+' : '') + pct(v.crescita_ricavi) + ' sull\'anno prima') : null),
      tile('EBITDA', euroK(v.ebitda), v.ebitda_margin != null ? pct(v.ebitda_margin) + ' del valore della produzione' : null),
      tile('Posizione finanziaria netta', euroK(v.pfn), v.pfn_ebitda != null ? fmtIndice(v.pfn_ebitda, 'x') + ' volte l\'EBITDA' : null),
      tile('Debito TFR', euroK(t.debito), t.scopertura ? 'scoperto ' + euroK(t.scopertura) : null, t.scopertura > 0 ? 'giallo' : null),
      tile('Coperture', (r.rosso || 0) + ' scoperte', (r.giallo || 0) + ' parziali, ' + (r.grigio || 0) + ' da verificare', r.rosso ? 'rosso' : r.giallo ? 'giallo' : 'verde'),
      tile('Segnali di crisi', String(AN.crisi.segnali_presenti), AN.crisi.assetti_mancanti + ' assetti da completare', AN.crisi.segnali_presenti ? 'rosso' : 'verde')));
    var prop = el('div', { class: 'card' }, el('h2', null, 'Proposte operative'));
    if (!AN.proposte.length) prop.appendChild(el('p', { class: 'muted' }, 'Nessuna proposta: completa le sezioni per ottenere indicazioni.'));
    AN.proposte.forEach(function (p) {
      prop.appendChild(el('div', { class: 'proposta' },
        el('span', { class: 'prio p' + p.priorita }, ['', 'Urgente', 'Importante', 'Utile'][p.priorita]),
        el('div', null, el('div', { class: 'area' }, p.area), el('strong', null, p.titolo), p.dettaglio ? el('div', { class: 'muted' }, p.dettaglio) : null)));
    });
    var completezza = el('div', { class: 'card' }, el('h2', null, 'Dati raccolti'),
      esito(AN.bilanci.length ? 'verde' : 'rosso', 'Bilanci: ' + (AN.bilanci.length ? AN.bilanci.map(function (b) { return b.anno; }).join(', ') : 'nessuno'), 'bilancio'),
      esito(t.metodo === 'dipendenti' ? 'verde' : t.metodo ? 'giallo' : 'rosso', t.metodo === 'dipendenti' ? 'Elenco dipendenti caricato' : 'TFR stimato dal bilancio: manca l\'elenco dipendenti', 'tfr'),
      esito(AN.tfm.amministratori.length ? 'verde' : 'giallo', AN.tfm.amministratori.length ? AN.tfm.amministratori.length + ' amministratori simulati' : 'Amministratori non inseriti', 'tfm'),
      esito(r.grigio ? 'giallo' : 'verde', r.grigio ? r.grigio + ' rischi da verificare' : 'Mappa dei rischi completa', 'rischi'),
      esito(AN.crisi.segnali.some(function (s) { return s.colore === 'grigio'; }) ? 'giallo' : 'verde', 'Segnali di crisi', 'crisi'));
    box.appendChild(el('div', { class: 'griglia' }, prop, completezza));
  }
  function esito(colore, testo, tab) {
    return el('div', { class: 'esito' }, dot(colore, NOMI_COLORE[colore]),
      el('div', null, tab ? el('a', { href: '#/azienda/' + AN.azienda.id + '/' + tab }, testo) : testo));
  }

  // ---------- bilancio ----------
  function tabBilancio(box) {
    var imp = el('div', { class: 'card' }, el('h2', null, 'Carica il bilancio XBRL'),
      el('p', { class: 'muted' }, 'Il file XBRL (.xbrl, oppure .zip o .p7m) che si scarica dal Registro Imprese o che ti passa il commercialista. ' +
        'Ogni file contiene l\'esercizio e quello precedente. I dati inseriti a mano non vengono sovrascritti.'),
      el('div', { class: 'barra-salva' }, bottoneFile('Scegli file XBRL…', '.xbrl,.xml,.zip,.p7m', function (f, buf) {
        return api('POST', '/api/aziende/' + AN.azienda.id + '/xbrl', buf).then(function (r) {
          var msg = 'Importati: ' + (r.salvati.join(', ') || 'nessun esercizio') + ' (' + r.tipo + ')';
          if (r.saltati.length) msg += '. Non sovrascritti perché inseriti a mano: ' + r.saltati.join(', ');
          toast(msg); return ricarica();
        });
      }), el('button', { type: 'button', class: 'btn', onclick: aggiungiAnno }, '+ Esercizio a mano')));
    box.appendChild(imp);
    if (!AN.bilanci.length) return;
    box.appendChild(tabellaIndici());
    box.appendChild(tabellaDati());
  }

  function aggiungiAnno() {
    var anno = prompt('Anno dell\'esercizio (es. 2025):');
    if (!anno || !/^\d{4}$/.test(anno.trim())) return;
    api('PUT', '/api/aziende/' + AN.azienda.id + '/bilanci/' + anno.trim(), { dati: {} }).then(ricarica).catch(function (e) { toast(e.message, true); });
  }

  function tabellaIndici() {
    var anni = AN.indici.anni;
    var righe = AN.indici.definizioni.map(function (d) {
      return el('tr', null, el('th', { scope: 'row', style: 'text-transform:none;letter-spacing:0;font-size:.84rem;color:var(--text);font-weight:600;position:static' },
        d.etichetta, ' ', el('button', { type: 'button', class: 'btn btn-ghost btn-sm', 'aria-label': 'Spiegazione', onclick: function () { toast(d.spiegazione || d.etichetta); } }, 'ⓘ')),
        anni.map(function (a) {
          var v = a.valori[d.chiave], c = a.colori[d.chiave];
          return el('td', { class: 'num' }, fmtIndice(v, d.unita), ' ', dot(c, NOMI_COLORE[c]));
        }));
    });
    return el('div', { class: 'card' }, el('h2', null, 'Indici'),
      el('div', { class: 'legenda' }, ['verde', 'giallo', 'rosso'].map(function (c) { return el('span', null, dot(c), NOMI_COLORE[c]); }),
        el('span', null, 'senza pallino: solo informativo')),
      el('div', { class: 'tab-scroll' }, el('table', null,
        el('thead', null, el('tr', null, el('th', null, 'Indice'), anni.map(function (a) { return el('th', { class: 'num' }, a.anno); }))),
        el('tbody', null, righe))),
      el('p', { class: 'fine' }, 'Soglie indicative e uguali per tutti i settori: si cambiano in config.yaml. n.s. = non significativo (es. EBITDA negativo).'));
  }

  function tabellaDati() {
    var bil = AN.bilanci.map(function (b) { return { anno: b.anno, chiusura: b.chiusura, tipo: b.tipo, fonte: b.fonte, dati: Object.assign({}, b.dati) }; });
    var voci = P.voci.concat([{ chiave: 'pfn_manuale', etichetta: 'PFN inserita a mano (sostituisce il calcolo)', sezione: 'nota' }]);
    var righe = [], sezCorr = null;
    voci.forEach(function (v) {
      if (v.sezione !== sezCorr) { sezCorr = v.sezione; righe.push(el('tr', { class: 'sez' }, el('td', { colspan: bil.length + 1 }, P.sezioni_bilancio[v.sezione]))); }
      righe.push(el('tr', null, el('td', null, v.etichetta), bil.map(function (b) {
        return el('td', { class: 'num' }, campo({ k: v.chiave, et: v.etichetta + ' ' + b.anno, tipo: 'num', dec: 0, nolabel: true }, b.dati));
      })));
    });
    var fonti = { manuale: 'a mano', xbrl: 'XBRL', 'xbrl-precedente': 'XBRL (anno prec.)' };
    return el('div', { class: 'card' }, el('h2', null, 'Dati di bilancio'),
      el('p', { class: 'fine' }, 'Puoi correggere o completare i valori (es. un bilancio in PDF o una situazione infrannuale). Salvando, l\'esercizio diventa "a mano" e non viene più sovrascritto dagli import.'),
      el('div', { class: 'tab-scroll' }, el('table', null,
        el('thead', null, el('tr', null, el('th', null, 'Voce'), bil.map(function (b) {
          return el('th', { class: 'num' }, b.anno, el('div', { class: 'fine', style: 'text-transform:none' }, (fonti[b.fonte] || b.fonte) + (b.tipo ? ' · ' + b.tipo : '')));
        }))),
        el('tbody', null, righe,
          el('tr', null, el('td'), bil.map(function (b) {
            return el('td', { class: 'num' },
              bottoneSalva('Salva ' + b.anno, function () {
                return api('PUT', '/api/aziende/' + AN.azienda.id + '/bilanci/' + b.anno, { dati: b.dati, chiusura: b.chiusura, tipo: b.tipo })
                  .then(function () { toast('Esercizio ' + b.anno + ' salvato'); return ricarica(); });
              }), ' ',
              el('button', { type: 'button', class: 'btn btn-sm btn-peri', onclick: function () {
                if (!confirm('Eliminare l\'esercizio ' + b.anno + '?')) return;
                api('DELETE', '/api/aziende/' + AN.azienda.id + '/bilanci/' + b.anno).then(ricarica);
              } }, 'Elimina'));
          }))))));
  }

  // ---------- TFR ----------
  var SPEC_TFR = [
    { k: 'inflazione', et: 'Inflazione attesa', tipo: 'pct' },
    { k: 'crescita_retribuzioni', et: 'Crescita retribuzioni', tipo: 'pct' },
    { k: 'turnover', et: 'Uscite volontarie annue', tipo: 'pct', aiuto: 'dimissioni e licenziamenti' },
    { k: 'anticipi', et: 'Richieste di anticipo annue', tipo: 'pct', aiuto: 'tra chi ha 8+ anni di anzianità' },
    { k: 'eta_pensione', et: 'Età di pensione', tipo: 'num' },
    { k: 'orizzonte', et: 'Orizzonte (anni)', tipo: 'num' },
    { k: 'rendimento_polizza', et: 'Rendimento netto polizza', tipo: 'pct' },
    { k: 'capitale_polizza', et: 'Già accantonato in polizza (€)', tipo: 'num', dec: 0 },
    { k: 'stress_persone', et: 'Scenario: persone che escono subito', tipo: 'num' }
  ];
  function tabTfr(box) {
    var t = AN.tfr;
    var par = Object.assign({}, AN.tfr_parametri);
    if (t.metodo) {
      box.appendChild(el('div', { class: 'tiles' },
        tile('Debito TFR in azienda', euroK(t.debito), t.metodo === 'bilancio' ? 'dal bilancio ' + AN.anno_ultimo : 'dall\'elenco dipendenti'),
        tile('Liquidità + polizza', euroK((t.liquidita || 0) + (t.capitale_polizza || 0)), t.copertura != null ? 'copre il ' + pct(t.copertura, 0) + ' del debito' : null,
          t.copertura == null ? null : t.copertura >= 1 ? 'verde' : t.copertura >= 0.5 ? 'giallo' : 'rosso'),
        tile('Uscite attese in 5 anni', euroK(t.uscite_5_anni), 'valore atteso'),
        t.stress ? tile('Se escono le ' + t.stress.persone.length + ' persone con più TFR', euroK(t.stress.importo), t.stress.persone.join(', ')) : null,
        tile('Premio annuo per coprire le uscite', euroK(t.premio_flussi), 'per ' + t.anni.length + ' anni'),
        tile('Premio annuo per accumulare il debito', euroK(t.premio_debito), 'debito atteso a fine orizzonte ' + euroK(t.debito_fine_orizzonte))));
      t.avvisi.forEach(function (a) { box.appendChild(el('div', { class: 'avviso' }, a)); });
      if (t.metodo === 'bilancio') box.appendChild(el('div', { class: 'avviso' }, 'Stima dal solo bilancio (uscite medie). Carica l\'elenco dei dipendenti per una proiezione per persona.'));
      box.appendChild(graficoTfr(t.anni));
      box.appendChild(tabellaTfr(t.anni));
    } else {
      box.appendChild(el('div', { class: 'card' }, el('p', null, t.messaggio)));
    }
    box.appendChild(el('div', { class: 'card' }, el('h2', null, 'Ipotesi'),
      el('p', { class: 'fine' }, 'Rivalutazione del fondo: 1,5% + 75% dell\'inflazione, al netto dell\'imposta del 17% (tasso netto ' + pct(t.tasso_rivalutazione_netto || 0, 2) + '). ' +
        'Quota annua: retribuzione/13,5 meno 0,50%. Anticipo: fino al 70% dopo 8 anni.'),
      form(SPEC_TFR, par),
      el('div', { class: 'barra-salva' }, bottoneSalva('Salva ipotesi', function () {
        var dati = {}; SPEC_TFR.forEach(function (s) { if (par[s.k] !== '' && par[s.k] != null) dati[s.k] = par[s.k]; });
        return salvaSezione('tfr', dati);
      }))));
    box.appendChild(editorDipendenti());
  }

  function graficoTfr(anni) {
    var serie = [['pensionamenti', 'Pensionamenti', 'var(--c0)'], ['dimissioni', 'Dimissioni e licenziamenti', 'var(--c1)'], ['anticipi', 'Anticipi', 'var(--c2)']];
    var W = 1000, H = 300, ml = 70, mr = 10, mt = 12, mb = 28;
    var max = Math.max.apply(null, anni.map(function (a) { return a.uscite; }).concat([1]));
    var passo = Math.pow(10, Math.floor(Math.log10(max)));
    if (max / passo <= 2) passo /= 4; else if (max / passo <= 5) passo /= 2;
    var top = Math.ceil(max / passo) * passo;
    var s = svg('svg', { viewBox: '0 0 ' + W + ' ' + H, role: 'img', 'aria-label': 'Uscite TFR attese per anno' });
    for (var g = 0; g <= top + 1e-9; g += passo) {
      var y = mt + (H - mt - mb) * (1 - g / top);
      s.appendChild(svg('line', { x1: ml, x2: W - mr, y1: y, y2: y, class: g === 0 ? 'asse' : 'griglia-l' }));
      var tx = svg('text', { x: ml - 6, y: y + 4, 'text-anchor': 'end' }); tx.textContent = euroK(g).replace(' €', ''); s.appendChild(tx);
    }
    var bw = (W - ml - mr) / anni.length;
    anni.forEach(function (a, i) {
      var x = ml + i * bw + bw * 0.18, w = bw * 0.64, base = H - mb;
      serie.forEach(function (se) {
        var v = a[se[0]] || 0; if (v <= 0) return;
        var h = (H - mt - mb) * v / top;
        s.appendChild(svg('rect', { x: x, y: base - h, width: w, height: Math.max(h - 1, 0.5), fill: se[2], rx: 2 }));
        base -= h;
      });
      var lab = svg('text', { x: x + w / 2, y: H - 8, 'text-anchor': 'middle' }); lab.textContent = a.anno; s.appendChild(lab);
      var hit = svg('rect', { x: ml + i * bw, y: mt, width: bw, height: H - mt - mb, fill: 'transparent' });
      hit.addEventListener('mousemove', function (ev) {
        mostraTip(ev, String(a.anno), serie.map(function (se) { return se[1] + ': ' + euro(a[se[0]]); }).concat(['Totale: ' + euro(a.uscite)]));
      });
      hit.addEventListener('mouseleave', nascondiTip);
      s.appendChild(hit);
    });
    return el('div', { class: 'card grafico' }, el('h2', null, 'Uscite TFR attese per anno'),
      el('div', { class: 'legenda' }, serie.map(function (se) { return el('span', null, el('span', { class: 'sw', style: 'background:' + se[2] }), se[1]); })), s,
      el('p', { class: 'fine' }, 'Valori attesi: le uscite volontarie e gli anticipi sono pesati con le probabilità annue delle ipotesi. Dettaglio nella tabella sotto.'));
  }

  function tabellaTfr(anni) {
    var col = [['anno', 'Anno'], ['pensionamenti', 'Pensionamenti'], ['dimissioni', 'Dimissioni'], ['anticipi', 'Anticipi'], ['uscite', 'Totale uscite'],
      ['accantonamento', 'Quote maturate'], ['debito_fine', 'Debito a fine anno'], ['saldo_polizza', 'Saldo polizza']];
    return el('div', { class: 'card' }, el('details', null, el('summary', null, 'Tabella anno per anno'),
      el('div', { class: 'tab-scroll' }, el('table', null,
        el('thead', null, el('tr', null, col.map(function (c, i) { return el('th', { class: i ? 'num' : null }, c[1]); }))),
        el('tbody', null, anni.map(function (a) {
          return el('tr', null, col.map(function (c, i) { return el('td', { class: i ? 'num' : null }, i ? euro(a[c[0]]) : a.anno); }));
        })))),
      el('p', { class: 'fine' }, 'Saldo polizza: con il premio annuo "per coprire le uscite", versato a inizio anno, dopo il pagamento delle uscite.')));
  }

  function editorDipendenti() {
    var elenco = ((AN.sezioni.dipendenti || {}).elenco || []).map(function (d) { return Object.assign({}, d); });
    var perNome = {}; (AN.tfr.dipendenti || []).forEach(function (d) { perNome[d.nome] = d; });
    var corpo = el('tbody');
    var cols = [{ k: 'nome', et: 'Nome o codice' }, { k: 'data_nascita', et: 'Nascita', tipo: 'date' }, { k: 'data_assunzione', et: 'Assunzione', tipo: 'date' },
      { k: 'ral', et: 'Retribuzione annua', tipo: 'num', dec: 0 }, { k: 'tfr_azienda', et: 'TFR in azienda', tipo: 'num', dec: 0 },
      { k: 'destinazione', et: 'Destinazione TFR', tipo: 'select', opz: [['azienda', 'Azienda'], ['fondo', 'Fondo pensione'], ['tesoreria', 'Tesoreria INPS']] },
      { k: 'eta_uscita', et: 'Età uscita', tipo: 'num', ph: String(P.tfr.eta_pensione) }];
    function disegna() {
      corpo.replaceChildren.apply(corpo, elenco.map(function (d, i) {
        var calc = perNome[d.nome];
        return el('tr', null, cols.map(function (c) {
          return el('td', { class: c.tipo === 'num' ? 'num' : null }, campo(Object.assign({ nolabel: true }, c, { et: c.et + ' riga ' + (i + 1) }), d));
        }), el('td', { class: 'num fine' }, calc && calc.anno_pensione ? calc.anno_pensione : ''),
        el('td', null, el('button', { type: 'button', class: 'btn btn-sm btn-ghost', 'aria-label': 'Elimina riga', onclick: function () { elenco.splice(i, 1); sporco = true; disegna(); } }, '✕')));
      }));
      tot.textContent = elenco.length + ' dipendenti · TFR in azienda ' + euro(elenco.reduce(function (s, d) { return s + (Number(d.tfr_azienda) || 0); }, 0));
    }
    var tot = el('span', { class: 'muted' });
    disegna();
    return el('div', { class: 'card' }, el('h2', null, 'Dipendenti'),
      el('p', { class: 'fine' }, 'Dal prospetto TFR del consulente del lavoro. Per la privacy puoi usare un codice al posto del nome. ' +
        'Con "Fondo pensione" o "Tesoreria INPS" la quota annua non resta in azienda: resta solo il TFR già maturato.'),
      el('div', { class: 'barra-salva' },
        bottoneFile('Importa CSV o Excel…', '.csv,.xlsx,.xlsm,.txt', function (f, buf) {
          return api('POST', '/api/importa-dipendenti', buf, { 'X-Nome-File': f.name }).then(function (r) {
            if (elenco.length && !confirm('Sostituire i ' + elenco.length + ' dipendenti attuali con i ' + r.elenco.length + ' del file?')) return;
            elenco = r.elenco; sporco = true; disegna(); toast(r.elenco.length + ' dipendenti letti: controlla e salva');
          });
        }),
        el('a', { class: 'btn', href: '/api/modello-dipendenti.csv' }, 'Scarica modello CSV'),
        el('button', { type: 'button', class: 'btn', onclick: function () { elenco.push({ destinazione: 'azienda' }); sporco = true; disegna(); } }, '+ Riga'),
        tot),
      el('div', { class: 'tab-scroll' }, el('table', null,
        el('thead', null, el('tr', null, cols.map(function (c) { return el('th', { class: c.tipo === 'num' ? 'num' : null }, c.et); }), el('th', { class: 'num' }, 'Anno pensione'), el('th'))),
        corpo)),
      el('div', { class: 'barra-salva' }, bottoneSalva('Salva dipendenti e ricalcola', function () { return salvaSezione('dipendenti', { elenco: elenco }); })));
  }

  // ---------- TFM ----------
  var SPEC_TFM_PAR = [
    { k: 'ires', et: 'IRES', tipo: 'pct' },
    { k: 'aliquota_marginale', et: 'Aliquota marginale amministratore', tipo: 'pct', aiuto: 'IRPEF + addizionali' },
    { k: 'aliquota_separata', et: 'Aliquota tassazione separata', tipo: 'pct', aiuto: 'stima: da verificare' },
    { k: 'contributi_gs', et: 'Contributi Gestione separata sul compenso', tipo: 'pct' },
    { k: 'contributi_tfm', et: 'Contributi sul TFM', tipo: 'pct', aiuto: 'verifica con il consulente' },
    { k: 'rendimento_polizza', et: 'Rendimento netto polizza', tipo: 'pct' }
  ];
  var SPEC_AMM = [
    { k: 'nome', et: 'Nome o ruolo' }, { k: 'compenso', et: 'Compenso annuo lordo (€)', tipo: 'num', dec: 0 },
    { k: 'percentuale', et: 'TFM sul compenso', tipo: 'pct', aiuto: 'riferimento 7,41% (1/13,5)' },
    { k: 'anni', et: 'Anni di mandato', tipo: 'num' },
    { k: 'data_inizio_mandato', et: 'Inizio mandato', tipo: 'date' }, { k: 'data_scadenza_mandato', et: 'Scadenza mandato', tipo: 'date' },
    { k: 'data_atto', et: 'Data atto che prevede il TFM', tipo: 'date', aiuto: 'delibera o statuto' },
    { k: 'data_certa', et: 'L\'atto ha data certa?', tipo: 'select', opz: SN() },
    { k: 'polizza', et: 'Coperto da polizza?', tipo: 'select', opz: SN() }
  ];
  function tabTfm(box) {
    var sez = AN.sezioni.tfm || {};
    var amm = (sez.amministratori || []).map(function (a) { return Object.assign({}, a); });
    var par = Object.assign({}, AN.tfm_parametri, sez.parametri || {});
    var risultati = {}; AN.tfm.amministratori.forEach(function (r) { risultati[r.nome] = r; });
    var comp = AN.bilancio_ultimo.compensi_amministratori;
    if (comp) box.appendChild(el('p', { class: 'muted' }, 'Compensi amministratori in bilancio ' + AN.anno_ultimo + ': ' + euro(comp) + '.'));
    var lista = el('div');
    function salva() { return salvaSezione('tfm', { amministratori: amm, parametri: datiPar() }); }
    function datiPar() { var d = {}; SPEC_TFM_PAR.forEach(function (s) { if (par[s.k] !== '' && par[s.k] != null) d[s.k] = par[s.k]; }); return d; }
    function disegna() {
      lista.replaceChildren.apply(lista, amm.map(function (a, i) {
        var r = risultati[a.nome];
        return el('div', { class: 'card' }, el('h3', null, a.nome || 'Amministratore ' + (i + 1)), form(SPEC_AMM, a),
          r ? risultatoTfm(r) : el('p', { class: 'fine' }, 'Salva per vedere la simulazione.'),
          el('div', { class: 'barra-salva' }, el('button', { type: 'button', class: 'btn btn-sm btn-peri', onclick: function () { amm.splice(i, 1); sporco = true; disegna(); } }, 'Rimuovi')));
      }));
    }
    disegna();
    box.appendChild(el('div', { class: 'barra-salva no-print', style: 'margin:0 0 1rem' },
      el('button', { type: 'button', class: 'btn', onclick: function () { amm.push({ percentuale: P.tfm.percentuale, anni: 3 }); sporco = true; disegna(); } }, '+ Amministratore'),
      bottoneSalva(null, salva)));
    box.appendChild(lista);
    box.appendChild(el('div', { class: 'card' }, el('h2', null, 'Ipotesi fiscali e previdenziali'),
      el('p', { class: 'fine' }, 'Valori indicativi, validi per tutti gli amministratori di questa azienda. Il confronto serve a mostrare l\'ordine di grandezza, non sostituisce il parere del commercialista.'),
      form(SPEC_TFM_PAR, par), el('div', { class: 'barra-salva' }, bottoneSalva(null, salva))));
  }
  function risultatoTfm(r) {
    var righe = [['Costo lordo per la società', 'costo_lordo'], ['Risparmio di imposte (IRES)', 'risparmio_imposte'], ['Costo netto per la società', 'costo_netto'],
      ['Netto all\'amministratore', 'netto_amministratore']];
    return el('div', null,
      el('div', { class: 'tiles', style: 'margin:.8rem 0' }, tile('Accantonamento annuo', euro(r.accantonamento_annuo)), tile('TFM a fine mandato', euro(r.totale)),
        tile('Capitale polizza stimato', euro(r.capitale_polizza)),
        tile('Netto in più rispetto al compenso', euro(r.vantaggio_netto), null, r.vantaggio_netto > 0 ? 'verde' : 'giallo')),
      el('div', { class: 'tab-scroll' }, el('table', null,
        el('thead', null, el('tr', null, el('th', null, ''), r.scenari.map(function (s) { return el('th', { class: 'num', style: 'text-transform:none' }, s.nome); }))),
        el('tbody', null, righe.map(function (x) {
          return el('tr', null, el('td', null, x[0]), r.scenari.map(function (s) { return el('td', { class: 'num' }, euro(s[x[1]])); }));
        }), el('tr', null, el('td', null, 'Netto ogni 100 € di costo netto'), r.scenari.map(function (s) { return el('td', { class: 'num' }, s.resa == null ? '—' : intero(s.resa * 100) + ' €'); }))))),
      el('div', { style: 'margin-top:.6rem' }, r.verifiche.map(function (v) { return el('div', { class: 'esito' }, dot(v.colore, NOMI_COLORE[v.colore]), el('div', null, v.testo)); })));
  }

  // ---------- rischi ----------
  var STATI = [['da_verificare', 'Da verificare'], ['protetto', 'Coperto'], ['parziale', 'Parziale'], ['scoperto', 'Scoperto'], ['non_applicabile', 'Non applicabile']];
  function tabRischi(box) {
    var dati = JSON.parse(JSON.stringify(AN.sezioni.rischi || {}));
    var r = AN.rischi;
    function salva() { return salvaSezione('rischi', dati); }
    box.appendChild(el('div', { class: 'testa' },
      el('div', { class: 'legenda' }, pill('rosso', (r.conteggio.rosso || 0) + ' scoperti'), pill('giallo', (r.conteggio.giallo || 0) + ' parziali'),
        pill('grigio', (r.conteggio.grigio || 0) + ' da verificare'), pill('verde', (r.conteggio.verde || 0) + ' coperti')),
      el('div', { class: 'azioni' }, bottoneSalva(null, salva))));
    var griglia = el('div', { class: 'griglia' });
    r.voci.forEach(function (v) {
      var d = dati[v.chiave] = dati[v.chiave] || {};
      var c = el('div', { class: 'rischio ' + (v.colore || '') + (v.chiave === 'persona_chiave' || v.chiave === 'soci' ? ' largo' : '') },
        el('h3', null, v.titolo, v.colore ? pill(v.colore, NOMI_COLORE[v.colore]) : el('span', { class: 'fine' }, 'n.a.')),
        el('p', { class: 'perche' }, v.perche),
        v.testo ? el('p', null, v.testo) : null,
        v.fabbisogno != null ? el('p', null, el('strong', null, 'Fabbisogno ' + euro(v.fabbisogno)), ' · coperto ' + euro(v.coperto) + ' · scoperto ', el('strong', null, euro(v.gap))) : null);
      if (v.chiave === 'persona_chiave') c.appendChild(editorPersone(d));
      else if (v.chiave === 'soci') c.appendChild(editorSoci(d));
      else if (v.chiave === 'passaggio') c.appendChild(form([{ k: 'eta_titolare', et: 'Età del titolare', tipo: 'num' },
        { k: 'successore', et: 'Successore', tipo: 'select', opz: [['', '—'], ['si', 'Individuato'], ['in_corso', 'In via di definizione'], ['no', 'Non individuato']] },
        { k: 'strumenti', et: 'Strumenti successori adottati', tipo: 'select', opz: SN() }], d));
      else c.appendChild(form([{ k: 'stato', et: 'Stato', tipo: 'select', opz: STATI }, { k: 'compagnia', et: 'Compagnia' },
        { k: 'massimale', et: 'Massimale / capitale (€)', tipo: 'num', dec: 0 }, { k: 'premio', et: 'Premio annuo (€)', tipo: 'num', dec: 0 },
        { k: 'scadenza', et: 'Scadenza', tipo: 'date' }, { k: 'note', et: 'Note', largo: true }], d));
      griglia.appendChild(c);
    });
    box.appendChild(griglia);
    box.appendChild(el('div', { class: 'barra-salva' }, bottoneSalva(null, salva)));
  }
  function tabellaEditabile(righe, cols, nuova) {
    var corpo = el('tbody');
    function disegna() {
      corpo.replaceChildren.apply(corpo, righe.map(function (x, i) {
        return el('tr', null, cols.map(function (c) { return el('td', { class: c.tipo === 'num' ? 'num' : null }, campo(Object.assign({ nolabel: true }, c), x)); }),
          el('td', null, el('button', { type: 'button', class: 'btn btn-sm btn-ghost', 'aria-label': 'Elimina riga', onclick: function () { righe.splice(i, 1); sporco = true; disegna(); } }, '✕')));
      }));
    }
    disegna();
    return el('div', null, el('div', { class: 'tab-scroll' }, el('table', null,
      el('thead', null, el('tr', null, cols.map(function (c) { return el('th', { class: c.tipo === 'num' ? 'num' : null, style: 'text-transform:none' }, c.et); }), el('th'))), corpo)),
      el('button', { type: 'button', class: 'btn btn-sm', style: 'margin-top:.4rem', onclick: function () { righe.push(nuova()); sporco = true; disegna(); } }, '+ Aggiungi'));
  }
  function editorPersone(d) {
    d.persone = d.persone || [];
    return tabellaEditabile(d.persone, [{ k: 'nome', et: 'Nome' }, { k: 'ruolo', et: 'Ruolo' },
      { k: 'quota_margine', et: '% margine legato', tipo: 'num' }, { k: 'anni_sostituzione', et: 'Anni per sostituirlo', tipo: 'num', ph: String(P.rischi.anni_sostituzione_persona_chiave) },
      { k: 'costo_sostituzione', et: 'Costi di sostituzione (€)', tipo: 'num', dec: 0 }, { k: 'capitale_assicurato', et: 'Capitale assicurato (€)', tipo: 'num', dec: 0 }],
    function () { return {}; });
  }
  function editorSoci(d) {
    d.elenco = d.elenco || [];
    var stima = AN.rischi.valore_azienda_stimato;
    return el('div', null,
      form([{ k: 'accordo', et: 'Accordo tra soci per il riacquisto delle quote', tipo: 'select', opz: SN() },
        { k: 'valore_azienda', et: 'Valore dell\'azienda (€)', tipo: 'num', dec: 0, ph: stima ? inNumero(stima, 0) : '',
          aiuto: stima ? 'Vuoto = stima ' + P.rischi.multiplo_ebitda_valutazione + ' × EBITDA − PFN' : null }], d),
      tabellaEditabile(d.elenco, [{ k: 'nome', et: 'Socio' }, { k: 'quota', et: 'Quota %', tipo: 'num' }, { k: 'eta', et: 'Età', tipo: 'num' },
        { k: 'capitale_assicurato', et: 'Capitale assicurato (€)', tipo: 'num', dec: 0 }], function () { return {}; }));
  }

  // ---------- crisi ----------
  function tabCrisi(box) {
    var d = Object.assign({}, AN.sezioni.crisi || {});
    var c = AN.crisi;
    function salva() { return salvaSezione('crisi', d); }
    var monte = c.monte_salari_mensile;
    box.appendChild(el('div', { class: 'griglia' },
      el('div', { class: 'card' }, el('h2', null, 'Segnali di allarme (art. 3 c. 4 CCII)'),
        c.segnali.map(function (s) { return el('div', { class: 'esito' }, dot(s.colore, NOMI_COLORE[s.colore]), el('div', null, el('strong', null, s.titolo), el('div', null, s.testo))); })),
      el('div', { class: 'card' }, el('h2', null, 'Patrimonio netto'),
        c.patrimonio.length ? c.patrimonio.map(function (s) { return el('div', { class: 'esito' }, dot(s.colore, NOMI_COLORE[s.colore]), el('div', null, s.testo)); })
          : el('p', { class: 'muted' }, 'Serve un bilancio con patrimonio netto e capitale.'))));
    box.appendChild(el('div', { class: 'card' }, el('h2', null, 'Dati per i segnali'),
      el('p', { class: 'fine' }, 'Dallo scadenzario dell\'azienda o dalla Centrale Rischi. I dati si riferiscono alla data più recente disponibile.'),
      form([
        { k: 'monte_salari_mensile', et: 'Monte salari mensile (€)', tipo: 'num', dec: 0, ph: monte ? inNumero(monte, 0) : '', aiuto: monte ? 'vuoto = salari di bilancio / 12' : null },
        { k: 'retribuzioni_scadute_30', et: 'Retribuzioni scadute da 30+ giorni (€)', tipo: 'num', dec: 0 },
        { k: 'fornitori_scaduti_90', et: 'Fornitori scaduti da 90+ giorni (€)', tipo: 'num', dec: 0 },
        { k: 'fornitori_non_scaduti', et: 'Fornitori non scaduti (€)', tipo: 'num', dec: 0 },
        { k: 'esposizione_bancaria', et: 'Esposizione bancaria totale (€)', tipo: 'num', dec: 0 },
        { k: 'esposizione_scaduta_60', et: 'Scaduto o sconfinato da 60+ giorni (€)', tipo: 'num', dec: 0 },
        { k: 'segnalazione_inps', et: 'Segnalazione INPS', tipo: 'select', opz: SN() },
        { k: 'segnalazione_inail', et: 'Segnalazione INAIL', tipo: 'select', opz: SN() },
        { k: 'segnalazione_ade', et: 'Segnalazione Agenzia Entrate', tipo: 'select', opz: SN() },
        { k: 'segnalazione_ader', et: 'Segnalazione Riscossione', tipo: 'select', opz: SN() }
      ], d)));
    box.appendChild(el('div', { class: 'card' }, el('h2', null, 'Adeguati assetti (art. 2086 c.c.)'),
      form(c.assetti.map(function (a) { return { k: 'assetto_' + a.chiave, et: a.testo, tipo: 'select', opz: SN() }; }), d),
      el('div', { class: 'barra-salva' }, bottoneSalva(null, salva))));
  }

  // ---------- scadenze ----------
  function tabScadenze(box) {
    var sez = JSON.parse(JSON.stringify(AN.sezioni.scadenze || {}));
    sez.manuali = sez.manuali || [];
    function salva() { return salvaSezione('scadenze', sez); }
    var lista = listaScadenze(AN.scadenze, false);
    var tbody = lista.querySelector('tbody');
    var thr = lista.querySelector('thead tr'); if (thr) thr.appendChild(el('th'));
    if (tbody) Array.prototype.forEach.call(tbody.rows, function (tr, i) {
      var s = AN.scadenze[i];
      var cella = el('td');
      if (s.origine === 'manuale') {
        cella.appendChild(el('button', { type: 'button', class: 'btn btn-sm', onclick: function () { sez.manuali[s.indice].fatto = !s.fatto; salva(); } }, s.fatto ? 'Riapri' : 'Fatto'));
        cella.appendChild(el('button', { type: 'button', class: 'btn btn-sm btn-ghost', 'aria-label': 'Elimina', onclick: function () { sez.manuali.splice(s.indice, 1); salva(); } }, '✕'));
      } else cella.appendChild(el('span', { class: 'fine' }, { bilancio: 'dal bilancio', tfm: 'dal TFM', rischi: 'dai rischi' }[s.origine] || ''));
      tr.appendChild(cella);
    });
    var nuova = { data: '', titolo: '', note: '' };
    box.appendChild(lista);
    box.appendChild(el('div', { class: 'card' }, el('h2', null, 'Aggiungi una scadenza'),
      form([{ k: 'data', et: 'Data', tipo: 'date' }, { k: 'titolo', et: 'Cosa' }, { k: 'note', et: 'Note', largo: true }], nuova),
      el('div', { class: 'barra-salva' }, bottoneSalva('Aggiungi', function () {
        if (!nuova.data || !nuova.titolo) { toast('Servono data e descrizione', true); return; }
        sez.manuali.push(Object.assign({ fatto: false }, nuova)); return salva();
      }))));
  }

  // ---------- report ----------
  function tabReport(box) {
    box.appendChild(el('p', { class: 'caricamento' }, 'Preparazione del report…'));
    api('GET', '/api/aziende/' + AN.azienda.id + '/report').then(function (r) { disegnaReport(box, r); })
      .catch(function (e) { box.replaceChildren(el('div', { class: 'card' }, e.message)); });
  }
  function disegnaReport(box, r) {
    var oggi = new Date(P.oggi);
    var doc = el('article', { class: 'report' },
      el('h1', null, r.titolo), el('p', { class: 'muted' }, oggi.toLocaleDateString('it-IT', { day: 'numeric', month: 'long', year: 'numeric' })),
      r.sezioni.map(function (s) { return [el('h2', null, s.titolo), s.paragrafi.map(function (p) { return el('p', null, p); })]; }),
      r.proposte.length ? [el('h2', null, 'Cosa propongo'), el('ol', null, r.proposte.map(function (p) {
        return el('li', null, el('strong', null, p.titolo), p.dettaglio ? ' – ' + p.dettaglio : '');
      }))] : null,
      el('p', { class: 'fine', style: 'margin-top:1.5rem' }, r.nota));
    var bStile = P.ollama ? el('button', { type: 'button', class: 'btn' }, 'Riscrivi nel mio stile') : null;
    if (bStile) bStile.addEventListener('click', function () {
      bStile.disabled = true; bStile.textContent = 'Riscrittura in corso (può richiedere qualche minuto)…';
      api('POST', '/api/aziende/' + AN.azienda.id + '/report/stile', {}).then(function (n) {
        toast(n.riscritti + ' paragrafi riscritti; gli altri restano com\'erano (il modello aveva cambiato i numeri).');
        disegnaReport(box, n);
      }).catch(function (e) { toast(e.message, true); bStile.disabled = false; bStile.textContent = 'Riscrivi nel mio stile'; });
    });
    box.replaceChildren(el('div', { class: 'barra-salva no-print', style: 'margin:0 0 1rem' },
      el('button', { type: 'button', class: 'btn btn-pri', onclick: function () { window.print(); } }, 'Stampa o salva PDF'), bStile,
      el('span', { class: 'fine' }, 'Rileggi sempre il testo prima di consegnarlo. La riscrittura usa Ollama sul Mac: i dati non escono dal computer.')), doc);
  }

  // ---------- tema ----------
  (function () {
    var root = document.documentElement;
    try { var t = localStorage.getItem('pmi-tema'); if (t) root.setAttribute('data-theme', t); } catch (e) { /* niente */ }
    document.getElementById('tema').addEventListener('click', function () {
      var scuro = root.getAttribute('data-theme') ? root.getAttribute('data-theme') === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches;
      var nuovo = scuro ? 'light' : 'dark';
      root.setAttribute('data-theme', nuovo);
      try { localStorage.setItem('pmi-tema', nuovo); } catch (e) { /* niente */ }
    });
  })();

  // ---------- avvio ----------
  api('GET', '/api/parametri').then(function (p) { P = p; render(); })
    .catch(function (e) { main.replaceChildren(el('div', { class: 'card' }, 'Server non raggiungibile: ' + e.message)); });
})();
