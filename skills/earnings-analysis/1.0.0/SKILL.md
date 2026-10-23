---
name: earnings-analysis
description: 分析公司收入与利润变化,计算增长并识别有证据支持的驱动因素;适用于业绩变化分析、增收不增利、扭亏/亏损类问题
metadata:
  app_version: "1.0.0"
  app_required_tools:
    - finance.get_metrics@1
    - finance.calculate_growth@1
  app_optional_tools:
    - documents.search@1
  app_tags: [财报, 利润, 收入, 业绩变化]
---

# 业绩变化分析

## 适用问题

- 收入与利润变化方向/幅度不一致(增收不增利、减收增利)
- 单季或累计口径的利润率变化拆解
- 业绩修订前后差异对结论的影响

## 研究方法

1. **先取数**:用 finance.get_metrics 分别取 revenue 与 net_profit,
   basis 显式指定(cumulative 或 single_quarter,不得混用);
   一次查询覆盖本期与同期两个报告期。省略 as_of 即任务截止时间。
2. **用工具计算**:增长率一律用 finance.calculate_growth(输入 observation_id),
   不自行心算;返回 ZERO_DENOMINATOR / INCOMPARABLE_INPUTS 时按原因调整
   输入(如换用同期、统一 basis),不能调整则写入 information_gaps。
3. **修订检查**:观测带 revision_id 与 note;发现修订说明时,优先说明
   "若沿用旧版本结论如何变化"。
4. **拆解方向**:收入与利润变化不一致时,计算两期净利率(净利润/收入)
   并比较;只声明数据能支持的表述(如"利润率下滑吞掉收入增量"),
   成本科目缺失时写入 information_gaps,不臆测科目。
5. **引用**:key_findings 中每个数值引用 observation_id;
   增长率引用 calculation_id(calc- 开头,来自工具返回)。

## 输出要求

- key_findings 至少两条,其中至少一条含 calculation_id 引用。
- 使用了修订版本时在 assumptions 或 key_findings 中说明版本选择。
- 可参考 references/metric-definitions.md 的口径定义。

## 参考

- references/metric-definitions.md:指标口径与 basis/scope 说明
