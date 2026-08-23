#!/usr/bin/env python3
"""毎週月曜の朝、その週のスクラップ動向レポートをAIに書かせる。

材料は data.json と history.json（3ヶ月の推移）。
・相場は「1週間の変化」と「1ヶ月の変化」を数字で渡す
・法規制・業界の記事の見出しを渡す
・同業の価格差も渡す
月曜以外は何もしない（前の週のレポートがそのまま残る）。

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


def build_prompt(data, hist):
    now = datetime.now(JST)
    L = [f"きょうは{now.year}年{now.month}月{now.day}日（月曜）。"
         "先週1週間のスクラップ相場と業界の動きをまとめる。", ""]

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

    L += [
        "",
        "この材料から、スクラップ買取業の経営者が月曜の朝に読む週次レポートを書いてください。",
        "",
        "・見出しなしの短い段落を4つ。1段落は3〜4文、全体で600字程度",
        "・1段落目「相場」: 銅・鉄・貴金属の1週間の動きと、その背景",
        "・2段落目「法規制」: 制度の動きと、自社が備えるべきこと",
        "・3段落目「商売のヒント」: 同業の価格差や基板相場から、仕入れ・出し先の判断材料",
        "・4段落目「来週の見通し」: 材料から読み取れる範囲での見通しと注意点",
        "",
        "・材料にない事実を書かない。数字は材料のまま使う",
        "・見通しは断定せず「〜の可能性」「〜に注意」と書く",
        "・専門用語は避け、非エンジニアの経営者が読んで分かる言葉で",
    ]
    return "\n".join(L)


def ask_claude(api_key, prompt):
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
                            "description": "4つの段落",
                        },
                    },
                    "required": ["title", "paragraphs"],
                    "additionalProperties": False,
                },
            },
        },
        "fallbacks": "default",
        "system": (
            "あなたはスクラップ・非鉄金属買取業「小林商会」の週次レポート担当です。"
            "経営者が月曜の朝に3分で読み、その週の判断に使えるレポートを書きます。"
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
    # 月曜以外でも書かせたいときは --force か FORCE_WEEKLY=1
    force = "--force" in sys.argv or os.environ.get("FORCE_WEEKLY", "") == "1"
    if now.weekday() != 0 and not force:      # 0=月曜
        print("週次レポート: 月曜ではないので飛ばします")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("週次レポート: 鍵が無いので飛ばします")
        return

    dest = os.path.join(HERE, "data.json")
    with open(dest, encoding="utf-8") as f:
        data = json.load(f)
    try:
        with open(os.path.join(HERE, "history.json"), encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        hist = {}

    print("週次レポート: 書いています…")
    try:
        got = ask_claude(api_key, build_prompt(data, hist))
    except Exception as e:
        # レポートが無くても他は出せるので止めない
        print(f"  ! 週次レポートの失敗: {e}", file=sys.stderr)
        return

    paras = [str(p).strip() for p in got.get("paragraphs", []) if str(p).strip()]
    if not paras:
        print("  ! 週次レポートの失敗: 中身が空でした", file=sys.stderr)
        return

    data["weekly"] = {
        "title": str(got.get("title", "今週のスクラップ動向")).strip(),
        "paragraphs": paras,
        "date": now.strftime("%Y-%m-%d"),
        "label": f"{now.month}/{now.day}の週",
    }
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"週次レポート: 書きました（{data['weekly']['title']} / {len(paras)}段落）")


if __name__ == "__main__":
    main()
