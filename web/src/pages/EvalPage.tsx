import { useEffect, useState } from "react";
import { api } from "../api";

interface GroupSummary {
  scored: number; cases: number; completion_rate: number | null;
  citation_valid_rate: number | null; numeric_ok_rate: number | null;
  skill_ok_rate: number | null; model_calls_total: number; tool_calls_total: number;
  input_tokens_total: number; output_tokens_total: number; wall_p50: number; wall_p95: number;
}

export default function EvalPage() {
  const [rows, setRows] = useState<{ label: string; summary: Record<string, GroupSummary> }[]>([]);
// eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [err, setErr] = useState("");

  useEffect(() => {
    api.evals().then((d) => setRows(d.results as { label: string; summary: Record<string, GroupSummary> }[])).catch((e) => setErr(String(e)));
  }, []);

  return (
    <div>
      <h3>评测结果(A/B/C/D + 版本对照)</h3>
      {err && <p style={{ color: "#d93025" }}>{err}(评测结果来自 m4 eval 的落盘文件)</p>}
      {rows.map(({ label, summary }) => (
        <div key={label} style={{ marginBottom: 24 }}>
          <h4>{label}</h4>
          <table style={{ borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #ddd", textAlign: "left" }}>
                <th>分组</th><th>完成率</th><th>引用有效</th><th>数值正确</th>
                <th>模型调用</th><th>工具调用</th><th>输入tok</th><th>P50/P95(s)</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(summary).map(([g, s]) => (
                <tr key={g} style={{ borderBottom: "1px solid #eee" }}>
                  <td><b>{g}</b> ({s.scored}/{s.cases})</td>
                  <td>{s.completion_rate ?? "-"}</td>
                  <td>{s.citation_valid_rate ?? "-"}</td>
                  <td>{s.numeric_ok_rate ?? "-"}</td>
                  <td>{s.model_calls_total}</td>
                  <td>{s.tool_calls_total}</td>
                  <td>{s.input_tokens_total}</td>
                  <td>{s.wall_p50} / {s.wall_p95}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {rows.length === 0 && !err && <p>暂无评测结果(运行 uv run m4 eval 后刷新)</p>}
    </div>
  );
}
