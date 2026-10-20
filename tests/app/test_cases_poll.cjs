// Run: node --test src/app/tests/test_cases_poll.cjs
// 案件の画面(src/app/ui/cases/cases.js)の load と poll を vm で切り出し、status の応答を遅らせて試す。
// 状態確認の途中で同じ案件を load(true) で読み直しても、次の問い合わせは予約される(自動の更新が止まらない)。古い案件への応答は当てない。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '..', 'ui', 'cases', 'cases.js'), 'utf8').replace(/\r\n/g, '\n');
const a = source.indexOf('  function load(keep) {'), b = source.indexOf('  /* ---- キー(keydown');
assert.ok(a >= 0 && b > a, 'load/schedule/poll boundaries must exist');
const code = source.slice(a, b);

const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness() {
  const S = { want: { c: 'A', d: '', m: '', tab: '' }, kase: null, sw: 0, items: [], sel: '', tab: '', status: { rev: null, all: [] },
    timer: 0, pollMs: 0, loading: false, checkAt: Date.now(), noCaseFilter: false, panel: null };
  const timers = [], statusReqs = [];
  let cases = { A: { id: 'A', root: 'rA' }, B: { id: 'B', root: 'rB' } }, away = false;
  const context = {
    S, Date, Array, Promise, Error, encodeURIComponent, document: { body: { setAttribute() {} } },
    POLL_ACTIVE: 2000, POLL_IDLE: 15000, CHECK_EVERY_MS: 14000, ACTIVE: { queued: 1, running: 1 },
    UIKit: { life: { isAway: () => away }, toast() {} },
    setTimeout: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length; },
    clearTimeout: id => { if (id && timers[id - 1]) timers[id - 1].live = false; },
    $: () => ({ hidden: false, innerHTML: '', textContent: '' }),
    api: (tool, p) => {
      if (p.indexOf('api/flow/status') === 0) { const d = deferred(); statusReqs.push(d); return d.promise; }
      return Promise.resolve({ cases: Object.values(cases).map(c => Object.assign({}, c)) });   // 毎回新しいオブジェクト
    },
    fetchCases: null, allCases: j => j.cases, pickCase: (list, w) => list.filter(c => c.id === w.c)[0] || null,
    itemsOf: () => [{ key: 'k', docId: '' }], curItem: () => ({ docId: '', markId: '' }), defaultKey: () => 'k',
    renderHead() {}, renderRail() {}, renderTabs() {}, renderNext() {}, showPanel() {}, select() {}, unmountPanel() {}, renderKeybar() {},
    writeUrl() {}, showEmpty() {}, showFail() {}, emptyBox: () => '', rememberCase() {}, loadCheckCount() {}, mine: () => true,
    HOME_BTN: ''
  };
  vm.createContext(context);
  vm.runInContext(code + '\nthis.load = load; this.poll = poll;', context);
  vm.runInContext('fetchCases = function (w) { return api("home", "api/cases"); };', context);   // 一覧の取得は常に新しい物を返す
  return { S, context, timers, statusReqs, setAway: v => { away = v; }, liveTimers: () => timers.filter(t => t.live) };
}

test('same case reloaded while a status poll is in flight still schedules the next poll', async () => {
  const h = harness();
  await h.context.load(false);
  await tick();
  assert.equal(h.statusReqs.length, 1, 'load starts the first poll');
  const first = h.S.kase;
  await h.context.load(true);                       // 校正済みの数の更新・パック完成のあとの ctx.reload() と同じ
  assert.notEqual(h.S.kase, first, 'reload puts a new object for the same case');
  assert.equal(h.S.sw, 1, 'the switch number does not change for the same case');
  h.statusReqs[0].resolve({ rev: 1, jobs: [] });
  await tick();
  assert.equal(h.liveTimers().length, 1, 'the next poll is scheduled');
  assert.equal(h.S.timer > 0, true);
  // 失敗の返事の枝: 読み直しのあと問い合わせが失敗しても 15 秒後に確かめ続ける
  const f = harness();
  await f.context.load(false);
  await tick();
  await f.context.load(true);
  f.statusReqs[0].reject(new Error('down'));
  await tick();
  assert.equal(f.liveTimers().length, 1);
  assert.equal(f.liveTimers()[0].ms, 15000);
});

test('stale reply for another case is ignored', async () => {
  const h = harness();
  await h.context.load(false);
  await tick();
  h.S.want = { c: 'B', d: '', m: '', tab: '' };
  await h.context.load(false);                      // 別の案件へ(新しい poll が始まる)
  await tick();
  assert.equal(h.S.sw, 2);
  assert.equal(h.statusReqs.length, 2);
  h.statusReqs[0].resolve({ rev: 9, jobs: [] });    // A への古い応答
  await tick();
  assert.equal(h.S.status.rev, null, 'stale reply is not applied');
  assert.equal(h.liveTimers().length, 0, 'stale reply does not schedule');
  h.statusReqs[1].resolve({ rev: 2, jobs: [] });
  await tick();
  assert.equal(h.S.status.rev, 2);
  assert.equal(h.liveTimers().length, 1);
});

test('reply after the case disappeared does not schedule', async () => {
  const h = harness();
  await h.context.load(false);
  await tick();
  h.S.kase = null; h.S.sw++;
  h.statusReqs[0].resolve({ rev: 1, jobs: [] });
  await tick();
  assert.equal(h.liveTimers().length, 0);
});
