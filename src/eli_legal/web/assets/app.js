/* ELI Legal: the browser application.
 *
 * Everything shown comes from this server's own API and is put on the page as text, never as
 * markup: documents in a dispute are untrusted, and one that contains a script must stay a
 * string. The session cookie cannot be read from here; what this page holds is the CSRF value
 * the server handed it at sign-in, kept in memory only.
 */
'use strict';
(() => {
  const S = { user: null, csrf: null, sys: null, wf: null, matters: [], matter: null, runs: [], run: null,
    tab: 'home', poll: null, picked: {}, need2fa: false, w: null };
  const root = document.getElementById('app');

  // ── building blocks ────────────────────────────────────────────────────────
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'class') el.className = v;
      else if (k === 'value') el.value = v;
      else if (k === 'checked' || k === 'disabled' || k === 'selected' || k === 'multiple') el[k] = !!v;
      else el.setAttribute(k, v === true ? '' : String(v));
    }
    for (const kid of kids.flat(Infinity)) {
      if (kid === null || kid === undefined || kid === false) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  /** Replace an element's content. Unlike replaceChildren, accepts nested arrays and text. */
  function fill(el, ...kids) {
    el.replaceChildren(...kids.flat(Infinity).filter((k) => k !== null && k !== undefined && k !== false).map((k) => (k instanceof Node ? k : document.createTextNode(String(k)))));
    return el;
  }
  const words = (v) => String(v ?? '').replace(/_/g, ' ');
  // The server's own words for states, checks, holds, roles and scopes (GET /v1/words), so this
  // page says everything exactly as the desktop application and the reports do.
  const say = (code) => (S.w && S.w.states[code]) || words(code).replace(/^./, (c) => c.toUpperCase());
  const toneOf = (code) => (S.w && S.w.tones[code]) || '';
  const tag = (code) => h('span', { class: toneOf(code) || null }, say(code));
  const checkName = (code) => (S.w && S.w.checks[code] ? S.w.checks[code].name : words(code));
  const holdWhy = (code) => (S.w && S.w.holds[code] ? S.w.holds[code].headline : words(code));
  const roleName = (code) => (S.w && S.w.roles[code] ? S.w.roles[code].label : words(code));
  const scopeName = (code) => (S.w && S.w.scopes[code] ? S.w.scopes[code].label : words(code));
  const when = (v) => (v ? String(v).slice(0, 19).replace('T', ' ') : '');
  const btn = (text, onclick, kind) => h('button', { class: kind || null, type: 'button', onclick }, text);
  const card = (title, ...kids) => h('section', { class: 'card' }, title ? h('h2', null, title) : null, ...kids);
  const facts = (pairs) => h('dl', null, pairs.filter((p) => p).map(([k, v]) => [h('dt', null, k), h('dd', null, v)]));
  const list = (items) => (items && items.length ? h('ul', null, items.map((i) => h('li', null, i))) : h('p', { class: 'muted' }, 'None.'));

  function table(cols, rows, opts = {}) {
    if (!rows.length) return h('p', { class: 'muted' }, opts.empty || 'Nothing here yet.');
    const body = rows.map((r) => {
      const tr = h('tr', { class: (opts.onRow ? 'pick ' : '') + (opts.on && opts.on(r) ? 'on' : ''), tabindex: opts.onRow ? 0 : null },
        cols.map(([, get, cls]) => h('td', { class: cls || null }, typeof get === 'function' ? get(r) : String(r[get] ?? ''))));
      if (opts.onRow) {
        tr.addEventListener('click', () => opts.onRow(r));
        tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') opts.onRow(r); });
      }
      return tr;
    });
    return h('div', { class: 'scroll' }, h('table', null, h('thead', null, h('tr', null, cols.map(([t]) => h('th', { scope: 'col', title: explain(t) }, t)))), h('tbody', null, body)));
  }

  function note(message, kind = 'bad') {
    let box = document.getElementById('toast');
    if (!box) { box = h('div', { id: 'toast', role: 'status' }); document.body.append(box); }
    const item = h('div', { class: `banner ${kind} card` }, message);
    box.append(item);
    setTimeout(() => item.remove(), kind === 'bad' ? 9000 : 4000);
  }

  /** A form in a dialog. Resolves to the values, or null if cancelled. */
  function ask(title, fields, submit = 'OK', intro = '') {
    return new Promise((resolve) => {
      const inputs = {};
      const form = h('form', { method: 'dialog' }, h('h2', null, title), intro ? h('p', { class: 'muted' }, intro) : null);
      for (const f of fields) {
        let input;
        if (f.type === 'select') {
          input = h('select', { multiple: f.multiple }, (f.options || []).map((o) => {
            const [value, text] = Array.isArray(o) ? o : [o, words(o)];
            return h('option', { value, selected: f.multiple ? (f.value || []).includes(value) : value === f.value }, text);
          }));
          if (f.multiple) input.size = Math.min(8, Math.max(3, (f.options || []).length));
        } else if (f.type === 'textarea') input = h('textarea', { value: f.value || '', placeholder: f.hint });
        else if (f.type === 'checkbox') input = h('input', { type: 'checkbox', checked: f.value });
        else input = h('input', { type: f.type || 'text', value: f.value || '', placeholder: f.hint, autocomplete: f.type === 'password' ? 'off' : null });
        if (f.required) input.required = true;
        inputs[f.name] = input;
        form.append(...(f.type === 'checkbox' ? [h('label', { class: 'check' }, input, f.label)] : [h('label', null, f.label), input]));
      }
      const dialog = h('dialog', null, form);
      const done = (value) => { dialog.close(); dialog.remove(); resolve(value); };
      form.append(h('div', { class: 'row' }, h('span', { class: 'spacer' }), btn('Cancel', () => done(null)), h('button', { class: 'go', type: 'submit' }, submit)));
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        const out = {};
        for (const f of fields) {
          const i = inputs[f.name];
          out[f.name] = f.type === 'checkbox' ? i.checked : f.multiple ? [...i.selectedOptions].map((o) => o.value) : i.value;
        }
        done(out);
      });
      dialog.addEventListener('cancel', (e) => { e.preventDefault(); done(null); });
      document.body.append(dialog);
      dialog.showModal();
    });
  }
  const reason = (title, intro) => ask(title, [{ name: 'reason', label: 'Reasons (recorded under your name)', type: 'textarea', required: true }], 'Record', intro);
  const lines = (text) => String(text || '').split('\n').map((l) => l.trim()).filter(Boolean);

  // ── talking to the server ──────────────────────────────────────────────────
  class Cancelled extends Error {}
  const b64 = (text) => btoa(String.fromCharCode(...new TextEncoder().encode(text)));

  async function api(method, path, body, opts = {}) {
    const headers = {};
    let payload;
    if (opts.raw) { payload = body; headers['Content-Type'] = 'application/octet-stream'; }
    else if (body !== undefined) { payload = JSON.stringify(body); headers['Content-Type'] = 'application/json'; }
    if (S.csrf && method !== 'GET') headers['X-ELI-CSRF'] = S.csrf;
    if (opts.phrase) headers['X-ELI-Passphrase-B64'] = b64(opts.phrase);
    const res = await fetch(path, { method, headers, body: payload, credentials: 'same-origin', cache: 'no-store', redirect: 'error' });
    if (res.status === 204) return null;
    if (res.ok) return opts.blob ? res.blob() : (res.headers.get('content-type') || '').includes('json') ? res.json() : res.text();
    let err = { error: 'Error', detail: res.statusText };
    try { err = await res.json(); } catch { /* not JSON */ }
    if (res.status === 401 && err.error === 'StepUpRequired' && !opts.phrase) {
      const got = await ask('Confirm it is you', [{ name: 'phrase', label: 'Your passphrase', type: 'password', required: true }], 'Confirm',
        'This is a decision recorded in your name, so it needs your passphrase again.');
      if (!got) throw new Cancelled();
      return api(method, path, body, { ...opts, phrase: got.phrase });
    }
    if (res.status === 401 && opts.phrase) throw new Error('That passphrase is not correct. Nothing was recorded.');
    if (res.status === 401 && !opts.quiet) { S.user = null; S.csrf = null; render(); }
    throw Object.assign(new Error(err.detail || err.error), { code: err.error, status: res.status });
  }
  /** Run an action; show a refusal in the server's own words. */
  async function attempt(work, done) {
    try {
      const out = await work();
      if (done) note(done, 'good');
      return out === undefined || out === null ? true : out;
    } catch (e) {
      if (!(e instanceof Cancelled) && S.user) note(e.message);
      return false;
    }
  }
  async function download(method, path, name) {
    const blob = await api(method, path, undefined, { blob: true });
    const url = URL.createObjectURL(blob instanceof Blob ? blob : new Blob([typeof blob === 'string' ? blob : JSON.stringify(blob, null, 2)]));
    const a = h('a', { href: url, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }
  const M = () => `/v1/matters/${encodeURIComponent(S.matter.matter_id)}`;
  const R = () => `${M()}/runs/${encodeURIComponent(S.run.run_id)}`;

  // ── session ────────────────────────────────────────────────────────────────
  async function start() {
    try {
      const s = await api('GET', '/v1/auth/session', undefined, { quiet: true });
      await signedIn(s);
    } catch { render(); }
  }
  async function signedIn(s) {
    S.user = s.user; S.csrf = s.csrf;
    S.need2fa = s.second_factor_required && !s.user.second_factor;
    if (!S.need2fa) {
      [S.sys, S.wf, S.matters, S.w] = await Promise.all([api('GET', '/v1/system'), api('GET', '/v1/workflow'), api('GET', '/v1/matters'), api('GET', '/v1/words')]);
      if (S.matters.length) await openMatter(S.matters[S.matters.length - 1].matter_id, false);
    }
    render();
  }
  async function openMatter(id, draw = true) {
    S.matter = await api('GET', `/v1/matters/${encodeURIComponent(id)}`);
    S.runs = await api('GET', `${M()}/runs`);
    S.run = null; S.picked = {};
    if (S.runs.length) await openRun(S.runs[S.runs.length - 1].run_id, false);
    if (draw) render();
  }
  async function openRun(id, draw = true) {
    S.run = await api('GET', `${M()}/runs/${encodeURIComponent(id)}`);
    const listed = S.runs.find((r) => r.run_id === id);
    if (listed) listed.status = S.run.status;
    if (draw) show();
  }
  async function signOut() {
    try { await api('POST', '/v1/auth/logout', undefined, { quiet: true }); } catch { /* already gone */ }
    Object.assign(S, { user: null, csrf: null, matter: null, run: null, matters: [], runs: [] });
    render();
  }

  function signInView() {
    const user = h('input', { autocomplete: 'username', required: true });
    const phrase = h('input', { type: 'password', autocomplete: 'current-password', required: true });
    const code = h('input', { inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: 8, placeholder: 'only if you have set up an authenticator' });
    const problem = h('div');
    const form = h('form', null, h('label', null, 'User'), user, h('label', null, 'Passphrase'), phrase, h('label', null, 'Code'), code,
      h('div', { class: 'row' }, h('span', { class: 'spacer' }), h('button', { class: 'go', type: 'submit' }, 'Sign in')));
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      fill(problem);
      try {
        await signedIn(await api('POST', '/v1/auth/login', { user_id: user.value.trim(), passphrase: phrase.value, code: code.value.trim() || null }, { quiet: true }));
      } catch (err) {
        phrase.value = ''; code.value = '';
        problem.append(h('div', { class: 'banner bad' }, err.code === 'SecondFactorRequired' ? 'Enter the code from your authenticator app as well.'
          : err.code === 'AccountLocked' || err.status === 429 ? err.message : 'Unknown user, wrong passphrase or wrong code.'));
        (err.code === 'SecondFactorRequired' ? code : phrase).focus();
      }
    });
    return h('div', { class: 'signin' }, h('div', { class: 'card' }, h('h1', null, 'ELI Legal'),
      h('p', { class: 'muted' }, 'Governed legal case preparation. Decision support only.'), problem, form,
      h('p', { class: 'muted' }, 'Everything you do is recorded under your name. A decision will ask for your passphrase again.')));
  }

  async function setUpSecondFactor() {
    const started = await attempt(() => api('POST', '/v1/auth/second-factor/begin'));
    if (!started || started === true) return false;
    const got = await ask('Set up your authenticator', [{ name: 'code', label: 'The six-digit code your app now shows', required: true }], 'Confirm',
      `Add this key to an authenticator app, then enter the code it shows.  Key: ${started.secret}`);
    if (!got) return false;
    const ok = await attempt(() => api('POST', '/v1/auth/second-factor/confirm', { code: got.code.trim() }), 'Second factor enabled. You will be asked for a code at every sign-in.');
    if (ok) { S.user.second_factor = true; S.need2fa = false; }
    return ok;
  }
  function enrolView() {
    return h('div', { class: 'signin' }, card('One more step',
      h('p', null, 'This server can be reached from other machines, so every account needs a second factor: a code from an authenticator app on your phone.'),
      h('div', { class: 'row' }, btn('Set it up now', async () => { if (await setUpSecondFactor()) await start(); }, 'go'), btn('Sign out', signOut))));
  }

  // ── frame ──────────────────────────────────────────────────────────────────
  // The pages, in plain words, as the desktop application names them (GET /v1/words, how_to.pages).
  const TAB_KEYS = ['start', 'help', 'home', 'matter', 'evidence', 'chat', 'dag', 'agents', 'findings', 'review', 'audit', 'governance', 'sources', 'laws', 'settings'];
  const pageOf = (id) => ((S.w && S.w.how_to && S.w.how_to.pages) || {})[id === 'dag' ? 'workflow' : id] || { name: id, about: '' };
  const TABS = () => TAB_KEYS.map((id) => [id, pageOf(id).name, pageOf(id).about]);
  // What a word means, for the pointer to rest on: column headings, and anything given a title.
  const explain = (word) => {
    const terms = (S.w && S.w.glossary) || {};
    const want = String(word || '').trim().toLowerCase();
    const key = Object.keys(terms).find((k) => k.toLowerCase() === want || k.toLowerCase() === want.replace(/s$/, ''));
    return key ? terms[key] : null;
  };
  const VIEWS = {};

  function render() {
    clearInterval(S.poll); S.poll = null;
    if (!S.user) { fill(root, signInView()); return; }
    if (S.need2fa) { fill(root, enrolView()); return; }
    const pick = h('select', { 'aria-label': 'Matter', onchange: (e) => attempt(() => openMatter(e.target.value)) },
      S.matters.length ? S.matters.map((m) => h('option', { value: m.matter_id, selected: S.matter && m.matter_id === S.matter.matter_id }, `${m.name}  ·  ${say(m.status).toLowerCase()}`))
        : h('option', { value: '' }, 'No matter yet'));
    const profile = S.matter ? S.sys.profiles.find((p) => p.profile === S.matter.profile) : null;
    const model = S.sys.model.active_model_id;
    fill(root, 
      h('header', { class: 'top' }, h('span', { class: 'brand' }, 'ELI Legal'), h('span', { class: 'muted' }, 'Case'), pick,
        h('span', { class: 'muted' }, profile ? profile.label : ''), h('span', { class: 'spacer' }),
        h('span', { class: `chip ${S.sys.audit.ok ? 'good' : 'bad'}` }, S.sys.audit.ok ? `Audit verified · ${S.sys.audit.events} events` : 'AUDIT CHAIN INVALID'),
        S.sys.network && S.sys.network.hard_offline
          ? h('span', { class: `chip ${/kernel|Firewall/.test(S.sys.network.enforced_by) ? 'good' : 'warn'}`, title: S.sys.network.detail }, /kernel|Firewall/.test(S.sys.network.enforced_by) ? 'Hard offline (kernel-enforced)' : 'Hard offline (this program only)')
          : h('span', { class: 'chip good' }, `Network ${S.sys.network_default} by default`),
        h('span', { class: `chip ${model && model !== 'none' ? 'good' : ''}` }, model && model !== 'none' ? `Model ${model}` : 'No model'),
        h('span', { class: 'chip human' }, `${S.user.display_name} · ${S.user.roles.map(roleName).join(', ')}`), btn('Sign out', signOut)),
      h('nav', { class: 'tabs', role: 'tablist' }, TABS().map(([id, text, about]) => h('button', { class: 'tab', role: 'tab', id: `tab-${id}`, title: about || null, 'aria-selected': String(S.tab === id), onclick: () => { S.tab = id; render(); } }, text))),
      h('main', { id: 'view', role: 'tabpanel' }),
      h('footer', { class: 'note' }, 'Decision support only. Nothing here may be relied on until a named reviewer has approved it.'));
    show();
  }
  async function show() {
    clearInterval(S.poll); S.poll = null;
    const view = document.getElementById('view');
    if (!view) return;
    const tab = S.tab;
    try {
      const node = await VIEWS[tab]();
      if (S.tab === tab && document.getElementById('view')) fill(document.getElementById('view'), node);
    } catch (e) {
      if (S.user) fill(view, h('div', { class: 'banner bad' }, e.message));
    }
  }
  const needMatter = () => (S.matter ? null : card('No matter is open', h('p', { class: 'muted' }, 'Open one in the Matter tab first.')));
  const needRun = () => needMatter() || (S.run ? null : card('No run yet', h('p', { class: 'muted' }, 'Start one in the DAG tab once the documents are in.')));
  const runPicker = () => h('select', { 'aria-label': 'Run', onchange: (e) => attempt(() => openRun(e.target.value)) },
    S.runs.map((r) => h('option', { value: r.run_id, selected: S.run && r.run_id === S.run.run_id }, `${when(r.created_at)}  ·  ${say(r.status)}  ·  ${r.run_id.slice(-8)}`)));

  // ── Home ───────────────────────────────────────────────────────────────────
  const PAGE_TAB = { matter: 'matter', evidence: 'evidence', workflow: 'dag', review: 'review', findings: 'findings', governance: 'governance', settings: 'settings', laws: 'laws' };
  const PAGE_NAME = new Proxy({}, { get: (_t, page) => pageOf(page).name });
  const goTo = (page) => { S.tab = PAGE_TAB[page] || page; render(); };
  const MARK = { ok: '✓', attention: '!', failed: '✗', could_not_run: '?' };
  const checkTone = (state) => (state === 'ok' ? 'good' : state === 'attention' ? 'warn' : 'bad');
  // ── Start a new case: the eleven parts, and every question in each ───────────
  const STAGE_OF = { documents: 'documents', analysis: 'analysis', holds: 'holds', review: 'review', release: 'release' };
  VIEWS.start = async () => {
    const guide = (S.w && S.w.how_to && S.w.how_to.new_case) || { intro: '', parts: [] };
    const m = S.matter;
    const done = new Set();
    if (m) {
      ['for', 'open'].forEach((k) => done.add(k));
      if (m.name && m.purpose) done.add('case');
      if ((m.parties || []).length && (m.stated_issues || []).length) done.add('parties');
      if ((m.reviewer_user_ids || []).length) done.add('team');
      if ((m.approved_source_ids || []).length) done.add('law');
      const stages = await api('GET', `${M()}/guide`).then((g) => g.stages).catch(() => []);
      stages.forEach((s) => { const part = Object.keys(STAGE_OF).find((k) => STAGE_OF[k] === s.key); if (part && s.state === 'done') done.add(part); });
    }
    if (S.part === undefined) S.part = 0;
    const part = guide.parts[S.part] || guide.parts[0];
    const pick = (i) => { S.part = i; render(); };
    return h('div', null,
      card('Start a new case: a guided walkthrough', h('p', null, guide.intro),
        h('div', { class: 'row' },
          h('p', null, m ? h('b', null, `Your open case: ${m.name} — ${done.size} of ${guide.parts.length} parts done.`) : h('b', null, 'No case is open.'),
            m ? ' A tick marks each; choose any part to see what it needs.' : ' Start one, or read each part first.'),
          btn('Start a new case', () => goTo('matter'), 'go'))),
      card('How a case is built — the eleven parts, in order',
        h('div', { class: 'partmap' }, guide.parts.map((p, i) => h('button', {
          type: 'button', class: `part${done.has(p.key) ? ' done' : ''}${i === S.part ? ' chosen' : ''}`, title: p.what, onclick: () => pick(i),
        }, h('b', null, `${done.has(p.key) ? '✓ ' : ''}${i + 1}. ${p.title}`), h('span', null, p.summary))))),
      part ? card(`${S.part + 1}. ${part.title}${done.has(part.key) ? ' — done for your open case' : ''}`,
        h('p', null, h('b', null, 'Who: '), part.who), h('p', null, part.what),
        part.questions.length ? table([['You are asked', 0], ['What it means', 1, 'wide'], ['For example', 2]], part.questions) : null,
        part.tips.length ? h('div', null, h('b', null, 'Good to know'), h('ul', null, part.tips.map((t) => h('li', null, t)))) : null,
        h('div', { class: 'row' },
          btn('◀ Previous part', () => pick(Math.max(0, S.part - 1))), btn('Next part ▶', () => pick(Math.min(guide.parts.length - 1, S.part + 1))),
          btn(part.button, () => goTo(part.page === 'new_matter' ? 'matter' : part.page), 'go'))) : null);
  };

  // ── How to use ─────────────────────────────────────────────────────────────
  VIEWS.help = async () => {
    const guide = (S.w && S.w.how_to) || { intro: '', reading: '', steps: [] };
    const words = h('div', { class: 'glossary' });
    const showWords = (wanted) => {
      const terms = Object.entries((S.w && S.w.glossary) || {}).sort(([a], [b]) => a.localeCompare(b));
      const want = (wanted || '').trim().toLowerCase();
      const shown = terms.filter(([t, m]) => !want || t.toLowerCase().includes(want) || m.toLowerCase().includes(want));
      fill(words, shown.length ? h('dl', null, ...shown.flatMap(([t, m]) => [h('dt', null, t), h('dd', null, m)])) : h('p', { class: 'muted' }, 'No word matches. Try fewer letters.'));
    };
    showWords('');
    return h('div', null,
      card('How to use ELI Legal', h('p', null, guide.intro), h('p', { class: 'muted' }, guide.reading)),
      ...guide.steps.map((step, i) => card(`${i + 1}. ${step.what}`,
        h('p', null, h('b', null, 'Who: '), step.who), h('p', null, step.how),
        h('div', { class: 'row' }, btn(step.button, () => goTo(step.page === 'new_matter' ? 'matter' : step.page), 'go')))),
      card('What the words mean',
        h('input', { type: 'search', placeholder: 'Look up a word: matter, authority, held, provider …', 'aria-label': 'Look up a word', oninput: (e) => showWords(e.target.value) }),
        words));
  };

  VIEWS.home = async () => {
    const home = await api('GET', '/v1/home');
    const guide = S.matter ? await api('GET', `${M()}/guide`) : null;
    const stage = (s, i) => h('div', { class: `stage ${s.state}`, title: s.detail }, h('b', null, `${i + 1}. ${s.title}`), h('div', null, s.state === 'current' ? 'Now' : say(s.state)));
    const step = (s, first) => h('div', { class: 'step' },
      h('div', null, h('b', null, s.title), h('div', { class: 'muted' }, s.why), s.can_do ? null : h('div', { class: 'warn' }, `You cannot do this. ${s.who}`)),
      btn(`Go to ${PAGE_NAME[s.page] || words(s.page)} →`, () => goTo(s.page), first && s.can_do ? 'go' : null));
    const matterCard = guide
      ? card(guide.matter_name, h('p', null, guide.headline),
        h('p', { class: 'muted' }, h('b', null, `Your role on this matter: ${guide.role}. `), `${guide.role_summary} ${guide.reads}`),
        h('div', { class: 'stages' }, guide.stages.map(stage)), h('h3', null, 'What to do next'),
        guide.steps.length ? guide.steps.map((s, i) => step(s, i === 0)) : h('p', { class: 'muted' }, 'Nothing is waiting on this matter.'))
      : card('No matter is open', h('p', { class: 'muted' }, 'Open a matter to begin: it asks who it is for, the legal system, the parties and issues, the team and their roles, the sources and the laws.'),
        h('div', { class: 'row' }, btn('Open a matter…', () => goTo('matter'), 'go')));
    const c = home.checks;
    const open = async (w) => { if (!S.matter || S.matter.matter_id !== w.matter_id) await openMatter(w.matter_id, false); goTo(w.page); };
    return h('div', { class: 'cols' }, matterCard, h('div', null,
      card('Waiting for you on your matters', home.work.length
        ? table([['Matter', 'matter_name'], ['What', 'text', 'wide']], home.work, { onRow: (w) => attempt(() => open(w)) })
        : h('p', { class: 'muted' }, 'Nothing is waiting for you.')),
      card('Routine checks', c
        ? [h('p', { class: checkTone(c.state) }, h('b', null, c.headline)), h('p', { class: 'muted' }, `Last run ${when(c.finished_at)} UTC by ${c.by}.`),
          h('ul', null, c.results.map((r) => h('li', { title: [r.what_to_do, ...r.items.slice(0, 8).map((i) => i.text)].join('\n') },
            h('span', { class: checkTone(r.state) }, MARK[r.state] || '?'), ` ${r.title}: ${r.summary}`)))]
        : h('p', { class: 'muted' }, 'The routine checks have not run yet.'),
      h('div', { class: 'row' }, btn('Details…', () => goTo('governance')))),
      card("The organisation's compliance", h('p', null, home.compliance), h('div', { class: 'row' }, btn('Open compliance…', () => goTo('governance'))))));
  };

  // ── Matter ─────────────────────────────────────────────────────────────────
  VIEWS.matter = async () => {
    const users = await api('GET', '/v1/users');
    const sources = await api('GET', '/v1/sources');
    const m = S.matter;
    const OVERSIGHT = ['legal_admin', 'governance_officer', 'auditor', 'reviewer', 'read_only'];
    const create = async () => {
      // Four short steps instead of one long form; nothing is created until the last.
      const one = await ask('Open a matter — 1 of 4: who it is for', [
        { name: 'profile', label: 'Who the work is for (fixes who may work on it and what the output may say; it cannot be changed later)', type: 'select', options: S.sys.profiles.map((p) => [p.profile, p.label]) },
        { name: 'name', label: 'Name', required: true }, { name: 'purpose', label: 'What the work product is for', type: 'textarea', required: true },
        { name: 'jurisdiction', label: 'Legal system', type: 'select', options: S.sys.jurisdictions.map((j) => [j.code, `${j.code} · ${j.name}${j.validated ? '' : ' (unvalidated pack)'}`]) },
        { name: 'forum', label: 'Court, tribunal or forum' }, { name: 'procedural_rules', label: 'Procedural rules' },
        { name: 'relevant_date', label: 'Assess the law as it stood on (usually when the events happened)', type: 'date' }], 'Next');
      if (!one) return;
      const profile = S.sys.profiles.find((p) => p.profile === one.profile);
      const rep = one.profile === 'party_representative';
      const two = await ask('Open a matter — 2 of 4: parties and issues', [
        { name: 'parties', label: 'Parties, one per line as  Name: role', type: 'textarea', hint: 'Harbour Freight Ltd: claimant\nNorthwind Logistics Ltd: respondent', required: true },
        { name: 'issues', label: 'Issues, one per line, each framed as a question', type: 'textarea', hint: 'Whether time for delivery was of the essence' },
        rep ? { name: 'represented_party', label: 'The party you act for (exactly as named above)', required: true } : null].filter(Boolean), 'Next');
      if (!two) return;
      const parties = lines(two.parties).map((l) => { const i = l.lastIndexOf(':'); return i > 0 ? { name: l.slice(0, i).trim(), role: l.slice(i + 1).trim() || 'party' } : { name: l, role: 'party' }; });
      const fits = (u) => u.active && u.user_id !== S.user.user_id && u.roles.some((r) => profile.roles.includes(r) || OVERSIGHT.includes(r));
      const people = users.filter(fits);
      const three = await ask('Open a matter — 3 of 4: the team', [
        { name: 'team', label: 'Who else works on it (you lead it)', type: 'select', multiple: true, options: people.map((u) => [u.user_id, `${u.display_name} · ${u.roles.map(roleName).join(', ')}`]) },
        { name: 'me_review', label: 'I review and approve the report myself', type: 'checkbox', value: S.user.roles.some((r) => profile.reviewer_roles.includes(r)) }], 'Next',
        'Next you choose each person’s role on this matter.');
      if (!three) return;
      const roles = Object.entries(S.w.matter_roles).filter(([code]) => code !== 'lead');
      let team = [], reviewers = three.me_review ? [S.user.user_id] : [];
      if (three.team.length) {
        const fields = three.team.flatMap((uid) => {
          const u = people.find((x) => x.user_id === uid);
          const canReview = u.roles.some((r) => profile.reviewer_roles.includes(r));
          return [
            { name: `role:${uid}`, label: `${u.display_name}: role on this matter`, type: 'select', options: roles.map(([code, r]) => [code, `${r.label} — ${r.summary}`]), value: canReview ? 'decision_maker' : 'case_worker' },
            { name: `party:${uid}`, label: `${u.display_name}: acts for`, type: 'select', options: [['', '(nobody in particular)'], ...parties.map((p) => [p.name, p.name])] },
            canReview ? { name: `review:${uid}`, label: `${u.display_name} reviews and approves`, type: 'checkbox' } : null];
        }).filter(Boolean);
        const roleAnswers = await ask('The team: their roles on this matter', fields, 'Next');
        if (!roleAnswers) return;
        team = three.team.map((uid) => ({ user_id: uid, matter_role: roleAnswers[`role:${uid}`], party: roleAnswers[`party:${uid}`] || null }));
        reviewers = reviewers.concat(three.team.filter((uid) => roleAnswers[`review:${uid}`]));
      }
      const packs = (await api('GET', '/v1/frameworks')).filter((f) => f.usable);
      const covering = sources.filter((x) => x.approved && (x.jurisdictions.includes(one.jurisdiction) || x.jurisdictions.includes('*')));
      const four = await ask('Open a matter — 4 of 4: legal sources, law and standards', [
        { name: 'sources', label: 'Approved legal sources it may use', type: 'select', multiple: true, options: sources.filter((x) => x.approved).map((x) => [x.source_id, `${x.name} · ${x.jurisdictions.join(', ')}`]), value: covering.map((x) => x.source_id) },
        { name: 'recommended', label: 'Apply the law and standards packages recommended for this kind of matter and legal system', type: 'checkbox', value: true },
        { name: 'frameworks', label: 'Also apply (change them later in Laws & Standards)', type: 'select', multiple: true, options: packs.map((f) => [f.id, `${f.short_title} · ${f.scope}`]) }], 'Open the matter',
        reviewers.length ? '' : 'No reviewer is named yet: the analysis will not start until someone is.');
      if (!four) return;
      const made = await attempt(() => api('POST', '/v1/matters', {
        name: one.name, purpose: one.purpose, profile: one.profile, jurisdiction: one.jurisdiction, forum: one.forum, procedural_rules: one.procedural_rules,
        relevant_date: one.relevant_date || null, stated_issues: lines(two.issues), parties, represented_party: rep ? two.represented_party : null,
        frameworks: four.frameworks, recommended_frameworks: four.recommended, team, reviewers, sources: four.sources }), 'Matter opened.');
      if (made && made !== true) { S.matters = await api('GET', '/v1/matters'); await openMatter(made.matter_id); }
    };
    const left = card('Matters', table([['Name', 'name'], ['For', (r) => words(r.profile)], ['Law', 'jurisdiction'], ['State', (r) => tag(r.status)]], S.matters,
      { onRow: (r) => attempt(() => openMatter(r.matter_id)), on: (r) => m && r.matter_id === m.matter_id, empty: 'You have no matters yet.' }),
      h('div', { class: 'row' }, btn('Open a matter…', create, 'go')));
    if (!m) return h('div', { class: 'cols' }, left, card('Start here', h('p', { class: 'muted' }, 'A matter fixes who the work is for, which legal system applies, who may see it and who must approve anything before it is relied on.')));
    const profile = S.sys.profiles.find((p) => p.profile === m.profile);
    const name = (id) => { const u = users.find((x) => x.user_id === id); return u ? `${u.display_name} (${id})` : id; };
    const members = await api('GET', `${M()}/members`);
    const roleChoices = Object.entries(S.w.matter_roles).filter(([code]) => code !== 'lead').map(([code, r]) => [code, `${r.label} — ${r.summary}`]);
    const again = () => openMatter(m.matter_id);
    const choose = async (title, label, options, current, path, intro) => {
      const v = await ask(title, [{ name: 'ids', label, type: 'select', multiple: true, options, value: current }], 'Set', intro);
      if (v && await attempt(() => api('PUT', `${M()}/${path}`, { ids: v.ids }), 'Recorded.')) again();
    };
    const right = card(m.name, facts([['State', say(m.status)], ['For', profile ? profile.label : words(m.profile)], ['Legal system', m.jurisdiction], ['Forum', m.forum || '—'],
      ['Rules', m.procedural_rules || '—'], ['Relevant date', m.relevant_date || 'not set'], ['Purpose', m.purpose]]),
      h('h3', null, 'Parties'), list(m.parties.map((p) => `${p.name} — ${p.role}`)),
      h('h3', null, 'Issues stated at intake'), list(m.stated_issues),
      h('h3', null, 'The team'),
      table([['Person', (x) => `${x.name} (${x.user_id})`], ['Role on this matter', (x) => (S.w.matter_roles[x.matter_role] || {}).label || words(x.matter_role)],
        ['Acts for', (x) => x.party || '—'], ['Reads', (x) => (x.reads.length === 4 ? 'Everything' : x.reads.map(scopeName).join(', ') || 'Nothing (withheld)')],
        ['Reviews', (x) => (x.reviewer ? 'yes' : '')]], members),
      h('div', { class: 'row' }, btn('Give access…', async () => {
        const v = await ask('Give access', [{ name: 'user', label: 'Person', type: 'select', options: users.filter((u) => u.active && !m.authorised_user_ids.includes(u.user_id)).map((u) => [u.user_id, `${u.display_name} · ${u.roles.map(roleName).join(', ')}`]) },
          { name: 'matter_role', label: 'Their role on this matter', type: 'select', options: roleChoices, value: 'case_worker' },
          { name: 'party', label: 'Acts for', type: 'select', options: [['', '(nobody in particular)'], ...m.parties.map((p) => [p.name, p.name])] }], 'Give access',
          'Only someone whose account fits this kind of matter can be added. Their role on the matter can only narrow what their account allows.');
        if (v && v.user && await attempt(() => api('POST', `${M()}/members/${encodeURIComponent(v.user)}`, { matter_role: v.matter_role, party: v.party || null }), 'Access given.')) again();
      }), btn('Change a role…', async () => {
        const others = members.filter((x) => !x.owner);
        const v = await ask('Change a role on this matter', [{ name: 'user', label: 'Person', type: 'select', options: others.map((x) => [x.user_id, `${x.name} (${x.user_id})`]) },
          { name: 'matter_role', label: 'Role on this matter', type: 'select', options: roleChoices }], 'Change', 'The person who opened the matter always leads it.');
        if (v && v.user && await attempt(() => api('PATCH', `${M()}/members/${encodeURIComponent(v.user)}`, { matter_role: v.matter_role }), 'Role changed.')) again();
      }), btn('Remove access…', async () => {
        const v = await ask('Remove access', [{ name: 'user', label: 'Person', type: 'select', options: m.authorised_user_ids.map((u) => [u, name(u)]) }], 'Remove');
        if (v && v.user && await attempt(() => api('DELETE', `${M()}/members/${encodeURIComponent(v.user)}`), 'Access removed.')) again();
      })),
      h('h3', null, 'Named reviewers'), list(m.reviewer_user_ids.map(name)),
      h('div', { class: 'row' }, btn('Set reviewers…', () => choose('Named reviewers', 'Who must approve before anything is relied on', m.authorised_user_ids.map((u) => [u, name(u)]), m.reviewer_user_ids, 'reviewers'))),
      h('h3', null, 'Approved legal sources'), list(m.approved_source_ids),
      h('div', { class: 'row' }, btn('Set sources…', () => choose('Legal sources for this matter', 'Approved sources', sources.filter((s) => s.approved).map((s) => [s.source_id, s.name]), m.approved_source_ids, 'sources', 'Only sources that have been approved can be used.')),
        h('span', { class: 'spacer' }), btn('Close matter…', async () => {
          const v = await ask('Close this matter', [{ name: 'reason', label: 'Reasons', type: 'textarea', required: true }, { name: 'purge', label: 'Also delete the documents and extracted text (the audit trail is kept)', type: 'checkbox' }], 'Close matter');
          if (v && await attempt(() => api('POST', `${M()}/close`, { reason: v.reason, purge_content: v.purge }), 'Matter closed.')) { S.matters = await api('GET', '/v1/matters'); again(); }
        }, 'danger')));
    return h('div', { class: 'cols' }, left, right);
  };

  // ── Evidence ───────────────────────────────────────────────────────────────
  VIEWS.evidence = async () => {
    const miss = needMatter(); if (miss) return miss;
    const docs = await api('GET', `${M()}/documents`);
    const files = h('input', { type: 'file', multiple: true, 'aria-label': 'Files' });
    const party = h('select', { 'aria-label': 'Filed by' }, h('option', { value: '' }, 'Filed by: not a party'), S.matter.parties.map((p) => h('option', { value: p.party_id }, `Filed by: ${p.name}`)));
    const kind = h('select', { 'aria-label': 'Kind' }, h('option', { value: '' }, 'Kind: work it out'), S.sys.document_types.map((t) => h('option', { value: t }, words(t))));
    const scope = h('select', { 'aria-label': 'Who may see it' }, S.sys.access_scopes.map((s) => h('option', { value: s, title: S.w && S.w.scopes[s] ? S.w.scopes[s].meaning : '' }, `Who may see it: ${scopeName(s)}`)));
    const custodian = h('input', { placeholder: 'Custodian (who held it)' });
    const upload = async () => {
      if (!files.files.length) { note('Choose at least one file.'); return; }
      for (const file of files.files) {
        const q = new URLSearchParams({ filename: file.name, scope: scope.value, custodian: custodian.value });
        if (party.value) q.set('party_id', party.value);
        if (kind.value) q.set('doc_type', kind.value);
        const done = await attempt(() => api('POST', `${M()}/documents?${q}`, file, { raw: true }));
        if (done && done !== true) note(`${file.name}: ${words(done.status)}${done.error ? ' — ' + done.error : ''}`, done.status === 'processed' ? 'good' : 'bad');
      }
      show();
    };
    const partyName = (id) => (S.matter.parties.find((p) => p.party_id === id) || {}).name || '';
    const pane = h('div', null, h('p', { class: 'muted' }, 'Select a document to read it as the located passages every finding points back to.'));
    const open = async (d) => {
      S.picked.doc = d.document_id;
      const parts = d.status === 'processed' || d.status === 'waived' ? await api('GET', `${M()}/documents/${encodeURIComponent(d.document_id)}/passages`) : [];
      fill(pane, h('h2', null, d.filename), facts([['Kind', words(d.doc_type)], ['State', words(d.status)], ['SHA-256', h('span', { class: 'mono' }, d.sha256)],
        ['Filed', `${when(d.ingested_at)} by ${d.ingested_by}`], d.error ? ['Not read', h('span', { class: 'bad' }, d.error)] : null,
        d.injection_flags.length ? ['Flagged', h('span', { class: 'warn' }, `text addressed to a model (${d.injection_flags.map(words).join(', ')}). It is treated as evidence, never as an instruction.`)] : null]),
        h('h3', null, 'Passages'), parts.length ? parts.map((p) => [h('div', { class: 'muted mono' }, p.locator), h('blockquote', null, p.text)]) : h('p', { class: 'muted' }, 'No readable text.'));
    };
    return h('div', { class: 'cols' },
      h('div', null, card('Take documents in', h('div', { class: 'row' }, files), h('div', { class: 'row' }, party, kind, scope), h('div', { class: 'row' }, custodian, btn('File them', upload, 'go')),
        h('p', { class: 'muted' }, 'Each file is stored once, read-only, addressed by its SHA-256. A file that cannot be read is reported, never guessed at.')),
      card('Documents', table([['File', 'filename'], ['Kind', (d) => words(d.doc_type)], ['Filed by', (d) => partyName(d.party_id)], ['State', (d) => tag(d.status)],
        ['Passages', 'passages'], ['Flags', (d) => (d.injection_flags.length ? h('span', { class: 'warn' }, 'flagged') : '')]], docs, { onRow: open, on: (d) => d.document_id === S.picked.doc }))),
      card(null, pane));
  };

  // ── Chat ───────────────────────────────────────────────────────────────────
  VIEWS.chat = async () => {
    const miss = needMatter(); if (miss) return miss;
    const log = h('div', { class: 'transcript' }, h('p', { class: 'muted' }, 'Ask about this matter. Answers are its own passages, findings and approved authorities, each with where it comes from and whether it may be relied on. It will not say who should succeed, and nothing can be decided here.'));
    const sources = h('div', null, h('p', { class: 'muted' }, 'The sources for the last answer appear here.'));
    const box = h('textarea', { placeholder: 'Ask about this matter…  (Ctrl+Enter to send)' });
    const model = h('input', { type: 'checkbox' });
    const send = async () => {
      const question = box.value.trim();
      if (!question) return;
      box.value = '';
      log.append(h('p', null, h('span', { class: 'you' }, 'You: '), question));
      const a = await attempt(() => api('POST', `${M()}/chat`, { question, run_id: S.run ? S.run.run_id : null, use_model: model.checked }));
      if (!a || a === true) return;
      const out = h('div', null, h('span', { class: 'who' }, 'ELI Legal: '));
      a.notes.forEach((n) => out.append(h('p', { class: 'muted' }, n)));
      a.lines.forEach(([text, cites]) => out.append(h('p', null, text, ' ', h('span', { class: 'muted mono' }, cites.map((c) => `[${c}]`).join(' ')))));
      if (a.lines.length) out.append(h('p', { class: 'muted' }, `Summary written by ${a.model_id} from the sources listed; every sentence is tied to them.`));
      a.sources.forEach((s) => out.append(h('div', { class: 'mono muted' }, `[${s.label}] ${words(s.kind)} · ${s.title} ${s.locator}${s.usable ? '' : ' — ' + s.note}`), h('blockquote', { class: s.usable ? '' : 'no' }, s.text)));
      log.append(out); log.scrollTop = log.scrollHeight;
      fill(sources, table([['Ref', 'label'], ['Kind', (s) => words(s.kind)], ['From', 'title'], ['Where', 'locator'], ['May it be relied on?', (s) => (s.usable ? 'yes' : h('span', { class: 'bad' }, `NO — ${s.note}`))]], a.sources, { empty: 'No source was found for that.' }));
    };
    box.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) send(); });
    return h('div', { class: 'cols' }, h('div', null, card('Conversation about this matter', log), card('Your question', box, h('div', { class: 'row' }, btn('Send', send, 'go'), h('label', { class: 'check' }, model, 'Let the model summarise the sources')))), card('Sources for the last answer', sources));
  };

  // ── DAG ────────────────────────────────────────────────────────────────────
  const NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs, ...kids) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, String(v));
    for (const kid of kids) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  }
  function dag(statuses, picked, onPick) {
    const W = 172, H = 50, GX = 44, GY = 14, BAND = 40, perRow = Math.max(3, Math.floor((Math.min(window.innerWidth, 1500) * 0.56) / (W + GX)));
    const pos = {}, col = {}, edges = [];
    let top = 16, width = 0;
    for (let i = 0; i < S.wf.layers.length; i += perRow) {
      const band = S.wf.layers.slice(i, i + perRow), tall = Math.max(...band.map((l) => l.length)) * (H + GY);
      band.forEach((layer, c) => layer.forEach((id, n) => {
        pos[id] = [16 + c * (W + GX), top + (tall - layer.length * (H + GY)) / 2 + n * (H + GY)]; col[id] = c;
        width = Math.max(width, pos[id][0] + W + 16);
      }));
      top += tall + BAND;
    }
    for (const s of S.wf.steps) for (const d of s.depends_on) {
      const [ax, ay] = pos[d], [bx, by] = pos[s.id];
      edges.push(ay + H < by && col[d] >= col[s.id]
        ? svg('path', { class: 'edge', d: `M${ax + W / 2},${ay + H} C${ax + W / 2},${ay + H + (by - ay - H) / 2} ${bx + W / 2},${by - (by - ay - H) / 2} ${bx + W / 2},${by}` })
        : svg('path', { class: 'edge', d: `M${ax + W},${ay + H / 2} C${ax + W + (bx - ax - W) / 2},${ay + H / 2} ${bx - (bx - ax - W) / 2},${by + H / 2} ${bx},${by + H / 2}` }));
    }
    const nodes = S.wf.steps.map((s) => {
      const [x, y] = pos[s.id], state = statuses[s.id] || 'pending';
      const g = svg('g', { class: `node ${state} ${s.manual ? 'manual' : ''} ${picked === s.id ? 'on' : ''}`, transform: `translate(${x},${y})`, tabindex: 0, role: 'button', 'aria-label': `${s.agent.name}: ${state}` },
        svg('rect', { width: W, height: H, rx: 9 }), svg('text', { x: 10, y: 21, 'font-weight': 600 }, s.agent.name),
        svg('text', { class: 'sub', x: 10, y: 38 }, `${words(state)} · ${s.manual ? 'person' : kindOf(s.agent)}`));
      g.addEventListener('click', () => onPick(s.id));
      g.addEventListener('keydown', (e) => { if (e.key === 'Enter') onPick(s.id); });
      return g;
    });
    return svg('svg', { class: 'dag', viewBox: `0 0 ${width} ${top - BAND + 16}`, role: 'group', 'aria-label': 'Case-preparation workflow' }, ...edges, ...nodes);
  }
  // A person's controls over the human stages: hold (or suspend reliance), and lift.
  const personHold = () => (S.run ? (S.run.open_holds || []).find((x) => x.reason === 'held_by_person') : null);
  async function holdRun() {
    const approved = S.run.status === 'approved_for_reliance';
    const v = await reason(approved ? 'Suspend reliance' : 'Put the run on hold', (approved
      ? 'The report is approved. Holding it suspends reliance on it and stops its release'
      : 'Nothing will be approved or released') + ' until a decision-maker lifts the hold or the run is stopped. Why are you holding it?');
    if (v && await attempt(() => api('POST', `${R()}/hold`, v), approved ? 'Reliance suspended, under your name.' : 'On hold, under your name.')) { await openRun(S.run.run_id, false); show(); }
  }
  async function liftHold() {
    const held = personHold();
    if (!held) { note('Nobody has put this run on hold.'); return; }
    const v = await reason('Lift the hold', `It was put on hold because: “${held.detail.split(';').slice(1).join(';').trim()}”. The run returns to where it was. Why can it be lifted?`);
    if (v && await attempt(() => api('POST', `${M()}/holds/${encodeURIComponent(held.hold_id)}/resolve`, { action: 'lift', reason: v.reason }), 'Hold lifted, under your name.')) { await openRun(S.run.run_id, false); show(); }
  }
  const kindOf = (agent) => (agent.kind === 'model-assisted' ? 'model-assisted' : 'rule-based');
  const busy = () => S.run && (S.run.status === 'running' || S.run.status === 'created');
  VIEWS.dag = async () => {
    const miss = needMatter(); if (miss) return miss;
    const statuses = {}; (S.run ? S.run.steps : []).forEach((s) => { statuses[s.step] = s.status; });
    const detail = h('div');
    const pick = (id) => { S.picked.step = id; show(); };
    const step = S.wf.steps.find((s) => s.id === S.picked.step) || S.wf.steps[0];
    const done = S.run ? S.run.steps.find((s) => s.step === step.id) : null;
    if (step.manual && S.run) {
      const held = personHold(), st = S.run.status, isReview = step.id === 'human_review';
      const said = held ? `On hold: “${held.detail.split(';').slice(1).join(';').trim()}”. Nothing goes further until a decision-maker lifts the hold, or the run is stopped.`
        : done && done.status === 'ok' ? `Done. ${done.detail || ''}`
          : isReview && st === 'awaiting_human_review' ? `Waiting for a named reviewer (${S.matter.reviewer_user_ids.join(', ')}) to read the report, acknowledge each stated limit, and approve, return or reject it. Anyone working on the matter can put it on hold first.`
            : !isReview && st === 'approved_for_reliance' ? 'Waiting for a person to prepare the release, confirm each recipient and stage it in the outbox. The approved report can still be put on hold, which suspends reliance on it.'
              : `Not reached yet: the run is ${say(st).toLowerCase()}.`;
      detail.append(card('What this step needs', h('p', null, said), h('div', { class: 'row' },
        isReview ? btn('Open the decision…', () => { S.tab = 'review'; render(); }, st === 'awaiting_human_review' && !held ? 'go' : null)
          : btn('Open the release…', () => { S.tab = 'review'; render(); }, st === 'approved_for_reliance' && !held ? 'go' : null),
        !held && (st === 'awaiting_human_review' || st === 'approved_for_reliance') ? btn('Put on hold…', holdRun) : null,
        held ? btn('Lift the hold…', liftHold) : null)));
    }
    detail.append(h('h2', null, step.agent.name), h('p', null, step.agent.role), facts([['Status', say(done ? done.status : 'pending')],
      ['Runs after', step.depends_on.map((d) => S.wf.steps.find((s) => s.id === d).agent.name).join(', ') || 'nothing: it is first'], ['Done by', step.manual ? 'a named person' : kindOf(step.agent)],
      done && done.detail ? ['Detail', done.detail] : null]), h('h3', null, 'What it recorded'), h('pre', null, done && Object.keys(done.outputs || {}).length ? JSON.stringify(done.outputs, null, 2) : '—'));
    const begin = async () => {
      const made = await attempt(() => api('POST', `${M()}/runs`), 'Run started. It is executing on the server.');
      if (made && made !== true) { S.runs = await api('GET', `${M()}/runs`); await openRun(made.run_id); }
    };
    const stop = async () => { const v = await reason('Stop this run'); if (v && await attempt(() => api('POST', `${R()}/stop`, v), 'Run stopped.')) openRun(S.run.run_id); };
    const restart = async () => {
      const v = await ask('Restart this run', [{ name: 'reason', label: 'Reasons', type: 'textarea', required: true },
        { name: 'from_step', label: 'From', type: 'select', options: [['', 'where it stopped'], ...S.wf.steps.filter((s) => !s.manual).map((s) => [s.id, s.agent.name])] }], 'Restart');
      if (v && await attempt(() => api('POST', `${R()}/resume`, { reason: v.reason, from_step: v.from_step || null }), 'Restarted.')) setTimeout(() => openRun(S.run.run_id), 400);
    };
    if (busy()) S.poll = setInterval(async () => { try { await openRun(S.run.run_id); } catch { /* shown on the next action */ } }, 1500);
    const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
    const state = S.run ? `${say(S.run.status)}${S.run.open_holds.length ? ` · ${plural(S.run.open_holds.length, 'hold', 'holds')} open` : ''}${S.run.open_tasks ? ` · ${plural(S.run.open_tasks, 'check', 'checks')} for a person` : ''}` : 'no run yet';
    return h('div', null, h('div', { class: 'row' }, h('span', { class: 'muted' }, 'Run'), S.runs.length ? runPicker() : null, h('span', { class: `chip ${busy() ? 'warn' : ''}` }, state), h('span', { class: 'spacer' }),
      btn('▶ Start a run', begin, 'go'), btn('↻ Restart…', restart), btn('■ Stop', stop, 'danger')),
    h('div', { class: 'cols' }, card('Case-preparation workflow', dag(statuses, step.id, pick),
      h('p', { class: 'muted' }, 'Green: done. Blue: running. Amber: held. Red: failed. Dashed: a step only a named person can take. A step that does not finish cleanly stops everything after it.')), card('Step', detail)));
  };

  // ── Agents ─────────────────────────────────────────────────────────────────
  VIEWS.agents = async () => {
    const controls = Object.fromEntries((await api('GET', '/v1/governance/registers/controls')).map((c) => [c.control_id || Object.values(c)[0], c.control || Object.values(c)[1]]));
    const step = S.wf.steps.find((s) => s.id === S.picked.agent) || S.wf.steps[0], a = step.agent;
    const done = S.run ? S.run.steps.find((s) => s.step === step.id) : null;
    const mesh = h('div', { class: 'mesh' }, S.wf.layers.map((layer, i) => h('div', { class: 'layer' }, h('span', null, `L${i + 1}`), layer.map((id) => {
      const s = S.wf.steps.find((x) => x.id === id);
      return h('button', { class: `pill ${s.manual ? 'manual' : ''} ${id === step.id ? 'on' : ''}`, onclick: () => { S.picked.agent = id; show(); } }, s.agent.name + (s.agent.kind === 'model-assisted' ? ' ✦' : ''));
    }))));
    const people = S.wf.steps.filter((s) => s.manual).length;
    return h('div', { class: 'cols' }, card('Agent mesh', h('p', { class: 'muted' }, `${S.wf.steps.length - people} automated, ${people} people, ${S.wf.layers.length} layers. Each agent has a fixed mandate: what it reads, what it writes and what it may never do. Those marked ✦ may use a model. None can approve its own work.`), mesh),
      card(a.name, h('p', null, a.role), h('p', { class: 'muted' }, step.manual ? 'A person: this step cannot be taken by software.' : a.kind === 'model-assisted' ? 'Model-assisted: a model may propose; rules decide what is kept.' : 'Rule-based: it follows fixed rules and uses no model.'),
        h('h3', null, 'Reads'), list(a.reads), h('h3', null, 'Writes'), list(a.writes), h('h3', { class: 'bad' }, 'May never'), list(a.may_not),
        h('h3', null, 'Controls it carries out'), list(a.controls.map((c) => `${c} — ${controls[c] || ''}`)),
        h('h3', null, 'In the selected run'), h('p', null, done ? `${words(done.status)}${done.detail ? ' — ' + done.detail : ''}` : 'Not run.')));
  };

  // ── Findings ───────────────────────────────────────────────────────────────
  VIEWS.findings = async () => {
    const miss = needRun(); if (miss) return miss;
    const claims = await api('GET', `${R()}/claims`);
    const f = S.picked.filter || (S.picked.filter = { status: '', kind: '', text: '' });
    const shown = claims.filter((c) => (!f.status || c.status === f.status) && (!f.kind || c.kind === f.kind) && (!f.text || (c.text + ' ' + (c.citation || '')).toLowerCase().includes(f.text.toLowerCase())));
    const option = (key, values, label) => h('select', { 'aria-label': label, onchange: (e) => { f[key] = e.target.value; show(); } }, h('option', { value: '' }, `${label}: all`), [...new Set(values)].sort().map((v) => h('option', { value: v, selected: f[key] === v }, words(v))));
    const pane = h('div', null, h('p', { class: 'muted' }, 'Select a finding to see its source passage, its checks and who decided them.'));
    const open = async (c) => {
      S.picked.claim = c.claim_id;
      const checks = await api('GET', `${M()}/claims/${encodeURIComponent(c.claim_id)}/verifications`);
      const record = async () => {
        const v = await ask('Record a check by hand', [{ name: 'check', label: 'Check', type: 'select', options: S.sys.checks }, { name: 'result', label: 'Result', type: 'select', options: ['verified', 'failed', 'inconclusive'] },
          { name: 'reason', label: 'What you checked it against, and what you found', type: 'textarea', required: true }], 'Record');
        if (v && await attempt(() => api('POST', `${M()}/claims/${encodeURIComponent(c.claim_id)}/verifications`, v), 'Recorded under your name.')) { await openRun(S.run.run_id, false); show(); }
      };
      fill(pane, h('h2', null, `${words(c.kind)} · `, tag(c.status)),
        h('blockquote', null, c.text), facts([c.citation ? ['Citation', c.citation] : null, c.event_date ? ['Date', c.event_date] : null, ['Where it came from', words(c.origin)], c.status_reason ? ['Why', c.status_reason] : null]),
        h('h3', null, 'Source passages'), c.evidence.length ? c.evidence.map((e) => [h('div', { class: 'muted mono' }, `${e.locator} · ${words(e.relationship)}`), h('blockquote', null, e.quote)]) : h('p', { class: 'muted' }, 'None.'),
        h('h3', null, 'Checks'), table([['Check', (v) => checkName(v.verification_type)], ['Result', (v) => tag(v.status)], ['By', (v) => (v.by_human ? `${v.verifier} (person)` : v.verifier)], ['Detail', (v) => v.reason || v.detail]], checks, { empty: 'No check has been run.' }),
        h('div', { class: 'row' }, btn('Record a check by hand…', record)));
    };
    return h('div', null, h('div', { class: 'row' }, h('span', { class: 'muted' }, 'Run'), runPicker(), option('status', claims.map((c) => c.status), 'Status'), option('kind', claims.map((c) => c.kind), 'Kind'),
      h('input', { placeholder: 'Search findings', value: f.text, onchange: (e) => { f.text = e.target.value; show(); } }), h('span', { class: 'muted' }, `${shown.length} of ${claims.length}`)),
    h('div', { class: 'cols' }, card('Findings', table([['Status', (c) => tag(c.status)], ['Kind', (c) => words(c.kind)], ['Finding', 'text', 'clip']], shown, { onRow: open, on: (c) => c.claim_id === S.picked.claim })), card(null, pane)));
  };

  // ── Review ─────────────────────────────────────────────────────────────────
  VIEWS.review = async () => {
    const miss = needRun(); if (miss) return miss;
    const [holds, tasks, claims, docs] = await Promise.all([api('GET', `${R()}/holds`), api('GET', `${R()}/tasks`), api('GET', `${R()}/claims`), api('GET', `${M()}/documents`)]);
    const subject = (x) => { const d = docs.find((y) => y.document_id === x.subject_id), c = claims.find((y) => y.claim_id === x.subject_id); return d ? d.filename : c ? `${c.citation ? c.citation + ' ' : ''}“${c.text}”` : ''; };
    let report = null;
    try { report = await api('GET', `${R()}/report`); } catch (e) { if (!S.user) throw e; }
    const again = async () => { await openRun(S.run.run_id, false); show(); };
    const resolve = async (hold, action) => {
      const v = await reason(action === 'exclude' ? 'Take this out of reliance' : 'Accept this gap', action === 'exclude' ? 'The finding stays on the record, marked excluded, with your reasons.' : 'The run will continue without it; your reasons are shown in the report.');
      if (v && await attempt(() => api('POST', `${M()}/holds/${encodeURIComponent(hold.hold_id)}/resolve`, { action, reason: v.reason }), 'Recorded under your name.')) again();
    };
    const answer = async (task) => {
      const v = await ask('Answer this check', [{ name: 'result', label: 'Result', type: 'select', options: ['verified', 'failed', 'inconclusive'] }, { name: 'reason', label: 'What you checked it against, and what you found', type: 'textarea', required: true }], 'Record', task.question);
      if (v && await attempt(() => api('POST', `${M()}/claims/${encodeURIComponent(task.claim_id)}/verifications`, { check: task.verification_type, result: v.result, reason: v.reason }), 'Recorded under your name.')) again();
    };
    const ticks = (report ? report.warnings : []).map((w) => [w.split(': ', 1)[0], h('input', { type: 'checkbox' }), w]);
    const reasons = h('textarea', { placeholder: 'Your reasons. They are recorded with the decision.' });
    const decide = async (decision) => {
      if (await attempt(() => api('POST', `${R()}/review`, { decision, reasons: reasons.value, report_hash: report.sha256, acknowledged: ticks.filter(([, box]) => box.checked).map(([id]) => id) }), 'Decision recorded under your name.')) again();
    };
    const people = h('textarea', { placeholder: 'One recipient per line:  id | name | address' });
    const staged = h('div');
    const prepare = async () => {
      const recipients = lines(people.value).map((l) => { const [recipient_id, display_name, address] = l.split('|').map((x) => x.trim()); return { recipient_id, display_name: display_name || recipient_id, address: address || '' }; });
      const pack = await attempt(() => api('POST', `${R()}/releases`, { recipients }));
      if (!pack || pack === true) return;
      const boxes = pack.recipients.map((r) => [r.recipient_id, h('input', { type: 'checkbox', disabled: !r.entitled }), `${r.display_name} — ${r.entitled ? 'entitled' : 'NOT entitled to this matter'}`]);
      fill(staged, h('p', null, 'Confirm each recipient yourself:'), boxes.map(([, box, text]) => h('label', { class: 'check' }, box, text)),
        h('div', { class: 'row' }, btn('Release to the confirmed recipients', async () => {
          const sent = await attempt(() => api('POST', `${M()}/releases/${encodeURIComponent(pack.release_id)}/send`, { confirmed_recipient_ids: boxes.filter(([, box]) => box.checked).map(([id]) => id) }));
          if (sent && sent !== true) fill(staged, list(sent.map((r) => `${r.recipient_id}: ${words(r.status)} ${r.detail || ''}`)), h('p', { class: 'muted' }, 'Staged in the outbox. Nothing has been sent anywhere.'));
        }, 'go')));
    };
    return h('div', null, h('div', { class: 'row' }, h('span', { class: 'muted' }, 'Run'), runPicker(), h('span', { class: 'chip' }, say(S.run.status))),
      card(`Holds (${holds.length})`, h('p', { class: 'muted' }, 'A hold closes when its check passes, or when a named person decides, with reasons. Nothing reaches review while one is open. Each reason below says what it means and what you can do.'),
        holds.length ? h('ul', null, [...new Set(holds.map((x) => x.reason_code))].map((code) => h('li', null, h('b', null, `${holdWhy(code)}. `), S.w && S.w.holds[code] ? `${S.w.holds[code].why} ${S.w.holds[code].options.join(' ')}` : ''))) : null,
        table([['Held', (x) => (x.scope === 'claim' ? 'a finding' : `a ${words(x.scope)}`)], ['Why', (x) => h('span', { title: S.w && S.w.holds[x.reason_code] ? `${S.w.holds[x.reason_code].why} ${S.w.holds[x.reason_code].options.join(' ')}` : '' }, holdWhy(x.reason_code))], ['What the system found', (x) => x.detail], ['What', subject, 'wide'], ['', (x) => (x.reason_code === 'held_by_person' ? h('div', { class: 'row' }, btn('Lift the hold…', liftHold)) : h('div', { class: 'row' }, btn('Take out of reliance…', () => resolve(x, 'exclude'), 'danger'), btn('Accept the gap…', () => resolve(x, 'waive'))))]], holds, { empty: 'No open holds.' })),
      card(`Checks for you (${tasks.filter((t) => t.status === 'open').length})`, table([['Check', (t) => checkName(t.verification_type)], ['Question', 'question'], ['Finding', (t) => subject({ subject_id: t.claim_id }), 'wide'], ['', (t) => (t.status === 'open' ? btn('Answer…', () => answer(t)) : words(t.status))]], tasks, { empty: 'Nothing is waiting for a person.' })),
      h('div', { class: 'cols' }, card('Report', report ? [facts([['Version', report.version], ['State', h('span', { class: report.release_status === 'approved_for_reliance' ? 'good' : 'warn' }, words(report.release_status))], ['SHA-256', h('span', { class: 'mono' }, report.sha256)]]),
        h('div', { class: 'row' }, btn('Download', () => attempt(() => download('GET', `${R()}/report.md`, `report_${S.run.run_id}.md`)))), h('div', { class: 'scroll' }, h('pre', null, report.text))] : h('p', { class: 'muted' }, 'No report has been drafted for this run yet.')),
      h('div', null, card('Decision', report ? [h('p', { class: 'muted' }, 'You approve this exact version, and only after acknowledging every limit it states.'), ticks.map(([, box, text]) => h('label', { class: 'check' }, box, text)), h('label', null, 'Reasons'), reasons,
        h('div', { class: 'row' }, btn('Approve for reliance', () => decide('approve'), 'go'), btn('Return for correction', () => decide('return_for_correction')), btn('Reject', () => decide('reject'), 'danger'), h('span', { class: 'spacer' }), btn('Put on hold…', holdRun), personHold() ? btn('Lift the hold…', liftHold) : null)] : h('p', { class: 'muted' }, 'There is nothing to decide yet.')),
      card('Release', h('p', { class: 'muted' }, 'An approved report is staged for entitled recipients you confirm one by one. The system sends nothing itself.'), people, h('div', { class: 'row' }, btn('Prepare the release', prepare), h('span', { class: 'spacer' }), S.run.status === 'approved_for_reliance' ? btn('Suspend reliance (put on hold)…', holdRun) : null, personHold() ? btn('Lift the hold…', liftHold) : null), staged))));
  };

  // ── Audit Trail ────────────────────────────────────────────────────────────
  VIEWS.audit = async () => {
    const global = !!S.picked.globalAudit;
    if (!global && !S.matter) return needMatter();
    const events = await api('GET', `/v1/audit/events${global ? '' : `?matter_id=${encodeURIComponent(S.matter.matter_id)}`}`);
    const pane = h('pre', null, 'Select an event to see everything recorded for it.');
    const verify = async () => { const r = await attempt(() => api('GET', '/v1/audit/verify')); if (r && r !== true) note(r.ok ? `The chain is valid: ${r.events} events, every signature and link checks out.` : `THE CHAIN IS INVALID: ${r.error}. Stop, preserve the databases and open an incident.`, r.ok ? 'good' : 'bad'); };
    const record = async () => { const r = await attempt(() => api('GET', `${R()}/record`)); if (r && r !== true) note(r.ok ? `The record is complete: ${r.events_checked} events account for every step, hold and decision.` : `Gaps: ${r.gaps.join('; ')}`, r.ok ? 'good' : 'bad'); };
    return h('div', null, card('Ledger', h('div', { class: 'row' }, h('span', { class: `chip ${S.sys.audit.ok ? 'good' : 'bad'}` }, `${events.length} events shown`), h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: global, onchange: (e) => { S.picked.globalAudit = e.target.checked; show(); } }), 'Events outside any matter (sign-ins, users, sources, settings)'), h('span', { class: 'spacer' }),
      btn('Verify the chain', verify, 'go'), S.run ? btn("Check this run's record", record) : null, btn('Download a checkpoint', () => attempt(() => download('POST', '/v1/audit/checkpoint', 'audit_checkpoint.json'))), S.run ? btn('Download the evidence pack', () => attempt(() => download('POST', `${R()}/evidence-pack`, `evidence_pack_${S.run.run_id}.zip`))) : null),
      h('p', { class: 'muted' }, 'Each event is signed over the one before it. Editing, removing or truncating events breaks the chain. The ledger holds identifiers and hashes, never document text.')),
    h('div', { class: 'cols' }, card('Events', table([['#', 'seq'], ['When (UTC)', (e) => when(e.created_at)], ['What happened', (e) => e.said || words(e.event_type)], ['Who', 'actor_id'], ['How they proved who they were', (e) => e.proof || (e.payload || {}).auth || ''], ['Action', 'action'], ['Outcome', (e) => words(e.outcome)]], events, { onRow: (e) => { pane.textContent = JSON.stringify(e, null, 2); } })), card('Selected event', pane)));
  };

  // ── Governance ─────────────────────────────────────────────────────────────
  const GOV = [['compliance', 'Requirements'], ['actions', 'Organisation actions'], ['checks', 'Routine checks'], ['matters', 'All matters'], ['registers', 'Registers, monitoring and incidents']];
  const today = () => new Date().toISOString().slice(0, 10);
  const ACTION_STATE = { done: 'Done', waiting: 'To do', review_due: 'Review due', not_applicable: 'Does not apply' };
  async function recordAction(a, users) {
    const path = `/v1/compliance/actions/${encodeURIComponent(a.id)}`;
    const done = (r) => r && r !== true;
    if (a.evidence === 'form') {
      const v = await ask(a.title, [...a.form.map((f) => ({ name: f.key, label: f.label, type: 'textarea', required: true })), { name: 'reference', label: 'Where the signed copy is kept (optional)' }], 'Record', a.what_to_do);
      if (v) { const { reference, ...answers } = v; return done(await attempt(() => api('POST', path, { answers, reference }), 'Recorded under your name.')); }
    } else if (a.evidence === 'attestation') {
      const v = await ask(a.title, [{ name: 'confirmed', label: `I confirm: “${a.statement}”`, type: 'checkbox' }, { name: 'notes', label: 'Notes', type: 'textarea' }, { name: 'reference', label: 'Reference (optional)' }], 'Record', a.what_to_do);
      if (v) return done(await attempt(() => api('POST', path, v), 'Recorded under your name.'));
    } else if (a.evidence === 'registration') {
      const v = await ask(a.title, [{ name: 'reference', label: 'Registration number', required: true }, { name: 'notes', label: 'Notes', type: 'textarea' }], 'Record', a.what_to_do);
      if (v) return done(await attempt(() => api('POST', path, v), 'Recorded under your name.'));
    } else if (a.evidence === 'training') {
      const v = await ask('Record training', [{ name: 'user_id', label: 'Person', type: 'select', options: users.filter((u) => u.active).map((u) => [u.user_id, `${u.display_name} (${u.user_id})`]) },
        { name: 'course', label: 'Training', value: 'AI literacy and the instructions for use', required: true }, { name: 'completed_on', label: 'Completed on', type: 'date', value: today(), required: true },
        { name: 'expires_on', label: 'Valid until (a year if blank)', type: 'date' }], 'Record', a.what_to_do);
      if (v) return done(await attempt(() => api('POST', '/v1/compliance/training', { ...v, expires_on: v.expires_on || null }), 'Training recorded.'));
    } else if (a.evidence === 'retention') {
      const v = await ask('Retention', [{ name: 'audit_days', label: 'Keep the audit trail (days, at least 183)', type: 'number', value: '3653', required: true },
        { name: 'closed_matter_days', label: 'Keep a closed matter’s documents (days)', type: 'number', value: '365', required: true }], 'Set', a.what_to_do);
      if (v) return done(await attempt(() => api('POST', '/v1/compliance/retention', { audit_days: Number(v.audit_days), closed_matter_days: Number(v.closed_matter_days) }), 'Retention set.'));
    } else if (a.evidence === 'evaluation') {
      const r = await attempt(() => api('POST', '/v1/compliance/evaluation', {}));
      if (done(r)) { note(r.summary, r.answers.passed === 'yes' ? 'good' : 'bad'); return true; }
    } else if (a.evidence === 'document') {
      const kind = a.id === 'OA-05' ? 'annex_iv' : 'declaration';
      const drafted = await attempt(() => api('POST', `/v1/compliance/documents/${kind}`));
      if (!done(drafted)) return false;
      const url = URL.createObjectURL(new Blob([drafted.text], { type: 'text/markdown' }));
      const link = h('a', { href: url, download: `${kind}.md` }); document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      const v = await ask(`Sign off: ${a.title}`, [{ name: 'sha256', label: 'SHA-256 of the document you are signing off', value: drafted.sha256, required: true }, { name: 'notes', label: 'Notes', type: 'textarea' }], 'Sign off',
        `The draft has been downloaded. Complete what only the provider can state, then sign it off. “${a.statement}”`);
      if (v) return done(await attempt(() => api('POST', `${path}/sign-off`, v), 'Signed off under your name.'));
    }
    return false;
  }
  VIEWS.governance = async () => {
    const pick = GOV.some(([k]) => k === S.picked.gov) ? S.picked.gov : 'compliance';
    const sub = h('div', { class: 'subnav' }, GOV.map(([k, text]) => h('button', { 'aria-pressed': String(k === pick), onclick: () => { S.picked.gov = k; show(); } }, text)));
    const body = await GOV_VIEWS[pick]();
    return h('div', null, sub, body);
  };
  const GOV_VIEWS = {
    compliance: async () => {
      const c = await api('GET', '/v1/compliance');
      return card(c.headline, h('p', { class: 'muted' }, 'Each requirement is met by the software, met once your organisation has recorded its part, or waiting for that. Working aids to check against the official texts: not legal advice, not a conformity assessment.'),
        h('div', { class: 'scroll' }, table([['Ref', 'id'], ['Instrument', 'instrument'], ['Provision', 'reference'], ['Requirement', 'requirement', 'wide'], ['Who does it', 'who'], ['Status', (r) => tag(r.state)],
          ['What remains', (r) => (r.actions.length ? r.actions.join(', ') : '—')], ['How it is met', 'how_met', 'clip']], c.requirements)));
    },
    actions: async () => {
      const c = await api('GET', '/v1/compliance');
      let users = [];
      try { users = await api('GET', '/v1/users', undefined, { quiet: true }); } catch { /* not for this role */ }
      const waiting = c.actions.filter((a) => a.state === 'waiting' || a.state === 'review_due').length;
      const notApplicable = async (a) => {
        const v = await reason(`${a.title}: it does not apply`, 'Say why it does not apply to this deployment. It is recorded in your name and reviewed again when its date comes.');
        if (v && await attempt(() => api('POST', `/v1/compliance/actions/${encodeURIComponent(a.id)}`, { not_applicable: true, notes: v.reason }), 'Recorded.')) show();
      };
      return card(`Organisation actions (${waiting} to do)`, h('p', { class: 'muted' }, 'What the software cannot do for you. Record each one when done, or why it does not apply. Recording needs the governance or legal administrator role and your passphrase.'),
        h('div', { class: 'scroll' }, table([['Action', (a) => `${a.id} ${a.title}`], ['What to do', 'what_to_do', 'wide'], ['For', (a) => words(a.owner)],
          ['Status', (a) => h('span', { class: a.state === 'done' || a.state === 'not_applicable' ? 'good' : 'warn' }, ACTION_STATE[a.state] || say(a.state))], ['Where it stands', 'detail'],
          ['', (a) => h('div', { class: 'row' }, btn('Record…', async () => { if (await recordAction(a, users)) show(); }, a.state === 'done' ? null : 'go'), btn('Does not apply…', () => notApplicable(a)))]], c.actions)));
    },
    checks: async () => {
      const c = await api('GET', '/v1/checks');
      const run = async () => { const r = await attempt(() => api('POST', '/v1/checks/run'), 'The routine checks have run.'); if (r) show(); };
      const l = c.latest;
      const schedule = c.every_hours > 0 ? `They run on their own every ${c.every_hours} hours.` : 'They run only when someone asks.';
      return card('Routine checks', l ? [h('p', { class: checkTone(l.state) }, h('b', null, l.headline)), h('p', { class: 'muted' }, `Last run ${when(l.finished_at)} UTC by ${l.by}. ${schedule}`),
        l.results.map((r) => h('details', { open: r.state !== 'ok' }, h('summary', null, h('span', { class: checkTone(r.state) }, MARK[r.state] || '?'), ` ${r.title}: ${r.summary}`),
          r.what_to_do ? h('p', null, h('b', null, 'What to do: '), r.what_to_do) : null, r.items.length ? list(r.items.map((i) => i.text)) : null,
          r.acted.length ? [h('p', null, h('b', null, 'What the check did:')), list(r.acted)] : null))]
        : h('p', { class: 'muted' }, `The routine checks have not run yet. ${schedule}`), h('div', { class: 'row' }, btn('Run the checks now', run, 'go')));
    },
    matters: async () => {
      let rows;
      try { rows = await api('GET', '/v1/oversight/matters', undefined, { quiet: true }); } catch { return card('All matters', h('p', { class: 'muted' }, 'Overseeing every matter needs the auditor, governance or legal administrator role.')); }
      return card('All matters', h('p', { class: 'muted' }, 'Every matter on this system. A matter you are not on shows no name, party or content.'),
        table([['Matter', 'name'], ['For', (r) => words(r.profile)], ['Legal system', 'jurisdiction'], ['State', (r) => tag(r.status)], ['People', 'people'], ['Last run', (r) => (r.last_run ? tag(r.last_run) : 'none')], ['Open holds', 'open_holds']], rows));
    },
    registers: async () => {
      const names = await api('GET', '/v1/governance/registers');
    const which = names.includes(S.picked.register) ? S.picked.register : names[0];
    const rows = await api('GET', `/v1/governance/registers/${encodeURIComponent(which)}`);
    let watch = null, incidents = [];
    try { watch = await api('GET', '/v1/monitoring', undefined, { quiet: true }); } catch { /* not for this role */ }
    if (S.matter) { try { incidents = await api('GET', `${M()}/incidents`, undefined, { quiet: true }); } catch { /* not for this role */ } }
    const open = async () => {
      const v = await ask('Open an incident', [{ name: 'category', label: 'Category', required: true }, { name: 'severity', label: 'Severity', type: 'select', options: ['low', 'medium', 'high', 'serious'], value: 'medium' }, { name: 'detail', label: 'What happened', type: 'textarea', required: true }], 'Open');
      if (v && await attempt(() => api('POST', `${M()}/incidents`, { ...v, run_id: S.run ? S.run.run_id : null }), 'Incident opened.')) show();
    };
    const close = async (i) => {
      const v = await ask('Close this incident', [{ name: 'containment', label: 'What was done to contain it', type: 'textarea', required: true }, { name: 'reason', label: 'Why it can be closed', type: 'textarea', required: true }], 'Close');
      if (v && await attempt(() => api('POST', `${M()}/incidents/${encodeURIComponent(i.incident_id)}/close`, v), 'Incident closed.')) show();
    };
    const reporting = async (i) => {
      const v = await ask('Decide on reporting (EU AI Act Art. 73)', [
        { name: 'reportable', label: 'Decision', type: 'select', options: [['yes', 'Reportable to the market surveillance authority'], ['no', 'Not reportable']] },
        { name: 'serious_kind', label: 'Kind', type: 'select', options: [['general', 'A serious incident (15 days)'], ['death', 'A person’s death (10 days)'], ['widespread', 'A widespread infringement or critical-infrastructure disruption (2 days)']] },
        { name: 'reason', label: 'Your reasons', type: 'textarea', required: true }, { name: 'reported_on', label: 'Reported on (if it has been)', type: 'date' }, { name: 'reference', label: 'The authority’s reference' }], 'Record');
      if (v && await attempt(() => api('POST', `${M()}/incidents/${encodeURIComponent(i.incident_id)}/reporting`, { ...v, reportable: v.reportable === 'yes', reported_on: v.reported_on || null }), 'Decision recorded under your name.')) show();
    };
    const reportState = (i) => (i.reported_at ? `reported ${when(i.reported_at).slice(0, 10)} (${i.report_reference})` : i.reportable === false ? 'not reportable' : i.severity === 'serious' ? h('span', { class: 'warn' }, 'decision needed') : '—');
    const cols = rows.length ? Object.keys(rows[0]).map((k) => [words(k), k]) : [];
    return h('div', null, card('Registers', h('div', { class: 'row' }, names.map((n) => h('button', { class: n === which ? 'go' : null, onclick: () => { S.picked.register = n; show(); } }, `${words(n)}`)), h('span', { class: 'muted' }, `${rows.length} rows. Each control names the code that carries it out and the tests that prove it; that link is checked automatically.`)), table(cols, rows)),
      h('div', { class: 'cols' }, card('Monitoring', watch ? [watch.alerts.length ? list(watch.alerts) : h('p', { class: 'good' }, 'No alert.'), facts(Object.entries(watch).filter(([k]) => k !== 'alerts').map(([k, v]) => [words(k), typeof v === 'object' ? JSON.stringify(v) : String(v)]))] : h('p', { class: 'muted' }, 'Your role does not include monitoring.')),
        card('Incidents in this matter', table([['Opened', (i) => when(i.created_at)], ['Category', 'category'], ['Severity', (i) => words(i.severity)], ['State', (i) => tag(i.status)], ['Detail', 'detail'], ['Reporting (Art. 73)', reportState], ['', (i) => (i.status === 'open' ? h('div', { class: 'row' }, btn('Decide on reporting…', () => reporting(i)), btn('Close…', () => close(i))) : '')]], incidents, { empty: 'None.' }), S.matter ? h('div', { class: 'row' }, btn('Open an incident…', open)) : null)));
    },
  };

  // ── Sources ────────────────────────────────────────────────────────────────
  VIEWS.sources = async () => {
    const sources = await api('GET', '/v1/sources');
    const s = sources.find((x) => x.source_id === S.picked.source) || sources[0];
    let held = [];
    if (s) { try { held = await api('GET', `/v1/sources/${encodeURIComponent(s.source_id)}/authorities`, undefined, { quiet: true }); } catch { /* not for this role */ } }
    const text = h('div');
    const add = async () => {
      const v = await ask('Register a legal source', [{ name: 'source_id', label: 'Short identifier', required: true }, { name: 'name', label: 'Name', required: true },
        { name: 'jurisdictions', label: 'Legal systems it covers', type: 'select', multiple: true, options: S.sys.jurisdictions.map((j) => [j.code, `${j.code} · ${j.name}`]) },
        { name: 'authority_owner', label: 'Who publishes it' }, { name: 'licence', label: 'Licence, and whether it permits this use', type: 'textarea' }, { name: 'terms_reviewed', label: 'The terms of use have been read and permit this', type: 'checkbox' },
        { name: 'treatment_semantics', label: 'How it says whether an authority is still good law', type: 'textarea' }, { name: 'freshness', label: 'How often it is updated' }], 'Register', 'A registered source cannot be used until someone with the right approves it.');
      if (v && await attempt(() => api('POST', '/v1/sources', v), 'Registered. It is not yet approved.')) show();
    };
    const act = (verb, done) => async () => { if (await attempt(() => api('POST', `/v1/sources/${encodeURIComponent(s.source_id)}/${verb}`), done)) show(); };
    const load = async () => {
      const v = await ask('Load a corpus', [{ name: 'directory', label: "Folder name inside the server's import area", required: true }], 'Load', 'The files must already be on the server, in its import folder. Nothing is fetched from the internet.');
      if (!v) return;
      const r = await attempt(() => api('POST', `/v1/sources/${encodeURIComponent(s.source_id)}/import`, v));
      if (r && r !== true) { note(`${r.imported} authorities loaded.`, 'good'); show(); }
    };
    const open = async (a) => {
      const parts = await api('GET', `/v1/authorities/${encodeURIComponent(a.authority_id)}`);
      fill(text, h('h2', null, a.citation), facts([['Title', a.title], ['Court', a.court || '—'], ['Decided', a.decision_date || '—'], ['Status', words(a.status)], ['Status confirmed', when(a.status_checked_at) || 'never'], ['On what basis', a.status_basis || '—']]),
        h('h3', null, 'How later law has treated it'), list(a.treatments.map((t) => `${words(t.treatment)} ${t.effective_date || ''} ${t.by_citation ? 'by ' + t.by_citation : ''} ${t.note || ''}`)),
        h('h3', null, 'Text'), parts.map((p) => [h('div', { class: 'muted mono' }, p.locator), h('blockquote', null, p.text)]));
    };
    return h('div', { class: 'cols' }, h('div', null, card('Approved-source register', h('p', { class: 'muted' }, 'The law always comes from a source on this list. An unapproved source cannot be reached, and nothing here reaches the internet.'),
      table([['Source', 'name'], ['Covers', (x) => x.jurisdictions.join(', ')], ['Approved', (x) => (x.approved ? h('span', { class: 'good' }, `yes, by ${x.approved_by}`) : h('span', { class: 'warn' }, 'no'))], ['Terms read', (x) => (x.terms_reviewed ? 'yes' : 'no')]], sources, { onRow: (x) => { S.picked.source = x.source_id; show(); }, on: (x) => s && x.source_id === s.source_id, empty: 'No source is registered.' }),
      h('div', { class: 'row' }, btn('Register a source…', add), s ? [btn('Approve', act('approve', 'Approved.'), 'go'), btn('Revoke', act('revoke', 'Revoked.'), 'danger'), btn('Load a corpus…', load)] : null)),
    s ? card(`What ${s.name} holds`, table([['Citation', 'citation'], ['Title', 'title', 'clip'], ['Status', (a) => h('span', { class: a.status === 'in_force' ? 'good' : 'warn' }, words(a.status))]], held, { onRow: open, empty: 'Nothing loaded.' })) : null), card(null, text.childNodes.length ? text : [text, h('p', { class: 'muted' }, 'Select an authority to read it and its status history.')]));
  };

  // ── Laws & Standards ───────────────────────────────────────────────────────
  VIEWS.laws = async () => {
    const all = await api('GET', '/v1/frameworks');
    const picked = all.find((f) => f.id === S.picked.law) || all[0];
    const detail = picked ? await api('GET', `/v1/frameworks/${encodeURIComponent(picked.id)}`) : null;
    const may = S.user.may || {};
    const act = (verb, done, method = 'POST') => async () => { if (await attempt(() => api(method, `/v1/frameworks/${encodeURIComponent(picked.id)}${verb}`), done)) show(); };
    const upload = async () => {
      const file = h('input', { type: 'file', accept: '.json,.csv,.pdf,.docx,.odt,.rtf,.txt,.md,.html,.htm,.eml' });
      const v = await ask('Import a law or standards package', [{ name: 'title', label: 'Title (taken from the file if blank)' }, { name: 'pack_id', label: 'Identifier (optional)' }, { name: 'issuer', label: 'Issued by' }, { name: 'version', label: 'Version', value: '1' }], 'Choose the file…',
        'A JSON package (as Export writes), a CSV requirements register (id, reference, title, text, effect), or your organisation\'s rules as a document. It cannot be used on a matter until it is approved.');
      if (!v) return;
      file.addEventListener('change', async () => {
        const f = file.files[0]; if (!f) return;
        const q = new URLSearchParams({ filename: f.name, title: v.title, pack_id: v.pack_id, issuer: v.issuer, version: v.version || '1' });
        const r = await attempt(() => api('POST', `/v1/frameworks/upload?${q}`, f, { raw: true }));
        if (r && r !== true) { note(`${r.title}: ${r.requirements} requirement(s); ${r.standing}.`, r.usable ? 'good' : 'bad'); S.picked.law = r.id; show(); }
      });
      file.click();
    };
    const current = async () => {
      const v = await reason('Confirm checked against the official text', `You checked “${picked.title}” against the official text today and it still states the law correctly. Say which text you checked it against; the routine checks then count its review from today.`);
      if (v && await attempt(() => api('POST', `/v1/frameworks/${encodeURIComponent(picked.id)}/current`, { checked_on: today(), note: v.reason }), 'Recorded under your name.')) show();
    };
    const validate = async () => {
      const v = await ask('Record a lawyer\'s validation', [{ name: 'lawyer', label: 'Name of the qualified lawyer who checked this version against its official text', required: true }], 'Record');
      if (v && await attempt(() => api('POST', `/v1/frameworks/${encodeURIComponent(picked.id)}/validate`, v), 'Validation recorded.')) show();
    };
    const exportPack = () => attempt(() => download('GET', `/v1/frameworks/${encodeURIComponent(picked.id)}/export`, `${picked.id}.json`));
    let mine = null, recommended = [];
    if (S.matter) {
      mine = await api('GET', `${M()}/frameworks`);
      recommended = await api('GET', `/v1/frameworks/recommended?profile=${encodeURIComponent(S.matter.profile)}&jurisdiction=${encodeURIComponent(S.matter.jurisdiction)}`);
    }
    const applied = new Set(S.matter ? S.matter.framework_ids || [] : []);
    const boxes = all.filter((f) => f.usable).map((f) => [f.id, h('input', { type: 'checkbox', checked: applied.has(f.id) }), `${recommended.includes(f.id) ? '★ ' : ''}${f.title} (${f.standing})`]);
    const save = async () => {
      if (await attempt(() => api('PUT', `${M()}/frameworks`, { ids: boxes.filter(([, b]) => b.checked).map(([id]) => id) }), 'Saved. They apply from the next run.')) { S.matter = await api('GET', `/v1/matters/${encodeURIComponent(S.matter.matter_id)}`); show(); }
    };
    const tickRecommended = () => boxes.forEach(([id, b]) => { b.checked = recommended.includes(id); });
    return h('div', null,
      card('Law and standards packages', h('p', { class: 'muted' }, 'International, regional, national, professional and your organisation\'s own. The packages a matter applies are given to the model as rules in every call, tighten the system where they say so, become confirmations the reviewer must give before approval, and are listed in the report. Shipped packages are summaries until a qualified lawyer\'s validation is recorded; your own must be approved.'),
        table([['Package', (f) => f.short_title + (f.example ? ' (example)' : '')], ['Instrument', 'instrument', 'clip'], ['Scope', 'scope'], ['Applies in', (f) => f.jurisdictions.join(', ').replace('*', 'anywhere')], ['Standing', (f) => h('span', { class: f.usable ? (f.validated || f.origin !== 'shipped' ? 'good' : 'warn') : 'bad' }, f.standing)], ['Requirements', 'requirements']], all,
          { onRow: (f) => { S.picked.law = f.id; show(); }, on: (f) => picked && f.id === picked.id }),
        may['framework.manage'] ? h('div', { class: 'row' }, btn('Import a package or document…', upload, 'go'), picked ? [btn('Approve', act('/approve', 'Approved.')), btn('Record a lawyer\'s validation…', validate), btn('Confirm checked against the official text…', current), btn('Withdraw', act('/withdraw', 'Withdrawn.'), 'danger'), btn('Reinstate', act('/reinstate', 'Reinstated.')), picked.origin !== 'shipped' ? btn('Remove', act('', 'Removed.', 'DELETE')) : null, btn('Export', exportPack)] : null) : null),
      h('div', { class: 'cols' },
        card(detail ? detail.pack.title : 'No package', detail ? [facts([['Instrument', detail.pack.instrument], ['Issued by', detail.pack.issuer], ['Version', detail.pack.version], ['Checked against its source', detail.pack.as_at || 'not recorded'], ['Standing', detail.standing]]),
          h('p', null, detail.pack.description), detail.pack.rules.status_max_age_days || detail.pack.rules.forbidden_terms.length ? h('p', { class: 'warn' }, 'Tightens the system: ' + [detail.pack.rules.status_max_age_days ? `authority status confirmed within ${detail.pack.rules.status_max_age_days} days` : '', detail.pack.rules.forbidden_terms.length ? `model-drafted text may not contain ${detail.pack.rules.forbidden_terms.join(', ')}` : ''].filter(Boolean).join('; ')) : null,
          table([['Provision', 'reference'], ['Requirement', 'title'], ['How it is met', (r) => (S.w ? S.w.effects : {})[r.effect] + (r.controls.length ? ` (${r.controls.join(', ')})` : '')], ['Only for', (r) => r.profiles.map(words).join(', ') || 'all']], detail.pack.requirements,
            { onRow: (r) => note(`${r.reference} — ${r.text}${r.effect === 'instruction' ? `\nThe model is told: ${r.instruction || r.text}` : ''}${r.statement ? `\n${r.effect === 'disclosure' ? 'The report says' : 'The reviewer confirms'}: ${r.statement}` : ''}`, 'good') }),
          h('p', { class: 'muted' }, detail.pack.status_note), detail.pack.licence_note ? h('p', { class: 'muted' }, detail.pack.licence_note) : null] : null),
        card('Packages applied to the open matter', S.matter ? [h('p', { class: 'muted' }, `${S.matter.name}. Ticked packages apply from the next run. ★ marks those recommended for this kind of matter and legal system.`),
          boxes.map(([, box, text]) => h('label', { class: 'check' }, box, text)),
          h('div', { class: 'row' }, btn('Tick the recommended set', tickRecommended), btn('Save for this matter', save, 'go')),
          h('h3', null, 'What the model is told'), h('pre', null, mine.model_is_told || 'No package applies, so the model is given only the system\'s own rules.')] : h('p', { class: 'muted' }, 'Open a matter to choose its packages.'))));
  };

  // ── Settings ───────────────────────────────────────────────────────────────
  VIEWS.settings = async () => {
    const net = await api('GET', '/v1/network');
    const cfg = await api('GET', '/v1/config');
    const may = S.user.may;
    const users = may['user.manage'] ? await api('GET', '/v1/users') : [];
    const roles = may['user.manage'] ? Object.keys(await api('GET', '/v1/roles')) : [];
    const passphrase = async () => {
      const v = await ask('Change your passphrase', [{ name: 'current', label: 'Current passphrase', type: 'password', required: true }, { name: 'new', label: 'New passphrase (at least 10 characters)', type: 'password', required: true }, { name: 'again', label: 'New passphrase again', type: 'password', required: true }], 'Change');
      if (!v) return;
      if (v.new !== v.again) { note('The two new passphrases differ. Nothing was changed.'); return; }
      if (await attempt(() => api('POST', '/v1/auth/passphrase', { current: v.current, new: v.new }), 'Changed. Sign in again with the new passphrase.')) signOut();
    };
    const token = async () => {
      const v = await ask('Create an API token', [{ name: 'label', label: 'What it is for' }], 'Create', 'A token lets a program act as you. It is shown once.');
      const r = v && await attempt(() => api('POST', '/v1/auth/tokens', v));
      if (r && r !== true) await ask('Your token', [{ name: 't', label: 'Copy it now; it cannot be shown again', value: r.token }], 'Done');
    };
    const person = (label, call) => async (u) => { if (await attempt(() => call(u), label)) show(); };
    const add = async () => {
      const v = await ask('Add a user', [{ name: 'user_id', label: 'User identifier', required: true }, { name: 'display_name', label: 'Name', required: true }, { name: 'roles', label: 'Roles', type: 'select', multiple: true, options: roles.map((r) => [r, `${roleName(r)} — ${(S.w.roles[r] || {}).summary || ''}`]) },
        { name: 'passphrase', label: 'First passphrase (they should change it)', type: 'password', required: true }], 'Add');
      if (v && await attempt(() => api('POST', '/v1/users', v), 'User added.')) show();
    };
    const setPhrase = async (u) => { const v = await ask(`Set a passphrase for ${u.display_name}`, [{ name: 'new', label: 'New passphrase', type: 'password', required: true }], 'Set'); if (v && await attempt(() => api('POST', `/v1/users/${encodeURIComponent(u.user_id)}/passphrase`, v), 'Set. Their sessions have been ended.')) show(); };
    const backends = [['gguf', 'A GGUF model file on this machine (as ELI v2 and v3 use)'], ['openai_compat', 'A model server on this machine (Ollama, llama.cpp, LM Studio)'],
      ...(cfg.model.hosted_by_eli_v3 ? [['eli_v3', "ELI v3's model"]] : []), ['none', 'No model (rules only)']];
    const backend = h('select', null, backends.map(([b, text]) => h('option', { value: b, selected: cfg.model.backend === b }, text)));
    const url = h('input', { value: cfg.model.url }), model = h('input', { value: cfg.model.backend === 'openai_compat' ? cfg.model.model : '', placeholder: 'model name' }), verifier = h('input', { value: cfg.model.backend === 'openai_compat' ? cfg.model.verifier_model : '', placeholder: 'a different model, used only to check propositions (optional)' });
    const ggufModel = h('select'), ggufVerifier = h('select');
    const ctxLen = h('input', { type: 'number', min: 0, max: 262144, step: 2048, value: cfg.model.gguf_context, title: '0: sized to the model and this machine' });
    const gpu = h('input', { type: 'number', min: -1, max: 999, value: cfg.model.gguf_gpu_layers, title: '-1: as many as fit; 0: the processor only; a number: at most that many' });
    const threads = h('input', { type: 'number', min: 0, max: 256, value: cfg.model.gguf_threads });
    const found = h('span', { class: 'muted' }), machine = h('p', { class: 'muted' }), placement = h('p');
    const showPlacement = async () => {
      if (backend.value !== 'gguf' || !ggufModel.value) { placement.textContent = ''; return; }
      const q = `gguf_context=${Number(ctxLen.value)}&gguf_gpu_layers=${Number(gpu.value)}&gguf_threads=${Number(threads.value)}`;
      const r = await attempt(() => api('GET', `/v1/config/models/${encodeURIComponent(ggufModel.value)}/placement?${q}`));
      if (r && r !== true) placement.textContent = `If loaded now: ${r.summary}. ${r.notes.join('. ')}`;
    };
    const fillGguf = (list) => {
      const opt = (m) => h('option', { value: m.ref, selected: cfg.model.backend === 'gguf' && cfg.model.model === m.name }, `${m.name} · ${m.size_gb} GB · ${m.location}`);
      fill(ggufModel, list.map(opt));
      fill(ggufVerifier, h('option', { value: '' }, '(none)'), list.map((m) => h('option', { value: m.ref, selected: cfg.model.backend === 'gguf' && cfg.model.verifier_model === m.name }, `${m.name} · ${m.location}`)));
    };
    const findModels = async () => {
      const r = await attempt(() => api('GET', `/v1/config/models?url=${encodeURIComponent(url.value)}`));
      if (!r || r === true) return;
      fillGguf(r.gguf);
      machine.textContent = `This machine: ${r.machine.summary}. ${r.machine.runtime.summary}.` + (r.machine.others_on_the_card ? ` Also using the graphics card: ${r.machine.others_on_the_card}.` : '');
      showPlacement();
      found.textContent = `${r.gguf.length} GGUF model(s) found in ELI's model folders${r.gguf_supported ? '' : ' (llama.cpp is not installed on the server, so they cannot run there)'}. ` +
        (r.models.length ? `The model server offers: ${r.models.join(', ')}.` : 'No model server answered at that address.');
    };
    const ggufBox = h('div', null, h('label', null, 'GGUF model'), ggufModel, h('label', null, 'Verifier (optional, a different model)'), ggufVerifier,
      h('div', { class: 'row' }, h('label', null, 'Context (0: automatic)'), ctxLen, h('label', null, 'Layers on the graphics card (-1: automatic)'), gpu, h('label', null, 'Threads (0: automatic)'), threads), machine, placement);
    [ggufModel, ctxLen, gpu, threads].forEach((el) => el.addEventListener('change', showPlacement));
    const serverBox = h('div', null, h('label', null, 'Address (this machine only)'), url, h('label', null, 'Model'), model, h('label', null, 'Verifier model'), verifier);
    const showBox = () => { ggufBox.hidden = backend.value !== 'gguf'; serverBox.hidden = backend.value !== 'openai_compat'; };
    backend.addEventListener('change', showBox); showBox();
    if (may['config.manage']) setTimeout(findModels, 0);
    const applyModel = async () => {
      const body = { backend: backend.value, url: url.value, model: '', verifier_model: '' };
      if (backend.value === 'gguf') Object.assign(body, { model: ggufModel.value, verifier_model: ggufVerifier.value, gguf_context: Number(ctxLen.value), gguf_gpu_layers: Number(gpu.value), gguf_threads: Number(threads.value) });
      if (backend.value === 'openai_compat') Object.assign(body, { model: model.value, verifier_model: verifier.value });
      if (await attempt(() => api('POST', '/v1/config/model', body), 'Model changed.')) { S.sys = await api('GET', '/v1/system'); render(); }
    };
    return h('div', { class: 'cols' }, h('div', null,
      card('You', facts([['Signed in as', `${S.user.display_name} (${S.user.user_id})`], ['Roles', S.user.roles.map(roleName).join(', ')], ['Second factor', S.user.second_factor ? h('span', { class: 'good' }, 'set up') : h('span', { class: 'warn' }, 'not set up')]]),
        h('div', { class: 'row' }, btn('Change passphrase…', passphrase), S.user.second_factor ? btn('Remove second factor', async () => { if (await attempt(() => api('DELETE', '/v1/auth/second-factor'), 'Removed. Sign in again.')) signOut(); }, 'danger') : btn('Set up a second factor…', async () => { if (await setUpSecondFactor()) show(); }, 'go'), btn('Create an API token…', token))),
      may['user.manage'] ? card('Users and roles', table([['User', (u) => `${u.display_name} (${u.user_id})`], ['Roles', (u) => u.roles.map(roleName).join(', ')], ['State', (u) => (!u.active ? h('span', { class: 'muted' }, 'deactivated') : u.locked_until ? h('span', { class: 'bad' }, 'locked') : !u.has_passphrase ? h('span', { class: 'warn' }, 'no passphrase') : 'active')], ['2nd factor', (u) => (u.second_factor ? 'yes' : 'no')],
        ['', (u) => h('div', { class: 'row' }, btn('Passphrase…', () => setPhrase(u)), u.locked_until ? btn('Unlock', () => person('Unlocked.', (x) => api('POST', `/v1/users/${encodeURIComponent(x.user_id)}/unlock`))(u)) : null,
          u.second_factor ? btn('Reset 2nd factor', () => person('Second factor removed.', (x) => api('DELETE', `/v1/users/${encodeURIComponent(x.user_id)}/second-factor`))(u)) : null,
          u.active ? btn('Deactivate', () => person('Deactivated.', (x) => api('POST', `/v1/users/${encodeURIComponent(x.user_id)}/deactivate`))(u), 'danger') : null)]], users), h('div', { class: 'row' }, btn('Add a user…', add, 'go'))) : null),
    h('div', null, card('Model', h('p', { class: 'muted' }, 'A model is optional. It may only run on this machine: matter content is never sent anywhere else. Changing it is a recorded decision.'), h('p', null, `In use: ${cfg.model.active_model_id}${cfg.model.active_verifier_id !== 'none' ? `; verifier ${cfg.model.active_verifier_id}` : ''}.` + (cfg.model.loaded && cfg.model.loaded.model.summary ? ` Loaded with ${cfg.model.loaded.model.summary}.` : (cfg.model.backend === 'gguf' ? ' It loads at its first use.' : ''))),
      h('label', null, 'Use'), backend, ggufBox, serverBox,
      h('div', { class: 'row' }, btn('Find models', findModels), btn('Apply', applyModel, 'go')), found),
    card('Legal systems installed', table([['Code', 'code'], ['Name', 'name'], ['Family', (j) => words(j.legal_family)], ['Validated by a qualified lawyer', (j) => (j.validated ? h('span', { class: 'good' }, j.validated_by) : h('span', { class: 'warn' }, 'no'))]], S.sys.jurisdictions),
      h('p', { class: 'muted' }, 'A pack describes courts and citation forms only. It contains no rules of law; the law comes from an approved source.')),
    card('Hard offline', h('p', { class: 'muted' }, 'Hard offline makes the computer’s own kernel refuse every network connection from the server: Python code, native code and any program it starts. Nothing running in it can undo it; it lasts until the server stops. The server keeps answering on its own port. Live legal sources and a model server stop working; local GGUF models do not.'),
      h('p', null, net.hard_offline ? `On, enforced by ${net.enforced_by}. ${net.detail}` : 'Off: the network guard denies connections by default and opens one approved host at a time for an approved legal source.'),
      h('div', { class: 'row' }, net.hard_offline ? null : btn('Go hard offline now…', async () => {
        const ok = await ask('Go hard offline', [], 'Go hard offline', 'From now until the server stops, the kernel will refuse every network connection it makes. This cannot be undone while it runs.');
        if (ok && await attempt(() => api('POST', '/v1/network/offline'), 'Hard offline is on.')) { S.sys = await api('GET', '/v1/system'); render(); }
      }, 'danger'), may['config.manage'] ? h('label', { class: 'check' }, h('input', { type: 'checkbox', checked: net.at_every_start, onchange: async (e) => {
        if (!await attempt(() => api('PUT', '/v1/network/at-start', { on: e.target.checked }), 'Recorded under your name.')) e.target.checked = !e.target.checked;
      } }), 'Start hard offline every time') : null)),
    card('This installation', facts([['Version', S.sys.version], ['Network', `${S.sys.network_default} by default`], ['Encrypted connection', cfg.server.tls ? 'yes' : 'no (this machine only)'], ['Second factor', cfg.server.second_factor_required ? 'required' : 'optional'],
      ['Sessions end after', `${cfg.server.idle_minutes} idle minutes, or ${cfg.server.session_hours} hours`], ['Never permitted', cfg.policy.prohibited_actions.map(words).join(', ')]]))));
  };

  start();
})();
