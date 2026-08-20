#!/usr/bin/env python3
"""携帯で見る用の1枚ファイルを作る。

index.html は data.json を別ファイルとして読みにいくので、
簡易サーバー（http.server）を通さないと表示できない。
このスクリプトは data.json の中身を index.html に埋め込んで、
ダブルクリックだけで開ける1枚のHTMLにする。

デザインは index.html をそのまま使う。見た目を直したいときは
index.html だけ直せばよく、こちらは触らなくてよい。

使い方:
    py build_page.py                     # 携帯用.html を作る
    py build_page.py --fragment out.html # <body>の中身だけを別に書き出す
"""

import argparse
import io
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# index.html のこの1行を、埋め込んだデータを読む形に差し替える
FETCH_CALL = "fetch('./data.json?t=' + Date.now())"
INLINE_CALL = (
    "Promise.resolve({ ok: true, json: function(){ "
    "return JSON.parse(document.getElementById('baked-data').textContent); } })"
)


def build(data, template):
    """index.html に data.json の中身を埋め込んだHTMLを返す。"""
    if FETCH_CALL not in template:
        raise SystemExit(
            "index.html の中に data.json を読む行が見つかりません。\n"
            "index.html を書き換えたときは build_page.py の FETCH_CALL も合わせてください。"
        )

    # </script> がデータの中にあるとHTMLが途中で切れるので逃がす
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    baked = (
        '<script id="baked-data" type="application/json">' + payload + "</script>\n"
    )

    html = template.replace(FETCH_CALL, INLINE_CALL, 1)
    html = html.replace("<script>", baked + "<script>", 1)
    return html


def to_fragment(html):
    """<body>の中身だけを取り出す（貼り付け先が用意されている場合用）。"""
    m = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    body = m.group(1) if m else html
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    style = "<style>" + m.group(1) + "</style>\n" if m else ""
    title = re.search(r"<title>(.*?)</title>", html, re.S)
    head = "<title>" + title.group(1) + "</title>\n" if title else ""
    return head + style + body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fragment", help="<body>の中身だけを書き出す先")
    args = ap.parse_args()

    data_path = os.path.join(HERE, "data.json")
    if not os.path.exists(data_path):
        raise SystemExit("data.json がありません。先に collect.py を実行してください。")

    with io.open(data_path, encoding="utf-8") as f:
        data = json.load(f)
    with io.open(os.path.join(HERE, "index.html"), encoding="utf-8") as f:
        template = f.read()

    html = build(data, template)

    dest = os.path.join(HERE, "携帯用.html")
    with io.open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print(f"作りました: {dest}（{len(data.get('items', []))} 件 / 更新 {data.get('updated', '')}）")

    if args.fragment:
        with io.open(args.fragment, "w", encoding="utf-8", newline="\n") as f:
            f.write(to_fragment(html))
        print(f"作りました: {args.fragment}")


if __name__ == "__main__":
    main()
