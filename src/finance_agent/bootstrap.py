"""装配:把具体实现接到核心接口(设计 §15 bootstrap)。

M1 装配 fixture 数据源;M4 增加真实供应商时在此切换,MetricSource/
DocumentSource 的使用方(工具、服务)不感知实现。
"""

from __future__ import annotations

import os

from finance_agent.adapters.data.fixture_source import FixtureDocumentSource, FixtureMetricSource
from finance_agent.tools.documents_tools import build_documents_read, build_documents_search
from finance_agent.tools.finance_tools import (
    build_calculate_growth,
    build_compare_peers,
    build_get_metrics,
)
from finance_agent.tools.registry import ToolRegistry


def build_default_registry(
    metric_source=None,
    document_source: FixtureDocumentSource | None = None,
) -> ToolRegistry:
    if metric_source is None:
        # 数据源切换(设计 §17 M4):fixture 默认;akshare 为真实源(仅财务观测,
        # 文档检索仍 fixture——akshare 无公告全文,接入记录如实标注)
        if os.environ.get("FINANCE_AGENT_DATA_SOURCE") == "akshare":
            from finance_agent.adapters.data.akshare_source import AkshareMetricSource

            metric = AkshareMetricSource()
        else:
            metric = FixtureMetricSource()
    else:
        metric = metric_source
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
