# M2 Skill 注册与首条真实研究任务说明

日期:2026-10-24(Asia/Shanghai)
对应设计文档:§7(Skill 设计)、§8.2(依赖检查与绑定)、§17 M2
验证:pytest 68 项(M2 新增 23 项)+ 真实模型(DeepSeek flash)完整执行
记录 `data/runtime/m2-runs/run-20261023-eab0e6/record.json`(status=succeeded)。

## 1. 退出条件对照

| 退出条件 | 验证 |
| --- | --- |
| 问题可以触发适合的 Skill | 真实运行:业绩+更正公告问题 → Agent 实际 read_file 了 earnings-analysis 与 announcement-impact 两个 Skill 正文并按方法执行(loaded_skills 记录) |
| 不匹配时不强行选择 | 离线测试:不读 Skill 直接研究 → 记录 `no_skill_selected: true`,执行正常完成 |
| 缺少必需工具有明确原因 | 离线测试:必需工具缺失(或主版本不符)→ 该 Skill 标记不可用并给出原因;显式指定不可用 Skill → 任务创建即失败,不静默替换 |
| 新增合格 Skill 不修改执行循环 | 离线测试:向目录放入新 Skill 包 → 自动进入候选与绑定,执行代码零修改 |

## 2. 模块

```text
skills/registry.py     扫描 skills/<name>/<version>/SKILL.md;元数据(name/description/
                       metadata.app_*)解析与校验;内容哈希;版本号校验
skills/resolver.py     覆盖顺序:任务显式(含 @version)→ 用户覆盖 → 项目最新;
                       依赖检查(必需缺失→不可用,可选缺失→降级);显式指定即任务边界
skills/view.py         候选(可用者)展开为引擎只读视图 + manifest(§7.3 快照)
adapters/engines/deepagents/
  tools.py             ToolRegistry → 引擎工具:点号名→下划线名映射;统一 JSON 返回
                       ({"ok":true,result} / {"ok":false,error{code,alternatives}})
  agent.py             装配:M1 工具 + Skill 视图 + ToolStrategy(ResearchResult)
  runner.py            事件流、预算计数、Skill 加载检测(read_file /skills/<name>/)、
                       no_skill_selected、执行记录;run_config 显式 recursion_limit
application/run_service.py  prepare_run:解析→绑定→视图→任务快照;save_run_record
interfaces/cli/m2.py   m2 skills / m2 run / m2 show
budget.py              预算实现归位(m0 经兼容层复用)
```

绑定集合(§8.2):候选 Skill 必需+可选工具(存在且主版本匹配)∪ 基础工具
(documents.search/read);显式指定 Skill 时收敛为该 Skill 的工具集。

## 3. 真实执行记录摘要(run-20261023-eab0e6)

- 候选 3 个(announcement-impact / earnings-analysis / peer-comparison 全部可用),
  绑定 5 个工具;Agent 实际加载 2 个(问题同时涉及业绩变化与更正公告,自主组合)。
- 预算:12 次模型调用 / 25 次工具调用(上限 15/30);usage 137,364 输入 + 5,014 输出 token。
- 结果:8 条 key_findings(fact 4 / inference 3 / assumption 1),
  2 个 calculation_id、4 个 evidence_id(含页码段落)、6 个 observation_id 引用;
  正确采用修订版观测并量化"更正公告把利润降幅从约 -4.6% 放大到 -11.11%"。
- 工具路径:read_file(Skill)→ get_metrics×4 → calculate_growth×2 →
  documents_search×2 → documents_read×2 → …

## 4. 本里程碑发现与决策

1. **子 Agent 子图递归上限**:引擎的子 Agent(task 工具)不继承主图
   recursion_limit,默认 25 步即 GraphRecursionError(首跑实测,21 次工具调用
   后触发)。修复:run_config 统一显式 recursion_limit=150;执行边界仍以预算
   为准(§10.4),图上限只作兜底。
2. **显式指定 Skill 的语义**:偏好即任务边界——候选与绑定工具都收敛为指定
   Skill(测试:仅指定 peer-comparison 时 calculate_growth 不绑定)。
3. **Skill 加载的判定**:"实际 read_file 了 /skills/<name>/ 下的文件"才计入
   loaded_skills(§7.3),而不是出现在系统提示中。

## 5. 遗留 → M3/M4

- 执行记录目前为 JSON 文件;M3 迁移 runs/run_events/run_skills 表并加 SSE
- 用户覆盖为 JSON 文件;M3 入 skill_activations 表并加发布/回滚流程
- 依赖检查在任务启动时一次完成;"运行中动态绑定"维持 §8.2 的首版策略(不承诺)
- M4 评测:A(无 Skill)/B(全装入)/C(按需加载)/D(固定流程)四组对照
