/* app-rows.js — 「編集」の画面: 編集画面(保存・開く・行の描画と操作)・字幕の文字数・行の移動・話者の色・キー配置・用語の挿入・履歴・行の追加(段10 で app.js から分けた。docs/plan/phase10-code-split.md)。
   ここは関数の定義だけ。状態(S・V など)・定数・ボタンの配線・起動は app.js(この後に読む)。
   関数はトップレベルの宣言なので、ほかの app-*.js・app.js から名前で呼べる(読む順番は index.html の1か所) */
'use strict';

/* ---------- 編集画面 ---------- */

function spById(id){ return S.doc && S.doc.speakers.find(s => s.id === id); }

function markDirty(){
  if (CUT){ clearTimeout(markDirty.c); markDirty.c = setTimeout(() => CUT.docChanged(), 300); }
  S.dirty = true; setSaveState(S.conflict ? '競合しています' : '未保存…', S.conflict ? 'err' : '');
  clearTimeout(markDirty.t); markDirty.t = setTimeout(saveDoc, 700);
}

/* 保存の状態の表示。kind: ''(未保存)/ 'busy'(保存中)/ 'ok'(保存済み)/ 'err'(競合・失敗)。色の印は CSS の [data-state] */
function setSaveState(text, kind){ const el = $('#saveState'); el.textContent = text; el.setAttribute('data-state', kind || ''); updateDocTitle(); }

function saveDoc(){
  clearTimeout(markDirty.t);
  if (docSaveP) return docSaveP;   // 文書を切り替える側も、実行中の保存が終わるまで待つ
  if (S.conflict) return Promise.resolve(false);
  if (!S.doc || !S.dirty) return Promise.resolve(true);
  S.saving = true;
  const run = async () => {
    while (S.doc && S.dirty){   // 保存を待っている間に編集された分も、順番に保存する
      S.dirty = false; setSaveState('保存中…', 'busy');
      for (const g of S.doc.segments) if (g.draft && String(g.text || '').trim()) delete g.draft;   // 文字の入った下書きの印は保存しない(入力のほかの道 = 提案の採用・置換などで文字が入ったとき)
      const id = S.docId, force = S.forceNext;
      const body = { title: S.doc.title, evalSet: S.doc.evalSet === true, speakers: S.doc.speakers, segments: S.doc.segments, baseUpdatedAt: S.baseUpdatedAt, ...(force ? { force: true } : {}) };
      try {
        const r = await api('/api/transcript?id=' + encodeURIComponent(id), { method: 'PUT', body });
        if (S.docId !== id) return false;
        S.baseUpdatedAt = r.updatedAt; S.forceNext = false;
        if (r.evalSet === true && !S.doc.evalSet){ S.doc.evalSet = true; syncEval(); }   // 評価用のフォルダの動画はサーバーが印を付ける
        if ('evalReviewed' in r && !!r.evalReviewed !== !!S.doc.evalReviewed){ S.doc.evalReviewed = r.evalReviewed || undefined; renderEvalReview(); renderDrillBar(); }   // 評価用を外すと確かめ済みの印も消える(サーバー)
        if (S.dirty) setSaveState('未保存…', ''); else setSaveState('保存しました ' + hhmm(), 'ok');
        scheduleLearn(); scheduleAcc(); scheduleProgress(); S.arcDirty = true; renderDataset();
        syncListItem(); cpAfterSave(); ovdAfterSave();
      } catch (e){
        if (S.docId !== id) return false;   // 保存を待つ間に文書が閉じられた(削除など)。閉じた文書の「未保存」を残さない
        S.dirty = true;
        if (e.code === 'conflict'){ S.conflict = true; $('#conflictBar').hidden = false; setSaveState('競合しています', 'err'); toast('別の場所で先に更新されています。映像の上の案内から選んでください', 6000, 'err'); if (CUT) CUT.refresh(); }   // 2 カット の字幕の段にも出す(段6 6-6)
        else { setSaveState('保存できません(5秒後にもう一度試します)', 'err'); toast('保存に失敗: ' + e.message, 3800, 'err'); clearTimeout(markDirty.t); markDirty.t = setTimeout(saveDoc, 5000); }
        return false;
      }
    }
    return !S.conflict;
  };
  docSaveP = run().finally(() => { S.saving = false; docSaveP = null; });
  return docSaveP;
}

/* ---------- 字幕の文字数(docs/design/edit-tool-design.md の 12 ②。設定の subtitle。範囲の確認はサーバーの subtitle_settings と同じ) ---------- */

function subNum(v, lo, hi, dv){ const n = Math.round(Number(v)); return Number.isFinite(n) && n >= lo && n <= hi ? n : dv; }

function readSubtitle(){
  const d = SUB_DEFAULT;
  return { orientation: $('#optSubOrient').value === 'horizontal' ? 'horizontal' : 'vertical',
    maxChars: { vertical: subNum($('#optMaxV').value, 4, 80, d.maxChars.vertical), horizontal: subNum($('#optMaxH').value, 4, 80, d.maxChars.horizontal) },
    wrapChars: { vertical: subNum($('#optWrapV').value, 2, 40, d.wrapChars.vertical), horizontal: subNum($('#optWrapH').value, 2, 40, d.wrapChars.horizontal) } };
}

function fillSubtitle(v){
  const d = SUB_DEFAULT, o = v && typeof v === 'object' ? v : {}, m = o.maxChars || {}, w = o.wrapChars || {};
  $('#optSubOrient').value = o.orientation === 'horizontal' ? 'horizontal' : 'vertical';
  $('#optMaxV').value = subNum(m.vertical, 4, 80, d.maxChars.vertical); $('#optMaxH').value = subNum(m.horizontal, 4, 80, d.maxChars.horizontal);
  $('#optWrapV').value = subNum(w.vertical, 2, 40, d.wrapChars.vertical); $('#optWrapH').value = subNum(w.horizontal, 2, 40, d.wrapChars.horizontal);
  renderResplitOpts();
}

/* 文字起こし・範囲の再認識の要求に付ける(設定の保存は少し遅れて送られるので、今の欄の値を直接渡す) */
function subtitleReq(){ const v = readSubtitle(); return { subtitleOrientation: v.orientation, splitChars: v.maxChars[v.orientation] }; }

function renderResplitOpts(){
  const v = readSubtitle(), sel = $('#rsOrient'), cur = sel.dataset.touched ? sel.value : v.orientation;
  sel.options[0].textContent = `縦(最大 ${v.maxChars.vertical} 文字)`; sel.options[1].textContent = `横(最大 ${v.maxChars.horizontal} 文字)`; sel.value = cur;
}

async function resplitDoc(){
  if (!S.docId || lockJob()) return;
  if (!(await saveDoc())) return toast('保存が終わっていません。少し待ってから、もう一度押してください', 5000, 'err');
  const b = $('#rsGo'), msg = $('#rsMsg'), id = S.docId, o = $('#rsOrient').value;
  b.disabled = true; msg.textContent = '分けています…';
  try {
    const r = await api('/api/resplit', { body: { id, orientation: o, splitChars: readSubtitle().maxChars[o], ...(Number.isInteger(S.baseUpdatedAt) ? { baseUpdatedAt: S.baseUpdatedAt } : {}) } });
    if (S.docId !== id) return;
    if (!r.changed){ msg.textContent = r.skipped ? `分ける行はありませんでした(人が直した長い行 ${r.skipped} 行は分けていません)` : '分ける行はありませんでした'; return; }
    await openDoc(id, true);
    msg.textContent = `${r.changed} 行を分けました(${r.added} 行増えました)`;
    toast(`${r.changed} 行を分けました(${r.added} 行増えました)。元に戻すときは「以前の版に戻す」`, 7000, 'ok');
  } catch (e){ msg.textContent = ''; toast('分け直せませんでした: ' + e.message, 8000, 'err'); }
  finally { b.disabled = false; }
}

async function openDoc(id, keep){
  const request = ++docOpenSeq;
  if (!(await saveDoc()) || request !== docOpenSeq) return false;
  if (CUT && S.docId && S.docId !== id && !(await CUT.flush())){   // 前の文書のカットを保存してから切り替える
    toast('カットを保存できないため、切り替えませんでした(カットのタブの案内を見てください)', 6000, 'err'); return false;
  }
  if (request !== docOpenSeq) return false;
  const previousDoc = S.doc, previousVersion = S.baseUpdatedAt;
  if (!keep && S.docId && S.docId !== id){
    autoArchive(S.docId);   // 別の文字起こしに移るときに、それまでの分を保管する
    const prev = S.docId; setTimeout(() => evalSettle(prev), 1500);   // 評価用の仮置きの動画なら、条件を満たせばメンバーのフォルダへ(再生が切り替わってから)
  }
  const navId = keep ? navSnapshot() : null;   // keep=true(再認識・話者判別が終わっての読み直しなど)は、見ていた行を id で覚えておく
  const scrollY = window.scrollY;
  let d; try { d = await api('/api/transcript?id=' + encodeURIComponent(id)); } catch (e){ toast(e.message); return false; }
  if (request !== docOpenSeq) return false;
  if (S.doc !== previousDoc || S.dirty || S.saving || S.conflict || S.baseUpdatedAt !== previousVersion){
    toast('読み込み中に編集されたため、現在の内容を保持しました。もう一度開いてください'); return false;
  }
  const sameDoc = S.docId === id;
  if (!sameDoc) effortStart(id);   // 前の文書の校正の手間を送ってから、この文書で数え始める(Q2)
  S.doc = d; S.docId = id; S.undo = []; S.sug = []; S.alt = null; S.sel = new Set(); S.curIdx = -1; S.dirty = false; S.conflict = false; S.forceNext = false; S.baseUpdatedAt = d.updatedAt || null; $('#conflictBar').hidden = true;
  if (!keep) S.navIdx = -1; else navRestore(navId, S.navIdx);
  const pos = keep ? null : loadPos(id), resumeIdx = pos ? d.segments.findIndex(x => x.id === pos.id) : -1;
  $('#noDoc').hidden = true; $('#doc').hidden = false;
  let autoClosed = false;   // 画面が狭いとき(メニューを開いたままだと一覧が細くなる)は、文字起こしを開いた時点でメニューを閉じる
  if (!keep && V.menu && ($('.editor').clientWidth < 1300 || (window.matchMedia && matchMedia(OVERLAY_MID).matches))){ toggleMenu(false); autoClosed = true; }   // 重ねて開く幅(B-7)では、選んだら閉じて本文を見せる   // 1300: 1440px の画面でメニューを開いたままだと、映像・行が細くなるため(2026-09-27。以前は 1000)
  $('.app').classList.add('has-doc');   // 文字起こしを開いている間は、メニューを少し細く(GPT 版)
  /* 並べて出すメニュー(1600px 以上)の履歴から開いたら、フォーカスをメニューの外へ(メニューの中のキーは文書を動かさないので、開いてすぐ ↓・S が効くように。3-1) */
  if (!keep && menuOpen() && !isDrawer() && document.activeElement && $('#menuPanel').contains(document.activeElement)) document.activeElement.blur();
  if (wideTab() && EDT.overlay){ EDT.overlay = false; applyView(); }   // カット・パックのタブで、帯から開いたメニューで選んだ → 閉じてタイムラインを見せる
  $('#docTitle').value = d.title || ''; setSaveState('', ''); syncEval(); renderDocExtras(d);
  { const pr = d.params || {}; $('#docInfo').textContent = `認識の設定: ${String(d.model || '').split('/').pop()}${pr.device ? ' / ' + devLabel(pr.device) : ''} / ${{ weak: '声の検出: 弱め', normal: '声の検出: 標準', off: '声の検出: なし' }[pr.vadMode] || (pr.vad === false ? '声の検出: なし' : '声の検出: 標準')}${pr.vadUsed && pr.vadMode && pr.vadUsed !== pr.vadMode ? '→' + ({ weak: '弱め', normal: '標準', off: 'なし' }[pr.vadUsed] || '') + '(捨てすぎたので自動で緩めた)' : ''}${pr.boost ? ' / 音量補正あり' : ''}${pr.beam === 1 ? ' / 速度優先' : ''}${d.diarization ? ' / 話者判別: ' + d.diarization.found + '人(' + (d.diarization.requested ? '指定' + d.diarization.requested + '人' : '人数は自動') + ', ' + ({ voxceleb: 'VoxCeleb', campplus: 'CAM++', standard: 'ERes2Net' }[d.diarization.embedding] || 'ERes2Net') + ')' : ''}${pr.dictApplied ? ' / 辞書を自動適用(' + pr.dictApplied + '箇所)' : ''}${pr.learnApplied ? ' / 学習済みの置換を自動適用(' + pr.learnApplied + '箇所)' : ''}${(pr.glossAuto || []).length ? ' / 用語を自動追加: ' + pr.glossAuto.slice(0, 5).join('、') + (pr.glossAuto.length > 5 ? ' ほか' : '') : ''}${d.retranscribed ? ' / ' + (d.retranscribed.whole ? '全体を再認識' : '再認識') + ': ' + String(d.retranscribed.model).split('/').pop() + '(' + d.retranscribed.lines + '行)' : ''}`; }
  if (!keep || !sameDoc) S.playerErr = null;
  renderPlayerMsg();
  const p = player();
  if (!keep){   // 話者判別のあとの読み直しでは、再生位置をそのままにする
    /* 読み込みに失敗した動画の loadedmetadata は来ないので、前の文書の待ち受けが残っていると、次に開いた文書の動画で
       前の文書の位置へ飛んでしまう。開くたびに番号を振り、最新の文書の待ち受けだけが働くようにする */
    const mediaSeq = S.mediaSeq = (S.mediaSeq || 0) + 1;
    p.addEventListener('loadedmetadata', () => { if (mediaSeq !== S.mediaSeq) return; p.playbackRate = Number(V.rate); if (resumeIdx >= 0) p.currentTime = d.segments[resumeIdx].start; else if (!d.whole && d.start > 0) p.currentTime = d.start; }, { once: true });
    p.src = apiUrl('/media?id=' + encodeURIComponent(id));
    $('#q').value = ''; $('#flagKind').value = '';
  }
  if (CUT){ if (!keep || !sameDoc) CUT.load(id); else CUT.docChanged(); }
  if (PACK && (!keep || !sameDoc)) PACK.load(id);   // 前回のパック(編集の内容の pack)を読む   // カット(編集の内容)を読む。話者判別・再認識のあとの読み直しでは、行の印だけ付け直す
  lookupSpeakerNames((d.speakers || []).map(s => s.name));   // 話者の色: 名前をまとめて1回で照らし合わせる(行ごとに通信しない。段2)
  renderDocBar(); renderDoc(); renderList(); updateUndo(); applyLock(); loadSuggest(); renderAb(); loadEvals(); renderTerms(); renderDataset(); $('#hiList').innerHTML = ''; txKeybarScene();
  if (!keep || !sameDoc){ renderDocAuto(PICK.lastRuns || []); $('#docAuto').open = false; if (window.UIKit && UIKit.streamer) UIKit.streamer.autoFill($('#docAutoWho'), { docId: id }); }   // 覚えた名前 → チャンネル名から(段5)   // 題名の行のまとめて実行の札は、開いた文書のもの
  if (keep) window.scrollTo(0, scrollY);
  else if (resumeIdx >= 0){ setNav(resumeIdx); const row = rowsEl()[resumeIdx]; if (row) row.scrollIntoView({ block: 'center' }); toast(`前回の続き(${fmtT(d.segments[resumeIdx].start)} の行)に移動しました。先頭から見るには、上へスクロールしてください`, 5000); }
  else window.scrollTo(0, 0);
  if (autoClosed && resumeIdx < 0 && !isDrawer() && !S.menuToldOnce){ S.menuToldOnce = true; toast('編集欄を広くするため、メニューを閉じました(左上の「メニューを開く」か G で開けます)', 4000); }   // 知らせるのはこの画面を開いている間に1回だけ(毎回だとうるさい。段3-3)
  setUrlDoc(id);   // 再読み込み・窓の開き直しで同じ文書に戻る(監査 06)
  loadOvd(id);     // 重なりの所の空の行の候補の数(話者のカードに出す。話者判別のあとの読み直しでも数え直す)
  return true;
}

/* 開いている文書を URL の ?doc= に残す(監査 06)。replaceState にする: pushState にすると、戻るボタンで文書を行き来させたときに
   未保存の保存・カットの flush と戻る操作がぶつかる(replace なら今の保存の順番のまま)。タブの # はそのまま */
function setUrlDoc(id){
  try {
    const q = new URLSearchParams(location.search);
    if (id) q.set('doc', id); else q.delete('doc');
    const rest = q.toString(), url = location.pathname + (rest ? '?' + rest : '') + location.hash;
    if (url !== location.pathname + location.search + location.hash) history.replaceState(history.state, '', url);
  } catch {}
}

/* 話者の選択肢: 話者なし → 組み込みの「ゲーム音声など」(文書に無くても常に出す・固定の位置)→ 文書の話者(番号の順) */
function opts(sel){
  return '<option value="">話者なし</option>' + `<option value="${esc(OTHER_SP.id)}"${sel === OTHER_SP.id ? ' selected' : ''}>${esc(OTHER_SP.name)}</option>`
    + numberedSpeakers().map(s => `<option value="${esc(s.id)}"${s.id === sel ? ' selected' : ''}>${esc(s.name)}</option>`).join('');
}

/* ---------- 組み込みの話者「ゲーム音声など」と、行の印「字幕に出さない」(noSub。2026-10-05) ---------- */

/* 番号の付く話者(Alt+数字・数字キー・話者の欄の「・ n」)= 組み込みの話者を除いた並び。今までの番号は変えない */
function numberedSpeakers(){ return S.doc ? S.doc.speakers.filter(s => !isOtherSp(s)) : []; }

/* 話者を足す(組み込みの話者はいつも最後に置く = 足した人の番号がずれない) */
function addSpeaker(sp){ const g = S.doc.speakers, k = g.findIndex(isOtherSp); if (k >= 0) g.splice(k, 0, sp); else g.push(sp); }

/* 行の話者を変える(1 か所: 行の欄・Alt+数字・数字キー・まとめて・話者の削除)。「ゲーム音声など」を選ぶと文書の speakers に 1 つだけ足し、
   その行の「字幕に出さない」をオン。「ゲーム音声など」から別の話者(話者なしを含む)へ変えたらオフ。row があればその行の見た目も合わせる */
function setSegSpeaker(s, id, row){
  id = id || '';
  const was = s.speaker === OTHER_SP.id;
  if (id === OTHER_SP.id && !S.doc.speakers.some(isOtherSp)) S.doc.speakers.push({ id: OTHER_SP.id, name: OTHER_SP.name, color: OTHER_SP.color, builtin: OTHER_SP.builtin });
  s.speaker = id;
  if (id === OTHER_SP.id) s.noSub = true; else if (was) delete s.noSub;
  if (row){ const sel = row.querySelector('.spk'); if (sel) sel.value = id; setRowSp(row, spById(id)); paintNoSub(row, s); }
  const i = S.doc.segments.indexOf(s); if (row && i >= 0) markOvl(i);   // 重なりの赤は話者で変わる(別の話者どうし・字幕に出さない行は赤くしない)
  if (row){ renderNoSubCount(); updateCaption(); }
}

/* 行の「字幕に出さない」を切り替える(行のボタン・右クリックのメニュー)。どの話者の行でも使える(NPC のセリフを出したい・独り言を出したくない) */
function setNoSub(s, on, row){
  if (on) s.noSub = true; else delete s.noSub;
  if (row) paintNoSub(row, s);
  const i = S.doc.segments.indexOf(s); if (i >= 0) markOvl(i);   // 字幕に出さない行との重なりは赤くしない
  updateCaption(); renderNoSubCount();
  if (CUT && CUT.refreshCaption) CUT.refreshCaption();
}

function paintNoSub(row, s){
  row.classList.toggle('nosub', !!s.noSub);
  const b = row.querySelector('[data-act=nosub]'); if (b) b.setAttribute('aria-pressed', s.noSub ? 'true' : 'false');
}

/* ---------- 重なり・抜けの所に置いた空の行(行の印 draft。2026-10-05。置く・消すは app-jobs.js の ovd*) ----------
   draft = 機械が置いた下書きで、まだ人が打っていない印(サーバーの ed_state.ROW_DRAFT_KINDS = DRAFT_KINDS。overlap = 重なり・missing = 抜け)。文字を打ったら外す(clearDraftMark・保存の前にも)。
   空のままの行は字幕・カット・パックに出ない(文字の無い行は今も数えない)・重なりの赤にしない。決まりは種類によらず同じで、札と案内の文だけ変える */
const DRAFT_NAME = { overlap: '重なり', missing: '抜け' };
const draftName = g => DRAFT_NAME[g && g.draft] || DRAFT_NAME.overlap;
const draftPh = g => `聞いて打ってください(${draftName(g)}の下書き。打つと札が外れます。要らなければ「削除」)`;
const draftTitle = g => (g && g.draft === 'missing' ? '話者の判別で声が見つかったのに、どの行も無かった所に置いた空の行です(認識が落としたかもしれない所)。'
  : '話者の判別で声が見つかったのに行が無かった所(声が重なっている所)に置いた空の行です。') + '聞いて文字を打ってください。空のままなら字幕・カット・パックに出ません';
function isBlankDraft(g){ return !!g && DRAFT_KINDS.includes(g.draft) && !String(g.text || '').trim(); }
function blankDrafts(){ return S.doc ? S.doc.segments.filter(isBlankDraft) : []; }

/* 文字が入った下書きの印を外す(行の文字の入力から)。札・placeholder・重なりの赤・「空のままを消す」の数を合わせる */
function clearDraftMark(s, row){
  if (!s.draft || !String(s.text || '').trim()) return;
  delete s.draft;
  if (row){
    row.classList.remove('tt-draft');
    const p = row.querySelector('.tt-draft-pill'); if (p) p.remove();
    const ta = row.querySelector('textarea'); if (ta) ta.placeholder = '(空の行)文字を入力。不要なら「削除」';
  }
  const i = S.doc.segments.indexOf(s); if (i >= 0) markOvl(i);
  renderOvd();
}

/* 字幕に出さない行の数(書き出しのカード・3 パック の「これから作るパック」に出す。0 なら出さない) */
function noSubCount(){ return S.doc ? S.doc.segments.filter(g => g.noSub && String(g.text || '').trim()).length : 0; }
function renderNoSubCount(){
  const n = noSubCount(), el = $('#exNoSub');
  if (el){ el.hidden = !n; el.textContent = n ? `字幕に出さない行: ${n} 行(SRT・VTT・パックの字幕に入りません。テキスト・JSON には入ります)` : ''; }
  if (PACK) PACK.refresh();
}

/* 話者の字幕の色(sub.color。"#RRGGBB" か '')。文書の JSON は手で直せるので形を確かめる(style 属性に入れるため) */
function subColorOf(sp){ const c = sp && sp.sub && typeof sp.sub === 'object' ? String(sp.sub.color || '') : ''; return /^#[0-9a-fA-F]{6}$/.test(c) ? c.toUpperCase() : ''; }
function setSubColor(sp, hex){
  const sub = { ...(sp.sub && typeof sp.sub === 'object' ? sp.sub : {}) };
  if (hex) sub.color = hex.toUpperCase(); else delete sub.color;
  if (Object.keys(sub).length) sp.sub = sub; else delete sp.sub;
}
/* 字幕の色の欄に打った文字 → 16 進だけ(貼り付けた # や空白は外す)・大文字・6 文字まで */
function subHexInput(v){ return String(v || '').replace(/[^0-9a-fA-F]/g, '').toUpperCase().slice(0, 6); }

/* 行どうしの時刻の重なりを赤くして知らせる(2026-10-05: 同じ話者どうしのときだけ)。
   両方に話者があって別の人なら赤くしない(同時にしゃべっている = 正しい入力。字幕は上下に積んで両方出る)。同じ話者・どちらかに話者が無いときは今までどおり赤。
   字幕に出さない行(noSub)との重なりも赤くしない。
   時刻の欄は 0.1 秒までしか見せない(UIKit.timebox の丸めと同じ Math.round(x*10))ので、見えている時刻で重なっていなければ赤くしない。
   必ず真偽値を返す(markOvl の classList.toggle に undefined を渡すと「付け外しの反転」になり、前後に行の無い先頭・最後の行が押すたびに赤白を繰り返した) */
const t10 = x => Math.round((Number(x) || 0) * 10);
const overlaps = (a, b) => !!a && !!b && t10(a.end) > t10(b.start);   // a の終わりが、次の行 b の始まりより(見える時刻で)後ろ
const badOverlap = (a, b) => overlaps(a, b) && !a.noSub && !b.noSub && !isBlankDraft(a) && !isBlankDraft(b) && !(a.speaker && b.speaker && a.speaker !== b.speaker);   // 重なりの下書き(空の行)は、重なる所に置いたものなので赤くしない(打ったら今までどおり)
const OVL_BACK = 8;   // 前の行は 8 行前まで見る(別の話者の行をはさんで、同じ話者の長い行と重なることがあるため。全部は見ない = 4000 行でも重くしない)
const OVL_TITLE = '同じ話者の行(か、話者の無い行)と時刻が重なっています。別の人が同時に話しているなら、それぞれの行に話者を付けると赤くなくなります';
function ovl(i){
  const g = S.doc.segments, s = g[i]; if (!s) return false;
  for (let j = i - 1; j >= 0 && j >= i - OVL_BACK; j--) if (badOverlap(g[j], s)) return true;
  for (let k = i + 1; k < g.length && t10(g[k].start) < t10(s.end); k++) if (badOverlap(s, g[k])) return true;
  return false;
}

/* 行 i と、重なりうる前後の行の印を付け直す(描き直さずに時刻だけ直した経路 = 微調整・時刻の欄の確定が通る。描き直す経路は segHTML が付ける) */
function markOvl(i){
  const g = S.doc.segments, s = g[i]; let hi = Math.min(g.length - 1, i + OVL_BACK);   // 終わりを早めたときに、前は重なっていた後ろの行も外す
  if (s) while (hi + 1 < g.length && t10(g[hi + 1].start) < t10(s.end)) hi++;
  for (let j = Math.max(0, i - OVL_BACK); j <= hi; j++){ const r = rowsEl()[j]; if (r && r.classList && r.classList.contains('seg')){ const t = r.querySelector('.times'); const o = ovl(j); t.classList.toggle('ovl', o); if (o) t.title = OVL_TITLE; else t.removeAttribute('title'); } }
}

/* 行 i の開始(f='start')か終了('end')を直したあと、隣の行の境目(開始なら前の行の終了・終了なら次の行の開始)と、見える時刻(0.1 秒)が同じなら、
   隣の値にぴったりそろえる(見えない 0.01 秒の隙間・重なりを残さない)。toward=false(隣から離れる向きの微調整)ではそろえない
   (そろえると、0.05 秒の幅で離れようとしても元へ戻されてしまう)。開始 < 終了のままにできないときもそろえない -> そろえたか */
function snapEdge(i, f, toward){
  const g = S.doc.segments, s = g[i], n = g[f === 'start' ? i - 1 : i + 1]; if (!s || !n || toward === false) return false;
  const nv = f === 'start' ? n.end : n.start;
  if (nv === s[f] || t10(nv) !== t10(s[f]) || !(f === 'start' ? nv < s.end : nv > s.start)) return false;
  s[f] = nv; return true;
}

function segHTML(s, i){
  const c = s.speaker ? rowSpColor(s.speaker) : '', cut = s.cutState === 'cut', ov = ovl(i), dr = isBlankDraft(s);
  return `<div class="seg${s.flag ? ' flag' : ''}${s.proofed ? ' proofed' : ''}${(s.tags || []).length ? ' tagged' : ''}${cut ? ' cut' : ''}${s.noSub ? ' nosub' : ''}${dr ? ' tt-draft' : ''}" data-i="${i}"${c ? ` style="--sp:${c}"` : ''}>
    <input type="checkbox" class="sel" ${S.sel.has(s.id) ? 'checked' : ''} aria-label="この行を選択">
    <button type="button" class="play" data-act="play" title="${esc(titlePlay())}" aria-label="この行だけ再生">▶</button>
    <div class="times${ov ? ' ovl' : ''}"${ov ? ` title="${esc(OVL_TITLE)}"` : ''}><span class="t" data-f="start" data-ui-time="${Number(s.start) || 0}" data-ui-time-short aria-label="開始"></span><span>–</span><span class="t" data-f="end" data-ui-time="${Number(s.end) || 0}" data-ui-time-short aria-label="終了"></span></div>
    <select class="spk" data-f="speaker" aria-label="話者">${opts(s.speaker)}</select>
    <textarea data-f="text" rows="1" spellcheck="false" aria-label="文字" placeholder="${dr ? draftPh(s) : '(空の行)文字を入力。不要なら「削除」'}">${esc(s.text)}</textarea>
    <span class="ops"><button type="button" class="cut-toggle" data-act="cut" aria-pressed="${cut ? 'true' : 'false'}" title="Resolveの仮編集から外します(カット済)。元素材は残るため、あとで「残す」に戻せます">${cut ? 'カット済' : '残す'}</button><button type="button" class="pf" data-act="proof" aria-pressed="${s.proofed ? 'true' : 'false'}" title="${esc(titleProof())}">校正済み</button></span>
    <span class="pill info tt-nosub-pill" title="この行は字幕(映像の上・書き出しの SRT・パック)に出しません。カットでは今までどおり残します">字幕に出さない</span>
    ${dr ? `<span class="pill wait tt-draft-pill" title="${esc(draftTitle(s))}">下書き(${draftName(s)})</span>` : ''}
    <div class="sug">${sugHTML(s)}</div>
    <div class="tg">${tagsHTML(s)}</div>
    <div class="adj" aria-label="この行の操作"><span class="g" title="幅は右上の ⚙ 設定の「時刻の微調整の幅」。数字を直接書き換えてもかまいません">開始<button type="button" data-act="adj" data-f="start" data-d="-1" title="開始を早める">−</button><button type="button" data-act="adj" data-f="start" data-d="1" title="開始を遅らせる">＋</button><button type="button" class="now" data-act="setnow" data-f="start" title="開始を、いまの再生位置にする">再生位置</button></span><span class="g">終了<button type="button" data-act="adj" data-f="end" data-d="-1" title="終了を早める">−</button><button type="button" data-act="adj" data-f="end" data-d="1" title="終了を遅らせる">＋</button><button type="button" class="now" data-act="setnow" data-f="end" title="終了を、いまの再生位置にする">再生位置</button></span><span class="sep" aria-hidden="true"></span><span class="g rowops" aria-label="行の操作"><button type="button" data-act="addb" title="この行の前に、空の行を足します(認識で抜けたセリフを書き足すとき)">＋前に行</button><button type="button" data-act="adda" title="${esc(titleAddAfter())}">＋後に行</button><button type="button" data-act="split" title="カーソル位置(なければ再生位置)で2つに分けます">分割</button><button type="button" data-act="merge" title="次の行とつなげて1行にします">次と結合</button><button type="button" class="tt-nosub-btn" data-act="nosub" aria-pressed="${s.noSub ? 'true' : 'false'}" title="この行を字幕に出さない(ゲームのキャラ・NPC・動画の音声など)/もう一度押すと出す。行は消えず、カットでは残します。話者を「ゲーム音声など」にすると自動でオン">字幕に出さない</button><button type="button" data-act="del" class="del" title="${esc(titleDel())}">削除</button></span></div>
    ${s.flag ? `<button type="button" class="fl" data-act="unflag" title="${esc(s.flag)}(押すと確認済みにします)">要確認: ${esc(s.flag)}</button>` : ''}
  </div>`;
}

function renderDoc(){
  const segs = S.doc.segments, untranscribed = !segs.length && !S.doc.model;   // 文字起こしせずに開いた文書(model が空)
  $('#noRows').hidden = !untranscribed; renderIntoState();
  $('#segs').innerHTML = segs.length ? segs.map(segHTML).join('') : untranscribed ? '' : '<div class="empty">文字が認識されませんでした(音声がない、または小さすぎる可能性があります)<div style="margin-top:10px"><button type="button" class="btn small" data-act="addfirst">＋行を追加(再生位置に)</button></div></div>';
  UIKit.timebox.attachAll($('#segs'));   // 行の時刻の欄(分:秒.0.1秒。数字だけで入れる・← → で場所・↑ ↓ で動かす。ui-kit v11)
  autoSizeAll(true);
  S.curIdx = -1;   // 描き直すと「再生中」の印(.cur)も消えるので、次の timeupdate で付け直す
  if (S.navIdx >= segs.length) S.navIdx = segs.length - 1;
  { const r = rowsEl()[S.navIdx]; if (S.navIdx >= 0 && r && r.classList && r.classList.contains('seg')) r.classList.add('nav'); }
  renderSpeakers(); applyFilter(); updateSel(); updatePfStat(); renderCutPack(); updateCaption(); renderNoSubCount(); renderOvd();
}

function autoSize(ta){ if (NATIVE_FS) return; ta.style.height = 'auto'; ta.style.height = (ta.scrollHeight + 2) + 'px'; }

function autoSizeAll(fresh){
  if (NATIVE_FS) return;
  if (!rowIO) return autoSizeList([...document.querySelectorAll('#segs .seg:not([hidden]) textarea')]);
  if (fresh){ visRows.clear(); rowIO.disconnect(); for (const r of rowsEl()) if (r.classList && r.classList.contains('seg')) rowIO.observe(r); }
  else autoSizeList([...visRows].filter(r => !r.hidden).map(r => r.querySelector('textarea')).filter(Boolean));
}

function autoSizeList(tas){   // まとめて縮める → まとめて測る → まとめて設定(レイアウト計算を1回にする)
  for (const t of tas) t.style.height = 'auto';
  const hs = tas.map(t => t.scrollHeight);
  tas.forEach((t, i) => { if (hs[i] > 0) t.style.height = (hs[i] + 2) + 'px'; });
}

function autoSizeSoon(){ clearTimeout(sizeT); sizeT = setTimeout(() => { if (S.doc) autoSizeAll(); drawStripSoon(); }, 200); }

function applyFilter(){
  const q = norm($('#q').value.trim()), only = $('#flagKind').value;
  let n = 0; const shown = [];
  document.querySelectorAll('#segs .seg').forEach(el => {
    const s = S.doc.segments[Number(el.dataset.i)]; if (!s) return;
    const hit = (!q || norm(s.text).includes(q)) && (!only || flagMatch(s, only));
    if (hit && el.hidden){ const ta = el.querySelector('textarea'); if (ta) shown.push(ta); }
    el.hidden = !hit; if (hit) n++;
  });
  if (shown.length && !NATIVE_FS && !rowIO) autoSizeList(shown);   // 隠れていた行は、表示するときに高さを測り直す
  $('#qCount').textContent = (q || only) ? `${n}行が該当` : `${S.doc.segments.length}行`;
}

function renderSpeakers(){
  if (typeof renderVoiceLearn === 'function' && document.querySelector('#spDetails[open]')) renderVoiceLearn();   // 名前を付けたら「声を覚える」を押せるように(A-3)
  const box = $('#spList');
  const focused = document.activeElement && box.contains(document.activeElement) ? document.activeElement : null;
  if (focused && focused.type === 'text') return;   // 名前を打っている間は描き直さない(打った文字・候補を消さない。確定(change)のあとで描き直す)
  let num = 0;   // 番号(Alt+数字)は組み込みの「ゲーム音声など」を除いて数える
  box.innerHTML = S.doc.speakers.map((s, i) => {
    const rows = S.doc.segments.filter(x => x.speaker === s.id).length;
    if (isOtherSp(s)) return `<div class="sp-row tt-sp-other" data-i="${i}"><i class="tt-sp-member" style="background:${esc(OTHER_SP.color)}" aria-hidden="true"></i><input type="text" class="tt-sp-name" value="${esc(OTHER_SP.name)}" readonly aria-label="話者名(組み込み。変えられません)" title="組み込みの話者(名前は変えられません・声は覚えません)" style="flex:1"><span class="n">${rows}行</span><button type="button" class="btn small" data-act="spplay" title="この話者の行を順に再生">▶ 聞く</button><button type="button" class="btn small danger" data-act="spdel" title="一覧から外します(付いていた行は話者なし・字幕に出す に戻ります)">削除</button></div>`
      + '<div class="hint tt-sp-why">ゲームのキャラ・NPC・動画の音声など。この話者の行は字幕に出しません(行ごとに「字幕に出さない」を外せます)</div>';
    const c = speakerColor(s.id), sub = subColorOf(s); num++;
    return `<div class="sp-row" data-i="${i}"><input type="color" value="${esc(/^#[0-9a-fA-F]{6}$/.test(s.color) ? s.color : '#888888')}" aria-label="色(メンバーと合わないときの色)"${c.hex ? ' hidden' : ''}>${c.hex ? `<i class="tt-sp-member" style="background:${esc(c.hex)}" title="${esc(c.sub ? '字幕の色' : c.member + 'の色')}"></i>` : ''}<input type="text" class="tt-sp-name" value="${esc(s.name)}" maxlength="30" aria-label="話者名" list="spNames" style="flex:1"><span class="n">${rows}行 ・ ${num}</span><button type="button" class="btn small" data-act="spplay" title="この人の発言を順に再生">▶ 聞く</button><button type="button" class="btn small danger" data-act="spdel">削除</button></div>`
      + `<div class="row tt-sp-subrow" data-i="${i}"><label class="lag tt-sp-sub" title="この人の字幕の文字の色(16 進 6 桁・# は要りません)。空にすると指定なし(名前がメンバーと合えばメンバーカラー・合わなければ配信者の色)">字幕の色 #<input type="text" data-f="sub" value="${esc(sub.slice(1))}" maxlength="7" placeholder="指定なし" spellcheck="false" autocomplete="off" aria-label="${esc(s.name)}の字幕の色(16 進 6 桁)"><i class="tt-sp-subsw"${sub ? ` style="background:${esc(sub)}"` : ' hidden'} aria-hidden="true"></i></label></div>`
      + (c.reason ? `<div class="hint tt-sp-why">${esc(c.reason)}</div>` : ''); }).join('');
  renderSpNames();
  const cur = $('#spBulk').value;
  $('#spBulk').innerHTML = opts(cur);
  renderSpAll();   // 評価用で話者の無い行があれば「全行をこの人に」(マスタープラン Q4。app-jobs.js)
}

function pushUndo(seq){   // seq: 2 カット の字幕の段の1回の操作(行の時刻 + 残す区間)は、カットの元に戻すと同じ番号で積む(段6 6-4)
  S.undo.push({ seq: seq || nextOp(), snap: JSON.stringify({ speakers: S.doc.speakers, segments: S.doc.segments, sug: S.sug }) }); if (S.undo.length > 30) S.undo.shift(); updateUndo();
}

/* 一番上の控えが seq の操作なら、その1つを戻す(2 カット の Ctrl+Z から。段6 6-4)-> 戻したか */
function undoDocIf(seq){
  if (!S.doc || !seq || !S.undo.length || S.undo[S.undo.length - 1].seq !== seq) return false;
  restoreUndo(); return true;
}

function restoreUndo(){
  const navId = navSnapshot();
  const d = JSON.parse(S.undo.pop().snap); S.doc.speakers = d.speakers; S.doc.segments = d.segments; S.sel.clear(); if (d.sug) S.sug = d.sug;
  navRestore(navId, S.navIdx);
  renderDoc(); renderChips(); updateUndo(); markDirty();
  if (CUT) CUT.docChanged();   // 控えの行の「カット済」は古いことがある → 今のカットから付け直す(markDirty の 0.3 秒後を待たない)
}

function updateUndo(){
  const n = S.undo.length + (CUT && CUT.undoCount ? CUT.undoCount() : 0);   // ボタンの数 = 2つの合計
  $('#btnUndo').disabled = !n; $('#btnUndo').textContent = n ? `元に戻す(${n})` : '元に戻す';
}

/* only = 'tx': 文字起こしの側だけ(全行を校正済みにした知らせの「元に戻す」) */
function doUndo(only, quiet){   // quiet: 2 カット のタブから(カットを戻した知らせは要らない)
  if (!S.doc || lockJob()) return;   // 処理中(話者判別・再認識など)はどちらも戻さない
  const tx = S.undo.length ? S.undo[S.undo.length - 1].seq : 0, ct = only !== 'tx' && CUT && CUT.undoTop ? CUT.undoTop() : 0;
  if (ct && ct >= tx){   // カットの方が新しい: カットを1つ戻す(同じ番号 = 字幕の段の1回の操作なら、CUT.undo が文書も一緒に戻す。段6 6-4)。1 文字起こし からは見えない変化なので知らせる
    if (CUT.undo() && ct > tx && !quiet) toast('カットを1つ戻しました(2 カット のタブの区間)', 2500);
    updateUndo(); return;
  }
  if (!S.undo.length) return;
  restoreUndo();
}

/* 開始/終了を、いまの再生位置にする(足した行の時刻を、聞きながら合わせるとき) */
function setTimeNow(s, f){
  const v = Math.round(player().currentTime * 100) / 100;
  if (f === 'start' ? !(v < s.end) : !(v > s.start)) return toast(f === 'start' ? '再生位置が、この行の終了より後です(先に終了を合わせてください)' : '再生位置が、この行の開始より前です', 2500);
  pushUndo(); s[f] = v; const id = s.id; sortSegs(); S.navIdx = S.doc.segments.findIndex(x => x.id === id); snapEdge(S.navIdx, f, true); renderDoc(); markDirty();
  toast((f === 'start' ? '開始' : '終了') + 'を ' + fmtT(v, true) + ' にしました', 1500);
}

function nudge(s, row, f, dir){
  const step = Number(V.adjStep) || 0.1, MIN = 0.1;
  let v = Math.round((s[f] + dir * step) * 100) / 100;
  if (f === 'start') v = Math.min(Math.max(0, v), Math.round((s.end - MIN) * 100) / 100); else v = Math.max(v, Math.round((s.start + MIN) * 100) / 100);
  if (v === s[f]) return toast(f === 'start' ? (dir < 0 ? 'これより早くできません(0秒)' : '開始は、終了より0.1秒以上前にしてください') : '終了は、開始より0.1秒以上後にしてください', 1500);
  pushUndo(); s[f] = v; markDirty();
  const segs = S.doc.segments; let i = segs.indexOf(s);
  const moved = (segs[i - 1] && segs[i - 1].start > s.start) || (segs[i + 1] && segs[i + 1].start < s.start);   // 並び順が変わるときだけ、並べ直す
  if (moved){ sortSegs(); i = segs.indexOf(s); }
  snapEdge(i, f, dir > 0 === (f === 'end'));
  if (moved){ renderDoc(); setNav(i); }
  else { const inp = row.querySelector(`.t[data-f="${f}"]`); if (inp) UIKit.timebox.set(inp, s[f]); markOvl(i); }
  if (S.playEnd !== null || player().paused){ const p = player(); p.currentTime = f === 'end' ? Math.max(s.start, s.end - 1.2) : s.start; S.playEnd = s.end; p.play().catch(() => {}); armPlayEnd(); }   // 動かした端を、すぐ聞き直せるように
}

function sortSegs(){ S.doc.segments.sort((a, b) => a.start - b.start); }   // v0.9.8: 開始が同じ行は、今の並びのまま(安定ソート)。終了で並べ替えると、足した行が意図と違う位置に動くため

function updateSel(){
  const n = S.sel.size; $('#selCount').textContent = n ? `${n}行を選択中` : '';
  $('#selAll').checked = n > 0 && n === S.doc.segments.length;
  updateRt(); $('#btnProofSel').disabled = !n; renderCutPack();
}

function closeCtxMenu(){ if (!ctxMenuEl) return; const m = ctxMenuEl; ctxMenuEl = null; m.remove(); document.removeEventListener('click', onCtxOutside, true); document.removeEventListener('contextmenu', onCtxOutside, true); }

function onCtxOutside(e){ if (ctxMenuEl && !ctxMenuEl.contains(e.target)) closeCtxMenu(); }

/* ---------- 行の移動(キーボードで校正を回す) ---------- */

function curNav(){ const a = rowIdxOf(document.activeElement); return a >= 0 ? a : (S.navIdx >= 0 ? S.navIdx : S.curIdx); }

/* v0.9.6: 行の分割・削除・結合・元に戻す・再読み込みで一覧の並びや行数が変わっても、キーボードの「今の行」(S.navIdx)が
   同じ行を指し続けるようにする(そうしないと、直前に見ていた行と違う行にShiftキー操作が効いてしまう)。
   変更の直前に navSnapshot() で行の id を覚え、直後に navRestore() でその id の新しい位置を探し直す
   (その行自体が無くなっていれば、fallbackIdx で渡した位置に近い行のままにする)。 */
function navSnapshot(){ return S.navIdx >= 0 && S.doc.segments[S.navIdx] ? S.doc.segments[S.navIdx].id : null; }

function navRestore(id, fallbackIdx){
  if (id == null || !S.doc) return;
  const ni = S.doc.segments.findIndex(x => x.id === id);
  S.navIdx = ni >= 0 ? ni : Math.max(-1, Math.min(fallbackIdx, S.doc.segments.length - 1));
}

function savePos(){ if (!S.doc || S.navIdx < 0) return; const g = S.doc.segments[S.navIdx]; if (g){ try { localStorage.setItem(posKey(S.docId), JSON.stringify({ id: g.id, t: g.start })); } catch {} } }

function loadPos(id){ try { const o = JSON.parse(localStorage.getItem(posKey(id)) || 'null'); return o && typeof o.id === 'string' ? o : null; } catch { return null; } }

/* 行が見える範囲(固定の再生欄の下〜画面の下)に収まっていれば動かさない。外れるときだけ、一定の位置(上から35%)に、なめらかに寄せる */
function ensureVisible(row, at){
  if (!row || row.hidden) return;
  const top = parseFloat(getComputedStyle(row).scrollMarginTop) || 0, bot = window.innerHeight - 24, r = row.getBoundingClientRect();
  if (r.top >= top && r.bottom <= bot) return;
  const goal = top + Math.max(0, (bot - top - Math.min(r.height, bot - top)) * (at === undefined ? 0.35 : at));
  const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  window.scrollBy({ top: r.top - goal, behavior: reduce ? 'auto' : 'smooth' });
}

function setNav(i){
  const rows = rowsEl(); if (S.navIdx >= 0 && rows[S.navIdx] && rows[S.navIdx].classList) rows[S.navIdx].classList.remove('nav');
  const was = S.navIdx; S.navIdx = i; if (i >= 0 && rows[i] && rows[i].classList) rows[i].classList.add('nav');
  if (was >= 0 && was !== i && rows[was] && rows[was].classList){ const w = rows[was]; w.classList.remove('was'); void w.offsetWidth; w.classList.add('was'); setTimeout(() => w.classList.remove('was'), 1500); }
  capFollow = false;
  updateCaption();
}

/* 映像の上に重ねる今の行の字幕(段2): capFollow なら再生位置の行(S.curIdx)と、それと重なる行(capStack)、そうでなければ選んだ行(S.navIdx)だけ。
   字幕に出さない行(noSub)は出さない */
function updateCaption(){
  const el = $('#playerCaption'); if (!el) return;
  const segs = S.doc ? S.doc.segments : [];
  let idxs = [];
  if (S.doc && capFollow) idxs = capStack(segs, player().currentTime || 0, { primary: S.curIdx });
  else if (S.doc && S.navIdx >= 0 && capOk(segs[S.navIdx])) idxs = [S.navIdx];
  paintCaps(el, idxs, segs);
}

/* ---------- 重なる行の字幕(2026-10-05。docs/plan/other-voice-and-overlap-plan.md の 2-2・6)----------
   1 文字起こし の映像の上(#playerCaption)と 2 カット のプレビュー(#cutCaption)が同じ関数を使う(cut.js には app.js が渡す) */
const CAP_SCAN = 40;   // 再生位置より前に始まった行を何行さかのぼって見るか(長い行が続く所でも足りる数。全部は見ない)
const capOk = g => !!g && !!String(g.text || '').trim() && !g.noSub;
const capOverlap = (a, b) => Math.min(a.end, b.end) - Math.max(a.start, b.start);

/* 時刻 t に出す字幕の行(添字。下の段 → 上の段の順)。重なりが CAP_OVERLAP_MIN 秒以上の行どうしは両方(開始が早い方を下・同時開始は話者の並び順・
   CAP_MAX_STACK 段まで。それより多ければ 3 段目は開始がいちばん遅い行)。それより短い重なりは今までどおり後の行だけ。
   opt.primary: 今の行(1 文字起こし の S.curIdx。行の終わりの少し後まで残る)。opt.skip(i): 出さない行(2 カット のカット後の見え方で削った行) */
function capStack(segs, t, opt = {}){
  const ok = i => capOk(segs[i]) && !(opt.skip && opt.skip(i));
  let lo = 0, hi = segs.length - 1, last = -1;
  while (lo <= hi){ const m = (lo + hi) >> 1; if (segs[m].start <= t){ last = m; lo = m + 1; } else hi = m - 1; }
  const on = [];
  for (let i = last; i >= 0 && i > last - CAP_SCAN; i--) if (t < segs[i].end && ok(i)) on.push(i);
  const p = opt.primary;
  let top = on.length ? on[0] : -1;   // 開始がいちばん遅い行(後の行に切り替わる)
  if (p != null && p >= 0 && ok(p) && (top < 0 || segs[p].start >= segs[top].start)) top = p;
  if (top < 0) return [];
  const spIdx = id => { const k = S.doc ? S.doc.speakers.findIndex(s => s.id === id) : -1; return k < 0 ? 99 : k; };
  const out = on.filter(i => i !== top && capOverlap(segs[i], segs[top]) >= CAP_OVERLAP_MIN).concat([top])
    .sort((a, b) => segs[a].start - segs[b].start || spIdx(segs[a].speaker) - spIdx(segs[b].speaker) || a - b);
  return out.length > CAP_MAX_STACK ? out.slice(0, CAP_MAX_STACK - 1).concat(out.slice(-1)) : out;
}

/* 字幕の箱に行を描く。1 行なら今までどおり(箱の文字と色)。2 行以上は 1 行ずつの span(上の段が先 = 開始が遅い行)に話者の色。
   同じ中身なら描き直さない(再生中は timeupdate のたびに呼ばれる) */
function paintCaps(el, idxs, segs){
  const hexOf = g => g.speaker ? speakerColor(g.speaker).hex : '';
  const items = idxs.map(i => ({ text: String(segs[i].text || '').trim(), hex: hexOf(segs[i]) })).filter(x => x.text);
  const key = JSON.stringify(items);
  if (el.dataset.capKey === key) return;
  el.dataset.capKey = key;
  el.hidden = !items.length;
  if (items.length <= 1){
    const x = items[0];
    el.textContent = x ? x.text : '';
    if (x && x.hex) el.style.setProperty('--tt-cap-color', x.hex); else el.style.removeProperty('--tt-cap-color');   // 無ければ配信者の色(pack-tab.js が body に入れる)のまま
    return;
  }
  el.style.removeProperty('--tt-cap-color');
  el.innerHTML = items.slice().reverse().map(x => `<span class="tt-cap-line"${/^#[0-9a-fA-F]{6}$/.test(x.hex) ? ` style="--tt-cap-color:${x.hex}"` : ''}>${esc(x.text)}</span>`).join('');
}

/* ---------- 話者の色(気が利く画面へ 段2)----------
   色を決めるのはここ1つ: 行の左端の線・話者の欄・映像の上の字幕・カットのプレビュー・パックの見本(cut.js・pack-tab.js にも渡す)。
   話者の名前がメンバーと合えばメンバーカラー(照らし合わせは入口の api/ytt/streamer-colors → ytt_core/colors.py。名前の一覧をまとめて1回)。
   合わなければ、行の線・話者の欄は今の自動の色、字幕は配信者の色(--tt-cap-color)。**文字起こしの行の文字の色は変えない**(明るい色は白い背景で読めない)。
   スイッチは編集の設定 speakerColors(パックのタブの「話者の名前がメンバーと合えば…」。まとめて実行も同じ値に従う。以前はこのブラウザの tx.pk.speakerColors) */

function lookupSpeakerNames(names){
  if (!TOKEN) return;
  const want = [...new Set(names.map(n => String(n || '').trim()).filter(n => n && !SPKC.has(n)))];
  if (!want.length) return;
  for (const n of want) SPKC.set(n, undefined);
  api('/api/ytt/streamer-colors', { body: { names: want } }).then(j => {
    for (const n of want){ const m = j && j.matches ? j.matches[n] : null; SPKC.set(n, m && /^#[0-9a-fA-F]{6}$/.test(String(m.hex || '')) ? { name: String(m.name), hex: m.hex } : null); }   // 色は style に入れるので形を確かめる
    onSpeakerColors();
  }, () => { for (const n of want) SPKC.delete(n); });
}

/* 話者の名前 → メンバーカラー(照らし合わせの1か所。段4 4-5: パックの見積もりの sampleSpeakers(名前)からも同じ道で色を出す)。
   -> {hex: '' = 合わない・照らし合わせ中・使わない, member: 合った人の名前, pending: 照らし合わせ中} */
function speakerColorByName(name){
  name = String(name || '').trim();
  const own = name && S.doc ? S.doc.speakers.find(s => !isOtherSp(s) && String(s.name || '').trim() === name && subColorOf(s)) : null;
  if (own) return { hex: subColorOf(own), member: '', pending: false, sub: true };   // 文書の話者の字幕の色(sub)が最優先(メンバーの色のスイッチを切っていても効く)
  if (!name || !TOKEN || !speakerColorsOn()) return { hex: '', member: '', pending: false };
  if (!SPKC.has(name)) lookupSpeakerNames([name]);
  const m = SPKC.get(name);
  return m === undefined ? { hex: '', member: '', pending: true } : m ? { hex: m.hex, member: m.name, pending: false } : { hex: '', member: '', pending: false };
}

/* -> {hex: メンバーカラー('' = 合わない・使わない), auto: 自動の色, member: 合った人の名前, reason: 話者の欄に出す理由} */
function speakerColor(spId){
  const sp = spById(spId), auto = spColor(sp), name = sp ? String(sp.name || '').trim() : '';
  if (!sp) return { hex: '', auto: '', member: '', reason: '' };
  const sub = subColorOf(sp);
  if (sub) return { hex: sub, auto, member: '', sub: true, reason: `字幕の色を指定しています(#${sub.slice(1)}。メンバーの色より優先)` };   // 文書の話者の字幕の色(sub。2026-10-05)が最優先
  if (!TOKEN) return { hex: '', auto, member: '', reason: 'ホームから開くと、名前をメンバーと照らし合わせて色を付けます' };
  if (!speakerColorsOn()) return { hex: '', auto, member: '', reason: 'パックの「話者の名前がメンバーと合えば…」を切っているので、メンバーの色は使いません' };
  const c = speakerColorByName(name);
  if (c.pending) return { hex: '', auto, member: '', reason: '' };
  return c.hex ? { hex: c.hex, auto, member: c.member, reason: `名簿の「${c.member}」と一致(この色で字幕を出します)` }
    : { hex: '', auto, member: '', reason: 'メンバーと合わないので、字幕は配信者の色で出します' };
}

/* 照らし合わせの結果が来た・名前やスイッチが変わった → 色を使う所を全部塗り直す(行は描き直さず、線の色だけ) */
function onSpeakerColors(){
  if (!S.doc) return;
  const rows = rowsEl();
  S.doc.segments.forEach((s, i) => { const r = rows[i]; if (r && r.classList && r.classList.contains('seg')){ const c = s.speaker ? rowSpColor(s.speaker) : ''; if (c) r.style.setProperty('--sp', c); else r.style.removeProperty('--sp'); } });
  updateCaption(); renderSpeakers();
  if (CUT && CUT.refreshCaption) CUT.refreshCaption();
  if (PACK) PACK.changed();
}

function gotoRow(i, opt = {}){
  const row = rowsEl()[i]; if (!row || !row.classList.contains('seg') || row.hidden) return false;
  setNav(i);
  if (opt.edit){ const ta = row.querySelector('textarea'); if (ta) ta.focus({ preventScroll: true }); }
  else if (document.activeElement && document.activeElement.closest && document.activeElement.closest('#segs') && isTextEntry(document.activeElement)) document.activeElement.blur();
  ensureVisible(row, opt.center ? 0.5 : 0.35);
  savePos();
  if (opt.play) playSeg(S.doc.segments[i], true);
  return true;
}

function findRow(from, dir, pred){
  const segs = S.doc.segments, rows = rowsEl();
  for (let i = from + dir; i >= 0 && i < segs.length; i += dir){ if (!rows[i] || rows[i].hidden) continue; if (!pred || pred(segs[i])) return i; }
  return -1;
}

function navigate(kind, dir){
  if (!S.doc || lockJob()) return;
  const pred = kind === 'unproofed' ? g => !g.proofed && g.text.trim() : kind === 'flag' ? g => !!g.flag : null;
  const from = curNav(), i = findRow(from < 0 && dir > 0 ? -1 : from, dir, pred);
  if (i < 0) return toast({ unproofed: dir > 0 ? 'これより後に、未校正の行はありません' : 'これより前に、未校正の行はありません', flag: '該当する「要確認」の行はありません' }[kind] || (dir > 0 ? '最後の行です' : '最初の行です'));
  gotoRow(i, { play: V.autoNext, center: !!kind });
}

function seek(d){ const p = player(); p.currentTime = Math.max(0, p.currentTime + d); S.playEnd = null; }   // Q/E(3秒)。行の終わりで止める予定は解く

function replayCur(){ const i = curNav(), g = S.doc && S.doc.segments[i]; if (g) playSeg(g, true); }

function toggleTag(s, t, row){
  const a = new Set(s.tags || []); if (a.has(t)) a.delete(t); else a.add(t);
  s.tags = Object.keys(TAG_LABEL).filter(k => a.has(k)); if (!s.tags.length) delete s.tags;
  if (row){ row.classList.toggle('tagged', !!s.tags); row.querySelector('.tg').innerHTML = tagsHTML(s); }
  markDirty();
}

function rowAndSeg(){ const i = curNav(), row = i >= 0 ? rowsEl()[i] : null, g = i >= 0 && S.doc.segments[i]; return g && row && row.classList && row.classList.contains('seg') ? { i, row, g } : null; }

function proofOk(){   // 校正済みにして、次の行へ(すでに校正済みなら、次へ進むだけ)
  const c = rowAndSeg(); if (!c) return toast('先に、行を選んでください(↓ で最初の行へ)');
  if (!c.g.proofed){ setProof(c.g, true, c.row); markDirty(); updatePfStat(); }
  const ni = findRow(c.i, 1); if (ni >= 0) gotoRow(ni, { play: V.autoNext }); else toast('最後の行です(表示している行は、すべて確認しました)');
}

function deleteCur(){
  const c = rowAndSeg(); if (!c) return;
  /* v0.9.8: 1文字キーになったので、Z は2回押し(1.5秒以内)で削除する(行のボタンの「削除」と同じ考え方) */
  if (!zArm || zArm.id !== c.g.id || Date.now() - zArm.t > 1500){ zArm = { id: c.g.id, t: Date.now() }; return toast(`もう一度 ${keymap().del ? keyText(keymap().del) : '削除のキー'} で、この行を削除します`, 1500); }
  zArm = null;
  pushUndo(); S.sel.delete(c.g.id); S.doc.segments.splice(c.i, 1); S.navIdx = Math.min(c.i, S.doc.segments.length - 1);
  renderDoc(); markDirty(); toast('行を削除しました(Ctrl+Z で元に戻せます)');
  if (V.autoNext && S.navIdx >= 0) playSeg(S.doc.segments[S.navIdx], true);
}

function assignSpeaker(n){
  const sps = numberedSpeakers(), c = rowAndSeg(); if (!c || (n && !sps[n - 1])) return;   // 番号は組み込みの「ゲーム音声など」を除いた並び
  pushUndo(); setSegSpeaker(c.g, n === 0 ? '' : sps[n - 1].id, c.row);
  markDirty(); renderSpeakers();
}

function editCur(){ const c = rowAndSeg(); if (c){ const ta = c.row.querySelector('textarea'); ta.focus(); ta.setSelectionRange(ta.value.length, ta.value.length); } }

/* 編集の設定の keymap は「送ったキーだけ直す」(api/settings/patch。丸ごとの保存ではサーバーの値が残る = 窓を並べても戻らない) */
function saveKeymap(part){
  if (S.settingsLoadErr) return toast('設定を読み込めていないため、キー配置を保存しません(⚙ 設定の「読み直す」を押してください)', 6000, 'err');   // 空の配置で上書きしない(監査 11)
  const km = { ...((S.settings && S.settings.keymap) || {}), ...part };
  S.settings.keymap = km;
  api('/api/settings/patch', { body: { values: { keymap: km } } }).catch(e => toast('キー配置を保存できませんでした: ' + e.message, { ms: 0, kind: 'err' }));
}

function keymap(){ return KM ? KM.map() : {}; }

function txActionOf(combo){ return KM ? KM.actionOf(combo) : null; }

/* ---------- キー配置の表示と変更(⚙ 設定の「キー配置」。2026-09-27) ----------
   割り当てを変えたら、下の帯・一覧の上の手がかり・キー操作の一覧(?)・設定の欄をまとめて描き直す(renderKeyUI) */

function renderKeyUI(){
  const km = keymap();
  txKeybarScene(); renderDrillBar();   // 評価ドリルの帯のボタンのキーも今の割り当てで
  /* 一覧の上の手がかり */
  const hint = $('#keyHintItems');
  if (hint) hint.innerHTML = [['rowNext', '次の行'], ['replay', '聞く'], ['playPause', '再生・停止'], ['proof', '校正済みにして次へ'], ['edit', '直す']]
    .map(([id, l]) => `<span class="tt-kh-i">${km[id] ? kbdHTML(km[id]) : ''}${KEY_ALT[id] ? (km[id] ? '<span class="muted">/</span>' : '') + kbdHTML(KEY_ALT[id]) : ''} ${esc(l)}</span>`).join('');
  /* 基本の流れ(キー操作の一覧の下。今の割り当てから) */
  const flow = $('#keysFlow');
  if (flow){
    const k = id => km[id] ? kbdHTML(km[id]) : '<span class="muted">(キーなし)</span>';
    flow.innerHTML = `基本の流れ: ${k('rowNext')}(<kbd>↓</kbd>)で行を選ぶ → 聞く(${k('replay')}) → 合っていれば ${k('proof')} / 直すなら ${k('edit')}(<kbd>Tab</kbd>)で入力 → <kbd>Esc</kbd>(<kbd>Tab</kbd>) → ${k('proof')}。` +
      `「移動したら自動で再生」(${k('autoNext')} か設定の引き出しで切り替え)をオンにすると、${k('proof')} を押すたびに「聞く → 確認 → 次を聞く」が続きます。` +
      `聞き取れない・重なり・BGM は ${k('tagUnclear')} / ${k('tagOverlap')} / ${k('tagBgm')} でメモしておくと、あとで学習に使うかどうかを選べます。`;
  }
  /* 行のボタンのツールチップ(描き直さずに title だけ合わせる) */
  document.querySelectorAll('#segs button[data-act=play]').forEach(b => { b.title = titlePlay(); });
  document.querySelectorAll('#segs button[data-act=proof]').forEach(b => { b.title = titleProof(); });
  document.querySelectorAll('#segs button[data-act=tag]').forEach(b => { b.title = titleTag(b.dataset.t); });
  document.querySelectorAll('#segs button[data-act=adda]').forEach(b => { b.title = titleAddAfter(); });
  document.querySelectorAll('#segs button[data-act=del]').forEach(b => { b.title = titleDel(); });
  /* 静的な HTML の中のキー(段3 3-3 監査 16): data-key-title = title の後ろに「(キー)」・data-key = 中の文字(data-key-fmt の {k} に入れる)。未設定なら出さない */
  document.querySelectorAll('[data-key-title]').forEach(el => {
    if (el.dataset.keyTitleBase === undefined) el.dataset.keyTitleBase = el.title;
    const t = el.dataset.keyTitleBase + keyParen(el.dataset.keyTitle);
    el.title = t; if (el.hasAttribute('aria-label') && !el.querySelector('.tt-hlabel')) el.setAttribute('aria-label', t);
  });
  document.querySelectorAll('[data-key]').forEach(el => { const k = km[el.dataset.key]; el.textContent = k ? (el.dataset.keyFmt || '{k}').replace('{k}', keyText(k)) : ''; });
  const an = $('#autoNextLbl');
  if (an) an.title = `${km.proof ? keyText(km.proof) + '・' : ''}Shift+↓/↑ で行を移動したとき、その行を自動で再生します(その行の終わりで止まります)${km.autoNext ? '。' + keyText(km.autoNext) + ' でも切り替わります' : ''}。聞いて確認する流れが、左手だけで回ります`;
  window.dispatchEvent(new CustomEvent('ytt-keys-changed'));   // 2 カット のタブ(cut.js)の帯・ツールチップも合わせる
}

/* 動画の fps が分からない文書では、キー操作の一覧に「1コマは約 1/30 秒」(段3 3-4)。カットの読み込みが終わったとき(onCutState)と文書を閉じたとき */
function renderFpsNote(){
  const el = $('#keysFpsNote'); if (!el) return;
  const st = CUT ? CUT.state() : null;
  el.hidden = !(S.doc && st && st.loaded && !CUT.fps());
}

/* キー操作の一覧(? とヘッダーの「キー」)。? をもう一度押すと閉じる(スタジオと同じ。S-29) */
function openKeys(){ const d = $('#keys'); if (d.open) return; if (KM) KM.clearNote(); renderFpsNote(); d.showModal(); }

/* ---------- 用語のワンクリック挿入 ---------- */

function renderTerms(){
  const box = $('#terms'), ts = String(S.settings.glossary || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean).slice(0, 16);
  box.hidden = !ts.length || !S.doc;
  box.innerHTML = ts.length ? '<span class="hint" title="行をクリックしてから押すと、カーソル位置に入ります。文字を選んでいれば、その文字を置き換えます">用語:</span>' + ts.map(t => `<button type="button" class="chip" data-t="${esc(t)}">${esc(t)}</button>`).join('') : '';
}

/* ---------- 履歴(自動バックアップ) ---------- */

async function loadHistory(){
  const id = S.docId; if (!id) return;
  let r; try { r = await api('/api/history?id=' + encodeURIComponent(id)); } catch (e){ return toast(e.message); }
  if (S.docId !== id) return;
  $('#hiList').innerHTML = r.items.length ? r.items.map(x => `<div class="row" data-ts="${x.ts}" style="margin-top:4px;justify-content:space-between;flex-wrap:nowrap"><span class="hint">${esc(new Date(x.ts).toLocaleString())} ・ ${x.segments}行 ・ 校正済み${x.proofed}行 ・ ${x.chars}字</span><button type="button" class="btn small" data-act="hirest">この時点に戻す</button></div>`).join('')
    : '<p class="hint" style="margin:6px 0 0">まだ以前の版はありません(10分ごと・再認識や話者判別の前に、自動で残ります)</p>';
}

function doSplit(i, row){
  const s = S.doc.segments[i], ta = row.querySelector('textarea');
  let pos = ta.selectionStart;
  if (!(pos > 0 && pos < s.text.length)) pos = Math.floor(s.text.length / 2);
  if (s.text.length < 2) return toast('短すぎて分割できません');
  const t = player().currentTime;
  const cut = t > s.start + 0.3 && t < s.end - 0.3 ? t : s.start + (s.end - s.start) * pos / s.text.length;
  splitRowAt(i, pos, cut);
}

/* 行 i を文字の位置 pos・時刻 cut で2つに(1 文字起こし の分割と、2 カット の字幕の段の「再生位置でこの行を分ける」が共用。段6 6-5)。
   話者・校正済み・メモは両方の行へそのまま。右の行は新しい id・flag は空。区間は変えない(カット済の印は区間から付け直す)-> 分けたか */
function splitRowAt(i, pos, cut){
  const segs = S.doc.segments, s = segs[i];
  if (!s || !(pos > 0 && pos < s.text.length)) return false;
  cut = Math.round(cut * 100) / 100;
  const navId = navSnapshot();
  pushUndo();
  const left = { ...s, text: s.text.slice(0, pos).trimEnd(), end: cut };
  const right = { ...s, id: uid(), text: s.text.slice(pos).trimStart(), start: cut, flag: '' };
  segs.splice(i, 1, left, right); navRestore(navId, i); renderDoc(); markDirty();
  return true;
}

/* 2 カット の字幕の段で行の時刻を直した(段6 6-3): 1 文字起こし のタブを描き直し、文書を保存する(markDirty → 0.7 秒後。CUT.docChanged も呼ばれる) */
function rowChanged(){ if (!S.doc) return; renderDoc(); markDirty(); }

/* ---------- v0.9.8: 行の追加(認識で抜けたセリフを書き足す) ----------
   時刻は前後の行の「すき間」に置く(すき間が 8 秒より長ければ 8 秒まで)。すき間が無いときは 1.5 秒の仮の長さで置き、重なりを案内する。
   並び順(開始時刻順)を必ず保つため、足したあと sortSegs() して id で位置を探し直す。原文(original)には何も足さないので、
   サーバー側の精度測定では「人が足した行 = 認識の脱落」として正しく数えられ、置換の学習には使われない */

function insertRow(at, start, end, speaker){
  if (lockJob()) return toast('処理中のため、今は行を足せません');
  if (!(end > start)) end = start + NEW_LEN;
  pushUndo();
  const g = { id: uid(), start: r2(start), end: r2(end), text: '', speaker: speaker || '', flag: '' };
  S.doc.segments.splice(at, 0, g);   // 決めた位置に入れる(開始時刻の順は、呼び出し側で保っている)
  S.navIdx = at; renderDoc(); markDirty();
  if (rowsEl()[at] && rowsEl()[at].hidden){ $('#q').value = ''; $('#flagKind').value = ''; applyFilter(); toast('絞り込みを解除しました(足した行が見えるように)'); }
  gotoRow(at, { edit: true, center: true });
  if (ovl(at)) toast('同じ話者の行と時刻が重なっています。必要なら開始・終了を直すか、別の人の声なら話者を付けてください', 3500);
  else toast('行を足しました。文字を入力してください(Esc で抜けます・Ctrl+Z で取り消し)', 2500);
}

function insertAfter(i){
  const segs = S.doc.segments, s = segs[i], nx = segs[i + 1]; if (!s) return;
  let a = s.end, b = nx ? nx.start : s.end + NEW_LEN;
  if (nx && a > nx.start) a = nx.start;
  if (b - a >= NEW_MIN_GAP) b = Math.min(b, a + NEW_MAX);
  else { b = a + NEW_LEN; if (nx && nx.end - a >= 0.5) b = Math.min(b, nx.end); }   // すき間が無いときの仮の長さ(次の行より後ろまでは伸ばさない)
  insertRow(i + 1, a, b, s.speaker);
}

function insertBefore(i){
  const segs = S.doc.segments, s = segs[i], pv = segs[i - 1]; if (!s) return;
  let b = s.start, a = pv ? Math.min(pv.end, b) : Math.max(0, b - NEW_LEN);
  if (b - a >= NEW_MIN_GAP) a = Math.max(a, b - NEW_MAX); else a = Math.max(pv ? pv.start : 0, b - NEW_LEN);
  insertRow(i, a, b > a ? b : a + NEW_LEN, s.speaker);
}

function insertAtTime(t){
  const segs = S.doc.segments; t = Math.max(0, Number(t) || 0);
  let k = -1; for (let j = 0; j < segs.length && segs[j].start <= t; j++) k = j;
  if (k >= 0 && t < segs[k].end) return insertAfter(k);   // 行の途中なら、その行の後ろへ
  const pv = segs[k], nx = segs[k + 1], lo = pv ? pv.end : 0, hi = nx ? nx.start : Infinity;
  const a = Math.max(lo, t - 0.3), b = Math.min(hi, a + 3);
  insertRow(k + 1, a, b - a >= NEW_MIN_GAP ? b : a + NEW_LEN, pv ? pv.speaker : (nx ? nx.speaker : ''));
}

function playSeg(s, one){
  const p = player(); p.currentTime = s.start;
  S.playEnd = one ? s.end : null;
  p.play().catch(() => {});
  armPlayEnd();   // 行の終わりで正確に止める(timeupdate は粗くて、終わりを平均 0.1 秒過ぎていた)
}

function curIndex(t){
  const segs = S.doc ? S.doc.segments : []; let lo = 0, hi = segs.length - 1, ans = -1;
  while (lo <= hi){ const m = (lo + hi) >> 1; if (segs[m].start <= t){ ans = m; lo = m + 1; } else hi = m - 1; }
  return ans >= 0 && t < segs[ans].end + 0.4 ? ans : -1;
}

/* 再生できないときの案内(段2 B-4)。動画が見つからない(カットのタブの offCode = source_missing)なら元のパスと「動画を選び直す」、
   それ以外(mkv など)は形式の案内だけ(付け替えても直らないのでボタンを出さない)。カットの読み込みが終わるまでは短い文 */
function renderPlayerMsg(){
  const m = $('#playerMsg');
  if (!S.doc || S.playerErr !== S.docId){ m.hidden = true; return; }
  const cs = CUT ? CUT.state() : null, known = !!(cs && cs.loaded && cs.docId === S.docId);
  const missing = known && cs.offCode === 'source_missing', tail = '文字の編集と書き出しは、再生できなくても使えます。';
  $('#playerMsgText').textContent = missing ? `元の動画が見つかりません: ${S.doc.sourcePath || '(パスの記録なし)'}。${tail}`
    : known && cs.offCode === 'network_path' ? `${cs.off}。${tail}`
    : known ? `この形式は再生できません(mkv など)。${tail}` : `元のファイルを再生できません。${tail}`;
  $('#playerRelink').hidden = !missing;
  m.hidden = false;
}
