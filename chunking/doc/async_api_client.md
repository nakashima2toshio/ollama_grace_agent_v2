# async_api_client.py - 非同期APIクライアント ドキュメント

**Version 1.1** | 最終更新: 2026-06-21

---

## 目次

1. [概要](#概要)
2. [アーキテクチャ構成図](#1-アーキテクチャ構成図)
3. [モジュール構成図](#2-モジュール構成図)
4. [クラス・関数一覧表](#3-クラス関数一覧表)
5. [クラス・関数 IPO詳細](#4-クラス関数-ipo詳細)
6. [設定・定数](#5-設定定数)
7. [使用例](#6-使用例)
8. [エクスポート](#7-エクスポート)
9. [変更履歴](#8-変更履歴)
10. [付録: 依存関係図](#付録-依存関係図)

---

## 概要

`async_api_client.py`は、Ollama API（OpenAI互換）への非同期アクセスを提供するクライアントモジュールです。`asyncio.to_thread()`で同期APIをラップし、Semaphoreによる並列数制御、指数バックオフによるリトライロジック、切断レスポンスの検出とリトライ機能を備えています。

Ollama は OpenAI 互換エンドポイント（`/v1`）を公開しているため、`openai` SDK を Ollama サーバ（既定 `http://localhost:11434/v1`）に向けて利用します。ローカル実行のため API キーは不要で、ダミー値 `"ollama"` を渡します。構造化出力は Ollama の JSON mode（`response_format={"type": "json_object"}`）を使い、Pydanticスキーマをシステムプロンプトに埋め込んだうえで `model_validate_json()` で検証します。

### 主な責務

- Ollama API（OpenAI互換）への非同期リクエスト送信
- Semaphoreによる並列実行数の制御（デフォルト8並列）
- 指数バックオフによるリトライロジック（最大3回）
- 切断レスポンス（`finish_reason == "length"`）の検出と自動リトライ
- JSON mode + スキーマ埋め込みによる構造化出力（`model_validate_json()`で検証）
- レート制限/クォータエラーへの対応
- API呼び出し統計情報の収集・管理

### 主要機能一覧

| 機能 | 説明 |
|------|------|
| `AsyncAPIClient` | 非同期APIクライアントクラス |
| `AsyncAPIClient.__init__()` | コンストラクタ（並列数、リトライ設定。APIキー不要） |
| `AsyncAPIClient.generate_content()` | セマフォ制御でOllama API呼び出し |
| `AsyncAPIClient._execute_with_retry()` | リトライロジック実行（プライベート） |
| `AsyncAPIClient._is_truncated()` | レスポンス切断チェック（プライベート） |
| `_resolve_schema_refs()` | JSON Schema の `$ref`/`$defs` をフラット化（モジュール関数） |
| `AsyncAPIClient.get_stats()` | API呼び出し統計情報を取得 |
| `AsyncAPIClient.reset_stats()` | 統計情報をリセット |

---

## 1. アーキテクチャ構成図

### 1.1 システム全体構成

```mermaid
flowchart TB
    subgraph CLIENT["クライアント層"]
        CHUNKER[csv_text_to_chunks_text_csv.py]
        BATCH[バッチ処理スクリプト]
        TEST[テストコード]
    end

    subgraph MODULE["async_api_client.py"]
        ASYNC_CLIENT[AsyncAPIClient]
    end

    subgraph EXTERNAL["外部サービス層"]
        GEMINI["Ollama API"]
    end

    CHUNKER --> ASYNC_CLIENT
    BATCH --> ASYNC_CLIENT
    TEST --> ASYNC_CLIENT
    ASYNC_CLIENT --> GEMINI
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class CHUNKER,BATCH,TEST,ASYNC_CLIENT,GEMINI default
style CLIENT fill:#1a1a1a,stroke:#fff,color:#fff
style MODULE fill:#1a1a1a,stroke:#fff,color:#fff
style EXTERNAL fill:#1a1a1a,stroke:#fff,color:#fff
```

### 1.2 データフロー

1. クライアント層から`generate_content()`を呼び出し
2. Semaphoreで並列数を制御（最大8並列）
3. `asyncio.to_thread()`で同期API（`client.chat.completions.create()`）を非同期実行（JSON mode）
4. レスポンス検証（切断チェック、`model_validate_json()`によるスキーマ検証）
5. 失敗時は指数バックオフでリトライ（最大3回）
6. 成功時はJSONテキストを返却、全リトライ失敗時は`None`を返却

---

## 2. モジュール構成図

### 2.1 内部モジュール構成

```mermaid
flowchart TB
    subgraph ASYNC_CLIENT["AsyncAPIClient クラス"]
        INIT["__init__()"]

        subgraph PUBLIC["公開メソッド"]
            GEN["generate_content()"]
            STATS["get_stats()"]
            RESET["reset_stats()"]
        end

        subgraph PRIVATE["プライベート/モジュール関数"]
            RETRY["_execute_with_retry()"]
            TRUNCATED["_is_truncated()"]
            RESOLVE["_resolve_schema_refs()"]
        end
    end

    INIT --> GEN
    GEN --> RETRY
    RETRY --> RESOLVE
    RETRY --> TRUNCATED
    RETRY --> STATS
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class INIT,GEN,STATS,RESET,RETRY,TRUNCATED,RESOLVE default
style ASYNC_CLIENT fill:#1a1a1a,stroke:#fff,color:#fff
style PUBLIC fill:#1a1a1a,stroke:#fff,color:#fff
style PRIVATE fill:#1a1a1a,stroke:#fff,color:#fff
```

### 2.2 外部依存関係

| ライブラリ | バージョン | 用途 |
|-----------|-----------|------|
| `openai` | >= 1.100.2 | Ollama（OpenAI互換エンドポイント）クライアント |
| `pydantic` | >= 2.0 | レスポンススキーマ定義・検証 |

### 2.3 標準ライブラリ依存

| モジュール | 用途 |
|-----------|------|
| `asyncio` | 非同期処理、Semaphore、`to_thread()` |
| `json` | JSON解析・検証 |
| `logging` | ログ出力 |
| `typing` | 型ヒント（`Type`, `Optional`） |

### 2.4 内部依存モジュール

（このモジュールは外部依存のみで、内部モジュールへの依存はありません）

---

## 3. クラス・関数一覧表

### 3.1 クラス一覧

#### AsyncAPIClient

| メソッド | 概要 |
|---------|------|
| `__init__(api_key, max_workers, max_retries, max_output_tokens)` | コンストラクタ（APIキー不要、ダミー`"ollama"`） |
| `generate_content(model, contents, response_schema, task_id, system)` | セマフォ制御でAPI呼び出し |
| `_execute_with_retry(model, contents, response_schema, task_id, system)` | リトライロジック実行 |
| `_is_truncated(finish_reason)` | レスポンス切断チェック（`finish_reason == "length"`） |
| `get_stats()` | 統計情報を取得 |
| `reset_stats()` | 統計情報をリセット |

> モジュール関数 `_resolve_schema_refs(schema)` は、Pydanticが生成するJSON Schemaの `$ref`/`$defs` を展開してフラットなスキーマに変換します（`llama3.2` などの小型モデルは複雑なスキーマを解釈できないため）。

---

## 4. クラス・関数 IPO詳細

### 4.1 AsyncAPIClient クラス

Ollama API（OpenAI互換）への非同期アクセスを提供するクライアント。Semaphoreによる並列数制御と指数バックオフによるリトライ機能を備える。

#### コンストラクタ: `__init__`

**概要**: AsyncAPIClientインスタンスを初期化する。`OpenAI`（Ollama互換）クライアント、Semaphore、統計カウンタを設定。ローカル実行のためAPIキーは不要。

```python
AsyncAPIClient(
    api_key: str = "ollama",
    max_workers: int = 8,
    max_retries: int = 3,
    max_output_tokens: int = 8192
)
```

| パラメータ | 型 | デフォルト | 説明 |
|------------|------|-----------|------|
| `api_key` | str | `"ollama"` | 未使用（後方互換のために残すダミー値） |
| `max_workers` | int | 8 | 並列実行数（Semaphore制御） |
| `max_retries` | int | 3 | 最大リトライ回数 |
| `max_output_tokens` | int | 8192 | 出力トークン制限（`max_tokens`） |

| 項目 | 内容 |
|------|------|
| **Input** | `api_key: str = "ollama"`, `max_workers: int = 8`, `max_retries: int = 3`, `max_output_tokens: int = 8192` |
| **Process** | 1. `OpenAI`（Ollama互換）クライアントを初期化（`base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")`, `api_key="ollama"`）<br>2. `asyncio.Semaphore`を作成<br>3. 統計カウンタを初期化（`_total_requests`, `_failed_requests`, `_truncated_responses`） |
| **Output** | `AsyncAPIClient`インスタンス |

**インスタンス属性**:

| 属性 | 型 | 説明 |
|------|-----|------|
| `client` | `OpenAI` | Ollama（OpenAI互換）APIクライアント |
| `max_workers` | `int` | 並列数 |
| `semaphore` | `asyncio.Semaphore` | 並列制御用セマフォ |
| `max_retries` | `int` | 最大リトライ回数 |
| `max_output_tokens` | `int` | 出力トークン制限 |
| `_total_requests` | `int` | 総リクエスト数 |
| `_failed_requests` | `int` | 失敗リクエスト数 |
| `_truncated_responses` | `int` | 切断レスポンス数 |

```python
# 使用例（APIキー不要・ローカル実行）
from chunking import AsyncAPIClient

client = AsyncAPIClient(
    max_workers=8,
    max_retries=3,
    max_output_tokens=8192
)
# 任意で接続先を変更したい場合は環境変数 OLLAMA_BASE_URL を設定
#   export OLLAMA_BASE_URL=http://localhost:11434/v1
```

---

#### メソッド: `generate_content`

**概要**: セマフォで並列数を制御しながらOllama API呼び出しを行う。失敗時は指数バックオフでリトライ。

```python
async def generate_content(
    self,
    model: str,
    contents: str,
    response_schema: Type[BaseModel],
    task_id: Optional[str] = None,
    system: Optional[str] = None
) -> Optional[str]
```

| パラメータ | 型 | デフォルト | 説明 |
|------------|------|-----------|------|
| `model` | str | - | Ollamaモデル名（例: `gemma4:e4b`、代替 `llama3.2`） |
| `contents` | str | - | 入力テキスト（可変部分） |
| `response_schema` | Type[BaseModel] | - | レスポンスのPydanticスキーマ |
| `task_id` | Optional[str] | None | タスク識別子（ログ用） |
| `system` | Optional[str] | None | 固定のタスク指示文。JSONスキーマ指示の前段に統合される |

| 項目 | 内容 |
|------|------|
| **Input** | `model: str`, `contents: str`, `response_schema: Type[BaseModel]`, `task_id: Optional[str] = None`, `system: Optional[str] = None` |
| **Process** | 1. `async with self.semaphore`で並列数制御<br>2. `_execute_with_retry()`を呼び出し |
| **Output** | `Optional[str]`: レスポンスJSONテキスト、失敗時は`None` |

**戻り値例**:

```python
# 成功時
'{"sentences": [{"id": 1, "text": "文章1"}, {"id": 2, "text": "文章2"}]}'

# 失敗時
None
```

```python
# 使用例
import asyncio
from pydantic import BaseModel
from typing import List

class SentenceResult(BaseModel):
    sentences: List[dict]

async def main():
    client = AsyncAPIClient()  # APIキー不要（ローカル実行）

    result = await client.generate_content(
        model="gemma4:e4b",
        contents="以下のテキストを分析してください: ...",
        response_schema=SentenceResult,
        task_id="task_001"
    )

    if result:
        print(f"成功: {result}")
    else:
        print("失敗: Noneが返されました")

asyncio.run(main())
```

---

#### メソッド: `_execute_with_retry`

**概要**: リトライロジックを実行する。Ollama JSON mode による構造化出力を行い、切断レスポンス検出時は指数バックオフでリトライ。レート制限/クォータエラー時は長めの待機。

```python
async def _execute_with_retry(
    self,
    model: str,
    contents: str,
    response_schema: Type[BaseModel],
    task_id: Optional[str],
    system: Optional[str] = None
) -> Optional[str]
```

| パラメータ | 型 | デフォルト | 説明 |
|------------|------|-----------|------|
| `model` | str | - | Ollamaモデル名 |
| `contents` | str | - | 入力テキスト |
| `response_schema` | Type[BaseModel] | - | レスポンススキーマ |
| `task_id` | Optional[str] | - | タスク識別子 |
| `system` | Optional[str] | None | 固定のタスク指示文 |

| 項目 | 内容 |
|------|------|
| **Input** | `model: str`, `contents: str`, `response_schema: Type[BaseModel]`, `task_id: Optional[str]`, `system: Optional[str] = None` |
| **Process** | 1. `max_retries`回ループ<br>2. `response_schema.model_json_schema()`を取得し`_resolve_schema_refs()`で`$ref`/`$defs`をフラット化<br>3. スキーマ指示文（＋`system`）を組み立て、システムプロンプトに埋め込み<br>4. `asyncio.to_thread()`で`client.chat.completions.create()`を呼び出し（`response_format={"type": "json_object"}`, `max_tokens=max_output_tokens`）<br>5. `_is_truncated()`で切断チェック（`finish_reason == "length"`）<br>6. `response_schema.model_validate_json()`でスキーマ検証・パース<br>7. 失敗時は指数バックオフ（`2^attempt`秒）で待機<br>8. レート制限/クォータ時は`30*(attempt+1)`秒待機 |
| **Output** | `Optional[str]`: 成功時はJSONテキスト、全リトライ失敗時は`None` |

**リトライ待機時間**:

| 状況 | 待機時間 |
|------|---------|
| 通常エラー/切断/検証失敗 | 2^attempt 秒（1, 2, 4秒） |
| レート制限/クォータ | 30*(attempt+1) 秒（30, 60, 90秒） |

> 📝 **注意**: このメソッドはプライベートです。直接呼び出さず、`generate_content()`を使用してください。

**構造化出力の仕組み**: Ollama の JSON mode（`response_format={"type": "json_object"}`）を利用し、Pydanticから生成したJSONスキーマを `_resolve_schema_refs()` でフラット化したうえでシステムプロンプトに埋め込みます。`llama3.2` などの小型モデルは `$ref` を含む複雑なスキーマを解釈できないため、このフラット化が必要です。出力テキストは `response_schema.model_validate_json()` で検証・パースします。

---

#### メソッド: `_is_truncated`

**概要**: Ollama（OpenAI互換）レスポンスが `max_tokens` で切断されたかチェックする。`finish_reason`を検査。

```python
def _is_truncated(self, finish_reason: Optional[str]) -> bool
```

| パラメータ | 型 | デフォルト | 説明 |
|------------|------|-----------|------|
| `finish_reason` | Optional[str] | - | ChatCompletion レスポンスの `choices[0].finish_reason` |

| 項目 | 内容 |
|------|------|
| **Input** | `finish_reason: Optional[str]` |
| **Process** | `finish_reason == "length"` かどうかを判定 |
| **Output** | `bool`: 切断（`"length"`）なら`True`、それ以外は`False` |

**finish_reason判定**:

| finish_reason | 判定 |
|---------------|------|
| `"stop"` | 正常（`False`） |
| `None` | 正常（`False`） |
| `"length"` | 切断（`True`） |

---

#### メソッド: `get_stats`

**概要**: API呼び出しの統計情報を取得する。

```python
def get_stats(self) -> dict
```

| 項目 | 内容 |
|------|------|
| **Input** | なし（selfのみ） |
| **Process** | 内部カウンタから統計情報を集計 |
| **Output** | `dict`: 統計情報の辞書 |

**戻り値例**:

```python
{
    "total_requests": 100,
    "failed_requests": 2,
    "truncated_responses": 5,
    "success_rate": 98.0,
    "concurrency": 8
}
```

| キー | 型 | 説明 |
|-----|-----|------|
| `total_requests` | int | 総リクエスト数 |
| `failed_requests` | int | 全リトライ失敗したリクエスト数 |
| `truncated_responses` | int | 切断（`finish_reason == "length"`）が検出された回数 |
| `success_rate` | float | 成功率（%） |
| `concurrency` | int | 設定された並列数 |

```python
# 使用例
stats = client.get_stats()
print(f"成功率: {stats['success_rate']:.1f}%")
print(f"失敗: {stats['failed_requests']}/{stats['total_requests']}")
```

---

#### メソッド: `reset_stats`

**概要**: 統計情報をリセットする。

```python
def reset_stats(self) -> None
```

| 項目 | 内容 |
|------|------|
| **Input** | なし（selfのみ） |
| **Process** | `_total_requests`, `_failed_requests`, `_truncated_responses`を0にリセット |
| **Output** | `None` |

```python
# 使用例
client.reset_stats()
# バッチ処理開始
for batch in batches:
    await process_batch(batch, client)
# バッチ終了後に統計確認
print(client.get_stats())
```

---

## 5. 設定・定数

### 5.1 デフォルト設定値

| 設定 | デフォルト値 | 説明 |
|-----|-------------|------|
| `max_workers` | 8 | 並列実行数 |
| `max_retries` | 3 | 最大リトライ回数 |
| `max_output_tokens` | 8192 | 出力トークン制限 |

### 5.2 リトライ設定

| 設定 | 値 | 説明 |
|-----|-----|------|
| 通常エラー待機 | 2^attempt 秒 | 指数バックオフ（1, 2, 4秒） |
| レート制限待機 | 30*(attempt+1) 秒 | 長めの待機（30, 60, 90秒） |

### 5.3 レート制限判定キーワード

```python
# エラー文字列に以下が含まれる場合、レート制限/クォータと判定
["429", "rate", "quota", "insufficient_quota"]
```

### 5.4 接続設定

| 設定 | 値 | 説明 |
|-----|-----|------|
| `base_url` | `os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")` | Ollama の OpenAI 互換エンドポイント |
| `api_key` | `"ollama"` | ダミー値（ローカル実行のため未使用） |

---

## 6. 使用例

### 6.1 基本的なワークフロー

```python
import asyncio
from pydantic import BaseModel
from typing import List
from chunking import AsyncAPIClient

# レスポンススキーマ定義
class AnalysisResult(BaseModel):
    sentences: List[dict]
    summary: str

async def main():
    # 1. クライアント初期化（APIキー不要・ローカル実行）
    client = AsyncAPIClient(
        max_workers=8,
        max_retries=3
    )

    # 2. API呼び出し
    result = await client.generate_content(
        model="gemma4:e4b",
        contents="以下のテキストを分析してください: 今日は良い天気です。",
        response_schema=AnalysisResult,
        task_id="analysis_001"
    )

    # 3. 結果処理
    if result:
        import json
        data = json.loads(result)
        print(f"分析結果: {data}")
    else:
        print("分析に失敗しました")

    # 4. 統計確認
    stats = client.get_stats()
    print(f"成功率: {stats['success_rate']:.1f}%")

asyncio.run(main())
```

### 6.2 並列バッチ処理

```python
import asyncio
from chunking import AsyncAPIClient

async def process_batch(texts: list, client: AsyncAPIClient):
    """複数テキストを並列処理"""
    tasks = [
        client.generate_content(
            model="gemma4:e4b",
            contents=text,
            response_schema=MySchema,
            task_id=f"batch_{i}"
        )
        for i, text in enumerate(texts)
    ]

    # 並列実行（Semaphoreで8並列に制限）
    results = await asyncio.gather(*tasks)
    return results

async def main():
    client = AsyncAPIClient(max_workers=8)  # APIキー不要

    texts = ["テキスト1", "テキスト2", "テキスト3", ...]

    # バッチサイズごとに処理
    batch_size = 50
    all_results = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        results = await process_batch(batch, client)
        all_results.extend(results)

        # 進捗表示
        stats = client.get_stats()
        print(f"進捗: {i+len(batch)}/{len(texts)}, 成功率: {stats['success_rate']:.1f}%")

    # 最終統計
    final_stats = client.get_stats()
    print(f"完了: {final_stats}")

asyncio.run(main())
```

### 6.3 エラーハンドリング付きワークフロー

```python
import asyncio
import logging
from chunking import AsyncAPIClient

logging.basicConfig(level=logging.INFO)

async def safe_process(client: AsyncAPIClient, text: str, task_id: str):
    """エラーハンドリング付き処理"""
    try:
        result = await client.generate_content(
            model="gemma4:e4b",
            contents=text,
            response_schema=MySchema,
            task_id=task_id
        )

        if result is None:
            logging.warning(f"[{task_id}] API呼び出し失敗（全リトライ失敗）")
            return {"status": "failed", "task_id": task_id}

        return {"status": "success", "task_id": task_id, "data": result}

    except Exception as e:
        logging.error(f"[{task_id}] 予期せぬエラー: {e}")
        return {"status": "error", "task_id": task_id, "error": str(e)}

async def main():
    client = AsyncAPIClient()  # APIキー不要

    results = await asyncio.gather(*[
        safe_process(client, text, f"task_{i}")
        for i, text in enumerate(texts)
    ])

    # 結果集計
    success = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")
    errors = sum(1 for r in results if r["status"] == "error")

    print(f"成功: {success}, 失敗: {failed}, エラー: {errors}")

asyncio.run(main())
```

---

## 7. エクスポート

`chunking/__init__.py`でエクスポートされる要素：

```python
__all__ = [
    # API Client
    "AsyncAPIClient",
]
```

---

## 8. 変更履歴

| バージョン | 日付 | 変更内容 |
|-----------|------|---------|
| 1.1 | 2026-06-21 | Ollama ネイティブ化：実装（openai SDK + JSON mode）に整合 |
| 1.0 | 2025-01-29 | 初版作成 |

---

## 付録: 依存関係図

```mermaid
flowchart LR
    ASYNC[async_api_client.py]

    subgraph GOOGLE["openai (Ollama互換)"]
        GENAI["OpenAI"]
    end

    subgraph PYDANTIC["pydantic"]
        BASEMODEL[BaseModel]
    end

    subgraph STDLIB["標準ライブラリ"]
        ASYNCIO[asyncio]
        JSON[json]
        LOGGING[logging]
        OS[os]
        TYPING[typing]
    end

    ASYNC --> GENAI
    ASYNC --> BASEMODEL
    ASYNC --> ASYNCIO
    ASYNC --> JSON
    ASYNC --> LOGGING
    ASYNC --> OS
    ASYNC --> TYPING

    GENAI --> GEN_CONTENT["chat.completions.create()"]
    ASYNCIO --> SEMAPHORE["Semaphore"]
    ASYNCIO --> TO_THREAD["to_thread()"]
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class ASYNC,GENAI,BASEMODEL,ASYNCIO,JSON,LOGGING,OS,TYPING,GEN_CONTENT,SEMAPHORE,TO_THREAD default
style GOOGLE fill:#1a1a1a,stroke:#fff,color:#fff
style PYDANTIC fill:#1a1a1a,stroke:#fff,color:#fff
style STDLIB fill:#1a1a1a,stroke:#fff,color:#fff
```

---

## 付録: 処理フロー図

### API呼び出しフロー

```mermaid
flowchart TB
    START(["generate_content() 呼び出し"]) --> SEM{"Semaphore<br/>取得可能?"}
    SEM -->|待機| SEM
    SEM -->|取得| RETRY["_execute_with_retry()"]

    subgraph RETRY_LOOP["リトライループ (max 3回)"]
        API["asyncio.to_thread()<br/>Ollama API呼び出し (JSON mode)"]
        API --> TRUNC{"切断<br/>チェック"}
        TRUNC -->|切断| WAIT["待機 (2^attempt秒)"]
        TRUNC -->|OK| JSON_CHECK{"スキーマ<br/>検証"}
        JSON_CHECK -->|失敗| WAIT
        JSON_CHECK -->|OK| SUCCESS(["成功: JSONテキスト返却"])
        WAIT --> NEXT{"次の<br/>リトライ?"}
        NEXT -->|Yes| API
        NEXT -->|No| FAIL(["失敗: None返却"])
    end

    RETRY --> RETRY_LOOP
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class START,SEM,RETRY,API,TRUNC,WAIT,JSON_CHECK,SUCCESS,NEXT,FAIL default
style RETRY_LOOP fill:#1a1a1a,stroke:#fff,color:#fff
```

### レート制限対応フロー

```mermaid
flowchart TB
    ERROR["例外発生"] --> CHECK{"エラー種別"}
    CHECK -->|"429/rate/quota"| RATE["レート制限"]
    CHECK -->|その他| NORMAL["通常エラー"]

    RATE --> WAIT_LONG["待機: 30*(attempt+1)秒<br/>(30, 60, 90秒)"]
    NORMAL --> WAIT_SHORT["待機: 2^attempt秒<br/>(1, 2, 4秒)"]

    WAIT_LONG --> RETRY["リトライ"]
    WAIT_SHORT --> RETRY
classDef default fill:#000,stroke:#fff,color:#fff
classDef subgraphStyle fill:#1a1a1a,stroke:#fff,color:#fff
class ERROR,CHECK,RATE,NORMAL,WAIT_LONG,WAIT_SHORT,RETRY default
```
