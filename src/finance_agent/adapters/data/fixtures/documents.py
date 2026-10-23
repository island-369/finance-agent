"""三家样本公司的公告/文档 fixture。

包含:更正公告(与观测修订对应)、版本链(业绩预告 v1→v2)、晚于默认
截止时间披露的半年报(时间边界用例)、USD 公司报告。chunk 带页码/段落
定位,内容哈希在 fixture_source 构建时计算。
"""

from __future__ import annotations

from datetime import UTC, datetime

from finance_agent.contracts.evidence import Chunk, DocumentVersion

RETRIEVED_AT = datetime(2026, 10, 24, tzinfo=UTC)


def _v(
    document_id: str,
    version_id: str,
    title: str,
    entity_id: str,
    doc_type: str,
    available_at: datetime,
) -> DocumentVersion:
    return DocumentVersion(
        document_id=document_id,
        version_id=version_id,
        title=title,
        entity_id=entity_id,
        doc_type=doc_type,
        source_url=f"fixture://documents/{version_id}",
        content_sha256="",  # 由 fixture_source 构建时按全文计算
        available_at=available_at,
        retrieved_at=RETRIEVED_AT,
    )


def _c(version_id: str, page: int, paragraph: int, text: str) -> Chunk:
    short = version_id.replace("docv-", "")
    return Chunk(
        chunk_id=f"chk-{short}-p{page}-{paragraph}",
        version_id=version_id,
        page=page,
        paragraph=paragraph,
        text=text,
    )


def build_document_fixtures() -> tuple[list[DocumentVersion], list[Chunk]]:
    a, b, c = "demo-company-a", "demo-company-b", "demo-company-c"
    versions: list[DocumentVersion] = [
        _v("doc-a-annual-2025", "docv-a-annual-2025-v1", "演示公司A 2025 年年度报告摘要", a, "年报摘要", datetime(2026, 1, 28, tzinfo=UTC)),
        _v("doc-a-q1-correct", "docv-a-q1-correct-v1", "演示公司A 2026 年第一季度报告更正公告", a, "更正公告", datetime(2026, 5, 30, tzinfo=UTC)),
        _v("doc-a-h1-preview", "docv-a-h1-preview-v1", "演示公司A 2026 年半年度业绩预告", a, "业绩预告", datetime(2026, 7, 10, tzinfo=UTC)),
        _v("doc-a-h1-preview", "docv-a-h1-preview-v2", "演示公司A 2026 年半年度业绩预告(更正后)", a, "业绩预告", datetime(2026, 7, 12, tzinfo=UTC)),
        _v("doc-b-h1-2026", "docv-b-h1-2026-v1", "演示公司B 2026 年半年度报告", b, "半年报", datetime(2026, 9, 1, tzinfo=UTC)),
        _v("doc-c-h1-2026", "docv-c-h1-2026-v1", "演示公司C 2026 年半年度报告(美元口径)", c, "半年报", datetime(2026, 8, 20, tzinfo=UTC)),
    ]
    chunks: list[Chunk] = [
        _c("docv-a-annual-2025-v1", 1, 1, "公司 2025 年度实现营业收入 92.00 亿元,同比增长 35.3%;归属于母公司股东的净利润 7.80 亿元,同比增长 42.9%。"),
        _c("docv-a-annual-2025-v1", 3, 2, "报告期内毛利率保持稳定,费用率同比下降。经营现金流净额为正,资产负债结构稳健。"),
        _c("docv-a-q1-correct-v1", 1, 1, "公司对 2026 年第一季度报告进行更正:归属于母公司股东的净利润由 112,000,000 元调整为 98,000,000 元,系子公司内部交易抵销遗漏。"),
        _c("docv-a-q1-correct-v1", 1, 2, "除上述更正外,第一季度报告其他财务数据不变。公司就本次更正向投资者致歉。"),
        _c("docv-a-h1-preview-v1", 1, 1, "公司预计 2026 年半年度实现净利润 29,600 万元,同比增长约 0% 至 5%。"),
        _c("docv-a-h1-preview-v2", 1, 1, "更正:公司预计 2026 年半年度实现净利润 27,200 万元,同比下降约 11%,此前预告数据有误,以本公告为准。"),
        _c("docv-b-h1-2026-v1", 2, 1, "公司 2026 年上半年实现营业收入 24.50 亿元;归属于母公司股东的净利润 1.79 亿元。毛利润数据未披露。"),
        _c("docv-c-h1-2026-v1", 1, 1, "The company reported H1 2026 net profit of USD 55.0 million, turning profitable from a loss of USD 12.0 million in H1 2025. Revenue was USD 610.0 million."),
        _c("docv-c-h1-2026-v1", 2, 1, "所有财务数据以美元列报,未经审计。本报告不构成投资建议。"),
    ]
    return versions, chunks
