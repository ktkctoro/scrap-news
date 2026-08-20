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
        "https://www.dokindokin.com/scrap_type/lead/",
        "https://www.dokindokin.com/scrap_type/stainless/",
        "https://www.dokindokin.com/scrap_type/iron/",
    ], "dokin"),
    ("長澤", ["https://nagasawametal.com/purchase-items/"], "nagasawa"),
    ("大畑", ["https://www.ohata.org/kakaku.html"], "ohata"),
    ("安城貿易", ["https://anjyo-t.com/scrap_miscellaneous.html"], "anjyo"),
    ("宝源", ["https://hougen-tokyo.jp/"], "hougen"),
    ("浜屋", ["https://hamaya-material.com/product"], "hamaya"),
    ("ケイワイ", ["https://www.k-y-system.jp/trader/list/"], "kys"),
    ("キバセン", ["https://kibasen.net/"], "kibasen"),
]

# ---- 比べる品目 --------------------------------------------------------
# 「画面に出す名前」と、それに当たる各社での言い方（部分一致で探す）。
# 各社で呼び名が違うので、ここで橋渡しをしている。
# 品目を足したいときは、この表に1行足すだけ。
COMPARE = [
    # (分野, 画面に出す名前, 各社での言い方)
    ("銅", "ピカ銅", ["ピカ銅", "ピカ線", "上銅"]),
    ("銅", "並銅", ["並銅", "=銅"]),
    ("銅", "込銅", ["込銅"]),
    ("銅", "下銅", ["下銅"]),
    ("銅", "銅ダライ粉", ["銅ダライ粉", "銅ダライ"]),

    ("電線", "雑線(銅率80%)", ["雑電線(銅率80%)", "1本線80%赤", "一本線(80%)"]),
    ("電線", "雑線(銅率60〜65%)", ["雑電線(銅率65%)", "3本線60%赤", "三本線(60%)"]),
    ("電線", "VA線・F線", ["ＶＡ線(巻き)", "VA線", "F線(42%)"]),
    ("電線", "家電線", ["家電線"]),
    ("電線", "エアコンパイプ", ["エアコンパイプ", "空調銅配管", "エアコン管"]),

    ("真鍮・砲金", "砲金", ["砲金(青銅)_付物なし", "砲金（上）", "砲金"]),
    ("真鍮・砲金", "込砲金", ["込砲金"]),
    ("真鍮・砲金", "真鍮(上)", ["真鍮（上）", "真鍮/黄銅", "真鍮", "黄銅"]),
    ("真鍮・砲金", "込真鍮", ["込真鍮", "込み真鍮"]),
    ("真鍮・砲金", "真鍮ダライ粉", ["真鍮ダライ粉", "真鍮粉"]),

    ("アルミ", "アルミ(上)", ["アルミ（上）", "Aサッシ", "アルミ合金・新切れ", "=アルミ"]),
    ("アルミ", "アルミサッシ", ["アルミサッシ", "アルミサッシバラ", "Aサッシ"]),
    ("アルミ", "アルミガラ", ["アルミガラA", "アルミガラ"]),
    ("アルミ", "アルミ缶(プレス)", ["アルミ缶（プレス）", "アルミ缶プレス"]),
    ("アルミ", "アルミラジエーター", ["アルミラジエーター(付物なし)", "アルミラジエター異物無", "アルミラジエーター"]),
    ("アルミ", "アルミホイール", ["アルミホイール鉄無", "アルミホイールA_付物なし", "アルミホイール"]),

    ("亜鉛・鉛", "亜鉛", ["亜鉛_付物なし", "亜鉛・丹入", "亜鉛"]),
    ("亜鉛・鉛", "込亜鉛", ["込亜鉛"]),
    ("亜鉛・鉛", "鉛(上)・鉛管", ["鉛（上）", "上鉛・鉛管", "鉛管(えんかん)_付物なし", "鉛管", "=鉛"]),
    ("亜鉛・鉛", "鉛(下)・込鉛", ["鉛（下）", "込鉛"]),
    ("亜鉛・鉛", "バランスウエイト", ["バランスウェイト(鉛)A_付物なし", "バランスウエイト", "バランスウェイト"]),

    # 基板（浜屋・ケイワイ・大畑）
    ("基板", "基板SS", ["基板SS", "ＳＳクラス基板", "SSランク基板"]),
    ("基板", "基板S", ["基板Ｓ", "Ｓクラス基板", "S基板"]),
    ("基板", "基板A", ["基板A(両面実装)", "Ａクラス基板", "A基板"]),
    ("基板", "基板B", ["基板B(片面実装)", "Ｂクラス基板", "B基板"]),
    ("基板", "基板C", ["基板C(ノートPC)", "Ｃクラス基板", "C基板"]),
    ("基板", "基板D", ["基板D(長方形チップ少)", "Ｄクラス基板"]),
    ("基板", "マザーボード", ["らくマザーA", "マザーボード（Ａ）", "パソコン用マザーボード"]),
    ("基板", "ノートPCマザー", ["マザーボードノート（上）", "ノートPC マザーボードMIX", "基板A(ノートPC)"]),
    ("基板", "PCメモリー", ["ＰＣメモリー基板", "メモリー", "パソコン用メモリーA"]),
    ("基板", "デスクトップPC", ["デスクトップPC", "パソコン屑(デスクトップPC,ノートPC)"]),
    ("基板", "リレー", ["リレー (接点付き)", "リレー混合"]),
    ("基板", "携帯電話基板", ["携帯電話基板"]),
    ("基板", "携帯電話(電池なし)", ["携帯電話（電池なし）", "携帯電話本体(電池無)", "携帯電話本体（電池なし）", "携帯電話本体"]),
    ("基板", "スマートフォン", ["スマートフォン", "スマートフォン（電池なし）", "スマートフォン本体"]),
    ("基板", "CPUセラ(上)", ["ＣＰＵセラＳ（両面金）", "ＣＰＵセラ異物なし", "CPU-SS", "CPUセラミック（紫）"]),
    ("基板", "CPU黒", ["ＣＰＵプラ黒", "ＣＰＵブラック", "CPU(黒)"]),
    ("基板", "CPU緑(下)", ["ＣＰＵプラB(金属板有り)", "ＣＰＵグリーン（下）", "CPU(緑)"]),
    ("基板", "IC正方形", ["ＩＣチップ正方形ミックス", "ＩＣ（正方形混合）", "IC(正方形)"]),
    ("基板", "IC長方形", ["ＩＣチップ長方形ミックス", "ＩＣ（長方形混合）", "IC(長方形)"]),
    ("基板", "電源基板", ["電源基板A(電源1)", "電源基板(鉄なし)", "内蔵電源"]),
    ("基板", "家電基板", ["家電基板", "家電基板A(緑・青)"]),
    ("基板", "HDD基板", ["HDD制御基板", "ＨＤＤ基板"]),
    ("基板", "PCカード", ["PCカード基板", "ＰＣカード", "PCカード"]),

    ("雑品", "給湯器", ["ガス給湯器", "給湯器"]),
    ("雑品", "黒モーター", ["黒モーターA", "黒モーター", "Bモーター"]),
    ("雑品", "ガスメーター", ["ガスメーター（ｱﾙﾐ外装）", "ガスメーター(アルミ外装)", "ガスメーター"]),
    ("雑品", "車バッテリー(鉛)", ["自動車用 鉛バッテリー", "車バッテリー", "バッテリー（上）", "バッテリー"]),
    ("雑品", "安定器", ["安定器"]),
    ("雑品", "工業雑品", ["工業雑品（上）", "工業雑品"]),
    ("雑品", "ステンレス", ["ステンレス（下）", "ステンレス"]),
    ("雑品", "鉄(B・ギロB)", ["ギロＢ", "鉄B", "=鉄"]),
]


# この分野は、書いた順ではなく「高い品目から順」に並べ替えて出す。
# 基板は等級と部品が入り混じるので、単価の高い順のほうが探しやすい。
SORT_BY_PRICE = {"基板"}


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


def read_hougen(h):
    """宝源: <div class="scrap_name">鉄</div> … <span class="scrap_kakaku">44</span>"""
    out = {}
    for name, price in re.findall(
        r'<div class="scrap_name">\s*(.{1,40}?)\s*</div>.{0,200}?'
        r'<span class="scrap_kakaku">\s*([\d,]+)\s*</span>', _strip(h), re.S
    ):
        v = _num(price)
        n = _clean(name)
        if v and n:
            out.setdefault(n, v)
    return out


def read_hamaya(h):
    """浜屋: <h4 class="product-card_title">基板 SS</h4> … <span>7,340</span>…円~/kg"""
    out = {}
    for name, price in re.findall(
        r'<h4 class="product-card_title">\s*(.{1,40}?)\s*</h4>.{0,600}?'
        r'<span>\s*([\d,]+)\s*</span>\s*<small>', _strip(h), re.S
    ):
        v = _num(price)
        n = _clean(name)
        if v and n:
            out.setdefault(n, v)
    return out


def read_kys(h):
    """ケイワイ: <p>ＳＳクラス基板</p><div class="catPrice">買取価格<span class="num">6,590円/kg前後"""
    out = {}
    for name, price in re.findall(
        r'<p>([^<]{1,40})</p>\s*<div class="catPrice">買取価格'
        r'<span class="num">\s*([\d,]+)\s*円', _strip(h), re.S
    ):
        v = _num(price)
        n = name.strip()
        if v and n:
            out.setdefault(n, v)
    return out


def read_kibasen(h):
    """キバセン: <span class="name">SSランク基板</span><span class="price">6900 円/kg</span>"""
    out = {}
    for name, price in re.findall(
        r'<span class="name">\s*(.{1,40}?)\s*</span>\s*'
        r'<span class="price">\s*([\d,]+)\s*円', _strip(h), re.S
    ):
        v = _num(price)
        n = _clean(name)
        if v and n:
            out.setdefault(n, v)
    return out


READERS = {
    "dokin": read_dokin,
    "hamaya": read_hamaya,
    "kys": read_kys,
    "kibasen": read_kibasen,
    "nagasawa": read_nagasawa,
    "ohata": read_ohata,
    "anjyo": read_anjyo,
    "hougen": read_hougen,
}


def find_price(prices, aliases):
    """その会社の一覧から、呼び名の候補に当たるものを探す。

    候補は書いた順に見て、最初に当たったものを採る（狭い言い方を先に書くこと）。
    先頭に「=」を付けた候補は完全一致のみ。「銅」「鉄」のような短い語が
    「銅トランスコア」「鉄付外装」のような別品目を拾うのを防ぐため。
    """
    plain = [a.lstrip("=") for a in aliases]
    for a in plain:
        if a in prices:                  # まず完全一致
            return prices[a]
    for a in aliases:
        if a.startswith("="):            # 完全一致だけの候補は部分一致に使わない
            continue
        for name, v in prices.items():
            if a in name:
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

    # 指定した分野だけ、いちばん高い値の順に並べ替える（分野の並び順は変えない）
    out = []
    i = 0
    while i < len(rows):
        g = rows[i]["group"]
        j = i
        while j < len(rows) and rows[j]["group"] == g:
            j += 1
        chunk = rows[i:j]
        if g in SORT_BY_PRICE:
            chunk.sort(key=lambda r: -max(c["value"] for c in r["cells"]))
        out.extend(chunk)
        i = j

    return {"dealers": list(by_dealer), "rows": out} if out else None
