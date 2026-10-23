---
name: peer-comparison
description: 同口径对齐比较多家公司同一指标,处理币种冲突与缺失并给出差异解释;适用于同业对标、行业内排名、相对表现类问题
metadata:
  app_version: "1.0.0"
  app_required_tools:
    - finance.compare_peers@1
    - finance.get_metrics@1
  app_optional_tools:
    - documents.search@1
  app_tags: [同业比较, 对标, 行业]
---

# 同业指标比较

## 适用问题

- 多家公司同一指标的同口径对比
- 行业内相对位置与差异解释
- 跨币种公司的比较处理

## 研究方法

1. **先定口径**:确认比较的 metric / basis / scope / 报告期完全一致;
   口径不一致时先调整查询条件,不得拿不同口径的结果硬比。
2. **对齐**:finance.compare_peers 一次传入全部公司;返回行级
   missing_reason 的公司如实说明(未披露/晚于截止),不剔除、不编数。
3. **币种冲突**:compare_peers 返回 INCOMPARABLE_METRICS 时,
   按币种分组分别比较;不做汇率换算(系统未提供汇率数据),
   禁止臆造汇率折算成同一币种。
4. **差异解释**:排序与倍数只用工具返回的观测值计算并在句内引用
   observation_id;解释差异原因需要公告佐证时用 documents.search,
   找不到就写 information_gaps。
5. **边界**:比较结论限定在"截至任务截止时间可得的数据"内,
   提示晚披露公司可能改变结论。

## 输出要求

- 输出对齐表(公司/数值/引用),缺失行单独说明。
- 涉及币种分组的,每组分别给结论。
- key_findings 中的每个数值都有 observation_id 引用。
