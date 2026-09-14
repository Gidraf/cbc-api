import React from "react";
import {
  Badge,
  Button,
  Card,
  CopyButton,
  ErrorNotice,
  Field,
  Input,
  QueryState,
  Select,
  Stack,
  Table,
  Td,
  Th,
  useToast,
} from "../ui/components";
import { useAuth } from "../lib/auth";
import {
  useCreatePortalKey,
  useAgentPack,
  useKitLink,
  useGrades,
  useSubjects,
  gradeOptionLabel,
  subjectOptionLabel,
  useLogHousekeeping,
  usePortalKeys,
  useProviders,
  useRevokePortalKey,
  useSaveProviderKey,
  type ProviderConfig,
} from "../lib/queries";

/**
 * Where the API keys live.
 *
 * They were environment variables, so changing one — a rotated key, a new
 * provider, a key that had run out of credit — meant editing `.env`, rebuilding
 * the image and restarting the service. The store behind this screen has always
 * been there: keys are encrypted and written to `provider_configs`, and read
 * back on the next call. Only the screen was missing.
 *
 * A saved key is never sent back to the browser. There is nothing to show but
 * whether one is set, so that is all this shows.
 */

const WHAT_FOR: Record<string, string> = {
  anthropic: "Notes, lesson material, questions, and SVG diagrams.",
  openai: "Generation, and the narration audio for maths walkthroughs.",
  gemini: "Generation, and image assets.",
  ollama: "A model running on your own machine. No key — just the address.",
};

const GET_A_KEY: Record<string, string> = {
  anthropic: "console.anthropic.com",
  openai: "platform.openai.com",
  gemini: "aistudio.google.com",
};

function ProviderRow({ config }: { config: ProviderConfig }) {
  const save = useSaveProviderKey();
  const isLocal = config.provider === "ollama";

  const [key, setKey] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState(config.base_url || "");
  const [saved, setSaved] = React.useState(false);

  const dirty = key.trim().length > 0 || baseUrl.trim() !== (config.base_url || "");

  function submit(event: React.FormEvent) {
    event.preventDefault();
    save.mutate(
      {
        provider: config.provider,
        api_key: key.trim() || undefined,
        base_url: baseUrl.trim() || undefined,
      },
      {
        onSuccess: () => {
          setKey("");
          setSaved(true);
          window.setTimeout(() => setSaved(false), 2600);
        },
      }
    );
  }

  return (
    <form
      onSubmit={submit}
      style={{
        border: "1px solid var(--line)",
        borderRadius: "var(--radius-sm)",
        padding: "var(--s3)",
        background: "var(--surface)",
      }}
    >
      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ textTransform: "capitalize" }}>{config.provider}</strong>
        {isLocal ? (
          <Badge tone="neutral">local</Badge>
        ) : config.has_api_key ? (
          <Badge tone="ok">key saved</Badge>
        ) : (
          <Badge tone="warn">no key</Badge>
        )}
        {saved && <Badge tone="ok">saved</Badge>}
      </Stack>

      <p style={{ margin: "var(--s1) 0 var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
        {WHAT_FOR[config.provider] || "Used by the stations bound to it."}
        {!isLocal && GET_A_KEY[config.provider] && (
          <> Keys come from <span className="mono">{GET_A_KEY[config.provider]}</span>.</>
        )}
      </p>

      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
        {!isLocal && (
          <Field
            label={config.has_api_key ? "Replace the key" : "API key"}
            hint={config.has_api_key ? "Leave blank to keep the one already saved." : undefined}
          >
            {(a11y) => (
              <Input
                {...a11y}
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={key}
                placeholder={config.has_api_key ? "•••••••• already saved" : "paste the key"}
                onChange={(e) => setKey(e.target.value)}
                style={{ minWidth: "22rem" }}
              />
            )}
          </Field>
        )}

        <Field label={isLocal ? "Address" : "Base URL"} hint="Blank uses the provider's own.">
          {(a11y) => (
            <Input
              {...a11y}
              value={baseUrl}
              placeholder={isLocal ? "http://localhost:11434" : "default"}
              onChange={(e) => setBaseUrl(e.target.value)}
              style={{ minWidth: "18rem" }}
            />
          )}
        </Field>

        <Button type="submit" disabled={!dirty || save.isPending} loading={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </Stack>

      {save.error && <ErrorNotice error={save.error} />}
    </form>
  );
}

/**
 * Keys for THIS API — what a script, a tool, or a person diagnosing a run
 * uses instead of a login. A key carries a role and does everything that role
 * can do here; an admin key also opens the log link and can clear the logs.
 * Shown once, at creation; revocable from the same table.
 */
const ROLE_LABEL: Record<string, string> = {
  admin: "admin — everything, including logs",
  operator: "operator — generate and review",
  developer: "developer — read and build",
  reviewer: "reviewer — review only",
};
const ROLE_RANK: Record<string, number> = { reviewer: 1, developer: 2, operator: 3, admin: 4 };

const AGENT_KITS: { id: string; title: string; blurb: string; icon: string }[] = [
  { id: "antigravity", title: "Antigravity", icon: "◈", blurb: "Unzip, run install.sh, open the folder in Antigravity, refresh MCP servers, ask for a paper." },
  { id: "claude", title: "Claude Code", icon: "✦", blurb: "Unzip, run install.sh, then `claude` in the folder. It reads CLAUDE.md and the cbc server." },
  { id: "codex", title: "Codex CLI", icon: "▣", blurb: "Unzip, run install.sh (adds the server to ~/.codex/config.toml), then `codex` in the folder." },
  { id: "ollama", title: "Ollama / local model", icon: "◉", blurb: "No agent needed: `sh run.sh order grade-7 Mathematics \"\" \"\" 30 qwen2.5:32b`." },
];

function AgentKits() {
  const { role } = useAuth();
  const grades = useGrades();
  const [grade, setGrade] = React.useState("");
  const subjects = useSubjects(grade);
  const [subject, setSubject] = React.useState("");
  const pack = useAgentPack();
  const link = useKitLink();
  const toast = useToast();
  const [made, setMade] = React.useState<{ agent: string; url: string; curl: string; minutes: number } | null>(null);
  const canMint = role === "admin" || role === "operator";

  async function makeLink(agent: string) {
    try {
      const res = await link.mutateAsync({ agent, grade, subject });
      setMade({ agent, url: res.url, curl: res.curl, minutes: res.expires_in_minutes });
      try { await navigator.clipboard.writeText(res.curl); toast("Command copied — paste it in a terminal.", "ok"); }
      catch { toast("Link made — copy it below.", "ok"); }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not make the link.", "danger");
    }
  }

  return (
    <Card
      title="Get the kit for your agent"
      description="Pick the agent the way you pick an OS. The zip carries the playbook, the MCP server, a fresh operator key already in its config, and a one-line installer — unzip, install, open, ask for a paper. Your agent's model answers the prompts; this platform assembles them, checks the answers, draws the figures and prints the PDF."
    >
      <Stack gap="var(--s3)">
        <Stack direction="row" gap="var(--s2)" wrap>
          <Field label="Design to include (optional)" hint="Adds the strands, sub-strands, outcomes and the term split, so the agent knows the scope.">
            {(a11y) => (
              <Stack direction="row" gap="var(--s2)">
                <Select {...a11y} value={grade} onChange={(e) => { setGrade(e.target.value); setSubject(""); }}>
                  <option value="">Any grade</option>
                  {(grades.data || []).map((g) => <option key={g.slug || g.name} value={g.slug || g.name}>{gradeOptionLabel(g)}</option>)}
                </Select>
                <Select value={subject} disabled={!grade} onChange={(e) => setSubject(e.target.value)}>
                  <option value="">Any subject</option>
                  {(subjects.data || []).map((s) => <option key={s.name} value={s.name}>{subjectOptionLabel(s)}</option>)}
                </Select>
              </Stack>
            )}
          </Field>
        </Stack>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "var(--s3)" }}>
          {AGENT_KITS.map((kit) => (
            <div key={kit.id} style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "var(--s3)" }}>
              <Stack gap="var(--s2)">
                <div style={{ fontSize: "var(--text-lg)" }}>{kit.icon} <b>{kit.title}</b></div>
                <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", minHeight: "3.6em" }}>{kit.blurb}</div>
                <Stack direction="row" gap="var(--s2)" wrap>
                  <Button variant="primary" size="sm" disabled={!canMint || pack.isPending}
                          title={canMint ? "Downloads a zip with a NEW operator key inside — treat it as a secret." : "An admin or operator key is needed to mint the key the kit carries."}
                          onClick={() => pack.mutate({ agent: kit.id, grade, subject })}>
                    {pack.isPending ? "Packing…" : "Download kit"}
                  </Button>
                  <Button variant="secondary" size="sm" disabled={!canMint || link.isPending}
                          title="A one-use link that fetches this kit from a terminal with no key in the command; expires in 30 minutes."
                          onClick={() => makeLink(kit.id)}>
                    Copy link for CLI
                  </Button>
                </Stack>
              </Stack>
            </div>
          ))}
        </div>
        {made && (
          <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "var(--s3)", fontSize: "var(--text-sm)" }}>
            <Stack gap="var(--s2)">
              <div><b>{AGENT_KITS.find((k) => k.id === made.agent)?.title} kit link</b> — one use, expires in {made.minutes} minutes. Paste in a terminal:</div>
              <code style={{ display: "block", whiteSpace: "pre-wrap", wordBreak: "break-all", padding: "var(--s2)", background: "var(--surface-2)", borderRadius: "var(--radius-sm)" }}>{made.curl}</code>
              <Stack direction="row" gap="var(--s2)">
                <Button size="sm" onClick={() => navigator.clipboard.writeText(made.curl).then(() => toast("Copied.", "ok"))}>Copy command</Button>
                <Button size="sm" variant="ghost" onClick={() => navigator.clipboard.writeText(made.url).then(() => toast("Copied.", "ok"))}>Copy URL only</Button>
              </Stack>
            </Stack>
          </div>
        )}
        <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
          Each download or used link mints a key labelled <code>kit-&lt;agent&gt;</code>; revoke it below when the laptop is gone. The context-only pack (no key) is the button on the keys card.
        </div>
      </Stack>
    </Card>
  );
}


function PortalKeys() {
  const { role } = useAuth();
  const keys = usePortalKeys();
  const create = useCreatePortalKey();
  const revoke = useRevokePortalKey();
  const [label, setLabel] = React.useState("");
  const [keyRole, setKeyRole] = React.useState<string>(role || "developer");
  const [fresh, setFresh] = React.useState<{ key_id: string; api_key: string; role: string; label: string } | null>(null);

  const mine = ROLE_RANK[role || ""] || 0;
  const roles = Object.keys(ROLE_LABEL).filter((r) => ROLE_RANK[r] <= mine);
  const origin = window.location.origin.replace(/\/$/, "");
  const logLink = (key: string) => `${origin}/api/v1/admin/logs/share?token=${encodeURIComponent(key)}&since_minutes=60`;
  const pack = useAgentPack();

  function submit(event: React.FormEvent) {
    event.preventDefault();
    create.mutate(
      { label: label.trim(), role: keyRole },
      { onSuccess: (made) => { setFresh(made); setLabel(""); } }
    );
  }

  return (
    <Card
      title="Keys for this API"
      description="For scripts, tools and anyone diagnosing a run without signing in. A key does everything its role can do; an admin key also opens the log link. A key is shown once, when it is made."
      actions={
        <Button size="sm" variant="secondary" disabled={pack.isPending} onClick={() => pack.mutate()}
                title="A zip with AGENTS.md/CLAUDE.md, the manifest, the paper formats, every prompt — unzip it where your agent (Claude Code, Codex, Antigravity) works, add the MCP server with a key from here, and ask it for a paper.">
          {pack.isPending ? "Packing…" : "Download agent pack"}
        </Button>
      }
    >
      <form onSubmit={submit}>
        <Stack direction="row" gap="var(--s2)" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
          <Field label="Label" hint="What it is for — e.g. claude-diagnostics.">
            {(a11y) => (
              <Input {...a11y} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="claude-diagnostics" style={{ minWidth: "16rem" }} />
            )}
          </Field>
          <Field label="Role" hint="Never above your own.">
            {(a11y) => (
              <Select {...a11y} value={keyRole} onChange={(e) => setKeyRole(e.target.value)}>
                {roles.map((r) => (
                  <option key={r} value={r}>{ROLE_LABEL[r]}</option>
                ))}
              </Select>
            )}
          </Field>
          <Button type="submit" disabled={!label.trim() || create.isPending} loading={create.isPending}>
            Create key
          </Button>
        </Stack>
      </form>
      {create.error && <ErrorNotice error={create.error} />}

      {fresh && (
        <div style={{ margin: "var(--s3) 0", padding: "var(--s3)", border: "1px solid var(--warn)", background: "var(--warn-wash)", borderRadius: "var(--radius-sm)" }}>
          <strong>New {fresh.role} key "{fresh.label}" — copy it now. It will not be shown again.</strong>
          <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap", marginTop: "var(--s2)" }}>
            <code className="mono" style={{ wordBreak: "break-all", padding: "var(--s1) var(--s2)", background: "var(--surface)", border: "1px solid var(--line)", borderRadius: "var(--radius-sm)" }}>
              {fresh.api_key}
            </code>
            <CopyButton label="Copy key" getText={() => fresh.api_key} />
            {fresh.role === "admin" && (
              <CopyButton
                label="Copy log link with this key"
                title="Opens the last hour of API and worker logs to whoever holds it"
                getText={() => logLink(fresh.api_key)}
              />
            )}
            <Button size="sm" variant="ghost" onClick={() => setFresh(null)}>Done</Button>
          </Stack>
        </div>
      )}

      <QueryState query={keys} label="Reading the keys" rows={3} />
      {keys.data && (
        <Table caption="Keys">
          <thead>
            <tr>
              <Th>Label</Th>
              <Th>Role</Th>
              <Th>Owner</Th>
              <Th>Last used</Th>
              <Th>Created</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {keys.data.api_keys.length === 0 && (
              <tr><Td colSpan={6}>No keys yet.</Td></tr>
            )}
            {keys.data.api_keys.map((k) => (
              <tr key={k.key_id}>
                <Td>{k.label}</Td>
                <Td><Badge tone={k.role === "admin" ? "accent" : "neutral"}>{k.role}</Badge></Td>
                <Td>{k.user_id}</Td>
                <Td>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</Td>
                <Td>{new Date(k.created_at).toLocaleString()}</Td>
                <Td>
                  <Button
                    size="sm"
                    variant="danger"
                    disabled={revoke.isPending}
                    onClick={() => {
                      if (window.confirm(`Revoke "${k.label}"? Anything using it stops at once.`)) revoke.mutate(k.key_id);
                    }}
                  >
                    Revoke
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {revoke.error && <ErrorNotice error={revoke.error} />}
    </Card>
  );
}

function LogHousekeeping() {
  const { role } = useAuth();
  const { prune, clear } = useLogHousekeeping();
  if (role !== "admin") return null;
  return (
    <Card
      title="Service logs"
      description="API and worker log lines kept in the database for the log link. Pruned every hour by age and by count; these do it now."
    >
      <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap", alignItems: "center" }}>
        <Button size="sm" variant="secondary" loading={prune.isPending} onClick={() => prune.mutate()}>Prune now</Button>
        <Button
          size="sm"
          variant="danger"
          loading={clear.isPending}
          onClick={() => { if (window.confirm("Delete ALL stored log lines?")) clear.mutate(); }}
        >
          Clear all logs
        </Button>
        {prune.data && <Badge tone="ok">{prune.data.removed} pruned</Badge>}
        {clear.data && <Badge tone="ok">{clear.data.removed} deleted</Badge>}
      </Stack>
      {(prune.error || clear.error) && <ErrorNotice error={prune.error || clear.error} />}
    </Card>
  );
}

export function ProviderKeys() {
  const providers = useProviders();
  const { role } = useAuth();

  return (
    <Stack gap="var(--s4)">
      {(role === "admin" || role === "operator" || role === "developer") && <AgentKits />}
      {(role === "admin" || role === "developer") && <PortalKeys />}
      <LogHousekeeping />
      <Card
        title="Provider keys"
        description="Saved encrypted and read on the next call, so a key can be added, replaced or rotated without rebuilding anything. A saved key is never sent back to this page — only whether one is set."
      >
        <QueryState query={providers} label="Reading the provider configuration" rows={4} />
        {providers.data && (
          <Stack gap="var(--s3)">
            {providers.data.providers.map((config) => (
              <ProviderRow key={config.provider} config={config} />
            ))}
          </Stack>
        )}
      </Card>
    </Stack>
  );
}
