// node のテスト(画面の JS の関数を vm で切り出して動かすもの)に渡す、UIKit の代わり(ui-kit v24。2026-10-09)。
// 画面の JS から `window.UIKit &&` の予備の経路を外すと、切り出した関数は UIKit を直接呼ぶので、テストの環境(context)にこれを入れる。
//
//   const { makeUIKit, withUIKit } = require(path.join(__dirname, '..', '..', 'ui-kit', 'tests', 'uikit_stub.cjs'));
//   const kit = makeUIKit({ toast: msg => notes.push(msg) });     // 差し替えたい部品だけ渡す(入れ子は 'dialog.confirm' のように . でつないだ名前でも)
//   const context = withUIKit({ S, ... }, kit);                   // context.UIKit と context.window.UIKit に入れる(window が既にあればそれに足す)
//   kit.calls        … 呼ばれた部品の [名前, 引数] の並び。kit.called('toast') でその名前の引数だけ
//   kit.fire('leave', 'hidden') / kit.fire('return', 'visible') … UIKit.life.onLeave / onReturn に渡された関数を呼ぶ
//
// - 文字の部品(esc・fmt)は本物の ui-kit.js から切り出して使う(写しを持たない = 本物とずれない)
// - Promise を返す部品(dialog・prefs・copy・autorun.start など)は Promise を返す。http・homeApi は差し替えないと reject(code 'stub')
//   = テストが知らないうちに API を呼んでいたら分かる
// - ここに無い名前(新しい部品)は「何もしない関数」として返す(呼ばれたことは calls に残る)。then は返さない(await で止まらないように)
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const KIT_SRC = fs.readFileSync(path.join(__dirname, '..', 'ui-kit.js'), 'utf8').replace(/\r\n/g, '\n');
function kitSlice(start, end) {
  const a = KIT_SRC.indexOf(start), b = KIT_SRC.indexOf(end, a);
  if (a < 0 || b <= a) throw new Error('ui-kit.js の切り出しの印が見つかりません: ' + start);
  return KIT_SRC.slice(a, b);
}
/* 本物の esc と fmt(ui-kit.js の「ツール間のリンク」の esc の 1 行と「表示の書式」の節) */
function realText() {
  const ctx = {};
  vm.createContext(ctx);
  vm.runInContext(kitSlice('  function esc(', '\n', 0) + '\n' + kitSlice('  function pad2(', '  /* ---- 入口の共通の API') + '\nthis.esc = esc; this.fmt = fmt;', ctx);
  return { esc: ctx.esc, fmt: ctx.fmt };
}

/* window.UIKit = { … } の一番上の名前(ui-kit.js の最後)。テストが「代わりが本物の名前を全部知っているか」を確かめるのに使う */
function realNames() {
  const lit = kitSlice('window.UIKit = {', '};');
  return [...lit.slice('window.UIKit = {'.length).matchAll(/(?:^|[,{]\s*)([A-Za-z_$][\w$]*)\s*:/g)].map(m => m[1]);
}

/* 本物にあって、ここでは「何もしない関数」(Proxy)で足りる名前。本物に名前を足したら、ここか下の kit のどちらかに足す
   (test_uikit_stub.cjs が確かめる。Promise や値を返す部品なら kit に書く) */
const FALLBACK = ['sound', 'theme', 'portal', 'streamer', 'appnav', 'drawer', 'keybar', 'settings', 'keymap', 'packLoud', 'restart', 'hide', 'liveBadge'];

function makeUIKit(overrides = {}) {
  const calls = [], handlers = { leave: [], return: [] };
  const rec = (name, impl) => function (...args) { calls.push([name, args]); return impl ? impl.apply(this, args) : undefined; };
  function noop(name) {
    const f = rec(name);
    return new Proxy(f, {
      get(t, k) {
        if (k in t || typeof k === 'symbol') return t[k];
        if (k === 'then') return undefined;
        return (t[k] = noop(name + '.' + String(k)));
      },
    });
  }
  const stubErr = name => Object.assign(new Error('テストで UIKit.' + name + ' を差し替えてください'), { code: 'stub', status: 0, body: {}, data: {}, reason: '', detail: '' });
  const { esc, fmt } = realText();
  const iconFn = rec('icon', () => '');
  iconFn.fill = rec('icon.fill');
  iconFn.names = rec('icon.names', () => []);
  const kit = {
    version: Number((/window\.UIKit = \{ version: (\d+)/.exec(KIT_SRC) || [])[1]) || 0,   // 本物の版
    esc, fmt,
    toast: rec('toast', () => ({ close() {}, el: null })),
    dialog: {
      confirm: rec('dialog.confirm', () => Promise.resolve(true)),
      alert: rec('dialog.alert', () => Promise.resolve()),
      choose: rec('dialog.choose', () => Promise.resolve(null)),
    },
    confirmTwice: rec('confirmTwice'),
    menuOff: rec('menuOff'),
    life: {
      onLeave: rec('life.onLeave', fn => { handlers.leave.push(fn); }),
      onReturn: rec('life.onReturn', fn => { handlers.return.push(fn); }),
      isAway: rec('life.isAway', () => false),
    },
    report: rec('report', () => false),
    win: { isApp: rec('win.isApp', () => false), open: rec('win.open', () => Promise.resolve()) },
    icon: iconFn,
    http: rec('http', () => Promise.reject(stubErr('http'))),
    homeApi: rec('homeApi', () => Promise.reject(stubErr('homeApi'))),
    homeUrl: rec('homeUrl', p => '/' + String(p == null ? '' : p).replace(/^\/+/, '')),
    copy: rec('copy', () => Promise.resolve(true)),
    keys: {
      isTyping: rec('keys.isTyping', () => false),
      playback: rec('keys.playback', () => false),
      keyText: rec('keys.keyText', k => String(k || '')),
    },
    tools: {
      paths: {},
      base: rec('tools.base', () => '/'),
      url: rec('tools.url', () => ''),
      mounted: rec('tools.mounted', () => false),
      render: rec('tools.render'),
      setPaths: rec('tools.setPaths'),
    },
    prefs: {
      get: rec('prefs.get', () => Promise.resolve({})),
      patch: rec('prefs.patch', () => Promise.resolve()),
      remember: rec('prefs.remember', () => Promise.resolve(null)),
      available: rec('prefs.available', () => false),
    },
    autorun: {
      start: rec('autorun.start', () => Promise.resolve(null)),
      panel: rec('autorun.panel', () => null),
      load: rec('autorun.load', () => Promise.resolve(null)),
      state: rec('autorun.state', () => null),
      watch: rec('autorun.watch'),
      stepLabel: rec('autorun.stepLabel', s => (s && (s.stateLabel || s.state)) || ''),
      runLabel: rec('autorun.runLabel', r => (r && (r.stateLabel || r.state)) || ''),
    },
    timebox: {
      format: rec('timebox.format', t => fmt.dur(t)),
      parse: rec('timebox.parse', () => null),
      attach: rec('timebox.attach'), attachAll: rec('timebox.attachAll'), get: rec('timebox.get', () => null), set: rec('timebox.set'),
    },
  };
  for (const [name, value] of Object.entries(overrides)) {   // 'dialog.confirm' のような入れ子の名前も
    const parts = name.split('.'), last = parts.pop();
    let o = kit;
    for (const p of parts) o = o[p] = o[p] && typeof o[p] === 'object' || typeof o[p] === 'function' ? o[p] : {};
    o[last] = typeof value === 'function' ? rec(name, value) : value;
  }
  const top = new Proxy(kit, {
    get(t, k) {
      if (k in t || typeof k === 'symbol') return t[k];
      if (k === 'then' || k === 'calls' || k === 'called' || k === 'fire') return undefined;
      return (t[k] = noop(String(k)));
    },
  });
  Object.defineProperty(kit, 'calls', { value: calls });
  Object.defineProperty(kit, 'called', { value: name => calls.filter(c => c[0] === name).map(c => c[1]) });
  Object.defineProperty(kit, 'fire', { value: (kind, reason) => (handlers[kind] || []).forEach(fn => fn(reason)) });
  return top;
}

/* context に UIKit と window.UIKit を入れて返す(context に UIKit・window.UIKit が既にあれば、そちらを残す) */
function withUIKit(context, kit = makeUIKit()) {
  if (!('UIKit' in context)) context.UIKit = kit;
  if (!context.window) context.window = { UIKit: context.UIKit };
  else if (!('UIKit' in context.window)) context.window.UIKit = context.UIKit;
  return context;
}

module.exports = { makeUIKit, withUIKit, realNames, FALLBACK };
