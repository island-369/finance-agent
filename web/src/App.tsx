import { useCallback, useEffect, useState } from "react";
import { App as AntApp, ConfigProvider, Layout, Menu, Button, theme } from "antd";
import zhCN from "antd/locale/zh_CN";
import {
  PlusOutlined,
  MessageOutlined,
  TagsOutlined,
  BarChartOutlined,
} from "@ant-design/icons";
import { Conversations } from "@ant-design/x";
import type { ConversationsProps } from "@ant-design/x";
import { BrowserRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api } from "./api";
import RunPage from "./pages/RunPage";
import SkillPage from "./pages/SkillPage";
import EvalPage from "./pages/EvalPage";

const STATUS_COLOR: Record<string, string> = {
  queued: "#9e9e9e",
  running: "#1a66d6",
  validating: "#1a66d6",
  waiting_input: "#d48b00",
  completed_partial: "#d48b00",
  succeeded: "#14804a",
  failed: "#c5221f",
  cancelled: "#9e9e9e",
};

function Sidebar() {
  const nav = useNavigate();
  const location = useLocation();
  const activeRunId = location.pathname.startsWith("/runs/") ? location.pathname.slice(6) : "";
  const [items, setItems] = useState<ConversationsProps["items"]>([]);

  const load = useCallback(async () => {
    try {
      const d = await api.listRuns(30);
      setItems(
        d.runs.map((r) => ({
          key: r.run_id,
          label: `${r.objective.slice(0, 28)}`,
          icon: <MessageOutlined style={{ color: STATUS_COLOR[r.status] ?? "#9e9e9e" }} />,
        })),
      );
    } catch {
      /* 列表失败不影响主流程 */
    }
  }, []);

  useEffect(() => {
    load();
    const onUpdate = () => load();
    window.addEventListener("runs-updated", onUpdate);
    const timer = window.setInterval(load, 15000);
    return () => {
      window.removeEventListener("runs-updated", onUpdate);
      window.clearInterval(timer);
    };
  }, [load]);

  const pageKey = location.pathname.startsWith("/skills")
    ? "skills"
    : location.pathname.startsWith("/evals")
      ? "evals"
      : "";

  return (
    <Layout.Sider
      width={264}
      theme="light"
      style={{ height: "100vh", position: "sticky", top: 0, background: "#f7f7f8", borderRight: "1px solid #e8eaed" }}
    >
      <div style={{ padding: "14px 12px 8px", background: "#f7f7f8" }}>
        <Button type="primary" icon={<PlusOutlined />} block onClick={() => nav("/")}>
          新建研究任务
        </Button>
      </div>
      <div style={{ height: "calc(100vh - 190px)", overflowY: "auto", padding: "0 8px", background: "#f7f7f8" }}>
        <Conversations
          items={items}
          activeKey={activeRunId}
          onActiveChange={(key) => nav(`/runs/${key}`)}
          menu={(conv) => ({
            items: [{ key: "open", label: "打开" }],
            onClick: () => nav(`/runs/${conv.key}`),
          })}
        />
      </div>
      <Menu
        mode="inline"
        selectedKeys={[pageKey]}
        style={{ borderInlineEnd: "none" }}
        onClick={({ key }) => nav(key)}
        items={[
          { key: "skills", icon: <TagsOutlined />, label: "Skill 版本" },
          { key: "evals", icon: <BarChartOutlined />, label: "评测结果" },
        ]}
      />
    </Layout.Sider>
  );
}

export default function App() {
  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.defaultAlgorithm,
        token: { colorPrimary: "#1a66d6", borderRadius: 10 },
      }}
    >
      <AntApp>
        <BrowserRouter>
          <Layout style={{ height: "100vh" }}>
            <Sidebar />
            <Layout style={{ background: "#f7f8fa" }}>
              <Routes>
                <Route path="/" element={<RunPage />} />
                <Route path="/runs/:runId" element={<RunPage />} />
                <Route path="/skills" element={<SkillPage />} />
                <Route path="/evals" element={<EvalPage />} />
              </Routes>
            </Layout>
          </Layout>
        </BrowserRouter>
      </AntApp>
    </ConfigProvider>
  );
}
