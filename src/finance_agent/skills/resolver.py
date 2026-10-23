"""Skill 解析:版本覆盖顺序、依赖检查与候选确定(设计 §7.2、§7.3、§8.2)。

覆盖顺序:任务显式版本 → 用户已发布覆盖 → 项目最新版本。
- 必需工具缺失(或主版本不符):该 Skill 标记不可用,给出原因,不进候选。
- 可选工具缺失:保留可用,记录降级说明。
- 显式指定的 Skill 不存在或不可用:抛 SkillResolutionError,不静默替换。
任务创建时把解析结果(候选+排除原因+绑定工具)写入执行快照(§7.3)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from finance_agent.skills.registry import SkillRecord, version_key
from finance_agent.tools.registry import ToolRegistry

BASE_TOOL_REFS: tuple[tuple[str, int], ...] = (
    ("documents.search", 1),
    ("documents.read", 1),
)
"""通用基础工具:候选为空时 Agent 仍可做受限的通用检索研究。"""


class SkillResolutionError(Exception):
    """显式指定无法满足;任务应在创建时失败,不静默替换。"""


@dataclass(frozen=True)
class ResolvedSkill:
    record: SkillRecord
    available: bool
    reason: str | None = None
    degraded_tools: tuple[str, ...] = field(default=())

    @property
    def ref(self) -> str:
        return self.record.ref


def _pick_version(records: list[SkillRecord]) -> SkillRecord:
    return max(records, key=lambda r: version_key(r.version))


def _has_tool(tools: ToolRegistry, name: str, major: int) -> bool:
    spec = tools.find(name)
    return spec is not None and spec.major_version == major


def _check_tools(
    record: SkillRecord, tools: ToolRegistry
) -> tuple[bool, str | None, tuple[str, ...]]:
    missing_required = [
        f"{name}@{major}" for name, major in record.required_tools if not _has_tool(tools, name, major)
    ]
    if missing_required:
        return (False, f"缺少必需工具: {', '.join(missing_required)}", ())
    degraded = [
        f"{name}@{major}" for name, major in record.optional_tools if not _has_tool(tools, name, major)
    ]
    return (True, None, tuple(degraded))


def resolve_skills(
    records: list[SkillRecord],
    tools: ToolRegistry,
    *,
    user_overrides: dict[str, str] | None = None,
    task_preferences: list[str] | None = None,
) -> list[ResolvedSkill]:
    """按覆盖顺序确定每个 Skill 的唯一版本,并做依赖检查。

    task_preferences 项为 `name` 或 `name@version`;显式指定的 Skill
    不存在或不可用时抛 SkillResolutionError。
    """
    by_name: dict[str, list[SkillRecord]] = {}
    for r in records:
        by_name.setdefault(r.name, []).append(r)

    user_overrides = user_overrides or {}

    # 显式偏好:name@version 精确锁定;name 锁定该名称(仍受覆盖顺序)
    locked: dict[str, str] = {}
    for pref in task_preferences or []:
        name, _, ver = pref.partition("@")
        if name not in by_name:
            known = ", ".join(sorted(by_name))
            raise SkillResolutionError(f"显式指定的 Skill 不存在: {pref}(已知: {known})")
        if ver and ver not in {r.version for r in by_name[name]}:
            raise SkillResolutionError(
                f"显式指定的版本不存在: {pref}(可用版本: "
                + ", ".join(sorted(r.version for r in by_name[name])) + ")"
            )
        locked[name] = ver or "latest"

    resolved: list[ResolvedSkill] = []
    for name, versions in sorted(by_name.items()):
        if name in locked and locked[name] != "latest":
            chosen = next(r for r in versions if r.version == locked[name])
        elif name in user_overrides:
            ver = user_overrides[name]
            chosen = next((r for r in versions if r.version == ver), None)
            if chosen is None:
                # 用户覆盖指向不存在的版本:回到项目最新,并如实记录
                chosen = _pick_version(versions)
                resolved.append(ResolvedSkill(record=chosen, available=True, reason=f"用户覆盖 {name}@{ver} 不存在,回退项目最新"))
                continue
        else:
            chosen = _pick_version(versions)
        ok, reason, degraded = _check_tools(chosen, tools)
        resolved.append(
            ResolvedSkill(record=chosen, available=ok, reason=reason, degraded_tools=degraded)
        )

    for r in resolved:
        if r.record.name in locked and not r.available:
            raise SkillResolutionError(f"显式指定的 Skill 不可用: {r.ref}({r.reason})")
    return resolved


def eligible_candidates(
    resolved: list[ResolvedSkill], only: set[str] | None = None
) -> list[ResolvedSkill]:
    """可用候选;显式指定 Skill 时任务边界收敛为指定集合(§7.2)。"""
    cands = [r for r in resolved if r.available]
    if only is not None:
        cands = [r for r in cands if r.record.name in only]
    return cands


def compute_bound_tools(
    candidates: list[ResolvedSkill], tools: ToolRegistry
) -> list[tuple[str, int]]:
    """绑定集合 = 候选 Skill 必需+可选工具(存在的) ∪ 通用基础工具(§8.2)。"""
    refs: set[tuple[str, int]] = set(BASE_TOOL_REFS)
    for c in candidates:
        for name, major in c.record.required_tools + c.record.optional_tools:
            if _has_tool(tools, name, major):
                refs.add((name, major))
    return sorted(refs)
