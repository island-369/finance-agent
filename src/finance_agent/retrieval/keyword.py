"""关键词评分:查询词与文本 token 的重叠计分。

先过滤(公司、版本可得性、时间范围)后评分——过滤职责在数据源,
本模块只做纯评分,便于 M4 替换为 BM25/向量混合。
"""

from __future__ import annotations

from collections import Counter

from finance_agent.retrieval.tokenization import tokenize


def score_text(query_tokens: list[str], text_tokens: list[str]) -> int:
    """重叠计分:每个查询词计 min(出现次数, 3),抑制单词刷分。"""
    counter = Counter(text_tokens)
    return sum(min(counter.get(qt, 0), 3) for qt in set(query_tokens))


def rank(query: str, texts: list[str]) -> list[tuple[int, int]]:
    """返回 [(原列表下标, 分数)],仅保留分数 > 0 的项,按分数降序。"""
    query_tokens = tokenize(query)
    scored = [
        (i, score_text(query_tokens, tokenize(text))) for i, text in enumerate(texts)
    ]
    return [(i, s) for i, s in scored if s > 0]
