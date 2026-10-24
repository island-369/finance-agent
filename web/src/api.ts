/** API 客户端:全部走 M3/M5 后端(默认 8010)。 */

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8010";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail ?? `${resp.status}`);
  }
  return resp.json() as Promise<T>;
}

export interface RunBrief {
  run_id: string;
  status: string;
  objective: string;
  entity_ids: string[];
  as_of: string;
  attempt: number;
  error: string | null;
  cancel_requested: boolean;
  budget: { limits: Record<string, number>; used: Record<string, number> };
  summary: string | null;
  artifact_kinds: string[];
}

export const api = {
  createRun: (body: {
    objective: string;
    entity_ids: string[];
    budget?: Record<string, number>;
    interrupt_on_tool?: string | null;
  }, idemKey?: string) =>
    req<{ run_id: string; status: string; replayed: boolean }>("/v1/runs", {
      method: "POST",
      body: JSON.stringify(body),
      headers: idemKey ? { "Idempotency-Key": idemKey } : {},
    }),
  getRun: (id: string) => req<RunBrief>(`/v1/runs/${id}`),
  cancelRun: (id: string) => req<unknown>(`/v1/runs/${id}/cancel`, { method: "POST" }),
  resumeRun: (id: string, approve: boolean) =>
    req<{ status: string }>(`/v1/runs/${id}/resume`, {
      method: "POST",
      body: JSON.stringify({ approve }),
    }),
  artifacts: (id: string) =>
    req<{ artifacts: { kind: string; content: Record<string, unknown> }[] }>(
      `/v1/runs/${id}/artifacts`,
    ),
  skills: () =>
    req<{ skills: { ref: string; available: boolean; reason: string | null; description: string }[] }>(
      "/v1/skills",
    ),
  adminSkills: () =>
    req<{ skills: { name: string; version: string; state: string; description: string; sha256: string }[] }>(
      "/v1/admin/skills",
    ),
  publishSkill: (name: string, version: string, note: string) =>
    req(`/v1/admin/skills/${name}/versions/${version}/publish`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  rollbackSkill: (name: string, version: string, note: string) =>
    req(`/v1/admin/skills/${name}/versions/${version}/rollback`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  retireSkill: (name: string, version: string, note: string) =>
    req(`/v1/admin/skills/${name}/versions/${version}/retire`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  userOverrides: () => req<{ overrides: Record<string, string> }>("/v1/admin/user-overrides"),
  evals: () => req<{ results: { label: string; summary: Record<string, unknown> }[] }>("/v1/admin/evals"),
  engines: () => req<{ engines: Record<string, unknown>[] }>("/v1/engines"),
  dataSource: () => req<{ data_source: string; note: string }>("/v1/admin/data-source"),
};

export interface Ev {
  seq: number;
  type: string;
  attempt: number;
  payload: Record<string, unknown>;
  occurred_at: string | null;
}

/** SSE 事件流;返回取消函数。 */
export function streamEvents(
  runId: string,
  onEvent: (e: Ev) => void,
  onEnd: () => void,
): () => void {
  const es = new EventSource(`${BASE}/v1/runs/${runId}/events`);
  es.onmessage = (msg) => {
    const e = JSON.parse(msg.data) as Ev;
    onEvent(e);
    if (e.type === "run.status_changed") {
      es.close();
      onEnd();
    }
  };
  es.onerror = () => {
    /* EventSource 自动重连,Last-Event-ID 由浏览器携带 */
  };
  return () => es.close();
}
