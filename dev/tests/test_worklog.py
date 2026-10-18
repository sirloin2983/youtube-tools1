import datetime
import os
import sys
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO, "dev"))
import worklog  # noqa: E402


def read(path):
    with open(path, "rb") as f:
        raw = f.read()
    assert b"\r" not in raw
    return raw.decode("utf-8")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


class WorklogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.notes = self.tmp.name
        self.wl = os.path.join(self.notes, "docs", "worklog")
        write(os.path.join(self.notes, "docs", "WORKLOG.md"),
              "# 記録\n\n## 週のファイル(新しい週が上)\n- [2026-10-12週](worklog/2026-10-12週.md)(10-12〜) — 前\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_week_of_day(self):
        self.assertEqual(worklog.week_name(datetime.date(2026, 10, 18)), "2026-10-12週")   # 日曜は前の月曜の週
        self.assertEqual(worklog.week_name(datetime.date(2026, 10, 19)), "2026-10-19週")

    def test_new_session_files_and_week_summary(self):
        p1 = worklog.new("aaa", datetime.date(2026, 10, 19), "見出し A", notes=self.notes)
        self.assertEqual(p1, os.path.join(self.wl, "2026-10-19週", "2026-10-19-aaa.md"))
        text = read(p1)
        self.assertTrue(text.startswith("---\n種類: 記録\n状態: 有効\nまとめ: "))
        self.assertIn("# 2026-10-19 Claude Code — 見出し A\n", text)
        write(p1, text.replace("まとめ: (1 行で。週のまとめに出る)", "まとめ: A をした"))
        self.assertEqual(worklog.new("aaa", datetime.date(2026, 10, 19), notes=self.notes), p1)   # あればそのまま
        self.assertIn("まとめ: A をした", read(p1))
        worklog.new("bbb", datetime.date(2026, 10, 21), "見出し [B]", notes=self.notes)
        week = read(os.path.join(self.wl, "2026-10-19週.md"))
        self.assertTrue(week.startswith("---\n種類: 記録\n状態: 進行中\n---\n# 作業の記録 2026-10-19週(10-19〜)\n"))
        self.assertIn("## まとめ\n- 10-21 bbb: (まとめ未記入)\n- 10-19 aaa: A をした\n", week)
        self.assertIn("- [2026-10-21 Claude Code — 見出し (B)](2026-10-19週/2026-10-21-bbb.md)\n"
                      "- [2026-10-19 Claude Code — 見出し A](2026-10-19週/2026-10-19-aaa.md)\n", week)
        index = read(os.path.join(self.notes, "docs", "WORKLOG.md"))
        self.assertIn("## 週のファイル(新しい週が上)\n- [2026-10-19週](worklog/2026-10-19週.md)", index)
        self.assertEqual(index.count("2026-10-19週.md"), 1)
        self.assertEqual(worklog.build(self.notes), 0)   # 同じなら書かない

    def test_hand_written_week_keeps_its_text(self):
        hand = "---\n種類: 記録\n---\n# 作業の記録 2026-10-12週\n\n## まとめ\n- 手の行\n\n## 2026-10-12 前の記録\n- 本文\n"
        write(os.path.join(self.wl, "2026-10-12週.md"), hand)
        worklog.new("ccc", datetime.date(2026, 10, 18), notes=self.notes)
        week = read(os.path.join(self.wl, "2026-10-12週.md"))
        self.assertTrue(week.startswith("---\n種類: 記録\n---\n# 作業の記録 2026-10-12週\n\n" + worklog.BEGIN + "\n## まとめ\n- 10-18 ccc"))
        self.assertIn(worklog.END + "\n\n## まとめ(分ける前に手で書いた分)\n- 手の行\n\n## 2026-10-12 前の記録\n- 本文\n", week)
        self.assertEqual(week.count("\n## まとめ\n"), 1)
        worklog.new("ddd", datetime.date(2026, 10, 17), notes=self.notes)
        week2 = read(os.path.join(self.wl, "2026-10-12週.md"))
        self.assertEqual(week2.count(worklog.BEGIN), 1)
        self.assertIn("- 10-18 ccc: (まとめ未記入)\n- 10-17 ddd:", week2)
        self.assertTrue(week2.endswith("## 2026-10-12 前の記録\n- 本文\n"))

    def test_bad_name(self):
        with self.assertRaises(SystemExit):
            worklog.new("a b", datetime.date(2026, 10, 19), notes=self.notes)


if __name__ == "__main__":
    unittest.main()
