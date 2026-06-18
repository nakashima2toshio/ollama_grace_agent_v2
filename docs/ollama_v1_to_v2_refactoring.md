# ollama_grace_agent v1→v2 リファクタリング資料

**Version 1.0** | 最終更新: 2026-06-18

> `ollama_grace_agent`（以下 **v1**）→ `ollama_grace_agent_v2`（以下 **v2**）で
> 「何を・なぜ・どう変えるか」を整理した資料。
> 参照元は `anthropic_grace_agent_v2/docs/anthropic_v1_to_v2_refactoring.md`（anthropic 版 v2）。
> 本資料は **ollama（ローカル LLM）前提**へ読み替えたもの。

---

## 0. 前提（v1 の実態）

ollama v1 は OpenAI→Ollama 移行を完了した**動作する完成版**であり、anthropic v1 とは
LLM 呼び出し方式が異なる:

| 層 | v1（ollama）の実態 |
|---|---|
| grace LLM | `helper.helper_llm.create_llm_client("ollama")` を **直接**使用（簡素化 3 メソッド interface: `generate_content` / `generate_structured` / `count_tokens`） |
| 既定モデル | `gemma4:e4b`（`grace/config.py` LLMConfig） |
| Embedding | `nomic-embed-text`（768 次元、`grace/config.py` EmbeddingConfig）。設定＝実装で一致 |
| コスト | なし（ローカル実行・トークン集計のみ） |
| 未実装 | eval ハーネス / 較正(calibration) / 実行メモリ(memory) / genai 互換アダプタ(llm_compat) / ハイブリッド ReAct / groundedness |

→ anthropic v2 の **provider 透過な自律能力（S0/S1/S3/P2/P4）**を ollama に横展開するのが v2 の本質。
anthropic は `create_chat_client`（genai 互換）経由で provider 透過を実現したが、
ollama v1 は `create_llm_client` 直呼びのため、**両者を橋渡しする `llm_compat`（ollama 分岐）**を核に据える。

---

## 1. v2 で追加するテーマ

| # | テーマ | 種別 | provider 依存性 | 本 PR 状態 |
|---|---|---|:--:|:--:|
| T1 | LLM クライアント層（既定 ollama・簡素化 interface） | 既存 | 依存 | ✅ v1 で完了済 |
| T2 | Embedding 方針（nomic-embed-text 768 に統一） | 既存 | 依存 | ✅ v1 で完了済 |
| T3 | `grace/llm_compat.py`（genai 互換 **Ollama** アダプタ） | 新規 | 半依存 | ✅ 本 PR |
| T5 | 評価ハーネス S0（`eval/`） | 新規 | 非依存 | ✅ 本 PR（ollama 化） |
| T6 | 信頼度の較正 S1（`grace/calibration.py`） | 新規 | 非依存 | ✅ 本 PR（計算部） |
| T8 | 実行メモリ層 P4（`grace/memory.py`） | 新規 | 非依存 | ✅ 本 PR |
| T6' | confidence への groundedness 検証統合 | 変更 | 非依存 | ✅ 完了（S1 PR） |
| T7 | ハイブリッド ReAct S3（executor 分岐） | 変更 | 非依存 | ✅ 完了（S3 PR） |
| T9 | code_execute サンドボックス P2 ＋ A/B 測定 | 新規 | 非依存 | ✅ 完了（P2 PR） |
| T10 | CI/pyproject/docs 整備 | 変更 | 半依存 | 🔶 一部（pyproject 名称・本資料） |

---

## 2. 本 PR で実施した内容

### 種（seed）
- `ollama_grace_agent`（v1）の **git 追跡ツリー全体**を `ollama_grace_agent_v2` に展開（動作するベースライン）。

### 新規モジュール（provider 透過 / ollama 化）
- **`grace/llm_compat.py`**（新規）: `create_chat_client(config)` が
  `config.llm.provider` に応じて genai 互換クライアントを返す。
  既定 **ollama**（`OllamaGenaiClient` が `helper.helper_llm.create_llm_client("ollama")` をラップし
  `client.models.generate_content(...)` 互換を提供）。`gemini` 指定時のみ google-genai。
  → 今後の executor ReAct / confidence groundedness 移植を **大改修なし**で載せ替える核。
- **`grace/calibration.py`**（新規・コピー）: 温度スケーリング `Calibrator` ＋ `expected_calibration_error`（ECE）。純計算で provider 非依存。
- **`grace/memory.py`**（新規・コピー）: `ExecutionMemory`。実行ログ（質問キーワード, コレクション, 成否, confidence）を JSONL 蓄積し、コレクション事前分布を学習。provider 非依存。
- **`eval/`**（新規・ollama 化）: `run_eval.py` / `metrics.py` / `build_dataset.py` / `ab_compare.py` / `calibrate.py`。
  - ジャッジを **`create_llm_client("ollama")` / `gemma4:e4b`** に変更。
  - 既定コレクションを **`cc_news_2per_ollama`** に変更。
  - コスト計測は `total_cost_usd=None`（ローカル実行のため自然に無効）。

### メタデータ
- `pyproject.toml`：`name = "ollama-grace-agent-v2"`、description を ollama v2 用に更新。

---

## 3. ollama 置換対応表（anthropic v2 → ollama v2）

| 項目 | anthropic v2 | ollama v2 |
|---|---|---|
| LLM 既定モデル | `claude-sonnet-4-6` | `gemma4:e4b` |
| LLM クライアント | `create_chat_client`/`AnthropicGenaiClient` | `create_chat_client`/`OllamaGenaiClient`（`create_llm_client("ollama")` ラップ） |
| LLM APIキー | `ANTHROPIC_API_KEY` | 不要（ローカル） |
| Embedding | `gemini-embedding-001`(3072) | `nomic-embed-text`(768) |
| Qdrant コレクション | `*_anthropic` | `*_ollama`（**768 次元で再作成必須**） |
| コスト計算 | あり | なし（ローカル・トークン集計のみ） |
| eval ジャッジ | `claude-haiku-4-5-20251001` | `gemma4:e4b` |
| 統合テスト前提 | `ANTHROPIC_API_KEY`＋Qdrant | `RUN_OLLAMA_INTEGRATION=1`＋ローカル Ollama＋Qdrant |

---

## 4. follow-up（次 PR 推奨順）

1. ~~**confidence groundedness（T6'）**~~ ✅ **完了**: `grace/confidence.py` に `GroundednessVerifier`
   （回答の各主張が引用ソースに支持されるか）を追加し、`grace/executor.py` の最終 confidence を
   `_blend_groundedness_confidence`（groundedness 主成分＋self_eval/coverage＋検索集約を補助）でブレンド、
   `Calibrator`（温度スケーリング）を適用。LLM 呼び出しは `create_chat_client`（llm_compat/Ollama）経由。
   設定は `ConfidenceConfig.groundedness_*` / `calibration_path`。
2. ~~**ハイブリッド ReAct（T7）**~~ ✅ **完了**: `grace/executor.py` に複雑度ベースの
   静的 Plan-Execute / 観測駆動 ReAct 振り分け（`_dispatch_generator`／`react_enabled`＋`react_complexity_threshold`、
   既定 OFF で静的パス温存）。`execute_react_generator`（Reason→Act→Observe→Confidence→Controller）と
   `_decide_next_action`（LLM 不在時は初期計画フォールバックへ degrade）を追加。
   `grace/schemas.py` に `Scratchpad`/`ScratchpadEntry`/`AgentThought` を追加。
   **LLM 呼び出しは `create_chat_client`（llm_compat/Ollama）経由**で provider 透過。
3. ~~**code_execute（T9）**~~ ✅ **完了**: `grace/tools.py` に `CodeExecuteTool`（別プロセス `python -I -S`＋`resource` 制限〔RLIMIT_CPU/AS/FSIZE、Darwin は RLIMIT_AS 除外〕＋AST 静的検査＋実時間タイムアウト、既定 opt-in）。`ConfigExecuteConfig`（`grace/config.py`）と ToolRegistry の opt-in 登録を追加。A/B は `eval/ab_compare.py`（react ON/OFF 比較、seed 済み）。
4. **CI/テスト（T10）**: テストの patch ターゲット・既定値を ollama へ。統合テストは `RUN_OLLAMA_INTEGRATION=1` の skipif。`pyproject` 依存整理（不要な `anthropic` 依存の削除可否を検証）。
5. **Qdrant データ**: 768 次元で `*_ollama` コレクションを再作成・再登録（次元差のため流用不可）。

---

## 5. リスク・注意点
- **埋め込み次元**：ollama は 768（nomic）。`*_ollama` コレクションを 768 で再作成すること（dimension mismatch は実害大）。
- **provider 透過の維持**：follow-up の S3/P2/groundedness は **LLM 呼び出しを `create_chat_client`（llm_compat）経由**に保つこと。これが移植容易性の鍵。
- **executor/confidence の丸ごとコピー禁止**：anthropic v2 のそれらは genai 形式直書きのため、ollama v1 既存実装と競合する。差分マージで対応する。

---

## 6. 変更履歴
| バージョン | 変更内容 |
|---|---|
| 1.0 | 初版（seed 展開＋llm_compat(ollama)/calibration/memory/eval 移植）。S3/P2/groundedness は follow-up（2026-06-18） |
