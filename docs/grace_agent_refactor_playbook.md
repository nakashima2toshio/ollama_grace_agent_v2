# GRACE Agent 改修まとめ ＆ 横展開プレイブック

`ollama_grace_agent` で実施した改修（PR #51〜#89）の総まとめと、**同じ作業を
`gemini_grace_agent` / `openai_grace_agent` に適用する**ための手順書。

- 作成日: 2026-06-14
- 基準（ロジックの正）: `anthropic_grace_agent`（6/10 以降に最新化済み）
- 対象: `ollama_grace_agent`（本書の改修済み）→ 横展開先 `gemini_grace_agent` / `openai_grace_agent`
- 関連: `docs/ollama_logic_port_todo_june13.md`（ロジック移植の検証反映版）、
  `docs/ollama_modernization_todo_june13.md`（CI/lint/テスト/docs）、`tests/README.md`

---

## 目次

1. [概要・適用方針](#1-概要適用方針)
2. [⛔ 横展開の鉄則（プロバイダー読み替え表）](#2-横展開の鉄則プロバイダー読み替え表)
3. [プログラム更新一覧](#3-プログラム更新一覧)
   - 3.1 [登録・Q/A・パイプライン系](#31-登録qapイプライン系)
   - 3.2 [GRACE 自律エージェント系](#32-grace-自律エージェント系)
   - 3.3 [リファクターの一覧](#33-リファクターの一覧)
   - 3.4 [基盤・ドキュメント系](#34-基盤ドキュメント系)
4. [テストの一覧](#4-テストの一覧)
5. [インストール](#5-インストール)
6. [横展開の進め方（gemini / openai への適用手順）](#6-横展開の進め方gemini--openai-への適用手順)
7. [検証・残課題](#7-検証残課題)

---

## 1. 概要・適用方針

本改修は **anthropic_grace_agent の 6/10 以降の純ロジック更新（P0–P3 ＋ GRACE）を
正とし、ロジックだけを各リポジトリへ移植**するもの。**プロバイダー層（LLM/Embedding
クライアント・モデル名・次元・コスト・コレクション名・APIキー）は各リポジトリの構成を
維持する。**

改修は次の4系統:

| 系統 | 内容 | 主担当 |
|---|---|---|
| 登録・Q/A・パイプライン | 登録経路一本化、Q/A 単段化、逐次永続化、完了順収集、メタデータ | `qa_qdrant/`・`qa_generation/`・`services/qdrant_service.py`・`celery_tasks.py` |
| GRACE 自律エージェント | eval除去、timeout、並列検索、二層計画、リプラン条件、統合評価 | `grace/` |
| テスト移植 | anthropic の体系的テストを各 provider 仕様で移植 | `tests/` |
| 基盤・ドキュメント | CI(pytest)、CLAUDE.md 規約、requirements 整理、各種 docs | ルート・`.github/`・`docs/` |

> **重要な教訓**: 全ファイル diff はプロバイダー差が支配的で、**「漏れ」と「provider差」を
> 誤認しやすい（偽陽性）**。移植要否は必ず **anthropic の git 履歴（コミット単位、lint一括
> 除外）× 各repo の現状** を照合して判断する。`ollama` では当初の「漏れ 約3,700行」の
> 大半が既実装/provider差/構造等価で、真の未実装は数点だった。

---

## 2. ⛔ 横展開の鉄則（プロバイダー読み替え表）

anthropic を「正」とするのは**ロジックのみ**。下表の provider 値は**各リポジトリの値を維持**する
（anthropic 値で上書きしない）。横展開時はまず対象リポジトリの `CLAUDE.md` と
`grace/config.py` で正しい値を確定すること。

| 項目 | anthropic（正にしない） | ollama（実施済み） | gemini（要確認） | openai（要確認） |
|---|---|---|---|---|
| LLM クライアント | `create_llm_client("anthropic")` | `("ollama")` | `("gemini")` | `("openai")` |
| Embedding クライアント | `create_embedding_client("gemini")` | `("ollama")` | `("gemini")` | `("openai")` |
| デフォルト LLM モデル | `claude-sonnet-4-6` | `gemma4:e4b` | （repo の既定） | （repo の既定） |
| Embedding モデル/次元 | `gemini-embedding-001`/3072 | `nomic-embed-text`/768 | `gemini-embedding-001`/3072 | `text-embedding-3-large`/3072 |
| Q/A JSON 形式 | 配列＋`raw_decode` | `{"qa_pairs":[...]}` | （repo の形式） | （repo の形式） |
| コスト計算 | あり | **なし**（トークン集計のみ） | あり/なし要確認 | あり |
| API キー | `ANTHROPIC_API_KEY` 必須 | 不要 | `GOOGLE_API_KEY` | `OPENAI_API_KEY` |
| Qdrant コレクション | `*_anthropic` | `*_ollama` | `*_gemini` | `*_openai` |
| LLM 数値パース | `float(text)` 直 | regex 抽出（冗長応答対策） | 要確認 | 要確認 |

---

## 3. プログラム更新一覧

PR 番号は ollama での実施 PR。各 repo へは**同等のロジック変更**を provider 値を読み替えて適用する。

### 3.1 登録・Q/A・パイプライン系

| PR | 種別 | 対象 | 内容 |
|---|---|---|---|
| #51 | feat/fix | `qa_qdrant/register_to_qdrant.py`・`qdrant_client_wrapper.py`・`services/qdrant_service.py` | 登録経路一本化、**ポイントID を内容ハッシュ化**（再登録べき等）、**ゼロベクトル廃止→None＋行フィルタ**、先読み並列化、重複Q/A除去 |
| #52 | feat | `qa_generation/smart_qa_generator.py` | **Q/A 生成を2段階→構造化出力1回に単段化**、死にフラグ削除 |
| #53 | feat | `qa_generation/pipeline.py` | 同期(sync)経路に**逐次永続化(JSONL)＋クラッシュ再開**（処理済みチャンクをスキップ） |
| #54 | feat | `qa_qdrant/make_qa.py` | CLI を単段化に整合（死にフラグ撤去・既定モデルを repo 値へ） |
| #55 | feat | `qa_qdrant/make_qa_register_qdrant.py` | 死んだスマート生成フラグ撤去 |
| #67 | feat | `celery_tasks.py` | **`collect_results` を完了順回収＋`on_result` フック化**（HOL ブロッキング解消） |
| #82 | feat | `services/qdrant_service.py` | **`get_collection_embedding_params` が payload の Embedding メタデータを優先読取**（無ければ次元数推論にフォールバック。登録→取得の round-trip 成立） |

### 3.2 GRACE 自律エージェント系（`grace/`）

| PR | 種別 | 対象 | 内容 |
|---|---|---|---|
| #56 | fix(security) | `executor.py` | **危険な `eval(tool_output)` を `ast.literal_eval` に置換**（`_handle_ask_user_response`） |
| #57 | feat | `executor.py` | **ツール実行に `timeout_seconds` 制限**（`_run_tool_with_timeout`・ハング防止） |
| #58 | feat | `config.py` | `PlannerConfig`/`ExecutorConfig` 追加（二層計画・並列検索の設定足場） |
| #59 | refactor | `executor.py` | **`execute_plan`(blocking) を generator へ委譲統合**（二重実行ループ解消） |
| #60 | feat | `executor.py` | **依存なし検索ステップの並列プリフェッチ**（`_prefetch_parallel_searches`） |
| #61/#62 | feat/test | `planner.py` | **二層計画**（複雑度ヒューリスティックで単純質問は LLM 省略・ルールベース計画） |
| #64 | feat | `executor.py` | **リプラン発火条件の精緻化**（`_should_trigger_replan`：低信頼度の検索ステップも対象）＋ ask_user 応答処理の実体化 |
| #65 | feat | `confidence.py`・`executor.py` | **`evaluate_final`（自己評価＋網羅度）で全体信頼度計算を2回→1回**に統合 |
| #66 | refactor | `executor.py`・`schemas.py`・`replan.py` | 信頼度ファクタ構築の共通化（`_build_confidence_factors`）＋出力型を `Optional[Any]` に拡張 |

### 3.3 リファクターの一覧

純粋な構造改善（挙動は同等～改善）。横展開時の**最重要レビュー対象**。

| 内容 | PR | 効果 |
|---|---|---|
| Q/A 生成 2段階 → 構造化出力1回 | #52 | LLM 呼び出し半減・JSON パース簡素化 |
| 実行ループ統合（blocking→generator 委譲） | #59 | 二重実装解消（−78行）、挙動を generator 版に一本化 |
| 信頼度計算 2回 → `evaluate_final` 1回 | #65 | 最終評価レイテンシ半減 |
| 信頼度ファクタ構築の共通化 `_build_confidence_factors` | #66 | 重複60行×2 を集約 |
| `get_collection_embedding_params` を payload 優先に | #82 | 登録メタデータの round-trip 成立 |
| 二層計画（単純質問で LLM 省略） | #61 | 単純質問の LLM 呼び出し 2→0 回 |

### 3.4 基盤・ドキュメント系

| PR | 種別 | 内容 |
|---|---|---|
| #58 | feat | `grace/config.py` に Planner/Executor 設定 |
| #75 | docs | `CLAUDE.md` §7 Mermaid・§8 コーディング・§9 技術スタック表記（provider 読み替え） |
| #76 | chore | 重複/誤記 requirements を削除し `requirements.txt`（uv export）に一本化 |
| #83 | ci | `.github/workflows/ci.yml` に **pytest ジョブ**追加（統合は `RUN_OLLAMA_INTEGRATION` 等でゲート） |
| #63/#68 | docs | ロジック移植 TODO（検証反映版） |
| #86–#89 | docs | `tests/README.md`（テスト一覧・実行/結果/uv）、`docs/setup_and_install.md`（uv export・任意依存の注意） |

---

## 4. テストの一覧

詳細は **`tests/README.md`**（対象モジュール／テストモジュール／関数数／種別／provider適応／由来PR／内容）。ollama では **31 ファイル / 342 関数**。

| 区分 | ディレクトリ | 主な対象 | 由来PR |
|---|---|---|---|
| GRACE | `tests/grace/` | schemas/config/confidence/executor/intervention/replan/統合 | #69–#73 |
| サービス層 | `tests/services/` | qdrant/cache/config/dataset/file/json/log/qa/token | #74,#78,#79,#80 |
| Q/A 生成 | `tests/qa_generation/` | smart_qa＋persistence/semantic/evaluation | #77 |
| チャンキング | `tests/chunking/` | document_chunking | #78 |
| ヘルパー | `tests/helpers/` | helper_embedding/helper_llm（**provider 用に新規作成**） | #84,#85 |
| 登録メタデータ等 | root 直下 | qdrant メタデータ round-trip / CSV | #81,#82 |

**移植の要点（各 repo 共通）:**

- **provider 非依存テスト**（schemas/intervention/replan/confidence/executor 等）は **verbatim 移植**可。
- **provider 結合テスト**（config・semantic・qdrant_service・metadata 等）は **値読み替え**（モデル名・次元・コレクション名）。
- **helpers**（helper_embedding/helper_llm）は anthropic 版が provider 固有・モック不能（ローカル import 等）なので、**各 repo の既定クライアントに合わせて新規作成**する。
- **実機依存テスト**は env ゲート（ollama は `RUN_OLLAMA_INTEGRATION=1`）。各 repo は対応する条件に読み替え。
- 対象モジュールが両 repo とも**非存在**のテスト（keyword_extraction/structure/content/generation 等）は**移植しない**（stale）。
- 当該機能が repo に**未実装**のテスト（例: payload メタデータ読取）は、**機能を実装してからテストを移植**する（ollama では #82）。

---

## 5. インストール

本プロジェクト群は **uv** 管理（`pyproject.toml` ＋ `uv.lock`）。

```bash
# uv 未導入なら: pipx install uv  /  pip install uv
uv sync                 # 本番依存（dev グループ=pytest/ruff 含む）
uv sync --no-dev        # dev を除く場合
uv run pytest tests/    # テストは uv 管理 venv で実行
```

> **`requirements.txt` の再生成は `uv export` を使う。`pip freeze` は禁止。**
> `pip freeze` は仮想環境全体（ビルドツール `setuptools` 等や手動導入パッケージ）を固定し、
> 依存衝突を起こす。
> ```bash
> uv export --format requirements-txt -o requirements.txt
> ```
> 任意依存（例: ollama の `streamlit-mermaid` は `altair<5` 要求で本体 `altair==5.5.0` と
> 非互換）は本体依存に含めず、`try/except` の任意 import として扱う（詳細は
> `docs/setup_and_install.md`）。

---

## 6. 横展開の進め方（gemini / openai への適用手順）

1. **作業ブランチ作成**（各 repo の指定ブランチ）。
2. **§2 の読み替え表を確定**: 対象 repo の `CLAUDE.md`・`grace/config.py`・`helper/` を確認し、
   LLM/Embedding provider・既定モデル・次元・コスト有無・コレクション接尾辞・API キーを把握。
3. **ロジック移植（§3）を PR 単位で適用**（推奨順）:
   1. GRACE の自己完結・低リスク（#56 eval除去 → #57 timeout → #58 config → #59 ループ統合 →
      #60 並列検索 → #61 二層計画 → #64 リプラン条件 → #65 evaluate_final → #66 共通化）
   2. 登録・Q/A 系（#51 → #52 → #53 → #54/#55 → #82 メタデータ → #67 Celery）
   - 各 PR は **anthropic の該当コミットを正に、provider 値だけ読み替え**。既に repo に実装済みの
     ものは**スキップ**（git 履歴 × 現状で確認）。
4. **テスト移植（§4）**: provider 非依存は verbatim、結合は値読み替え、helpers は新規作成。
5. **基盤（§3.4）**: CI に pytest ジョブ、CLAUDE.md 規約、requirements 整理。
6. **検証**: 各 PR で `ruff check .` ＋ `python -m compileall`。実機は対応 env ゲートで pytest。
7. **ドキュメント化**: 本書に相当する `docs/<provider>_refactor_playbook.md` と
   `tests/README.md` を各 repo に作成。

> **偽陽性を避ける**: 全ファイル diff ではなく **anthropic git 履歴のコミット単位**で
> 「genuine な漏れ」を特定する。provider 差・既実装・構造等価は移植不要。

---

## 7. 検証・残課題

- **静的検証**: 全 PR で `ruff check .` ＋ `compileall` を緑に。
- **実機検証（要サービス）**: 並列検索のスレッド安全性、二層計画の閾値、Celery 完了順/逐次永続化、
  登録メタデータ round-trip は **実 LLM/Qdrant/Redis 環境での pytest** を推奨（CI に services
  コンテナ＋統合ジョブを追加し、env ゲートで実行）。
- **ollama での保留事項**（各 repo でも判断要）:
  - pipeline の Celery 経路への逐次永続化配線（バッチ task-idx ↔ chunk_id の再開キー整合）
  - 登録経路の delegation 一本化（embedding 対象カラムの意味論差の調整）
  - root 直下テストの `tests/grace`・`tests/services` への整理
- **未移植（実サービス前提）**: `test_collection`（実 Qdrant）・`test_agent_4operations`・`agents/`・`legacy/`。
