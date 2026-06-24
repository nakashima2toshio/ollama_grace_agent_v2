"""
GRACE Executor Tests
Executorのテスト
"""

from unittest.mock import MagicMock, patch

import pytest

from grace.config import reset_config
from grace.executor import ExecutionState, Executor, create_executor
from grace.schemas import ExecutionPlan, PlanStep, StepResult, StepStatus
from grace.tools import ToolRegistry, ToolResult


class TestExecutionState:
    """ExecutionStateのテスト"""

    @pytest.fixture
    def sample_plan(self):
        """テスト用の計画"""
        return ExecutionPlan(
            original_query="テスト",
            complexity=0.5,
            estimated_steps=2,
            requires_confirmation=False,
            steps=[
                PlanStep(
                    step_id=1,
                    action="rag_search",
                    description="検索",
                    expected_output="結果"
                ),
                PlanStep(
                    step_id=2,
                    action="reasoning",
                    description="推論",
                    depends_on=[1],
                    expected_output="回答"
                )
            ],
            success_criteria="テスト",
            plan_id="test123"
        )

    def test_initial_state(self, sample_plan):
        """初期状態"""
        state = ExecutionState(plan=sample_plan)

        assert state.current_step_id == 0
        assert len(state.step_results) == 0
        assert state.overall_confidence == 0.0
        assert not state.is_cancelled
        assert not state.is_paused
        assert state.replan_count == 0

    def test_step_statuses_initialized(self, sample_plan):
        """ステップステータスの初期化"""
        state = ExecutionState(plan=sample_plan)

        assert state.step_statuses[1] == StepStatus.PENDING
        assert state.step_statuses[2] == StepStatus.PENDING

    def test_get_completed_outputs(self, sample_plan):
        """完了済み出力の取得"""
        state = ExecutionState(plan=sample_plan)
        state.step_results[1] = StepResult(
            step_id=1,
            status="success",
            output="検索結果",
            confidence=0.8
        )

        outputs = state.get_completed_outputs()
        assert 1 in outputs
        assert outputs[1] == "検索結果"

    def test_can_replan(self, sample_plan):
        """リプラン可否判定"""
        state = ExecutionState(plan=sample_plan, max_replans=3)

        assert state.can_replan()

        state.replan_count = 3
        assert not state.can_replan()

        state.replan_count = 0
        state.is_cancelled = True
        assert not state.can_replan()


class TestExecutor:
    """Executorのテスト"""

    def setup_method(self):
        """各テスト前の準備"""
        reset_config()

    @pytest.fixture(autouse=True)
    def _stub_rag_relevance(self):
        """RAG意味的適合性チェックは実LLM呼び出しを伴う。

        本クラスはモックツールでオーケストレーションを検証するユニットテストのため、
        実LLMに依存する適合性判定は固定値にスタブする。スタブしないと、LLMの有無や
        モデル種別（thinking/推論系）で判定が変動し、動的 web_search 挿入により
        テストが非決定的になる。実LLM版は統合テスト側で担保する。
        """
        with patch.object(Executor, "_evaluate_rag_relevance", return_value=True):
            yield

    @pytest.fixture
    def mock_tool_registry(self):
        """モックツールレジストリ"""
        registry = MagicMock(spec=ToolRegistry)

        # RAG検索ツールのモック
        rag_tool = MagicMock()
        rag_tool.execute.return_value = ToolResult(
            success=True,
            output=[
                {"id": 1, "score": 0.9, "payload": {"question": "Q1", "answer": "A1"}}
            ],
            confidence_factors={
                "result_count": 1,
                "avg_score": 0.9,
                "score_variance": 0.0
            }
        )

        # 推論ツールのモック
        reasoning_tool = MagicMock()
        reasoning_tool.execute.return_value = ToolResult(
            success=True,
            output="回答です",
            confidence_factors={
                "has_sources": True,
                "source_count": 1
            }
        )

        def get_tool(name):
            if name == "rag_search":
                return rag_tool
            elif name == "reasoning":
                return reasoning_tool
            return None

        registry.get.side_effect = get_tool
        return registry

    @pytest.fixture
    def sample_plan(self):
        """テスト用の計画"""
        return ExecutionPlan(
            original_query="Pythonについて教えて",
            complexity=0.5,
            estimated_steps=2,
            requires_confirmation=False,
            steps=[
                PlanStep(
                    step_id=1,
                    action="rag_search",
                    description="関連情報を検索",
                    query="Python",
                    expected_output="検索結果"
                ),
                PlanStep(
                    step_id=2,
                    action="reasoning",
                    description="回答を生成",
                    depends_on=[1],
                    expected_output="回答"
                )
            ],
            success_criteria="質問に回答できている",
            plan_id="test123"
        )

    def test_execute_plan_success(self, mock_tool_registry, sample_plan):
        """計画実行の成功"""
        executor = Executor(tool_registry=mock_tool_registry)
        result = executor.execute_plan(sample_plan)

        assert result.overall_status == "success"
        assert len(result.step_results) == 2
        assert result.final_answer is not None

    def test_execute_plan_with_callbacks(self, mock_tool_registry, sample_plan):
        """コールバック付きの計画実行"""
        step_starts = []
        step_completes = []

        executor = Executor(
            tool_registry=mock_tool_registry,
            on_step_start=lambda step: step_starts.append(step.step_id),
            on_step_complete=lambda result: step_completes.append(result.step_id)
        )

        executor.execute_plan(sample_plan)

        assert len(step_starts) == 2
        assert len(step_completes) == 2

    def test_execute_plan_dependency_check(self, mock_tool_registry):
        """依存関係のチェック"""
        plan = ExecutionPlan(
            original_query="テスト",
            complexity=0.5,
            estimated_steps=2,
            requires_confirmation=False,
            steps=[
                PlanStep(
                    step_id=1,
                    action="rag_search",
                    description="検索",
                    expected_output="結果"
                ),
                PlanStep(
                    step_id=2,
                    action="reasoning",
                    description="推論",
                    depends_on=[1],
                    expected_output="回答"
                )
            ],
            success_criteria="テスト",
            plan_id="test123"
        )

        # Step 1を失敗させる
        rag_tool = MagicMock()
        rag_tool.execute.return_value = ToolResult(
            success=False,
            output=None,
            error="Search failed"
        )
        mock_tool_registry.get.side_effect = lambda name: rag_tool if name == "rag_search" else None

        executor = Executor(tool_registry=mock_tool_registry)
        result = executor.execute_plan(plan)

        # Step 2はスキップされる
        assert result.overall_status in ["partial", "failed"]

    def test_cancel_execution(self, mock_tool_registry, sample_plan):
        """実行のキャンセル"""
        state = ExecutionState(plan=sample_plan)
        executor = Executor(tool_registry=mock_tool_registry)

        executor.cancel(state)
        assert state.is_cancelled

    def test_calculate_overall_confidence(self, mock_tool_registry, sample_plan):
        """全体信頼度の計算"""
        executor = Executor(tool_registry=mock_tool_registry)
        result = executor.execute_plan(sample_plan)

        # 信頼度は0.0-1.0の範囲
        assert 0.0 <= result.overall_confidence <= 1.0

    def test_reasoning_kwargs_use_original_query(self, mock_tool_registry, sample_plan):
        """reasoning ステップは step.description ではなく元の質問を query に渡す。"""
        executor = Executor(tool_registry=mock_tool_registry)
        state = ExecutionState(plan=sample_plan)
        reasoning_step = sample_plan.steps[1]  # action='reasoning', query=None, description='推論'
        kwargs = executor._prepare_tool_kwargs(reasoning_step, state)
        # description（'推論'）ではなく original_query が渡る
        assert kwargs["query"] == sample_plan.original_query
        assert kwargs["query"] != reasoning_step.description


class TestRagRelevanceFallback:
    """_evaluate_rag_relevance: LLM 判定不能時のスコアベースフォールバック。"""

    def setup_method(self):
        reset_config()

    def _executor(self):
        return Executor(tool_registry=MagicMock(spec=ToolRegistry))

    def test_empty_answer_low_score_not_relevant(self):
        """空応答＋スコアが しきい値+margin 未満 → not relevant（web/escalate へ）。"""
        ex = self._executor()
        with patch("grace.executor.create_llm_client") as mk:
            mk.return_value.generate_content.return_value = ""
            # threshold 0.7 + margin 0.08 = 0.78。0.72 は未満 → False
            assert ex._evaluate_rag_relevance(
                "q", "out", rag_max_score=0.72, rag_threshold=0.7) is False

    def test_empty_answer_high_score_relevant(self):
        """空応答でもスコアが十分高ければ relevant 維持（Q01 0.81 を守る）。"""
        ex = self._executor()
        with patch("grace.executor.create_llm_client") as mk:
            mk.return_value.generate_content.return_value = ""
            assert ex._evaluate_rag_relevance(
                "q", "out", rag_max_score=0.81, rag_threshold=0.7) is True

    def test_llm_no_overrides_high_score(self):
        """LLM が NO と明言したらスコアが高くても not relevant。"""
        ex = self._executor()
        with patch("grace.executor._LLM_CLIENT_AVAILABLE", True), \
             patch("grace.executor.create_llm_client") as mk:
            mk.return_value.generate_content.return_value = "NO"
            assert ex._evaluate_rag_relevance(
                "q", "out", rag_max_score=0.85, rag_threshold=0.7) is False

    def test_llm_japanese_muskankei_is_not_relevant(self):
        """日本語『無関係』も not relevant として解釈する。"""
        ex = self._executor()
        with patch("grace.executor._LLM_CLIENT_AVAILABLE", True), \
             patch("grace.executor.create_llm_client") as mk:
            mk.return_value.generate_content.return_value = "この検索結果は質問とは無関係です"
            assert ex._evaluate_rag_relevance(
                "q", "out", rag_max_score=0.85) is False

    def test_llm_yes_is_relevant(self):
        ex = self._executor()
        with patch("grace.executor._LLM_CLIENT_AVAILABLE", True), \
             patch("grace.executor.create_llm_client") as mk:
            mk.return_value.generate_content.return_value = "YES、関連しています"
            assert ex._evaluate_rag_relevance(
                "q", "out", rag_max_score=0.72) is True


class TestExecutorFallback:
    """フォールバック機能のテスト"""

    def test_fallback_on_failure(self):
        """失敗時のフォールバック"""
        # RAG検索が失敗し、推論にフォールバック
        registry = MagicMock(spec=ToolRegistry)

        rag_tool = MagicMock()
        rag_tool.execute.side_effect = Exception("Search failed")

        reasoning_tool = MagicMock()
        reasoning_tool.execute.return_value = ToolResult(
            success=True,
            output="フォールバック回答",
            confidence_factors={}
        )

        def get_tool(name):
            if name == "rag_search":
                return rag_tool
            elif name == "reasoning":
                return reasoning_tool
            return None

        registry.get.side_effect = get_tool

        plan = ExecutionPlan(
            original_query="テスト",
            complexity=0.5,
            estimated_steps=1,
            requires_confirmation=False,
            steps=[
                PlanStep(
                    step_id=1,
                    action="rag_search",
                    description="検索",
                    expected_output="結果",
                    fallback="reasoning"
                )
            ],
            success_criteria="テスト",
            plan_id="test123"
        )

        executor = Executor(tool_registry=registry)
        _result = executor.execute_plan(plan)

        # フォールバックが実行された
        assert reasoning_tool.execute.called


class TestCreateExecutor:
    """create_executor関数のテスト"""

    def test_create_executor_default(self):
        """デフォルト設定でのExecutor作成"""
        with patch("grace.executor.create_tool_registry") as mock_registry:
            mock_registry.return_value = MagicMock()
            executor = create_executor()

            assert isinstance(executor, Executor)

    def test_create_executor_custom_registry(self):
        """カスタムレジストリでのExecutor作成"""
        custom_registry = MagicMock(spec=ToolRegistry)
        executor = create_executor(tool_registry=custom_registry)

        assert executor.tool_registry is custom_registry