# ollama_grace_agent ロジック移植 TODO（表1：純ロジック更新漏れ）— 検証反映版

作成日: 2026-06-13 / 最終更新: 2026-06-13（実地検証反映）
基準: `anthropic_grace_agent` の 6/10 以降コミット（P0–P3 パイプライン改修 #40–#43 ＋ GRACE 群）を「ロジックの正」とする。
出所: anthropic 側 git 履歴（lint 一括コミット `eea1046` / `3966404` を除外）。

> 本書は **表1（純ロジック）専用**。CI/lint/テスト移植/ドキュメント刷新（表2・表3）は `docs/ollama_modernization_todo_june13.md` を参照。

---

## 🔑 検証の結論（最重要）

当初の表1（漏れ ≈3,700行）は**全ファイル diff ベース**だったため、**プロバイダー差を「漏れ」と誤認した偽陽性が大半**だった。実地検証（anthropic git 履歴のコミット単位 × ollama 現状の照合）の結果：

- ollama は **6/10 改修で P1/P2/P3 のパイプライン系ロジックを既に取り込み済み**。
- 本セッション（PR #51–#67）で **GRACE 中心の genuine な穴を解消**。
- **表1 の純ロジック移植は実質完了**。残るのは実機検証前提の任意項目のみ。

---

## ⛔ 移植方向の鉄則（恒久・誤りやすい）

anthropic を「正」とするのは **ロジックのみ**。プロバイダー層は Ollama を維持する。全ファイル diff をそのまま取り込むと以下を逆向きに上書きするため厳禁。

| 項目 | ❌ 取り込まない | ✅ 維持 |
|---|---|---|
| LLM/Embedding クライアント | `"anthropic"`/`"openai"`/`"gemini"` | `create_*_client("ollama")` |
| モデル | `claude-sonnet-4-6` | `gemma4:e4b` / `llama3.2` |
| Embedding/次元 | `text-embedding-3-large`/3072・`gemini-embedding-001` | `nomic-embed-text`/768 |
| Q/A JSON | 配列＋`raw_decode` | `{"qa_pairs":[...]}` |
| コスト計算 | あり | **なし**（トークン集計のみ可） |
| API キー | `ANTHROPIC_API_KEY` 必須 | 不要 |
| Qdrant コレクション | `*_anthropic` | `*_ollama` |

---

## ✅ 本セッションで完了（PR #51–#67）

| PR | 内容 | TODO |
|---|---|---|
| #51 | register_to_qdrant 一本化・内容ハッシュID・先読み並列／qdrant_client_wrapper | P1 |
| #52 | smart_qa_generator 単段化（JSON mode）・死にフラグ削除 | — |
| #53 | pipeline 同期(sync)経路の逐次永続化＋再開 | P3 |
| #54 / #55 | make_qa CLI 整合 / make_qa_register 死にフラグ撤去 | — |
| #56 | executor eval除去（ast.literal_eval） | GRACE |
| #57 | executor tool timeout | GRACE |
| #58 | config に PlannerConfig/ExecutorConfig | GRACE |
| #59 | executor 実行ループ一本化（generator 委譲） | GRACE |
| #60 | executor 並列検索（_prefetch_parallel_searches） | GRACE |
| #61 / #62 | planner 二層計画 / test_planner 追従 | GRACE |
| #64 | A1 リプラン条件精緻化＋A5 ask_user 実体化 | GRACE |
| #65 | B1/B2 evaluate_final 統合評価（2回→1回） | GRACE |
| #66 | A6 ファクタ共通化＋H 出力型構造化 | GRACE |
| #67 | **D1 Celery collect_results 完了順回収（HOLブロッキング解消）** | P3 |

---

## ✅ 元々 ollama 実装済み（偽陽性・対応不要）

実地検証で「既に実装済み」と確認。全ファイル diff のプロバイダー差を漏れと誤認していたもの。

| 旧項目 | 検証で確認した実装箇所 |
|---|---|
| **E** csv チャンキング（905・最大） | `EMBEDDING_INPUT_TOKEN_LIMIT=2048`・`_report_coverage`・`CheckpointManager`・文書単位チャンキング を `chunking/csv_text_to_chunks_text_csv.py` が既に保有 |
| **F1** 重複Q/A除去 | `services/qdrant_service.py:611` `drop_duplicates`／`qa_qdrant/register_to_qdrant.py:214` 重複テキスト除去 |
| **F3** Embedding クライアントキャッシュ | `services/qdrant_service.py:627` `_embedding_client_cache` |
| **G** async_api_client 強化 | `_resolve_schema_refs`（$ref/$defs 平坦化・小型モデル対策）・`_is_truncated` を既に保有。diff は Tool Use↔JSON mode の provider 差 |
| **C1** .txt 直接処理＋combine-rows | `--combine-rows`/`--block-size`/`combine_rows_to_chunks` を既に保有（むしろ anthropic は .txt 拒否） |
| **A4** 介入の一時停止（is_paused） | `grace/executor.py` に `is_paused` の set/clear と yield 再開を既に保有 |

---

## 🔵 provider 差／構造等価（移植不要・任意）

- **A2/A3** フォールバック連鎖・RAG十分度：ollama は `_execute_dynamic_web_search` / `_execute_dynamic_ask_user` ＋スコア分岐で **機能的に等価**を別実装済み。anthropic の `_execute_fallback_chain`（config 連動）への置換は「動く実装の構造リファクタ」であり機能的な穴ではない。**任意・高リスク・実機必須**。

---

## 🟡 真に残っている項目（いずれも実機検証前提・任意）

- [ ] **D2. pipeline の Celery 経路への逐次永続化配線**（中／**Celery+Redis 実機必須**）
  - #67 で `collect_results` に `on_result` フックは追加済み。残りは `_generate_with_celery` から `on_result=_append_progress` 相当を渡す配線。
  - ⚠️ 設計上の論点：Celery はバッチ（`batch_chunks`）単位のタスクで、`on_result(idx, qa_pairs)` の idx は **task 投入インデックス**。一方 sync 経路の再開キーは **chunk_id**。両者の整合（バッチ→chunk_id 展開、または task-idx ベースの別 progress ファイル）を設計し、実機で再開挙動を検証する必要がある。
- [ ] **A2/A3 構造統一**（任意）：上記「機能等価」を anthropic 実装へ揃える場合のみ。実機必須。
- [ ] **C2. 登録経路 delegation 一本化**（保留・要意味論調整）：ollama `run_registration` は意図的に「question のみ embedding（不具合B修正）」。`register_to_qdrant`（detect_text_column）への委譲一本化は意味論差の調整が必要。実機必須。

---

## 検証メモ

- 当面の検証は `ruff check .` ＋ `python -m compileall`（`pydantic`/Qdrant/Ollama/`pytest`/Celery+Redis は未導入）。
- D2・A2/A3・C2 は**実機（Ollama/Qdrant/Celery+Redis）での回帰確認を必須**とする。
