"""只读 Skill 视图(设计 §7.2、§8.2)。

任务启动前把"本次候选"展开为引擎可扫描的扁平视图(<view>/skills/<name>/),
不可用的 Skill 不进入视图;视图整目录只读,写权限由引擎适配器拒绝。
manifest 记录候选与内容哈希,写入执行记录(§7.3 快照)。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from finance_agent.skills.resolver import ResolvedSkill


def build_skill_view(candidates: list[ResolvedSkill], view_root: Path) -> list[dict]:
    if view_root.exists():
        shutil.rmtree(view_root)
    (view_root / "skills").mkdir(parents=True)

    manifest: list[dict] = []
    for cand in sorted(candidates, key=lambda c: c.record.name):
        record = cand.record
        target = view_root / "skills" / record.name
        shutil.copytree(record.path, target)
        manifest.append(
            {
                "name": record.name,
                "version": record.version,
                "ref": record.ref,
                "description": record.description,
                "required_tools": [f"{n}@{m}" for n, m in record.required_tools],
                "optional_tools": [f"{n}@{m}" for n, m in record.optional_tools],
                "skill_md_sha256": record.skill_md_sha256,
                "degraded_tools": list(cand.degraded_tools),
                "source": str(record.path),
            }
        )
    (view_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
