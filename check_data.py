#!/usr/bin/env python3
"""data.json がちゃんと出来ているか確かめる。

毎朝GitHubで動かしたとき、取得先の仕様が変わって
中身が空になっていないかを見張るための番人。
おかしければエラーで止まり、GitHubからメールが届く。
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    path = os.path.join(HERE, "data.json")
    if not os.path.exists(path):
        sys.exit("data.json が出来ていません。collect.py が途中で止まった可能性があります。")

    with open(path, encoding="utf-8") as f:
        d = json.load(f)

    items = d.get("items", [])
    fx = d.get("fx")
    print(f"記事 {len(items)} 件 / 更新 {d.get('updated', '不明')}")
    print(f"為替 {fx}")

    counts = {}
    for i in items:
        counts[i.get("label", "?")] = counts.get(i.get("label", "?"), 0) + 1
    print("内訳 " + " / ".join(f"{k} {v}件" for k, v in sorted(counts.items())))

    if not items:
        sys.exit("記事が1件も取れていません。Googleニュースの取得先が変わった可能性があります。")
    if len(items) > 120:
        sys.exit(f"記事が {len(items)} 件と多すぎます。ふるい分けが効いていない可能性があります。")
    if not fx:
        print("注意: 為替が取れていません（記事は出せるので止めません）")

    # 自動取得の建値・金・銀がそろっているか
    prices = d.get("manual") or {}
    names = [t.get("name", "") for t in prices.get("tiles", [])] \
          + [r.get("name", "") for r in prices.get("rows", [])]
    missing = [label for label, word in
               (("銅建値", "銅建値"), ("金", "金"), ("銀", "銀"))
               if not any(word in n for n in names)]
    if len(missing) == 3:
        sys.exit("銅建値・金・銀が全部取れていません。公表ページの作りが変わった可能性があります。")
    for m in missing:
        print(f"注意: {m}が取れていません（ほかは出せるので止めません）")

    print("問題なし")


if __name__ == "__main__":
    main()
