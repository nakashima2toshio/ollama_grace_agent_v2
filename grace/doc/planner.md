# grace Planner（計画生成）— 短縮ドキュメント

**Version 1.0** | 最終更新: 2026-06-19

> 対象コード: `grace/planner.py` ／ 関連: `grace/executor.py`・`grace/schemas.py`

---

## 概要（Planner とは）

**Planner** は、ユーザーの質問を分析して **実行計画（`ExecutionPlan`）** を作る入口のエージェントです。
本プロジェクトでは **二層方式**を採り、`create_plan` が質問の **複雑度（complexity）** を見積もって分岐します。
単純な質問は **ルールベースの 2 ステップ計画**（`rag_search` → `reasoning`）を **LLM なしで即時生成**し、複雑な質問や「最新ニュースを検索」等の明示指示のときだけ **LLM で計画を生成**します。
LLM 経路は **構造化出力（JSON + Pydantic / `generate_structured`）** で `ExecutionPlan` を直接得て、失敗時は **指数バックオフでリトライ → 最終的にルールベース計画へフォールバック**します。
ここで決めた `complexity` は、後段 `executor.py` の **静的 Plan-Execute / 動的 ReAct の振り分け**にもそのまま使われます。

---

## 要点・重点

### 1. 二層計画（ルールベース即時 vs LLM 計画）— 速度とコストの肝

`create_plan` → `_should_use_llm_plan` で分岐します。多くの質問は `_create_rule_based_plan`（`rag_search`(fallback=`web_search`) → `reasoning` の標準 2 ステップ）を **LLM 呼び出しゼロ**で返すため、ローカル Ollama でも高速。LLM 計画は本当に必要なときだけ使います。

### 2. 複雑度推定が「分岐の鍵」（入口の動的判断）

`estimate_complexity` はキーワードベースの軽量推定（基準 0.5＋「比較／違い／複数／なぜ」等の加点＋長文加点）。`_should_use_llm_plan` は **① `force_llm_plan` ② 明示マーカー（`最新ニュース` 等）③ `complexity >= llm_plan_complexity_threshold`** のいずれかで LLM 計画を選択。この `complexity` が **executor の ReAct 切替の入力**にもなります。

### 3. 構造化出力＋リトライで堅牢

`_generate_plan_with_retry` が `generate_structured(response_schema=ExecutionPlan)`（Ollama は JSON モード + Pydantic parse）を実行。`_is_transient_error`（接続/タイムアウト/5xx/429 等）だけを **指数バックオフ**で再試行し、非一時的エラーは即送出。`validate_plan_dependencies` で依存関係も検証します。

### 4. フォールバックで壊れない

LLM 計画生成が失敗しても `_create_fallback_plan` → `_create_rule_based_plan(complexity=0.5)` に落ちるため、**API/モデル不在でも必ず実行可能な計画を返す**。「できるときに賢く、できないとき安全に」。

### 5. 計画の規約（executor との約束事）

- `rag_search` は 1 ステップにまとめ、`query` は**ユーザーの原文をそのままコピー**（要約・キーワード化・分割は禁止）。
- 計画に `web_search` 単体は原則含めない（**rag_search の結果が不十分なとき executor が動的に挿入**）。`rag_search` の `fallback` に `web_search` を指定。
- 最終ステップは必ず `reasoning`。

### 6. 再計画（`refine_plan`）

介入フィードバックを受け、**元計画の完全な JSON（query・依存・fallback 含む）** を渡して指摘箇所のみ修正。失敗時は元計画を返す。

### 7. 役割の一行まとめ

| 要素 | 役割 |
|---|---|
| `estimate_complexity` / `_should_use_llm_plan` | どれだけ複雑かを見て **ルール vs LLM** を選ぶ（入口の判断） |
| `_create_rule_based_plan` | 標準 2 ステップ計画を即時生成（LLM なし） |
| `_create_llm_plan` / `_generate_plan_with_retry` | 複雑質問を構造化出力＋リトライで計画化 |
| `_create_fallback_plan` | 失敗時の安全網（ルールベースへ degrade） |
| `refine_plan` | フィードバックによる再計画 |
