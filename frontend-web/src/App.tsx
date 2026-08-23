import { FormEvent, useMemo, useState, useEffect } from "react";
import { API_BASE_URL, fetchJson } from "./api";

type Role = "admin" | "operator" | "reviewer" | "developer";
type Provider = "openai" | "anthropic" | "gemini" | "ollama";
type Stage =
  | "notes_generation"
  | "diagram_generation"
  | "activity_generation"
  | "question_generation"
  | "reviewer_panel"
  | "regeneration";

type View =
  | "dashboard"
  | "datasets"
  | "prompts"
  | "questions"
  | "targets"
  | "generation"
  | "review"
  | "providers"
  | "pipelines"
  | "browser"
  | "production";

const roleRights: Record<Role, string[]> = {
  admin: ["all"],
  operator: ["bindings", "generate", "jobs", "health", "browse", "production_read", "targets", "datasets", "prompts"],
  reviewer: ["health", "admin_config", "jobs", "review", "human_review", "production_read", "questions"],
  developer: ["health", "admin_config", "jobs", "browse", "production_read", "questions"]
};

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function hasRight(role: Role | null, right: string): boolean {
  if (!role) return false;
  const rights = roleRights[role] || [];
  return rights.includes("all") || rights.includes(right);
}

export function App() {
  const [output, setOutput] = useState("Ready");
  const [view, setView] = useState<View>("dashboard");
  const [isRunning, setIsRunning] = useState(false);

  // Authentication
  const [username, setUsername] = useState(() => localStorage.getItem("cbc_username") || "admin");
  const [password, setPassword] = useState("admin123");
  const [bearerToken, setBearerToken] = useState(() => localStorage.getItem("cbc_token") || "");
  const [apiKey, setApiKey] = useState("");
  const [currentRole, setCurrentRole] = useState<Role | null>(() => (localStorage.getItem("cbc_role") as Role) || null);
  const [currentSubject, setCurrentSubject] = useState(() => localStorage.getItem("cbc_subject") || "");

  // Providers & Stage Bindings
  const [providerDrafts, setProviderDrafts] = useState<Record<Provider, { api_key: string; base_url: string; ollama_models: string }>>({
    openai: { api_key: "", base_url: "https://api.openai.com/v1", ollama_models: "" },
    anthropic: { api_key: "", base_url: "https://api.anthropic.com", ollama_models: "" },
    gemini: { api_key: "", base_url: "https://generativelanguage.googleapis.com", ollama_models: "" },
    ollama: { api_key: "", base_url: "http://host.docker.internal:11434", ollama_models: "llama3.1,qwen2.5:7b,mistral" }
  });
  const [stageDrafts, setStageDrafts] = useState<Record<Stage, { provider: Provider; model: string; base_url: string }>>({
    notes_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    diagram_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    activity_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    question_generation: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    reviewer_panel: { provider: "openai", model: "gpt-4o-mini", base_url: "" },
    regeneration: { provider: "openai", model: "gpt-4o-mini", base_url: "" }
  });

  // Datasets & Prompts State (Langfuse)
  const [datasetsList, setDatasetsList] = useState<string[]>([]);
  const [selectedGrade, setSelectedGrade] = useState("grade-7");
  const [gradeDatasetItems, setGradeDatasetItems] = useState<any[]>([]);
  const [newSubjectName, setNewSubjectName] = useState("Integrated Science");
  const [newSubjectEssence, setNewSubjectEssence] = useState("Develops scientific inquiry, environmental conservation, and technological literacy.");
  const [selectedPromptName, setSelectedPromptName] = useState("question-generator");
  const [previewMessages, setPreviewMessages] = useState<any[]>([]);

  // Generation & Pipeline
  const [genGrade, setGenGrade] = useState("7");
  const [genSubject, setGenSubject] = useState("Integrated Science");
  const [genStrand, setGenStrand] = useState("Matter");
  const [genSubstrand, setGenSubstrand] = useState("Classification of Matter");
  const [genSloId, setGenSloId] = useState("MS-G7-ISCI-MAT-CLM-01");
  const [generationResult, setGenerationResult] = useState<any>(null);

  // Question Bank
  const [questionBank, setQuestionBank] = useState<any[]>([]);
  const [selectedQuestionDna, setSelectedQuestionDna] = useState<any>(null);

  // Targets
  const [dailyTargetData, setDailyTargetData] = useState<any>(null);
  const [targetCountInput, setTargetCountInput] = useState(100);

  // Reviews
  const [reviewItems, setReviewItems] = useState<any[]>([]);
  const [humanReviewItems, setHumanReviewItems] = useState<any[]>([]);
  const [productionItems, setProductionItems] = useState<any[]>([]);

  // Browser Agent
  const [browseUrl, setBrowseUrl] = useState("https://example.com");

  // Dynamic Curriculum Data (from Langfuse datasets)
  const [gradeSubjects, setGradeSubjects] = useState<any[]>([]);
  const [subjectStrands, setSubjectStrands] = useState<any[]>([]);
  const [substrandSlos, setSubstrandSlos] = useState<string[]>([]);

  // Global BECF Context
  const [masterContext, setMasterContext] = useState("");
  const [masterContextMeta, setMasterContextMeta] = useState<any>(null);
  const [masterContextDraft, setMasterContextDraft] = useState("");

  // Cost Tracking
  const [costSummary, setCostSummary] = useState<any>(null);
  const [generationCosts, setGenerationCosts] = useState<any>(null);

  // Error banner state
  const [errorBanner, setErrorBanner] = useState<{code: string; message: string; retryable: boolean} | null>(null);

  const title = useMemo(() => `CBC API Platform`, []);

  function auth() {
    return {
      bearerToken: bearerToken || undefined,
      apiKey: apiKey || undefined
    };
  }

  async function run<T>(label: string, fn: () => Promise<T>): Promise<T | undefined> {
    try {
      setIsRunning(true);
      setOutput(`${label}...`);
      setErrorBanner(null);
      const result = await fn();
      setOutput(pretty(result));
      return result;
    } catch (error) {
      // Parse structured API errors
      let errMsg = error instanceof Error ? error.message : String(error);
      try {
        const parsed = JSON.parse(errMsg);
        if (parsed.errors?.[0]) {
          const apiErr = parsed.errors[0];
          setErrorBanner({ code: apiErr.code, message: apiErr.message, retryable: apiErr.retryable || false });
          errMsg = pretty(parsed);
        }
      } catch { /* not JSON, use raw message */ }
      setOutput(errMsg);
      return undefined;
    } finally {
      setIsRunning(false);
    }
  }

  async function onLoginSubmit(event: FormEvent) {
    event.preventDefault();
    await run("Login", async () => {
      const result = await fetchJson<{ access_token: string; role: Role; subject: string }>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
      });
      setBearerToken(result.access_token);
      setCurrentRole(result.role);
      setCurrentSubject(result.subject);
      localStorage.setItem("cbc_token", result.access_token);
      localStorage.setItem("cbc_role", result.role);
      localStorage.setItem("cbc_subject", result.subject);
      localStorage.setItem("cbc_username", username);
      setView("dashboard");
      return result;
    });
  }

  function logout() {
    setBearerToken("");
    setApiKey("");
    setCurrentRole(null);
    setCurrentSubject("");
    localStorage.removeItem("cbc_token");
    localStorage.removeItem("cbc_role");
    localStorage.removeItem("cbc_subject");
    setOutput("Logged out");
  }

  // Load Langfuse Datasets
  async function loadDatasets() {
    await run("Load Datasets", async () => {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/datasets", { method: "GET" }, auth());
      const list = res.datasets?.map((d: any) => d.name) || [];
      setDatasetsList(list);
      return res;
    });
  }

  async function loadGradeDataset(gradeSlug: string) {
    await run(`Load ${gradeSlug}`, async () => {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}`, { method: "GET" }, auth());
      setGradeDatasetItems(res.items || []);
      return res;
    });
  }

  async function onUploadSubjectContext(event: FormEvent) {
    event.preventDefault();
    await run("Upload Subject Context", async () => {
      const payload = {
        subject: newSubjectName,
        subject_code: newSubjectName.slice(0, 4).toUpperCase(),
        essence_statement: newSubjectEssence,
        strands: [{ name: genStrand, sub_strands: [{ name: genSubstrand, slos: [genSloId] }] }]
      };
      const res = await fetchJson(`/api/v1/admin/langfuse/datasets/${selectedGrade}`, {
        method: "POST",
        body: JSON.stringify(payload)
      }, auth());
      await loadGradeDataset(selectedGrade);
      return res;
    });
  }

  async function previewPromptContext() {
    await run("Preview Prompt Context", async () => {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/context/preview", {
        method: "POST",
        body: JSON.stringify({
          grade: genGrade,
          subject: genSubject,
          agent_name: selectedPromptName,
          template_vars: { strand: genStrand, sub_strand: genSubstrand, slo_id: genSloId }
        })
      }, auth());
      setPreviewMessages(res.messages || []);
      return res;
    });
  }

  // Question Bank
  async function loadQuestionBank() {
    await run("Load Question Bank", async () => {
      const res = await fetchJson<any>("/api/v1/questions?limit=50", { method: "GET" }, auth());
      setQuestionBank(res.items || []);
      return res;
    });
  }

  async function triggerQuestionAction(questionId: string, action: "re-create" | "regenerate" | "re-review") {
    await run(`Action: ${action}`, async () => {
      const res = await fetchJson(`/api/v1/questions/${questionId}/action`, {
        method: "POST",
        body: JSON.stringify({ action })
      }, auth());
      await loadQuestionBank();
      return res;
    });
  }

  // Targets
  async function loadTodayTarget() {
    await run("Load Targets", async () => {
      const res = await fetchJson<any>("/api/v1/targets/today", { method: "GET" }, auth());
      setDailyTargetData(res);
      return res;
    });
  }

  async function configureTargetSubmit(event: FormEvent) {
    event.preventDefault();
    await run("Configure Target", async () => {
      const res = await fetchJson("/api/v1/targets/configure", {
        method: "POST",
        body: JSON.stringify({ target_count: Number(targetCountInput) })
      }, auth());
      setDailyTargetData(res);
      return res;
    });
  }

  // Real Generation
  async function triggerGenerate() {
    await run("Generate Content", async () => {
      const payload = {
        request_id: `req_${Date.now()}`,
        trace_id: `trc_${Date.now()}`,
        tenant_id: "cbc_web",
        actor: { type: "admin", id: currentSubject || "admin" },
        curriculum: {
          level: "Middle School",
          grade: genGrade,
          subject: genSubject,
          subject_code: genSubject.slice(0, 4).toUpperCase(),
          pathway: null,
          track: null,
          strand: genStrand,
          sub_strand: genSubstrand,
          slo_id: genSloId
        },
        controls: {
          idempotency_key: `idem_${Date.now()}`,
          deadline_ms: 120000,
          max_regen_attempts: 2,
          environment: "prod"
        }
      };

      const res = await fetchJson<any>("/pipeline/generate", {
        method: "POST",
        body: JSON.stringify(payload)
      }, auth());

      setGenerationResult(res.result?.published_bundle || res.result);
      setGenerationCosts(res.provenance?.cost_summary || res.result?.cost_summary || null);
      return res;
    });
  }

  // Dynamic Curriculum Cascade
  async function loadGradeSubjects(gradeSlug: string) {
    try {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}/subjects`, { method: "GET" }, auth());
      setGradeSubjects(res.subjects || []);
      setGenSubject("");
      setSubjectStrands([]);
      setSubstrandSlos([]);
      setGenStrand("");
      setGenSubstrand("");
      setGenSloId("");
    } catch(e) {
      setGradeSubjects([]);
    }
  }

  async function loadSubjectStrands(gradeSlug: string, subject: string) {
    try {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}/${encodeURIComponent(subject)}/strands`, { method: "GET" }, auth());
      setSubjectStrands(res.strands || []);
      setSubstrandSlos([]);
      setGenStrand("");
      setGenSubstrand("");
      setGenSloId("");
    } catch(e) {
      setSubjectStrands([]);
    }
  }

  async function loadSubstrandSlos(gradeSlug: string, subject: string, strand: string, subStrand: string) {
    try {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}/${encodeURIComponent(subject)}/strands/${encodeURIComponent(strand)}/${encodeURIComponent(subStrand)}/slos`, { method: "GET" }, auth());
      setSubstrandSlos(res.slos || []);
      setGenSloId("");
    } catch(e) {
      setSubstrandSlos([]);
    }
  }

  // Global BECF Context
  async function loadMasterContext() {
    try {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/context/master", { method: "GET" }, auth());
      setMasterContext(res.text || "");
      setMasterContextDraft(res.text || "");
      setMasterContextMeta(res);
    } catch(e) { /* ignore */ }
  }

  async function saveMasterContext() {
    await run("Save Master Context", async () => {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/context/master", {
        method: "PUT",
        body: JSON.stringify({ text: masterContextDraft })
      }, auth());
      setMasterContext(masterContextDraft);
      setMasterContextMeta(res);
      return res;
    });
  }

  async function seedLangfuse() {
    await run("Seed Langfuse", async () => {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/seed", { method: "POST" }, auth());
      await loadDatasets();
      return res;
    });
  }

  // Cost tracking
  async function loadCostSummary() {
    try {
      const res = await fetchJson<any>("/api/v1/costs/summary", { method: "GET" }, auth());
      setCostSummary(res);
    } catch(e) { /* ignore */ }
  }

  // Dashboard Refresh
  async function refreshDashboard() {
    await Promise.all([loadTodayTarget(), loadQuestionBank(), loadCostSummary()]);
  }

  useEffect(() => {
    if (currentRole) {
      loadDatasets();
      loadGradeDataset(selectedGrade);
      loadGradeSubjects(selectedGrade);
      loadTodayTarget();
      loadQuestionBank();
      loadCostSummary();
      loadMasterContext();
    }
  }, [currentRole]);

  const canAdmin = hasRight(currentRole, "all");

  const navItems: Array<{ id: View; label: string; right: string }> = [
    { id: "dashboard", label: "Dashboard", right: "health" },
    { id: "datasets", label: "Datasets (Langfuse)", right: "datasets" },
    { id: "prompts", label: "Prompt Builder", right: "prompts" },
    { id: "generation", label: "Generation", right: "generate" },
    { id: "questions", label: "Questions & DNA", right: "questions" },
    { id: "targets", label: "Targets & Alerts", right: "targets" },
    { id: "review", label: "Review & Quality", right: "review" },
    { id: "providers", label: "Model Providers", right: "all" },
    { id: "pipelines", label: "Stage Bindings", right: "bindings" },
    { id: "browser", label: "Browser Agent", right: "browse" },
    { id: "production", label: "Production Bundles", right: "production_read" }
  ];

  if (!currentRole) {
    return (
      <div className="login-shell">
        <section className="login-art">
          <h1>{title}</h1>
          <p>Contract-first multi-agent production platform for Kenyan CBC educational content, Question DNA, and vector diagrams.</p>
        </section>

        <section className="login-card">
          <h2>Sign In to Control Plane</h2>
          <form onSubmit={onLoginSubmit} className="stack">
            <label>
              Role
              <select value={username} onChange={(e) => setUsername(e.target.value)}>
                <option value="admin">Admin</option>
                <option value="operator">Operator</option>
                <option value="reviewer">Reviewer</option>
                <option value="developer">Developer</option>
              </select>
            </label>
            <label>
              Username
              <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" />
            </label>
            <label>
              Password
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="password" />
            </label>
            <button type="submit" disabled={isRunning}>Sign In</button>
          </form>
        </section>
      </div>
    );
  }

  return (
    <div className="cp-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">C</span>
          <div>
            <strong>CBC API</strong>
            <small>Platform Control Room</small>
          </div>
        </div>

        <nav>
          {navItems
            .filter((item) => hasRight(currentRole, item.right) || (item.right === "all" && canAdmin))
            .map((item) => (
              <button key={item.id} className={`nav-item ${view === item.id ? "active" : ""}`} onClick={() => setView(item.id)}>
                {item.label}
              </button>
            ))}
        </nav>

        <div className="sidebar-footer">
          <button className="ghost" onClick={logout}>Sign out</button>
          <small>{currentSubject} ({currentRole})</small>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <h1>{title}</h1>
          <div className="topbar-actions">
            <button className="ghost" onClick={refreshDashboard}>Refresh Data</button>
          </div>
        </header>

        {errorBanner && (
          <div className={`error-banner ${errorBanner.retryable ? 'warn' : 'danger'}`}>
            <span className="error-icon">
              {errorBanner.code === 'LLM_CREDIT_EXHAUSTED' ? '💳' :
               errorBanner.code === 'LLM_RATE_LIMITED' ? '⏳' :
               errorBanner.code === 'LANGFUSE_UNAVAILABLE' ? '🔌' :
               errorBanner.code === 'MISSING_CONTEXT_LAYER' ? '📋' :
               errorBanner.code === 'MODEL_CREDENTIAL_MISSING' ? '🔑' :
               errorBanner.code.startsWith('LLM_') ? '🤖' : '⚠️'}
            </span>
            <div className="error-content">
              <strong>{errorBanner.code}</strong>
              <p>{errorBanner.message}</p>
              {errorBanner.retryable && <small>This error is retryable — the system will attempt again automatically.</small>}
            </div>
            <button className="ghost" onClick={() => setErrorBanner(null)}>✕</button>
          </div>
        )}

        {/* 1. DASHBOARD TAB */}
        {view === "dashboard" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>System Overview</h2>
                <p>Live generation telemetry, Question DNA metrics, and daily production target status.</p>
              </div>
            </div>

            <div className="kpi-grid">
              <article className="kpi">
                <h3>Today's Target</h3>
                <p>{dailyTargetData?.target_count || 100}</p>
              </article>
              <article className="kpi">
                <h3>Completed Today</h3>
                <p>{dailyTargetData?.completed_count || 0}</p>
              </article>
              <article className="kpi">
                <h3>Approved Items</h3>
                <p>{dailyTargetData?.approved_count || 0}</p>
              </article>
              <article className="kpi">
                <h3>Question Bank Total</h3>
                <p>{questionBank.length}</p>
              </article>
            </div>

            {costSummary && (
              <div className="kpi-grid" style={{marginTop: '1rem'}}>
                <div className="kpi">
                  <div className="muted">Total Tokens Used</div>
                  <div className="kpi-value">{(costSummary.total_tokens || 0).toLocaleString()}</div>
                </div>
                <div className="kpi">
                  <div className="muted">Total Cost (USD)</div>
                  <div className="kpi-value">${(costSummary.total_cost_usd || 0).toFixed(4)}</div>
                </div>
                <div className="kpi">
                  <div className="muted">Total Runs</div>
                  <div className="kpi-value">{costSummary.total_runs || 0}</div>
                </div>
                <div className="kpi">
                  <div className="muted">Avg Cost / Run</div>
                  <div className="kpi-value">${(costSummary.avg_cost_per_run || 0).toFixed(4)}</div>
                </div>
              </div>
            )}

            <div className="surface">
              <h3>Daily Target Progress</h3>
              <div className="progress-bar-wrap">
                <div
                  className="progress-bar"
                  style={{
                    width: `${Math.min(100, Math.round(((dailyTargetData?.completed_count || 0) / (dailyTargetData?.target_count || 100)) * 100))}%`
                  }}
                />
              </div>
              <div className="milestone-badges">
                <span>0%</span>
                <span className={(dailyTargetData?.completed_count || 0) >= (dailyTargetData?.target_count || 100) * 0.25 ? "active" : ""}>25% Milestone</span>
                <span className={(dailyTargetData?.completed_count || 0) >= (dailyTargetData?.target_count || 100) * 0.5 ? "active" : ""}>50% Milestone</span>
                <span className={(dailyTargetData?.completed_count || 0) >= (dailyTargetData?.target_count || 100) * 0.75 ? "active" : ""}>75% Milestone</span>
                <span className={(dailyTargetData?.completed_count || 0) >= (dailyTargetData?.target_count || 100) ? "active" : ""}>100% Goal</span>
              </div>
            </div>
          </section>
        )}

        {/* 2. DATASETS (LANGFUSE) TAB */}
        {view === "datasets" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Langfuse Curriculum Datasets</h2>
                <p>Browse and upload KICD curriculum design essence statements, strands, and SLOs stored dynamically in Langfuse.</p>
              </div>
            </div>

            <div className="panel" style={{marginTop: '1rem', marginBottom: '1rem'}}>
              <div className="panel-head">
                📜 Global BECF Context
                <button className="ghost" onClick={loadMasterContext} style={{marginLeft: 'auto', fontSize: '0.8rem'}}>Refresh</button>
              </div>
              {masterContextMeta && (
                <div style={{padding: '0.5rem 1rem', fontSize: '0.8rem', color: 'var(--muted)'}}>
                  Prompt: {masterContextMeta.prompt_name} | Version: {masterContextMeta.prompt_version} | Label: {masterContextMeta.prompt_label}
                </div>
              )}
              <div style={{padding: '0 1rem 1rem'}}>
                <textarea
                  value={masterContextDraft}
                  onChange={(e) => setMasterContextDraft(e.target.value)}
                  rows={12}
                  style={{width: '100%', fontFamily: 'monospace', fontSize: '0.85rem'}}
                  placeholder="Paste the full KICD BECF master context here..."
                />
                <div style={{display: 'flex', gap: '0.5rem', marginTop: '0.5rem'}}>
                  <button onClick={saveMasterContext} disabled={isRunning}>Save to Langfuse</button>
                  <button className="ghost" onClick={seedLangfuse} disabled={isRunning}>Seed Langfuse (Create All Prompts & Datasets)</button>
                </div>
              </div>
            </div>

            <div className="two-col">
              <div className="surface">
                <h3>Select Grade Dataset</h3>
                <select value={selectedGrade} onChange={(e) => { setSelectedGrade(e.target.value); loadGradeDataset(e.target.value); }}>
                  {datasetsList.map((d) => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>

                <h4 style={{ marginTop: "16px" }}>Subjects in {selectedGrade}:</h4>
                {gradeDatasetItems.length === 0 ? (
                  <p className="muted">No subjects loaded for this grade.</p>
                ) : (
                  gradeDatasetItems.map((item, idx) => (
                    <div key={idx} className="card-item">
                      <strong>{item.input?.subject || "Subject"}</strong>
                      <p className="muted" style={{ fontSize: "12px", marginTop: "4px" }}>{item.metadata?.essence_statement || "No essence statement"}</p>
                    </div>
                  ))
                )}
              </div>

              <div className="surface">
                <h3>Upload New Subject Context Item</h3>
                <form onSubmit={onUploadSubjectContext} className="stack">
                  <label>
                    Subject Name
                    <input value={newSubjectName} onChange={(e) => setNewSubjectName(e.target.value)} />
                  </label>
                  <label>
                    Essence Statement
                    <textarea rows={4} value={newSubjectEssence} onChange={(e) => setNewSubjectEssence(e.target.value)} />
                  </label>
                  <button type="submit" disabled={isRunning}>Upload to Langfuse</button>
                </form>
              </div>
            </div>
          </section>
        )}

        {/* 3. PROMPT BUILDER TAB */}
        {view === "prompts" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Langfuse Dynamic Prompt Builder</h2>
                <p>Inspect master context and test-compile agent prompts with live variables.</p>
              </div>
            </div>

            <div className="two-col">
              <div className="surface">
                <h3>Select Agent Prompt</h3>
                <select value={selectedPromptName} onChange={(e) => setSelectedPromptName(e.target.value)}>
                  <option value="note-generator">note-generator</option>
                  <option value="diagram-generator">diagram-generator</option>
                  <option value="activity-generator">activity-generator</option>
                  <option value="question-generator">question-generator</option>
                  <option value="reviewer-panel">reviewer-panel</option>
                </select>
                <button style={{ marginTop: "12px" }} onClick={previewPromptContext} disabled={isRunning}>Compile & Preview</button>
              </div>

              <div className="surface">
                <h3>Assembled Message Stack</h3>
                <pre>{pretty(previewMessages)}</pre>
              </div>
            </div>
          </section>
        )}

        {/* 4. GENERATION TAB */}
        {view === "generation" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Real-Time Content Generation</h2>
                <p>Trigger Notes, SVG Diagrams, Activities, and Questions with Question DNA lineage.</p>
              </div>
            </div>

            <div className="surface">
              <div className="three-col">
                <label>
                  Grade
                  <select value={genGrade} onChange={(e) => {
                    const g = e.target.value;
                    setGenGrade(g);
                    const slug = g.startsWith('grade-') ? g : (g === 'pp1' || g === 'pp2' ? `grade-${g}` : `grade-${g}`);
                    loadGradeSubjects(slug);
                  }}>
                    <option value="">Select grade...</option>
                    {datasetsList.map(d => <option key={d} value={d}>{d}</option>)}
                  </select>
                </label>
                <label>
                  Subject
                  <select value={genSubject} onChange={(e) => {
                    setGenSubject(e.target.value);
                    const slug = genGrade.startsWith('grade-') ? genGrade : `grade-${genGrade}`;
                    if (e.target.value) loadSubjectStrands(slug, e.target.value);
                  }}>
                    <option value="">Select subject...</option>
                    {gradeSubjects.map((s: any) => <option key={s.name || s} value={s.name || s}>{s.name || s}</option>)}
                  </select>
                </label>
                <label>
                  Strand
                  <select value={genStrand} onChange={(e) => {
                    setGenStrand(e.target.value);
                    setGenSubstrand("");
                    setGenSloId("");
                    setSubstrandSlos([]);
                  }}>
                    <option value="">Select strand...</option>
                    {subjectStrands.map((s: any) => <option key={s.name} value={s.name}>{s.name}</option>)}
                  </select>
                </label>
              </div>
              <div className="two-col" style={{ marginTop: "12px" }}>
                <label>
                  Sub-Strand
                  <select value={genSubstrand} onChange={(e) => {
                    setGenSubstrand(e.target.value);
                    if (e.target.value) {
                      const slug = genGrade.startsWith('grade-') ? genGrade : `grade-${genGrade}`;
                      loadSubstrandSlos(slug, genSubject, genStrand, e.target.value);
                    }
                  }}>
                    <option value="">Select sub-strand...</option>
                    {subjectStrands.find((s: any) => s.name === genStrand)?.sub_strands?.map((ss: any) => (
                      <option key={ss.name} value={ss.name}>{ss.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  SLO ID
                  <select value={genSloId} onChange={(e) => setGenSloId(e.target.value)}>
                    <option value="">Select SLO...</option>
                    {substrandSlos.map(slo => <option key={slo} value={slo}>{slo}</option>)}
                  </select>
                </label>
              </div>
              <button style={{ marginTop: "16px" }} onClick={triggerGenerate} disabled={isRunning}>
                {isRunning ? "Generating with LLM..." : "Run Real Generation Pipeline"}
              </button>
            </div>

            {generationResult && (
              <div className="surface" style={{ marginTop: "16px" }}>
                <h3>Generated Resource Bundle ({generationResult.bundle_id})</h3>
                <h4>Notes: {generationResult.notes?.title}</h4>
                <p>{generationResult.notes?.intro}</p>

                {generationResult.diagrams?.[0]?.diagram_svg && (
                  <div>
                    <h4>Generated Vector Diagram (SHA-256 Deduplicated):</h4>
                    <div
                      className="svg-preview"
                      dangerouslySetInnerHTML={{ __html: generationResult.diagrams[0].diagram_svg }}
                    />
                    <small className="muted">Alt Text: {generationResult.diagrams[0].accessibility?.alt_text}</small>
                  </div>
                )}

                <h4>Questions ({generationResult.questions?.length}):</h4>
                {generationResult.questions?.map((q: any, idx: number) => (
                  <div key={idx} className="card-item">
                    <strong>{q.content?.question_type?.toUpperCase()}: {q.content?.question_text}</strong>
                    <div style={{ marginTop: "6px" }}>
                      <span className="pill ok">Meeting Rubric: {q.content?.marking_guide?.meeting}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {generationCosts && (
              <div className="panel" style={{marginTop: '1rem'}}>
                <div className="panel-head">💰 Generation Cost Breakdown</div>
                <div className="kpi-grid">
                  <div className="kpi">
                    <div className="muted">Total Tokens</div>
                    <div className="kpi-value">{(generationCosts.total_tokens || 0).toLocaleString()}</div>
                  </div>
                  <div className="kpi">
                    <div className="muted">Total Cost</div>
                    <div className="kpi-value">${(generationCosts.total_cost_usd || 0).toFixed(4)}</div>
                  </div>
                </div>
                {generationCosts.stages && (
                  <table style={{width: '100%', marginTop: '0.5rem', fontSize: '0.85rem'}}>
                    <thead>
                      <tr style={{textAlign: 'left'}}>
                        <th>Stage</th><th>Model</th><th>Prompt Tokens</th><th>Completion</th><th>Cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {generationCosts.stages.map((s: any, i: number) => (
                        <tr key={i}>
                          <td>{s.model}</td><td>{s.provider}</td>
                          <td>{(s.prompt_tokens || 0).toLocaleString()}</td>
                          <td>{(s.completion_tokens || 0).toLocaleString()}</td>
                          <td>${(s.cost_usd || 0).toFixed(4)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}
          </section>
        )}

        {/* 5. QUESTIONS & DNA TAB */}
        {view === "questions" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Question DNA Bank</h2>
                <p>Browse generated assessment questions, inspect cryptographic provenance, and trigger lifecycle actions.</p>
              </div>
            </div>

            <div className="split">
              <div className="surface">
                <h3>Question Repository</h3>
                {questionBank.map((q: any) => (
                  <div key={q.question_id} className="card-item">
                    <div className="card-item-head">
                      <strong>{q.question_id}</strong>
                      <span className="pill ok">{q.status}</span>
                    </div>
                    <p style={{ fontSize: "13px", margin: "4px 0" }}>{q.content?.question_text}</p>
                    <div className="inline wrap" style={{ marginTop: "8px" }}>
                      <button className="ghost" style={{ fontSize: "11px", padding: "4px 8px" }} onClick={() => setSelectedQuestionDna(q)}>Inspect DNA</button>
                      <button className="ghost" style={{ fontSize: "11px", padding: "4px 8px" }} onClick={() => triggerQuestionAction(q.question_id, "re-create")}>Re-create</button>
                      <button className="ghost" style={{ fontSize: "11px", padding: "4px 8px" }} onClick={() => triggerQuestionAction(q.question_id, "regenerate")}>Regenerate</button>
                      <button className="ghost" style={{ fontSize: "11px", padding: "4px 8px" }} onClick={() => triggerQuestionAction(q.question_id, "re-review")}>Re-review</button>
                    </div>
                  </div>
                ))}
              </div>

              <div className="surface">
                <h3>Question DNA Inspector</h3>
                {selectedQuestionDna ? (
                  <pre>{pretty(selectedQuestionDna)}</pre>
                ) : (
                  <p className="muted">Select a question to inspect full lineage and provenance.</p>
                )}
              </div>
            </div>
          </section>
        )}

        {/* 6. TARGETS TAB */}
        {view === "targets" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Daily Production Targets & Alerts</h2>
                <p>Configure daily quotas and track automatic 25%, 50%, 75%, 100% milestone email dispatches.</p>
              </div>
            </div>

            <div className="two-col">
              <div className="surface">
                <h3>Target Configuration</h3>
                <form onSubmit={configureTargetSubmit} className="stack">
                  <label>
                    Daily Target Items
                    <input type="number" value={targetCountInput} onChange={(e) => setTargetCountInput(Number(e.target.value))} />
                  </label>
                  <button type="submit" disabled={isRunning}>Save Daily Target</button>
                </form>
              </div>

              <div className="surface">
                <h3>Current Target Metrics</h3>
                <pre>{pretty(dailyTargetData)}</pre>
              </div>
            </div>
          </section>
        )}

        {/* 7. PROVIDERS TAB */}
        {view === "providers" && canAdmin && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Model Providers & Credentials</h2>
                <p>Manage OpenAI, Anthropic, Gemini, and Ollama encrypted keys and endpoints.</p>
              </div>
            </div>
            <div className="provider-grid">
              {(["openai", "anthropic", "gemini", "ollama"] as Provider[]).map((p) => (
                <article key={p} className="provider-card">
                  <div className="provider-head">
                    <h3>{p.toUpperCase()}</h3>
                  </div>
                  <label>
                    API Key
                    <input
                      type="password"
                      value={providerDrafts[p].api_key}
                      onChange={(e) => setProviderDrafts({ ...providerDrafts, [p]: { ...providerDrafts[p], api_key: e.target.value } })}
                    />
                  </label>
                  <label>
                    Base URL
                    <input
                      value={providerDrafts[p].base_url}
                      onChange={(e) => setProviderDrafts({ ...providerDrafts, [p]: { ...providerDrafts[p], base_url: e.target.value } })}
                    />
                  </label>
                </article>
              ))}
            </div>
          </section>
        )}

        {/* 8. PIPELINES TAB */}
        {view === "pipelines" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Stage-to-Model Bindings</h2>
                <p>Configure which LLM powers each stage (notes, diagrams, activities, questions, reviewers).</p>
              </div>
            </div>
            <pre>{pretty(stageDrafts)}</pre>
          </section>
        )}

        {/* 9. BROWSER AGENT TAB */}
        {view === "browser" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Playwright Browser Verification Agent</h2>
                <p>Execute live web verification for curriculum resources.</p>
              </div>
            </div>
            <div className="surface">
              <label>
                Target URL
                <input value={browseUrl} onChange={(e) => setBrowseUrl(e.target.value)} />
              </label>
              <button style={{ marginTop: "10px" }} onClick={() => run("Browse", () => fetchJson("/agents/browse", { method: "POST", body: JSON.stringify({ url: browseUrl }) }, auth()))}>
                Execute Browser Page Analysis
              </button>
            </div>
          </section>
        )}

        {/* CONSOLE OUTPUT PANEL */}
        <section className="panel console-panel">
          <h3>System Console</h3>
          <pre>{output}</pre>
        </section>
      </main>
    </div>
  );
}
