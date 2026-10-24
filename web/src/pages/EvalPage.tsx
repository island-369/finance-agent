import { useEffect, useState } from "react";
import { api } from "../api";

interface GroupSummary {
  scored: number;
  cases: number;
  completion_rate: number | null;
  citation_valid_rate: number | null;
  numeric_ok_rate: number | null;
  skill_ok_rate: number | null;
  model_calls_total: number;
  tool_calls_total: number;
  input_tokens_total: number;
  output_tokens_total: number;
  wall_p50: number;
  wall_p95: number;
}

interface EvalRow {
  label: string;
  summary: Record<string, GroupSummary>;
}

export default function EvalPage() {
  const [rows, setRows] = useState<EvalRow[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api
      .evals()
      .then((d) => setRows(d.results as EvalRow[]))
      .catch((e) => setErr(String(e)));
  }, []);

  return (
    <div>
      <section className="card">
        <h3>评测结果</h3>
        <p className="section-hint">
          A 无 Skill / B 全装入 / C 按需加载(主配置)/ D 固定流程;数据来自 m4 eval 的落盘文件。
          每题每组单次运行,失败样例保留在分母;语义支持度留待人工抽查。
        </p>
        {err && <div className="notice error">{err}</div>}
        {rows.map(({ label, summary }) => (
          <div className="eval-block" key={label}>
            <h4>
              <span className="label">{label}</span>
            </h4>
            <table className="data">
              <thead>
                <tr>
                  <th>分组</th>
                  <th>完成率</th>
                  <th>引用有效</th>
                  <th>数值正确</th>
                  <th>模型调用</th>
                  <th>工具调用</th>
                  <th>输入 tok</th>
                  <th>输出 tok</th>
                  <th>P50 / P95(s)</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(summary).map(([g, s]) => (
                  <tr key={g}>
                    <td>
                      <b>{g}</b>
                      <div className="cell-sub">
                        {s.scored}/{s.cases} 题得分
                      </div>
                    </td>
                    <td className="num">{s.completion_rate ?? "-"}</td>
                    <td className="num">{s.citation_valid_rate ?? "-"}</td>
                    <td className="num">{s.numeric_ok_rate ?? "-"}</td>
                    <td className="num">{s.model_calls_total}</td>
                    <td className="num">{s.tool_calls_total}</td>
                    <td className="num">{s.input_tokens_total.toLocaleString()}</td>
                    <td className="num">{s.output_tokens_total.toLocaleString()}</td>
                    <td className="num">
                      {s.wall_p50} / {s.wall_p95}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
        {rows.length === 0 && !err && (
          <div className="empty">暂无评测结果(运行 uv run m4 eval 后刷新)</div>
        )}
      </section>
    </div>
  );
}
