import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Avatar, Button, Tag, Typography, App as AntApp } from "antd";
import { Bubble, Sender, ThoughtChain } from "@ant-design/x";
import type { BubbleItemType, ThoughtChainItemType } from "@ant-design/x";
import {
  CheckCircleOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  RobotOutlined,
  UserOutlined,
  InfoCircleOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { api, streamEvents, type Ev } from "../api";

type StepStatus = "loading" | "success" | "error";

interface Step {
  key: string;
  title: string;
  description?: string;
  content?: React.ReactNode;
  status: StepStatus;
}

interface Finding {
  statement: string;
  kind: string;
  refs: string[];
}
interface EvidenceRefT {
  evidence_id: string;
  page: number;
  paragraph: number;
}
interface ResultBody {
  summary?: string;
  key_findings?: Finding[];
  evidence_refs?: EvidenceRefT[];
  information_gaps?: string[];
}

const KIND_LABEL: Record<string, string> = {
  fact: "事实",
  inference: "推断",
  assumption: "假设",
};

function brief(text: unknown, limit = 160): string {
  const s = typeof text === "string" ? text : JSON.stringify(text);
  return (s ?? "").length > limit ? s.slice(0, limit) + "…" : s;
}

function buildSteps(events: Ev[]): Step[] {
  const steps: Step[] = [];
  const openTool: Record<string, Step | undefined> = {};
  for (const e of events) {
    const p = e.payload as Record<string, unknown>;
    if (e.type === "engine.tool_start") {
      const step: Step = {
        key: `t-${e.seq}`,
        title: String(p.name ?? "工具调用"),
        description: brief(p.input_brief),
        status: "loading",
      };
      steps.push(step);
      openTool[String(p.name)] = step;
    } else if (e.type === "engine.tool_end") {
      const name = String(p.name ?? "");
      const target = openTool[name];
      const out = brief(p.output_brief);
      if (target) {
        target.status = "success";
        target.content = <div className="step-mono">{out}</div>;
        openTool[name] = undefined;
      } else {
        steps.push({
          key: `t-${e.seq}`,
          title: name,
          content: <div className="step-mono">{out}</div>,
          status: "success",
        });
      }
    } else if (e.type === "run.attempt_started") {
      const carried = (p.budget_carried as Record<string, number> | undefined) ?? {};      
      const resumed = Number(p.attempt ?? 1) > 1;
      steps.push({
        key: `a-${e.seq}`,
        title: resumed ? `第 ${e.attempt} 次尝试(从检查点恢复)` : "任务开始",
        description: resumed
          ? `沿用已消耗预算:模型 ${carried.model_calls ?? 0} / 工具 ${carried.tool_calls ?? 0}`
          : undefined,
        status: "success",
      });
    } else if (e.type === "run.skills_loaded") {
      const loaded = (p.loaded as string[] | undefined) ?? [];
      steps.push({
        key: `sk-${e.seq}`,
        title: loaded.length ? `已加载 Skill:${loaded.join("、")}` : "未使用 Skill,按通用方法研究",
        status: "success",
      });
    } else if (e.type === "run.waiting_input") {
      steps.push({ key: `w-${e.seq}`, title: "工具调用等待审批", status: "loading" });
    } else if (e.type === "run.resume_requested") {
      steps.push({
        key: `r-${e.seq}`,
        title: p.action === "approve" ? "审批通过,继续执行" : "审批拒绝",
        status: p.action === "approve" ? "success" : "error",
      });
    } else if (e.type === "run.validating") {
      const hard = (p.hard as string[] | undefined) ?? [];
      const repairable = (p.repairable as string[] | undefined) ?? [];
      const n = hard.length + repairable.length;
      steps.push({
        key: `v-${e.seq}`,
        title: n === 0 ? "结果校验通过(引用/数值/时间边界)" : `结果校验:发现 ${n} 个问题`,
        description: n === 0 ? undefined : [...hard, ...repairable].slice(0, 3).join(";"),
        status: n === 0 ? "success" : "loading",
      });
    } else if (e.type === "run.repair_feedback") {
      steps.push({
        key: `rf-${e.seq}`,
        title: `第 ${p.round} 轮修复:问题清单已反馈给模型(计入预算)`,
        status: "loading",
      });
    } else if (e.type === "run.requeued") {
      steps.push({ key: `rq-${e.seq}`, title: "执行中断,已重新排队", status: "error" });
    }
  }
  return steps;
}

const AVATAR_AI = <Avatar icon={<RobotOutlined />} style={{ background: "#1a66d6", flexShrink: 0 }} />;
const AVATAR_USER = <Avatar icon={<UserOutlined />} style={{ background: "#eceff2", flexShrink: 0 }} />;

function ResultMessage({ res }: { res: ResultBody }) {
  const pending = ((res as { quality_flags?: string[] }).quality_flags ?? []).includes("pending_review");
  return (
    <div>
      {res.summary && (
        <Typography.Paragraph style={{ marginBottom: 12 }}>{res.summary}</Typography.Paragraph>
      )}
      {(res.key_findings ?? []).map((f, i) => (
        <div key={i} style={{ marginBottom: 10 }}>
          <Tag
            color={f.kind === "fact" ? "green" : f.kind === "inference" ? "blue" : "orange"}
            style={{ marginRight: 8 }}
          >
            {KIND_LABEL[f.kind] ?? f.kind}
          </Tag>
          <span style={{ fontSize: 13.5 }}>{f.statement}</span>
          {f.refs.length > 0 && (
            <div style={{ marginTop: 2 }}>
              {f.refs.map((r) => (
                <span key={r} className="ref-chip">
                  {r}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
      {res.evidence_refs && res.evidence_refs.length > 0 && (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5, marginBottom: 0 }}>
          证据定位:
          {res.evidence_refs
            .map((e) => `${e.evidence_id}(p${e.page}-¶${e.paragraph})`)
            .join(";")}
        </Typography.Paragraph>
      )}
      {res.information_gaps && res.information_gaps.length > 0 && (
        <Typography.Paragraph type="warning" style={{ fontSize: 12.5, marginBottom: 0, marginTop: 8 }}>
          信息缺口:{res.information_gaps.join(";")}
        </Typography.Paragraph>
      )}
      {pending && (
        <Typography.Paragraph type="warning" style={{ fontSize: 12.5, marginBottom: 0, marginTop: 8 }}>
          ⚠ 部分数字未能映射到已登记记录,结果标记为待复核(completed_partial)
        </Typography.Paragraph>
      )}
    </div>
  );
}

export default function RunPage() {
  const { runId: routeRunId } = useParams();
  const nav = useNavigate();
  const { message: antMessage } = AntApp.useApp();
  const [run, setRun] = useState<Awaited<ReturnType<typeof api.getRun>> | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const [result, setResult] = useState<ResultBody | null>(null);
  const [senderValue, setSenderValue] = useState("");
  const closeRef = useRef<null | (() => void)>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const stopStream = () => closeRef.current?.();
  const notifyUpdate = () => window.dispatchEvent(new Event("runs-updated"));

  const loadRun = useCallback(async (id: string) => {
    try {
      const brief = await api.getRun(id);
      setRun(brief);
      const arts = await api.artifacts(id);
      setResult((arts.artifacts[0]?.content as ResultBody) ?? null);
    } catch {
      nav("/", { replace: true });
    }
  }, [nav]);

  const startSSE = useCallback((id: string) => {
    stopStream();
    closeRef.current = streamEvents(
      id,
      (e) => setEvents((prev) => (prev.some((x) => x.seq === e.seq) ? prev : [...prev, e])),
      () => {
        if (routeRunId) loadRun(routeRunId);
        notifyUpdate();
      },
    );
  }, [loadRun, routeRunId]);

  useEffect(() => {
    setEvents([]);
    setResult(null);
    setRun(null);
    if (routeRunId) {
      loadRun(routeRunId);
      startSSE(routeRunId);
    }
    return stopStream;
  }, [routeRunId, loadRun, startSSE]);

  // 自动滚到底部
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events, result, run?.status]);

  const active = run ? ["queued", "running", "validating"].includes(run.status) : false;
  const steps = useMemo(() => buildSteps(events), [events]);
  const hasUserMsg = Boolean(routeRunId || run);
  const isWaiting = run?.status === "waiting_input";

  const createRun = async (text: string) => {
    const res = await api.createRun(
      {
        objective: text,
        entity_ids: deriveEntities(text),
      },
      crypto.randomUUID(),
    );
    nav(`/runs/${res.run_id}`);
    notifyUpdate();
  };

  const handleSubmit = async (text: string) => {
    if (!text.trim()) return;
    setSenderValue("");
    try {
      await createRun(text.trim());
    } catch (e) {
      antMessage.error(String(e));
    }
  };

  const doResume = async (approve: boolean) => {
    if (!run) return;
    try {
      await api.resumeRun(run.run_id, approve);
      startSSE(run.run_id);
      notifyUpdate();
    } catch (e) {
      antMessage.error(String(e));
    }
  };

  const doCancel = async () => {
    if (!run) return;
    try {
      await api.cancelRun(run.run_id);
      antMessage.info("已请求取消;Worker 将在下次模型/工具调用前停止");
      notifyUpdate();
    } catch (e) {
      antMessage.error(String(e));
    }
  };

  // ------- 对话气泡流 -------
  const bubbles: BubbleItemType[] = [];
  if (hasUserMsg && run) {
    bubbles.push({
      key: "user",
      role: "user",
      placement: "end",
      avatar: AVATAR_USER,
      variant: "filled",
      content: run.objective,
    });
  }
  if (steps.length > 0) {
    bubbles.push({
      key: "steps",
      role: "ai",
      placement: "start",
      avatar: AVATAR_AI,
      variant: "borderless",
      header: <Typography.Text type="secondary" style={{ fontSize: 12 }}>执行过程</Typography.Text>,
      content: (
        <ThoughtChain
          style={{ fontSize: 13 }}
          items={steps.map((s): ThoughtChainItemType => ({
            key: s.key,
            title: s.title,
            description: s.description,
            content: s.content,
            status: s.status,
            icon:
              s.status === "loading" ? (
                <LoadingOutlined spin />
              ) : s.status === "error" ? (
                <CloseCircleOutlined style={{ color: "#c5221f" }} />
              ) : (
                <CheckCircleOutlined style={{ color: "#14804a" }} />
              ),
          }))}
        />
      ),
    });
  }
  if (result) {
    bubbles.push({
      key: "result",
      role: "ai",
      placement: "start",
      avatar: AVATAR_AI,
      variant: "outlined",
      header: <Typography.Text strong style={{ fontSize: 13 }}>研究结果</Typography.Text>,
      content: <ResultMessage res={result} />,
    });
  }
  if (run?.status === "failed" && run.error) {
    bubbles.push({
      key: "failed",
      role: "ai",
      placement: "start",
      avatar: <Avatar icon={<WarningOutlined />} style={{ background: "#fce8e6", color: "#c5221f", flexShrink: 0 }} />,
      variant: "outlined",
      header: <Typography.Text type="danger" style={{ fontSize: 13 }}>执行失败</Typography.Text>,
      content: <span style={{ fontSize: 13 }}>{run.error}</span>,
    });
  }
  if (isWaiting) {
    bubbles.push({
      key: "approve",
      role: "ai",
      placement: "start",
      avatar: <Avatar icon={<InfoCircleOutlined />} style={{ background: "#fdf1dc", color: "#d48b00", flexShrink: 0 }} />,
      variant: "outlined",
      header: <Typography.Text type="warning" style={{ fontSize: 13 }}>等待你的审批</Typography.Text>,
      content: (
        <div>
          <span style={{ fontSize: 13 }}>
            Agent 的下一次工具调用需要确认(演示:工具审批中断 → 跨进程恢复)。
          </span>
          <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
            <Button type="primary" size="small" onClick={() => doResume(true)}>
              批准并继续
            </Button>
            <Button size="small" danger onClick={() => doResume(false)}>
              拒绝
            </Button>
          </div>
        </div>
      ),
    });
  }
  if (active) {
    bubbles.push({
      key: "pending",
      role: "ai",
      placement: "start",
      avatar: AVATAR_AI,
      loading: true,
      variant: "borderless",
      content: "正在执行…",
    });
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <div
        ref={scrollRef}
        className="chat-scroll"
        style={{ background: "#f7f8fa" }}
      >
        <div className="chat-column">
          {!hasUserMsg && (
            <div style={{ textAlign: "center", padding: "64px 0 28px" }}>
              <Typography.Title level={3} style={{ marginBottom: 4 }}>
                金融研究 Agent
              </Typography.Title>
              <Typography.Text type="secondary">
                描述一个研究问题,Agent 自主选择 Skill 与工具完成分析,结论带可核查引用
              </Typography.Text>
            </div>
          )}
          <Bubble.List items={bubbles} style={{ paddingBottom: 16 }} />
        </div>
      </div>

      <div style={{ padding: "8px 16px 18px", background: "#f7f8fa" }}>
        <div className="chat-column" style={{ padding: 0 }}>
          {run && (
            <div style={{ marginBottom: 6, display: "flex", alignItems: "center", gap: 8, fontSize: 12, color: "#8a97a5" }}>
              <span className="mono">{run.run_id}</span>
              <Tag color={run.status === "succeeded" ? "green" : run.status === "failed" ? "red" : run.status === "completed_partial" ? "orange" : "blue"}>
                {run.status}
              </Tag>
              <span>
                模型 {run.budget.used.model_calls ?? 0}/{run.budget.limits.max_model_calls} · 工具{" "}
                {run.budget.used.tool_calls ?? 0}/{run.budget.limits.max_tool_calls}
                {run.attempt > 1 ? ` · 已重试 ${run.attempt - 1} 次` : ""}
              </span>
              {active && (
                <Button size="small" danger style={{ marginLeft: "auto" }} onClick={doCancel}>
                  停止
                </Button>
              )}
            </div>
          )}
          <Sender
            value={senderValue}
            onChange={setSenderValue}
            onSubmit={handleSubmit}
            placeholder={
              hasUserMsg
                ? "输入新的研究问题(将创建新任务)…"
                : "例如:分析 demo-company-a 2026 年上半年净利润变化,识别与收入变化不一致的环节"
            }
            loading={active}
            onCancel={doCancel}
          />
          <div style={{ fontSize: 11.5, color: "#8a97a5", marginTop: 6, textAlign: "center" }}>
            数据为合成样本 · 结论中的数值均可通过引用(obs/calc/chk)回溯核查
          </div>
        </div>
      </div>
    </div>
  );
}

/** 从目标文本推断公司 ID:demo-company-* 或 cn-\d+(演示场景);其余用默认样本公司 */
function deriveEntities(text: string): string[] {
  const matched = text.match(/(?:demo-company-[a-z]|cn-\d{6})/g);
  if (matched && matched.length > 0) {
    return [...new Set(matched)];
  }
  return ["demo-company-a"];
}
