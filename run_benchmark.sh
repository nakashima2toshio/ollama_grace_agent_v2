#!/usr/bin/env zsh
# ==============================================================
# run_benchmark.sh - ollama_grace_agent ベンチマーク実行
# ==============================================================
# 使用法:
#   chmod +x run_benchmark.sh
#   ./run_benchmark.sh
#
# 前提条件:
#   - Qdrant が起動済み (localhost:6333)
#   - cc_news_100_ollama コレクションが作成・ embedding 済み
#   - Ollama サービスが起動済み (localhost:11434)
#   - gemma4:e4b モデルが pull 済み: ollama pull gemma4:e4b
#   - nomic-embed-text が pull 済み: ollama pull nomic-embed-text
# ==============================================================

set -euo pipefail

COLLECTION="cc_news_100_ollama"
PROJECT="ollama_grace_agent"
MODEL="gemma4:e4b"

echo "================================================================"
echo "  GRACE Benchmark Runner"
echo "  Project   : ${PROJECT}"
echo "  Model     : ${MODEL}"
echo "  Collection: ${COLLECTION}"
echo "  Start     : $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================"
echo "  Note: Ollamaはローカル実行のため処理時間が長くなります"
echo "================================================================"

uv run python - << PYEOF
from grace.benchmark import BenchmarkRunner

runner = BenchmarkRunner(qdrant_collection="${COLLECTION}")
sessions = runner.run_query_set(runs_per_query=3)
count = len(sessions)
print(f"\n完了: {count} セッション -> logs/benchmark_results.csv")
PYEOF

echo "================================================================"
echo "  End: $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================"
