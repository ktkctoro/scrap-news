#!/usr/bin/env python3
"""スクラップ動向レポートを書く（無料版。AIは使わない）。週次と月次の2種類。

  週次: 毎週月曜の朝。1週間の数字の動き。
  月次: 毎月1日の朝。1ヶ月の数字の動き。

材料は data.json と history.json（3ヶ月の推移）。決まった書き方で
段落を組み立てる。
  1段落目: 相場の変化率（週・月）
  2段落目: 上がったもの・下がったものの大きい順
  3段落目: 法規制の新着の見出し
  4段落目: 同業の価格差が大きい品目
その日でなければ何もしない（前回のレポートがそのまま残る）。

2026-10まではClaude APIに書かせていたが、費用をゼロにするためやめた。

使い方:
  py weekly.py            # 月曜なら週次、1日なら月次を書く
  py weekly.py --force    # きょうが何曜でも週次を書く
  py weekly.py --monthly --force

追加ライブラリなし（標準ライブラリのみ）。
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
JST = timezone(timedelta(hours=9))

# history.json の名前 → レポートでの呼び名
KEYS = (("銅建値", "銅建値"), ("東鉄名古屋二級", "鉄二級"), ("金", "金"), ("銀", "銀"),
        ("ドル円", "ドル円"), ("日経平均", "日経平均"), ("NYダウ", "NYダウ"),
        ("ビットコイン", "ビットコイン"))


def _pct(now, past):
    if not past:
        return None
    return (now - past) / past * 100


def _change(series, days_back):
    """推移から「何日前と比べてどうか」を出す。"""
    if not series:
        return None, None
    days = sorted(series)
    now = series[days[-1]]
    target = (datetime.now(JST) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    past = [d for d in days if d <= target]
    if not past:
        return now, None
    return now, _pct(now, series[past[-1]])


def _num(v):
    """銀のように小さい数は小数1桁まで、ほかは整数で。"""
    return f"{v:,.1f}" if v < 1000 else f"{v:,.0f}"


def _md(iso):
    try:
        return f"{int(iso[5:7])}/{int(iso[8:10])}"
    except (TypeError, ValueError):
        return ""


def build_report(data, hist, monthly=False):
    """段落のリストと見出しを返す。"""
    now = datetime.now(JST)
    span, days = ("1ヶ月", 30) if monthly else ("1週間", 7)

    # 相場の変化
    moves = []          # (呼び名, 現在値, 変化率)
    for key, label in KEYS:
        v, p = _change(hist.get(key), days)
        if v is not None and p is not None:
            moves.append((label, v, p))

    paras = []
    if moves:
        paras.append(f"この{span}の相場の動き。" + "、".join(
            f"{label}{_num(v)}（{p:+.1f}%）" for label, v, p in moves) + "。")

        ups = sorted([m for m in moves if m[2] >= 0.05], key=lambda m: -m[2])
        downs = sorted([m for m in moves if m[2] <= -0.05], key=lambda m: m[2])
        s = []
        if ups:
            s.append("上がったのは " + "、".join(f"{m[0]}（{m[2]:+.1f}%）" for m in ups[:3]))
        if downs:
            s.append("下がったのは " + "、".join(f"{m[0]}（{m[2]:+.1f}%）" for m in downs[:3]))
        if s:
            paras.append("。".join(s) + "。")
    else:
        paras.append(f"この{span}の相場は、記録がまだ足りず比べられませんでした。")

    # 法規制の新着
    since = (now - timedelta(days=days)).isoformat()
    laws = sorted([i for i in data.get("items") or []
                   if i.get("cat") == "law" and (i.get("published") or "") >= since],
                  key=lambda i: i.get("published") or "", reverse=True)[:5]
    if laws:
        paras.append(f"この{span}の法規制の記事。" + "／".join(
            f"{i['title']}（{_md(i.get('published'))}）" for i in laws))
    else:
        paras.append(f"この{span}は、法規制の新しい記事がありませんでした。")

    # 同業の価格差
    rows = sorted((data.get("compare") or {}).get("rows", []),
                  key=lambda r: -r.get("spread", 0))[:3]
    if rows:
        s = []
        for r in rows:
            cells = sorted(r["cells"], key=lambda c: -c["value"])
            s.append(f"{r['name']}は{cells[0]['dealer']}{cells[0]['value']:,}円・"
                     f"{cells[-1]['dealer']}{cells[-1]['value']:,}円で差{r['spread']:,}円")
        paras.append("同業の価格差が大きい品目（きょう時点）。" + "、".join(s) + "。")

    # 見出し: いちばん大きく動いたもの
    if moves:
        top = max(moves, key=lambda m: abs(m[2]))
        title = f"{top[0]}が{span}で{top[2]:+.1f}%"
    else:
        title = "スクラップ動向"
    return title, paras


def main():
    now = datetime.now(JST)
    monthly = "--monthly" in sys.argv or os.environ.get("REPORT_KIND", "") == "monthly"
    name = "月次レポート" if monthly else "週次レポート"

    # その日でなくても書かせたいときは --force か FORCE_WEEKLY=1
    force = "--force" in sys.argv or os.environ.get("FORCE_WEEKLY", "") == "1"
    if monthly:
        due = now.day == 1                    # 毎月1日
        when = "1日"
    else:
        due = now.weekday() == 0              # 0=月曜
        when = "月曜"
    if not due and not force:
        print(f"{name}: {when}ではないので飛ばします")
        return

    dest = os.path.join(HERE, "data.json")
    with open(dest, encoding="utf-8") as f:
        data = json.load(f)
    try:
        with open(os.path.join(HERE, "history.json"), encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = {}

    title, paras = build_report(data, hist, monthly)

    # 月次は「先月」ぶんなので、見出しの月は1つ前にする
    prev_month = (now.replace(day=1) - timedelta(days=1))
    key = "monthly" if monthly else "weekly"
    data[key] = {
        "title": title,
        "paragraphs": paras,
        "date": now.strftime("%Y-%m-%d"),
        "label": f"{prev_month.month}月のまとめ" if monthly else f"{now.month}/{now.day}の週",
    }
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{name}: 書きました（{title} / {len(paras)}段落）")


if __name__ == "__main__":
    main()
