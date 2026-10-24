"""文档类工具:documents.search / documents.read。

search 先过滤(实体、版本可得性、时间范围)再评分;read 按证据 ID
(chunk_id)返回原文与定位。文档版本选择(同文档多版本取截止时间内
最新)由数据源保证。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from finance_agent.contracts.common import DATA_NOT_FOUND, ToolError
from finance_agent.contracts.evidence import Chunk, DocumentVersion, EvidenceRef
from finance_agent.contracts.task import TaskContext
from finance_agent.contracts.toolspec import ToolSpec
from finance_agent.ports.data import DocumentSource
from finance_agent.tools.finance_tools import _effective_as_of


class SearchInput(BaseModel):
    query: str = Field(min_length=1, description="检索关键词")
    entity_ids: list[str] | None = Field(default=None, description="限定公司;缺省全部")
    available_from: datetime | None = None
    available_to: datetime | None = None
    limit: int = Field(default=8, ge=1, le=20)
    as_of: datetime | None = None


class SearchHit(BaseModel):
    evidence: EvidenceRef
    document: DocumentVersion


class SearchOutput(BaseModel):
    query: str
    as_of_effective: datetime
    hits: list[SearchHit]


def build_documents_search(source: DocumentSource) -> ToolSpec:
    def handler(args: SearchInput, ctx: TaskContext) -> SearchOutput:
        assert isinstance(args, SearchInput)
        as_of = _effective_as_of(args.as_of, ctx)
        chunks = source.search_chunks(
            query=args.query,
            entity_ids=args.entity_ids,
            available_from=args.available_from,
            available_to=args.available_to,
            limit=args.limit,
            as_of=as_of,
        )
        hits: list[SearchHit] = []
        for chunk in chunks:
            version = source.latest_version_for_chunk(chunk)
            if version is None:
                continue
            hits.append(
                SearchHit(
                    evidence=EvidenceRef(
                        evidence_id=chunk.chunk_id,
                        document_version_id=chunk.version_id,
                        page=chunk.page,
                        paragraph=chunk.paragraph,
                        available_at=version.available_at,
                        quote=chunk.text[:120],
                    ),
                    document=version,
                )
            )
        if not hits:
            raise ToolError(
                DATA_NOT_FOUND,
                f"未检索到相关文档片段: query={args.query!r}",
                alternatives=["更换关键词;放宽时间范围;确认文档已在截止时间前发布。"],
                detail={"query": args.query, "as_of_effective": as_of.isoformat()},
            )
        return SearchOutput(query=args.query, as_of_effective=as_of, hits=hits)

    return ToolSpec(
        name="documents.search",
        major_version=1,
        description="检索公告/财报片段,返回证据 ID 与来源定位(只含截止时间前可得的版本)",
        input_model=SearchInput,
        output_model=SearchOutput,
        timeout_seconds=10,
        retry_policy="limited_backoff",
        read_only=True,
        idempotent=True,
        handler=handler,
    )


class ReadInput(BaseModel):
    chunk_id: str | None = Field(default=None, description="证据 ID(documents.search 返回)")
    document_version_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    as_of: datetime | None = None

    @model_validator(mode="after")
    def _need_target(self) -> ReadInput:
        if self.chunk_id is None and self.document_version_id is None:
            raise ValueError("需要 chunk_id,或 document_version_id + page/paragraph")
        if self.chunk_id is None and (self.page is None or self.paragraph is None):
            raise ValueError("按文档定位读取时必须同时提供 page 与 paragraph")
        return self


class ReadOutput(BaseModel):
    as_of_effective: datetime
    chunk: Chunk
    document: DocumentVersion
    context_before: str | None = None
    context_after: str | None = None


def build_documents_read(source: DocumentSource) -> ToolSpec:
    def handler(args: ReadInput, ctx: TaskContext) -> Any:
        assert isinstance(args, ReadInput)
        as_of = _effective_as_of(args.as_of, ctx)
        if args.chunk_id is not None:
            chunk = source.get_chunk(args.chunk_id, as_of=as_of)
        else:
            assert args.document_version_id is not None and args.page and args.paragraph
            chunk = source.get_chunk_by_location(
                args.document_version_id, args.page, args.paragraph, as_of=as_of
            )
        if chunk is None:
            target = args.chunk_id or f"{args.document_version_id}@p{args.page}-para{args.paragraph}"
            raise ToolError(
                DATA_NOT_FOUND,
                f"证据不存在或晚于截止时间不可得: {target}",
                alternatives=["先用 documents.search 获取截止时间内的证据 ID。"],
            )
        version = source.latest_version_for_chunk(chunk)
        if version is None:
            raise ToolError(DATA_NOT_FOUND, f"证据所属版本不可得: {chunk.version_id}")
        return ReadOutput(as_of_effective=as_of, chunk=chunk, document=version)

    return ToolSpec(
        name="documents.read",
        major_version=1,
        description="按证据 ID 或文档定位读取原文与页码/段落信息",
        input_model=ReadInput,
        output_model=ReadOutput,
        timeout_seconds=5,
        retry_policy="none",
        read_only=True,
        idempotent=True,
        handler=handler,
    )
