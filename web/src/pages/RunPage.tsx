import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, streamEvents, type Ev, type RunBrief } from "../api";

function evText(e: Ev): string {
  const p = e.payload as Record<string, unknown>;
  const bits = [String(p.name ?? "")];
  if (p.input_brief) bits.push(String(p.input_brief).slice(0, 90));
  const usage = p.usage as { input_tokens?: number; output_tokens?: number } | undefined;
  if (usage) bits.push(`in ${usage.input_tokens ?? "?"} / out ${usage.output_tokens ?? "?"}`);
  return bits.filter(Boolean).join(" · ");
}

interface RunListItem {
  run_id: string;
  status: string;
  objective: string;
  entity_ids: string[];
  attempt: number;
  created_at: string | null;
  summary: string | null;
}

const STATUS_STYLE: Record<string, string> = {
  queued: "#888", running: "#1a73e8", validating: "#1a73e8",
  waiting_input: "#e8710a", succeeded: "#188038", failed: "#d93025",
  cancelled: "#888",
};

export default function RunPage() {
  const { runId: routeRunId } = useParams();
  const nav = useNavigate();
  const [objective, setObjective] = useState("分析 demo-company-a 2026 年上半年净利润变化,识别与收入变化不一致的环节");
  const [entities, setEntities] = useState("demo-company-a");
  const [interruptTool, setInterruptTool] = useState("");
  const [run, setRun] = useState<RunBrief | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const [artifacts, setArtifacts] = useState<Record<string, unknown>[]>([]);
  const [recent, setRecent] = useState<RunListItem[]>([]);
  const [error, setError] = useState("");
  const closeRef = useRef<null | (() => void)>(null);

  const stopStream = () => closeRef.current?.();

  const loadRecent = useCallback(async () => {
    try {
      const d = await api.listRuns(15);
      setRecent(d.runs);
    } catch {
      /* 列表失败不影响主流程 */
    }
  }, []);

  const loadRun = useCallback(async (id: string) => {
    try {
      const brief = await api.getRun(id);
      setRun(brief);
      const arts = await api.artifacts(id);
      setArtifacts(arts.artifacts.map((a) => a.content));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const startSSE = useCallback((id: string) => {
    stopStream();
    closeRef.current = streamEvents(
      id,
      (e) => setEvents((prev) => (prev.some((x) => x.seq === e.seq) ? prev : [...prev, e])),
      () => loadRun(id),
    );
  }, [loadRun]);

  useEffect(() => {
    loadRecent();
    if (routeRunId) {
      setEvents([]);
      setArtifacts([]);
      loadRun(routeRunId);
      startSSE(routeRunId);
    }
    return stopStream;
  }, [routeRunId, loadRun, startSSE, loadRecent]);

  const create = async () => {
    setError("");
    setEvents([]);
    setArtifacts([]);
    try {
      const res = await api.createRun(
        {
          objective,
          entity_ids: entities.split(/[,，\s]+/).filter(Boolean),
          interrupt_on_tool: interruptTool || null,
        },
        crypto.randomUUID(),
      );
      nav(`/runs/${res.run_id}`);
      loadRecent();
    } catch (e) {
      setError(String(e));
    }
  };

  const doResume = async (approve: boolean) => {
    if (!run) return;
    await api.resumeRun(run.run_id, approve);
    startSSE(run.run_id);
  };

  const status = run?.status ?? "";
  return (
    <div>
      <section style={{ marginBottom: 24 }}>
        <h3>新建任务</h3>
        <textarea
          value={objective} onChange={(e) => setObjective(e.target.value)}
          rows={3} style={{ width: "100%", boxSizing: "border-box" }}
        />
        <div style={{ display: "flex", gap: 8, marginTop: 8, alignItems: "center" }}>
          <input value={entities} onChange={(e) => setEntities(e.target.value)}
                 placeholder="公司 ID(逗号分隔)" style={{ flex: 1 }} />
          <input value={interruptTool} onChange={(e) => setInterruptTool(e.target.value)}
                 placeholder="审批工具名(可选,如 finance_get_metrics)" style={{ flex: 1 }} />
          <button onClick={create}>创建并执行</button>
        </div>
        {error && <p style={{ color: "#d93025" }}>{error}</p>}
      </section>

      {recent.length > 0 && !routeRunId && (
        <section style={{ marginBottom: 24 }}>
          <h3>最近任务</h3>
          <table style={{ width: "100%", fontSize: 14 }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #ddd", textAlign: "left" }}>
                <th>任务</th><th>状态</th><th>公司</th><th>摘要</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((r) => (
                <tr key={r.run_id} style={{ borderBottom: "1px solid #eee", cursor: "pointer" }}
                    onClick={() => nav(`/runs/${r.run_id}`)}>
                  <td>
                    {r.run_id}
                    <div style={{ fontSize: 12, color: "#555" }}>{r.objective.slice(0, 50)}</div>
                  </td>
                  <td style={{ color: STATUS_STYLE[r.status] ?? "#333" }}>{r.status}</td>
                  <td style={{ fontSize: 12 }}>{r.entity_ids.join(", ")}</td>
                  <td style={{ fontSize: 12, color: "#555" }}>
                    {(r.summary ?? "").slice(0, 60) || "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {run && (
        <section style={{ marginBottom: 24 }}>
          <h3>
            {run.run_id}{" "}
            <span style={{ color: STATUS_STYLE[status] ?? "#333", fontSize: 16 }}>[{status}]</span>
            {run.cancel_requested && <small>(已请求取消)</small>}
          </h3>
          <p style={{ color: "#555", fontSize: 14 }}>{run.objective}</p>
          <p style={{ fontSize: 14 }}>
            预算:模型 {run.budget.used.model_calls ?? 0}/{run.budget.limits.max_model_calls} ·
            工具 {run.budget.used.tool_calls ?? 0}/{run.budget.limits.max_tool_calls}
            {run.summary && <> · 摘要:{run.summary.slice(0, 80)}…</>}
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <button onClick={() => api.cancelRun(run.run_id).then(() => loadRun(run.run_id))}>取消</button>
            {status === "waiting_input" && (
              <>
                <button onClick={() => doResume(true)}>批准并恢复</button>
                <button onClick={() => doResume(false)}>拒绝</button>
              </>
            )}
          </div>
        </section>
      )}

      {events.length > 0 && (
        <section style={{ marginBottom: 24 }}>
          <h3>执行时间线(SSE)</h3>
          <div style={{ maxHeight: 260, overflowY: "auto", border: "1px solid #eee", padding: 8, fontSize: 13, fontFamily: "monospace" }}>
            {events.map((e) => (
              <div key={e.seq}>
                <span style={{ color: "#999" }}>{e.seq}</span>{" "}
                <b style={{ color: e.type.includes("tool") ? "#1a73e8" : "#188038" }}>{e.type}</b>{" "}
                {evText(e)}
              </div>
            ))}
          </div>
        </section>
      )}

      {artifacts.length > 0 && (
        <section>
          <h3>结果与证据</h3>
          {artifacts.map((a, i) => {
            const res = a as { summary?: string; key_findings?: { statement: string; kind: string; refs: string[] }[]; evidence_refs?: { evidence_id: string; page: number; paragraph: number }[]; metric_refs?: string[]; calculation_refs?: string[]; information_gaps?: string[] };
            return (
              <div key={i}>
                <p><b>摘要:</b>{res.summary}</p>
                <ul>
                  {(res.key_findings ?? []).map((f, j) => (
                    <li key={j}>
                      [{f.kind}] {f.statement}
                      {f.refs.length > 0 && <small> 引用: {f.refs.join(", ")}</small>}
                    </li>
                  ))}
                </ul>
                {(res.evidence_refs ?? []).length > 0 && (
                  <p style={{ fontSize: 13 }}>
                    证据:{(res.evidence_refs ?? []).map((e) => `${e.evidence_id}(p${e.page}-¶${e.paragraph})`).join("; ")}
                  </p>
                )}
                {(res.information_gaps ?? []).length > 0 && (
                  <p style={{ fontSize: 13, color: "#a05a00" }}>信息缺口:{(res.information_gaps ?? []).join("; ")}</p>
                )}
              </div>
            );
          })}
        </section>
      )}
    </div>
  );
}
