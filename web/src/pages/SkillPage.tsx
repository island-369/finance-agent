import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

interface Row {
  name: string;
  version: string;
  state: string;
  description: string;
  sha256: string;
}

export default function SkillPage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState("");
  const [msgKind, setMsgKind] = useState<"ok" | "error">("ok");

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
      setMsg(`${label} 完成`);
      setMsgKind("ok");
      await reload();
    } catch (e) {
      setMsg(`${label} 失败: ${e}`);
      setMsgKind("error");
    }
  };

  const activeCount = rows.filter((r) => r.state === "active").length;

  return (
    <div>
      <section className="card">
        <h3>Skill 版本管理</h3>
        <p className="section-hint">
          状态:active=当前发布 · draft=目录最新未发布 · candidate=历史版本 · retired=停用。
          发布/回滚只切换指针(发布记录文件),不覆盖任何版本内容(§7.1)。
          当前 {rows.length} 个版本包,{activeCount} 个处于 active。
        </p>
        <div className="field-row">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="操作备注(写入发布记录)"
            style={{ width: 340 }}
          />
        </div>
        <table className="data" style={{ marginTop: 12 }}>
          <thead>
            <tr>
              <th>Skill</th>
              <th>版本</th>
              <th>状态</th>
              <th>描述</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.name}@${r.version}`}>
                <td className="mono">{r.name}</td>
                <td className="mono">{r.version}</td>
                <td>
                  <span className={`badge s-${r.state}`}>{r.state}</span>
                </td>
                <td className="cell-sub" style={{ maxWidth: 380 }}>
                  {r.description}
                </td>
                <td>
                  <div className="row-actions">
                    {r.state !== "active" && r.state !== "retired" && (
                      <button
                        onClick={() => act(() => api.publishSkill(r.name, r.version, note), `发布 ${r.name}@${r.version}`)}
                      >
                        发布
                      </button>
                    )}
                    {r.state === "active" && (
                      <button
                        className="danger"
                        onClick={() => act(() => api.retireSkill(r.name, r.version, note), `停用 ${r.name}@${r.version}`)}
                      >
                        停用
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {msg && <div className={`notice ${msgKind}`}>{msg}</div>}
      </section>

      <section className="card">
        <h3>生效中的版本覆盖</h3>
        <p className="section-hint">= active 指针 ≠ 目录最新的 Skill;执行侧经 resolver 覆盖顺序生效(§7.3)。</p>
        {Object.keys(overrides).length === 0 ? (
          <div className="empty">无覆盖:所有 Skill 的 active 指针均指向目录最新版本。</div>
        ) : (
          <table className="data">
            <tbody>
              {Object.entries(overrides).map(([name, version]) => (
                <tr key={name}>
                  <td className="mono">{name}</td>
                  <td className="mono">{version}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h3>版本回滚</h3>
        <p className="section-hint">把 active 指针切回历史版本;回滚后新任务立即使用该版本,进行中的任务保持原快照(§7.4)。</p>
        <RollbackPanel rows={rows} note={note} onDone={reload} setMsg={setMsg} setMsgKind={setMsgKind} />
      </section>
    </div>
  );
}

function RollbackPanel({
  rows,
  note,
  onDone,
  setMsg,
  setMsgKind,
}: {
  rows: Row[];
  note: string;
  onDone: () => void;
  setMsg: (s: string) => void;
  setMsgKind: (k: "ok" | "error") => void;
}) {
  const [sel, setSel] = useState("");
  const historical = rows.filter((r) => r.state === "candidate" || r.state === "active");
  return (
    <div className="field-row" style={{ marginTop: 0 }}>
      <select value={sel} onChange={(e) => setSel(e.target.value)} style={{ minWidth: 280 }}>
        <option value="">选择要回滚到的版本…</option>
        {historical.map((r) => (
          <option key={`${r.name}@${r.version}`} value={`${r.name}@${r.version}`}>
            {r.name}@{r.version}({r.state})
          </option>
        ))}
      </select>
      <button
        className="primary"
        disabled={!sel}
        onClick={async () => {
          const [name, version] = sel.split("@");
          try {
            await api.rollbackSkill(name, version, note || "UI 回滚");
            setMsg(`已回滚 ${sel}`);
            setMsgKind("ok");
            onDone();
          } catch (e) {
            setMsg(`回滚失败: ${e}`);
            setMsgKind("error");
          }
        }}
      >
        回滚到此版本
      </button>
    </div>
  );
}
