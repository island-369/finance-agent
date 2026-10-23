"""金融数据源接口。

修订/时间边界语义集中在数据源实现:所有查询都接受 as_of,并只返回
available_at <= as_of 的版本;同报告期多版本取截止时间内最新修订。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable

from finance_agent.contracts.evidence import Chunk, DocumentVersion
from finance_agent.contracts.observation import Basis, MetricObservation


@runtime_checkable
class MetricSource(Protocol):
    def get_observations(
        self,
        *,
        entity_id: str,
        metric: str,
        basis: Basis | None = None,
        scope: str | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
        as_of: datetime,
    ) -> list[MetricObservation]:
        """按条件查询观测;已做 as_of 过滤与"最新修订"选择,按 period_end 升序。"""
        ...

    def get_observation(self, observation_id: str, *, as_of: datetime) -> MetricObservation | None:
        """按 ID 取单条观测;available_at 晚于 as_of 时返回 None。"""
        ...


@runtime_checkable
class DocumentSource(Protocol):
    def search_chunks(
        self,
        *,
        query: str,
        entity_ids: list[str] | None = None,
        available_from: datetime | None = None,
        available_to: datetime | None = None,
        limit: int = 8,
        as_of: datetime,
    ) -> list[Chunk]:
        """先过滤(实体、版本可得性 ≤ as_of、可得时间范围),再按关键词评分排序。

        同一文档存在多版本时,只检索 as_of 时点可得的最新版本。
        """
        ...

    def get_chunk(self, chunk_id: str, *, as_of: datetime) -> Chunk | None:
        ...

    def get_chunk_by_location(
        self, version_id: str, page: int, paragraph: int, *, as_of: datetime
    ) -> Chunk | None:
        """按文档版本 + 页/段落定位取 chunk;版本晚于 as_of 时返回 None。"""
        ...

    def get_document_version(
        self, version_id: str, *, as_of: datetime
    ) -> DocumentVersion | None:
        ...

    def latest_version_for_chunk(self, chunk: Chunk) -> DocumentVersion | None:
        """chunk 所属文档版本;供 read 工具组装输出。"""
        ...
