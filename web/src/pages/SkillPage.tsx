import { useCallback, useEffect, useState } from "react";
import { Card, Table, Tag, Input, Button, Select, Typography, App as AntApp, Space } from "antd";
import { api } from "../api";

interface Row {
  name: string;
  version: string;
  state: string;
  description: string;
  sha256: string;
}

const STATE_TAG: Record<string, { color: string; text: string }> = {
  active: { color: "green", text: "active · 当前发布" },
  draft: { color: "blue", text: "draft · 最新未发布" },
  candidate: { color: "default", text: "candidate · 历史版本" },
  retired: { color: "red", text: "retired · 已停用" },
};

export default function SkillPage() {
  const { message } = AntApp.useApp();
  const [rows, setRows] = useState<Row[]>([]);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [rollbackTarget, setRollbackTarget] = useState<string>("");

  const reload = useCallback(async () => {
    const [a, o] = await Promise.all([api.adminSkills(), api.userOverrides()]);
    setRows(a.skills);
    setOverrides(o.overrides);
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const act = async (fn: () => Promise<unknown>, label: string) => {
    try {
      await fn();
      message.success(`${label} 完成`);
      await reload();
    } catch (e) {
      message.error(`${label} 失败: ${e}`);
    }
  };

  return (
    <div style={{ maxWidth: 1020, margin: "0 auto", padding: 24 }}>
      <Card
        title="Skill 版本管理"
        extra={
          <Input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="操作备注(写入发布记录)"
            style={{ width: 280 }}
            size="small"
          />
        }
      >
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
          发布/回滚只切换 active 指针(发布记录文件),不覆盖任何版本内容(§7.1);
          回滚后新任务立即使用该版本,进行中的任务保持原快照(§7.4)。
        </Typography.Paragraph>
        <Table<Row>
          rowKey={(r) => `${r.name}@${r.version}`}
          dataSource={rows}
          pagination={false}
          size="middle"
          columns={[
            { title: "Skill", dataIndex: "name", render: (v: string) => <span className="mono">{v}</span> },
            { title: "版本", dataIndex: "version", width: 90, render: (v: string) => <span className="mono">{v}</span> },
            {
              title: "状态",
              dataIndex: "state",
              width: 170,
              render: (v: string) => {
                const t = STATE_TAG[v] ?? { color: "default", text: v };
                return <Tag color={t.color}>{t.text}</Tag>;
              },
            },
            { title: "描述", dataIndex: "description", ellipsis: true },
            {
              title: "操作",
              width: 110,
              render: (_, r) =>
                r.state !== "active" && r.state !== "retired" ? (
                  <Button
                    size="small"
                    onClick={() => act(() => api.publishSkill(r.name, r.version, note), `发布 ${r.name}@${r.version}`)}
                  >
                    发布
                  </Button>
                ) : r.state === "active" ? (
                  <Button
                    size="small"
                    danger
                    onClick={() => act(() => api.retireSkill(r.name, r.version, note), `停用 ${r.name}@${r.version}`)}
                  >
                    停用
                  </Button>
                ) : null,
            },
          ]}
        />
      </Card>

      <Card title="生效中的版本覆盖" style={{ marginTop: 20 }}>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12.5 }}>
          = active 指针 ≠ 目录最新的 Skill;执行侧经 resolver 覆盖顺序生效(§7.3)。
        </Typography.Paragraph>
        {Object.keys(overrides).length === 0 ? (
          <Typography.Text type="secondary">无覆盖:所有 Skill 的 active 指针均指向目录最新版本。</Typography.Text>
        ) : (
          <Space wrap>
            {Object.entries(overrides).map(([name, version]) => (
              <Tag key={name} className="mono">
                {name}@{version}
              </Tag>
            ))}
          </Space>
        )}
      </Card>

      <Card title="版本回滚" style={{ marginTop: 20 }}>
        <Space.Compact style={{ width: "100%" }}>
          <Select
            style={{ width: 360 }}
            placeholder="选择要回滚到的版本…"
            value={rollbackTarget || undefined}
            onChange={setRollbackTarget}
            options={rows
              .filter((r) => r.state === "candidate" || r.state === "active")
              .map((r) => ({
                value: `${r.name}@${r.version}`,
                label: `${r.name}@${r.version}(${r.state})`,
              }))}
          />
          <Button
            type="primary"
            disabled={!rollbackTarget}
            onClick={async () => {
              const [name, version] = rollbackTarget.split("@");
              await act(
                () => api.rollbackSkill(name, version, note || "UI 回滚"),
                `回滚到 ${rollbackTarget}`,
              );
              setRollbackTarget("");
            }}
          >
            回滚到此版本
          </Button>
        </Space.Compact>
      </Card>
    </div>
  );
}
