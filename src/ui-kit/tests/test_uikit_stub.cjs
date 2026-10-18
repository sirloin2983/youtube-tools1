// Run: node --test src/ui-kit/tests/test_uikit_stub.cjs
// node のテストに渡す UIKit の代わり(uikit_stub.cjs)が、本物の ui-kit.js と食い違っていないか(ui-kit v24)
const assert = require('node:assert/strict');
const vm = require('node:vm');
const { test } = require('node:test');
const { makeUIKit, withUIKit, realNames, FALLBACK } = require('./uikit_stub.cjs');

test('every top-level name of the real window.UIKit is known to the stub (explicit or a deliberate no-op)', () => {
  const kit = makeUIKit(), names = realNames();
  assert.ok(names.length >= 30 && names.includes('http') && names.includes('copy'), 'reads the real names: ' + names.join(','));
  const explicit = Object.keys(kit);
  const unknown = names.filter(n => !explicit.includes(n) && !FALLBACK.includes(n));
  assert.deepEqual(unknown, [], 'add these to uikit_stub.cjs (kit or FALLBACK)');
  assert.deepEqual(FALLBACK.filter(n => !names.includes(n)), [], 'FALLBACK names that the real UIKit no longer has');
  assert.ok(kit.version >= 24, 'version is read from the real ui-kit.js: ' + kit.version);
});

test('esc and fmt are the real ones (cut out of ui-kit.js)', () => {
  const kit = makeUIKit();
  assert.equal(kit.esc('<a href="x">&\'</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
  assert.equal(kit.esc(null), '');
  assert.equal(kit.fmt.dur(59.6), '1:00');
  assert.equal(kit.fmt.dur(59.6, { floor: true }), '0:59');
  assert.equal(kit.fmt.dur(83.44, { tenths: true }), '1:23.4');
  assert.equal(kit.fmt.day(new Date(2020, 0, 2, 3, 4).getTime()), '2020/1/2');
});

test('calls are recorded; overrides (also nested names) replace the default; unknown names are no-ops that never look like promises', async () => {
  const notes = [];
  const kit = makeUIKit({ toast: m => notes.push(m), 'dialog.confirm': () => Promise.resolve(false) });
  kit.toast('a', { kind: 'ok' });
  assert.deepEqual(notes, ['a']);
  assert.deepEqual(kit.called('toast'), [['a', { kind: 'ok' }]]);
  assert.equal(await kit.dialog.confirm({ title: 't' }), false);
  assert.equal(await kit.dialog.alert({}), undefined);
  assert.equal(kit.liveBadge.refresh(1), undefined);
  assert.deepEqual(kit.called('liveBadge.refresh'), [[1]]);
  assert.equal(await kit.liveBadge, kit.liveBadge, 'await on an unknown part does not hang');
  assert.equal(await kit.copy('x'), true);
  assert.equal(kit.icon('play'), '');
  await assert.rejects(kit.http('api/x'), e => e.code === 'stub');
  await assert.rejects(kit.homeApi('api/x'), e => e.code === 'stub');
  assert.equal(kit.homeUrl('/api/ytt/prefs'), '/api/ytt/prefs');
});

test('life handlers can be fired; withUIKit fills context.UIKit and window.UIKit without dropping what is there', () => {
  const kit = makeUIKit(), seen = [];
  kit.life.onLeave(r => seen.push('leave:' + r));
  kit.life.onReturn(r => seen.push('return:' + r));
  kit.fire('leave', 'hidden'); kit.fire('return', 'visible');
  assert.deepEqual(seen, ['leave:hidden', 'return:visible']);
  const ctx = withUIKit({ window: { scrollY: 3 } }, kit);
  assert.equal(ctx.UIKit, kit);
  assert.equal(ctx.window.UIKit, kit);
  assert.equal(ctx.window.scrollY, 3);
  const own = { win: { isApp: () => true } };
  assert.equal(withUIKit({ window: { UIKit: own } }).window.UIKit, own, 'a window.UIKit the test made itself stays');
  vm.createContext(ctx);
  assert.equal(vm.runInContext("UIKit.toast('x'); window.UIKit === UIKit && UIKit.esc('<')", ctx), '&lt;', 'works inside a vm context');
});

/* ---- ui-kit.js の http / settingsForm を本物から切り出して動かす ---- */
const fs = require('node:fs');
const path = require('node:path');
const KIT_TEXT = fs.readFileSync(path.join(__dirname, '..', 'ui-kit.js'), 'utf8').replace(/\r\n/g, '\n');
function slice(start, end) {
  const a = KIT_TEXT.indexOf(start), b = KIT_TEXT.indexOf(end, a);
  assert.ok(a >= 0 && b > a, 'marker not found: ' + start);
  return KIT_TEXT.slice(a, b);
}

test('http: 403 {"error":"token"} shows the "reopen" notice once (and only for that error)', async () => {
  const toasts = []; let reloads = 0, status = 403, body = { error: 'token', message: 'm' };
  const ctx = {
    toastFn: (m, o) => { toasts.push([m, o]); }, token: () => 'tk', location: { href: 'http://x/a/', origin: 'http://x', reload: () => { reloads++; } },
    URL, AbortController, setTimeout, clearTimeout, Promise, JSON,
    fetch: () => Promise.resolve({ ok: false, status, json: () => Promise.resolve(body) }),
  };
  vm.createContext(ctx);
  vm.runInContext(slice('  var HTTP_OFFLINE', '  /* 入口(ホーム)の API の場所') + '\nthis.http = http; this.tokenStale = tokenStale;', ctx);
  await assert.rejects(ctx.http('api/x', { body: {} }), e => e.status === 403 && e.code === 'token');
  await assert.rejects(ctx.http('api/x', { body: {} }), e => e.code === 'token');
  assert.equal(toasts.length, 1, 'only once');
  assert.match(toasts[0][0], /起動し直されました/);
  assert.equal(toasts[0][1].action.label, '開き直す');
  assert.equal(reloads, 0);
  toasts[0][1].action.fn();
  assert.equal(reloads, 1);
  status = 403; body = { error: 'forbidden' };
  const t0 = toasts.length;
  await assert.rejects(ctx.http('api/x', { body: {} }));
  status = 409; body = { error: 'token' };
  await assert.rejects(ctx.http('api/x', { body: {} }));
  assert.equal(toasts.length, t0);
});

/* 最小の偽 DOM(settingsForm の描画に要る分だけ) */
function fakeDom() {
  const doc = { activeElement: null };
  function el(tag) {
    const e = {
      tagName: tag.toUpperCase(), children: [], attrs: {}, listeners: {}, _cls: new Set(), value: '', checked: false, hidden: false, disabled: false, style: {}, dataset: {},
      set className(v) { this._cls = new Set(String(v).split(/\s+/).filter(Boolean)); }, get className() { return [...this._cls].join(' '); },
      classList: null, appendChild(c) { this.children.push(c); return c; }, setAttribute(k, v) { this.attrs[k] = v; }, getAttribute(k) { return this.attrs[k]; },
      addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }, dispatchEvent() {},
      set textContent(v) { this._t = v; }, get textContent() { return this._t || ''; },
    };
    e.classList = { add: c => e._cls.add(c), toggle: (c, on) => { on ? e._cls.add(c) : e._cls.delete(c); }, contains: c => e._cls.has(c) };
    e.fire = (t) => (e.listeners[t] || []).forEach(f => f({}));
    return e;
  }
  doc.createElement = el;
  return doc;
}
function mountForm(items, store, setImpl) {
  const document = fakeDom();
  const ctx = { document, CustomEvent: function (n, o) { this.n = n; this.detail = o && o.detail; }, setTimeout, clearTimeout, Promise, JSON, Math, Number, String, isFinite, RegExp };
  vm.createContext(ctx);
  vm.runInContext(slice('  function setFormId(', '  function settingsFormFilter(') + '\nthis.render = settingsFormRender;', ctx);
  const host = document.createElement('div');
  const io = { get: k => store[k], set: (k, v) => setImpl(k, v) };
  const form = ctx.render(host, { id: 'g', items }, io);
  const sec = host.children[0];
  const rowOf = k => sec.children.find(r => r.attrs && r.attrs['data-ui-set-key'] === k);
  const ctl = k => rowOf(k).children[0].children[1].children[0];
  return { document, form, ctl };
}

test('settingsForm: a save finishing does not wipe a text field that is being typed in', async () => {
  const store = { engine: 'a', model: '' };
  const m = mountForm([{ key: 'engine', type: 'enum', options: [['a', 'A'], ['b', 'B']], 'default': 'a' }, { key: 'model', type: 'text', 'default': '' }],
    store, (k, v) => { store[k] = v; return Promise.resolve(); });
  const engine = m.ctl('engine'), model = m.ctl('model');
  engine.value = 'b'; model.value = 'whisper-lar'; m.document.activeElement = model;   // typing in the model field
  engine.fire('change');
  await new Promise(r => setTimeout(r, 0));
  assert.equal(store.engine, 'b');
  assert.equal(model.value, 'whisper-lar', 'typed text kept');
  m.document.activeElement = null;
  m.form.refresh();
  assert.equal(model.value, '', 'a normal refresh (no focus) still writes the stored value');
});

test('settingsForm: another save finishing does not repaint a select whose own save is still on its way', async () => {
  const store = { engine: 'a', model: 'm1' }, wait = {};
  const m = mountForm([{ key: 'engine', type: 'enum', options: [['a', 'A'], ['b', 'B']], 'default': 'a' }, { key: 'model', type: 'enum', options: [['m1', '1'], ['m2', '2']], 'default': 'm1' }],
    store, (k, v) => new Promise(r => { wait[k] = () => { store[k] = v; r(); }; }));
  const engine = m.ctl('engine'), model = m.ctl('model');
  engine.value = 'b'; engine.fire('change');
  model.value = 'm2'; model.fire('change');   // the store still says m1 until the model save answers
  await new Promise(r => setTimeout(r, 0));
  wait.engine(); await new Promise(r => setTimeout(r, 0));
  assert.equal(model.value, 'm2', 'the chosen model stays while its save is on its way');
  wait.model(); await new Promise(r => setTimeout(r, 0));
  assert.equal(store.model, 'm2');
  assert.equal(model.value, 'm2');
});

test('settingsForm: a failed save puts the stored value back even in a focused field', async () => {
  const store = { model: 'old' };
  const m = mountForm([{ key: 'model', type: 'text', 'default': '' }], store, () => Promise.reject(new Error('no')));
  const model = m.ctl('model');
  model.value = 'new'; m.document.activeElement = model;
  model.fire('change');
  await new Promise(r => setTimeout(r, 0));
  assert.equal(model.value, 'old');
});
