/* 「編集」3 パック のタブ(docs/edit-tool-design.md の 3・5)。app.js より先に読み、app.js が EditPack.create(host) で起動する。
   パックは cut2resolve の pack.py だけが作る(api/build の spec.keeps = 2 カット のタブの残す区間。pack.EDIT_KEEPS)。ここに Resolve 用の計算を書かない。
   「これから作るパック」の字幕の数・注意は、文字起こしのサーバーの /api/edit/preview(同じ pack.py でファイルを作らずに見積もる)。
   作り終えたら /api/edit/pack に記録し(packRev)、カットか字幕が変わったら「作り直し」と知らせる */
(function () {
'use strict';
const PREVIEW_DELAY = 600;

function create(h){
  const $ = h.$, esc = h.esc;
  const P = { docId: null, pack: null, rev: 0, preview: null, previewKey: '', previewErr: '', pvT: 0, pvSeq: 0, building: false, job: null, err: '', readme: '', lastRes: null };
  const fpsOf = () => { const o = $('#pkFpsOther').value; return o || (h.S.settings.packFps === '60' ? '60' : String(h.S.settings.packFps || '30')); };
  const sizeOf = () => h.S.settings.packSize === '1920x1080' ? '1920x1080' : '1080x1920';
  /* Text+ 字幕の1段の文字数(字幕の文字数の設定 subtitle.wrapChars。置き先が横なら横の値。規則(どこで改行するか)は cut2resolve の resolve_textplus.wrap_caption) */
  const wrapOf = () => { const w = (h.S.settings.subtitle || {}).wrapChars || {}, o = sizeOf() === '1920x1080' ? 'horizontal' : 'vertical', n = Number(w[o]);
    return Number.isInteger(n) && n >= 0 && n <= 40 ? n : (o === 'horizontal' ? 14 : 8); };
  const kept = g => g.cutState !== 'cut' && String(g.text || '').trim();

  /* パックを作れない理由(無ければ '')。見積もりと zip は、cut2resolve が無くても使える */
  function block(){
    const d = h.S.doc; if (!d) return 'no-doc';
    const cs = h.CUT ? h.CUT.state() : null;
    if (!h.CUT || !h.CUT.active()) return cs && cs.off ? 'off' : 'cut';
    if (cs.off) return 'off';
    if (!h.TOKEN) return 'standalone';
    if (!h.S.sibLoaded) return 'checking';
    if (!h.c2rBase()) return 'no-c2r';
    if (h.lockJob()) return 'lock';
    if (!(h.CUT.keepsSec() || []).length) return 'empty';
    return '';
  }
  function blockMsg(b){
    const cs = h.CUT ? h.CUT.state() : {};
    return {
      off: (cs.off || 'この動画はカット・パックに使えません') + '。',
      cut: 'カットの準備をしています…',
      standalone: 'パック作りは、入口(start-all.bat)から開いたときだけ使えます。今は「詳しい設定」の「zip でダウンロード」が使えます。',
      checking: 'cut2resolve を確かめています…',
      'no-c2r': 'cut2resolve が起動していないため、パックは作れません。入口の画面で cut2resolve を起動してから、この画面を開き直してください。',
      lock: '話者の判別・再認識の途中です。終わってから作ってください。',
      empty: '残す区間がありません(2 カット のタブで決めてください)。'
    }[b] || '';
  }

  /* ---------- 読み込み(文書を開いたとき・タブを開いたとき) ---------- */
  async function load(docId){
    Object.assign(P, { docId, pack: null, rev: 0, preview: null, previewKey: '', previewErr: '', err: '', readme: '', lastRes: null });
    $('#pkReadmeText').hidden = true; $('#pkDir').value = '';
    if (!docId) return render();
    try {
      const r = await h.api('/api/edit?id=' + encodeURIComponent(docId));
      if (P.docId !== docId) return;
      P.pack = r.edit && r.edit.pack ? r.edit.pack : null; P.rev = r.rev;
    } catch {}
    render(); schedulePreview(0);
  }
  /* ---------- これから作るパック(見積もり) ---------- */
  function schedulePreview(ms = PREVIEW_DELAY){
    clearTimeout(P.pvT);
    if (!h.S.doc || !h.CUT || !h.CUT.active() || h.CUT.state().off) return;
    P.pvT = setTimeout(runPreview, ms);
  }
  async function runPreview(){
    const d = h.S.doc, keeps = h.CUT && h.CUT.keepsSec(); if (!d || !keeps || !keeps.length) return render();
    const key = JSON.stringify(keeps) + '|' + h.rowSig() + '|' + wrapOf();
    if (key === P.previewKey && P.preview) return render();
    const seq = ++P.pvSeq, id = h.S.docId;
    try {
      if (!(await h.saveDoc())) return;   // 保存済みの文字起こしで見積もる
      const r = await h.api('/api/edit/preview', { body: { id, keeps, wrap: wrapOf() } });
      if (seq !== P.pvSeq || id !== h.S.docId) return;
      P.preview = r; P.previewKey = key; P.previewErr = '';
    } catch (e){ if (seq === P.pvSeq) { P.preview = null; P.previewErr = e.message; } }
    render();
  }

  /* ---------- 描画 ---------- */
  let rq = 0;
  function render(){ if (!rq) rq = requestAnimationFrame(() => { rq = 0; renderNow(); }); }
  function renderNow(){
    const d = h.S.doc; if (!d) return;
    const b = block(), msg = blockMsg(b), off = $('#pkOff');
    off.hidden = !msg; off.textContent = msg;
    // 置き先
    const fps = fpsOf(), size = sizeOf();
    document.querySelectorAll('#pkFps [data-v]').forEach(x => x.setAttribute('aria-pressed', x.dataset.v === fps ? 'true' : 'false'));
    document.querySelectorAll('#pkSize [data-v]').forEach(x => x.setAttribute('aria-pressed', x.dataset.v === size ? 'true' : 'false'));
    const src = h.CUT && h.CUT.fps ? h.CUT.fps() : null, srcFps = src ? src[0] / src[1] : 0;
    const fw = $('#pkFpsWarn');
    fw.hidden = !(srcFps > 45 && Number(fps) <= 30);
    fw.textContent = `元の動画は ${srcFps.toFixed(2).replace(/\.?0+$/, '')}fps です。${fps}fps のプロジェクトに入れると、区間の端が Resolve で丸められて1フレームずれることがあります(実機で確かめてください)。`;
    // これから作るパック
    const sm = h.CUT && h.CUT.summary(), pv = P.preview, fresh = pv && P.previewKey === JSON.stringify(h.CUT.keepsSec()) + '|' + h.rowSig() + '|' + wrapOf();
    $('#pkLen').textContent = sm ? h.fmtCs(sm.keptSec) : '–';
    $('#pkSrcLen').textContent = sm ? h.fmtCs(sm.durSec) : '–';
    $('#pkCount').textContent = sm ? String(sm.count) : '–';
    const hasRows = d.segments.some(kept);
    $('#pkCaps').textContent = !hasRows ? '0' : fresh ? String(pv.captions) : '…';
    $('#pkCapsL').textContent = hasRows ? 'Text+ 字幕' : 'Text+ 字幕(文字起こしが無い)';
    renderMap(sm);
    // 字幕の見た目の見本(残す行の最初の2行)
    const rows = fresh && Array.isArray(pv.samples) && pv.samples.length ? pv.samples : d.segments.filter(kept).slice(0, 2).map(g => String(g.text).trim());   // 見積もりができたら、パックと同じ改行の見本
    $('#pkSamples').innerHTML = rows.length ? rows.map(t => `<div class="tt-pk-cap tt-cap-look">${esc(t)}</div>`).join('') : '<p class="hint">文字起こしの行が無いので、字幕は入りません(EDL と動画のコピーのパックになります)</p>';
    $('#pkPhoneCap').textContent = rows[0] || '';
    $('#pkPhone').classList.toggle('land', size === '1920x1080');
    $('#pkLookNote').textContent = `左は${size === '1920x1080' ? '横 1920×1080' : '縦 1080×1920'} に置いたときのおおよその見え方(映像の切り抜きは Resolve で)。字幕の位置・大きさは置き先の大きさに合わせます。フォント「けいふぉんと」はパックに入れません(友人の PC に入れておく。無ければ Windows の日本語フォントになり、マーカーが黄色)`;
    // 作る前の注意(cut2resolve の plan の注意。例: とても短い区間)
    const warns = [];
    if (fresh) warns.push(...(pv.warnings || []));
    if (P.previewErr) warns.push('見積もりを出せませんでした: ' + P.previewErr);
    if (hasRows && fresh && pv.vanished) warns.push(`削る区間に入って消える字幕が ${pv.vanished} 件あります(削った行の字幕は入りません)`);
    const w = $('#pkWarn'); w.hidden = !warns.length; w.innerHTML = warns.slice(0, 6).map(x => `<li>${esc(x)}</li>`).join('');
    // 作る
    const stale = isStale();
    const btn = $('#pkBuild');
    btn.disabled = !!b || P.building;
    btn.textContent = P.building ? 'パックを作っています…' : P.pack ? 'パックを作り直す' : 'パックを作る';
    const bk = $('#pkBackup'); bk.disabled = !hasRows; if (!hasRows) bk.checked = true;
    $('#pkBackupHint').textContent = hasRows ? 'スクリプトが使えないときに、EDL と字幕のファイルで開くための予備。ふだんは要りません'
      : '字幕が無いパックは EDL が本体なので、いつも入ります(Text+ のスクリプトは作りません)';
    $('#pkBuildHint').textContent = P.building ? '' : b ? '' : !hasRows ? '字幕が無いので Text+ は作りません(EDL と元の動画のコピー)' : stale ? '前回のパックのあとにカットか字幕を直しています。作り直すと今の内容になります' : '作成中は進み具合と「中止」が出ます';
    const er = $('#pkErr'); er.hidden = !P.err; er.textContent = P.err ? 'パックを作れませんでした: ' + P.err : '';
    $('#pkDir').placeholder = '空欄なら 動画の隣の「' + defaultDirName() + '」';
    renderJob(); renderLast(stale);
    $('#pkZipNote').textContent = h.CUT && h.CUT.active() && !h.CUT.state().pristine ? '中身は上の「パックを作る」と同じ(2 カット のタブの区間)です。' : '中身は上の「パックを作る」と同じです。';
  }
  function defaultDirName(){ const p = String(h.S.doc && h.S.doc.sourcePath || ''), n = p.split(/[\\/]/).pop() || ''; return n.replace(/\.[^.]*$/, '') + '_pack'; }
  function renderMap(sm){
    const box = $('#pkMap'), keeps = h.CUT && h.CUT.keepsSec();
    if (!sm || !keeps || !sm.durSec){ box.innerHTML = ''; return; }
    const merged = []; for (const [a, b] of keeps){ const l = merged[merged.length - 1]; if (l && a <= l[1] + 1e-6) l[1] = b; else merged.push([a, b]); }
    box.innerHTML = merged.slice(0, 400).map(([a, b]) => `<i style="left:${a / sm.durSec * 100}%;width:${Math.max(0.3, (b - a) / sm.durSec * 100)}%"></i>`).join('');
  }
  function isStale(){
    const pk = P.pack; if (!pk || !h.CUT) return false;
    const cs = h.CUT.state();
    return pk.rev !== cs.rev || (Number(h.S.baseUpdatedAt) || 0) > (Number(pk.docUpdatedAt) || 0) || cs.dirty;
  }
  const KIND = n => /\.(lua|bat|ps1|drb)$|^textplus-import\.json$/i.test(n) ? 'Text+ のスクリプト' : /_roughcut\.mp4$/i.test(n) ? '粗編集の動画' : /\.(edl|srt)$/i.test(n) ? '予備のカット・字幕'
    : /(友人へ|手順)|^cut-plan\.json$/.test(n) ? '手順書・カットの記録' : /\.(mp4|mov|mkv|webm|m4v|avi)$/i.test(n) ? '元の動画のコピー' : 'その他';
  function renderLast(stale){
    const pk = P.pack, box = $('#pkLast');
    box.hidden = !pk; if (!pk) return;
    const pill = $('#pkLastPill'); pill.className = 'pill ' + (stale ? 'warn' : 'ok'); pill.textContent = stale ? '作り直しが要る' : '前回のパック';
    $('#pkLastWhen').textContent = `${h.ago(pk.at)}${stale ? ' ・ カットか字幕が変わっています → 作ると作り直し(上書きの確認あり)' : ''}`;
    const groups = new Map(); for (const n of pk.files || []){ const k = KIND(n); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(n); }
    $('#pkLastFiles').innerHTML = [...groups].map(([k, ns]) => `<div class="tt-pk-file"><span class="mono">${esc(ns.join(' ・ '))}</span><span class="hint">${esc(k)}</span></div>`).join('');
    $('#pkLastDir').textContent = pk.dir || ''; $('#pkLastDir').title = pk.dir || '';
    $('#pkOpen').hidden = !h.c2rBase();
  }
  function renderJob(){
    const box = $('#pkJob'), j = P.job;
    if (!j){ box.hidden = true; box.innerHTML = ''; return; }
    if (!box.firstChild) box.innerHTML = '<div class="row"><span><span class="pill run">パックを作っています</span> <span class="tt-cp-jmsg"></span></span><span class="mono hint tt-cp-jpct"></span></div><div class="bar"><i></i></div><div class="row" style="justify-content:flex-end"><button type="button" class="btn small" data-act="pkcancel">中止</button></div>';
    box.hidden = false;
    const pct = j.progress != null ? Math.round(j.progress * 100) : null;
    box.querySelector('.tt-cp-jmsg').textContent = j.message || '';
    box.querySelector('.tt-cp-jpct').textContent = pct != null ? pct + '%' : (j.elapsed != null ? Number(j.elapsed).toFixed(0) + '秒' : '');
    const bar = box.querySelector('.bar'); bar.classList.toggle('indeterminate', pct == null); bar.querySelector('i').style.width = (pct || 0) + '%';
  }

  /* ---------- パックを作る(cut2resolve の api/build。区間は spec.keeps) ---------- */
  async function build(){
    if (P.building || block()) return;
    const id = h.S.docId, d = h.S.doc; P.building = true; P.err = ''; render();
    try {
      if (!(await h.CUT.commit())) throw new Error('カットを保存できませんでした(カットのタブの案内を見てください)');
      if (h.S.docId !== id) return;
      const hasRows = d.segments.some(kept);
      const path = hasRows ? await h.cpExport(id) : null;   // 字幕の元(保存済みの文字起こしを動画の隣に .transcript.json で)
      const rev = h.CUT.state().rev, docAt = h.S.baseUpdatedAt;
      const adv = {}; for (const [k, sel] of [['srcStartTc', '#pkSrcTc'], ['recStart', '#pkRecTc'], ['reel', '#pkReel']]){ const v = $(sel).value.trim(); if (v) adv[k] = v; }
      const spec = { video: d.sourcePath, keeps: h.CUT.keepsSec(), advanced: adv, ...(path ? { transcript: path } : {}) };
      const out = { textplus: hasRows, copyVideo: true, render: $('#pkRender').checked, backup: hasRows && $('#pkBackup').checked, textplusFps: fpsOf(), textplusSize: sizeOf(), textplusWrap: wrapOf(), ...($('#pkDir').value.trim() ? { dir: $('#pkDir').value.trim() } : {}) };
      let force = false, res;
      for (;;){
        try {
          const j = await h.c2rApi('api/build', { body: { spec, output: { ...out, force } } });
          P.job = j.job; renderJob();
          res = await h.c2rWait(j.job, pj => { P.job = pj; renderJob(); });
          break;
        } catch (e){
          P.job = null; renderJob();
          if (e.code === 'exists' && !force){
            const dd = e.data || {};
            if (!(await h.confirmOverwrite(dd.files || [], dd.dir || ''))) return;
            force = true; continue;
          }
          throw e;
        }
      }
      const files = (res.files || []).map(f => f.name);
      const r = await h.api('/api/edit/pack', { body: { id, rev, docUpdatedAt: Number(docAt) || 0, dir: res.outDir, files } });
      if (h.S.docId !== id) return;
      P.pack = { rev, at: r.at, docUpdatedAt: Number(docAt) || 0, dir: res.outDir, files: files.map(n => n.split(/[\\/]/).pop()) };
      P.readme = res.readme || ''; P.lastRes = res;
      h.onPacked(id, { rev, at: r.at });
      for (const w of (res.warnings || []).slice(0, 2)) h.toast(w, 6000);
      h.toast(`パックを作りました(残す区間 ${Number(res.summary && res.summary.count) || 0}か所)。フォルダの中の「友人へ.txt」の手順で Resolve に取り込みます`, 8000, 'ok');
    } catch (e){
      if (e.code === 'cancelled') h.toast('パック作りを中止しました', 3000);
      else if (e.code !== 'switched') P.err = e.code === 'busy' ? 'cut2resolve で別の処理が動いています。終わってから、もう一度押してください' : e.message;
    } finally { P.building = false; P.job = null; render(); }
  }

  /* ---------- イベント ---------- */
  function setOpt(key, v){ h.S.settings[key] = v; h.saveSettings(); render(); }
  $('#pkFps').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b){ $('#pkFpsOther').value = ''; setOpt('packFps', b.dataset.v); } });
  $('#pkSize').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) setOpt('packSize', b.dataset.v); });
  $('#pkFpsOther').addEventListener('change', () => { if ($('#pkFpsOther').value) setOpt('packFps', $('#pkFpsOther').value); else render(); });
  $('#pkBuild').addEventListener('click', build);
  $('#pkBackup').addEventListener('change', render);
  $('#pkJob').addEventListener('click', async e => {
    if (!e.target.closest('[data-act=pkcancel]') || !P.job) return;
    try { await h.c2rApi('api/job/cancel', { body: { id: P.job.id } }); } catch (er){ h.toast(er.message, 4000, 'err'); }
  });
  $('#pkOpen').addEventListener('click', async () => {
    if (!P.pack) return;
    try { await h.c2rApi('api/open-folder', { body: { path: P.pack.dir } }); } catch (er){ h.toast('フォルダを開けませんでした: ' + er.message, 5000, 'err'); }
  });
  $('#pkCopy').addEventListener('click', async () => {
    if (!P.pack) return;
    try { await navigator.clipboard.writeText(P.pack.dir || ''); h.toast('パスをコピーしました', 2000, 'ok'); } catch { h.toast('コピーできませんでした(パスを選んでコピーしてください)', 3000, 'err'); }
  });
  $('#pkReadme').addEventListener('click', async () => {
    const pre = $('#pkReadmeText');
    if (!pre.hidden){ pre.hidden = true; return; }
    let text = P.readme;
    if (!text){ try { text = (await h.api('/api/edit/pack-readme?id=' + encodeURIComponent(h.S.docId))).text; } catch (e){ return h.toast(e.message, 5000, 'err'); } }
    pre.textContent = String(text).slice(0, 20000); pre.hidden = false;
  });
  /* zip でダウンロード(人に送るとき。/api/resolve-package。中身は pack.py で作る Text+ パックと同じ。カットがあればそのとおり) */
  $('#pkZip').addEventListener('click', async () => {
    if (!h.S.docId) return;
    if (!(await h.saveDoc()) || (h.CUT && !(await h.CUT.flush()))) return h.toast('保存が追いついていません。少し待ってから、もう一度押してください', 5000, 'err');
    const b = $('#pkZip'), label = b.textContent; b.disabled = true; b.textContent = '作成中…';
    try {
      const r = await h.apiBlob('/api/resolve-package', { tid: h.S.docId, fps: fpsOf(), size: sizeOf(), backup: $('#pkBackup').checked, wrap: wrapOf() });
      h.download(await r.blob(), `${h.safeName(h.S.doc.title)}-resolve.zip`);
      const cuts = r.headers.get('X-Resolve-Cuts') || '?', caps = r.headers.get('X-Resolve-Captions') || '?';
      h.toast(`パック(zip)を作成しました(残す区間${cuts}か所・Text+ ${caps}件)。zip を展開して、中の「友人へ.txt」の手順で Resolve に取り込みます`, 8000, 'ok');
    } catch (e){ h.toast('パック(zip)を作れませんでした: ' + e.message, 7000, 'err'); }
    finally { b.disabled = false; b.textContent = label; }
  });

  return {
    load,
    shown(){ if (h.S.doc){ render(); schedulePreview(0); } },
    changed(){ render(); if (h.tab() === 'pack') schedulePreview(); else { P.previewKey = ''; } },   // カット・文字起こしが変わった
    refresh: render,
    state: () => ({ building: P.building, pack: P.pack })
  };
}
window.EditPack = { create };
})();
