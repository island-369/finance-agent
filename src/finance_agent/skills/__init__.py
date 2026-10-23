"""Skill 模块:注册、发现、解析、版本与覆盖(设计 §7)。

SKILL.md 是包元数据的唯一来源;注册表由其解析生成。
`app_*` 为本应用扩展字段,由本模块解析;引擎侧只见引擎支持的格式。
"""

from finance_agent.skills.registry import SkillRecord, scan_skill_dir
from finance_agent.skills.resolver import (
    ResolvedSkill,
    SkillResolutionError,
    resolve_skills,
)
from finance_agent.skills.view import build_skill_view

__all__ = [
    "ResolvedSkill",
    "SkillRecord",
    "SkillResolutionError",
    "build_skill_view",
    "resolve_skills",
    "scan_skill_dir",
]
