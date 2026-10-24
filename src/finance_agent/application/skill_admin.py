"""Skill 版本管理(M5 演示用,文件化注册表;M6+ 可迁移数据库)。

状态模型(设计 §7.4):draft → candidate → evaluated → active → retired。
实现为 JSON 发布记录(releases.json)+ 仓库目录中的版本包:
- publish:把候选版本标记为 active(回滚 = 把旧版本再次置为 active,指针切换)
- retire:标记 retired(不再进入候选)
- active 指针信息由 resolver 的 user_overrides(项目级)表达,零代码改动
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from finance_agent.skills.registry import scan_skill_dir, version_key

RELEASES_FILE = "releases.json"


class SkillAdminError(Exception):
    pass


def releases_path(skills_dir: Path) -> Path:
    return skills_dir / ".releases" / RELEASES_FILE


def load_releases(skills_dir: Path) -> list[dict]:
    p = releases_path(skills_dir)
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def save_releases(skills_dir: Path, releases: list[dict]) -> None:
    p = releases_path(skills_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(releases, ensure_ascii=False, indent=2), encoding="utf-8")


def _active_pointers(skills_dir: Path) -> dict[str, str]:
    """从发布记录推导 active 指针:每个 name 最近一次 publish/rollback 的版本。"""
    pointers: dict[str, str] = {}
    for r in load_releases(skills_dir):
        if r["action"] in ("publish", "rollback"):
            pointers[r["name"]] = r["version"]
    return pointers


def user_overrides_from_releases(skills_dir: Path) -> dict[str, str]:
    """active 指针 ≠ 该 name 目录内最新版本时,输出 user_overrides。"""
    records = scan_skill_dir(skills_dir)
    latest: dict[str, str] = {}
    for rec in records:
        cur = latest.get(rec.name)
        if cur is None or version_key(rec.version) > version_key(cur):
            latest[rec.name] = rec.version
    overrides = {}
    for name, ver in _active_pointers(skills_dir).items():
        if latest.get(name) and ver != latest[name]:
            overrides[name] = ver
    return overrides


def status_of(skills_dir: Path) -> list[dict]:
    """全部 (name, version) 与其状态(draft / active / retired)。"""
    records = scan_skill_dir(skills_dir)
    pointers = _active_pointers(skills_dir)
    retired = {
        (r["name"], r["version"])
        for r in load_releases(skills_dir)
        if r["action"] == "retire"
    }
    latest: dict[str, str] = {}
    for rec in records:
        cur = latest.get(rec.name)
        if cur is None or version_key(rec.version) > version_key(cur):
            latest[rec.name] = rec.version
    rows = []
    for rec in sorted(records, key=lambda r: (r.name, r.version)):
        if (rec.name, rec.version) in retired:
            state = "retired"
        elif pointers.get(rec.name) == rec.version:
            state = "active"
        elif latest.get(rec.name) == rec.version:
            state = "draft"  # 目录内最新但未发布
        else:
            state = "candidate"  # 已被新版本超越的历史版本
        rows.append(
            {
                "name": rec.name,
                "version": rec.version,
                "state": state,
                "description": rec.description,
                "sha256": rec.skill_md_sha256,
            }
        )
    return rows


def import_version(skills_dir: Path, name: str, version: str, source_dir: Path) -> Path:
    """导入一个新版本包(draft);目录结构必须 name/version 且 frontmatter 一致。"""
    src = source_dir / name / version
    skill_md = src / "SKILL.md"
    if not skill_md.is_file():
        raise SkillAdminError(f"导入源缺少 SKILL.md: {src}")
    dst = skills_dir / name / version
    if dst.exists():
        raise SkillAdminError(f"版本已存在,不可覆盖(§7.1): {dst}")
    shutil.copytree(src, dst)
    from finance_agent.skills.registry import load_skill_record

    load_skill_record(dst)  # 校验元数据
    save_releases(skills_dir, load_releases(skills_dir) + [{
        "name": name, "version": version, "action": "import",
        "at": datetime.now(UTC).isoformat(), "note": f"imported from {source_dir}",
    }])
    return dst


def publish(skills_dir: Path, name: str, version: str, note: str = "") -> dict:
    _require(skills_dir, name, version)
    entry = {"name": name, "version": version, "action": "publish",
             "at": datetime.now(UTC).isoformat(), "note": note}
    save_releases(skills_dir, load_releases(skills_dir) + [entry])
    return entry


def rollback(skills_dir: Path, name: str, version: str, note: str = "") -> dict:
    _require(skills_dir, name, version)
    entry = {"name": name, "version": version, "action": "rollback",
             "at": datetime.now(UTC).isoformat(), "note": note}
    save_releases(skills_dir, load_releases(skills_dir) + [entry])
    return entry


def retire(skills_dir: Path, name: str, version: str, note: str = "") -> dict:
    _require(skills_dir, name, version)
    entry = {"name": name, "version": version, "action": "retire",
             "at": datetime.now(UTC).isoformat(), "note": note}
    save_releases(skills_dir, load_releases(skills_dir) + [entry])
    return entry


def _require(skills_dir: Path, name: str, version: str) -> None:
    if not (skills_dir / name / version / "SKILL.md").is_file():
        raise SkillAdminError(f"版本不存在: {name}@{version}")
