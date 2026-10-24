import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import RunPage from "./pages/RunPage";
import SkillPage from "./pages/SkillPage";
import EvalPage from "./pages/EvalPage";

export default function App() {
  return (
    <BrowserRouter>
      <header className="app-header">
        <div className="inner">
          <span className="brand">
            <span className="logo">FA</span>
            金融研究 Agent 工作台
          </span>
          <nav className="app-nav">
            <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : "")}>
              任务
            </NavLink>
            <NavLink to="/skills" className={({ isActive }) => (isActive ? "active" : "")}>
              Skill 版本
            </NavLink>
            <NavLink to="/evals" className={({ isActive }) => (isActive ? "active" : "")}>
              评测结果
            </NavLink>
          </nav>
          <span className="header-meta">M0–M5 · deepagents · 合成样本演示</span>
        </div>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<RunPage />} />
          <Route path="/runs/:runId" element={<RunPage />} />
          <Route path="/skills" element={<SkillPage />} />
          <Route path="/evals" element={<EvalPage />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
