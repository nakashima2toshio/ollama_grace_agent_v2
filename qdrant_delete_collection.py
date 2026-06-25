#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
qdrant_delete_collection.py - 指定コレクションを削除するコマンド（Ollama 版）

Ollama ネイティブ運用では Embedding は nomic-embed-text（768次元）、コレクションは
``*_ollama`` 命名を用いる。本リポジトリには旧 OpenAI/Gemini 由来の 3072次元
コレクションが混在し得るため、--list では次元数と Embedding モデルも表示して
誤削除を防ぐ。

使用例:
    # 一覧表示（次元数・Embeddingモデル付き）
    uv run python qdrant_delete_collection.py --list

    # ollama コレクションのみ一覧
    uv run python qdrant_delete_collection.py --list --ollama-only

    # 指定コレクションを削除（確認プロンプトあり）
    uv run python qdrant_delete_collection.py cc_news_2per_ollama

    # 確認をスキップして削除
    uv run python qdrant_delete_collection.py cc_news_2per_ollama --yes
"""

import argparse
import sys

from qdrant_client_wrapper import create_qdrant_client, get_all_collections


def _get_vector_size(client, name: str):
    """コレクションのベクトル次元数を取得する（取得不能なら None）。"""
    try:
        vc = client.get_collection(name).config.params.vectors
        if hasattr(vc, "size"):
            return vc.size
        if isinstance(vc, dict) and vc:
            first = next(iter(vc.values()))
            return getattr(first, "size", None)
    except Exception:
        return None
    return None


def _get_embedding_model(client, name: str):
    """先頭ポイントの payload から embedding_model を取得する（無ければ None）。"""
    try:
        points, _ = client.scroll(collection_name=name, limit=1, with_payload=True)
        if points:
            payload = getattr(points[0], "payload", None) or {}
            return payload.get("embedding_model")
    except Exception:
        return None
    return None


def main():
    parser = argparse.ArgumentParser(description="Qdrant コレクション削除コマンド（Ollama 版）")
    parser.add_argument("collection_name", nargs="?", help="削除するコレクション名")
    parser.add_argument("--url", default="http://localhost:6333", help="Qdrant URL")
    parser.add_argument("--yes", "-y", action="store_true", help="確認プロンプトをスキップ")
    parser.add_argument("--list", "-l", action="store_true", help="コレクション一覧を表示して終了")
    parser.add_argument("--ollama-only", action="store_true",
                        help="--list 時、'_ollama' を含むコレクションのみ表示")
    args = parser.parse_args()

    client = create_qdrant_client(url=args.url)

    # --list: コレクション一覧表示（次元数・Embeddingモデル付き）
    if args.list:
        collections = get_all_collections(client)
        if args.ollama_only:
            collections = [c for c in collections if "_ollama" in c["name"]]
        if not collections:
            print("コレクションが存在しません。")
            return
        print(f"コレクション一覧 ({len(collections)}件):")
        print(f"  {'name':40s}  {'points':>8s}  {'dim':>5s}  {'embedding_model':20s}  status")
        for col in collections:
            dim = _get_vector_size(client, col["name"])
            model = _get_embedding_model(client, col["name"]) or "-"
            dim_s = str(dim) if dim is not None else "?"
            print(
                f"  {col['name']:40s}  {col['points_count']:>8,}  "
                f"{dim_s:>5s}  {model:20s}  {col['status']}"
            )
        return

    # コレクション名が指定されていない場合
    if not args.collection_name:
        parser.print_help()
        sys.exit(1)

    collection_name = args.collection_name

    # 存在確認
    collections = get_all_collections(client)
    existing = [c["name"] for c in collections]
    if collection_name not in existing:
        print(f"エラー: コレクション '{collection_name}' は存在しません。")
        print(f"既存コレクション: {existing}")
        sys.exit(1)

    # 削除前の情報表示（次元数・Embeddingモデルも表示）
    target = next(c for c in collections if c["name"] == collection_name)
    dim = _get_vector_size(client, collection_name)
    model = _get_embedding_model(client, collection_name) or "-"
    print(f"削除対象: {collection_name}")
    print(f"  points_count    : {target['points_count']:,}")
    print(f"  dimensions      : {dim if dim is not None else '?'}")
    print(f"  embedding_model : {model}")
    print(f"  status          : {target['status']}")

    # 確認プロンプト（--yes で省略可）
    if not args.yes:
        answer = input(f"\n'{collection_name}' を削除しますか？ [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("削除をキャンセルしました。")
            sys.exit(0)

    # 削除実行
    client.delete_collection(collection_name=collection_name)
    print(f"削除完了: コレクション '{collection_name}' を削除しました。")


if __name__ == "__main__":
    main()
