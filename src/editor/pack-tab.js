/* 「編集」のパック(2 カット の末尾 #packArea。docs/design/edit-tool-design.md の 3・5)。app.js より先に読み、app.js が EditPack.create(host) で起動する。
   0.62.0 で「3 パック」のタブを無くした: 作るのは 2 カット の末尾・設定(fps・大きさ・音量・予備・字幕の 1 段の文字数・余白・話者の色)は ⚙ の「パック」の節 #edSetPack(欄の id は以前のまま)・
   配信者(字幕の色)の欄は見せず、文書に覚えている名前(友人の依頼・まとめて実行の指定)を隠した欄 #pkWho に UIKit.streamer.autoFill で入れてそのまま使う(docs/spec/settings.md の 3)。
   パックは cut2resolve の pack.py だけが作る(api/build の spec.keeps = 2 カット のタブの残す区間。pack.EDIT_KEEPS)。ここに Resolve 用の計算を書かない。
   「これから作るパック」の字幕の数・注意は、文字起こしのサーバーの /api/edit/preview(同じ pack.py でファイルを作らずに見積もる)。
   作り終えたら /api/edit/pack に記録し(packRev)、カットか字幕が変わったら「作り直し」と知らせる */
(function () {
'use strict';
const PREVIEW_DELAY = 600;

function create(h){
  const $ = h.$, esc = h.esc;
  const P = { docId: null, pack: null, rev: 0, preview: null, previewKey: '', previewErr: '', pv: 'idle', pvErrKey: '', pvT: 0, pvSeq: 0, building: false, job: null, err: '', readme: '', lastRes: null,
    notes: [], focusOpen: false };   // notes = 作ったときの案内(info。知らせに積まず「前回のパック」に出す)・focusOpen = 作り終えたら「フォルダを開く」へフォーカス(段7 E-11)
  /* パックの fps は 30 固定(2026-10-11 RS7-1 S6a。素材は 30fps にそろえる = マスタープラン Q1。画面の欄は消した。設定に残っている packFps は読まない・消さない) */
  const fpsOf = () => '30';
  const sizeOf = () => h.S.settings.packSize === '1920x1080' ? '1920x1080' : '1080x1920';
  /* 音量のそろえ方(LUFS。編集の設定 packLoudness。0 = そろえない(% で決める)。まとめて実行のパックも同じ値。既定は 0・音量 30%(2026-10-01 ユーザー決定)) */
  const loudOf = () => {
    const raw = h.S.settings.packLoudness; if (raw === undefined || raw === null || raw === '') return 0;
    const v = Number(raw); return v === 0 ? 0 : [-11, -14, -16, -18].includes(v) ? v : -14;
  };
  const volOf = () => { const v = Math.round(Number(h.S.settings.packVolume)); return v >= 1 && v <= 200 ? v : 30; };   // LUFS でそろえないときの音量(%。元 = 100・既定 30)
  async function saveLoud(values){   // パックの出力(音量・fps・縦横・話者の色・予備)は「送ったキーだけ直す」API で(丸ごとの保存では変えない。まとめて実行の欄と同じ値)
    await h.patchSettings(values, 'パックの設定を保存できませんでした', { ms: 10000, retry: () => saveLoud(values) });   // 失敗は [もう一度](S27)
    render();
  }
  /* Text+ 字幕の1段の文字数(字幕の文字数の設定 subtitle.wrapChars。置き先が横なら横の値。規則(どこで改行するか)は cut2resolve の resolve_textplus.wrap_caption) */
  const wrapOf = () => { const w = (h.S.settings.subtitle || {}).wrapChars || {}, o = sizeOf() === '1920x1080' ? 'horizontal' : 'vertical', n = Number(w[o]);
    return Number.isInteger(n) && n >= 0 && n <= 40 ? n : (o === 'horizontal' ? 14 : 8); };
  const kept = g => g.cutState !== 'cut' && String(g.text || '').trim();
  const padOf = () => { const o = h.S.settings.rowEdge && typeof h.S.settings.rowEdge === 'object' ? h.S.settings.rowEdge : {}, n = Number(o.padAfter); return Number.isFinite(n) && n >= 0 && n <= 2 ? n : 0.2; };   // 行の後の余白(段6 6-2)
  const previewKeyNow = () => JSON.stringify(h.CUT ? h.CUT.keepsSec() : null) + '|' + h.rowSig() + '|' + wrapOf();   // 見積もりの鍵(残す区間・行の文字・字幕の1段の文字数(縦横で変わる))。同じなら出し直さない

  /* 今の出力の設定(段4 4-3)。パックを作る API に渡す物と、作った記録(/api/edit/pack の output)と、前回のパックとの違いは、ここ1か所から作る */
  function outputNow(hasRows){
    const adv = {}; for (const [k, sel] of [['srcStartTc', '#pkSrcTc'], ['recStart', '#pkRecTc'], ['reel', '#pkReel']]){ const v = $(sel).value.trim(); if (v) adv[k] = v.slice(0, 40); }
    const o = { fps: fpsOf(), size: sizeOf(), wrap: wrapOf(), textplus: hasRows, backup: hasRows && $('#pkBackup').checked, render: $('#pkRender').checked,
      speakerColors: hasRows && $('#pkSpk').checked, loudness: loudOf(), volume: volOf(), advanced: adv };
    if (hasRows && whoOf()) o.streamer = whoOf().slice(0, 200);
    const st = hasRows ? stylesNow() : null; if (st) o.speakerStyles = st;   // 1 人もいなければ鍵ごと送らない(今までと同じ要求)
    return o;
  }
  /* 話者ごとの字幕の見た目(文書の話者の sub。今は色だけ。2026-10-05)-> {話者の名前: {color: "#RRGGBB"}} か null。
     cut2resolve は speakerStyles の色を最優先にする(「話者の名前がメンバーと合えば…」を切っていても効く) */
  function stylesNow(){
    const out = {}; let n = 0;
    for (const sp of (h.S.doc && h.S.doc.speakers) || []){
      const name = String(sp.name || '').trim(), hex = h.isOtherSp(sp) ? '' : h.subColorOf(sp);
      if (name && hex && !(name in out)){ out[name.slice(0, 60)] = { color: hex }; n++; }
    }
    return n ? out : null;
  }
  const stylesText = st => st && typeof st === 'object' ? Object.keys(st).sort().map(k => `${k} ${(st[k] && st[k].color) || ''}`).join('、') : '';
  /* 作ったときの出力の設定(記録)と今の設定の違い(4-3。監査 08)。記録が無ければ null(この版より前・まとめて実行で作ったパック) */
  const OUT_LABEL = { fps: 'フレームレート', size: '大きさ', wrap: '字幕の1段の文字数', textplus: 'Text+ 字幕', backup: '予備', render: '粗編集の動画', speakerColors: '話者の色', streamer: '配信者', speakerStyles: '話者ごとの字幕の色',
    srcStartTc: '開始タイムコード', recStart: 'タイムラインの開始', reel: 'リール名' };
  function outputDiff(rec, now){
    if (!rec || typeof rec !== 'object') return null;
    const fmt = (k, v) => v === undefined || v === '' ? 'なし' : typeof v === 'boolean' ? (v ? 'あり' : 'なし') : k === 'size' ? (v === '1920x1080' ? '横 1920×1080' : '縦 1080×1920') : k === 'fps' ? v + 'fps' : String(v);
    const diffs = [];
    for (const k of ['fps', 'size', 'wrap', 'textplus', 'backup', 'render', 'speakerColors', 'streamer']){
      const a = rec[k] === undefined ? '' : rec[k], b = now[k] === undefined ? '' : now[k];
      if (String(a) !== String(b)) diffs.push(`${OUT_LABEL[k]}: ${fmt(k, rec[k])} → ${fmt(k, now[k])}`);
    }
    { const a = stylesText(rec.speakerStyles), b = stylesText(now.speakerStyles);   // 話者ごとの字幕の色(記録に無い = 指定なしで作った)
      if (a !== b) diffs.push(`${OUT_LABEL.speakerStyles}: ${a || 'なし'} → ${b || 'なし'}`); }
    const vol = x => x.loudness ? `${x.loudness} LUFS` : x.volume !== undefined ? `${x.volume}%` : '';
    if (vol(rec) && vol(rec) !== vol(now)) diffs.push(`音量: ${vol(rec)} → ${vol(now)}`);
    const ra = rec.advanced && typeof rec.advanced === 'object' ? rec.advanced : {}, na = now.advanced || {};
    for (const k of ['srcStartTc', 'recStart', 'reel']) if (String(ra[k] || '') !== String(na[k] || '')) diffs.push(`${OUT_LABEL[k]}: ${ra[k] || 'なし'} → ${na[k] || 'なし'}`);
    return diffs;
  }
  /* zip に渡らない設定(4-4。監査 10。zip の中身は今のまま = ユーザー決定 09-29)。dev/tests/test_resolve_pack_contract.py の ZipSkipsContract がこの差を固定している
     (zip に渡すようにしたら、そのテストが落ちて、ここの説明を直す合図になる)。開始タイムコード・リール名は予備の EDL にだけ効く */
  const ZIP_SKIPS = [['render', '粗編集の動画'], ['volume', '音量の調整'], ['srcStartTc', '開始タイムコード'], ['recStart', 'タイムラインの開始タイムコード'], ['reel', 'リール名']];
  const zipSkipped = o => ZIP_SKIPS.filter(([k]) => k === 'render' ? o.render : k === 'volume' ? !!(o.loudness || o.volume !== 100) : !!(o.advanced || {})[k]).map(([, l]) => l);

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
      standalone: 'パック作りは、ホーム(start.bat)から開いたときだけ使えます。今は「詳しい設定」の「zip でダウンロード」が使えます。',
      checking: 'cut2resolve を確かめています…',
      'no-c2r': 'cut2resolve が起動していないため、パックは作れません。start.bat でホームを起動し直してから、この画面を開き直してください。',
      lock: '話者の判別・再認識の途中です。終わってから作ってください。',
      empty: '残す区間がありません(2 カット のタブで決めてください)。'
    }[b] || '';
  }

  /* ---------- 配信者の名前(字幕の文字の色。git の履歴(679ff01 以前)の docs/archive/followup-2026-09-27.md の 4)----------
     手で入れたときだけ(自動では入れない)。文書ごとにこのブラウザに覚える(tx.streamer.v1。{文書の id: 名前}・新しい 300 件まで)。
     名前 → 色の照らし合わせは入口(ui-kit の UIKit.streamer → ytt/colors.py)。パックには名前のまま渡す(cut2resolve が同じ規則で照らし合わせる) */
  const WHO_KEY = 'tx.streamer.v1';
  const whoMap = () => { try { const m = JSON.parse(localStorage.getItem(WHO_KEY) || '{}'); return m && typeof m === 'object' ? m : {}; } catch { return {}; } };
  const whoFor = id => { const v = whoMap()[id]; return typeof v === 'string' ? v : ''; };
  const whoOf = () => $('#pkWho').value.trim();
  /* 配信者の名前は、ホームの設定に文書ごとに覚える(UIKit.streamer.autoFill。直したら文書・配信・チャンネルに。段5)。
     以前のこのブラウザの記憶(tx.streamer.v1)は、初めて開いた文書で1回だけ移す(消さない) */
  $('#pkWho').addEventListener('ui-streamer', e => {   // 合う人が決まったら、字幕の見本(パック・カットのタブ)の色と見出しを変える
    const who = e.detail;
    if (who) document.body.style.setProperty('--tt-cap-color', who.hex); else document.body.style.removeProperty('--tt-cap-color');
    $('#pkLookName').textContent = who ? `けいふぉんと・${who.name}の色の文字(${who.hex})・白いふち・黒いふち` : 'けいふぉんと・黒い文字・白いふち・黒いふち';
    /* 配信者の欄は見せない(0.62.0)ので、どの名前を使うかを 1 行で */
    const note = $('#pkWhoNote'), name = whoOf();
    if (note) note.textContent = who ? `配信者: ${who.name}(この文書に覚えている名前。字幕の文字をこの色に。変えるには題名の行の「まとめて実行」の配信者の欄)`
      : name ? `配信者「${name}」はメンバーカラーに見つからないので、黒い文字になります(ホロカラーのマイカラーに足すと使えます)`
      : h.TOKEN ? '配信者はまだ決まっていないので黒い文字(題名の行の「まとめて実行」の配信者の欄で決めると、この文書に覚えます)' : '配信者の色はホームから開いたときだけ(単体では黒い文字)';
    render();   // 「前回の設定」の要約の色の丸も、入れ直すたびに合わせる
  });

  /* ---------- 話者ごとの字幕の色(A-2)。色を決めるのは app.js の speakerColor の1か所(気が利く画面へ 段2。照らし合わせは入口の
     api/ytt/streamer-colors → ytt/colors.py)。パックを作るのは cut2resolve(output.speakerColors)で、ここは「どの話者が何色になるか」を見せるだけ。
     スイッチは編集の設定 speakerColors(1 文字起こし・カットのプレビュー・まとめて実行も同じ値。以前はこのブラウザの tx.pk.speakerColors) ---------- */
  const spkOn = () => h.S.settings.speakerColors !== false;
  $('#pkSpk').addEventListener('change', async () => { await saveLoud({ speakerColors: $('#pkSpk').checked }); h.onSpeakerColors(); });
  function renderSpk(){
    const box = $('#pkSpkList'), d = h.S.doc, on = spkOn();
    $('#pkSpk').checked = on;
    const sps = d ? (d.speakers || []).filter(s => String(s.name || '').trim() && !h.isOtherSp(s)) : [];   // 組み込みの「ゲーム音声など」は字幕に出さないので並べない
    const own = sps.filter(s => h.subColorOf(s));   // 字幕の色を指定した話者(スイッチによらず効く)
    $('#pkSpk').disabled = !h.TOKEN; $('#pkSpk').title = h.TOKEN ? '' : 'ホームから開くと使えます';   // 押せない理由(A-34)
    const item = (hex, text) => `<span class="tt-pk-spk-i"><i class="tt-pk-spk-sw" style="background:${esc(hex)}"></i>${esc(text)}</span>`;   // 色の丸つきの 1 人
    const ownHTML = own.slice(0, 12).map(sp => { const hex = h.subColorOf(sp); return item(hex, `${String(sp.name).trim()} → 指定の色(${hex})`); }).join(' ・ ');
    if (!h.TOKEN){ if (own.length) box.innerHTML = ownHTML; else box.textContent = 'ホームから開くと使えます'; return; }
    if (!on || !sps.length){ if (own.length) box.innerHTML = ownHTML; else box.textContent = on ? '話者がいない文書です(話者判別か「話者」の欄で名前を付けると使えます)' : ''; return; }
    box.innerHTML = sps.slice(0, 12).map(sp => {
      const c = h.speakerColor(sp.id), n = String(sp.name).trim();
      return c.sub ? item(c.hex, `${n} → 指定の色(${c.hex})`) : c.hex ? item(c.hex, `${n} → ${c.member}の色`)
        : c.reason ? `<span class="tt-pk-spk-i">${esc(n)} → 配信者の色のまま</span>` : `<span>${esc(n)}: …</span>`;
    }).join(' ・ ');
  }
  /* 字幕の見本の色: 話者の字幕の色(sub)→ メンバーと合えばその色(合わなければ配信者の色 = body の --tt-cap-color のまま)。行の話者(id)からと、見積もりの話者(名前)から。
     メンバーの色のスイッチ(speakerColors)は app.js の speakerColor / speakerColorByName が見る(指定の色はスイッチによらず効く) */
  const segHex = seg => seg && seg.speaker ? h.speakerColor(seg.speaker).hex : '';
  const nameHex = name => name ? h.speakerColorByName(name).hex : '';
  const capStyle = hex => hex ? ` style="--tt-cap-color:${h.esc(hex)}"` : '';

  /* ---------- 読み込み(文書を開いたとき・タブを開いたとき) ---------- */
  async function load(docId){
    Object.assign(P, { docId, pack: null, rev: 0, preview: null, previewKey: '', previewErr: '', pv: 'idle', pvErrKey: '', err: '', readme: '', lastRes: null, notes: [], focusOpen: false });
    $('#pkReadmeText').hidden = true; $('#pkDir').value = '';
    thLoad(docId);
    const old = docId ? whoFor(docId) : '';
    if (old && UIKit.prefs.available()) UIKit.prefs.get(['streamer']).then(p => {
      if (!(docId in ((p.streamer || {}).docs || {}))) return UIKit.prefs.remember('docs', docId, old);
    }).catch(() => {}).then(() => UIKit.streamer.autoFill($('#pkWho'), { docId }));
    else if (docId) UIKit.streamer.autoFill($('#pkWho'), { docId });
    else UIKit.streamer.set($('#pkWho'), '');
    if (!docId) return render();
    try {
      const r = await h.api('/api/edit?id=' + encodeURIComponent(docId));
      if (P.docId !== docId) return;
      P.pack = r.edit && r.edit.pack ? r.edit.pack : null; P.rev = r.rev;
    } catch {}
    render(); schedulePreview(0);
  }
  /* ---------- サムネの案(提案 P5。0.64.0)----------
     作るのはサーバーのジョブ kind thumb(POST /api/thumb-ideas → 作業用/<名前>_thumb-ideas.png)。結果は GET /api/thumb-ideas・画像は /api/thumb-ideas/image。
     切り取りは編集の設定 thumbCrop に覚える。文書は読むだけなので、作っている間も編集はできる(作る前に保存して、今の字幕で作る) */
  const TH = { docId: null, info: null, busy: false, msg: '', seq: 0 };
  const thCropOf = () => ['alt', 'center', 'right'].includes(h.S.settings.thumbCrop) ? h.S.settings.thumbCrop : 'alt';
  async function thLoad(docId){
    const seq = ++TH.seq;
    Object.assign(TH, { docId, info: null, msg: '' });
    thRender();
    if (!docId) return;
    try { const r = await h.api('/api/thumb-ideas?id=' + encodeURIComponent(docId)); if (seq === TH.seq) TH.info = r; }
    catch (e){ if (seq === TH.seq) TH.msg = e.message; }   // 動画が無いなど(作るボタンの理由に出す)
    if (seq === TH.seq) thRender();
  }
  function thRender(){
    const card = $('#thCard'), d = h.S.doc;
    card.hidden = !TH.docId || !d;
    if (card.hidden) return;
    $('#thCrop').value = thCropOf();
    const info = TH.info, go = $('#thGo');
    go.disabled = TH.busy || !info;
    go.textContent = info && info.ok ? 'サムネの案を作り直す' : 'サムネの案を作る';
    go.title = TH.busy ? '作っている途中です' : !info ? (TH.msg || '読み込み中です') : '今の字幕と動画から 6 案を作ります(上書き)';
    $('#thMsg').textContent = TH.busy ? (TH.msg || '作っています…') : TH.msg || (info && info.ok ? `作った案(${h.ago(info.at)}・${info.file}・動画のフォルダの 作業用)` : 'まだ作っていません');
    const link = $('#thLink');
    link.hidden = !(info && info.ok);
    if (!link.hidden){ const u = h.apiUrl('/api/thumb-ideas/image?id=' + encodeURIComponent(TH.docId) + '&t=' + info.at); link.href = u; if ($('#thImg').getAttribute('src') !== u) $('#thImg').src = u; }
  }
  async function thGo(){
    const id = TH.docId; if (!id || TH.busy) return;
    TH.busy = true; TH.msg = '保存しています…'; thRender();
    try {
      try { await h.saveDoc(); } catch { /* 保存できなくても、保存済みの字幕で作る */ }
      TH.msg = '作っています…'; thRender();
      const job = await h.api('/api/thumb-ideas', { body: { id, crop: thCropOf() } });
      const end = await thWait(job.id);
      if (TH.docId !== id) return;
      if (end.state === 'done') h.toast('サムネの案を作りました(作業用 のフォルダ)', { kind: 'ok' });
      else h.toast(end.error || 'サムネの案を作れませんでした', { kind: 'err', ms: 10000 });
      TH.msg = end.state === 'done' ? '' : (end.error || '作れませんでした');
    } catch (e){ TH.msg = e.message; }
    finally { TH.busy = false; }
    if (TH.docId === id){ const keep = TH.msg; await thLoad(id); if (keep) { TH.msg = keep; thRender(); } }
  }
  /* ジョブが終わるまで待つ(0.8 秒ごとに一覧を聞く。続けて 5 回読めなければやめる) */
  async function thWait(jid){
    for (let errs = 0; ;){
      await new Promise(r => setTimeout(r, 800));
      let j = null;
      try { const r = await h.api('/api/jobs'); j = (r.jobs || []).find(x => x.id === jid); errs = 0; }
      catch (e){ if (++errs >= 5) throw e; continue; }
      if (!j) return { state: 'error', error: '処理の記録が見つかりませんでした(画面を読み込み直してください)' };
      if (!['queued', 'loading', 'extracting', 'running'].includes(j.state)) return j;
    }
  }
  $('#thGo').addEventListener('click', thGo);
  $('#thCrop').addEventListener('change', async () => {
    const v = $('#thCrop').value;
    if (!(await h.patchSettings({ thumbCrop: v }, '切り取りの指定を保存できませんでした', { ms: 8000 }))) $('#thCrop').value = thCropOf();
  });

  /* ---------- これから作るパック(見積もり) ---------- */
  function schedulePreview(ms = PREVIEW_DELAY){
    clearTimeout(P.pvT); P.pvT = 0;
    if (!h.S.doc || !h.CUT || !h.CUT.active() || h.CUT.state().off) return;
    P.pv = 'wait'; P.pvT = setTimeout(runPreview, ms);
  }
  /* 見積もりの状態 P.pv(4-1。監査 07): idle(最新か、出す物が無い)/ wait(予約)/ run(計算中)/ save(文字起こしの保存を待っている)/ err(失敗)。
     save・err のときは同じ鍵(pvErrKey)では自動で出し直さない(「もう一度」か、設定・カット・行が変わって鍵が変わったとき)。失敗しても前の見積もりは消さない(薄く残す) */
  async function runPreview(){
    P.pvT = 0;
    const d = h.S.doc, keeps = h.CUT && h.CUT.keepsSec(); if (!d || !keeps || !keeps.length){ P.pv = 'idle'; return render(); }
    const key = previewKeyNow();
    if (key === P.previewKey && P.preview){ P.pv = 'idle'; return render(); }
    const seq = ++P.pvSeq, id = h.S.docId;
    P.pv = 'run'; render();
    try {
      let saved = false; try { saved = await h.saveDoc(); } catch { saved = false; }   // 保存済みの文字起こしで見積もる
      if (seq !== P.pvSeq || id !== h.S.docId) return;
      if (!saved){ P.pv = 'save'; P.pvErrKey = key; return render(); }
      const r = await h.api('/api/edit/preview', { body: { id, keeps, wrap: wrapOf() } });
      if (seq !== P.pvSeq || id !== h.S.docId) return;
      P.preview = r; P.previewKey = key; P.previewErr = ''; P.pv = 'idle'; P.pvErrKey = '';
    } catch (e){ if (seq === P.pvSeq && id === h.S.docId){ P.previewErr = e.message; P.pv = 'err'; P.pvErrKey = key; } }
    render();
  }

  /* ---------- 描画 ---------- */
  let rq = 0;
  const TEXTPLUS_ABBR = '<abbr class="ui-term" title="DaVinci Resolve の文字のタイトル。パックに入るスクリプトが Resolve の中で字幕として作ります">Text+</abbr>';
  const CODEC_HOW = '変換するには: スタジオで書き出し直す(H.264 の mp4 になります)か、ffmpeg で「ffmpeg -i 元の動画 -c:v libx264 -crf 18 -c:a aac 出力.mp4」';
  function render(){ if (!rq) rq = requestAnimationFrame(() => { rq = 0; renderNow(); }); }
  function renderNow(){
    const d = h.S.doc; if (!d) return;
    const b = block(), msg = blockMsg(b), off = $('#pkOff');
    off.hidden = !msg; off.textContent = msg;
    // 置き先
    const fps = fpsOf(), size = sizeOf();
    document.querySelectorAll('#pkSize [data-v]').forEach(x => x.setAttribute('aria-pressed', x.dataset.v === size ? 'true' : 'false'));
    // これから作るパック
    const sm = h.CUT && h.CUT.summary(), pv = P.preview, pvKey = previewKeyNow(), fresh = !!pv && P.previewKey === pvKey;
    const hasRows = d.segments.some(kept), o = outputNow(hasRows);
    // 4-1: 鍵が変わっていて(縦横・字幕の文字数・カット・行)、予約も計算も無く、同じ鍵で失敗していなければ、ここで出し直しを予約する。
    // 設定を変える所ごとに予約を書くと足し忘れで同じ不具合が戻るので、描画の1か所で(タブを見ているときだけ。render は rAF でまとまるので連打にならない)
    if (!fresh && sm && sm.count && h.tab() === 'cut' && P.pv !== 'wait' && P.pv !== 'run' && P.pvErrKey !== pvKey) schedulePreview();
    $('#pkLen').textContent = sm ? h.fmtCs(sm.keptSec) : '–';
    $('#pkSrcLen').textContent = sm ? h.fmtCs(sm.durSec) : '–';
    $('#pkCount').textContent = sm ? String(sm.count) : '–';
    $('#pkCaps').textContent = !hasRows ? '0' : fresh ? String(pv.captions) : '…';
    $('#pkCapsL').innerHTML = TEXTPLUS_ABBR + (hasRows ? ' 字幕' : ' 字幕(文字起こしが無い)');   // 最初に出る所に言葉の説明(A-15・S10)
    renderMap(sm);
    // 字幕の見た目の見本(残す行の最初の2行)
    const keptSegs = d.segments.filter(g => kept(g) && !g.noSub).slice(0, 2);   // 字幕に出さない行は見本にも出さない
    { /* 字幕に出さない行の数(残す区間には数える。0 なら出さない)・重なる字幕の段(2 段以上のとき)。見積もりができたらパックと同じ数(pack.summary の noSubRows・captionLanes)、
         古い間は行から数えた目安 */
      const n = fresh && Number.isFinite(pv.noSubRows) ? pv.noSubRows : d.segments.filter(g => kept(g) && g.noSub).length;
      const lanes = fresh ? Number(pv.captionLanes) || 0 : 0, stacked = fresh ? Number(pv.captionsStacked) || 0 : 0, el = $('#pkNoSub');
      const bits = [n ? `字幕に出さない行: ${n} 行(ゲームの声など。字幕は作らず、区間は残します)` : '', lanes >= 2 ? `重なる字幕を ${lanes} 段に分けます(${stacked} 個)` : ''].filter(Boolean);
      el.hidden = !bits.length; el.textContent = bits.join(' ・ '); }
    { /* 読みにくい字幕(速い・短い。2026-10-05): 残す行のうち読む速さの印が付く行の数(画面の側で数える。パックは変えない。0 なら出さない)。
         readMark は app-rows.js(この画面の後に読む。描くときには読み終わっている) */
      const el = $('#pkRead'), n = typeof readMark === 'function' ? d.segments.filter(g => kept(g) && readMark(g)).length : 0;
      if (el){ el.hidden = !n; el.textContent = n ? `読みにくい字幕: ${n} 行(1 秒あたりの文字が多い・表示が短い。1 文字起こし の絞り込み「読みにくい行だけ」で確かめられます)` : ''; } }
    const rows = fresh && Array.isArray(pv.samples) && pv.samples.length ? pv.samples : keptSegs.map(g => String(g.text).trim());   // 見積もりができたら、パックと同じ改行の見本
    // 見本の色(4-5。監査 12): 見積もりができたら、パックと同じ規則の話者(pack.py の cue_speakers → sampleSpeakers。名前)。古い間は行の話者から。規則は同じなので通常は同じ色
    const spkNames = fresh && Array.isArray(pv.sampleSpeakers) && pv.samples && pv.samples.length ? pv.sampleSpeakers : null;
    const capHex = i => spkNames ? nameHex(spkNames[i]) : segHex(keptSegs[i]);
    $('#pkSamples').innerHTML = rows.length ? rows.map((t, i) => `<div class="tt-pk-cap tt-cap-look"${capStyle(capHex(i))}>${esc(t)}</div>`).join('') : '<p class="hint">文字起こしの行が無いので、字幕は入りません(EDL と動画のコピーのパックになります)</p>';
    $('#pkPhoneCap').textContent = rows[0] || '';
    { const hex = capHex(0);   // 見本の電話の字幕も話者の色(GPT-12)
      if (hex) $('#pkPhoneCap').style.setProperty('--tt-cap-color', hex); else $('#pkPhoneCap').style.removeProperty('--tt-cap-color'); }
    $('#pkPhone').classList.toggle('land', size === '1920x1080');
    renderSpk();
    $('#pkLookNote').textContent = `左は${size === '1920x1080' ? '横 1920×1080' : '縦 1080×1920'} に置いたときのおおよその見え方(縦に切り取る作業(クロップ)は Resolve で)。字幕の位置・大きさは置き先の大きさに合わせます。フォント「けいふぉんと」はパックに入れません(友人の PC に入れておく。無ければ Windows の日本語フォントになり、マーカーが黄色)`;
    // 見積もりの状態(4-1): 計算中・保存待ち・失敗を見せる(黙って「…」のままにしない)
    const stEl = $('#pkPvState'), busy = P.pv === 'wait' || P.pv === 'run';
    let stMsg = '', stErr = false;
    if (!fresh && sm && sm.count){
      if (busy) stMsg = '字幕の数と注意を計算しています…' + (pv ? '(下の注意は前の設定での見積もりです)' : '');
      else if (P.pv === 'save'){ stMsg = h.S.conflict ? '文字起こしの保存が競合しています。1 文字起こし の映像の上の案内から選ぶと、見積もりを出します' : '文字起こしの保存を待っています(保存できると見積もりを出します)'; stErr = true; }
      else if (P.pv === 'err'){ stMsg = '見積もりを出せませんでした: ' + P.previewErr; stErr = true; }
    }
    stEl.hidden = !stMsg; stEl.querySelector('span').textContent = stMsg; stEl.classList.toggle('err', stErr); stEl.classList.toggle('info', !stErr);
    $('#pkPvRetry').hidden = !(P.pv === 'save' || P.pv === 'err');
    // 作る前の注意(cut2resolve の plan の注意。例: とても短い区間)。見積もりが古い間は前の見積もりの注意を薄く残す(黙って消さない)
    const warns = [];
    if (pv) warns.push(...(pv.warnings || []));
    if (hasRows && pv && pv.vanished) warns.push(`削る区間に入って消える字幕が ${pv.vanished} 件あります(削った行の字幕は入りません)`);
    const w = $('#pkWarn'); w.hidden = !warns.length; w.classList.toggle('old', !fresh);
    w.innerHTML = warns.slice(0, 6).map((x, i) => `<li${/コーデック|H\.264/.test(x) ? ` title="${esc(CODEC_HOW)}"` : ''}>${!fresh && i === 0 ? '<span class="hint">(前の設定での見積もり)</span> ' : ''}${esc(x)}${/コーデック|H\.264/.test(x) ? ` <span class="hint">${esc(CODEC_HOW)}</span>` : ''}</li>`).join('');   // 形式の注意には変換の手段(S10)
    // 作る(前回のパックと同じ場所なら「作り直す(上書き)」= 上書きの確認を出さない。出力先を変えたら新しく作る。段7 E-15)
    const why = staleWhy(), stale = why.length > 0, diffs = P.pack ? outputDiff(P.pack.output, o) : null, differ = !!(diffs && diffs.length);
    const btn = $('#pkBuild');
    btn.disabled = !!b || P.building;
    btn.title = P.building ? 'パックを作っています' : b ? blockMsg(b) : '';   // 押せない理由(A-34。同じ文は上の帯にも出る)
    /* 前回のパックが今の内容のまま(作り直しが要らない)ときは、次の一歩(Resolve で取り込む = 手順を見る)を主に、作り直しは普通のボタンに(UI の見直し S2) */
    const packFresh = !!P.pack && !stale && !differ && !$('#pkDir').value.trim() && !P.building;
    btn.textContent = P.building ? 'パックを作っています…' : packFresh ? '同じ内容で作り直す' : P.pack && !$('#pkDir').value.trim() ? 'パックを作り直す(上書き)' : 'パックを作る';
    btn.classList.toggle('primary', !packFresh); btn.classList.toggle('lg', !packFresh);
    $('#pkReadme').classList.toggle('primary', packFresh);
    const bk = $('#pkBackup'); bk.disabled = !hasRows; if (!hasRows) bk.checked = true;
    bk.title = hasRows ? '' : '字幕が無いパックでは、いつも入ります';
    $('#pkBackupHint').textContent = hasRows ? 'スクリプトが使えないときに、EDL と字幕のファイルで開くための予備。ふだんは要りません'
      : '字幕が無いパックは EDL が本体なので、いつも入ります(Text+ のスクリプトは作りません)';
    $('#pkBuildHint').textContent = P.building ? '' : b ? '' : !hasRows ? '字幕が無いので Text+ は作りません(EDL と元の動画のコピー)' : stale ? `前回のパックのあとに、${why.join('・')}。作り直すと今の内容になります(同じ場所に上書きします)` : differ ? '前回のパックと設定が違います。作り直すと今の設定になります(できているファイルはそのまま)' : '作成中は進み具合と「中止」が出ます';
    const er = $('#pkErr'); er.hidden = !P.err; er.textContent = P.err ? 'パックを作れませんでした: ' + P.err : '';
    $('#pkDir').placeholder = '空欄なら 動画の隣の「' + defaultDirName() + '」';
    renderJob(); renderLast(why, diffs);
    if (P.focusOpen && !P.building){ P.focusOpen = false; const ob = $('#pkOpen'); if (!ob.hidden && ob.offsetParent) ob.focus(); }   // 作り終えたら次に押す所へ(段7 E-11。押したボタンは作っている間は押せず、フォーカスが落ちていた)
    // zip(4-4): 渡らない設定を書く。字幕の無い文書は zip にできない(zip はいつも Text+ あり。契約テストの ZipSkipsContract)
    $('#pkZipNote').textContent = '残す区間(2 カット のタブ)・字幕・予備・fps・大きさ・字幕の文字数・配信者と話者の色は、上の「パックを作る」と同じです。粗編集の動画・音量の調整・開始タイムコード・リール名は zip には入りません(使うのはホームから開いて「パックを作る」)。';
    const skipped = hasRows ? zipSkipped(o) : [], zw = $('#pkZipWarn');
    zw.hidden = !skipped.length && hasRows;
    zw.textContent = !hasRows ? '字幕の無い文書は zip にできません(「パックを作る」で EDL と動画のコピーのパックになります)' : skipped.length ? `今の設定のうち ${skipped.join('・')} は zip に入りません` : '';
    $('#pkZip').disabled = !hasRows; $('#pkZip').title = hasRows ? '' : '字幕の無い文書は zip にできません';
    renderSummaryText(fps, size, hasRows);
  }
  /* 前回の設定の要約(段3。詳しい設定は「設定を変える」の右の欄)。配信者の色の丸は、字幕があるときだけ(無いときは字幕そのものが無いので色も出ない) */
  function renderSummaryText(fps, size, hasRows){
    const bits = [`${fps}fps(1 秒のコマ数)`, size === '1920x1080' ? '横 1920×1080' : '縦 1080×1920'];
    if (hasRows && document.activeElement !== $('#pkBackup')) $('#pkBackup').checked = h.S.settings.packBackup === true;   // 予備は覚える(段4・E-4)。字幕の無いパックは EDL が本体なので入れたまま(render が決める)
    if (hasRows) bits.push($('#pkBackup').checked ? '予備あり' : '予備なし');
    if (document.activeElement !== $('#pkRender')) $('#pkRender').checked = h.S.settings.packRender === true;   // 粗編集の動画つきも覚える(段4 4-2。監査 09。設定は config.json なので別の窓・ブラウザでも同じ)
    if ($('#pkRender').checked) bits.push('粗編集の動画つき');
    bits.push(loudOf() ? `音量 ${loudOf()} LUFS` : `音量 ${volOf()}%`);
    if (!padT && document.activeElement !== $('#pkPadAfter')) $('#pkPadAfter').value = String(padOf());   // 保存を待つ間は書き戻さない
    if (padOf() !== 0.2) bits.push(`行の後の余白 ${padOf()}秒`);   // 既定と違うときだけ(覚えている設定だけを出す。監査 09)
    if (document.activeElement !== $('#pkLoud')) $('#pkLoud').value = String(loudOf());
    if (document.activeElement !== $('#pkVol')) $('#pkVol').value = String(volOf());
    $('#pkVolBox').hidden = loudOf() !== 0;
    $('#pkSummaryText').textContent = bits.join(' ・ ');   // 要約は覚えている物だけ(4-2): 再読み込みの前後で同じになる
    // 出力先は覚えない(09-29 決定: 別の案件へ間違って出さないため)ので要約に入れず、毎回どこに作るかを1行で
    const dir = $('#pkDir').value.trim();
    $('#pkPlace').textContent = dir ? `作る場所(この文書を開いている間だけ): ${dir}` : `作る場所: 動画の隣の「${defaultDirName()}」(毎回ここ。変えるときは下の「詳しく」の出力先。出力先は覚えません)`;
    const color = hasRows ? ($('#pkWho').dataset.color || '') : '', sw = $('#pkSummarySw');
    sw.hidden = !color; if (color) sw.style.background = color;
    sw.title = color ? `配信者の色(${color})` : '';
  }
  function defaultDirName(){ const p = String(h.S.doc && h.S.doc.sourcePath || ''), n = p.split(/[\\/]/).pop() || ''; return n.replace(/\.[^.]*$/, '') + '_pack'; }
  function renderMap(sm){
    const box = $('#pkMap'), keeps = h.CUT && h.CUT.keepsSec();
    if (!sm || !keeps || !sm.durSec){ box.innerHTML = ''; return; }
    const merged = []; for (const [a, b] of keeps){ const l = merged[merged.length - 1]; if (l && a <= l[1] + 1e-6) l[1] = b; else merged.push([a, b]); }
    box.innerHTML = merged.slice(0, 400).map(([a, b]) => `<i style="left:${a / sm.durSec * 100}%;width:${Math.max(0.3, (b - a) / sm.durSec * 100)}%"></i>`).join('');
  }
  /* 前回のパックのあとに変わったこと = 作り直しが要る理由(段7 E-20)。カット(rev が違う・まだ保存していない変更)と字幕(文字起こしの保存 = docUpdatedAt より新しい)。
     出力の設定の違いは outputDiff(札は「設定が違う」・理由は「設定が変わった」)。-> 理由の文の並び(空 = 作り直しは要らない) */
  function staleWhy(){
    const pk = P.pack; if (!pk || !h.CUT) return [];
    const cs = h.CUT.state(), why = [];
    if (pk.rev !== cs.rev || cs.dirty) why.push('カットが変わった');
    if ((Number(h.S.baseUpdatedAt) || 0) > (Number(pk.docUpdatedAt) || 0)) why.push('字幕が変わった');
    return why;
  }
  const isStale = () => staleWhy().length > 0;
  /* 別の場所に前のパックがあるとき(M3。ui-kit の 3 択 UIKit.dialog.choose。以前は画面ごとの #dlgOverwrite)-> 'over'(上書き)| 'other'(別の場所)| null(やめる・Esc) */
  function overwriteChoice(files, dir){
    const list = files.slice(0, 20).map(f => '・' + f).join('\n') + (files.length > 20 ? `\n・ほか ${files.length - 20}件` : '');
    return UIKit.dialog.choose({ title: 'パックを作り直しますか?',
      body: '次のフォルダに、前に作ったパックがあります。作り直すと、中のファイルを上書きします(Resolve に取り込み済みなら、取り込み直してください)。' + (dir ? '\n\n' + dir : '') + (list ? '\n' + list : ''),
      buttons: [{ label: 'やめる', value: null, kind: 'ghost' }, { label: '別の場所を選ぶ', value: 'other' }, { label: '上書きして作り直す', value: 'over', kind: 'danger' }], cancel: null });
  }
  /* 「詳しく」を開いて、その欄へ(上書きの確認の「別の場所を選ぶ」= 出力先。0.62.0 から出力先はカードの「詳しく」の中) */
  function openMoreAt(sel){
    const m = $('#pkMore'); if (m) m.open = true;
    requestAnimationFrame(() => { const el = $(sel); if (el){ el.focus(); if (el.select) el.select(); } });
  }
  const sameDir = (a, b) => { const n = p => String(p || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase(); return !!a && n(a) === n(b); };   // Windows のパス(大文字小文字・区切り)をそろえて比べる
  const KIND = n => /\.(lua|bat|ps1|drb)$|^textplus-import\.json$/i.test(n) ? 'Text+ のスクリプト' : /_roughcut\.mp4$/i.test(n) ? '粗編集の動画' : /\.(edl|srt)$/i.test(n) ? '予備のカット・字幕'
    : /(友人へ|手順)|^cut-plan\.json$/.test(n) ? '手順書・カットの記録' : /\.(mp4|mov|mkv|webm|m4v|avi)$/i.test(n) ? '元の動画のコピー' : 'その他';
  function renderLast(why, diffs){
    const pk = P.pack, box = $('#pkLast');
    box.hidden = !pk; if (!pk) return;
    const differ = !!(diffs && diffs.length), stale = why.length > 0, reasons = why.concat(differ ? ['設定が変わった'] : []);
    const pill = $('#pkLastPill'); pill.className = 'pill ' + (stale || differ ? 'warn' : 'ok'); pill.textContent = stale ? '作り直しが要る' : differ ? '設定が違う' : '前回のパック';
    $('#pkLastWhen').textContent = `${h.ago(pk.at)}${reasons.length ? ` ・ 作り直しが要る理由: ${reasons.join('・')}(「パックを作り直す(上書き)」で同じ場所に作り直します)` : ''}`;   // 段7 E-15・E-20
    const nt = $('#pkLastNotes'); nt.hidden = !P.notes.length; nt.innerHTML = P.notes.map(x => `<li>${esc(x)}</li>`).join('');   // 作ったときの案内(info)
    // 作ったときの出力の設定との違い(4-3。監査 08)。カット・字幕の変更(stale)とは別の文で出す(直す場所が違う)
    const dv = $('#pkLastDiff'); dv.hidden = !(differ || !diffs);
    dv.innerHTML = !diffs ? '<span class="hint">作ったときの設定の記録がありません(この版より前か、まとめて実行で作ったパック)。今の設定との違いは出せません</span>'
      : differ ? `<b>作ったときと違う設定:</b> ${diffs.map(esc).join(' ・ ')}<br><span class="hint">できているファイルは作ったときのまま(変わっていません)。作り直すと今の設定になります</span>` : '';
    const groups = new Map(); for (const n of pk.files || []){ const k = KIND(n); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(n); }
    $('#pkLastFiles').innerHTML = [...groups].map(([k, ns]) => `<div class="tt-pk-file"><span class="mono">${esc(ns.join(' ・ '))}</span><span class="hint">${esc(k)}</span></div>`).join('');
    $('#pkLastDir').textContent = pk.dir || ''; $('#pkLastDir').title = pk.dir || '';
    $('#pkOpen').hidden = !h.c2rBase();
    $('#pkDeliver').hidden = !h.TOKEN;   // 友人へ届ける(入口の api/ytt/deliver)はホームから開いたときだけ
  }
  function renderJob(){
    const box = $('#pkJob'), j = P.job;
    if (!j){ box.hidden = true; box.innerHTML = ''; return; }
    const first = !box.firstChild;
    if (first) box.innerHTML = '<div class="row"><span><span class="pill run">パックを作っています</span> <span class="tt-cp-jmsg"></span></span><span class="mono hint tt-cp-jpct"></span></div><div class="bar"><i></i></div><div class="row" style="justify-content:flex-end"><button type="button" class="btn small" data-act="pkcancel">中止</button></div>';
    box.hidden = false;
    if (first && (document.activeElement === document.body || document.activeElement === $('#pkBuild'))) box.querySelector('[data-act=pkcancel]').focus();   // 押したボタンは作っている間は押せないので、フォーカスは「中止」へ(S18)
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
      const o = outputNow(hasRows);   // 出力の設定は1か所から(4-3)。記録にも同じ物を残す
      const spec = { video: d.sourcePath, keeps: h.CUT.keepsSec(), advanced: o.advanced, ...(path ? { transcript: path } : {}) };
      const out = { textplus: o.textplus, copyVideo: true, render: o.render, backup: o.backup, textplusFps: o.fps, textplusSize: o.size, textplusWrap: o.wrap,
        ...($('#pkDir').value.trim() ? { dir: $('#pkDir').value.trim() } : {}), ...(o.streamer ? { streamer: o.streamer } : {}),
        speakerColors: o.speakerColors, ...(o.speakerStyles ? { speakerStyles: o.speakerStyles } : {}), ...(o.loudness ? { loudness: o.loudness } : o.volume !== 100 ? { volume: o.volume } : {}) };
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
            /* 前回この文書のパックを作った場所(P.pack.dir)への作り直しは確認を省く(段7 E-15)。ほかの物がある場所だけ、何を上書きするかを見せて聞く */
            if (!(P.pack && sameDir(dd.dir, P.pack.dir))){
              const v = await overwriteChoice(dd.files || [], dd.dir || '');
              if (v === 'other'){ openMoreAt('#pkDir'); return; }   // 別の場所: 「詳しく」の出力先へ
              if (v !== 'over'){ setTimeout(() => { const b = $('#pkBuild'); if (!b.disabled && b.offsetParent) b.focus(); }, 150); return; }   // やめた: 押したボタンへ戻す(開いた時の「中止」は消えている。2 周目 N4)
            }
            force = true; continue;
          }
          throw e;
        }
      }
      const files = (res.files || []).map(f => f.name);
      const r = await h.api('/api/edit/pack', { body: { id, rev, docUpdatedAt: Number(docAt) || 0, dir: res.outDir, files, output: o } });
      if (h.S.docId !== id) return;
      P.pack = { rev, at: r.at, docUpdatedAt: Number(docAt) || 0, dir: res.outDir, files: files.map(n => n.split(/[\\/]/).pop()), output: o };
      P.readme = res.readme || ''; P.lastRes = res;
      h.onPacked(id, { rev, at: r.at });
      /* 注意(warn)は今までどおり知らせに(2 件まで)。ただの案内(info。cut2resolve の warningLevels = 「コピーを飛ばしました」など)は知らせに積まず
         「前回のパック」の欄に出す(知らせが重なると、次に作るときの「中止」まで隠していた) */
      const lv = Array.isArray(res.warningLevels) ? res.warningLevels : [], ws = res.warnings || [];
      P.notes = ws.filter((w, i) => lv[i] === 'info').slice(0, 6);
      for (const w of ws.filter((w, i) => lv[i] !== 'info').slice(0, 2)) h.toast(w, 6000);
      const lo = res.loudness, pct = g => Math.round(100 * Math.pow(10, Number(g) / 20)), sg = g => (g >= 0 ? '+' : '') + Number(g).toFixed(1);
      const loudMsg = lo && lo.measured != null ? `音量: ${Number(lo.measured).toFixed(1)} → ${(Number(lo.measured) + Number(lo.gainDb)).toFixed(1)} LUFS(元の約 ${pct(lo.gainDb)}%・${sg(lo.gainDb)} dB${Number(lo.measured) + Number(lo.gainDb) < lo.target - 0.2 ? '。音が割れる・雑音が大きくなるのを避けるため、目標の手前で止めました' : ''})。`
        : lo && lo.volume && lo.gainDb != null ? `音量: 元の ${lo.volume}%(${sg(lo.gainDb)} dB)。` : '';
      const nNote = P.notes.length ? `・案内 ${P.notes.length} 件は「前回のパック」の欄に` : '';
      h.toast(`パックを作りました(残す区間 ${Number(res.summary && res.summary.count) || 0}か所${nNote})。${loudMsg}「Resolve での手順を見る」の手順で取り込みます`,
        { ms: 8000, kind: 'ok', action: h.c2rBase() ? { label: 'フォルダを開く', fn: openFolder } : null });   // 次の一手(段7 E-11)
      P.focusOpen = true;
    } catch (e){
      if (e.code === 'cancelled') h.toast('パック作りを中止しました', 3000);
      else if (e.code !== 'switched') P.err = e.code === 'busy' ? 'cut2resolve で別の処理が動いています。終わってから、もう一度押してください' : e.message;
    } finally { P.building = false; P.job = null; render(); }
  }

  /* ---------- イベント ---------- */
  /* 「設定を変える」= ⚙ の設定の引き出し(UIKit.settings)を開いて「パック」の節へ(0.62.0。以前はパックのタブの中の右の欄) */
  $('#pkSettingsBtn').addEventListener('click', e => {
    const d = $('#uiSettingsDrawer'); if (!d) return;
    UIKit.drawer.open(d, { modal: true, opener: e.currentTarget });
    requestAnimationFrame(() => { const sec = $('#edSetPack'); if (sec) sec.scrollIntoView({ block: 'start' }); });
  });
  function setOpt(key, v){ saveLoud({ [key]: v }); }   // パックの出力は「送ったキーだけ直す」API で(まとめて実行の欄と同じ値。段4)
  $('#pkSize').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) setOpt('packSize', b.dataset.v); });
  /* 行の後の余白(段6 6-2・B-1): 設定 rowEdge.padAfter(規則は cut2resolve の pack.py row_edge_from。「行から」のたたき台・zip・まとめて実行に効く。変える入口はここ1か所) */
  let padT = 0;
  $('#pkPadAfter').addEventListener('change', () => { const raw = $('#pkPadAfter').value; clearTimeout(padT); padT = setTimeout(() => { padT = 0; savePad(raw); }, 800); });   // 打つたびに「行から」を作り直さない(無音の検出は重い)。値はそのとき読む(待つ間に render が欄を書き戻すため)
  async function savePad(rawText){
    const raw = Number(rawText), before = padOf();
    if (!Number.isFinite(raw) || raw < 0 || raw > 2){ h.toast('行の後の余白は 0〜2 秒で入れてください', 4000, 'err'); $('#pkPadAfter').value = String(before); return; }
    const v = Math.round(raw * 100) / 100;
    if (v === before) return;
    const cur = h.S.settings.rowEdge && typeof h.S.settings.rowEdge === 'object' ? h.S.settings.rowEdge : { on: h.S.settings.rowEdge !== false, after: 0.5, before: 0.3 };
    h.S.settings.rowEdge = { ...cur, padAfter: v };
    try { await h.putSettings(); }
    catch (e){ h.S.settings.rowEdge = cur; $('#pkPadAfter').value = String(before); h.toast('設定を保存できませんでした: ' + e.message, { kind: 'err', ms: 10000, action: { label: 'もう一度', fn: () => savePad(String(v)) } }); return; }   // [もう一度](S27)   // 保存できなければ欄も元へ(zip・まとめて実行は保存済みの設定を読む)
    const redo = h.CUT && h.CUT.redraftPristine ? h.CUT.redraftPristine() : false;
    $('#pkPadAfterNote').textContent = redo ? '「行から」のたたき台を作り直します(区間の終わりが変わります)' : '手で直したカットには効きません。2 カット の「行から」でたたき台を作り直すと効きます(zip と、まとめて実行で「行から」を選んだときには効きます)';
    render();
  }
  $('#pkBuild').addEventListener('click', build);
  $('#pkBackup').addEventListener('change', () => saveLoud({ packBackup: $('#pkBackup').checked }));
  $('#pkRender').addEventListener('change', () => saveLoud({ packRender: $('#pkRender').checked }));   // 覚える(4-2)
  $('#pkPvRetry').addEventListener('click', () => { P.pvErrKey = ''; schedulePreview(0); });
  $('#pkLoud').addEventListener('change', () => saveLoud({ packLoudness: Number($('#pkLoud').value) }));
  $('#pkVol').addEventListener('change', () => { const v = Math.round(Number($('#pkVol').value)); if (v >= 1 && v <= 200) saveLoud({ packVolume: v }); else { h.toast('音量(%)は 1〜200 で入れてください', 4000, 'err'); render(); } });
  $('#pkDir').addEventListener('input', render);
  // 開始タイムコードに ; 区切り(ドロップフレーム表記)を入れたら、その場で「ノンドロップとして扱う」と知らせる(作るときの結果の注意は今までどおり)
  for (const id of ['pkSrcTc', 'pkRecTc']){
    const inp = $('#' + id), hint = $('#' + id + 'Hint');
    const upd = () => { hint.hidden = !inp.value.includes(';'); };
    inp.addEventListener('input', upd); inp.addEventListener('change', upd); upd();
  }
  $('#pkJob').addEventListener('click', async e => {
    if (!e.target.closest('[data-act=pkcancel]') || !P.job) return;
    try { await h.c2rApi('api/job/cancel', { body: { id: P.job.id } }); } catch (er){ h.toast(er.message, 4000, 'err'); }
  });
  async function openFolder(){   // 前回のパックのフォルダ(「フォルダを開く」と、作り終えた知らせのボタン)
    if (!P.pack) return;
    try { await h.c2rApi('api/open-folder', { body: { path: P.pack.dir } }); } catch (er){ h.toast('フォルダを開けませんでした: ' + er.message, 5000, 'err'); }
  }
  $('#pkOpen').addEventListener('click', openFolder);
  /* 友人へ届ける: パックのフォルダを zip にして Dropbox の 出力 に置く(入口の api/ytt/deliver → home/deliver.py。① 全自動と同じ作り方)。
     友人のアプリの「受け取る」に出る = 外へ出す操作なので確認してから。数 GB の zip は時間がかかるので、仕事の状態を聞き直す */
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  function deliverMsg(text, tone){ const m = $('#pkDeliverMsg'); m.hidden = !text; m.textContent = text || ''; m.className = 'hint' + (tone ? ' tt-pk-dl-' + tone : ''); }
  $('#pkDeliver').addEventListener('click', async () => {
    const pk = P.pack, b = $('#pkDeliver'); if (!pk || !pk.dir || b.disabled) return;
    const title = String(h.S.doc && h.S.doc.title || '').trim();
    const ok = await UIKit.dialog.confirm({ title: '友人へ届けますか', ok: '届ける',
      body: `このパックを zip にして Dropbox の「出力」に置きます。同期が終わると、友人の送るアプリの「受け取る」に「${title || 'パック'}」として出ます。`
        + (isStale() ? ' 注意: カットか字幕が、パックを作ったあとに変わっています。今の内容で届けるなら、先にパックを作り直してください。' : '') });
    if (!ok) return;
    b.disabled = true; deliverMsg('zip にしています…');
    try {
      let j = (await h.api('/api/ytt/deliver', { body: { op: 'start', dir: pk.dir, title } })).job;
      while (j.state === 'running'){
        deliverMsg(`${j.message}…${j.progress ? ' ' + Math.round(j.progress * 100) + '%' : ''}`);
        await sleep(1000);
        j = (await h.api('/api/ytt/deliver', { body: { op: 'status', job: j.id } })).job;
      }
      if (j.state === 'done'){ deliverMsg(`${j.message}(${j.name})`, 'ok'); h.toast('友人へ届けました(Dropbox の 出力 に置きました)', 5000, 'ok'); }
      else { deliverMsg(j.message, 'err'); h.toast(j.message, 7000, 'err'); }
    } catch (e){ deliverMsg('届けられませんでした: ' + e.message, 'err'); h.toast('届けられませんでした: ' + e.message, 7000, 'err'); }
    finally { b.disabled = false; }
  });
  $('#pkCopy').addEventListener('click', async () => {
    if (!P.pack) return;
    h.copyPath(P.pack.dir || '');
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
    if (!(await h.savedAll())) return;
    const b = $('#pkZip'), label = b.textContent; b.disabled = true; b.textContent = '作成中…';
    try {
      const r = await h.apiBlob('/api/resolve-package', { tid: h.S.docId, fps: fpsOf(), size: sizeOf(), backup: $('#pkBackup').checked, wrap: wrapOf(),
        ...(whoOf() ? { streamer: whoOf() } : {}), speakerColors: $('#pkSpk').checked });
      h.download(await r.blob(), `${h.safeName(h.S.doc.title)}-resolve.zip`);
      const cuts = r.headers.get('X-Resolve-Cuts') || '?', caps = r.headers.get('X-Resolve-Captions') || '?';
      h.toast(`パック(zip)を作成しました(残す区間${cuts}か所・Text+ ${caps}件)。zip を展開して、フォルダの bat でスクリプトを登録してから Resolve で実行します`, 8000, 'ok');
    } catch (e){ h.toast('パック(zip)を作れませんでした: ' + e.message, 7000, 'err'); }
    finally { b.disabled = false; b.textContent = label; }
  });

  return {
    load,
    shown(){   // 2 カット を開いたとき(帯の場面はカットのものなので触らない。0.62.0)
      if (h.S.doc){ render(); schedulePreview(0); }
      h.api('/api/settings').then(st => {   // パックの音量はほかの画面(まとめて実行の欄)でも変えられるので、開くたびに読み直す
        const keys = ['packLoudness', 'packVolume', 'packSize', 'speakerColors', 'packBackup', 'packRender'];   // ほかの画面(まとめて実行の欄)でも変えられる値
        if (st && keys.some(k => st[k] !== h.S.settings[k])){ for (const k of keys) h.S.settings[k] = st[k]; if (h.S.doc) render(); h.onSpeakerColors(); }
      }, () => {});
    },
    changed(){ if (P.pv === 'save') P.pvErrKey = ''; render(); if (h.tab() === 'cut') schedulePreview(); else { P.previewKey = ''; } },
    refreshWho(){ if (h.S.docId) UIKit.streamer.autoFill($('#pkWho'), { docId: h.S.docId }); },   // 題名の行で配信者を直したあと(隠した欄を入れ直す。0.62.0)   // カット・文字起こしが変わった(保存できたときも来る → 保存待ちを解く)
    refresh: render,
    state: () => ({ building: P.building, pack: P.pack })
  };
}
window.EditPack = { create };
})();
