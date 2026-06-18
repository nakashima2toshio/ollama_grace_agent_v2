from unittest.mock import patch

import numpy as np
import pytest

from qa_generation.evaluation import analyze_coverage


def _tiktoken_encoding_available() -> bool:
    """tiktoken の cl100k_base エンコーディングがロード可能か。

    analyze_coverage は内部で tiktoken.get_encoding("cl100k_base") を呼ぶ。
    初回はネットワークから BPE をダウンロードするため、オフライン環境
    （ネットワーク制限された CI / サンドボックス）では取得できない。
    その場合は本テストを skip し、環境差による偽陰性を避ける。
    """
    try:
        import tiktoken

        tiktoken.get_encoding("cl100k_base")
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _tiktoken_encoding_available(),
    reason="tiktoken cl100k_base エンコーディングが取得できない（オフライン環境）",
)
@patch("qa_generation.evaluation.SemanticCoverage")
def test_analyze_coverage(mock_semantic_coverage_cls):
    # Setup mock analyzer
    mock_analyzer = mock_semantic_coverage_cls.return_value
    
    # Mock embeddings (2 chunks, 2 QA pairs) -> dimension 2
    mock_analyzer.generate_embeddings.return_value = np.array([[1.0, 0.0], [0.0, 1.0]])
    mock_analyzer.generate_embeddings_batch.return_value = np.array([[1.0, 0.0], [0.0, 1.0]])
    
    # Mock cosine similarity
    # chunk0-qa0: 1.0 (perfect)
    # chunk0-qa1: 0.0
    # chunk1-qa0: 0.0
    # chunk1-qa1: 1.0
    def side_effect_similarity(v1, v2):
        return float(np.dot(v1, v2))
    
    mock_analyzer.cosine_similarity.side_effect = side_effect_similarity
    
    chunks = [{"id": "c1", "text": "t1"}, {"id": "c2", "text": "t2"}]
    qa_pairs = [{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}]
    
    result = analyze_coverage(chunks, qa_pairs, custom_threshold=0.5)
    
    assert result["coverage_rate"] == 1.0
    assert result["covered_chunks"] == 2
    assert result["total_chunks"] == 2
