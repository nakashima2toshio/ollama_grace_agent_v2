"""
GRACE llm_compat Tests（Ollama 構成）

grace/llm_compat.py の genai 互換 Ollama アダプタを検証する。
内部の helper.helper_llm.create_llm_client をモックし、実 Ollama 接続なしで検証する。
"""

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from grace.llm_compat import (
    DEFAULT_OLLAMA_MODEL,
    OllamaGenaiClient,
    _strip_to_json,
    create_chat_client,
)


def _config(provider="ollama", model=None):
    """config.llm.provider / config.llm.model を持つ簡易設定オブジェクト。"""
    return SimpleNamespace(llm=SimpleNamespace(provider=provider, model=model))


class TestStripToJson:
    def test_plain_object(self):
        assert _strip_to_json('{"a": 1}') == '{"a": 1}'

    def test_markdown_fence(self):
        assert _strip_to_json('```json\n{"a": 1}\n```') == '{"a": 1}'

    def test_surrounding_prose(self):
        assert _strip_to_json('結果は {"a": 1} です') == '{"a": 1}'

    def test_array(self):
        assert _strip_to_json("前置き [1, 2, 3] 後置き") == "[1, 2, 3]"


class TestCreateChatClient:
    def test_default_is_ollama(self):
        client = create_chat_client()
        assert isinstance(client, OllamaGenaiClient)
        assert client._default_model == DEFAULT_OLLAMA_MODEL

    def test_config_model_propagates(self):
        client = create_chat_client(_config(provider="ollama", model="llama3.2"))
        assert isinstance(client, OllamaGenaiClient)
        assert client._default_model == "llama3.2"

    def test_none_provider_falls_back_to_ollama(self):
        client = create_chat_client(_config(provider=None, model=None))
        assert isinstance(client, OllamaGenaiClient)
        assert client._default_model == DEFAULT_OLLAMA_MODEL

    def test_gemini_provider_routes_to_genai(self, monkeypatch):
        """provider=gemini のときのみ google-genai を呼ぶ（fake モジュールで検証）。"""
        fake_client = object()
        fake_genai = types.ModuleType("google.genai")
        fake_genai.Client = lambda *a, **k: fake_client
        fake_google = types.ModuleType("google")
        fake_google.genai = fake_genai
        monkeypatch.setitem(sys.modules, "google", fake_google)
        monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

        result = create_chat_client(_config(provider="gemini", model=None))
        assert result is fake_client


class TestOllamaGenaiClientGenerateContent:
    def _patch_llm(self, returns="hello"):
        """helper.helper_llm.create_llm_client を差し替えるパッチャを返す。"""
        mock_llm = MagicMock()
        mock_llm.generate_content.return_value = returns
        return patch("helper.helper_llm.create_llm_client", return_value=mock_llm), mock_llm

    def test_generate_content_returns_text(self):
        patcher, mock_llm = self._patch_llm("こんにちは")
        with patcher:
            client = create_chat_client(_config(model="gemma4:e4b"))
            resp = client.models.generate_content(contents="hi")
        assert resp.text == "こんにちは"
        assert resp.parsed is None
        # OllamaClient.generate_content(prompt, **kwargs) が呼ばれている
        assert mock_llm.generate_content.call_args.args[0] == "hi"

    def test_lazy_init_no_call_until_generate(self):
        """構築時には create_llm_client を呼ばない（遅延初期化）。"""
        patcher, mock_llm = self._patch_llm()
        with patcher as mocked:
            client = create_chat_client()
            mocked.assert_not_called()
            client.models.generate_content(contents="x")
            mocked.assert_called_once()

    def test_passes_temperature_and_max_tokens(self):
        patcher, mock_llm = self._patch_llm()
        with patcher:
            client = create_chat_client()
            client.models.generate_content(
                contents="x",
                config={"temperature": 0.3, "max_output_tokens": 256},
            )
        kwargs = mock_llm.generate_content.call_args.kwargs
        assert kwargs["temperature"] == 0.3
        assert kwargs["max_tokens"] == 256

    def test_json_mode_strips_fence_and_sets_response_format(self):
        patcher, mock_llm = self._patch_llm('```json\n{"ok": true}\n```')
        with patcher:
            client = create_chat_client()
            resp = client.models.generate_content(
                contents="x",
                config={"response_mime_type": "application/json"},
            )
        assert resp.text == '{"ok": true}'
        kwargs = mock_llm.generate_content.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}
        assert "system" in kwargs  # JSON 厳守のシステム指示が付く

    def test_non_string_contents_stringified(self):
        patcher, mock_llm = self._patch_llm("ok")
        with patcher:
            client = create_chat_client()
            client.models.generate_content(contents=123)
        assert mock_llm.generate_content.call_args.args[0] == "123"
