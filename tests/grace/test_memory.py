"""
GRACE Execution Memory Tests（P4・Ollama 構成）

grace/memory.py の実行メモリ層（JSONL 蓄積・コレクション事前分布）を検証する。
LLM 非依存・決定的（外部サービス不要、一時ファイルのみ使用）。
"""

from grace.memory import (
    CollectionStat,
    ExecutionMemory,
    MemoryRecord,
    create_execution_memory,
    extract_keywords,
)


class TestExtractKeywords:
    def test_empty(self):
        assert extract_keywords("") == []

    def test_alnum_and_japanese(self):
        kws = extract_keywords("Python の 機械学習 入門 2024")
        assert "python" in kws  # 小文字化
        assert "機械学習" in kws
        assert "2024" in kws

    def test_dedup_and_top_n(self):
        kws = extract_keywords("aa aa bb cc aa", top_n=2)
        assert kws == ["aa", "bb"]

    def test_single_char_ignored(self):
        # 1文字は抽出されない（2文字以上）
        assert extract_keywords("a b c") == []


class TestMemoryRecord:
    def test_roundtrip_dict(self):
        rec = MemoryRecord(
            query="q", keywords=["k1"], collection="cc_news_2per_ollama",
            success=True, confidence=0.8,
        )
        d = rec.to_dict()
        back = MemoryRecord.from_dict(d)
        assert back.query == "q"
        assert back.collection == "cc_news_2per_ollama"
        assert back.success is True
        assert back.confidence == 0.8

    def test_from_dict_defaults(self):
        rec = MemoryRecord.from_dict({})
        assert rec.query == ""
        assert rec.keywords == []
        assert rec.collection is None
        assert rec.success is False
        assert rec.confidence == 0.0


class TestCollectionStat:
    def test_success_rate(self):
        s = CollectionStat("c", count=4, success_count=3, mean_confidence=0.5)
        assert s.success_rate == 0.75

    def test_success_rate_zero_count(self):
        s = CollectionStat("c", count=0, success_count=0, mean_confidence=0.0)
        assert s.success_rate == 0.0

    def test_score_is_smoothed_rate_times_confidence(self):
        s = CollectionStat("c", count=10, success_count=10, mean_confidence=0.8)
        # smoothed = (10+1)/(10+2) = 0.9167 ; score = 0.9167 * 0.8
        assert abs(s.score() - (11 / 12) * 0.8) < 1e-9


class TestExecutionMemory:
    def _mem(self, tmp_path) -> ExecutionMemory:
        return ExecutionMemory(path=str(tmp_path / "mem.jsonl"))

    def test_record_and_load(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.record("Python とは", "col_a", success=True, confidence=0.9)
        recs = mem.load()
        assert len(recs) == 1
        assert recs[0].collection == "col_a"
        assert "python" in recs[0].keywords

    def test_load_missing_file_returns_empty(self, tmp_path):
        assert self._mem(tmp_path).load() == []

    def test_record_many_dedups_collections(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.record_many("q", ["a", "a", "b", None, "b"], success=True, confidence=0.5)
        cols = sorted(r.collection for r in mem.load() if r.collection)
        assert cols == ["a", "b"]

    def test_collection_priors_ordering(self, tmp_path):
        mem = self._mem(tmp_path)
        # good: 高 success_rate × confidence / bad: 低
        for _ in range(5):
            mem.record("機械学習 の質問", "good", success=True, confidence=0.9)
        for _ in range(5):
            mem.record("機械学習 の質問", "bad", success=False, confidence=0.2)
        priors = mem.collection_priors()
        assert priors[0].collection == "good"
        assert priors[0].score() > priors[-1].score()

    def test_collection_priors_keyword_filter(self, tmp_path):
        mem = self._mem(tmp_path)
        mem.record("料理 レシピ", "cooking", success=True, confidence=0.9)
        mem.record("機械学習 入門", "ml", success=True, confidence=0.9)
        priors = mem.collection_priors(query="機械学習 を学ぶ")
        cols = [p.collection for p in priors]
        assert "ml" in cols
        # キーワード一致するレコードのみ → cooking は除外される
        assert "cooking" not in cols

    def test_best_collection_threshold(self, tmp_path):
        mem = self._mem(tmp_path)
        # count<min_count（既定3）→ None
        mem.record("q", "c", success=True, confidence=0.9)
        assert mem.best_collection() is None
        # 十分な実績を積む → 返る
        for _ in range(5):
            mem.record("q", "c", success=True, confidence=0.9)
        assert mem.best_collection() == "c"

    def test_factory(self, tmp_path):
        mem = create_execution_memory(path=str(tmp_path / "m.jsonl"))
        assert isinstance(mem, ExecutionMemory)
