# 自治体予算

市区町村を選ぶと、令和6年度の普通会計決算をサンキー図で見る Open GENAI のアプリです。画面は `/budget` です。

`docker compose up -d` で `budget-app`（ポート 8022）が起動します。未起動のあいだはアプリ一覧に出ません。

歳入の各科目は普通会計に入り、歳出は目的別か性質別のどちらかに分かれます。この二つは同じ歳出の別の分け方です。

決算 JSON を作り直すとき:

```bash
python3 budget-app/scripts/build_data.py
```

総務省の [令和6年度 市町村別決算状況調](https://www.soumu.go.jp/iken/zaisei/r06_shichouson.html) を取得し、全市区町村で歳入・目的別・性質別の合計が概況と一致することを確認してから `budget-app/app/data/fy2024.json` を書き出します。
