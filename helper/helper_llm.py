"""
Ollama 既定のマルチプロバイダー LLM クライアント抽象化レイヤー

Ollama をデフォルトとし、OpenAI API / Gemini API / Anthropic API も
切り替えて利用できる統一インターフェースを提供する。
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Type

from dotenv import load_dotenv
from pydantic import BaseModel

# ================================================================
# SDK imports
# ================================================================

# OpenAI (Ollama も OpenAI SDK 経由で使用)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Gemini (既存。gemini_grace_agent との並行運用のため維持)
try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None

# Anthropic (後方互換として維持)
try:
    import anthropic as anthropic_sdk
except ImportError:
    anthropic_sdk = None

import tiktoken

load_dotenv()

logger = logging.getLogger(__name__)


# ================================================================
# LLM モデル設定
# ================================================================

# --- Gemini モデル (既存) ---
LLM_MODELS_GEMINI = [
    "gemini-2.5-flash",
    "gemini-3-pro-preview",
    "gemini-2.5-flash-preview",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
]

# --- Anthropic モデル (後方互換として維持) ---
LLM_MODELS_ANTHROPIC = [
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-haiku-4-5-20251001",
]

# --- OpenAI モデル (後方互換として維持) ---
LLM_MODELS_OPENAI = [
    "gpt-4o",
    "gpt-4o-mini",
]

# --- Ollama モデル ---
LLM_MODELS_OLLAMA = [
    "llama3.2",
    "llama3.2:3b",
    "llama3.2:1b",
    "llama3.1",
    "llama3.1:8b",
    "llama3.1:70b",
    "qwen2.5:7b",
    "qwen2.5:14b",
    "mistral",
    "mistral-nemo",
    "phi3",
    "phi3:mini",
    "gemma2",
    "gemma2:9b",
]

# 全モデル一覧（後方互換性のため維持）
LLM_MODELS = LLM_MODELS_ANTHROPIC + LLM_MODELS_GEMINI + LLM_MODELS_OPENAI + LLM_MODELS_OLLAMA

# ----------------------------------------------------------------
# 料金設定（USD / 1K tokens）
# Ollama はローカル実行のため料金 0.0
# ----------------------------------------------------------------
LLM_PRICING = {
    # Ollama ローカルモデル (新規追加)
    "llama3.2"           : {"input": 0.0,    "output": 0.0   },
    "llama3.2:3b"        : {"input": 0.0,    "output": 0.0   },
    "llama3.2:1b"        : {"input": 0.0,    "output": 0.0   },
    "llama3.1"           : {"input": 0.0,    "output": 0.0   },
    "llama3.1:8b"        : {"input": 0.0,    "output": 0.0   },
    "llama3.1:70b"       : {"input": 0.0,    "output": 0.0   },
    "qwen2.5:7b"         : {"input": 0.0,    "output": 0.0   },
    "qwen2.5:14b"        : {"input": 0.0,    "output": 0.0   },
    "mistral"            : {"input": 0.0,    "output": 0.0   },
    "mistral-nemo"       : {"input": 0.0,    "output": 0.0   },
    "phi3"               : {"input": 0.0,    "output": 0.0   },
    "gemma2"             : {"input": 0.0,    "output": 0.0   },

    # Anthropic Claude 4.x (後方互換)
    "claude-opus-4-7"         : {"input": 0.005,   "output": 0.025  },
    "claude-opus-4-6"         : {"input": 0.015,   "output": 0.075  },
    "claude-sonnet-4-6"       : {"input": 0.003,   "output": 0.015  },
    "claude-sonnet-4-5"       : {"input": 0.003,   "output": 0.015  },
    "claude-haiku-4-5-20251001": {"input": 0.0008,  "output": 0.004  },

    # Ollama (ローカル実行のため無料)
    **{model: {"input": 0.0, "output": 0.0} for model in LLM_MODELS_OLLAMA},

    # Gemini (既存)
    "gemini-2.5-flash"        : {"input": 0.0001,  "output": 0.0004 },
    "gemini-3-pro-preview"    : {"input": 0.00125, "output": 0.010  },
    "gemini-2.5-flash-preview": {"input": 0.00015, "output": 0.0035 },
    "gemini-2.0-flash"        : {"input": 0.0001,  "output": 0.0004 },
    "gemini-1.5-pro"          : {"input": 0.00125, "output": 0.005  },
    "gemini-1.5-flash"        : {"input": 0.000075,"output": 0.0003 },
}

# ----------------------------------------------------------------
# コンテキスト上限設定（tokens）
# ----------------------------------------------------------------
LLM_LIMITS = {
    # Ollama ローカルモデル (新規追加)
    # ※ コンテキスト長はモデルと利用可能 VRAM に依存する
    "llama3.2"           : {"max_tokens": 128000, "max_output": 8192 },
    "llama3.2:3b"        : {"max_tokens": 128000, "max_output": 8192 },
    "llama3.2:1b"        : {"max_tokens": 128000, "max_output": 8192 },
    "llama3.1"           : {"max_tokens": 128000, "max_output": 8192 },
    "llama3.1:8b"        : {"max_tokens": 128000, "max_output": 8192 },
    "llama3.1:70b"       : {"max_tokens": 128000, "max_output": 8192 },
    "qwen2.5:7b"         : {"max_tokens": 128000, "max_output": 8192 },
    "qwen2.5:14b"        : {"max_tokens": 128000, "max_output": 8192 },
    "mistral"            : {"max_tokens": 32000,  "max_output": 8192 },
    "mistral-nemo"       : {"max_tokens": 128000, "max_output": 8192 },
    "phi3"               : {"max_tokens": 128000, "max_output": 4096 },
    "gemma2"             : {"max_tokens": 8192,   "max_output": 4096 },

    # Anthropic Claude 4.x (後方互換)
    "claude-opus-4-7"         : {"max_tokens": 200000,  "max_output": 32000},
    "claude-opus-4-6"         : {"max_tokens": 1000000, "max_output": 32000},
    "claude-sonnet-4-6"       : {"max_tokens": 1000000, "max_output": 64000},
    "claude-sonnet-4-5"       : {"max_tokens": 200000,  "max_output": 64000},
    "claude-haiku-4-5-20251001": {"max_tokens": 200000,  "max_output": 8192 },

    # Ollama (ローカル実行)
    **{model: {"max_tokens": 128000, "max_output": 8192} for model in LLM_MODELS_OLLAMA},

    # Gemini (既存)
    "gemini-2.5-flash"        : {"max_tokens": 1000000, "max_output": 8192 },
    "gemini-3-pro-preview"    : {"max_tokens": 1000000, "max_output": 64000},
    "gemini-2.5-flash-preview": {"max_tokens": 1000000, "max_output": 64000},
    "gemini-2.0-flash"        : {"max_tokens": 1000000, "max_output": 8192 },
    "gemini-1.5-pro"          : {"max_tokens": 1000000, "max_output": 8192 },
    "gemini-1.5-flash"        : {"max_tokens": 1000000, "max_output": 8192 },
}

# ================================================================
# Embedding モデル設定（既存のまま維持）
# ================================================================

EMBEDDING_MODELS = [
    "nomic-embed-text",     # Ollama デフォルト (768次元)
    "mxbai-embed-large",    # Ollama 大容量モデル (1024次元)
    "all-minilm",           # Ollama 軽量モデル (384次元)
    "gemini-embedding-001",
    "text-embedding-3-small",
    "text-embedding-3-large",
]

EMBEDDING_PRICING = {
    "nomic-embed-text"      : 0.0,       # Ollama ローカル
    "mxbai-embed-large"     : 0.0,       # Ollama ローカル
    "all-minilm"            : 0.0,       # Ollama ローカル
    "gemini-embedding-001"  : 0.0001,
    "text-embedding-3-small": 0.00002,
    "text-embedding-3-large": 0.00013,
}

EMBEDDING_DIMS = {
    "nomic-embed-text"      : 768,
    "mxbai-embed-large"     : 1024,
    "all-minilm"            : 384,
    "gemini-embedding-001"  : 3072,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}

# ================================================================
# デフォルトプロバイダー
# 環境変数 LLM_PROVIDER で切り替え可能
#   export LLM_PROVIDER=ollama   # ollama_grace_agent (デフォルト)
#   export LLM_PROVIDER=openai   # openai_grace_agent
#   export LLM_PROVIDER=gemini   # gemini_grace_agent
# ================================================================
# 環境変数 LLM_PROVIDER で切り替え可能（既定は ollama）
DEFAULT_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")


# ================================================================
# 抽象基底クラス
# ================================================================

class LLMClient(ABC):
    """LLM クライアント統一インターフェース"""

    @abstractmethod
    def generate_content(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        """テキスト生成"""
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        model: Optional[str] = None,
        **kwargs,
    ) -> BaseModel:
        """構造化出力（Pydantic モデル）を生成"""
        pass

    @abstractmethod
    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """トークン数をカウント"""
        pass


def _resolve_schema_refs(schema: dict) -> dict:
    """
    JSON Schema の $ref / $defs を解決してフラットな構造に変換する。
    Ollama ローカルモデル（llama3.2, gemma4:e4b 等）は $ref を含む複雑な
    スキーマを解釈できずスキーマ定義をそのまま返してしまうため、
    展開したシンプルなスキーマを使用する。全 Ollama モデルに適用する。
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


def _parse_text_tool_calls(text: str) -> list:
    """
    テキスト形式のツール呼び出しをパースする。
    gemma4:e4b 等は tool_calls を構造化レスポンスではなくテキストで返すため、
    msg.content からツール呼び出し情報を抽出して構造化形式に変換する。

    対応フォーマット:
      1. Gemma4 形式: Action:tool_name{key:<|"|>value<|"|>}
      2. JSON 辞書形式: {"name": "tool_name", "parameters": {"key": "value"}}
      3. 簡易 KV 形式: Action:tool_name Args: {"key": "value"}
    """
    import re
    import uuid

    result = []

    # --- フォーマット1: Gemma4 ネイティブ形式 ---
    # Action:tool_name{key:<|"|>value<|"|>, ...}
    gemma_block = re.findall(r'Action:(\w+)\{([^}]*)\}', text)
    for tool_name, args_str in gemma_block:
        args: dict = {}
        # <|"|>value<|"|> トークン形式
        for km in re.finditer(r'(\w+):<[|]"[|]>([^<]*)<[|]"[|]>', args_str):
            args[km.group(1)] = km.group(2).strip()
        # fallback: key:"value" 形式
        if not args:
            for km in re.finditer(r'(\w+):\s*"([^"]*)"', args_str):
                args[km.group(1)] = km.group(2)
        # fallback: key:value（クォートなし）
        if not args:
            for km in re.finditer(r'(\w+):\s*([^\s,}]+)', args_str):
                args[km.group(1)] = km.group(2).strip()
        if tool_name:
            result.append({
                "name" : tool_name,
                "input": args,
                "id"   : f"call_{uuid.uuid4().hex[:8]}",
            })
    if result:
        return result

    # --- フォーマット2: JSON 辞書形式 ---
    # {"name": "tool_name", "parameters": {...}} or {"tool": "...", "args": {...}}
    for m in re.finditer(r'\{[^{}]*"name"\s*:\s*"(\w+)"[^{}]*\}', text):
        try:
            obj = json.loads(m.group(0))
            tool_name = obj.get("name") or obj.get("tool")
            args = obj.get("parameters") or obj.get("args") or obj.get("arguments") or {}
            if tool_name and isinstance(args, dict):
                result.append({
                    "name" : tool_name,
                    "input": args,
                    "id"   : f"call_{uuid.uuid4().hex[:8]}",
                })
        except Exception:
            pass
    if result:
        return result

    # --- フォーマット3: Action:tool_name Args: {...} 形式 ---
    for m in re.finditer(r'Action:\s*(\w+)\s+Args:\s*(\{[^}]*\})', text, re.DOTALL):
        tool_name = m.group(1)
        try:
            args = json.loads(m.group(2))
        except Exception:
            args = {}
        result.append({
            "name" : tool_name,
            "input": args,
            "id"   : f"call_{uuid.uuid4().hex[:8]}",
        })

    return result



# ================================================================
# OpenAI クライアント（後方互換として維持）
# ================================================================

class OpenAIClient(LLMClient):
    def __init__(self, api_key: Optional[str] = None, default_model: str = "gpt-4o-mini"):
        if not OpenAI:
            raise ImportError("openai package is not installed.")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY is not set")
        self.client = OpenAI(api_key=self.api_key)
        self.default_model = default_model

    def generate_content(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        model = model or self.default_model
        system = kwargs.pop("system", None)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        if "max_tokens" in kwargs and "max_completion_tokens" not in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        response = self.client.chat.completions.create(model=model, messages=messages, **kwargs)
        return response.choices[0].message.content

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        model: Optional[str] = None,
        **kwargs,
    ) -> BaseModel:
        model = model or self.default_model
        system = kwargs.pop("system", None)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        if "max_tokens" in kwargs and "max_completion_tokens" not in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        response = self.client.beta.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=response_schema,
            **kwargs,
        )
        return response.choices[0].message.parsed

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        model = model or self.default_model
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))

    def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str = "",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> tuple:
        """
        Tool Use を含む ReAct ループの 1 ステップを実行する。
        """
        import json as _json

        model_name = model or self.default_model

        full_messages: List[Dict[str, Any]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        create_kwargs: Dict[str, Any] = {
            "model"   : model_name,
            "messages": full_messages,
        }

        if tools:
            openai_tools = [
                {
                    "type"    : "function",
                    "function": {
                        "name"       : t["name"],
                        "description": t.get("description", ""),
                        "parameters" : t.get("input_schema", t.get("parameters", {})),
                    }
                }
                for t in tools
            ]
            create_kwargs["tools"] = openai_tools

        if "temperature" in kwargs:
            create_kwargs["temperature"] = kwargs["temperature"]

        response = self.client.chat.completions.create(**create_kwargs)
        msg = response.choices[0].message

        tool_calls_result = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = _json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                tool_calls_result.append({
                    "name" : tc.function.name,
                    "input": args,
                    "id"   : tc.id,
                })

        text = msg.content or ""
        finish_reason = response.choices[0].finish_reason or "stop"

        return text, tool_calls_result, finish_reason

    def build_tool_result_message(
        self,
        tool_calls: List[Dict[str, Any]],
        results: List[str],
    ) -> List[Dict[str, Any]]:
        return [
            {
                "role"        : "tool",
                "tool_call_id": tc["id"],
                "content"     : result,
            }
            for tc, result in zip(tool_calls, results)
        ]


# ================================================================
# Gemini クライアント（後方互換として維持 / gemini_grace_agent との並行運用用）
# ================================================================

class GeminiClient(LLMClient):
    def __init__(self, api_key: Optional[str] = None, default_model: str = "gemini-2.0-flash"):
        if genai is None:
            raise ImportError(
                "google-genai package is not installed. "
                "Install with: pip install google-genai"
            )
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY is not set")
        self.client = genai.Client(api_key=self.api_key)
        self.default_model = default_model

    def generate_content(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        model_name = model or self.default_model
        config = {}
        if "temperature" in kwargs:
            config["temperature"] = kwargs.pop("temperature")
        if "max_output_tokens" in kwargs:
            config["max_output_tokens"] = kwargs.pop("max_output_tokens")
        response = self.client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=genai_types.GenerateContentConfig(**config) if config else None,
        )
        return response.text

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        model: Optional[str] = None,
        **kwargs,
    ) -> BaseModel:
        model_name = model or self.default_model
        config: Dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_schema"   : response_schema.model_json_schema(),
        }
        if "temperature" in kwargs:
            config["temperature"] = kwargs.pop("temperature")
        if "max_output_tokens" in kwargs:
            config["max_output_tokens"] = kwargs.pop("max_output_tokens")
        schema_prompt = (
            f"{prompt}\n\nOutput in JSON format following this schema: "
            f"{response_schema.model_json_schema()}"
        )
        response = self.client.models.generate_content(
            model=model_name,
            contents=schema_prompt,
            config=genai_types.GenerateContentConfig(**config),
        )
        try:
            return response_schema.model_validate_json(response.text)
        except Exception as e:
            logger.error(f"JSON parse error: {e}")
            logger.error(f"Raw response text from Gemini:\n{response.text}")
            raise

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        model_name = model or self.default_model
        response = self.client.models.count_tokens(model=model_name, contents=text)
        return response.total_tokens


# ================================================================
# Anthropic クライアント（後方互換として維持）
# ================================================================

class AnthropicClient(LLMClient):
    """
    Anthropic Claude API クライアント（後方互換として維持）
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        default_model: str = "claude-sonnet-4-6",
    ):
        if anthropic_sdk is None:
            raise ImportError(
                "anthropic package is not installed. "
                "Install with: pip install anthropic"
            )
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")
        self.client = anthropic_sdk.Anthropic(api_key=self.api_key)
        self.default_model = default_model
        logger.info(f"AnthropicClient initialized: model={default_model}")

    def generate_content(
        self,
        prompt: str,
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        model_name = model or self.default_model
        system = kwargs.pop("system", "You are a helpful assistant.")
        max_tokens = kwargs.pop("max_tokens", 4096)
        temperature = kwargs.pop("temperature", None)

        create_kwargs: Dict[str, Any] = {
            "model"     : model_name,
            "max_tokens": max_tokens,
            "system"    : system,
            "messages"  : [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature

        response = self.client.messages.create(**create_kwargs)
        return response.content[0].text

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        model: Optional[str] = None,
        **kwargs,
    ) -> BaseModel:
        model_name  = model or self.default_model
        system      = kwargs.pop("system", "You are a helpful assistant. Return structured data as requested.")
        max_tokens  = kwargs.pop("max_tokens", 4096)
        temperature = kwargs.pop("temperature", None)

        tool_def = {
            "name"        : "structured_output",
            "description" : "Return the result as a structured JSON object matching the given schema exactly.",
            "input_schema": response_schema.model_json_schema(),
        }

        create_kwargs: Dict[str, Any] = {
            "model"      : model_name,
            "max_tokens" : max_tokens,
            "system"     : system,
            "tools"      : [tool_def],
            "tool_choice": {"type": "tool", "name": "structured_output"},
            "messages"   : [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature

        response = self.client.messages.create(**create_kwargs)

        if response.stop_reason != "tool_use":
            raise ValueError(
                f"Unexpected stop_reason: {response.stop_reason}. "
                f"Content: {response.content}"
            )

        try:
            tool_block = next(b for b in response.content if b.type == "tool_use")
        except StopIteration:
            raise ValueError(f"No tool_use block in response. Content: {response.content}")

        try:
            return response_schema.model_validate(tool_block.input)
        except Exception as e:
            logger.error(f"Pydantic validation error: {e}")
            logger.error(f"Raw tool input: {tool_block.input}")
            raise

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        model_name = model or self.default_model
        response = self.client.messages.count_tokens(
            model=model_name,
            messages=[{"role": "user", "content": text}],
        )
        return response.input_tokens

    def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str = "",
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> Tuple[str, List[Dict[str, Any]], str]:
        model_name = model or self.default_model

        create_kwargs: Dict[str, Any] = {
            "model"     : model_name,
            "max_tokens": max_tokens,
            "tools"     : tools,
            "messages"  : messages,
        }
        if system:
            create_kwargs["system"] = system

        response = self.client.messages.create(**create_kwargs)

        tool_calls = [
            {"name": b.name, "input": b.input, "id": b.id}
            for b in response.content if b.type == "tool_use"
        ]
        text = " ".join(b.text for b in response.content if b.type == "text")
        return text, tool_calls, response.stop_reason

    def build_tool_result_message(
        self,
        tool_calls: List[Dict[str, Any]],
        results: List[str],
    ) -> Dict[str, Any]:
        content = [
            {"type": "tool_result", "tool_use_id": tc["id"], "content": result}
            for tc, result in zip(tool_calls, results)
        ]
        return {"role": "user", "content": content}


# ================================================================
# Ollama クライアント
# ================================================================

class OllamaClient(LLMClient):
    """
    Ollama ローカル LLM クライアント

    OpenAI SDK の base_url を差し替えて Ollama の OpenAI 互換エンドポイントを使用する。
    API キーは不要（api_key="ollama" はダミー値）。

    OpenAI との主要な差異：
      - Chat Completions のみ対応（Responses API 非対応）
      - 構造化出力: beta.parse() / responses.parse() 非対応 → JSON モード + Pydantic parse
      - max_tokens を使用（max_completion_tokens / max_output_tokens は非対応）
      - dimensions パラメータ（Embedding）非対応
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        default_model: str = "gemma4:e4b",
        **kwargs,
    ):
        if not OpenAI:
            raise ImportError("openai package is not installed.")
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.client = OpenAI(base_url=self.base_url, api_key="ollama")
        self.default_model = default_model
        logger.info(f"OllamaClient initialized: base_url={self.base_url}, model={default_model}")

    def generate_content(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        model_name = model or self.default_model
        system = kwargs.pop("system", None)
        # max_completion_tokens / max_output_tokens を max_tokens に統一
        max_tokens = (
            kwargs.pop("max_completion_tokens", None)
            or kwargs.pop("max_output_tokens", None)
            or kwargs.pop("max_tokens", 4096)
        )
        temperature = kwargs.pop("temperature", None)
        # JSON モード強制オプション（llama3.2 で空レスポンス防止）
        response_format = kwargs.pop("response_format", None)

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        create_kwargs: Dict[str, Any] = {
            "model"     : model_name,
            "messages"  : messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        if response_format is not None:
            create_kwargs["response_format"] = response_format

        response = self.client.chat.completions.create(**create_kwargs)
        return response.choices[0].message.content

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[BaseModel],
        model: Optional[str] = None,
        **kwargs,
    ) -> BaseModel:
        model_name = model or self.default_model
        system = kwargs.pop("system", "You are a helpful assistant. Output valid JSON only.")
        max_tokens = (
            kwargs.pop("max_completion_tokens", None)
            or kwargs.pop("max_output_tokens", None)
            or kwargs.pop("max_tokens", 8192)
        )
        temperature = kwargs.pop("temperature", 0.1)

        # $ref/$defs を解決してフラットなスキーマを使用
        # llama3.2 は $ref を含む複雑なスキーマを解釈できずスキーマ定義をオウム返しする
        raw_schema = response_schema.model_json_schema()
        flat_schema = _resolve_schema_refs(raw_schema)
        schema_json = json.dumps(flat_schema, ensure_ascii=False, indent=2)
        augmented_prompt = (
            f"{prompt}\n\n"
            "以下のJSONスキーマに完全に従い、スキーマ定義自体ではなく実際のデータをJSONで出力してください。\n"
            "余分なテキスト・説明・マークダウンは一切出力しないでください。JSONのみを出力してください。\n\n"
            f"スキーマ:\n{schema_json}"
        )

        messages = [
            {"role": "system", "content": system},
            {"role": "user",   "content": augmented_prompt},
        ]

        response = self.client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            temperature=temperature,
        )
        raw = response.choices[0].message.content
        try:
            return response_schema.model_validate_json(raw)
        except Exception as e:
            logger.error(f"Ollama JSON parse error: {e}")
            logger.error(f"Raw response: {raw}")
            raise

    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))

    def generate_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        system: str = "",
        model: Optional[str] = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> tuple:
        """
        Tool Use を含む ReAct ループの 1 ステップ。
        OpenAI Chat Completions 互換形式（tools パラメータ）を使用。
        対応モデル: llama3.2, llama3.1, gemma4:e4b, qwen2.5, mistral 等。
        非対応モデル（phi3, gemma2）は tools パラメータを送信しない。
        GeminiConfig.MODEL_CONSTRAINTS["supports_tool_calls"] で制御。
        """
        model_name = model or self.default_model

        # tool calling 非対応モデルは tools パラメータを除去してテキスト生成にフォールバック
        try:
            from config import GeminiConfig
            if tools and not GeminiConfig.supports_tool_calls(model_name):
                logger.warning(f"Model {model_name} does not support tool_calls. Falling back to text generation.")
                tools = []
        except ImportError:
            pass

        full_messages: List[Dict[str, Any]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        create_kwargs: Dict[str, Any] = {
            "model"     : model_name,
            "messages"  : full_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            openai_tools = [
                {
                    "type"    : "function",
                    "function": {
                        "name"       : t["name"],
                        "description": t.get("description", ""),
                        "parameters" : t.get("input_schema", t.get("parameters", {})),
                    }
                }
                for t in tools
            ]
            create_kwargs["tools"] = openai_tools

        if "temperature" in kwargs:
            create_kwargs["temperature"] = kwargs["temperature"]

        response = self.client.chat.completions.create(**create_kwargs)
        msg = response.choices[0].message

        tool_calls_result = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except Exception:
                    args = {}
                tool_calls_result.append({
                    "name" : tc.function.name,
                    "input": args,
                    "id"   : tc.id,
                })

        # gemma4:e4b 等は tool_calls を構造化レスポンスではなくテキストで返す
        # (finish_reason="stop", msg.tool_calls=None)
        # msg.content からテキスト形式のツール呼び出しをパースしてフォールバック
        text = msg.content or ""
        finish_reason = response.choices[0].finish_reason or "stop"

        if not tool_calls_result and text and tools:
            parsed = _parse_text_tool_calls(text)
            if parsed:
                tool_calls_result = parsed
                finish_reason = "tool_calls"
                logger.debug(f"Text-based tool calls parsed: {[t['name'] for t in parsed]}")

        # ケースB: msg.content=None かつ tool_calls=None（完全な空レスポンス）
        # tools パラメータが原因で一部モデルが無応答になる場合のフォールバック。
        # tools なしで再試行するが、ツール説明をプロンプトに埋め込んで
        # テキスト形式ツール呼び出し（_parse_text_tool_calls が解釈）を誘導する。
        if not text and not tool_calls_result and tools:
            logger.warning(
                f"Empty response from {model_name} with tools (finish_reason={finish_reason}). "
                "Retrying without tools parameter."
            )
            tool_desc_lines = "\n".join(
                f'- {t["name"]}: {t.get("description", "")}' for t in tools
            )
            fallback_messages = list(full_messages)
            fallback_messages.append({
                "role": "user",
                "content": (
                    f"利用可能なツール:\n{tool_desc_lines}\n\n"
                    "ツールを使う場合は次の形式で出力してください:\n"
                    'Action:ツール名{"引数名": "引数値"}\n\n'
                    "ツールが不要な場合は直接回答してください。"
                ),
            })
            retry_kwargs: Dict[str, Any] = {
                "model"     : model_name,
                "messages"  : fallback_messages,
                "max_tokens": max_tokens,
            }
            retry_response = self.client.chat.completions.create(**retry_kwargs)
            retry_msg = retry_response.choices[0].message
            text = retry_msg.content or ""
            finish_reason = retry_response.choices[0].finish_reason or "stop"
            logger.info(f"Retry without tools result length: {len(text)}")

            if text and not tool_calls_result:
                parsed = _parse_text_tool_calls(text)
                if parsed:
                    tool_calls_result = parsed
                    finish_reason = "tool_calls"
                    logger.debug(f"Retry text-based tool calls parsed: {[t['name'] for t in parsed]}")

        return text, tool_calls_result, finish_reason

    def build_tool_result_message(
        self,
        tool_calls: List[Dict[str, Any]],
        results: List[str],
    ) -> List[Dict[str, Any]]:
        return [
            {
                "role"        : "tool",
                "tool_call_id": tc["id"],
                "content"     : result,
            }
            for tc, result in zip(tool_calls, results)
        ]


# ================================================================
# ファクトリ関数
# ================================================================

def create_llm_client(provider: str = "ollama", **kwargs) -> LLMClient:
    """
    LLM クライアントのファクトリ関数

    Args:
        provider: "ollama" | "openai" | "anthropic" | "gemini"
                  デフォルト: "ollama"（ollama_grace_agent）
        **kwargs: 各クライアントの __init__ に渡すパラメータ

    Returns:
        LLMClient インスタンス

    Example:
        # ollama_grace_agent（デフォルト）
        llm = create_llm_client()
        text = llm.generate_content("こんにちは")

        # モデル指定
        llm = create_llm_client("ollama", default_model="llama3.2")

        # 他プロバイダー（後方互換）
        llm = create_llm_client("openai")
        llm = create_llm_client("anthropic")
    """
    provider = (provider or DEFAULT_LLM_PROVIDER).lower()

    if provider == "ollama":
        return OllamaClient(**kwargs)
    elif provider == "anthropic":
        return AnthropicClient(**kwargs)
    elif provider == "openai":
        return OpenAIClient(**kwargs)
    elif provider == "gemini":
        return GeminiClient(**kwargs)
    else:
        raise ValueError(
            f"Unknown provider: '{provider}'. "
            "Choose from 'ollama', 'openai', 'anthropic', 'gemini'."
        )


# ================================================================
# ヘルパー関数
# ================================================================

def get_available_llm_models() -> List[str]:
    """全プロバイダーの利用可能モデル一覧"""
    return LLM_MODELS


def get_available_llm_models_by_provider(provider: str) -> List[str]:
    """プロバイダー別モデル一覧"""
    provider = provider.lower()
    if provider == "ollama":
        return LLM_MODELS_OLLAMA
    elif provider == "anthropic":
        return LLM_MODELS_ANTHROPIC
    elif provider == "openai":
        return LLM_MODELS_OPENAI
    elif provider == "gemini":
        return LLM_MODELS_GEMINI
    return []


def get_llm_model_pricing(model_name: str) -> Dict[str, float]:
    return LLM_PRICING.get(model_name, {"input": 0.0, "output": 0.0})


def get_llm_model_limits(model_name: str) -> Dict[str, int]:
    return LLM_LIMITS.get(model_name, {"max_tokens": 0, "max_output": 0})


def get_available_embedding_models() -> List[str]:
    return EMBEDDING_MODELS


def get_embedding_model_pricing(model_name: str) -> float:
    return EMBEDDING_PRICING.get(model_name, 0.0)


def get_embedding_model_dimensions(model_name: str) -> int:
    return EMBEDDING_DIMS.get(model_name, 0)
