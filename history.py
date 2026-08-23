#!/usr/bin/env python3
"""各指標の3ヶ月分の推移を集めて、簡易チャート用の数字を作る。

2種類ある:
  1. 取得元に過去分がある指標（銅建値・日経平均・NYダウ・ビットコイン・ドル円）
     → 毎回まるごと取り直す。いつでも3ヶ月そろう。
  2. 取得元に過去分がない指標（金・銀・鉄スクラップ・基板）
     → 毎朝その日の値を history.json に足していく。日がたつほど伸びる。

追加ライブラリなし（標準ライブラリのみ）。
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
JST = timezone(timedelta(hours=9))
HIST_PATH = os.path.join(HERE, "history.json")

DAYS = 92          # 何日ぶん残すか（およそ3ヶ月）
MIN_POINTS = 3     # これ未満の点数ならチャートを出さない


def _today():
    return datetime.now(JST).strftime("%Y-%m-%d")


def load():
    """これまでの記録を読む。無ければ空。"""
    try:
        with open(HIST_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(hist):
    with open(HIST_PATH, "w", encoding="utf-8") as f:
        json.dump(hist, f, ensure_ascii=False, indent=0, sort_keys=True)


def _trim(series):
    """古すぎる分を捨てる。"""
    limit = (datetime.now(JST) - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    return {d: v for d, v in series.items() if d >= limit}


# ---- 過去分が取れる指標 -------------------------------------------------

def from_jx(fetch, url):
    """JX金属の改定履歴から、銅建値の推移を作る。"""
    h = fetch(url).decode("utf-8", errors="replace")
    out = {}
    # 年ごとの表が並んでいるので、全部の年を見る
    for year, block in re.findall(
        r'accordion_label">\s*(\d{4})年\s*</span>(.*?)(?=accordion_label"|\Z)', h, re.S
    ):
        for mo, day, val in re.findall(
            r">\s*(\d{1,2})月(\d{1,2})日\s*</th>\s*<td[^>]*>\s*([\d,]+)\s*円", block
        ):
            d = f"{year}-{int(mo):02d}-{int(day):02d}"
            out[d] = int(val.replace(",", ""))
    return out


def from_yahoo(fetch, symbol):
    """Yahoo!ファイナンスの3ヶ月の終値。"""
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           "?range=3mo&interval=1d")
    r = json.loads(fetch(url))["chart"]["result"][0]
    closes = r["indicators"]["quote"][0]["close"]
    out = {}
    for ts, c in zip(r["timestamp"], closes):
        if c is None:
            continue
        d = datetime.fromtimestamp(ts, JST).strftime("%Y-%m-%d")
        out[d] = round(float(c), 2)
    return out


def from_coingecko(fetch):
    """ビットコインの90日ぶん（円）。"""
    url = ("https://api.coingecko.com/api/v3/coins/bitcoin/market_chart"
           "?vs_currency=jpy&days=90&interval=daily")
    out = {}
    for ms, v in json.loads(fetch(url))["prices"]:
        d = datetime.fromtimestamp(ms / 1000, JST).strftime("%Y-%m-%d")
        out[d] = round(float(v))
    return out


def from_frankfurter(fetch):
    """ドル円の3ヶ月ぶん。"""
    end = datetime.now(JST).strftime("%Y-%m-%d")
    start = (datetime.now(JST) - timedelta(days=DAYS)).strftime("%Y-%m-%d")
    url = f"https://api.frankfurter.app/{start}..{end}?from=USD&to=JPY"
    rates = json.loads(fetch(url))["rates"]
    return {d: round(float(v["JPY"]), 2) for d, v in rates.items()}


# ---- まとめ役 -----------------------------------------------------------

def _num(s):
    """「2,360,000」のような表記を数にする。"""
    if isinstance(s, (int, float)):
        return float(s)
    s = re.sub(r"[^\d.]", "", str(s))
    return float(s) if s else None


def build(fetch, jx_url, data):
    """history.json を更新して、画面に渡す推移データを返す。

    data は collect.py が組み立てた data.json の中身。
    そこに出ている「今日の値」を記録に足していく。
    """
    hist = load()
    today = _today()

    # 1) 過去分が取れるものは、まるごと取り直す
    fresh = [
        ("銅建値", lambda: from_jx(fetch, jx_url)),
        ("日経平均", lambda: from_yahoo(fetch, "%5EN225")),
        ("NYダウ", lambda: from_yahoo(fetch, "%5EDJI")),
        ("ビットコイン", lambda: from_coingecko(fetch)),
        ("ドル円", lambda: from_frankfurter(fetch)),
    ]
    for name, getter in fresh:
        try:
            got = getter()
            if got:
                hist[name] = _trim(got)
        except Exception as e:
            print(f"  ! {name}の推移が取れません: {e}", file=sys.stderr)

    # 2) 過去分が取れないものは、今日の値を足す
    prices = data.get("manual") or {}
    for row in list(prices.get("tiles", [])) + list(prices.get("rows", [])):
        name, v = row.get("name", ""), _num(row.get("value"))
        if not name or v is None:
            continue
        key = _hist_key(name)
        if key in ("銅建値", "ビットコイン", "日経平均", "NYダウ", "ドル円"):
            continue                       # 上でまるごと取り直した分
        hist.setdefault(key, {})[today] = v

    fx = data.get("fx")
    if fx and fx.get("usdjpy"):
        hist.setdefault("ドル円", {})[today] = float(fx["usdjpy"])

    for row in (data.get("boards") or {}).get("rows", []):
        v = _num(row.get("value"))
        if v is not None:
            hist.setdefault(f"基板:{row['name']}", {})[today] = v

    hist = {k: _trim(v) for k, v in hist.items()}
    save(hist)

    # 3) 画面用に、日付順の並びにして返す（点が少ないものは出さない）
    out = {}
    for k, series in hist.items():
        if len(series) < MIN_POINTS:
            continue
        days = sorted(series)
        out[k] = {"d": days, "v": [series[d] for d in days]}
    return out


def _hist_key(name):
    """画面の表示名から、記録用の名前を作る。

    「銅建値（8/21改定）」「東鉄名古屋二級(8/22)」のように日付が付くので、
    括弧から先を落として、日々ぶれない名前にする。
    """
    return re.sub(r"[（(].*$", "", name).strip()
