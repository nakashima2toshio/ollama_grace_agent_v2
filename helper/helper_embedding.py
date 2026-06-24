"""
Embeddingクライアント抽象化レイヤー

Ollama をデフォルトとし、OpenAI / Gemini Embeddings API にも対応する統一インターフェースを提供。

- デフォルトプロバイダー: "ollama"
- Ollama デフォルトモデル: nomic-embed-text (768次元)

⚠️ 注意: プロバイダーごとに Embedding 次元数が異なります。
   - Ollama nomic-embed-text: 768次元
   - OpenAI text-embedding-3-large: 3072次元
   Embedding プロバイダーを切り替える場合は Qdrant コレクションの再作成が必要です。

使用例:
    from helper_embedding import create_embedding_client

    # Ollama Embeddingクライアント（768次元: デフォルト）
    embedding = create_embedding_client(provider="ollama")
    vector = embedding.embed_text("Hello world")
    print(f"Dimensions: {len(vector)}")  # 768
"""

import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from dotenv import load_dotenv

# SDK imports
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)


DEFAULT_GEMINI_EMBEDDING_DIMS = 3072
DEFAULT_OPENAI_EMBEDDING_DIMS = 3072
DEFAULT_OLLAMA_EMBEDDING_DIMS = 768   # nomic-embed-text


class EmbeddingClient(ABC):
    """Embeddingクライアント抽象基底クラス"""

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Embedding次元数を返す"""
        pass

    @abstractmethod
    def embed_text(self, text: str, task_type: Optional[str] = None) -> List[float]:
        """
        単一テキストのEmbedding生成

        Args:
            text: 入力テキスト
            task_type: タスクタイプ (Gemini用: retrieval_query, retrieval_documentなど)
                       OpenAI / Ollama では無視される。

        Returns:
            Embeddingベクトル（floatのリスト）
        """
        pass

    @abstractmethod
    def embed_texts(
        self,
        texts: List[str],
        batch_size: int = 100
    ) -> List[List[float]]:
        """
        バッチEmbedding生成

        Args:
            texts: 入力テキストのリスト
            batch_size: バッチサイズ

        Returns:
            Embeddingベクトルのリスト
        """
        pass


# ================================================================
# OpenAI Embedding クライアント（後方互換として維持）
# ================================================================

class OpenAIEmbedding(EmbeddingClient):
    """OpenAI Embeddings API実装"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "text-embedding-3-large",
        dims: int = DEFAULT_OPENAI_EMBEDDING_DIMS,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY が設定されていません")

        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self._dims = dims

    @property
    def dimensions(self) -> int:
        return self._dims

    def embed_text(self, text: str, task_type: Optional[str] = None) -> List[float]:
        """単一テキストのEmbedding生成"""
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
            dimensions=self._dims,
        )
        return response.data[0].embedding

    def embed_texts(
        self,
        texts: List[str],
        batch_size: int = 100,
    ) -> List[List[float]]:
        """バッチEmbedding生成"""
        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
                dimensions=self._dims,
            )

            sorted_data = sorted(response.data, key=lambda x: x.index)
            batch_embeddings = [item.embedding for item in sorted_data]
            all_embeddings.extend(batch_embeddings)

            if i + batch_size < len(texts):
                time.sleep(0.1)

        return all_embeddings


# ================================================================
# Ollama Embedding クライアント（デフォルト: ollama_grace_agent）
# ================================================================

class OllamaEmbedding(EmbeddingClient):
    """Ollama Embeddings API 実装（OpenAI SDK 流用 / nomic-embed-text / 768次元）

    - OpenAI SDK の base_url を差し替えて Ollama の OpenAI 互換エンドポイントを使用
    - dimensions パラメータ非対応（モデル固定次元数）
    - API キー不要（api_key="ollama" はダミー値）
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: str = "nomic-embed-text",
        dims: int = DEFAULT_OLLAMA_EMBEDDING_DIMS,
    ):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.client = OpenAI(base_url=self.base_url, api_key="ollama")
        self.model = model
        self._dims = dims
        logger.info(f"OllamaEmbedding initialized: model={model}, dims={dims}, base_url={self.base_url}")

    @property
    def dimensions(self) -> int:
        return self._dims

    def _apply_task_prefix(self, text: str, kind: str) -> str:
        """nomic-embed-text 用のタスクプレフィックスを付与する。

        nomic-embed-text は ``search_query:`` / ``search_document:`` の
        タスクプレフィックスが必須で、付けないと検索品質が大きく劣化する
        （日本語文がスコア 0.7〜0.8 帯に密集し正解が際立たなくなる）。
        プレフィックス不要なモデル（bge-m3 / mxbai 等）には付与しない。

        Args:
            text: 入力テキスト
            kind: "query"（検索クエリ）または "document"（登録文書）
        """
        if "nomic" not in self.model:
            return text
        prefix = "search_query: " if kind == "query" else "search_document: "
        return f"{prefix}{text}"

    def embed_text(self, text: str, task_type: Optional[str] = None) -> List[float]:
        # 単一テキストは原則「検索クエリ」。task_type に document 指定があれば文書扱い。
        kind = "document" if (task_type and "document" in task_type) else "query"
        response = self.client.embeddings.create(
            model=self.model,
            input=self._apply_task_prefix(text, kind),
            # dimensions パラメータは Ollama では非対応（指定しない）
        )
        return response.data[0].embedding

    def embed_texts(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            # バッチ Embedding は登録（文書）用途。nomic では search_document: を付与。
            prefixed = [self._apply_task_prefix(t, "document") for t in batch]
            response = self.client.embeddings.create(
                model=self.model,
                input=prefixed,
            )
            sorted_data = sorted(response.data, key=lambda x: x.index)
            all_embeddings.extend([item.embedding for item in sorted_data])
            if i + batch_size < len(texts):
                time.sleep(0.05)
        return all_embeddings


class GeminiEmbedding(EmbeddingClient):
    """Gemini Embeddings API実装（3072次元: 後方互換として残存）"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gemini-embedding-001",
        dims: int = DEFAULT_GEMINI_EMBEDDING_DIMS,
    ):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY が設定されていません")

        try:
            from google import genai as _genai
        except ImportError:
            raise ImportError("google-genai が未インストールです: pip install google-genai")
        self.client = _genai.Client(api_key=self.api_key)
        self.model = model
        self._dims = dims
        logger.info(f"GeminiEmbedding initialized: model={model}, dims={dims}")

    @property
    def dimensions(self) -> int:
        return self._dims

    def embed_text(self, text: str, task_type: Optional[str] = None) -> List[float]:
        """単一テキストのEmbedding生成（3072次元）"""
        config: dict[str, Any] = {"output_dimensionality": self._dims}
        if task_type:
            config["task_type"] = task_type
        response = self.client.models.embed_content(
            model=self.model, contents=text, config=config
        )
        return response.embeddings[0].values

    def embed_texts(
        self,
        texts: List[str],
        batch_size: int = 100,
    ) -> List[List[float]]:
        """バッチEmbedding生成"""
        all_embeddings: List[List[float]] = []
        total = len(texts)

        if batch_size > 100:
            batch_size = 100

        for i in range(0, total, batch_size):
            batch_texts = texts[i: i + batch_size]
            try:
                response = self.client.models.embed_content(
                    model=self.model,
                    contents=batch_texts,
                    config={"output_dimensionality": self._dims, "task_type": "retrieval_document"},
                )
                if hasattr(response, "embeddings") and response.embeddings:
                    all_embeddings.extend([e.values for e in response.embeddings])
                else:
                    raise ValueError("No embeddings returned in response")
                time.sleep(0.5)
            except Exception as e:
                logger.error(f"[Embedding] Batch error at index {i}: {e}")
                all_embeddings.extend([[0.0] * self._dims] * len(batch_texts))
                time.sleep(2.0)

        return all_embeddings


# ================================================================
# ファクトリ関数
# ================================================================

def create_embedding_client(
    provider: str = "ollama",
    **kwargs
) -> EmbeddingClient:
    """
    Embeddingクライアントのファクトリ関数

    Args:
        provider: "ollama", "openai", "gemini", or "fastembed"
                  デフォルト: "ollama"（ollama_grace_agent）
        **kwargs: クライアント初期化パラメータ

    Returns:
        EmbeddingClientインスタンス

    Example:
        # Ollama Embedding（768次元: デフォルト）
        embedding = create_embedding_client("ollama")

        # OpenAI Embedding（3072次元: 後方互換）
        embedding = create_embedding_client("openai")
    """
    if provider is None:
        logger.warning("Provider is None. Defaulting to 'ollama'.")
        provider = "ollama"

    if provider.lower() == "ollama":
        return OllamaEmbedding(**kwargs)
    elif provider.lower() == "openai":
        return OpenAIEmbedding(**kwargs)
    elif provider.lower() == "gemini":
        return GeminiEmbedding(**kwargs)
    elif provider.lower() == "fastembed":
        try:
            from helper.helper_embedding_fastembed import FastEmbedEmbedding
            return FastEmbedEmbedding(**kwargs)
        except ImportError as e:
            raise ImportError(f"FastEmbed module load failed: {e}. Check if 'fastembed' is installed.")
    else:
        raise ValueError(f"Unknown provider: {provider}. Use 'ollama', 'openai', 'gemini', or 'fastembed'")


# 環境変数 EMBEDDING_PROVIDER で上書き可能（.env に EMBEDDING_PROVIDER=ollama を追加推奨）
DEFAULT_EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "ollama")


def get_default_embedding_client(**kwargs) -> EmbeddingClient:
    """デフォルト設定でEmbeddingクライアントを取得"""
    return create_embedding_client(DEFAULT_EMBEDDING_PROVIDER, **kwargs)


# Qdrant用のヘルパー関数

EMBEDDING_PRICING: dict = {
    "nomic-embed-text"      : 0.0,
    "mxbai-embed-large"     : 0.0,
    "all-minilm"            : 0.0,
    "text-embedding-3-large": 0.00013,
    "text-embedding-3-small": 0.00002,
    "text-embedding-ada-002": 0.00010,
    "gemini-embedding-001"  : 0.0,
}


def get_embedding_model_pricing(model_name: str) -> float:
    """Embeddingモデルの価格を取得"""
    return EMBEDDING_PRICING.get(model_name, 0.0)


def get_embedding_dimensions(provider: str = "ollama") -> int:
    """
    指定プロバイダーのデフォルトEmbedding次元数を取得

    Qdrantコレクション作成時に使用

    Args:
        provider: "ollama", "openai", "gemini", or "fastembed"

    Returns:
        次元数
    """
    if provider is None:
        provider = "ollama"

    if provider.lower() == "ollama":
        return DEFAULT_OLLAMA_EMBEDDING_DIMS  # 768
    elif provider.lower() == "gemini":
        return DEFAULT_GEMINI_EMBEDDING_DIMS  # 3072
    elif provider.lower() == "openai":
        return DEFAULT_OPENAI_EMBEDDING_DIMS  # 3072
    elif provider.lower() == "fastembed":
        return 384
    else:
        raise ValueError(f"Unknown provider: {provider}")


if __name__ == "__main__":
    print("EmbeddingClient テスト")
    print("=" * 40)

    try:
        print("\n[Ollama Embedding Test] nomic-embed-text / 768次元")
        ollama_emb = create_embedding_client("ollama")
        print(f"Dimensions: {ollama_emb.dimensions}")
        vector = ollama_emb.embed_text("これはテストです")
        print(f"Vector length: {len(vector)}")
        print(f"First 5 values: {vector[:5]}")
        if len(vector) == DEFAULT_OLLAMA_EMBEDDING_DIMS:
            print("[OK] 768次元の検証: PASS")
        else:
            print(f"[NG] 768次元の検証: FAIL (actual: {len(vector)})")
    except Exception as e:
        print(f"Ollama Error: {e}")
        print("Ollama が起動しているか確認してください: ollama serve")
        print("モデルがインストール済みか確認してください: ollama pull nomic-embed-text")

    print("\n" + "=" * 40)
    print(f"Ollama default dims : {get_embedding_dimensions('ollama')}")
    print(f"OpenAI default dims : {get_embedding_dimensions('openai')}")
    print(f"Gemini default dims : {get_embedding_dimensions('gemini')}")
    print(f"DEFAULT_EMBEDDING_PROVIDER: {DEFAULT_EMBEDDING_PROVIDER}")
