"""
helper/helper_llm.py 単体テスト（Ollama 構成）

anthropic 版（Gemini/OpenAI 前提・gemini は google.genai のローカル import で
patch 不可）をそのまま移植せず、Ollama 既定（OllamaClient / OpenAI 互換
エンドポイント）に合わせて作り直したもの。

テスト実行:
    pytest tests/helpers/test_helper_llm.py -v
"""

import os
import sys
from unittest.mock import Mock, patch

import pytest
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from helper.helper_llm import (
    OllamaClient,
    create_llm_client,
)


class MockResponseSchema(BaseModel):
    message: str
    score: int


class TestCreateLLMClient:
    """create_llm_client ファクトリ関数のテスト"""

    def test_create_ollama_client(self):
        """Ollamaクライアント生成"""
        with patch("helper.helper_llm.OpenAI"):
            client = create_llm_client("ollama")
            assert isinstance(client, OllamaClient)

    def test_create_default_is_ollama(self):
        """provider 省略時は Ollama"""
        with patch("helper.helper_llm.OpenAI"):
            client = create_llm_client()
            assert isinstance(client, OllamaClient)

    def test_invalid_provider(self):
        """不正なプロバイダー指定でエラー"""
        with pytest.raises(ValueError, match="Unknown provider"):
            create_llm_client("invalid_provider")


class TestOllamaClient:
    """OllamaClient クラスのテスト（OpenAI 互換エンドポイント）"""

    @pytest.fixture
    def mock_ollama_client(self):
        with patch("helper.helper_llm.OpenAI") as mock_class:
            mock_instance = Mock()
            mock_class.return_value = mock_instance
            client = OllamaClient(default_model="gemma4:e4b")
            return client, mock_instance

    def test_generate_content(self, mock_ollama_client):
        """テキスト生成（chat.completions.create を使用）"""
        client, mock_instance = mock_ollama_client

        mock_message = Mock()
        mock_message.content = "こんにちは"
        mock_choice = Mock()
        mock_choice.message = mock_message
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_instance.chat.completions.create.return_value = mock_response

        result = client.generate_content("挨拶して")

        assert result == "こんにちは"
        mock_instance.chat.completions.create.assert_called_once()

    def test_generate_structured(self, mock_ollama_client):
        """構造化出力（JSON モード + Pydantic parse）"""
        client, mock_instance = mock_ollama_client

        mock_message = Mock()
        mock_message.content = '{"message": "hi", "score": 5}'
        mock_choice = Mock()
        mock_choice.message = mock_message
        mock_response = Mock()
        mock_response.choices = [mock_choice]
        mock_instance.chat.completions.create.return_value = mock_response

        result = client.generate_structured("生成して", MockResponseSchema)

        assert isinstance(result, MockResponseSchema)
        assert result.message == "hi"
        assert result.score == 5
        # JSON モードが指定されていること
        _, kwargs = mock_instance.chat.completions.create.call_args
        assert kwargs.get("response_format") == {"type": "json_object"}

    def test_count_tokens(self, mock_ollama_client):
        """トークン数カウント（tiktoken cl100k_base）"""
        client, _ = mock_ollama_client

        with patch("helper.helper_llm.tiktoken") as mock_tiktoken:
            mock_enc = Mock()
            mock_enc.encode.return_value = [1, 2, 3, 4]
            mock_tiktoken.get_encoding.return_value = mock_enc

            result = client.count_tokens("テスト文字列")

        assert result == 4
