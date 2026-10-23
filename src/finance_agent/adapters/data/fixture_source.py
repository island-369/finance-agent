"""fixture 数据源:实现 ports 的 MetricSource / DocumentSource。

职责(设计 §8.4 的执行端语义):
- 一切查询先过滤 available_at <= as_of;
- 同报告期(同 entity/metric/basis/scope/period)多版本时取最新修订;
- 文档同一 document_id 多版本时,检索只针对 as_of 时点可得的最新版本。
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime

from finance_agent.adapters.data.fixtures import (
    build_document_fixtures,
    build_observation_fixtures,
)
from finance_agent.contracts.evidence import Chunk, DocumentVersion
from finance_agent.contracts.observation import Basis, MetricObservation
from finance_agent.retrieval.keyword import rank


class FixtureMetricSource:
    def __init__(self, observations: list[MetricObservation] | None = None) -> None:
        self._observations = observations if observations is not None else build_observation_fixtures()

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
        matched = [
            o
            for o in self._observations
            if o.entity_id == entity_id
            and o.metric == metric
            and o.available_at <= as_of
            and (basis is None or o.basis == basis)
            and (scope is None or o.scope == scope)
            and (period_start is None or o.period_start >= period_start)
            and (period_end is None or o.period_end <= period_end)
        ]
        latest: dict[tuple[str, str, str, str, str], MetricObservation] = {}
        for o in matched:
            key = (o.entity_id, o.metric, o.basis, o.scope, str(o.period_end))
            if key not in latest or o.available_at > latest[key].available_at:
                latest[key] = o
        return sorted(latest.values(), key=lambda o: (o.period_end, o.metric))

    def get_observation(self, observation_id: str, *, as_of: datetime) -> MetricObservation | None:
        obs = next((o for o in self._observations if o.observation_id == observation_id), None)
        if obs is None or obs.available_at > as_of:
            return None
        return obs


class FixtureDocumentSource:
    def __init__(
        self,
        versions: list[DocumentVersion] | None = None,
        chunks: list[Chunk] | None = None,
    ) -> None:
        if versions is None or chunks is None:
            v, c = build_document_fixtures()
            versions = versions if versions is not None else v
            chunks = chunks if chunks is not None else c
        # 按版本全文计算内容哈希(设计 §8.4:内容哈希是证据要素)
        text_by_version: dict[str, str] = {}
        for chunk in chunks:
            text_by_version.setdefault(chunk.version_id, "")
            text_by_version[chunk.version_id] += chunk.text
        self._versions = [
            v.model_copy(update={"content_sha256": hashlib.sha256(text_by_version.get(v.version_id, "").encode()).hexdigest()})
            for v in versions
        ]
        self._chunks = chunks
        self._version_by_id = {v.version_id: v for v in self._versions}

    def _latest_version_ids(self, as_of: datetime) -> set[str]:
        latest: dict[str, DocumentVersion] = {}
        for v in self._versions:
            if v.available_at <= as_of and (
                v.document_id not in latest or v.available_at > latest[v.document_id].available_at
            ):
                latest[v.document_id] = v
        return {v.version_id for v in latest.values()}

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
        visible = self._latest_version_ids(as_of)
        candidates: list[Chunk] = []
        for chunk in self._chunks:
            if chunk.version_id not in visible:
                continue
            version = self._version_by_id[chunk.version_id]
            if entity_ids is not None and version.entity_id not in entity_ids:
                continue
            if available_from is not None and version.available_at < available_from:
                continue
            if available_to is not None and version.available_at > available_to:
                continue
            candidates.append(chunk)
        ranked = rank(query, [c.text for c in candidates])
        return [candidates[i] for i, _ in sorted(ranked, key=lambda t: (-t[1], t[0]))][:limit]

    def get_chunk(self, chunk_id: str, *, as_of: datetime) -> Chunk | None:
        chunk = next((c for c in self._chunks if c.chunk_id == chunk_id), None)
        if chunk is None:
            return None
        version = self._version_by_id.get(chunk.version_id)
        if version is None or version.available_at > as_of:
            return None
        return chunk

    def get_chunk_by_location(
        self, version_id: str, page: int, paragraph: int, *, as_of: datetime
    ) -> Chunk | None:
        version = self._version_by_id.get(version_id)
        if version is None or version.available_at > as_of:
            return None
        return next(
            (
                c
                for c in self._chunks
                if c.version_id == version_id and c.page == page and c.paragraph == paragraph
            ),
            None,
        )

    def get_document_version(self, version_id: str, *, as_of: datetime) -> DocumentVersion | None:
        version = self._version_by_id.get(version_id)
        if version is None or version.available_at > as_of:
            return None
        return version

    def latest_version_for_chunk(self, chunk: Chunk) -> DocumentVersion | None:
        return self._version_by_id.get(chunk.version_id)
