# スクラップ今日

スクラップ・非鉄金属の買取業（小林商会）の事業主が、朝いちにスマホで
自分の商売に効くニュースだけを1分で確認するための小さな仕組み。

## 使う人の前提

- Windows 11。ターミナルは詳しくない。
- 説明は日本語で、専門用語は避けて、具体的に。
- 手順を出すときは、コマンドをそのまま貼れる形で。

## 構成

| ファイル | 役割 |
|---|---|
| `collect.py` | Googleニュースの無料RSSと為替をあつめて `data.json` を書き出す |
| `manual.json` | 建値・金・銀を手で書くところ（自動取得できないため） |
| `index.html` | スマホで見る画面。`data.json` を読んで表示する |
| `data.json` | 自動生成。手で触らない |
| `check_data.py` | `data.json` が空でないか等を見張る番人。おかしければエラーで止める |
| `build_page.py` | `data.json` を `index.html` に埋め込んで1枚のHTMLにする（サーバー不要・offline用） |
| `.github/workflows/collect.yml` | 毎朝GitHubで `collect.py` を動かし、GitHub Pagesに公開する |

## 動いている場所

**スマホで見るURL: https://ktkctoro.github.io/scrap-news/**

毎朝4時30分（日本時間）にGitHubのサーバーで `collect.py` が動き、
`data.json` を作り直してこのURLに反映する。**パソコンの電源は関係ない。**

- 建値（`manual.json`）を直したいときは、スマホやパソコンのブラウザで
  GitHubの `manual.json` を開いて編集すればよい。保存すると数分で画面に反映される
- リポジトリは公開（public）。建値・買取価格もURLを知っていれば誰でも見られる

## 設計の方針

- **追加ライブラリを入れない。** Python標準ライブラリだけで完結させる。
  pip install が必要になる変更は、先に理由を説明して確認を取ること。
- **分類は4つ。** `mkt`（相場）/ `law`（法規制）/ `gen`（業界）/ `dc`（AI・DC）。
  増やさない。画面のチップが増えると朝いちに読めなくなる。
- **AI・DC分類はノイズが多い。** 株価やAIモデルの新版といった、買取に関係ない
  記事が大量に混ざる。`DC_MUST_HAVE` で銅・電線・変圧器・電力などに絞っている。
- 分類は見出しの語で判定する（`CLASSIFY`）。検索クエリの順番に依存させない。

## 未解決のこと

- 建値・金・銀の自動取得先がない。当面は `manual.json` の手入力。
  安定して読める公開ページが見つかれば、そこを取りにいく処理を足したい。
- Googleニュースの無料フィードは新着が遅れがちで、当日の記事が少ない日がある。

## 済んだこと（2026-08-20）

1. Windowsで動かないの日付書式（`%-m`）を直した
2. 関係ない記事のふるい分けを足した（`RELEVANT` / `NG_WORDS` / `NG_SOURCES` /
   `CONDITIONAL`）。203件 → 24件になった
3. 毎朝の自動実行を GitHub Actions + GitHub Pages に置いた。
   Windowsのタスクスケジューラは使わない

## 次にやってほしいこと

1. 数日ぶん動かしてみて、まだ混ざる関係ない記事があれば
   `NG_WORDS` / `NG_SOURCES` を足す。逆に、拾ってほしいのに落ちている記事が
   あれば `RELEVANT` に語を足す
2. 建値・金・銀の自動取得先をさがす（今は `manual.json` の手入力）

## 動作確認

パソコンで試すとき:

```
py collect.py
py check_data.py
py build_page.py
```

`build_page.py` が作る `携帯用.html` はダブルクリックで開ける。
`index.html` のほうを直接開くと `data.json` を読めない（ブラウザの制限）ので、
そちらを確認したいときは `py -m http.server 8000` を通すこと。

GitHub側で試すとき:

```
gh workflow run collect.yml
gh run watch
```
