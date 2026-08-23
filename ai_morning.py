#!/usr/bin/env python3
"""The Last Three Minutes（AIの朝3本）を取り込む。

毎朝3本のAI関連の話題を出している媒体。日付ごとのページがあるので、
今日のぶんを見て、無ければ昨日のぶんを見る。

追加ライブラリなし（標準ライブラリのみ）。
"""

import re
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
BASE = "https://thelastthreeminutes.com"


def _parse(html, date):
    """「IN THIS ISSUE」の一覧から3本の見出しとリンクを取り出す。"""
    m = re.search(r'class="web-issue-list">(.*?)</section>', html, re.S)
    if not m:
        return None

    items = []
    for path, title in re.findall(
        r'href="(/issues/[^"]+?)"[^>]*>\s*<span>\d+</span>\s*<strong>(.*?)</strong>',
        m.group(1), re.S,
    ):
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title)).strip()
        if t:
            items.append({"title": t, "link": BASE + path})
    if not items:
        return None

    out = {"date": date, "items": items[:3], "link": f"{BASE}/issues/{date}/"}

    # その日のまとめ文（3本をつないだ紹介文）
    d = re.search(r'<meta name="description" content="(.*?)"', html, re.S)
    if d:
        out["lead"] = re.sub(r"\s+", " ", d.group(1)).strip()

    # 動画版があればリンクも
    v = re.search(r'youtube(?:-nocookie)?\.com/embed/([\w-]{6,})', html)
    if v:
        out["video"] = f"https://www.youtube.com/watch?v={v.group(1)}"
    return out


def fetch_today(fetch):
    """今日のぶんを取る。まだ出ていなければ昨日のぶん。"""
    now = datetime.now(JST)
    for back in (0, 1):
        date = (now - timedelta(days=back)).strftime("%Y-%m-%d")
        try:
            html = fetch(f"{BASE}/issues/{date}/", timeout=30, tries=2).decode(
                "utf-8", errors="replace")
        except Exception as e:
            print(f"  ! AIの朝3本({date})が取れません: {e}", file=sys.stderr)
            continue
        got = _parse(html, date)
        if got:
            return got
        print(f"  ! AIの朝3本({date})の中身が読めません", file=sys.stderr)
    return None
