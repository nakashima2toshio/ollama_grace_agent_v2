# LLM出力枠の是正（推論/thinking 系モデル対応） — ollama 版

`openai_grace_agent` で特定した根本原因対策（PR #25）を **ollama_grace_agent へ横展開**した
記録。`anthropic_grace_agent` を「正（ロジック・数値の基準）」とし、provider 層
（クライアント・モデル名・パラメータ名・APIキー）は **ollama の構成を維持**する。

- 作成日: 2026-06-14
- 基準（数値の正）: `anthropic_grace_agent`
- 対象ブランチ: `claude/upbeat-bell-rnr7ma`
- 反映 PR: `ollama_grace_agent#92`

---

## §0 プロバイダー読み替え（確定値）

anthropic を正にするのは**ロジック・数値**のみ。下表は ollama のものを維持する。

| 項目 | anthropic（正にしない） | **ollama（維持する値）** |
|---|---|---|
| LLM クライアント | `create_llm_client("anthropic")` | `create_llm_client("ollama")` |
| Embedding クライアント | `create_embedding_client("gemini")` | `create_embedding_client("ollama")` |
| デフォルト LLM モデル | `claude-sonnet-4-6` | `gemma4:e4b`（または `llama3.2`） |
| Embedding モデル/次元 | `gemini-embedding-001` / 3072 | `nomic-embed-text` / **768** |
| 出力枠パラメータ名 | `max_tokens` | `max_tokens` |
| API キー | `ANTHROPIC_API_KEY` | 不要（ローカル実行） |
| Qdrant コレクション | `*_anthropic` | `*_ollama` |

---

## 根本原因（単一）

**出力枠（`max_tokens`）が小さいと、推論/thinking 系モデルは出力枠をまず思考トークンに
消費し、本文が出る前に打ち切られて可視出力が空/切断になる。**

- **移植リグレッション**: anthropic（正）の出力枠が ollama 移植時に削られていた
  （`512→10`、`1024→200`）。非推論モデルでは小枠でも応答するため顕在化しにくいが、
  thinking を持つローカルモデルでは破綻リスクがある。
- **テスト非密閉**: `tests/grace/test_executor.py` の `TestExecutor` は実LLMを呼ぶ
  非密閉テストで、LLM 不在時は例外→`default True` で素通りする。実 LLM 稼働時に
  relevance 判定が変動し、不要な `web_search`/`ask_user` 動的挿入で `partial` 化して非決定的になる。

### 連鎖（症状）

| 経路 | 症状 | 影響 |
|---|---|---|
| `confidence.evaluate_*` | 出力空→parse失敗→毎回フォールバック | 信頼度劣化（status は不変） |
| `executor._evaluate_rag_relevance` | 出力空→常に不適合 | 不要な web_search/ask_user 挿入→`partial`・余分なステップ |

---

## 対応

| # | 種別 | 状態 | 作業 |
|---|---|---|---|
| **H1** | fix | ⚪ N/A | gpt-5 系の `temperature` 制約は OpenAI 固有。ollama（ローカル）には該当せず対象外 |
| **H2** | fix | ✅ DONE（PR #92） | `grace/confidence.py` の出力枠を anthropic 基準に復元（`max_tokens` を `10→512`、`200→1024`）。`grace/executor.py _evaluate_rag_relevance` は枠 `5→256` ＋ **空応答時は関数自身のフォールバック契約どおり `True`（適合扱い）** を返す安全網を追加 |
| **H3** | test | ✅ DONE（PR #92） | `tests/grace/test_executor.py` `TestExecutor` を **密閉化**（autouse fixture で `_evaluate_rag_relevance` をスタブ）。LLM有無・モデル種別に依存せず決定的に |

> パラメータ名（`max_tokens`）・モデル値は ollama のまま維持。モデル名マッピング・
> APIメソッド変更は行わない。

---

## 検証

- `tests/grace/test_executor.py` ＋ `tests/grace/test_confidence.py` 全 **45 件 PASS**（`uv run`）。
- `ruff check grace/ tests/grace/test_executor.py` クリーン。

---

## 横展開状況（全 provider）

| repo | 出力枠パラメータ | confidence 枠 | relevance 枠 | 反映 |
|---|---|---|---|---|
| anthropic（正） | `max_tokens` | 512 / 1024 | 5 | 元から正（=baseline） |
| openai | `max_completion_tokens` | 512 / 1024 | 256 | PR #25 |
| ollama | `max_tokens` | **512 / 1024** | **256** | **PR #92（本リポジトリ）** |
| gemini | `max_output_tokens` | 512 / 1024 | 256 | PR #20 |

---

*作成日: 2026-06-14*
