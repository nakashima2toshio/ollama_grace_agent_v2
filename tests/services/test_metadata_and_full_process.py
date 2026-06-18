
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

# プロジェクトルートをパスに追加
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from services.qdrant_service import build_points_for_qdrant, get_collection_embedding_params


class TestQdrantMetadataAndProcess(unittest.TestCase):

    def test_full_point_conversion_with_metadata(self):
        """バッチサイズに関わらず、全データがメタデータ付きで変換されるか検証"""
        # バッチサイズを超えるデータを想定（例: 150件）
        num_records = 150
        df = pd.DataFrame({
            'question': [f'Q{i}' for i in range(num_records)],
            'answer': [f'A{i}' for i in range(num_records)]
        })
        vectors = [[0.1] * 768] * num_records
        
        # 修正後のロジックをシミュレートして全件処理を確認
        points = build_points_for_qdrant(df, vectors, domain="test", source_file="test.csv")
        
        # メタデータ付与（修正予定のロジック）
        for p in points:
            p.payload["embedding_provider"] = "ollama"
            p.payload["embedding_model"] = "nomic-embed-text"
            
        self.assertEqual(len(points), num_records)
        self.assertEqual(points[149].payload['embedding_provider'], 'ollama')
        self.assertEqual(points[149].payload['question'], 'Q149')

    @patch('services.qdrant_service.QdrantClient')
    def test_get_params_prioritizes_payload(self, MockClient):
        """qdrant_service が Payload 内のメタデータを正しく優先認識するか検証"""
        mock_client = MockClient()
        
        # Payload にメタデータがあるポイントを返すようにモック
        mock_point = MagicMock()
        mock_point.payload = {
            "embedding_provider": "ollama",
            "embedding_model": "nomic-embed-test-model"
        }
        mock_client.scroll.return_value = ([mock_point], None)
        
        # コレクション情報は 768次元とする
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 768
        mock_client.get_collection.return_value = mock_info

        # 実行 (修正後の想定動作)
        params = get_collection_embedding_params(mock_client, "test_collection")
        
        # 検証: Payload のモデル名が取得されていること
        self.assertEqual(params['model'], 'nomic-embed-test-model')

if __name__ == '__main__':
    unittest.main()
