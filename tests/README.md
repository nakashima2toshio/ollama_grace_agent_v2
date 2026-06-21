# tests/ テストスイート一覧

`ollama_grace_agent` のテスト一覧。anthropic_grace_agent から移植し、Ollama 構成
（`gemma4:e4b` / `nomic-embed-text`(768次元) / `{"qa_pairs":[...]}` / API キー不要 /
`*_ollama` コレクション）に読み替えている。

- 合計: **31 テストファイル / 342 テスト関数**
- 実行: `pytest tests/`（`pyproject.toml` の `[tool.pytest.ini_options] pythonpath=["."]`）
- 実機依存の統合テストは **`RUN_OLLAMA_INTEGRATION=1`** のときのみ実行（既定では skip）
- CI: `.github/workflows/ci.yml` の `unit-tests` ジョブで `pytest tests/` を実行（現状 advisory）

## スキップされる統合テスト（4件）

`uv run pytest tests/` を素で実行すると `317 passed, 4 skipped` となる。スキップされる 4 件は
すべて **実 Ollama / Qdrant を使う統合テスト**で、環境変数 **`RUN_OLLAMA_INTEGRATION=1`** を
付けたときのみ実行される（未設定だと各クラスの `@pytest.mark.skipif` でスキップ）。
ネットワーク・モデル応答の揺らぎ・登録データの有無で結果が変わるため、CI や依存のない環境で
赤くならないよう **既定では除外（opt-in 方式）** にしてある。

### `tests/grace/test_executor_integration.py`（2件）

Planner と Executor を **モックなしの実 LLM・実 Qdrant** で連携させる完全統合テスト。
前提: ① Ollama 起動、② Qdrant 起動、③ Qdrant に Wikipedia 系 QA データ
（`a02_qa_pairs_wikipedia_ja.csv` 等）が登録済み。

| テスト | 確認内容 |
|---|---|
| `test_execute_plan_generator_flow` | クエリ（スペイン語の文法・単語は何語の影響を受けるか）を計画化し、`execute_plan_generator`（**ストリーミング/逐次**実行）でステップを回す。`ExecutionResult` が `success`、信頼度が算出され、期待キーワード（ラテン語/アラビア語）を含むか確認 |
| `test_execute_plan_blocking_flow` | 同種クエリを `execute_plan`（**ブロッキング=一括**実行）で流し、`overall_status == "success"` と `final_answer` が返ることを確認 |

### `tests/grace/test_planner_integration.py`（2件）

Planner 単体を **実 Ollama LLM** で動かすテスト。

| テスト | 確認内容 |
|---|---|
| `test_create_plan_real_llm` | `force_llm_plan = True` で **LLM 計画生成を強制**し、返る計画が `ExecutionPlan` 構造を満たすか（`original_query` 一致／ステップ数 > 0／`complexity > 0`／**最終ステップが必ず `reasoning`**）を検証。内容は変動するため構造のみチェック |
| `test_create_plan_rule_based_no_llm` | 単純クエリ（「Pythonとは何ですか」）では **LLM を呼ばずルールベース計画**（2ステップ＝`rag_search` → `reasoning`）になることを確認。実質 LLM 非依存だが同クラスの skipif 対象のため一緒にスキップされる |

実行方法は「[3. 統合テストの実行（実 Ollama / Qdrant が必要）](#3-統合テストの実行実-ollama--qdrant-が必要)」を参照。

## 凡例

- **種別**: `unit`（モックベース・外部サービス不要） / `integration 🔌`（実 Ollama/Qdrant 必須・`RUN_OLLAMA_INTEGRATION=1`）
- **Ollama適応**: `読替`（provider/モデル/次元を Ollama 値へ調整して移植） / `そのまま`（provider 非依存で verbatim 移植） / `新規`（Ollama 用に作り直し）
- **状態**: 現状すべて「静的検証（`ruff check .` + `compileall`）まで。実機 pytest 実行は #83 の CI ジョブで担保予定」

---

## テストの実行方法

### 1. 依存のインストール

本プロジェクトは **uv** で管理されている（`pyproject.toml` ＋ `uv.lock`）。**uv を推奨**。

#### 1-a. uv（推奨）

```bash
# uv 未導入なら: pipx install uv  または  pip install uv

# uv.lock に基づいて同期（[project].dependencies ＋ dev グループ=ruff/pytest を含む）
uv sync

# テストは uv 管理の仮想環境で実行する（下記「実行」も同様に uv run を前置）
uv run pytest tests/
```

> `uv sync` は既定で `dev` グループ（`pytest` / `pytest-asyncio` / `ruff`）も入れる。
> dev を除く場合は `uv sync --no-dev`。

uv のまま requirements を使う場合:

```bash
uv pip install -r requirements.txt
```

#### 1-b. pip（uv を使わない場合）

最小構成:

```bash
pip install pytest pytest-asyncio pydantic pandas numpy \
  qdrant-client tiktoken scikit-learn pyyaml
```

完全再現が必要な場合はプロジェクトの依存を入れる:

```bash
pip install -r requirements.txt
```

> 以降のコマンドは pip 前提で記載する。uv を使う場合は各 `pytest ...` を **`uv run pytest ...`** に読み替える。

### 2. ユニットテストの実行（外部サービス不要）

`pyproject.toml` に `pythonpath = ["."]` が設定済みのため、リポジトリ直下から実行する。

```bash
# 全ユニットテスト（統合テストは RUN_OLLAMA_INTEGRATION 未設定で自動 skip）
pytest tests/

# ディレクトリ単位
pytest tests/grace/
pytest tests/services/

# ファイル単位
pytest tests/grace/test_confidence.py

# クラス／関数を指定（"::" で絞り込み）
pytest tests/grace/test_config.py::TestConfigModels
pytest tests/grace/test_config.py::TestConfigModels::test_llm_config_defaults

# 名前で部分一致フィルタ
pytest tests/ -k "confidence and not integration"
```

### 3. 統合テストの実行（実 Ollama / Qdrant が必要）

`integration 🔌` のテスト（`tests/grace/test_executor_integration.py` / `test_planner_integration.py`）は、
**`RUN_OLLAMA_INTEGRATION=1`** を付け、かつ Ollama（`gemma4:e4b`）と Qdrant がローカル起動している場合のみ実行される。

```bash
# 前提: ollama serve / docker-compose で Qdrant 起動済み
RUN_OLLAMA_INTEGRATION=1 pytest tests/grace/test_executor_integration.py -v
```

> 補足: `pyproject.toml` には `integration` マーカーも定義済み（`-m "not integration"` 等で利用可）。現状の統合テストは `RUN_OLLAMA_INTEGRATION` 環境変数の skipif で制御している。

---

## テスト結果の見方

### 1. 端末での読み方

```bash
# 進捗ドットを抑えて簡潔に（推奨）
pytest tests/ -q

# 詳細（テスト名を1行ずつ表示）
pytest tests/ -v

# skip された理由を一覧表示（統合テストが何故 skip されたか分かる）
pytest tests/ -rs

# 失敗時のトレースバックを短く
pytest tests/ --tb=short

# 最初の失敗で停止 / 直近失敗のみ再実行
pytest tests/ -x
pytest tests/ --lf
```

出力末尾のサマリ行の読み方:

```
==== 12 passed, 4 skipped, 1 failed in 3.21s ====
```

- `passed` 成功 / `failed` 失敗 / `skipped` スキップ（統合テスト等）/ `error` 収集・前処理エラー
- 失敗は `FAILED tests/...::test_xxx` の行＋トレースバックで原因箇所を特定する。
- `-rs` を付けると `SKIPPED [1] tests/...: 実Ollama統合テストは RUN_OLLAMA_INTEGRATION=1 のときのみ実行` のように理由が出る。

### 2. レポート出力（CI 連携・履歴保存）

```bash
# JUnit XML（CI の test-results 連携用）
pytest tests/ --junitxml=test-results.xml

# HTML レポート（要 pip install pytest-html）
pytest tests/ --html=report.html --self-contained-html

# カバレッジ（要 pip install pytest-cov）
pytest tests/ --cov=. --cov-report=term-missing --cov-report=html
# → htmlcov/index.html をブラウザで開く
```

### 3. CI（GitHub Actions）の結果を見る

`.github/workflows/ci.yml` の `unit-tests` ジョブで `pytest tests/ -q -rs` が実行される（現状 advisory）。

- **GitHub の Web UI**: 対象 PR の「Checks」タブ →「CI / pytest (unit, integration skipped)」のログ。
- **`gh` CLI**:
  ```bash
  gh run list --workflow CI            # 直近の実行一覧
  gh run view <run-id> --log           # ログ全文
  gh run view <run-id> --log-failed    # 失敗ステップのみ
  ```

> 注: `unit-tests` は `continue-on-error: true` の advisory ジョブのため、テストが赤でも `auto-merge` はブロックされない。安定して緑になったら blocking 化し `auto-merge` の `needs` に追加する（`ci.yml` のコメント参照）。

---

## 1. GRACE 自律エージェント（`tests/grace/` ＋ root 一部）

| 対象モジュール | テストモジュール | 関数数 | 種別 | Ollama適応 | 由来PR | テスト内容 |
|---|---|---:|---|---|---|---|
| `grace/schemas.py` | `grace/test_schemas.py` | 17 | unit | そのまま | #69 | PlanStep/ExecutionPlan/StepResult/ExecutionResult スキーマ・Enum・依存検証 |
| `grace/config.py` | `grace/test_config.py` | 14 | unit | 読替 | #69 | LLM/Embedding/Confidence/Planner/Executor 既定値、YAML/環境変数上書き、シングルトン、重み合計=1.0 |
| `grace/confidence.py` | `grace/test_confidence.py` | 33 | unit | そのまま | #71 | Factors/Score、Calculator、LLMSelfEvaluator（evaluate/evaluate_final）、SourceAgreement、QueryCoverage、Aggregator |
| `grace/executor.py` | `grace/test_executor.py` | 12 | unit | そのまま | #72 | ExecutionState、execute_plan、cancel、fallback、create_executor |
| `grace/intervention.py` | `grace/test_intervention.py` | 40 | unit | そのまま | #70 | InterventionRequest/Response、Handler、動的閾値、確認フロー、ファクトリ |
| `grace/replan.py` | `grace/test_replan.py` | 58 | unit | そのまま | #70 | ReplanTrigger/Strategy/Context/Result、Manager/Orchestrator、依存処理、拡張クエリ生成 |
| `grace/planner.py` | `grace/test_planner.py` | 32 | unit | 読替 | #62 | 二層計画（複雑度推定・ルールベース/LLM 計画）、フォールバック、refine、プロンプト、依存検証 |
| 横断（Plan→Executor→Confidence→Intervention） | `grace/test_grace_integration.py` | 10 | unit | そのまま | #73 | 各フェーズの統合（モック） |
| `grace/executor.py`＋`planner.py` | `grace/test_executor_integration.py` | 2 | integration 🔌 | 読替 | #73 | 実 LLM/Qdrant での Plan+Executor 連携 |
| `grace/planner.py` | `grace/test_planner_integration.py` | 2 | integration 🔌 | 読替 | #73 | 実 LLM での計画生成 |
| `grace/tools.py` | `grace/test_dynamic_thresholding.py` | 3 | unit | そのまま | #81 | RAGSearchTool の動的スコア閾値 |
| `grace/confidence.py` | `grace/test_confidence_fix.py` | 3 | unit | そのまま | #81 | ConfidenceFactors/Score の回帰修正 |
| `grace/calibration.py` | `grace/test_calibration.py` | 18 | unit | そのまま | v2 | 温度スケーリング（apply/fit）、ECE 縮小、Calibrator 永続化・恒等フォールバック |
| `grace/memory.py` | `grace/test_memory.py` | 17 | unit | そのまま | v2 | キーワード抽出、JSONL 記録/読込、コレクション事前分布（score 順・キーワード絞込）、best_collection 閾値 |
| `grace/llm_compat.py` | `grace/test_llm_compat.py` | 14 | unit | 読替 | v2 | genai 互換 Ollama アダプタ（既定 ollama／model 伝播／gemini ルーティング／遅延初期化／JSON 抽出） |

## 2. サービス層（`tests/services/`）

| 対象モジュール | テストモジュール | 関数数 | 種別 | Ollama適応 | 由来PR | テスト内容 |
|---|---|---:|---|---|---|---|
| `services/qdrant_service.py` | `services/test_qdrant_service.py` | 22 | unit | 読替 | #80 | 埋め込みパラメータ、embed、build_points（安定ID・内容ハッシュ・ゼロベクトル廃止）、merge、行フィルタ。※モジュールキャッシュ分離フィクスチャ |
| `services/cache_service.py` | `services/test_cache_service.py` | 4 | unit | そのまま | #74 | MemoryCache、cache_result デコレータ |
| `services/config_service.py` | `services/test_config_service.py` | 6 | unit | 読替 | #79 | ConfigManager（既定 gemma4:e4b/YAML/環境変数/再読込） |
| `services/dataset_service.py` | `services/test_dataset_service.py` | 4 | unit | そのまま | #74 | データセット読込・テキスト抽出 |
| `services/file_service.py` | `services/test_file_service.py` | 4 | unit | そのまま | #74 | ファイル入出力 |
| `services/json_service.py` | `services/test_json_service.py` | 6 | unit | そのまま | #74 | JSON 抽出・整形・パース |
| `services/log_service.py` | `services/test_log_service.py` | 3 | unit | そのまま | #74 | 未回答ログの記録/読込/クリア |
| `services/qa_service.py` | `services/test_qa_service.py` | 3 | unit | そのまま | #74 | QAPair、Q/A 生成・保存 |
| `services/token_service.py` | `services/test_token_service.py` | 6 | unit | そのまま | #78 | TokenManager（トークン推定・コスト表） |

## 3. Q/A 生成（`tests/qa_generation/`）

| 対象モジュール | テストモジュール | 関数数 | 種別 | Ollama適応 | 由来PR | テスト内容 |
|---|---|---:|---|---|---|---|
| `qa_generation/smart_qa_generator.py`＋`pipeline.py` | `qa_generation/test_smart_qa_and_persistence.py` | 8 | unit | 読替 | #77 | SmartQAGenerator 単段生成（`{"qa_pairs"}`）、逐次永続化・再開、manifest 検証 |
| `qa_generation/semantic.py` | `qa_generation/test_semantic.py` | 10 | unit | 読替 | #77 | SemanticCoverage（nomic-embed-text/768・段落分割・埋め込み） |
| `qa_generation/evaluation.py` | `qa_generation/test_evaluation.py` | 1 | unit | そのまま | #77 | analyze_coverage（カバレッジ評価） |

## 4. チャンキング（`tests/chunking/`）

| 対象モジュール | テストモジュール | 関数数 | 種別 | Ollama適応 | 由来PR | テスト内容 |
|---|---|---:|---|---|---|---|
| `chunking/csv_text_to_chunks_text_csv.py`＋`checkpoint_manager.py` | `chunking/test_document_chunking.py` | 17 | unit | そのまま | #78 | 文書単位分割、規則ベース連続性、トークン計数、Embedding 上限強制、E2E |

## 5. ヘルパー（`tests/helpers/`）

| 対象モジュール | テストモジュール | 関数数 | 種別 | Ollama適応 | 由来PR | テスト内容 |
|---|---|---:|---|---|---|---|
| `helper/helper_embedding.py` | `helpers/test_helper_embedding.py` | 9 | unit | 新規 | #84 | create_embedding_client、OllamaEmbedding（768）/OpenAIEmbedding、get_embedding_dimensions |
| `helper/helper_llm.py` | `helpers/test_helper_llm.py` | 6 | unit | 新規 | #85 | create_llm_client、OllamaClient（generate_content/structured/count_tokens） |

## 6. 登録メタデータ・その他

| 対象モジュール | テストモジュール | 関数数 | 種別 | Ollama適応 | 由来PR | テスト内容 |
|---|---|---:|---|---|---|---|
| `services/qdrant_service.py` | `services/test_qdrant_service_metadata.py` | 1 | unit | 読替 | #82 | payload からの埋め込みメタデータ読取 |
| `services/qdrant_service.py` | `services/test_register_qdrant_metadata.py` | 2 | unit | 読替 | #82 | build_points のメタデータ付与・取得 round-trip |
| `services/qdrant_service.py` | `services/test_metadata_and_full_process.py` | 2 | unit | 読替 | #82 | 全件メタデータ付与＋payload 優先 |
| （CSV ロジック・自己完結） | `test_make_qa_register_qdrant_csv.py`（root） | 2 | unit | そのまま | #81 | UI 用 CSV 出力（プロジェクト import なし） |

---

## 既知の TODO / 改善余地

- ✅ **root 直下のテスト整理（完了）**: `test_planner.py`・`test_confidence_fix.py`・`test_dynamic_thresholding.py` を `tests/grace/` へ、metadata 3件を `tests/services/` へ移動済み（`sys.path` 階層も調整）。`test_make_qa_register_qdrant_csv.py`（プロジェクト import なしの自己完結）のみ root に残置。
- **未移植（実サービス前提）**: `test_collection`（実 Qdrant 接続）・`test_agent_4operations`（ReAct）・`agents/`・`legacy/` は、CI の services コンテナ（Ollama/Qdrant/Redis）整備とあわせて実機で移植する。
- **実機実行**: 現状すべて静的検証のみ。#83 の `unit-tests` CI ジョブが緑で安定したら `auto-merge` の `needs` に加え blocking 化する。
- **依存**: 実行には `pydantic` / `pytest` / `pandas` / `numpy` / `qdrant-client` / `tiktoken` / `scikit-learn` 等が必要（当面ローカル未導入のため CI で実行）。
