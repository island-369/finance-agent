"""M2 注册表与解析器测试:元数据、依赖检查、版本覆盖、绑定集合、只读视图。"""

from __future__ import annotations

from pathlib import Path

import pytest

from finance_agent.bootstrap import build_default_registry
from finance_agent.skills.registry import SkillRecord, load_skill_record, scan_skill_dir
from finance_agent.skills.resolver import (
    SkillResolutionError,
    compute_bound_tools,
    eligible_candidates,
    resolve_skills,
)
from finance_agent.skills.view import build_skill_view

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def registry():
    return build_default_registry()


@pytest.fixture()
def records():
    return scan_skill_dir(PROJECT_ROOT / "skills")


def fake_record(
    name: str,
    version: str = "1.0.0",
    required: tuple | None = None,
    optional: tuple | None = None,
    tmp: Path | None = None,
) -> SkillRecord:
    return SkillRecord(
        name=name,
        version=version,
        declared_name=name,
        description="测试 Skill",
        required_tools=required or (),
        optional_tools=optional or (),
        tags=("测试",),
        path=tmp or PROJECT_ROOT / "skills" / name / version,
        skill_md_sha256="0" * 64,
    )


class TestRegistry:
    def test_scan_finds_all_versions(self, records):
        by_ref = {r.ref for r in records}
        assert "earnings-analysis@1.0.0" in by_ref
        assert "earnings-analysis@0.1.0" in by_ref  # M0 遗留版本仍在
        assert "announcement-impact@1.0.0" in by_ref
        assert "peer-comparison@1.0.0" in by_ref

    def test_metadata_parsed_with_hash(self, records):
        ea = next(r for r in records if r.ref == "earnings-analysis@1.0.0")
        assert ea.required_tools == (("finance.get_metrics", 1), ("finance.calculate_growth", 1))
        assert ea.optional_tools == (("documents.search", 1),)
        assert "财报" in ea.tags
        assert len(ea.skill_md_sha256) == 64

    def test_invalid_frontmatter_rejected(self, tmp_path: Path):
        d = tmp_path / "bad-skill" / "1.0.0"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
        with pytest.raises(ValueError, match="frontmatter"):
            load_skill_record(d)

    def test_name_mismatch_rejected(self, tmp_path: Path):
        d = tmp_path / "skill-a" / "1.0.0"
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            "---\nname: skill-b\ndescription: x\n---\n\n正文", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="不一致"):
            load_skill_record(d)


class TestResolver:
    def test_defaults_pick_latest(self, records, registry):
        resolved = resolve_skills(records, registry)
        by_name = {r.record.name: r for r in resolved}
        assert by_name["earnings-analysis"].record.version == "1.0.0"
        assert all(r.available for r in resolved)

    def test_user_override_pins_version(self, records, registry):
        resolved = resolve_skills(records, registry, user_overrides={"earnings-analysis": "0.1.0"})
        ea = next(r for r in resolved if r.record.name == "earnings-analysis")
        assert ea.record.version == "0.1.0"

    def test_task_preference_beats_user_override(self, records, registry):
        resolved = resolve_skills(
            records, registry,
            user_overrides={"earnings-analysis": "0.1.0"},
            task_preferences=["earnings-analysis@1.0.0"],
        )
        ea = next(r for r in resolved if r.record.name == "earnings-analysis")
        assert ea.record.version == "1.0.0"

    def test_explicit_missing_skill_fails_loudly(self, records, registry):
        with pytest.raises(SkillResolutionError, match="不存在"):
            resolve_skills(records, registry, task_preferences=["no-such-skill"])

    def test_explicit_missing_version_fails_loudly(self, records, registry):
        with pytest.raises(SkillResolutionError, match="版本不存在"):
            resolve_skills(records, registry, task_preferences=["earnings-analysis@9.9.9"])

    def test_missing_required_tool_marks_unavailable(self, registry):
        recs = [fake_record("needs-ghost", required=(("finance.get_segments", 1),))]
        resolved = resolve_skills(recs, registry)
        assert not resolved[0].available
        assert "finance.get_segments@1" in resolved[0].reason
        assert eligible_candidates(resolved) == []

    def test_explicit_unavailable_skill_fails_loudly(self, registry):
        recs = [fake_record("needs-ghost", required=(("finance.get_segments", 1),))]
        with pytest.raises(SkillResolutionError, match="不可用"):
            resolve_skills(recs, registry, task_preferences=["needs-ghost"])

    def test_missing_optional_tool_degrades(self, registry):
        recs = [
            fake_record(
                "partial-deps",
                required=(("finance.get_metrics", 1),),
                optional=(("finance.get_segments", 1),),
            )
        ]
        resolved = resolve_skills(recs, registry)
        assert resolved[0].available
        assert resolved[0].degraded_tools == ("finance.get_segments@1",)

    def test_major_version_mismatch_is_missing(self, registry):
        recs = [fake_record("wrong-major", required=(("finance.get_metrics", 2),))]
        resolved = resolve_skills(recs, registry)
        assert not resolved[0].available


class TestBoundTools:
    def test_all_candidates_bind_all_five(self, records, registry):
        resolved = resolve_skills(records, registry)
        refs = compute_bound_tools(eligible_candidates(resolved), registry)
        assert refs == [
            ("documents.read", 1),
            ("documents.search", 1),
            ("finance.calculate_growth", 1),
            ("finance.compare_peers", 1),
            ("finance.get_metrics", 1),
        ]

    def test_no_candidates_bind_base_only(self, registry):
        refs = compute_bound_tools([], registry)
        assert refs == [("documents.read", 1), ("documents.search", 1)]

    def test_unavailable_skills_tools_not_bound(self, registry):
        recs = [
            fake_record("needs-ghost", required=(("finance.get_segments", 1), ("finance.compare_peers", 1))),
        ]
        resolved = resolve_skills(recs, registry)
        refs = compute_bound_tools(eligible_candidates(resolved), registry)
        assert ("finance.compare_peers", 1) not in refs


class TestView:
    def test_only_available_candidates_copied(self, records, registry, tmp_path: Path):
        ghost = fake_record("needs-ghost", required=(("finance.get_segments", 1),), tmp=tmp_path)
        resolved = resolve_skills(records + [ghost], registry)
        candidates = eligible_candidates(resolved)
        manifest = build_skill_view(candidates, tmp_path / "view")
        names = {m["name"] for m in manifest}
        assert names == {"earnings-analysis", "announcement-impact", "peer-comparison"}
        assert "needs-ghost" not in names  # 不可用不进视图
        assert (tmp_path / "view" / "skills" / "earnings-analysis" / "SKILL.md").is_file()
        assert (tmp_path / "view" / "skills" / "earnings-analysis" / "references" / "metric-definitions.md").is_file()

    def test_view_respects_user_override(self, records, registry, tmp_path: Path):
        resolved = resolve_skills(records, registry, user_overrides={"earnings-analysis": "0.1.0"})
        manifest = build_skill_view(eligible_candidates(resolved), tmp_path / "view")
        ea = next(m for m in manifest if m["name"] == "earnings-analysis")
        assert ea["version"] == "0.1.0"
