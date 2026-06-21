"""
GRACE LLM 互換クライアント（ollama_grace_agent_v2）

GRACE 本体（planner / executor / confidence / tools）は、もともと
google-genai の `client.models.generate_content(...)` 形式で実装されている。
本プロジェクトは **Ollama（ローカル LLM）** を LLM プロバイダーとするため、
同一の呼び出しインターフェースを保ったまま Ollama を呼び出すアダプターを提供する。

これにより、各呼び出しサイトのコードは

    response = client.models.generate_content(
        model=...,
        contents="...",
        config={"temperature": ..., "max_output_tokens": ...},
    )
    text = response.text

をそのまま維持できる（client の生成だけ `create_chat_client(config)` に置き換える）。

実装方針:
    - `OllamaGenaiClient` が `helper.helper_llm.OllamaClient` をラップし、
      genai 互換の `client.models.generate_content(...)` を提供する。
    - 既定モデルは `DEFAULT_OLLAMA_MODEL`（gemma4:e4b）。API キー不要（ローカル実行）。
    - 既定 provider は "ollama"。`gemini` 等を明示指定した場合のみ google-genai を使用する
      （embedding 検証などの限定用途）。

Embedding（`client.models.embed_content`）は Ollama Embedding（nomic-embed-text/768）を
継続利用するため、本アダプターは LLM テキスト生成（generate_content）のみを対象とする。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Gemini をそのまま使う場合のプロバイダー名（embedding 検証等の限定用途）
_GEMINI_PROVIDERS = {"gemini", "google", "google-genai", "genai"}

# Ollama デフォルトモデル（config 未指定時のフォールバック）
DEFAULT_OLLAMA_MODEL = "gemma4:e4b"


class _UsageMetadata:
    """genai の usage_metadata 互換オブジェクト。"""

    def __init__(self, prompt_token_count: int = 0, candidates_token_count: int = 0):
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class _GenaiCompatResponse:
    """genai の generate_content レスポンス互換オブジェクト。

    呼び出しサイトが参照する属性のみを提供する:
        - .text          : 生成テキスト
        - .parsed         : 構造化出力（Ollama では None。呼び出し側が手動 JSON パースする）
        - .usage_metadata : トークン使用量（Ollama はローカル実行のためコスト計算なし）
    """

    def __init__(self, text: str, usage: Optional[_UsageMetadata] = None):
        self.text = text
        self.parsed = None
        self.usage_metadata = usage or _UsageMetadata()


def _extract_config(config: Any) -> dict[str, Any]:
    """生成設定から必要なキーを取り出す。

    LLM テキスト生成は Ollama 専用へ移行したため、呼び出し側は
    google-genai の `types.GenerateContentConfig` ではなく **plain dict** で
    設定を渡す。後方互換のため属性アクセス（旧 GenerateContentConfig 等）にも対応する。
    """
    if config is None:
        return {}
    out: dict[str, Any] = {}
    for key in ("temperature", "max_output_tokens", "response_mime_type", "response_schema"):
        if isinstance(config, dict):
            out[key] = config.get(key)
        else:
            out[key] = getattr(config, key, None)
    return out


def _schema_hint(response_schema: Any) -> str:
    """response_schema から JSON スキーマのヒント文字列を生成する。"""
    if response_schema is None:
        return ""
    # Pydantic モデルクラスの場合は JSON Schema を埋め込む
    model_json_schema = getattr(response_schema, "model_json_schema", None)
    if callable(model_json_schema):
        try:
            return json.dumps(model_json_schema(), ensure_ascii=False)
        except Exception:  # pragma: no cover - スキーマ生成失敗は無視
            return ""
    return ""


def _strip_to_json(text: str) -> str:
    """Markdown フェンスや前後の散文を除去し、JSON 本体（{...} or [...]）を抽出する。"""
    s = text.strip()
    if s.startswith("```"):
        # ```json ... ``` / ``` ... ``` を剥がす
        body = s.split("\n", 1)
        if len(body) == 2:
            s = body[1]
        s = s.rsplit("```", 1)[0].strip()
    # オブジェクト/配列のいずれか先に出現する方を抽出
    candidates = [i for i in (s.find("{"), s.find("[")) if i >= 0]
    if not candidates:
        return s
    start = min(candidates)
    end = max(s.rfind("}"), s.rfind("]")) + 1
    if end > start:
        return s[start:end]
    return s


class _OllamaModels:
    """genai の `client.models` 互換ラッパー（generate_content のみ）。"""

    def __init__(self, client_getter: Any, default_model: str):
        # client_getter は呼び出し時に Ollama クライアント（helper_llm.OllamaClient）を
        # 遅延生成する callable。（genai.Client() と同様、構築時には SDK / 接続を要求しない）
        self._get_client = client_getter
        self._default_model = default_model

    def generate_content(
        self,
        model: Optional[str] = None,
        contents: Any = None,
        config: Any = None,
        **_kwargs: Any,
    ) -> _GenaiCompatResponse:
        cfg = _extract_config(config)
        model_name = model or self._default_model

        # contents は GRACE 本体では常に str。念のため文字列化する。
        prompt = contents if isinstance(contents, str) else str(contents)

        # JSON 出力が要求されている場合（mime or schema）はシステム指示を付与
        want_json = bool(cfg.get("response_mime_type") == "application/json"
                         or cfg.get("response_schema") is not None)

        system_parts: list[str] = []
        if want_json:
            system_parts.append(
                "あなたは厳密な JSON ジェネレーターです。"
                "出力は有効な JSON オブジェクト 1 個のみとし、"
                "Markdown のコードブロックや説明文を一切含めないでください。"
            )
            hint = _schema_hint(cfg.get("response_schema"))
            if hint:
                system_parts.append(f"出力は次の JSON Schema に厳密に従ってください:\n{hint}")
        system_prompt = "\n\n".join(system_parts) if system_parts else None

        # genai の max_output_tokens を OllamaClient の max_tokens に流用し、
        # 未指定時は十分な既定値を確保する。
        max_tokens = cfg.get("max_output_tokens") or 4096
        temperature = cfg.get("temperature")

        kwargs: dict[str, Any] = {
            "model": model_name,
            "max_tokens": int(max_tokens),
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if temperature is not None:
            kwargs["temperature"] = float(temperature)
        # JSON モード時は Ollama の OpenAI 互換 response_format を有効化
        if want_json:
            kwargs["response_format"] = {"type": "json_object"}

        # OllamaClient.generate_content(prompt, model=..., **kwargs) は str を返す
        text = self._get_client().generate_content(prompt, **kwargs) or ""

        # JSON モード時は呼び出し側が response.text を直接 model_validate_json /
        # json.loads するため、Markdown コードフェンスや前後の散文を除去して
        # 純粋な JSON 本体のみを返す。
        if want_json and text:
            text = _strip_to_json(text)

        # ローカル実行のため厳密なトークン使用量は取得しない（count_tokens で近似可能）。
        return _GenaiCompatResponse(text=text, usage=_UsageMetadata())


class OllamaGenaiClient:
    """genai.Client 互換の Ollama クライアント。

    `.models.generate_content(...)` のみをサポートする。
    内部で helper.helper_llm.OllamaClient を遅延生成して使用する。
    """

    def __init__(self, default_model: str, base_url: Optional[str] = None):
        self._default_model = default_model
        self._base_url = base_url
        self._client: Any = None
        # genai.Client() と同様、構築時には接続を行わず、
        # 最初の generate_content 呼び出し時に遅延生成する（import 安全性のため）。
        self.models = _OllamaModels(self._ensure_client, default_model)

    def _ensure_client(self) -> Any:
        if self._client is None:
            try:
                from helper.helper_llm import create_llm_client
            except ImportError:  # pragma: no cover - フラット配置フォールバック
                from helper_llm import create_llm_client  # type: ignore[no-redef]
            # base_url は環境変数（OLLAMA_BASE_URL）で解決されるため通常は未指定で良い
            self._client = create_llm_client("ollama", default_model=self._default_model)
        return self._client


def create_chat_client(config: Any = None) -> Any:
    """GRACE 本体のテキスト生成用クライアントを生成する。

    config.llm.provider に応じて以下を返す:
        - "gemini"/"google" → google-genai の genai.Client()
        - "ollama"（既定）   → OllamaGenaiClient（genai 互換）

    いずれの戻り値も `client.models.generate_content(...)` を提供する。
    """
    provider = "ollama"
    model = DEFAULT_OLLAMA_MODEL
    llm = getattr(config, "llm", None) if config is not None else None
    if llm is not None:
        provider = (getattr(llm, "provider", None) or provider).lower()
        model = getattr(llm, "model", None) or model

    if provider in _GEMINI_PROVIDERS:
        from google import genai
        return genai.Client()

    return OllamaGenaiClient(default_model=model)
