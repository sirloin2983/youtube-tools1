"""② サムネの案の口(OPT-H2 の組 A)。③ の editor/thumb_ideas.py(案の決め方・文字起こしを読む殻)が、① pipeline/export/thumb_cards を直に読まずに済むための動詞だけを出す。

- font()   : 描くフォントのパス(無ければ ThumbError)
- scan(v)  : 動画の長さ・幅・高さと、音の大きい瞬間・場面の切り替わりの候補
- render() : 案の一覧を 1 枚の PNG にする(ffmpeg は ① の中で呼ぶ)
ThumbError は ① の物をそのまま使う(ed_thumb が thumb_ideas の名前で読む)。
"""
from pipeline.export import thumb_cards as _cards

ThumbError = _cards.ThumbError


def font():   # flow: alias ok(③ は ① を読めない。フォントを決める正は ① thumb_cards.font_path)
    """描くフォントのパス(無ければ ThumbError)"""
    return _cards.font_path()


def scan(video):
    """-> (長さの秒, 幅, 高さ, [(時刻, 点数, 出どころ)])。音と場面の候補は ffmpeg で読む"""
    ff = _cards.ffmpeg_path()
    duration, vw, vh = _cards.probe(ff, video)
    return duration, vw, vh, _cards.loud_times(ff, video) + _cards.scene_times(ff, video)


def render(video, vw, vh, plan, color, font_file, out, rect=None):
    """plan = [{"n", "layout", "label", "t", "crop", "texts"}] の案を 1 枚の PNG(out)に描く(① draw_sheet)"""
    _cards.draw_sheet(_cards.ffmpeg_path(), video, vw, vh, plan, color, font_file, out, rect)
