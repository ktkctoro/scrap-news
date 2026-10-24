#!/usr/bin/env python3
"""けさの3行まとめを書く（無料版。AIは使わない）。

collect.py が作った data.json を読み、決まった書き方で「けさの3行」を
組み立てて data.json に書き足す。

  1行目: 銅建値と鉄スクラップ
  2行目: 金・銀・ドル円
  3行目: ここ3日の法規制の新着（無ければ業界の新着）

2026-10まではClaude APIに書かせていたが、費用をゼロにするためやめた。
AIらしい言い回しは無いかわりに、数字は取ってきたものをそのまま出すので
まちがえない。追加ライブラリなし（標準ライブラリのみ）。
使い方: py summarize.py
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
JST = timezone(timedelta(hours=9))

NEW_DAYS = 3        # 3行目に載せる記事の新しさ（日）
TITLE_MAX = 34      # 3行目の見出しの長さ。スマホで2行に収まる程度


def _md(iso):
    """'2026-10-23T21:37:00+09:00' → '10/23'。日付が無ければ空。"""
    try:
        return f"{int(iso[5:7])}/{int(iso[8:10])}"
    except (TypeError, ValueError):
        return ""


def _diff(d):
    """前回比の文字列を見やすくする。'0' や空は「変わらず」。"""
    d = str(d or "").strip()
    if d in ("", "0", "±0", "+0", "-0"):
        return "変わらず"
    return d if d[0] in "+-" else "+" + d


def _short(name):
    """'銅建値（10/23改定）' → '銅建値'。"""
    for mark in ("（", "("):
        name = name.split(mark)[0]
    return name.strip()


def _find(rows, word):
    for r in rows:
        if word in r.get("name", ""):
            return r
    return None


def line_base(data):
    """1行目: 銅建値と鉄スクラップ。"""
    tiles = (data.get("manual") or {}).get("tiles", [])
    parts = []
    for word, label in (("銅建値", "銅建値"), ("東鉄", "鉄二級")):
        t = _find(tiles, word)
        if t:
            parts.append(f"{label}{t['value']}{t['unit'].split('/')[0]}（{_diff(t.get('diff'))}）")
    return "・" + "、".join(parts) if parts else None


def line_metal(data):
    """2行目: 金・銀・ドル円。"""
    rows = (data.get("manual") or {}).get("rows", [])
    parts = []
    for word in ("金", "銀"):
        r = _find(rows, word)
        if r:
            parts.append(f"{_short(r['name'])}{r['value']}円（{_diff(r.get('diff'))}）")
    fx = data.get("fx")
    if fx and fx.get("usdjpy"):
        parts.append(f"ドル円{fx['usdjpy']}円")
    return "・" + "、".join(parts) if parts else None


def line_news(data, now):
    """3行目: ここ数日の法規制の新着。無ければ業界の新着。"""
    since = (now - timedelta(days=NEW_DAYS)).isoformat()
    items = data.get("items") or []
    for cat, label in (("law", "法規制"), ("gen", "業界")):
        fresh = [i for i in items
                 if i.get("cat") == cat and (i.get("published") or "") >= since]
        if fresh:
            i = max(fresh, key=lambda x: x.get("published") or "")
            title = i["title"]
            if len(title) > TITLE_MAX:
                title = title[:TITLE_MAX] + "…"
            return f"・{label}：{title}（{_md(i.get('published'))}）"
    return f"・法規制・業界は、ここ{NEW_DAYS}日の新しい記事なし"


def main():
    dest = os.path.join(HERE, "data.json")
    if not os.path.exists(dest):
        print("けさの3行: data.json がありません。先に collect.py を実行してください", file=sys.stderr)
        return

    with open(dest, encoding="utf-8") as f:
        data = json.load(f)

    now = datetime.now(JST)
    rows = [l for l in (line_base(data), line_metal(data), line_news(data, now)) if l]
    if not rows:
        print("  ! けさの3行: 材料がありませんでした", file=sys.stderr)
        return

    data["ai"] = {"lines": rows, "at": f"{now.month}/{now.day} {now.hour}:{now.minute:02d}"}
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"けさの3行: 書きました（{len(rows)}行）")
    for l in rows:
        print("   " + l)


if __name__ == "__main__":
    main()
