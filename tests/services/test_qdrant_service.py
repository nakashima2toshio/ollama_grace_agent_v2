from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from qdrant_client.http import models

from services.qdrant_service import (
    QdrantDataFetcher,
    QdrantHealthChecker,
    build_inputs_for_embedding,
    build_points_for_qdrant,
    embed_query_for_search,
    embed_texts_for_qdrant,
    get_collection_embedding_params,
    get_dynamic_collection_mapping,
    load_csv_for_qdrant,
    map_collection_to_csv,
    merge_collections,
)


@pytest.fixture
def mock_qdrant_client():
    client = MagicMock()
    return client


@pytest.fixture(autouse=True)
def _clear_embedding_client_cache():
    """services.qdrant_service はモジュールレベルで Embedding クライアントを
    キャッシュする（_embedding_client_cache）。テスト間でモックが漏れないよう、
    各テストの前後でキャッシュをクリアして create_embedding_client のパッチを
    確実に効かせる。
    """
    from services.qdrant_service import _embedding_client_cache
    _embedding_client_cache.clear()
    yield
    _embedding_client_cache.clear()


class TestQdrantService:

    def test_map_collection_to_csv(self):
        with patch("os.path.exists") as mock_exists:
            # Case 1: 完全一致
            mock_exists.return_value = True
            assert map_collection_to_csv("test") == "test.csv"

            # Case 2: 完全一致のみサポート（'qa_' プレフィックス除去は廃止済み）。
            # "qa_test" に対し "qa_test.csv" が無ければ None を返す（"test.csv" へは丸めない）。
            mock_exists.return_value = False
            assert map_collection_to_csv("qa_test") is None

    def test_get_dynamic_collection_mapping(self, mock_qdrant_client):
        # Mock collections
        mock_c1 = MagicMock()
        mock_c1.name = "col1"
        mock_qdrant_client.get_collections.return_value.collections = [mock_c1]
        
        # Mock payload scroll
        mock_point = MagicMock()
        mock_point.payload = {"source": "source.csv"}
        mock_qdrant_client.scroll.return_value = ([mock_point], None)
        
        mapping = get_dynamic_collection_mapping(mock_qdrant_client)
        assert mapping["col1"] == "source.csv"

    def test_get_collection_embedding_params(self, mock_qdrant_client):
        # Case 1: 768 dim
        mock_info = MagicMock()
        mock_info.config.params.vectors.size = 768
        mock_qdrant_client.get_collection.return_value = mock_info
        
        params = get_collection_embedding_params(mock_qdrant_client, "c")
        assert params["dims"] == 768
        assert params["model"] == "nomic-embed-text"

    def test_health_checker(self):
        checker = QdrantHealthChecker()
        with patch.object(checker, "check_port", return_value=True), \
             patch("services.qdrant_service.QdrantClient") as MockClient:
            
            MockClient.return_value.get_collections.return_value.collections = []
            success, msg, metrics = checker.check_qdrant()
            assert success is True
            assert metrics is not None

    def test_data_fetcher(self, mock_qdrant_client):
        fetcher = QdrantDataFetcher(mock_qdrant_client)
        
        # fetch_collections
        mock_c = MagicMock()
        mock_c.name = "c1"
        mock_qdrant_client.get_collections.return_value.collections = [mock_c]
        mock_qdrant_client.get_collection.return_value.points_count = 100
        
        df = fetcher.fetch_collections()
        assert len(df) == 1
        assert df.iloc[0]["Collection"] == "c1"
        
        # fetch_collection_points
        mock_point = MagicMock()
        mock_point.id = 1
        mock_point.payload = {"k": "v"}
        mock_qdrant_client.scroll.return_value = ([mock_point], None)
        
        df_points = fetcher.fetch_collection_points("c1")
        assert len(df_points) == 1
        assert df_points.iloc[0]["k"] == "v"

    def test_load_csv_for_qdrant(self):
        with patch("os.path.exists", return_value=True), \
             patch("pandas.read_csv") as mock_read:
            
            mock_read.return_value = pd.DataFrame({
                "Question": ["q"], "Answer": ["a"]
            })
            
            df = load_csv_for_qdrant("dummy.csv")
            assert "question" in df.columns
            assert "answer" in df.columns

    def test_build_inputs_for_embedding(self):
        df = pd.DataFrame({"question": ["q"], "answer": ["a"]})
        inputs = build_inputs_for_embedding(df, include_answer=True)
        assert inputs[0] == "q\na"

    @patch("services.qdrant_service.create_embedding_client")
    def test_embed_texts_for_qdrant(self, mock_create):
        mock_client = MagicMock()
        mock_client.embed_texts.return_value = [[0.1]*768]
        mock_create.return_value = mock_client
        
        vecs = embed_texts_for_qdrant(["text"], model="nomic-embed-text")
        assert len(vecs) == 1
        assert len(vecs[0]) == 768

    def test_build_points_for_qdrant(self):
        df = pd.DataFrame({"question": ["q"], "answer": ["a"]})
        vectors = [[0.1]*768]
        
        points = build_points_for_qdrant(df, vectors, "domain", "source.csv")
        assert len(points) == 1
        assert isinstance(points[0], models.PointStruct)
        assert points[0].payload["question"] == "q"

    @patch("services.qdrant_service.create_embedding_client")
    def test_embed_query_for_search(self, mock_create):
        mock_client = MagicMock()
        mock_client.embed_text.return_value = [0.1]*768
        mock_create.return_value = mock_client
        
        vec = embed_query_for_search("q", dims=768)
        assert len(vec) == 768

    def test_merge_collections(self, mock_qdrant_client):
        # Mock scroll
        p1 = models.Record(id=1, vector=[0.1]*768, payload={"a": 1})
        mock_qdrant_client.scroll.side_effect = [([p1], None), ([p1], None)] # Called for each source col
        mock_qdrant_client.get_collection.return_value.points_count = 1
        
        result = merge_collections(mock_qdrant_client, ["s1"], "target")
        
        assert result["success"] is True
        mock_qdrant_client.upsert.assert_called()


class TestP0Fixes:
    """P0バグ修正の回帰テスト（安定ID・ゼロベクトル廃止・行フィルタ）"""

    def test_stable_point_id_deterministic(self):
        """ポイントIDが決定的であること（旧 hash() はプロセスごとに変動した）"""
        from qdrant_client_wrapper import stable_point_id

        a = stable_point_id("domain-source.csv-0")
        b = stable_point_id("domain-source.csv-0")
        assert a == b
        assert 0 < a < 2 ** 63
        # 既知のキーに対する期待値（プロセスを跨いだ安定性の固定値検証）
        assert stable_point_id("x-y-0") == 3147582548484565541

    def test_stable_point_id_distinct_keys(self):
        from qdrant_client_wrapper import stable_point_id

        assert stable_point_id("d-s-0") != stable_point_id("d-s-1")

    def test_build_points_uses_stable_ids(self):
        """build_points_for_qdrant の ID が同一入力で再現すること"""
        df = pd.DataFrame({"question": ["q1", "q2"], "answer": ["a1", "a2"]})
        vectors = [[0.1] * 768, [0.2] * 768]

        points1 = build_points_for_qdrant(df, vectors, "domain", "source.csv", start_index=0)
        points2 = build_points_for_qdrant(df, vectors, "domain", "source.csv", start_index=0)

        assert [p.id for p in points1] == [p.id for p in points2]
        assert points1[0].id != points1[1].id

    @patch("services.qdrant_service.create_embedding_client")
    def test_embed_texts_empty_returns_none(self, mock_create):
        """空テキストはゼロベクトルではなく None を返すこと"""
        mock_client = MagicMock()
        mock_client.embed_texts.return_value = [[0.1] * 768]
        mock_create.return_value = mock_client

        vecs = embed_texts_for_qdrant(["text", "", "   "])

        assert len(vecs) == 3
        assert vecs[0] is not None and len(vecs[0]) == 768
        assert vecs[1] is None
        assert vecs[2] is None

    @patch("services.qdrant_service.create_embedding_client")
    def test_embed_texts_all_empty(self, mock_create):
        """全て空テキストの場合は全て None（ダミーベクトルを返さない）"""
        mock_create.return_value = MagicMock()

        vecs = embed_texts_for_qdrant(["", "  "])

        assert vecs == [None, None]

    def test_filter_embeddable_rows(self):
        """None ベクトルの行が登録対象から除外されること"""
        from services.qdrant_service import filter_embeddable_rows

        df = pd.DataFrame({"question": ["q1", "q2", "q3"], "answer": ["a1", "a2", "a3"]})
        vectors = [[0.1] * 3, None, [0.3] * 3]

        fdf, fvecs, skipped = filter_embeddable_rows(df, vectors)

        assert skipped == 1
        assert len(fdf) == 2
        assert list(fdf["question"]) == ["q1", "q3"]
        assert fvecs == [[0.1] * 3, [0.3] * 3]

    def test_filter_embeddable_rows_no_skip(self):
        from services.qdrant_service import filter_embeddable_rows

        df = pd.DataFrame({"question": ["q1"], "answer": ["a1"]})
        vectors = [[0.1] * 3]

        fdf, fvecs, skipped = filter_embeddable_rows(df, vectors)

        assert skipped == 0
        assert len(fdf) == 1

    def test_filter_embeddable_rows_length_mismatch(self):
        from services.qdrant_service import filter_embeddable_rows

        df = pd.DataFrame({"question": ["q1"], "answer": ["a1"]})
        with pytest.raises(ValueError):
            filter_embeddable_rows(df, [[0.1], [0.2]])


class TestP1ContentBasedIds:
    """P1: ポイントIDの内容ハッシュ化（再登録べき等性）の回帰テスト"""

    def test_point_id_is_position_independent(self):
        """同一Q/Aは行の並び順が変わっても同一IDになること（位置非依存）"""
        df_a = pd.DataFrame({"question": ["q1", "q2"], "answer": ["a1", "a2"]})
        df_b = pd.DataFrame({"question": ["q2", "q1"], "answer": ["a2", "a1"]})
        vectors = [[0.1] * 768, [0.2] * 768]

        pa = build_points_for_qdrant(df_a, vectors, "dom", "src.csv")
        pb = build_points_for_qdrant(df_b, vectors, "dom", "src.csv")

        # q1/a1 の ID は並び順に関係なく一致する
        id_q1_in_a = pa[0].id
        id_q1_in_b = pb[1].id
        assert id_q1_in_a == id_q1_in_b

    def test_point_id_changes_with_content(self):
        """内容が異なれば別ID、同一内容なら同一ID"""
        df1 = pd.DataFrame({"question": ["q"], "answer": ["a"]})
        df2 = pd.DataFrame({"question": ["q"], "answer": ["a"]})
        df3 = pd.DataFrame({"question": ["q"], "answer": ["b"]})
        v = [[0.1] * 768]

        assert build_points_for_qdrant(df1, v, "d", "s.csv")[0].id == \
               build_points_for_qdrant(df2, v, "d", "s.csv")[0].id
        assert build_points_for_qdrant(df1, v, "d", "s.csv")[0].id != \
               build_points_for_qdrant(df3, v, "d", "s.csv")[0].id

    def test_point_id_independent_of_start_index(self):
        """start_index が変わっても内容が同じなら同一ID（旧実装は位置依存だった）"""
        df = pd.DataFrame({"question": ["q1"], "answer": ["a1"]})
        v = [[0.1] * 768]

        id0 = build_points_for_qdrant(df, v, "d", "s.csv", start_index=0)[0].id
        id100 = build_points_for_qdrant(df, v, "d", "s.csv", start_index=100)[0].id
        assert id0 == id100
