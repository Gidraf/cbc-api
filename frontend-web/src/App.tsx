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

  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [bearerToken, setBearerToken] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [currentRole, setCurrentRole] = useState<Role | null>(null);
  const [currentSubject, setCurrentSubject] = useState("");

  const [provider, setProvider] = useState<Provider>("gemini");
  const [providerApiKey, setProviderApiKey] = useState("");
  const [providerBaseUrl, setProviderBaseUrl] = useState("");
  const [providerOllamaModels, setProviderOllamaModels] = useState("llama3.1,qwen2.5:7b,mistral");

  const [stage, setStage] = useState<Stage>("notes_generation");
  const [stageProvider, setStageProvider] = useState<Provider>("gemini");
  const [stageModel, setStageModel] = useState("gemini-2.5-flash");
  const [stageBaseUrl, setStageBaseUrl] = useState("");

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

  const title = useMemo(() => `CBC Control Plane (${API_BASE_URL})`, []);

  async function run(label: string, fn: () => Promise<unknown>) {
    try {
      setOutput(`${label}...`);
      const result = await fn();
      setOutput(pretty(result));
    } catch (error) {
      setOutput(error instanceof Error ? error.message : String(error));
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

  async function onProviderConfigSubmit(event: FormEvent) {
    event.preventDefault();
    const payload: Record<string, unknown> = {
      api_key: providerApiKey || null,
      base_url: providerBaseUrl || null,
      ollama_models:
        provider === "ollama"
          ? providerOllamaModels
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean)
          : []
    };

    await run("Configure provider", () =>
      fetchJson(
        `/admin/providers/${provider}/config`,
        {
          method: "PUT",
          body: JSON.stringify(payload)
        },
        auth()
      )
    );
  }

  async function onStageBindingSubmit(event: FormEvent) {
    event.preventDefault();
    await run("Set stage binding", () =>
      fetchJson(
        `/admin/pipeline-bindings/${stage}`,
        {
          method: "POST",
          body: JSON.stringify({
            provider: stageProvider,
            model: stageModel,
            base_url: stageBaseUrl || null
          })
        },
        auth()
      )
    );
  }

  async function onBootstrapSubmit(event: FormEvent) {
    event.preventDefault();
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

  async function onSyncGenerate(event: FormEvent) {
    event.preventDefault();
    await run("Run sync generation", () =>
      fetchJson(
        "/pipeline/generate",
        {
          method: "POST",
          body: syncPayload
        },
        auth()
      )
    );
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
      return result;
    });
  }

  return (
    <div className="page">
      <header className="hero">
        <h1>{title}</h1>
        <p>Authenticated control plane with role-based visibility for admin, operator, reviewer, and developer.</p>
      </header>

      <section className="card">
        <h2>Authentication</h2>
        <form onSubmit={onLoginSubmit} className="form-grid">
          <label>
            Username
            <input value={username} onChange={(event) => setUsername(event.target.value)} placeholder="admin" />
          </label>
          <label>
            Password
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="admin123" />
          </label>
          <button type="submit">POST /auth/login</button>
        </form>
        <form onSubmit={onUseApiKey} className="form-grid" style={{ marginTop: 12 }}>
          <label>
            Developer API Key
            <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="DEVELOPER_API_KEY" />
          </label>
          <button type="submit">GET /auth/me via x-api-key</button>
        </form>
        <div className="inline-actions" style={{ marginTop: 12 }}>
          <button onClick={() => run("Auth me", () => fetchJson("/auth/me", { method: "GET" }, auth()))}>GET /auth/me</button>
          <button onClick={logout}>Logout</button>
        </div>
        <p>
          Session: {currentSubject || "none"} ({currentRole || "unauthenticated"})
        </p>
      </section>

      <section className="grid two">
        {hasRight(currentRole, "health") && <button onClick={() => run("Health", () => fetchJson("/health"))}>GET /health</button>}
        {hasRight(currentRole, "admin_config") && (
          <button onClick={() => run("Admin config", () => fetchJson("/admin/config", { method: "GET" }, auth()))}>GET /admin/config</button>
        )}
      </section>

      {hasRight(currentRole, "all") && (
        <section className="card">
          <h2>Provider Configuration (Admin)</h2>
          <form onSubmit={onProviderConfigSubmit} className="form-grid">
            <label>
              Provider
              <select value={provider} onChange={(event) => setProvider(event.target.value as Provider)}>
                <option value="openai">openai</option>
                <option value="anthropic">anthropic</option>
                <option value="gemini">gemini</option>
                <option value="ollama">ollama</option>
              </select>
            </label>
            <label>
              API Key
              <input value={providerApiKey} onChange={(event) => setProviderApiKey(event.target.value)} placeholder="optional" />
            </label>
            <label>
              Base URL
              <input value={providerBaseUrl} onChange={(event) => setProviderBaseUrl(event.target.value)} placeholder="optional" />
            </label>
            <label>
              Ollama Models (comma separated)
              <input value={providerOllamaModels} onChange={(event) => setProviderOllamaModels(event.target.value)} placeholder="llama3.1,qwen2.5:7b" />
            </label>
            <button type="submit">PUT /admin/providers/{provider}/config</button>
          </form>
        </section>
      )}

      {hasRight(currentRole, "bindings") && (
        <>
          <section className="card">
            <h2>Single Stage Binding</h2>
            <form onSubmit={onStageBindingSubmit} className="form-grid">
              <label>
                Stage
                <select value={stage} onChange={(event) => setStage(event.target.value as Stage)}>
                  {stageOptions.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Provider
                <select value={stageProvider} onChange={(event) => setStageProvider(event.target.value as Provider)}>
                  <option value="openai">openai</option>
                  <option value="anthropic">anthropic</option>
                  <option value="gemini">gemini</option>
                  <option value="ollama">ollama</option>
                </select>
              </label>
              <label>
                Model
                <input value={stageModel} onChange={(event) => setStageModel(event.target.value)} />
              </label>
              <label>
                Base URL Override
                <input value={stageBaseUrl} onChange={(event) => setStageBaseUrl(event.target.value)} placeholder="optional" />
              </label>
              <button type="submit">POST /admin/pipeline-bindings/{stage}</button>
            </form>
          </section>

          <section className="card">
            <h2>Bootstrap All Stage Bindings</h2>
            <form onSubmit={onBootstrapSubmit} className="form-grid">
              <label>
                Provider
                <select value={bootstrapProvider} onChange={(event) => setBootstrapProvider(event.target.value as Provider)}>
                  <option value="openai">openai</option>
                  <option value="anthropic">anthropic</option>
                  <option value="gemini">gemini</option>
                  <option value="ollama">ollama</option>
                </select>
              </label>
              <label>
                Model
                <input value={bootstrapModel} onChange={(event) => setBootstrapModel(event.target.value)} />
              </label>
              <label>
                Base URL Override
                <input value={bootstrapBaseUrl} onChange={(event) => setBootstrapBaseUrl(event.target.value)} placeholder="optional" />
              </label>
              <button type="submit">POST /admin/pipeline-bindings/bootstrap</button>
            </form>
          </section>
        </>
      )}

      {hasRight(currentRole, "generate") && (
        <>
          <section className="card">
            <h2>Sync Generation</h2>
            <form onSubmit={onSyncGenerate} className="form-grid">
              <label>
                Payload JSON
                <textarea rows={14} value={syncPayload} onChange={(event) => setSyncPayload(event.target.value)} />
              </label>
              <button type="submit">POST /pipeline/generate</button>
            </form>
          </section>

          <section className="card">
            <h2>Async Generation</h2>
            <form onSubmit={onAsyncGenerate} className="form-grid">
              <label>
                Payload JSON
                <textarea rows={14} value={asyncPayload} onChange={(event) => setAsyncPayload(event.target.value)} />
              </label>
              <button type="submit">POST /pipeline/enqueue</button>
            </form>
          </section>
        </>
      )}

      {hasRight(currentRole, "jobs") && (
        <section className="card">
          <h2>Pipeline Jobs</h2>
          <div className="inline-actions">
            <input value={jobId} onChange={(event) => setJobId(event.target.value)} placeholder="job_id" />
            <button onClick={() => run("Get job", () => fetchJson(`/pipeline/jobs/${jobId}`, { method: "GET" }, auth()))} disabled={!jobId}>
              GET /pipeline/jobs/{`{job_id}`}
            </button>
          </div>
        </section>
      )}

      {hasRight(currentRole, "review") && (
        <section className="card">
          <h2>Reviewer Queue</h2>
          <div className="inline-actions">
            <button onClick={() => run("Review queue", () => fetchJson("/review/queue", { method: "GET" }, auth()))}>GET /review/queue</button>
          </div>
          <div className="inline-actions" style={{ marginTop: 10 }}>
            <input value={reviewRunId} onChange={(event) => setReviewRunId(event.target.value)} placeholder="run_id" />
            <select value={reviewDecision} onChange={(event) => setReviewDecision(event.target.value)}>
              <option value="approve_to_human_review">approve_to_human_review</option>
              <option value="return_for_regeneration">return_for_regeneration</option>
              <option value="reject">reject</option>
            </select>
            <button
              onClick={() =>
                run("Review decision", () =>
                  fetchJson(
                    `/review/${reviewRunId}/decision`,
                    {
                      method: "POST",
                      body: JSON.stringify({ decision: reviewDecision })
                    },
                    auth()
                  )
                )
              }
              disabled={!reviewRunId}
            >
              POST /review/{`{run_id}`}/decision
            </button>
          </div>
        </section>
      )}

      {hasRight(currentRole, "human_review") && (
        <section className="card">
          <h2>Human Review Queue</h2>
          <div className="inline-actions">
            <button onClick={() => run("Human review queue", () => fetchJson("/human-review/queue", { method: "GET" }, auth()))}>
              GET /human-review/queue
            </button>
          </div>
          <div className="inline-actions" style={{ marginTop: 10 }}>
            <input value={humanReviewRunId} onChange={(event) => setHumanReviewRunId(event.target.value)} placeholder="run_id" />
            <select value={humanReviewDecisionValue} onChange={(event) => setHumanReviewDecisionValue(event.target.value)}>
              <option value="approve">approve</option>
              <option value="reject">reject</option>
            </select>
            <button
              onClick={() =>
                run("Human review decision", () =>
                  fetchJson(
                    `/human-review/${humanReviewRunId}/decision`,
                    {
                      method: "POST",
                      body: JSON.stringify({ decision: humanReviewDecisionValue })
                    },
                    auth()
                  )
                )
              }
              disabled={!humanReviewRunId}
            >
              POST /human-review/{`{run_id}`}/decision
            </button>
          </div>
        </section>
      )}

      {hasRight(currentRole, "production_read") && (
        <section className="card">
          <h2>Production Ready Queue</h2>
          <button onClick={() => run("Production ready", () => fetchJson("/production/ready", { method: "GET" }, auth()))}>
            GET /production/ready
          </button>
        </section>
      )}

      {hasRight(currentRole, "browse") && (
        <section className="card">
          <h2>Browser Agent</h2>
          <div className="inline-actions">
            <input value={browseUrl} onChange={(event) => setBrowseUrl(event.target.value)} placeholder="https://example.com" />
            <button
              onClick={() =>
                run("Browse", () =>
                  fetchJson(
                    "/agents/browse",
                    {
                      method: "POST",
                      body: JSON.stringify({ url: browseUrl })
                    },
                    auth()
                  )
                )
              }
            >
              POST /agents/browse
            </button>
          </div>
        </section>
      )}

      <section className="card">
        <h2>Response</h2>
        <pre>{output}</pre>
      </section>
    </div>
  );
}
