# 業界特化（VerticalProfile / GRACE-Support）Ollama 移植 TODO

作成日: 2026-07-03 | 対象: `ollama_grace_agent_v2`
基準: `anthropic_grace_agent_v2` PR #106〜#130 を「ロジックの正」とする。
仕様は [`docs/vertical_port_spec.md`](./vertical_port_spec.md) を参照。

> 本書はチェックリスト。設計の背景・読替表・KPI 定義は仕様書側にある。

---

## ⛔ 移植の鉄則（各項目で必ず確認）

- [ ] LLM は `create_llm_client("ollama")` / `create_chat_client`（内部 Ollama shim）のまま
- [ ] モデルは `gemma4:e4b`、軽量用途は軽量 Ollama タグ（`claude-*` を持ち込まない）
- [ ] Embedding は `nomic-embed-text` / **768 次元**（`gemini-embedding-001` / 3072 を持ち込まない）
- [ ] コレクションは `*_ollama`（`*_anthropic` を持ち込まない）
- [ ] コスト計算を有効化しない（ローカル＝トークン集計のみ）
- [ ] API キー必須化をしない（`ANTHROPIC_API_KEY` / `GOOGLE_API_KEY` ゲートを移植しない）

---

## P0: コアフックの新設（最小・最重要）

> 業界特化の「配線」はこの 2 フックに集約される。ここだけで既存 GRACE 経路に業界スコープ／方針が効く。

- [ ] **`grace/config.py` `LLMConfig`（:54）に `prompt_addendum: str = ""` を追加**（参照: anthropic config.py:69）
- [ ] **`grace/config.py` `QdrantConfig`（:147）に `allowed_collections: list = Field(default_factory=list)` を追加**（参照: config.py:173）
  - [ ] 環境変数 `GRACE_QDRANT_ALLOWED_COLLECTIONS=a,b` で上書き可能なこと（既存 `_apply_env_overrides` のカンマ分割を確認）
- [ ] **`grace/tools.py` `RAGSearchTool` に `_apply_allowed_collections()` を追加**（参照: tools.py:356-381）
  - [ ] staticmethod・許可リストと**部分一致（`a==c or a in c`）**で積集合
  - [ ] `allowed` が空 → 全候補を返す（無制限）
  - [ ] 積集合が空（未一致）→ **制限せず全候補＋警告**（デモ・評価の継続性）
  - [ ] `execute()` の候補構築後に適用。`allowed_collections` kwarg も受け、無ければ `config.qdrant.allowed_collections` を使う（参照: tools.py:160-165）
- [ ] **`grace/tools.py` `ReasoningTool._build_prompt()`（:503）に方針注入を追加**（参照: tools.py:525-528）
  - [ ] `getattr(config.llm,"prompt_addendum","")` を `### 【業務方針（遵守）】` ブロックとしてシステム指示直後に連結
- [ ] 検証: `ruff check .` ＋ `python -m compileall grace/`
- [ ] （planner / executor / schemas は既存フックで足りるため**変更しない**ことを確認）

---

## P1: GRACE-Support 本体 ＋ アクション層の移植

- [ ] **`support_actions.py` を新規移植（ほぼ丸ごとコピー・プロバイダ非依存）**（参照: 同名 252行）
  - [ ] `ActionBackend` / `DryRunActionBackend` / `PseudoActionBackend` / `WebhookActionBackend`
  - [ ] `create_action_backend()` / `IdentityVerifier` / `CsvIdentityChecker` / `create_identity_verifier()`
  - [ ] 環境変数（`SUPPORT_ACTION_WEBHOOK_URL` / `_TOKEN` / `SUPPORT_IDENTITY_FILE`）はそのまま
- [ ] **`agent_support_example.py` を新規移植（プロバイダ読替）**（参照: 同名 905行）
  - [ ] `VerticalProfile` dataclass（8 フィールド）
  - [ ] `PROFILES`（gov / saas / ec）— **コレクション名を `*_ollama` に**（§7 の対応表）
  - [ ] `create_intent_classifier` / `create_no_info_judge` — **`INTENT_MODEL` を軽量 Ollama タグに**（P4-1 の決定に従う）
  - [ ] `_should_force_escalate` / `_match_keyword` / `_answer_gate` / `_decide_action` / `_perform_action`
  - [ ] `_detect_no_info_answer`（④'・`force_judge` 含む）/ `_should_rescue_unaffirmed` / `_pick_groundedness`
  - [ ] `run_support_agent()` — 冒頭で `config.qdrant.allowed_collections` / `config.llm.prompt_addendum` を設定（P0 フックへ配線）
  - [ ] **`ANTHROPIC_API_KEY` ゲート（:613）を削除**（キーレス化。必要なら Ollama 到達性チェック）
  - [ ] docstring のキー前提を「ローカル・キー不要」に修正
  - [ ] `main()` の argparse（`--vertical {gov,saas,ec}` / `--no-web` / `--no-action` / `--dry-run` / `--identity`）
  - [ ] LLM 呼び出しが `client.models.generate_content(...)`（ollama shim）で動くこと

---

## P2: KPI 評価ハーネス（eval/vertical/）の移植

- [ ] `eval/vertical/` ディレクトリ ＋ `__init__.py` を新設（CLI ヒントのみ読替）
- [ ] **`eval/vertical/metrics.py` をコピー（無改変・プロバイダ非依存）**
- [ ] **`eval/vertical/run.py` を移植**（docstring のキー前提のみ読替。`run_support_agent` を dry-run で駆動）
- [ ] **`eval/vertical/register_test_collections.py` を移植**
  - [ ] `--provider` 既定 `"gemini"` → `"ollama"`、ヘルプ「3072次元」→「nomic-embed-text 768次元」
  - [ ] `VERTICAL_COLLECTIONS` を `*_ollama` 6 本に
- [ ] **`eval/vertical/fetch_real_knowledge.py` を移植**
  - [ ] 印字フォローアップコマンド（L290）の `gov_laws_anthropic` / `saas_docs_anthropic` を `*_ollama` に
  - [ ] e-Gov API / FastAPI docs の URL・`DEFAULT_LAWS` はデータ源として維持
- [ ] **`eval/vertical/cases/{gov,saas,ec}.jsonl` をコピー**（日本語・プロバイダ非依存）
- [ ] **`eval/vertical/data/*.csv`（6本）をコピー**（`question,answer,topic`）
- [ ] スモーク: `python -m eval.vertical.register_test_collections --vertical all --recreate --provider ollama`（要 Ollama/Qdrant）
- [ ] スモーク: `python -m eval.vertical.run --vertical gov --report logs/vertical_gov.json`

---

## P3: テスト移植

- [ ] `tests/test_agent_support_vertical.py`（純関数・API 不要）— PROFILES のコレクション名 assert を `*_ollama` に
- [ ] `tests/test_support_actions.py`（無改変・webhook mock / CSV 台帳）
- [ ] `tests/grace/test_vertical_scope.py` — `_apply_allowed_collections` / `prompt_addendum` 注入。`_anthropic`→`_ollama`、候補名を `*_ollama` に
- [ ] `tests/eval/test_vertical_metrics.py`（無改変・`cases/*.jsonl` スキーマ検証）
- [ ] `tests/eval/test_register_test_collections.py` — `_anthropic`→`_ollama` の assert
- [ ] `tests/eval/test_fetch_real_knowledge.py`（無改変・ネット不要のパース検証）
- [ ] 実 Ollama/Qdrant 依存分は `RUN_OLLAMA_INTEGRATION=1` / `@pytest.mark.integration` でゲート
- [ ] 検証: `uv run pytest tests/test_agent_support_vertical.py tests/test_support_actions.py tests/grace/test_vertical_scope.py tests/eval/`

---

## P4: ドキュメント移植（CLAUDE.md §7 Mermaid ／ §9.1 表記統一を厳守）

- [ ] `grace/doc/agent_support_verticals.md`（主設計書 v1.4）— モデル／Embedding／コレクション／コスト章／キー前提を Ollama へ読替
- [ ] `grace/doc/agent_support_example.md`（GRACE-Support コア設計）— モデル名のみ読替（しきい値等は共通）
- [ ] `docs/vertical_test_data.md`（テストデータ準備ガイド）— Embedding「nomic 768」・`*_ollama`・キー前提削除。データ候補は維持
- [ ] `docs/migration_and_update.md`（需要分析・ロードマップ）— 表記統一のみ
- [ ] （任意）`docs/vertical_spec_review.md`（実装レビュー履歴）
- [ ] CLAUDE.md §9.2 ドキュメント一覧に本 2 ドキュメント（spec / todo）と移植したドキュメントを追記

---

## 要確認（着手前に確定）

- [x] **P4-1: 軽量モデル選定** — `LLMConfig.light_model` 新設。既定は `gemma4:e4b`（実機で `llama3.2:3b` が日本語 question/request を誤判定→keyword-trap 誤エスカレしたため精度優先で確定。`llama3.2:3b` 等への切替でレイテンシ短縮可）
- [ ] コレクション接尾辞 `*_ollama` で確定（§7）
- [ ] Embedding 768 / `nomic-embed-text` で確定（登録・検索とも）
- [ ] `docs/vertical_spec_review.md` を移植対象に含めるか

---

## 進め方（推奨順）

1. **P0**（コアフック 2 点）→ `ruff` / `compileall` で緑化。既存 GRACE を壊さないことを最優先。
2. **P1**（`support_actions.py` → `agent_support_example.py`）— コピー先行、次に読替。
3. **P2**（`eval/vertical/`）— `metrics.py`/`cases`/`data` を先にコピー、次に register/fetch/run を読替。
4. **P3**（テスト）— 純関数系（API 不要）から。実機依存は marker ゲート。
5. **P4**（ドキュメント）— 最後に表記統一で仕上げ、CLAUDE.md 一覧を更新。

各 PR で「鉄則」チェックリストを必ず通す。実 Ollama/Qdrant 前提の項目（登録・KPI・統合テスト）は実機で回帰確認する。
