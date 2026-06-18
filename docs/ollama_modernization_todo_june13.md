# ollama_grace_agent 最新化 TODO（全面改訂版・プログラム主軸）

作成日: 2026-06-13（改訂）
基準: `anthropic_grace_agent` を「正」とする。ollama は 2026-06-10 で更新停止、以降の anthropic 更新が未反映。
調査方法: 全 `.py` のファイル集合比較（anthropic 138 / ollama 83）＋ 共通82ファイルの中身 diff ＋
「6/10 以降に anthropic が変更した実行数（lint一括整形コミット `eea1046`/`3966404` を除外）」＝**純ロジック更新漏れ**を算出。

> 旧版TODO（`ollama_modernization_todo_june13.md`）は CI/テスト/ドキュメントに偏り、**P0〜P3 のロジック更新漏れ（合計 約3,700行）を取りこぼしていた**。本書がそれを正とする。

---

## ⚠️ 大前提：プロバイダー差は「上書きせず取り込む」

ollama は移行時から Anthropic 版と LLM 層が異なる。以下は**最近の更新ではなく既存の実装差**なので、最新化で上書きしないこと。
表1のロジック更新は **Ollama 実装の上に移植**する（anthropic ファイルの丸コピー禁止）。

| 項目 | anthropic（正にしない） | ollama（維持） |
|---|---|---|
| LLM API | `create_llm_client("anthropic", ...)` | `create_llm_client("ollama", ...)` |
| デフォルトモデル | `claude-sonnet-4-6` | `llama3.2` / `gemma4:e4b` |
| QA JSON形式 | 配列 `[...]` + `raw_decode` | オブジェクト `{"qa_pairs": [...]}` |
| コスト計算 | あり（トークン課金） | なし（ローカル実行） |
| Embedding | Gemini 固定（`gemini-embedding-001`） | Ollama/既存構成に読み替え |
| Qdrantコレクション | `*_anthropic` | `*_ollama` |

これらが大差として出るファイル（**移植時に骨格だけ取り込み、API層は触らない**）:
`helper/helper_rag_qa.py`(両者3873行差/うち6/10以降のロジック変更0)・`helper/helper_llm.py`(709行差)・
`grace/benchmark.py`(502行差)・`helper/helper_embedding.py`(386行差)。

---

# P0：ロジック更新漏れの移植（最重要・本丸）

数値 = anthropic が 6/10 以降に変更した純ロジック行数（lint除外）。**この移植が最新化の中核**。
参考コミット（anthropic）: GRACE系=`98c4881`/`364eea5`/`53cbd43`/`4963e6d`/`9658e32`/`4d73265`、
パイプライン系=`39995e4`/`284ade6`/`e0b682e`/`51316f6`/`62ed1c1`/`37de6de`/`2083276`/`f463229`。

## P0-A: チャンキング（文書単位化）

- [ ] **`chunking/csv_text_to_chunks_text_csv.py`（漏れ 905行 +639/-266）** ★最大
  - 行/レコード単位 → **文書単位チャンキング**へ再設計
  - **カバレッジ保証**（原文の取りこぼし防止）
  - **チャンク最大長を Embedding 次元上限と連携**（`2083276`）→ ollama の Embedding 構成値に読み替え
  - **逐次永続化・manifest検証・`main()`分解**（`51316f6`）
  - コスト集計部は **Ollama=コスト無し** に読み替え
- [ ] **`chunking/async_api_client.py`（104行 +72/-32）**：非同期チャンク生成APIの強化を移植
- [ ] `chunking/__init__.py`：公開シンボル追従（lint分は別途 ruff）

## P0-B: Q/A生成 → Qdrant登録 パイプライン

- [ ] **`qa_qdrant/make_qa_register_qdrant.py`（706行 +245/-461）** ★
  - 経路一本化・Step3ルールベース化・登録ロジック統合・重複Q/A除去
- [ ] **`qa_generation/smart_qa_generator.py`（416行 +119/-297）** ★
  - Q/A統合生成・死にフラグ削除・JSON後の余分テキスト対処
  - ⚠️ JSON形式は **Ollama の `{"qa_pairs":[...]}`** を維持（anthropic の配列+`raw_decode` にしない）
- [ ] **`celery_tasks.py`（263行 +180/-83）**
  - 逐次永続化・結果収集の完了順化・進捗ログ・トークン集計 → **コスト集計は無効化/Ollama化**
- [ ] **`qa_generation/pipeline.py`（249行 +207/-42）**：カバレッジ保証・コスト集計・main分解
- [ ] **`qa_qdrant/register_to_qdrant.py`（138行 +102/-36）**：登録一本化・**ポイントID内容ハッシュ化**・並列化
- [ ] **`services/qdrant_service.py`（117行 +97/-20）**：重複Q/A除去・登録メタデータ整備
- [ ] **`qdrant_client_wrapper.py`（16行）**：**安定ポイントID・ゼロベクトル廃止**（`39995e4`）
- [ ] **`qa_qdrant/make_qa.py`（49行）**：make_qa 是正
- [ ] `qa_qdrant/__init__.py`：公開シンボル追従
- [ ] `ui/pages/qdrant_registration_page.py`（7行）：上記に伴うUI追従
  - ⚠️ Embedding は anthropic で **Gemini固定**（`62ed1c1`）。ollama では Embedding 構成に読み替え必須。

## P0-C: GRACE 自律エージェント（Plan/Executor）

- [ ] **`grace/executor.py`（843行 +428/-415）** ★
  - **`eval` 除去**（安全性）・実行経路の一本化・**並列検索実行**・`timeout` 実装
  - legacy経路のジェネレータ`return`修正・`ask_user`応答・**LOW_CONFIDENCEリプラン条件**（`4d73265`/`98c4881`）
- [ ] **`grace/planner.py`（291行 +132/-159）**：二層計画生成・宣言的フォールバック連鎖・複雑度推定統合
- [ ] **`grace/confidence.py`（75行 +74/-1）**：信頼度計算の共通化・統合評価
- [ ] **`grace/config.py`（26行）**：timeout 等の設定追加
- [ ] `grace/schemas.py` / `grace/replan.py`（各2〜4行）：出力構造化・リプラン条件の追従
- [ ] `grace/__init__.py`：公開シンボル追従
  - ⚠️ LLM呼び出しは **Ollama クライアント**を維持。

---

# P1：欠落ファイルの移植

| フォルダ | ファイル | 対応 |
|---|---|---|
| トップ | `qdrant_delete_collection.py` | 移植（コレクション削除CLI、`f5eeea0`） |
| ui/pages | `benchmark_page.py` | 移植（Ollamaモデルに調整） |
| grace/check_code | `test_planner.py`, `test_planner_create_plan.py` | 移植 |

---

# P1：テストスイートの移植（54ファイル欠落）

ollama は `tests/test_planner.py` の **1件のみ**。anthropic は領域別に約55ファイル。

- [ ] ディレクトリ構成 `tests/{grace,services,qa_generation,helpers,chunking,agents,legacy}/` ＋ `__init__.py` / `conftest.py` を移植
- [ ] 各テストを **Ollama 仕様**（モデル名・JSON `{"qa_pairs":...}`・コスト無し・コレクション名）に読み替え
- [ ] 実API/実Qdrant依存（`*_integration`, `verify_fix_logic_real_api.py`）は既存 marker `@pytest.mark.integration` でゲート
- [ ] 移植優先順: `grace/` → `services/`（特に `test_qdrant_service.py`）→ `qa_generation/` → `chunking/` → `helpers/` → 直下

---

# P2：lint / CI 基盤（ollama は未整備）

- [ ] **`.github/workflows/ci.yml` を新規作成**（anthropic `612c748`/`eea1046` を移植：`ruff check .` blocking + compileall + `claude/*` 自動マージ）
- [ ] **ruff 負債解消**：`ruff check . --fix`（現状 **270 errors / 246 自動修正可**）→ 残りを手動。
  - これにより **helper/・services/・agent_*・ui/・config.py 等の "lint整形のみ" 差分はほぼ解消**（＝これらはロジック移植不要）。
  - 自動修正が Ollama API 層のロジックを変えていないことを確認。
- [ ] **`pyproject.toml`**：`[tool.ruff.lint.isort] known-first-party=[...]`（ollama のモジュール名で）＋ `[tool.pytest.ini_options] pythonpath=["."]` を追加

---

# P2：依存・ドキュメント整理

- [x] 重複/誤記 requirements を統合：`requrements.txt`(誤記)・`requirements_fixed.txt` を削除し `requirements.txt`（uv export・ハッシュ付き）に一本化（コード/CI/setup からの参照なしを確認のうえ実施）
- [ ] `grace/docs/` → `grace/doc/` 命名統一＋旧版 `old/` 退避、`qa_generation/doc/` 新設、`chunking/doc/` 再編（anthropic 構成に追従）
- [ ] `CLAUDE.md` 拡充：Mermaid規約(§7)・コーディング規約(§8)・ドキュメント/技術スタック表記統一(§9) を **Ollama 用に読み替えて**追記
- [ ] README + `assets/` 図の追従

---

## 進め方（推奨）

1. **P2 lint/CI を先に**（`ruff --fix` で大量の "整形のみ" 差分を消し込み、以降のロジック diff を見やすくする＋緑化基盤）。
2. **P0-A → P0-B → P0-C** をファイル単位の小PRで移植（各PRで「Ollama仕様が上書きされていないか」を必ず確認）。
3. **P1 テスト移植**を領域ごとに。
4. **P1 欠落ファイル / P2 ドキュメント**を仕上げ。

### 各移植で必ず確認するチェックリスト
- [ ] LLM クライアントが `create_llm_client("ollama", ...)` のままか
- [ ] QA JSON が `{"qa_pairs":[...]}` 形式のままか（配列+`raw_decode` にしていないか）
- [ ] コスト計算を有効化していないか（ローカル＝無し）
- [ ] Embedding を Gemini 固定で持ち込んでいないか（Ollama構成に読み替えたか）
- [ ] Qdrant コレクション名が `*_ollama` か
