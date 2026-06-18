# ベンチマーク関連ファイル一覧

## 0. 必要データファイルの一覧

### データ準備フロー

```
HuggingFace
    ↓ (1) down_load_non_qa_rag_data_from_huggingface.py
OUTPUT/cc_news.txt
OUTPUT/cc_news_2per.csv
    ↓ (2) chunking/csv_text_to_chunks_text_csv.py
output_chunked/cc_news_2per_chunks.csv
    ↓ (3) qa_qdrant/make_qa_register_qdrant.py
Qdrant コレクション（各プロジェクト別）
    ↓ (4) run_benchmark.sh
logs/benchmark_results.csv
```

---

### (1) HuggingFaceからダウンロードしたファイル

実行スクリプト: `down_load_non_qa_rag_data_from_huggingface.py`（Streamlit UI）

| ファイル | 説明 | 行数 |
|---|---|---|
| `OUTPUT/cc_news.txt` | cc_newsニュース本文テキスト（改行区切り） | 499行 |
| `OUTPUT/cc_news_2per.csv` | cc_news 2%サンプル・前処理済みCSV | 7,319行 |
| `OUTPUT/metadata_cc_news.json` | ダウンロード時のメタデータ（件数・日時など） | - |

---

### (2) チャンクファイル

実行スクリプト: `chunking/csv_text_to_chunks_text_csv.py`

**バッチコマンド:**

```bash
uv run python -m chunking.csv_text_to_chunks_text_csv \
  --input-file OUTPUT/cc_news_2per.csv \
  --output output_chunked \
  --model claude-haiku-4-5-20251001 \
  --workers 2
```

| ファイル | 説明 | 行数 |
|---|---|---|
| `output_chunked/cc_news_2per_chunks.csv` | セマンティックチャンク済みCSV（LLMチャンク） | 1,418行 |
| `output_chunked/cc_news_2per_chunks_simple.csv` | シンプル分割チャンクCSV | 1,418行 |

---

### (3) Qdrant登録用ファイル

実行スクリプト: `qa_qdrant/make_qa_register_qdrant.py`

**バッチコマンド:**

```bash
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_2per_chunks.csv \
  --collection cc_news_2per_anthropic \
  --model claude-haiku-4-5-20251001 \
  --concurrency 4 \
  --use-celery \
  --recreate
```

| ファイル | 説明 | 行数 |
|---|---|---|
| `OUTPUT/cc_news_2per_anthropic.csv` | Anthropic向けQ/Aペア（Qdrant登録済み） | 11行 |
| `OUTPUT/cc_news_2per_openai.csv` | OpenAI向けQ/Aペア（Qdrant登録済み） | 11行 |
| `OUTPUT/cc_news_2per_gemini.csv` | Gemini向けQ/Aペア（Qdrant登録済み） | 11行 |
| `qa_output/qa_pairs_cc_news_2per_chunks.csv` | Q/A生成結果全件CSV | 3,536行 |
| `qa_output/pipeline/qa_pairs_cc_news_2per_chunks_*.csv` | タイムスタンプ付き生成結果 | 3,536行 |

---

### (4) 各プロジェクトが作成するファイル一覧

4プロジェクト（anthropic / openai / gemini / ollama）それぞれで同一手順を実行し、
プロジェクト固有のコレクションとベンチマーク結果を作成する。

| プロジェクト | Qdrantコレクション名 | ベンチマーク結果 | モデル |
|---|---|---|---|
| `anthropic_grace_agent` | `cc_news_2per_anthropic` | `logs/benchmark_results.csv` | `claude-sonnet-4-6` |
| `openai_grace_agent` | `cc_news_2per_openai` | `logs/benchmark_results.csv` | `gpt-4o`（相当） |
| `gemini_grace_agent` | `cc_news_2per_gemini` | `logs/benchmark_results.csv` | `gemini-*` |
| `ollama_grace_agent` | `cc_news_2per_ollama` | `logs/benchmark_results.csv` | ローカルモデル |

**4プロジェクト結合比較:** `run_benchmark_all.sh` を実行すると `benchmark_combined.csv` を生成。

```bash
# 4プロジェクトのCSVを1つに結合して比較
cd /Users/nakashima_toshio/PycharmProjects
bash run_benchmark_all.sh
# → benchmark_combined.csv（project × level 別の平均値サマリー）
```

---

## 1. 6月1日以降の改修プログラム一覧

| # | ファイル名 | PR / コミット | 改修概要 |
|---|---|---|---|
| 1 | `grace/executor.py` | PR #15 (6/1) | `_evaluate_rag_relevance` が OpenAI API を誤って呼び出すバグを修正 → Anthropic API を正しく使用するよう修正 |
| 2 | `down_load_non_qa_rag_data_from_huggingface.py` | PR #16 (6/2) | cc_news ダウンロード時の出力ファイル名をサイドバーから変更可能に変更（デフォルト: `cc_news_2per.csv`） |
| 3 | `helper/helper_rag.py` | PR #16 (6/2) | `save_files_to_output()` に `output_name` パラメータを追加し、任意ファイル名での保存に対応 |
| 4 | `down_load_non_qa_rag_data_from_huggingface.py` | PR #17 (6/2) | HuggingFace `datasets` 再インポート時に PyArrow 拡張型が二重登録されるエラーを修正（早期リターンガードを追加） |
| 5 | `down_load_non_qa_rag_data_from_huggingface.py` | PR #18 (6/2) | `st.dataframe(width='stretch')` → `use_container_width=True` に修正（3箇所、TypeError解消） |
| 6 | `qa_generation/smart_qa_generator.py` | PR #19 (6/2) | `json.loads()` → `json.JSONDecoder().raw_decode()` に変更し、LLMがJSONの後に余分なテキストを返す場合のパースエラーを修正 |
| 7 | `celery_tasks.py` | PR #19 (6/2) | `collect_results()` で `qa_count=0`（正常完了）を失敗扱いしていたバグを修正、WARNINGをDEBUGに変更 |
| 8 | `celery_tasks.py` | PR #20 (6/2→6/3) | `collect_results()` に5%刻みの進捗ログを追加（コンソールが止まって見える問題を解消） |
| 9 | `start_celery.sh` | PR #20 (6/2→6/3) | `stop` / `restart` コマンドにRedisキューパージ（`celery purge`）を追加（再起動時に残タスクが再処理される問題を解消） |
| 10 | `chunking/csv_text_to_chunks_text_csv.py` | 2026-0603-1/2 (6/3) | チャンク分割スクリプトの出力ファイル名・処理の調整（`cc_news_2per_chunks.csv` 生成対応） |
| 11 | `run_benchmark_all.sh` | 2026-0601-1 (6/1) | 4プロジェクト（anthropic/openai/gemini/ollama）のベンチマーク結果CSVを結合・比較するシェルスクリプトを新規追加 |
| 12 | `logs/benchmark_results.csv` | PR #21 (6/3) | マージコンフリクトマーカーと旧データを削除し、2026-06-03の正常データ36行のみに整理 |

---

## 2. 改修の主な目的別分類

| 分類 | 件数 | 主なファイル |
|---|---|---|
| バグ修正 | 5件 | `grace/executor.py`, `qa_generation/smart_qa_generator.py`, `celery_tasks.py`, `down_load_non_qa_rag_data_from_huggingface.py`×2 |
| 機能改善 | 3件 | `celery_tasks.py`（進捗表示）, `start_celery.sh`（キューパージ）, `helper/helper_rag.py`（ファイル名変更） |
| 機能追加 | 2件 | `down_load_non_qa_rag_data_from_huggingface.py`（ファイル名UI）, `run_benchmark_all.sh`（新規） |
| データ整理 | 2件 | `chunking/csv_text_to_chunks_text_csv.py`, `logs/benchmark_results.csv` |

---

## 3. コマンド別・必要ファイル一覧

### ① Q/A生成 + Qdrant登録

```bash
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_2per_chunks.csv \
  --collection cc_news_2per_anthropic \
  --model claude-haiku-4-5-20251001 \
  --concurrency 4 \
  --use-celery \
  --recreate
```

| 種別 | ファイル / リソース | 状態 |
|---|---|---|
| 入力ファイル | `output_chunked/cc_news_2per_chunks.csv` | ✅ 存在（1418行） |
| スクリプト | `qa_qdrant/make_qa_register_qdrant.py` | ✅ 存在 |
| 環境変数 | `.env`（ANTHROPIC_API_KEY, GOOGLE_API_KEY） | ローカルのみ（リポジトリ管理外） |
| インフラ | Qdrant（localhost:6333） | 実行前に起動が必要 |
| インフラ | Redis + Celeryワーカー（`--use-celery` 使用時） | 実行前に起動が必要 |

### ② ベンチマーク実行

```bash
./run_benchmark.sh
```

| 種別 | ファイル / リソース | 状態 |
|---|---|---|
| スクリプト | `run_benchmark.sh` | ✅ 存在 |
| モジュール | `grace/benchmark.py` | ✅ 存在 |
| Qdrantコレクション | `cc_news_2per_anthropic` | ①実行後に作成される |
| 環境変数 | `.env`（ANTHROPIC_API_KEY） | ローカルのみ（リポジトリ管理外） |
| インフラ | Qdrant（localhost:6333） | 実行前に起動が必要 |
| 出力先 | `logs/benchmark_results.csv` | ✅ 存在（36行・クリーン済み） |

---

## 4. 実行手順

```bash
# Step 1: Qdrant起動
docker-compose -f docker-compose/docker-compose.yml up -d

# Step 2: Celeryワーカー起動（①のみ必要）
./start_celery.sh restart -c 4 --flower

# Step 3: Q/A生成 + Qdrant登録
uv run python qa_qdrant/make_qa_register_qdrant.py \
  --input-file output_chunked/cc_news_2per_chunks.csv \
  --collection cc_news_2per_anthropic \
  --model claude-haiku-4-5-20251001 \
  --concurrency 4 \
  --use-celery \
  --recreate

# Step 4: ベンチマーク実行（Step 3完了後）
./run_benchmark.sh
```

> **注意**: `run_benchmark.sh` は `cc_news_2per_anthropic` コレクションが Qdrant に登録済みであることを前提としています。必ず Step 3 完了後に実行してください。
