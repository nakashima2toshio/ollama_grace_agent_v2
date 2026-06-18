"""
GRACE Groundedness Verifier Tests（S1・Ollama 構成）

grace/confidence.py の GroundednessVerifier を、LLM クライアント
（client.models.generate_content）をモックして検証する。実 Ollama 接続は不要。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from grace.confidence import (
    ClaimVerdict,
    GroundednessResponse,
    GroundednessResult,
    GroundednessVerifier,
    create_groundedness_verifier,
)


def _verifier_with_response(json_text):
    """client.models.generate_content が json_text を返す GroundednessVerifier。"""
    v = GroundednessVerifier()
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = SimpleNamespace(text=json_text)
    v.client = mock_client
    return v, mock_client


class TestGroundednessResponseSchema:
    def test_claim_verdict_default_neutral(self):
        cv = ClaimVerdict()
        assert cv.verdict == "neutral"

    def test_response_parses(self):
        resp = GroundednessResponse.model_validate_json(
            '{"claims": [{"claim": "x", "verdict": "supported"}], "reason": "ok"}'
        )
        assert resp.claims[0].verdict == "supported"
        assert resp.reason == "ok"


class TestVerify:
    def test_empty_answer_unverified(self):
        v, _ = _verifier_with_response("{}")
        res = v.verify("q", "", ["src"])
        assert res.verified is False
        assert res.reason == "empty answer"

    def test_no_sources_unverified(self):
        v, _ = _verifier_with_response("{}")
        res = v.verify("q", "ans", sources=None)
        assert res.verified is False
        assert res.reason == "no sources"

    def test_all_supported_support_rate_1(self):
        v, mock_client = _verifier_with_response(
            '{"claims": [{"claim": "a", "verdict": "supported"},'
            ' {"claim": "b", "verdict": "supported"}], "reason": "r"}'
        )
        res = v.verify("q", "ans", ["src1", "src2"])
        assert res.verified is True
        assert res.support_rate == 1.0
        assert res.supported == 2
        assert res.has_contradiction is False
        # LLM が JSON モードで呼ばれている
        cfg = mock_client.models.generate_content.call_args.kwargs["config"]
        assert cfg["response_mime_type"] == "application/json"

    def test_mixed_support_rate(self):
        v, _ = _verifier_with_response(
            '{"claims": [{"claim": "a", "verdict": "supported"},'
            ' {"claim": "b", "verdict": "contradicted"},'
            ' {"claim": "c", "verdict": "neutral"}], "reason": ""}'
        )
        res = v.verify("q", "ans", ["src"])
        # decided = supported(1)+contradicted(1)=2, support_rate = 1/2
        assert res.support_rate == 0.5
        assert res.total == 3
        assert res.has_contradiction is True

    def test_empty_response_unverified(self):
        v, _ = _verifier_with_response("")
        res = v.verify("q", "ans", ["src"])
        assert res.verified is False
        assert res.reason == "empty response"

    def test_llm_exception_unverified(self):
        v = GroundednessVerifier()
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("boom")
        v.client = mock_client
        res = v.verify("q", "ans", ["src"])
        assert res.verified is False
        assert res.reason.startswith("error:")


class TestFactoryAndResult:
    def test_factory_returns_verifier(self):
        assert isinstance(create_groundedness_verifier(), GroundednessVerifier)

    def test_result_fields(self):
        r = GroundednessResult(0.5, 1, 1, 2, True, True, "r")
        assert r.support_rate == 0.5
        assert r.has_contradiction is True
        assert r.verified is True
