"""装配:把具体实现接到核心接口(设计 §15 bootstrap)。

M1 装配 fixture 数据源;M4 增加真实供应商时在此切换,MetricSource/
DocumentSource 的使用方(工具、服务)不感知实现。
"""

from __future__ import annotations

from finance_agent.adapters.data.fixture_source import FixtureDocumentSource, FixtureMetricSource
from finance_agent.tools.documents_tools import build_documents_read, build_documents_search
from finance_agent.tools.finance_tools import (
    build_calculate_growth,
    build_compare_peers,
    build_get_metrics,
)
from finance_agent.tools.registry import ToolRegistry


def build_default_registry(
    metric_source: FixtureMetricSource | None = None,
    document_source: FixtureDocumentSource | None = None,
) -> ToolRegistry:
    metric = metric_source or FixtureMetricSource()
    documents = document_source or FixtureDocumentSource()
    registry = ToolRegistry()
    registry.register_all(
        [
            build_documents_search(documents),
            build_documents_read(documents),
            build_get_metrics(metric),
            build_calculate_growth(metric),
            build_compare_peers(metric),
        ]
    )
    return registry
