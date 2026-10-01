'use strict';
/* SAGARAKSHAK MVP client. Talks to server.py; falls back to the signed packet offline. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const store = {
  get(k) { try { return JSON.parse(localStorage.getItem('sgk.' + k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem('sgk.' + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

const state = {
  meta: null, boat: store.get('boat') || [9.56, 79.37], lang: store.get('lang') || 'en',
  offline: false, layer: 'sst', ti: 0, last: null, packet: null, packetOK: null, sim: null,
};

const PRESETS = {
  en: [
    { q: 'Is it safe to go out tomorrow morning, and where will the fish be?' },
    { q: 'Where is the nearest fishing zone today?' },
    { q: 'Am I close to the border?' },
    { q: 'Why has fishing gotten worse here?' },
    { q: 'What is the chlorophyll at Kachchatheevu right now?', trap: 'Trap · cloud gap' },
    { q: 'How many fish will there be next month?', trap: 'Trap · no data' },
  ],
  ta: [
    { q: 'நாளை காலை கடலுக்குப் போகலாமா, மீன் எங்கே கிடைக்கும்?' },
    { q: 'இன்று அருகிலுள்ள மீன்பிடி இடம் எங்கே?' },
    { q: 'நான் எல்லைக்கு அருகில் இருக்கிறேனா?' },
    { q: 'இங்கே மீன்பிடி ஏன் குறைந்துவிட்டது?' },
    { q: 'கச்சத்தீவில் இப்போது குளோரோபில் எவ்வளவு?', trap: 'Trap · cloud gap' },
    { q: 'அடுத்த மாதம் எவ்வளவு மீன் கிடைக்கும்?', trap: 'Trap · no data' },
    { q: 'border evlo dooram?', mix: 'Mixed · Tanglish' },
    { q: 'naalai kaalai pogalama? fish zone enga?', mix: 'Mixed · Tanglish' },
  ],
  te: [
    { q: 'రేపు ఉదయం సముద్రంలోకి వెళ్ళవచ్చా, చేపలు ఎక్కడ దొరుకుతాయి?' },
    { q: 'ఈరోజు దగ్గరలో చేపల వేట ప్రాంతం ఎక్కడ ఉంది?' },
    { q: 'నేను సరిహద్దుకు దగ్గరగా ఉన్నానా?' },
    { q: 'ఇక్కడ చేపల వేట ఎందుకు తగ్గిపోయింది?' },
    { q: 'కచ్చతీవు దగ్గర ఇప్పుడు క్లోరోఫిల్ ఎంత?', trap: 'Trap · cloud gap' },
    { q: 'వచ్చే నెల ఎన్ని చేపలు దొరుకుతాయి?', trap: 'Trap · no data' },
    { q: 'border enta duram?', mix: 'Mixed · Tenglish' },
    { q: 'repu weather ela undi? fish zone ekkada?', mix: 'Mixed · Tenglish' },
  ],
};
/* Language of a piece of text, from its script. */
function langOf(text, hint = state.lang) {
  // Same rules as the server: script first, then romanised Telugu/Tamil markers,
  // then the selected language for one- or two-word questions, else English.
  const ta = (text.match(/[\u0B80-\u0BFF]/g) || []).length, te = (text.match(/[\u0C00-\u0C7F]/g) || []).length;
  if (ta || te) return ta >= te ? 'ta' : 'te';
  const M = state.meta && state.meta.lang_markers; if (!M) return 'en';
  const toks = text.toLowerCase().match(/[a-z]+/g) || [], weak = new Set(M.weak);
  const hit = (t, m) => t === m || (m.length >= 5 && t.startsWith(m));
  const score = lg => toks.reduce((n, t) => n + (M[lg].some(m => hit(t, m)) ? (weak.has(t) ? .3 : 1) : 0), 0);
  const sc = { te: score('te'), ta: score('ta') }, best = sc.te >= sc.ta ? 'te' : 'ta';
  if (sc[best] >= 1 && sc[best] > sc[best === 'te' ? 'ta' : 'te']) return best;
  return (hint !== 'en' && toks.length <= 2) ? hint : 'en';
}
const LANG_NAME = { en: 'English', ta: 'Tamil', te: 'Telugu' };
const LOCALE = { en: 'en-IN', ta: 'ta-IN', te: 'te-IN' };
const TAG = {
  en: { weather: 'Sea safety', border: 'Border', fish: 'Fishing zones', ocean: 'Ocean state', diagnose: 'Diagnosis', refusal: 'Refused', clarify: 'Help', offline: 'Offline · packet' },
  ta: { weather: 'கடல் பாதுகாப்பு', border: 'எல்லை', fish: 'மீன்பிடி இடங்கள்', ocean: 'கடல் நிலை', diagnose: 'காரண ஆய்வு', refusal: 'மறுப்பு', clarify: 'உதவி', offline: 'சிக்னல் இல்லை · தொகுப்பு' },
  te: { weather: 'సముద్ర భద్రత', border: 'సరిహద్దు', fish: 'చేపల వేట ప్రాంతాలు', ocean: 'సముద్ర స్థితి', diagnose: 'కారణ విశ్లేషణ', refusal: 'తిరస్కరణ', clarify: 'సహాయం', offline: 'సిగ్నల్ లేదు · ప్యాకెట్' },
};
const LEVEL = {
  en: { ok: 'clear', warn: 'caution', crit: 'alert', blocked: 'withheld', info: 'info' },
  ta: { ok: 'சரி', warn: 'கவனம்', crit: 'அபாயம்', blocked: 'தரப்படவில்லை', info: 'தகவல்' },
  te: { ok: 'సురక్షితం', warn: 'జాగ్రత్త', crit: 'ప్రమాదం', blocked: 'ఇవ్వలేదు', info: 'సమాచారం' },
};

/* ------------------------------------------------------------------ geo helpers */
const R = 6371.0088, rad = d => d * Math.PI / 180, deg = r => r * 180 / Math.PI;
const kmLon = lat => 111.32 * Math.cos(rad(lat));
function hav(a, b) {
  const dp = rad(b[0] - a[0]), dl = rad(b[1] - a[1]);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function bearing(a, b) {
  const p1 = rad(a[0]), p2 = rad(b[0]), dl = rad(b[1] - a[1]);
  return (deg(Math.atan2(Math.sin(dl) * Math.cos(p2), Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl))) + 360) % 360;
}
function distToLine(p, line) {
  let best = [Infinity, null]; const kx = kmLon(p[0]);
  for (let k = 0; k < line.length - 1; k++) {
    const ax = (line[k][1] - p[1]) * kx, ay = (line[k][0] - p[0]) * 111.32;
    const bx = (line[k + 1][1] - p[1]) * kx, by = (line[k + 1][0] - p[0]) * 111.32;
    const dx = bx - ax, dy = by - ay, L2 = dx * dx + dy * dy;
    const t = L2 ? Math.max(0, Math.min(1, -(ax * dx + ay * dy) / L2)) : 0;
    const px = ax + t * dx, py = ay + t * dy, d = Math.hypot(px, py);
    if (d < best[0]) best = [d, [p[0] + py / 111.32, p[1] + px / kx]];
  }
  return best;
}
function boundaryLon(lat, line) {
  for (let k = 0; k < line.length - 1; k++) {
    const [a1, o1] = line[k], [a2, o2] = line[k + 1];
    if (a2 <= lat && lat <= a1) return o2 + (a1 === a2 ? 0 : (lat - a2) / (a1 - a2)) * (o1 - o2);
  }
  return null;
}
const sideOf = (p, line) => { const b = boundaryLon(p[0], line); return b === null ? 'IN' : p[1] < b ? 'IN' : 'LK'; };
function inPoly(p, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [yi, xi] = poly[i], [yj, xj] = poly[j];
    if ((yi > p[0]) !== (yj > p[0]) && p[1] < xi + (p[0] - yi) * (xj - xi) / (yj - yi)) inside = !inside;
  }
  return inside;
}
const onLand = p => Object.values(state.meta.land).some(poly => inPoly(p, poly));
const COMPASS = { en: ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'], ta: ['வடக்கு', 'வடகிழக்கு', 'கிழக்கு', 'தென்கிழக்கு', 'தெற்கு', 'தென்மேற்கு', 'மேற்கு', 'வடமேற்கு'], te: ['ఉత్తరం', 'ఈశాన్యం', 'తూర్పు', 'ఆగ్నేయం', 'దక్షిణం', 'నైరుతి', 'పడమర', 'వాయువ్యం'] };
const compass = (b, lg = 'en') => COMPASS[lg][Math.floor((b + 22.5) / 45) % 8];
const pad3 = n => String(Math.round(n) % 360).padStart(3, '0');

/* ------------------------------------------------------------------ api */
async function api(path, body) {
  const r = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

/* ------------------------------------------------------------------ map */
let map, tiles, fieldOverlay, curLayer, answerLayer, advLayer, repLayer, boatMarker;
const BOAT_SVG = '<svg viewBox="0 0 32 32"><path d="M4 18h24l-4 7H8z" fill="#f1b440" stroke="#02090e" stroke-width="1.5"/><path d="M15 4v14M15 5l8 11h-8" fill="#d9e8ee" stroke="#02090e" stroke-width="1.3"/></svg>';

function initMap() {
  map = L.map('map', { zoomControl: true, preferCanvas: false }).setView(state.boat, 9);
  map.createPane('field'); map.getPane('field').style.zIndex = 350;
  setTiles();
  advLayer = L.layerGroup().addTo(map);
  curLayer = L.layerGroup().addTo(map);
  answerLayer = L.layerGroup().addTo(map);
  repLayer = L.layerGroup();
  L.polyline(state.meta.imbl, { color: css('--coral'), weight: 2.5, dashArray: '8 6' })
    .bindTooltip('IMBL — India–Sri Lanka maritime boundary (approx., from 1974/76 agreements)', { sticky: true }).addTo(map);
  for (const z of state.meta.advisory) {
    const IN = z.side === 'IN';
    L.circle([z.lat, z.lon], { radius: z.radius_km * 1000, color: IN ? css('--teal') : css('--faint'), weight: 1, opacity: .55, fillOpacity: .05, dashArray: IN ? null : '3 4' })
      .bindTooltip(`${z.id} · today's advisory · score ${z.score}${IN ? '' : ' · across IMBL'}`).addTo(advLayer);
  }
  boatMarker = L.marker(state.boat, { draggable: true, icon: L.divIcon({ className: 'boat-ico', html: BOAT_SVG, iconSize: [28, 28], iconAnchor: [14, 20] }), zIndexOffset: 1000, keyboard: true, title: 'Your boat (drag to move)' }).addTo(map);
  boatMarker.on('dragend', () => {
    const p = boatMarker.getLatLng(), pos = [+p.lat.toFixed(4), +p.lng.toFixed(4)];
    const [[la0, lo0], [la1, lo1]] = state.meta.bounds;
    if (onLand(pos) || pos[0] < la0 || pos[0] > la1 || pos[1] < lo0 || pos[1] > lo1) {
      boatMarker.setLatLng(state.boat);
      sys(onLand(pos) ? 'That spot is on land — boat moved back.' : 'Outside the demo region — boat moved back.');
      return;
    }
    setBoat(pos);
    answerLayer.clearLayers();
    if (!state.offline) refreshPacket();
  });
}
function setTiles() {
  const light = document.documentElement.dataset.theme === 'light' ||
    (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme: light)').matches);
  if (tiles) map.removeLayer(tiles);
  // Esri basemaps: no API key needed. Ocean base shows bathymetry, which suits a sea chart.
  const svc = light ? 'Ocean/World_Ocean_Base' : 'Canvas/World_Dark_Gray_Base';
  tiles = L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`, {
    maxZoom: 13, maxNativeZoom: light ? 10 : 16, attribution: 'Tiles &copy; Esri — GEBCO, NOAA, HERE, Garmin, OSM contributors',
  }).addTo(map);
  let failed = 0;
  tiles.on('tileerror', () => { if (++failed === 4) drawFallbackLand(); });
}
let landDrawn = false;
function drawFallbackLand() {
  if (landDrawn) return; landDrawn = true;
  for (const poly of Object.values(state.meta.land)) L.polygon(poly, { color: css('--line2'), weight: 1, fillColor: css('--raise'), fillOpacity: 1, interactive: false }).addTo(map);
}
function setBoat(pos) {
  state.boat = pos; store.set('boat', pos);
  boatMarker.setLatLng(pos);
  updateReadout();
}
function updateReadout(extra) {
  const [km] = distToLine(state.boat, state.meta.imbl);
  const side = sideOf(state.boat, state.meta.imbl);
  const el = $('#readout');
  el.hidden = false;
  el.className = 'readout' + (side === 'LK' || km < 2 ? ' crit' : km < 5 ? ' warn' : '');
  el.innerHTML = `Boat <b>${state.boat[0].toFixed(3)}°N ${state.boat[1].toFixed(3)}°E</b><br>` +
    (side === 'LK' ? '<b style="color:var(--coral)">Across the IMBL</b>' : `IMBL <b>${km.toFixed(1)} km</b>`) + (extra || '');
}

/* colour ramps (value 0..1) */
const RAMPS = {
  sst: ['#2b3a8f', '#2a7fb8', '#35c0c4', '#9fe07a', '#f6d44a', '#f08a3c', '#d7343a'],
  chl: ['#10244a', '#1b5a7a', '#1f8f78', '#5cbf4f', '#c9e24a', '#f6f08c'],
  hs: ['#1b2f5a', '#2a6fb0', '#57b6d8', '#d9f0f4', '#f3b14a', '#e0513d'],
  ts: ['#00000000', '#6a5acd55', '#8a6cff99', '#b18cffcc', '#ff6f61ee'],
};
const SCALE = {
  sst: { lo: 27.2, hi: 29.4, label: 'Sea surface temperature', unit: '°C' },
  chl: { lo: Math.log10(0.1), hi: Math.log10(3), log: true, label: 'Chlorophyll-a (log)', unit: 'mg/m³' },
  hs: { lo: 0, hi: 3, label: 'Significant wave height', unit: 'm' },
  ts: { lo: 0, hi: 1, label: 'Thunderstorm probability', unit: '' },
};
function hexToRgba(h) {
  const n = h.replace('#', '');
  return [0, 2, 4, 6].map(i => i < n.length ? parseInt(n.slice(i, i + 2), 16) : 255);
}
function ramp(name, x) {
  const st = RAMPS[name].map(hexToRgba), t = Math.max(0, Math.min(1, x)) * (st.length - 1);
  const i = Math.min(st.length - 2, Math.floor(t)), f = t - i;
  return st[i].map((v, k) => Math.round(v + (st[i + 1][k] - v) * f));
}
async function loadLayer() {
  if (fieldOverlay) { map.removeLayer(fieldOverlay); fieldOverlay = null; }
  $('#legend').hidden = true;
  if (state.layer !== 'none' && !state.offline) {
    const d = await api(`/api/layer?field=${state.layer}&t=${state.ti}`);
    const g = state.meta.grid, sc = SCALE[state.layer];
    const c = document.createElement('canvas'); c.width = g.nlon; c.height = g.nlat;
    const ctx = c.getContext('2d'), img = ctx.createImageData(g.nlon, g.nlat);
    for (let i = 0; i < g.nlat; i++) for (let j = 0; j < g.nlon; j++) {
      const v = d.grid[i][j], o = ((g.nlat - 1 - i) * g.nlon + j) * 4;
      let rgba;
      if (d.land[i][j]) rgba = [0, 0, 0, 0];
      else if (v === null) rgba = [150, 150, 160, 150];           // sea but no retrieval: cloud gap
      else { const x = sc.log ? Math.log10(Math.max(v, 1e-3)) : v; rgba = ramp(state.layer, (x - sc.lo) / (sc.hi - sc.lo)); rgba[3] = Math.min(rgba[3], 175); }
      img.data.set(rgba, o);
    }
    ctx.putImageData(img, 0, 0);
    const big = document.createElement('canvas'); big.width = g.nlon * 12; big.height = g.nlat * 12;
    const bctx = big.getContext('2d'); bctx.imageSmoothingEnabled = true; bctx.drawImage(c, 0, 0, big.width, big.height);
    const h = g.step / 2;
    fieldOverlay = L.imageOverlay(big.toDataURL(), [[g.lat0 - h, g.lon0 - h], [g.lat0 + (g.nlat - 1) * g.step + h, g.lon0 + (g.nlon - 1) * g.step + h]], { pane: 'field', opacity: .6 }).addTo(map);
    const lg = $('#legend'); lg.hidden = false;
    const stops = RAMPS[state.layer].map((c, k, a) => `${c} ${k / (a.length - 1) * 100}%`).join(',');
    const fmt = x => sc.log ? (10 ** x).toFixed(1) : x.toFixed(1);
    lg.innerHTML = `<b>${sc.label}</b> ${sc.unit ? '· ' + sc.unit : ''}<div class="bar" style="background:linear-gradient(90deg,${stops})"></div>
      <div class="ends"><span>${fmt(sc.lo)}</span><span>${fmt(sc.hi)}</span></div>
      ${state.layer === 'chl' ? '<div class="src"><span style="display:inline-block;width:10px;height:10px;background:#9696a0;vertical-align:middle"></span> grey = no satellite retrieval (cloud)</div>' : ''}
      <div class="src">SAMPLE · stands in for ${esc(state.meta.fields[state.layer].stands_in_for)}</div>`;
  }
  await loadCurrents();
}
async function loadCurrents() {
  curLayer.clearLayers();
  if (!$('#curToggle').checked || state.offline) return;
  const d = await api(`/api/layer?field=currents&t=${state.ti}`), g = state.meta.grid;
  const rend = L.canvas({ padding: .2 }), col = css('--text');
  for (let i = 0; i < g.nlat; i += 2) for (let j = 0; j < g.nlon; j += 2) {
    if (d.land[i][j]) continue;
    const [u, v] = d.vectors[i][j], sp = Math.hypot(u, v);
    if (sp < .02) continue;
    const lat = g.lat0 + i * g.step, lon = g.lon0 + j * g.step, L_ = 0.06 + sp * 0.35;
    const la2 = lat + v / sp * L_, lo2 = lon + u / sp * L_ / Math.cos(rad(lat));
    const a = Math.atan2(v, u), hl = L_ * .35;
    const h1 = [la2 - hl * Math.sin(a - .45), lo2 - hl * Math.cos(a - .45)], h2 = [la2 - hl * Math.sin(a + .45), lo2 - hl * Math.cos(a + .45)];
    L.polyline([[lat, lon], [la2, lo2]], { renderer: rend, color: col, weight: 1.1, opacity: .55, interactive: false }).addTo(curLayer);
    L.polyline([h1, [la2, lo2], h2], { renderer: rend, color: col, weight: 1.1, opacity: .55, interactive: false }).addTo(curLayer);
  }
}
function timeLabel(ti) {
  const t = new Date(new Date(state.meta.issued).getTime() + ti * 3 * 3600e3);
  return t.toLocaleString('en-IN', { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }) + ` (+${ti * 3} h)`;
}

/* ------------------------------------------------------------------ chat */
const chat = () => $('#chat');
function addMsg(cls, html, lang) {
  const d = document.createElement('div'); d.className = 'msg ' + cls; if (lang) d.lang = lang;
  d.innerHTML = html; chat().appendChild(d); chat().scrollTop = chat().scrollHeight; return d;
}
const sys = t => addMsg('sys', esc(t));
function renderChips() {
  $('#chips').innerHTML = PRESETS[state.lang].map((p, k) =>
    `<button type="button" class="chip${p.trap ? ' trap' : ''}${p.mix ? ' mix' : ''}" data-k="${k}" lang="${langOf(p.q)}">${p.trap || p.mix ? `<small>${p.trap || p.mix}</small>` : ''}${esc(p.q)}</button>`).join('');
  $$('#chips .chip').forEach(b => b.onclick = () => ask(PRESETS[state.lang][+b.dataset.k].q));
  $('#q').placeholder = { en: 'Ask about fish, weather, the border…', ta: 'மீன், வானிலை, எல்லை பற்றி கேளுங்கள்…', te: 'చేపలు, వాతావరణం, సరిహద్దు గురించి అడగండి…' }[state.lang];
}

async function ask(text, fromVoice = false) {
  text = text.trim(); if (!text) return;
  $('#q').value = '';
  addMsg('me', esc(text), langOf(text));
  if (state.offline) return offlineAnswer(text, fromVoice);
  const typing = addMsg('bot', '<span class="typing"><i></i><i></i><i></i></span>');
  try {
    const res = await api('/api/ask', { text, lat: state.boat[0], lon: state.boat[1], fault: $('#fault').checked ? 'pfz' : null, lang: state.lang });
    typing.remove();
    state.last = { q: text, res };
    renderAnswer(res, fromVoice);
    drawAnswer(res.map);
    renderEvidence(); renderTrace();
  } catch (e) {
    typing.remove();
    addMsg('bot', `<div class="sec crit"><span class="tag">error</span><p>${esc(e.message)}</p></div>`);
  }
}

function renderAnswer(res, speakNow) {
  const lg = res.understood.lang;
  const nv = res.claims.filter(c => c.status === 'verified').length, nb = res.claims.length - nv;
  let html = res.sections.map(s => `<div class="sec ${s.level}"><span class="tag">${esc(TAG[lg][s.agent] || s.agent)} · ${LEVEL[lg][s.level]}</span>${s.lines.map(l => `<p>${esc(l)}</p>`).join('')}</div>`).join('');
  if (res.notes.diagnose) html += diagChart(res.notes.diagnose);
  html += `<div class="msgfoot">${res.claims.length ? `<span class="pill v">✓ ${nv} verified</span>${nb ? `<span class="pill b">⊘ ${nb} withheld</span>` : ''}<button type="button" data-act="ev">Evidence</button><button type="button" data-act="ag">Agents</button>` : '<span>No claims made.</span>'}<button type="button" data-act="speak" data-mode="idle">${LISTEN[lg].idle}</button></div>`;
  const m = addMsg('bot', html, lg);
  const lb = m.querySelector('[data-act="speak"]');
  lb.onclick = () => speak(res.speak, lg, lb);
  m.querySelector('[data-act="ev"]')?.addEventListener('click', () => showTab('evidence'));
  m.querySelector('[data-act="ag"]')?.addEventListener('click', () => showTab('agents'));
  if (speakNow) speak(res.speak, lg, lb);
}

function diagChart(n) {
  const W = 320, H = 118, P = 6, s = n.series, N = s.cpue.length, k = n.recent_weeks;
  const z = xs => { const m = xs.reduce((a, b) => a + b) / xs.length, sd = Math.sqrt(xs.reduce((a, b) => a + (b - m) ** 2, 0) / (xs.length - 1)); return xs.map(x => (x - m) / sd); };
  const X = i => P + i * (W - 2 * P) / (N - 1), Y = v => H / 2 - v * (H / 2 - 14) / 3;
  const line = (xs, col, w) => `<polyline fill="none" stroke="${col}" stroke-width="${w}" stroke-linejoin="round" points="${z(xs).map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' ')}"/>`;
  return `<svg class="chart" viewBox="0 0 ${W} ${H + 14}" role="img" aria-label="52 weeks of catch, chlorophyll and upwelling, standardised">
    <rect x="${X(N - k)}" y="0" width="${X(N - 1) - X(N - k)}" height="${H}" fill="var(--amber-soft)"/>
    <line x1="${P}" x2="${W - P}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--line2)" stroke-dasharray="2 3"/>
    ${line(s.upwelling, 'var(--violet)', 1.2)}${line(s.chl, 'var(--amber)', 1.2)}${line(s.cpue, 'var(--teal)', 2)}
    <text x="${P}" y="${H + 11}">52 weeks · standardised</text>
    <text x="${W - P}" y="${H + 11}" text-anchor="end"><tspan fill="var(--teal)">■ catch</tspan> <tspan fill="var(--amber)">■ chl</tspan> <tspan fill="var(--violet)">■ upwelling</tspan></text>
  </svg>`;
}

function drawAnswer(m) {
  answerLayer.clearLayers();
  const pts = [state.boat];
  const b = m.border;
  if (b) {
    L.polygon(b.cone, { color: '#02090e', weight: 5, opacity: .55, fill: false, interactive: false }).addTo(answerLayer);
    L.polygon(b.cone, { color: css('--amber'), weight: 2.5, fillColor: css('--amber'), fillOpacity: .28 }).bindTooltip('Where the boat could drift in 8 h with the engine off (40 scenarios)').addTo(answerLayer);
    for (const [h, hull] of Object.entries(b.iso)) if (hull.length > 2)
      L.polygon(hull, { color: css('--amber'), weight: 1, dashArray: '3 4', fill: false }).bindTooltip(`+${h} h`, { sticky: true }).addTo(answerLayer);
    L.polyline(b.center, { color: '#02090e', weight: 6, opacity: .6 }).addTo(answerLayer);
    L.polyline(b.center, { color: css('--amber'), weight: 3 }).bindTooltip('Best-estimate drift track').addTo(answerLayer);
    L.polyline([state.boat, b.nearest], { color: css('--coral'), weight: 1.5, dashArray: '2 4' }).addTo(answerLayer);
    pts.push(...b.cone);
  }
  const f = m.fish;
  if (f) {
    for (const z of f.zones) {
      L.circle([z.lat, z.lon], { radius: z.radius_km * 1000, color: z.withheld ? css('--violet') : css('--teal'), weight: 2.5, dashArray: z.withheld ? '2 5' : null, fillOpacity: z.withheld ? .03 : .18 })
        .bindTooltip(z.withheld ? `${z.id} · withheld by verifier` : z.id, { permanent: true, direction: 'center', className: 'zlabel' }).addTo(answerLayer);
      pts.push([z.lat, z.lon]);
    }
    for (const z of f.excluded)
      L.circle([z.lat, z.lon], { radius: z.radius_km * 1000, color: css('--coral'), weight: 1.5, dashArray: '4 4', fillOpacity: .06 })
        .bindTooltip(`${z.id} · across IMBL — not advised`, { permanent: true, direction: 'center', className: 'zlabel' }).addTo(answerLayer);
  }
  if (m.ocean) {
    L.circleMarker(m.ocean.point, { radius: 7, color: css('--violet'), weight: 2, fillOpacity: .2 }).addTo(answerLayer);
    pts.push(m.ocean.point);
  }
  if (pts.length > 1) map.fitBounds(L.latLngBounds(pts).pad(.15), { maxZoom: m.fish || m.ocean ? 10 : 12 });
}

/* ------------------------------------------------------------------ evidence pane */
const AGENT_NAME = { fish: 'Fishing-zone agent', weather: 'Weather agent', border: 'Border & drift agent', ocean: 'Ocean-state agent', diagnose: 'Diagnosis agent' };
function fmtVal(v) {
  if (v === null || v === undefined) return '— (no value)';
  if (typeof v !== 'object') return String(v);
  return Object.entries(v).map(([k, x]) => `${k}=${x ?? '—'}`).join('  ');
}
function renderEvidence() {
  const L_ = state.last; if (!L_) return;
  const cl = L_.res.claims, nb = cl.filter(c => c.status !== 'verified').length;
  $('#evCount').textContent = cl.length ? `${cl.length - nb}✓${nb ? ' ' + nb + '⊘' : ''}` : '';
  const pane = $('#pane-evidence');
  if (!cl.length) { pane.innerHTML = `<p class="q">“${esc(L_.q)}”</p><div class="empty">No claims were made for this question — the planner found no agent or dataset that could support an answer, so nothing was computed.</div>`; return; }
  let html = `<div class="ledger-head"><span class="q">“${esc(L_.q)}”</span><span class="pill v">${cl.length - nb} verified</span>${nb ? `<span class="pill b">${nb} withheld</span>` : ''}</div>`;
  let cur = null;
  for (const c of cl) {
    if (c.agent !== cur) { cur = c.agent; html += `<div class="agentgrp">${AGENT_NAME[cur]}</div>`; }
    const ok = c.status === 'verified';
    html += `<details class="claim${ok ? '' : ' blocked'}"${ok ? '' : ' open'}><summary><span class="pill ${ok ? 'v' : 'b'}">${ok ? '✓' : '⊘'}</span><span class="lbl">${esc(c.label)}</span><span class="id">${c.id}</span>
      <span class="val">${esc(fmtVal(c.value))} ${esc(c.unit)}</span></summary><div class="body">
      ${ok ? `<div class="check">✓ ${esc(c.check)}</div>` : `<div class="reason">⊘ Blocked at ${esc(c.gate)} gate: ${esc(c.reason)}</div>${c.check ? `<div>${esc(c.check)}</div>` : ''}`}
      ${c.recomputed !== undefined ? `<div>Verifier got: <span class="mono">${esc(fmtVal(c.recomputed))}</span></div>` : ''}
      ${inputsHtml(c)}</div></details>`;
  }
  pane.innerHTML = html;
}
function inputsHtml(c) {
  if (!c.inputs.length) return `<div class="note">Inputs: ${esc(JSON.stringify(c.params))} (geometry only)</div>`;
  if (c.inputs[0].series !== undefined) {
    const names = [...new Set(c.inputs.map(r => r.series))];
    return `<div class="note">Inputs: ${c.inputs.length} weekly values from ${names.map(esc).join(' + ')} (${names.map(n => esc(state.meta.fields[n]?.stands_in_for || seriesSrc[n] || '')).join('; ')})</div>`;
  }
  const rows = c.inputs.slice(0, 8).map(r => `<tr><td>${r.field}${r.role ? ' · ' + r.role : ''}</td><td>${r.lat.toFixed(1)}°N ${r.lon.toFixed(1)}°E</td><td>t${r.ti}</td><td>${r.value === null ? '<b style="color:var(--violet)">none</b>' : r.value}</td><td>${r.w !== undefined ? r.w.toFixed(2) : ''}</td></tr>`).join('');
  const fields = [...new Set(c.inputs.map(r => r.field))];
  return `<table class="inputs"><thead><tr><th>field</th><th>cell</th><th>time</th><th>value</th><th>weight</th></tr></thead><tbody>${rows}</tbody></table>
    ${c.inputs.length > 8 ? `<div class="note">+ ${c.inputs.length - 8} more cells</div>` : ''}
    <div class="note">Source: ${fields.map(f => `${esc(f)} → SAMPLE, stands in for ${esc(state.meta.fields[f].stands_in_for)}`).join('; ')}</div>`;
}
const seriesSrc = { cpue: 'fisher catch reports + CMFRI landings', upwelling: 'Ekman transport from IMD winds', sst_anom: 'MOSDAC SST vs climatology', rain: 'IMD gridded rainfall', effort: 'Dept. of Fisheries trip logs', chl: 'OCM-3 chlorophyll, sector mean' };

/* ------------------------------------------------------------------ agents pane */
function renderTrace() {
  const L_ = state.last; if (!L_) return;
  const tr = L_.res.trace, by = Object.fromEntries(tr.map(n => [n.node, n]));
  const specialists = tr.filter(n => n.deps.includes('plan'));
  const node = n => n ? `<div class="node${n.node === 'verifier' ? ' ver' : ''}"><div class="nm">${esc(n.label)}</div><div class="ms">${n.ms} ms</div><div class="dt">${esc(n.detail)}</div></div>` : '';
  const stages = [[by.understand], [by.plan], specialists, [by.verifier], [by.compose]].filter(s => s.length && s[0]);
  let html = `<p class="explain">How the orchestrator handled <span class="q">“${esc(L_.q)}”</span>. Specialists have no dependencies on each other, so they run at the same time; the verifier waits for all of them; the composer may only use what the verifier passed.</p><div class="dag">`;
  html += stages.map((s, k) => (k ? '<div class="arrow">↓</div>' : '') + `<div class="stage">${s.map(node).join('')}</div>`).join('');
  html += '</div>';
  if (specialists.length) {
    const mx = Math.max(...tr.map(n => n.ms), 1);
    html += `<div class="bars"><div class="agentgrp">Time per step</div>${tr.map(n => `<div class="row"><span>${esc(n.label)}</span><div class="b" style="width:${Math.max(2, n.ms / mx * 100)}%"></div><span class="num">${n.ms} ms</span></div>`).join('')}</div>
      <p class="note">The border agent's cost is the 40-member RK4 drift ensemble; the verifier re-runs it from the same seed to reproduce the result.</p>`;
  }
  $('#pane-agents').innerHTML = html;
}

/* ------------------------------------------------------------------ feedback loop */
async function renderLoop(result) {
  const sc = await api('/api/scorecard');
  drawReports(sc);
  const f = x => x ?? '—';
  $('#pane-loop').innerHTML = `
    <p class="explain">Advice goes out; catch reports come back. Each report is scored against the advisory the fisher fished under, and boat-measured water temperature checks the satellite. <b>This is the reply envelope.</b></p>
    <div class="kpis">
      <div class="kpi"><div class="k">Zone lift</div><div class="v">×${f(sc.lift)}</div><div class="s">catch rate inside ÷ outside zones</div></div>
      <div class="kpi"><div class="k">In-zone share</div><div class="v">${sc.hit_share === null ? '—' : Math.round(sc.hit_share * 100) + '%'}</div><div class="s">${sc.n} reports · ${sc.n_live} live</div></div>
      <div class="kpi"><div class="k">SST RMSE</div><div class="v">${f(sc.sst.rmse)}°</div><div class="s">bias ${sc.sst.bias > 0 ? '+' : ''}${f(sc.sst.bias)} °C · n=${sc.sst.n}</div></div>
    </div>
    <div class="note" style="margin:-4px 0 12px">Catch rate: ${f(sc.cpue_inside)} kg/h inside vs ${f(sc.cpue_outside)} kg/h outside advised zones.</div>
    ${result ? `<div class="result">${result}</div>` : ''}
    <form class="report" id="reportForm">
      <div class="full" style="font-weight:600;font-size:12.5px">Report today's catch <span class="note">— at the boat's position (${state.boat[0].toFixed(3)}, ${state.boat[1].toFixed(3)})</span></div>
      <label>Species<select name="species"><option>sardine</option><option>mackerel</option><option>prawn</option><option>squid</option><option>trevally</option></select></label>
      <label>Catch (kg)<input name="kg" type="number" min="0" step="1" value="60" required></label>
      <label>Hours fished<input name="hours" type="number" min="0.5" step="0.5" value="7" required></label>
      <label>Water temp °C <span class="note">(optional)</span><input name="water_temp" type="number" step="0.1" placeholder="e.g. 28.7"></label>
      <div class="full"><button class="btn" type="submit">Send report</button></div>
    </form>
    <div class="agentgrp">Latest reports</div>
    <table class="recent"><thead><tr><th>when</th><th>species</th><th>kg/h</th><th>zone</th><th>ΔSST</th></tr></thead><tbody>
    ${sc.recent.map(r => `<tr><td>${new Date(r.time).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}${r.seed ? ' <span class="note">seed</span>' : ''}</td><td>${esc(r.species)}</td><td class="num">${r.cpue}</td><td>${r.inside ? `<b style="color:var(--teal)">${r.nearest_zone}</b>` : `<span class="note">${r.zone_km} km out</span>`}</td><td class="num">${r.sst_diff !== undefined ? (r.sst_diff > 0 ? '+' : '') + r.sst_diff : '—'}</td></tr>`).join('')}
    </tbody></table>
    <p class="note">Seed reports are synthetic, so the scorecard isn't empty on first run; reports you send are stored in data/catches.json. Toggle “Catch reports” on the map to see them.</p>`;
  $('#reportForm').onsubmit = async e => {
    e.preventDefault();
    if (state.offline) { sys('No signal — the report will need to wait until you are back in range.'); return; }
    const fd = Object.fromEntries(new FormData(e.target));
    try {
      const r = await api('/api/catch', { ...fd, lat: state.boat[0], lon: state.boat[1] });
      const ev = r.evaluation;
      renderLoop(`${ev.inside ? `✓ Inside advised zone <b>${ev.nearest_zone}</b> (${ev.zone_km} km from its centre) — counts toward the advisory's hit rate.` : `Outside all advised zones (nearest ${ev.nearest_zone}, ${ev.zone_km} km) — logged as an out-of-zone comparison.`}
        Catch rate <b>${ev.cpue} kg/h</b>.${ev.sst_diff !== undefined ? ` Your water temp differs from the satellite by <b>${ev.sst_diff > 0 ? '+' : ''}${ev.sst_diff} °C</b> — one more validation point for the SST product.` : ''}`);
    } catch (err) { sys(err.message); }
  };
}
function drawReports(sc) {
  repLayer.clearLayers();
  for (const [lat, lon, inside, seed] of sc.points)
    L.circleMarker([lat, lon], { radius: seed ? 3.5 : 6, color: inside ? css('--teal') : css('--muted'), weight: seed ? 1 : 2.5, fillOpacity: .6 }).addTo(repLayer);
}

/* ------------------------------------------------------------------ offline packet */
const hex2buf = h => new Uint8Array(h.match(/../g).map(x => parseInt(x, 16)));
async function verifyPacket(p) {
  const pinned = store.get('pubkey') || state.meta.pubkey;
  try {
    const key = await crypto.subtle.importKey('raw', hex2buf(pinned), { name: 'Ed25519' }, false, ['verify']);
    return await crypto.subtle.verify({ name: 'Ed25519' }, key, hex2buf(p.sig), new TextEncoder().encode(p.body));
  } catch { return 'unsupported'; }
}
async function refreshPacket() {
  try {
    const p = await api(`/api/packet?lat=${state.boat[0]}&lon=${state.boat[1]}`);
    state.packet = p; state.packet.tampered = false; store.set('packet', p);
    state.packetOK = await verifyPacket(p);
    renderPacket();
  } catch (e) { console.warn(e); }
}
function renderPacket() {
  const p = state.packet, pane = $('#pane-packet');
  if (!p) { pane.innerHTML = '<div class="empty">No packet yet.</div>'; return; }
  const b = JSON.parse(p.body), ok = state.packetOK;
  pane.innerHTML = `
    <p class="explain">What the phone keeps for when the signal drops. In production this rides the <b>GEMINI / GAGAN</b> satellite broadcast that already reaches boats beyond mobile range; SAGARAKSHAK makes the message smarter, not the delivery. The phone refuses any packet whose Ed25519 signature doesn't check against the key pinned at install.</p>
    <div class="vstate ${ok === true ? 'ok' : ok === false ? 'bad' : ''}">${ok === true ? '✓ Signature valid — packet accepted' : ok === false ? '✕ Signature INVALID — packet rejected, phone will not use it' : '… This browser has no Ed25519 in WebCrypto; signature not checked here'}</div>
    <dl class="kv">
      <dt>Issued</dt><dd>${new Date(b.issued).toLocaleString('en-IN', { hour12: false, timeZone: 'Asia/Kolkata' })} · valid ${b.valid_h} h</dd>
      <dt>Size</dt><dd>${p.bytes.toLocaleString()} bytes (JSON; binary packing would shrink it further)</dd>
      <dt>Contents</dt><dd>${b.grid.n}×${b.grid.n} current+wind grid × ${b.grid.cu.length} time steps · ${b.imbl.length} IMBL vertices · ${b.zones.length} zones · ${b.wx.length}-step sea-state strip</dd>
      <dt>Alerts</dt><dd>warn ${b.alert_km.warn} km · critical ${b.alert_km.crit} km from IMBL</dd>
      <dt>Signature</dt><dd>${p.sig.slice(0, 32)}…</dd>
    </dl>
    <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
      <button class="btn alt" type="button" id="pktRefresh" ${state.offline ? 'disabled' : ''}>Refresh packet</button>
    </div>
    <div class="agentgrp">Sea-state strip at the boat</div>
    <table class="recent"><thead><tr><th>time</th><th>waves</th><th>wind</th><th>storm</th></tr></thead><tbody>${b.wx.map(w => `<tr><td>${w[0]}</td><td class="num">${w[1]} m</td><td class="num">${w[2]} km/h</td><td class="num">${w[3]}%</td></tr>`).join('')}</tbody></table>
    <div class="agentgrp">Body (signed bytes)</div><div class="pkt">${esc(p.body.slice(0, 1400))}${p.body.length > 1400 ? '…' : ''}</div>`;
  $('#pktRefresh').onclick = refreshPacket;
}

/* offline drift: RK4 through the packet's current + wind subgrid */
function pktVel(b, lat, lon, t) {
  const g = b.grid, n = g.n, x = (lon - g.lon0) / g.step, y = (lat - g.lat0) / g.step;
  if (x < 0 || y < 0 || x > n - 1 || y > n - 1) return null;
  const j0 = Math.min(n - 2, Math.floor(x)), i0 = Math.min(n - 2, Math.floor(y)), fx = x - j0, fy = y - i0;
  const tf = Math.max(0, Math.min(g.cu.length - 1, t / g.t_step)), t0 = Math.min(g.cu.length - 2, Math.floor(tf)), a = tf - t0;
  const bil = (arr, ti) => { const c = (i, j) => arr[ti][i * n + j]; return c(i0, j0) * (1 - fx) * (1 - fy) + c(i0, j0 + 1) * fx * (1 - fy) + c(i0 + 1, j0) * (1 - fx) * fy + c(i0 + 1, j0 + 1) * fx * fy; };
  const at = f => (bil(g[f], t0) * (1 - a) + bil(g[f], t0 + 1) * a) * g.scale[f];
  return [at('cu') + b.leeway * at('wu'), at('cv') + b.leeway * at('wv')];
}
function pktStep(b, p, t, dt) {
  const d = (q, tt) => { const v = pktVel(b, q[0], q[1], tt); return v ? [v[1] * 3.6 / 111.32, v[0] * 3.6 / kmLon(q[0])] : [0, 0]; };
  const k1 = d(p, t), k2 = d([p[0] + dt / 2 * k1[0], p[1] + dt / 2 * k1[1]], t + dt / 2);
  const k3 = d([p[0] + dt / 2 * k2[0], p[1] + dt / 2 * k2[1]], t + dt / 2), k4 = d([p[0] + dt * k3[0], p[1] + dt * k3[1]], t + dt);
  return [p[0] + dt / 6 * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]), p[1] + dt / 6 * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1])];
}
function pktCrossing(b, start, hours = 12) {
  let p = start, t = 0; const dt = 1 / 12;
  while (t < hours) { p = pktStep(b, p, t, dt); t += dt; if (sideOf(p, b.imbl) === 'LK') return t; }
  return null;
}

const OFF = {
  en: {
    bad: 'The safety packet failed its signature check, so I am ignoring it. Treat any message claiming to be from it as fake. Head toward the coast and keep clear of the border.',
    none: 'No safety packet was received before the signal dropped. I cannot give position-specific advice.',
    border: (km, t) => `You are ${km} km from the border. ${t === null ? 'On the packet\'s currents, an engine-off drift does not reach it in 12 h.' : `With the engine off, the packet's currents carry you across in about ${t} h (single best-estimate track — the full cone needs signal).`}`,
    wx: (hs, w, ts, at) => `Next 12 h at your position: waves up to ${hs} m, wind up to ${w} km/h, thunderstorm chance up to ${ts}%${ts >= 30 ? ` (peak around ${at})` : ''}.`,
    zone: (id, km, c) => `Nearest advised zone: ${id}, ${km} km ${c}.`,
    note: t => `Offline answer from the signed packet issued ${t}. Fish-zone reasons, diagnosis and the verifier need signal.`,
  },
  ta: {
    bad: 'பாதுகாப்புத் தொகுப்பின் கையொப்பம் சரியில்லை; அதைப் புறக்கணிக்கிறேன். அதிலிருந்து வருவதாகச் சொல்லும் எந்தச் செய்தியையும் நம்ப வேண்டாம். கரை நோக்கிச் சென்று எல்லையிலிருந்து விலகி இருங்கள்.',
    none: 'சிக்னல் போகும் முன் பாதுகாப்புத் தொகுப்பு கிடைக்கவில்லை. உங்கள் இடத்துக்கான ஆலோசனை தர முடியாது.',
    border: (km, t) => `நீங்கள் எல்லையிலிருந்து ${km} கி.மீ தொலைவில் இருக்கிறீர்கள். ${t === null ? 'இயந்திரம் நின்றாலும் 12 மணி நேரத்தில் எல்லையை அடையமாட்டீர்கள்.' : `இயந்திரம் நின்றால், சுமார் ${t} மணி நேரத்தில் நீரோட்டம் உங்களை எல்லைக்கு அப்பால் கொண்டு செல்லும்.`}`,
    wx: (hs, w, ts, at) => `அடுத்த 12 மணி நேரம்: அலை ${hs} மீ வரை, காற்று மணிக்கு ${w} கி.மீ வரை, இடி-மழை வாய்ப்பு ${ts}% வரை${ts >= 30 ? ` (சுமார் ${at} மணிக்கு அதிகம்)` : ''}.`,
    zone: (id, km, c) => `அருகிலுள்ள மீன்பிடி இடம்: ${id}, ${c} திசையில் ${km} கி.மீ.`,
    note: t => `${t} மணிக்கு வெளியான கையொப்பமிட்ட தொகுப்பிலிருந்து பதில். விரிவான காரணங்களுக்கு சிக்னல் தேவை.`,
  },
  te: {
    bad: 'భద్రతా ప్యాకెట్ సంతకం సరిగా లేదు; దాన్ని పట్టించుకోవడం లేదు. దాని నుండి వచ్చినట్లు చెప్పే ఏ సందేశాన్నీ నమ్మవద్దు. ఒడ్డు వైపు వెళ్ళి సరిహద్దుకు దూరంగా ఉండండి.',
    none: 'సిగ్నల్ పోకముందు భద్రతా ప్యాకెట్ అందలేదు. మీ స్థానానికి సంబంధించిన సలహా ఇవ్వలేను.',
    border: (km, t) => `మీరు సరిహద్దు నుండి ${km} కి.మీ. దూరంలో ఉన్నారు. ${t === null ? 'ఇంజిన్ ఆగిపోయినా 12 గంటల్లో సరిహద్దు చేరరు.' : `ఇంజిన్ ఆగిపోతే, సుమారు ${t} గంటల్లో ప్రవాహం మిమ్మల్ని సరిహద్దు దాటిస్తుంది.`}`,
    wx: (hs, w, ts, at) => `తదుపరి 12 గంటలు: అలలు ${hs} మీ. వరకు, గాలి గంటకు ${w} కి.మీ. వరకు, ఉరుములతో కూడిన వర్షం అవకాశం ${ts}% వరకు${ts >= 30 ? ` (సుమారు ${at} గంటలకు ఎక్కువ)` : ''}.`,
    zone: (id, km, c) => `దగ్గరలోని చేపల వేట ప్రాంతం: ${id}, ${c} దిశలో ${km} కి.మీ.`,
    note: t => `${t} గంటలకు విడుదలైన సంతకం చేసిన ప్యాకెట్ నుండి సమాధానం. వివరమైన కారణాలకు సిగ్నల్ అవసరం.`,
  },
};
function offlineAnswer(text, fromVoice) {
  const lg = langOf(text), T = OFF[lg];
  const p = state.packet;
  let lines, level = 'warn';
  if (!p) { lines = [T.none]; level = 'blocked'; }
  else if (state.packetOK === false) { lines = [T.bad]; level = 'crit'; }
  else {
    const b = JSON.parse(p.body);
    const [km] = distToLine(state.boat, b.imbl);
    const tc = pktCrossing(b, state.boat);
    const hs = Math.max(...b.wx.map(w => w[1])), wmax = Math.max(...b.wx.map(w => w[2])), ts = Math.max(...b.wx.map(w => w[3]));
    const at = b.wx.find(w => w[3] === ts)[0];
    lines = [T.border(km.toFixed(1), tc === null ? null : tc.toFixed(1)), T.wx(hs, wmax, ts, at)];
    const z = b.zones.map(z => [z, hav(state.boat, [z[1], z[2]])]).sort((a, c) => a[1] - c[1])[0];
    if (z) lines.push(T.zone(z[0][0], z[1].toFixed(0), compass(bearing(state.boat, [z[0][1], z[0][2]]), lg)));
    lines.push(T.note(new Date(b.issued).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })));
    level = km < 2 || (tc !== null && tc < 3) ? 'crit' : km < 5 || tc !== null ? 'warn' : 'ok';
  }
  const ob = addMsg('bot', `<div class="sec ${level}"><span class="tag">${TAG[lg].offline}</span>${lines.map(l => `<p>${esc(l)}</p>`).join('')}</div><div class="msgfoot"><button type="button" data-mode="idle">${LISTEN[lg].idle}</button></div>`, lg).querySelector('button');
  ob.onclick = () => speak(lines.join(' '), lg, ob);
  if (fromVoice) speak(lines.join(' '), lg, ob);
}

/* engine-failure simulation: the phone drifts the boat on its own and alerts */
let audioCtx;
function beep(freq, n) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    for (let k = 0; k < n; k++) {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.frequency.value = freq; o.connect(g); g.connect(audioCtx.destination);
      const t = audioCtx.currentTime + k * .28; g.gain.setValueAtTime(.12, t); g.gain.exponentialRampToValueAtTime(.001, t + .22);
      o.start(t); o.stop(t + .24);
    }
  } catch { /* audio blocked */ }
}
function startSim() {
  if (state.sim) return stopSim('Simulation stopped.');
  if (!state.packet || state.packetOK === false) { sys('No trusted packet — cannot run on-device drift.'); return; }
  const b = JSON.parse(state.packet.body), lg = state.lang;
  let t = 0, level = 'ok';
  const track = L.polyline([state.boat], { color: css('--coral'), weight: 2.5, dashArray: '1 5', lineCap: 'round' }).addTo(answerLayer);
  sys({ en: 'Engine failed. The phone is now tracking drift on its own — 1 second = 5 minutes.', ta: 'இயந்திரம் நின்றது. தொலைபேசி தானாகவே நகர்வைக் கணிக்கிறது.', te: 'ఇంజిన్ ఆగిపోయింది. ఫోన్ స్వయంగా కదలికను లెక్కిస్తోంది — 1 సెకను = 5 నిమిషాలు.' }[lg]);
  $('#simBtn').textContent = 'Stop simulation';
  state.sim = setInterval(() => {
    const dt = 5 / 60;
    const p = pktStep(b, state.boat, t, dt); t += dt;
    setBoat([+p[0].toFixed(5), +p[1].toFixed(5)]); track.addLatLng(state.boat);
    const [km] = distToLine(state.boat, b.imbl), side = sideOf(state.boat, b.imbl);
    const tc = side === 'LK' ? 0 : pktCrossing(b, state.boat, 6);
    updateReadout(`<br>Drift clock <b>+${Math.floor(t)}h${String(Math.round((t % 1) * 60)).padStart(2, '0')}</b>${tc ? ` · crossing in ~<b>${tc.toFixed(1)} h</b>` : ''}`);
    const nl = side === 'LK' ? 'over' : km < b.alert_km.crit ? 'crit' : km < b.alert_km.warn ? 'warn' : 'ok';
    if (nl !== level) {
      level = nl;
      const msg = {
        warn: { en: `Caution: ${km.toFixed(1)} km from the border and drifting toward it. Drop anchor or steer ${pad3(bearing(distToLine(state.boat, b.imbl)[1], state.boat))}°.`, ta: `எச்சரிக்கை: எல்லையிலிருந்து ${km.toFixed(1)} கி.மீ, அதை நோக்கி நகர்கிறீர்கள். நங்கூரம் இடுங்கள்.`, te: `హెచ్చరిక: సరిహద్దు నుండి ${km.toFixed(1)} కి.మీ., దాని వైపు కదులుతున్నారు. లంగరు వేయండి.` },
        crit: { en: `ALERT: ${km.toFixed(1)} km from the border. Anchor now and call for a tow on VHF channel 16.`, ta: `அபாயம்: எல்லையிலிருந்து ${km.toFixed(1)} கி.மீ மட்டுமே. உடனே நங்கூரம் இடுங்கள்.`, te: `ప్రమాదం: సరిహద్దు నుండి కేవలం ${km.toFixed(1)} కి.మీ. వెంటనే లంగరు వేయండి.` },
        over: { en: 'You have drifted across the IMBL. Anchor, stay visible, and call the Coast Guard.', ta: 'நீங்கள் எல்லையைத் தாண்டிவிட்டீர்கள். நங்கூரம் இட்டு கடலோரக் காவல்படையை அழையுங்கள்.', te: 'మీరు సరిహద్దు దాటారు. లంగరు వేసి తీర రక్షక దళాన్ని పిలవండి.' },
      }[nl];
      if (msg) {
        addMsg('bot', `<div class="sec ${nl === 'warn' ? 'warn' : 'crit'}"><span class="tag">${TAG[lg].offline} · +${t.toFixed(1)} h</span><p>${esc(msg[lg])}</p></div>`, lg);
        beep(nl === 'warn' ? 660 : 880, nl === 'warn' ? 2 : 4);
        if (navigator.vibrate) navigator.vibrate(nl === 'warn' ? [200, 100, 200] : [400, 100, 400, 100, 400]);
        speak(msg[lg], lg);
        $('#phone').classList.remove('alertflash'); void $('#phone').offsetWidth; $('#phone').classList.add('alertflash');
      }
      if (nl === 'over') return stopSim();
    }
    if (t >= 12) stopSim({ en: 'Packet horizon (12 h) reached.', ta: '12 மணி நேரம் முடிந்தது.', te: '12 గంటలు పూర్తయ్యాయి.' }[lg]);
  }, 250);
}
function stopSim(msg) {
  clearInterval(state.sim); state.sim = null; $('#simBtn').textContent = 'Simulate engine failure';
  if (msg) sys(msg);
}
async function tamper() {
  if (!state.packet) return;
  // An attacker nudges the border 0.2° east so boats think they have more room.
  const b = JSON.parse(state.packet.body);
  b.imbl = b.imbl.map(([a, o]) => [a, +(o + 0.2).toFixed(4)]);
  state.packet = { ...state.packet, body: JSON.stringify(b), tampered: true };
  state.packetOK = await verifyPacket(state.packet);
  renderPacket();
  sys(state.packetOK === false ? 'Packet altered (border moved 0.2° east). Signature check FAILED — the phone rejects it.' : 'Packet altered — this browser cannot check Ed25519, so it could not tell.');
  showTab('packet');
}
function setOffline(on) {
  state.offline = on;
  if (state.sim && !on) stopSim();
  $('#phone').classList.toggle('offline', on);
  $('#offLbl').textContent = on ? 'Signal off' : 'Signal on';
  $('#sigText').textContent = on ? 'No signal · GEMINI packet' : '4G · online';
  $('#offBanner').hidden = !on;
  $('#offText').textContent = state.packetOK === false ? 'The stored packet failed its signature check.' :
    state.packet ? 'Running on the signed safety packet. Ask anything — answers come from the phone alone.' : 'No packet stored.';
  if (on) { answerLayer.clearLayers(); sys('Signal lost. Server unreachable — the phone switches to its signed packet.'); }
  else { sys('Signal back. Live agents and verifier available again.'); refreshPacket(); }
  loadLayer();
  renderPacket();
}

/* ------------------------------------------------------------------ speech */
/* Output: prefer a browser voice for the language (Edge ships natural Tamil voices);
   otherwise ask the server to speak with the host's Windows voice (Chrome can't see
   those). Input: the browser's speech recognition, in the selected language. */
const speech = { audio: null, hostVoices: null, noVoiceWarned: {}, utts: [], btn: null, token: 0 };
const LISTEN = {
  en: { idle: '▶ Listen', wait: '… Preparing voice', stop: '■ Stop' },
  ta: { idle: '▶ கேளுங்கள்', wait: '… குரல் தயாராகிறது', stop: '■ நிறுத்து' },
  te: { idle: '▶ వినండి', wait: '… గొంతు సిద్ధమవుతోంది', stop: '■ ఆపండి' },
};
function browserVoices() {
  if (!('speechSynthesis' in window)) return Promise.resolve([]);
  const v = speechSynthesis.getVoices();
  if (v.length) return Promise.resolve(v);
  return new Promise(res => {
    const done = () => res(speechSynthesis.getVoices());
    speechSynthesis.addEventListener('voiceschanged', done, { once: true });
    setTimeout(done, 1200);
  });
}
async function pickBrowserVoice(lg) {
  const vs = await browserVoices(), low = v => v.lang.toLowerCase().replace('_', '-');
  const loc = LOCALE[lg].toLowerCase(), base = lg;
  return vs.find(v => low(v) === loc && /natural/i.test(v.name)) || vs.find(v => low(v) === loc) || vs.find(v => low(v).startsWith(base));
}
function setListen(mode) {
  const b = speech.btn; if (!b) return;
  b.textContent = LISTEN[b.dataset.lg || 'en'][mode];
  b.dataset.mode = mode;
}
function stopSpeaking() {
  speech.token++;
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  speech.utts = [];
  if (speech.audio) { speech.audio.pause(); speech.audio = null; }
  setListen('idle'); speech.btn = null;
}
/* Split into sentence-sized pieces: long single utterances get dropped by some voices. */
function chunks(text, max = 220) {
  const parts = text.replace(/\s+/g, ' ').split(/(?<=[.!?।—:;])\s+/), out = [];
  for (const p of parts) {
    if (out.length && (out[out.length - 1] + ' ' + p).length <= max) out[out.length - 1] += ' ' + p;
    else out.push(p);
  }
  return out.filter(x => x.trim());
}
/* Resolves true once the browser voice actually starts, false if it errors or stalls. */
function speakBrowser(text, v, token) {
  return new Promise(resolve => {
    const pieces = chunks(text);
    let started = false;
    const fail = why => { if (!started) { started = true; resolve(false); console.warn('browser voice failed:', why); } };
    const watchdog = setTimeout(() => fail('no start within 6 s'), 6000);
    speechSynthesis.resume();                           // Chrome can be left paused
    pieces.forEach((p, k) => {
      const u = new SpeechSynthesisUtterance(p);
      u.voice = v; u.lang = v.lang; u.rate = .95;
      u.onstart = () => { if (token !== speech.token) return; if (!started) { started = true; clearTimeout(watchdog); setListen('stop'); resolve(true); } };
      u.onerror = e => { if (e.error === 'interrupted' || e.error === 'canceled') return; clearTimeout(watchdog); fail(e.error); };
      if (k === pieces.length - 1) u.onend = () => { if (token === speech.token) setListen('idle'); };
      speech.utts.push(u);                              // keep references: GC'd utterances go silent
    });
    setTimeout(() => { if (token === speech.token) speech.utts.forEach(u => speechSynthesis.speak(u)); }, 80);  // speak right after cancel() is dropped in Chromium
  });
}
async function speakServer(text, lg, token) {
  const r = await fetch('/api/tts', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, lang: lg }) });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    if (j.novoice) return 'novoice';
    throw new Error(j.error || r.statusText);
  }
  const blob = await r.blob();
  if (token !== speech.token) return 'cancelled';
  speech.audio = new Audio(URL.createObjectURL(blob));
  speech.audio.onended = () => { if (token === speech.token) setListen('idle'); };
  await speech.audio.play();
  setListen('stop');
  return 'ok';
}
async function speak(text, lg, btn) {
  if (btn && speech.btn === btn && btn.dataset.mode !== 'idle') { stopSpeaking(); return; }   // second click = stop
  stopSpeaking();
  if (!text) return;
  const token = speech.token;
  if (btn) { btn.dataset.lg = lg; speech.btn = btn; setListen('wait'); }
  const v = await pickBrowserVoice(lg);
  if (token !== speech.token) return;
  if (v && await speakBrowser(text, v, token)) return;
  if (token !== speech.token) return;
  if ('speechSynthesis' in window) speechSynthesis.cancel();
  try {
    const res = await speakServer(text, lg, token);
    if (res === 'novoice') { setListen('idle'); noVoice(lg, !!v); }
  } catch (e) {
    setListen('idle');
    sys('Could not speak the answer: ' + e.message);
  }
}
function noVoice(lg, browserTried) {
  const name = LANG_NAME[lg];
  if (speech.noVoiceWarned[lg]) { sys(`No ${name} voice available here — the answer is shown but not spoken.${lg === 'en' ? '' : ' Open this page in Microsoft Edge to hear it.'}`); return; }
  speech.noVoiceWarned[lg] = true;
  if (browserTried) { sys(`The browser's ${name} voice did not start (it needs internet in Edge), and this computer has no offline ${name} voice. Check your connection and sound output, then press Listen again.`); return; }
  sys(lg === 'ta'
    ? 'No Tamil voice on this computer, so the answer is shown but not spoken. Install one in Windows: Settings → Time & language → Speech → Manage voices → Add voices → Tamil. Or open this page in Microsoft Edge, which has Tamil voices built in.'
    : lg === 'te'
      ? 'This browser has no Telugu voice, and Windows does not offer one to install, so the answer is shown but not spoken. Open this page in Microsoft Edge, which has Telugu voices built in (needs internet).'
      : 'No English voice available to speak the answer.');
}
/* Which voice will read answers in the selected language; shown next to "Try asking". */
async function checkVoices(lg = state.lang) {
  try { speech.hostVoices = await api('/api/voices'); } catch { speech.hostVoices = null; }
  const inBrowser = !!(await pickBrowserVoice(lg));
  const ok = inBrowser || !!speech.hostVoices?.[lg];
  const el = $('#voiceState');
  el.textContent = `${LANG_NAME[lg]} voice: ${ok ? (inBrowser ? 'browser' : 'Windows') : 'not available'}`;
  el.dataset.ok = ok;
  return ok;
}

const MIC_ERR = {
  'not-allowed': 'Microphone is blocked. Click the mic/lock icon in the address bar, choose Allow, then tap the mic again.',
  'service-not-allowed': 'The browser blocked its speech service. Allow the microphone for this site, or use Chrome/Edge.',
  'audio-capture': 'No microphone found. Plug one in or check Windows sound settings (Settings → System → Sound → Input).',
  'network': 'Voice recognition needs internet: Chrome and Edge send the audio to their online speech service.',
  'language-not-supported': 'This browser cannot recognise that language. Try Chrome or Edge.',
};
const MIC_TXT = {
  en: { listen: 'Listening… speak now', hint: 'English · tap the mic to stop', none: "Didn't hear anything. Tap the mic and speak." },
  ta: { listen: 'கேட்கிறேன்… பேசுங்கள்', hint: 'தமிழ் · நிறுத்த மைக்கைத் தட்டவும்', none: 'எதுவும் கேட்கவில்லை. மீண்டும் மைக்கைத் தட்டிப் பேசுங்கள்.' },
  te: { listen: 'వింటున్నాను… మాట్లాడండి', hint: 'తెలుగు · ఆపడానికి మైక్ నొక్కండి', none: 'ఏమీ వినిపించలేదు. మళ్ళీ మైక్ నొక్కి మాట్లాడండి.' },
};
function initMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition, btn = $('#micBtn'), bar = $('#listenBar');
  if (!SR) { btn.onclick = () => sys('Voice input needs Chrome or Edge. Type your question instead.'); return; }
  let rec = null, heard = '';
  const setBar = (html, cls) => { bar.hidden = !html; bar.className = 'listen ' + (cls || ''); bar.innerHTML = html || ''; };
  const start = () => {
    stopSpeaking();                                   // don't let it hear its own answer
    heard = '';
    const T = MIC_TXT[state.lang];
    rec = new SR();
    rec.lang = LOCALE[state.lang];
    rec.interimResults = true; rec.continuous = false; rec.maxAlternatives = 1;
    btn.classList.add('rec'); btn.setAttribute('aria-label', 'Stop listening');
    setBar(`<i></i><b>${T.listen}</b><span>${T.hint}</span>`);
    rec.onresult = e => {
      let fin = '', interim = '';
      for (const r of e.results) { if (r.isFinal) fin += r[0].transcript; else interim += r[0].transcript; }
      heard = (fin || interim).trim();
      $('#q').value = heard;
      if (heard) setBar(`<i></i><b>${esc(heard)}</b>`, 'heard');
    };
    rec.onerror = e => {
      if (e.error === 'aborted') return;
      setBar(esc(e.error === 'no-speech' ? T.none : (MIC_ERR[e.error] || 'Voice input error: ' + e.error)), 'err');
    };
    rec.onend = () => {
      btn.classList.remove('rec'); btn.setAttribute('aria-label', 'Speak your question');
      rec = null;
      if (heard) { setBar(''); ask(heard, true); }
      else if (!bar.classList.contains('err')) setBar('');
    };
    try { rec.start(); } catch (e) { setBar(esc('Could not start the microphone: ' + e.message), 'err'); rec = null; btn.classList.remove('rec'); }
  };
  btn.onclick = () => (rec ? rec.stop() : start());
  // Shortcut: press M (when not typing in a field) to start or stop listening.
  document.addEventListener('keydown', e => {
    if (e.key.toLowerCase() === 'm' && !e.ctrlKey && !e.metaKey && !e.altKey && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) { e.preventDefault(); btn.click(); }
  });
}

/* ------------------------------------------------------------------ chrome */
function showTab(name) {
  $$('.tabs button').forEach(b => b.setAttribute('aria-selected', b.dataset.tab === name));
  $$('.pane').forEach(p => p.hidden = p.id !== 'pane-' + name);
}
function tick() {
  $('#clock').textContent = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }) + ' IST';
}

async function init() {
  const saved = store.get('theme'); if (saved) document.documentElement.dataset.theme = saved;
  state.meta = await api('/api/meta');
  if (!store.get('pubkey')) store.set('pubkey', state.meta.pubkey);   // pin the signing key at "install"
  $('#dataBadge').textContent = `SAMPLE DATA · issued ${new Date(state.meta.issued).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' })} IST`;
  $('#lang').value = state.lang;
  initMap(); updateReadout();
  renderChips(); initMic(); tick(); setInterval(tick, 15000);
  $('#tLbl').textContent = timeLabel(0);

  $('#composer').onsubmit = e => { e.preventDefault(); ask($('#q').value); };
  $('#lang').onchange = async e => {
    state.lang = e.target.value; store.set('lang', state.lang); renderChips();
    if (!(await checkVoices()) && state.lang !== 'en') noVoice(state.lang);
  };
  $('#offline').onchange = e => setOffline(e.target.checked);
  $('#fault').onchange = e => sys(e.target.checked ? 'Fault injected: the fishing-zone agent will now cite a chlorophyll value the satellite never recorded. Ask about fishing zones.' : 'Fault cleared.');
  $('#simBtn').onclick = startSim;
  $('#tamperBtn').onclick = tamper;
  $('#themeBtn').onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    document.documentElement.dataset.theme = cur === 'light' ? 'dark' : 'light'; store.set('theme', document.documentElement.dataset.theme);
    setTiles(); loadLayer(); if (state.last) drawAnswer(state.last.res.map);
  };
  $$('#layerSeg button').forEach(b => b.onclick = () => {
    state.layer = b.dataset.f; $$('#layerSeg button').forEach(x => x.setAttribute('aria-pressed', x === b)); loadLayer();
  });
  $('#curToggle').onchange = loadCurrents;
  $('#repToggle').onchange = e => e.target.checked ? repLayer.addTo(map) : map.removeLayer(repLayer);
  $('#tSlider').oninput = e => { state.ti = +e.target.value; $('#tLbl').textContent = timeLabel(state.ti); };
  $('#tSlider').onchange = loadLayer;
  $$('.tabs button').forEach(b => b.onclick = () => showTab(b.dataset.tab));

  addMsg('bot', `<div class="sec info"><span class="tag">SAGARAKSHAK</span><p>Ask me in English, Tamil or Telugu — or a mix, like “border enta duram?” — by voice or text. I'll check the satellite data, show my evidence, and say so when the data can't support an answer.</p><p class="note">Your boat is off Rameswaram, near the border. Drag it on the chart to move.</p></div>`);
  await Promise.all([loadLayer(), renderLoop(), refreshPacket(), checkVoices()]);
}
init().catch(e => { document.body.insertAdjacentHTML('afterbegin', `<p style="padding:12px;color:#ff6f61">Could not start: ${esc(e.message)}. Is server.py running?</p>`); });
