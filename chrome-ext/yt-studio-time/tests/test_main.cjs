// main.js の純粋な部分(応答の読み取り・時刻の選び方・書式)の確認。node --test chrome-ext/yt-studio-time/tests/test_main.cjs
const test = require('node:test');
const assert = require('node:assert');
const path = require('path');
const m = require(path.join(__dirname, '..', 'main.js'));
const p2 = n => String(n).padStart(2, '0');

test('harvest: 入れ子の応答から videoId と秒を拾う(秒は文字列でも数でも)', () => {
  m.times.clear();
  const n = m.harvest({
    videos: [
      { videoId: 'abcdefghijk', timePublishedSeconds: '1759640580', timeCreatedSeconds: '1759640000', title: 'x' },
      { videoId: 'zzzzzzzzzzz', title: '時刻が無い' },
    ],
    other: { nested: [{ videoId: 'lmnopqrstuv', timeCreatedSeconds: 1759600000 }] },
  });
  assert.strictEqual(n, 2);
  assert.deepStrictEqual(m.times.get('abcdefghijk'), { published: 1759640580, created: 1759640000 });
  assert.deepStrictEqual(m.times.get('lmnopqrstuv'), { published: null, created: 1759600000 });
  assert.strictEqual(m.times.has('zzzzzzzzzzz'), false);
});

test('harvest: 0 や数でない秒は無いものとして扱い、循環しても止まる', () => {
  m.times.clear();
  assert.strictEqual(m.harvest({ videoId: 'abcdefghijk', timePublishedSeconds: '0', timeCreatedSeconds: 'abc' }), 0);
  const a = { videoId: 'abcdefghijk', timePublishedSeconds: 10 };
  a.self = a; a.list = [a, { back: a }];
  assert.strictEqual(m.harvest(a), 1);
  assert.strictEqual(m.harvest(null), 0);
  assert.strictEqual(m.harvest('text'), 0);
});

test('harvest: 同じ videoId は新しい応答で置き換わる', () => {
  m.times.clear();
  m.harvest({ videoId: 'abcdefghijk', timePublishedSeconds: 100 });
  m.harvest({ videoId: 'abcdefghijk', timePublishedSeconds: 200, timeCreatedSeconds: 50 });
  assert.deepStrictEqual(m.times.get('abcdefghijk'), { published: 200, created: 50 });
});

test('choose: 公開日なら公開の時刻、アップロード日ならアップロードの時刻、片方しか無ければそれ', () => {
  const t = { published: 200, created: 100 };
  assert.strictEqual(m.choose(t, '2026/10/05 公開日'), 200);
  assert.strictEqual(m.choose(t, '2026/10/05 アップロード日'), 100);
  assert.strictEqual(m.choose(t, 'Oct 5, 2026 Uploaded'), 100);
  assert.strictEqual(m.choose({ published: null, created: 100 }, '公開日'), 100);
  assert.strictEqual(m.choose({ published: 200, created: null }, 'アップロード日'), 200);
  assert.strictEqual(m.choose(null, '公開日'), null);
});

test('fmtTime / fmtFull / tooltip: ローカル時刻で 0 埋め', () => {
  const sec = 1759640580;
  const d = new Date(sec * 1000);
  const hm = p2(d.getHours()) + ':' + p2(d.getMinutes());
  assert.strictEqual(m.fmtTime(sec), hm);
  assert.strictEqual(m.fmtFull(sec), d.getFullYear() + '/' + p2(d.getMonth() + 1) + '/' + p2(d.getDate()) + ' ' + hm + ':' + p2(d.getSeconds()));
  assert.strictEqual(m.tooltip({ published: sec, created: null }), '公開 ' + m.fmtFull(sec));
  assert.strictEqual(m.tooltip({ published: sec, created: sec }), '公開 ' + m.fmtFull(sec) + ' / アップロード ' + m.fmtFull(sec));
});

test('videoIdFromHref: 行のリンクから 11 文字の id', () => {
  assert.strictEqual(m.videoIdFromHref('/video/abc-DEF_123/edit'), 'abc-DEF_123');
  assert.strictEqual(m.videoIdFromHref('https://studio.youtube.com/video/abc-DEF_123/analytics/tab-overview'), 'abc-DEF_123');
  assert.strictEqual(m.videoIdFromHref('/video/abc-DEF_123'), 'abc-DEF_123');
  assert.strictEqual(m.videoIdFromHref('/video/tooshort/edit'), null);
  assert.strictEqual(m.videoIdFromHref('/channel/UCxxxx/videos/short'), null);
  assert.strictEqual(m.videoIdFromHref(null), null);
});

test('API_RE / DATE_RE: 内部 API の URL と、日付の欄の文字(日本語・英語)', () => {
  assert.ok(m.API_RE.test('https://studio.youtube.com/youtubei/v1/creator/list_creator_videos?alt=json&key=x'));
  assert.ok(m.API_RE.test('/youtubei/v1/creator/get_creator_videos'));
  assert.ok(!m.API_RE.test('https://studio.youtube.com/youtubei/v1/creator/get_creator_channels'));
  assert.ok(m.DATE_RE.test('2026/10/05'));
  assert.ok(m.DATE_RE.test('2026-10-05'));
  assert.ok(m.DATE_RE.test('Oct 5, 2026'));
  assert.ok(m.DATE_RE.test('10/5/2026'));
  assert.ok(!m.DATE_RE.test('公開日'));
  assert.ok(!m.DATE_RE.test('115,020'));
});
