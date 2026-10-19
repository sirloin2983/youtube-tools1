#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""パック(pipeline.pack)のテスト。正しく動く道・端の場合・時刻の計算・入力の誤りは、本物の ffmpeg の通し(TestPackRun)で見本に混ぜてまとめて確かめる。
ほかのクラスは通しでは起こせない物だけ(Resolve の中の Lua・途中の失敗と中止・前の版の形・壊れた記録・後から書き換えた置き場所・安全の境目)。
python -m unittest test_pack(道具は test_cut2resolve から読む)"""
import hashlib
import json
import os
os.environ.setdefault("YTT_DATA_DIR", "inplace")   # テストは作業データを本物の置き場所(AppData など)に書かない(ytt.datadir)
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parents[2]))   # src(パックの部品は pipeline.pack)
sys.path.insert(0, str(TESTS))          # 隣のテスト(test_cut2resolve の道具)
from pipeline.pack import auto_cut as AC  # noqa: E402
from pipeline.pack import cut2resolve_core as C  # noqa: E402
from pipeline.pack import pack  # noqa: E402
from pipeline.pack import request as R  # noqa: E402
from pipeline.pack import resolve_textplus as RTP  # noqa: E402
from pipeline.pack import srt2resolve as S  # noqa: E402
from ytt import testkit  # noqa: E402
from ytt.errors import ApiError  # noqa: E402
from test_cut2resolve import FPS30, HAVE_FFMPEG, make_video, parse_edl, selection_pack, tc2f  # noqa: E402


def write(path, text, enc="utf-8"):
    Path(path).write_text(text, encoding=enc)
    return Path(path)


def transcript_doc(rows, media=None):
    return {"schema": "youtube-tools-transcript/v1", "tool": {"name": "transcribe-tool", "version": "0.10.0"},
            "media": media or {}, "segments": [dict(id="s%d" % i, start=a, end=b, text=t, cut=c)
                                              for i, (a, b, t, c) in enumerate(rows, 1)]}


def ffmpeg_video(path, dur, rate, size="160x90", audio=True, extra=()):
    """make_video に無い指定(fps の分数・埋め込みのタイムコード)の見本"""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=%s:rate=%s:duration=%s" % (size, rate, dur)]
    if audio:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % dur, "-c:a", "aac", "-shortest"]
    subprocess.run(cmd + ["-pix_fmt", "yuv420p", "-c:v", "libx264", *extra, str(path)], check=True)
    return Path(path)


def _lua_runtime():
    import shutil as _sh
    for name in ("luajit", "lua5.1", "lua", "texlua"):   # Resolve は LuaJIT。無ければ構文の近い Lua 5.3(texlua)で代用
        p = _sh.which(name)
        if p:
            return p
    return None


def _textplus_plan(cues_out, keeps, fps=(60, 1), total=2064, target=None, video_tracks=1):
    plan = mock.Mock()
    plan.video = Path('test.mp4')
    plan.req.name = 'test'
    plan.meta = {'fps': fps, 'w': 1920, 'h': 1080, 'total': total}
    plan.cues_out = cues_out
    plan.keeps = keeps
    return RTP.build_import_plan(plan, Path('media/test.mp4'), target, video_tracks=video_tracks)


class TestResolveTextPlusScript(unittest.TestCase):
    """計画の作り方では起きない守り(通しの出力には出ない)"""

    def test_plan_guards(self):
        with self.assertRaises(ValueError):                       # plan_cut の字幕は必ず区間の中なので、通しでは起きない
            RTP.caption_segments([(100, 700), (1000, 1600)], [(1300, 1310, 'x')])
        plan = _textplus_plan([(60, 300, 'a')], [(0, 2064)])
        before = json.dumps(plan, sort_keys=True)
        RTP.importer_script(plan)                                 # Lua を作っても計画を書き換えない(呼んだ後の計画は通しの出力に出ない)
        self.assertEqual(json.dumps(plan, sort_keys=True), before)


@unittest.skipUnless(_lua_runtime(), 'Lua の実行環境がない')
class TestResolveTextPlusLuaRun(unittest.TestCase):
    """生成した Lua を、Resolve の API をまねた偽物(resolve_lua_mock.lua)の上で実際に動かす"""

    KEI = {'けいふぉんと': ['Regular'], 'Meiryo': ['Regular']}   # 指定のフォントを入れた PC

    def run_lua(self, plan, settings, media_fps=60, template_ok=True, media_ok=True, fonts=None, ignore=(), inputs=(), media_path=None):
        mock_path = TESTS / 'resolve_lua_mock.lua'
        body = RTP.importer_script(plan)
        pre = 'dofile(%s)\n' % json.dumps(str(mock_path))
        pre += 'MOCK.mediaFps = %s\nMOCK.templateOk = %s\nMOCK.mediaOk = %s\n' % (
            media_fps, 'true' if template_ok else 'false', 'true' if media_ok else 'false')
        for k, v in settings.items():
            pre += 'MOCK.settings[%s] = %s\n' % (json.dumps(k), json.dumps(v))
        for k in ignore:        # この Resolve に無い入力の名前(実機で名前が違ったとき)
            pre += 'MOCK.ignoreInputs[%s] = true\n' % json.dumps(k)
        for i, (k, n) in enumerate(inputs, 1):   # GetInputList が返す入力(名前, 表示名)
            pre += 'MOCK.inputList[%d] = {id=%s, name=%s}\n' % (i, json.dumps(k), json.dumps(n, ensure_ascii=False))
        if media_path:          # 登録用の ps1 と同じく、動画の場所を埋め込む
            body = body.replace('__C2R_MEDIA_PATH__', str(media_path).replace('\\', '\\\\'))
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
        self.assertIn('item track=2 start=108030 dur=120 text=一 font=けいふぉんと', out)   # 指定のフォント(ユーザーの指定)
        self.assertIn('  style=Regular fill=0.0,0.0,0.0 outline=1:1.0,1.0,1.0', out)       # 黒い文字 + 白いふち
        self.assertIn('  size=0.14 anchor=1.0,0.0 thick=0.12,0.18 shape=0,1,1 prio=8,7,4 offset2=0.015,-0.02 outer=1:0.0,0.0,0.0', out)   # + 外側の黒いふち
        self.assertIn('字体 けいふぉんと Regular(指定のフォント)', out)
        self.assertIn('・見た目 けいふぉんと・黒い文字・白いふち・黒いふち・', out)
        self.assertIn('item track=2 start=108300 dur=60 text=二', out)
        self.assertIn('item track=2 start=108550 dur=51 text=三', out)
        self.assertIn('marker=Green|cut2resolve 完了|字幕 3/3・カット 2/2・長さのずれ 0', out)

    def test_video_tracks_put_captions_on_top(self):
        """映像トラックの数 3: V1〜V3 = 同じカットの動画(V2・V3 は映像だけ = mediaType 1)・V4 = 字幕(一番上)。既定 1 は V2"""
        s = {'timelineFrameRate': '30', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'}
        out = self.run_lua(_textplus_plan([(60, 300, '一')], [(0, 600), (1000, 1601)], video_tracks=3), s, fonts=self.KEI)
        cut = out.split('timeline=CUT_TextPlus\n')[1].split('timeline=')[0]
        self.assertIn('tracks=4\n', cut)
        for k in (1, 2, 3):                                                   # 各トラックに 2 区間・同じ位置と長さ
            self.assertIn('item track=%d start=108000 dur=300' % k, cut)
            self.assertIn('item track=%d start=108300 dur=301' % k, cut)
        self.assertEqual(cut.count('  mediaType=1'), 4)                         # V2・V3 の 2 区間ずつ = 映像だけ(音声は A1 だけ)
        self.assertIn('item track=4 start=108030 dur=120 text=一', cut)
        self.assertIn('marker=Green|cut2resolve 完了|字幕 1/1(V4)・カット 2/2・同じ映像 V1〜V3・', cut)
        out = self.run_lua(_textplus_plan([(60, 300, '一')], [(0, 600)]), s, fonts=self.KEI)
        cut = out.split('timeline=CUT_TextPlus\n')[1].split('timeline=')[0]
        self.assertIn('tracks=2\n', cut)
        self.assertIn('item track=2 start=108030 dur=120 text=一', cut)
        self.assertIn('|字幕 1/1・カット 1/1・長さ', cut)
        self.assertNotIn('mediaType', cut)

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
        # けいふぉんと が無い PC: 自動選択(Windows の日本語フォント)にして、マーカーを黄色(要確認)に
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
        out = self.run_lua(plan, s, fonts=self.KEI, ignore=('Offset2', 'Priority5', 'PriorityBack5'))
        self.assertIn('(反映できなかった: Offset2, Priority5)', out)
        self.assertIn('marker=Yellow|cut2resolve 完了(要確認)|字幕 2/2', out)
        # 実機で Priority1/2/5 が入らなかった: 入力の一覧から表示名「Priority」と要素の番号で探す → 候補の名前、の順。
        # 見つけた名前は 2つ目の字幕でも使い、メモに「読み替え」と出す(緑のまま)。見つからなければ入力の一覧をパックのフォルダに書く
        no_prio = ('Priority1', 'Priority2', 'Priority5')
        # 一覧から表示名で見つかる(候補の名前より先)
        listed = [('ElementPriority%d' % n, 'Priority') for n in (1, 2, 5)] + [('Softness1', 'Softness')]
        out = self.run_lua(plan, s, fonts=self.KEI, ignore=no_prio, inputs=listed)
        self.assertIn('入力の名前を読み替え: Priority1→ElementPriority1, Priority2→ElementPriority2, Priority5→ElementPriority5', out)
        self.assertIn('marker=Green|cut2resolve 完了|', out)
        self.assertNotIn('反映できなかった', out)
        # 一覧を読めない → 候補の名前(PriorityBack)
        out = self.run_lua(plan, s, fonts=self.KEI, ignore=no_prio)
        self.assertIn('入力の名前を読み替え: Priority1→PriorityBack1, Priority2→PriorityBack2, Priority5→PriorityBack5', out)
        self.assertIn('marker=Green|', out)
        # どれも入らない → 黄色・入力の一覧をパックのフォルダ(動画の隣)に書く
        with tempfile.TemporaryDirectory() as d:
            video = Path(d) / 'clip.mp4'
            out = self.run_lua(plan, s, fonts=self.KEI, ignore=no_prio + ('PriorityBack1', 'PriorityBack2', 'PriorityBack5'),
                               inputs=[('Softness1', 'Softness'), ('Offset5', 'Offset')], media_path=video)
            self.assertIn('(反映できなかった: Priority1, Priority2, Priority5。入力の一覧: textplus-inputs.txt)', out)
            self.assertIn('marker=Yellow|', out)
            dump = (Path(d) / 'textplus-inputs.txt').read_text(encoding='utf-8')
            self.assertIn('Offset5\tOffset', dump)
            self.assertIn('Softness1\tSoftness', dump)

    def test_wrong_project_settings_stop_without_changes(self):
        out = self.run_lua(_textplus_plan([(60, 300, 'a')], [(0, 2064)]),
                           {'timelineFrameRate': '60', 'timelineResolutionWidth': '1920', 'timelineResolutionHeight': '1080'})
        self.assertIn('forbidden=\n', out)
        self.assertIn('timeline=C2R_エラー_プロジェクトのfps・解像度が違う', out)
        self.assertNotIn('CUT_TextPlus', out)
        self.assertIn('media=nil', out)                 # 動画も読み込まない

    def test_30fps_media_on_60fps_project_warns_without_stopping(self):
        """素材が 30fps(Q1)のとき、プロジェクトが 60fps でも止めずに置く(換算 x2)。マーカーは黄色で注意を出す。大きさが違うときは止める"""
        plan = _textplus_plan([(30, 150, '一')], [(0, 300)], fps=(30, 1), total=900)
        out = self.run_lua(plan, {'timelineFrameRate': '60', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'},
                           media_fps=30, fonts=self.KEI)
        self.assertNotIn('C2R_エラー', out)
        self.assertIn('item track=1 start=108000 dur=600', out)                       # 300 コマ x (60/30)
        self.assertIn('item track=2 start=108060 dur=240 text=一', out)               # 字幕も換算(開始 30 コマ → 60、長さ 120 → 240)
        self.assertIn('marker=Yellow|cut2resolve 完了(要確認)|', out)
        self.assertIn('・注意 素材は30fpsですがプロジェクトは60', out)
        out = self.run_lua(plan, {'timelineFrameRate': '30', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'},
                           media_fps=30, fonts=self.KEI)
        self.assertIn('marker=Green|', out)                                            # 30fps のプロジェクトなら警告なし
        self.assertNotIn('注意 素材は', out)
        out = self.run_lua(plan, {'timelineFrameRate': '30', 'timelineResolutionWidth': '1920', 'timelineResolutionHeight': '1080'}, media_fps=30)
        self.assertIn('timeline=C2R_エラー_プロジェクトのfps・解像度が違う', out)         # 大きさが違えば止める

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

    def test_overlapping_captions_go_to_upper_lanes(self):
        """重なる字幕の段: 2 段目は字幕のトラックの 1 つ上・縦の位置を LANE_STEP_Y だけ上(偽物の Center は空 → 0.5 + 0.2)。
        切った字幕は短くなる。映像トラック 2 のときは字幕 V3・段 V4"""
        s = {'timelineFrameRate': '30', 'timelineResolutionWidth': '1080', 'timelineResolutionHeight': '1920'}
        cues = [(30, 120, '一'), (60, 150, '二'), (150, 210, '三'), (205, 260, '四')]
        out = self.run_lua(_textplus_plan(cues, [(0, 900)], fps=(30, 1), total=900), s, media_fps=30, fonts=self.KEI)
        cut = out.split('timeline=CUT_TextPlus\n')[1].split('timeline=')[0]
        self.assertIn('tracks=3\n', cut)
        self.assertIn('item track=2 start=108030 dur=90 text=一', cut)
        self.assertIn('item track=3 start=108060 dur=90 text=二', cut)
        self.assertIn('item track=2 start=108150 dur=55 text=三', cut)   # 四 に 5 コマはみ出す → 切る
        self.assertIn('item track=2 start=108205 dur=55 text=四', cut)
        self.assertEqual(cut.count('  center=0.5,0.7'), 1)                # 2 段目の 二 だけ
        self.assertIn('marker=Green|cut2resolve 完了|字幕 4/4・重なる字幕 V2〜V3(2 段)・カット 1/1・', cut)
        out = self.run_lua(_textplus_plan(cues, [(0, 900)], fps=(30, 1), total=900, video_tracks=2), s, media_fps=30, fonts=self.KEI)
        cut = out.split('timeline=CUT_TextPlus\n')[1].split('timeline=')[0]
        self.assertIn('tracks=4\n', cut)
        self.assertIn('item track=3 start=108030 dur=90 text=一', cut)
        self.assertIn('item track=4 start=108060 dur=90 text=二', cut)
        self.assertIn('|字幕 4/4(V3)・重なる字幕 V3〜V4(2 段)・カット 1/1・同じ映像 V1〜V2', cut)
        out = self.run_lua(_textplus_plan(cues, [(0, 900)], fps=(30, 1), total=900), s, media_fps=30, fonts=self.KEI, ignore=('Center',))
        self.assertIn('marker=Yellow|cut2resolve 完了(要確認)|字幕 4/4・重なる字幕 V2〜V3(2 段。位置を変えられなかった 1)', out)


class TestParsingFixes(unittest.TestCase):
    def test_edl_clip_name_newline_is_removed(self):
        """動画の名前の改行は EDL に入れない(Windows のファイル名には改行が入らないので通しでは作れない)"""
        text = C.build_edl("t", "a\nb.mp4", [(0, 5)], FPS30, True)
        self.assertIn("* FROM CLIP NAME: a b.mp4", text)
        self.assertEqual(len(parse_edl(text)), 1)


class TestGainCopyRecord(unittest.TestCase):
    """音量をかけた写しの記録(gain_copy_record)と比べ方(same_gain_copy)。前の記録の形の違い・壊れた記録・秒の中の更新日時は
    通しでは作れないので、記録を直に書き換えて確かめる。ffmpeg は使わない"""
    T0 = 1_700_000_000_250_000_000

    def setUp(self):
        self.dir = Path(testkit.tempdir(self))
        self.src = write(self.dir / "clip.mp4", "source")
        os.utime(self.src, ns=(self.T0, self.T0))
        self.out = self.dir / "pack"
        self.out.mkdir()
        self.dst = write(self.out / "clip.mp4", "copied with gain")
        self.meta = {"start_tc": "01:00:00:00"}

    def _rec(self, gain=-10.457):
        key = C.gain_copy_key(self.src, self.dst, gain, self.meta)
        return key, json.loads(json.dumps(C.gain_copy_record(key, self.dst, volume=30)))   # パックの記録を通したのと同じ形

    def test_key_and_record(self):
        key, rec = self._rec()
        self.assertEqual(key["source"], {"name": "clip.mp4", "size": 6, "mtime": self.T0 // 10 ** 9})
        self.assertEqual((key["v"], key["gainDb"]), (C.GAIN_COPY_V, -10.46))
        self.assertEqual(key["ffmpeg"], C._gain_copy_opts(self.src, ".mp4", -10.457, self.meta))   # 書き出しの設定 = copy_video_gain が使うもの
        self.assertIn("volume=-10.46dB", key["ffmpeg"])
        self.assertEqual(key["ffmpeg"][-2:], ["-timecode", "01:00:00:00"])
        st = self.dst.stat()
        self.assertEqual(rec["output"], {"name": "clip.mp4", "size": st.st_size, "mtime": st.st_mtime_ns // 10 ** 9})
        self.assertEqual(rec["volume"], 30)
        webm = C.gain_copy_key(self.src, self.out / "clip.webm", -3, {"start_tc": None})["ffmpeg"]
        self.assertIn("libopus", webm)
        self.assertNotIn("+faststart", webm)
        self.assertIsNone(C.gain_copy_key(self.dir / "none.mp4", self.dst, -3, self.meta))   # 元が読めない = 記録しない
        self.assertIsNone(C.gain_copy_record(None, self.dst))
        self.assertIsNone(C.gain_copy_record(key, self.out / "none.mp4"))

    def test_same_only_when_everything_matches(self):
        key, rec = self._rec()
        self.assertTrue(C.same_gain_copy(key, self.dst, rec))
        self.assertTrue(C.same_gain_copy(dict(key), self.dst, dict(rec, volume=None, loudness=-14)))   # 量の決め方は比べない(かけた dB で比べる)

        def changed(path, value):
            r = json.loads(json.dumps(rec))
            d = r
            for k in path[:-1]:
                d = d[k]
            d[path[-1]] = value
            return r
        for path, value in ((("v",), 0), (("gainDb",), -10.45), (("ffmpeg",), key["ffmpeg"][:-2]), (("source", "size"), 7),
                            (("source", "mtime"), self.T0 // 10 ** 9 + 1), (("source", "name"), "other.mp4"),
                            (("output", "size"), 1), (("output", "mtime"), 0), (("output", "name"), "x.mp4")):
            self.assertFalse(C.same_gain_copy(key, self.dst, changed(path, value)), path)
        for prev in (None, "x", [], {}, {"output": rec["output"]}):                         # 記録が無い・形が違う
            self.assertFalse(C.same_gain_copy(key, self.dst, prev), prev)
        self.assertFalse(C.same_gain_copy(None, self.dst, rec))
        self.assertFalse(C.same_gain_copy(key, self.out / "none.mp4", rec))                # 置き場所に動画が無い
        self.assertFalse(C.same_gain_copy(key, self.out, rec))                              # フォルダ
        os.utime(self.dst, ns=(self.T0, self.T0))                                           # 置き場所の動画が変わった(更新日時)
        self.assertFalse(C.same_gain_copy(key, self.dst, rec))
        os.utime(self.src, ns=(self.T0 + 600_000_000,) * 2)                                 # 元の動画の更新日時が同じ秒の中で変わっただけ
        self.assertEqual(C.gain_copy_key(self.src, self.dst, -10.457, self.meta), key)      # → 条件は同じ(same_copy と同じ秒単位)


class TestOldDocs(unittest.TestCase):
    """前の版の形(通しの道具は今の形しか書かない)と、安全の境目のうち通しで起こせない物(ネットワークのパス)"""

    def setUp(self):
        self.dir = Path(testkit.tempdir(self))

    def test_old_detailed_cut_plan_is_readable(self):
        p = write(self.dir / "cut-plan.json", json.dumps({"schema": "youtube-tools-cut-plan/v1", "frame_rate": "30/1",
                                                         "keep_frames": [[30, 60], [90, 150]]}))
        doc = AC.read_cut_plan(p)
        self.assertEqual([(s["start_seconds"], s["end_seconds"]) for s in doc["segments"]], [(1, 2), (3, 5)])
        self.assertEqual(AC.default_handles(doc), 0.0)

    def test_network_paths_are_not_touched(self):
        """ネットワーク上のパス(サーバーの共有)は存在も確かめない(確かめるだけで資格情報のハッシュを送るため)。"""
        for p in (r"\\server\share\clip2.mp4", "//server/share/clip2.mp4"):
            self.assertTrue(C.is_network_path(p), p)
        for p in (r"C:\gone\clip.mp4", "/nope/x.mp4", "clip.mp4", "", None):
            self.assertFalse(C.is_network_path(p), p)
        with mock.patch.object(Path, "is_file", side_effect=AssertionError("ネットワークのパスを調べた")):
            self.assertIsNone(C.find_edit_media(r"\\server\share\clip2.mp4"))   # 余白つき素材も探さない


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無いためスキップ")
class TestPackWithFfmpeg(unittest.TestCase):
    """途中の失敗・中止・後から書き換えた置き場所(通しでは起こせない)"""

    @classmethod
    def setUpClass(cls):
        cls.tmpc = tempfile.TemporaryDirectory()
        cls.gaps = Path(cls.tmpc.name) / "gaps.mp4"
        make_video(cls.gaps, 10, audio="gaps")   # 音 0-2 / 無音 2-4 / 音 4-6 / 無音 6-8 / 音 8-10

    @classmethod
    def tearDownClass(cls):
        cls.tmpc.cleanup()

    def setUp(self):
        self.dir = Path(testkit.tempdir(self))
        self.video = self.dir / "clip.mp4"
        self.video.write_bytes(self.gaps.read_bytes())

    T0 = 1_700_000_000_250_000_000   # 元の動画の更新日時(ns。秒の途中 = .25 秒)

    def _fake(self, dst, size, mtime_ns):
        """パックの動画を、中身の違う(0 で埋めた)ファイルにする。写し直したかを中身で見分ける"""
        dst.write_bytes(b"\0" * size)
        os.utime(dst, ns=(mtime_ns, mtime_ns))
        return dst.read_bytes()

    def test_copy_skip_compares_size_and_mtime_seconds(self):
        """前に写した同じ動画(大きさ・更新日時が秒単位で同じ)はコピーを飛ばす。中身は読まない。置き場所の動画を後から書き換えた形は通しでは作れない"""
        os.utime(self.video, ns=(self.T0, self.T0))
        plan = pack.plan_cut(pack.Request(video=self.video))
        out = self.dir / "again"
        pack.build_pack(plan, out, copy_video=True)
        dst = out / "clip.mp4"
        st = dst.stat()
        self.assertEqual((st.st_size, st.st_mtime_ns), (self.video.stat().st_size, self.T0))   # 写したら更新日時も元に合わせる
        fake = self._fake(dst, st.st_size, self.T0 + 600_000_000)        # 同じ秒の中(.85 秒)・同じ大きさ・中身は違う
        res = pack.build_pack(plan, out, copy_video=True, force=True)
        self.assertEqual(dst.read_bytes(), fake)                          # 写していない(中身は読まない = 比べ方の限界)
        self.assertEqual(res["warnings"][-1], C.COPY_SKIPPED.format("clip.mp4"))
        src = self.video.read_bytes()
        for size, mtime in ((len(src) + 1, self.T0), (len(src), self.T0 + 1_000_000_000), (len(src), self.T0 - 300_000_000)):
            self._fake(dst, size, mtime)                                  # 大きさが違う / 次の秒 / 前の秒(.95 秒)
            res = pack.build_pack(plan, out, copy_video=True, force=True)
            self.assertEqual(dst.read_bytes(), src, (size, mtime))        # 写し直した
            self.assertEqual(dst.stat().st_mtime_ns, self.T0)
            self.assertNotIn(C.COPY_SKIPPED.format("clip.mp4"), res["warnings"])
        dst.unlink()
        dst.mkdir()                                                       # 置き場所の名前がフォルダ
        self.assertFalse(C.same_copy(self.video, dst))

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


class TestEditMediaLookup(unittest.TestCase):
    """切り抜きスタジオの余白つき素材(.edit.json)を探す規則のうち、通しでは作れない形(壊れた・外を指す・2 か所にある)。ffmpeg なし"""

    def setUp(self):
        self.d = Path(testkit.tempdir(self))
        self.video = write(self.d / "clip.mp4", "x")
        write(self.d / "clip_edit.mp4", "y")

    def sidecar(self, **kw):
        d = {"schema": C.EDIT_MEDIA_SCHEMA, "media": "clip_edit.mp4", "selectionIn": 10, "handleBefore": 10, "handleAfter": 10}
        d.update(kw)
        write(self.d / "clip.edit.json", json.dumps(d))

    def test_found_in_work_dir(self):
        """スタジオは .edit.json と _edit.mp4 を 作業用/ に書く。作業用/ が先・前の置き方(隣)も読む"""
        w = self.d / C.WORK_DIR
        w.mkdir()
        write(w / "clip_edit.mp4", "z")
        write(w / "clip.edit.json", json.dumps({"schema": C.EDIT_MEDIA_SCHEMA, "media": "clip_edit.mp4", "selectionIn": 7, "handleBefore": 7, "handleAfter": 10}))
        self.sidecar()                                                              # 前の置き方のものもある
        em = C.find_edit_media(self.video)
        self.assertEqual((em["path"], em["selectionIn"]), (w / "clip_edit.mp4", 7.0))
        (w / "clip.edit.json").unlink()
        self.assertEqual(C.find_edit_media(self.video)["path"], self.d / "clip_edit.mp4")

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


class TestRowEdgeRule(unittest.TestCase):
    """行から作るカットの端を広げる窓のちょうど端(pack.widen_row_edges)。本物の音の無音の境目は AAC で 1 コマほど揺れるので、
    窓の端・無音の境目ちょうどは通しでは作れない(ほかの規則は TestPackRun.test_row_edge_run)。30fps: 0.1 秒 = 3 フレーム"""

    def w(self, spans, silence):
        return pack.widen_row_edges(spans, silence, FPS30, 900, pack.ROW_EDGE)   # 後 0.5 秒(15)・前 0.3 秒(9)まで

    def test_window_and_silence_edges(self):
        self.assertEqual(self.w([(100, 200)], [(40, 90), (216, 300)]), [(97, 206)])   # 窓(前 9・後 15)の 1 コマ外の無音 → 決まった余白
        self.assertEqual(self.w([(100, 200)], [(40, 91), (215, 300)]), [(91, 215)])   # ちょうど窓の端
        self.assertEqual(self.w([(100, 200)], [(90, 105), (195, 260)]), [(100, 200)])   # 端がもう無音の中
        self.assertEqual(self.w([(100, 200)], [(90, 100), (200, 260)]), [(100, 200)])   # ちょうど無音の境目


def dataclasses_replace(obj, **kw):
    import dataclasses
    return dataclasses.replace(obj, **kw)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg が無いためスキップ")
class TestPackRun(unittest.TestCase):
    """パックの通し: 見本の動画から、本物の ffmpeg で plan_cut → build_pack(画面の指定から作るときは request_from_spec → output_from_spec も)を通し、
    出来上がったファイル・中身・記録・注意をまとめて確かめる。端の場合・時刻の計算・入力の誤りは見本に混ぜる。
    見本: さくらみこ.mp4(10 秒・30fps・音 2 秒 / 無音 2 秒の繰り返し・名前は日本語。隣に余白つき素材 前後 10 秒)・v60(4 秒・60fps・ずっと音)・
    v2997.mov(10 秒・29.97fps・ドロップの埋め込みタイムコード)・tc.mov(6 秒・30fps・10:00:00:00)・mute(10 秒・音声なし)・v23976(3 秒)・long(60 秒・音声なし)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.d = Path(cls.tmp.name)
        cls.video = d / "さくらみこ.mp4"
        make_video(cls.video, 10, size="320x180", audio="gaps")
        make_video(d / "さくらみこ_edit.mp4", 30, size="320x180")
        make_video(d / "other_edit.mp4", 1, fps="60", size="320x180", audio=None)
        cls.sidecar = write(d / "さくらみこ.edit.json", json.dumps({"schema": C.EDIT_MEDIA_SCHEMA, "media": "さくらみこ_edit.mp4",
                                                                  "selectionIn": 10, "handleBefore": 10, "handleAfter": 10}, ensure_ascii=False))
        cls.srt = write(d / "subs.srt", "1\n00:00:01,000 --> 00:00:02,000\nあ\n\n2\n00:00:05,000 --> 00:00:06,000\nい\n\n"
                                        "3\n00:00:09,000 --> 00:00:09,800\nう\n")
        cls.v60 = ffmpeg_video(d / "v60.mp4", 4, "60")
        cls.v2997 = ffmpeg_video(d / "v2997.mov", 10, "30000/1001", extra=("-timecode", "01:00:00;00"))
        cls.tc = ffmpeg_video(d / "tc.mov", 6, "30", extra=("-timecode", "10:00:00:00"))
        cls.mute = ffmpeg_video(d / "mute.mp4", 10, "30", audio=False)
        cls.v23976 = ffmpeg_video(d / "v23976.mp4", 3, "24000/1001", audio=False)
        cls.long = ffmpeg_video(d / "long.mp4", 60, "30", audio=False)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    MEDIA = "さくらみこ_edit.mp4"
    MINIMAL = ["ResolveにText+スクリプトを登録.bat", "create_resolve_textplus_project.lua", "install_resolve_textplus_script.ps1",
               "textplus-template.drb"]
    SCREEN = dict(plan_file=False, readme_file=False)                               # 画面・API の既定
    SPEAKERS = [{"id": 0, "name": "兎田ぺこら"}, {"id": 1, "name": "話者2"}]

    def spk_doc(self, name, rows, extra=None):
        """rows: [(開始, 終了, 文, 話者の番号 | None)](0 = 兎田ぺこら・1 = 話者2)。extra: {行の番号(0 から): {足す項目}}"""
        doc = transcript_doc([(a, b, t, False) for a, b, t, _ in rows])
        doc["speakers"] = self.SPEAKERS
        for g, (_, _, _, sp) in zip(doc["segments"], rows):
            if sp is not None:
                g["speaker"] = sp
        for i, kv in (extra or {}).items():
            doc["segments"][i].update(kv)
        return write(self.d / (name + ".transcript.json"), json.dumps(doc, ensure_ascii=False))

    def frame_doc(self, name, rows, fps=30):
        """rows: [(開始のコマ, 終了のコマ, 文, 話者の番号 | None)]。秒に直して書く(読むと同じコマに戻る)"""
        return self.spk_doc(name, [(round(a / fps, 4), round(b / fps, 4), t, sp) for a, b, t, sp in rows])

    def plan(self, tr, **kw):
        return pack.plan_cut(pack.Request(video=self.video, transcript=tr, **dict(pack.TRANSCRIPT_ROWS, row_edge=None, **kw)))

    def spec_pack(self, spec, output=None):
        """画面・API(cut2resolve の serve.start_build と同じ): 指定 → request_from_spec → output_from_spec → plan_cut → build_pack。-> (計画, 結果)"""
        req = R.request_from_spec(spec)
        out = R.output_from_spec(output or {}, req.video)
        plan = pack.plan_cut(req)
        spk, _ = R.speaker_colors_for(plan, out)
        res = pack.build_pack(plan, out["dir"], render=out["render"], copy_video=out["copyVideo"], textplus=out["textplus"],
                              textplus_target=out["textplusTarget"], force=out["force"], textplus_wrap=out["textplusWrap"],
                              textplus_color=out["textplusColor"], speaker_colors=spk or None, loudness=out["loudness"], volume=out["volume"],
                              video_tracks=out["videoTracks"], **self.SCREEN)
        return plan, res

    def names(self, out):
        return sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())

    @staticmethod
    def lua(out):
        return (out / "create_resolve_textplus_project.lua").read_text(encoding="utf-8")

    @staticmethod
    def name_warnings(lines):
        return sum("ファイル名に日本語" in w for w in lines)

    def test_textplus_run(self):
        """Text+ パック: 画面・API の既定(最小限・余白つき素材)・コマンドの既定・配信者の色と話者の色・簡易版・映像トラック・重なる字幕"""
        tr = self.spk_doc("plain", [(0.5, 2, "一", 0), (3, 5, "二", 1)])
        self.assertEqual([r["speaker"] for r in C.read_transcript(tr)["rows"]], ["兎田ぺこら", "話者2"])
        plan = self.plan(tr)
        self.assertEqual(plan.keeps, [(15, 60), (90, 150)])
        self.assertEqual(plan.speaker_spans, [(0.5, 2, "兎田ぺこら"), (3, 5, "話者2")])
        self.assertEqual(pack.cue_speakers(plan), ["兎田ぺこら", "話者2"])               # カットで詰めても、元の時刻の話者
        self.assertEqual(self.name_warnings(plan.warnings + pack.describe(plan)), 0)       # 試算には名前の注意を出さない

        # 画面・API の既定: 動画(余白つき素材・直下)・Lua・雛形・登録用の ps1/bat だけ。手順書・cut-plan は書かずに中身を返す。
        # 余白つき素材の媒体情報は Cache に覚える(同じ素材は 1 回・選び直しは毎回読む・素材の更新日時が変われば調べ直す)
        cache = pack.Cache()
        media = self.d / self.MEDIA
        with mock.patch.object(pack.S, "probe", wraps=pack.S.probe) as probe:
            out = self.d / "tp_min"
            res = pack.build_pack(plan, out, textplus=True, cache=cache, **self.SCREEN)
            pack.build_pack(plan, self.d / "tp_min2", textplus=True, cache=cache, **self.SCREEN)
            self.assertEqual(sum(1 for c in probe.call_args_list if Path(c.args[0]) == media), 1)
            orig = self.sidecar.read_text(encoding="utf-8")
            try:
                self.sidecar.write_text(orig.replace('"selectionIn": 10', '"selectionIn": 5'), encoding="utf-8")
                self.assertEqual(pack.build_pack(plan, self.d / "tp_min3", textplus=True, cache=cache, **self.SCREEN)["mediaKeeps"],
                                 [[165, 210], [240, 300]])                                 # 選び直しは毎回読む
            finally:
                self.sidecar.write_text(orig, encoding="utf-8")
            st = media.stat()
            os.utime(media, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
            pack.build_pack(plan, self.d / "tp_min4", textplus=True, cache=cache, **self.SCREEN)
            self.assertEqual(sum(1 for c in probe.call_args_list if Path(c.args[0]) == media), 2)
        self.assertEqual(self.names(out), sorted(self.MINIMAL + [self.MEDIA]))
        self.assertEqual(sorted(p.relative_to(out).as_posix() for _, p in res["files"]), self.names(out))
        self.assertEqual(pack.planned_outputs(plan, out, textplus=True)[1]["video"], out / self.MEDIA)   # 上書き確認の下見も同じ名前
        self.assertEqual(self.name_warnings(res["warnings"]), 0)                           # EDL を入れないので名前の注意も出さない
        self.assertTrue(any("余白つき素材" in w for w in res["warnings"]))
        self.assertEqual((res["plan"]["schema"], res["plan"]["keep_frames"]), ("youtube-tools-cut-plan/v1", [[15, 60], [90, 150]]))
        self.assertEqual(res["mediaKeeps"], [[315, 360], [390, 450]])                      # 余白の分だけ後ろへ
        self.assertEqual((res["editMedia"]["handleBefore"], res["editMedia"]["handleAfter"]), (10.0, 10.0))
        self.assertEqual((out / RTP.TEMPLATE_NAME).read_bytes(), Path(RTP.__file__).with_name(RTP.TEMPLATE_NAME).read_bytes())
        self.assertNotIn("keifont.ttf", [p.name for p in Path(RTP.__file__).parent.iterdir()])   # フォントをリポジトリ・パックに置かない
        raw = (out / "install_resolve_textplus_script.ps1").read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b"\r\r" not in raw)   # ps1 は BOM つき・CRLF(書き方の 1 か所)
        ps1 = raw.decode("utf-8-sig")
        self.assertIn("Join-Path $packageDir '%s'" % self.MEDIA, ps1)                     # 登録するときも直下の動画を探す
        self.assertNotIn("media\\", ps1)
        lua = self.lua(out)
        for bad in ("CreateProject", "SetSetting", "LoadProject", "InsertFusionTitleIntoTimeline", "__C2R_LANES", "cap.trackUp"):
            self.assertNotIn(bad, lua, bad)                                                # プロジェクトを作らない・設定を変えない・重ならなければ段のコードは無い
        for s in ('GetSetting("timelineFrameRate")', "trackIndex=captionTrack, recordFrame=recordFrame",
                  "local media30 = math.abs(DATA.mediaFps - 30) <= 0.01", "if tfps and media30 and math.abs(tfps - 30) > 0.01 then",
                  "(not media30 and math.abs(tfps - T.fps) > 0.01)", "tw ~= T.width or th ~= T.height", "fontOk and styleOk and fpsWarn == nil",
                  '(fpsWarn and "・注意 " .. fpsWarn or "")', "local ratio = tfps / DATA.mediaFps", 'tool:SetInput("Font", fontName)',
                  'tool:SetInput("Style", fontStyle)', "GetFontList", "AddMarker"):
            self.assertIn(s, lua)   # 30fps の素材はプロジェクトの fps が違っても止めずに黄色で警告・大きさの違いは止める(動かす確かめは TestResolveTextPlusLuaRun)
        # 重なりが無いパックの Lua は、段のコードの印を消した雛形と 1 バイトも変わらない(Lua の本体を直したら、下の値も直す)
        bare = RTP.LUA_TEMPLATE
        for mark in RTP.LUA_LANES:
            self.assertEqual(bare.count(mark), 1, mark)
            bare = bare.replace(mark, '')
        self.assertEqual(re.findall(r'__C2R_[A-Z_]+__', bare), ['__C2R_DATA__'])
        self.assertEqual(hashlib.sha256(bare.encode('utf-8')).hexdigest(), 'f0569df532d5e038eb863e37cbbff8dafd7e1d6d2b93853d3e55cc5e5b5a1ff6')
        head, tail = bare.split('__C2R_DATA__')
        self.assertTrue(lua.startswith(head) and lua.endswith(tail))
        ip = RTP.read_script_plan(lua)
        self.assertEqual((ip["target"], ip["mediaFps"], ip["title"], ip["media"]["file"], ip["captionWrap"]),
                         ({"fps": 30, "width": 1080, "height": 1920}, 30, "さくらみこ", self.MEDIA, 8))
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(315, 360), (390, 450)])
        self.assertEqual([(c["startFrame"], c["endFrame"], c["text"]) for c in ip["captions"]], [(0, 45, "一"), (45, 105, "二")])   # タイムラインの位置は同じ
        self.assertEqual(ip["sourceTimeline"], {"startFrame": 0, "endFrame": 900})         # 復旧用は余白込みの全体
        self.assertFalse(any("fill" in c or "outline" in c for c in ip["captions"]))        # 話者の色を渡さなければ、ふだんの見た目
        self.assertNotIn("videoTracks", ip)                                                # 既定 1 は書かない
        self.assertNotIn("outlineN", ip["style"])
        # 字幕の見た目(ユーザーの指定。素材フォルダの Text+ のインスペクタの画像)
        self.assertEqual([list(x) for x in ip["style"]["inputs"]], [list(x) for x in RTP.style_inputs()])
        self.assertEqual((ip["style"]["fonts"][:2], ip["style"]["styles"], ip["style"]["fillN"]), (["けいふぉんと", "Keifont"], ["Regular"], 1))
        inputs = dict((kv[0], kv[1]) for kv in ip["style"]["inputs"])
        for k, v in {"Size": 0.14, "CharacterSpacing": 1.0, "LineSpacing": 1.0, "VerticalTopCenterBottom": 1.0, "HorizontalLeftCenterRight": 0.0,
                     "Enabled1": 1, "ElementShape1": 0, "Red1": 0.0, "Green1": 0.0, "Blue1": 0.0, "Alpha1": 1.0, "Priority1": 8, "Offset1": [0.0, 0.0],
                     "Enabled2": 1, "ElementShape2": 1, "Thickness2": 0.12, "Red2": 1.0, "Green2": 1.0, "Blue2": 1.0, "Priority2": 7,
                     "Offset2": [0.015, -0.02],
                     "Enabled5": 1, "ElementShape5": 1, "Thickness5": 0.18, "Red5": 0.0, "Green5": 0.0, "Blue5": 0.0, "Priority5": 4,
                     "Offset5": [0.0, 0.0]}.items():
            self.assertEqual(inputs.get(k), v, k)
        self.assertNotIn("Thickness1", inputs)                                             # 塗りに太さは無い
        look = next(kv[2] for kv in ip["style"]["inputs"] if kv[0] == "Priority5")          # 名前で入らなかったときの探し方
        self.assertEqual(look, {"names": ["Priority", "優先順位"], "n": 5, "ids": ["PriorityBack5"]})
        readme = res["readme"]
        self.assertEqual(RTP.readme_from_script(lua), readme)                              # 前回のパックの「手順を見る」は Lua から作り直す
        for s in ("Text+ 字幕つき", "動画: " + self.MEDIA, "1080 x 1920", "最短辺をマッチ: 他をクロップ", "けいふぉんと", "このパックには入っていません",
                  "黒い文字"):
            self.assertIn(s, readme)
        for s in ("予備", "黄色い文字"):
            self.assertNotIn(s, readme)

        # コマンドの既定: cut-plan.json・友人へ.txt も書く。.json(計画は Lua に埋め込む)・予備は出さない
        out = self.d / "tp_cli"
        res = pack.build_pack(plan, out, textplus=True)
        self.assertEqual(self.names(out), sorted(self.MINIMAL + [self.MEDIA, "cut-plan.json", RTP.README_NAME]))
        self.assertEqual((out / RTP.README_NAME).read_text(encoding="utf-8-sig"), res["readme"])
        cp = json.loads((out / "cut-plan.json").read_text(encoding="utf-8"))
        self.assertEqual((cp["keep_frames"], cp["editMedia"]["keep_frames"]), ([[15, 60], [90, 150]], [[315, 360], [390, 450]]))   # 読み直す用は元の時刻
        self.assertEqual(AC.read_cut_plan(out / "cut-plan.json")["segments"][0]["start_seconds"], 0.5)

        # 配信者のメンバーカラーの文字 + 話者の色(A-2)+ 既定の見た目の話者のふち。余白つき素材を使わない
        out = self.d / "tp_color"
        res = pack.build_pack(self.plan(tr, edit_media=False), out, textplus=True, textplus_color={"hex": "#FF8FDF", "who": "さくらみこ"},
                              speaker_colors={"兎田ぺこら": "#7EC2FE"}, speaker_outlines={"話者2": "#00FF00"}, **self.SCREEN)
        self.assertEqual((res["editMedia"], self.names(out)), (None, sorted(self.MINIMAL + ["さくらみこ.mp4"])))
        lua = self.lua(out)
        ip = RTP.read_script_plan(lua)
        self.assertEqual([(c["sourceStartFrame"], c["sourceEndFrame"]) for c in ip["cuts"]], [(15, 60), (90, 150)])
        colored = dict((kv[0], kv[1]) for kv in ip["style"]["inputs"])
        self.assertEqual([colored[k] for k in ("Red1", "Green1", "Blue1", "Alpha1")], [1.0, 0.5608, 0.8745, 1.0])   # 文字(塗り)だけメンバーカラー
        self.assertEqual([colored[k] for k in ("Red2", "Red5", "Thickness2", "Thickness5")], [1.0, 0.0, 0.12, 0.18])  # ふちは同じ
        self.assertEqual(ip["style"]["name"], "けいふぉんと・さくらみこの色の文字(#FF8FDF)・白いふち・黒いふち")
        self.assertEqual(ip["style"]["outlineN"], 2)                                        # 字幕ごとのふちを入れる先(既定の見た目でも)
        self.assertIn("さくらみこの色の文字", res["readme"])
        self.assertEqual(RTP.readme_from_script(lua), res["readme"])
        self.assertEqual(ip["captions"][0].get("fill"), [0.4941, 0.7608, 0.9961, 1.0])       # 話者の色は、その話者の字幕だけ
        self.assertNotIn("fill", ip["captions"][1])                                        # 色の決まらない話者は、ふだんの見た目のまま
        self.assertEqual((ip["captions"][0].get("outline"), ip["captions"][1]["outline"]), (None, [0.0, 1.0, 0.0, 1.0]))
        self.assertIn("cap.fill", lua)

        # 簡易版(lite): MS ゴシック・大きさ 0.08・要素 5 は切る。話者ごとの文字とふちの色・配信者の色の文字
        out = self.d / "tp_lite"
        res = pack.build_pack(plan, out, textplus=True, textplus_style="lite", textplus_color={"hex": "#FF0000", "who": ""},
                              speaker_colors={"兎田ぺこら": "#FF0000", "話者2": "#00FF00"}, speaker_outlines={"話者2": "#0000FF"}, **self.SCREEN)
        lua = self.lua(out)
        ip = RTP.read_script_plan(lua)
        lite = [kv[:2] for kv in ip["style"]["inputs"]]
        d = dict((k, v) for k, v in lite)
        self.assertEqual((ip["style"]["fonts"][0], d["Size"], d["Enabled5"]), ("MS Gothic", 0.08, 0))
        self.assertEqual((d["Enabled1"], d["ElementShape1"], d["Enabled2"], d["ElementShape2"], d["Thickness2"]), (1, 0, 1, 1, 0.15))
        self.assertEqual((d["Red1"], d["Green1"], d["Blue1"]), (1.0, 0.0, 0.0))             # 簡易版にも配信者の色
        self.assertEqual([k for k, _ in lite if k.endswith("5")], ["Enabled5"])              # 要素 5 は Enabled だけ
        self.assertEqual((ip["style"]["fillN"], ip["style"]["outlineN"]), (1, 2))
        self.assertEqual(ip["captions"][0]["fill"], [1.0, 0.0, 0.0, 1.0])
        self.assertNotIn("outline", ip["captions"][0])                                     # 兎田ぺこら のふちは決まらない = 見た目のまま
        self.assertEqual(ip["captions"][1]["outline"], [0.0, 0.0, 1.0, 1.0])
        self.assertIn("cap.outline", lua)
        self.assertIn("簡易版", res["readme"])
        out = self.d / "tp_lite_outline"                                                   # ふちだけ渡しても名前を引ける
        pack.build_pack(plan, out, textplus=True, textplus_style="lite", speaker_outlines={"兎田ぺこら": "#112233"}, **self.SCREEN)
        ip = RTP.read_script_plan(self.lua(out))
        self.assertIn("outline", ip["captions"][0])
        self.assertFalse(any("fill" in c for c in ip["captions"]))
        out = self.d / "tp_tracks"                                                         # 映像トラックの数(簡易版で友人が選ぶ)
        res = pack.build_pack(plan, out, textplus=True, textplus_style="lite", video_tracks=5, **self.SCREEN)
        self.assertEqual(RTP.read_script_plan(self.lua(out))["videoTracks"], 5)
        self.assertIn("V1〜V5 同じ映像(重ねて加工する用。V2 から上は映像だけ)・V6 Text+ 字幕(一番上)", res["readme"])
        self.assertIn("V6 の Text+ を選び", RTP.readme_from_script(self.lua(out)))

        # 重なる字幕の段(notes:plan/done/line-b-overlap.md の 6-2 の 4): 段に分けても、字幕ごとの色(話者)は同じ字幕に付く。話者は行から直接たどる
        # (字幕の真ん中の時刻で探すと、重なる行では別の人の行に当たる)。二 は 一 に 1 秒重なる → 2 段目。三 は 二 と 2 コマ重なるが 1 段目が空いている
        over = self.plan(self.spk_doc("over", [(0.5, 2, "一", 0), (1.0, 2.5, "二", 1), (2.45, 3.5, "三", 0), (4, 5, "四", None)]))
        self.assertEqual(pack.cue_speakers(over), ["兎田ぺこら", "話者2", "兎田ぺこら", None])
        self.assertEqual(pack.cue_order(over), [0, 1, 0, 2])
        sm = pack.summary(over)
        self.assertEqual((sm["captionLanes"], sm["captionsStacked"], sm["captionsTrimmed"], sm["noSubRows"], sm["subtitles"]["out"]), (2, 1, 0, 0, 4))
        self.assertIn("重なる字幕(Text+): 2 段・上の段へ分けた字幕 1件・終わりを切った字幕 0件", sm["text"])
        out = self.d / "tp_over"
        res = pack.build_pack(over, out, textplus=True, speaker_colors={"兎田ぺこら": "#FF0000", "話者2": "#0000FF"}, **self.SCREEN)
        lua = self.lua(out)
        ip = RTP.read_script_plan(lua)
        caps = ip["captions"]
        self.assertEqual((ip["captionLanes"], [c["text"] for c in caps]), (2, ["一", "二", "三", "四"]))
        self.assertEqual([(c.get("trackUp"), c.get("dy")) for c in caps], [(None, None), (1, RTP.LANE_STEP_Y), (None, None), (None, None)])
        self.assertEqual([c.get("fill") for c in caps], [[1.0, 0.0, 0.0, 1.0], [0.0, 0.0, 1.0, 1.0], [1.0, 0.0, 0.0, 1.0], None])
        self.assertNotIn("__C2R_LANES", lua)
        for s in ("trackIndex=captionTrack + (cap.trackUp or 0), recordFrame=recordFrame", "for _ = 2, captionLanes do",
                  'trySet(tool, "Center", {cx, cy + cap.dy})', "fpsWarn == nil and laneMiss == 0)", '"・重なる字幕 V" .. captionTrack'):
            self.assertIn(s, lua)
        self.assertEqual(RTP.readme_from_script(lua), res["readme"])
        for s in ("V1 映像・A1 音声・V2〜V3 Text+ 字幕。同時にしゃべっている所の字幕は、重ならないように上のトラック(V3)に置き",
                  "V2〜V3 の Text+ を選び", "重なる字幕(V3)の高さを直す"):
            self.assertIn(s, res["readme"])
        out = self.d / "over_edl"                                                          # EDL が本体のパック(Text+ でない)の SRT は段に分けない
        pack.build_pack(over, out, **self.SCREEN)
        cues = S.parse_subs((out / "さくらみこ_cut.srt").read_text(encoding="utf-8-sig"))
        self.assertEqual(cues[1][2], "二")
        self.assertGreater(cues[0][1], cues[1][0])                                         # 一 の終わり > 二 の始まり(重なったまま)

        # 不正な見た目・映像トラックの数ではフォルダも作らない
        with self.assertRaises(C.ToolError):
            pack.build_pack(plan, self.d / "bad", textplus=True, textplus_style="nope", **self.SCREEN)
        for bad in (0, 6, "x", True):
            with self.assertRaises(C.ToolError):
                pack.build_pack(plan, self.d / "bad_tracks", textplus=True, video_tracks=bad, **self.SCREEN)
        self.assertFalse((self.d / "bad").exists() or (self.d / "bad_tracks").exists())

    # 重なる字幕の段の見本(30fps のコマ)。組ごとに時刻を詰めて 1 つの区間に並べる(組の境目は接するだけ = 前の組の段は空く)
    LANES = [
        [(0, 38, "a1", 0), (30, 60, "a2", 1)],                                   # はみ出し 8 コマ(0.3 秒未満)→ 同じ段で前を切る
        [(60, 99, "b1", None), (90, 120, "b2", None)],                           # 9 コマ = 0.3 秒 → 上の段
        [(120, 270, "長い", None), (180, 186, "うん", None)],                      # 長い字幕の途中の相づち: 前のはみ出し(84)で数える = 切らない
        [(270, 370, "d1", None), (280, 320, "d2", None), (330, 390, "d3", None), (371, 400, "d4", None)],   # 置いた字幕は動かさない・空いている下の段
        [(400, 490, "e1", None), (410, 490, "e2", None), (420, 490, "e3", None), (430, 490, "e4", None)],   # 4 つ目は 3 段目に入れ、3 段目の重なりは切る
        [(490, 495, "f1", None), (490, 550, "f2", None)],                        # 同じコマに始まる: 切ると前が 0 コマ → 上の段
        [(550, 551, "g5", None), (550, 640, "g1", None), (550, 640, "g2", None), (550, 640, "g3", None), (550, 640, "g4", None)],   # 5 つが同時
        [(640, 700, "h1", 1), (640, 700, "h2", 0)],                              # 同時に始まる字幕は話者の並び順の小さい方を下へ
    ]
    WRAP = [("今日はいい天気ですね散歩に行こう", "今日はいい天気ですね\n散歩に行こう"), ("これマジでヤバくないですか", "これマジで\nヤバくないですか"),
            ("ホロライブの新しいメンバーが来た", "ホロライブの新しい\nメンバーが来た"),                  # 送りがなの前では切らない
            ("マインクラフトでエンダードラゴンをたおす", "マインクラフトで\nエンダードラゴンをたおす"),     # カタカナの語の途中で切らない
            ("えっと、ちょっとまってください!", "えっと、ちょっと\nまってください!"), ("あいうえおかきくけこ", "あいうえおかきくけこ"),   # 10 ≦ 8 + 2
            ("今日はいい天気ですね散歩\nに行こう", "今日はいい天気ですね散歩\nに行こう")]               # もう改行がある文はそのまま
    KEEP_CHARS = ["ABCDEFGHIJKLMNOPQRSTU", "、あいうえおかきくけこさしすせ", "ーーーーーーーーーーーーーーー", "あっっっっっっっっっっっっっっ"]

    def test_captions_run(self):
        """字幕の通し(画面の指定から): 重なる字幕の段(30fps・60fps・29.97fps)・話者の色と並び順・映像トラック 3・Text+ の改行(縦 8・横 14・0 = しない)・
        置き先の指定と不正な指定・60fps の素材を 30fps の置き先へ(作り直さない)・1 コマの隙間をつなぐ"""
        rows = [r for g in self.LANES for r in g]
        wrap0 = 700
        rows += [(wrap0 + 30 * i, wrap0 + 30 * (i + 1), t, None) for i, t in enumerate([a for a, _ in self.WRAP] + self.KEEP_CHARS)]
        tr = self.frame_doc("lanes", rows)
        spec = {"video": str(self.long), "transcript": str(tr), "preset": "transcript-rows"}
        styles = {"兎田ぺこら": {"color": "#FF0000"}, "話者2": {"color": "#0000FF"}}
        out = self.d / "lanes"
        plan, res = self.spec_pack(spec, {"textplus": True, "dir": str(out), "videoTracks": 3, "speakerStyles": styles})
        self.assertEqual(plan.keeps, [(0, wrap0 + 30 * (len(self.WRAP) + len(self.KEEP_CHARS)))])   # 重なる・接する行は 1 つの区間
        ip = RTP.read_script_plan(self.lua(out))
        caps = ip["captions"]
        n = len(self.LANES and [r for g in self.LANES for r in g])
        lane = [1 + c.get("trackUp", 0) for c in caps[:n]]
        got = [(c["startFrame"], c["endFrame"]) for c in caps[:n]]
        self.assertEqual([c["text"] for c in caps[:n]], [r[2] for r in rows[:n]])               # 字幕の数・並びは変えない
        self.assertEqual((lane[0:2], got[0:2]), ([1, 1], [(0, 30), (30, 60)]))                   # a: 前を 30 で切る
        self.assertEqual((lane[2:4], got[2:4]), ([1, 2], [(60, 99), (90, 120)]))                 # b: 切らずに上
        self.assertEqual((lane[4:6], got[4:6]), ([1, 2], [(120, 270), (180, 186)]))              # 長い字幕は切らない
        self.assertEqual(lane[6:10], [1, 2, 2, 1])                                              # d3 は 1 段目が空くまで待たず 2 段目・d4 は空いた 1 段目
        self.assertEqual((lane[10:14], got[12]), ([1, 2, 3, 3], (420, 430)))                     # e3 を e4 の始まりで切る
        self.assertEqual((lane[14:16], got[14:16]), ([1, 2], [(490, 495), (490, 550)]))          # f1 は 0 コマにしない
        g = got[16:21]
        self.assertTrue(all(b > a for a, b in g) and max(lane[16:21]) == 3, (g, lane[16:21]))   # 同時に 5 つ: 消さない・3 段まで
        self.assertEqual(lane[21:23], [2, 1])                                                   # h2(兎田ぺこら = 並び 0)が下
        self.assertEqual([c.get("fill") for c in (caps[0], caps[1], caps[21], caps[22])],
                         [[1.0, 0.0, 0.0, 1.0], [0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0], [1.0, 0.0, 0.0, 1.0]])   # 切った・段に分けたあとも色は同じ字幕に
        self.assertEqual([c.get("dy") for c in caps[10:14]], [None, 0.2, 0.4, 0.4])
        self.assertEqual((ip["captionLanes"], ip["videoTracks"]), (3, 3))
        self.assertIn('V1〜V3 同じ映像(重ねて加工する用。V2 から上は映像だけ)・V4〜V6 Text+ 字幕(一番上)・A1 音声。', res["readme"])
        self.assertIn('上のトラック(V5〜V6)', res["readme"])
        sm = pack.summary(plan)
        self.assertEqual((sm["captionLanes"], sm["captionsTrimmed"]), (3, sum(1 for a, b in zip(got, [r[:2] for r in rows[:n]]) if a != b)))
        # 字幕の位置: 区間の頭からのコマ(区間は 1 つ)
        self.assertEqual({c["segment"] for c in caps}, {1})
        self.assertEqual([(c["offsetStart"], c["offsetEnd"]) for c in caps[4:6]], [(120, 270), (180, 186)])
        # 改行(縦の置き先は 1 段 8 文字前後)。Lua にも改行のまま入る
        self.assertEqual(ip["captionWrap"], 8)
        wrapped = [c["text"] for c in caps[n:]]
        self.assertEqual(wrapped[:len(self.WRAP)], [b for _, b in self.WRAP])
        self.assertEqual(wrapped[len(self.WRAP)].count("\n"), 2)                                # 長ければ 3 段
        self.assertEqual([t.replace("\n", "") for t in wrapped[len(self.WRAP):]], self.KEEP_CHARS)   # 文字は落とさない
        # 横の置き先(60fps・1920x1080)は 1 段 14 文字前後(16 ≦ 14 + 2 は 1 段)・0 = 改行しない
        out = self.d / "lanes_h"
        self.spec_pack(spec, {"textplus": True, "dir": str(out), "textplusFps": "60", "textplusSize": "1920x1080"})
        ip = RTP.read_script_plan(self.lua(out))
        self.assertEqual((ip["target"], ip["captionWrap"], ip["captions"][n]["text"]), ({"fps": 60, "width": 1920, "height": 1080}, 14, self.WRAP[0][0]))
        out = self.d / "lanes_0"
        self.spec_pack(spec, {"textplus": True, "dir": str(out), "textplusWrap": 0})
        ip = RTP.read_script_plan(self.lua(out))
        self.assertEqual([c["text"] for c in ip["captions"][n:n + 2]], [self.WRAP[0][0], self.WRAP[1][0]])
        for bad in ({"textplusFps": "29"}, {"textplusFps": "abc"}, {"textplusSize": "1080"}, {"textplusSize": "1080*1920"},
                    {"textplusSize": "1081x1920"}, {"textplusSize": "8x8"}):
            with self.subTest(bad=bad), self.assertRaises(ApiError) as cm:
                self.spec_pack(spec, dict(bad, textplus=True, dir=str(self.d / "x")))
            self.assertEqual(cm.exception.code, "bad_textplus")
        self.assertFalse((self.d / "x").exists())                                              # 不正な指定ではファイルを作らない

        # 60fps の素材: 60fps のコマで段を数える(0.3 秒 = 18 コマ)。置き先は 30fps の縦のまま、動画は作り直さずに直下へ写す
        tr = self.frame_doc("lanes60", [(0, 77, "六1", None), (60, 120, "六2", None), (120, 198, "六3", None), (180, 240, "六4", None)], 60)
        out = self.d / "v60_pack"
        plan, res = self.spec_pack({"video": str(self.v60), "transcript": str(tr), "preset": "transcript-rows"}, {"textplus": True, "dir": str(out)})
        ip = RTP.read_script_plan(self.lua(out))
        self.assertEqual([1 + c.get("trackUp", 0) for c in ip["captions"]], [1, 1, 1, 2])        # 17 コマは切る・18 コマは上の段
        self.assertEqual((ip["target"], ip["mediaFps"], ip["fps"]), ({"fps": 30, "width": 1080, "height": 1920}, 60, "60/1"))
        self.assertEqual((out / "v60.mp4").read_bytes(), self.v60.read_bytes())                   # 作り直さない
        self.assertNotIn(str(self.d), json.dumps(ip, ensure_ascii=False))                        # 計画にこの PC の絶対パスを入れない
        self.assertNotIn("textplus-import.json", self.names(out))
        # 29.97fps も 9 コマ(0.3 秒未満の 8 コマは切る)
        tr = self.frame_doc("lanes2997", [(0, 38, "九1", None), (30, 60, "九2", None)], 30000 / 1001)
        out = self.d / "v2997_pack"
        self.spec_pack({"video": str(self.v2997), "transcript": str(tr), "preset": "transcript-rows"}, {"textplus": True, "dir": str(out)})
        ip = RTP.read_script_plan(self.lua(out))
        self.assertEqual([(c["startFrame"], c["endFrame"], c.get("trackUp")) for c in ip["captions"]], [(0, 30, None), (30, 60, None)])

        # 1 コマの隙間はつなぐ(行の規則 join_frames 1)・0 ならつながない・不正な値は断る
        tr = write(self.d / "gap.transcript.json", json.dumps(transcript_doc([(1, 2, "a", False), (2.034, 3, "b", False)])))
        req = pack.Request(video=self.video, transcript=tr, **dict(pack.TRANSCRIPT_ROWS, row_edge=None))
        self.assertEqual(pack.plan_cut(req).keeps, [(30, 90)])
        self.assertEqual(pack.plan_cut(dataclasses_replace(req, join_frames=0)).keeps, [(30, 60), (61, 90)])
        for bad in (-1, 1.5, True, 1001):
            with self.subTest(bad=bad), self.assertRaises(pack.ToolError):
                pack.plan_cut(dataclasses_replace(req, join_frames=bad))

    def test_edl_run(self):
        """EDL が本体のパック(Text+ でない): 無音で自動 + SRT + 粗編集 + 動画の同梱 + 音量をそろえる・作り直し・文字起こしの行・時刻リスト・余白つき素材"""
        before = self.video.read_bytes()
        # 無音で自動 + SRT。進み具合が来る・無音は Cache に覚える(2 回目は調べない)
        seen, cache = [], pack.Cache()
        req = pack.Request(video=self.video, sub=self.srt, silence=True, edit_media=False)
        plan = pack.plan_cut(req, task=C.Task(lambda f, m: seen.append((f, m))), cache=cache)
        self.assertTrue(any(isinstance(f, float) for f, _ in seen), seen)
        self.assertTrue(cache.silence_cached(self.video, plan.meta["fps"], plan.meta["total"], -35.0, 0.6, 0.15))
        with mock.patch.object(C, "detect_silence", side_effect=AssertionError("キャッシュを使うはず")):
            self.assertEqual(pack.plan_cut(req, cache=cache).keeps, plan.keeps)
        sil = plan.drops["silence"]                                                        # 無音は 2-4s と 6-8s。前後 0.15s を残す(±3 フレーム)
        self.assertEqual(len(sil), 2, sil)
        for (s, e), (es, ee) in zip(sil, [(64, 116), (184, 236)]):
            self.assertLessEqual(abs(s - es), 3)
            self.assertLessEqual(abs(e - ee), 3)
        self.assertFalse(any("切れる所が見つかりませんでした" in w for w in plan.warnings))
        sm = pack.summary(plan)
        self.assertEqual((sm["fps"], sm["total"], sm["subtitles"]["source"]), ([30, 1], 300, "srt"))
        self.assertIn("silence", sm["drops"])
        self.assertAlmostEqual(sm["keptSec"] + sm["removedSec"], 10.0, places=3)
        json.dumps(sm)                                                                    # そのまま JSON にできる
        out = self.d / "edl_a"
        res = pack.build_pack(plan, out, render=True, copy_video=True, loudness=-14.0)
        self.assertEqual(self.names(out), sorted(["さくらみこ.edl", "さくらみこ_cut.srt", "さくらみこ_roughcut.mp4", "さくらみこ.mp4",
                                                  "cut-plan.json", "友人へ.txt"]))
        self.assertEqual(self.name_warnings(res["warnings"]), 1)                           # EDL はファイル名で元の動画と結び付く
        raw = (out / "さくらみこ.edl").read_bytes()
        self.assertTrue(raw.startswith(b"TITLE: \xe3\x81\x95") and b"\r\nFCM: NON-DROP FRAME\r\n" in raw)   # EDL は CRLF・BOM なし
        ev = parse_edl(raw.decode("utf-8"))
        self.assertEqual(len(ev), 3)                                                       # 音のある 3 か所
        self.assertEqual([e[0] for e in ev], ["001", "002", "003"])
        rec = 108000
        for num, reel, track, si, so, ri, ro, com in ev:
            self.assertEqual(track, "AA/V")
            self.assertEqual(tc2f(ri, 30), rec)                                            # 記録側は隙間なく連続・長さは元と同じ
            self.assertEqual(tc2f(ro, 30) - tc2f(ri, 30), tc2f(so, 30) - tc2f(si, 30))
            self.assertIn("FROM CLIP NAME: さくらみこ.mp4", com)
            rec = tc2f(ro, 30)
        rough = S.probe(out / "さくらみこ_roughcut.mp4")
        self.assertLessEqual(abs(rough["total"] - (tc2f(ev[-1][6], 30) - tc2f(ev[0][5], 30))), 3)   # 粗編集の長さ = EDL の長さ
        self.assertIsNotNone(rough["audio"])
        self.assertEqual([c[2] for c in S.parse_subs((out / "さくらみこ_cut.srt").read_text(encoding="utf-8"))], ["あ", "い", "う"])   # 字幕は全て音のある区間
        self.assertTrue((out / "友人へ.txt").read_text(encoding="utf-8-sig").startswith("DaVinci Resolve"))
        lo = res["loudness"]
        spans = [(a / 30, b / 30) for a, b in plan.keeps]
        self.assertEqual(lo["target"], -14.0)
        self.assertAlmostEqual(lo["measured"], C.measure_loudness(self.video, spans)[0], delta=0.2)   # 測るのは残す区間だけ
        want = lo["measured"] + lo["gainDb"]
        self.assertAlmostEqual(C.measure_loudness(out / "さくらみこ.mp4", spans)[0], want, delta=1.0)  # 同梱の動画は その分だけ変わった
        self.assertAlmostEqual(C.measure_loudness(out / "さくらみこ_roughcut.mp4")[0], want, delta=1.0)  # 粗編集の動画にも同じ量
        self.assertEqual(self.video.read_bytes(), before)                                 # 元の動画は書き換えない
        rec, dst = res["videoCopy"], (out / "さくらみこ.mp4").stat()
        src = self.video.stat()
        self.assertEqual((rec["v"], rec["loudness"], rec["gainDb"]), (C.GAIN_COPY_V, -14.0, round(lo["gainDb"], 2)))
        self.assertEqual(rec["source"], {"name": "さくらみこ.mp4", "size": src.st_size, "mtime": src.st_mtime_ns // 10 ** 9})
        self.assertEqual(rec["output"], {"name": "さくらみこ.mp4", "size": dst.st_size, "mtime": dst.st_mtime_ns // 10 ** 9})
        self.assertIn("volume=%.2fdB" % lo["gainDb"], rec["ffmpeg"])
        self.assertNotIn("volume", rec)
        # 同じフォルダにもう一度: force が無ければ断り、書いてあるファイルを知らせる
        with self.assertRaises(C.OutputExists) as cm:
            pack.build_pack(plan, out)
        self.assertIsInstance(cm.exception, C.ToolError)
        self.assertEqual(sorted(p.name for p in cm.exception.existing), ["cut-plan.json", "さくらみこ.edl", "さくらみこ_cut.srt", "友人へ.txt"])
        # 作り直す(serve.py は作業データの packs/ の記録を prev_copy に渡す。JSON を通した形): 前の記録と条件・置き場所の動画が
        # 同じなら、音量をかけた写しは作り直さない(比べ方の端は TestGainCopyRecord)。LUFS は毎回測る(カットが変わると量が変わる)

        def again(prev, **kw):
            with mock.patch.object(C, "copy_video_gain", wraps=C.copy_video_gain) as cg, \
                    mock.patch.object(C, "measure_loudness", wraps=C.measure_loudness) as ml:
                r = pack.build_pack(plan, out, copy_video=True, force=True, prev_copy=prev, **kw)
            return r, cg.called, ml.called
        mtime = (out / "さくらみこ.mp4").stat().st_mtime_ns
        rec = json.loads(json.dumps(rec))
        r, regain, measured = again(rec, loudness=-14.0)
        self.assertEqual((regain, measured, (out / "さくらみこ.mp4").stat().st_mtime_ns), (False, True, mtime))
        self.assertEqual(r["warnings"][-1], C.GAIN_COPY_SKIPPED.format("さくらみこ.mp4", r["loudness"]["gainDb"]))   # 注意に 1 行(ほかの注意の後ろ)
        self.assertIn("コピーを飛ばしました", r["warnings"][-1])                          # serve.py が info に分ける言葉
        self.assertTrue(any("さくらみこ_roughcut.mp4" in w for w in r["warnings"]))         # 今回書かない前の粗編集は消さずに知らせる
        self.assertEqual((r["videoCopy"], dict(r["files"])["video"]), (rec, out / "さくらみこ.mp4"))   # 次のパックの記録にも同じ条件を残す
        gain = C.loudness_mod().pct_to_db(50)
        r, regain, measured = again(rec, volume=50)                                       # 量が違う → 作り直す(% は測らない)
        self.assertEqual((regain, measured, r["loudness"]), (True, False, {"volume": 50, "gainDb": gain}))
        self.assertFalse(any("コピーを飛ばしました" in w for w in r["warnings"]))
        rec = json.loads(json.dumps(r["videoCopy"]))
        self.assertEqual((rec["volume"], rec["gainDb"]), (50, round(gain, 2)))
        self.assertIn("volume=%.2fdB" % gain, rec["ffmpeg"])
        self.assertEqual(rec["output"]["mtime"], (out / "さくらみこ.mp4").stat().st_mtime_ns // 10 ** 9)
        self.assertIs(again(rec, volume=50)[1], False)                                    # 作り直した後の記録となら、次は飛ばす
        r, regain, _ = again(rec)                                                         # 音量を変えない(100%)に戻したら普通のコピー
        self.assertEqual((regain, r["videoCopy"], (out / "さくらみこ.mp4").read_bytes()), (False, None, before))
        self.assertEqual(self.names(out), sorted(["さくらみこ.edl", "さくらみこ_cut.srt", "さくらみこ_roughcut.mp4", "さくらみこ.mp4",
                                                  "cut-plan.json", "友人へ.txt"]))      # 記録・一時ファイルはフォルダに置かない

        # 文字起こしの行: カット済の行を削り、字幕は残す行から。SRT もあれば SRT の字幕(注意を出す)。動画を入れないパックは余白つき素材を使わない
        tr = write(self.d / "edl.transcript.json", json.dumps(transcript_doc(
            [(0.5, 1.5, "こんにちは", False), (4.0, 5.0, "カット", True), (8.5, 9.5, "またね", False), (6.0, 7.0, "", False), (5.0, 4.0, "逆", False)],
            {"path": str(self.video), "name": self.video.name}), ensure_ascii=False))
        plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr))
        self.assertEqual((plan.keeps, plan.sub_source), ([(0, 120), (150, 300)], "transcript"))
        self.assertEqual([(a, b, t) for a, b, t in plan.cues_out], [(15, 45, "こんにちは"), (225, 255, "またね")])   # 8.5 秒 → カット後 7.5 秒
        self.assertTrue(any("1 行" in w or "1行" in w for w in plan.warnings), plan.warnings)   # 読めない行(終わりが先)を知らせる
        sm = pack.summary(plan)
        self.assertEqual((sm["subtitles"]["source"], len(sm["transcriptRows"])), ("transcript", 4))
        self.assertIn("cutRows", sm["drops"])
        self.assertEqual(pack.plan_cut(pack.Request(video=self.video, transcript=tr, drop_cut_rows=False)).keeps, [(0, 300)])
        rows_plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr, base="rows"))   # 行だけを残す: 行の間を削る・空の行は残さない
        self.assertEqual((rows_plan.keeps, rows_plan.handles), ([(15, 45), (255, 285)], 0.0))
        self.assertEqual(pack.plan_cut(pack.Request(video=self.video, transcript=tr, base="rows", handles=0.5)).keeps, [(0, 60), (240, 300)])
        for text, msg in ('{"schema": "youtube-tools-transcript/v9", "segments": []}', "未対応の版"), \
                ('{"schema": "youtube-tools-cut-plan/v1", "segments": []}', "ではありません"), ("{broken", "JSON"):
            with self.subTest(text=text), self.assertRaisesRegex(C.ToolError, msg):
                pack.plan_cut(pack.Request(video=self.video, transcript=write(self.d / "bad.transcript.json", text)))
        both = pack.plan_cut(pack.Request(video=self.video, transcript=tr, sub=self.srt))
        self.assertEqual(both.sub_source, "srt")
        self.assertTrue(any("SRT のほう" in w for w in both.warnings))
        out = self.d / "edl_b"
        res = pack.build_pack(plan, out)
        self.assertEqual(self.names(out), sorted(["さくらみこ.edl", "さくらみこ_cut.srt", "cut-plan.json", "友人へ.txt"]))
        self.assertIsNone(res["editMedia"])
        ev = parse_edl((out / "さくらみこ.edl").read_text(encoding="utf-8"))
        self.assertEqual([(e[3], e[4]) for e in ev], [("00:00:00:00", "00:00:04:00"), ("00:00:05:00", "00:00:10:00")])
        readme = (out / "友人へ.txt").read_text(encoding="utf-8-sig")
        self.assertIn("cut-plan.json", readme)
        self.assertNotIn("fcpxml", readme)
        self.assertEqual(len(AC.read_cut_plan(out / "cut-plan.json")["segments"]), 2)       # 読み直せる
        # 同じ計画で動画を入れる: 余白つき素材。EDL・SRT の名前は元の切り抜き
        files = dict(pack.build_pack(plan, self.d / "edl_media", copy_video=True)["files"])
        self.assertEqual((files["edl"].name, files["srt"].name, files["video"].name), ("さくらみこ.edl", "さくらみこ_cut.srt", self.MEDIA))
        ev = parse_edl(files["edl"].read_text(encoding="utf-8"))
        self.assertEqual([(tc2f(e[3], 30), tc2f(e[4], 30)) for e in ev], [(300, 420), (450, 600)])
        self.assertIn("FROM CLIP NAME: " + self.MEDIA, ev[0][7])

        # 時刻リスト + SRT・動画を入れる・画面の既定(手順書・cut-plan は書かない)。音量を変えなければ、そのまま写す
        plan = pack.plan_cut(pack.Request(video=self.video, sub=self.srt, base="list", keep_pairs=[(0, 3), (5, 8)], edit_media=False))
        out = self.d / "edl_c"
        res = pack.build_pack(plan, out, copy_video=True, **self.SCREEN)
        self.assertEqual(self.names(out), ["さくらみこ.edl", "さくらみこ.mp4", "さくらみこ_cut.srt"])
        self.assertEqual(((out / "さくらみこ.mp4").read_bytes(), res["loudness"], res["videoCopy"]), (before, None, None))
        self.assertNotIn(C.COPY_SKIPPED.format("さくらみこ.mp4"), res["warnings"])
        self.assertIn("DaVinci Resolve", res["readme"])
        self.assertIn("さくらみこ.edl", res["readme"])
        ev = parse_edl((out / "さくらみこ.edl").read_text(encoding="utf-8"))
        self.assertEqual([(e[3], e[4]) for e in ev], [("00:00:00:00", "00:00:03:00"), ("00:00:05:00", "00:00:08:00")])
        self.assertEqual([(e[5], e[6]) for e in ev], [("01:00:00:00", "01:00:03:00"), ("01:00:03:00", "01:00:06:00")])
        cues = S.parse_subs((out / "さくらみこ_cut.srt").read_text(encoding="utf-8"))
        self.assertEqual([(c[0], c[1], c[2]) for c in cues], [(1000, 2000, "あ"), (3000, 4000, "い")])   # い(5-6s)はカット後 3-4s・う は消える
        res = pack.build_pack(plan, out, copy_video=True, force=True, **self.SCREEN)       # 同じ動画(大きさ・更新日時が同じ)は写さない
        self.assertEqual((res["warnings"][-1], dict(res["files"])["video"]), (C.COPY_SKIPPED.format("さくらみこ.mp4"), out / "さくらみこ.mp4"))
        self.assertEqual(self.names(out), ["さくらみこ.edl", "さくらみこ.mp4", "さくらみこ_cut.srt"])
        res = pack.build_pack(plan, out, copy_video=True, force=True, volume=50, **self.SCREEN)   # 音量をかけるときは同じ動画が置いてあっても作り直す
        self.assertEqual(res["loudness"]["volume"], 50)
        self.assertNotEqual((out / "さくらみこ.mp4").read_bytes(), before)
        self.assertNotIn(C.COPY_SKIPPED.format("さくらみこ.mp4"), res["warnings"])

        # 音声の無い動画: 無音で削れない(断る)・EDL は映像だけ(V)・粗編集も映像だけ
        with self.assertRaises(C.ToolError):
            pack.plan_cut(pack.Request(video=self.mute, silence=True))
        plan = pack.plan_cut(pack.Request(video=self.mute, base="list", keep_pairs=[(0, 1), (2, 3)]))
        out = self.d / "mute_pack"
        pack.build_pack(plan, out, render=True)
        self.assertEqual({e[2] for e in parse_edl((out / "mute.edl").read_text(encoding="utf-8"))}, {"V"})
        rough = S.probe(out / "mute_roughcut.mp4")
        self.assertLessEqual(abs(rough["total"] - 60), 2)
        self.assertIsNone(rough["audio"])
        self.assertIn("字幕は付いていません", (out / "友人へ.txt").read_text(encoding="utf-8-sig"))
        self.assertFalse((out / "mute_cut.srt").exists())
        # ずっと音のある動画を無音で自動: 削れる所が無い → 注意(ほかの決め方を勧める)。時刻リストで結果的にカットが無いのは対象外
        plan = pack.plan_cut(pack.Request(video=self.v60, silence=True))
        self.assertEqual(plan.keeps, [(0, 240)])
        self.assertTrue(any("切れる所が見つかりませんでした" in w for w in plan.warnings), plan.warnings)
        plan = pack.plan_cut(pack.Request(video=self.v60, base="list", keep_pairs=[(0, 4)]))
        self.assertFalse(any("切れる所が見つかりませんでした" in w for w in plan.warnings), plan.warnings)

    LIST = ("\ufeff# 時刻リストの見本\n"
            "start,end\n"                                                         # 最初の行が数字を含まなければ見出し(コメントの行は数えない)
            "0.5 1   # コメント\n"
            "0.6 0.9\n"                                                           # 重なる区間はまとめる
            "1.0 1.01\n"                                                          # コマに丸めると 0 → 捨てて知らせる
            "\n"
            "0:01.5 - 0:02\n"
            "0:00:02,5〜0:00:03\n"
            "３．５ → ４\n"
            "0:04.5 --> 00:00:05\n"
            "5.5,6\n"
            "6,5 7\n"
            "7.5, 0:08, 見どころ\n"
            "8.5\t9\n"
            "9.1 9.3\n"                                                           # 最短(0.3 秒)より短い区間は捨てる
            "９．５ 75\n")
    LIST_KEEPS = [(15, 30), (45, 60), (75, 90), (105, 120), (135, 150), (165, 180), (195, 210), (225, 240), (255, 270), (285, 300)]

    def test_list_run(self):
        """時刻リストの通し(画面の指定から): 書き方の全部(BOM・コメント・空行・区切り・全角・CSV・小数のコンマ・60 以上の先頭の欄・動画の外)・
        字幕の付け直し・削る区間・詳しい設定(タイムコード・リール・題)・埋め込みのタイムコード・29.97 / 23.976fps・入力の誤り"""
        out = self.d / "list_a"
        spec = {"video": str(self.video), "srt": str(self.srt), "mode": "list", "listText": self.LIST}
        plan, res = self.spec_pack(spec, {"dir": str(out), "copyVideo": False})
        self.assertEqual(plan.keeps, self.LIST_KEEPS)
        self.assertTrue(any("動画の長さ" in w or "範囲" in w for w in plan.warnings), plan.warnings)   # 75 秒は動画の終わりで切って知らせる
        self.assertTrue(any("0 になる" in w for w in plan.warnings), plan.warnings)
        self.assertEqual(self.name_warnings(res["warnings"]), 1)
        ev = parse_edl((out / "さくらみこ.edl").read_text(encoding="utf-8"))
        self.assertEqual([(tc2f(e[3], 30), tc2f(e[4], 30)) for e in ev], self.LIST_KEEPS)
        # 字幕の付け直し: 区間の中・区間をまたぐと割る・切られて短い断片は捨てる・全部カットの字幕は消える・カット後は時刻順
        srt = write(self.d / "remap.srt", "1\n00:00:05,500 --> 00:00:07,000\nB\n\n2\n00:00:01,000 --> 00:00:02,000\nA\n\n"
                                          "3\n00:00:03,500 --> 00:00:04,500\ncut\n\n4\n00:00:02,000 --> 00:00:06,000\nX\n\n"
                                          "5\n00:00:02,950 --> 00:00:03,400\nT\n\n6\n00:00:01,000 --> 00:00:01,100\nshort\n")
        out = self.d / "list_remap"
        plan, res = self.spec_pack({"video": str(self.video), "srt": str(srt), "mode": "list", "listText": "1 3\n5 8\n"}, {"dir": str(out)})
        cues = [(S.ms_to_frames(a, FPS30), S.ms_to_frames(b, FPS30), t) for a, b, t in S.parse_subs((out / "さくらみこ_cut.srt").read_text(encoding="utf-8"))]
        self.assertEqual(sorted(cues), sorted([(0, 30, "A"), (0, 3, "short"), (30, 60, "X"), (60, 90, "X"), (75, 120, "B")]))
        self.assertEqual([c[0] for c in cues], sorted(c[0] for c in cues))
        self.assertEqual(pack.summary(plan)["subtitles"]["vanished"], 2)
        # 削る区間・詳しい設定: 元の開始タイムコード(ドロップの書き方は直して知らせる)・タイムラインの開始・リール名・題の改行
        out = self.d / "list_drop"
        adv = {"srcStartTc": "01:00:00;00", "recStart": "02:00:00:00", "reel": "日本語 x-1", "name": "a\nb"}
        plan, res = self.spec_pack({"video": str(self.video), "mode": "list", "listKind": "drop", "listText": "0 1\n9 10\n", "advanced": adv},
                                   {"dir": str(out)})
        self.assertTrue(any(";" in w or "ドロップ" in w for w in plan.warnings), plan.warnings)
        text = (out / "さくらみこ.edl").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("TITLE: a b\n"))
        ev = parse_edl(text)
        self.assertEqual([(e[1], e[2], e[3], e[4], e[5]) for e in ev], [("X1", "AA/V", "01:00:01:00", "01:00:09:00", "02:00:00:00")])
        out = self.d / "list_reel"
        self.spec_pack({"video": str(self.video), "mode": "list", "listText": "0 1", "advanced": {"reel": "日本語"}}, {"dir": str(out)})
        self.assertEqual(parse_edl((out / "さくらみこ.edl").read_text(encoding="utf-8"))[0][1], "AX")
        # 字幕の行を削る(drop_lines)・試算だけ(ファイルを作らない)・上書きは force
        plan = pack.plan_cut(pack.Request(video=self.video, sub=self.srt, drop_lines={2}))
        self.assertEqual(plan.keeps, [(0, 150), (180, 300)])                               # 5-6 秒の字幕の時間帯が抜ける
        self.assertFalse((self.d / "さくらみこ_pack").exists())
        # 動画に埋め込まれた開始タイムコード(EDL の元の側はその範囲)・指定が優先・埋め込みが無ければ 0
        out = self.d / "tc_pack"
        _, res = self.spec_pack({"video": str(self.tc), "mode": "list", "listText": "1 2\n3 5\n"}, {"dir": str(out)})
        self.assertEqual(self.name_warnings(res["warnings"]), 0)                           # 英字の名前なら名前の注意は出さない
        ev = parse_edl((out / "tc.edl").read_text(encoding="utf-8"))
        self.assertEqual([(e[3], e[4]) for e in ev], [("10:00:01:00", "10:00:02:00"), ("10:00:03:00", "10:00:05:00")])
        self.assertEqual(ev[0][5], "01:00:00:00")                                          # 記録側は元の開始タイムコードに影響されない
        self.assertIn("10:00:00:00", pack.build_pack(pack.plan_cut(pack.Request(video=self.tc, base="list", keep_pairs=[(1, 2)])),
                                                     self.d / "tc_readme")["readme"])
        out = self.d / "tc_override"
        self.spec_pack({"video": str(self.tc), "mode": "list", "listText": "1 2", "advanced": {"srcStartTc": "00:00:00:00"}}, {"dir": str(out)})
        self.assertEqual(parse_edl((out / "tc.edl").read_text(encoding="utf-8"))[0][3], "00:00:01:00")
        self.assertEqual(pack.plan_cut(pack.Request(video=self.mute)).src_start, "00:00:00:00")
        # 29.97fps(埋め込みはドロップの書き方 → 直して使う): EDL は呼び名の 30 で数える・粗編集のコマ数と fps は元のまま。23.976 は 24 で数える
        out = self.d / "v2997_list"
        plan, res = self.spec_pack({"video": str(self.v2997), "mode": "list", "listText": "1 2\n3 4\n"}, {"dir": str(out), "render": True})
        self.assertEqual(plan.meta["fps"], (30000, 1001))
        self.assertTrue(any(";" in w or "ドロップ" in w for w in plan.warnings), plan.warnings)
        ev = parse_edl((out / "v2997.edl").read_text(encoding="utf-8"))
        self.assertEqual([(e[3], e[4]) for e in ev], [("01:00:01:00", "01:00:02:00"), ("01:00:03:00", "01:00:04:00")])
        n = sum(tc2f(e[4], 30) - tc2f(e[3], 30) for e in ev)
        rough = S.probe(out / "v2997_roughcut.mp4")
        self.assertLessEqual(abs(rough["total"] - n), 2)
        self.assertEqual(rough["fps"], (30000, 1001))
        out = self.d / "v23976_list"
        self.spec_pack({"video": str(self.v23976), "mode": "list", "listText": "1 2"}, {"dir": str(out)})
        self.assertEqual([(e[3], e[4]) for e in parse_edl((out / "v23976.edl").read_text(encoding="utf-8"))], [("00:00:01:00", "00:00:02:00")])
        # 「-」で始まる名前の動画を相対パスで渡しても、ffprobe / ffmpeg にオプションと取り違えさせない
        dash = self.d / "dash"
        dash.mkdir()
        (dash / "-i.mp4").write_bytes(self.video.read_bytes())
        cwd = os.getcwd()
        os.chdir(dash)
        try:
            plan = pack.plan_cut(pack.Request(video=Path("-i.mp4"), silence=True))
        finally:
            os.chdir(cwd)
        self.assertEqual((plan.meta["total"], len(plan.keeps)), (300, 3))

        # 入力の誤り(ffmpeg の前に断る。行の番号を出す)
        for text, msg in (("0:01 0:02\n0:05 abc\n", "2行目"), ("0:05 0:10\n0:20\n", "2行目"), ("0:10 0:05\n", "1行目"),
                          ("1:75 2:00\n", "60 未満"), ("0:60:00 1:00:00\n", "60 未満"), ("", "1行以上")):
            with self.subTest(text=text), self.assertRaises(ApiError) as cm:
                self.spec_pack(dict(spec, listText=text))
            self.assertIn(msg, cm.exception.message)
        for bad in ("abc", "1:2:3:4", "inf", "nan", "1..2"):
            with self.subTest(bad=bad), self.assertRaises(ApiError):
                self.spec_pack(dict(spec, listText="%s 5\n" % bad))
        with self.assertRaises(C.ToolError):                                              # 動画の外だけ
            self.spec_pack(dict(spec, listText="100 200\n"), {"dir": str(self.d / "list_out")})
        for kw in ({"keep_pairs": [(0, 10)], "drop_pairs": [(0, 10)]}, {"drop_lines": {1}, "sub": None}):   # 全部削る・字幕が無いのに行を削る
            with self.assertRaises(C.ToolError):
                pack.plan_cut(pack.Request(video=self.video, base="list", **dict({"keep_pairs": [(0, 10)]}, **kw)))
        for adv, msg in (({"srcStartTc": "00:00:00:45"}, None), ({"srcStartTc": "00:00:00:30"}, "--src-start-tc"), ({"recStart": "1:00:00"}, "--rec-start")):
            with self.subTest(adv=adv), self.assertRaises(C.ToolError) as cm:
                self.spec_pack(dict(spec, listText="1 2\n", advanced=adv), {"dir": str(self.d / "tc_bad"), "render": True})
            if msg:
                self.assertIn(msg, str(cm.exception))
        self.assertFalse((self.d / "tc_bad").exists() or (self.d / "list_out").exists())    # 粗編集も書き出さずに失敗する
        self.spec_pack(dict(spec, listText="1 2\n", advanced={"recStart": "10:00:00:29"}), {"dir": str(self.d / "tc_max")})

    def test_plan_run(self):
        """採用区間 JSON(cut-plan)からの通し: 出どころごとの余白の既定・採用の区間だけ・余白が重なれば 1 つに・削った所の記録・4 つのファイル・
        上書きと入力の字幕の守り・29.97fps の読み直し・同じ動画の写しを飛ばす・形の誤り"""
        def plan_file(name, segs, **extra):
            return write(self.d / name, json.dumps(dict({"schema": "youtube-tools-cut-plan/v1", "segments": segs}, **extra)))
        segs = [{"id": "a", "start": 1.0, "end": 2.0}, {"id": "b", "start": 3.0, "end": 4.0, "status": "rejected"}]
        for extra, handles, keeps in (({}, 10.0, [(0, 300)]), ({"tool": {"name": "clip-studio"}}, 10.0, [(0, 300)]),
                                      ({"tool": {"name": "transcribe-tool"}}, 0.0, [(30, 60)]), ({"segmentsIncludeHandles": True}, 0.0, [(30, 60)])):
            with self.subTest(extra=extra):
                p = pack.plan_cut(pack.Request(video=self.video, plan=plan_file("p.json", segs, **extra), base="plan"))
                self.assertEqual((p.handles, p.keeps, p.selected), (handles, keeps, [(30, 60)]))   # 採用しなかった区間は使わない
        lines = [{"id": "segment-001", "start": 1.0, "end": 2.0, "status": "adopted", "lines": ["s1"]},
                 {"id": "segment-002", "start": 5.0, "end": 6.0, "status": "adopted", "lines": ["s3"]}]
        p = plan_file("lines.json", lines, tool={"name": "transcribe-tool", "version": "0.10.0"})
        self.assertEqual(pack.plan_cut(pack.Request(video=self.video, plan=p, base="plan")).keeps, [(30, 60), (150, 180)])   # 行から = 余白なし
        self.assertEqual(pack.plan_cut(pack.Request(video=self.video, plan=p, base="plan", handles=10)).keeps, [(0, 300)])
        bom = self.d / "bom.json"
        bom.write_bytes(b"\xef\xbb\xbf" + json.dumps({"schema": "youtube-tools-cut-plan/v1", "segments": [{"start": 1, "end": 2}]}).encode())
        self.assertEqual(pack.plan_cut(pack.Request(video=self.video, plan=bom, base="plan", handles=0)).keeps, [(30, 60)])
        for text, msg in (('{"schema":"youtube-tools-cut-plan/v2","segments":[]}', "未対応の版"),
                          ('{"schema":"youtube-tools-cut-plan/v1","segments":[{"start":NaN,"end":1}]}', "")):
            with self.subTest(text=text), self.assertRaisesRegex(C.ToolError, msg):
                pack.plan_cut(pack.Request(video=self.video, plan=write(self.d / "bad.json", text), base="plan"))
        for bad in (-1, float("inf"), float("nan")):
            with self.assertRaises(C.ToolError):
                pack.plan_cut(pack.Request(video=self.video, plan=bom, base="plan", handles=bad))
        # 余白が重なる 2 区間は 1 つにまとめる・削った所と選んだ区間を cut-plan.json に残す(60 秒の動画)
        sel = plan_file("long.json", [{"id": "a", "label": "first", "start": 20, "end": 30}, {"id": "b", "label": "second", "start": 35, "end": 40}])
        p = pack.plan_cut(pack.Request(video=self.long, plan=sel, base="plan", handles=10, min_len=0.0))
        self.assertEqual((p.keeps, p.doc["removed_frames"], p.doc["selected_segments"][0]["selected_frames"]),
                         ([(300, 1500)], [[0, 300], [1500, 1800]], [600, 900]))
        # 採用区間 + 字幕のパック: EDL・カット後の SRT・cut-plan.json(tool は cut2resolve)・友人へ.txt。2 回目は force が要る
        sel = plan_file("sel.json", [{"id": "m1", "label": "moment", "start": 3, "end": 5}])
        out = self.d / "sel_pack"
        _, res = selection_pack(self.video, sel, out, self.srt, handles=1.0)
        self.assertEqual(self.names(out), sorted(["さくらみこ.edl", "さくらみこ_cut.srt", "cut-plan.json", "友人へ.txt"]))
        saved = json.loads((out / "cut-plan.json").read_text(encoding="utf-8"))
        self.assertEqual((saved["keep_frames"], saved["removed_frames"], saved["tool"]["name"], saved["media"]["name"]),
                         ([[60, 180]], [[0, 60], [180, 300]], "cut2resolve", "さくらみこ.mp4"))
        for k in ("schema", "createdAt", "segments"):
            self.assertIn(k, saved)
        self.assertIn("DaVinci Resolve", (out / "友人へ.txt").read_text(encoding="utf-8-sig"))
        with self.assertRaisesRegex(C.ToolError, "--force"):
            selection_pack(self.video, sel, out, self.srt, handles=1.0)
        selection_pack(self.video, sel, out, self.srt, handles=1.0, force=True)
        # 出力と同じ場所にある入力の字幕は force でも上書きしない(出力先を「..」つきで書いても同じ場所と分かる)・断ったときは何も書かない
        guard = self.d / "guard"
        (guard / "sub").mkdir(parents=True)
        sub = write(guard / "さくらみこ_cut.srt", "1\n00:00:01,000 --> 00:00:02,000\nx\n")
        with self.assertRaisesRegex(C.ToolError, "入力ファイル"):
            selection_pack(self.video, sel, guard / "sub" / "..", sub, handles=0.0, force=True)
        self.assertEqual((sub.read_text(encoding="utf-8").count("x"), self.names(guard)), (1, ["さくらみこ_cut.srt"]))
        # 同じ動画を写したパックをもう一度: 写さずに注意
        out = self.d / "sel_copy"
        plan, res = selection_pack(self.video, sel, out, handles=0.5, copy_video=True)
        self.assertNotIn(C.COPY_SKIPPED.format("さくらみこ.mp4"), plan.warnings + res["warnings"])
        self.assertTrue(C.same_copy(self.video, out / "さくらみこ.mp4"))
        plan, res = selection_pack(self.video, sel, out, handles=0.5, copy_video=True, force=True)
        self.assertIn(C.COPY_SKIPPED.format("さくらみこ.mp4"), plan.warnings + res["warnings"])
        # 29.97fps: 書いた cut-plan.json を読み直すと同じ残す区間(pack 経由でも build_plan と同じ)
        segs = [{"id": "a", "start": 1.3, "end": 3.7}, {"id": "b", "start": 6, "end": 8}]
        out = self.d / "sel_2997"
        selection_pack(self.v2997, plan_file("s2997.json", segs), out, handles=0.5)
        saved = json.loads((out / "cut-plan.json").read_text(encoding="utf-8"))
        meta = S.probe(self.v2997)
        want = AC.build_plan([dict(id=s["id"], label="", start_seconds=s["start"], end_seconds=s["end"]) for s in segs], meta, 0.5)["keep_frames"]
        self.assertEqual(saved["keep_frames"], want)
        doc = AC.read_cut_plan(out / "cut-plan.json")
        self.assertEqual(AC.build_plan(doc["segments"], meta, AC.default_handles(doc))["keep_frames"], want)
        again = pack.plan_cut(pack.Request(video=self.v2997, plan=out / "cut-plan.json", base="plan", min_len=0.0))
        self.assertEqual([list(x) for x in again.keeps], want)

    def test_row_edge_run(self):
        """行から作るカットの端を声の止まる所まで広げる(本物の無音。0-2 秒 音 / 2-4 無音 / 4-6 音 / 6-8 無音 / 8-10 音)。画面の指定 rowEdge も通す"""
        cache = pack.Cache()

        def keeps(rows, video=None, spec_edge="default", **kw):
            tr = write(self.d / "re.transcript.json", json.dumps(transcript_doc(rows), ensure_ascii=False))
            if spec_edge != "default":
                req = R.request_from_spec({"video": str(video or self.video), "transcript": str(tr), "preset": "transcript-rows", "rowEdge": spec_edge})
            else:
                req = pack.Request(video=video or self.video, transcript=tr, **dict(pack.TRANSCRIPT_ROWS, **kw))
            plan = pack.plan_cut(req, cache=cache)
            return plan.keeps, plan

        def near(got, want, tol=1):
            """AAC の符号化で無音の境目が 1 フレームほど前後することがある"""
            self.assertEqual(len(got), len(want), got)
            for g, x in zip(got, want):
                self.assertTrue(all(abs(a - b) <= tol for a, b in zip(g, x)), "%r != %r" % (got, want))
        # 終わり 1.8 → 無音の始まり 2.0(60)。始まり 4.2 → 無音の終わり 4.0(120)。終わり 5.0 → 窓(5.5 まで)に無音が無い → 5.2(156)。
        # 始まり 0.5 → 前に無音が無い → 0.4(12)。字幕(行の時刻)は変えない
        k, plan = keeps([(0.5, 1.8, "一", False), (4.2, 5.0, "二", False)])
        near(k, [(12, 60), (120, 156)])
        self.assertEqual(([c[2] for c in plan.cues_out], plan.cues[0][:2]), (["一", "二"], (500, 1800)))
        self.assertEqual(keeps([(0.5, 1.0, "一", False)])[0], [(12, 36)])                  # 無音(2.0)は 0.5 秒より先 → 決まった余白 1.2(36)
        near(keeps([(4.2, 4.9, "a", False), (5.1, 5.8, "b", False)])[0], [(120, 180)])     # 広げて重なった 2 つ → 1 つ(終わり 5.8 → 無音 6.0)
        self.assertEqual(keeps([(0.05, 0.5, "頭", False), (9.6, 9.95, "尻", False)])[0], [(0, 21), (285, 300)])   # 0〜動画の長さで止める
        # 隣の「カット済」の行の時間には入らない・越えない(無音 2.0 までの 1.9〜2.0 の切れ端を残さない)
        self.assertEqual(keeps([(0.5, 1.5, "a", False), (1.5, 1.9, "切る", True)])[0], [(12, 45)])
        self.assertEqual(keeps([(0.5, 1.5, "a", False), (1.6, 1.9, "切る", True)])[0], [(12, 48)])
        self.assertEqual(keeps([(0.5, 1.5, "a", False), (1.5, 1.9, "切る", True)], drop_cut_rows=False)[0], [(12, 60)])   # 削らない指定なら行として扱わない
        # 広げない・無音を調べない・音声が無い
        rows = [(0.5, 1.8, "一", False)]
        self.assertEqual(keeps(rows, row_edge=None)[0], [(15, 54)])
        self.assertEqual(keeps(rows, row_edge=pack.without_detect(pack.Request(video=self.video, row_edge=pack.ROW_EDGE)).row_edge)[0], [(12, 60)])
        self.assertEqual(keeps(rows, video=self.mute)[0], [(15, 54)])
        # 画面の指定(rowEdge): 省略 = 既定・false / {"on": false} = 広げない・上限と余白の秒(padAfter は後ろの余白。上限より長ければ上限も上がる)
        self.assertEqual(keeps(rows, spec_edge=None)[0], keeps(rows)[0])
        for off in (False, {"on": False}, {"on": False, "padAfter": 0.4}):
            self.assertEqual(keeps(rows, spec_edge=off)[0], [(15, 54)], off)
        self.assertEqual(keeps([(4.2, 5.0, "二", False)], spec_edge={"after": 0.1, "before": 0})[0], [(126, 153)])   # 余白も上限の中
        self.assertEqual(keeps([(4.2, 5.0, "二", False)], spec_edge={"padAfter": 0.4})[0][0][1], 162)              # 後ろ 0.4 秒(12)
        self.assertEqual(keeps([(4.2, 5.0, "二", False)], spec_edge={"padAfter": 1.0})[0][0][1], 180)              # 上限 1.0 秒 → 無音 6.0 まで
        self.assertEqual(keeps([(4.2, 5.0, "二", False)], spec_edge={"padAfter": 0})[0][0][1], 150)
        for bad in ({"padAfter": 3}, {"padAfter": -0.1}, {"padAfter": "0.4"}, {"padAfter": True}, {"padAfter": float("nan")},
                    {"after": 3}, {"before": -1}, {"after": "x"}, {"after": True}, [1], "on"):
            with self.subTest(bad=bad), self.assertRaises(ApiError):
                keeps(rows, spec_edge=bad)
        # 無音を調べる前か(画面の「調べています」)・2 回目は覚えた無音を使う
        tr = write(self.d / "p.transcript.json", json.dumps(transcript_doc(rows), ensure_ascii=False))
        req = pack.Request(video=self.video, transcript=tr, **pack.TRANSCRIPT_ROWS)
        fresh = pack.Cache()
        self.assertTrue(pack.row_edge_pending(req, fresh))
        pack.plan_cut(req, cache=fresh)
        self.assertFalse(pack.row_edge_pending(req, fresh))
        for other in (dataclasses_replace(req, row_edge=None), pack.without_detect(req), pack.Request(video=self.video, base="all", row_edge=pack.ROW_EDGE)):
            self.assertFalse(pack.row_edge_pending(other, pack.Cache()))
        # 手で決めた区間(keeps)・時刻リストには使わない
        self.assertEqual(pack.plan_cut(pack.Request(video=self.video, keep_pairs=[(0.5, 1.8)], **pack.EDIT_KEEPS)).keeps, [(15, 54)])
        self.assertEqual(pack.plan_cut(pack.Request(video=self.video, base="list", keep_pairs=[(0.5, 1.8)], min_len=0, row_edge=pack.ROW_EDGE)).keeps,
                         [(15, 54)])

    def test_row_edge_detection_failure_falls_back_to_pad(self):
        """無音を調べる ffmpeg が落ちた(差し込む失敗)→ 決まった余白で続ける"""
        tr = write(self.d / "fail.transcript.json", json.dumps(transcript_doc([(0.5, 1.8, "一", False)]), ensure_ascii=False))
        with mock.patch.object(C, "detect_silence", side_effect=C.ToolError("だめ")):
            plan = pack.plan_cut(pack.Request(video=self.video, transcript=tr, **pack.TRANSCRIPT_ROWS))
        self.assertEqual(plan.keeps, [(12, 60)])
        self.assertTrue(any("声の止まる所を調べられなかった" in w for w in plan.warnings))

    def test_snap_run(self):
        """切り抜きの両端を話の切れ目へ詰める(LD-2c)・余白つきの動画のマークの区間(LD-2f)。画面の指定 snapEdges・clipRange も通す"""
        def run(video, rows, **kw):
            tr = write(self.d / "snap.transcript.json", json.dumps(transcript_doc(rows), ensure_ascii=False))
            plan = pack.plan_cut(pack.Request(video=video, transcript=tr, drop_cut_rows=False, **dict({"snap_edges": True}, **kw)))
            return plan.keeps, [w for w in plan.warnings if "切れ目" in w or "余白" in w]
        # 0 秒から言葉の途中で始まり(1 行目)・最後の行が動画の終わりまで続く(言葉の途中で終わる)→ 3.5 秒〜 50.5 秒(終助詞の行のあと)
        k, w = run(self.long, [(0.0, 3.0, "だから", False), (4.0, 40.0, "本題です。", False), (41.0, 50.0, "でね", False), (51.0, 60.0, "最後まで", False)])
        self.assertEqual(k, [(105, 1515)])
        self.assertTrue(any("話の切れ目" in x for x in w), w)
        # 話の前後に間がある = 詰めない・カット済の行は見ない
        self.assertEqual(run(self.video, [(1.0, 5.0, "はい。", False), (6.0, 9.0, "どうも。", False)]), ([(0, 300)], []))
        self.assertEqual(run(self.video, [(0.0, 3.0, "だから", True), (4.0, 9.0, "本題", False)])[0], run(self.video, [(4.0, 9.0, "本題", False)])[0])
        # 余白つきの動画(60 秒・マーク 10〜50 秒): 端の言葉の途中を、余白の中の切れ目へ外へ伸ばす
        rows = [(2.0, 6.5, "はい。", False), (8.0, 12.0, "これは", False), (12.5, 40.0, "本題", False), (40.5, 44.5, "でね", False),
                (45.0, 52.0, "最後まで", False), (53.0, 57.0, "おわり。", False)]
        k, w = run(self.long, rows, clip_range=(10.0, 50.0))
        self.assertTrue(k[0][0] < 300 and k[-1][1] > 1500, k)
        self.assertTrue(any("伸ばした" in x and "余白" in x for x in w), w)
        rows = [(12.0, 20.0, "はい。", False), (30.0, 40.0, "どうも。", False)]
        k, w = run(self.long, rows, clip_range=(10.0, 50.0))                               # 端に声が無い = マークのまま
        self.assertEqual((k, len(w)), ([(300, 1500)], 1))
        self.assertIn("余白", w[0])
        k, w = run(self.long, rows, clip_range=(10.0, 50.0), snap_edges=False)             # 寄せないとき = マークの区間だけ
        self.assertEqual((k, len(w)), ([(300, 1500)], 1))
        # 画面の指定(② が送る): snapEdges・clipRange
        tr = str(self.d / "snap.transcript.json")
        base = {"video": str(self.long), "transcript": tr}
        self.assertEqual(R.request_from_spec(dict(base, preset="transcript-rows", clipRange=[10, 50])).clip_range, (10.0, 50.0))
        self.assertIsNone(R.request_from_spec(dict(base, mode="silence")).clip_range)
        with self.assertRaises(ApiError):
            R.request_from_spec(dict(base, mode="silence", clipRange=[50, 10]))
        self.assertTrue(R.request_from_spec(dict(base, preset="transcript-rows", snapEdges=True)).snap_edges)
        self.assertFalse(R.request_from_spec(dict(base, preset="transcript-rows")).snap_edges)
        self.assertTrue(R.request_from_spec(dict(base, mode="silence", snapEdges=True)).snap_edges)

    def test_mismatched_edit_media_falls_back(self):
        """余白つき素材の fps・大きさが違う・短いときは使わず、元の動画を入れて理由を注意に出す"""
        tr = self.spk_doc("mismatch", [(0.5, 2, "一", 0), (3, 5, "二", 1)])
        orig = self.sidecar.read_text(encoding="utf-8")
        try:
            self.sidecar.write_text(json.dumps({"schema": C.EDIT_MEDIA_SCHEMA, "media": "other_edit.mp4",
                                                "selectionIn": 10, "handleBefore": 10, "handleAfter": 10}), encoding="utf-8")
            out = self.d / "pack_mismatch"
            res = pack.build_pack(self.plan(tr), out, textplus=True)
            self.assertIsNone(res["editMedia"])
            self.assertTrue((out / "さくらみこ.mp4").is_file())
            self.assertTrue(any("fps・大きさが違う" in w for w in res["warnings"]))
            self.sidecar.write_text(json.dumps({"schema": C.EDIT_MEDIA_SCHEMA, "media": self.MEDIA, "selectionIn": 26,
                                                "handleBefore": 10, "handleAfter": 0}, ensure_ascii=False), encoding="utf-8")
            res = pack.build_pack(self.plan(tr), self.d / "pack_short", textplus=True)      # 26 + 5 秒 > 30 秒
            self.assertIsNone(res["editMedia"])
            self.assertTrue(any("短い" in w for w in res["warnings"]))
        finally:
            self.sidecar.write_text(orig, encoding="utf-8")

    def test_no_sub_rows(self):
        """字幕に出さない行(noSub): 時間は残す区間に数えるが、字幕は作らない。話者・色は残りの字幕に合う。段は noSub を外してから数える"""
        rows = [(0.5, 2, "一", 0), (1.0, 2.5, "ゲームの声", 1), (2.5, 3, "まだ", 1), (3, 5, "二", 1)]
        tr = self.spk_doc("nosub", rows, {1: {"noSub": True}})
        self.assertEqual([r["noSub"] for r in C.read_transcript(tr)["rows"]], [False, True, False, False])
        plan = self.plan(tr)
        self.assertEqual(plan.keeps, [(15, 150)])                                     # 1.0〜2.5 も残す(つながって 1 区間)
        self.assertEqual([c[2] for c in plan.cues_out], ["一", "まだ", "二"])
        self.assertEqual(pack.cue_speakers(plan), ["兎田ぺこら", "話者2", "話者2"])
        self.assertEqual(plan.speaker_spans, [(0.5, 2, "兎田ぺこら"), (2.5, 3, "話者2"), (3, 5, "話者2")])
        sm = pack.summary(plan)
        self.assertEqual((sm["noSubRows"], sm["captionLanes"], sm["captionsStacked"]), (1, 1, 0))   # 重なっていた行は字幕に出さない → 段は 1
        self.assertIn("字幕に出さない行: 1行", sm["text"])
        out = self.d / "nosub"
        pack.build_pack(plan, out, textplus=True, speaker_colors={"話者2": "#0000FF"}, **self.SCREEN)
        ip = RTP.read_script_plan(self.lua(out))
        self.assertEqual([c["text"] for c in ip["captions"]], ["一", "まだ", "二"])
        self.assertEqual([c.get("fill") for c in ip["captions"]], [None, [0.0, 0.0, 1.0, 1.0], [0.0, 0.0, 1.0, 1.0]])
        self.assertNotIn("captionLanes", ip)
        # 編集のカット(EDIT_KEEPS)の道でも同じ字幕
        p2 = pack.plan_cut(pack.Request(video=self.video, transcript=tr, keep_pairs=[(0.5, 5.0)], **pack.EDIT_KEEPS))
        self.assertEqual(([c[2] for c in p2.cues_out], p2.no_sub_rows), (["一", "まだ", "二"], 1))
        # 項目が無い・false なら字幕に出す
        p0 = self.plan(self.spk_doc("nosub0", rows, {1: {"noSub": False}}))
        self.assertEqual(([c[2] for c in p0.cues_out], pack.summary(p0)["noSubRows"]), (["一", "ゲームの声", "まだ", "二"], 0))
        # 残す行がすべて noSub: 字幕なし(注意を出す)。区間は残す
        p1 = self.plan(self.spk_doc("nosub_all", rows[:2], {0: {"noSub": True}, 1: {"noSub": True}}))
        self.assertEqual((p1.cues_out, p1.keeps, pack.summary(p1)["noSubRows"]), (None, [(15, 75)], 2))
        self.assertTrue(any("字幕に出さない" in w for w in p1.warnings))
        with self.assertRaises(C.ToolError):
            pack.build_pack(p1, self.d / "nosub_all", textplus=True, **self.SCREEN)

    def test_overwrite_check_and_leftovers(self):
        """上書きの確認は今回書くものだけ。前に作ったパックの残り(前の置き方・消した予備)は消さずに知らせる"""
        plan = self.plan(self.spk_doc("again", [(0.5, 2, "一", 0), (3, 5, "二", 1)]), edit_media=False)
        out = self.d / "again"
        pack.build_pack(plan, out, textplus=True, plan_file=True)                       # cut-plan.json・友人へ.txt もあるフォルダ
        for n in ("さくらみこ.edl", "さくらみこ_cut.srt", "予備_EDLで開く手順.txt"):       # 古いパックの予備(決定 3-34)
            (out / n).write_text("old", encoding="utf-8")
        (out / "media").mkdir()
        (out / "media" / "さくらみこ.mp4").write_bytes(b"old")                          # 古いパックの動画の場所
        _, paths, existing = pack.planned_outputs(plan, out, textplus=True, **self.SCREEN)
        self.assertEqual(sorted(p.name for p in existing), sorted(self.MINIMAL + ["さくらみこ.mp4"]))
        with self.assertRaises(C.OutputExists):
            pack.build_pack(plan, out, textplus=True, **self.SCREEN)
        res = pack.build_pack(plan, out, textplus=True, force=True, **self.SCREEN)
        left = next(w for w in res["warnings"] if "前に作った" in w)
        for n in ("さくらみこ.edl", "さくらみこ_cut.srt", "予備_EDLで開く手順.txt", "cut-plan.json", RTP.README_NAME, "media/さくらみこ.mp4"):
            self.assertIn(n, left)                                                      # 残っている前のファイルを知らせる(消さない)
        self.assertEqual((out / "media" / "さくらみこ.mp4").read_bytes(), b"old")


if __name__ == "__main__":
    unittest.main(verbosity=2)
