---
name: valuation-snapshot
description: 快速生成公司估值快照:最新收入/净利润/同比增速的一页式摘要;适用于快速了解公司经营概况类问题
metadata:
  app_version: "0.1.0"
  app_required_tools:
    - finance.get_metrics@1
    - finance.calculate_growth@1
  app_optional_tools: []
  app_tags: [估值, 概览]
---

# 估值快照

1. 用 finance.get_metrics 取最新两期 cumulative 的 revenue 与 net_profit。
2. 用 finance.calculate_growth 计算同比。
3. 汇总为一页摘要:最新收入、净利润、同比、口径与修订说明;每个数值带引用。
