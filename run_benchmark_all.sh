# 4プロジェクトのCSVを1つに結合して比較
cd /Users/nakashima_toshio/PycharmProjects
python - <<'EOF'
import pandas as pd, glob

files = {
    "anthropic": "anthropic_grace_agent/logs/benchmark_results.csv",
    "openai":    "openai_grace_agent/logs/benchmark_results.csv",
    "gemini":    "gemini_grace_agent/logs/benchmark_results.csv",
    "ollama":    "ollama_grace_agent/logs/benchmark_results.csv",
}

dfs = []
for label, path in files.items():
    df = pd.read_csv(path)
    df["project"] = label
    dfs.append(df)

combined = pd.concat(dfs, ignore_index=True)
combined.to_csv("benchmark_combined.csv", index=False)

summary = combined.groupby(["project", "level"])[
    ["overall_confidence", "total_time_sec", "cost_usd"]
].mean().round(3)
print(summary)
EOF
