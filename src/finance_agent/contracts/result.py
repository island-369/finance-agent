"""研究结构化结果契约(设计 §11)。

M1 定义完整字段;候选产物与正式产物共用本结构,校验顺序(M3 的结果校验
模块)按 §11 的五步执行。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from finance_agent.contracts.evidence import EvidenceRef


class KeyFinding(BaseModel):
    statement: str = Field(description="结论表述;涉及数值须内联引用 observation/calculation ID")
    kind: str = Field(default="fact", description="fact / assumption / inference")
    refs: list[str] = Field(default_factory=list, description="observation_id / calculation_id / evidence_id")


class ResearchResult(BaseModel):
    objective: str
    researched_at: str = Field(description="研究执行时间(ISO 8601)")
    entity_ids: list[str]
    summary: str
    key_findings: list[KeyFinding] = Field(min_length=1)
    metric_refs: list[str] = Field(default_factory=list)
    calculation_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    skill_versions: list[str] = Field(default_factory=list, description="实际加载的 Skill 与版本")
    tool_versions: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list, description="如 completed_partial / pending_review")
