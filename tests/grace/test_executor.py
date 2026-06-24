"""
GRACE Executor Tests
Executorのテスト
"""

from types import SimpleNamespace
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


class TestBlendRouteBounds:
    """S2: 検索ハンドリング連動のフロア/天井（_blend_groundedness_confidence）。"""

    def setup_method(self):
        reset_config()

    @pytest.fixture
    def mock_tool_registry(self):
        return MagicMock(spec=ToolRegistry)

    def _stub_gres(self, executor, *, verified, support_rate=0.0,
                   supported=0, contradicted=0, total=0):
        gres = SimpleNamespace(
            verified=verified, support_rate=support_rate,
            supported=supported, contradicted=contradicted, total=total,
            has_contradiction=contradicted > 0, reason="stub",
        )
        executor.groundedness_verifier = MagicMock()
        executor.groundedness_verifier.verify.return_value = gres

    def test_floor_lifts_clear_grounded_hit(self, mock_tool_registry):
        """Fix1: 高スコア命中＋網羅十分なら NOTIFY フロア(0.7)まで底上げ。"""
        executor = Executor(tool_registry=mock_tool_registry)
        # 接地はされているが support_rate が低めで希釈され、素のブレンドは低い
        self._stub_gres(executor, verified=True, support_rate=0.3,
                        supported=1, contradicted=0, total=1)
        conf = executor._blend_groundedness_confidence(
            query="Amazonの新規雇用は何件？",
            final_answer="5,000人の在宅カスタマーサービス職です。",
            self_eval=0.4, coverage=0.6, aggregated=0.5,
            sources=["src"], search_max_score=0.81,
        )
        assert conf >= executor.config.confidence.rag_hit_floor  # 0.7

    def test_ceiling_caps_low_coverage_overconfidence(self, mock_tool_registry):
        """Fix2: 網羅不足なのに自己評価だけ高い回答は天井(0.5)で抑制。"""
        executor = Executor(tool_registry=mock_tool_registry)
        # groundedness は判定不能（neutral）→ self_eval が支配しがちなフォールバック経路
        self._stub_gres(executor, verified=False)
        conf = executor._blend_groundedness_confidence(
            query="あの件について詳しく教えて",  # 曖昧
            final_answer="安全運転の注意点は…",   # クエリに答えていない
            self_eval=0.9, coverage=0.2, aggregated=0.72,
            sources=["src"], search_max_score=0.72,
        )
        assert conf <= executor.config.confidence.low_coverage_ceiling  # 0.5

    def test_no_bounds_leaves_value_untouched(self, mock_tool_registry):
        """中間ケース（網羅十分・明確なヒットではない）はフロア/天井とも非適用。"""
        executor = Executor(tool_registry=mock_tool_registry)
        self._stub_gres(executor, verified=True, support_rate=0.7,
                        supported=2, contradicted=0, total=2)
        conf = executor._blend_groundedness_confidence(
            query="49ersのGM人事を比較して",
            final_answer="バラードとセサリオが候補です。",
            self_eval=0.7, coverage=0.7, aggregated=0.7,
            sources=["src"], search_max_score=0.70,  # フロア閾値0.75未満
        )
        # 天井（coverage>=0.5）にもフロア（score<0.75）にも該当しない
        assert 0.5 < conf < 0.9


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