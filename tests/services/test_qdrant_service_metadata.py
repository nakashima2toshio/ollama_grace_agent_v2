
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# プロジェクトルートをパスに追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

# 実際の関数をインポート
from services.qdrant_service import get_collection_embedding_params


class TestQdrantServiceMetadata(unittest.TestCase):

    @patch('services.qdrant_service.QdrantClient')
    def test_get_collection_embedding_params_with_payload(self, MockClient):
        """qdrant_service.py がPayloadからプロバイダー情報を読み取れるか検証"""
        
        # モックの設定
        mock_client = MockClient()
        
        # scroll の戻り値をモック (Ollamaのケース)
        mock_point_ollama = MagicMock()
        mock_point_ollama.payload = {
            "embedding_provider": "ollama",
            "embedding_model": "nomic-embed-text"
        }
        # scroll は (points, next_offset) を返す
        mock_client.scroll.side_effect = [
            ([mock_point_ollama], None),  # 1回目の呼び出し (Ollamaテスト用)
            ([MagicMock(payload={"embedding_provider": "openai", "embedding_model": "text-embedding-3-small"})], None) # 2回目の呼び出し (OpenAIテスト用)
        ]
        
        # 1. Ollamaのケース検証
        params_ollama = get_collection_embedding_params(mock_client, "test_collection_ollama")
        self.assertEqual(params_ollama['model'], 'nomic-embed-text')
        
        # 2. OpenAIのケース検証
        params_openai = get_collection_embedding_params(mock_client, "test_collection_openai")
        self.assertEqual(params_openai['model'], 'text-embedding-3-small')

if __name__ == '__main__':
    unittest.main()
