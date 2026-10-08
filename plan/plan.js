/* plan/plan.js — index.html と user-tasks.html の共通の表示部品(データは data.js。ここは見せ方だけ)
   状態は色ではなく記号と札の形で見せる(色相は線だけ。plan.css の先頭)。 */
(function () {
  var ST = {
    done: ["✓", "済み"], doing: ["▸", "進行中"], next: ["▸", "次"], todo: ["", "あと"], wait: ["", "待ち"], cont: ["↻", "継続"]
  };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  /* data の文に混ざる **太字** だけを太字にする(ほかの記法は使わない) */
  function md(s) { return esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>"); }
  function stLabel(st, label) { var s = ST[st] || ["", st]; return (s[0] ? s[0] + " " : "") + (label || s[1]); }
  function badge(st, label) {
    var s = ST[st] || ["", st];
    return '<span class="badge ' + esc(st) + '">' + (s[0] ? '<i aria-hidden="true">' + s[0] + "</i>" : "") + esc(label || s[1]) + "</span>";
  }
  /* 線の帯: "B・C" のような値は最初の A〜D。それ以外(別件・運用)は X = その他 */
  function laneOf(line) { var m = String(line == null ? "" : line).match(/[ABCD]/); return m ? m[0] : "X"; }
  function lineDot(line) { return '<span class="ld l' + laneOf(line) + '" aria-hidden="true"></span>'; }
  /* 「主の名前(補足)」の末尾の (…) を補足として分ける。[主, 補足] */
  function splitName(name) {
    var s = String(name == null ? "" : name), depth = 0;
    if (s.charAt(s.length - 1) !== ")") return [s, ""];
    for (var i = s.length - 1; i >= 0; i--) {
      var c = s.charAt(i);
      if (c === ")") depth++;
      else if (c === "(" && --depth === 0) {
        var main = s.slice(0, i).replace(/\s+$/, "");
        return main.length >= 2 ? [main, s.slice(i + 1, s.length - 1)] : [s, ""];
      }
    }
    return [s, ""];
  }
  function nameHtml(name) {
    var p = splitName(name);
    return '<span class="nm">' + md(p[0]) + "</span>" + (p[1] ? '<span class="nm-sub">' + md(p[1]) + "</span>" : "");
  }
  /* 表の見出しを各セルの data-label に写し、中身を 1 つの div にまとめる(狭い画面でカードにしたとき「見出し | 中身」の 2 列になる) */
  function resp(table) {
    var hs = [].map.call(table.querySelectorAll("thead th"), function (th) { return th.textContent; });
    table.classList.add("resp");
    [].forEach.call(table.querySelectorAll("tbody tr"), function (tr) {
      [].forEach.call(tr.children, function (td, i) {
        if (hs[i] && !td.hasAttribute("data-label")) td.setAttribute("data-label", hs[i]);
        if (td.textContent.trim() === "—") td.classList.add("opt-empty");   // 狭い画面のカードでは空の行を出さない
        if (td.colSpan > 1 || (td.children.length === 1 && td.firstElementChild.className === "cv" && td.childNodes.length === 1)) return;
        var cv = document.createElement("div"); cv.className = "cv";
        while (td.firstChild) cv.appendChild(td.firstChild);
        td.appendChild(cv);
      });
    });
  }
  /* md へのリンク。公開ページ(Artifact)には md が無いので、ファイル名の文字だけにする */
  function docLink(path, label) {
    label = label == null ? String(path).replace(/^\.\.\//, "") : label;
    if (window.PLAN_NO_MD) return '<span class="mdref">' + esc(label) + "</span>";
    return '<a href="' + esc(path) + '">' + esc(label) + "</a>";
  }
  /* ブラウザに残す小さな好み(表示の切り替えなど)。使えない所では何もしない */
  var pref = {
    get: function (k, d) { try { var v = localStorage.getItem(k); return v == null ? d : v; } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
  };
  /* "10-07〜10-13" が今日を含むか(年は data の updated から) */
  function weekHasToday(dates, updated) {
    var m = String(dates).match(/^(\d{1,2})-(\d{1,2})〜(\d{1,2})-(\d{1,2})$/), y = parseInt(String(updated).slice(0, 4), 10);
    if (!m || !y) return false;
    var a = new Date(y, +m[1] - 1, +m[2]), b = new Date(y, +m[3] - 1, +m[4], 23, 59, 59), now = new Date();
    if (b < a) b.setFullYear(y + 1);
    return now >= a && now <= b;
  }
  window.PlanUI = { ST: ST, esc: esc, md: md, stLabel: stLabel, badge: badge, laneOf: laneOf, lineDot: lineDot, splitName: splitName,
    nameHtml: nameHtml, resp: resp, docLink: docLink, pref: pref, weekHasToday: weekHasToday };
})();
