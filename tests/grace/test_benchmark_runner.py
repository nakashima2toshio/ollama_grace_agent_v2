"""BenchmarkRunner の設定配線テスト（高速化フラグ）。

実 Ollama/Qdrant を起動せずに、--model / --lite-eval 相当の設定が
正しく BenchmarkRunner・config に反映されるかだけを検証する軽量ユニットテスト。
"""

from grace.benchmark import BenchmarkRunner
from grace.config import get_config, reset_config


class TestBenchmarkRunnerConfigWiring:
    def setup_method(self):
        reset_config()

    def test_model_override_propagates_to_config(self):
        """--model 相当の model_name 上書きが config.llm.model に反映される。"""
        runner = BenchmarkRunner(model_name="llama3.2:3b")
        assert runner.model_name == "llama3.2:3b"
        # 全コンポーネントが参照する config.llm.model にも反映される
        assert runner.config.llm.model == "llama3.2:3b"

    def test_default_model_keeps_config(self):
        """model_name 未指定なら config の既定モデルを使う。"""
        runner = BenchmarkRunner()
        assert runner.model_name == runner.config.llm.model

    def test_enable_judge_false_disables_judge(self):
        """--lite-eval 相当（enable_judge=False）で LLM-as-judge を無効化する。"""
        runner = BenchmarkRunner(enable_judge=False)
        assert runner.judge is None

    def test_enable_judge_true_creates_judge(self):
        runner = BenchmarkRunner(enable_judge=True)
        assert runner.judge is not None

    def test_lite_eval_disables_groundedness(self):
        """--lite-eval 相当: groundedness 検証（最も遅い）を無効化できる。"""
        cfg = get_config()
        cfg.confidence.groundedness_enabled = False
        runner = BenchmarkRunner(config=cfg, enable_judge=False)
        assert runner.config.confidence.groundedness_enabled is False
        assert runner.judge is None
