import React from "react";
import { Badge, Button, ErrorNotice, LoadingBlock, Stack } from "./components";
import {
  useProposePrompt,
  usePrompt,
  useReviewerNotes,
  useSavePrompt,
} from "../lib/queries";

/**
 * A reviewer's complaint about the OUTPUT, turned into a change to the PROMPT.
 *
 * "This explains which key on the calculator is the minus sign" is a defect in
 * the prompt, not in the guide: every future guide does it again. The route
 * from that sentence to the prompt ran through somebody who knew which of
 * twenty-two prompts to open and what to change in it.
 *
 * Nothing here applies on its own. A prompt is the behaviour of every
 * generator downstream of it, and a model rewriting one on a single complaint
 * is how a system loses a rule nobody remembers adding — so the models
 * propose, the difference is shown, and a person saves it.
 *
 * Saving writes to Langfuse, which every generator reads at run time. No
 * deploy, live on the next run.
 */
export function PromptWorkshop({
  agent,
  artifactId,
}: {
  agent: string;
  artifactId?: string;
}) {
  const prompt = usePrompt(agent);
  const notes = useReviewerNotes(artifactId || "");
  const propose = useProposePrompt();
  const save = useSavePrompt();

  const [draft, setDraft] = React.useState("");
  const [extra, setExtra] = React.useState("");
  const [providers, setProviders] = React.useState<string[]>([]);
  const [confirming, setConfirming] = React.useState(false);

  React.useEffect(() => {
    if (prompt.data?.text) setDraft(prompt.data.text);
  }, [prompt.data?.text]);

  if (prompt.isPending) return <LoadingBlock rows={3} label="Reading the prompt" />;
  if (prompt.isError) return <ErrorNotice error={prompt.error} />;
  const data = prompt.data!;

  // What reviewers already said about this content, plus anything typed here.
  const complaints = [
    ...(notes.data?.notes || []),
    ...(extra.trim() ? [extra.trim()] : []),
  ];

  function toggle(name: string) {
    setProviders((was) =>
      was.includes(name) ? was.filter((p) => p !== name) : [...was, name]
    );
  }

  return (
    <Stack gap="var(--s3)" style={{ marginTop: "var(--s3)" }}>
      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: "var(--text-sm)" }}>The prompt behind this</strong>
        <Badge tone="neutral">{agent}</Badge>
        {data.errors.length > 0 ? (
          <Badge tone="warn">{data.errors.length} problem(s)</Badge>
        ) : (
          <Badge tone="ok">binds cleanly</Badge>
        )}
        <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          Saving writes to Langfuse — live on the next run, no deploy.
        </span>
      </Stack>

      {data.errors.map((e, i) => (
        <div key={i} style={{ fontSize: "var(--text-sm)", color: "var(--danger, #a1281e)" }}>{e}</div>
      ))}

      {complaints.length > 0 && (
        <div>
          <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)" }}>
            What reviewers said about what it produced
          </div>
          <ul style={{ margin: "2px 0 0", paddingLeft: "1.1rem", fontSize: "var(--text-sm)" }}>
            {complaints.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}

      <textarea
        value={extra}
        onChange={(e) => setExtra(e.target.value)}
        placeholder="Anything else wrong with what this prompt produces — in the words you would use to a colleague."
        style={{
          width: "100%", minHeight: 64, padding: "var(--s2)",
          borderRadius: "var(--radius-sm)", border: "1px solid var(--line)",
          background: "var(--surface-2)", color: "var(--ink-1)",
          fontSize: "var(--text-sm)",
        }}
      />

      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        {/* Two vendors disagree usefully: asked to fix the same complaint one
            adds a rule and the other rewrites a section, and the difference
            says whether the complaint was a missing instruction or a badly
            worded one. */}
        {["openai", "gemini", "anthropic"].map((p) => (
          <label key={p} style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            <input
              type="checkbox"
              checked={providers.includes(p)}
              onChange={() => toggle(p)}
              style={{ marginRight: 4 }}
            />
            {p}
          </label>
        ))}
        <Button
          size="sm"
          disabled={!complaints.length || propose.isPending}
          loading={propose.isPending}
          title={complaints.length ? "" : "Say what is wrong with it first."}
          onClick={() => propose.mutate({ agent, notes: complaints, providers })}
        >
          Ask how to fix it
        </Button>
        <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          Nothing is changed until you save.
        </span>
      </Stack>

      {propose.error && <ErrorNotice error={propose.error} />}
      {propose.data?.proposals.map((p, i) => (
        <div key={i} style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "var(--s3)" }}>
          <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ fontSize: "var(--text-sm)" }}>{p.model}</strong>
            {p.error ? (
              <Badge tone="warn">no proposal</Badge>
            ) : (
              <Badge tone={p.valid ? "ok" : "warn"}>
                {p.valid ? "safe to serve" : "would not bind"}
              </Badge>
            )}
            {!p.error && (
              <Button size="sm" variant="ghost" onClick={() => setDraft(p.revised)}>
                Use this one
              </Button>
            )}
          </Stack>
          {p.error && <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>{p.error}</div>}
          {p.problems.map((problem, n) => (
            <div key={n} style={{ fontSize: "var(--text-sm)", color: "var(--danger, #a1281e)", marginTop: 3 }}>
              {problem}
            </div>
          ))}
          {p.changes.map((c, n) => (
            <div key={n} style={{ fontSize: "var(--text-sm)", marginTop: 3 }}>
              <b>{c.what}</b> — {c.why}
            </div>
          ))}
          {p.already_covered.length > 0 && (
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", marginTop: 3 }}>
              Already covered: {p.already_covered.join("; ")}
            </div>
          )}
          {p.diff && (
            <pre style={{
              marginTop: "var(--s2)", maxHeight: 260, overflow: "auto",
              fontSize: "0.72rem", background: "var(--surface-2)",
              padding: "var(--s2)", borderRadius: "var(--radius-sm)",
              whiteSpace: "pre-wrap",
            }}>{p.diff}</pre>
          )}
        </div>
      ))}

      <textarea
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        spellCheck={false}
        style={{
          width: "100%", minHeight: 300, padding: "var(--s2)",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          fontSize: 12, lineHeight: 1.45,
          borderRadius: "var(--radius-sm)", border: "1px solid var(--line)",
          background: "var(--surface-2)", color: "var(--ink-1)",
        }}
      />

      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <Button
          size="sm"
          variant="ghost"
          disabled={save.isPending || draft === data.text}
          onClick={() => {
            setConfirming(false);
            save.mutate({ agent, text: draft });
          }}
        >
          Show what would change
        </Button>
        {confirming ? (
          <Button
            size="sm"
            variant="danger"
            loading={save.isPending}
            onClick={() =>
              save.mutateAsync({ agent, text: draft, confirm: "APPLY" })
                .then(() => setConfirming(false))
            }
          >
            Save it — live on the next run
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={save.isPending || draft === data.text}
            onClick={() => setConfirming(true)}
          >
            Save
          </Button>
        )}
        {draft !== data.text && (
          <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            Edited — not saved.
          </span>
        )}
      </Stack>

      {save.error && <ErrorNotice error={save.error} />}
      {save.data && (
        <div
          style={{
            padding: "var(--s2)", fontSize: "var(--text-sm)",
            borderRadius: "var(--radius-sm)",
            background: save.data.valid ? "var(--surface-2)" : "var(--warn-bg, #fff8e6)",
          }}
        >
          {save.data.says}
          {save.data.diff && (
            <pre style={{
              marginTop: "var(--s2)", maxHeight: 240, overflow: "auto",
              fontSize: "0.72rem", whiteSpace: "pre-wrap",
            }}>{save.data.diff}</pre>
          )}
        </div>
      )}
    </Stack>
  );
}
