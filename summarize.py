#!/usr/bin/env python3
"""けさの3行まとめを書く。

collect.py が作った data.json を読み、Claude(AI)に「けさの3行」を
書かせて data.json に書き足す。鍵(ANTHROPIC_API_KEY)が無いときは
何もせずに正常終了する(ページにまとめ欄が出ないだけで、記事や価格は出る)。

鍵は GitHub の Secrets(金庫)にだけ置く。このファイルにも data.json にも
鍵そのものは入らない。追加ライブラリなし(標準ライブラリのみ)。
使い方: py summarize.py
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
JST = timezone(timedelta(hours=9))

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-opus-5"


def build_prompt(data):
    """data.json の中身を、AIに渡す材料の文章にする。"""
    now = datetime.now(JST)
    lines = [f"きょうは{now.year}年{now.month}月{now.day}日。以下はけさ集めた相場と記事の見出し。", ""]

    lines.append("【相場】")
    manual = data.get("manual") or {}
    for t in manual.get("tiles", []):
        lines.append(f"{t['name']} {t['value']}{t['unit']}（前回比 {t['diff'] or '±0'}）")
    for r in manual.get("rows", []):
        lines.append(f"{r['name']} {r['value']}{r['unit']}（前日比 {r['diff'] or '±0'}）")
    fx = data.get("fx")
    if fx:
        lines.append(f"ドル円 {fx['usdjpy']}円")

    boards = data.get("boards") or {}
    if boards.get("rows"):
        lines.append("")
        lines.append("【基板の買取価格（K&Y）】")
        for r in boards["rows"]:
            lines.append(f"{r['name']} {r['value']}{r['unit']}（前回比 {r.get('diff') or '±0'}）")

    cmp_ = data.get("compare") or {}
    if cmp_.get("rows"):
        lines.append("")
        lines.append("【同業各社の買取価格くらべ】")
        for r in cmp_["rows"]:
            cells = "、".join(f"{c['dealer']}{c['value']:,}円" for c in r["cells"])
            lines.append(f"{r['name']}：{cells}（差{r['spread']:,}円）")

    lines.append("")
    lines.append("【記事の見出し】")
    for i in (data.get("items") or [])[:40]:
        lines.append(f"[{i['label']}] {i['title']}")

    lines += [
        "",
        "この材料から、経営者が朝いちに読む「けさの3行」を書いてください。",
        "・ちょうど3行。1行は40字以内。各行の頭に「・」を付ける",
        "・1行目は相場の動き、2行目は法規制・制度の動き、3行目はそのほかで商売に効く話",
        "・材料にない事実を書かない。数字は材料のまま使う",
        "・前置きや説明は書かず、3行だけを出力する",
    ]
    return "\n".join(lines)


def ask_claude(api_key, prompt):
    """Claudeに1回問い合わせて、返ってきた本文を返す。"""
    body = {
        "model": MODEL,
        "max_tokens": 8000,
        # 3行まとめは軽い仕事なので、考える量は控えめでよい
        "output_config": {"effort": "low"},
        # 安全側の判定で回答を断られたときは、別モデルが自動で代わりに答える
        "fallbacks": "default",
        "system": (
            "あなたはスクラップ・非鉄金属買取業「小林商会」の朝のブリーフィング担当です。"
            "経営者が朝いちの1分で読む要約を書きます。"
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
    with urllib.request.urlopen(req, timeout=180) as r:
        data = json.load(r)

    if data.get("stop_reason") == "refusal":
        raise RuntimeError("AIが回答を断りました")
    for block in data.get("content", []):
        if block.get("type") == "text" and block.get("text"):
            return block["text"].strip()
    raise RuntimeError("AIの返事に本文がありませんでした")


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("AIまとめ: 鍵(ANTHROPIC_API_KEY)が無いので飛ばします")
        return

    dest = os.path.join(HERE, "data.json")
    if not os.path.exists(dest):
        print("AIまとめ: data.json がありません。先に collect.py を実行してください", file=sys.stderr)
        return

    with open(dest, encoding="utf-8") as f:
        data = json.load(f)

    print("AIまとめ: けさの3行を書いています…")
    try:
        text = ask_claude(api_key, build_prompt(data))
    except Exception as e:
        # まとめが無くても記事と価格は出せるので、失敗しても止めない
        print(f"  ! AIまとめの失敗: {e}", file=sys.stderr)
        return

    rows = [l.strip() for l in text.splitlines() if l.strip()][:3]
    if not rows:
        print("  ! AIまとめの失敗: 中身が空でした", file=sys.stderr)
        return

    now = datetime.now(JST)
    data["ai"] = {"lines": rows, "at": f"{now.month}/{now.day} {now.hour}:{now.minute:02d}"}
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"AIまとめ: 書きました（{len(rows)}行）")
    for l in rows:
        print("   " + l)


if __name__ == "__main__":
    main()
