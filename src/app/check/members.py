"""確かめるの話者カードの「ほかのメンバーを足す」の欄が使う、メンバーの探し方の表(11-02。GET /api/check/members)。
表は dev/make_member_index.py が名簿・メンバーの色・保管庫の名前と呼び方の表から作る member_index.json(読むだけ)。
-> {"groups": [{label, names}], "members": {名前: {yomi, en, calls, hex}}}。無い・読めなければ空の形
"""
import os

from ytt import fsio

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "member_index.json")


def index():
    d = fsio.read_json_or(PATH, {}, max_bytes=1024 * 1024, kind=dict)
    return {"groups": d.get("groups") if isinstance(d.get("groups"), list) else [], "members": d.get("members") if isinstance(d.get("members"), dict) else {}}
