/* 切り抜きスタジオ: 画面の共通部分(window.Studio)。各 JS はこのAPIだけに依存する。 */
(() => {
'use strict';
const APP_VERSION = '0.1.8';   // serve.py の SERVER_VERSION と同じ値にする
const $ = s => document.querySelector(s);
const Studio = window.Studio = { version: APP_VERSION, state: null, review: null, ready: false };
const STEPS = ['rank', 'queue', 'review', 'collab'];
const PANES = { rank: '#paneRank', queue: '#paneQueue', review: '#paneReview', collab: '#paneCollab' };

Studio.esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* JSON API 呼び出し。失敗は Error(message)(e.code にサーバーのエラーコード、e.status にHTTPステータス) */
Studio.api = async (path, opts = {}) => {
  const init = { method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'), cache: 'no-store', headers: {} };
  if (opts.body !== undefined){ init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opts.body); }
  let r;
  try { r = await fetch(path, init); } catch (e){ const er = new Error('サーバーに接続できません(黒い画面が閉じていないか確認してください)'); er.code = 'network'; throw er; }
  let j = null;
  try { j = await r.json(); } catch {}
  if (!r.ok){ const er = new Error((j && j.message) || ('サーバーエラー(HTTP ' + r.status + ')')); er.code = (j && j.error) || 'http'; er.status = r.status; throw er; }
  return j;
};

let toastT = null;
Studio.toast = (msg, ms) => { const t = $('#toast'); t.textContent = String(msg); t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, ms || 4500); };
Studio.showErr = msg => { const b = $('#errBar'); b.textContent = String(msg); b.hidden = false; };

Studio.refreshState = async () => {
  Studio.state = await Studio.api('/api/state');
  document.dispatchEvent(new CustomEvent('studio:state', { detail: Studio.state }));
  return Studio.state;
};

/* 小さな数字のバッジ(タブの右)。text が空なら隠す */
Studio.setBadge = (step, text) => {
  const b = $('#badge' + step.charAt(0).toUpperCase() + step.slice(1)); if (!b) return;
  b.textContent = text || ''; b.hidden = !text;
};

Studio.step = 'rank';
Studio.go = step => {
  if (!STEPS.includes(step)) return;
  Studio.step = step;
  for (const s of STEPS){ $(PANES[s]).hidden = s !== step; }
  document.querySelectorAll('#steps .step').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.step === step)));
  try { localStorage.setItem('clipstudio:step', step); } catch {}
  document.dispatchEvent(new CustomEvent('studio:step', { detail: step }));
};

/* 各 JS の初期化。ready 後に呼ばれる(すでに ready なら即実行) */
const readyFns = [];
Studio.onReady = fn => { if (Studio.ready) fn(); else readyFns.push(fn); };
Studio.on = (name, fn) => document.addEventListener('studio:' + name, e => fn(e.detail));

document.querySelectorAll('#steps .step').forEach(b => b.addEventListener('click', () => Studio.go(b.dataset.step)));
$('#ver').textContent = 'v' + APP_VERSION;

window.addEventListener('load', async () => {
  try {
    const p = await Studio.api('/api/ping');
    if (p.app !== 'clip-studio') throw new Error('このアドレスは切り抜きスタジオではありません');
    if (p.version !== APP_VERSION) Studio.showErr('画面(v' + APP_VERSION + ')とサーバー(v' + p.version + ')の版が違います。黒い画面を閉じて起動し直してください');
    await Studio.refreshState();
  } catch (e){ Studio.showErr(e.message); return; }
  Studio.ready = true;
  for (const fn of readyFns.splice(0)){ try { fn(); } catch (e){ console.error(e); Studio.showErr('画面の初期化に失敗しました: ' + e.message); } }
  let st = 'rank'; try { st = localStorage.getItem('clipstudio:step') || 'rank'; } catch {}
  Studio.go(STEPS.includes(st) ? st : 'rank');
});
})();
