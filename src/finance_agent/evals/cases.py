"""评测用例契约与加载。

用例是 JSON 文件(evals/cases/dev/*.json),字段全部机器可校验;
expected 只描述可判定的要求(引用 ID、关键词、期望数值的文本表示),
不预设"唯一正确答案"。
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class Expectation(BaseModel):
    required_refs: list[str] = Field(default_factory=list, description="结果必须引用的 obs-/chk-/calc- 之外的确定性 ID(obs-/chk- 前缀)")
    required_keywords: list[str] = Field(default_factory=list, description="摘要+发现文本必须包含的关键词(任一命中即计 1 项)")
    expected_numbers: list[str] = Field(default_factory=list, description="期望数值的文本表示(如 -11.11 / 272000000 / 2.72亿;任一命中即通过)")
    forbidden_numbers: list[str] = Field(default_factory=list, description="禁止出现的数值文本(反编造检查,如未披露的对手利润)")
    skill_hint: list[str] = Field(default_factory=list, description="C 组合理 Skill(加载任一即通过;空表示无需 Skill 也合理)")
    allow_no_skill: bool = True


class EvalCase(BaseModel):
    case_id: str
    task_type: str = Field(description="earnings / announcement / peer / boundary")
    objective: str
    entity_ids: list[str]
    as_of: str
    expectation: Expectation
    notes: str = ""


def load_cases(case_dir: Path) -> list[EvalCase]:
    files = sorted(case_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"用例目录为空: {case_dir}")
    cases = [EvalCase.model_validate(json.loads(f.read_text(encoding="utf-8"))) for f in files]
    ids = [c.case_id for c in cases]
    assert len(ids) == len(set(ids)), "case_id 必须唯一"
    return cases
