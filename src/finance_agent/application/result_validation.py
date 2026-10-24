"""结果校验链(设计 §11 第 2–4 步)与修复反馈(§6.2 第 7 步)。

校验在候选结果提交时执行,输入是"本次运行的工具输出记录"(RunTrace):

- **不可修复错误(hard)**:引用了本次运行中不存在的观测/计算/证据 ID——
  已确认的错误数据,按 §11 不提交为成功报告;
- **可修复问题(repairable)**:关键判断缺引用、正文数字无法映射到已登记
  记录——反馈给模型修正,最多 result_repair_rounds 轮(计入预算),仍不通过
  则 completed_partial(quality_flags 标记 pending_review,§11)。

数字映射是启发式(§11 明示"纯文本数字的语义识别不保证完整覆盖",漏检在
评测中记录):支持观测值的 元/万/亿/万亿 换算、计算值的百分比、以及同一
发现内(或全局同指标)两个观测的 差值/比值/百分比 推导;年份整数豁免。
本模块为纯函数,不依赖任何框架。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation

# 数字两侧不得紧邻字母/数字(排除 Q2、H1、obs-xxx 残片等标记);引用 ID 单独剔除
_NUM_RE = re.compile(r"(?<![A-Za-z0-9._])-?\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9])")
_REF_ID_RE = re.compile(r"\b(?:obs|calc|chk|docv)-[A-Za-z0-9_-]+")
# 证据定位引用(第 N 页/段/条/项/行)与日期不是财务数字,豁免
_LOC_RE = re.compile(r"第\s*\d+\s*[页段条项行]")
_DATE_RE = re.compile(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}")
_SCALE_FACTORS = (Decimal(1), Decimal("1e4"), Decimal("1e8"), Decimal("1e12"))
# 相对容差(数值换算)与绝对容差(百分点)
_REL_TOL = Decimal("0.005")
_PCT_TOL = Decimal("0.051")


@dataclass(frozen=True)
class RunTrace:
    """一次运行中工具实际返回的记录(校验的"允许引用集合")。"""

    observations: dict[str, dict] = field(default_factory=dict)
    calculations: dict[str, dict] = field(default_factory=dict)
    evidence_ids: frozenset[str] = frozenset()
    document_version_ids: frozenset[str] = frozenset()
    evidence_texts: tuple[str, ...] = field(default=())


@dataclass
class ValidationResult:
    hard: list[str] = field(default_factory=list)
    repairable: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.hard and not self.repairable


def _dt(value: str | datetime) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))  # py3.11+ 原生支持 Z 后缀
    except ValueError:
        return None


def build_run_trace(tool_outputs: list[dict], *, as_of: datetime) -> RunTrace:
    """从录制到的工具输出构建允许引用集合;只保留 available_at ≤ as_of 的记录。"""
    observations: dict[str, dict] = {}
    calculations: dict[str, dict] = {}
    evidence: set[str] = set()
    versions: set[str] = set()
    evidence_texts: list[str] = []

    def _obs(o: dict) -> None:
        oid = o.get("observation_id")
        if not oid:
            return
        av = _dt(o.get("available_at") or "")
        if av is not None and av > as_of:
            return
        observations.setdefault(oid, o)

    for out in tool_outputs:
        if not out.get("ok"):
            continue
        payload = out.get("result") or {}
        tool = out.get("tool")
        if tool == "finance.get_metrics":
            for o in payload.get("observations") or []:
                _obs(o)
        elif tool == "finance.compare_peers":
            for row in payload.get("rows") or []:
                if row.get("observation_id") and row.get("value") is not None:
                    observations.setdefault(row["observation_id"], dict(row))
        elif tool == "finance.calculate_growth":
            cid = payload.get("calculation_id")
            if cid:
                calculations.setdefault(cid, payload)
        elif tool == "documents.search":
            for hit in payload.get("hits") or []:
                ev = hit.get("evidence") or {}
                av = _dt(ev.get("available_at") or "")
                if ev.get("evidence_id") and (av is None or av <= as_of):
                    evidence.add(ev["evidence_id"])
                    if ev.get("quote"):
                        evidence_texts.append(ev["quote"])
                doc = hit.get("document") or {}
                dav = _dt(doc.get("available_at") or "")
                if doc.get("version_id") and (dav is None or dav <= as_of):
                    versions.add(doc["version_id"])
        elif tool == "documents.read":
            chunk = payload.get("chunk") or {}
            if chunk.get("chunk_id"):
                evidence.add(chunk["chunk_id"])
                if chunk.get("text"):
                    evidence_texts.append(chunk["text"])
            doc = payload.get("document") or {}
            if doc.get("version_id"):
                versions.add(doc["version_id"])
        elif tool == "documents.search":
            pass  # 摘要 quote 在上方 evidence 分支已采集
    return RunTrace(observations, calculations, frozenset(evidence), frozenset(versions), tuple(evidence_texts))


def _dec(value) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _close(a: Decimal, b: Decimal, rel: Decimal = _REL_TOL) -> bool:
    base = max(abs(b), Decimal(1))
    return abs(a - b) <= base * rel


def _pct_close(text_n: Decimal, record: Decimal) -> bool:
    """文本百分数 vs 记录值(比率或百分点),符号不敏感。"""
    cand = abs(record) * 100 if abs(record) < 1 else abs(record)
    return abs(cand - abs(text_n)) <= _PCT_TOL


def _scale_match(n: Decimal, value: Decimal) -> bool:
    """文本数字按 元/万/亿/万亿 换算后与记录值比对(符号不敏感)。"""
    a = abs(n)
    b = abs(value)
    for mult in _SCALE_FACTORS:
        if _close(a * mult, b):
            return True
    return False


def _derivation_match(n: Decimal, values: list[Decimal]) -> bool:
    """n 能否由两个记录值的 差/比/百分比 推导(净利率、增速等派生数)。"""
    for a in values:
        for b in values:
            if b == 0:
                continue
            for cand in ((a - b) / b * 100, a / b * 100, (a - b) / b):
                if abs(abs(cand) - abs(n)) <= _PCT_TOL:
                    return True
            if abs(a - b) > 0 and _scale_match(n, abs(a - b)):
                return True
    return False


def _extract_numbers(text: str) -> list[Decimal]:
    clean = _DATE_RE.sub(" ", _LOC_RE.sub(" ", _REF_ID_RE.sub(" ", text or "")))
    out = []
    for m in _NUM_RE.findall(clean):
        d = _dec(m.replace(",", ""))
        if d is not None:
            out.append(d)
    return out


def _in_evidence_text(n: Decimal, trace: RunTrace) -> bool:
    """数字(含千分位/亿万元换算后的形态)是否出现在本次引用的证据原文中。"""
    if not trace.evidence_texts:
        return False
    for mult in _SCALE_FACTORS:
        scaled = abs(n) * mult
        if scaled == scaled.to_integral_value():
            # 整数形态:精确值 + 千分位写法(无舍入)
            forms = (str(scaled), f"{scaled:,.0f}")
        else:
            forms = (str(scaled),)  # 非整数禁止舍入匹配,避免"2.72→3"类误报
        if any(form in text for text in trace.evidence_texts for form in forms):
            return True
    return False


def _number_mapped(n: Decimal, trace: RunTrace, context_values: list[Decimal]) -> bool:
    if 1900 <= n <= 2100 and n == int(n):
        return True  # 年份豁免
    if _in_evidence_text(n, trace):
        return True  # 引用的公告原文中出现的数字(§11:证据可核查)
    record_values = [d for v in context_values if (d := _dec(v)) is not None]
    for v in record_values:
        if _scale_match(n, v):
            return True
    for c in trace.calculations.values():
        cv = _dec(c.get("value"))
        if cv is None:
            continue
        if _pct_close(n, cv) or _close(abs(n), abs(cv)):
            return True
        # 公告/正文的整数约数("约 11%"):百分比取整匹配
        if abs(n) == abs((cv * 100).quantize(Decimal(1))):
            return True
    return _derivation_match(n, record_values) or _derivation_match(n, _all_trace_values(trace))


def _all_trace_values(trace: RunTrace) -> list[Decimal]:
    vals: list[Decimal] = []
    for o in trace.observations.values():
        d = _dec(o.get("value"))
        if d is not None:
            vals.append(d)
    for c in trace.calculations.values():
        d = _dec(c.get("value"))
        if d is not None:
            vals.append(d)
    return vals


def validate_result(result: dict, trace: RunTrace) -> ValidationResult:
    """按 §11 第 2–4 步校验候选结果;返回不可修复与可修复问题清单。"""
    report = ValidationResult()
    if not result:
        report.hard.append("结果为空")
        return report

    def _known(ref: str) -> bool:
        return (
            ref in trace.observations
            or ref in trace.calculations
            or ref in trace.evidence_ids
            or ref in trace.document_version_ids
        )

    findings = result.get("key_findings") or []
    for f in findings:
        for ref in f.get("refs") or []:
            if not _known(ref):
                report.hard.append(f"引用 {ref} 不存在于本次工具输出(发现:{str(f.get('statement'))[:40]}…)")
    for ref in result.get("metric_refs") or []:
        if not _known(ref):
            report.hard.append(f"metric_refs 中的 {ref} 不存在于本次工具输出")
    for ref in result.get("calculation_refs") or []:
        if ref not in trace.calculations:
            report.hard.append(f"calculation_refs 中的 {ref} 不存在于本次运行的计算记录")
    for ev in result.get("evidence_refs") or []:
        ref = ev.get("evidence_id") if isinstance(ev, dict) else ev
        if ref and not _known(ref):
            report.hard.append(f"evidence_refs 中的 {ref} 不存在于本次工具输出")

    for i, f in enumerate(findings, 1):
        if f.get("kind") in ("fact", "inference") and not (f.get("refs") or []):
            report.repairable.append(
                f"第 {i} 条 {f.get('kind')} 发现缺少引用:每个关键判断都应引用 observation/calculation/evidence ID,"
                "或改标为 assumption"
            )

    findings_vals = {
        i: [
            d
            for ref in (f.get("refs") or [])
            if (o := trace.observations.get(ref)) and (d := _dec(o.get("value"))) is not None
        ]
        for i, f in enumerate(findings, 1)
    }
    global_vals = _all_trace_values(trace)
    texts = [result.get("summary") or ""] + [str(f.get("statement")) for f in findings]
    for text in texts:
        for n in _extract_numbers(text):
            if _number_mapped(n, trace, global_vals):
                continue
            in_finding = any(
                _number_mapped(n, trace, vals) for vals in findings_vals.values()
            )
            if not in_finding:
                report.repairable.append(
                    f"数字 {n} 无法映射到本次工具返回的观测/计算记录:"
                    "请引用来源 ID,改用工具计算,或删除该数字"
                )
    return report


def render_repair_feedback(report: ValidationResult, round_no: int, max_rounds: int) -> str:
    """把校验问题渲染为修复反馈消息(§6.2:反馈给模型,计入预算)。"""
    lines = [
        (
            f"你提交的 ResearchResult 未通过系统校验(第 {round_no}/{max_rounds} 轮)。"
            "请只修正以下问题后重新调用 ResearchResult 提交,其余内容保持不变:"
        ),
    ]
    if report.hard:
        lines.append("【必须修正·引用错误】")
        lines += [f"- {h}" for h in report.hard]
        lines.append("  引用必须来自本次工具调用的实际返回,不得凭记忆填写 ID。")
    if report.repairable:
        lines.append("【请修正或改述】")
        seen: list[str] = []
        for r in report.repairable:
            if r not in seen:
                seen.append(r)
        lines += [f"- {r}(出现 {report.repairable.count(r)} 处)" for r in seen]
    return "\n".join(lines)
