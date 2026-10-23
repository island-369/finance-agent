"""评测框架(设计 §16):四组对照、逐题结果、指标与报告。

A 无领域 Skill(相同引擎与工具)/ B 全部 Skill 正文装入上下文 /
C 简介发现按需加载(主配置)/ D 代表性任务的固定流程基线(确定性代码)。
评分以代码为主(引用存在性、数值、时间边界、完成标记);开放式语义
判断留给后续人工抽查(§16.3),报告中如实标注覆盖范围。
"""

from finance_agent.evals.cases import EvalCase, load_cases
from finance_agent.evals.runner import CaseResult, run_case
from finance_agent.evals.scorers import score_case

__all__ = ["CaseResult", "EvalCase", "load_cases", "run_case", "score_case"]
