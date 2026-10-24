import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, streamEvents, type Ev, type RunBrief } from "../api";

interface RunListItem {
  run_id: string;
  status: string;
  objective: string;
  entity_ids: string[];
  attempt: number;
  created_at: string | null;
  summary: string | null;
}

function evText(e: Ev): string {
  const p = e.payload as Record<string, unknown>;
  const bits = [String(p.name ?? "")];
  if (p.input_brief) bits.push(String(p.input_brief).slice(0, 90));
  const usage = p.usage as { input_tokens?: number; output_tokens?: number } | undefined;
  if (usage) bits.push(`in ${usage.input_tokens ?? "?"} / out ${usage.output_tokens ?? "?"}`);
  return bits.filter(Boolean).join(" · ");
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
  metric_refs?: string[];
  calculation_refs?: string[];
  information_gaps?: string[];
}

export default function RunPage() {
  const { runId: routeRunId } = useParams();
  const nav = useNavigate();
  const [objective, setObjective] = useState("分析 demo-company-a 2026 年上半年净利润变化,识别与收入变化不一致的环节");
  const [entities, setEntities] = useState("demo-company-a");
  const [interruptTool, setInterruptTool] = useState("");
  const [run, setRun] = useState<RunBrief | null>(null);
  const [events, setEvents] = useState<Ev[]>([]);
  const [artifacts, setArtifacts] = useState<ResultBody[]>([]);
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
      setArtifacts(arts.artifacts.map((a) => a.content as ResultBody));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const startSSE = useCallback(
    (id: string) => {
      stopStream();
      closeRef.current = streamEvents(
        id,
        (e) => setEvents((prev) => (prev.some((x) => x.seq === e.seq) ? prev : [...prev, e])),
        () => loadRun(id),
      );
    },
    [loadRun],
  );

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
      <section className="card">
        <h3>新建任务</h3>
        <p className="section-hint">
          目标描述后由 Agent 自主选择 Skill 与工具执行;结果须带可核查引用(obs / calc / chk)。
        </p>
        <textarea value={objective} onChange={(e) => setObjective(e.target.value)} rows={3} />
        <div className="field-row">
          <input
            value={entities}
            onChange={(e) => setEntities(e.target.value)}
            placeholder="公司 ID(逗号分隔)"
          />
          <input
            value={interruptTool}
            onChange={(e) => setInterruptTool(e.target.value)}
            placeholder="审批工具名(可选,如 finance_get_metrics)"
          />
          <button className="primary" onClick={create}>
            创建并执行
          </button>
        </div>
        {error && (
          <div className="notice error" role="alert">
            {error}
          </div>
        )}
      </section>

      {run && (
        <section className="card">
          <div className="run-head">
            <span className="run-id">{run.run_id}</span>
            <span className={`badge s-${status}`}>{status}</span>
            {run.cancel_requested && <small style={{ color: "var(--warn)" }}>(已请求取消)</small>}
          </div>
          <p className="run-meta">{run.objective}</p>
          <p className="run-meta">
            预算:模型 <b>{run.budget.used.model_calls ?? 0}</b>/{run.budget.limits.max_model_calls}
            　·　工具 <b>{run.budget.used.tool_calls ?? 0}</b>/{run.budget.limits.max_tool_calls}
            　·　尝试 <b>{run.attempt}</b> 次
          </p>
          {run.summary && <p className="run-summary">{run.summary}</p>}
          {run.error && <div className="notice error">{run.error}</div>}
          <div className="run-actions">
            <button className="danger" onClick={() => api.cancelRun(run.run_id).then(() => loadRun(run.run_id))}>
              取消任务
            </button>
            {status === "waiting_input" && (
              <>
                <button className="primary" onClick={() => doResume(true)}>
                  批准并恢复
                </button>
                <button className="danger" onClick={() => doResume(false)}>
                  拒绝
                </button>
              </>
            )}
          </div>
        </section>
      )}

      {events.length > 0 && (
        <section className="card">
          <h3>执行时间线</h3>
          <p className="section-hint">SSE 实时推送;断开后按 Last-Event-ID 自动补读。</p>
          <div className="timeline">
            {events.map((e) => (
              <div key={e.seq} className="tl-item">
                <span className="tl-seq">{e.seq}</span>
                <span className={`tl-type ${e.type.includes("tool") ? "tool" : "model"}`}>{e.type}</span>
                <span className="tl-detail">{evText(e)}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {artifacts.map((res, i) => (
        <section className="card" key={i}>
          <h3>结果与证据</h3>
          {res.summary && (
            <p style={{ fontSize: 14, marginTop: 0 }}>
              <b>摘要</b>　{res.summary}
            </p>
          )}
          {res.key_findings?.map((f, j) => (
            <div className="finding" key={j}>
              <span className={`kind ${f.kind}`}>{f.kind}</span>
              <div className="body">
                {f.statement}
                {f.refs.length > 0 && (
                  <span className="refs">
                    {f.refs.map((r) => (
                      <code key={r}>{r}</code>
                    ))}
                  </span>
                )}
              </div>
            </div>
          ))}
          {res.evidence_refs && res.evidence_refs.length > 0 && (
            <p style={{ fontSize: 12.5, color: "var(--muted)", marginBottom: 0 }}>
              <b>证据定位</b>　
              {res.evidence_refs.map((e) => `${e.evidence_id}(p${e.page}-¶${e.paragraph})`).join("; ")}
            </p>
          )}
          {res.information_gaps && res.information_gaps.length > 0 && (
            <div className="notice warn">
              <b>信息缺口</b>　{res.information_gaps.join(";")}
            </div>
          )}
        </section>
      ))}

      {recent.length > 0 && !routeRunId && (
        <section className="card">
          <h3>最近任务</h3>
          <table className="data">
            <thead>
              <tr>
                <th>任务</th>
                <th>状态</th>
                <th>公司</th>
                <th>摘要</th>
              </tr>
            </thead>
            <tbody>
              {recent.map((r) => (
                <tr key={r.run_id} className="clickable" onClick={() => nav(`/runs/${r.run_id}`)}>
                  <td>
                    <span className="mono">{r.run_id}</span>
                    <div className="cell-sub">{r.objective.slice(0, 50)}</div>
                  </td>
                  <td>
                    <span className={`badge s-${r.status}`}>{r.status}</span>
                  </td>
                  <td className="cell-sub">{r.entity_ids.join(", ")}</td>
                  <td className="cell-sub">{(r.summary ?? "").slice(0, 60) || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
