"""規則の見張り(dev/rule_checks.py・dev/rule_imports.py・dev/ui_audit.py の A-16〜A-19・A-37)が、破った見本で止まり、正しい見本で通ることを確かめる。

    py -3.10 -m unittest dev/tests/test_rule_checks.py

規則 1 つ 1 行の表: (名前, 検査の関数, 入力, 止まるときの文言の一部 / None = 通る)。検査そのものの計算の芯(⑤a)。
規則を実物のリポジトリに当てた結果(0 件)は dev/lint.py の `rule`・dev/ui_audit.py static が見る。
"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所に書かない(ytt.datadir)
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # dev/
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "src"))
import rule_checks as RC  # noqa: E402
import rule_imports as RI  # noqa: E402
import ui_audit as UA  # noqa: E402
from ytt import testkit  # noqa: E402


class Table(unittest.TestCase):
    def run_table(self, rows):
        for name, fn, args, want in rows:
            with self.subTest(name):
                got = fn(*args)
                if want is None:
                    self.assertEqual(got, [], name)
                else:
                    self.assertTrue(any(want in p for p in got), "%s: %r に %r が無い" % (name, got, want))


GOOD_PUSH = "python dev\\push_helper.py removals\r\ngit add -A\r\npython dev\\push_helper.py check\r\ngit reset -q\r\ncall :notes\r\ncall :notes\r\npython dev\\push_helper.py notes\r\n"
GOOD_MEMBER = {"id": "a", "name": "あ", "en": "A", "hex": "#112233", "colors": [{"hex": "#112233", "label": "x", "src": ["s1"], "confidence": "high"}], "src": ["s1"]}


def members(n=51, **change):
    ms = []
    for i in range(n):
        ms.append(dict(GOOD_MEMBER, id="m%d" % i, name="n%d" % i))
    if change:
        ms[0] = dict(ms[0], **change)
    groups = [{"id": "g%d" % i, "branch": b, "name": b, "members": ms if i == 0 else [dict(GOOD_MEMBER, id="z%d" % i, name="z%d" % i)]} for i, b in enumerate(("JP", "DEV_IS", "EN", "ID", "GRAD"))]
    return {"version": 2, "updated": "2026-10-18", "groups": groups, "sources": [{"id": "s1"}]}


class TestFileShapes(Table):
    def test_table(self):
        self.run_table([
            ("bat: ASCII・CRLF は通る", RC.bat_problems, ("a.bat", b"@echo off\r\nexit\r\n"), None),
            ("bat: 日本語が入ると止まる", RC.bat_problems, ("a.bat", "@echo 日本\r\n".encode("utf-8")), "ASCII 以外"),
            ("bat: LF だけだと止まる", RC.bat_problems, ("a.bat", b"@echo off\nexit\r\n"), "CRLF でない"),
            ("requirements: ASCII は通る", RC.requirements_problems, ("r.txt", b"numpy==2.2.6\r\n"), None),
            ("requirements: 日本語の 1 行目で止まる", RC.requirements_problems, ("r.txt", "# 日本語\nnumpy\n".encode("utf-8")), "ASCII 以外"),
            ("push.bat: 正しい順は通る", RC.push_bat_problems, (GOOD_PUSH,), None),
            ("push.bat: 検査のあとの reset が無い", RC.push_bat_problems, (GOOD_PUSH.replace("git reset -q", "echo"),), "git reset -q"),
            ("push.bat: 保管庫を送るのが 1 か所", RC.push_bat_problems, (GOOD_PUSH.replace("call :notes\r\n", "", 1),), "call :notes"),
            ("push.bat: 順が逆", RC.push_bat_problems, ("python dev\\push_helper.py check\r\ngit add -A\r\npython dev\\push_helper.py removals\r\ngit reset -q\r\ncall :notes\r\ncall :notes\r\npush_helper.py notes",), "処理の順"),
        ])

    def test_rules_on_a_copy_of_the_repo(self):
        """実際のファイルの探し方まで: 破ったファイルを置いた仮のリポジトリに規則を当てる"""
        tmp = testkit.tempdir(self)
        testkit.write_text(os.path.join(tmp, "setup", "install.bat"), "@echo off\r\n")
        testkit.write_text(os.path.join(tmp, "bad.bat"), "@echo 日本\n")
        testkit.write_text(os.path.join(tmp, "setup", "requirements.txt"), "# 日本語\n")
        testkit.write_text(os.path.join(tmp, "push.bat"), "git add -A\r\n")
        self.assertTrue(any("ASCII" in p and "bad.bat" in p for p in RC.rule_bat_ascii_crlf(tmp)))
        self.assertTrue(any("CRLF" in p for p in RC.rule_bat_ascii_crlf(tmp)))
        self.assertTrue(any("requirements.txt" in p for p in RC.rule_requirements_ascii(tmp)))
        self.assertTrue(RC.rule_push_bat_order(tmp))
        os.remove(os.path.join(tmp, "bad.bat"))
        self.assertEqual(RC.rule_bat_ascii_crlf(tmp), [])   # 直せば通る
        os.remove(os.path.join(tmp, "setup", "install.bat"))
        self.assertIn("setup/install.bat が見つからない", RC.rule_bat_ascii_crlf(tmp))


class TestE2eSuite(Table):
    def test_table(self):
        tmp = testkit.tempdir(self)
        testkit.write_text(os.path.join(tmp, "a", "e2e_a.py"), "")
        suite = [("g", "a/e2e_a.py", [], 1), ("g", "a/e2e_gone.py", [], 1)]
        self.run_table([
            ("一覧にあって実在しない", RC.suite_problems, (tmp, suite, set(), {"a/e2e_a.py"}), "実在しない: a/e2e_gone.py"),
            ("実在するのに一覧にも除外にも無い", RC.suite_problems, (tmp, suite[:1], set(), {"a/e2e_a.py", "a/e2e_new.py"}), "e2e を足したら"),
            ("除外に入れれば通る", RC.suite_problems, (tmp, suite[:1], {"a/e2e_a.py"}, {"a/e2e_a.py"}), None),
            ("編集の一式が一覧に無い物を流す", RC.suite_problems, (tmp, suite[:1], set(), {"a/e2e_a.py"}, ["x-case"], [], {"y"}), "CASES_E2E"),
            ("編集だけの e2e が復活", RC.suite_problems, (tmp, suite[:1], set(), {"a/e2e_a.py"}, [], ["old"], set()), "E2E が空でない"),
        ])


class TestDataShapes(Table):
    def test_members(self):
        no_en = members(en="")
        dup = members()
        dup["groups"][0]["members"][1] = dict(dup["groups"][0]["members"][0])
        self.run_table([
            ("members: 正しい形は通る", RC.members_problems, (members(),), None),
            ("members: version が違う", RC.members_problems, (dict(members(), version=1),), "version"),
            ("members: en が空", RC.members_problems, (no_en,), "ローマ字・英語名"),
            ("members: hex が #なし", RC.members_problems, (members(hex="112233"),), "hex の形"),
            ("members: 先頭の色と hex が違う", RC.members_problems, (members(colors=[{"hex": "#000000", "label": "", "src": [], "confidence": "high"}]),), "先頭と hex"),
            ("members: ラベルが 13 字", RC.members_problems, (members(colors=[{"hex": "#112233", "label": "x" * 13, "src": [], "confidence": "high"}]),), "ラベル"),
            ("members: confidence が無い", RC.members_problems, (members(colors=[{"hex": "#112233", "label": "", "src": []}]),), "confidence"),
            ("members: 知らない出典", RC.members_problems, (members(src=["s9"]),), "知らない出典"),
            ("members: id が重なる", RC.members_problems, (dup,), "id が無いか重なっている"),
            ("members: グループが足りない", RC.members_problems, (dict(members(), groups=members()["groups"][:4]),), "このグループが無い: GRAD"),
            ("members: 人数が少なすぎる", RC.members_problems, (members(n=3),), "50 人以下"),
        ])

    def test_roster(self):
        good = {"groups": [{"id": "hololive", "names": ["あ", "い"]}, {"id": "units", "names": ["ゆ"]}],
                "members": [{"name": "あ", "aliases": ["a1"], "common": ["a1"], "region": "JP"}, {"name": "い", "aliases": ["i1"], "region": "JP"}] + [
                    {"name": "あ", "aliases": ["z%d" % i], "region": "JP"} for i in range(50)]}
        gr = {"hololive": "JP"}

        def mut(**kw):
            d = json.loads(json.dumps(good))
            d["members"][0].update(kw)
            return d
        dup = json.loads(json.dumps(good))
        dup["members"][1]["aliases"] = ["a1"]
        self.run_table([
            ("roster: 正しい形は通る", RC.roster_problems, (good, gr, ("JP", "EN")), None),
            ("roster: 組にいない人", RC.roster_problems, (mut(name="だれか"), gr, ("JP",)), "名簿の人でない"),
            ("roster: 呼び名が同じ", RC.roster_problems, (dup, gr, ("JP",)), "同じ呼び名"),
            ("roster: 地域が組と合わない", RC.roster_problems, (mut(region="EN"), gr, ("JP", "EN")), "region が組と合わない"),
            ("roster: 普通の言葉が呼び名に無い", RC.roster_problems, (mut(common=["他"]), gr, ("JP",)), "普通の言葉"),
        ])

    def test_schema_shape(self):
        item = {"key": "a.b", "type": "int", "label": "L", "min": 0, "max": 5, "default": 3}
        sc = lambda **kw: {"sections": [{"id": "s", "title": "T", "store": "home", "groups": [{"items": [dict(item, **kw)]}]}]}   # noqa: E731
        self.run_table([
            ("schema: 正しい形は通る", RI.schema_shape_problems, (sc(),), None),
            ("schema: 知らない型", RI.schema_shape_problems, (sc(type="color"),), "知らない型"),
            ("schema: 既定が範囲の外", RI.schema_shape_problems, (sc(default=9),), "範囲の外"),
            ("schema: label が無い", RI.schema_shape_problems, (sc(label=""),), "label"),
            ("schema: enum の既定が選択肢に無い", RI.schema_shape_problems, (sc(type="enum", options=[["x", "X"]], default="y"),), "選択肢に無い"),
            ("schema: when が知らない鍵", RI.schema_shape_problems, (sc(when={"key": "zz"}),), "when"),
        ])


class TestSourceRules(Table):
    def test_table(self):
        self.run_table([
            ("write_doc: store の中だけは通る", RC.write_doc_problems, ({"human/proof/store.py": "write_doc(1, 2)\n", "x.py": "# write_doc(1)\ndef write_doc(a): pass\n"},), None),
            ("write_doc: ほかのファイルで呼ぶと止まる", RC.write_doc_problems, ({"manage/x.py": "store.write_doc(t, d)\n"},), "manage/x.py"),
            ("yt-dlp -o: ytdlp_out を通せば通る", RC.ytdlp_template_problems, ("a.py", 'cmd = ["-o", yturl.ytdlp_out(x)]'), None),
            ("yt-dlp -o: os.path.join を直に渡すと止まる", RC.ytdlp_template_problems, ("a.py", 'cmd = ["-o", os.path.join(d, "x")]'), "ytdlp_out"),
            ("TOOL_APPS: runtime そのままは通る", RC.tool_apps_problems, ("TOOL_APPS = _runtime.TOOL_APPS\n",), None),
            ("TOOL_APPS: 書き直すと止まる", RC.tool_apps_problems, ('TOOL_APPS = {"studio": "x"}\n',), "TOOL_APPS"),
            ("keys: adopt が無ければ通る", RC.keys_adopt_problems, ("def key(adoptedBy): pass",), None),
            ("keys: perHour を使うと止まる", RC.keys_adopt_problems, ("x = cfg['perHour']",), "perHour"),
            ("編集の部品: 関数の中の import は通る", RC.editor_import_problems, ("a.py", "def f():\n    import ed_state\n"), None),
            ("編集の部品: 先頭の import ed_state で止まる", RC.editor_import_problems, ("a.py", "import ed_state\n"), "ed_state"),
            ("編集の部品: from serve import で止まる", RC.editor_import_problems, ("a.py", "try:\n    from serve import x\nexcept ImportError:\n    pass\n"), "serve"),
            ("編集の部品: 相対 import は通る", RC.editor_import_problems, ("a.py", "from . import store\n"), None),
        ])

    def test_rules_on_a_copy_of_the_repo(self):
        tmp = testkit.tempdir(self)
        testkit.write_text(os.path.join(tmp, "src", "human", "proof", "store.py"), "def write_doc(a): pass\nwrite_doc(1)\n")
        testkit.write_text(os.path.join(tmp, "src", "manage", "x.py"), "write_doc(1)\n")
        testkit.write_text(os.path.join(tmp, "src", "human", "proof", "alt.py"), "import ed_state\n")
        testkit.write_text(os.path.join(tmp, "src", "pipeline", "analyze", "analyze.py"), 'c = ["-o", os.path.join(a, "b")]\n')
        testkit.write_text(os.path.join(tmp, "src", "flow", "keys.py"), "x = 'waitMin'\n")
        testkit.write_text(os.path.join(tmp, "src", "cut2resolve", "serve.py"), "TOOL_APPS = {}\n")
        self.assertEqual(RC.rule_write_doc_only_in_store(tmp), ["write_doc を store.commit の外で呼んでいる: manage/x.py"])
        self.assertTrue(any("alt.py:1" in p for p in RC.rule_owners_do_not_read_editor_parts(tmp)))
        self.assertTrue(any("analyze.py" in p for p in RC.rule_ytdlp_out_template(tmp)))
        self.assertTrue(RC.rule_keys_ignore_adopt(tmp))
        self.assertTrue(RC.rule_cut2resolve_tool_apps(tmp))
        testkit.write_text(os.path.join(tmp, "src", "manage", "x.py"), "pass\n")
        self.assertEqual(RC.rule_write_doc_only_in_store(tmp), [])   # 直せば通る

    def test_members_rule_on_a_copy(self):
        tmp = testkit.tempdir(self)
        self.assertEqual(RC.rule_members_json(tmp), ["friend-apps/holo-colors/members.json が無い"])
        testkit.write_json(os.path.join(tmp, "friend-apps", "holo-colors", "members.json"), members(hex="x"))
        self.assertTrue(any("hex の形" in p for p in RC.rule_members_json(tmp)))
        testkit.write_json(os.path.join(tmp, "friend-apps", "holo-colors", "members.json"), members())
        self.assertEqual(RC.rule_members_json(tmp), [])


class TestImportRules(Table):
    def test_forbidden_loaded(self):
        self.run_table([
            ("完全一致", RI.forbidden_loaded, (["os", "numpy", "numpy.core"], ["numpy"]), "numpy"),
            ("ワイルドカード(ed_*)", RI.forbidden_loaded, (["os", "ed_state"], ["ed_*"]), "ed_state"),
            ("eval.* は eval.x に当たり evaluate には当たらない", RI.forbidden_loaded, (["evaluate"], ["eval", "eval.*"]), None),
            ("無ければ空", RI.forbidden_loaded, (["os", "sys"], ["numpy", "serve"]), None),
        ])

    def test_forbidden_loaded_returns_names(self):
        self.assertEqual(RI.forbidden_loaded(["a", "numpy", "numpy.x", "ed_x"], ["numpy", "ed_*"]), ["ed_x", "numpy"])

    def test_isolation_child_stops_on_a_forbidden_import(self):
        """切り離しの子の判定: 読み込んではいけない名前を実際に import すると止まり、読まなければ通る(別のプロセスで読む本物は lint が流す)"""
        old = RI.ISOLATION
        try:
            RI.ISOLATION = [("T-1", "t", "t", [], "import json", ["json"]), ("T-2", "t", "t", [], "import json", ["no_such_module_xyz"]),
                            ("T-3", "t", "t", [], "import no_such_module_xyz", ["json"])]
            self.assertIn("json", RI.child_isolation("T-1")["T-1"][0])
            self.assertEqual(RI.child_isolation("T-2"), {"T-2": []})
            self.assertIn("読み込めない", RI.child_isolation("T-3")["T-3"][0])
        finally:
            RI.ISOLATION = old

    def test_registry(self):
        ids = [r[0] for r in RC.RULES] + [r[0] for r in RI.CHECKS] + [r[0] for r in RI.ISOLATION]
        self.assertEqual(len(ids), len(set(ids)), "規則の番号が重なる")
        self.assertGreaterEqual(len(ids), 40)


class TestUiContracts(Table):
    PANEL = "CasesPanels.define('cand', {mount: 1, update: 2, unmount: 3, keys: 4, keybar: 5})"

    def test_table(self):
        html = '<script src="cases.js"></script><script src="cases-panels/cand.js"></script><script src="cases-panels/proof.js"></script><script src="cases-panels/cut.js"></script>' \
               '<script src="cases-edhost.js"></script><script src="cases-panels/machpick.js"></script><div class="ui-header top">'
        good_html = html.replace('<script src="cases-edhost.js"></script><script src="cases-panels/machpick.js"></script>', "").replace(
            '<script src="cases-panels/proof.js">', '<script src="cases-edhost.js"></script><script src="cases-panels/machpick.js"></script><script src="cases-panels/proof.js">')
        card = "CheckCards.define('read', {})"
        shell_good = "render(card, el, ctx) keys(e, card) keybar(card) unmount() typingKeys\nUIKit.life.onLeave(function (reason) {\n  if (reason !== 'blur') {\n    flush();\n  }\n});\n" \
                     "api/check/flush', { body: { page: PAGE }\napi/check/skip', { body: { card: card.id, page: PAGE }\nvar b = { page: PAGE };"
        png = b"\x89PNG" + b"0" * 10
        guide = "".join('<img src="guide/%d.png">' % i for i in range(6))
        self.run_table([
            ("案件の画面: 正しい順は通る", UA.cases_html_problems, (good_html,), None),
            ("案件の画面: パネルが殻より先", UA.cases_html_problems, (good_html.replace('<script src="cases.js"></script>', "") + '<script src="cases.js"></script>',), "先に読む"),
            ("案件の画面: .top のヘッダーが無い", UA.cases_html_problems, (good_html.replace(' top"', '"'),), "ui-header top"),
            ("確かめる画面: 殻が先は通る", UA.check_html_problems, ('<script src="check.js"></script><script src="check-player.js"></script><script src="check-cards/read.js"></script>', ["read"]), None),
            ("確かめる画面: カードが殻より先", UA.check_html_problems, ('<script src="check-cards/read.js"></script><script src="check.js"></script><script src="check-player.js"></script>', ["read"]), "先に読む"),
            ("パネル: 口が揃えば通る", UA.panel_problems, ("cand", self.PANEL), None),
            ("パネル: keybar が無い", UA.panel_problems, ("cand", self.PANEL.replace("keybar: 5", "")), "keybar:"),
            ("パネル: document.getElementById", UA.panel_problems, ("cand", self.PANEL + "\ndocument.getElementById('x')"), "getElementById"),
            ("パネル: visibilitychange を直に", UA.panel_problems, ("cand", self.PANEL + "\nwindow.addEventListener('visibilitychange', f)"), "visibilitychange"),
            ("新しい案件: setVisible が無い", UA.panel_problems, ("new", "window.NewCasePanel CasesPanels.define('new' mount: update: unmount:", "new"), "setVisible:"),
            ("殻: 正しい形は通る", UA.cases_shell_problems, ("addEventListener('keydown', f); UIKit.life.onLeave(g)",), None),
            ("殻: keydown が 2 本", UA.cases_shell_problems, ("addEventListener('keydown', f); addEventListener('keydown', g); UIKit.life.onLeave(g)",), "keydown"),
            ("殻: 絶対パスの API", UA.cases_shell_problems, ("addEventListener('keydown', f); UIKit.life.onLeave(g); fetch('/api/x')",), "絶対パス"),
            ("編集の口: 相対パスと EditHost は通る", UA.edhost_problems, ("'transcribe/' + n window.EditHost", {"app.js": "EDIT_HOST"}), None),
            ("編集の口: 絶対パス", UA.edhost_problems, ("'transcribe/' + n window.EditHost '/api/x'", {"app.js": "EDIT_HOST"}), "絶対パス"),
            ("編集の口: app.js に EDIT_HOST が無い", UA.edhost_problems, ("'transcribe/' + n window.EditHost", {"app.js": ""}), "EDIT_HOST"),
            ("カード: 正しい形は通る", UA.check_card_problems, ("read", card), None),
            ("カード: document.querySelector", UA.check_card_problems, ("read", card + "\ndocument.querySelector('a')"), "querySelector"),
            ("カード: on〇〇=", UA.check_card_problems, ("read", card + '\n<b onclick="x">'), "on〇〇="),
            ("確かめる殻: 正しい形は通る", UA.check_shell_problems, (shell_good, {"check.js": shell_good}), None),
            ("確かめる殻: blur でも flush", UA.check_shell_problems, (shell_good.replace("if (reason !== 'blur') {", "if (true) {"), {}), "blur"),
            ("確かめる殻: page を送らない", UA.check_shell_problems, (shell_good.replace("page: PAGE };", ""), {}), "page: PAGE"),
            ("確かめる殻: カードが confirm を使う", UA.check_shell_problems, (shell_good, {"cards/a.js": "if (confirm('x')) {}"}), "ダイアログ"),
            ("id: 重ならなければ通る", UA.id_collision_problems, ('<div id="home1">', {"rank.js": "".join('id="r%d" ' % i for i in range(45))}), None),
            ("id: 重なると止まる", UA.id_collision_problems, ('<div id="r3">', {"rank.js": "".join('id="r%d" ' % i for i in range(45))}), "id=r3"),
            ("[?]: 揃えば通る", UA.help_links_problems, ({"friend.html": "guide.html#send guide.html#receive", "settings.js": "guide.html#settings", "setup.html": "guide.html#setup"},), None),
            ("[?]: 受け取るが無い", UA.help_links_problems, ({"friend.html": "guide.html#send", "settings.js": "guide.html#settings", "setup.html": "guide.html#setup"},), "#receive"),
            ("説明ページ: 正しい形は通る", UA.guide_problems, (guide, {"guide/%d.png" % i: png for i in range(6)}), None),
            ("説明ページ: 旧い言葉", UA.guide_problems, (guide + "スタジオ", {"guide/%d.png" % i: png for i in range(6)}), "使わない言葉"),
            ("説明ページ: インラインの script", UA.guide_problems, (guide + "<script>x</script>", {"guide/%d.png" % i: png for i in range(6)}), "インライン"),
            ("説明ページ: 画像が PNG でない", UA.guide_problems, (guide, dict({"guide/%d.png" % i: png for i in range(6)}, **{"guide/0.png": b"GIF"})), "PNG でない"),
            ("説明ページ: 画像が 300KB 超", UA.guide_problems, (guide, dict({"guide/%d.png" % i: png for i in range(6)}, **{"guide/0.png": b"\x89PNG" + b"0" * 300 * 1024})), "300KB"),
            ("説明ページ: 画像が足りない", UA.guide_problems, ("<img src=\"guide/0.png\">", {"guide/0.png": png}), "6 枚未満"),
        ])


if __name__ == "__main__":
    unittest.main()
