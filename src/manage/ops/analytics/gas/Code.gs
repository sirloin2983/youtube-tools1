/**
 * Youtube分析 連携 (Google Apps Script)
 *
 * 何のためのプロジェクトか
 *   PC のローカルのツール(src/analytics/。Python)が YouTube チャンネルの日次分析をして LINE に送る形にするための、
 *   Google 側の窓口。PC は iPhone から直接データを受け取れないので、Drive を間に挟む。
 *     (1) iPhone のブックマーク → 既存の「Youtube日次」プロジェクトが Drive の raw/<日付>.json に書く(このプロジェクトは触らない)
 *         → このプロジェクトが、その raw をツールに渡す(list / get)
 *     (2) ツールが作ったレポートを受け取って Drive の reports/ に保存し、LINE に送る(report)
 *     (3) タップ忘れ・PC が動いていないときに LINE で知らせる(watchdog。1 時間ごとのトリガー)
 *   ウェブアプリとしてデプロイする(実行ユーザー = 自分 / アクセスできるユーザー = 全員)。
 *   ツールは Google のログインなしで HTTPS で呼ぶので、すべての操作に合言葉(ANALYTICS_SECRET)が要る。
 *
 * 約束(ツール側の Python と同じ形。変えない)
 *   すべて POST <ウェブアプリの URL>。本文は JSON 文字列 {"secret": "...", "op": "...", ...}
 *   (Content-Type は text/plain で来る想定。e.postData.contents を JSON.parse する)。
 *   応答は JSON。失敗は {"ok": false, "error": "<英小文字の識別子>", "message": "<日本語>"}
 *   (HTTP の番号は 200 のまま。Apps Script は番号を選べない)。
 *     op "ping"    → {ok, version, now, folder}  folder = DRIVE_FOLDER_ID のフォルダが開けるか
 *     op "list"    since(ISO か null) → {ok, files: [{id, name, updated, size}]}
 *                  raw フォルダの <YYYY-MM-DD>.json だけ(_daily は除く)。updated が since より後。昇順・最大 60 件
 *     op "get"     id → {ok, id, name, updated, content}  raw フォルダの中のファイルだけ。違えば error "not_found"
 *     op "report"  kind(daily|weekly|monthly)・date(YYYY-MM-DD)・text(LINE の文面 1〜4500 字)・
 *                  html(レポートのページ 1〜1,500,000 字)・source(任意の小さな object)・notify(省略 = true)
 *                  → reports/<date>_<kind>.html に保存(同名は中身を置き換える)、閲覧用の鍵を作り、
 *                    notify なら LINE に「文面 + 詳しく: <URL>?v=<鍵>」を送る
 *                  → {ok, url, sent}。LINE が失敗したら {ok: false, error: "line", message, url}(保存は済む)
 *     op "status"  → {ok, sent: {daily, weekly, monthly: {date, at} か null}, latestRaw: {name, updated} か null}
 *   GET ?v=<鍵> → その鍵のレポートの HTML(鍵が無い・違うときは短い日本語)。v なしは "ok"
 *   error の識別子: secret / bad_request / bad_op / not_found / busy / line / internal
 *
 * スクリプト プロパティ(プロジェクトの設定 → スクリプト プロパティ。値はコードにもログにも出さない)
 *   ANALYTICS_SECRET            合言葉(32 文字以上。makeSecret() が作る)
 *   DRIVE_FOLDER_ID             Drive のフォルダ「Youtube日次」の ID(中に raw/ があり、reports/ を作る)
 *   LINE_CHANNEL_ACCESS_TOKEN   LINE Messaging API のチャネル アクセス トークン(必須)
 *   LINE_USER_ID                知らせ・レポートの送り先(必須)
 *   LINE_SHARE_IDS              任意。カンマ区切り。レポートだけ一緒に送る(知らせは LINE_USER_ID だけ)
 *   (自動で作られるもの) VIEW_<鍵>・LAST_VIEW_<kind>_<date>・SENT_<kind>_<date>・NOTIFIED_<種類>_<日付>
 *                        120 日より前の日付のものは watchdog が消す
 *
 * 初回の手順(詳しくは README.txt)
 *   1. 新しいプロジェクトを作り、このコードを貼る。スクリプト プロパティに DRIVE_FOLDER_ID・LINE_* を入れる
 *   2. makeSecret() を実行して合言葉を作る(ログに出る。ツールの画面に貼る)
 *   3. checkSetup()・testLine() を実行して確かめる
 *   4. ウェブアプリとしてデプロイし、URL(/exec で終わる)をツールの画面に貼る
 *   5. setupTriggers() を実行して見張り(watchdog)を動かす
 *   コードを直したら「デプロイを管理」→ 編集 → 新しいバージョン(URL を変えないため)
 */

const VERSION_ = '1';
const TZ_ = 'Asia/Tokyo';
const RAW_FOLDER_NAME_ = 'raw';
const REPORTS_FOLDER_NAME_ = 'reports';
const RAW_NAME_RE_ = /^\d{4}-\d{2}-\d{2}\.json$/;
const DATE_RE_ = /^\d{4}-\d{2}-\d{2}$/;
const VIEW_KEY_RE_ = /^[A-Za-z0-9-]{32,100}$/;
const KINDS_ = ['daily', 'weekly', 'monthly'];
const SECRET_MIN_LEN_ = 32;
const LIST_MAX_ = 60;
const LINE_TEXT_MAX_ = 5000;
const REPORT_TEXT_MAX_ = 4500;
const REPORT_HTML_MAX_ = 1500000;
const KEEP_DAYS_ = 120;
const LINE_PUSH_URL_ = 'https://api.line.me/v2/bot/message/push';

// ───────────────────────── 入り口 ─────────────────────────

function doPost(e) {
  try {
    const req = parseRequest_(e);
    checkSecret_(req.secret);
    switch (req.op) {
      case 'ping': return jsonOut_(opPing_());
      case 'list': return jsonOut_(opList_(req));
      case 'get': return jsonOut_(opGet_(req));
      case 'report': return jsonOut_(opReport_(req));
      case 'status': return jsonOut_(opStatus_());
      default: throw fail_('bad_op', '未対応の op です');
    }
  } catch (err) {
    return jsonOut_(errorBody_(err));
  }
}

function doGet(e) {
  const v = e && e.parameter && e.parameter.v;
  if (!v) return ContentService.createTextOutput('ok');
  if (!VIEW_KEY_RE_.test(String(v))) return notFoundPage_();
  try {
    const fileId = props_().getProperty('VIEW_' + v);
    if (!fileId) return notFoundPage_();
    const file = DriveApp.getFileById(fileId);
    if (file.isTrashed()) return notFoundPage_();
    return HtmlService.createHtmlOutput(file.getBlob().getDataAsString('UTF-8'))
      .setTitle('Youtube分析')
      .addMetaTag('viewport', 'width=device-width, initial-scale=1');
  } catch (err) {
    console.error('doGet: ' + errText_(err));
    return notFoundPage_();
  }
}

function notFoundPage_() {
  return HtmlService.createHtmlOutput('<p>見つかりません。</p>')
    .setTitle('Youtube分析')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

// ───────────────────────── 要求の読み取りと合言葉 ─────────────────────────

function parseRequest_(e) {
  const raw = e && e.postData && e.postData.contents;
  if (!raw) throw fail_('bad_request', '本文がありません');
  let req;
  try {
    req = JSON.parse(raw);
  } catch (err) {
    throw fail_('bad_request', '本文が JSON ではありません');
  }
  if (!req || typeof req !== 'object' || Array.isArray(req)) {
    throw fail_('bad_request', '本文は JSON の object にしてください');
  }
  return req;
}

function checkSecret_(given) {
  const expected = props_().getProperty('ANALYTICS_SECRET') || '';
  if (expected.length < SECRET_MIN_LEN_) {
    throw fail_('secret', '合言葉が未設定か短すぎます。makeSecret() を実行してください');
  }
  if (typeof given !== 'string' || !constantTimeEquals_(given, expected)) {
    throw fail_('secret', '合言葉が違います');
  }
}

// 長さと全文字を最後まで比べる(途中で抜けない)
function constantTimeEquals_(a, b) {
  let diff = a.length ^ b.length;
  const n = Math.max(a.length, b.length);
  for (let i = 0; i < n; i++) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return diff === 0;
}

// ───────────────────────── op ─────────────────────────

function opPing_() {
  return { ok: true, version: VERSION_, now: new Date().toISOString(), folder: !!openRootFolder_() };
}

function opList_(req) {
  let sinceMs = null;
  if (req.since !== undefined && req.since !== null) {
    sinceMs = new Date(req.since).getTime();
    if (isNaN(sinceMs)) throw fail_('bad_request', 'since が日時として読めません');
  }
  const raw = findRawFolder_();
  const files = [];
  if (raw) {
    const it = raw.getFiles();
    while (it.hasNext()) {
      const f = it.next();
      if (!RAW_NAME_RE_.test(f.getName()) || f.isTrashed()) continue;
      const updated = f.getLastUpdated();
      if (sinceMs !== null && updated.getTime() <= sinceMs) continue;
      files.push({ id: f.getId(), name: f.getName(), updated: updated.toISOString(), size: f.getSize() });
    }
  }
  files.sort((a, b) => (a.updated < b.updated ? -1 : a.updated > b.updated ? 1 : 0));
  return { ok: true, files: files.slice(0, LIST_MAX_) };
}

function opGet_(req) {
  if (typeof req.id !== 'string' || !req.id) throw fail_('bad_request', 'id がありません');
  const raw = findRawFolder_();
  if (!raw) throw fail_('not_found', 'raw フォルダが見つかりません');
  let file;
  try {
    file = DriveApp.getFileById(req.id);
  } catch (err) {
    throw fail_('not_found', 'ファイルが見つかりません');
  }
  if (file.isTrashed() || !RAW_NAME_RE_.test(file.getName()) || !hasParent_(file, raw.getId())) {
    throw fail_('not_found', 'raw フォルダの日次ファイルではありません');
  }
  return {
    ok: true,
    id: file.getId(),
    name: file.getName(),
    updated: file.getLastUpdated().toISOString(),
    content: file.getBlob().getDataAsString('UTF-8'),
  };
}

function hasParent_(file, folderId) {
  const it = file.getParents();
  while (it.hasNext()) {
    if (it.next().getId() === folderId) return true;
  }
  return false;
}

function opStatus_() {
  const all = props_().getProperties();
  const sent = {};
  KINDS_.forEach(kind => { sent[kind] = latestSent_(all, kind); });
  return { ok: true, sent: sent, latestRaw: latestRaw_() };
}

function latestSent_(all, kind) {
  const prefix = 'SENT_' + kind + '_';
  let best = null;
  Object.keys(all).forEach(key => {
    if (key.indexOf(prefix) !== 0) return;
    const date = key.slice(prefix.length);
    if (!DATE_RE_.test(date) || (best && date <= best.date)) return;
    let at = null;
    try { at = JSON.parse(all[key]).at || null; } catch (err) { at = null; }
    best = { date: date, at: at };
  });
  return best;
}

function latestRaw_() {
  const raw = findRawFolder_();
  if (!raw) return null;
  let best = null;
  const it = raw.getFiles();
  while (it.hasNext()) {
    const f = it.next();
    if (!RAW_NAME_RE_.test(f.getName()) || f.isTrashed()) continue;
    const cand = { name: f.getName(), updated: f.getLastUpdated().toISOString() };
    if (!best || cand.name > best.name || (cand.name === best.name && cand.updated > best.updated)) best = cand;
  }
  return best;
}

// ───────────────────────── report ─────────────────────────

function opReport_(req) {
  const p = validateReport_(req);
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) throw fail_('busy', '別の処理中です。少し待って再実行してください');
  try {
    return saveAndSend_(p);
  } finally {
    lock.releaseLock();
  }
}

function validateReport_(req) {
  if (KINDS_.indexOf(req.kind) < 0) throw fail_('bad_request', 'kind は daily / weekly / monthly のどれかです');
  if (typeof req.date !== 'string' || !isValidDate_(req.date)) throw fail_('bad_request', 'date は YYYY-MM-DD の形にしてください');
  if (typeof req.text !== 'string' || req.text.length < 1 || req.text.length > REPORT_TEXT_MAX_) {
    throw fail_('bad_request', 'text は 1〜' + REPORT_TEXT_MAX_ + ' 文字にしてください');
  }
  if (typeof req.html !== 'string' || req.html.length < 1 || req.html.length > REPORT_HTML_MAX_) {
    throw fail_('bad_request', 'html は 1〜' + REPORT_HTML_MAX_ + ' 文字にしてください');
  }
  const source = req.source === undefined ? null : req.source;
  if (source !== null && (typeof source !== 'object' || Array.isArray(source))) {
    throw fail_('bad_request', 'source は object にしてください');
  }
  return { kind: req.kind, date: req.date, text: req.text, html: req.html, source: source, notify: req.notify !== false };
}

function isValidDate_(s) {
  if (!DATE_RE_.test(s)) return false;
  const d = new Date(s + 'T00:00:00Z');
  return !isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

function saveAndSend_(p) {
  const root = openRootFolder_();
  if (!root) throw fail_('internal', 'DRIVE_FOLDER_ID のフォルダが開けません');
  const file = upsertReportFile_(getOrCreateSubFolder_(root, REPORTS_FOLDER_NAME_), p.date + '_' + p.kind + '.html', p.html);
  const key = issueViewKey_(p.kind, p.date, file.getId());
  const url = ScriptApp.getService().getUrl() + '?v=' + key;
  if (!p.notify) return { ok: true, url: url, sent: false };

  const result = pushLine_(lineUserId_(), p.text + '\n\n詳しく: ' + url);
  if (!result.ok) {
    return { ok: false, error: 'line', message: 'LINE への送信に失敗しました(' + result.code + ')。レポートは保存済みです', url: url };
  }
  shareIds_().forEach(id => {
    const r = pushLine_(id, p.text + '\n\n詳しく: ' + url);
    if (!r.ok) console.warn('LINE_SHARE_IDS への送信に失敗: ' + r.code);
  });
  recordSent_(p, new Date().toISOString());
  return { ok: true, url: url, sent: true };
}

function upsertReportFile_(folder, name, html) {
  const it = folder.getFilesByName(name);
  while (it.hasNext()) {
    const f = it.next();
    if (f.isTrashed()) continue;
    f.setContent(html);
    return f;
  }
  return folder.createFile(name, html, MimeType.HTML);
}

// 同じ date・kind の古い鍵は消してから新しい鍵を覚える
function issueViewKey_(kind, date, fileId) {
  const store = props_();
  const lastKey = 'LAST_VIEW_' + kind + '_' + date;
  const old = store.getProperty(lastKey);
  if (old) store.deleteProperty('VIEW_' + old);
  const key = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
  store.setProperty('VIEW_' + key, fileId);
  store.setProperty(lastKey, key);
  return key;
}

function recordSent_(p, atIso) {
  let value = JSON.stringify({ at: atIso, source: p.source });
  if (value.length > 8000) value = JSON.stringify({ at: atIso, source: { truncated: true } });
  props_().setProperty('SENT_' + p.kind + '_' + p.date, value);
}

// ───────────────────────── 見張り ─────────────────────────

function watchdog() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(20000)) {
    console.warn('watchdog: ロックを取れませんでした');
    return;
  }
  try {
    const now = new Date();
    const today = Utilities.formatDate(now, TZ_, 'yyyy-MM-dd');
    const hour = Number(Utilities.formatDate(now, TZ_, 'H'));
    const store = props_();
    const rawToday = hasRawFile_(today + '.json');

    if (hour === 9 && !rawToday) {
      notifyOnce_('NOTIFIED_noraw_' + today,
        '今日のデータがまだありません。iPhone の Safari で Studio を開いて、ブックマーク「日次取得」をタップしてください');
    }
    if (hour >= 13 && rawToday && !store.getProperty('SENT_daily_' + today)) {
      notifyOnce_('NOTIFIED_nopc_' + today,
        '今日のデータは届いていますが、PC で日報がまだ作られていません。PC と入口(start.bat)が動いているか確かめてください');
    }
    cleanupProps_(now);
  } catch (err) {
    console.error('watchdog: ' + errText_(err));
  } finally {
    lock.releaseLock();
  }
}

function notifyOnce_(flagKey, text) {
  const store = props_();
  if (store.getProperty(flagKey)) return;
  const result = pushLine_(lineUserId_(), text);
  if (result.ok) store.setProperty(flagKey, new Date().toISOString());
}

function hasRawFile_(name) {
  const raw = findRawFolder_();
  if (!raw) return false;
  const it = raw.getFilesByName(name);
  while (it.hasNext()) {
    if (!it.next().isTrashed()) return true;
  }
  return false;
}

// 120 日より前の日付の NOTIFIED_・SENT_・LAST_VIEW_(と対応する VIEW_)を消す
function cleanupProps_(now) {
  const cutoff = Utilities.formatDate(new Date(now.getTime() - KEEP_DAYS_ * 86400000), TZ_, 'yyyy-MM-dd');
  const store = props_();
  const all = store.getProperties();
  Object.keys(all).forEach(key => {
    const m = /^(NOTIFIED_|SENT_|LAST_VIEW_)[A-Za-z]+(?:_[A-Za-z]+)?_(\d{4}-\d{2}-\d{2})$/.exec(key);
    if (!m || m[2] >= cutoff) return;
    if (m[1] === 'LAST_VIEW_') store.deleteProperty('VIEW_' + all[key]);
    store.deleteProperty(key);
  });
}

// ───────────────────────── 手で実行する設定用の関数 ─────────────────────────

function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'watchdog') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('watchdog').timeBased().everyHours(1).create();
  console.log('watchdog を 1 時間ごとに動かすトリガーを作りました(1 つだけ)');
}

function makeSecret() {
  const hex = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
  const secret = hex.slice(0, 48);
  const had = !!props_().getProperty('ANALYTICS_SECRET');
  props_().setProperty('ANALYTICS_SECRET', secret);
  console.log((had ? '既存の合言葉を置き換えました。ツールの画面も更新してください\n' : '') +
    '合言葉(ツールの画面の「連携の設定」に貼る): ' + secret);
}

function testLine() {
  const result = pushLine_(lineUserId_(), 'Youtube分析 連携: LINE のテストです');
  console.log(result.ok ? 'LINE に送りました' : 'LINE への送信に失敗しました(' + result.code + ')');
}

function checkSetup() {
  const store = props_();
  ['ANALYTICS_SECRET', 'DRIVE_FOLDER_ID', 'LINE_CHANNEL_ACCESS_TOKEN', 'LINE_USER_ID'].forEach(name => {
    console.log(name + ': ' + (store.getProperty(name) ? 'あり' : '無い(必須)'));
  });
  const secret = store.getProperty('ANALYTICS_SECRET') || '';
  if (secret && secret.length < SECRET_MIN_LEN_) console.log('ANALYTICS_SECRET が短すぎます(32 文字以上が必要)');
  console.log('LINE_SHARE_IDS: ' + (store.getProperty('LINE_SHARE_IDS') ? 'あり' : '無し(任意)'));
  const root = openRootFolder_();
  console.log('Drive のフォルダ: ' + (root ? '開けました' : '開けません'));
  if (root) console.log('raw フォルダ: ' + (findRawFolder_() ? 'あります' : '無い'));
  console.log('watchdog のトリガー: ' + ScriptApp.getProjectTriggers().filter(t => t.getHandlerFunction() === 'watchdog').length + ' 個');
}

// ───────────────────────── LINE ─────────────────────────

function lineUserId_() {
  return props_().getProperty('LINE_USER_ID') || '';
}

function shareIds_() {
  return (props_().getProperty('LINE_SHARE_IDS') || '').split(',').map(s => s.trim()).filter(s => s);
}

// 戻り値: {ok, code}。200 以外は失敗(応答の本文は 200 文字までログ)
function pushLine_(to, text) {
  const token = props_().getProperty('LINE_CHANNEL_ACCESS_TOKEN');
  if (!token || !to) {
    console.error('LINE の設定(LINE_CHANNEL_ACCESS_TOKEN / 送り先)が足りません');
    return { ok: false, code: 'no_config' };
  }
  const body = text.length > LINE_TEXT_MAX_ ? text.slice(0, LINE_TEXT_MAX_ - 1) + '…' : text;
  try {
    const res = UrlFetchApp.fetch(LINE_PUSH_URL_, {
      method: 'post',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + token },
      payload: JSON.stringify({ to: to, messages: [{ type: 'text', text: body }] }),
      muteHttpExceptions: true,
    });
    const code = res.getResponseCode();
    if (code !== 200) {
      console.error('LINE push 失敗 ' + code + ': ' + res.getContentText().slice(0, 200));
      return { ok: false, code: code };
    }
    return { ok: true, code: code };
  } catch (err) {
    console.error('LINE push 例外: ' + errText_(err));
    return { ok: false, code: 'exception' };
  }
}

// ───────────────────────── Drive・共通 ─────────────────────────

function props_() {
  return PropertiesService.getScriptProperties();
}

function openRootFolder_() {
  const id = props_().getProperty('DRIVE_FOLDER_ID');
  if (!id) return null;
  try {
    const folder = DriveApp.getFolderById(id);
    return folder.isTrashed() ? null : folder;
  } catch (err) {
    return null;
  }
}

function findSubFolder_(parent, name) {
  const it = parent.getFoldersByName(name);
  while (it.hasNext()) {
    const f = it.next();
    if (!f.isTrashed()) return f;
  }
  return null;
}

function getOrCreateSubFolder_(parent, name) {
  return findSubFolder_(parent, name) || parent.createFolder(name);
}

function findRawFolder_() {
  const root = openRootFolder_();
  return root ? findSubFolder_(root, RAW_FOLDER_NAME_) : null;
}

function jsonOut_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function fail_(code, message) {
  const err = new Error(message);
  err.code = code;
  return err;
}

function errorBody_(err) {
  if (err && err.code) return { ok: false, error: err.code, message: err.message };
  console.error('doPost: ' + errText_(err));
  return { ok: false, error: 'internal', message: '内部エラー: ' + errText_(err) };
}

function errText_(err) {
  return err && err.message ? String(err.message) : String(err);
}
