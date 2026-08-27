import React from "react";
import { Badge, Button, CopyButton, EmptyState, Modal, Stack } from "../ui/components";

/**
 * What will be sent to the model, before it is sent.
 *
 * An output cannot tell you whether the prompt carried the right document, the
 * right teaching skill, or the right prompt version — a plausible answer looks
 * identical either way. Showing the inputs is what makes prompt improvement
 * deliberate rather than guesswork.
 */

export type Inspection = {
  agent: string;
  grade: string;
  subject: string;
  strand?: string;
  sub_strand?: string;
  model?: string;
  grounded?: boolean;
  prompt: { name: string; version: string; label: string; hash: string };
  source_document: { present: boolean; chars: number; head: string };
  skill:
    | { found: true; subject: string; grade: string; persona: string; directives: string[] }
    | { found: false; note: string };
  messages: { role: string; content: string; chars: number }[];
  total_prompt_chars: number;
  research_citations?: string[];
};

function asText(i: Inspection): string {
  const lines = [
    `AGENT: ${i.agent}`,
    `MODEL: ${i.model || "—"}`,
    `PROMPT: ${i.prompt.name} v${i.prompt.version} (${i.prompt.label}) #${i.prompt.hash}`,
    `CONTEXT: ${i.grade} · ${i.subject}${i.strand ? ` · ${i.strand}` : ""}${i.sub_strand ? ` · ${i.sub_strand}` : ""}`,
    `SOURCE DOCUMENT: ${i.source_document.present ? `${i.source_document.chars} chars` : "NONE — generating from the model's own knowledge"}`,
    `TEACHING SKILL: ${i.skill.found ? `${i.skill.subject} / ${i.skill.grade}` : "none — generic profile"}`,
    "",
    "=== COMPILED MESSAGES ===",
    "",
  ];
  i.messages.forEach((m, n) => {
    lines.push(`--- [${n + 1}] ${m.role.toUpperCase()} (${m.chars} chars) ---`, m.content, "");
  });
  return lines.join("\n");
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: "var(--s4)" }}>
      <div
        style={{
          fontSize: "var(--text-xs)",
          fontWeight: 650,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--ink-3)",
          marginBottom: "var(--s2)",
        }}
      >
        {title}
      </div>
      {children}
    </div>
  );
}

const mono: React.CSSProperties = {
  fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  fontSize: "var(--text-xs)",
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  background: "var(--surface-2)",
  border: "1px solid var(--line-2)",
  borderRadius: "var(--radius-sm)",
  padding: "var(--s3)",
  maxHeight: 320,
  overflowY: "auto",
};

export function PromptInspector({
  inspection,
  onClose,
}: {
  inspection: Inspection | null;
  onClose: () => void;
}) {
  if (!inspection) return null;
  const i = inspection;

  return (
    <Modal open title={`Prompt for ${i.agent}`} onClose={onClose} width="min(1000px, 94vw)">
      <Stack direction="row" gap="var(--s2)" wrap style={{ marginBottom: "var(--s4)" }}>
        <Badge tone={i.source_document.present ? "ok" : "danger"}>
          {i.source_document.present
            ? `Design attached · ${(i.source_document.chars / 1000).toFixed(0)}k chars`
            : "No design attached"}
        </Badge>
        <Badge tone={i.skill.found ? "ok" : "warn"}>
          {i.skill.found ? `Skill: ${i.skill.subject}` : "No teaching skill — generic"}
        </Badge>
        <Badge tone="info">{`${i.prompt.name} v${i.prompt.version}`}</Badge>
        {i.model && <Badge tone="neutral">{i.model}</Badge>}
        <Badge tone="neutral">{`${(i.total_prompt_chars / 1000).toFixed(1)}k chars`}</Badge>
      </Stack>

      {!i.source_document.present && (
        <EmptyState
          title="This prompt carries no curriculum design"
          description="Whatever it returns will come from the model's own knowledge. Ingest the design for this subject before generating."
          tone="warn"
        />
      )}

      <Section title="Source document">
        {i.source_document.present ? (
          <div style={mono}>{i.source_document.head}…</div>
        ) : (
          <div style={{ color: "var(--ink-3)" }}>None attached.</div>
        )}
      </Section>

      <Section title="Teaching skill">
        {i.skill.found ? (
          <div>
            <div style={mono}>{i.skill.persona}</div>
            {i.skill.directives.length > 0 && (
              <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "var(--s5)", color: "var(--ink-2)" }}>
                {i.skill.directives.map((d, n) => (
                  <li key={n} style={{ fontSize: "var(--text-sm)" }}>{d}</li>
                ))}
              </ul>
            )}
          </div>
        ) : (
          <div style={{ color: "var(--ink-3)" }}>{(i.skill as any).note}</div>
        )}
      </Section>

      {i.research_citations && i.research_citations.length > 0 && (
        <Section title={`Research sources (${i.research_citations.length})`}>
          <ul style={{ margin: 0, paddingLeft: "var(--s5)" }}>
            {i.research_citations.map((u) => (
              <li key={u} style={{ fontSize: "var(--text-sm)" }}>
                <a href={u} target="_blank" rel="noreferrer">{u}</a>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title={`Compiled messages (${i.messages.length})`}>
        <Stack gap="var(--s3)">
          {i.messages.map((m, n) => (
            <div key={n}>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)", marginBottom: 4 }}>
                [{n + 1}] {m.role} · {m.chars.toLocaleString()} chars
              </div>
              <div style={mono}>{m.content}</div>
            </div>
          ))}
        </Stack>
      </Section>

      <Stack direction="row" gap="var(--s2)" justify="flex-end">
        <CopyButton
          label="Copy the whole prompt"
          variant="secondary"
          title="Copy everything that would be sent, to review or paste into another model"
          getText={() => asText(i)}
        />
        <Button onClick={onClose}>Close</Button>
      </Stack>
    </Modal>
  );
}
