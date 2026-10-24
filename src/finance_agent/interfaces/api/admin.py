"""管理端点:Skill 版本状态/发布/回滚/导入、评测结果列表、用户覆盖。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from finance_agent.application.skill_admin import (
    SkillAdminError,
    import_version,
    publish,
    releases_path,
    retire,
    rollback,
    status_of,
    user_overrides_from_releases,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]
SKILLS_DIR = PROJECT_ROOT / "skills"
EVALS_RESULTS = PROJECT_ROOT / "evals" / "results"

router = APIRouter(prefix="/v1", tags=["admin"])


class VersionAction(BaseModel):
    note: str = Field(default="")


@router.get("/admin/skills")
async def admin_list() -> dict:
    return {"skills": status_of(SKILLS_DIR), "releases_file": str(releases_path(SKILLS_DIR))}


@router.post("/admin/skills/{name}/versions/{version}/publish")
async def admin_publish(name: str, version: str, req: VersionAction) -> dict:
    try:
        return publish(SKILLS_DIR, name, version, req.note)
    except SkillAdminError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/admin/skills/{name}/versions/{version}/rollback")
async def admin_rollback(name: str, version: str, req: VersionAction) -> dict:
    try:
        return rollback(SKILLS_DIR, name, version, req.note)
    except SkillAdminError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/admin/skills/{name}/versions/{version}/retire")
async def admin_retire(name: str, version: str, req: VersionAction) -> dict:
    try:
        return retire(SKILLS_DIR, name, version, req.note)
    except SkillAdminError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/admin/skills/import")
async def admin_import(
    name: str = Form(...),
    version: str = Form(...),
    bundle: UploadFile = File(...),  # noqa: B008 — FastAPI 依赖注入约定
) -> dict:
    """上传一个 zip(<name>/<version>/SKILL.md …)并导入为 draft。"""
    if not bundle.filename or not bundle.filename.endswith(".zip"):
        raise HTTPException(status_code=422, detail="需要 .zip 包")
    import zipfile

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        zip_path = tmp / "bundle.zip"
        zip_path.write_bytes(await bundle.read())
        try:
            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                if f"{name}/{version}/SKILL.md" not in names:
                    raise HTTPException(
                        status_code=422,
                        detail=f"包内缺少 {name}/{version}/SKILL.md;实际: {names[:6]}",
                    )
                zf.extractall(tmp / "bundle")
        except zipfile.BadZipFile as e:
            raise HTTPException(status_code=422, detail="非法 zip 包") from e
        try:
            dst = import_version(SKILLS_DIR, name, version, tmp / "bundle")
        except SkillAdminError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
    return {"imported": f"{name}@{version}", "path": str(dst)}


@router.get("/admin/user-overrides")
async def admin_overrides() -> dict:
    """当前发布指针推导出的用户覆盖(执行侧实际生效的配置)。"""
    return {"overrides": user_overrides_from_releases(SKILLS_DIR)}


@router.get("/admin/evals")
async def eval_results() -> dict:
    """列出评测结果目录与各轮 summary(若存在)。"""
    items = []
    if EVALS_RESULTS.is_dir():
        for d in sorted(EVALS_RESULTS.iterdir()):
            summary = d / "summary.json"
            if summary.is_file():
                items.append({"label": d.name, "summary": __import__("json").loads(summary.read_text(encoding="utf-8"))})
    return {"results": items}


@router.get("/admin/data-source")
async def data_source() -> dict:
    return {"data_source": os.environ.get("FINANCE_AGENT_DATA_SOURCE", "fixture"),
            "note": "Worker 进程的环境变量决定其数据源;切换后需重启 Worker"}
