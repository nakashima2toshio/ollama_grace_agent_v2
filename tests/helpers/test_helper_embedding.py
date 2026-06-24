"""
helper/helper_embedding.py 単体テスト（Ollama 構成）

anthropic 版（Gemini/OpenAI 前提・gemini は google.genai のローカル import で
patch 不可）をそのまま移植せず、Ollama 既定（OllamaEmbedding / nomic-embed-text /
768次元）に合わせて作り直したもの。OpenAI 経路は OpenAI SDK 流用のため module
レベルの `OpenAI` を patch して検証する。

テスト実行:
    pytest tests/helpers/test_helper_embedding.py -v
"""

import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from helper.helper_embedding import (
    OllamaEmbedding,
    OpenAIEmbedding,
    create_embedding_client,
    get_embedding_dimensions,
)


class TestCreateEmbeddingClient:
    """create_embedding_client ファクトリ関数のテスト"""

    def test_create_ollama_client(self):
        """Ollamaクライアント生成（デフォルト）"""
        with patch("helper.helper_embedding.OpenAI") as _mock_openai:
            client = create_embedding_client("ollama")
            assert isinstance(client, OllamaEmbedding)

    def test_create_default_is_ollama(self):
        """provider 省略時は Ollama"""
        with patch("helper.helper_embedding.OpenAI") as _mock_openai:
            client = create_embedding_client()
            assert isinstance(client, OllamaEmbedding)

    def test_create_openai_client(self):
        """OpenAIクライアント生成（後方互換・多provider対応）"""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("helper.helper_embedding.OpenAI") as _mock_openai:
                client = create_embedding_client("openai")
                assert isinstance(client, OpenAIEmbedding)

    def test_invalid_provider(self):
        """不正なプロバイダー指定でエラー"""
        with pytest.raises(ValueError, match="Unknown provider"):
            create_embedding_client("invalid_provider")


class TestOllamaEmbedding:
    """OllamaEmbedding クラスのテスト（nomic-embed-text / 768次元）"""

    @pytest.fixture
    def mock_ollama_client(self):
        with patch("helper.helper_embedding.OpenAI") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            client = OllamaEmbedding()
            return client, mock_instance

    def test_dimensions_is_768(self, mock_ollama_client):
        """既定次元数は 768（nomic-embed-text）"""
        client, _ = mock_ollama_client
        assert client.dimensions == 768

    def test_embed_text(self, mock_ollama_client):
        """単一テキストEmbedding"""
        client, mock_instance = mock_ollama_client

        mock_data = Mock()
        mock_data.embedding = [0.1] * 768
        mock_response = Mock()
        mock_response.data = [mock_data]
        mock_instance.embeddings.create.return_value = mock_response

        result = client.embed_text("Hello")

        assert len(result) == 768
        assert result[0] == 0.1
        mock_instance.embeddings.create.assert_called_once()

    def test_embed_texts(self, mock_ollama_client):
        """バッチEmbedding（index順にソートされること）"""
        client, mock_instance = mock_ollama_client

        # モックレスポンス（3件分・index を意図的に逆順で返す）
        mock_data0 = Mock(embedding=[0.1] * 768, index=0)
        mock_data1 = Mock(embedding=[0.2] * 768, index=1)
        mock_data2 = Mock(embedding=[0.3] * 768, index=2)

        mock_response = Mock()
        mock_response.data = [mock_data2, mock_data0, mock_data1]  # 逆順
        mock_instance.embeddings.create.return_value = mock_response

        result = client.embed_texts(["Hello", "World", "Test"])

        assert len(result) == 3
        assert len(result[0]) == 768
        # index 順にソートされる
        assert result[0][0] == 0.1
        assert result[1][0] == 0.2
        assert result[2][0] == 0.3

    def test_query_gets_search_query_prefix(self, mock_ollama_client):
        """nomic では検索クエリに search_query: プレフィックスが付与される"""
        client, mock_instance = mock_ollama_client
        mock_response = Mock()
        mock_response.data = [Mock(embedding=[0.1] * 768)]
        mock_instance.embeddings.create.return_value = mock_response

        client.embed_text("Amazonの在宅勤務")

        sent = mock_instance.embeddings.create.call_args.kwargs["input"]
        assert sent == "search_query: Amazonの在宅勤務"

    def test_documents_get_search_document_prefix(self, mock_ollama_client):
        """nomic では登録文書（バッチ）に search_document: プレフィックスが付与される"""
        client, mock_instance = mock_ollama_client
        mock_response = Mock()
        mock_response.data = [Mock(embedding=[0.1] * 768, index=0),
                              Mock(embedding=[0.2] * 768, index=1)]
        mock_instance.embeddings.create.return_value = mock_response

        client.embed_texts(["記事A", "記事B"])

        sent = mock_instance.embeddings.create.call_args.kwargs["input"]
        assert sent == ["search_document: 記事A", "search_document: 記事B"]

    def test_non_nomic_model_skips_prefix(self):
        """プレフィックス不要モデル（bge-m3 等）には付与しない"""
        with patch("helper.helper_embedding.OpenAI") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            client = OllamaEmbedding(model="bge-m3", dims=1024)
            mock_response = Mock()
            mock_response.data = [Mock(embedding=[0.1] * 1024)]
            mock_instance.embeddings.create.return_value = mock_response

            client.embed_text("Amazonの在宅勤務")

            sent = mock_instance.embeddings.create.call_args.kwargs["input"]
            assert sent == "Amazonの在宅勤務"  # プレフィックスなし


class TestOpenAIEmbedding:
    """OpenAIEmbedding クラスのテスト（後方互換）"""

    @pytest.fixture
    def mock_openai_client(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            with patch("helper.helper_embedding.OpenAI") as mock_class:
                mock_instance = Mock()
                mock_class.return_value = mock_instance
                client = OpenAIEmbedding()
                return client, mock_instance

    def test_embed_text(self, mock_openai_client):
        """単一テキストEmbedding"""
        client, mock_instance = mock_openai_client

        mock_data = Mock()
        mock_data.embedding = [0.1] * 3072
        mock_response = Mock()
        mock_response.data = [mock_data]
        mock_instance.embeddings.create.return_value = mock_response

        result = client.embed_text("Hello")

        assert len(result) == 3072
        assert result[0] == 0.1
        mock_instance.embeddings.create.assert_called_once()


class TestHelpers:
    """ヘルパー関数のテスト"""

    def test_get_embedding_dimensions(self):
        # Ollama 既定（nomic-embed-text）は 768
        assert get_embedding_dimensions("ollama") == 768
        # 後方互換: openai / gemini は 3072（text-embedding-3-large / gemini-embedding-001）
        assert get_embedding_dimensions("openai") == 3072
        assert get_embedding_dimensions("gemini") == 3072

        with pytest.raises(ValueError):
            get_embedding_dimensions("invalid")
