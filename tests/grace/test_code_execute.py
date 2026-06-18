"""
GRACE P2 CodeExecuteTool Tests（Ollama 構成）

grace/tools.py の CodeExecuteTool（サブプロセス分離＋AST 静的検査＋resource 制限）を
検証する。LLM 非依存。実プロセス実行を伴うため POSIX 前提（CI=ubuntu）。
"""

import sys

import pytest

from grace.config import GraceConfig, reset_config
from grace.tools import CodeExecuteTool, ToolRegistry


@pytest.fixture(autouse=True)
def _reset():
    reset_config()
    yield
    reset_config()


def _tool(timeout=5):
    cfg = GraceConfig()
    cfg.code_execute.timeout_seconds = timeout
    return CodeExecuteTool(config=cfg)


class TestStaticCheck:
    def test_denied_import_rejected(self):
        r = _tool().execute(code="import socket")
        assert r.success is False
        assert "禁止された import" in r.error
        assert r.confidence_factors.get("rejected") is True

    def test_denied_from_import_rejected(self):
        r = _tool().execute(code="from subprocess import run")
        assert r.success is False
        assert "禁止された import" in r.error

    def test_dangerous_attribute_rejected(self):
        r = _tool().execute(code="import os\nos.system('echo hi')")
        assert r.success is False
        # import os は許可だが .system 属性アクセスで拒否
        assert "禁止された属性アクセス" in r.error

    def test_eval_call_rejected(self):
        r = _tool().execute(code="eval('1+1')")
        assert r.success is False
        assert "禁止された関数呼び出し" in r.error

    def test_syntax_error_rejected(self):
        r = _tool().execute(code="def (:")
        assert r.success is False
        assert "SyntaxError" in r.error


class TestExecute:
    def test_simple_print(self):
        r = _tool().execute(code="print(2 + 3)")
        assert r.success is True
        assert r.output.strip() == "5"
        assert r.execution_time_ms is not None

    def test_query_alias_accepted(self):
        # code 未指定でも query をコードとして受け付ける
        r = _tool().execute(query="print('ok')")
        assert r.success is True
        assert "ok" in r.output

    def test_empty_code_error(self):
        r = _tool().execute(code="   ")
        assert r.success is False
        assert "指定されていません" in r.error

    def test_non_string_error(self):
        r = _tool().execute(code=123)
        assert r.success is False

    def test_runtime_error_reports_stderr(self):
        r = _tool().execute(code="raise ValueError('boom')")
        assert r.success is False
        assert "ValueError" in (r.output or "") or "ValueError" in (r.error or "")

    def test_output_truncated(self):
        tool = _tool()
        tool.cfg.max_output_chars = 50
        r = tool.execute(code="print('x' * 1000)")
        assert r.success is True
        assert len(r.output) <= 50

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX resource 制限前提")
    def test_infinite_loop_is_killed(self):
        # RLIMIT_CPU / 実時間タイムアウトで停止する（成功しない）
        r = _tool(timeout=1).execute(code="while True:\n    pass")
        assert r.success is False


class TestRegistration:
    def test_not_registered_by_default(self):
        reg = ToolRegistry()
        assert reg.get("code_execute") is None

    def test_registered_when_enabled(self):
        cfg = GraceConfig()
        cfg.tools.enabled = ["rag_search", "reasoning", "code_execute"]
        reg = ToolRegistry(config=cfg)
        assert isinstance(reg.get("code_execute"), CodeExecuteTool)
