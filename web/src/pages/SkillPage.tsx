import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

interface Row {
  name: string; version: string; state: string; description: string; sha256: string;
}

const STATE_COLOR: Record<string, string> = {
  active: "#188038", draft: "#1a73e8", candidate: "#888", retired: "#d93025",
};

export default function SkillPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");

  const reload = useCallback(async () => {
    const [a, o] = await Promise.all([api.adminSkills(), api.userOverrides()]);
    setRows(a.skills);
    setOverrides(o.overrides);
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const act = async (fn: () => Promise<unknown>, label: string) => {
    setMsg("");
    try {
      await fn();
      setMsg(`${label} 完成`);
      await reload();
    } catch (e) {
      setMsg(`${label} 失败: ${e}`);
    }
  };

  return (
    <div>
      <h3>Skill 版本管理</h3>
      <p style={{ fontSize: 13, color: "#555" }}>
        状态:active=当前发布 · draft=目录最新未发布 · candidate=历史版本 · retired=停用。
        发布/回滚只切换指针(发布记录文件),不覆盖任何版本内容(§7.1)。
      </p>
      <input value={note} onChange={(e) => setNote(e.target.value)}
             placeholder="操作备注(写入发布记录)" style={{ width: 320 }} />
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 12, fontSize: 14 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "2px solid #ddd" }}>
            <th>Skill</th><th>版本</th><th>状态</th><th>描述</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.name}@${r.version}`} style={{ borderBottom: "1px solid #eee" }}>
              <td>{r.name}</td>
              <td>{r.version}</td>
              <td style={{ color: STATE_COLOR[r.state] }}>{r.state}</td>
              <td style={{ fontSize: 12, color: "#555" }}>{r.description.slice(0, 60)}…</td>
              <td style={{ whiteSpace: "nowrap" }}>
                {r.state !== "active" && r.state !== "retired" && (
                  <button onClick={() => act(() => api.publishSkill(r.name, r.version, note), `发布 ${r.name}@${r.version}`)}>
                    发布
                  </button>
                )}
                {r.state === "active" && (
                  <button onClick={() => act(() => api.retireSkill(r.name, r.version, note), `停用 ${r.name}@${r.version}`)}>
                    停用
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ marginTop: 12, fontSize: 13 }}>
        当前生效的版本覆盖(= active 指针 ≠ 目录最新):
        <code>{JSON.stringify(overrides)}</code>
      </p>
      {msg && <p style={{ color: "#188038" }}>{msg}</p>}
      <h3 style={{ marginTop: 24 }}>版本回滚(选择历史版本)</h3>
      <RollbackPanel rows={rows} note={note} onDone={reload} setMsg={setMsg} />
    </div>
  );
}

function RollbackPanel({ rows, note, onDone, setMsg }: {
  rows: Row[]; note: string; onDone: () => void; setMsg: (s: string) => void;
}) {
  const [sel, setSel] = useState("");
  const historical = rows.filter((r) => r.state === "candidate" || r.state === "active");
  return (
    <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
      <select value={sel} onChange={(e) => setSel(e.target.value)}>
        <option value="">选择要回滚到的版本…</option>
        {historical.map((r) => (
          <option key={`${r.name}@${r.version}`} value={`${r.name}@${r.version}`}>
            {r.name}@{r.version}({r.state})
          </option>
        ))}
      </select>
      <button
        disabled={!sel}
        onClick={async () => {
          const [name, version] = sel.split("@");
          try {
            await api.rollbackSkill(name, version, note || "UI 回滚");
            setMsg(`已回滚 ${sel}`);
            onDone();
          } catch (e) {
            setMsg(`回滚失败: ${e}`);
          }
        }}
      >
        回滚到此版本
      </button>
    </div>
  );
}
