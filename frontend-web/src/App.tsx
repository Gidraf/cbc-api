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
  const [genGrade, setGenGrade] = useState("grade-7");
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

  // Human Review & Production Bundles
  const [reviewBundles, setReviewBundles] = useState<any[]>([]);
  const [reviewFilter, setReviewFilter] = useState("human_review_queue");
  const [selectedBundleForModal, setSelectedBundleForModal] = useState<any>(null);
  const [reviewNotesInput, setReviewNotesInput] = useState("");

  // Browser Agent
  const [browseUrl, setBrowseUrl] = useState("https://example.com");

  // Dynamic Curriculum Data
  const [gradeSubjects, setGradeSubjects] = useState<any[]>([]);
  const [subjectStrands, setSubjectStrands] = useState<any[]>([]);
  const [substrandSlos, setSubstrandSlos] = useState<string[]>([]);
  const [rawCurriculumInput, setRawCurriculumInput] = useState("");
  const [ingestedDesignResult, setIngestedDesignResult] = useState<any>(null);

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
    } catch (err: any) {
      const errBody = err?.payload || {};
      const errCode = errBody?.error?.code || "UNEXPECTED_ERROR";
      const errMsg = errBody?.error?.message || err.message || "An unexpected error occurred.";
      const retryable = errBody?.error?.retryable || false;

      setErrorBanner({ code: errCode, message: errMsg, retryable });
      setOutput(`Error (${errCode}): ${errMsg}`);
      return undefined;
    } finally {
      setIsRunning(false);
    }
  }

  // Authentication Handlers
  async function onLoginSubmit(e: FormEvent) {
    e.preventDefault();
    await run("Signing in", async () => {
      const res = await fetchJson<any>("/api/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password })
      });
      setBearerToken(res.access_token);
      setCurrentRole(res.user.role);
      setCurrentSubject(res.user.subject_scope || "");
      localStorage.setItem("cbc_token", res.access_token);
      localStorage.setItem("cbc_role", res.user.role);
      localStorage.setItem("cbc_username", username);
      localStorage.setItem("cbc_subject", res.user.subject_scope || "");
      return res;
    });
  }

  function logout() {
    setBearerToken("");
    setCurrentRole(null);
    localStorage.removeItem("cbc_token");
    localStorage.removeItem("cbc_role");
    localStorage.removeItem("cbc_username");
  }

  // Dynamic Curriculum Cascade
  async function loadGradeSubjects(gradeSlug: string) {
    try {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}/subjects`, { method: "GET" }, auth());
      const subs = res.subjects || [];
      setGradeSubjects(subs);
      if (subs.length > 0) {
        const firstSub = subs[0].name || subs[0];
        setGenSubject(firstSub);
        await loadSubjectStrands(gradeSlug, firstSub);
      }
    } catch(e) {
      setGradeSubjects([]);
    }
  }

  async function loadSubjectStrands(gradeSlug: string, subject: string) {
    try {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}/subjects/${encodeURIComponent(subject)}/strands`, { method: "GET" }, auth());
      const strands = res.strands || [];
      setSubjectStrands(strands);
      if (strands.length > 0) {
        const firstStrand = strands[0].name;
        setGenStrand(firstStrand);
        const subList = strands[0].sub_strands || [];
        if (subList.length > 0) {
          const firstSub = subList[0].name || subList[0];
          setGenSubstrand(firstSub);
          await loadSubstrandSlos(gradeSlug, subject, firstStrand, firstSub);
        }
      }
    } catch(e) {
      setSubjectStrands([]);
    }
  }

  async function loadSubstrandSlos(gradeSlug: string, subject: string, strand: string, subStrand: string) {
    try {
      const res = await fetchJson<any>(
        `/api/v1/admin/langfuse/datasets/${gradeSlug}/subjects/${encodeURIComponent(subject)}/strands/${encodeURIComponent(strand)}/substrands/${encodeURIComponent(subStrand)}/slos`,
        { method: "GET" },
        auth()
      );
      const slos = res.slos || [];
      setSubstrandSlos(slos);
      if (slos.length > 0) {
        setGenSloId(slos[0]);
      }
    } catch(e) {
      setSubstrandSlos([]);
    }
  }

  // Datasets Management
  async function loadDatasets() {
    try {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/datasets", { method: "GET" }, auth());
      setDatasetsList(res.datasets || []);
    } catch(e) { /* ignore */ }
  }

  async function loadGradeDataset(gradeSlug: string) {
    try {
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${gradeSlug}`, { method: "GET" }, auth());
      setGradeDatasetItems(res.items || []);
    } catch(e) { /* ignore */ }
  }

  async function onUploadSubjectContext(e: FormEvent) {
    e.preventDefault();
    await run("Upload Subject Context to Langfuse", async () => {
      const payload = {
        subject: newSubjectName,
        essence_statement: newSubjectEssence,
        strands: []
      };
      const res = await fetchJson<any>(`/api/v1/admin/langfuse/datasets/${selectedGrade}/items`, {
        method: "POST",
        body: JSON.stringify(payload)
      }, auth());
      await loadGradeDataset(selectedGrade);
      return res;
    });
  }

  // Master Context Management
  async function loadMasterContext() {
    try {
      const res = await fetchJson<any>("/api/v1/admin/langfuse/context/master", { method: "GET" }, auth());
      setMasterContext(res.master_context || "");
      setMasterContextDraft(res.master_context || "");
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

  async function onIngestRawCurriculum() {
    if (!rawCurriculumInput.trim()) return;
    await run("Ingest & Structure Raw Curriculum", async () => {
      let bodyPayload: any = { raw_text: rawCurriculumInput };
      try {
        const parsed = JSON.parse(rawCurriculumInput);
        bodyPayload = { raw_payload: parsed };
      } catch {
        // Plain text format
      }
      const res = await fetchJson<any>("/api/v1/curriculum/ingest-raw", {
        method: "POST",
        body: JSON.stringify(bodyPayload)
      }, auth());
      setIngestedDesignResult(res);
      await loadDatasets();
      if (res.grade) {
        setSelectedGrade(res.grade);
        setGenGrade(res.grade);
        await loadGradeDataset(res.grade);
        await loadGradeSubjects(res.grade);
      }
      return res;
    });
  }

  async function syncLangfuseDatasets() {
    await run("Pull & Structure All Datasets from Langfuse", async () => {
      const res = await fetchJson<any>("/api/v1/curriculum/sync-langfuse-datasets", {
        method: "POST"
      }, auth());
      await loadDatasets();
      if (res.structured_blueprints && res.structured_blueprints.length > 0) {
        setIngestedDesignResult(res.structured_blueprints[0]);
        const firstGrade = res.structured_blueprints[0].grade;
        if (firstGrade) {
          setSelectedGrade(firstGrade);
          setGenGrade(firstGrade);
          await loadGradeDataset(firstGrade);
          await loadGradeSubjects(firstGrade);
        }
      }
      return res;
    });
  }

  // Prompt preview
  async function previewPromptContext() {
    await run("Assemble Prompt Context", async () => {
      const slug = genGrade.startsWith("grade-") ? genGrade : `grade-${genGrade}`;
      const payload = {
        agent_name: selectedPromptName,
        grade_slug: slug,
        subject: genSubject,
        template_vars: {
          level: "Basic Education",
          strand: genStrand,
          sub_strand: genSubstrand,
          slo_id: genSloId,
        }
      };
      const res = await fetchJson<any>("/api/v1/admin/langfuse/prompts/preview", {
        method: "POST",
        body: JSON.stringify(payload)
      }, auth());
      setPreviewMessages(res.messages || []);
      return res;
    });
  }

  // Generation & Pipeline Execution
  async function triggerGenerate() {
    await run("Run Full CBC Production Pipeline", async () => {
      const slug = genGrade.startsWith("grade-") ? genGrade : `grade-${genGrade}`;
      const payload = {
        request_id: `req_${Date.now()}`,
        trace_id: `trace_${Date.now()}`,
        curriculum: {
          grade: slug,
          subject: genSubject,
          subject_code: genSubject.substring(0, 4).toUpperCase(),
          strand: genStrand,
          sub_strand: genSubstrand,
          slo_id: genSloId || "SLO-GEN",
          level: "Basic Education"
        },
        controls: {
          environment: "production",
          strict_validation: true,
          force_refresh: true
        }
      };
      const res = await fetchJson<any>("/generate", {
        method: "POST",
        body: JSON.stringify(payload)
      }, auth());

      const result = res.result || {};
      setGenerationResult(result.published_bundle || {});
      setGenerationCosts(result.cost_summary || {});
      await Promise.all([loadQuestionBank(), loadCostSummary(), loadReviewBundles(reviewFilter)]);
      return res;
    });
  }

  // Human Review & Bundles Management
  async function loadReviewBundles(status: string = "human_review_queue") {
    try {
      const query = status === "all" ? "" : `?status=${status}`;
      const res = await fetchJson<any>(`/api/v1/bundles${query}`, { method: "GET" }, auth());
      setReviewBundles(res.bundles || []);
    } catch(e) {
      setReviewBundles([]);
    }
  }

  async function handleHumanDecision(bundleId: string, decision: string) {
    await run(`Human Review: ${decision.toUpperCase()}`, async () => {
      const res = await fetchJson<any>(`/api/v1/bundles/${bundleId}/human-decision`, {
        method: "POST",
        body: JSON.stringify({ decision, notes: reviewNotesInput })
      }, auth());
      setSelectedBundleForModal(null);
      setReviewNotesInput("");
      await loadReviewBundles(reviewFilter);
      return res;
    });
  }

  // Question Bank
  async function loadQuestionBank() {
    try {
      const res = await fetchJson<any>("/questions/bank?limit=50", { method: "GET" }, auth());
      setQuestionBank(res.questions || []);
    } catch(e) { /* ignore */ }
  }

  async function triggerQuestionAction(questionId: string, action: string) {
    await run(`Question Action (${action})`, async () => {
      const res = await fetchJson<any>(`/questions/${questionId}/action`, {
        method: "POST",
        body: JSON.stringify({ action, reason: `Triggered from control plane: ${action}` })
      }, auth());
      await loadQuestionBank();
      return res;
    });
  }

  // Target Metrics
  async function loadTodayTarget() {
    try {
      const res = await fetchJson<any>("/targets/today", { method: "GET" }, auth());
      setDailyTargetData(res);
    } catch(e) { /* ignore */ }
  }

  async function configureTargetSubmit(e: FormEvent) {
    e.preventDefault();
    await run("Save Daily Target", async () => {
      const res = await fetchJson<any>("/targets/configure", {
        method: "POST",
        body: JSON.stringify({ target_date: new Date().toISOString().split("T")[0], target_count: targetCountInput })
      }, auth());
      await loadTodayTarget();
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

  // Refresh Dashboard
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
      loadReviewBundles(reviewFilter);
    }
  }, [currentRole]);

  const canAdmin = hasRight(currentRole, "all");

  const navItems: Array<{ id: View; label: string; right: string }> = [
    { id: "dashboard", label: "Dashboard", right: "health" },
    { id: "datasets", label: "Datasets & Blueprints", right: "datasets" },
    { id: "generation", label: "Generation Studio", right: "generate" },
    { id: "review", label: "Review & Human Approval", right: "review" },
    { id: "production", label: "Production Bundles", right: "production_read" },
    { id: "prompts", label: "Prompt Builder", right: "prompts" },
    { id: "questions", label: "Questions & DNA", right: "questions" },
    { id: "targets", label: "Targets & Alerts", right: "targets" },
    { id: "providers", label: "Model Providers", right: "all" },
    { id: "pipelines", label: "Stage Bindings", right: "bindings" },
    { id: "browser", label: "Browser Agent", right: "browse" }
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
              <button key={item.id} className={`nav-item ${view === item.id ? "active" : ""}`} onClick={() => {
                setView(item.id);
                if (item.id === "review") loadReviewBundles(reviewFilter);
                if (item.id === "production") loadReviewBundles("published");
              }}>
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
            <span className="pill ok">Langfuse Connected</span>
            <span className="pill ok">Role: {currentRole}</span>
          </div>
        </header>

        {/* Global Error Banner */}
        {errorBanner && (
          <div className="error-banner">
            <div className="error-banner-content">
              <strong>{errorBanner.code}</strong>
              <p>{errorBanner.message}</p>
            </div>
            {errorBanner.retryable && (
              <span className="pill warn">Retryable Error</span>
            )}
            <button className="ghost" onClick={() => setErrorBanner(null)} style={{marginLeft: 'auto'}}>Dismiss</button>
          </div>
        )}

        {/* 1. DASHBOARD TAB */}
        {view === "dashboard" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Operations Dashboard</h2>
                <p>System KPIs, pipeline health, token consumption, and daily production target tracking.</p>
              </div>
              <button className="ghost" onClick={refreshDashboard} disabled={isRunning}>Refresh</button>
            </div>

            <div className="kpi-grid">
              <div className="kpi">
                <div className="muted">Master Context</div>
                <div className="kpi-value">{masterContext ? "Loaded (BECF)" : "Pending Seed"}</div>
              </div>
              <div className="kpi">
                <div className="muted">Total Tokens Consumed</div>
                <div className="kpi-value">{(costSummary?.total_tokens || 0).toLocaleString()}</div>
              </div>
              <div className="kpi">
                <div className="muted">Total LLM Cost (USD)</div>
                <div className="kpi-value">${(costSummary?.total_cost_usd || 0).toFixed(4)}</div>
              </div>
              <div className="kpi">
                <div className="muted">Generation Runs</div>
                <div className="kpi-value">{costSummary?.total_runs || 0}</div>
              </div>
            </div>

            {/* Cost Breakdown by Provider Table */}
            {costSummary?.cost_by_provider && costSummary.cost_by_provider.length > 0 && (
              <div style={{marginTop: '1.5rem'}}>
                <h3>Cost & Token Consumption by Model</h3>
                <table style={{width: '100%', marginTop: '0.5rem', fontSize: '0.85rem'}}>
                  <thead>
                    <tr style={{textAlign: 'left'}}>
                      <th>Provider</th><th>Model</th><th>Prompt Tokens</th><th>Completion</th><th>Total Tokens</th><th>Total Cost (USD)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {costSummary.cost_by_provider.map((p: any, idx: number) => (
                      <tr key={idx}>
                        <td><strong>{p.provider}</strong></td>
                        <td>{p.model}</td>
                        <td>{(p.prompt_tokens || 0).toLocaleString()}</td>
                        <td>{(p.completion_tokens || 0).toLocaleString()}</td>
                        <td>{(p.total_tokens || 0).toLocaleString()}</td>
                        <td>${(p.total_cost_usd || 0).toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {/* 2. DATASETS & BLUEPRINTS TAB */}
        {view === "datasets" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Datasets & Curriculum Blueprints</h2>
                <p>Ingest raw curriculum datasets (DTE, Grade 1-12) to extract blueprints and tailored agent prompts.</p>
              </div>
            </div>

            {/* Raw Dataset Ingestion & Extraction Engine */}
            <div className="panel" style={{marginTop: '0.5rem', marginBottom: '1rem', border: '1px solid var(--accent, #6366f1)'}}>
              <div className="panel-head">
                <div>
                  <h3>📥 Raw Dataset Ingestion & Automated Blueprinting</h3>
                  <p style={{fontSize: '0.85rem', color: 'var(--muted)'}}>
                    Paste raw unclarified dataset text or PDF extracts (e.g. Diploma in Teacher Education, Grade 1-12 curriculum text).
                    The AI engine automatically extracts subject, strands, sub-strands, SLOs, safety hazards to check, diagram specifications, and dynamic agent prompts.
                  </p>
                </div>
              </div>
              <div style={{padding: '0 1rem 1rem'}}>
                <textarea
                  value={rawCurriculumInput}
                  onChange={(e) => setRawCurriculumInput(e.target.value)}
                  rows={8}
                  style={{width: '100%', fontFamily: 'monospace', fontSize: '0.82rem'}}
                  placeholder="Paste raw curriculum design text or JSON dataset payload here..."
                />
                <div style={{display: 'flex', gap: '0.5rem', marginTop: '0.5rem', flexWrap: 'wrap'}}>
                  <button onClick={onIngestRawCurriculum} disabled={isRunning || !rawCurriculumInput.trim()}>
                    {isRunning ? "Structuring Curriculum..." : "Ingest & Structure Curriculum Design"}
                  </button>
                  <button onClick={syncLangfuseDatasets} disabled={isRunning} style={{background: '#4338ca', borderColor: '#4338ca'}}>
                    {isRunning ? "Fetching from Langfuse..." : "📥 Pull & Structure All Datasets from Langfuse"}
                  </button>
                  <button
                    className="ghost"
                    onClick={() => {
                      setRawCurriculumInput(`DIPLOMA IN TEACHER EDUCATION\nPRE-PRIMARY AND PRIMARY\nAGRICULTURE\nCURRICULUM DESIGN 2024\n\nESSENCE STATEMENT\nKenya is mainly dependent on an agro-based economy that requires competent manpower for sustainable development.\n\nGENERAL LEARNING OUTCOMES\n1. Develop Agricultural knowledge, skills, values and attitudes.\n2. Apply knowledge and pedagogical skills to rear domestic animals.\n\nSTRAND 1.0 AGRICULTURE AND ENVIRONMENT\n1.1 Overview of Agriculture (4 hours)\nBy the end of the sub strand, the teacher trainee should be able to:\na) discuss the importance of Agriculture in Kenya,\nb) relate the key natural resources to Agricultural production in Kenya,\nSuggested Learning Experiences\n• Through discussion and literature review, develop the meaning and importance of Agriculture.\n• Research on key natural resources that influence Agricultural production.\nSuggested Key Inquiry Questions\nHow does curriculum in primary education relate to Agriculture productivity in Kenya?\nCore competencies to be developed:\nCritical thinking and problem solving.\nValues:\nPatriotism as teacher trainees take initiative.\n\n1.4 Soil Composition (4 hours)\nBy the end of the sub strand, the teacher trainee should be able to:\na) investigate components of a garden soil sample,\nb) relate components of soil to its productivity in Agriculture,\nSuggested Learning Experiences\n• Carry out experiments to investigate presence of components (air, water, organic matter) of a garden soil sample.\n• Prepare compost manure using heap and pit methods.\nSuggested Key Inquiry Questions\nWhat makes a quality fertile soil?`);
                    }}
                  >
                    Load Sample Agriculture DTE Design
                  </button>
                </div>

                {ingestedDesignResult && (
                  <div style={{marginTop: '1rem', padding: '0.75rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0'}}>
                    <h4>✓ Successfully Ingested: {ingestedDesignResult.subject} ({ingestedDesignResult.grade})</h4>
                    <p style={{fontSize: '0.85rem', color: '#475569'}}>{ingestedDesignResult.essence_statement}</p>
                    <div style={{marginTop: '0.5rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap'}}>
                      <span className="pill ok">Sub-strands: {ingestedDesignResult.substrand_count}</span>
                      <span className="pill ok">Dataset DNA: {ingestedDesignResult.dataset_dna_id}</span>
                      <span className="pill ok">Subject DNA: {ingestedDesignResult.subject_dna_id}</span>
                      <span className="pill ok">Langfuse Synced</span>
                    </div>

                    <div style={{marginTop: '0.75rem', maxHeight: '240px', overflowY: 'auto'}}>
                      {ingestedDesignResult.substrands?.map((ss: any, idx: number) => (
                        <div key={idx} style={{fontSize: '0.8rem', padding: '0.5rem', borderBottom: '1px solid #e2e8f0'}}>
                          <strong>{ss.strand} ➔ {ss.sub_strand}</strong> ({ss.hours}) | {ss.slo_count} SLOs
                          {ss.diagrams_required?.length > 0 && (
                            <div style={{color: '#6366f1'}}>📐 Visual Diagram specs: {ss.diagrams_required.join(', ')}</div>
                          )}
                          {ss.experiments?.length > 0 && (
                            <div style={{color: '#059669'}}>🧪 Experiments planned: {ss.experiments.join('; ')}</div>
                          )}
                          {ss.safety_hazards_to_check?.length > 0 && (
                            <div style={{color: '#dc2626'}}>⚠️ Safety Hazards to Audit: {ss.safety_hazards_to_check.slice(0, 2).join('; ')}</div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Global BECF Master Context Editor */}
            <div className="panel" style={{marginBottom: '1rem'}}>
              <div className="panel-head">
                <div>
                  <h3>Global BECF Master Context (Prompt: "BECF")</h3>
                  <p style={{fontSize: '0.85rem', color: 'var(--muted)'}}>This is the foundational prompt governing all 5 agent stages.</p>
                </div>
              </div>
              <div style={{padding: '0 1rem 1rem'}}>
                <textarea
                  value={masterContextDraft}
                  onChange={(e) => setMasterContextDraft(e.target.value)}
                  rows={8}
                  style={{width: '100%', fontFamily: 'monospace', fontSize: '0.85rem'}}
                />
                <div style={{display: 'flex', gap: '0.5rem', marginTop: '0.5rem'}}>
                  <button onClick={saveMasterContext} disabled={isRunning}>Save to Langfuse</button>
                  <button className="ghost" onClick={seedLangfuse} disabled={isRunning}>Seed Langfuse Defaults</button>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* 3. GENERATION STUDIO TAB */}
        {view === "generation" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Multi-Agent Generation Studio</h2>
                <p>Execute complete pipeline: Notes ➔ Vector Diagrams ➔ Real Experiments (Hazard Checked) ➔ Questions ➔ Strict Review ➔ Dual-Agent Deliberation.</p>
              </div>
            </div>

            <div className="surface">
              <div className="three-col">
                <label>
                  Grade / Level
                  <select value={genGrade} onChange={(e) => {
                    const g = e.target.value;
                    setGenGrade(g);
                    loadGradeSubjects(g);
                  }}>
                    <option value="">Select level...</option>
                    {datasetsList.map(d => <option key={d} value={d}>{d}</option>)}
                  </select>
                </label>
                <label>
                  Subject
                  <select value={genSubject} onChange={(e) => {
                    setGenSubject(e.target.value);
                    if (e.target.value) loadSubjectStrands(genGrade, e.target.value);
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
                      loadSubstrandSlos(genGrade, genSubject, genStrand, e.target.value);
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
                {isRunning ? "Running Multi-Agent Pipeline..." : "Run Multi-Agent Production Pipeline"}
              </button>
            </div>

            {generationResult && (
              <div className="surface" style={{ marginTop: "16px" }}>
                <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                  <h3>Resource Bundle: {generationResult.bundle_id}</h3>
                  <span className="pill ok" style={{fontWeight: 600}}>STATUS: {generationResult.status?.toUpperCase()}</span>
                </div>

                <h4>📝 Revision Notes: {generationResult.notes?.title}</h4>
                <p>{generationResult.notes?.intro}</p>

                {generationResult.diagrams?.[0]?.diagram_svg && (
                  <div style={{marginTop: '1rem'}}>
                    <h4>📐 Vector SVG Diagram: {generationResult.diagrams[0].diagram_title}</h4>
                    <div
                      className="svg-preview"
                      dangerouslySetInnerHTML={{ __html: generationResult.diagrams[0].diagram_svg }}
                    />
                    <small className="muted">Alt Text: {generationResult.diagrams[0].accessibility?.alt_text}</small>
                  </div>
                )}

                {/* Real Experiments Section */}
                {generationResult.experiments?.length > 0 && (
                  <div style={{marginTop: '1rem', padding: '0.75rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0'}}>
                    <h4>🧪 Real Learning Experiments & Practical Tasks:</h4>
                    {generationResult.experiments.map((exp: any, idx: number) => (
                      <div key={idx} style={{marginTop: '0.5rem', fontSize: '0.85rem'}}>
                        <strong>{idx + 1}. {exp.title || exp}</strong>
                        {exp.procedure && <p style={{margin: '4px 0'}}>Procedure: {exp.procedure}</p>}
                        {exp.safety_warning && <p style={{color: '#dc2626', margin: '4px 0'}}>⚠️ Hazard Warning: {exp.safety_warning}</p>}
                      </div>
                    ))}
                  </div>
                )}

                {/* Derived Questions */}
                <h4 style={{marginTop: '1rem'}}>❓ Questions & Answers ({generationResult.questions?.length}):</h4>
                {generationResult.questions?.map((q: any, idx: number) => (
                  <div key={idx} className="card-item">
                    <strong>{q.content?.question_type?.toUpperCase()}: {q.content?.question_text}</strong>
                    <div style={{ marginTop: "6px" }}>
                      <span className="pill ok">Meeting Rubric: {q.content?.marking_guide?.meeting}</span>
                    </div>
                  </div>
                ))}

                {/* Multi-Agent Approver Deliberation */}
                {generationResult.multi_agent_deliberation && (
                  <div style={{marginTop: '1.25rem', padding: '0.75rem', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0'}}>
                    <h4>🤖 Multi-Agent Approver Consensus Deliberation:</h4>
                    <div style={{fontSize: '0.82rem', marginTop: '0.4rem'}}>
                      <p><strong>Auditor 1 (Primary):</strong> {generationResult.multi_agent_deliberation.auditor_1_assessment}</p>
                      <p><strong>Auditor 2 (Senior):</strong> {generationResult.multi_agent_deliberation.auditor_2_cross_examination}</p>
                      <p style={{color: '#059669'}}><strong>Consensus:</strong> {generationResult.multi_agent_deliberation.summary_for_human_approver}</p>
                    </div>
                  </div>
                )}

                {/* Universal Artifact DNA Verification */}
                {generationResult.bundle_dna && (
                  <div style={{marginTop: '1.25rem', padding: '0.75rem', background: '#f0fdf4', borderRadius: '8px', border: '1px solid #bbf7d0'}}>
                    <div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
                      <strong style={{color: '#166534', fontSize: '0.9rem'}}>🛡️ Universal Artifact DNA & Chain of Custody (BECF Verified)</strong>
                      <span className="pill ok" style={{background: '#dcfce7', color: '#15803d', fontWeight: 600}}>
                        {generationResult.bundle_dna.status?.toUpperCase()}
                      </span>
                    </div>
                    <div style={{fontSize: '0.8rem', color: '#334155', marginTop: '0.4rem', fontFamily: 'monospace'}}>
                      Bundle Merkle Root: {generationResult.bundle_dna.payload?.bundle_merkle_root?.slice(0, 32)}...
                    </div>

                    <div style={{marginTop: '0.6rem', padding: '0.5rem', background: '#ffffff', borderRadius: '6px', border: '1px solid #dcfce7', fontSize: '0.78rem'}}>
                      <strong>🔗 Merkle Chain of Custody (Anti-Hallucination Verified):</strong>
                      <div style={{marginTop: '4px', display: 'flex', alignItems: 'center', gap: '4px', flexWrap: 'wrap'}}>
                        <span className="pill" style={{background: '#f1f5f9', color: '#475569'}}>📦 Raw Dataset</span>
                        <span>➔</span>
                        <span className="pill" style={{background: '#e0e7ff', color: '#4338ca'}}>📚 Subject DNA</span>
                        <span>➔</span>
                        <span className="pill" style={{background: '#fef3c7', color: '#92400e'}}>🌿 Strand DNA</span>
                        <span>➔</span>
                        <span className="pill" style={{background: '#e0f2fe', color: '#0369a1'}}>🌱 Substrand DNA</span>
                        <span>➔</span>
                        <span className="pill ok">🎯 Generated DNA</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        )}

        {/* 4. REVIEW & HUMAN APPROVAL TAB */}
        {view === "review" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Human Review & Production Approval</h2>
                <p>Inspect AI-generated bundles, safety audit reports, and multi-agent deliberations before signing off for classroom release.</p>
              </div>
              <div style={{display: 'flex', gap: '0.5rem'}}>
                <select value={reviewFilter} onChange={(e) => { setReviewFilter(e.target.value); loadReviewBundles(e.target.value); }}>
                  <option value="human_review_queue">Pending Human Approval</option>
                  <option value="published">Production Published</option>
                  <option value="needs_safety_revision">Needs Safety Revision</option>
                  <option value="all">All Bundles</option>
                </select>
                <button className="ghost" onClick={() => loadReviewBundles(reviewFilter)}>Refresh Queue</button>
              </div>
            </div>

            {reviewBundles.length === 0 ? (
              <p className="muted" style={{padding: '1rem'}}>No bundles found matching filter "{reviewFilter}".</p>
            ) : (
              <div className="stack" style={{gap: '1rem', marginTop: '1rem'}}>
                {reviewBundles.map((b: any) => (
                  <div key={b.bundle_id} className="surface" style={{border: '1px solid #e2e8f0', borderRadius: '8px', padding: '1rem'}}>
                    <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
                      <div>
                        <h3>{b.curriculum?.subject || "Subject"} - {b.curriculum?.sub_strand || "Substrand"}</h3>
                        <small className="muted">{b.bundle_id} | {b.curriculum?.grade} | Tokens: {b.total_tokens || 0} (${b.total_cost_usd || 0})</small>
                      </div>
                      <span className={`pill ${b.status === 'published' ? 'ok' : (b.status === 'human_review_queue' ? 'warn' : 'err')}`}>
                        {b.status?.toUpperCase()}
                      </span>
                    </div>

                    <p style={{fontSize: '0.9rem', marginTop: '0.5rem'}}><strong>Notes:</strong> {b.notes?.title}</p>
                    <p style={{fontSize: '0.85rem', color: '#475569'}}>{b.notes?.intro?.slice(0, 160)}...</p>

                    {/* Action Bar */}
                    <div style={{marginTop: '1rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center'}}>
                      <button onClick={() => setSelectedBundleForModal(b)}>🔍 Inspect Full Bundle & Multi-Agent Deliberation</button>
                      {b.status === "human_review_queue" && (
                        <>
                          <button style={{background: '#15803d', borderColor: '#15803d'}} onClick={() => handleHumanDecision(b.bundle_id, "approve")}>
                            ✅ Approve to Production
                          </button>
                          <button className="ghost" style={{color: '#ea580c'}} onClick={() => handleHumanDecision(b.bundle_id, "revision")}>
                            🔄 Request Revision
                          </button>
                          <button className="ghost" style={{color: '#dc2626'}} onClick={() => handleHumanDecision(b.bundle_id, "reject")}>
                            ❌ Reject
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Inspect Modal */}
            {selectedBundleForModal && (
              <div style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9999
              }}>
                <div style={{background: '#fff', padding: '1.5rem', borderRadius: '12px', width: '90%', maxWidth: '850px', maxHeight: '85vh', overflowY: 'auto'}}>
                  <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #e2e8f0', paddingBottom: '0.5rem'}}>
                    <h3>Inspect Bundle: {selectedBundleForModal.bundle_id}</h3>
                    <button className="ghost" onClick={() => setSelectedBundleForModal(null)}>✕ Close</button>
                  </div>

                  <div style={{marginTop: '1rem'}}>
                    <h4>Curriculum Context</h4>
                    <p>{selectedBundleForModal.curriculum?.subject} - {selectedBundleForModal.curriculum?.strand} ➔ {selectedBundleForModal.curriculum?.sub_strand}</p>

                    <h4 style={{marginTop: '1rem'}}>Notes Content</h4>
                    <p><strong>{selectedBundleForModal.notes?.title}</strong></p>
                    <p style={{fontSize: '0.85rem'}}>{selectedBundleForModal.notes?.intro}</p>

                    {selectedBundleForModal.diagrams?.[0]?.diagram_svg && (
                      <div style={{marginTop: '1rem'}}>
                        <h4>Diagram Preview</h4>
                        <div className="svg-preview" dangerouslySetInnerHTML={{ __html: selectedBundleForModal.diagrams[0].diagram_svg }} />
                      </div>
                    )}

                    <h4 style={{marginTop: '1rem'}}>Reviewer Safety Audit</h4>
                    <pre style={{fontSize: '0.75rem', maxHeight: '150px'}}>{pretty(selectedBundleForModal.review_audit)}</pre>

                    <div style={{marginTop: '1rem'}}>
                      <label>Reviewer Notes / Feedback:
                        <input value={reviewNotesInput} onChange={(e) => setReviewNotesInput(e.target.value)} placeholder="Add human approval feedback or revision directives..." />
                      </label>
                    </div>

                    <div style={{marginTop: '1rem', display: 'flex', gap: '0.5rem'}}>
                      <button style={{background: '#15803d', borderColor: '#15803d'}} onClick={() => handleHumanDecision(selectedBundleForModal.bundle_id, "approve")}>
                        ✅ Approve to Production
                      </button>
                      <button className="ghost" style={{color: '#ea580c'}} onClick={() => handleHumanDecision(selectedBundleForModal.bundle_id, "revision")}>
                        🔄 Request Revision
                      </button>
                      <button className="ghost" style={{color: '#dc2626'}} onClick={() => handleHumanDecision(selectedBundleForModal.bundle_id, "reject")}>
                        ❌ Reject
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </section>
        )}

        {/* 5. PRODUCTION BUNDLES TAB */}
        {view === "production" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Production Published Bundles</h2>
                <p>Curriculum resource bundles approved by Human Reviewers and published to production.</p>
              </div>
            </div>
            {reviewBundles.filter(b => b.status === "published").length === 0 ? (
              <p className="muted">No published bundles yet. Approve bundles from the Review tab to publish them.</p>
            ) : (
              <div className="stack" style={{gap: '1rem'}}>
                {reviewBundles.filter(b => b.status === "published").map((b: any) => (
                  <div key={b.bundle_id} className="surface">
                    <div style={{display: 'flex', justifyContent: 'space-between'}}>
                      <strong>{b.curriculum?.subject} - {b.curriculum?.sub_strand}</strong>
                      <span className="pill ok">PUBLISHED</span>
                    </div>
                    <p style={{fontSize: '0.85rem', marginTop: '4px'}}>Notes: {b.notes?.title}</p>
                    <small className="muted">{b.bundle_id} | Tokens: {b.total_tokens || 0} | Published: {b.updated_at}</small>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* 6. PROMPT BUILDER TAB */}
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

        {/* 7. QUESTIONS & DNA TAB */}
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

        {/* 8. TARGETS TAB */}
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

        {/* 9. PROVIDERS TAB */}
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

        {/* 10. PIPELINES TAB */}
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

        {/* 11. BROWSER AGENT TAB */}
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
