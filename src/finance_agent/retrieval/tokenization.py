"""中文关键词分词:ASCII 词 + CJK 二元组(bigram)。

零依赖的轻量方案:不假设 PostgreSQL 默认分词适配中文(设计 §8.4);
fixture 规模下 bigram 召回足够,真实数据阶段替换为分词器 + BM25。
"""

from __future__ import annotations

import re

_ASCII_WORD = re.compile(r"[a-zA-Z0-9]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for word in _ASCII_WORD.findall(text):
        tokens.append(word.lower())
    # 抽取连续中文串,逐串生成 bigram;单字串保留单字
    runs = re.findall(r"[\u4e00-\u9fff]+", text)
    for run in runs:
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def term_set(text: str) -> set[str]:
    return set(tokenize(text))
