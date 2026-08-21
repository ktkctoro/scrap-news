#!/usr/bin/env python3
"""スクラップ今日 — 記事と為替をあつめて data.json を書き出す。

標準ライブラリだけで動く（pip install 不要）。
使い方:  python collect.py
"""

import difflib
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime, timezone, timedelta

import dealers

HERE = os.path.dirname(os.path.abspath(__file__))
JST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; scrap-news/1.0)"

# ---- 拾うキーワード -------------------------------------------------
# (分類, 検索語, さかのぼる日数, その検索語から拾う上限)。
# 日数を書かなければ7日、上限を書かなければ制限なし。
# 法規制は動きが少ないぶん見落とすと痛いので、60日さかのぼる。
# 話題が多すぎてニュース欄を埋めてしまう検索語には上限をつける。
QUERIES = [
    ("mkt", "銅 建値"),
    ("mkt", "亜鉛 建値"),
    ("mkt", "アルミ二次地金"),
    ("mkt", "非鉄金属 相場"),
    ("mkt", "鉄スクラップ 価格"),
    ("mkt", "金 相場 地金"),
    ("law", "金属盗対策法", 60),
    ("law", "金属くず ヤード 条例", 60),
    ("law", "特定金属くず買受業", 60),
    ("law", "古物営業法", 60),
    ("law", "古物商 金属", 60),
    ("law", "廃棄物処理法 改正", 60),
    ("law", "廃棄物処理法 スクラップ", 60),
    ("law", "再資源化事業 高度化法", 60),
    ("law", "雑品スクラップ 輸出 規制", 60),
    ("law", "フロン排出抑制法", 60),
    ("gen", "スクラップ 盗難"),
    ("gen", "非鉄金属 リサイクル"),
    ("gen", "エアコン 室外機 盗難"),
    ("dc", "データセンター 銅 需要"),
    ("dc", "データセンター 電力設備 投資"),
    ("dc", "サーバー 廃棄 リサイクル"),
    ("btc", "ビットコイン 相場", 7, 5),   # 話題が多いので5本まで
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
    # 法規まわり（スクラップ業の許認可・規制に関わる語）
    "古物", "再資源化", "フロン", "バーゼル", "ヤード",
    # 資産の値動き（金と並べて見たい）
    "ビットコイン", "BTC", "暗号資産",
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
    "市場の規模", "シェア、成長率", "発売のお知らせ", "業務提携を締結",
    # 暗号資産まわりのノイズ（取引所の事務連絡・値動き予想・解説記事）
    "ハードフォーク", "入出金", "メンテナンス", "価格予想", "価格予測",
    "上昇の可能性", "解説", "週刊", "ロードマップ", "アルトコイン",
    "相場分析", "ショート清算", "テクニカル",
    # 広告・ランキング記事・PR・セミナー告知
    "人気ランキング", "無料査定", "買取フェア", "鉱山株", "ソフトボール",
    "プレスリリース", "セミナー", "オープン！", "NEW OPEN", "徹底解説",
    "億ドルへ", "開催中止", "録画配信",
    # 海外の金・宝飾相場（うちの買値と関係しない）
    "ベトナム", "SJC", "ルピア", "金指輪", "金リング", "テール",
]

# 単独では拾いすぎる語。右の語も一緒に入っているときだけ残す。
# （室外機は破裂・水没のニュースが多く、盗難の話だけが商売に効く）
CONDITIONAL = {
    "室外機": ["盗", "窃盗", "被害", "逮捕", "買取", "リサイクル"],
}

# 媒体そのものが株・相場データ専門で、毎回ノイズになるもの。
# Googleニュースは媒体を「日本経済新聞」と「nikkei.com」のように
# 表示名とドメインの両方の書き方で返してくるので、両方書いておく。
# 判定は大文字小文字を区別しない。
NG_SOURCES = [
    "vietnam.vn", "laodong.vn", "biggo", "simplywall.st",
    "traders union", "tradersunion",
    "newscast", "アットプレス", "atpress", "ドリームニュース", "dreamnews",
    "gold price", "goldprice", "vt markets", "vtmarkets", "tradingkey",
    "moomoo", "yahoo!ファイナンス", "finance.yahoo", "株探", "kabutan",
    "ログミーfinance", "logmi", "investing.com", "まぐまぐ", "mag2",
    # 暗号資産の取引所・値動きツール系（記事ではなく価格表や宣伝が多い）
    "bybit", "phemex", "panews", "bitbank", "coincheck", "zaif",
]

# ドメイン表記で来たときに、画面で読みやすい名前に直す
SOURCE_NAMES = {
    "nikkei.com": "日本経済新聞",
    "news.yahoo.co.jp": "Yahoo!ニュース",
    "japanmetaldaily.com": "日刊鉄鋼新聞",
    "nikkan.co.jp": "日刊工業新聞",
}


def is_relevant(title, source):
    """商売に効く記事かどうかを見出しと媒体で判定する。"""
    src = source.lower()
    if any(w in src for w in NG_SOURCES):
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
    ("btc", ["ビットコイン", "BTC", "暗号資産", "仮想通貨"]),
    ("law", ["金属盗", "条例", "改正", "届出", "規制", "警察庁", "法案", "施行", "買受業",
             "古物", "廃棄物処理法", "リサイクル法", "再資源化", "バーゼル", "フロン",
             "義務化", "省令", "政令"]),
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
LABELS = {"mkt": "相場", "law": "法規制", "gen": "業界", "dc": "AI・DC", "btc": "ビットコイン"}

FEED = "https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"
FX_URL = "https://api.frankfurter.app/latest?from=USD&to=JPY"

# 建値・金銀・鉄スクラップの公表ページ（どれも1日1回読むだけ）
JX_CUPRICE_URL = "https://www.jx-nmm.com/cuprice/"
TANAKA_URL = "https://gold.tanaka.co.jp/commodity/souba/"
TOKYO_STEEL_URL = "https://www.tokyosteel.co.jp/scrapprice/"
BTC_URL = ("https://api.coingecko.com/api/v3/simple/price"
           "?ids=bitcoin&vs_currencies=jpy&include_24hr_change=true")
# 基板の買取価格（K&Yシステムの公開価格表）
KYS_URL = "https://www.k-y-system.jp/trader/list/"
# 載せる品目。ページ上の表記そのまま（全角・半角も同じに）で書くこと。
KYS_ITEMS = [
    "メモリー",
    "ＣＰＵグリーン（下）",
    "電源基板(鉄なし)",
    "Ｃクラス基板",
    "Ｄクラス基板",
    "マザーボード（Ｃ）",
]
# 株価指数はYahoo!ファイナンス（米国版）の公開データから。^N225=日経平均, ^DJI=NYダウ
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d"

# 東京製鐵の価格表のうち、画面に出す拠点と等級。変えたいときはここ。
TS_PLANT = "名古屋"   # 価格表の列見出しに含まれる語（名古屋サテライト）
TS_GRADE = "二級"     # 品名。表では「二　　級」のように空白入りで載っている


def fetch(url, timeout=20, tries=3, wait=4):
    """取りにいく。断られたときは少し待ってやり直す。

    相手のサーバーが混んでいて一時的に断ってくること（503など）があるので、
    間をあけて数回試す。それでもだめなら、そのまま失敗として返す。
    """
    last = None
    ctx = ssl.create_default_context()
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.read()
        except Exception as e:
            last = e
            if i < tries - 1:
                time.sleep(wait * (i + 1))
    raise last


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
        source = source.strip()
        return head.strip(), SOURCE_NAMES.get(source.lower(), source)
    return title.strip(), ""


def _norm_title(title):
    """見出しから飾りと記号を落として、比べやすい形にする。"""
    t = re.sub(r"[【（(\[].{0,12}?[】）)\]]", "", title)
    return re.sub(r"[^0-9A-Za-z぀-ヿ一-鿿]", "", t)


def _bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)}


def same_story(a, b):
    """同じ出来事を伝える記事かどうかを、見出しの似かたで判断する。

    同じ事件を各社が少しずつ違う言い回しで書くので、前から順に
    文字を比べるやり方（difflib）と、2文字組の重なり具合の
    両方を見て、どちらかが基準を超えたら同じ話とみなす。

    ただし相場の記事は書き方がそっくりなので、出てくる数字が
    まったく別なら（例：亜鉛建値67万円と銅建値236万円）、
    別の話とみなして基準をぐっと厳しくする。
    """
    if not a or not b:
        return False

    na, nb = set(re.findall(r"\d+", a)), set(re.findall(r"\d+", b))
    both_have_numbers = bool(na) and bool(nb)
    if both_have_numbers and not (na & nb):
        # 数字がまったく重ならない＝別の日・別の品目の可能性が高い
        return difflib.SequenceMatcher(None, a, b).ratio() >= 0.70

    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.50:
        return True
    A, B = _bigrams(a), _bigrams(b)
    if not A or not B:
        return False
    return len(A & B) / len(A | B) >= 0.32


def merge_same_stories(items):
    """同じ出来事の記事を1本にまとめる。新しいほうを残す。

    まとめた本数は dups に入れて、画面に「他2件」と出せるようにする。
    """
    kept, norms = [], []
    for it in items:
        n = _norm_title(it["title"])
        hit = None
        for i, prev in enumerate(norms):
            if same_story(n, prev):
                hit = i
                break
        if hit is None:
            kept.append(it)
            norms.append(n)
        else:
            kept[hit]["dups"] = kept[hit].get("dups", 0) + 1
    return kept


def dedupe_key(title):
    """同じ話題の記事を1本にまとめるための見出しキー。
    【画像】【速報】のような飾りと記号を落としてから比べる。"""
    t = re.sub(r"[【（(\[].{0,10}?[】）)\]]", "", title)
    t = re.sub(r"[^0-9A-Za-z぀-ヿ一-鿿]", "", t)
    return t[:30]


def collect_articles(default_days=7):
    seen = set()
    items = []
    now = datetime.now(JST)

    for entry in QUERIES:
        cat, query = entry[0], entry[1]
        days = entry[2] if len(entry) > 2 else default_days
        cap = entry[3] if len(entry) > 3 else None
        taken = 0
        cutoff = now - timedelta(days=days)
        q = urllib.parse.quote(f"{query} when:{days}d")
        try:
            raw = fetch(FEED.format(q=q))
            root = ET.fromstring(raw)
        except Exception as e:
            print(f"  ! 取得失敗 [{query}]: {e}", file=sys.stderr)
            continue

        for node in root.iterfind(".//item"):
            if cap is not None and taken >= cap:
                break
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
            taken += 1
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
    before = len(items)
    items = merge_same_stories(items)   # 新しい順に見て、同じ話は1本にまとめる
    if before != len(items):
        print(f"  同じ出来事の記事 {before - len(items)} 本を1本にまとめました")
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


# ---- 東京製鐵の鉄スクラップ購入価格（PDF） ------------------------------
# 価格はPDFでしか公表されないので、PDFの中の文字を自力で読む。
# PDFは文字を圧縮した塊(ストリーム)で持っていて、日本語は番号(CID)で
# 書かれている。番号と文字の対応表(ToUnicode CMap)もPDFの中にあるので、
# それを使って番号を文字に戻す。追加ライブラリは使わない。

def _pdf_cmap(raw):
    """PDFの中の「番号→文字」対応表を集める。"""
    cmap = {}
    for s in re.findall(rb"stream\r?\n(.*?)endstream", raw, re.S):
        try:
            data = zlib.decompress(s)
        except Exception:
            continue
        if b"beginbfchar" not in data and b"beginbfrange" not in data:
            continue
        for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
            for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                cmap[int(src, 16)] = bytes.fromhex(dst.decode()).decode(
                    "utf-16-be", errors="replace")
        for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
            for lo, hi, dst in re.findall(
                rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block
            ):
                for i in range(int(hi, 16) - int(lo, 16) + 1):
                    cmap[int(lo, 16) + i] = chr(int(dst, 16) + i)
    return cmap


def _pdf_pages(raw):
    """PDFの各ページから (縦位置, 横位置, 文字列) の一覧を取り出す。"""
    cmap = _pdf_cmap(raw)

    def dec_hex(h):
        return "".join(cmap.get(int(h[i:i + 4], 16), "") for i in range(0, len(h), 4))

    def dec_lit(b):
        return (b.replace(rb"\(", b"(").replace(rb"\)", b")")
                 .replace(rb"\\", b"\\").decode("latin-1"))

    pages = []
    for s in re.findall(rb"stream\r?\n(.*?)endstream", raw, re.S):
        try:
            data = zlib.decompress(s)
        except Exception:
            continue
        if b"TJ" not in data and b"Tj" not in data:
            continue
        page, x, y = [], 0.0, 0.0
        for m in re.finditer(
            rb"1 0 0 1 ([\d.\-]+) ([\d.\-]+) Tm"
            rb"|\[(.*?)\]\s*TJ|\((.*?)\)\s*Tj|<([0-9A-Fa-f]+)>\s*Tj",
            data, re.S,
        ):
            if m.group(1) is not None:
                x, y = float(m.group(1)), float(m.group(2))
                continue
            parts = []
            if m.group(3) is not None:
                for lit, hx in re.findall(rb"\((.*?)\)|<([0-9A-Fa-f]+)>", m.group(3), re.S):
                    parts.append(dec_lit(lit) if lit else dec_hex(hx.decode()))
            elif m.group(4) is not None:
                parts.append(dec_lit(m.group(4)))
            elif m.group(5) is not None:
                parts.append(dec_hex(m.group(5).decode()))
            text = "".join(parts).strip()
            if text:
                page.append((y, x, text))
        if page:
            pages.append(page)
    return pages


def _ts_cell(page, plant, grade):
    """価格表ページから、指定の拠点×品名の数字を1つ取り出す。"""
    # 拠点の列見出しの横位置
    plant_x = None
    for _, x, t in page:
        if plant in t:
            plant_x = x
            break
    if plant_x is None:
        return None
    # 品名の行（「二　　級」→「二級」に詰めて比べる）を探し、
    # その行の数字のうち、列見出しに横位置がいちばん近いものを取る
    best = None
    for y, x, t in page:
        if re.sub(r"\s", "", t) != grade:
            continue
        for y2, x2, t2 in page:
            if abs(y2 - y) < 3 and re.fullmatch(r"-?[\d,]+", t2):
                d = abs(x2 - plant_x)
                if d < 45 and (best is None or d < best[0]):
                    best = (d, t2)
        break
    return best[1] if best else None


def parse_tokyo_steel(raw, plant=TS_PLANT, grade=TS_GRADE):
    """東京製鐵の価格表PDFから 値・前回比・適用日 を取り出す。"""
    price_page = diff_page = None
    asof = ""
    for page in _pdf_pages(raw):
        joined = "".join(t for _, _, t in page)
        if "購入価格表" in joined:
            price_page = page
            m = re.search(r"(\d{1,2})月\s*(\d{1,2})日\s*午前", joined)
            if m:
                asof = f"{int(m.group(1))}/{int(m.group(2))}"
        elif "改定幅" in joined:
            diff_page = page

    if price_page is None:
        return None
    value = _ts_cell(price_page, plant, grade)
    if value is None:
        return None
    if not (10_000 < int(value.replace(",", "")) < 200_000):
        raise ValueError(f"鉄スクラップらしくない数字です: {value}")

    diff = ""
    if diff_page is not None:
        d = _ts_cell(diff_page, plant, grade)
        if d is not None:
            diff = "0" if d in ("0", "-0") else (d if d.startswith("-") else "+" + d)
    return {"value": value, "diff": diff, "asof": asof}


def fetch_tokyo_steel():
    try:
        listing = fetch(TOKYO_STEEL_URL).decode("utf-8", errors="replace")
        links = re.findall(r'href="([^"]*scrapprice[^"]*\.pdf)"', listing)
        if not links:
            raise ValueError("価格表PDFへのリンクが見つかりません")
        pdf_url = urllib.parse.urljoin(TOKYO_STEEL_URL, links[0])  # 先頭が最新
        got = parse_tokyo_steel(fetch(pdf_url))
        if got is None:
            raise ValueError("PDFの中に拠点・品名の表が見つかりません")
        return got
    except Exception as e:
        print(f"  ! 鉄スクラップの取得失敗: {e}", file=sys.stderr)
        return None


def fetch_bitcoin():
    """ビットコインの円建て価格と24時間の変化率（CoinGecko）。"""
    try:
        data = json.loads(fetch(BTC_URL))["bitcoin"]
        jpy = float(data["jpy"])
        if not (1_000_000 < jpy < 1_000_000_000):
            raise ValueError(f"ビットコインらしくない数字です: {jpy}")
        chg = data.get("jpy_24h_change")
        diff = f"{chg:+.1f}%" if chg is not None else ""
        return {"value": f"{int(round(jpy)):,}", "diff": diff}
    except Exception as e:
        print(f"  ! ビットコインの取得失敗: {e}", file=sys.stderr)
        return None


def fetch_index(sym, label):
    """株価指数の直近値と前日比（Yahoo!ファイナンスの公開データ）。"""
    try:
        url = YAHOO_URL.format(sym=urllib.parse.quote(sym))
        meta = json.loads(fetch(url))["chart"]["result"][0]["meta"]
        value = float(meta["regularMarketPrice"])
        if not (1_000 < value < 500_000):
            raise ValueError(f"{label}らしくない数字です: {value}")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        diff = ""
        if prev:
            d = value - float(prev)
            diff = "0" if abs(d) < 0.5 else f"{d:+,.0f}"
        return {"value": f"{value:,.0f}", "diff": diff}
    except Exception as e:
        print(f"  ! {label}の取得失敗: {e}", file=sys.stderr)
        return None


def parse_kys(html):
    """K&Yの価格表ページから、KYS_ITEMS の品名の買取価格と改定日を取り出す。"""
    pairs = dict(re.findall(
        r'<p>([^<]{1,40})</p>\s*<div class="catPrice">買取価格<span class="num">([^<]+)</span>',
        html,
    ))
    asof = ""
    m = re.search(r"最終更新日&nbsp;\s*\d{4}年(\d{1,2})月(\d{1,2})日", html)
    if m:
        asof = f"{int(m.group(1))}/{int(m.group(2))}"

    rows = []
    for name in KYS_ITEMS:
        raw = pairs.get(name)
        if raw is None:
            print(f"  ! 基板: 「{name}」がページに見つかりません", file=sys.stderr)
            continue
        m2 = re.search(r"([\d,]+)\s*円", raw)
        if not m2:
            print(f"  ! 基板: 「{name}」の価格が読めません: {raw}", file=sys.stderr)
            continue
        price = int(m2.group(1).replace(",", ""))
        if not (10 <= price <= 200_000):
            raise ValueError(f"基板らしくない数字です: {name} {raw}")
        rows.append({"name": name, "value": f"{price:,}", "unit": "円/kg"})
    return {"asof": asof, "rows": rows} if rows else None


def fetch_kys():
    try:
        html = fetch(KYS_URL).decode("utf-8", errors="replace")
        got = parse_kys(html)
        if got is None:
            raise ValueError("ページの中に品目が見つかりません")
        return got
    except Exception as e:
        print(f"  ! 基板買取の取得失敗: {e}", file=sys.stderr)
        return None


def build_boards(prev):
    """基板買取（K&Y）の段を作る。前回の値と比べて前回比も付ける。"""
    got = fetch_kys()
    if got is None:
        if prev:
            print("  ! 基板買取は前回の値を使い回します", file=sys.stderr)
        return prev or None

    prev_rows = {r["name"]: r for r in (prev or {}).get("rows", [])}
    for r in got["rows"]:
        diff = ""
        old = prev_rows.get(r["name"])
        if old:
            d = int(r["value"].replace(",", "")) - int(old["value"].replace(",", ""))
            diff = f"{d:+,}" if d else "0"
        r["diff"] = diff
    return got


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
            "name": f"銅建値（{copper['asof']}改定）",
            "value": copper["value"], "unit": "円/t", "diff": copper["diff"],
        })
    elif _pick(prev_tiles, "銅建値"):
        print("  ! 銅建値は前回の値を使い回します", file=sys.stderr)
        tiles.append(_pick(prev_tiles, "銅建値"))

    steel = fetch_tokyo_steel()
    if steel:
        name = f"東鉄{TS_PLANT}{TS_GRADE}"
        if steel["asof"]:
            name += f"({steel['asof']})"
        tiles.append({
            "name": name,
            "value": steel["value"], "unit": "円/t", "diff": steel["diff"],
        })
    elif _pick(prev_tiles, "東鉄"):
        print("  ! 鉄スクラップは前回の値を使い回します", file=sys.stderr)
        tiles.append(_pick(prev_tiles, "東鉄"))

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

    # 市場もの（ビットコイン・株価指数）。ドル円は画面側が為替の値から足す。
    markets = [
        ("ビットコイン", "円", fetch_bitcoin),
        ("日経平均", "円", lambda: fetch_index("^N225", "日経平均")),
        ("NYダウ", "$", lambda: fetch_index("^DJI", "NYダウ")),
    ]
    for name, unit, getter in markets:
        got = getter()
        if got:
            rows.append({"name": name, "value": got["value"],
                         "unit": unit, "diff": got["diff"]})
        elif _pick(prev_rows, name):
            print(f"  ! {name}は前回の値を使い回します", file=sys.stderr)
            rows.append(_pick(prev_rows, name))

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
    print("基板の買取価格をあつめています…")
    boards = build_boards(prev.get("boards"))
    print("同業各社の価格をあつめています…")
    compare = dealers.build_compare(fetch, prev.get("compare"))

    # ニュースが1件も取れなかった朝は、前回の記事をそのまま残す。
    # （Googleが一時的に断ってくることがある。価格や画面の更新まで
    #   止めてしまわないようにするため。）
    stale = False
    if not items and prev.get("items"):
        print("  ! 記事が取れなかったので前回の記事を使い回します", file=sys.stderr)
        items = prev["items"]
        stale = True

    out = {
        "updated": _now_label(),
        "fx": fx,
        # 画面(index.html)が読む場所の名前が manual のままなのでそのまま使う。
        # 中身は「自動取得(銅・金・銀) + 手入力(アルミ・H2・LME)」の合わせたもの。
        "manual": prices,
        "items": items,
    }
    if boards:
        out["boards"] = boards
    if stale:
        out["items_stale"] = True
    if compare:
        out["compare"] = compare
    elif prev.get("compare"):
        print("  ! 同業各社の価格は前回の値を使い回します", file=sys.stderr)
        out["compare"] = prev["compare"]
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"\n完了: {len(items)} 件を {dest} に書き出しました。")


if __name__ == "__main__":
    main()
