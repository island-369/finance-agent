import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import RunPage from "./pages/RunPage";
import SkillPage from "./pages/SkillPage";
import EvalPage from "./pages/EvalPage";

export default function App() {
  return (
    <BrowserRouter>
      <div style={{ maxWidth: 960, margin: "0 auto", padding: 16, fontFamily: "system-ui, sans-serif" }}>
        <h1 style={{ fontSize: 22 }}>金融研究 Agent 工作台</h1>
        <nav style={{ display: "flex", gap: 16, marginBottom: 20, borderBottom: "1px solid #ddd", paddingBottom: 8 }}>
          <Link to="/">任务</Link>
          <Link to="/skills">Skill 版本</Link>
          <Link to="/evals">评测结果</Link>
        </nav>
        <Routes>
          <Route path="/" element={<RunPage />} />
          <Route path="/runs/:runId" element={<RunPage />} />
          <Route path="/skills" element={<SkillPage />} />
          <Route path="/evals" element={<EvalPage />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
