#!/usr/bin/env python3
"""スクラップ動向レポートをAIに書かせる。週次と月次の2種類。

  週次: 毎週月曜の朝。先週1週間の動き。
  月次: 毎月1日の朝。先月1ヶ月の動きと、もう少し長い目線。

材料は data.json と history.json（3ヶ月の推移）。
・相場は「1週間の変化」と「1ヶ月の変化」を数字で渡す
・法規制・業界の記事の見出しを渡す
・同業の価格差も渡す
その日でなければ何もしない（前回のレポートがそのまま残る）。

使い方:
  py weekly.py            # 月曜なら週次、1日なら月次を書く
  py weekly.py --force    # きょうが何曜でも週次を書く
  py weekly.py --monthly --force

鍵（ANTHROPIC_API_KEY）が無ければ何もしない。
追加ライブラリなし（標準ライブラリのみ）。
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
JST = timezone(timedelta(hours=9))

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-5"


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


def build_prompt(data, hist, monthly=False):
    now = datetime.now(JST)
    span = "先月1ヶ月" if monthly else "先週1週間"
    L = [f"きょうは{now.year}年{now.month}月{now.day}日。"
         f"{span}のスクラップ相場と業界の動きをまとめる。", ""]

    L.append("【相場の変化】")
    for key in ("銅建値", "東鉄名古屋二級", "金", "銀", "ドル円",
                "日経平均", "NYダウ", "ビットコイン"):
        s = hist.get(key)
        if not s:
            continue
        v, w = _change(s, 7)
        _, m = _change(s, 30)
        if v is None:
            continue
        wt = f"週{w:+.1f}%" if w is not None else "週—"
        mt = f"月{m:+.1f}%" if m is not None else "月—"
        L.append(f"{key} 現在{v:,.0f}（{wt} / {mt}）")

    boards = data.get("boards") or {}
    if boards.get("rows"):
        L.append("")
        L.append("【基板の買取価格（K&Y）】")
        for r in boards["rows"]:
            L.append(f"{r['name']} {r['value']}{r['unit']}（前回比 {r.get('diff') or '±0'}）")

    cmp_ = data.get("compare") or {}
    if cmp_.get("rows"):
        L.append("")
        L.append("【同業の価格差が大きい品目】")
        top = sorted(cmp_["rows"], key=lambda r: -r.get("spread", 0))[:10]
        for r in top:
            cells = "、".join(f"{c['dealer']}{c['value']:,}" for c in r["cells"])
            L.append(f"{r['name']}：{cells}（差{r['spread']:,}円）")

    items = data.get("items") or []
    for label, head in (("法規制", "【法規制の記事】"), ("業界", "【業界の記事】"),
                        ("相場", "【相場の記事】"), ("AI・DC", "【AI・データセンターの記事】")):
        rows = [i for i in items if i.get("label") == label][:14]
        if rows:
            L.append("")
            L.append(head)
            for i in rows:
                L.append(f"・{i['title']}（{i['source']}）")

    if monthly:
        L += [
            "",
            "この材料から、スクラップ買取業の経営者が月初に読む月次レポートを書いてください。",
            "",
            "・見出しなしの短い段落を5つ。1段落は4〜5文、全体で900字程度",
            "・1段落目「先月の相場」: 銅・鉄・貴金属の1ヶ月の動きと、その背景",
            "・2段落目「制度の動き」: 先月固まった制度と、いつまでに何をすべきか",
            "・3段落目「商売の見直し」: 同業の価格差や基板相場から、出し先や選別の見直し案",
            "・4段落目「数字の振り返り」: 1ヶ月の変化率を並べ、効いた要因を整理",
            "・5段落目「今月の重点」: 今月ひと月で取り組むべきことを2〜3点",
            "",
            "・週次より長い目線で書く。1日ごとの上下ではなく、ひと月の流れを説明する",
        ]
    else:
        L += [
            "",
            "この材料から、スクラップ買取業の経営者が月曜の朝に読む週次レポートを書いてください。",
            "",
            "・見出しなしの短い段落を4つ。1段落は3〜4文、全体で600字程度",
            "・1段落目「相場」: 銅・鉄・貴金属の1週間の動きと、その背景",
            "・2段落目「法規制」: 制度の動きと、自社が備えるべきこと",
            "・3段落目「商売のヒント」: 同業の価格差や基板相場から、仕入れ・出し先の判断材料",
            "・4段落目「来週の見通し」: 材料から読み取れる範囲での見通しと注意点",
        ]

    L += [
        "",
        "・材料にない事実を書かない。数字は材料のまま使う",
        "・見通しは断定せず「〜の可能性」「〜に注意」と書く",
        "・専門用語は避け、非エンジニアの経営者が読んで分かる言葉で",
    ]
    return "\n".join(L)


def ask_claude(api_key, prompt, monthly=False):
    body = {
        "model": MODEL,
        "max_tokens": 16000,
        # 週に一度のまとめなので、しっかり考えさせる
        "output_config": {
            "effort": "high",
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "20字以内の見出し"},
                        "paragraphs": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "5つの段落" if monthly else "4つの段落",
                        },
                    },
                    "required": ["title", "paragraphs"],
                    "additionalProperties": False,
                },
            },
        },
        "fallbacks": "default",
        "system": (
            "あなたはスクラップ・非鉄金属買取業「小林商会」のレポート担当です。"
            + ("経営者が月初に5分で読み、その月の方針を決めるのに使えるレポートを書きます。"
               if monthly else
               "経営者が月曜の朝に3分で読み、その週の判断に使えるレポートを書きます。")
        ),
        "messages": [{"role": "user", "content": prompt}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "server-side-fallback-2026-07-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.load(r)

    if res.get("stop_reason") == "refusal":
        raise RuntimeError("AIが回答を断りました")
    for block in res.get("content", []):
        if block.get("type") == "text" and block.get("text"):
            return json.loads(block["text"])
    raise RuntimeError("AIの返事に本文がありませんでした")


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

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print(f"{name}: 鍵が無いので飛ばします")
        return

    dest = os.path.join(HERE, "data.json")
    with open(dest, encoding="utf-8") as f:
        data = json.load(f)
    try:
        with open(os.path.join(HERE, "history.json"), encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = {}

    print(f"{name}: 書いています…")
    try:
        got = ask_claude(api_key, build_prompt(data, hist, monthly), monthly)
    except Exception as e:
        # レポートが無くても他は出せるので止めない
        print(f"  ! {name}の失敗: {e}", file=sys.stderr)
        return

    paras = [str(p).strip() for p in got.get("paragraphs", []) if str(p).strip()]
    if not paras:
        print(f"  ! {name}の失敗: 中身が空でした", file=sys.stderr)
        return

    # 月次は「先月」ぶんなので、見出しの月は1つ前にする
    prev_month = (now.replace(day=1) - timedelta(days=1))
    key = "monthly" if monthly else "weekly"
    data[key] = {
        "title": str(got.get("title", "スクラップ動向")).strip(),
        "paragraphs": paras,
        "date": now.strftime("%Y-%m-%d"),
        "label": f"{prev_month.month}月のまとめ" if monthly else f"{now.month}/{now.day}の週",
    }
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{name}: 書きました（{data[key]['title']} / {len(paras)}段落）")


if __name__ == "__main__":
    main()
