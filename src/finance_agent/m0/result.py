"""M0 结构化候选结果契约。

设计 §11 ResearchResult 的最小子集。字段刻意要求引用 observation_id /
source_id,以便验证"候选结果必须携带可核查引用"的校验链路(M1 补完整契约)。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class M0ResearchResult(BaseModel):
    """研究任务的结构化候选结果。"""

    objective: str = Field(description="任务目标(一句话)")
    summary: str = Field(description="结论摘要")
    key_findings: list[str] = Field(
        description="关键发现;涉及数值时必须在句内引用 observation_id", min_length=1
    )
    metric_refs: list[str] = Field(
        description="引用的观测 ID 列表,如 obs-001;必须来自工具返回结果",
        default_factory=list,
    )
    evidence_refs: list[str] = Field(
        description="其他证据引用(来源 ID 或 Skill 路径)", default_factory=list
    )
    assumptions: list[str] = Field(description="未能证实、按假设陈述的判断", default_factory=list)
    information_gaps: list[str] = Field(description="信息缺口与未能回答的部分", default_factory=list)
