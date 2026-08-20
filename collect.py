#!/usr/bin/env python3
"""スクラップ今日 — 記事と為替をあつめて data.json を書き出す。

標準ライブラリだけで動く（pip install 不要）。
使い方:  python collect.py
"""

import json
import os
import re
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
JST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; scrap-news/1.0)"

# ---- 拾うキーワード -------------------------------------------------
# 左が分類、右が検索語。増やしたいときはこの表に足すだけ。
QUERIES = [
    ("mkt", "銅 建値"),
    ("mkt", "非鉄金属 相場"),
    ("mkt", "鉄スクラップ 価格"),
    ("mkt", "金 相場 地金"),
    ("law", "金属盗対策法"),
    ("law", "金属くず ヤード 条例"),
    ("law", "特定金属くず買受業"),
    ("gen", "スクラップ 盗難"),
    ("gen", "非鉄金属 リサイクル"),
    ("gen", "エアコン 室外機 盗難"),
    ("dc", "データセンター 銅 需要"),
    ("dc", "データセンター 電力設備 投資"),
    ("dc", "サーバー 廃棄 リサイクル"),
]

# AI・DC分類はノイズが多いので、この語のどれかを含む記事だけ残す
DC_MUST_HAVE = ["銅", "電線", "変圧器", "電力", "ケーブル", "廃棄", "リサイクル", "回収", "設備投資"]

# ---- 関係ない記事を落とす門番 ---------------------------------------
# Googleニュースは検索語とゆるくしか一致しない記事も返してくる。
# （「金属盗対策法」で将棋や交通事故が返ってくる、など）
# そこで「商売に効く語」がひとつも入っていない見出しは捨てる。
RELEVANT = [
    "銅", "鉄スクラップ", "鉄くず", "スクラップ", "非鉄", "金属", "アルミ",
    "真鍮", "黄銅", "ステンレス", "鉛", "亜鉛", "電線", "ケーブル", "変圧器",
    "室外機", "建値", "地金", "貴金属", "リサイクル", "資源循環",
    "買取", "買受", "廃棄物", "解体",
]

# 逆に、この語が入っていたら商売に関係ないので捨てる。
# 株の話・海外の金相場・広告みたいな市場調査リリースが大半を占めるため。
NG_WORDS = [
    # 株式・決算
    "日経平均", "株価", "騰落", "銘柄", "寄与度", "上場投信", "東証", "TOPIX",
    "決算", "純利益", "営業利益", "四半期", "上方修正", "大量保有", "配当",
    "GDP", "鉱業会社", "株式市場", "押し目買い", "A株",
    # 市場調査リリース（内容がなく件数だけ稼ぐ）
    "市場規模", "市場動向", "調査レポート", "業界分析", "分析レポート",
    "CAGR", "年平均成長率", "成長予測", "産業レポート", "世界市場",
    # 広告・ランキング記事
    "人気ランキング", "無料査定", "買取フェア", "鉱山株", "ソフトボール",
    # 海外の金・宝飾相場（うちの買値と関係しない）
    "ベトナム", "SJC", "ルピア", "金指輪", "金リング", "テール",
]

# 単独では拾いすぎる語。右の語も一緒に入っているときだけ残す。
# （室外機は破裂・水没のニュースが多く、盗難の話だけが商売に効く）
CONDITIONAL = {
    "室外機": ["盗", "窃盗", "被害", "逮捕", "買取", "リサイクル"],
}

# 媒体そのものが株・相場データ専門で、毎回ノイズになるもの
NG_SOURCES = [
    "Vietnam.vn", "Laodong.vn", "BigGo", "simplywall.st", "Traders Union",
    "Newscast.jp", "アットプレス", "ドリームニュース", "Gold Price",
    "VT Markets", "TradingKey", "Moomoo", "Yahoo!ファイナンス", "株探",
    "ログミーFinance", "Investing.com", "まぐまぐ",
]


def is_relevant(title, source):
    """商売に効く記事かどうかを見出しと媒体で判定する。"""
    if any(w in source for w in NG_SOURCES):
        return False
    if any(w in title for w in NG_WORDS):
        return False
    hits = [w for w in RELEVANT if w in title]
    if not hits:
        return False
    # 拾った語が条件付きのものだけなら、相方の語も要る
    return any(
        w not in CONDITIONAL or any(x in title for x in CONDITIONAL[w])
        for w in hits
    )

# 見出しの語で分類する。上から順に判定し、最初に当たったものを採用。
# （同じ記事が複数のキーワードで拾われても分類がぶれないようにするため）
CLASSIFY = [
    ("law", ["金属盗", "条例", "改正", "届出", "規制", "警察庁", "法案", "施行", "買受業"]),
    ("gen", ["盗難", "窃盗", "逮捕", "被害", "火災", "火事"]),
    ("dc", ["データセンター", "生成AI", "AI投資", "半導体工場"]),
    ("mkt", ["建値", "相場", "価格", "市況", "値上げ", "値下げ", "高値", "安値", "需給"]),
]


def classify(title, fallback):
    for cat, words in CLASSIFY:
        if any(w in title for w in words):
            return cat
    return fallback

# 分類の表示名
LABELS = {"mkt": "相場", "law": "法規制", "gen": "業界", "dc": "AI・DC"}

FEED = "https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
FX_URL = "https://api.frankfurter.app/latest?from=USD&to=JPY"

# 建値と金・銀の公表ページ（どちらも1日1回読むだけ）
JX_CUPRICE_URL = "https://www.jx-nmm.com/cuprice/"
TANAKA_URL = "https://gold.tanaka.co.jp/commodity/souba/"


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def parse_pubdate(text):
    """RSSのpubDate（GMT）を日本時間のdatetimeにする。"""
    if not text:
        return None
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(text.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(JST)
        except ValueError:
            continue
    return None


def clean_title(title):
    """Googleニュースの見出しは「見出し - 媒体名」の形。媒体名を切り出す。"""
    if " - " in title:
        head, source = title.rsplit(" - ", 1)
        return head.strip(), source.strip()
    return title.strip(), ""


def dedupe_key(title):
    """同じ話題の記事を1本にまとめるための見出しキー。
    【画像】【速報】のような飾りと記号を落としてから比べる。"""
    t = re.sub(r"[【（(\[].{0,10}?[】）)\]]", "", title)
    t = re.sub(r"[^0-9A-Za-z぀-ヿ一-鿿]", "", t)
    return t[:30]


def collect_articles(days=7):
    seen = set()
    items = []
    cutoff = datetime.now(JST) - timedelta(days=days)

    for cat, query in QUERIES:
        q = urllib.parse.quote(f"{query} when:{days}d")
        try:
            raw = fetch(FEED.format(q=q))
            root = ET.fromstring(raw)
        except Exception as e:
            print(f"  ! 取得失敗 [{query}]: {e}", file=sys.stderr)
            continue

        for node in root.iterfind(".//item"):
            title_raw = (node.findtext("title") or "").strip()
            if not title_raw:
                continue
            title, source = clean_title(title_raw)

            key = dedupe_key(title)
            if key in seen:
                continue

            if not is_relevant(title, source):
                continue

            final = classify(title, cat)
            if final == "dc" and not any(w in title for w in DC_MUST_HAVE):
                continue

            dt = parse_pubdate(node.findtext("pubDate"))
            if dt and dt < cutoff:
                continue

            seen.add(key)
            items.append({
                "cat": final,
                "label": LABELS[final],
                "title": title,
                "source": source,
                "link": (node.findtext("link") or "").strip(),
                "published": dt.isoformat() if dt else "",
            })
        print(f"  ✓ {query} → 累計 {len(items)} 件")

    items.sort(key=lambda x: x["published"], reverse=True)
    return items


def collect_fx():
    try:
        data = json.loads(fetch(FX_URL))
        return {"usdjpy": round(float(data["rates"]["JPY"]), 2), "date": data.get("date", "")}
    except Exception as e:
        print(f"  ! 為替の取得失敗: {e}", file=sys.stderr)
        return None


def parse_jx_copper(html):
    """JX金属のページから最新の銅建値・改定日・前回比を取り出す。

    ページには年ごとの「銅建値改定の履歴」の表があるので、
    いちばん上（今年）の表の最後の行を最新の建値として読む。
    """
    m = re.search(
        r'accordion_label">\s*(\d{4})年\s*</span>(.*?)(?=accordion_label"|\Z)',
        html, re.S,
    )
    if not m:
        return None
    revs = re.findall(
        r">\s*(\d{1,2})月(\d{1,2})日\s*</th>\s*<td[^>]*>\s*([\d,]+)\s*円", m.group(2)
    )
    if not revs:
        return None

    mo, day, val = revs[-1]
    price = int(val.replace(",", ""))
    if not (500_000 < price < 10_000_000):
        # ページの作りが変わって別の数字を拾ってしまったときの保険
        raise ValueError(f"銅建値らしくない数字です: {val}")

    diff = ""
    if len(revs) >= 2:
        d = price - int(revs[-2][2].replace(",", ""))
        diff = f"{d:+,}" if d else "0"
    return {"value": val, "diff": diff, "asof": f"{int(mo)}/{int(day)}"}


def fetch_jx_copper():
    try:
        html = fetch(JX_CUPRICE_URL).decode("utf-8", errors="replace")
        got = parse_jx_copper(html)
        if got is None:
            raise ValueError("ページの中に建値の表が見つかりません")
        return got
    except Exception as e:
        print(f"  ! 銅建値の取得失敗: {e}", file=sys.stderr)
        return None


def parse_tanaka(html):
    """田中貴金属のページから金・銀の店頭買取価格（税込）と前日比を取り出す。"""
    ranges = {"金": (5_000, 100_000), "銀": (50, 2_000)}
    out = {}
    for metal, cls in (("金", "gold"), ("銀", "silver")):
        row = re.search(rf'<tr class="{cls}">(.*?)</tr>', html, re.S)
        if not row:
            continue
        v = re.search(r"purchase_tax[^>]*>\s*([\d,.]+)\s*円", row.group(1))
        d = re.search(r"purchase_ratio[^>]*>\s*([+\-]?[\d,.]+)\s*円", row.group(1))
        if not v:
            continue
        lo, hi = ranges[metal]
        if not (lo < float(v.group(1).replace(",", "")) < hi):
            raise ValueError(f"{metal}らしくない数字です: {v.group(1)}")
        diff = d.group(1) if d else ""
        # 上がった日に「+」が付いていなくても▲で出せるように揃える
        if diff and diff[0] not in "+-" and float(diff.replace(",", "")) != 0:
            diff = "+" + diff
        out[metal] = {"value": v.group(1), "diff": diff}
    return out


def fetch_tanaka():
    try:
        html = fetch(TANAKA_URL).decode("utf-8", errors="replace")
        got = parse_tanaka(html)
        if not got:
            raise ValueError("ページの中に金・銀の表が見つかりません")
        return got
    except Exception as e:
        print(f"  ! 金・銀の取得失敗: {e}", file=sys.stderr)
        return None


def load_previous(dest):
    """前回の data.json。取得に失敗した朝は前回の値を使い回すために読む。"""
    try:
        with open(dest, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _pick(entries, word):
    for e in entries:
        if word in e.get("name", ""):
            return e
    return None


def build_prices(manual, prev):
    """建値（JX金属）と金・銀（田中貴金属）を自動で取り、手入力ぶんと合わせる。

    取れなかったものは前回の値を使い回す（建値は毎日変わるものではないため）。
    manual.json に同じ名前の項目が残っていても、自動のほうを優先して重複させない。
    """
    tiles, rows = [], []
    prev_tiles = prev.get("tiles", [])
    prev_rows = prev.get("rows", [])

    copper = fetch_jx_copper()
    if copper:
        tiles.append({
            "name": f"電気銅建値（{copper['asof']}改定）",
            "value": copper["value"], "unit": "円/t", "diff": copper["diff"],
        })
    elif _pick(prev_tiles, "銅建値"):
        print("  ! 銅建値は前回の値を使い回します", file=sys.stderr)
        tiles.append(_pick(prev_tiles, "銅建値"))

    metals = fetch_tanaka() or {}
    for metal in ("金", "銀"):
        if metal in metals:
            rows.append({
                "name": f"{metal}（店頭買取）",
                "value": metals[metal]["value"], "unit": "円/g",
                "diff": metals[metal]["diff"],
            })
        elif _pick(prev_rows, metal):
            print(f"  ! {metal}は前回の値を使い回します", file=sys.stderr)
            rows.append(_pick(prev_rows, metal))

    # 手入力ぶん（アルミ・鉄スクラップH2・LMEなど）を後ろに足す
    for t in manual.get("tiles", []):
        if "銅建値" in t.get("name", "") and _pick(tiles, "銅建値"):
            continue
        tiles.append(t)
    for r in manual.get("rows", []):
        if any(r.get("name", "").startswith(m) and _pick(rows, m) for m in ("金", "銀")):
            continue
        rows.append(r)

    return {"tiles": tiles, "rows": rows}


def load_manual():
    """アルミ二次地金・鉄スクラップH2・LME銅は無料の公表先がないので手入力ファイルから読む。"""
    path = os.path.join(HERE, "manual.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  ! manual.json の読み込み失敗: {e}", file=sys.stderr)
        return {}


def _now_label():
    """「8/20 7:41」の形にする。Windowsでは %-m が使えないので手で組む。"""
    now = datetime.now(JST)
    return f"{now.month}/{now.day} {now.hour}:{now.minute:02d}"


def main():
    dest = os.path.join(HERE, "data.json")
    prev = load_previous(dest)

    print("記事をあつめています…")
    items = collect_articles()
    print("為替をあつめています…")
    fx = collect_fx()
    print("建値と金・銀をあつめています…")
    prices = build_prices(load_manual(), prev.get("manual") or {})

    out = {
        "updated": _now_label(),
        "fx": fx,
        # 画面(index.html)が読む場所の名前が manual のままなのでそのまま使う。
        # 中身は「自動取得(銅・金・銀) + 手入力(アルミ・H2・LME)」の合わせたもの。
        "manual": prices,
        "items": items,
    }
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n完了: {len(items)} 件を {dest} に書き出しました。")


if __name__ == "__main__":
    main()
