"""公司实体登记(M1 为 fixture;M4 接真实数据源时替换为查询)。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entity:
    entity_id: str
    name: str
    reporting_currency: str
    note: str = ""


_ENTITIES: dict[str, Entity] = {
    e.entity_id: e
    for e in [
        Entity("demo-company-a", "演示公司A", "CNY", "合成样本"),
        Entity("demo-company-b", "演示公司B", "CNY", "合成样本;财报披露较晚"),
        Entity("demo-company-c", "演示公司C", "USD", "合成样本;美元报告,用于币种冲突用例"),
    ]
}


def get_entity(entity_id: str) -> Entity | None:
    return _ENTITIES.get(entity_id)


def list_entities() -> list[Entity]:
    return list(_ENTITIES.values())
