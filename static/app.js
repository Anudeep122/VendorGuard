/* VendorGuard SPA - vanilla JS, no build step */
(() => {
'use strict';

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clone = (o) => JSON.parse(JSON.stringify(o));
const view = $('#app');

const STAGES = [
  ['intake', 'Intake & normalization'], ['completeness', 'Completeness'], ['format', 'Format validation'],
  ['cross', 'Cross-field consistency'], ['risk', 'Risk & fraud signals'], ['documents', 'Document checks'],
  ['decision', 'Decision'], ['communication', 'Communication'],
];
const DTYPE = {
  approved_clean: 'Approved - clean', approved_with_notes: 'Approved - with notes',
  needs_vendor_action: 'Needs vendor action', needs_human_review: 'Needs human review', rejected_critical: 'Rejected - critical finding',
};
const COUNTRIES = { IN: 'India', US: 'United States', GB: 'United Kingdom', DE: 'Germany', AE: 'United Arab Emirates' };
const ALWAYS_REQ = ['company.legal_name', 'company.country', 'company.address.line1', 'company.address.city', 'company.address.postal_code', 'contact.email', 'bank.account_holder', 'bank.bank_country'];
const RULES = {
  IN: { req: ['tax.tax_id', 'tax.pan', 'bank.account_number', 'bank.ifsc'], docs: ['TAX_CERTIFICATE', 'BANK_LETTER'],
        hints: { 'tax.tax_id': 'GSTIN, 15 characters (e.g. 27AAPFU0939F1ZV)', 'tax.pan': '10 characters, e.g. ABCDE1234F', 'bank.ifsc': '4 letters + 0 + 6 characters, e.g. HDFC0001234', 'company.address.postal_code': '6-digit PIN code' } },
  US: { req: ['tax.tax_id', 'bank.account_number', 'bank.routing_number'], docs: ['W9', 'BANK_LETTER'],
        hints: { 'tax.tax_id': 'EIN, format 12-3456789', 'bank.routing_number': '9-digit ABA routing number', 'company.address.postal_code': '5-digit ZIP or ZIP+4' } },
  GB: { req: ['tax.tax_id', 'bank.swift_bic'], anyOf: [['bank.account_number', 'bank.iban']], docs: ['TAX_CERTIFICATE', 'BANK_LETTER'],
        hints: { 'tax.tax_id': 'UK VAT number: GB + 9 digits', 'bank.iban': 'Account number or IBAN is required', 'bank.swift_bic': '8 or 11 characters, e.g. NWBKGB2L', 'company.address.postal_code': 'UK postcode, e.g. EC1M 5PQ' } },
  DE: { req: ['tax.tax_id', 'bank.iban', 'bank.swift_bic'], docs: ['TAX_CERTIFICATE', 'BANK_LETTER'],
        hints: { 'tax.tax_id': 'German VAT number: DE + 9 digits', 'bank.iban': '22 characters, starts with DE', 'bank.swift_bic': '8 or 11 characters', 'company.address.postal_code': '5 digits' } },
  AE: { req: ['tax.tax_id', 'bank.iban', 'bank.swift_bic'], docs: ['TAX_CERTIFICATE', 'BANK_LETTER'],
        hints: { 'tax.tax_id': 'TRN, 15 digits', 'bank.iban': '23 characters, starts with AE', 'bank.swift_bic': '8 or 11 characters' } },
};
const DOC_TYPES = ['TAX_CERTIFICATE', 'BANK_LETTER', 'INCORPORATION_CERT', 'W9', 'W8BEN', 'OTHER'];
const FORM = [
  ['Company', [
    ['company.legal_name', 'Legal name', 'text', 'full'], ['company.trading_name', 'Trading name', 'text'],
    ['company.country', 'Country of registration', 'country'], ['company.registration_number', 'Registration number', 'text'],
    ['company.incorporation_date', 'Incorporation date', 'date'], ['company.website', 'Website', 'text'],
    ['company.address.line1', 'Address line 1', 'text', 'full'], ['company.address.city', 'City', 'text'],
    ['company.address.postal_code', 'Postal code', 'text'], ['company.address.country', 'Address country', 'country']]],
  ['Tax', [
    ['tax.tax_id', 'Tax ID', 'text'], ['tax.tax_id_type', 'Tax ID type', 'select:,GSTIN,PAN,EIN,VAT'], ['tax.pan', 'PAN (India)', 'text']]],
  ['Contact', [
    ['contact.name', 'Contact name', 'text'], ['contact.email', 'Email', 'text'], ['contact.phone', 'Phone', 'text']]],
  ['Bank', [
    ['bank.bank_name', 'Bank name', 'text'], ['bank.account_holder', 'Account holder', 'text'],
    ['bank.account_number', 'Account number', 'text'], ['bank.iban', 'IBAN', 'text'],
    ['bank.swift_bic', 'SWIFT / BIC', 'text'], ['bank.ifsc', 'IFSC (India)', 'text'],
    ['bank.routing_number', 'Routing number (US)', 'text'], ['bank.bank_country', 'Bank country', 'country']]],
];

const state = { sub: emptySub(), issues: [], parentRun: null, sampleKey: null, samples: null, lastRun: null, es: null, poll: null, llm: 'none' };

function emptySub() {
  return {
    company: { legal_name: '', trading_name: '', country: '', registration_number: '', incorporation_date: '', address: { line1: '', city: '', postal_code: '', country: '' }, website: '' },
    tax: { tax_id: '', tax_id_type: '', pan: '' }, contact: { name: '', email: '', phone: '' },
    bank: { bank_name: '', account_holder: '', account_number: '', iban: '', swift_bic: '', ifsc: '', routing_number: '', bank_country: '' },
    documents: [],
  };
}
const getPath = (o, p) => p.split('.').reduce((a, k) => (a == null ? a : a[k]), o);
function setPath(o, p, v) {
  const ks = p.split('.'); let cur = o;
  ks.slice(0, -1).forEach((k) => { if (typeof cur[k] !== 'object' || cur[k] === null) cur[k] = {}; cur = cur[k]; });
  cur[ks[ks.length - 1]] = v;
}

/* ------------------------------------------------------------ helpers */
async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...opts });
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch (e) { /* ignore */ } throw new Error(m); }
  return r.json();
}
function toast(msg, err) {
  const t = document.createElement('div'); t.className = 'toast' + (err ? ' err' : ''); t.textContent = msg;
  $('#toasts').appendChild(t); setTimeout(() => t.remove(), 4500);
}
const fmtDur = (ms) => (ms == null ? '-' : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
const fmtTime = (iso) => { try { return new Date(iso).toLocaleString(undefined, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso || ''; } };
const badge = (s, cls = '') => `<span class="badge ${esc(s)} ${cls}">${esc(s)}</span>`;
const chip = (s) => `<span class="chip chip-${esc(s)}">${esc(s)}</span>`;
function evChips(ev) {
  if (!ev || typeof ev !== 'object') return '';
  return Object.entries(ev).filter(([k, v]) => v !== null && v !== '' && !['system', 'field'].includes(k) && typeof v !== 'object')
    .slice(0, 6).map(([k, v]) => `<span class="ev" title="${esc(k)}: ${esc(v)}"><b>${esc(k)}</b>${esc(String(v).slice(0, 48))}</span>`).join('');
}
function findingLi(f, i) {
  return `<li class="finding sev-${esc(f.severity)}" style="animation-delay:${i * 70}ms">${chip(f.severity)}
    <div><div class="f-msg">${esc(f.message)}</div><div class="f-meta"><code>${esc(f.rule_id)}</code>${evChips(f.evidence)}</div></div></li>`;
}
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); toast('Copied to clipboard'); }
  catch (e) { const ta = document.createElement('textarea'); ta.value = t; document.body.appendChild(ta); ta.select(); try { document.execCommand('copy'); toast('Copied to clipboard'); } catch (e2) { toast('Copy failed', true); } ta.remove(); }
}
function ringSvg(score) {
  const r = 42, c = 2 * Math.PI * r, col = score >= 60 ? '#dc2626' : score >= 25 ? '#f59e0b' : '#16a34a';
  return `<div class="ring" role="img" aria-label="Risk score ${score} of 100"><svg width="104" height="104" viewBox="0 0 104 104"><circle cx="52" cy="52" r="${r}" fill="none" stroke="#e2e8f0" stroke-width="9"/>
    <circle cx="52" cy="52" r="${r}" fill="none" stroke="${col}" stroke-width="9" stroke-linecap="round" stroke-dasharray="${(c * score / 100).toFixed(1)} ${c.toFixed(1)}"/></svg>
    <div class="num"><div>${score}<small>RISK / 100</small></div></div></div>`;
}

/* ------------------------------------------------------------ router */
function stopLive() { if (state.es) { state.es.close(); state.es = null; } if (state.poll) { clearInterval(state.poll); state.poll = null; } }
function route() {
  stopLive(); closeDrawer();
  const h = location.hash.replace(/^#\/?/, '') || 'new';
  const [page, arg] = h.split('/');
  $$('.nav a').forEach((a) => a.classList.toggle('active', a.dataset.nav === page));
  view.scrollTo?.(0, 0); window.scrollTo(0, 0);
  if (page === 'run') { if (arg) renderRun(arg); else if (state.lastRun) location.replace('#/run/' + state.lastRun); else renderNoRun(); }
  else if (page === 'dashboard') renderDashboard();
  else if (page === 'samples') renderSamples();
  else renderNew();
}
window.addEventListener('hashchange', route);

async function loadSamples() {
  if (state.samples) return state.samples;
  state.samples = await api('/api/samples');
  return state.samples;
}

/* ------------------------------------------------------------ New Review */
async function renderNew() {
  view.innerHTML = `
    <div class="page-head"><div><h1>New vendor review</h1><p>Submit a vendor onboarding package. Rules decide; every decision traces to named rules with evidence.</p></div>
      <button class="btn primary lg" id="runBtn">Run review &rarr;</button></div>
    <div class="sample-bar"><strong>Load sample&hellip;</strong>
      <select id="sampleSel" aria-label="Load a sample scenario"><option value="">Choose one of the 9 scenarios</option></select>
      <span id="sampleChip"></span></div>
    <div id="issuesPanel"></div>
    <div class="new-grid">
      <form class="card card-pad" id="form" autocomplete="off" onsubmit="return false"></form>
      <div class="card card-pad sticky"><div class="card-title"><h2>JSON editor</h2><div class="row"><button class="btn sm" id="fmtBtn" type="button">Format</button><button class="btn sm" id="clearBtn" type="button">Clear form</button></div></div>
        <textarea class="json-box" id="json" spellcheck="false" aria-label="Submission JSON"></textarea><div class="json-status ok" id="jsonStatus">Valid JSON</div></div>
    </div>`;
  buildForm(); syncJson(); applyHints(); renderIssues(); renderDocs();
  $('#runBtn').onclick = submitReview;
  $('#fmtBtn').onclick = () => { try { $('#json').value = JSON.stringify(JSON.parse($('#json').value), null, 2); } catch (e) { toast('JSON is not valid', true); } };
  $('#clearBtn').onclick = () => { state.sub = emptySub(); state.issues = []; state.parentRun = null; state.sampleKey = null; fillForm(); syncJson(); renderDocs(); renderIssues(); $('#sampleSel').value = ''; $('#sampleChip').innerHTML = ''; };
  $('#json').addEventListener('input', onJsonInput);
  try {
    const samples = await loadSamples();
    const sel = $('#sampleSel');
    samples.forEach((s) => { const o = document.createElement('option'); o.value = s.key; o.textContent = `${s.key.split('_')[0]} - ${s.title}`; sel.appendChild(o); });
    sel.onchange = () => loadSample(sel.value);
    if (state.sampleKey) { sel.value = state.sampleKey; showChip(state.sampleKey); }
  } catch (e) { toast('Could not load samples: ' + e.message, true); }
}
function showChip(key) {
  const chipEl = $('#sampleChip'); if (!chipEl) return;
  const s = (state.samples || []).find((x) => x.key === key); if (!s) { chipEl.innerHTML = ''; return; }
  chipEl.innerHTML = `Expected: ${badge(s.expected.status)} <span class="chip neutral">${esc(s.expected.decision_type)}</span> <span class="muted small">${esc(s.tests)}</span>`;
}
function loadSample(key) {
  if (!key) { state.sampleKey = null; if ($('#sampleChip')) $('#sampleChip').innerHTML = ''; return; }
  const s = state.samples.find((x) => x.key === key);
  state.sub = clone(s.submission); state.issues = []; state.parentRun = null; state.sampleKey = key;
  fillForm(); syncJson(); renderDocs(); renderIssues(); applyHints(); showChip(key);
}
function buildForm() {
  const f = $('#form');
  f.innerHTML = FORM.map(([sec, items]) => `<fieldset><legend>${sec}</legend><div class="grid2">${items.map(([path, label, type, span]) => {
    const id = 'f_' + path.replace(/\./g, '_');
    let ctl;
    if (type.startsWith('select:')) ctl = `<select id="${id}" data-path="${path}">${type.slice(7).split(',').map((o) => `<option value="${o}">${o || '-'}</option>`).join('')}</select>`;
    else if (type === 'country') ctl = `<input id="${id}" data-path="${path}" list="countries" maxlength="3" placeholder="IN / US / GB / DE / AE" style="text-transform:uppercase">`;
    else ctl = `<input id="${id}" data-path="${path}" type="${type === 'date' ? 'date' : 'text'}">`;
    return `<div class="field ${span || ''}" data-fp="${path}"><label for="${id}">${label}</label>${ctl}<div class="hint"></div><div class="issue-msg"></div></div>`;
  }).join('')}</div></fieldset>`).join('') +
  `<fieldset><legend>Documents</legend><div class="docs-req" id="docsReq"></div><div id="docs"></div>
    <div class="row"><button class="btn sm" type="button" id="addDoc">+ Add document</button><label class="btn sm" for="upFile" style="margin:0">Upload file&hellip;</label><input type="file" id="upFile" hidden accept=".pdf,.png,.jpg,.jpeg,.webp">
    <span class="muted small" id="upNote"></span></div></fieldset>`;
  fillForm();
  $$('[data-path]', f).forEach((el) => el.addEventListener('input', () => {
    let v = el.value; if (el.list && el.dataset.path !== undefined && el.getAttribute('list')) v = v.toUpperCase();
    setPath(state.sub, el.dataset.path, v); syncJson(); if (el.dataset.path === 'company.country') applyHints();
  }));
  $('#addDoc').onclick = () => { state.sub.documents.push({ doc_type: 'TAX_CERTIFICATE', filename: '', extracted: { name_on_document: '', id_number: '', issue_date: '' } }); renderDocs(); syncJson(); };
  $('#upFile').onchange = uploadFile;
}
function fillForm() {
  $$('[data-path]').forEach((el) => { if (document.activeElement !== el) { const v = getPath(state.sub, el.dataset.path); el.value = v == null ? '' : String(v); } });
}
function syncJson() { const t = $('#json'); if (t && document.activeElement !== t) { t.value = JSON.stringify(state.sub, null, 2); setJsonStatus(true); } }
function setJsonStatus(ok, msg) { const s = $('#jsonStatus'); if (!s) return; s.className = 'json-status ' + (ok ? 'ok' : 'bad'); s.textContent = ok ? 'Valid JSON' : (msg || 'Invalid JSON'); }
function onJsonInput() {
  try {
    const o = JSON.parse($('#json').value);
    if (o === null || typeof o !== 'object' || Array.isArray(o)) throw new Error('Top level must be an object');
    state.sub = o; setJsonStatus(true); fillForm(); renderDocs(); applyHints();
  } catch (e) { setJsonStatus(false, 'Invalid JSON: ' + e.message); }
}
function applyHints() {
  const cc = String(getPath(state.sub, 'company.country') || '').toUpperCase(); const rule = RULES[cc];
  $$('.field[data-fp]').forEach((fl) => {
    const p = fl.dataset.fp; const anyOf = rule && (rule.anyOf || []).some((g) => g.includes(p));
    fl.classList.toggle('req', ALWAYS_REQ.includes(p) || !!(rule && rule.req.includes(p)) || (anyOf && p === 'bank.iban' && false));
    $('.hint', fl).textContent = (rule && rule.hints[p]) || '';
  });
  const req = $('#docsReq'); if (!req) return;
  const have = new Set((state.sub.documents || []).map((d) => d.doc_type));
  req.innerHTML = rule ? `<span class="muted small">Required for ${COUNTRIES[cc]}:</span>` + rule.docs.map((d) => `<span class="chip ${have.has(d) ? 'have' : 'miss'}">${have.has(d) ? '✓' : '○'} ${d}</span>`).join('') : '<span class="muted small">Select a country to see required documents.</span>';
  markIssues();
}
function renderDocs() {
  const box = $('#docs'); if (!box) return;
  if (!Array.isArray(state.sub.documents)) state.sub.documents = [];
  box.innerHTML = state.sub.documents.map((d, i) => {
    const ex = d.extracted || {};
    return `<div class="docrow" data-i="${i}"><select data-k="doc_type" aria-label="Document type">${DOC_TYPES.map((t) => `<option ${t === d.doc_type ? 'selected' : ''}>${t}</option>`).join('')}</select>
      <input data-k="filename" placeholder="filename.pdf" value="${esc(d.filename)}" aria-label="Filename">
      <input data-k="x.name_on_document" placeholder="Name on document" value="${esc(ex.name_on_document)}" aria-label="Name on document">
      <input class="c-id" data-k="x.id_number" placeholder="ID number" value="${esc(ex.id_number)}" aria-label="ID number">
      <input class="c-date" data-k="x.issue_date" type="date" value="${esc(ex.issue_date)}" aria-label="Issue date">
      <button type="button" class="x" aria-label="Remove document" title="Remove">&times;</button></div>`;
  }).join('') || '<p class="muted small" style="margin:0 0 8px">No documents attached yet.</p>';
  $$('.docrow', box).forEach((row) => {
    const i = +row.dataset.i;
    $$('[data-k]', row).forEach((el) => el.addEventListener('input', () => {
      const k = el.dataset.k; const d = state.sub.documents[i];
      if (k.startsWith('x.')) { d.extracted = d.extracted || {}; d.extracted[k.slice(2)] = el.value; } else d[k] = el.value;
      syncJson(); applyHints();
    }));
    $('.x', row).onclick = () => { state.sub.documents.splice(i, 1); renderDocs(); syncJson(); applyHints(); };
  });
  applyHints();
}
async function uploadFile(e) {
  const file = e.target.files[0]; if (!file) return;
  const fd = new FormData(); fd.append('file', file);
  $('#upNote').textContent = 'Uploading…';
  try {
    const r = await fetch('/api/upload', { method: 'POST', body: fd }); if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const j = await r.json();
    state.sub.documents.push({ doc_type: j.doc_type && DOC_TYPES.includes(j.doc_type) ? j.doc_type : 'OTHER', filename: file.name, extracted: j.extracted || {} });
    renderDocs(); syncJson(); $('#upNote').textContent = j.note;
  } catch (err) { $('#upNote').textContent = ''; toast('Upload failed: ' + err.message, true); }
  e.target.value = '';
}
function renderIssues() {
  const p = $('#issuesPanel'); if (!p) return;
  if (!state.parentRun) { p.innerHTML = ''; return; }
  p.innerHTML = `<div class="issues-panel" role="region" aria-label="Open issues"><div class="row" style="justify-content:space-between"><strong>Resubmitting run <a href="#/run/${esc(state.parentRun)}">${esc(state.parentRun)}</a> &mdash; ${state.issues.length} open issue(s) to fix</strong>
    <button class="btn sm" id="cancelResub" type="button">Submit as new instead</button></div>
    <ul>${state.issues.map((f) => `<li>${chip(f.severity)}<span>${esc(f.message)}${f.action ? `<br><span class="muted">&rarr; ${esc(f.action)}</span>` : ''}</span></li>`).join('')}</ul></div>`;
  $('#cancelResub').onclick = () => { state.parentRun = null; state.issues = []; renderIssues(); markIssues(); };
}
function markIssues() {
  $$('.field.issue').forEach((f) => { f.classList.remove('issue'); $('.issue-msg', f).textContent = ''; });
  $$('.docrow.issue').forEach((f) => f.classList.remove('issue'));
  if (!state.parentRun) return;
  state.issues.forEach((f) => {
    const fp = f.evidence && f.evidence.field;
    const el = fp && $(`.field[data-fp="${fp}"]`);
    if (el) { el.classList.add('issue'); $('.issue-msg', el).textContent = f.action || f.message; }
    else if (f.rule_id === 'COMPLETENESS_MISSING_DOC' || f.rule_id.startsWith('DOC_')) {
      const fn = f.evidence && f.evidence.filename; $$('.docrow').forEach((r) => { if (fn && state.sub.documents[+r.dataset.i]?.filename === fn) r.classList.add('issue'); });
    }
  });
}
async function submitReview() {
  let sub; try { sub = JSON.parse($('#json').value || JSON.stringify(state.sub)); } catch (e) { return toast('Fix the JSON before running: ' + e.message, true); }
  if (document.activeElement !== $('#json')) sub = state.sub;
  const btn = $('#runBtn'); btn.disabled = true; btn.textContent = 'Starting…';
  try {
    let parent = state.parentRun;
    const sample = state.sampleKey && state.samples.find((s) => s.key === state.sampleKey);
    if (!parent && sample && sample.parent_sample && JSON.stringify(sample.submission) === JSON.stringify(sub)) {
      const r = await api('/api/runs', { method: 'POST', body: JSON.stringify({ sample: sample.key }) });   // server links to / creates the parent run
      state.lastRun = r.run_id; return (location.hash = '#/run/' + r.run_id);
    }
    const r = await api(parent ? `/api/runs/${parent}/resubmit` : '/api/runs', { method: 'POST', body: JSON.stringify(sub) });
    state.parentRun = null; state.issues = []; state.lastRun = r.run_id; location.hash = '#/run/' + r.run_id;
  } catch (e) { toast('Could not start run: ' + e.message, true); btn.disabled = false; btn.innerHTML = 'Run review &rarr;'; }
}

/* ------------------------------------------------------------ Live Run */
function renderNoRun() {
  view.innerHTML = `<div class="card empty"><h2>No run yet</h2><p>Start a review to watch the pipeline execute stage by stage.</p><a class="btn primary" href="#/new">New review</a> <a class="btn" href="#/samples">Browse samples</a></div>`;
}
function stepHTML(key, label) {
  return `<li class="step pending" id="st-${key}"><div class="step-ico" aria-hidden="true">○</div>
    <div class="step-main"><button class="step-head" aria-expanded="false"><div><div class="step-title">${label}</div><div class="step-sub">Waiting</div></div><span class="step-time"></span><span class="chev">&#9656;</span></button>
    <div class="step-body"></div></div></li>`;
}
async function renderRun(id) {
  state.lastRun = id;
  view.innerHTML = `<div class="run-head"><div><h1 id="rhTitle">Review run</h1><div class="meta" id="rhMeta"><span class="vid">${esc(id)}</span><span id="rhBadge">${badge('Running')}</span></div></div><div id="rhRight"></div></div>
    <div id="resubBanner"></div>
    <div class="run-grid"><div class="card"><ol class="stepper" id="stepper">${STAGES.map(([k, l]) => stepHTML(k, l)).join('')}</ol></div>
    <div id="decisionBox"></div><div id="emailBox"></div></div>`;
  $$('.step-head').forEach((h) => h.onclick = () => { const s = h.closest('.step'); const o = s.classList.toggle('open'); h.setAttribute('aria-expanded', o); });
  const emails = [];
  let sub = null;
  try {
    const d = await api('/api/runs/' + id); sub = d.submission; setHeader(d);
  } catch (e) { view.innerHTML = `<div class="card err-box"><h2>Run not found</h2><p>${esc(e.message)}</p><a class="btn" href="#/new">Back to New Review</a></div>`; return; }
  const es = new EventSource(`/api/runs/${id}/stream`); state.es = es;
  const on = (t, fn) => es.addEventListener(t, (e) => { try { fn(JSON.parse(e.data)); } catch (err) { console.error(err); } });
  on('stage_started', (d) => {
    const s = $('#st-' + d.stage_key); if (!s) return; s.className = 'step running';
    $('.step-ico', s).innerHTML = '<div class="spinner"></div>'; $('.step-sub', s).textContent = 'Running…';
  });
  on('stage_finished', (d) => {
    const s = $('#st-' + d.stage_key); if (!s) return;
    const icons = { ok: '✓', warn: '⚠', error: '✕', skipped: '–' };
    s.className = 'step done ' + d.status; $('.step-ico', s).textContent = icons[d.status] || '✓';
    const shown = d.findings.filter((f) => !['DECISION', 'EMAIL_DRAFTED'].includes(f.rule_id));
    const cnt = (sev) => shown.filter((f) => f.severity === sev).length;
    const parts = [];
    if (d.passes.length && d.status !== 'skipped') parts.push(`${d.passes.length} check${d.passes.length > 1 ? 's' : ''} passed`);
    [['CRITICAL', 'critical'], ['ERROR', 'error'], ['WARN', 'warning'], ['INFO', 'note']].forEach(([sev, w]) => { const n = cnt(sev); if (n) parts.push(`${n} ${w}${n > 1 ? 's' : ''}`); });
    $('.step-sub', s).textContent = d.status === 'skipped' ? 'Skipped' : (parts.join(' · ') || 'No findings');
    $('.step-time', s).textContent = d.duration_ms ? fmtDur(d.duration_ms) : '';
    $('.step-body', s).innerHTML = (shown.length ? `<ul class="findings">${shown.map(findingLi).join('')}</ul>` : '') +
      (d.passes.length ? `<ul class="passes">${d.passes.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : '');
    if (shown.length || d.passes.length) { if (shown.some((f) => f.severity !== 'INFO') || d.status === 'warn' || d.status === 'error') { s.classList.add('open'); $('.step-head', s).setAttribute('aria-expanded', 'true'); } }
    s.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  });
  on('decision', (d) => renderDecision(d));
  on('email', (e) => { emails.push(e); renderEmails(emails); });
  on('run_finished', async (d) => {
    es.close(); state.es = null;
    try { const det = await api('/api/runs/' + id); setHeader(det); renderBanner(det); renderActions(det); } catch (e) { /* non-fatal */ }
  });
  es.onerror = () => { if (es.readyState === EventSource.CLOSED) toast('Live connection closed', true); };
}
function setHeader(d) {
  $('#rhTitle').textContent = d.vendor_name || 'Review run';
  const meta = $('#rhMeta'); if (!meta) return;
  meta.innerHTML = `<span class="vid">${esc(d.id)}</span>${d.country ? `<span class="chip neutral">${esc(d.country)}</span>` : ''}<span>${badge(d.status === 'Running' ? 'Running' : d.status)}</span>
    ${d.decision_type ? `<span class="chip neutral">${esc(d.decision_type)}</span>` : ''}${d.duration_ms ? `<span class="small">${fmtDur(d.duration_ms)}</span>` : ''}
    ${d.parent_run_id ? `<a href="#/run/${esc(d.parent_run_id)}">↳ resubmission of ${esc(d.parent_run_id)}</a>` : ''}`;
}
function renderBanner(d) {
  const r = d.resubmission; const b = $('#resubBanner'); if (!r || !b) return;
  b.innerHTML = `<div class="banner"><div style="font-size:20px">↳</div><div><strong>Resubmission of <a href="#/run/${esc(r.parent.id)}">${esc(r.parent.vendor_name)} (run ${esc(r.parent.id)})</a></strong>
    <span class="muted"> - previous status: ${esc(r.parent.status)}</span>
    <ul>${r.resolved.map((x) => `<li class="res"><code>${esc(x.rule_id)}</code> resolved: ${esc(x.message)}</li>`).join('')}${r.still_open.map((x) => `<li class="open"><code>${esc(x.rule_id)}</code> still open: ${esc(x.message)}</li>`).join('')}</ul></div></div>`;
}
function renderDecision(d) {
  $('#decisionBox').innerHTML = `<section class="card decision ${esc(d.status)}" aria-label="Decision">
    <div><h2>Decision</h2>${badge(d.status, 'xl')}<div class="dtype">${esc(DTYPE[d.decision_type] || d.decision_type)}</div><div class="muted">${esc(d.meaning)}</div><p class="summary">${esc(d.summary)}</p></div>
    ${ringSvg(d.risk_score)}
    <div class="why"><h3>Why</h3>${d.reasoning.length ? `<ol>${d.reasoning.map((r) => `<li>${chip(r.severity)}<div><div>${esc(r.sentence)}</div><div class="f-meta"><code>${esc(r.rule_id)}</code>${evChips(r.evidence)}</div></div></li>`).join('')}</ol>` : '<p class="muted" style="margin:6px 0 0">No warnings, errors or critical findings were raised.</p>'}
      ${d.notes.length ? `<h3 style="margin-top:14px">Notes</h3><ol>${d.notes.map((n) => `<li>${chip('INFO')}<div><div>${esc(n.sentence)}</div><div class="f-meta"><code>${esc(n.rule_id)}</code></div></div></li>`).join('')}</ol>` : ''}
      <p class="muted small" style="margin:12px 0 0">The risk score is supporting information only - the decision is made by the rules above, never by the score or an AI model.</p></div>
    <div class="actions" id="actions"></div></section>`;
  $('#decisionBox').scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
function renderActions(det) {
  const a = $('#actions'); if (!a) return;
  const open = det.findings.filter((f) => ['ERROR', 'CRITICAL'].includes(f.severity)).length;
  a.innerHTML = `<button class="btn primary" id="reBtn" ${open ? '' : 'title="No open issues, but you can still edit and resubmit"'}>Resubmit corrected version</button>
    <a class="btn" href="/api/runs/${esc(det.id)}/export" download>Export JSON</a><button class="btn" id="againBtn">Run again</button><a class="btn" href="#/dashboard">View in dashboard</a>`;
  const stripped = () => { const s = clone(det.submission); delete s.submission_id; delete s.parent_run_id; return s; };
  $('#reBtn').onclick = () => { state.sub = stripped(); state.issues = det.findings.filter((f) => ['ERROR', 'CRITICAL'].includes(f.severity)); state.parentRun = det.id; state.sampleKey = null; location.hash = '#/new'; };
  $('#againBtn').onclick = async () => { try { const r = await api('/api/runs', { method: 'POST', body: JSON.stringify(stripped()) }); location.hash = '#/run/' + r.run_id; } catch (e) { toast(e.message, true); } };
}
function emailHTML(e) {
  const internal = e.audience === 'internal';
  return `<div class="email-body"><div class="email-meta"><span>To</span><span>${esc(e.to)} ${internal ? '<span class="chip neutral">internal</span>' : '<span class="chip neutral">vendor</span>'}</span><span>Subject</span><strong>${esc(e.subject)}</strong></div><pre>${esc(e.body)}</pre></div>`;
}
function renderEmails(list) {
  const box = $('#emailBox'); let cur = box._cur || 0; if (cur >= list.length) cur = 0;
  const lab = { approved: 'Welcome email', needs_vendor_action: 'Vendor email', human_review: 'Reviewer notification', holding: 'Vendor holding message', rejected: 'Vendor message', compliance_alert: 'Compliance alert' };
  box.innerHTML = `<section class="card email" aria-label="Drafted email"><div class="card-title" style="padding:16px 20px 0;margin:0"><h2>Drafted ${list.length > 1 ? 'messages' : 'email'}</h2>
    <div class="row"><span class="chip draft">Draft (not sent)</span><span class="chip ${list[cur].source === 'ai' ? 'ai' : 'neutral'}">${list[cur].source === 'ai' ? 'Email: AI-drafted' : 'Email: template'}</span><button class="btn sm" id="copyBtn">Copy</button></div></div>
    <div class="tabs" role="tablist">${list.map((e, i) => `<button class="tab ${i === cur ? 'active' : ''}" role="tab" data-i="${i}">${esc(lab[e.kind] || e.kind)}</button>`).join('')}</div>${emailHTML(list[cur])}</section>`;
  $$('.tab', box).forEach((t) => t.onclick = () => { box._cur = +t.dataset.i; renderEmails(list); });
  $('#copyBtn').onclick = () => copyText(`To: ${list[cur].to}\nSubject: ${list[cur].subject}\n\n${list[cur].body}`);
}

/* ------------------------------------------------------------ Dashboard */
let charts = [];
async function renderDashboard() {
  view.innerHTML = `<div class="page-head"><div><h1>Dashboard</h1><p>History, status and outputs across all runs.</p></div><a class="btn primary" href="#/new">New review</a></div>
    <div class="kpis" id="kpis">${Array(6).fill('<div class="card kpi"><div class="skeleton" style="width:60%"></div><div class="skeleton" style="height:30px;margin-top:10px"></div></div>').join('')}</div>
    <div class="charts"><div class="card card-pad"><div class="card-title"><h2>Outcomes</h2></div><div class="chart-box"><canvas id="cStatus" role="img" aria-label="Status doughnut chart"></canvas></div></div>
      <div class="card card-pad"><div class="card-title"><h2>Top triggered rules</h2></div><div class="chart-box"><canvas id="cRules" role="img" aria-label="Top rules bar chart"></canvas></div></div></div>
    <div class="card card-pad"><div class="card-title"><h2>Runs</h2></div>
      <div class="filters"><input type="search" id="fSearch" placeholder="Search vendor or run id" aria-label="Search runs"><select id="fStatus" aria-label="Status"><option value="">All statuses</option><option>Approved</option><option>Pending</option><option>Rejected</option></select>
        <select id="fCountry" aria-label="Country"><option value="">All countries</option>${Object.keys(COUNTRIES).map((c) => `<option>${c}</option>`).join('')}</select><input type="date" id="fSince" aria-label="From date" title="From date"></div>
      <div class="tbl-wrap"><table><thead><tr><th>Vendor</th><th>Country</th><th>Status</th><th>Decision type</th><th>Risk</th><th>Started</th><th>Parent</th></tr></thead><tbody id="rows"><tr><td colspan="7" class="empty">Loading…</td></tr></tbody></table></div></div>`;
  let last = '';
  const load = async (force) => {
    try {
      const q = new URLSearchParams(); const v = (id) => $(id).value;
      if (v('#fSearch')) q.set('search', v('#fSearch')); if (v('#fStatus')) q.set('status', v('#fStatus')); if (v('#fCountry')) q.set('country', v('#fCountry')); if (v('#fSince')) q.set('since', v('#fSince'));
      const [st, runs] = await Promise.all([api('/api/stats'), api('/api/runs?' + q)]);
      const sig = JSON.stringify([st, runs]); if (sig === last && !force) return; last = sig;
      drawKpis(st); drawCharts(st); drawRows(runs);
    } catch (e) { $('#rows').innerHTML = `<tr><td colspan="7" class="err-box">Could not load data: ${esc(e.message)} <button class="btn sm" id="retry">Retry</button></td></tr>`; $('#retry') && ($('#retry').onclick = () => load(true)); }
  };
  let t; ['#fSearch', '#fStatus', '#fCountry', '#fSince'].forEach((s) => $(s).addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => load(true), 200); }));
  await load(true);
  state.poll = setInterval(() => { if (!$('.drawer')) load(false); }, 6000);
}
function drawKpis(s) {
  const t = s.total || 0, pct = (n) => (t ? Math.round((100 * (n || 0)) / t) : 0), b = s.by_status || {};
  const k = [['Total runs', t, '', ''], ['Approved', pct(b.Approved) + '%', 'g', `${b.Approved || 0} runs`], ['Pending', pct(b.Pending) + '%', 'a', `${b.Pending || 0} runs`], ['Rejected', pct(b.Rejected) + '%', 'r', `${b.Rejected || 0} runs`],
    ['Avg processing time', fmtDur(s.avg_duration_ms), '', 'rules engine, excl. demo delay'], ['Need human review', s.needs_human_review || 0, 'a', 'escalated to a reviewer']];
  $('#kpis').innerHTML = k.map(([l, v, c, sub]) => `<div class="card kpi ${c}"><div class="lbl">${l}</div><div class="val">${v}</div><div class="sub">${sub || '&nbsp;'}</div></div>`).join('');
}
function drawCharts(s) {
  charts.forEach((c) => c.destroy()); charts = [];
  if (typeof Chart === 'undefined') { $$('.chart-box').forEach((b) => b.innerHTML = '<p class="muted">Charts unavailable offline.</p>'); return; }
  const b = s.by_status || {};
  charts.push(new Chart($('#cStatus'), { type: 'doughnut', data: { labels: ['Approved', 'Pending', 'Rejected'], datasets: [{ data: [b.Approved || 0, b.Pending || 0, b.Rejected || 0], backgroundColor: ['#22c55e', '#f59e0b', '#ef4444'], borderWidth: 2, borderColor: '#fff' }] },
    options: { maintainAspectRatio: false, cutout: '62%', plugins: { legend: { position: 'bottom' } } } }));
  const col = { WARN: '#f59e0b', ERROR: '#f97316', CRITICAL: '#ef4444' };
  charts.push(new Chart($('#cRules'), { type: 'bar', data: { labels: s.top_rules.map((r) => r.rule_id), datasets: [{ label: 'Times triggered', data: s.top_rules.map((r) => r.count), backgroundColor: s.top_rules.map((r) => col[r.severity]), borderRadius: 4 }] },
    options: { indexAxis: 'y', maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { afterLabel: (c) => 'Highest severity: ' + s.top_rules[c.dataIndex].severity } } }, scales: { x: { beginAtZero: true, ticks: { precision: 0 } }, y: { ticks: { font: { size: 11 } } } } } }));
}
function drawRows(runs) {
  const tb = $('#rows');
  if (!runs.length) { tb.innerHTML = '<tr><td colspan="7" class="empty">No runs match these filters.</td></tr>'; return; }
  tb.innerHTML = runs.map((r) => `<tr tabindex="0" data-id="${esc(r.id)}" aria-label="Open run ${esc(r.vendor_name)}"><td><div class="vname">${esc(r.vendor_name)}</div><div class="vid">${esc(r.id)}</div></td><td>${esc(r.country || '-')}</td>
    <td>${badge(r.status)}</td><td>${esc(DTYPE[r.decision_type] || r.decision_type || '-')}</td><td><span class="score">${r.risk_score ?? '-'}</span></td><td class="small">${fmtTime(r.started_at)}</td>
    <td>${r.parent_run_id ? `<a href="#/run/${esc(r.parent_run_id)}" data-stop>↳ ${esc(r.parent_run_id)}</a>` : '<span class="muted">-</span>'}</td></tr>`).join('');
  $$('tr[data-id]', tb).forEach((tr) => { const open = () => openDrawer(tr.dataset.id); tr.onclick = (e) => { if (e.target.closest('[data-stop]')) return; open(); }; tr.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } }; });
}
function closeDrawer() { $('#drawerRoot').innerHTML = ''; document.removeEventListener('keydown', escClose); }
const escClose = (e) => { if (e.key === 'Escape') closeDrawer(); };
async function openDrawer(id) {
  const root = $('#drawerRoot');
  root.innerHTML = `<div class="scrim"></div><aside class="drawer" role="dialog" aria-modal="true" aria-label="Run audit trail"><div class="drawer-body"><div class="skeleton"></div><div class="skeleton" style="height:120px"></div></div></aside>`;
  $('.scrim', root).onclick = closeDrawer; document.addEventListener('keydown', escClose);
  try {
    const d = await api('/api/runs/' + id);
    const lab = Object.fromEntries(STAGES);
    $('.drawer', root).innerHTML = `<div class="drawer-head"><div><h2>${esc(d.vendor_name)}</h2><div class="row small" style="margin-top:6px">${badge(d.status)}<span class="chip neutral">${esc(d.decision_type || '')}</span><span class="vid">${esc(d.id)}</span></div></div><button class="btn sm" id="dClose" aria-label="Close">Close ✕</button></div>
      <div class="drawer-body">
        ${d.parent_run_id ? `<div class="banner" style="margin:0">↳ Resubmission of <a href="#/run/${esc(d.parent_run_id)}">${esc(d.parent_run_id)}</a></div>` : ''}
        ${d.children.length ? `<div class="banner" style="margin:0">Resubmitted as ${d.children.map((c) => `<a href="#/run/${esc(c.id)}">${esc(c.id)} (${esc(c.status)})</a>`).join(', ')}</div>` : ''}
        <div class="card card-pad"><div class="row" style="justify-content:space-between;align-items:flex-start"><div><h3>Summary</h3><p style="margin:6px 0 0">${esc(d.summary)}</p></div>${ringSvg(d.risk_score || 0)}</div>
          <p class="muted small" style="margin:8px 0 0">Started ${esc(fmtTime(d.started_at))} · processed in ${fmtDur(d.duration_ms)}</p></div>
        <h2>Audit trail</h2>
        ${d.stages.map((s) => { const sh = s.findings.filter((f) => !['DECISION', 'EMAIL_DRAFTED'].includes(f.rule_id)); return `<div class="card stage-block"><h3><span class="chip ${s.status === 'error' ? 'chip-ERROR' : s.status === 'warn' ? 'chip-WARN' : 'chip-INFO'}">${esc(s.status)}</span>${esc(lab[s.key] || s.key)}</h3>
          ${sh.length ? `<ul class="findings">${sh.map((f, i) => findingLi(f, 0)).join('')}</ul>` : ''}${s.passes.length ? `<ul class="passes">${s.passes.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : ''}</div>`; }).join('')}
        <h2>Emails</h2>${d.emails.map((e) => `<div class="card email"><div class="card-title" style="padding:14px 20px 0;margin:0"><div class="row"><span class="chip neutral">${esc(e.audience)}</span><span class="chip draft">Draft (not sent)</span><span class="chip ${e.source === 'ai' ? 'ai' : 'neutral'}">${e.source === 'ai' ? 'AI-drafted' : 'Template'}</span></div></div>${emailHTML(e)}</div>`).join('') || '<p class="muted">No emails.</p>'}
        <div class="row"><a class="btn primary" href="#/run/${esc(d.id)}">Open run view</a><a class="btn" href="/api/runs/${esc(d.id)}/export" download>Export JSON</a></div></div>`;
    $('#dClose').onclick = closeDrawer; $('#dClose').focus();
  } catch (e) { $('.drawer', root).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; }
}

/* ------------------------------------------------------------ Samples */
async function renderSamples() {
  view.innerHTML = `<div class="page-head"><div><h1>Sample scenarios</h1><p>Nine scenarios (8 + a resubmission) with fixed expected outcomes. Each one runs through the real pipeline.</p></div></div><div class="sample-grid" id="sg"><div class="card card-pad"><div class="skeleton"></div></div></div>`;
  try {
    const list = await loadSamples();
    $('#sg').innerHTML = list.map((s) => `<article class="card sample"><div class="row" style="justify-content:space-between"><span class="no">${esc(s.key.split('_')[0].toUpperCase())}</span><span class="chip neutral">${esc(s.tests)}</span></div>
      <h2>${esc(s.title)}</h2><p>${esc(s.description)}</p><div class="row small">Expected: ${badge(s.expected.status)}<span class="chip neutral">${esc(s.expected.decision_type)}</span></div>
      <div class="row"><button class="btn primary" data-run="${esc(s.key)}">${s.parent_sample ? 'Run this (resubmits sample 3)' : 'Run this'}</button><button class="btn" data-load="${esc(s.key)}">Load in form</button></div></article>`).join('');
    $$('[data-run]').forEach((b) => b.onclick = async () => { b.disabled = true; try { const r = await api('/api/runs', { method: 'POST', body: JSON.stringify({ sample: b.dataset.run }) }); state.lastRun = r.run_id; location.hash = '#/run/' + r.run_id; } catch (e) { toast(e.message, true); b.disabled = false; } });
    $$('[data-load]').forEach((b) => b.onclick = () => { loadSample(b.dataset.load); location.hash = '#/new'; });
  } catch (e) { $('#sg').innerHTML = `<div class="card err-box">Could not load samples: ${esc(e.message)}</div>`; }
}

/* ------------------------------------------------------------ boot */
fetch('/api/meta').then((r) => r.json()).then((m) => { state.llm = m.llm_provider; $('#llmBadge').textContent = m.llm_provider === 'none' ? 'Rules only · AI drafting off' : `Rules decide · AI drafting: ${m.llm_provider}`; }).catch(() => {});
route();
})();
