import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, ErrorNotice, Input, LoadingBlock, PageHeader, Select, Stack, useToast } from "../ui/components";
import { useApi } from "../lib/queries";

type Project = {
  project_id: string; idea: string; category: string; provider: string; model: string; stage: string; status: string;
  error: string; title: string; created_at: string;
  urls: { app?: string; book?: string; long?: { url: string; seconds?: number }; shorts?: { episode: number; title: string; url: string }[] };
};

const CATEGORIES = ["productivity", "games", "visualisation", "animations", "android"] as const;
const STAGES = ["plan", "code", "test", "publish", "shots", "videos", "book", "done"];

/** The developer studio: an idea in; a tested app on the CBC API, its videos, its book and a test link out. */
export function DevStudio() {
  const api = useApi();
  const qc = useQueryClient();
  const toast = useToast();
  const list = useQuery({
    queryKey: ["dev-projects"],
    queryFn: () => api<{ projects: Project[]; ideas: Record<string, string[]> }>("/api/v1/dev/projects"),
    refetchInterval: 15_000,
  });
  const [idea, setIdea] = React.useState("");
  const [category, setCategory] = React.useState<string>("productivity");
  const [provider, setProvider] = React.useState("");
  const [model, setModel] = React.useState("");
  const create = useMutation({
    mutationFn: () => api<{ project_id: string }>("/api/v1/dev/projects", { method: "POST",
      body: JSON.stringify({ idea, category, provider, model }) }),
    onSuccess: () => { setIdea(""); qc.invalidateQueries({ queryKey: ["dev-projects"] }); toast("Queued: it plans, codes, tests, films and writes it up.", "ok"); },
    onError: (e) => toast(e instanceof Error ? e.message : "Could not start it.", "danger"),
  });
  const act = useMutation({
    mutationFn: (v: { id: string; what: "retry" | "linkedin" }) => api<any>(`/api/v1/dev/projects/${v.id}/${v.what}`, { method: "POST" }),
    onSuccess: (out, v) => { qc.invalidateQueries({ queryKey: ["dev-projects"] });
      toast(v.what === "linkedin" ? `${out.queued} post(s) queued for LinkedIn — the poster sends them.` : "Running again from where it stopped.", "ok"); },
    onError: (e) => toast(e instanceof Error ? e.message : "Could not.", "danger"),
  });
  const ideas = list.data?.ideas?.[category] || [];

  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader eyebrow="Developers" title="Developer studio"
        description="A project idea in: the plan, the architecture, the code, tested in a browser, published at a test link — then short videos per episode, one long video, a PDF book, and LinkedIn posts. Every app is built on the CBC API." />
      <Card title="New project" description="Leave the idea empty for one of the ideas below. Provider empty uses the default model; 'agent' hands each prompt to your own Claude Code, Codex, Antigravity or Ollama through Agent tasks.">
        <Stack gap="var(--s3)">
          <Input value={idea} onChange={(e) => setIdea(e.target.value)} placeholder="e.g. A timed maths race where CBC questions move your runner" />
          <Stack direction="row" gap="var(--s3)" wrap align="end">
            <label style={lbl}>Kind
              <Select value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </Select>
            </label>
            <label style={lbl}>Provider
              <Select value={provider} onChange={(e) => setProvider(e.target.value)}>
                <option value="">Default</option><option value="anthropic">Claude</option><option value="openai">OpenAI / Codex</option>
                <option value="gemini">Gemini</option><option value="ollama">Ollama</option><option value="agent">My agent (Agent tasks)</option>
              </Select>
            </label>
            <label style={lbl}>Model (optional)<Input value={model} onChange={(e) => setModel(e.target.value)} style={{ width: "14rem" }} /></label>
            <Button variant="primary" loading={create.isPending} onClick={() => create.mutate()}>Build it</Button>
          </Stack>
          {ideas.length > 0 && (
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
              {ideas.map((i) => <Button key={i} size="sm" variant="ghost" onClick={() => setIdea(i)}>{i}</Button>)}
            </div>
          )}
        </Stack>
      </Card>
      {list.error && <ErrorNotice error={list.error} />}
      {!list.data ? <LoadingBlock rows={3} label="Loading projects" /> : (
        <Card title="Projects">
          <div style={{ display: "grid", gap: "var(--s3)" }}>
            {list.data.projects.length === 0 && <span style={{ color: "var(--ink-3)" }}>None yet.</span>}
            {list.data.projects.map((p) => (
              <div key={p.project_id} style={{ border: "1px solid var(--line-2)", borderRadius: "var(--radius)", padding: "var(--s3)", display: "grid", gap: 6 }}>
                <Stack direction="row" gap="var(--s2)" align="center" wrap>
                  <strong style={{ flex: 1, minWidth: 200 }}>{p.title || p.idea}</strong>
                  <Badge tone="neutral">{p.category}</Badge>
                  <Badge tone={p.status === "done" ? "ok" : p.status === "failed" ? "danger" : "info"}>
                    {p.status === "done" ? "done" : `${p.status} · ${p.stage}`}
                  </Badge>
                </Stack>
                {p.title && <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>{p.idea}</span>}
                {p.status !== "done" && p.status !== "failed" && (
                  <div style={{ display: "flex", gap: 3 }}>
                    {STAGES.map((s) => <span key={s} title={s} style={{ flex: 1, height: 5, borderRadius: 3,
                      background: STAGES.indexOf(s) <= STAGES.indexOf(p.stage) ? "var(--accent)" : "var(--line)" }} />)}
                  </div>
                )}
                {p.error && <span style={{ color: "var(--danger)", fontSize: "var(--text-sm)" }}>{p.error}</span>}
                <Stack direction="row" gap="var(--s2)" wrap>
                  {p.urls.app && <a href={p.urls.app} target="_blank" rel="noreferrer"><Button size="sm">Try the app ↗</Button></a>}
                  {p.urls.book && <a href={p.urls.book} target="_blank" rel="noreferrer"><Button size="sm" variant="ghost">Book (PDF)</Button></a>}
                  {p.urls.long?.url && <a href={p.urls.long.url} target="_blank" rel="noreferrer"><Button size="sm" variant="ghost">Long video</Button></a>}
                  {(p.urls.shorts || []).map((s) => (
                    <a key={s.url} href={s.url} target="_blank" rel="noreferrer"><Button size="sm" variant="ghost">Short {s.episode}</Button></a>
                  ))}
                  <span style={{ flex: 1 }} />
                  {p.status === "done" && <Button size="sm" onClick={() => act.mutate({ id: p.project_id, what: "linkedin" })}>Post to LinkedIn</Button>}
                  {p.status !== "done" && <Button size="sm" variant="ghost" onClick={() => act.mutate({ id: p.project_id, what: "retry" })}>Run again</Button>}
                </Stack>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

const lbl: React.CSSProperties = { display: "grid", gap: 4, fontSize: "var(--text-sm)", fontWeight: 550, color: "var(--ink-2)" };
