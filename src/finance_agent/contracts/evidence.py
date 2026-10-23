"""文档证据契约(设计 §8.4)。

证据至少保存:来源链接、文档版本、内容哈希、页码/段落定位、available_at、
抓取时间。chunk 是检索与引用的最小单元,evidence_id 即 chunk_id。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_id: str = Field(description="逻辑文档 ID,同一文档多版本共用")
    version_id: str = Field(description="具体版本 ID;版本不可原地覆盖")
    title: str
    entity_id: str
    doc_type: str = Field(description="年报摘要 / 业绩预告 / 更正公告 等")
    source_url: str
    content_sha256: str
    available_at: datetime = Field(description="该版本可公开获知的时间(UTC)")
    retrieved_at: datetime
    language: str = "zh"


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    version_id: str
    page: int
    paragraph: int
    text: str


class EvidenceRef(BaseModel):
    """结果中引用证据的最小结构。"""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(description="即 chunk_id")
    document_version_id: str
    page: int
    paragraph: int
    available_at: datetime
    quote: str | None = Field(default=None, description="可选:被引用的原文摘录")
