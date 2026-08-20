#!/usr/bin/env python3
"""同業各社の買取価格を集めて、品目ごとに横並びで比べられるようにする。

各社サイトの書き方が違うので、会社ごとに読み取り処理を分けている。
サイトの作りが変わるとその会社だけ読めなくなるが、ほかの会社は
そのまま出るようにしてある（1社こけても全体は止めない）。

追加ライブラリなし（標準ライブラリのみ）。
"""

import re
import sys

# ---- 各社の価格表ページ ------------------------------------------------
# 会社によっては品目ごとにページが分かれているので、複数URLを並べてある。
# 同じ会社の中では、先に書いたページで見つかった値を優先する。
DEALERS = [
    # (表示名, [URL...], 読み取り関数の名前)
    ("土金", [
        "https://www.dokindokin.com/scrap_type/copper/",
        "https://www.dokindokin.com/scrap_type/brass/",
        "https://www.dokindokin.com/scrap_type/aluminum/",
        "https://www.dokindokin.com/scrap_type/electrical-wire/",
        "https://www.dokindokin.com/scrap_type/radiator-motor/",
        "https://www.dokindokin.com/scrap_type/heater/",
        "https://www.dokindokin.com/scrap_type/battery/",
        "https://www.dokindokin.com/scrap_type/trans/",
    ], "dokin"),
    ("長澤", ["https://nagasawametal.com/purchase-items/"], "nagasawa"),
    ("大畑", ["https://www.ohata.org/kakaku.html"], "ohata"),
    ("安城貿易", ["https://anjyo-t.com/scrap_miscellaneous.html"], "anjyo"),
]

# ---- 比べる品目 --------------------------------------------------------
# 「画面に出す名前」と、それに当たる各社での言い方（部分一致で探す）。
# 各社で呼び名が違うので、ここで橋渡しをしている。
# 品目を足したいときは、この表に1行足すだけ。
COMPARE = [
    # (分野, 画面に出す名前, 各社での言い方)
    ("銅", "ピカ銅", ["ピカ銅", "ピカ線", "上銅"]),
    ("銅", "並銅", ["並銅"]),
    ("銅", "込銅", ["込銅"]),
    ("銅", "下銅", ["下銅"]),
    ("銅", "銅ダライ粉", ["銅ダライ粉", "銅ダライ"]),

    ("電線", "雑線(銅率80%)", ["雑電線(銅率80%)", "1本線80%赤"]),
    ("電線", "雑線(銅率60〜65%)", ["雑電線(銅率65%)", "3本線60%赤"]),
    ("電線", "VA線", ["ＶＡ線(巻き)", "VA線"]),
    ("電線", "家電線", ["家電線"]),
    ("電線", "エアコンパイプ", ["エアコンパイプ", "空調銅配管"]),

    ("真鍮・砲金", "砲金", ["砲金(青銅)_付物なし", "砲金（上）", "砲金"]),
    ("真鍮・砲金", "込砲金", ["込砲金"]),
    ("真鍮・砲金", "真鍮(上)", ["真鍮（上）", "真鍮/黄銅", "黄銅"]),
    ("真鍮・砲金", "込真鍮", ["込真鍮"]),
    ("真鍮・砲金", "真鍮ダライ粉", ["真鍮ダライ粉", "真鍮粉"]),

    ("アルミ", "アルミ(上)", ["アルミ（上）", "Aサッシ", "アルミ合金・新切れ"]),
    ("アルミ", "アルミサッシ", ["アルミサッシ", "アルミサッシバラ", "Aサッシ"]),
    ("アルミ", "アルミガラ", ["アルミガラA", "アルミガラ"]),
    ("アルミ", "アルミ缶(プレス)", ["アルミ缶（プレス）", "アルミ缶プレス"]),
    ("アルミ", "アルミラジエーター", ["アルミラジエーター(付物なし)", "アルミラジエター異物無", "アルミラジエーター"]),
    ("アルミ", "アルミホイール", ["アルミホイール鉄無", "アルミホイール"]),

    ("雑品", "給湯器", ["ガス給湯器", "給湯器"]),
    ("雑品", "黒モーター", ["黒モーターA", "黒モーター"]),
    ("雑品", "ガスメーター(アルミ外装)", ["ガスメーター（ｱﾙﾐ外装）", "ガスメーター(アルミ外装)"]),
    ("雑品", "車バッテリー(鉛)", ["自動車用 鉛バッテリー", "車バッテリー", "バッテリー（上）", "バッテリー"]),
    ("雑品", "安定器", ["安定器"]),
]


def _strip(h):
    """scriptとstyleを落とす。"""
    return re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)


def _num(s):
    s = re.sub(r"[^\d]", "", s)
    return int(s) if s.isdigit() else None


def _clean(s):
    """タグを外して前後の空白を落とす。"""
    return re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", s))


# ---- 会社ごとの読み取り ------------------------------------------------

def read_dokin(h):
    """土金: <span class="item-name">上銅</span> … <strong>2360</strong>円/kg"""
    out = {}
    for name, price in re.findall(
        r'<span class="item-name">([^<]{1,30})</span>.{0,200}?'
        r'<strong>([\d,]+)</strong>\s*円/kg', _strip(h), re.S
    ):
        v = _num(price)
        if v:
            out.setdefault(name.strip(), v)
    return out


def read_nagasawa(h):
    """長澤: <h4 class="it__tt1">ピカ銅</h4> … <span class="t1">2270</span>円/kg"""
    out = {}
    for name, price in re.findall(
        r'<h4 class="it__tt1">\s*([^<]{1,30}?)\s*</h4>.{0,300}?'
        r'<span class="t1">([\d,]+)</span>\s*<span class="t2">円/kg', _strip(h), re.S
    ):
        v = _num(price)
        if v:
            out.setdefault(name.strip(), v)
    return out


def read_ohata(h):
    """大畑: <h4 …>品名</h4> … <data value="2250">2,250</data>…円/kg

    トップページと全価格ページ(kakaku.html)で書き方が少し違うので両対応。
    """
    body = _strip(h)
    out = {}
    # 全価格ページ: <h4>品名</h4> … <data value="2250">
    for name, price in re.findall(
        r'<h4[^>]*>\s*([^<]{2,60}?)\s*</h4>.{0,2500}?<data value="(\d+)"', body, re.S
    ):
        v = _num(price)
        if v:
            out.setdefault(name.strip(), v)
    # トップページ: <p>品名</p><figure> … >2,250<small>円/kg
    for name, price in re.findall(
        r'<p[^>]*>([^<]{2,40})</p>\s*<figure.{0,900}?>([\d,]+)<small>\s*円/kg', body, re.S
    ):
        v = _num(price)
        if v:
            out.setdefault(name.strip(), v)
    return out


def read_anjyo(h):
    """安城貿易: <div class="name">給湯器</div><div class="price">470<span..."""
    out = {}
    for name, price in re.findall(
        r'<div class="name">(.{1,60}?)</div>\s*'
        r'<div class="price">([\d,]+)<span', _strip(h), re.S
    ):
        v = _num(price)
        n = _clean(name)
        if v and n:
            out.setdefault(n, v)
    return out


READERS = {
    "dokin": read_dokin,
    "nagasawa": read_nagasawa,
    "ohata": read_ohata,
    "anjyo": read_anjyo,
}


def find_price(prices, aliases):
    """その会社の一覧から、呼び名の候補に当たるものを探す。

    候補は書いた順に見て、最初に当たったものを採る（狭い言い方を先に書くこと）。
    """
    for alias in aliases:
        if alias in prices:              # 完全一致を優先
            return prices[alias]
    for alias in aliases:
        for name, v in prices.items():   # 次に部分一致
            if alias in name:
                return v
    return None


def build_compare(fetch, prev=None):
    """各社を読んで、品目ごとに横並びの表を組み立てる。

    fetch は collect.py の取得関数（URL→bytes）をそのまま渡す。
    """
    by_dealer = {}
    for label, urls, key in DEALERS:
        prices = {}
        for url in urls:
            try:
                html = fetch(url).decode("utf-8", errors="replace")
                got = READERS[key](html)
                if not got:
                    raise ValueError("価格が1件も読めません")
                for k, v in got.items():
                    prices.setdefault(k, v)   # 先に読んだページを優先
            except Exception as e:
                print(f"  ! 他社価格({label} {url}): {e}", file=sys.stderr)
        if prices:
            by_dealer[label] = prices
        else:
            print(f"  ! 他社価格({label})は1件も読めませんでした", file=sys.stderr)

    if not by_dealer:
        return None

    prev_rows = {r["name"]: r for r in (prev or {}).get("rows", [])}
    rows = []
    for group, disp, aliases in COMPARE:
        cells = []
        for label in by_dealer:
            v = find_price(by_dealer[label], aliases)
            if v is not None:
                cells.append({"dealer": label, "value": v})
        if len(cells) < 2:      # 1社しか出ない品目は比較にならないので出さない
            continue
        best = max(c["value"] for c in cells)
        for c in cells:
            c["best"] = c["value"] == best
        cells.sort(key=lambda c: -c["value"])

        row = {"group": group, "name": disp, "cells": cells,
               "spread": best - min(c["value"] for c in cells)}
        old = prev_rows.get(disp)
        if old:
            old_best = max((c["value"] for c in old.get("cells", [])), default=None)
            if old_best is not None:
                d = best - old_best
                row["diff"] = f"{d:+,}" if d else "0"
        rows.append(row)

    return {"dealers": list(by_dealer), "rows": rows} if rows else None
