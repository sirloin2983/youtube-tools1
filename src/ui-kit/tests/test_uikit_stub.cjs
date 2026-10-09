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
