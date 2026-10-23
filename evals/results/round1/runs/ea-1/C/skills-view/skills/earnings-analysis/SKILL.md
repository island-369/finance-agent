---
name: earnings-analysis
description: 分析公司收入与利润变化,识别有证据支持的驱动因素;适用于业绩变化分析类研究问题
metadata:
  app_version: "0.1.0"
  app_required_tools:
    - finance.get_metrics@1
  app_optional_tools: []
  app_tags: [财报, 利润, 收入]
---

# 业绩变化分析(M0 演示版)

## 适用问题

- 收入增长但利润下降(或相反)的原因分析
- 单季/累计利润率变化拆解

## 研究方法

1. **先取数,后判断**:用 `finance_get_metrics` 分别取 revenue 与 net_profit,
   至少覆盖本期、去年同期两个报告期;省略 as_of 参数以使用任务截止时间。
2. **校验口径再比较**:确认观测 scope 均为"合并报表"、unit 与 currency 一致;
   同一报告期出现多版本时,以工具返回的版本(截止时间内最新修订)为准。
3. **拆解方向**:先看收入变化幅度,再看利润变化幅度;两者方向或幅度不一致时,
   重点检查利润率(净利润/收入)的同期变化,并给出"成本/费用侧压力"这类
   可由数据支持的表述;数据不足以区分的原因写入信息缺口,不臆测。
4. **引用**:结论中的每个数值都引用对应观测的 observation_id。

## 输出要求

- key_findings 至少两条,每条包含数值与 observation_id 引用。
- 使用了本方法但数据不足的环节,在 information_gaps 中说明缺哪个报告期或口径。

版本 0.1.0 为 M0 底座实验用最小实现;完整版将增加分部数据与成本科目拆解。
