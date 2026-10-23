# 金融研究 Agent

面向求职作品集的金融研究 Agent 项目,采用成熟执行引擎、按需加载的研究 Skill,
以及独立的金融工具与数据契约。

- [系统设计与实施方案](docs/金融研究Agent系统设计与实施方案.md)
- [M0 能力矩阵与选型记录](docs/M0-能力矩阵与选型记录.md)

## 实施进度(按设计文档 §17 的 M0–M6)

里程碑与 Issue 在 GitHub Issues / Milestones 中跟踪;以下表格为当前快照:

| 里程碑 | 状态 | 说明 |
| --- | --- | --- |
| M0 底座兼容实验 | **完成,已验证** | Deep Agents Skill 加载 / 自定义工具 / 结构化结果 / 事件 / 预算 / 检查点恢复;离线 10 项检查 + 10 项测试,真实模型(DeepSeek flash)端到端、审批中断、跨进程恢复均已跑通 |
| M1 金融契约与离线工具 | 未开始 | |
| M2 Skill 注册与首条真实研究任务 | 未开始 | |
| M3 任务服务、持久化与恢复 | 未开始 | |
| M4 数据源替换与评测基线 | 未开始 | |
| M5 研究工作台 | 未开始 | |

## 快速开始

```bash
uv sync                 # 安装依赖(uv.lock 已锁定版本)
uv run m0 check         # 离线兼容性检查,无需模型秘钥
uv run pytest -q        # 回归测试

# 真实模型执行(需要秘钥;.env 不入库):
cp .env.example .env    # 填入 OPENAI_API_KEY(示例为 DeepSeek 端点)
uv run m0 run                                        # 一次完整研究任务
uv run m0 run --interrupt-on-tool finance_get_metrics # 演示审批中断
uv run m0 resume --thread <id>                       # 跨进程恢复
```

当前 M0 代码位于 `src/finance_agent/m0/`,是 M2 引擎适配器的种子;
Skill 包在 `skills/`(版本化目录,执行时展开为只读视图)。
所有财务数据为合成样本,仅用于工程验证。
