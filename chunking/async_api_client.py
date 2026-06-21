# async_api_client.py
"""
非同期APIクライアント（Ollama ネイティブ）
- asyncio.to_thread() で同期APIをラップ
- Semaphore で並列数制御（固定）
- リトライロジック（3回、指数バックオフ）
- 構造化出力は JSON mode + スキーマをシステムプロンプトに埋め込み + model_validate_json() で実現

Ollama は OpenAI 互換エンドポイント（/v1）を公開しているため、`openai` SDK を
Ollama サーバ（既定 http://localhost:11434/v1）に向けて利用する。ローカル実行のため
API キーは不要（ダミー値 "ollama" を渡す）。

実装方針:
  - クライアント: OpenAI(base_url="http://localhost:11434/v1", api_key="ollama")
  - 構造化出力: client.chat.completions.create() + JSON mode
    （response_format={"type": "json_object"} + スキーマをシステムプロンプトに埋め込み）
  - パース: model_validate_json(choice.message.content)
  - 出力トークン上限: max_tokens
"""

import asyncio
import json
import logging
import os
from typing import Optional, Type

from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _resolve_schema_refs(schema: dict) -> dict:
    """
    JSON Schema の $ref / $defs を解決してフラットな構造に変換する。
    llama3.2 などの小型モデルは $ref を含む複雑なスキーマを解釈できないため、
    $ref を実際の定義に展開したシンプルなスキーマを生成する。
    """
    defs = schema.get("$defs", {})

    def resolve(obj, depth=0):
        if depth > 10:
            return obj
        if isinstance(obj, dict):
            if "$ref" in obj:
                ref_name = obj["$ref"].split("/")[-1]
                return resolve(defs.get(ref_name, obj), depth + 1)
            return {k: resolve(v, depth + 1) for k, v in obj.items() if k not in ("$defs", "title")}
        if isinstance(obj, list):
            return [resolve(item, depth + 1) for item in obj]
        return obj

    return resolve(schema)


class AsyncAPIClient:
    """
    非同期APIクライアント（Ollama ネイティブ）
    - asyncio.to_thread() で同期APIをラップ
    - Semaphore で並列数制御（固定）
    - リトライロジック（3回、指数バックオフ）
    - 構造化出力: Ollama JSON mode（response_format={"type": "json_object"} + スキーマ埋め込み）
    """

    def __init__(
        self,
        api_key: str = "ollama",
        max_workers: int = 8,
        max_retries: int = 3,
        max_output_tokens: int = 8192
    ):
        """
        Args:
            api_key: 未使用（後方互換のために残す）
            max_workers: 並列数（デフォルト: 8）
            max_retries: リトライ回数（デフォルト: 3）
            max_output_tokens: 出力トークン制限（デフォルト: 8192）
        """
        # Ollama の OpenAI 互換エンドポイントに接続（ローカル実行のため API キー不要）
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.client = OpenAI(base_url=base_url, api_key="ollama")
        self.max_workers = max_workers
        self.semaphore = asyncio.Semaphore(max_workers)
        self.max_retries = max_retries
        self.max_output_tokens = max_output_tokens
        self._total_requests = 0
        self._failed_requests = 0
        self._truncated_responses = 0

    def _is_truncated(self, finish_reason: Optional[str]) -> bool:
        """レスポンスが max_tokens で切断されたか判定"""
        return finish_reason == "length"

    async def generate_content(
        self,
        model: str,
        contents: str,
        response_schema: Type[BaseModel],
        task_id: Optional[str] = None,
        system: Optional[str] = None
    ) -> Optional[str]:
        """
        セマフォで並列数を制御しながらAPI呼び出し
        失敗時は指数バックオフでリトライ

        Args:
            model: Ollama モデル名（例: llama3.2）
            contents: 入力テキスト（可変部分）
            response_schema: レスポンスのPydanticスキーマ
            task_id: タスク識別子（ログ用）
            system: 固定のタスク指示文（任意）。JSONスキーマ指示の前段に統合する。

        Returns:
            JSON文字列（Pydanticモデルとして解析可能）、失敗時はNone
        """
        async with self.semaphore:
            return await self._execute_with_retry(
                model, contents, response_schema, task_id, system
            )

    async def _execute_with_retry(
        self,
        model: str,
        contents: str,
        response_schema: Type[BaseModel],
        task_id: Optional[str],
        system: Optional[str] = None
    ) -> Optional[str]:
        """リトライロジック（Ollama JSON mode による構造化出力）"""

        for attempt in range(self.max_retries):
            try:
                self._total_requests += 1

                # Ollama JSON mode による構造化出力（chat.completions.create + json_object）
                # $ref/$defs を解決したフラットなスキーマを使用（llama3.2 は複雑なスキーマを解釈できない）
                raw_schema = response_schema.model_json_schema()
                flat_schema = _resolve_schema_refs(raw_schema)
                schema_str = json.dumps(flat_schema, ensure_ascii=False, indent=2)
                schema_instruction = (
                    "あなたはJSONを出力するアシスタントです。\n"
                    "以下のJSONスキーマに完全に従い、スキーマ定義自体ではなく実際のデータをJSONで出力してください。\n"
                    "余分なテキスト・説明・マークダウンは一切出力しないでください。JSONのみを出力してください。\n\n"
                    f"スキーマ:\n{schema_str}"
                )
                # [chunking refactor] タスク指示（system）をスキーマ指示の前段に統合
                system_prompt = (
                    f"{system}\n\n{schema_instruction}" if system else schema_instruction
                )
                response = await asyncio.to_thread(
                    self.client.chat.completions.create,
                    model=model,
                    max_tokens=self.max_output_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": contents}
                    ],
                    response_format={"type": "json_object"},
                )

                choice = response.choices[0]
                finish_reason = choice.finish_reason

                # max_tokens超過チェック
                if self._is_truncated(finish_reason):
                    self._truncated_responses += 1
                    raise ValueError(
                        f"Response truncated (finish_reason: {finish_reason}). "
                        f"Increase max_output_tokens or reduce block_size."
                    )

                # JSON mode の出力テキストを Pydantic スキーマで検証・パース
                result_text = choice.message.content
                if result_text is None:
                    raise ValueError(
                        f"Response content is None (finish_reason: {finish_reason})."
                    )

                parsed = response_schema.model_validate_json(result_text)
                result_json = json.dumps(parsed.model_dump(), ensure_ascii=False)
                return result_json

            except ValueError as e:
                wait_time = 2 ** attempt
                logger.warning(
                    f"[{task_id}] {e}. "
                    f"Retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})"
                )
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(wait_time)

            except Exception as e:
                error_str = str(e).lower()

                if "429" in error_str or "rate" in error_str or "quota" in error_str or "insufficient_quota" in error_str:
                    wait_time = 30 * (attempt + 1)
                    logger.warning(
                        f"[{task_id}] Rate limit / quota hit. "
                        f"Waiting {wait_time}s (attempt {attempt + 1}/{self.max_retries})"
                    )
                else:
                    wait_time = 2 ** attempt
                    logger.warning(
                        f"[{task_id}] Error: {e}. "
                        f"Retrying in {wait_time}s (attempt {attempt + 1}/{self.max_retries})"
                    )

                if attempt < self.max_retries - 1:
                    await asyncio.sleep(wait_time)

        self._failed_requests += 1
        logger.error(f"[{task_id}] Failed after {self.max_retries} retries. Using fallback.")
        return None

    def get_stats(self) -> dict:
        """統計情報を取得"""
        return {
            "total_requests"     : self._total_requests,
            "failed_requests"    : self._failed_requests,
            "truncated_responses": self._truncated_responses,
            "success_rate"       : (
                (self._total_requests - self._failed_requests) / self._total_requests * 100
                if self._total_requests > 0 else 0
            ),
            "concurrency"        : self.max_workers
        }

    def reset_stats(self):
        """統計情報をリセット"""
        self._total_requests = 0
        self._failed_requests = 0
        self._truncated_responses = 0
