"""
GRACE Benchmark Logger

GRACEエージェントの各フェーズ（Plan / Execute / Confidence /
Intervention / Replan）の性能指標を計測・記録・CSV出力するモジュール。

使用例::

    from grace.benchmark import BenchmarkRunner, BENCHMARK_QUERIES

    runner = BenchmarkRunner()          # config.llm.model / provider を自動取得
    session = runner.run(
        query_id="Q01",
        query_text="cc_newsから最近のAIニュースを3件教えて",
        level="Easy",
        category="事実検索",
    )

    # Qdrantコレクションを明示指定して全クエリセットを３回ずつ実行
    runner = BenchmarkRunner(qdrant_collection="cc_news_100_ollama")
    sessions = runner.run_query_set(runs_per_query=3)
"""

from __future__ import annotations

import csv
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BENCHMARK_LOG_DIR = Path("logs")
BENCHMARK_CSV_PATH = BENCHMARK_LOG_DIR / "benchmark_results.csv"

CSV_HEADERS: List[str] = [
    "timestamp", "session_id", "query_id", "query_text_short",
    "level", "category", "model", "provider", "run_number",
    "plan_time_sec", "plan_complexity", "plan_steps", "requires_confirmation",
    "execute_time_sec", "total_time_sec",
    "tool_calls", "rag_step_count", "sources_total",
    "overall_confidence", "min_step_confidence", "max_step_confidence",
    "intervention_level",
    "replan_count", "overall_status",
    "input_tokens", "output_tokens", "cost_usd",
    "accuracy_score", "completeness_score",
]

BENCHMARK_QUERIES: List[Dict[str, str]] = [
    {"id": "Q01", "level": "Easy",   "category": "事実検索",
     "text": "cc_newsコレクションにある最近のAI関連ニュースを3件教えてください"},
    {"id": "Q02", "level": "Easy",   "category": "事実検索",
     "text": "最近最も報道されたスポーツイベントは何ですか？"},
    {"id": "Q03", "level": "Medium", "category": "推論・比較",
     "text": "最近２年間の気候変動に関するニュースから主要トレンドを比較してまとめてください"},
    {"id": "Q04", "level": "Medium", "category": "推論・比較",
     "text": "テクノロジー企業の人員削減ニュースを複数比較して、業界全体の傾向を分析してください"},
    {"id": "Q05", "level": "Hard",   "category": "推論・比較",
     "text": "エネルギー問題とインフレの関係を、複数のニュース記事から根拠を挙げて説明してください"},
    {"id": "Q06", "level": "Hard",   "category": "推論・比較",
     "text": "地政学的リスクが特定の産業に与えた影響を直近数年で追って分析してください"},
    {"id": "Q07", "level": "Easy",   "category": "手順説明",
     "text": "AIの倫理問題について、ニュースで報道された主な事例を時系列で教えてください"},
    {"id": "Q08", "level": "Medium", "category": "手順説明",
     "text": "医療AI分野のここ２年のニュースをカテゴリ別に整理してください"},
    {"id": "Q09", "level": "Easy",   "category": "曖昧",
     "text": "最近の重要なニュースを教えて"},
    {"id": "Q10", "level": "Easy",   "category": "曖昧",
     "text": "最近話題になっている技術トレンドを簡単に教えてください"},
    {"id": "Q11", "level": "Hard",   "category": "推論・比較",
     "text": "cc_newsに存在しないトピックを検索して、リプランが発生する過程を示してください"},
    {"id": "Q12", "level": "Hard",   "category": "推論・比較",
     "text": "５つ以上の異なるニュースソースの情報を統合して、最近の総括レポートを作成してください"},
]

# クエリごとの期待キーワード・採点基準（LLM-as-judge 用）
# "keywords": 回答に含まれるべき概念（いずれか複数が含まれれば OK）
# "no_answer_ok": True の場合、RAG ヒットなし＝適切な「情報なし」応答も正解とみなす
BENCHMARK_EXPECTED: Dict[str, Dict[str, Any]] = {
    "Q01": {
        "keywords": ["AI", "人工知能", "機械学習", "ChatGPT", "LLM", "生成AI", "ニュース"],
        "criteria": "AI関連ニュースを3件以上列挙し、各件の概要が述べられていること",
        "no_answer_ok": False,
    },
    "Q02": {
        "keywords": ["スポーツ", "オリンピック", "サッカー", "野球", "テニス", "試合", "選手権", "リーグ"],
        "criteria": "具体的なスポーツイベント名が1件以上含まれていること",
        "no_answer_ok": True,
    },
    "Q03": {
        "keywords": ["気候変動", "温暖化", "CO2", "排出", "再生可能", "エネルギー", "環境", "COP"],
        "criteria": "気候変動に関する複数のトレンドが比較・列挙されていること",
        "no_answer_ok": True,
    },
    "Q04": {
        "keywords": ["人員削減", "レイオフ", "解雇", "リストラ", "テック", "IT企業", "従業員"],
        "criteria": "複数企業または傾向が比較分析されていること",
        "no_answer_ok": True,
    },
    "Q05": {
        "keywords": ["エネルギー", "インフレ", "物価", "原油", "電力", "コスト", "経済"],
        "criteria": "エネルギーとインフレの関係が根拠付きで説明されていること",
        "no_answer_ok": True,
    },
    "Q06": {
        "keywords": ["地政学", "リスク", "産業", "影響", "制裁", "貿易", "紛争", "サプライチェーン"],
        "criteria": "地政学リスクが特定産業に与えた影響が分析されていること",
        "no_answer_ok": True,
    },
    "Q07": {
        "keywords": ["AI", "倫理", "バイアス", "差別", "プライバシー", "規制", "事例"],
        "criteria": "AI倫理に関する事例が時系列または複数件示されていること",
        "no_answer_ok": True,
    },
    "Q08": {
        "keywords": ["医療", "AI", "診断", "画像認識", "創薬", "病院", "治療"],
        "criteria": "医療AI分野のニュースが複数カテゴリに整理されていること",
        "no_answer_ok": True,
    },
    "Q09": {
        "keywords": ["ニュース", "最近", "話題", "出来事", "報道"],
        "criteria": "何らかのニュース・出来事が1件以上回答されていること",
        "no_answer_ok": False,
    },
    "Q10": {
        "keywords": ["技術", "トレンド", "AI", "クラウド", "量子", "ロボット", "半導体", "IoT"],
        "criteria": "技術トレンドが1件以上具体的に説明されていること",
        "no_answer_ok": False,
    },
    "Q11": {
        "keywords": ["見つかりません", "情報なし", "存在しない", "ヒットしない", "リプラン", "再検索", "該当なし"],
        "criteria": "存在しないトピックに対して適切に「情報なし」または再計画を報告していること",
        "no_answer_ok": True,
    },
    "Q12": {
        "keywords": ["ニュース", "ソース", "統合", "レポート", "まとめ", "分析"],
        "criteria": "複数のニュースソースから情報を統合した総括レポートが生成されていること",
        "no_answer_ok": True,
    },
}


@dataclass
class BenchmarkSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    query_id: str = ""
    query_text: str = ""
    level: str = ""
    category: str = ""
    model: str = ""
    provider: str = ""
    run_number: int = 1
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    plan_start: float = 0.0
    plan_end: float = 0.0
    execute_start: float = 0.0
    execute_end: float = 0.0
    plan_complexity: float = 0.0
    plan_steps: int = 0
    requires_confirmation: bool = False
    plan_id: str = ""
    tool_calls: int = 0
    rag_step_count: int = 0
    sources_total: int = 0
    step_confidences: List[float] = field(default_factory=list)
    overall_confidence: float = 0.0
    intervention_level: str = ""
    replan_count: int = 0
    overall_status: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    accuracy_score: Optional[float] = None
    completeness_score: Optional[float] = None

    @property
    def plan_time_sec(self) -> float:
        if self.plan_end > 0 and self.plan_start > 0:
            return round(self.plan_end - self.plan_start, 3)
        return 0.0

    @property
    def execute_time_sec(self) -> float:
        if self.execute_end > 0 and self.execute_start > 0:
            return round(self.execute_end - self.execute_start, 3)
        return 0.0

    @property
    def total_time_sec(self) -> float:
        start = self.plan_start if self.plan_start > 0 else self.execute_start
        end   = self.execute_end if self.execute_end > 0 else self.plan_end
        if start > 0 and end > 0:
            return round(end - start, 3)
        return round(self.plan_time_sec + self.execute_time_sec, 3)

    @property
    def min_step_confidence(self) -> float:
        return round(min(self.step_confidences), 3) if self.step_confidences else 0.0

    @property
    def max_step_confidence(self) -> float:
        return round(max(self.step_confidences), 3) if self.step_confidences else 0.0

    def to_csv_row(self) -> Dict[str, Any]:
        return {
            "timestamp":           self.timestamp,
            "session_id":          self.session_id,
            "query_id":            self.query_id,
            "query_text_short":    self.query_text[:50].replace("\n", " "),
            "level":               self.level,
            "category":            self.category,
            "model":               self.model,
            "provider":            self.provider,
            "run_number":          self.run_number,
            "plan_time_sec":       self.plan_time_sec,
            "plan_complexity":     round(self.plan_complexity, 3),
            "plan_steps":          self.plan_steps,
            "requires_confirmation": self.requires_confirmation,
            "execute_time_sec":    self.execute_time_sec,
            "total_time_sec":      self.total_time_sec,
            "tool_calls":          self.tool_calls,
            "rag_step_count":      self.rag_step_count,
            "sources_total":       self.sources_total,
            "overall_confidence":  round(self.overall_confidence, 3),
            "min_step_confidence": self.min_step_confidence,
            "max_step_confidence": self.max_step_confidence,
            "intervention_level":  self.intervention_level,
            "replan_count":        self.replan_count,
            "overall_status":      self.overall_status,
            "input_tokens":        self.input_tokens,
            "output_tokens":       self.output_tokens,
            "cost_usd":            round(self.cost_usd, 6),
            "accuracy_score":      self.accuracy_score,
            "completeness_score":  self.completeness_score,
        }


class BenchmarkLogger:
    _THRESH_SILENT:  float = 0.9
    _THRESH_NOTIFY:  float = 0.7
    _THRESH_CONFIRM: float = 0.4

    def __init__(self, csv_path: Optional[Path] = None) -> None:
        self.csv_path = csv_path or BENCHMARK_CSV_PATH
        BENCHMARK_LOG_DIR.mkdir(exist_ok=True)
        self._ensure_csv_headers()

    def _ensure_csv_headers(self) -> None:
        if not self.csv_path.exists():
            with open(self.csv_path, "w", newline="", encoding="utf-8") as fh:
                csv.DictWriter(fh, fieldnames=CSV_HEADERS).writeheader()

    def record_plan_result(self, session: BenchmarkSession, plan: Any) -> None:
        session.plan_complexity       = getattr(plan, "complexity", 0.0)
        session.plan_steps            = len(getattr(plan, "steps", []))
        session.requires_confirmation = getattr(plan, "requires_confirmation", False)
        session.plan_id               = getattr(plan, "plan_id", "") or ""

    def record_execution_result(self, session: BenchmarkSession, result: Any) -> None:
        session.overall_confidence = getattr(result, "overall_confidence", 0.0)
        session.replan_count       = getattr(result, "replan_count", 0)
        session.overall_status     = getattr(result, "overall_status", "")
        exec_ms = getattr(result, "total_execution_time_ms", None)
        if exec_ms and session.execute_time_sec == 0.0:
            session.execute_end = session.execute_start + exec_ms / 1000.0
        tu = getattr(result, "total_token_usage", None) or {}
        if isinstance(tu, dict):
            session.input_tokens  = tu.get("input_tokens")  or tu.get("prompt_tokens")    or 0
            session.output_tokens = tu.get("output_tokens") or tu.get("completion_tokens") or 0
        cost = getattr(result, "total_cost_usd", None)
        if cost is not None:
            session.cost_usd = float(cost)
        for step_result in getattr(result, "step_results", []):
            session.tool_calls += 1
            conf = getattr(step_result, "confidence", 0.0)
            session.step_confidences.append(conf)
            sources = getattr(step_result, "sources", []) or []
            if sources:
                session.rag_step_count += 1
                session.sources_total  += len(sources)
        session.intervention_level = self._score_to_intervention(session.overall_confidence)

    def _score_to_intervention(self, score: float) -> str:
        if score >= self._THRESH_SILENT:
            return "SILENT"
        if score >= self._THRESH_NOTIFY:
            return "NOTIFY"
        if score >= self._THRESH_CONFIRM:
            return "CONFIRM"
        return "ESCALATE"

    def finalize_and_log(self, session: BenchmarkSession) -> None:
        sep = "=" * 60
        lines = [
            f"\n[BENCHMARK] {sep}",
            f"[BENCHMARK] Query: {session.query_id} | {session.level} | {session.category}",
            f"[BENCHMARK] Model: {session.model} ({session.provider}) Run#{session.run_number}",
            f"[BENCHMARK] Plan={session.plan_time_sec:.2f}s Exec={session.execute_time_sec:.2f}s Total={session.total_time_sec:.2f}s",
            f"[BENCHMARK] Conf={session.overall_confidence:.3f} IV={session.intervention_level} Replan={session.replan_count}",
            f"[BENCHMARK] {sep}\n",
        ]
        log_text = "\n".join(lines)
        logger.info(log_text)
        print(log_text)

    def save_to_csv(self, session: BenchmarkSession) -> None:
        with open(self.csv_path, "a", newline="", encoding="utf-8") as fh:
            csv.DictWriter(fh, fieldnames=CSV_HEADERS).writerow(session.to_csv_row())
        logger.info("[BENCHMARK] CSV appended: %s", self.csv_path)


class LLMJudge:
    """LLM-as-judge: エージェント回答の accuracy / completeness を自動採点する。

    Ollama の chat API を直接呼び出し、0.0〜1.0 のスコアを返す。
    LLM 呼び出しに失敗した場合はキーワード一致率でフォールバック採点する。
    """

    JUDGE_PROMPT = """\
あなたは厳格な採点者です。以下の情報をもとに回答を評価してください。

【質問】
{query}

【採点基準】
{criteria}

【期待キーワード（いくつか含まれていれば十分）】
{keywords}

【エージェントの回答】
{answer}

以下のJSON形式のみで回答してください。説明文は不要です。
{{"accuracy": <0.0〜1.0>, "completeness": <0.0〜1.0>, "reason": "<20字以内>"}}

採点基準:
- accuracy: 事実の正確さ・質問への適切な回答になっているか
- completeness: 期待キーワードや要求項目を網羅しているか
- no_answer_ok={no_answer_ok} の場合、「情報が見つかりません」等の回答も completeness=1.0 とする
"""

    def __init__(self, model: str = "gemma4:e4b", base_url: str = "http://localhost:11434") -> None:
        self.model    = model
        self.base_url = base_url.rstrip("/")

    def score(
        self,
        query_id: str,
        query_text: str,
        answer: str,
        expected: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, float]:
        """accuracy_score, completeness_score を返す（0.0〜1.0）。"""
        if not answer or not expected:
            return self._keyword_fallback(answer or "", expected)

        prompt = self.JUDGE_PROMPT.format(
            query=query_text,
            criteria=expected.get("criteria", ""),
            keywords="、".join(expected.get("keywords", [])),
            answer=answer[:2000],
            no_answer_ok=expected.get("no_answer_ok", False),
        )
        try:
            import urllib.request
            payload = json.dumps({
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 100},
            }).encode()
            req = urllib.request.Request(
                f"{self.base_url}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
            content = body.get("message", {}).get("content", "")
            return self._parse_scores(content)
        except Exception as exc:
            logger.warning("[JUDGE] LLM call failed (%s), falling back to keyword match", exc)
            return self._keyword_fallback(answer, expected)

    @staticmethod
    def _parse_scores(content: str) -> Tuple[float, float]:
        m = re.search(r'\{[^}]*"accuracy"\s*:\s*([\d.]+)[^}]*"completeness"\s*:\s*([\d.]+)', content)
        if not m:
            m = re.search(r'"completeness"\s*:\s*([\d.]+)[^}]*"accuracy"\s*:\s*([\d.]+)', content)
            if m:
                return round(min(1.0, float(m.group(2))), 3), round(min(1.0, float(m.group(1))), 3)
            logger.warning("[JUDGE] Cannot parse scores from: %s", content[:200])
            return 0.5, 0.5
        return round(min(1.0, float(m.group(1))), 3), round(min(1.0, float(m.group(2))), 3)

    @staticmethod
    def _keyword_fallback(answer: str, expected: Optional[Dict[str, Any]]) -> Tuple[float, float]:
        if not expected or not answer:
            return 0.0, 0.0
        keywords = expected.get("keywords", [])
        if not keywords:
            return 0.5, 0.5
        hit = sum(1 for kw in keywords if kw in answer)
        ratio = round(hit / len(keywords), 3)
        # 「情報なし」系の回答を no_answer_ok クエリで正解とみなす
        no_answer_phrases = ["見つかりません", "情報なし", "存在しない", "ヒットしない", "該当なし"]
        if expected.get("no_answer_ok") and any(p in answer for p in no_answer_phrases):
            return 1.0, 1.0
        return ratio, ratio


class BenchmarkRunner:
    DEFAULT_MODEL = "gemma4:e4b"

    def __init__(
        self,
        model_name: Optional[str] = None,
        provider: Optional[str]   = None,
        config: Any               = None,
        csv_path: Optional[Path]  = None,
        qdrant_collection: Optional[str] = None,
        enable_judge: bool = True,
        judge_model: Optional[str] = None,
    ) -> None:
        from .config import get_config as _get_config
        self.config     = config or _get_config()
        self.model_name = model_name or self.DEFAULT_MODEL
        self.provider   = provider   or self.config.llm.provider
        self.bm_logger  = BenchmarkLogger(csv_path=csv_path)
        if qdrant_collection:
            self.config.qdrant.collection_name = qdrant_collection
        self.judge: Optional[LLMJudge] = (
            LLMJudge(model=judge_model or self.model_name) if enable_judge else None
        )

    def run(
        self,
        query_id: str,
        query_text: str,
        run_number: int = 1,
        level: str = "",
        category: str = "",
    ) -> BenchmarkSession:
        from .executor import Executor
        from .planner import Planner
        session = BenchmarkSession(
            query_id=query_id, query_text=query_text,
            model=self.model_name, provider=self.provider,
            run_number=run_number, level=level, category=category,
        )
        final_answer: str = ""
        try:
            try:
                planner = Planner(config=self.config, model_name=self.model_name)
            except TypeError:
                planner = Planner(config=self.config)
            session.plan_start = time.monotonic()
            plan = planner.create_plan(query_text)
            session.plan_end   = time.monotonic()
            self.bm_logger.record_plan_result(session, plan)
            try:
                executor = Executor(config=self.config, model_name=self.model_name)
            except TypeError:
                executor = Executor(config=self.config)
            session.execute_start = time.monotonic()
            result = self._call_execute(executor, plan)
            session.execute_end   = time.monotonic()
            self.bm_logger.record_execution_result(session, result)
            # 最終回答テキストを取り出す（各 Executor の返り値形式に対応）
            for attr in ("final_answer", "answer", "response", "result"):
                val = getattr(result, attr, None)
                if val and isinstance(val, str):
                    final_answer = val
                    break
        except Exception as exc:
            logger.error("[BENCHMARK] %s run%d failed: %s", query_id, run_number, exc, exc_info=True)
            session.overall_status = "failed"
            now = time.monotonic()
            if session.plan_end == 0.0:
                session.plan_end = now
            if session.execute_end == 0.0:
                session.execute_end = now
        finally:
            # LLM-as-judge による accuracy / completeness 採点
            if self.judge and session.overall_status != "failed":
                expected = BENCHMARK_EXPECTED.get(query_id)
                try:
                    acc, comp = self.judge.score(
                        query_id=query_id,
                        query_text=query_text,
                        answer=final_answer,
                        expected=expected,
                    )
                    session.accuracy_score    = acc
                    session.completeness_score = comp
                    logger.info("[JUDGE] %s -> accuracy=%.3f completeness=%.3f", query_id, acc, comp)
                except Exception as judge_exc:
                    logger.warning("[JUDGE] Scoring failed for %s: %s", query_id, judge_exc)
            self.bm_logger.finalize_and_log(session)
            self.bm_logger.save_to_csv(session)
        return session

    @staticmethod
    def _call_execute(executor: Any, plan: Any) -> Any:
        import types
        if hasattr(executor, 'execute'):
            result = executor.execute(plan)
        elif hasattr(executor, 'execute_plan_generator'):
            result = executor.execute_plan_generator(plan)
        else:
            result = executor.execute_plan(plan)
        if isinstance(result, types.GeneratorType):
            last, ret = None, None
            try:
                while True:
                    last = next(result)
            except StopIteration as e:
                ret = e.value
            return ret if ret is not None else last
        return result

    def run_query_set(
        self,
        queries: Optional[List[Dict[str, str]]] = None,
        runs_per_query: int = 3,
    ) -> List[BenchmarkSession]:
        queries = queries or BENCHMARK_QUERIES
        sessions: List[BenchmarkSession] = []
        total = len(queries) * runs_per_query
        done  = 0
        for query in queries:
            for run in range(1, runs_per_query + 1):
                done += 1
                logger.info("[BENCHMARK] Progress %d/%d | %s Run %d/%d", done, total, query["id"], run, runs_per_query)
                session = self.run(
                    query_id=query["id"], query_text=query["text"],
                    run_number=run, level=query.get("level", ""), category=query.get("category", ""),
                )
                sessions.append(session)
        logger.info("[BENCHMARK] All done: %d sessions. CSV => %s", done, self.bm_logger.csv_path)
        return sessions


__all__ = [
    "BENCHMARK_QUERIES", "BENCHMARK_EXPECTED", "CSV_HEADERS", "BENCHMARK_CSV_PATH",
    "BenchmarkSession", "BenchmarkLogger", "LLMJudge", "BenchmarkRunner",
]
