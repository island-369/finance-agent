"""M0 Skill 只读视图构建。

仓库内 Skill 采用设计 §7.1 的版本化布局 `skills/<name>/<version>/SKILL.md`;
Deep Agents 的 SkillsMiddleware 扫描的是"源目录下的直接子目录中的 SKILL.md",
不支持版本层级。因此在任务启动前构建一个扁平只读视图:

    <view_root>/skills/<name>/SKILL.md      (取该 name 已发布的最高版本)

并写 manifest.json 记录 name、version、内容 sha256 与源路径,作为 M2
"注册表由 SKILL.md 解析生成、按内容哈希寻址"的雏形。视图每次全量重建,
不回写仓库目录。
"""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[.-].*)?$")


def _version_key(version: str) -> tuple[int, int, int, str]:
    m = VERSION_RE.match(version.strip())
    if not m:
        return (0, 0, 0, version)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), version)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_skill_frontmatter(skill_md: Path) -> dict:
    """解析 SKILL.md 的 YAML frontmatter(仅取 name/description/metadata 顶层字段)。"""
    import yaml

    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{skill_md} 缺少 YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{skill_md} frontmatter 未闭合")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict) or "name" not in data or "description" not in data:
        raise ValueError(f"{skill_md} frontmatter 必须包含 name 与 description")
    return data


def build_skill_view(repo_skills_dir: Path, view_root: Path) -> list[dict]:
    """把版本化 Skill 目录展开成引擎可扫描的扁平视图,返回 manifest 条目。"""
    if not repo_skills_dir.is_dir():
        raise FileNotFoundError(f"Skill 目录不存在: {repo_skills_dir}")

    entries: dict[str, Path] = {}
    for skill_md in sorted(repo_skills_dir.glob("*/*/SKILL.md")):
        name_dir = skill_md.parent
        version = name_dir.name
        name = name_dir.parent.name
        key = _version_key(version)
        if name not in entries or key > entries[name][0]:
            entries[name] = (key, name_dir)

    if view_root.exists():
        shutil.rmtree(view_root)
    (view_root / "skills").mkdir(parents=True)

    manifest: list[dict] = []
    for name, (_, version_dir) in sorted(entries.items()):
        meta = parse_skill_frontmatter(version_dir / "SKILL.md")
        target = view_root / "skills" / name
        shutil.copytree(version_dir, target)
        manifest.append(
            {
                "name": name,
                "version": version_dir.name,
                "declared_name": meta["name"],
                "description": meta["description"],
                "skill_md_sha256": _sha256(version_dir / "SKILL.md"),
                "source": str(version_dir),
            }
        )

    import json

    (view_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
