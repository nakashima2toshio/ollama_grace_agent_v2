# bench_result.md - gemma4:e4b 完全ベンチマーク解析

**バージョン**: 1.0
**日付**: 2026-06-10
**対象**: `logs/benchmark_results.csv`（36セッション、モデル: `gemma4:e4b`、コレクション: `cc_news_100_ollama`）

---

## 1. 全体サマリ

| 指標 | 値 | 評価 |
|---|---|---|
| 成功率 | 36/36 = **100%** | ✅ |
| confidence 平均 | **0.578**（範囲: 0.537〜0.648） | ⚠️ 全件 CONFIRM |
| 平均処理時間 | **290.1s**（〜4.8分） | ⚠️ 遅い |
| replan 発生 | **0/36件** | ❌ リプランなし |
| requires_confirmation | **14/36件（39%）** | ⚠️ 多い |
| RAGソース取得数 | ほぼ **1件固定**（Q11 run2のみ10件） | ❌ 少ない |
| accuracy_score | **全件 0.5**（LLM judge未機能） | ❌ 要修正 |

---

## 2. クエリ別詳細

| QID | 難易度/カテゴリ | conf_avg | conf_max | time_avg | time_max | src_avg | req_conf | steps_max |
|---|---|---|---|---|---|---|---|---|
| Q01 | Easy/事実検索 | 0.584 | 0.620 | 251s | 282s | 1.0 | 0/3 | 2 |
| Q02 | Easy/事実検索 | 0.565 | 0.566 | 210s | 241s | 1.0 | 0/3 | 2 |
| Q03 | Med/推論比較 | 0.576 | 0.576 | 288s | 363s | 1.0 | 0/3 | 2 |
| Q04 | Med/推論比較 | 0.573 | 0.581 | 320s | 411s | 1.0 | 0/3 | 2 |
| Q05 | Hard/推論比較 | 0.564 | 0.564 | 389s | 791s | 1.0 | 0/3 | 2 |
| Q06 | Hard/推論比較 | 0.564 | 0.577 | 418s | 588s | 1.0 | 3/3 | 4 |
| Q07 | Easy/手順説明 | 0.596 | 0.629 | 271s | 302s | 1.0 | 1/3 | 2 |
| Q08 | Med/手順説明 | 0.572 | 0.572 | 249s | 335s | 1.0 | 2/3 | 2 |
| Q09 | Easy/曖昧 | 0.586 | 0.591 | 233s | 253s | 1.0 | 3/3 | 2 |
| Q10 | Easy/曖昧 | 0.587 | 0.590 | 254s | 284s | 1.0 | 0/3 | 2 |
| Q11 | Hard/推論比較 | 0.572 | 0.575 | 341s | 454s | 4.0 | 2/3 | 3 |
| Q12 | Hard/推論比較 | 0.603 | 0.648 | 258s | 272s | 1.0 | 3/3 | 2 |

### クエリ別コメント

```
Q01  Easy     0.584      251s       0/3       安定
Q02  Easy     0.565      210s       0/3       最速・最低conf
Q03  Medium   0.576      288s       0/3       run2で plan=203s（異常スパイク）
Q04  Medium   0.573      320s       0/3       run3で plan=288s（異常スパイク）
Q05  Hard     0.564      389s       0/3       ⚠️ run2で total=791s（plan=696s）
Q06  Hard     0.564      418s       3/3       ⚠️ 全run要確認、run3でsteps=4
Q07  Easy     0.596      271s       1/3       最高conf（0.629）
Q08  Medium   0.573      249s       2/3       run1で plan=222s（異常スパイク）
Q09  Easy     0.586      233s       3/3       ⚠️ 全run要確認
Q10  Easy     0.587      254s       0/3       Q10修正後：正常動作
Q11  Hard     0.572      341s       2/3       run2のみ steps=3, sources=10
Q12  Hard     0.603      258s       3/3       ⚠️ 全run要確認、最高conf(0.648)
```

---

## 3. 異常値・注目レコード

| QID | run | total_time | plan_time | steps | sources | conf | req_conf |
|---|---|---|---|---|---|---|---|
| Q03 | 2 | 363s | 203s | 2 | 1 | 0.576 | False |
| Q04 | 3 | 411s | 288s | 2 | 1 | 0.563 | False |
| Q05 | 2 | **791s** | **696s** | 2 | 1 | 0.564 | False |
| Q06 | 2 | 399s | 219s | 2 | 1 | 0.577 | True |
| Q06 | 3 | 588s | 247s | **4** | 1 | 0.537 | True |
| Q08 | 1 | 335s | 222s | 2 | 1 | 0.571 | True |
| Q11 | 2 | 454s | 257s | 3 | **10** | 0.575 | False |
| Q11 | 3 | 320s | 205s | 2 | 1 | 0.573 | True |

> Q05 run2 の plan_time=696s は Ollama モデル再ロードによる可能性が高い。
> Q11 run2 は唯一 sources_total=10 を取得（他は全件1件固定）。

---

## 4. 重要問題点（優先度順）

### ❌ 問題1: accuracy_score が全件 0.5（LLM judge 完全未機能）

- **症状**: 36件全て `accuracy_score=0.5`, `completeness_score=0.5`
- **原因**: `BenchmarkRunner.run()` で `final_answer` を取得する際、Executor の返り値オブジェクトに `final_answer` / `answer` / `response` / `result` 属性が存在しない。空文字列が LLMJudge に渡り、キーワード一致率 0/N → 0.5 のフォールバックになっている。
- **対処**: `grace/executor.py` の返り値クラスの属性名を確認し、`BenchmarkRunner` の属性取得ループを修正する。

### ❌ 問題2: replan が 0 件（リプラン機構が動いていない）

- **症状**: 全36セッションで `replan_count=0`
- **llama3.2との差**: llama3.2 では全クエリで `replan_count=1〜3` が発生していた
- **原因候補**: confidence スコアが 0.56〜0.65 → CONFIRM 閾値（0.4）より上のため、`replan` のトリガー条件を満たさない設計になっている可能性。または gemma4:e4b の出力形式がリプラン判定ロジックと不整合。
- **対処**: `grace/replan.py` のリプラン発動条件を確認する。

### ⚠️ 問題3: RAG ソース数が 1 件固定

- **症状**: Q11 run2（sources=10）を除く全35件で `sources_total=1`
- **llama3.2との差**: llama3.2 は全件 `sources_total=10`
- **原因候補**: Qdrant 検索の `top_k` 設定、またはスコアギャップフィルタが厳しすぎてほぼ1件しか残らない。
- **対処**: `helper/helper_llm.py` または RAG 検索設定の `top_k` パラメータを確認する。

### ⚠️ 問題4: plan_time の異常スパイク

- **症状**: Q05 run2（696s）、Q04 run3（288s）、Q03 run2（203s）、Q06 run2（219s）など Plan フェーズが断続的に長時間化
- **原因候補**: Ollama のモデルが VRAM から追い出され再ロードが発生している
- **対処**: `ollama ps` でモデルのキープアライブ設定を確認、または `OLLAMA_KEEP_ALIVE` 環境変数を設定する。

### ⚠️ 問題5: requires_confirmation 多発（Q06/Q09/Q12 は全 run）

- **症状**: Q06（地政学）・Q09（曖昧）・Q12（統合レポート）は毎回 `requires_confirmation=True`
- **原因候補**: Planner の確認閾値が gemma4:e4b の出力スタイルに対して過敏になっている
- **対処**: `grace/planner.py` の確認フラグ判定ロジックを確認する。

---

## 5. llama3.2 との比較（Q01〜Q12 完全実行）

| 指標 | llama3.2 | gemma4:e4b | 差 |
|---|---|---|---|
| confidence 平均 | **0.753** | 0.578 | **-0.175** |
| confidence 最大 | **0.940** | 0.648 | -0.292 |
| 平均処理時間 | 203s | **290s** | +87s（+43%） |
| 成功率 | 97.5% | **100%** | +2.5% |
| replan 平均 | **1.15回** | 0.00回 | リプランなし |
| sources 平均 | **10件** | 1件 | -9件 |
| Intervention | SILENT/NOTIFY/CONFIRM | **全件 CONFIRM** | 多様性なし |
| requires_confirmation | 0件 | **14件（39%）** | 大幅増 |

> llama3.2 は confidence・replan・RAG品質で優位。gemma4:e4b は成功率100%だが全件 CONFIRM 止まりで品質評価が困難な状態。

---

## 6. 修正優先順位

| 優先度 | 問題 | 対象ファイル | 推定工数 |
|---|---|---|---|
| **HIGH** | accuracy_score 取得修正 | `grace/benchmark.py`, `grace/executor.py` | 小 |
| **HIGH** | replan=0 の原因調査・修正 | `grace/replan.py`, `grace/executor.py` | 中 |
| **MEDIUM** | RAG ソース数1件の原因調査 | `helper/helper_llm.py`, RAG 設定 | 小 |
| **MEDIUM** | plan_time スパイク対策 | Ollama 設定（KEEP_ALIVE） | 小 |
| **LOW** | requires_confirmation チューニング | `grace/planner.py` | 中 |

---

## 変更履歴

| バージョン | 日付 | 内容 |
|---|---|---|
| 1.0 | 2026-06-10 | 初版作成（gemma4:e4b 36セッション解析） |
