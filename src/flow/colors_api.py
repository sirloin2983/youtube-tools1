# -*- coding: utf-8 -*-
"""② 管理の層 flow: api/ytt/streamer-colors の口(入口 src/app/server.py も友人のアプリ src/friendapp/server.py も同じ物を呼ぶ)。
要求の本文を解いて応答を組むだけ。名前の照らし合わせの規則・色の一覧の読みは ytt/colors。
"""
from ytt import colors


def _public(e):
    return {k: e[k] for k in ("name", "en", "hex", "group", "mine")}


def streamer_api(body):
    """{q, all?} -> 入れた名前に合う人・候補(all なら全員も)/ {names: [...]} -> 名前ごとに合う人
    (話者の名前をまとめて。画面が行ごとに通信しないように)"""
    entries = colors.load()
    if isinstance(body.get("names"), list):
        names = list(dict.fromkeys(n.strip()[:colors.NAME_MAX] for n in body["names"][:60] if isinstance(n, str) and n.strip()))
        matches = {n: colors.lookup(n, entries)["match"] for n in names}
        return {"ok": True, "matches": {n: _public(m) if m else None for n, m in matches.items()}}
    q = body.get("q") if isinstance(body.get("q"), str) else ""
    r = colors.lookup(q[:colors.NAME_MAX], entries)
    return {"ok": True, "match": _public(r["match"]) if r["match"] else None, "candidates": [_public(e) for e in r["candidates"]],
            "items": [_public(e) for e in entries] if body.get("all") is True else []}
