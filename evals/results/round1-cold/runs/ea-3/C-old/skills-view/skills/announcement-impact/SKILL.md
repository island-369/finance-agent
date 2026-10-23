---
name: announcement-impact
description: 研究公告/财报披露对公司财务的影响路径,基于原文与数据印证区分事实与推断;适用于更正公告、业绩预告、重大事项影响类问题
metadata:
  app_version: "1.0.0"
  app_required_tools:
    - documents.search@1
    - documents.read@1
    - finance.get_metrics@1
  app_optional_tools:
    - finance.calculate_growth@1
  app_tags: [公告, 更正, 业绩预告, 影响分析]
---

# 公告影响研究

## 适用问题

- 更正公告/业绩预告对业绩结论的影响
- 公告陈述与财务数据的印证或矛盾
- 事项影响的证据链梳理

## 研究方法

1. **检索公告**:documents.search 用公司+事项关键词(如"更正""业绩预告"),
   时间范围按需要收窄;返回的 evidence_id 用于引用。
2. **读原文**:documents.read 读取关键片段原文,确认表述原文而非转述。
3. **数据印证**:finance.get_metrics 取公告涉及的指标,口径(basis/scope)
   与公告一致;数据缺失时明确"数据不可得",不用公告数字冒充标准化观测。
4. **区分三类陈述**(写入 key_findings 的 kind):
   - fact:公告原文或工具观测直接支持(引用 evidence_id / observation_id)
   - inference:由事实推出的判断(说明推导依据)
   - assumption:无法证实的假设(写入 assumptions)
5. **影响路径**:变化 → 环节 → 证据 的链条表述;证据断链处写 information_gaps。

## 输出要求

- key_findings 中 fact 类至少两条且各带 evidence_id 或 observation_id 引用。
- 涉及修订/更正的,说明修订前后数值与结论差异。
- 公告原文引用需给出页码/段落(documents.read 返回的定位)。
