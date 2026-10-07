#!/usr/bin/env python3
"""画面(UI)の見直しの合格の基準のうち、機械で測れるものを測る道具(読むだけ。基準は `docs/spec/ui-review-criteria.md` の A)。

    python dev/ui_audit.py static                 # コードを読むだけの検査(サーバー不要)
    python dev/ui_audit.py live --port 8750       # 動いている見本サーバー(dev/demo_env.py)の画面を Playwright で測る
    python dev/ui_audit.py live --demo            # 見本サーバーを自分で起動して測り、終わったら止める
    python dev/ui_audit.py all --demo --shots <フォルダ>   # 両方 + 画面の写真(場面 × 幅 × テーマ)を保存
    python dev/ui_audit.py ... --json             # 同じ内容を JSON で
    python dev/ui_audit.py live --widths 1440 --variants light --scenes home,editor-tx   # 一部だけ(直している最中の確認用)

終了コード: Must の項目が 1 件でもあれば 1(Should は数えるだけ)。
例外: 問題の行(JS/CSS/HTML/PY)に `ui-audit: allow A-xx <理由>` を書く(コメントの中でよい)。live の検査は要素(か先祖)に `data-ui-audit-allow="A-xx"`。
同じ原因の指摘は、報告の末尾で「場面を除いた一意の数」としてもまとめる(直す量の目安)。

static で見るもの(ID は基準の文書と同じ):
  A-01 abs-path      … 取り込まれる画面(studio・editor)が fetch・href・src・location・window.open・EventSource に絶対パス("/api/" など)を書いていない
                       (API の URL は Studio.api / apiUrl() / c2rUrl() の 1 か所で作る決まり。その関数へ渡す '/api/…' は見ない。ホームへの a[data-ui-portal] も可)
  A-02 inline-script … HTML にインラインの <script>(src なし)・on〇〇= 属性が無い(CSP script-src 'self')
  A-03 native-dialog … ブラウザの confirm/alert/prompt を使っていない(UIKit.dialog を使う)
  A-05 visibility    … visibilitychange を直接使っていない(UIKit.life。ui-kit が無いときの保険(直前の行に UIKit.life / if (life))は可)
  A-06 api-ytt       … ツールの serve.py に /api/ytt/ を作っていない
  A-07 outline-none  … outline:none / outline:0 でフォーカスの輪を消していない(同じ規則に box-shadow か、同じセレクタの :focus-visible の規則があれば可)
  A-08 hard-color    … ツールの CSS/JS に固定の色(#hex・rgb()・white/black)を書いていない(トークン var(--…) を使う)
  A-09 term          … 用語集の「使わない言葉」が画面の文言(HTML の文・JS の文字列・home の画面に出る .py の文字列)に無い
  A-10 text-icon     … 絵文字・記号のアイコン(☰ ⚙ ✂ ✓ ▶ ▾ ▸ ⋮ × など)を文言に使っていない(SVG の UIKit.icon。数字の横の × (0.5×) は掛け算なので可)
  A-11 reduced-motion… ui-kit.css に prefers-reduced-motion の全体の節がある(各ツールは ui-kit の節に乗る)
  A-12 html-base     … <html lang>・<title>・<meta viewport> がある
  A-13 transition-all… transition: all を書いていない
  A-14 ui-kit-sync   … ui-kit の写しが正本と同じ(dev/sync_ui_kit.py --check)
  A-15 abbr-term     … 専門用語(EDL・Text+・FCPXML・LUFS・CER)を出す画面に abbr.ui-term の説明がある
  (target="_blank" は見ない: 窓の中では UIKit.win が自動で「このパソコンの画面 → 窓・外のサイト → ブラウザ」に振り分ける決まり)

live で見るもの(場面 × 幅 390/960/1440(主な作業の場面は 1920 も)× 明・暗。文字「大きい」は 390/960 で はみ出し・縦割れ だけ):
  A-01 abs-path      … (実行時)取り込まれた画面が自分の場所(/studio/・/transcribe/)と許した所(/cut2resolve/・/live/)の外へ要求を出していない
  A-20 overflow      … 横にはみ出さない(scrollWidth ≤ 窓の幅)
  A-21 target-size   … 押せる部品(button・input・select・summary・role=button・a.btn)の高さと幅が 28px 以上(::before/::after で広げた当たり判定も数える。checkbox/radio は 16px)
  A-22 contrast      … 文字と背景のコントラストが 4.5:1 以上(大きい文字は 3:1)。背景は文字の中心の点に重なる要素を上から合成。disabled・placeholder・aria-hidden・背景画像の上は除く
  A-23 name          … 押せる部品に名前がある(文字・aria-label・aria-labelledby・title・img の alt)。記号だけの名前(× … ▾)は不可
  A-24 label         … 入力欄(input・select・textarea)に label(for / 包む)か aria-label・aria-labelledby・title がある
  A-25 focusable     … cursor:pointer の要素は Tab で届く(button・a[href]・input・summary・tabindex≥0 か、その中)
  A-26 focus-ring    … Tab で移った要素に見えるフォーカスの輪がある(outline か box-shadow か border-color の変化)
  A-27 console       … 画面の読み込み・操作でエラー(pageerror・console.error・同じサーバーへの要求の 4xx/5xx・CSP 違反)が出ない(録画の部品が無いときの /live/api/info の 404 は除く。外のサイトの失敗は見ない)
  A-28 header        … 3 画面のヘッダーに同じ部品が同じ順にある(nav[data-ui-appnav] → .ui-ver → .ui-header-actions の最後が [data-ui-settings])
  A-29 tap-link      … 文の中以外のリンク(a)が 28px 以上(Should)
  A-30 wrap-split    … 文字が 1 文字ずつ縦に割れない(390・960。3 文字以上の文字で、行の数が文字の数以上なら不可)
  A-31 modal         … 重ねる欄(設定の引き出し・キー操作の一覧・パックの詳しい設定・スタジオの書き出し(1680 未満))は、開いたらフォーカスが中・Tab で外へ出ない・aria-modal・Esc で閉じる・閉じたら開いたボタンへ戻る
  A-32 animation     … ずっと動き続ける表示は回転の輪・読み込み中だけ。prefers-reduced-motion で動きが止まる(1 ms より長い animation が走っていない)
  A-33 pill          … 状態の札(.pill)は押せない(button・a・role=button・tabindex・cursor:pointer でない)
  A-34 disabled-why  … 押せない部品(disabled・aria-disabled)に理由(title・data-ui-why・aria-describedby)がある(Should)
  A-35 one-primary   … 1 つの入れ物(card・section・dialog・drawer・pop・details)に .btn.primary は 1 つ(Should)
  A-36 truncate      … 切れている文字(text-overflow / overflow:hidden で scrollWidth > clientWidth)に title か aria-label がある(Should)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "src")
MOUNTED = ("studio", "editor")   # 入口に取り込まれる画面(絶対パス禁止の対象)
SCREENS = {"home": ["portal.html", "portal.js", "portal.css", "intake.html", "intake.js", "backup.html", "backup.js", "live.html", "live.js"],
           "studio": ["index.html", "core.js", "rank.js", "queue.js", "review.js", "collab.js", "settings.js", "app.css", "review.css"],
           "editor": ["index.html", "app.js", "app-core.js", "app-jobs.js", "app-learn.js", "app-list.js", "app-rows.js", "app-tools.js", "cut.js", "pack-tab.js"],
           "ui-kit": ["ui-kit.css", "ui-kit.js", "styleguide.html", "styleguide.js"]}
# ホームの画面に文が出る .py(launch.py の argparse・backup.py の CLI の問いは黒い画面に出るだけなので見ない)
HOME_PY = ["autorun.py", "cases.py", "live.py", "live_archive.py", "live_export.py", "live_failures.py", "accuracy.py", "health.py", "cleanup.py", "deliver.py", "intake.py", "restart.py"]
# 用語集(docs/spec/ui-guidelines.md の 1)の「使わない言葉」のうち、文脈によらず使わないもの(「動画」「削除」「更新」「ショート」は別の意味で使うので見ない = B-04)
BANNED_TERMS = ["ストリーム", "トランスクリプト", "セグメント", "カットリスト", "編集点", "削除区間", "自動カット", "パッケージ", "再生成", "ポータル", "一括実行", "操作キー", "ショートカット",
                "文字起こしツール", "Resolve パック", "Resolveパック", "Resolve のパック", "クリップ", "プリセット", "入口"]
# 記号のアイコン(SVG の UIKit.icon に置き換える)。矢印 ← → ↑ ↓ と ①〜⑤(今をマーク。ユーザー決定)は文字として可。× は数字の横(0.5×・1080×1920)だけ可
TEXT_ICONS = "☰⚙✂✓✔✕✖×▶▾▸⋮■●★☆⚠ℹ❌✅⏵⏸⏹⏺⏭⏮↶↷↻↺⟳⟲🔍🔧📁📂📝🎬🎞🎥🔊🔇⬆⬇⬅➡"
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
ABBR_TERMS = ["EDL", "Text+", "FCPXML", "LUFS", "CER"]
ALLOW = re.compile(r"ui-audit:\s*allow\s+(A-\d\d)")
HTML_ATTRS = ("title", "placeholder", "aria-label", "alt", "data-ui-why", "data-l", "value")
MUST = {"A-01", "A-02", "A-03", "A-05", "A-06", "A-07", "A-09", "A-10", "A-11", "A-12", "A-13", "A-14",
        "A-20", "A-21", "A-22", "A-23", "A-24", "A-25", "A-26", "A-27", "A-28", "A-30", "A-31", "A-32", "A-33"}
WIDTHS = (390, 960, 1440)
WIDE = 1920
VARIANTS = ("light", "dark", "light-lg")
IGNORE_CONSOLE = ("/live/api/info",)
REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")   # この文字のあとの / は正規表現の始まり(割り算ではない)
# 取り込まれた画面が要求してよい場所(取り込みの場所 + ホームの API /api/(まとめて実行・api/ytt)+ 録画の部品 /live/)。UIKit.tools.base() が作る他ツールの URL も含む
ALLOWED_PREFIX = {"/studio/": ("/studio/", "/transcribe/", "/cut2resolve/", "/live/", "/api/"), "/transcribe/": ("/transcribe/", "/cut2resolve/", "/studio/", "/live/", "/api/")}


class Findings:
    """検査の結果の入れ物(ID・場所・説明)。"""

    def __init__(self):
        self.items = []

    def add(self, fid, where, msg):
        self.items.append({"id": fid, "where": where, "msg": msg, "must": fid in MUST})

    def by_id(self):
        out = {}
        for it in self.items:
            out.setdefault(it["id"], []).append(it)
        return out


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def rel(path):
    return os.path.relpath(path, REPO).replace("\\", "/")


def screen_files(kinds):
    for screen, names in SCREENS.items():
        for name in names:
            if name.endswith(kinds):
                p = os.path.join(SRC, screen, name)
                if os.path.exists(p) and not (screen in MOUNTED and name.startswith("ui-kit")):
                    yield screen, p


def allowed(line, fid):
    m = ALLOW.search(line)
    return bool(m and m.group(1) == fid)


def each_line(text, pattern, fid, path, out, msg, flags=0):
    """pattern に当たる行を 1 件ずつ記録する(allow のある行は除く)。"""
    for i, line in enumerate(text.split("\n"), 1):
        if re.search(pattern, line, flags) and not allowed(line, fid):
            out.add(fid, f"{rel(path)}:{i}", msg + ": " + line.strip()[:120])


def regex_starts(text, i):
    """text[i] の / が正規表現の始まりか(直前の記号・行頭・return のあとなら正規表現)。"""
    j = i - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    if j < 0 or text[j] in REGEX_BEFORE or text[j] == "\n":
        return True
    return bool(re.search(r"(?:return|typeof|case|in|of)$", text[max(0, j - 6):j + 1]))


def scan_string(text, i, strings):
    """text[i] の引用符から文字列の終わりまで進み、終わりの次の位置を返す(テンプレートの ${…} の中の文字列も拾う)。"""
    q, n, j = text[i], len(text), i + 1
    while j < n and text[j] != q:
        if text[j] == "\\":
            j += 2
        elif q == "`" and text.startswith("${", j):
            j = scan_code(text, j + 2, strings, stop="}")
        else:
            j += 1
    strings.append((i, text[i + 1:j]))
    return j + 1


def scan_code(text, i, strings, stop=None, out=None):
    """JS のコードを進む。stop(= '}')で止まり、その次の位置を返す。out にコメントを空白にした文字を積む(最上位だけ)。"""
    n, depth = len(text), 0
    while i < n:
        c = text[i]
        if stop and c == "{":
            depth += 1
        elif stop and c == "}":
            if depth == 0:
                if out is not None:
                    out.append(c)
                return i + 1
            depth -= 1
        if c in "'\"`":
            j = scan_string(text, i, strings)
            if out is not None:
                out.append(text[i:j])
            i = j
        elif c == "/" and i + 1 < n and text[i + 1] not in "/*" and regex_starts(text, i):
            j, in_class = i + 1, False
            while j < n and text[j] != "\n" and (in_class or text[j] != "/"):
                if text[j] == "\\":
                    j += 1
                elif text[j] == "[":
                    in_class = True
                elif text[j] == "]":
                    in_class = False
                j += 1
            if out is not None:
                out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            if out is not None:
                out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            if out is not None:
                out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        else:
            if out is not None:
                out.append(c)
            i += 1
    return i


def strip_js_comments(text):
    """JS のコメントを空白にする(文字列・正規表現の中の // は残す)。文字列リテラルの位置も返す。"""
    out, strings = [], []
    scan_code(text, 0, strings, out=out)
    return "".join(out), strings


def html_texts(text):
    """HTML の画面に出る文(タグの外の文と title/placeholder/aria-label などの属性)を (位置, 文) で返す。script/style/コメントは除く。"""
    out = []
    body = re.sub(r"<!--.*?-->", lambda m: " " * len(m.group(0)), text, flags=re.S)
    body = re.sub(r"<(script|style)\b.*?</\1>", lambda m: " " * len(m.group(0)), body, flags=re.S | re.I)
    for m in re.finditer(r"<[^>]+>", body):
        for a in HTML_ATTRS:
            for am in re.finditer(r'\b%s="([^"]*)"' % a, m.group(0)):
                out.append((m.start() + am.start(1), am.group(1)))
    stripped = re.sub(r"<[^>]+>", lambda m: " " * len(m.group(0)), body)
    for m in re.finditer(r"[^\s<>]+(?:[ \t][^\s<>]+)*", stripped):
        out.append((m.start(), m.group(0)))
    return out


def py_strings(path):
    """画面に出る可能性のある .py の文字列(docstring は除く)を (行, 文) で返す。"""
    import ast
    try:
        tree = ast.parse(read(path))
    except SyntaxError:
        return []
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs and re.search(r"[ぁ-んァ-ン一-龥]", node.value):
            out.append((node.lineno, node.value))
    return out


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def check_terms(path, text, out, texts):
    """A-09・A-10: 文言の中の使わない言葉と記号のアイコン。"""
    lines = text.split("\n")
    for lineno, s in texts:
        line = lines[lineno - 1] if 0 < lineno <= len(lines) else ""
        for term in BANNED_TERMS:
            if term in s and not allowed(line, "A-09"):
                out.add("A-09", f"{rel(path)}:{lineno}", f"用語「{term}」: {s.strip()[:80]}")
        s2 = re.sub(r"\d\s*×|×\s*\d", "", s)   # 0.5× や 1080×1920 の掛け算は記号のアイコンではない
        bad = [ch for ch in s2 if ch in TEXT_ICONS or EMOJI.match(ch)]
        if bad and not allowed(line, "A-10"):
            out.add("A-10", f"{rel(path)}:{lineno}", f"記号 {''.join(sorted(set(bad)))}: {s.strip()[:80]}")


def static_html(screen, path, text, out):
    each_line(text, r"<script\b(?![^>]*\bsrc=)(?![^>]*type=\"application/json\")", "A-02", path, out, "インラインの script")
    each_line(text, r"\son[a-z]+=\"", "A-02", path, out, "on〇〇= 属性", re.I)
    if screen in MOUNTED:
        for i, line in enumerate(text.split("\n"), 1):
            if re.search(r"""(?:src|href|action)=["']/(?!/)""", line) and "data-ui-portal" not in line and not allowed(line, "A-01"):
                out.add("A-01", f"{rel(path)}:{i}", "絶対パス: " + line.strip()[:120])
    if "styleguide" not in path:
        if not re.search(r"<html[^>]*\blang=", text):
            out.add("A-12", rel(path), "<html lang> が無い")
        if not re.search(r"<title>\s*\S", text):
            out.add("A-12", rel(path), "<title> が無い")
        if not re.search(r'<meta[^>]*name="viewport"', text):
            out.add("A-12", rel(path), "viewport が無い")
    texts = [(line_of(text, pos), s) for pos, s in html_texts(text)]
    check_terms(path, text, out, texts)
    for term in ABBR_TERMS:
        if re.search(r"(?<![\w+])" + re.escape(term) + r"(?![\w+])", " ".join(s for _, s in texts)) and not re.search(r'class="ui-term"[^>]*>' + re.escape(term) + "<|>" + re.escape(term) + r"</abbr>", text):
            out.add("A-15", rel(path), f"「{term}」に abbr.ui-term の説明が無い")
    style = "\n".join(re.findall(r"<style\b[^>]*>(.*?)</style>", text, flags=re.S))
    if style:
        style = re.sub(r"/\* ui-kit:css:begin \*/.*?/\* ui-kit:css:end \*/", "", style, flags=re.S)
        static_css(screen, path, style, out, offset=line_of(text, text.find("<style")))


def static_css(screen, path, text, out, offset=0):
    """CSS の検査(ファイルか <style> の中身)。"""
    lines = text.split("\n")
    for i, line in enumerate(lines, 1):
        where = f"{rel(path)}:{i + offset - (1 if offset else 0)}"
        m = re.match(r"\s*([^{]+?):focus\s*\{[^}]*outline\s*:\s*(?:none|0)\b", line)
        if m and "box-shadow" not in line and not allowed(line, "A-07") and (m.group(1).strip() + ":focus-visible") not in text:
            out.add("A-07", where, "outline:none(:focus-visible の代わりが無い): " + line.strip()[:100])
        elif not m and re.search(r"outline\s*:\s*(none|0)\b", line) and "box-shadow" not in line and ":focus-visible" not in line and not allowed(line, "A-07"):
            out.add("A-07", where, "outline:none: " + line.strip()[:100])
        if re.search(r"transition\s*:\s*all\b", line) and not allowed(line, "A-13"):
            out.add("A-13", where, line.strip()[:100])
        if screen != "ui-kit" and not re.match(r"\s*/\*", line) and not allowed(line, "A-08"):
            body = re.sub(r"/\*.*?\*/", "", line)
            body = re.sub(r"url\([^)]*\)", "", body)
            if re.search(r"(?<![\w-])#[0-9a-fA-F]{3,8}\b|(?<![\w-])rgba?\(|(?<![\w-])(?:white|black)(?![\w-])", body) and not re.match(r"\s*--[\w-]+\s*:", body):
                out.add("A-08", where, "固定の色: " + line.strip()[:100])
    if screen == "ui-kit" and path.endswith("ui-kit.css") and not re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{\s*\*", text):
        out.add("A-11", rel(path), "prefers-reduced-motion で全部の animation/transition を止める節が無い")


def static_js(screen, path, text, out):
    code, strings = strip_js_comments(text)
    each_line(code, r"(?<![\w.$])(confirm|alert|prompt)\s*\(", "A-03", path, out, "ブラウザのダイアログ")
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        if screen != "ui-kit" and "visibilitychange" in line and not allowed(line, "A-05") and not re.search(r"UIKit\.life|if \(life\)", "\n".join(lines[max(0, i - 3):i])):
            out.add("A-05", f"{rel(path)}:{i}", "visibilitychange を直接使っている: " + line.strip()[:100])
    if screen in MOUNTED:
        each_line(code, r"""(?:fetch|open|EventSource|WebSocket|URL)\s*\(\s*["`']/(?!/)|(?:href|src|location(?:\.href)?)\s*=\s*["`']/(?!/)""", "A-01", path, out, "絶対パス")
    if screen != "ui-kit":
        each_line(code, r"""(?:style\.[a-zA-Z]+|color|background[a-zA-Z]*|fill|stroke)\s*=\s*["'](?:#[0-9a-fA-F]{3,8}|rgba?\(|white|black)""", "A-08", path, out, "JS の固定の色")
    texts = [(line_of(code, pos), s) for pos, s in strings if re.search(r"[ぁ-んァ-ン一-龥]", s) or any(ch in TEXT_ICONS for ch in s)]
    check_terms(path, code, out, texts)


def static_checks(out):
    for screen, path in screen_files((".html",)):
        static_html(screen, path, read(path), out)
    for screen, path in screen_files((".css",)):
        static_css(screen, path, read(path), out)
    for screen, path in screen_files((".js",)):
        static_js(screen, path, read(path), out)
    for name in HOME_PY:
        path = os.path.join(SRC, "home", name)
        if os.path.exists(path):
            check_terms(path, read(path), out, py_strings(path))
    for tool in ("studio", "editor", "cut2resolve"):
        each_line(read(os.path.join(SRC, tool, "serve.py")), r"api/ytt/", "A-06", os.path.join(SRC, tool, "serve.py"), out, "ツールに api/ytt を作っている")
    r = subprocess.run([sys.executable, os.path.join(REPO, "dev", "sync_ui_kit.py"), "--check"], capture_output=True, text=True)
    if r.returncode != 0:
        out.add("A-14", "dev/sync_ui_kit.py --check", (r.stdout + r.stderr).strip()[:200])


# ---------- live(Playwright) ----------
LIVE_JS = r"""
(opts) => {
  const W = innerWidth, out = [];
  // 見えているか: 閉じた details の中身(content-visibility:hidden。大きさは残る)・opacity 0・visibility hidden は checkVisibility が false
  const vis = (el) => { const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && el.checkVisibility({ opacityProperty: true, visibilityProperty: true, contentVisibilityAuto: true }) && !el.closest('[hidden],[aria-hidden="true"],[inert]'); };
  const allow = (el, id) => !!el.closest('[data-ui-audit-allow~="' + id + '"]');
  const desc = (el) => { const t = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    return el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '') + (t ? ' 「' + t + '」' : ''); };
  const push = (id, el, msg) => { if (!opts.only || opts.only.includes(id)) out.push({ id, where: typeof el === 'string' ? el : desc(el), msg }); };
  // A-20 はみ出し
  if (document.documentElement.scrollWidth > W + 1) {
    const over = [...document.querySelectorAll('body *')].filter(el => vis(el) && el.getBoundingClientRect().right > W + 1).slice(0, 3).map(desc);
    push('A-20', 'document', `scrollWidth ${document.documentElement.scrollWidth} > ${W}: ` + over.join(' / '));
  }
  // A-30 縦に割れる(390・960)
  if (W <= 960) {
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let tn; const seenSplit = new Set();
    while ((tn = tw.nextNode())) {
      const s = tn.nodeValue.replace(/\s+/g, ''); if (s.length < 3) continue;
      const el = tn.parentElement; if (!el || !vis(el) || el.closest('script,style,textarea,pre,code') || allow(el, 'A-30') || seenSplit.has(el)) continue;
      const rg = document.createRange(); rg.selectNodeContents(tn); const tops = new Set([...rg.getClientRects()].map(r => Math.round(r.top)));
      if (tops.size >= s.length) { seenSplit.add(el); push('A-30', el, `${s.length} 文字が ${tops.size} 行に: 「${s.slice(0, 20)}」`); }
    }
  }
  if (opts.only && !opts.only.some(id => !['A-20', 'A-30'].includes(id))) return out;
  // A-21 / A-29 当たり判定
  const hit = (el) => { const r = { width: el.offsetWidth || el.getBoundingClientRect().width, height: el.offsetHeight || el.getBoundingClientRect().height }; let h = r.height, w = r.width;   // offset = 変形(開くときの scale)の影響を受けない大きさ
    for (const ps of ['::before', '::after']) { const b = getComputedStyle(el, ps);
      if (b.content !== 'none' && b.position === 'absolute') { const t = parseFloat(b.top) || 0, bt = parseFloat(b.bottom) || 0, l = parseFloat(b.left) || 0, rt = parseFloat(b.right) || 0;
        if (b.top !== 'auto' && b.bottom !== 'auto') h = Math.max(h, r.height - t - bt); if (b.left !== 'auto' && b.right !== 'auto') w = Math.max(w, r.width - l - rt); } }
    return [w, h]; };
  for (const el of document.querySelectorAll('button, input:not([type=hidden]), select, textarea, summary, [role=button], a.btn, a:not(p a):not(li a):not(.hint a):not(td a)')) {
    if (!vis(el) || el.closest('.ui-keybar') ) continue;
    const id = el.matches('a') && !el.matches('a.btn,[role=button]') ? 'A-29' : 'A-21';
    if (allow(el, id)) continue;
    const [w, h] = hit(el);
    const min = el.matches('input[type=checkbox],input[type=radio],input[type=range]') ? 16 : 28;
    if (h < min - 0.5 || (w < min - 0.5 && !el.matches('input[type=range],input[type=color]'))) push(id, el, `${Math.round(w)}x${Math.round(h)}px`);
  }
  // A-23 名前 / A-24 label
  const nameOf = (el) => { const vt = [...el.childNodes].filter(n => !(n.nodeType === 1 && (n.getAttribute('aria-hidden') === 'true'))).map(n => n.textContent).join('').trim();
    return (el.getAttribute('aria-label') || el.getAttribute('title') || (el.getAttribute('aria-labelledby') && document.getElementById(el.getAttribute('aria-labelledby'))?.textContent) || vt || '').trim()
    || [...el.querySelectorAll('img[alt]')].map(i => i.alt).join('') || (el.matches('input[type=submit],input[type=button]') ? el.value : ''); };
  for (const el of document.querySelectorAll('button, a[href], summary, [role=button]')) {
    if (!vis(el) || allow(el, 'A-23')) continue;
    const nm = nameOf(el);
    if (!nm) push('A-23', el, '名前が無い(文字・aria-label・title)');
    else if (/^[\s×✕⋮▾▸…・\-–—|]+$/.test(nm)) push('A-23', el, `名前が記号だけ「${nm}」`);
  }
  for (const el of document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea')) {
    if (!vis(el) || allow(el, 'A-24')) continue;
    const ok = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title') || el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`));
    if (!ok) push('A-24', el, 'label が無い' + (el.placeholder ? '(placeholder だけ: ' + el.placeholder.slice(0, 30) + ')' : ''));
  }
  // A-25 cursor:pointer なのに Tab で届かない / A-33 札は押せない / A-34 押せない理由 / A-35 primary は 1 つ / A-36 切れた文字
  const focusable = 'button, a[href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"]), [contenteditable=true], label, video[controls], audio[controls]';
  const prim = new Map();
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el)) continue;
    const cs = getComputedStyle(el);
    if (cs.cursor === 'pointer' && !allow(el, 'A-25') && !(el.closest(focusable) || el.querySelector(focusable) || el.matches('details, .ui-toasts *, [data-ui-audit-skip]') || el.closest('label')))
      push('A-25', el, 'cursor:pointer だが Tab で届かない');
    if (el.matches('.pill') && !allow(el, 'A-33') && (el.matches('button, a[href], [role=button], [tabindex]') || cs.cursor === 'pointer'))
      push('A-33', el, '状態の札が押せる形になっている(押せるものは .btn)');
    if (el.matches(':disabled, [aria-disabled="true"]') && !allow(el, 'A-34') && !(el.getAttribute('title') || el.getAttribute('data-ui-why') || el.getAttribute('aria-describedby') || el.closest('[data-ui-why]')))
      push('A-34', el, '押せない理由が無い(title / data-ui-why / aria-describedby)');
    if (el.matches('.btn.primary') && !allow(el, 'A-35')) { const box = el.closest('.card, section, dialog, .ui-drawer, .ui-pop-body, .ui-menu-pop, details, form, .pt-auto, aside, header, main') || document.body;
      prim.set(box, (prim.get(box) || []).concat(desc(el))); }
    if ((cs.textOverflow === 'ellipsis' || (cs.overflow === 'hidden' && cs.whiteSpace === 'nowrap')) && el.scrollWidth > el.clientWidth + 1 && el.childElementCount === 0 && !allow(el, 'A-36') && !el.matches('.sr-only')
        && !(el.getAttribute('title') || el.getAttribute('aria-label') || el.closest('[title]')))
      push('A-36', el, '切れた文字に title が無い');
  }
  for (const [box, list] of prim) if (list.length > 1) push('A-35', box, 'primary が ' + list.length + ' つ: ' + list.join(' / '));
  // A-22 コントラスト(文字の中心の点に重なる要素を上から合成)
  const parse = (s) => { let m = s.match(/rgba?\(([^)]+)\)/); if (m) { const p = m[1].split(/[\s,\/]+/).map(Number); return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; }
    m = s.match(/color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)/); if (m) return [+m[1]*255, +m[2]*255, +m[3]*255, m[4] === undefined ? 1 : +m[4]];
    return null; };
  const over = (top, under) => { const a = top[3]; return [top[0]*a + under[0]*(1-a), top[1]*a + under[1]*(1-a), top[2]*a + under[2]*(1-a), Math.min(1, a + under[3]*(1-a))]; };
  const baseBg = (() => { const b = parse(getComputedStyle(document.body).backgroundColor), h = parse(getComputedStyle(document.documentElement).backgroundColor); const w = [255, 255, 255, 1];
    const hh = h && h[3] > 0 ? over(h, w) : w; return b && b[3] > 0 ? over(b, hh) : hh; })();
  const bgAt = (el, x, y) => { const stack = document.elementsFromPoint(x, y); let i = stack.indexOf(el); if (i < 0) i = stack.findIndex(e => e.contains(el)); if (i < 0) return null;   // 何かに隠れている
    let acc = null;
    for (; i < stack.length; i++) { const e = stack[i]; const cs = getComputedStyle(e); if (cs.backgroundImage !== 'none') return null;   // 背景画像・グラデーションの上は比が決まらない(見直し役が見る)
      if (e.matches('video, canvas, img')) return null;
      const c = parse(cs.backgroundColor); if (!c || c[3] === 0) continue;
      acc = acc ? over(acc, c) : c; if (acc[3] >= 0.999) return acc; }
    return acc ? over(acc, baseBg) : baseBg; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126*f(c[0]) + 0.7152*f(c[1]) + 0.0722*f(c[2]); };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };
  const seen = new Set(); const modalDlg = document.querySelector('dialog:modal');   // showModal の後ろ(::backdrop の下)は見ない
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node; while ((node = walker.nextNode())) {
    const txt = node.nodeValue.trim(); if (!txt) continue;
    const el = node.parentElement; if (!el || seen.has(el) || !vis(el) || allow(el, 'A-22')) continue; seen.add(el);
    if (modalDlg && !modalDlg.contains(el)) continue;
    if (el.closest('script,style,[disabled],[aria-disabled="true"],.ui-toasts,option,canvas,video,.ui-keybar,.tt-cap-look,.tt-cap-line') ) continue;
    const cs = getComputedStyle(el); const fg = parse(cs.color); if (!fg || fg[3] === 0) continue;
    let op = 1; for (let e = el; e && e !== document.body; e = e.parentElement) op *= parseFloat(getComputedStyle(e).opacity);
    const rg = document.createRange(); rg.selectNodeContents(node); const rects = [...rg.getClientRects()].filter(r => r.width > 0 && r.height > 0); if (!rects.length) continue;
    const r0 = rects[0]; const x = Math.min(innerWidth - 1, Math.max(0, r0.left + Math.min(6, r0.width / 2))), y = Math.min(innerHeight - 1, Math.max(0, r0.top + r0.height / 2));
    if (r0.bottom < 0 || r0.top > innerHeight) continue;   // 画面の外(スクロールしないと見えない)は elementsFromPoint で取れない
    const bg = bgAt(el, x, y); if (!bg) continue;
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 600;
    const need = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
    const a = fg[3] * op; const fgc = a < 1 ? [fg[0]*a + bg[0]*(1-a), fg[1]*a + bg[1]*(1-a), fg[2]*a + bg[2]*(1-a)] : fg;
    const rt = ratio(fgc, bg);
    if (rt < need) push('A-22', el, `${rt.toFixed(2)}:1 (${need} が要る) 文字 ${cs.color}${op < 1 ? ' ×opacity ' + op.toFixed(2) : ''} 背景 rgb(${bg.slice(0,3).map(Math.round).join(',')}) ${Math.round(size)}px: 「${txt.slice(0, 30)}」`);
  }
  // A-28 ヘッダー(部品と順)
  if (opts.header) { const h = document.querySelector('.ui-header');
    if (!h) push('A-28', 'header', '.ui-header が無い');
    else { const order = ['nav[data-ui-appnav]', '.ui-ver', '.ui-header-actions']; let last = -1;
      for (const sel of order) { const e = h.querySelector(sel); if (!e) { push('A-28', 'header', sel + ' が無い'); continue; }
        const all = [...h.querySelectorAll('*')]; const idx = all.indexOf(e); if (idx < last) push('A-28', 'header', sel + ' の順が違う'); last = idx; }
      const acts = h.querySelector('.ui-header-actions'); const st = acts && acts.querySelector('[data-ui-settings]');
      if (!st) push('A-28', 'header', '[data-ui-settings] が無い');
      else { const kids = [...acts.children].filter(vis); if (kids[kids.length - 1] !== st && !kids[kids.length - 1].contains(st)) push('A-28', 'header', '⚙ 設定が右端ではない: ' + kids.map(desc).join(' / ')); } } }
  // A-32 ずっと動き続ける表示
  for (const an of document.getAnimations()) { if (an.playState !== 'running') continue; const ef = an.effect; const t = ef && ef.target; if (!t || !vis(t)) continue;
    const tm = ef.getTiming(); const nm = an.animationName || ''; if (tm.iterations === Infinity && !/spin|rot|indet|skel|busy|pulse-run/.test(nm) && !t.matches('.ui-spin, .ui-spin *, .pill.run, .pill.run *, .ui-skel, .ui-indet, .indet, .ui-miniprogress.indet, [class*=spin], [class*=rot]') && !allow(t, 'A-32'))
      push('A-32', t, 'ずっと動くアニメーション: ' + (an.animationName || an.id || '?')); }
  return out;
}
"""

FOCUS_JS = r"""
() => { const el = document.activeElement; if (!el || el === document.body) return null;
  const cs = getComputedStyle(el); const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none';
  const t = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 30);
  return { ok: ring, desc: el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (t ? ' 「' + t + '」' : ''), allow: !!el.closest('[data-ui-audit-allow~="A-26"]'), border: cs.borderColor }; }
"""

REDUCED_JS = r"""
() => document.getAnimations().filter(a => a.playState === 'running' && a.effect && (a.effect.getTiming().duration > 1)).map(a => (a.animationName || a.id || '?') + '@' + ((a.effect.target && a.effect.target.tagName) || '')).slice(0, 5)
"""


def demo_doc_id(base):
    """見本の文字起こしの id を 1 つ返す(無ければ空)。行があって評価用でない文書を選ぶ。"""
    import urllib.request
    try:
        with urllib.request.urlopen(base + "/transcribe/api/transcripts", timeout=10) as r:
            items = json.load(r)
    except Exception:
        return ""
    items = items.get("items") if isinstance(items, dict) else items
    if not isinstance(items, list):
        return ""
    for it in items:
        if isinstance(it, dict) and it.get("id") and it.get("rows") and not it.get("evalSet"):
            return it["id"]
    return items[0]["id"] if items and isinstance(items[0], dict) and items[0].get("id") else ""


def default_scenes(base):
    """live で開く場面(名前・URL・開いたあとの操作)。操作は [('click', セレクタ) | ('fill', セレクタ, 文) | ('key', キー) | ('wait', ms) | ('eval', JS)]。
    modal = {root, opener} は A-31(重ねる欄の約束)を見る。wide は 1920 でも見る。
    見本のデータ(dev/demo_env.py)の配信 demo0000000 と、文字起こし 1 件を使う。副作用のあるボタン(終了・片付け・実行)は押さない。"""
    doc = demo_doc_id(base)
    ed = base + "/transcribe/?doc=" + doc if doc else base + "/transcribe/"
    styleguide = "file://" + os.path.join(SRC, "ui-kit", "styleguide.html")
    settings = {"root": "#uiSettingsDrawer", "opener": "[data-ui-settings]"}
    return [
        {"name": "home", "url": base + "/", "header": True, "wide": True},
        {"name": "home-case-open", "url": base + "/", "actions": [("click", "details.pt-case > summary"), ("wait", 500)]},
        {"name": "home-empty-filter", "url": base + "/", "actions": [("fill", "#fText", "zzzz-no-match-zzzz"), ("wait", 500)]},
        {"name": "home-advanced", "url": base + "/", "actions": [("click", "#advancedBox > summary"), ("wait", 400)]},
        {"name": "home-settings", "url": base + "/", "actions": [("click", "[data-ui-settings]"), ("wait", 400)], "modal": settings},
        {"name": "studio-rank", "url": base + "/studio/?step=rank", "header": True},
        {"name": "studio-queue", "url": base + "/studio/?step=queue"},
        {"name": "studio-review-empty", "url": base + "/studio/?step=review"},
        {"name": "studio-review", "url": base + "/studio/?video=demo0000000", "wide": True},
        {"name": "studio-review-marks", "url": base + "/studio/?video=demo0000002"},   # マークのある配信(行の札・理由の札)
        {"name": "studio-review-export", "url": base + "/studio/?video=demo0000000", "actions": [("click", "#rvJump [data-jump=export]"), ("wait", 500)],
         "modal": {"root": "#rvExport", "opener": "#rvJump [data-jump=export]", "docked_from": 1680}},
        {"name": "studio-review-pick", "url": base + "/studio/?video=demo0000000", "actions": [("click", "#rvPick > summary"), ("wait", 400)]},
        {"name": "studio-keys", "url": base + "/studio/?video=demo0000000", "actions": [("click", "#btnKeys"), ("wait", 400)], "modal": {"root": "#keyHelp", "opener": "#btnKeys"}},
        {"name": "studio-settings", "url": base + "/studio/?step=rank", "actions": [("click", "[data-ui-settings]"), ("wait", 400)], "modal": settings},
        {"name": "editor-empty", "url": base + "/transcribe/", "header": True},
        {"name": "editor-tx", "url": ed + "#tx", "wide": True},
        {"name": "editor-tx-more", "url": ed + "#tx", "actions": [("click", "#moreTools > summary"), ("wait", 300)]},
        {"name": "editor-tx-jump", "url": ed + "#tx", "actions": [("click", "#jumpMenu > summary"), ("wait", 300)]},
        {"name": "editor-cut", "url": ed + "#cut", "wide": True},
        {"name": "editor-pack", "url": ed + "#pack"},
        {"name": "editor-pack-settings", "url": ed + "#pack", "actions": [("click", "#pkSettingsBtn"), ("wait", 500)], "modal": {"root": "#pkSettingsDrawer", "opener": "#pkSettingsBtn"}},
        {"name": "editor-keys", "url": ed + "#tx", "actions": [("click", "#btnKeys"), ("wait", 400)], "modal": {"root": "#keys", "opener": "#btnKeys"}, "min_width": 561},   # 560px 以下はキー操作のボタンを出さない(? キーだけ)
        {"name": "editor-settings", "url": base + "/transcribe/", "actions": [("click", "[data-ui-settings]"), ("wait", 400)], "modal": settings},
        {"name": "styleguide", "url": styleguide},
    ]


def do_actions(pg, actions):
    for act in actions:
        if act[0] == "click":
            pg.click(act[1], timeout=5000)
        elif act[0] == "fill":
            pg.fill(act[1], act[2], timeout=5000)
        elif act[0] == "key":
            pg.keyboard.press(act[1])
        elif act[0] == "wait":
            pg.wait_for_timeout(act[1])
        elif act[0] == "eval":
            pg.evaluate(act[1])


def check_modal(pg, scene, width, tag, out):
    """A-31: 重ねる欄の約束(フォーカスが中・Tab で外へ出ない・aria-modal・Esc で閉じる・開いたボタンへ戻る)。"""
    m = scene["modal"]
    root, opener = m["root"], m["opener"]
    inside = "(sel) => { const r = document.querySelector(sel); const a = document.activeElement; return !!(r && a && (r === a || r.contains(a))); }"
    if m.get("docked_from") and width >= m["docked_from"]:
        return   # 横に固定(docked)の欄は閉じ込めないのが正しい
    if not pg.evaluate(inside, root):
        out.add("A-31", f"{tag} {root}", "開いたのにフォーカスが中に無い")
    modal = pg.evaluate("(sel) => { const r = document.querySelector(sel); return !!(r && (r.getAttribute('aria-modal') === 'true' || (r.tagName === 'DIALOG' && r.matches(':modal')))); }", root)
    if not modal:
        out.add("A-31", f"{tag} {root}", "aria-modal=true(dialog は showModal)が無い")
    for _ in range(30):
        pg.keyboard.press("Tab")
        if not pg.evaluate(inside, root):
            # body に落ちるのは、ブラウザの枠(アドレス欄)へ一巡している途中(headless では body になる)。裏の要素へ移ったときだけ不可
            where = pg.evaluate("() => { const a = document.activeElement; return a && a !== document.body ? a.tagName + (a.id ? '#' + a.id : '') + (a.className ? '.' + String(a.className).split(' ')[0] : '') : '' }")
            if where:
                out.add("A-31", f"{tag} {root}", "Tab でフォーカスが外(裏の要素)へ出た: " + where)
                break
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(300)
    still = pg.evaluate("(sel) => { const r = document.querySelector(sel); if (!r) return false; if (r.tagName === 'DIALOG') return r.open; return !r.hidden && getComputedStyle(r).display !== 'none'; }", root)
    if still:
        out.add("A-31", f"{tag} {root}", "Esc で閉じない")
        return
    back = pg.evaluate("(sel) => { const o = document.querySelector(sel); const a = document.activeElement; return !!(o && a && (o === a || o.contains(a))); }", opener)
    if not back:
        out.add("A-31", f"{tag} {root}", "閉じたあと開いたボタンへフォーカスが戻らない: " + (pg.evaluate("() => { const a = document.activeElement; return a ? a.tagName + (a.id ? '#' + a.id : '') : '' }") or ""))


def run_scene(pg, scene, width, variant, out, shots):
    """1 つの場面を 1 つの幅・テーマで開いて測る。"""
    errors, reqs = [], []
    origin = (re.match(r"https?://[^/]+", scene["url"]) or re.match(r"file://.*/", scene["url"])).group(0)
    handler = lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None   # noqa: E731 1 行の捕まえ役
    perr = lambda e: errors.append("pageerror: " + str(e))   # noqa: E731
    resp = lambda r: errors.append(f"{r.status} {r.url}") if r.status >= 400 and r.url.startswith(origin) and not any(x in r.url for x in IGNORE_CONSOLE) else None   # noqa: E731
    req = lambda r: reqs.append(r.url) if r.url.startswith(origin) else None   # noqa: E731
    pg.on("console", handler); pg.on("pageerror", perr); pg.on("response", resp); pg.on("request", req)
    tag = f"{scene['name']}@{width}/{variant['name']}"
    only = variant.get("only")
    try:
        pg.goto(scene["url"], wait_until="networkidle", timeout=30000)
        pg.wait_for_timeout(600)
        do_actions(pg, scene.get("actions", []))
        pg.wait_for_timeout(300)
        for it in pg.evaluate(LIVE_JS, {"header": bool(scene.get("header")), "only": only}):
            out.add(it["id"], f"{tag} {it['where']}", it["msg"])
        if only:
            return
        for e in errors:
            out.add("A-27", tag, e[:160])
        path = re.sub(r"^https?://[^/]+", "", scene["url"])
        for pre, ok in ALLOWED_PREFIX.items():
            if path.startswith(pre):
                for u in reqs:
                    p = u[len(origin):]
                    if not p.startswith(ok):
                        out.add("A-01", f"{tag}", f"自分の場所の外への要求: {p[:100]}")
        if shots:
            pg.screenshot(path=os.path.join(shots, f"{scene['name']}-{width}-{variant['name']}.png"), full_page=width != 390)
        if width == 1440 and variant["name"] == "light":
            if scene.get("modal"):
                check_modal(pg, scene, width, tag, out)
            else:
                focus_walk(pg, tag, out)
        if scene.get("modal") and width != 1440 and variant["name"] == "light":
            check_modal(pg, scene, width, tag, out)
    except Exception as e:   # 場面が開けないのも 1 件として残す(検査を止めない)
        out.add("A-27", tag, f"場面を開けない: {str(e)[:140]}")
    finally:
        pg.remove_listener("console", handler); pg.remove_listener("pageerror", perr); pg.remove_listener("response", resp); pg.remove_listener("request", req)


def focus_walk(pg, tag, out, steps=60):
    """A-26: Tab で順に移り、フォーカスの輪が見えるかを見る(outline・box-shadow・枠の色の変化)。"""
    pg.evaluate("() => { document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); }")
    seen = set()
    for _ in range(steps):
        pg.keyboard.press("Tab")
        info = pg.evaluate(FOCUS_JS)
        if not info:
            continue
        if info["desc"] in seen:
            break
        seen.add(info["desc"])
        if not info["ok"] and not info["allow"]:
            # 枠の色だけで見せる部品: フォーカスの前後で borderColor が変わっていれば可
            moved = pg.evaluate("() => { const a = document.activeElement; a.blur(); const b = getComputedStyle(a).borderColor; a.focus(); return b; }")
            if moved == info["border"]:
                out.add("A-26", f"{tag} {info['desc']}", "フォーカスの輪が見えない(outline も box-shadow も枠の変化も無い)")


def variant_defs(names):
    out = []
    for n in names:
        if n == "light-lg":
            out.append({"name": n, "theme": "light", "fs": "lg", "only": ["A-20", "A-30"], "widths": (390, 960)})
        else:
            out.append({"name": n, "theme": n})
    return out


def live_checks(base, out, shots=None, scenes=None, widths=WIDTHS, variants=VARIANTS, names=None):
    from playwright.sync_api import sync_playwright
    scenes = scenes or default_scenes(base)
    if names:
        scenes = [s for s in scenes if s["name"] in names]
    if shots:
        os.makedirs(shots, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for variant in variant_defs(variants):
            for width in list(variant.get("widths") or widths) + ([WIDE] if WIDE not in widths and not variant.get("widths") else []):
                ctx = browser.new_context(viewport={"width": width, "height": 900 if width > 400 else 800}, reduced_motion="no-preference")
                ctx.add_init_script("try{localStorage.setItem('ytt:theme','%s');%s}catch(e){}" % (variant["theme"], "localStorage.setItem('ytt:fs','lg');" if variant.get("fs") else "localStorage.removeItem('ytt:fs');"))
                pg = ctx.new_page()
                for scene in scenes:
                    if (width == WIDE and not scene.get("wide")) or width < scene.get("min_width", 0):
                        continue
                    run_scene(pg, scene, width, variant, out, shots)
                ctx.close()
        # A-32: prefers-reduced-motion で動きが止まる(主な 3 場面)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        pg = ctx.new_page()
        for scene in scenes:
            if scene["name"] in ("home", "studio-review", "editor-tx"):
                try:
                    pg.goto(scene["url"], wait_until="networkidle", timeout=30000)
                    pg.wait_for_timeout(500)
                    for a in pg.evaluate(REDUCED_JS):
                        out.add("A-32", f"{scene['name']}@1440/reduce", "prefers-reduced-motion でも動いている: " + a)
                except Exception as e:
                    out.add("A-27", f"{scene['name']}@1440/reduce", f"場面を開けない: {str(e)[:120]}")
        ctx.close()
        browser.close()


def start_demo(port):
    """見本サーバーを起動して READY まで待つ(戻り値: プロセス)。"""
    env = dict(os.environ, YTT_DATA_DIR="inplace", PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([sys.executable, os.path.join(REPO, "dev", "demo_env.py"), "--port", str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    deadline = time.time() + 180
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line and proc.poll() is not None:
            raise SystemExit("見本サーバーが起動できなかった")
        if line.startswith("READY"):
            return proc
    proc.terminate()
    raise SystemExit("見本サーバーの起動が 180 秒で終わらなかった")


def report(out, as_json):
    groups = out.by_id()
    uniq = {}
    for it in out.items:
        key = (it["id"], re.sub(r"^\S+@\d+/[\w-]+ ", "", it["where"]), re.sub(r"\d+(\.\d+)?", "#", it["msg"])[:60])
        uniq.setdefault(key, 0)
        uniq[key] += 1
    if as_json:
        print(json.dumps({"findings": out.items, "counts": {k: len(v) for k, v in groups.items()}, "unique": len(uniq)}, ensure_ascii=False, indent=1))
    else:
        for fid in sorted(groups):
            items = groups[fid]
            n_uniq = len({k for k in uniq if k[0] == fid})
            print(f"== {fid} ({'Must' if fid in MUST else 'Should'}): {len(items)} 件(場面を除いて {n_uniq})")
            for it in items:
                print(f"  {it['where']}  {it['msg']}")
        must = sum(1 for it in out.items if it["must"])
        should = len(out.items) - must
        print(f"合計 Must {must} 件・Should {should} 件(場面を除いて一意 {len(uniq)})。Must 0 で合格")
    return 1 if any(it["must"] for it in out.items) else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["static", "live", "all"])
    ap.add_argument("--port", type=int, default=8750)
    ap.add_argument("--demo", action="store_true", help="見本サーバーを自分で起動する")
    ap.add_argument("--shots", help="画面の写真を保存するフォルダ")
    ap.add_argument("--widths", default=",".join(str(w) for w in WIDTHS))
    ap.add_argument("--variants", default=",".join(VARIANTS), help="light,dark,light-lg(文字「大きい」で はみ出し・縦割れ だけ)")
    ap.add_argument("--scenes", help="場面の名前(カンマ区切り。省略で全部)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = Findings()
    if a.mode in ("static", "all"):
        static_checks(out)
    proc = None
    if a.mode in ("live", "all"):
        if a.demo:
            proc = start_demo(a.port)
        try:
            live_checks(f"http://localhost:{a.port}", out, a.shots, widths=[int(w) for w in a.widths.split(",")], variants=a.variants.split(","), names=a.scenes.split(",") if a.scenes else None)
        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()
    return report(out, a.json)


if __name__ == "__main__":
    sys.exit(main())
