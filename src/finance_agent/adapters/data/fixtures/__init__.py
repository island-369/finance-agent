"""M1 合成样本。全部为合成数据,明确标注,不代表任何真实公司。"""

from finance_agent.adapters.data.fixtures.documents import build_document_fixtures
from finance_agent.adapters.data.fixtures.observations import build_observation_fixtures

__all__ = ["build_document_fixtures", "build_observation_fixtures"]
