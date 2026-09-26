#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cut2resolve の見直し(2026-09)で直した所・足した所のテスト。
python -m unittest test_cut2resolve で一緒に走る(test_cut2resolve の load_tests)。単独なら python -m unittest test_pack"""
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt_core.datadir)
import subprocess
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import auto_cut as AC  # noqa: E402
import cut2resolve as FULL  # noqa: E402
import cut2resolve_core as C  # noqa: E402
import pack  # noqa: E402
import resolve_textplus as RTP  # noqa: E402
import srt2resolve as S  # noqa: E402
from test_cut2resolve import FPS30, HAVE_FFMPEG, make_video, parse_edl, tc2f  # noqa: E402


def write(path, text, enc="utf-8"):
    Path(path).write_text(text, encoding=enc)
    return Path(path)


def transcript_doc(rows, media=None):
    return {"schema": "youtube-tools-transcript/v1", "tool": {"name": "transcribe-tool", "version": "0.10.0"},
            "media": media or {}, "segments": [dict(id="s%d" % i, start=a, end=b, text=t, cut=c)
                                              for i, (a, b, t, c) in enumerate(rows, 1)]}


def _lua_runtime():
    import shutil as _sh
    for name in ("luajit", "lua5.1", "lua", "texlua"):   # Resolve は LuaJIT。無ければ構文の近い Lua 5.3(texlua)で代用
        p = _sh.which(name)
        if p:
            return p
    return None


def _textplus_plan(cues_out, keeps, fps=(60, 1), total=2064, target=None):
    plan = mock.Mock()
    plan.video = Path('test.mp4')
    plan.req.name = 'test'
    plan.meta = {'fps': fps, 'w': 1920, 'h': 1080, 'total': total}
    plan.cues_out = cues_out
    plan.keeps = keeps
    return RTP.build_import_plan(plan, Path('media/test.mp4'), target)


class TestResolveTextPlusScript(unittest.TestCase):
    def test_script_never_creates_project_or_changes_settings(self):
        script = RTP.importer_script(_textplus_plan([(60, 300, '字幕')], [(0, 2064)]))
        for bad in ('CreateProject', 'SetSetting', 'LoadProject', 'InsertFusionTitleIntoTimeline'):
            self.assertNotIn(bad, script)
        self.assertIn('GetSetting("timelineFrameRate")', script)
        self.assertIn('trackIndex=2, recordFrame=recordFrame', script)
        self.assertIn('tool:SetInput("Font", fontName)', script)
        self.assertIn('tool:SetInput("Style", fontStyle)', script)
        self.assertIn('GetFontList', script)
        self.assertIn('AddMarker', script)
        self.assertIn('字幕', script)

    def test_caption_segments_are_relative_to_each_keep(self):
        keeps = [(100, 700), (1000, 1600)]          # カット後: 0-600 / 600-1200
        cues = [(30, 150, 'a'), (600, 660, 'b'), (1100, 1200, 'c')]
        caps = RTP.caption_segments(keeps, cues)
        self.assertEqual([(c['segment'], c['offsetStart'], c['offsetEnd']) for c in caps],
                         [(1, 30, 150), (2, 0, 60), (2, 500, 600)])
        with self.assertRaises(ValueError):
            RTP.caption_segments(keeps, [(1300, 1310, 'x')])

    def test_parse_target(self):
        self.assertEqual(RTP.parse_target(), {'fps': 30, 'width': 1080, 'height': 1920})
        self.assertEqual(RTP.parse_target('60', '1920x1080'), {'fps': 60, 'width': 1920, 'height': 1080})
        for fps, size in (('29', None), ('abc', None), (None, '1080*1920'), (None, '1081x1920'), (None, '8x8')):
            with self.assertRaises(ValueError):
                RTP.parse_target(fps, size)

    def test_importer_script_does_not_modify_plan(self):
        plan = _textplus_plan([(60, 300, 'a')], [(0, 2064)])
        before = json.dumps(plan, sort_keys=True)
        RTP.importer_script(plan)
        self.assertEqual(json.dumps(plan, sort_keys=True), before)

    def test_template_is_bundled(self):
        import zipfile
        template = Path(RTP.__file__).with_name(RTP.TEMPLATE_NAME)
        with zipfile.ZipFile(template) as archive:
            self.assertIn('project.xml', archive.namelist())
        install = RTP.installer_script('test.mov')
        self.assertIn('textplus-template.drb', install)
        self.assertIn('__C2R_TEMPLATE_PATH__', install)

    def test_generated_pack_contains_template_target_and_script(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            plan = mock.Mock()
            plan.video = Path('test.mov')
            plan.req.name = 'test'
            plan.meta = {'fps': (60, 1), 'w': 1920, 'h': 1080, 'total': 120}
            plan.cues_out = [(27, 93, '日本語字幕')]
            plan.keeps = [(0, 120)]
            paths = pack.pack_paths(plan.video, output, True, textplus=True)
            files = RTP.write_files(paths, plan, output, {'fps': 30, 'width': 1080, 'height': 1920})
            self.assertEqual(paths['textplus_template'].read_bytes(),
                             Path(RTP.__file__).with_name(RTP.TEMPLATE_NAME).read_bytes())
            self.assertNotIn('textplus_plan', files)                  # 計画は Lua に埋め込む(.json は出さない。④)
            self.assertFalse((output / 'textplus-import.json').exists())
            data = RTP.read_script_plan(files['textplus_script'].read_text(encoding='utf-8'))
            self.assertEqual(data['target'], {'fps': 30, 'width': 1080, 'height': 1920})
            self.assertEqual(data['mediaFps'], 60.0)
            readme = files['textplus_readme'].read_text(encoding='utf-8-sig')
            self.assertIn('1080 x 1920', readme)
            self.assertIn('最短辺をマッチ: 他をクロップ', readme)
            self.assertIn('trackIndex=2', files['textplus_script'].read_text(encoding='utf-8'))


class TestTextStyle(unittest.TestCase):
    """字幕の見た目(ユーザーの指定 2026-09-26。素材フォルダの Text+ のインスペクタの画像)。Lua が無くても確かめられる所"""

    def test_values_from_the_screenshots(self):
        inputs = dict((k, v) for k, v in RTP.style_inputs())
        self.assertEqual(RTP.TEXT_STYLE['fonts'][:2], ['けいふぉんと', 'Keifont'])          # keifont.ttf の名前表(日本語・英語)
        self.assertEqual(RTP.TEXT_STYLE['styles'], ['Regular'])
        for k, v in {'Size': 0.14, 'CharacterSpacing': 1.0, 'LineSpacing': 1.0, 'VerticalTopCenterBottom': 1.0, 'HorizontalLeftCenterRight': 0.0,
                     'Enabled1': 1, 'ElementShape1': 0, 'Red1': 0.0, 'Green1': 0.0, 'Blue1': 0.0, 'Alpha1': 1.0, 'Priority1': 8, 'Offset1': [0.0, 0.0],
                     'Enabled2': 1, 'ElementShape2': 1, 'Thickness2': 0.12, 'Red2': 1.0, 'Green2': 1.0, 'Blue2': 1.0, 'Priority2': 7,
                     'Offset2': [0.015, -0.02],
                     'Enabled5': 1, 'ElementShape5': 1, 'Thickness5': 0.18, 'Red5': 0.0, 'Green5': 0.0, 'Blue5': 0.0, 'Priority5': 4,
                     'Offset5': [0.0, 0.0]}.items():
            self.assertEqual(inputs.get(k), v, k)
        self.assertNotIn('Thickness1', inputs)                                               # 塗りに太さは無い

    def test_wrap_caption(self):
        """Text+ 字幕の改行(12 ②): 1段 8(縦)/ 14(横)文字前後で2段。+2 文字までは改行しない・句読点/助詞のあと・漢字やカタカナの始まりで切る"""
        w, NL = RTP.wrap_caption, chr(10)
        self.assertEqual(w('今日はいい天気ですね散歩に行こう', 8), '今日はいい天気ですね' + NL + '散歩に行こう')
        self.assertEqual(w('これマジでヤバくないですか', 8), 'これマジで' + NL + 'ヤバくないですか')
        self.assertEqual(w('ホロライブの新しいメンバーが来た', 8), 'ホロライブの新しい' + NL + 'メンバーが来た')    # 送りがなの前では切らない
        self.assertEqual(w('マインクラフトでエンダードラゴンをたおす', 8), 'マインクラフトで' + NL + 'エンダードラゴンをたおす')   # カタカナの語の途中で切らない
        self.assertEqual(w('えっと、ちょっとまってください!', 8), 'えっと、ちょっと' + NL + 'まってください!')
        self.assertEqual(w('今日はいい天気ですね散歩に行こう', 14), '今日はいい天気ですね散歩に行こう')    # 16 ≦ 14 + 2 は1段
        self.assertEqual(w('あいうえおかきくけこ', 8), 'あいうえおかきくけこ')                    # 10 ≦ 8 + 2
        self.assertEqual(w('ABCDEFGHIJKLMNOPQRSTU', 8).count(NL), 2)                                 # 長ければ3段
        self.assertEqual(w('今日はいい天気ですね散歩に行こう', 0), '今日はいい天気ですね散歩に行こう')     # 0 = 改行しない
        self.assertEqual(w(' 前' + NL + '後 ', 4), '前' + NL + '後')                                     # もう改行がある文はそのまま
        for s in ('、あいうえおかきくけこさしすせ', 'ーーーーーーーーーーーーーーー', 'あっっっっっっっっっっっっっっ'):
            self.assertEqual(w(s, 8).replace(NL, ''), s)                                              # 文字は落とさない

    def test_wrap_in_plan_by_target(self):
        NL = chr(10)
        plan = mock.Mock()
        plan.video, plan.req.name = Path('v.mp4'), 'v'
        plan.meta = {'fps': (30, 1), 'w': 1920, 'h': 1080, 'total': 900}
        plan.keeps = [(0, 900)]
        plan.cues_out = [(30, 120, '今日はいい天気ですね散歩に行こう')]
        v = RTP.build_import_plan(plan, 'media/v.mp4', {'fps': 30, 'width': 1080, 'height': 1920})
        self.assertEqual((v['captions'][0]['text'], v['captionWrap']), ('今日はいい天気ですね' + NL + '散歩に行こう', 8))    # 縦は 8
        h = RTP.build_import_plan(plan, 'media/v.mp4', {'fps': 30, 'width': 1920, 'height': 1080})
        self.assertEqual((h['captions'][0]['text'], h['captionWrap']), ('今日はいい天気ですね散歩に行こう', 14))    # 横は 14
        self.assertEqual(RTP.build_import_plan(plan, 'media/v.mp4', None, 0)['captions'][0]['text'], '今日はいい天気ですね散歩に行こう')
        data = RTP.read_script_plan(RTP.importer_script(v))
        self.assertEqual(data['captions'][0]['text'], '今日はいい天気ですね' + NL + '散歩に行こう')                    # Lua にも改行のまま入る

    def test_embedded_in_script_and_readme(self):
        plan = _textplus_plan([(60, 300, '字幕')], [(0, 2064)])
        data = RTP.read_script_plan(RTP.importer_script(plan))
        self.assertEqual([list(x) for x in data['style']['inputs']], [list(x) for x in RTP.style_inputs()])
        self.assertEqual(data['style']['fonts'][0], 'けいふぉんと')
        text = RTP.instructions('clip.mp4', None, {'fps': (60, 1), 'w': 1920, 'h': 1080}, 1, 1)
        self.assertIn('けいふぉんと', text)
        self.assertIn('このパックには入っていません', text)                                  # 再配布しない(規約に許可が無い)
        self.assertNotIn('黄色い文字', text)
        self.assertNotIn('keifont.ttf', [p.name for p in Path(RTP.__file__).parent.iterdir()])   # フォントをリポジトリ・パックに置かない


@unittest.skipUnless(_lua_runtime(), 'Lua の実行環境がない')
class TestResolveTextPlusLuaRun(unittest.TestCase):
    """生成した Lua を、Resolve の API をまねた偽物(resolve_lua_mock.lua)の上で実際に動かす"""

    KEI = {'けいふぉんと': ['Regular'], 'Meiryo': ['Regular']}   # 指定のフォントを入れた PC

    def run_lua(self, plan, settings, media_fps=60, template_ok=True, media_ok=True, fonts=None, ignore=()):
        mock_path = Path(RTP.__file__).with_name('resolve_lua_mock.lua')
        body = RTP.importer_script(plan)
        pre = 'dofile(%s)\n' % json.dumps(str(mock_path))
        pre += 'MOCK.mediaFps = %s\nMOCK.templateOk = %s\nMOCK.mediaOk = %s\n' % (
            media_fps, 'true' if template_ok else 'false', 'true' if media_ok else 'false')
        for k, v in settings.items():
            pre += 'MOCK.settings[%s] = %s\n' % (json.dumps(k), json.dumps(v))
        for k in ignore:        # この Resolve に無い入力の名前(実機で名前が違ったとき)
            pre += 'MOCK.ignoreInputs[%s] = true\n' % json.dumps(k)
        if fonts is not None:   # {書体: [太さ, ...]}
            pre += 'MOCK.fonts = {' + ','.join('[%s]={%s}' % (json.dumps(f, ensure_ascii=False), ','.join('[%s]="x"' % json.dumps(s, ensure_ascii=False) for s in st))
                                             for f, st in fonts.items()) + '}\n'
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / 'run.lua'
            f.write_text(pre + body + '\nMOCK.dump()\n', encoding='utf-8')
            r = subprocess.run([_lua_runtime(), str(f)], capture_output=True, text=True, encoding='utf-8', timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_60fps_media_on_30fps_vertical_project(self):
        keeps = [(0, 600), (1000, 1601)]            # 2区間目は奇数コマ(601)
        cues = [(60, 300, '一'), (600, 720, '二'), (1100, 1201, '三')]
        out = self.run_lua(_textplus_plan(cues, keeps),
                           {'timelineFrameRate': '30', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'}, fonts=self.KEI)
        self.assertIn('forbidden=\n', out)
        self.assertIn('timeline=CUT_TextPlus', out)
        self.assertIn('timeline=SOURCE_WITH_HANDLES', out)
        self.assertNotIn('C2R_エラー', out)
        # V1: 600コマ->300、601コマ->301(偽物は四捨五入)。V2: 各区間の実際の位置 + オフセット/2
        self.assertIn('item track=1 start=108000 dur=300', out)
        self.assertIn('item track=1 start=108300 dur=301', out)
        self.assertIn('item track=2 start=108030 dur=120 text=一 font=けいふぉんと', out)   # 指定のフォント(ユーザーの指定 2026-09-26)
        self.assertIn('  style=Regular fill=0.0,0.0,0.0 outline=1:1.0,1.0,1.0', out)       # 黒い文字 + 白いふち
        self.assertIn('  size=0.14 anchor=1.0,0.0 thick=0.12,0.18 shape=0,1,1 prio=8,7,4 offset2=0.015,-0.02 outer=1:0.0,0.0,0.0', out)   # + 外側の黒いふち
        self.assertIn('字体 けいふぉんと Regular(指定のフォント)', out)
        self.assertIn('・見た目 けいふぉんと・黒い文字・白いふち・黒いふち・', out)
        self.assertIn('item track=2 start=108300 dur=60 text=二', out)
        self.assertIn('item track=2 start=108550 dur=51 text=三', out)
        self.assertIn('marker=Green|cut2resolve 完了|字幕 3/3・カット 2/2・長さのずれ 0', out)

    def test_scaling_value_is_only_reported(self):
        base = {'timelineFrameRate': '30', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'}
        plan = _textplus_plan([(60, 300, 'a')], [(0, 2064)])
        out = self.run_lua(plan, dict(base, timelineInputResMismatchBehavior='scaleToFit'), fonts=self.KEI)
        self.assertIn('marker=Green|cut2resolve 完了|', out)             # 値が当てにならないので警告しない
        self.assertIn('拡大設定(参考) scaleToFit', out)

    def test_font_is_chosen_from_resolve_font_list(self):
        s = {'timelineFrameRate': '30', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'}
        plan = _textplus_plan([(60, 300, 'a')], [(0, 2064)])
        out = self.run_lua(plan, s, fonts={'Keifont': ['Regular'], 'Meiryo': ['Regular']})   # 英語名の一覧
        self.assertIn('text=a font=Keifont', out)
        self.assertIn('marker=Green|cut2resolve 完了|', out)
        # けいふぉんと が無い PC: 以前の自動選択(Windows の日本語フォント)にして、マーカーを黄色(要確認)に
        out = self.run_lua(plan, s, fonts={'Arial': ['Regular'], 'Meiryo': ['Regular', 'Bold', 'Italic'], 'MS Gothic': ['Regular']})
        self.assertIn('text=a font=Meiryo', out)                       # 候補の順: 游ゴシック が無いので メイリオ
        self.assertIn('  style=Bold ', out)
        self.assertIn('字体 Meiryo Bold(けいふぉんと が無いので自動で選択。入れると次から使えます)', out)
        self.assertIn('marker=Yellow|cut2resolve 完了(要確認)|', out)
        self.assertIn('  style=Bold fill=0.0,0.0,0.0 outline=1:1.0,1.0,1.0', out)   # 見た目(色・ふち)は同じ
        out = self.run_lua(plan, s, fonts={'ＭＳ ゴシック': ['標準']})    # 日本語名しか無い環境
        self.assertIn('text=a font=ＭＳ ゴシック', out)
        self.assertIn('  style=標準 ', out)
        out = self.run_lua(plan, s, fonts={'Yu Gothic': ['Light', 'Medium']})   # 候補の太さが無ければ、ある太さのどれか
        self.assertIn('字体 Yu Gothic Light(けいふぉんと が無いので自動で選択', out)
        out = self.run_lua(plan, s, fonts={'Arial': ['Regular'], 'Noto Sans CJK JP': ['Regular'], 'ヒラギノ角ゴ': ['W3']})
        self.assertIn('一覧に候補なし(例: ヒラギノ角ゴ)', out)             # 次に直すための手がかり
        out = self.run_lua(plan, s)                                          # 一覧を読めない → 予備の書体・黄色
        self.assertIn('text=a font=MS Gothic', out)
        self.assertIn('字体 MS Gothic Regular(フォントの一覧を読めない)', out)
        self.assertIn('marker=Yellow|', out)

    def test_style_inputs_are_read_back(self):
        """入れた値を読み直し、この Resolve に無い入力(名前が違う)はマーカーのメモに出して黄色にする(実機で名前を確かめるため)"""
        s = {'timelineFrameRate': '30', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'}
        plan = _textplus_plan([(60, 300, 'a'), (400, 500, 'b')], [(0, 2064)])
        out = self.run_lua(plan, s, fonts=self.KEI, ignore=('Offset2', 'Priority5'))
        self.assertIn('(反映できなかった: Offset2, Priority5)', out)
        self.assertIn('marker=Yellow|cut2resolve 完了(要確認)|字幕 2/2', out)

    def test_wrong_project_settings_stop_without_changes(self):
        out = self.run_lua(_textplus_plan([(60, 300, 'a')], [(0, 2064)]),
                           {'timelineFrameRate': '60', 'timelineResolutionWidth': '1920', 'timelineResolutionHeight': '1080'})
        self.assertIn('forbidden=\n', out)
        self.assertIn('timeline=C2R_エラー_プロジェクトのfps・解像度が違う', out)
        self.assertNotIn('CUT_TextPlus', out)
        self.assertIn('media=nil', out)                 # 動画も読み込まない

    def test_only_fps_differs_also_stops(self):
        out = self.run_lua(_textplus_plan([(60, 300, 'a')], [(0, 2064)]),
                           {'timelineFrameRate': '60', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'})
        self.assertIn('timeline=C2R_エラー_プロジェクトのfps・解像度が違う', out)
        self.assertNotIn('CUT_TextPlus', out)

    def test_missing_template_and_media_show_error_timeline(self):
        s = {'timelineFrameRate': '30', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'}
        out = self.run_lua(_textplus_plan([(60, 300, 'a')], [(0, 2064)]), s, template_ok=False)
        self.assertIn('timeline=C2R_エラー_Text+雛形を読めない', out)
        out = self.run_lua(_textplus_plan([(60, 300, 'a')], [(0, 2064)]), s, media_ok=False)
        self.assertIn('timeline=C2R_エラー_動画を読めない_パックを移したら登録し直す', out)

    def test_same_fps_landscape_60(self):
        out = self.run_lua(_textplus_plan([(60, 300, 'a')], [(0, 2064)], target={'fps': 60, 'width': 1920, 'height': 1080}),
                           {'timelineFrameRate': '60', 'timelineResolutionWidth': '1920', 'timelineResolutionHeight': '1080'}, fonts=self.KEI)
        self.assertIn('item track=1 start=108000 dur=2064', out)
        self.assertIn('item track=2 start=108060 dur=240 text=a', out)
        self.assertIn('marker=Green', out)


class TestParsingFixes(unittest.TestCase):
    def test_minutes_seconds_over_59_is_rejected(self):
        with self.assertRaises(C.ToolError):
            C.parse_time("1:75")
        with self.assertRaises(C.ToolError):
            C.parse_time("0:60:00")
        self.assertEqual(C.parse_time("75"), 75)       # 先頭の欄は 60 以上でもよい(秒だけ・分だけ)
        self.assertEqual(C.parse_time("90:00"), 5400)

    def test_fullwidth_digits_and_colon(self):
        self.assertEqual(C.parse_time("１：０２．５"), 62.5)
        self.assertEqual(C.parse_cut_list("１：００〜１：３０\n"), [(60, 90)])

    def test_csv_lines(self):
        t = "start,end\n5,20\n0:05, 0:20\n1,5 3,5\n1,2,見どころ\n7\t9\n"
        self.assertEqual(C.parse_cut_list(t), [(5, 20), (5, 20), (1.5, 3.5), (1, 2), (7, 9)])

    def test_bad_time_error_has_line_number(self):
        with self.assertRaises(C.ToolError) as cm:
            C.parse_cut_list("0:01 0:02\n0:05 abc\n")
        self.assertIn("2行目", str(cm.exception))

    def test_zero_length_after_rounding_warns(self):
        keeps, w = C.cut_list_to_keeps([(1.0, 1.01), (2, 3)], FPS30, 300)
        self.assertEqual(keeps, [(60, 90)])
        self.assertTrue(any("0 になる" in x for x in w))

    def test_fmt_sec_rounds_before_splitting(self):
        self.assertEqual(C.fmt_sec(59.996), "1:00.00")
        self.assertEqual(C.fmt_sec(3599.999), "1:00:00.00")
        self.assertEqual(C.fmt_sec(5.2), "0:05.20")

    def test_edl_clip_name_newline_is_removed(self):
        text = C.build_edl("t", "a\nb.mp4", [(0, 5)], FPS30, True)
        self.assertIn("* FROM CLIP NAME: a b.mp4", text)
        self.assertEqual(len(parse_edl(text)), 1)

    def test_check_timecodes(self):
        C.check_timecodes(FPS30, "01:00:00:00", "10:00:00:29")
        with self.assertRaisesRegex(C.ToolError, "--src-start-tc"):
            C.check_timecodes(FPS30, "01:00:00:00", "00:00:00:30")
        with self.assertRaisesRegex(C.ToolError, "--rec-start"):
            C.check_timecodes((25, 1), "1:00:00", "00:00:00:00")

    def test_src_start_override_drop_frame_is_converted(self):
        tc, desc, warns = C.resolve_src_start(Path("x.mp4"), "01:00:00;00")
        self.assertEqual((tc, desc, len(warns)), ("01:00:00:00", "指定", 1))
        self.assertEqual(C.resolve_src_start(Path("x.mp4"), None, {"start_tc": None})[0], "00:00:00:00")
        self.assertEqual(C.resolve_src_start(Path("x.mp4"), None, {"start_tc": "02:00:00:00"})[0], "02:00:00:00")


class TestOutputGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_output_exists_lists_files(self):
        a = write(self.dir / "a.edl", "x")
        with self.assertRaises(C.OutputExists) as cm:
            C.validate_output_paths([a, self.dir / "b.srt"])
        self.assertEqual(cm.exception.existing, [a])
        self.assertIsInstance(cm.exception, C.ToolError)   # CLI は従来どおり ToolError として表示する

    def test_same_path_variants(self):
        a = write(self.dir / "a.srt", "x")
        self.assertTrue(S.same_path(a, self.dir / "." / "a.srt"))
        self.assertFalse(S.same_path(a, None))
        with self.assertRaisesRegex(C.ToolError, "入力ファイル"):
            C.validate_output_paths([self.dir / "sub" / ".." / "a.srt"], force=True, protected=(a,))

    def test_atomic_write_leaves_no_temp(self):
        p = self.dir / "x.txt"
        S.write_text_atomic(p, "あ\nい\n", encoding="utf-8-sig", newline="\r\n")
        self.assertEqual(p.read_bytes(), "\ufeffあ\r\nい\r\n".encode("utf-8"))
        self.assertEqual(sorted(x.name for x in self.dir.iterdir()), ["x.txt"])

    def test_auto_cut_package_protects_subtitle_input_even_with_force(self):
        video = write(self.dir / "v.mp4", "fake")
        out = self.dir / "pack"
        out.mkdir()
        sub = write(out / "v_cut.srt", "1\n00:00:01,000 --> 00:00:02,000\nx\n")
        meta = {"fps": FPS30, "total": 300, "w": 640, "h": 360, "audio": None}
        plan = AC.build_plan([{"id": "a", "label": "", "start_seconds": 1, "end_seconds": 2}], meta, 0)
        with self.assertRaisesRegex(C.ToolError, "入力ファイル"):
            AC.write_package(video, out, meta, plan, [(0, 30, "x")], "00:00:00:00", force=True, protected=(sub,))
        self.assertIn("x", sub.read_text(encoding="utf-8"))


class TestFcpxml(unittest.TestCase):
    meta = {"fps": FPS30, "total": 300, "w": 640, "h": 360, "audio": None}

    def _root(self, xml):
        return ET.fromstring(xml.split("\n", 2)[2])

    def test_title_offsets_are_in_parent_clip_time(self):
        # 2つ目のクリップは元動画の 5秒(150f)から。字幕はカット後の 2.5秒(75f) = 2つ目のクリップの 0.5秒後
        xml = AC.build_cut_fcpxml(Path("/tmp/src.mp4"), self.meta, [(0, 60), (150, 240)], [(75, 105, "B")])
        root = self._root(xml)
        clips = root.findall(".//spine/asset-clip")
        self.assertEqual(clips[1].get("start"), "5s")
        title = clips[1].find("title")
        self.assertEqual(title.get("offset"), "11/2s")   # 150 + 15 フレーム = 5.5秒(親の start 基準)
        self.assertIsNone(clips[0].find("title"))

    def test_text_style_ids_are_unique(self):
        xml = AC.build_cut_fcpxml(Path("/tmp/src.mp4"), self.meta, [(0, 60), (150, 240)],
                                  [(0, 30, "a"), (60, 90, "b"), (100, 120, "c")])
        ids = [e.get("id") for e in self._root(xml).iter("text-style-def")]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)

    def test_start_timecode_is_applied(self):
        t0 = 108000   # 01:00:00:00 @30
        xml = AC.build_cut_fcpxml(Path("/tmp/src.mp4"), self.meta, [(30, 60)], [(0, 10, "a")], t0)
        root = self._root(xml)
        self.assertEqual(root.find(".//asset").get("start"), "3600s")
        clip = root.find(".//spine/asset-clip")
        self.assertEqual(clip.get("start"), "3601s")
        self.assertEqual(clip.find("title").get("offset"), "3601s")
        xml2, _ = S.build_fcpxml(Path("/tmp/src.mp4"), self.meta, [(30, 60, "x")], "n", "Yu Gothic", 40, True, t0)
        r2 = self._root(xml2)
        self.assertEqual(r2.find(".//asset").get("start"), "3600s")
        self.assertEqual(r2.find(".//spine/asset-clip").get("start"), "3600s")
        self.assertEqual(r2.find(".//title").get("offset"), "3601s")

    def test_start_tc_frames(self):
        self.assertEqual(S.start_tc_frames(None, FPS30), (0, []))
        self.assertEqual(S.start_tc_frames("01:00:00;00", (30000, 1001))[0], 108000)
        self.assertEqual(len(S.start_tc_frames("01:00:00;00", (30000, 1001))[1]), 1)


class TestCutPlanDocs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _plan(self, extra=None, segs=None):
        d = {"schema": "youtube-tools-cut-plan/v1",
             "segments": segs or [{"id": "a", "start": 1.0, "end": 2.0}, {"id": "b", "start": 3.0, "end": 4.0, "status": "rejected"}]}
        d.update(extra or {})
        return write(self.dir / "plan.json", json.dumps(d))

    def test_default_handles_by_source(self):
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan())), 10.0)
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan({"tool": {"name": "clip-studio"}}))), 10.0)
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan({"tool": {"name": "transcribe-tool"}}))), 0.0)
        segs = [{"id": "x", "start": 1.0, "end": 2.0, "lines": ["s1", "s2"]}]
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan(segs=segs))), 0.0)
        self.assertEqual(AC.default_handles(AC.read_cut_plan(self._plan({"segmentsIncludeHandles": True}))), 0.0)

    def test_unsupported_version_and_bom(self):
        p = write(self.dir / "v2.json", json.dumps({"schema": "youtube-tools-cut-plan/v2", "segments": []}))
        with self.assertRaisesRegex(C.ToolError, "未対応の版"):
            AC.read_cut_plan(p)
        p = self.dir / "bom.json"
        p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"schema": "youtube-tools-cut-plan/v1", "segments": [{"start": 0, "end": 1}]}).encode())
        self.assertEqual(len(AC.read_selection(p)), 1)
        p = write(self.dir / "nan.json", '{"schema":"youtube-tools-cut-plan/v1","segments":[{"start":NaN,"end":1}]}')
        with self.assertRaises(C.ToolError):
            AC.read_cut_plan(p)

    def test_old_detailed_doc_is_readable(self):
        p = write(self.dir / "cut-plan.json", json.dumps({"schema": "youtube-tools-cut-plan/v1", "frame_rate": "30/1",
                                                         "keep_frames": [[30, 60], [90, 150]]}))
        doc = AC.read_cut_plan(p)
        self.assertEqual([(s["start_seconds"], s["end_seconds"]) for s in doc["segments"]], [(1, 2), (3, 5)])
        self.assertEqual(AC.default_handles(doc), 0.0)

    def test_package_plan_round_trips(self):
        """書いた cut-plan.json を読み直すと、同じ残す区間になる(以前は segments が無く読み直せなかった)"""
        video = write(self.dir / "v.mp4", "fake")
        meta = {"fps": (30000, 1001), "total": 900, "w": 640, "h": 360, "audio": (2, 48000)}
        plan = AC.build_plan([{"id": "a", "label": "", "start_seconds": 3.3, "end_seconds": 7.7},
                              {"id": "b", "label": "", "start_seconds": 20, "end_seconds": 25}], meta, 1.5)
        AC.write_package(video, self.dir / "out", meta, plan, None, "00:00:00:00")
        saved = json.loads((self.dir / "out" / "cut-plan.json").read_text(encoding="utf-8"))
        for k in ("schema", "tool", "createdAt", "media", "segments"):
            self.assertIn(k, saved)
        self.assertEqual(saved["media"]["name"], "v.mp4")
        doc = AC.read_cut_plan(self.dir / "out" / "cut-plan.json")
        again = AC.build_plan(doc["segments"], meta, AC.default_handles(doc))
        self.assertEqual(again["keep_frames"], plan["keep_frames"])


class TestTranscript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_and_rules(self):
        rows = [(3.0, 4.0, "c", False), (0.5, 1.5, "a", False), (1.5, 2.0, "b", False),
                (2.2, 2.8, "えー", True), (5.0, 4.0, "bad", False), (6.0, 7.0, "", False), (3.5, 5.0, "重なるカット", True)]
        p = write(self.dir / "t.transcript.json", json.dumps(transcript_doc(rows), ensure_ascii=False))
        tr = C.read_transcript(p)
        self.assertEqual(tr["bad"], 1)
        self.assertEqual([r["text"] for r in tr["rows"]][:3], ["a", "b", "えー"])
        self.assertEqual(C.transcript_kept_spans(tr["rows"]), [(0.5, 2.0), (3.0, 4.0)])   # 接する行はまとめ、空の行は残さない
        self.assertEqual(C.transcript_cut_spans(tr["rows"]), [(2.2, 2.8), (3.5, 5.0)])
        self.assertEqual([c[2] for c in C.transcript_cues(tr["rows"])], ["a", "b", "c"])

    def test_schema_errors(self):
        p = write(self.dir / "x.json", json.dumps({"schema": "youtube-tools-transcript/v9", "segments": []}))
        with self.assertRaisesRegex(C.ToolError, "未対応の版"):
            C.read_transcript(p)
        p = write(self.dir / "y.json", json.dumps({"schema": "youtube-tools-cut-plan/v1", "segments": []}))
        with self.assertRaisesRegex(C.ToolError, "ではありません"):
            C.read_transcript(p)
        p = write(self.dir / "z.json", "{broken")
        with self.assertRaisesRegex(C.ToolError, "JSON"):
            C.read_transcript(p)

    def test_resolve_media_path_fallback_to_same_folder(self):
        v = write(self.dir / "clip.mp4", "fake")
        j = self.dir / "clip.transcript.json"
        self.assertEqual(C.resolve_media_path({"path": str(v)}, j), str(v))
        self.assertEqual(C.resolve_media_path({"path": r"C:\gone\clip.mp4"}, j), str(v))   # Windows のパスでも名前だけ使う
        self.assertEqual(C.resolve_media_path({"path": "/nope/x.mp4", "name": "../clip.mp4"}, j), str(v))
        self.assertIsNone(C.resolve_media_path({"path": r"\\server\share\clip2.mp4"}, j))
        self.assertIsNone(C.resolve_media_path(None, j))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無いためスキップ")
class TestPackWithFfmpeg(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpc = tempfile.TemporaryDirectory()
        cls.gaps = Path(cls.tmpc.name) / "gaps.mp4"
        make_video(cls.gaps, 10, audio="gaps")   # 音 0-2 / 無音 2-4 / 音 4-6 / 無音 6-8 / 音 8-10

    @classmethod
    def tearDownClass(cls):
        cls.tmpc.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.video = self.dir / "clip.mp4"
        self.video.write_bytes(self.gaps.read_bytes())

    def tearDown(self):
        self.tmp.cleanup()

    def _tr(self, rows, name="clip.transcript.json"):
        return write(self.dir / name, json.dumps(transcript_doc(rows, {"path": str(self.video), "name": "clip.mp4"}),
                                                 ensure_ascii=False))

    def test_transcript_cut_rows_are_removed_and_subtitles_come_from_kept_rows(self):
        tr = self._tr([(0.5, 1.5, "こんにちは", False), (4.0, 5.0, "カットして", True), (8.5, 9.5, "またね", False)])
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr))
        self.assertEqual(plan.keeps, [(0, 120), (150, 300)])
        self.assertEqual(plan.sub_source, "transcript")
        self.assertEqual([c[2] for c in plan.cues_out], ["こんにちは", "またね"])
        self.assertEqual(plan.cues_out[1][:2], (225, 255))   # 8.5 秒 → カット後 7.5 秒
        plan2 = pack.plan_cut(pack.Request(video=self.video, transcript=tr, drop_cut_rows=False))
        self.assertEqual(plan2.keeps, [(0, 300)])

    def test_keep_rows_base_removes_gaps_between_rows(self):
        tr = self._tr([(0.5, 1.5, "a", False), (1.5, 2.0, "b", False), (8.5, 9.5, "c", False)])
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr, base="rows"))
        self.assertEqual(plan.keeps, [(15, 60), (255, 285)])
        self.assertEqual(plan.handles, 0.0)
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr, base="rows", handles=0.5))
        self.assertEqual(plan.keeps, [(0, 75), (240, 300)])

    def test_transcribe_tool_cut_plan_defaults_to_no_handles(self):
        p = write(self.dir / "clip.cut-plan.json", json.dumps({
            "schema": "youtube-tools-cut-plan/v1", "tool": {"name": "transcribe-tool", "version": "0.10.0"},
            "segments": [{"id": "segment-001", "start": 1.0, "end": 2.0, "status": "adopted", "lines": ["s1"]},
                         {"id": "segment-002", "start": 5.0, "end": 6.0, "status": "adopted", "lines": ["s3"]}]}))
        plan = pack.plan_cut(pack.Request(video=self.video, plan=p, base="plan"))
        self.assertEqual(plan.keeps, [(30, 60), (150, 180)])   # 10秒の余白で全部つながらない
        plan = pack.plan_cut(pack.Request(video=self.video, plan=p, base="plan", handles=10))
        self.assertEqual(plan.keeps, [(0, 300)])

    def test_srt_wins_over_transcript_with_note(self):
        tr = self._tr([(0.5, 1.5, "文字起こし", False)])
        srt = write(self.dir / "s.srt", "1\n00:00:00,500 --> 00:00:01,500\nSRT の字幕\n")
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr, sub=srt))
        self.assertEqual(plan.sub_source, "srt")
        self.assertTrue(any("SRT のほう" in w for w in plan.warnings))

    def test_silence_with_cache_and_task_progress(self):
        seen = []
        task = C.Task(lambda f, m: seen.append((f, m)))
        cache = pack.Cache()
        req = pack.Request(video=self.video, silence=True)
        p1 = pack.plan_cut(req, task=task, cache=cache)
        self.assertEqual(len(p1.keeps), 3)
        self.assertTrue(any(isinstance(f, float) for f, _ in seen), seen)   # 進み具合(0〜1)が来る
        self.assertTrue(cache.silence_cached(self.video, p1.meta["fps"], p1.meta["total"], -35.0, 0.6, 0.15))
        with mock.patch.object(C, "detect_silence", side_effect=AssertionError("キャッシュを使うはず")):
            p2 = pack.plan_cut(req, cache=cache)
        self.assertEqual(p2.keeps, p1.keeps)

    def test_silence_mode_with_zero_cuts_shows_guidance(self):
        """問題3: 既定の「①無音で自動」のまま削れる区間が無い(またはごくわずか)だと、何も言わずに
        動画全体そのままのパックを作ってしまわないよう注意を出す(他の削り方を試すよう促す)"""
        tone = self.dir / "tone.mp4"
        make_video(tone, 5, audio="tone")   # 無音区間が無い動画
        plan = pack.plan_cut(pack.Request(video=tone, silence=True))
        self.assertEqual(plan.keeps, [(0, 150)])   # 何も削れず、動画全体のまま
        self.assertTrue(any("切れる所が見つかりませんでした" in w for w in plan.warnings), plan.warnings)
        # 実際に無音があって削れている(既存の gaps 動画)ときは出ない
        plan2 = pack.plan_cut(pack.Request(video=self.video, silence=True))
        self.assertFalse(any("切れる所が見つかりませんでした" in w for w in plan2.warnings), plan2.warnings)
        # ①以外(残す区間・時刻リストなど)で結果的にカットが無いのは、この注意の対象外(別の警告のまま)
        plan3 = pack.plan_cut(pack.Request(video=tone, base="list", keep_pairs=[(0, 5)]))
        self.assertFalse(any("切れる所が見つかりませんでした" in w for w in plan3.warnings), plan3.warnings)

    def test_invalid_timecode_fails_before_rendering(self):
        cuts = write(self.dir / "cuts.txt", "1 2\n")
        rc = FULL.main([str(self.video), str(cuts), "--render", "--src-start-tc", "00:00:00:45"])
        self.assertEqual(rc, 1)
        self.assertFalse((self.dir / "clip_pack").exists())   # 以前は粗編集の mp4 だけ書き出してから失敗していた

    def test_full_cli_with_transcript_json_and_fcpxml(self):
        tr = self._tr([(0.5, 1.5, "こんにちは", False), (4.0, 5.0, "カット", True), (8.5, 9.5, "またね", False)])
        self.assertEqual(FULL.main([str(self.video), str(tr), "--fcpxml"]), 0)   # .json は順不同で schema から判別
        out = self.dir / "clip_pack"
        names = sorted(p.name for p in out.iterdir())
        self.assertEqual(names, ["clip.edl", "clip_cut.fcpxml", "clip_cut.srt", "cut-plan.json", "友人へ.txt"])
        ev = parse_edl((out / "clip.edl").read_text(encoding="utf-8"))
        self.assertEqual([(e[3], e[4]) for e in ev], [("00:00:00:00", "00:00:04:00"), ("00:00:05:00", "00:00:10:00")])
        readme = (out / "友人へ.txt").read_text(encoding="utf-8-sig")
        self.assertIn("cut-plan.json", readme)
        self.assertIn("clip_cut.fcpxml", readme)
        doc = AC.read_cut_plan(out / "cut-plan.json")   # 読み直せる
        self.assertEqual(len(doc["segments"]), 2)
        bad = write(self.dir / "other.json", '{"schema":"something/v1"}')
        self.assertEqual(FULL.main([str(self.video), str(bad), "-o", str(self.dir / "o")]), 1)

    def test_full_cli_plan_and_list_are_exclusive(self):
        cuts = write(self.dir / "cuts.txt", "1 2\n")
        p = write(self.dir / "p.json", json.dumps({"schema": "youtube-tools-cut-plan/v1", "segments": [{"start": 1, "end": 2}]}))
        self.assertEqual(FULL.main([str(self.video), str(cuts), str(p), "--dry-run"]), 1)
        self.assertEqual(FULL.main([str(self.video), "--keep-rows", "--dry-run"]), 1)   # 文字起こしが無い
        self.assertEqual(FULL.main([str(self.video), str(p), "--dry-run"]), 0)

    def test_build_pack_stale_files_warning_and_force(self):
        plan = pack.plan_cut(pack.Request(video=self.video, silence=True))
        r1 = pack.build_pack(plan, render=True)
        self.assertEqual([k for k, _ in r1["files"]], ["edl", "readme", "plan", "roughcut"])
        with self.assertRaises(C.OutputExists) as cm:
            pack.build_pack(plan)
        self.assertEqual(sorted(p.name for p in cm.exception.existing), ["clip.edl", "cut-plan.json", "友人へ.txt"])
        r2 = pack.build_pack(plan, force=True)
        self.assertTrue(any("clip_roughcut.mp4" in w for w in r2["warnings"]))
        self.assertIn("DaVinci Resolve", r2["readme"])
        leftovers = [p.name for p in r2["out_dir"].iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_textplus_pack_friend_readme_is_textplus_guide(self):
        srt = write(self.dir / "clip.srt", "1\n00:00:00,500 --> 00:00:01,500\nこんにちは\n\n2\n00:00:08,500 --> 00:00:09,500\nまたね\n")
        plan = pack.plan_cut(pack.Request(video=self.video, sub=srt, base="list", keep_pairs=[(0, 4), (5, 10)]))
        r = pack.build_pack(plan, textplus=True, textplus_target={"fps": 30, "width": 1080, "height": 1920})
        names = sorted(p.name for p in r["out_dir"].iterdir())
        self.assertIn(RTP.README_NAME, names)
        self.assertIn(RTP.EDL_README_NAME, names)
        self.assertNotIn("Text+の使い方.txt", names)
        guide = (r["out_dir"] / RTP.README_NAME).read_text(encoding="utf-8-sig")
        self.assertIn("Text+ 字幕つき", guide)
        self.assertIn("字幕 2 件・残す区間 2 か所", guide)
        self.assertIn("最短辺をマッチ: 他をクロップ", guide)
        self.assertIn("フレームレートは、タイムラインを1本でも作ると", guide)
        self.assertEqual(r["readme"], guide)                       # 画面に出すのも友人が最初に読む方
        backup = (r["out_dir"] / RTP.EDL_README_NAME).read_text(encoding="utf-8-sig")
        self.assertIn("DaVinci Resolve", backup)
        self.assertIn(RTP.README_NAME, backup)                    # 予備の手順書から本来の手順書を案内する
        self.assertTrue((r["out_dir"] / "media" / self.video.name).exists())

    def test_cancel_during_copy_leaves_nothing(self):
        plan = pack.plan_cut(pack.Request(video=self.video))
        task = C.Task()
        task._on = lambda f, m: task.cancel() if isinstance(f, float) else None
        out = self.dir / "o"
        with self.assertRaises(C.Cancelled):
            pack.build_pack(plan, out, copy_video=True, task=task)
        self.assertEqual(list(out.iterdir()), [])   # 途中の一時ファイルも、半端なパックも残さない

    def test_cancel_during_render_kills_ffmpeg_and_cleans_up(self):
        long_v = self.dir / "long.mp4"
        make_video(long_v, 20, size="960x540")
        task = C.Task()
        task._on = lambda f, m: task.cancel() if isinstance(f, float) and f > 0 else None
        out = self.dir / "r"
        out.mkdir()
        with self.assertRaises(C.Cancelled):
            C.render_rough_cut(long_v, [(0, 1200)], FPS30, True, out / "x.mp4", 18, task)
        self.assertEqual(list(out.iterdir()), [])

    def test_render_failure_leaves_no_partial_file(self):
        noa = self.dir / "noaudio.mp4"
        make_video(noa, 2, audio=None)
        out = self.dir / "f"
        out.mkdir()
        with self.assertRaises(C.ToolError):
            C.render_rough_cut(noa, [(0, 30)], FPS30, True, out / "x.mp4")   # 音声が無いのに音声ありで書き出す → ffmpeg が失敗
        self.assertEqual(list(out.iterdir()), [])

    def test_relative_path_starting_with_dash(self):
        """「-」で始まるファイル名を ffprobe / ffmpeg にオプションと取り違えさせない"""
        odd = self.dir / "-i.mp4"
        odd.write_bytes(self.video.read_bytes())
        cwd = os.getcwd()
        os.chdir(self.dir)
        try:
            meta = S.probe(Path("-i.mp4"))
            self.assertEqual(meta["total"], 300)
            self.assertEqual(len(C.detect_silence(Path("-i.mp4"), meta["fps"], meta["total"])), 2)
        finally:
            os.chdir(cwd)

    def test_srt2resolve_uses_embedded_start_timecode(self):
        v = self.dir / "tc.mov"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=3",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-timecode", "01:00:00:00", str(v)], check=True)
        srt = write(self.dir / "tc.srt", "1\n00:00:01,000 --> 00:00:02,000\nx\n")
        self.assertEqual(S.main([str(v), str(srt)]), 0)
        root = ET.fromstring((self.dir / "tc_resolve" / "tc.fcpxml").read_text(encoding="utf-8").split("\n", 2)[2])
        self.assertEqual(root.find(".//asset").get("start"), "3600s")
        self.assertEqual(root.find(".//title").get("offset"), "3601s")
        self.assertEqual(S.main([str(v), str(srt), "--src-start-tc", "00:00:00:00", "-o", str(self.dir / "z")]), 0)
        root = ET.fromstring((self.dir / "z" / "tc.fcpxml").read_text(encoding="utf-8").split("\n", 2)[2])
        self.assertEqual(root.find(".//asset").get("start"), "0s")

    def test_summary_shape(self):
        tr = self._tr([(0.5, 1.5, "a", False), (4.0, 5.0, "cut", True)])
        s = pack.summary(pack.plan_cut(pack.Request(video=self.video, transcript=tr, silence=True)))
        self.assertEqual(s["fps"], [30, 1])
        self.assertEqual(s["total"], 300)
        self.assertIn("silence", s["drops"])
        self.assertIn("cutRows", s["drops"])
        self.assertEqual(s["subtitles"]["source"], "transcript")
        self.assertEqual(len(s["transcriptRows"]), 2)
        self.assertAlmostEqual(s["keptSec"] + s["removedSec"], 10.0, places=3)
        json.dumps(s)   # そのまま JSON にできる


class TestEditMediaLookup(unittest.TestCase):
    """切り抜きスタジオの余白つき素材(.edit.json)を探す規則(ffmpeg なし)"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)
        self.video = write(self.d / "clip.mp4", "x")
        write(self.d / "clip_edit.mp4", "y")

    def tearDown(self):
        self.tmp.cleanup()

    def sidecar(self, **kw):
        d = {"schema": C.EDIT_MEDIA_SCHEMA, "media": "clip_edit.mp4", "selectionIn": 10, "handleBefore": 10, "handleAfter": 10}
        d.update(kw)
        write(self.d / "clip.edit.json", json.dumps(d))

    def test_found(self):
        self.sidecar()
        em = C.find_edit_media(self.video)
        self.assertEqual((em["path"].name, em["selectionIn"], em["handleAfter"]), ("clip_edit.mp4", 10.0, 10.0))
        self.assertEqual(pack.edit_media_path(self.video, None, True), self.d / "clip_edit.mp4")
        self.assertIsNone(pack.edit_media_path(self.video, None, False))   # 動画を同梱しないパックでは使わない

    def test_rejected(self):
        self.assertIsNone(C.find_edit_media(self.video))                      # .edit.json が無い
        for bad in ({"schema": "other/v1"}, {"media": "../clip_edit.mp4x"}, {"media": "missing.mp4"},
                    {"media": "clip.mp4"}, {"selectionIn": -1}, {"handleAfter": "10"}, {"selectionIn": float("nan")}):
            with self.subTest(bad=bad):
                self.sidecar(**bad)
                self.assertIsNone(C.find_edit_media(self.video))
        write(self.d / "clip.edit.json", "{壊れた")
        self.assertIsNone(C.find_edit_media(self.video))

    def test_media_name_is_basename_only(self):
        """../ で .edit.json のフォルダの外を指させない(名前だけを使う)"""
        sub = self.d / "sub"
        sub.mkdir()
        v = write(sub / "clip.mp4", "x")
        write(sub / "clip.edit.json", json.dumps({"schema": C.EDIT_MEDIA_SCHEMA, "media": "../clip_edit.mp4",
                                                  "selectionIn": 1, "handleBefore": 1, "handleAfter": 1}))
        self.assertIsNone(C.find_edit_media(v))                   # sub/clip_edit.mp4 は無い(外の clip_edit.mp4 は使わない)
        write(sub / "clip_edit.mp4", "y")
        self.assertEqual(C.find_edit_media(v)["path"], sub / "clip_edit.mp4")


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無いためスキップ")
class TestEditMediaPack(unittest.TestCase):
    """余白つき素材を同梱した Text+ パック: 残す区間は余白の分だけ後ろへ、字幕の位置は変わらない"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.video = d / "clip.mp4"
        make_video(cls.video, dur=6)
        make_video(d / "clip_edit.mp4", dur=26)               # 前後 10 秒の余白
        write(d / "clip.edit.json", json.dumps({"schema": C.EDIT_MEDIA_SCHEMA, "media": "clip_edit.mp4",
                                                "selectionIn": 10, "handleBefore": 10, "handleAfter": 10}))
        make_video(d / "other_edit.mp4", dur=26, fps="60")
        cls.tr = write(d / "clip.transcript.json", json.dumps(transcript_doc(
            [(0, 2, "残す", False), (2, 4, "切る", True), (4, 6, "もう一度", False)]), ensure_ascii=False))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def plan(self, **kw):
        return pack.plan_cut(pack.Request(video=self.video, transcript=self.tr, **dict(pack.TRANSCRIPT_ROWS, **kw)))

    def test_textplus_pack_uses_edit_media(self):
        plan = self.plan()
        self.assertEqual(plan.keeps, [(0, 60), (120, 180)])            # 試算・画面は元の切り抜きのフレームのまま
        out = Path(self.tmp.name) / "pack_tp"
        res = pack.build_pack(plan, out, textplus=True)
        files = dict(res["files"])
        self.assertEqual(files["video"], out / "media" / "clip_edit.mp4")
        self.assertTrue(files["video"].is_file())
        self.assertEqual((files["edl"].name, files["srt"].name), ("clip.edl", "clip_cut.srt"))   # 名前は元の切り抜き
        self.assertEqual(res["mediaKeeps"], [[300, 360], [420, 480]])
        self.assertEqual((res["editMedia"]["handleBefore"], res["editMedia"]["handleAfter"]), (10.0, 10.0))
        ip = RTP.read_script_plan((out / "create_resolve_textplus_project.lua").read_text(encoding="utf-8"))
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(300, 360), (420, 480)])
        self.assertEqual([(c["startFrame"], c["endFrame"]) for c in ip["captions"]], [(0, 60), (60, 120)])  # タイムラインの位置は同じ
        self.assertEqual(ip["sourceTimeline"], {"startFrame": 0, "endFrame": 780})   # 復旧用は余白込みの全体
        self.assertEqual(ip["media"]["file"], "media/clip_edit.mp4")
        self.assertEqual(ip["title"], "clip")
        self.assertIn("media\\clip_edit.mp4", (out / "install_resolve_textplus_script.ps1").read_text(encoding="utf-8-sig"))
        ev = parse_edl(files["edl"].read_text(encoding="utf-8"))
        self.assertEqual([(tc2f(e[3], 30), tc2f(e[4], 30)) for e in ev], [(300, 360), (420, 480)])
        self.assertIn("FROM CLIP NAME: clip_edit.mp4", ev[0][7])
        cp = json.loads((out / "cut-plan.json").read_text(encoding="utf-8"))
        self.assertEqual(cp["editMedia"]["keep_frames"], [[300, 360], [420, 480]])
        self.assertEqual(cp["keep_frames"], [[0, 60], [120, 180]])   # 読み直す用の区間は元の切り抜きの時刻
        self.assertTrue(any("余白つき素材" in w for w in res["warnings"]))
        # 上書き確認の下見も同じ名前を出す
        _, paths, _ = pack.planned_outputs(plan, out, textplus=True)
        self.assertEqual(paths["video"], out / "media" / "clip_edit.mp4")

    def test_not_used_without_video_or_when_disabled(self):
        res = pack.build_pack(self.plan(), Path(self.tmp.name) / "pack_edl")          # EDL だけ(動画を入れない)
        self.assertIsNone(res["editMedia"])
        ev = parse_edl(dict(res["files"])["edl"].read_text(encoding="utf-8"))
        self.assertEqual([(tc2f(e[3], 30), tc2f(e[4], 30)) for e in ev], [(0, 60), (120, 180)])
        out = Path(self.tmp.name) / "pack_off"
        res = pack.build_pack(self.plan(edit_media=False), out, textplus=True)
        self.assertIsNone(res["editMedia"])
        self.assertTrue((out / "media" / "clip.mp4").is_file())

    def test_mismatched_edit_media_falls_back(self):
        d = Path(self.tmp.name)
        sc = d / "clip.edit.json"
        orig = sc.read_text(encoding="utf-8")
        try:
            sc.write_text(json.dumps({"schema": C.EDIT_MEDIA_SCHEMA, "media": "other_edit.mp4",
                                      "selectionIn": 10, "handleBefore": 10, "handleAfter": 10}), encoding="utf-8")
            out = d / "pack_mismatch"
            res = pack.build_pack(self.plan(), out, textplus=True)
            self.assertIsNone(res["editMedia"])
            self.assertTrue((out / "media" / "clip.mp4").is_file())
            self.assertTrue(any("fps・大きさが違う" in w for w in res["warnings"]))
            sc.write_text(json.dumps({"schema": C.EDIT_MEDIA_SCHEMA, "media": "clip_edit.mp4",
                                      "selectionIn": 22, "handleBefore": 10, "handleAfter": 0}), encoding="utf-8")
            res = pack.build_pack(self.plan(), d / "pack_short", textplus=True)      # 22 + 6 秒 > 26 秒
            self.assertIsNone(res["editMedia"])
            self.assertTrue(any("短い" in w for w in res["warnings"]))
        finally:
            sc.write_text(orig, encoding="utf-8")

    def test_join_frames(self):
        tr = write(Path(self.tmp.name) / "gap.transcript.json", json.dumps(transcript_doc(
            [(1, 2, "a", False), (2.034, 3, "b", False)])))
        req = pack.Request(video=self.video, transcript=tr, **dict(pack.TRANSCRIPT_ROWS, row_edge=None))   # 端を広げない(つなぐ隙間だけを見る)
        self.assertEqual(pack.plan_cut(req).keeps, [(30, 90)])
        self.assertEqual(pack.plan_cut(dataclasses_replace(req, join_frames=0)).keeps, [(30, 60), (61, 90)])
        for bad in (-1, 1.5, True, 1001):
            with self.subTest(bad=bad), self.assertRaises(pack.ToolError):
                pack.plan_cut(dataclasses_replace(req, join_frames=bad))


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無いためスキップ")
class TestMinimalPack(unittest.TestCase):
    """パックの出力を最小限に(docs/edit-tool-design.md の 12 ④): 既定の Text+ パックは media の動画・Lua・雛形・登録用の ps1/bat・友人へ.txt だけ。
    backup=True で EDL・予備_EDLで開く手順.txt・カット後の SRT も。plan_file=False で cut-plan.json を書かない(画面・API。記録は作業データ)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.video = d / "clip.mp4"
        make_video(cls.video, dur=6)
        cls.tr = write(d / "clip.transcript.json", json.dumps(transcript_doc([(0.5, 2, "一", False), (3, 5, "二", False)]), ensure_ascii=False))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def build(self, name, **kw):
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=self.tr, **dict(pack.TRANSCRIPT_ROWS, row_edge=None)))
        out = Path(self.tmp.name) / name
        return out, pack.build_pack(plan, out, textplus=True, **kw)

    def names(self, out):
        return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())

    MINIMAL = ["ResolveにText+スクリプトを登録.bat", "create_resolve_textplus_project.lua", "install_resolve_textplus_script.ps1",
               "media/clip.mp4", "textplus-template.drb", "友人へ.txt"]

    def test_minimal_by_default_for_screen(self):
        out, res = self.build("min", backup=False, plan_file=False)
        self.assertEqual(self.names(out), self.MINIMAL)
        self.assertEqual(sorted(p.relative_to(out).as_posix() for _, p in res["files"]), self.MINIMAL)
        self.assertEqual(res["plan"]["schema"], "youtube-tools-cut-plan/v1")         # cut-plan の中身は返す(作業データに記録する)
        self.assertEqual(res["plan"]["keep_frames"], [[15, 60], [90, 150]])
        readme = (out / "友人へ.txt").read_text(encoding="utf-8-sig")
        self.assertNotIn("予備_EDLで開く手順", readme)                             # 入っていない予備を案内しない
        self.assertIn("予備も入れて", readme)
        ip = RTP.read_script_plan((out / "create_resolve_textplus_project.lua").read_text(encoding="utf-8"))
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(15, 60), (90, 150)])
        self.assertEqual([c["text"] for c in ip["captions"]], ["一", "二"])
        self.assertEqual(res["readme"], readme)

    def test_backup_adds_edl_readme_and_srt(self):
        out, res = self.build("bk", backup=True, plan_file=False)
        self.assertEqual(self.names(out), sorted(self.MINIMAL + ["clip.edl", "clip_cut.srt", "予備_EDLで開く手順.txt"]))
        self.assertIn("予備_EDLで開く手順.txt", (out / "友人へ.txt").read_text(encoding="utf-8-sig"))
        self.assertNotIn("cut-plan.json", (out / "予備_EDLで開く手順.txt").read_text(encoding="utf-8-sig"))   # 入れていないものを載せない

    def test_command_keeps_full_output(self):
        out, res = self.build("cli")                                                # コマンドの既定(予備・cut-plan.json も)。.json だけは出さない
        self.assertEqual(self.names(out), sorted(self.MINIMAL + ["clip.edl", "clip_cut.srt", "予備_EDLで開く手順.txt", "cut-plan.json"]))

    def test_overwrite_check_and_leftovers(self):
        out, _ = self.build("again", backup=True, plan_file=True)                 # 以前の中身(予備・cut-plan.json)のフォルダ
        (out / "textplus-import.json").write_text("{}", encoding="utf-8")         # 以前の版の .json
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=self.tr, **dict(pack.TRANSCRIPT_ROWS, row_edge=None)))
        _, paths, existing = pack.planned_outputs(plan, out, textplus=True, backup=False, plan_file=False)
        self.assertEqual(sorted(p.name for p in existing), sorted(Path(n).name for n in self.MINIMAL))   # 上書きの確認は今回書くものだけ
        with self.assertRaises(C.OutputExists):
            pack.build_pack(plan, out, textplus=True, backup=False, plan_file=False)
        res = pack.build_pack(plan, out, textplus=True, backup=False, plan_file=False, force=True)
        left = next(w for w in res["warnings"] if "前に作った" in w)
        for n in ("clip.edl", "clip_cut.srt", "予備_EDLで開く手順.txt", "cut-plan.json", "textplus-import.json"):
            self.assertIn(n, left)                                                  # 残っている以前のファイルを知らせる(消さない)


class TestRowEdgeRule(unittest.TestCase):
    """行から作るカットの端を声の止まる所まで広げる規則(pack.widen_row_edges。docs/edit-tool-design.md の 12 ⑥)。30fps: 0.1 秒 = 3 フレーム"""
    E = pack.ROW_EDGE   # 後 0.5 秒(15)・前 0.3 秒(9)まで。無音が無ければ 後 0.2 秒(6)・前 0.1 秒(3)

    def w(self, spans, silence, total=900, edge=None):
        return pack.widen_row_edges(spans, silence, FPS30, total, edge or self.E)

    def test_extends_to_where_voice_stops(self):
        self.assertEqual(self.w([(100, 200)], [(40, 95), (210, 300)]), [(95, 210)])   # 前は 5・後は 10 フレームの所で無音

    def test_stops_at_the_limit(self):
        self.assertEqual(self.w([(100, 200)], [(40, 90), (216, 300)]), [(97, 206)])   # 窓(前 9・後 15)の外の無音 → 決まった余白
        self.assertEqual(self.w([(100, 200)], [(40, 91), (215, 300)]), [(91, 215)])   # ちょうど窓の端

    def test_fixed_pad_without_silence(self):
        self.assertEqual(self.w([(100, 200)], []), [(97, 206)])        # BGM が続く(無音が無い)
        self.assertEqual(self.w([(100, 200)], None), [(97, 206)])      # 調べていない(detect=False・調べられない)
        self.assertEqual(self.w([(100, 200)], [], edge=pack.row_edge_from({"after": 0.1, "before": 0})), [(100, 203)])   # 余白も上限の中

    def test_edge_already_in_silence_stays(self):
        self.assertEqual(self.w([(100, 200)], [(90, 105), (195, 260)]), [(100, 200)])
        self.assertEqual(self.w([(100, 200)], [(90, 100), (200, 260)]), [(100, 200)])   # ちょうど無音の境目

    def test_neighbours_join_and_clamp(self):
        self.assertEqual(self.w([(100, 200), (205, 300)], []), [(97, 306)])             # 広げて重なった → 1つ
        self.assertEqual(self.w([(2, 50), (880, 898)], [], total=900), [(0, 56), (877, 900)])   # 0〜動画の長さ
        self.assertEqual(self.w([(100, 200), (230, 300)], [(200, 230)]), [(97, 200), (230, 306)])   # 間の無音はそのまま削る

    def test_does_not_cross_cut_rows(self):
        blocks = [(40, 98), (203, 260)]   # カット済の行
        self.assertEqual(pack.widen_row_edges([(100, 200)], [(40, 95), (210, 300)], FPS30, 900, self.E, blocks), [(98, 203)])
        self.assertEqual(pack.widen_row_edges([(100, 200)], [], FPS30, 900, self.E, [(90, 100), (200, 230)]), [(100, 200)])

    def test_row_edge_from(self):
        self.assertIs(pack.row_edge_from(None), pack.ROW_EDGE)
        self.assertIs(pack.row_edge_from(True), pack.ROW_EDGE)
        self.assertIsNone(pack.row_edge_from(False))
        self.assertIsNone(pack.row_edge_from({"on": False, "after": 1}))
        e = pack.row_edge_from({"on": True, "after": 0.8, "before": 0})
        self.assertEqual((e.after, e.before, e.pad_after, e.noise), (0.8, 0.0, 0.2, -35.0))
        for bad in ({"after": 3}, {"before": -1}, {"after": "x"}, {"after": True}, [1], "on"):
            with self.subTest(bad=bad), self.assertRaises(pack.ToolError):
                pack.row_edge_from(bad)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無いためスキップ")
class TestRowEdgeWithAudio(unittest.TestCase):
    """合成の音(声の代わりの音と無音。0-2 秒 音 / 2-4 無音 / 4-6 音 / 6-8 無音 / 8-10 音)で、行から作るカットの端を確かめる"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.video = d / "gaps.mp4"
        make_video(cls.video, dur=10, audio="gaps")
        cls.mute = d / "mute.mp4"
        make_video(cls.mute, dur=10, audio=None)
        cls.n = 0

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def keeps(self, rows, video=None, **kw):
        type(self).n += 1
        tr = write(Path(self.tmp.name) / ("r%d.transcript.json" % self.n), json.dumps(transcript_doc(rows), ensure_ascii=False))
        plan = pack.plan_cut(pack.Request(video=video or self.video, transcript=tr, **dict(pack.TRANSCRIPT_ROWS, **kw)))
        return plan.keeps, plan

    def near(self, got, want, tol=1):
        """AAC の符号化で無音の境目が 1 フレームほど前後することがある"""
        self.assertEqual(len(got), len(want), got)
        for g, x in zip(got, want):
            self.assertTrue(all(abs(a - b) <= tol for a, b in zip(g, x)), "%r != %r" % (got, want))

    def test_widens_to_silence_and_limits(self):
        # 終わり 1.8 → 無音の始まり 2.0(60)。始まり 4.2 → 無音の終わり 4.0(120)。終わり 5.0 → 窓(5.5 まで)に無音が無い → 5.2(156)。
        # 始まり 0.5 → 前に無音が無い → 0.4(12)
        k, plan = self.keeps([(0.5, 1.8, "一", False), (4.2, 5.0, "二", False)])
        self.near(k, [(12, 60), (120, 156)])
        self.assertEqual([c[2] for c in plan.cues_out], ["一", "二"])
        self.assertEqual(plan.cues[0][:2], (500, 1800))                    # 字幕(行の時刻)は変えない
        # 上限: 終わり 1.0 → 無音(2.0)は 0.5 秒より先 → 決まった余白 1.2(36)
        k, _ = self.keeps([(0.5, 1.0, "一", False)])
        self.assertEqual(k, [(12, 36)])

    def test_neighbours_join(self):
        # 4.2〜4.9 と 5.1〜5.8: 4.9+0.2 = 5.1、5.1−0.1 = 5.0 で重なる → 1つ。終わり 5.8 → 無音 6.0
        k, _ = self.keeps([(4.2, 4.9, "a", False), (5.1, 5.8, "b", False)])
        self.near(k, [(120, 180)])

    def test_cut_rows_stay_cut(self):
        # 残す行の終わりを広げても、隣の「カット済」の行の時間には入らない・越えない(無音 2.0 までの 1.9〜2.0 の切れ端を残さない)
        k, _ = self.keeps([(0.5, 1.5, "a", False), (1.5, 1.9, "切る", True)])
        self.assertEqual(k, [(12, 45)])
        k, _ = self.keeps([(0.5, 1.5, "a", False), (1.6, 1.9, "切る", True)])
        self.assertEqual(k, [(12, 48)])                                    # カット済の行の手前(1.6)まで
        k, _ = self.keeps([(0.5, 1.5, "a", False), (1.5, 1.9, "切る", True)], drop_cut_rows=False)
        self.assertEqual(k, [(12, 60)])                                    # カット済の行で削らない指定なら、行として扱わない

    def test_off_and_fixed_and_no_audio(self):
        rows = [(0.5, 1.8, "一", False)]
        self.assertEqual(self.keeps(rows, row_edge=None)[0], [(15, 54)])                                   # 広げない
        self.assertEqual(self.keeps(rows, row_edge=pack.without_detect(pack.Request(
            video=self.video, row_edge=pack.ROW_EDGE)).row_edge)[0], [(12, 60)])                        # 無音を調べない → 決まった余白
        self.assertEqual(self.keeps(rows, video=self.mute)[0], [(15, 54)])                                 # 音声が無い → 広げない

    def test_detection_failure_falls_back_to_pad(self):
        with mock.patch.object(C, "detect_silence", side_effect=C.ToolError("だめ")):
            k, plan = self.keeps([(0.5, 1.8, "一", False)])
        self.assertEqual(k, [(12, 60)])
        self.assertTrue(any("声の止まる所を調べられなかった" in w for w in plan.warnings))

    def test_pending_and_cache(self):
        tr = write(Path(self.tmp.name) / "p.transcript.json", json.dumps(transcript_doc([(0.5, 1.8, "一", False)]), ensure_ascii=False))
        req = pack.Request(video=self.video, transcript=tr, **pack.TRANSCRIPT_ROWS)
        cache = pack.Cache()
        self.assertTrue(pack.row_edge_pending(req, cache))
        pack.plan_cut(req, cache=cache)
        self.assertFalse(pack.row_edge_pending(req, cache))                 # 2回目は覚えた無音を使う
        self.assertFalse(pack.row_edge_pending(dataclasses_replace(req, row_edge=None), cache))
        self.assertFalse(pack.row_edge_pending(pack.without_detect(req), cache))
        self.assertFalse(pack.row_edge_pending(pack.Request(video=self.video, base="all", row_edge=pack.ROW_EDGE), cache))

    def test_only_rows_base(self):
        """手で決めた区間(keeps)・時刻リストには使わない"""
        plan = pack.plan_cut(pack.Request(video=self.video, keep_pairs=[(0.5, 1.8)], **pack.EDIT_KEEPS))
        self.assertEqual(plan.keeps, [(15, 54)])
        plan = pack.plan_cut(pack.Request(video=self.video, base="list", keep_pairs=[(0.5, 1.8)], min_len=0, row_edge=pack.ROW_EDGE))
        self.assertEqual(plan.keeps, [(15, 54)])

    def test_cli_option(self):
        import contextlib
        import io
        tr = write(Path(self.tmp.name) / "cli.transcript.json", json.dumps(transcript_doc([(0.5, 1.8, "一", False)]), ensure_ascii=False))
        for extra, shown in (([], True), (["--no-row-edge"], False)):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(FULL.main([str(self.video), "--transcript", str(tr), "--keep-rows", "--dry-run"] + extra), 0)
            self.assertEqual("行の端: 声の止まる所まで" in buf.getvalue(), shown, buf.getvalue())


def dataclasses_replace(obj, **kw):
    import dataclasses
    return dataclasses.replace(obj, **kw)


if __name__ == "__main__":
    unittest.main(verbosity=2)
