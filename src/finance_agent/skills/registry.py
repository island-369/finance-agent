"""Skill 注册表:扫描版本化目录并解析 SKILL.md 元数据。

目录约定(设计 §7.1):skills/<name>/<version>/SKILL.md;
版本与内容哈希对应,已发布版本不可原地覆盖(哈希记录在案,M3 入库强制)。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
TOOL_REF_RE = re.compile(r"^(?P<name>[a-z_.]+)@(?P<major>\d+)$")


@dataclass(frozen=True)
class SkillRecord:
    name: str
    version: str
    declared_name: str
    description: str
    required_tools: tuple[tuple[str, int], ...]
    optional_tools: tuple[tuple[str, int], ...]
    tags: tuple[str, ...]
    path: Path
    skill_md_sha256: str

    @property
    def ref(self) -> str:
        return f"{self.name}@{self.version}"

    def intros(self) -> dict:
        """注入给引擎的简介(§7.2 三粒度之第一级)。"""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "required_tools": [f"{n}@{m}" for n, m in self.required_tools],
            "optional_tools": [f"{n}@{m}" for n, m in self.optional_tools],
            "tags": list(self.tags),
        }


def version_key(version: str) -> tuple[int, int, int]:
    m = VERSION_RE.match(version)
    if not m:
        raise ValueError(f"非法版本号: {version!r}(期望 x.y.z)")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def _parse_tool_ref(value: str, source: Path) -> tuple[str, int]:
    m = TOOL_REF_RE.match(value.strip())
    if not m:
        raise ValueError(f"{source}: 工具引用格式应为 name@major,得到 {value!r}")
    return (m.group("name"), int(m.group("major")))


def parse_skill_md(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{skill_md} 缺少 YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{skill_md} frontmatter 未闭合")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        raise TypeError(f"{skill_md} frontmatter 不是映射")
    return data


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_skill_record(version_dir: Path) -> SkillRecord:
    name = version_dir.parent.name
    version = version_dir.name
    skill_md = version_dir / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"缺少 SKILL.md: {skill_md}")
    if not NAME_RE.match(name):
        raise ValueError(f"Skill 名称不合规: {name!r}")
    version_key(version)  # 校验版本号格式

    data = parse_skill_md(skill_md)
    declared_name = data.get("name")
    description = data.get("description")
    if declared_name != name:
        raise ValueError(f"{skill_md}: frontmatter name({declared_name!r})与目录名({name!r})不一致")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{skill_md}: description 不能为空")

    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise TypeError(f"{skill_md}: metadata 必须是映射")
    declared_version = metadata.get("app_version")
    if declared_version is not None and str(declared_version) != version:
        raise ValueError(
            f"{skill_md}: metadata.app_version({declared_version})与目录版本({version})不一致"
        )

    def _tool_list(key: str) -> tuple[tuple[str, int], ...]:
        raw = metadata.get(key) or []
        if not isinstance(raw, list):
            raise TypeError(f"{skill_md}: metadata.{key} 必须是列表")
        return tuple(_parse_tool_ref(str(v), skill_md) for v in raw)

    tags_raw = metadata.get("app_tags") or []
    if not isinstance(tags_raw, list):
        raise TypeError(f"{skill_md}: metadata.app_tags 必须是列表")

    return SkillRecord(
        name=name,
        version=version,
        declared_name=declared_name,
        description=description.strip(),
        required_tools=_tool_list("app_required_tools"),
        optional_tools=_tool_list("app_optional_tools"),
        tags=tuple(str(t) for t in tags_raw),
        path=version_dir,
        skill_md_sha256=_sha256(skill_md),
    )


def scan_skill_dir(repo_skills_dir: Path) -> list[SkillRecord]:
    """扫描 skills/<name>/<version>/SKILL.md,返回全部已发布记录。"""
    records: list[SkillRecord] = []
    for skill_md in sorted(repo_skills_dir.glob("*/*/SKILL.md")):
        records.append(load_skill_record(skill_md.parent))
    if not records:
        raise FileNotFoundError(f"未发现任何 Skill: {repo_skills_dir}")
    return records
