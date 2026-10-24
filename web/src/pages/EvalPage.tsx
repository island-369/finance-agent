import { useEffect, useState } from "react";
import { Card, Table, Typography } from "antd";
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

const pct = (v: number | null) => (v === null ? "-" : `${(v * 100).toFixed(1)}%`);

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
    <div style={{ maxWidth: 1020, margin: "0 auto", padding: 24 }}>
      <Card title="评测结果">
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
          A 无 Skill / B 全装入 / C 按需加载(主配置)/ D 固定流程;每题每组单次运行,
          失败样例保留在分母(§16.2);语义支持度留待人工抽查。
        </Typography.Paragraph>
        {err && <Typography.Text type="danger">{err}</Typography.Text>}
        {rows.map(({ label, summary }) => (
          <div key={label} style={{ marginBottom: 28 }}>
            <Typography.Title level={5}>{label}</Typography.Title>
            <Table
              rowKey={(g) => g}
              dataSource={Object.keys(summary)}
              pagination={false}
              size="middle"
              columns={[
                {
                  title: "分组",
                  render: (g: string) => (
                    <>
                      <b>{g}</b>
                      <div style={{ fontSize: 12, color: "#8a97a5" }}>
                        {summary[g].scored}/{summary[g].cases} 题得分
                      </div>
                    </>
                  ),
                },
                { title: "完成率", render: (g: string) => pct(summary[g].completion_rate) },
                { title: "引用有效", render: (g: string) => pct(summary[g].citation_valid_rate) },
                { title: "数值正确", render: (g: string) => pct(summary[g].numeric_ok_rate) },
                { title: "模型调用", dataIndex: "", render: (g: string) => summary[g].model_calls_total },
                { title: "工具调用", render: (g: string) => summary[g].tool_calls_total },
                {
                  title: "输入 tok",
                  render: (g: string) => summary[g].input_tokens_total.toLocaleString(),
                },
                {
                  title: "输出 tok",
                  render: (g: string) => summary[g].output_tokens_total.toLocaleString(),
                },
                { title: "P50/P95(s)", render: (g: string) => `${summary[g].wall_p50} / ${summary[g].wall_p95}` },
              ]}
            />
          </div>
        ))}
        {rows.length === 0 && !err && (
          <Typography.Text type="secondary">暂无评测结果(运行 uv run m4 eval 后刷新)</Typography.Text>
        )}
      </Card>
    </div>
  );
}
