# 金融研究 Agent

金融研究 Agent 项目,采用成熟执行引擎、按需加载的研究 Skill,
以及独立的金融工具与数据契约。

- [系统设计与实施方案](docs/金融研究Agent系统设计与实施方案.md)
- [M0 能力矩阵与选型记录](docs/M0-能力矩阵与选型记录.md)
- [M1 契约与工具说明](docs/M1-契约与工具说明.md)
- [M2 Skill 注册与执行记录](docs/M2-Skill注册与执行记录.md)
- [M3 任务服务与恢复说明](docs/M3-任务服务与恢复说明.md)

## 实施进度(按设计文档 §17 的 M0–M6)

里程碑与 Issue 在 GitHub Issues / Milestones 中跟踪;以下表格为当前快照:

| 里程碑 | 状态 | 说明 |
| --- | --- | --- |
| M0 底座兼容实验 | **完成,已验证** | Deep Agents Skill 加载 / 自定义工具 / 结构化结果 / 事件 / 预算 / 检查点恢复;离线 10 项检查 + 10 项测试,真实模型(DeepSeek flash)端到端、审批中断、跨进程恢复均已跑通 |
| M1 金融契约与离线工具 | **完成,已验证** | 完整数据契约 + 五个核心工具(可脱离 Agent 单独调用)+ 三家样本公司;零分母/缺失值/币种冲突/累计口径/修订时间全部有明确行为与测试(45 项测试通过) |
| M2 Skill 注册与首条真实研究任务 | **完成,已验证** | 三个研究包 1.0.0 + 注册表/依赖检查/版本覆盖/只读视图 + M1 工具接入引擎适配器;真实模型自主组合 2 个 Skill 完成研究并产出完整执行记录(引用 calc/obs/chk 三类 ID);不匹配不强选、缺工具有明确原因、新增 Skill 不改执行循环均有测试(68 项通过) |
| M3 任务服务、持久化与恢复 | **完成,已验证(SQLite 全链路)** | FastAPI + 独立 Worker + 任务表(租约/fencing token/幂等键)+ SSE 补读 + 崩溃恢复 + 预算持久化 + 取消/审批恢复;92 项测试,真实进程端到端跑通;Compose(PostgreSQL)待可用 Docker 实测 |
| M4 数据源替换与评测基线 | 未开始 | |
| M5 研究工作台 | 未开始 | |

## 快速开始

```bash
uv sync                 # 安装依赖(uv.lock 已锁定版本)
uv run m0 check         # 离线兼容性检查,无需模型秘钥
uv run pytest -q        # 回归测试
uv run m1 tools         # M1:列出五个核心工具
uv run m1 call finance.get_metrics '{"entity_id":"demo-company-a","metric":"net_profit"}'

# 真实模型执行(需要秘钥;.env 不入库):
cp .env.example .env    # 填入 OPENAI_API_KEY(示例为 DeepSeek 端点)
uv run m2 skills                                        # 列出 Skill 与可用性
uv run m2 run --objective "分析 demo-company-a 2026 年上半年净利润变化" \
              --entities demo-company-a                # Skill + 工具 + 执行记录
uv run m2 show <run_id>                                 # 查看完整执行记录

# M3 任务服务(API + Worker + 持久化):
uv run fa-db upgrade
uv run uvicorn finance_agent.interfaces.api.app:app --port 8010 &
uv run fa-worker &
curl -X POST localhost:8010/v1/runs -H 'Content-Type: application/json' \
     -d '{"objective":"分析 demo-company-a 2026 年上半年净利润变化","entity_ids":["demo-company-a"]}'
```

正式模块:contracts / finance / tools / retrieval / ports / skills /
application / adapters(engines、data)/ interfaces;
`src/finance_agent/m0/` 为 M0 底座实验记录,保留原样。
Skill 包在 `skills/`(版本化目录,执行时展开为只读视图)。
所有财务数据为合成样本,仅用于工程验证。
