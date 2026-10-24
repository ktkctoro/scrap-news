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
import urllib.error
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
    lines.append("【記事の見出し（番号つき・全件。かっこ内は出た日）】")
    for n, i in enumerate(data.get("items") or [], 1):
        lines.append(f"{n}. [{i['label']}] {i['title']}（{i['source']}・{_md(i.get('published'))}）")

    lines += [
        "",
        "頼みたいことは2つ。",
        "",
        "1) この材料から、経営者が朝いちに読む「けさの3行」を書く。",
        "・ちょうど3行。1行は40字以内。各行の頭に「・」を付ける",
        "・1行目は相場の動き、2行目は法規制・制度の動き、3行目はそのほかで商売に効く話",
        "・法規制の記事は2ヶ月前のものまで混ざっている。2行目はここ数日に出た動きを選ぶ。",
        "  新しい動きがなければ、2行目も相場か商売の話に回してよい（古い話をくり返さない）",
        "・材料にない事実を書かない。数字は材料のまま使う",
        "",
        "2) 見出しの中から、明らかに載せる価値のない記事の番号を挙げる。",
        "・例: 宝飾やファッションの記事、骨董やオークションの出品ページ、",
        "  商品の宣伝や店舗のオープン告知、芸能、スポーツ",
        "・[ビットコイン]の記事は経営者が見たくて載せているので、外さない",
        "・相場・法規制・業界・AIデータセンターの記事も、この商売の関心事なので残す",
        "・判断に迷うものは残す（挙げない）。関係ある可能性が少しでもあれば残す",
    ]
    return "\n".join(lines)


def _md(iso):
    """'2026-10-23T21:37:00+09:00' → '10/23'。日付が無ければ '日付不明'。"""
    try:
        return f"{int(iso[5:7])}/{int(iso[8:10])}"
    except (TypeError, ValueError):
        return "日付不明"


def call_api(api_key, body, timeout):
    """Claudeに問い合わせて、返事(JSON)をそのまま返す。weekly.py からも使う。

    断られたとき(HTTPエラー)は、理由の本文を例外の文に入れる。
    以前は「400 Bad Request」としか残らず、3週間止まっていても原因が分からなかった。
    400(頼み方がおかしい)のときは、おまけの機能(fallbacks)を外してもう1回だけ試す。
    """
    def post(b, beta):
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if beta:
            headers["anthropic-beta"] = beta
        req = urllib.request.Request(
            API_URL,
            data=json.dumps(b, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"HTTP {e.code}: {detail}") from None

    try:
        return post(body, "server-side-fallback-2026-07-01")
    except RuntimeError as e:
        if not str(e).startswith("HTTP 400"):
            raise
        print(f"  ! 1回目は断られました（{e}）。fallbacks を外して試し直します", file=sys.stderr)
        plain = {k: v for k, v in body.items() if k != "fallbacks"}
        return post(plain, None)


def ask_claude(api_key, prompt):
    """Claudeに1回問い合わせて、3行まとめと「関係ない記事の番号」を受け取る。

    返事は決まった形（JSON）で返させるので、揺れずに読み取れる。
    """
    body = {
        "model": MODEL,
        "max_tokens": 8000,
        # 3行まとめは軽い仕事なので、考える量は控えめでよい
        "output_config": {
            "effort": "low",
            "format": {
                "type": "json_schema",
                "schema": {
                    "type": "object",
                    "properties": {
                        "lines": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "けさの3行。各行の頭に「・」",
                        },
                        "drop": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "商売と明らかに関係ない記事の番号",
                        },
                    },
                    "required": ["lines", "drop"],
                    "additionalProperties": False,
                },
            },
        },
        # 安全側の判定で回答を断られたときは、別モデルが自動で代わりに答える
        "fallbacks": "default",
        "system": (
            "あなたはスクラップ・非鉄金属買取業「小林商会」の朝のブリーフィング担当です。"
            "経営者が朝いちの1分で読む要約を書き、記事のふるい分けも手伝います。"
        ),
        "messages": [{"role": "user", "content": prompt}],
    }
    data = call_api(api_key, body, timeout=180)

    if data.get("stop_reason") == "refusal":
        raise RuntimeError("AIが回答を断りました")
    for block in data.get("content", []):
        if block.get("type") == "text" and block.get("text"):
            return block["text"].strip()
    raise RuntimeError("AIの返事に本文がありませんでした")


def _mark_failed(data, dest, reason):
    """失敗した印を data.json に残す。画面の「けさの3行」の場所に小さく出る。"""
    now = datetime.now(JST)
    data["ai_error"] = {"at": f"{now.month}/{now.day} {now.hour}:{now.minute:02d}",
                        "reason": reason[:200]}
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


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

    print("AIまとめ: けさの3行と記事のふるい分けをしています…")
    try:
        text = ask_claude(api_key, build_prompt(data))
        got = json.loads(text)
        rows = [str(l).strip() for l in got.get("lines", []) if str(l).strip()][:3]
        drop = {int(n) for n in got.get("drop", []) if isinstance(n, (int, float))}
    except Exception as e:
        # まとめが無くても記事と価格は出せるので、失敗しても止めない。
        # ただし黙って欄が消えると気づけないので、画面に出す印を残す
        print(f"  ! AIまとめの失敗: {e}", file=sys.stderr)
        _mark_failed(data, dest, str(e))
        return

    if not rows:
        print("  ! AIまとめの失敗: 中身が空でした", file=sys.stderr)
        _mark_failed(data, dest, "中身が空でした")
        return

    # 関係ないと判定された記事を落とす。
    # まちがって大量に消さないよう、全体の3割までにとどめる。
    # ビットコインは意図して載せている分類なので、判定にかかわらず必ず残す。
    items = data.get("items") or []
    drop = {n for n in drop
            if 1 <= n <= len(items) and items[n - 1].get("cat") != "btc"}
    limit = max(3, len(items) * 3 // 10)
    if drop and len(drop) <= limit:
        kept = [it for n, it in enumerate(items, 1) if n not in drop]
        removed = [it["title"][:40] for n, it in enumerate(items, 1) if n in drop]
        data["items"] = kept
        print(f"AIまとめ: 関係ない記事 {len(removed)} 件を外しました")
        for t in removed:
            print("   × " + t)
    elif drop:
        print(f"  ! ふるい分けが多すぎる（{len(drop)}件）ので今回は採用しません", file=sys.stderr)

    now = datetime.now(JST)
    data["ai"] = {"lines": rows, "at": f"{now.month}/{now.day} {now.hour}:{now.minute:02d}"}
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"AIまとめ: 書きました（{len(rows)}行）")
    for l in rows:
        print("   " + l)


if __name__ == "__main__":
    main()
