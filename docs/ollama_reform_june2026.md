# ollama_grace_agent 6月改修記録

## 前提：anthropic vs ollama の本質的違い

| 項目 | anthropic | ollama |
|---|---|---|
| LLM API | `create_llm_client("anthropic", ...)` | `create_llm_client("ollama", ...)` |
| デフォルトモデル | `claude-sonnet-4-6` | `llama3.2` |
| JSON形式 | 配列 `[...]` + `raw_decode` | オブジェクト `{"qa_pairs": [...]}` + `json.loads` |
| コスト計算 | あり | なし（ローカル実行） |
| Qdrantコレクション | `cc_news_2per_anthropic` | `cc_news_2per_ollama` |

---

## 改修ファイル一覧

| No. | ファイル | 改修概要 | 優先度 |
|---|---|---|---|
| 1 | `celery_tasks.py` | `collect_results()` バグ修正 + 5%刻み進捗ログ追加 | 高 |
| 2 | `qa_generation/smart_qa_generator.py` | `analyze_chunk()` JSONパース修正（`raw_decode`） | 高 |
| 3 | `grace/executor.py` | スタブ追加・インポート移動・`execute()`追加・トークン追跡 | 高 |
| 4 | `helper/helper_rag.py` | `save_files_to_output()` シグネチャ拡張 | 中 |
| 5 | `down_load_non_qa_rag_data_from_huggingface.py` | PyArrow早期リターン・ccnewsシャッフル・出力ファイル名UI | 中 |
| 6 | `start_celery.sh` | stop/restart コマンドに Redis キューパージを追加 | 中 |
| 7 | `chunking/csv_text_to_chunks_text_csv.py` | `save_chunks_as_csv()` 安全チェック確認（既適用） | 低 |
| 8 | `run_benchmark_all.sh` | 新規作成（4プロジェクト比較スクリプト） | 低 |
| 9 | `logs/benchmark_results.csv` | コンフリクトマーカー確認（ファイル不存在のため不要） | 低 |

---

## 各改修の詳細説明

### 1. `celery_tasks.py` - `collect_results()` 修正

**変更前:**
```python
if result:
    all_qa_pairs.extend(result)
    success_count += 1
    logger.debug(f"タスク {i}/{len(tasks)}: ✅ 成功（Q/A数={len(result)}）")
else:
    failed_count += 1
    logger.warning(f"タスク {i}/{len(tasks)}: ⚠️ 結果が空")
```

**変更後:**
- `qa_count=0`（LLMがQ/A不要と判断した正常完了）を `success_count` に計上
- 5%刻みの進捗ログを `report_interval = max(1, total // 20)` で実装

---

### 2. `qa_generation/smart_qa_generator.py` - JSONパース修正

**変更前（`analyze_chunk`内）:**
```python
result = json.loads(text.strip())
```

**変更後:**
```python
# raw_decode: JSONオブジェクト終端以降の余分なテキストを無視
result, _ = json.JSONDecoder().raw_decode(text.strip())
```

`generate_qa_pairs()` 内は既に `raw_decode` 使用。ollama固有の `response_format=json_object` および `{"qa_pairs": [...]}` オブジェクト形式はそのまま維持。

---

### 3. `grace/executor.py` - 複数改善

**a. インポート移動:**
`from .replan import ReplanOrchestrator, create_replan_orchestrator` をモジュール冒頭へ移動（クラス定義前）

**b. スタブ追加（`LEGACY_AGENT_AVAILABLE=False` 時の NameError 防止）:**
```python
class ReActAgent:  # type: ignore[no-redef]
    pass

def get_available_collections_from_qdrant_helper(*args, **kwargs) -> list:
    raise ImportError("services.agent_service is not available")
```

**c. `create_llm_client` スタブ追加:**
ImportError 時に NameError を防ぐスタブを追加

**d. トークン追跡インポート追加:**
```python
try:
    from helper.helper_llm import (
        reset_token_counter as _reset_token_counter,
        get_token_counter   as _get_token_counter,
        LLM_PRICING         as _LLM_PRICING,
    )
    _TOKEN_TRACKING_AVAILABLE = True
except ImportError:
    _TOKEN_TRACKING_AVAILABLE = False
    ...
```

**e. `execute()` メソッド追加（benchmark.py 互換）:**
```python
def execute(self, plan: ExecutionPlan) -> ExecutionResult:
    """execute_plan() の統一エントリーポイント（benchmark.py 互換）"""
    return self.execute_plan(plan)
```

**f. `_execute_step()` トークンリセット/集計追加:**
tool実行前に `_reset_token_counter()`、実行後に `_get_token_counter()` でステップトークン集計

**g. `_create_execution_result()` トークン集計追加:**
ステップ横断トークン合計を集計。ollama はコスト0（`_LLM_PRICING = {}`）

**h. `assert state is not None` 追加:**
`execute_plan_generator` 内で state 型を確定

**i. `state.current_step_id` リセット追加:**
動的 web_search / ask_user 実行後に `state.current_step_id = step.step_id`

---

### 4. `helper/helper_rag.py` - `save_files_to_output()` シグネチャ拡張

**変更前:**
```python
def save_files_to_output(df_processed, dataset_type: str, csv_data: str, text_data: str = None) -> Dict[str, str]:
    ...
    csv_filename = f"preprocessed_{dataset_type}.csv"
```

**変更後:**
```python
def save_files_to_output(df_processed, dataset_type: str, csv_data: str, text_data: str = None, output_name: str = None) -> Dict[str, str]:
    ...
    base_name = output_name if output_name else f"preprocessed_{dataset_type}"
    csv_filename = f"{base_name}.csv"
```

---

### 5. `down_load_non_qa_rag_data_from_huggingface.py` - 3点改善

**a. PyArrow早期リターンガード追加:**
`_import_hf_load_dataset()` 内で `datasets` が正しくインポート済みなら再利用（PyArrow二重登録エラー防止）

**b. cc_news シャッフルオプション追加:**
サイドバーに shuffle / shuffle_seed / shuffle_buffer_size UI を追加し、データセット取得後に `dataset.shuffle()` を適用

**c. 出力ファイル名 UI 追加:**
サイドバーに `output_filename` テキスト入力を追加（デフォルト: `cc_news_2per`）。
`save_files_to_output()` 呼び出し時に `output_name=config['options'].get('output_filename')` を渡す

---

### 6. `start_celery.sh` - Redis キューパージ追加

**追加関数:**
```bash
purge_queues() {
    echo "Redisキューをパージ中..."
    celery -A celery_config purge -f 2>/dev/null && echo "✅ キューパージ完了" || echo "⚠️ キューパージ失敗（ワーカーが停止済みの可能性あり）"
}
```

`stop_workers()` が `purge_queues` → `kill_all_celery` の順で呼び出すように変更。`restart` コマンドは `stop_workers` を経由するため自動的に適用される。

---

### 7. `chunking/csv_text_to_chunks_text_csv.py` - 安全チェック確認

`save_chunks_as_csv()` の安全チェックは既に ollama 版に適用済みであることを確認。変更なし。

```python
if 'tokens' in df.columns and len(df) > 0:
    logger.info(f"  総トークン数: {df['tokens'].sum()}")
    logger.info(f"  平均トークン数: {df['tokens'].mean():.1f}")
else:
    logger.warning("  ⚠️ チャンクが0件です。APIキーを確認してください。")
```

---

### 8. `run_benchmark_all.sh` - 新規作成

4プロジェクト（anthropic / openai / gemini / ollama）の `benchmark_results.csv` を結合して比較するスクリプト。

---

## 実行手順

### 通常のベンチマーク実行（ollama単体）

```bash
cd /path/to/ollama_grace_agent

# 1. Celeryワーカー起動
./start_celery.sh restart -c 8 --flower

# 2. ベンチマーク実行
./run_benchmark.sh
```

### 4プロジェクト横断比較

```bash
cd /Users/nakashima_toshio/PycharmProjects
./ollama_grace_agent/run_benchmark_all.sh
```

---

## 注意事項

- `create_llm_client("ollama", ...)` は変更しない
- `llama3.2` モデル名は変更しない
- `cc_news_2per_ollama` コレクション名は変更しない
- ollama 固有の `response_format={"type": "json_object"}` は変更しない
- コメントの `[MIGRATION openai→ollama]` タグはそのまま維持
