import { FormEvent, useMemo, useState } from "react";
import { API_BASE_URL, fetchJson } from "./api";

const defaultGeneratePayload = {
  request_id: "req_01",
  trace_id: "trc_01",
  tenant_id: "cbc_default",
  actor: { type: "admin", id: "usr_admin_01" },
  curriculum: {
    level: "Middle School",
    grade: "7",
    subject: "Integrated Science",
    subject_code: "ISCI",
    pathway: null,
    track: null,
    strand: "Matter",
    sub_strand: "Classification of Matter",
    slo_id: "MS-G7-ISCI-MAT-CLM-01"
  },
  controls: {
    idempotency_key: "idem_01",
    deadline_ms: 120000,
    max_regen_attempts: 2,
    environment: "prod"
  }
};

type Role = "admin" | "operator" | "reviewer" | "developer";
type Provider = "openai" | "anthropic" | "gemini" | "ollama";
type Stage =
  | "notes_generation"
  | "diagram_generation"
  | "activity_generation"
  | "question_generation"
  | "reviewer_panel"
  | "regeneration";

const stageOptions: Stage[] = [
  "notes_generation",
  "diagram_generation",
  "activity_generation",
  "question_generation",
  "reviewer_panel",
  "regeneration"
];

const roleRights: Record<Role, string[]> = {
  admin: ["all"],
  operator: ["bindings", "generate", "jobs", "health", "browse", "production_read"],
  reviewer: ["health", "admin_config", "jobs", "review", "human_review", "production_read"],
  developer: ["health", "admin_config", "jobs", "browse", "production_read"]
};

type View = "dashboard" | "providers" | "pipelines" | "generation" | "review" | "browser" | "production";

type ProviderDraft = {
  api_key: string;
  base_url: string;
  ollama_models: string;
};

type StageDraft = {
  provider: Provider;
  model: string;
  base_url: string;
};

type CurriculumContext = {
  profile_name: string;
  level: string;
  grade: string;
  subject: string;
  subject_code: string;
  pathway: string;
  track: string;
  strand: string;
  sub_strand: string;
  slo_id: string;
  strand_context: string;
  sub_strand_context: string;
  learning_objectives: string;
  assessment_focus: string;
};

const providerLabel: Record<Provider, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Gemini",
  ollama: "Ollama"
};

const defaultProviderDrafts: Record<Provider, ProviderDraft> = {
  openai: { api_key: "", base_url: "https://api.openai.com/v1", ollama_models: "" },
  anthropic: { api_key: "", base_url: "https://api.anthropic.com/v1", ollama_models: "" },
  gemini: { api_key: "", base_url: "https://generativelanguage.googleapis.com", ollama_models: "" },
  ollama: { api_key: "", base_url: "http://host.docker.internal:11434", ollama_models: "llama3.1,qwen2.5:7b,mistral" }
};

const defaultStageDrafts: Record<Stage, StageDraft> = {
  notes_generation: { provider: "gemini", model: "gemini-2.5-flash", base_url: "" },
  diagram_generation: { provider: "gemini", model: "gemini-2.5-flash", base_url: "" },
  activity_generation: { provider: "gemini", model: "gemini-2.5-flash", base_url: "" },
  question_generation: { provider: "gemini", model: "gemini-2.5-flash", base_url: "" },
  reviewer_panel: { provider: "gemini", model: "gemini-2.5-flash", base_url: "" },
  regeneration: { provider: "gemini", model: "gemini-2.5-flash", base_url: "" }
};

const defaultCurriculumContext: CurriculumContext = {
  profile_name: "Grade 7 Integrated Science: Matter",
  level: "Middle School",
  grade: "7",
  subject: "Integrated Science",
  subject_code: "ISCI",
  pathway: "",
  track: "",
  strand: "Matter",
  sub_strand: "Classification of Matter",
  slo_id: "MS-G7-ISCI-MAT-CLM-01",
  strand_context:
    "Learners distinguish solids, liquids, and gases through observable properties, particle arrangement, and daily-life applications.",
  sub_strand_context:
    "Focus on compressibility, particle spacing, and examples from home and school contexts.",
  learning_objectives:
    "Classify matter by state, explain particle model differences, and apply to real examples.",
  assessment_focus:
    "Use mixed assessment with both selected-response and written-response items tied to criteria-based rubrics."
};

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function hasRight(role: Role | null, right: string): boolean {
  if (!role) {
    return false;
  }
  const rights = roleRights[role] || [];
  return rights.includes("all") || rights.includes(right);
}

export function App() {
  const [output, setOutput] = useState("Ready");
  const [view, setView] = useState<View>("dashboard");
  const [isRunning, setIsRunning] = useState(false);

  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [bearerToken, setBearerToken] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [currentRole, setCurrentRole] = useState<Role | null>(null);
  const [currentSubject, setCurrentSubject] = useState("");

  const [providerDrafts, setProviderDrafts] = useState<Record<Provider, ProviderDraft>>(defaultProviderDrafts);
  const [providerStatus, setProviderStatus] = useState<Record<Provider, boolean>>({
    openai: false,
    anthropic: false,
    gemini: false,
    ollama: false
  });

  const [stageDrafts, setStageDrafts] = useState<Record<Stage, StageDraft>>(defaultStageDrafts);

  const [bootstrapProvider, setBootstrapProvider] = useState<Provider>("gemini");
  const [bootstrapModel, setBootstrapModel] = useState("gemini-2.5-flash");
  const [bootstrapBaseUrl, setBootstrapBaseUrl] = useState("");

  const [syncPayload, setSyncPayload] = useState(pretty(defaultGeneratePayload));
  const [asyncPayload, setAsyncPayload] = useState(pretty(defaultGeneratePayload));
  const [jobId, setJobId] = useState("");
  const [browseUrl, setBrowseUrl] = useState("https://example.com");

  const [reviewRunId, setReviewRunId] = useState("");
  const [reviewDecision, setReviewDecision] = useState("approve_to_human_review");
  const [humanReviewRunId, setHumanReviewRunId] = useState("");
  const [humanReviewDecisionValue, setHumanReviewDecisionValue] = useState("approve");

  const [dashboardStats, setDashboardStats] = useState({ queued: 0, inReview: 0, failed: 0, ready: 0 });
  const [recentRuns, setRecentRuns] = useState<Array<Record<string, unknown>>>([]);
  const [reviewItems, setReviewItems] = useState<Array<Record<string, unknown>>>([]);
  const [humanReviewItems, setHumanReviewItems] = useState<Array<Record<string, unknown>>>([]);
  const [productionItems, setProductionItems] = useState<Array<Record<string, unknown>>>([]);
  const [selectedReviewRaw, setSelectedReviewRaw] = useState("");
  const [generationMode, setGenerationMode] = useState<"sync" | "async">("sync");
  const [curriculumContext, setCurriculumContext] = useState<CurriculumContext>(defaultCurriculumContext);
  const [datasetLibrary, setDatasetLibrary] = useState<CurriculumContext[]>([defaultCurriculumContext]);

  const title = useMemo(() => `CBC API Control Plane`, []);

  async function run<T>(label: string, fn: () => Promise<T>) {
    try {
      setIsRunning(true);
      setOutput(`${label}...`);
      const result = await fn();
      setOutput(pretty(result));
      return result;
    } catch (error) {
      setOutput(error instanceof Error ? error.message : String(error));
      return undefined;
    } finally {
      setIsRunning(false);
    }
  }

  function auth() {
    return {
      bearerToken: bearerToken || undefined,
      apiKey: apiKey || undefined
    };
  }

  async function onLoginSubmit(event: FormEvent) {
    event.preventDefault();
    await run("Login", async () => {
      const result = await fetchJson<{ access_token: string; role: Role; subject: string }>(
        "/auth/login",
        {
          method: "POST",
          body: JSON.stringify({ username, password })
        }
      );
      setBearerToken(result.access_token);
      setCurrentRole(result.role);
      setCurrentSubject(result.subject);
      setView("dashboard");
      return result;
    });
  }

  async function onUseApiKey(event: FormEvent) {
    event.preventDefault();
    await run("Use API key", async () => {
      const result = await fetchJson<{ subject: string; role: Role; auth_type: string }>("/auth/me", { method: "GET" }, { apiKey });
      setCurrentRole(result.role);
      setCurrentSubject(result.subject);
      setBearerToken("");
      setView("dashboard");
      return result;
    });
  }

  function logout() {
    setBearerToken("");
    setApiKey("");
    setCurrentRole(null);
    setCurrentSubject("");
    setOutput("Logged out");
  }

  async function loadAdminConfig() {
    const result = await run("Admin config", () => fetchJson<any>("/admin/config", { method: "GET" }, auth()));
    if (!result) {
      return;
    }

    const nextDrafts: Record<Provider, ProviderDraft> = { ...providerDrafts };
    const nextStatus: Record<Provider, boolean> = { ...providerStatus };
    const nextStages: Record<Stage, StageDraft> = { ...stageDrafts };

    if (Array.isArray(result.providers)) {
      for (const item of result.providers) {
        const p = item.provider as Provider;
        if (!nextDrafts[p]) {
          continue;
        }
        nextDrafts[p] = {
          api_key: "",
          base_url: String(item.base_url || nextDrafts[p].base_url || ""),
          ollama_models: Array.isArray(item.ollama_models) ? item.ollama_models.join(",") : nextDrafts[p].ollama_models
        };
        nextStatus[p] = Boolean(item.has_api_key);
      }
    }

    if (Array.isArray(result.stage_bindings)) {
      for (const row of result.stage_bindings) {
        const stageName = row.pipeline_stage as Stage;
        if (!nextStages[stageName]) {
          continue;
        }
        nextStages[stageName] = {
          provider: row.provider as Provider,
          model: String(row.model || ""),
          base_url: String(row.base_url || "")
        };
      }
    }

    setProviderDrafts(nextDrafts);
    setProviderStatus(nextStatus);
    setStageDrafts(nextStages);
  }

  function asList(value: unknown): Array<Record<string, unknown>> {
    if (Array.isArray(value)) {
      return value as Array<Record<string, unknown>>;
    }
    if (!value || typeof value !== "object") {
      return [];
    }
    const record = value as Record<string, unknown>;
    for (const key of ["items", "queue", "runs", "results", "ready", "bundles", "data"]) {
      if (Array.isArray(record[key])) {
        return record[key] as Array<Record<string, unknown>>;
      }
    }
    return [];
  }

  async function refreshDashboard() {
    const [runs, review, production] = await Promise.all([
      run("Pipeline runs", () => fetchJson<any>("/pipeline/runs", { method: "GET" }, auth())),
      run("Review queue", () => fetchJson<any>("/review/queue", { method: "GET" }, auth())),
      run("Production ready", () => fetchJson<any>("/production/ready", { method: "GET" }, auth()))
    ]);

    const reviewList = asList(review);
    const productionList = asList(production);
    const runsList = asList(runs);

    setReviewItems(reviewList);
    setProductionItems(productionList);
    setRecentRuns(runsList.slice(0, 8));
    setDashboardStats({
      queued: runsList.filter((item) => String(item.workflow_state || "").includes("queue")).length,
      inReview: reviewList.length,
      failed: runsList.filter((item) => String(item.workflow_state || "").toLowerCase() === "rejected").length,
      ready: productionList.length
    });
  }

  async function saveProvider(provider: Provider) {
    const draft = providerDrafts[provider];
    const payload: Record<string, unknown> = {
      api_key: draft.api_key || null,
      base_url: draft.base_url || null,
      ollama_models:
        provider === "ollama"
          ? draft.ollama_models
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean)
          : []
    };
    await run(`Configure provider: ${provider}`, () =>
      fetchJson(`/admin/providers/${provider}/config`, { method: "PUT", body: JSON.stringify(payload) }, auth())
    );
    setProviderStatus((prev) => ({ ...prev, [provider]: Boolean(draft.api_key) || prev[provider] }));
  }

  async function onProviderConfigSubmit(event: FormEvent) {
    event.preventDefault();
    await saveProvider("openai");
    await saveProvider("anthropic");
    await saveProvider("gemini");
    await saveProvider("ollama");
  }

  async function saveStageBinding(stageName: Stage) {
    const row = stageDrafts[stageName];
    await run(`Set stage binding: ${stageName}`, () =>
      fetchJson(
        `/admin/pipeline-bindings/${stageName}`,
        {
          method: "POST",
          body: JSON.stringify({
            provider: row.provider,
            model: row.model,
            base_url: row.base_url || null
          })
        },
        auth()
      )
    );
  }

  async function runBootstrap() {
    await run("Bootstrap stage bindings", () =>
      fetchJson(
        "/admin/pipeline-bindings/bootstrap",
        {
          method: "POST",
          body: JSON.stringify({
            provider: bootstrapProvider,
            model: bootstrapModel,
            base_url: bootstrapBaseUrl || null
          })
        },
        auth()
      )
    );
  }

  async function onBootstrapSubmit(event: FormEvent) {
    event.preventDefault();
    await runBootstrap();
  }

  function buildPayloadFromContext(basePayload: string): string {
    const parsed = JSON.parse(basePayload) as Record<string, unknown>;
    const next = {
      ...parsed,
      curriculum: {
        level: curriculumContext.level,
        grade: curriculumContext.grade,
        subject: curriculumContext.subject,
        subject_code: curriculumContext.subject_code,
        pathway: curriculumContext.pathway || null,
        track: curriculumContext.track || null,
        strand: curriculumContext.strand,
        sub_strand: curriculumContext.sub_strand,
        slo_id: curriculumContext.slo_id
      }
    };
    return pretty(next);
  }

  function applyContextToPayload(target: "sync" | "async" | "both") {
    try {
      if (target === "sync" || target === "both") {
        setSyncPayload(buildPayloadFromContext(syncPayload));
      }
      if (target === "async" || target === "both") {
        setAsyncPayload(buildPayloadFromContext(asyncPayload));
      }
      setOutput("Curriculum context applied to payload");
    } catch {
      setOutput("Payload JSON is invalid. Fix JSON first, then apply curriculum context.");
    }
  }

  function saveCurriculumProfile() {
    setDatasetLibrary((prev) => {
      const idx = prev.findIndex((item) => item.profile_name === curriculumContext.profile_name);
      if (idx === -1) {
        return [...prev, curriculumContext];
      }
      const next = [...prev];
      next[idx] = curriculumContext;
      return next;
    });
    setOutput(`Saved dataset profile: ${curriculumContext.profile_name}`);
  }

  async function onSyncGenerate(event: FormEvent) {
    event.preventDefault();
    await run("Run sync generation", async () => {
      const result = await fetchJson(
        "/pipeline/generate",
        {
          method: "POST",
          body: syncPayload
        },
        auth()
      );
      const runId = (result as any)?.result?.run_id;
      if (runId) {
        setReviewRunId(String(runId));
        setHumanReviewRunId(String(runId));
      }
      setSelectedReviewRaw(pretty(result));
      return result;
    });
  }

  async function fetchJobStatus() {
    if (!jobId) {
      setOutput("Set a job_id first");
      return;
    }
    await run("Get job", async () => {
      const result = await fetchJson(`/pipeline/jobs/${jobId}`, { method: "GET" }, auth());
      setSelectedReviewRaw(pretty(result));
      return result;
    });
  }

  async function onAsyncGenerate(event: FormEvent) {
    event.preventDefault();
    await run("Enqueue generation", async () => {
      const result = await fetchJson<{ job_id: string }>(
        "/pipeline/enqueue",
        {
          method: "POST",
          body: asyncPayload
        },
        auth()
      );
      setJobId(result.job_id);
      setSelectedReviewRaw(pretty(result));
      return result;
    });
  }

  async function loadReviewQueue() {
    await run("Review queue", async () => {
      const result = await fetchJson<any>("/review/queue", { method: "GET" }, auth());
      const items = asList(result);
      setReviewItems(items);
      if (items[0]) {
        setSelectedReviewRaw(pretty(items[0]));
      }
      return result;
    });
  }

  async function loadHumanReviewQueue() {
    await run("Human review queue", async () => {
      const result = await fetchJson<any>("/human-review/queue", { method: "GET" }, auth());
      const items = asList(result);
      setHumanReviewItems(items);
      if (items[0]) {
        setSelectedReviewRaw(pretty(items[0]));
      }
      return result;
    });
  }

  async function loadProductionReady() {
    await run("Production ready", async () => {
      const result = await fetchJson<any>("/production/ready", { method: "GET" }, auth());
      const items = asList(result);
      setProductionItems(items);
      if (items[0]) {
        setSelectedReviewRaw(pretty(items[0]));
      }
      return result;
    });
  }

  async function applyReviewDecision(runId: string, decision: string, path: "review" | "human-review") {
    if (!runId) {
      setOutput("Choose or provide a run_id first");
      return;
    }
    await run("Submit decision", () =>
      fetchJson(
        `/${path}/${runId}/decision`,
        {
          method: "POST",
          body: JSON.stringify({ decision })
        },
        auth()
      )
    );
    await refreshDashboard();
    if (path === "review") {
      await loadReviewQueue();
    } else {
      await loadHumanReviewQueue();
    }
  }

  const canAdmin = hasRight(currentRole, "all");
  const navItems: Array<{ id: View; label: string; right: string }> = [
    { id: "dashboard", label: "Dashboard", right: "health" },
    { id: "providers", label: "Providers", right: "all" },
    { id: "pipelines", label: "Pipelines", right: "bindings" },
    { id: "generation", label: "Generation", right: "generate" },
    { id: "review", label: "Review", right: "review" },
    { id: "browser", label: "Browser Agent", right: "browse" },
    { id: "production", label: "Production", right: "production_read" }
  ];

  if (!currentRole) {
    return (
      <div className="login-shell">
        <section className="login-art">
          <h1>{title}</h1>
          <p>Technical control room for provider routing, pipeline orchestration, and approval workflows.</p>
          <div className="art-grid">
            <div className="node" />
            <div className="node" />
            <div className="node" />
            <div className="node" />
          </div>
        </section>

        <section className="login-card">
          <h2>Welcome back</h2>
          <form onSubmit={onLoginSubmit} className="stack">
            <label>
              Role
              <select value={username} onChange={(event) => setUsername(event.target.value)}>
                <option value="admin">admin</option>
                <option value="operator">operator</option>
                <option value="reviewer">reviewer</option>
                <option value="developer">developer</option>
              </select>
            </label>
            <label>
              Username
              <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="admin" />
            </label>
            <label>
              Password
              <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="password" />
            </label>
            <button type="submit" disabled={isRunning}>
              Sign In
            </button>
          </form>

          <form onSubmit={onUseApiKey} className="stack api-key-login">
            <label>
              Developer API key
              <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="DEVELOPER_API_KEY" />
            </label>
            <button type="submit" className="ghost" disabled={isRunning}>
              Use API Key
            </button>
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
            <small>Control Plane</small>
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
          <button className="ghost" onClick={logout}>
            Sign out
          </button>
          <small>{currentSubject || "session"}</small>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <h1>{title}</h1>
          <div className="topbar-actions">
            <button className="ghost" onClick={() => run("Health", () => fetchJson("/health"))}>
              Health
            </button>
            <button className="ghost" onClick={() => run("Auth me", () => fetchJson("/auth/me", { method: "GET" }, auth()))}>
              Session
            </button>
          </div>
        </header>

        {view === "dashboard" && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>System Overview</h2>
                <p>Real-time telemetry and generation status.</p>
              </div>
              <button onClick={refreshDashboard}>Refresh</button>
            </div>

            <div className="kpi-grid">
              <article className="kpi">
                <h3>Queued Jobs</h3>
                <p>{dashboardStats.queued}</p>
              </article>
              <article className="kpi">
                <h3>In Review</h3>
                <p>{dashboardStats.inReview}</p>
              </article>
              <article className="kpi">
                <h3>Failed</h3>
                <p>{dashboardStats.failed}</p>
              </article>
              <article className="kpi">
                <h3>Ready</h3>
                <p>{dashboardStats.ready}</p>
              </article>
            </div>

            <div className="split">
              <div className="surface">
                <h3>Recent Generation Runs</h3>
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Stage</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentRuns.length === 0 && (
                      <tr>
                        <td colSpan={3}>No runs loaded yet.</td>
                      </tr>
                    )}
                    {recentRuns.map((item, idx) => (
                      <tr key={`${item.run_id || "run"}-${idx}`}>
                        <td>{String(item.run_id || item.job_id || "run")}</td>
                        <td>{String(item.request_id || item.trace_id || "-")}</td>
                        <td>{String(item.workflow_state || item.status || "queued")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="surface">
                <h3>Quick Actions</h3>
                <div className="stack">
                  <button onClick={() => setView("generation")}>Start Sync Run</button>
                  {canAdmin && <button onClick={() => setView("providers")}>Configure Providers</button>}
                  {hasRight(currentRole, "production_read") && <button onClick={() => setView("production")}>Export Production Data</button>}
                </div>
              </div>
            </div>
          </section>
        )}

        {view === "providers" && canAdmin && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Providers Configuration</h2>
                <p>Configure API keys and endpoints for all providers.</p>
              </div>
              <button className="ghost" onClick={loadAdminConfig}>
                Load Existing
              </button>
            </div>

            <form onSubmit={onProviderConfigSubmit} className="provider-grid">
              {(["openai", "anthropic", "gemini"] as Provider[]).map((p) => (
                <article className="provider-card" key={p}>
                  <div className="provider-head">
                    <h3>{providerLabel[p]}</h3>
                    <span className={`pill ${providerStatus[p] ? "ok" : "idle"}`}>{providerStatus[p] ? "Active" : "No key"}</span>
                  </div>
                  <label>
                    API Key
                    <input
                      type="password"
                      value={providerDrafts[p].api_key}
                      onChange={(event) =>
                        setProviderDrafts((prev) => ({ ...prev, [p]: { ...prev[p], api_key: event.target.value } }))
                      }
                    />
                  </label>
                  <label>
                    Base URL
                    <input
                      value={providerDrafts[p].base_url}
                      onChange={(event) =>
                        setProviderDrafts((prev) => ({ ...prev, [p]: { ...prev[p], base_url: event.target.value } }))
                      }
                    />
                  </label>
                  <button type="button" onClick={() => saveProvider(p)}>
                    Save {providerLabel[p]}
                  </button>
                </article>
              ))}

              <article className="provider-card wide">
                <div className="provider-head">
                  <h3>Ollama (Local/Self-hosted)</h3>
                  <span className={`pill ${providerStatus.ollama ? "ok" : "idle"}`}>{providerStatus.ollama ? "Ready" : "Setup"}</span>
                </div>
                <div className="two-col">
                  <label>
                    Base URL
                    <input
                      value={providerDrafts.ollama.base_url}
                      onChange={(event) =>
                        setProviderDrafts((prev) => ({ ...prev, ollama: { ...prev.ollama, base_url: event.target.value } }))
                      }
                    />
                  </label>
                  <label>
                    Available Models List
                    <input
                      value={providerDrafts.ollama.ollama_models}
                      onChange={(event) =>
                        setProviderDrafts((prev) => ({ ...prev, ollama: { ...prev.ollama, ollama_models: event.target.value } }))
                      }
                    />
                  </label>
                </div>
                <button type="button" onClick={() => saveProvider("ollama")}>
                  Save Ollama
                </button>
              </article>

              <button type="submit" className="wide-submit">
                Save All Providers
              </button>
            </form>
          </section>
        )}

        {view === "pipelines" && hasRight(currentRole, "bindings") && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Pipeline Stage Bindings</h2>
                <p>Configure provider and model assignments for each pipeline stage.</p>
              </div>
              <div className="inline">
                <button className="ghost" onClick={loadAdminConfig}>
                  Load Current
                </button>
                <button className="ghost" onClick={runBootstrap}>
                  Bulk Bootstrap
                </button>
              </div>
            </div>

            <div className="surface">
              <table>
                <thead>
                  <tr>
                    <th>Stage</th>
                    <th>Provider</th>
                    <th>Model</th>
                    <th>Base URL</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {stageOptions.map((stageName) => (
                    <tr key={stageName}>
                      <td>{stageName}</td>
                      <td>
                        <select
                          value={stageDrafts[stageName].provider}
                          onChange={(event) =>
                            setStageDrafts((prev) => ({
                              ...prev,
                              [stageName]: { ...prev[stageName], provider: event.target.value as Provider }
                            }))
                          }
                        >
                          <option value="openai">OpenAI</option>
                          <option value="anthropic">Anthropic</option>
                          <option value="gemini">Gemini</option>
                          <option value="ollama">Ollama</option>
                        </select>
                      </td>
                      <td>
                        <input
                          value={stageDrafts[stageName].model}
                          onChange={(event) =>
                            setStageDrafts((prev) => ({
                              ...prev,
                              [stageName]: { ...prev[stageName], model: event.target.value }
                            }))
                          }
                        />
                      </td>
                      <td>
                        <input
                          value={stageDrafts[stageName].base_url}
                          onChange={(event) =>
                            setStageDrafts((prev) => ({
                              ...prev,
                              [stageName]: { ...prev[stageName], base_url: event.target.value }
                            }))
                          }
                          placeholder="optional"
                        />
                      </td>
                      <td>
                        <button type="button" className="ghost" onClick={() => saveStageBinding(stageName)}>
                          Save
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <form onSubmit={onBootstrapSubmit} className="surface stack compact">
              <h3>Bulk Bootstrap</h3>
              <div className="three-col">
                <label>
                  Provider
                  <select value={bootstrapProvider} onChange={(event) => setBootstrapProvider(event.target.value as Provider)}>
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="gemini">Gemini</option>
                    <option value="ollama">Ollama</option>
                  </select>
                </label>
                <label>
                  Model
                  <input value={bootstrapModel} onChange={(event) => setBootstrapModel(event.target.value)} />
                </label>
                <label>
                  Base URL
                  <input value={bootstrapBaseUrl} onChange={(event) => setBootstrapBaseUrl(event.target.value)} placeholder="optional" />
                </label>
              </div>
              <button type="submit">Apply to All Stages</button>
            </form>
          </section>
        )}

        {view === "generation" && hasRight(currentRole, "generate") && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Run Generation</h2>
                <p>Execute manual inference pipelines against configured models.</p>
              </div>
              <div className="inline">
                <button className={generationMode === "sync" ? "" : "ghost"} onClick={() => setGenerationMode("sync")}>
                  Sync Run
                </button>
                <button className={generationMode === "async" ? "" : "ghost"} onClick={() => setGenerationMode("async")}>
                  Async Run
                </button>
              </div>
            </div>

            <div className="surface stack compact">
              <h3>Curriculum Dataset Builder</h3>
              <p className="muted">
                Build complete curriculum context from subject to strand and sub-strand, then inject directly into generation payloads.
              </p>
              <div className="dataset-grid">
                <label>
                  Profile Name
                  <input
                    value={curriculumContext.profile_name}
                    onChange={(event) => setCurriculumContext((prev) => ({ ...prev, profile_name: event.target.value }))}
                  />
                </label>
                <label>
                  Level
                  <input value={curriculumContext.level} onChange={(event) => setCurriculumContext((prev) => ({ ...prev, level: event.target.value }))} />
                </label>
                <label>
                  Grade
                  <input value={curriculumContext.grade} onChange={(event) => setCurriculumContext((prev) => ({ ...prev, grade: event.target.value }))} />
                </label>
                <label>
                  Subject
                  <input
                    value={curriculumContext.subject}
                    onChange={(event) => setCurriculumContext((prev) => ({ ...prev, subject: event.target.value }))}
                  />
                </label>
                <label>
                  Subject Code
                  <input
                    value={curriculumContext.subject_code}
                    onChange={(event) => setCurriculumContext((prev) => ({ ...prev, subject_code: event.target.value }))}
                  />
                </label>
                <label>
                  SLO ID
                  <input value={curriculumContext.slo_id} onChange={(event) => setCurriculumContext((prev) => ({ ...prev, slo_id: event.target.value }))} />
                </label>
                <label>
                  Pathway (optional)
                  <input
                    value={curriculumContext.pathway}
                    onChange={(event) => setCurriculumContext((prev) => ({ ...prev, pathway: event.target.value }))}
                  />
                </label>
                <label>
                  Track (optional)
                  <input value={curriculumContext.track} onChange={(event) => setCurriculumContext((prev) => ({ ...prev, track: event.target.value }))} />
                </label>
                <label>
                  Strand
                  <input value={curriculumContext.strand} onChange={(event) => setCurriculumContext((prev) => ({ ...prev, strand: event.target.value }))} />
                </label>
                <label>
                  Sub-strand
                  <input
                    value={curriculumContext.sub_strand}
                    onChange={(event) => setCurriculumContext((prev) => ({ ...prev, sub_strand: event.target.value }))}
                  />
                </label>
              </div>

              <div className="dataset-context-grid">
                <label>
                  Strand Context
                  <textarea
                    rows={3}
                    value={curriculumContext.strand_context}
                    onChange={(event) => setCurriculumContext((prev) => ({ ...prev, strand_context: event.target.value }))}
                  />
                </label>
                <label>
                  Sub-strand Context
                  <textarea
                    rows={3}
                    value={curriculumContext.sub_strand_context}
                    onChange={(event) => setCurriculumContext((prev) => ({ ...prev, sub_strand_context: event.target.value }))}
                  />
                </label>
                <label>
                  Learning Objectives
                  <textarea
                    rows={3}
                    value={curriculumContext.learning_objectives}
                    onChange={(event) => setCurriculumContext((prev) => ({ ...prev, learning_objectives: event.target.value }))}
                  />
                </label>
                <label>
                  Assessment Focus
                  <textarea
                    rows={3}
                    value={curriculumContext.assessment_focus}
                    onChange={(event) => setCurriculumContext((prev) => ({ ...prev, assessment_focus: event.target.value }))}
                  />
                </label>
              </div>

              <div className="inline wrap">
                <button type="button" className="ghost" onClick={() => applyContextToPayload("sync")}>
                  Apply to Sync Payload
                </button>
                <button type="button" className="ghost" onClick={() => applyContextToPayload("async")}>
                  Apply to Async Payload
                </button>
                <button type="button" className="ghost" onClick={() => applyContextToPayload("both")}>
                  Apply to Both
                </button>
                <button type="button" onClick={saveCurriculumProfile}>
                  Save Dataset Profile
                </button>
              </div>

              <div className="dataset-list">
                {datasetLibrary.map((item, idx) => (
                  <button
                    key={`${item.profile_name}-${idx}`}
                    className="review-item"
                    onClick={() => setCurriculumContext(item)}
                    type="button"
                  >
                    <strong>{item.profile_name}</strong>
                    <small>
                      {item.grade} · {item.subject} · {item.strand} · {item.sub_strand}
                    </small>
                  </button>
                ))}
              </div>
            </div>

            <div className="split">
              <form onSubmit={generationMode === "sync" ? onSyncGenerate : onAsyncGenerate} className="surface stack">
                <label>
                  Payload JSON
                  <textarea
                    rows={18}
                    value={generationMode === "sync" ? syncPayload : asyncPayload}
                    onChange={(event) =>
                      generationMode === "sync" ? setSyncPayload(event.target.value) : setAsyncPayload(event.target.value)
                    }
                  />
                </label>
                <button type="submit">Execute Generation</button>
              </form>

              <div className="surface stack">
                <h3>Output Response</h3>
                <pre>{selectedReviewRaw || output}</pre>
                <div className="inline">
                  <input value={jobId} onChange={(event) => setJobId(event.target.value)} placeholder="job_id for status" />
                  <button onClick={fetchJobStatus} className="ghost">
                    Check Job
                  </button>
                </div>
              </div>
            </div>
          </section>
        )}

        {view === "review" && (hasRight(currentRole, "review") || hasRight(currentRole, "human_review")) && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Human Review Queue</h2>
                <p>Pending manual validation for generation runs.</p>
              </div>
              <div className="inline">
                {hasRight(currentRole, "review") && (
                  <button className="ghost" onClick={loadReviewQueue}>
                    Load Review Queue
                  </button>
                )}
                {hasRight(currentRole, "human_review") && (
                  <button className="ghost" onClick={loadHumanReviewQueue}>
                    Load Human Queue
                  </button>
                )}
              </div>
            </div>

            <div className="split">
              <div className="surface">
                <h3>Queue</h3>
                <div className="review-list">
                  {[...reviewItems, ...humanReviewItems].map((item, idx) => {
                    const runId = String(item.run_id || item.id || `run-${idx}`);
                    return (
                      <button
                        className="review-item"
                        key={`${runId}-${idx}`}
                        onClick={() => {
                          setReviewRunId(runId);
                          setHumanReviewRunId(runId);
                          setSelectedReviewRaw(pretty(item));
                        }}
                      >
                        <strong>{runId}</strong>
                        <small>{String(item.workflow_state || item.status || "review")}</small>
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="surface stack">
                <h3>Run Details</h3>
                <pre>{selectedReviewRaw || "Select a queue item"}</pre>
                {hasRight(currentRole, "review") && (
                  <div className="inline">
                    <select value={reviewDecision} onChange={(event) => setReviewDecision(event.target.value)}>
                      <option value="approve_to_human_review">approve_to_human_review</option>
                      <option value="return_for_regeneration">return_for_regeneration</option>
                      <option value="reject">reject</option>
                    </select>
                    <button onClick={() => applyReviewDecision(reviewRunId, reviewDecision, "review")}>Submit Review</button>
                  </div>
                )}
                {hasRight(currentRole, "human_review") && (
                  <div className="inline">
                    <select value={humanReviewDecisionValue} onChange={(event) => setHumanReviewDecisionValue(event.target.value)}>
                      <option value="approve">approve</option>
                      <option value="reject">reject</option>
                    </select>
                    <button onClick={() => applyReviewDecision(humanReviewRunId, humanReviewDecisionValue, "human-review")}>
                      Submit Human Review
                    </button>
                  </div>
                )}
              </div>
            </div>
          </section>
        )}

        {view === "browser" && hasRight(currentRole, "browse") && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Browser Agent</h2>
                <p>Run extraction against target configuration URLs.</p>
              </div>
            </div>

            <div className="surface stack">
              <div className="inline">
                <input value={browseUrl} onChange={(event) => setBrowseUrl(event.target.value)} placeholder="https://example.com" />
                <button
                  onClick={() =>
                    run("Browse", async () => {
                      const result = await fetchJson(
                        "/agents/browse",
                        {
                          method: "POST",
                          body: JSON.stringify({ url: browseUrl })
                        },
                        auth()
                      );
                      setSelectedReviewRaw(pretty(result));
                      return result;
                    })
                  }
                >
                  Run Agent
                </button>
              </div>
              <pre>{selectedReviewRaw || output}</pre>
            </div>
          </section>
        )}

        {view === "production" && hasRight(currentRole, "production_read") && (
          <section className="panel">
            <div className="panel-head">
              <div>
                <h2>Production Readiness</h2>
                <p>Final verification and deployment for approved bundles.</p>
              </div>
              <button onClick={loadProductionReady}>Refresh</button>
            </div>

            <div className="split">
              <div className="surface">
                <h3>Pre-flight Checklist</h3>
                <ul className="checklist">
                  <li>Data schema validation</li>
                  <li>Asset resolution complete</li>
                  <li>Human review gates passed</li>
                  <li>Policy compliance checks passed</li>
                </ul>
              </div>

              <div className="surface">
                <h3>Ready Bundles</h3>
                <div className="review-list">
                  {productionItems.length === 0 && <p>No production-ready bundles loaded.</p>}
                  {productionItems.map((item, idx) => (
                    <button className="review-item" key={`prod-${idx}`} onClick={() => setSelectedReviewRaw(pretty(item))}>
                      <strong>{String(item.bundle_id || item.run_id || `bundle-${idx + 1}`)}</strong>
                      <small>{String(item.updated_at || item.created_at || "ready")}</small>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </section>
        )}

        <section className="panel console-panel">
          <div className="panel-head">
            <h2>Response Console</h2>
            <small>{isRunning ? "Running request..." : "Idle"}</small>
          </div>
          <pre>{output}</pre>
        </section>
      </main>
    </div>
  );
}
