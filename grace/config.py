"""
GRACE Config - 設定管理

YAMLファイルと環境変数からの設定読み込み
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field

# =============================================================================
# Logging Configuration
# =============================================================================

def init_grace_logging():
    """GRACEパッケージ用のロギングを初期化"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    log_file = log_dir / "grace_run.log"

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    else:
        grace_logger = logging.getLogger("grace")
        if not any(isinstance(h, logging.FileHandler) for h in grace_logger.handlers):
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
            grace_logger.addHandler(fh)
            grace_logger.setLevel(logging.INFO)


init_grace_logging()

logger = logging.getLogger(__name__)


# =============================================================================
# 設定モデル定義
# =============================================================================

class LLMConfig(BaseModel):
    """LLM設定（Ollama ローカルLLM）"""
    # 既定は Ollama のローカルLLM。モデルは gemma4:e4b（代替: llama3.2）
    provider: str = "ollama"
    model: str = "gemma4:e4b"
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 30


class EmbeddingConfig(BaseModel):
    """Embedding設定（Ollama ローカル Embedding）"""
    # 既定は Ollama の bge-m3（多言語・日本語対応 / 1024次元）。
    # ※次元を変更した場合は Qdrant コレクションの再作成が必要。
    provider: str = "ollama"
    model: str = "bge-m3"
    dimensions: int = 1024


class ConfidenceWeights(BaseModel):
    """Confidence重み設定"""
    search_quality: float = 0.25
    source_agreement: float = 0.20
    llm_self_eval: float = 0.25
    tool_success: float = 0.15
    query_coverage: float = 0.15


class ConfidenceThresholds(BaseModel):
    """Confidence閾値設定"""
    silent: float = 0.9
    notify: float = 0.7
    confirm: float = 0.4


class ConfidenceConfig(BaseModel):
    """Confidence計算設定"""
    weights: ConfidenceWeights = Field(default_factory=ConfidenceWeights)
    thresholds: ConfidenceThresholds = Field(default_factory=ConfidenceThresholds)

    # S1: 根拠妥当性（groundedness）を最終 confidence の主成分にする設定
    groundedness_enabled: bool = True   # 最終回答の支持率検証を有効化
    groundedness_weight: float = 0.6    # 支持率（主成分）の重み
    self_eval_weight: float = 0.25      # 自己評価（従）の重み
    coverage_weight: float = 0.15       # 網羅度（従）の重み
    search_aux_weight: float = 0.2      # 検索ベース集約値（補助）の重み
    # S1: confidence 較正（温度スケーリング）パラメータの保存先
    calibration_path: str = "config/calibration.json"


class InterventionConfig(BaseModel):
    """介入設定"""
    default_timeout: int = 300
    auto_proceed_on_timeout: bool = False
    max_clarification_rounds: int = 3


class ReplanConfig(BaseModel):
    """リプラン設定"""
    max_replans: int = 3
    confidence_threshold: float = 0.4
    partial_replan_threshold: float = 0.6
    cooldown_seconds: int = 5


class CostConfig(BaseModel):
    """コスト管理設定"""
    daily_limit_usd: float = 10.0
    hourly_limit_usd: float = 2.0
    per_query_limit_usd: float = 0.50
    warning_threshold: float = 0.8


class ErrorConfig(BaseModel):
    """エラーハンドリング設定"""
    max_retries: int = 3
    retry_delay_base: float = 1.0
    retry_delay_max: float = 30.0
    exponential_backoff: bool = True


class LoggingConfig(BaseModel):
    """ログ設定"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: str = "logs/grace.log"
    max_size_mb: int = 100
    backup_count: int = 5


class QdrantConfig(BaseModel):
    """Qdrant設定"""
    url: str = "http://localhost:6333"
    collection_name: str = "customer_support_faq"
    search_limit: int = 5
    score_threshold: float = 0.35
    rag_sufficient_score: float = 0.7
    # True の場合、RAG検索を collection_name（または明示指定コレクション）の
    # 1コレクションのみに限定し、全コレクション横断のフォールバックを行わない。
    # ベンチマーク等でアクセス回数を最小化したい場合に使用する。
    restrict_to_collection: bool = False
    search_priority: list = Field(default_factory=lambda: ["wikipedia_ja", "livedoor", "cc_news", "japanese_text"])


class WebSearchConfig(BaseModel):
    """Web検索設定"""
    backend: str = "serpapi"
    num_results: int = 5
    language: str = "ja"
    timeout: int = 30
    google_cse_api_key: str = ""
    google_cse_engine_id: str = ""
    serpapi_api_key: str = ""


class ToolsConfig(BaseModel):
    """ツール設定"""
    enabled: list = Field(default_factory=lambda: ["rag_search", "web_search", "reasoning", "ask_user"])
    disabled: list = Field(default_factory=list, description="プロジェクト全体で恒久的に禁止するツールのリスト")


class CodeExecuteConfig(BaseModel):
    """code_execute（サンドボックス Python 実行・P2）設定。

    セキュリティ上、既定では tools.enabled に含めず opt-in とする。
    実体はサブプロセス分離＋resource 制限＋isolated mode による best-effort サンドボックス。
    真の隔離が必要な場合はコンテナ/gVisor 等の外部境界を併用すること。
    """
    timeout_seconds: int = 5          # CPU/実時間のタイムアウト
    max_memory_mb: int = 256          # アドレス空間上限（RLIMIT_AS）
    max_output_chars: int = 10000     # 標準出力の最大文字数（超過分は切り詰め）
    # AST レベルで import を禁止するモジュール（防御の多層化）
    denied_imports: list = Field(default_factory=lambda: [
        "subprocess", "socket", "ctypes", "multiprocessing",
        "urllib", "requests", "http", "ftplib", "shutil", "asyncio",
    ])


class PlannerConfig(BaseModel):
    """Planner設定（二層計画生成）"""
    # この複雑度（ヒューリスティック推定）未満の質問は
    # ルールベース計画（LLM呼び出しなし）で即時に計画を生成する
    llm_plan_complexity_threshold: float = 0.7
    # True の場合、複雑度に関わらず常に LLM 計画生成を使用する
    force_llm_plan: bool = False


class ExecutorConfig(BaseModel):
    """Executor設定"""
    # 検索結果が不十分な場合に動的挿入するフォールバックアクションの連鎖
    # （PlanStep.fallback が指定されていない場合のデフォルト）
    fallback_chain: Dict[str, str] = Field(default_factory=lambda: {
        "rag_search": "web_search",
        "web_search": "ask_user",
    })
    # 依存関係のない検索ステップを並列実行する
    parallel_search: bool = True
    max_parallel_steps: int = 4

    # reasoning ステップのタイムアウト下限（秒）。ローカルLLM（gemma4:e4b 等）は
    # 回答生成に時間がかかり、計画側の timeout_seconds=30 では毎回タイムアウト→
    # 不要な replan / partial を誘発する。reasoning に限りこの値まで引き上げる
    # （0 以下で無効化）。
    reasoning_timeout_seconds: int = 120

    # S3: ハイブリッド ReAct ループ
    # react_enabled は既定 False（静的 Plan-Execute を温存）。有効化すると
    # complexity >= react_complexity_threshold の計画を観測駆動 ReAct で実行する。
    react_enabled: bool = False
    react_complexity_threshold: float = 0.7  # この複雑度以上のみ ReAct（未満は静的パス）
    react_max_iterations: int = 8            # ReAct ループの最大反復回数


class OllamaConfig(BaseModel):
    """Ollama 設定（ローカルLLM・OpenAI 互換エンドポイント）"""
    base_url: str = "http://localhost:11434/v1"
    llm_model: str = "gemma4:e4b"
    available_models: list = Field(default_factory=lambda: [
        "gemma4:e4b",                 # デフォルト推奨
        "gemma4:26b-a4b-it-q4_K_M",  # Gemma 4 26B 量子化版（高性能）
        "llama3.2",                   # ローカル・高速
        "llama3.2:3b",                # 軽量版
        "llama3.1",                   # 大容量
        "qwen2.5:7b",                 # 多言語対応
        "mistral",                    # 汎用
        "phi3",                       # 軽量
        "gemma2",                     # Google製軽量
    ])
    embedding_model: str = "bge-m3"
    embedding_dims: int = 1024


class GraceConfig(BaseModel):
    """GRACE Agent 統合設定"""
    version: str = "1.0"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    confidence: ConfidenceConfig = Field(default_factory=ConfidenceConfig)
    intervention: InterventionConfig = Field(default_factory=InterventionConfig)
    replan: ReplanConfig = Field(default_factory=ReplanConfig)
    cost: CostConfig = Field(default_factory=CostConfig)
    error: ErrorConfig = Field(default_factory=ErrorConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    code_execute: CodeExecuteConfig = Field(default_factory=CodeExecuteConfig)  # P2
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)


# =============================================================================
# 設定ローダー
# =============================================================================

class ConfigLoader:
    """設定ローダー"""

    DEFAULT_CONFIG_PATH = "config/grace_config.yml"
    ENV_PREFIX = "GRACE_"

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self._config: Optional[GraceConfig] = None

    def load(self) -> GraceConfig:
        """設定を読み込み"""
        if self._config is not None:
            return self._config

        config_dict: Dict[str, Any] = {}

        config_file = Path(self.config_path)
        if config_file.exists():
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    loaded = yaml.safe_load(f)
                    if loaded:
                        config_dict = loaded
                logger.info(f"Config loaded from {self.config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config from {self.config_path}: {e}")
        else:
            logger.info(f"Config file not found: {self.config_path}, using defaults")

        config_dict = self._apply_env_overrides(config_dict)

        self._config = GraceConfig(**config_dict)

        return self._config

    def _apply_env_overrides(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """環境変数による上書き"""
        for key, value in os.environ.items():
            if not key.startswith(self.ENV_PREFIX):
                continue

            parts = key[len(self.ENV_PREFIX):].lower().split('_')

            if len(parts) >= 2:
                section = parts[0]
                subkey = '_'.join(parts[1:])

                if section not in config_dict:
                    config_dict[section] = {}

                config_dict[section][subkey] = self._convert_value(value)
                logger.debug(f"Config override: {section}.{subkey} = {value}")

        return config_dict

    def _convert_value(self, value: str) -> Any:
        """文字列から適切な型に変換"""
        if value.lower() in ('true', 'false'):
            return value.lower() == 'true'

        try:
            return int(value)
        except ValueError:
            pass

        try:
            return float(value)
        except ValueError:
            pass

        if ',' in value:
            return [v.strip() for v in value.split(',')]

        return value

    def reload(self) -> GraceConfig:
        """設定を再読み込み"""
        self._config = None
        return self.load()


# =============================================================================
# シングルトンインスタンス
# =============================================================================

_config_loader: Optional[ConfigLoader] = None


def get_config(config_path: Optional[str] = None) -> GraceConfig:
    """設定を取得（シングルトン）"""
    global _config_loader

    if _config_loader is None:
        _config_loader = ConfigLoader(config_path)

    return _config_loader.load()


def reload_config() -> GraceConfig:
    """設定を再読み込み"""
    global _config_loader

    if _config_loader is not None:
        return _config_loader.reload()

    return get_config()


def reset_config():
    """設定をリセット（テスト用）"""
    global _config_loader
    _config_loader = None


# =============================================================================
# エクスポート
# =============================================================================

__all__ = [
    # Config models
    "LLMConfig",
    "EmbeddingConfig",
    "OllamaConfig",
    "ConfidenceWeights",
    "ConfidenceThresholds",
    "ConfidenceConfig",
    "InterventionConfig",
    "ReplanConfig",
    "CostConfig",
    "ErrorConfig",
    "LoggingConfig",
    "QdrantConfig",
    "WebSearchConfig",
    "ToolsConfig",
    "PlannerConfig",
    "ExecutorConfig",
    "GraceConfig",

    # Loader
    "ConfigLoader",

    # Functions
    "get_config",
    "reload_config",
    "reset_config",
]
