"""
GRACE S3 ハイブリッド ReAct Tests（Ollama 構成）

grace/executor.py の ReAct ループ（_dispatch_generator / execute_react_generator /
_decide_next_action）と grace/schemas.py の ReAct スキーマを検証する。
LLM（_react_client / _decide_next_action）はモックし、実 Ollama 接続は不要。
"""

from unittest.mock import MagicMock, patch

import pytest

from grace.config import reset_config
from grace.executor import Executor
from grace.schemas import (
    AgentThought,
    ExecutionPlan,
    PlanStep,
    Scratchpad,
    ScratchpadEntry,
)
from grace.tools import ToolRegistry, ToolResult

# =============================================================================
# スキーマ
# =============================================================================

class TestReactSchemas:
    def test_agent_thought_defaults(self):
        t = AgentThought()
        assert t.next_action == "reasoning"
        assert t.is_final is False

    def test_scratchpad_empty_prompt(self):
        assert "まだ何も実行" in Scratchpad().as_prompt()

    def test_scratchpad_add_and_prompt(self):
        sp = Scratchpad()
        sp.add(action="rag_search", observation="見つかった", confidence=0.8, query="Python")
        prompt = sp.as_prompt()
        assert "rag_search" in prompt
        assert "Python" in prompt
        assert sp.last_confidence() == 0.8

    def test_scratchpad_truncates_long_observation(self):
        sp = Scratchpad()
        sp.add(action="x", observation="あ" * 1000, confidence=0.5)
        assert "省略" in sp.entries[0].observation
        assert len(sp.entries[0].observation) <= 620

    def test_scratchpad_entry_confidence_bounds(self):
        with pytest.raises(Exception):
            ScratchpadEntry(action="x", confidence=1.5)


# =============================================================================
# ディスパッチ・ReAct ループ
# =============================================================================

class TestReactExecutor:
    def setup_method(self):
        reset_config()

    @pytest.fixture(autouse=True)
    def _stub_rag_relevance(self):
        with patch.object(Executor, "_evaluate_rag_relevance", return_value=True):
            yield

    @pytest.fixture
    def mock_tool_registry(self):
        registry = MagicMock(spec=ToolRegistry)
        rag_tool = MagicMock()
        rag_tool.execute.return_value = ToolResult(
            success=True,
            output=[{"id": 1, "score": 0.9, "payload": {"question": "Q1", "answer": "A1"}}],
            confidence_factors={"result_count": 1, "avg_score": 0.9, "score_variance": 0.0},
        )
        reasoning_tool = MagicMock()
        reasoning_tool.execute.return_value = ToolResult(
            success=True, output="最終回答です",
            confidence_factors={"has_sources": True, "source_count": 1},
        )

        def get_tool(name):
            return {"rag_search": rag_tool, "reasoning": reasoning_tool}.get(name)

        registry.get.side_effect = get_tool
        return registry

    def _complex_plan(self):
        return ExecutionPlan(
            original_query="複雑な質問",
            complexity=0.9,
            estimated_steps=2,
            requires_confirmation=False,
            steps=[
                PlanStep(step_id=1, action="rag_search", description="検索", query="q",
                         expected_output="検索結果"),
                PlanStep(step_id=2, action="reasoning", description="回答",
                         depends_on=[1], expected_output="回答"),
            ],
            success_criteria="ok",
            plan_id="cplx1",
        )

    def test_dispatch_static_when_react_disabled(self, mock_tool_registry):
        """react_enabled=False（既定）→ 静的パスへ振り分け"""
        ex = Executor(tool_registry=mock_tool_registry)
        ex.config.executor.react_enabled = False
        with patch.object(ex, "execute_react_generator") as react, \
             patch.object(ex, "execute_plan_generator") as static:
            static.return_value = iter([])
            list(ex._dispatch_generator(self._complex_plan()))
            static.assert_called_once()
            react.assert_not_called()

    def test_dispatch_react_when_enabled_and_complex(self, mock_tool_registry):
        """react_enabled=True かつ complexity>=閾値 → ReAct へ振り分け"""
        ex = Executor(tool_registry=mock_tool_registry)
        ex.config.executor.react_enabled = True
        ex.config.executor.react_complexity_threshold = 0.7
        with patch.object(ex, "execute_react_generator") as react, \
             patch.object(ex, "execute_plan_generator") as static:
            react.return_value = iter([])
            list(ex._dispatch_generator(self._complex_plan()))
            react.assert_called_once()
            static.assert_not_called()

    def test_dispatch_static_when_below_threshold(self, mock_tool_registry):
        """react_enabled でも complexity<閾値 → 静的パス温存"""
        ex = Executor(tool_registry=mock_tool_registry)
        ex.config.executor.react_enabled = True
        ex.config.executor.react_complexity_threshold = 0.7
        plan = self._complex_plan()
        plan.complexity = 0.3
        with patch.object(ex, "execute_react_generator") as react, \
             patch.object(ex, "execute_plan_generator") as static:
            static.return_value = iter([])
            list(ex._dispatch_generator(plan))
            static.assert_called_once()
            react.assert_not_called()

    def test_decide_next_action_fallback_without_llm(self, mock_tool_registry):
        """LLM 失敗時は初期計画キューを辿るフォールバック（degrade）"""
        ex = Executor(tool_registry=mock_tool_registry)
        # _react_client を失敗させる
        ex._react_client = MagicMock()
        ex._react_client.models.generate_content.side_effect = RuntimeError("no ollama")
        plan = self._complex_plan()
        queue = list(plan.steps)
        thought = ex._decide_next_action(plan, Scratchpad(), queue)
        assert isinstance(thought, AgentThought)
        assert thought.next_action == "rag_search"  # 先頭ステップ
        assert len(queue) == 1  # pop された

    def test_decide_next_action_uses_llm_response(self, mock_tool_registry):
        """LLM 応答（JSON）を AgentThought としてパースする"""
        ex = Executor(tool_registry=mock_tool_registry)
        ex._react_client = MagicMock()
        ex._react_client.models.generate_content.return_value = MagicMock(
            text='{"reasoning": "検索する", "next_action": "rag_search",'
                 ' "query": "Python", "is_final": false}'
        )
        thought = ex._decide_next_action(self._complex_plan(), Scratchpad(), [])
        assert thought.next_action == "rag_search"
        assert thought.query == "Python"

    def test_react_loop_finishes_with_final_answer(self, mock_tool_registry):
        """ReAct ループ: reasoning(is_final) → 最終回答を生成して終了"""
        ex = Executor(tool_registry=mock_tool_registry)
        ex.config.executor.react_enabled = True
        # 1手目で reasoning + is_final を返す
        with patch.object(
            ex, "_decide_next_action",
            return_value=AgentThought(
                reasoning="十分", next_action="reasoning",
                query="複雑な質問", is_final=True,
            ),
        ):
            result = ex.execute_react_generator(self._complex_plan())
            # ジェネレータをドレイン
            try:
                while True:
                    next(result)
            except StopIteration as e:
                exec_result = e.value
        assert exec_result is not None
        assert 0.0 <= exec_result.overall_confidence <= 1.0
        assert exec_result.final_answer is not None

    def test_react_loop_degrades_to_plan_without_llm(self, mock_tool_registry):
        """LLM 不在でも初期計画フォールバックで完走する（クラッシュしない）"""
        ex = Executor(tool_registry=mock_tool_registry)
        ex.config.executor.react_enabled = True
        ex._react_client = MagicMock()
        ex._react_client.models.generate_content.side_effect = RuntimeError("no ollama")
        gen = ex.execute_react_generator(self._complex_plan())
        try:
            while True:
                next(gen)
        except StopIteration as e:
            exec_result = e.value
        assert exec_result is not None
        assert exec_result.overall_status in ("success", "partial", "failed", "cancelled")
