# grace ReAct（観測駆動エージェント）— 短縮ドキュメント

**Version 1.0** | 最終更新: 2026-06-19

> 関連コード: `grace/planner.py` / `grace/executor.py` / `grace/confidence.py`

---

## 概要（ReAct とは）

**ReAct（Reason + Act）** は、計画どおりに動くのではなく「**推論（Reason）→ 行動（Act）→ 観測（Observe）**」を繰り返し、**毎ターンその場で次の一手を決める**動的エージェント方式です。
本プロジェクトでは `planner.py` が質問の複雑度（complexity）を見積もって計画を作り、複雑な質問のときだけ `executor.py` が ReAct ループに切り替えます。
ループ内では `_decide_next_action` がこれまでの観測（`Scratchpad`）を踏まえて「検索する／推論して答える／終了する」を **LLM にその場で判断**させ、`_execute_step` で実行します。
各ターンの結果は `confidence.py` の `decide_action` が信頼度で評価し、**根拠が十分なら finish、不十分なら検索を続行、低すぎれば人間に介入**を求めます。
つまり「**観測しながら計画を組み替える**」点が、固定手順の Plan-Execute との決定的な違いです。

---

## 要点・重点（特に「動的な判断」）

### 1. 静的 Plan-Execute と動的 ReAct の二段構え（核心）

`executor._dispatch_generator` が `plan.complexity >= react_complexity_threshold(0.7)` を見て切替えます。単純な質問は固定計画で速く、複雑な質問だけ ReAct で粘る——**無駄なループを避けつつ難問に強い**という設計上の肝です。

### 2. 「次の一手」を実行時に決める（＝動的判断の本体）

`_decide_next_action` は固定手順ではなく、直前までの観測（`Scratchpad`）を入力に LLM が `next_action` を選ぶ（`rag_search` / `web_search` / `reasoning` / `finish`）。検索結果が薄ければもう一度検索、揃えば回答生成、と**状況に応じて経路が変わる**のが ReAct の動的性です。

### 3. 信頼度がループの「制御弁」

`confidence.decide_action` が各ターンの信頼度を `SILENT` / `NOTIFY` / `CONFIRM` / `ESCALATE` に変換し、続行・人間介入・終了を動的に決定。さらに `GroundednessVerifier`（回答の各主張が引用ソースに支持されるか）を信頼度の主成分にしているため、「**根拠があるか**」で止め時を判断します。

### 4. フォールバックで壊れない

LLM 不在（ローカル Ollama 未起動など）でも `_decide_next_action` は初期計画の手順を順に辿る**静的動作へ degrade** します。動的判断は「**できるときに賢く、できないとき安全に**」が担保されています。

### 5. 役割分担の一行まとめ

| モジュール | 役割 | 判断の位置づけ |
|---|---|---|
| `planner.py` | どれだけ複雑かを見て計画と分岐を決める | 入口の判断 |
| `executor.py` | 次に何をするかを毎ターン決めて回す | ループの判断 |
| `confidence.py` | 続けるか止めるか・人を呼ぶかを信頼度で決める | 停止の判断 |
