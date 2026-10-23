"""金融类工具:finance.get_metrics / calculate_growth / compare_peers。

时间边界规则统一在 _effective_as_of:任务 as_of 由 TaskContext 注入,
模型传入的 as_of 只能收窄,不能扩大(设计 §8.4),违反时返回
INVALID_ARGUMENT,机器可读 detail 标记 as_of_exceeds_task_cutoff。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from finance_agent.contracts.common import (
    DATA_NOT_FOUND,
    INCOMPARABLE_METRICS,
    INVALID_ARGUMENT,
    ToolError,
)
from finance_agent.contracts.observation import SCOPE_CONSOLIDATED, Basis, MetricObservation
from finance_agent.contracts.task import TaskContext
from finance_agent.contracts.toolspec import ToolSpec
from finance_agent.finance.calculations import calculate_growth
from finance_agent.finance.entities import get_entity, list_entities
from finance_agent.finance.metrics import get_metric, list_metrics
from finance_agent.ports.data import MetricSource


def _effective_as_of(requested: datetime | None, ctx: TaskContext) -> datetime:
    if requested is not None and requested > ctx.as_of:
        raise ToolError(
            INVALID_ARGUMENT,
            f"请求的 as_of({requested.isoformat()})晚于任务截止时间"
            f"({ctx.as_of.isoformat()}),不允许扩大截止时间。",
            detail={"violation": "as_of_exceeds_task_cutoff"},
            alternatives=["使用不晚于任务截止时间的 as_of,或省略该参数。"],
        )
    return requested or ctx.as_of


# --------------------------------------------------------- get_metrics ----


class GetMetricsInput(BaseModel):
    entity_id: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    basis: Basis | None = Field(default=None, description="累计/单季;缺省两者都返回")
    scope: str | None = Field(default=None, description="报表口径;缺省默认合并报表")
    period_start: date | None = None
    period_end: date | None = None
    as_of: datetime | None = Field(default=None, description="不得晚于任务截止时间")


class GetMetricsOutput(BaseModel):
    entity_id: str
    metric: str
    as_of_effective: datetime
    observations: list[MetricObservation]
    notes: list[str] = Field(default_factory=list)


def build_get_metrics(source: MetricSource) -> ToolSpec:
    def handler(args: GetMetricsInput, ctx: TaskContext) -> GetMetricsOutput:
        assert isinstance(args, GetMetricsInput)
        if get_metric(args.metric) is None:
            raise ToolError(
                INVALID_ARGUMENT,
                f"未登记的指标: {args.metric}",
                detail={"registered_metrics": [m.name for m in list_metrics()]},
            )
        if get_entity(args.entity_id) is None:
            raise ToolError(
                DATA_NOT_FOUND,
                f"未知公司: {args.entity_id}",
                detail={"known_entities": [e.entity_id for e in list_entities()]},
            )
        as_of = _effective_as_of(args.as_of, ctx)
        observations = source.get_observations(
            entity_id=args.entity_id,
            metric=args.metric,
            basis=args.basis,
            scope=args.scope or SCOPE_CONSOLIDATED,
            period_start=args.period_start,
            period_end=args.period_end,
            as_of=as_of,
        )
        notes = [o.note for o in observations if o.note]
        if not observations:
            raise ToolError(
                DATA_NOT_FOUND,
                f"截止 {as_of.isoformat()} 无可得观测: entity={args.entity_id}, "
                f"metric={args.metric}, basis={args.basis or 'any'}, scope={args.scope or SCOPE_CONSOLIDATED}",
                alternatives=[
                    "确认报告期是否已披露(如对手方财报发布晚于截止时间)。",
                    "尝试更早的报告期或其他 basis。",
                ],
                detail={"entity_id": args.entity_id, "metric": args.metric},
            )
        return GetMetricsOutput(
            entity_id=args.entity_id,
            metric=args.metric,
            as_of_effective=as_of,
            observations=observations,
            notes=notes,
        )

    return ToolSpec(
        name="finance.get_metrics",
        major_version=1,
        description="查询标准化财务观测(修订按截止时间选择;口径与币种显式)",
        input_model=GetMetricsInput,
        output_model=GetMetricsOutput,
        timeout_seconds=10,
        retry_policy="none",
        read_only=True,
        idempotent=True,
        handler=handler,
    )


# ---------------------------------------------------- calculate_growth ----


class CalculateGrowthInput(BaseModel):
    current_observation_id: str = Field(min_length=1)
    base_observation_id: str = Field(min_length=1)
    as_of: datetime | None = None


def build_calculate_growth(source: MetricSource) -> ToolSpec:
    def handler(args: CalculateGrowthInput, ctx: TaskContext) -> Any:
        assert isinstance(args, CalculateGrowthInput)
        as_of = _effective_as_of(args.as_of, ctx)
        current = source.get_observation(args.current_observation_id, as_of=as_of)
        base = source.get_observation(args.base_observation_id, as_of=as_of)
        missing = [
            oid
            for oid, obs in ((args.current_observation_id, current), (args.base_observation_id, base))
            if obs is None
        ]
        if missing:
            raise ToolError(
                DATA_NOT_FOUND,
                f"观测不存在或晚于截止时间不可得: {', '.join(missing)}",
                detail={"missing_observation_ids": missing, "as_of_effective": as_of.isoformat()},
                alternatives=["先用 finance.get_metrics 获取截止时间内可得的观测 ID。"],
            )
        return calculate_growth(current, base)

    return ToolSpec(
        name="finance.calculate_growth",
        major_version=1,
        description="按公式 (本期-同期)/同期 计算增长率;零分母/缺失/口径不可比时返回不可计算原因",
        input_model=CalculateGrowthInput,
        output_model=None,
        timeout_seconds=5,
        retry_policy="none",
        read_only=True,
        idempotent=True,
        handler=handler,
    )


# ------------------------------------------------------ compare_peers ----


class ComparePeersInput(BaseModel):
    entity_ids: list[str] = Field(min_length=2, max_length=10)
    metric: str
    basis: Basis
    period_start: date
    period_end: date
    scope: str = Field(default=SCOPE_CONSOLIDATED)
    as_of: datetime | None = None

    @field_validator("entity_ids")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("entity_ids 不能有重复")
        return v


class PeerRow(BaseModel):
    entity_id: str
    observation_id: str | None = None
    value: str | None = Field(default=None, description="Decimal 字符串")
    unit: str | None = None
    currency: str | None = None
    missing_reason: str | None = Field(default=None, description="未披露 / 晚于截止时间未发布 / 无该口径")


class ComparePeersOutput(BaseModel):
    metric: str
    basis: Basis
    period_start: date
    period_end: date
    scope: str
    as_of_effective: datetime
    rows: list[PeerRow]
    currency_conflicts: list[str] = Field(default_factory=list)


def build_compare_peers(source: MetricSource) -> ToolSpec:
    def handler(args: ComparePeersInput, ctx: TaskContext) -> ComparePeersOutput:
        assert isinstance(args, ComparePeersInput)
        as_of = _effective_as_of(args.as_of, ctx)
        rows: list[PeerRow] = []
        currencies: dict[str, list[str]] = {}
        for entity_id in args.entity_ids:
            if get_entity(entity_id) is None:
                raise ToolError(
                    DATA_NOT_FOUND,
                    f"未知公司: {entity_id}",
                    detail={"known_entities": [e.entity_id for e in list_entities()]},
                )
            observations = source.get_observations(
                entity_id=entity_id,
                metric=args.metric,
                basis=args.basis,
                scope=args.scope,
                period_start=args.period_start,
                period_end=args.period_end,
                as_of=as_of,
            )
            exact = [o for o in observations if o.period_start == args.period_start and o.period_end == args.period_end]
            if not exact:
                rows.append(PeerRow(entity_id=entity_id, missing_reason="无该报告期观测(未披露或晚于截止时间发布)"))
                continue
            obs = exact[-1]
            if obs.value is None:
                rows.append(PeerRow(entity_id=entity_id, observation_id=obs.observation_id, missing_reason=f"数值缺失: {obs.note or '未披露'}"))
                continue
            if obs.currency:
                currencies.setdefault(obs.currency, []).append(entity_id)
            rows.append(
                PeerRow(
                    entity_id=entity_id,
                    observation_id=obs.observation_id,
                    value=str(obs.value),
                    unit=obs.unit,
                    currency=obs.currency,
                )
            )
        conflicts = [f"{cur}: {'+'.join(ents)}" for cur, ents in currencies.items()] if len(currencies) > 1 else []
        if conflicts:
            raise ToolError(
                INCOMPARABLE_METRICS,
                f"同业比较的币种不一致: {'; '.join(conflicts)}。不能默认换算或直接比较。",
                detail={"currency_conflicts": conflicts},
                alternatives=[
                    "按币种分组分别比较。",
                    "接入汇率数据源后再做统一币种比较(当前不可用)。",
                ],
            )
        return ComparePeersOutput(
            metric=args.metric,
            basis=args.basis,
            period_start=args.period_start,
            period_end=args.period_end,
            scope=args.scope,
            as_of_effective=as_of,
            rows=rows,
        )

    return ToolSpec(
        name="finance.compare_peers",
        major_version=1,
        description="同口径对齐多公司同报告期指标;币种冲突返回结构化错误,缺失逐行说明",
        input_model=ComparePeersInput,
        output_model=ComparePeersOutput,
        timeout_seconds=10,
        retry_policy="none",
        read_only=True,
        idempotent=True,
        handler=handler,
    )
