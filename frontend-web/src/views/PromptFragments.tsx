import React from "react";
import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  Field,
  Input,
  LoadingBlock,
  Stack,
  Textarea,
} from "../ui/components";
import { usePromptFragments, type PromptFragment } from "../lib/queries";

/**
 * The domain prompts, one at a time.
 *
 * Education is wide. A prompt that must serve every subject is a prompt nobody
 * improves: change the paragraph about balancing equations and you have edited
 * the prompt that writes a PP1 singing lesson — so the person who knows
 * chemistry will not touch it, and it stays wrong.
 *
 * These are small, separate, and each is its own Langfuse prompt. Somebody who
 * knows maps can improve the map fragment without reading a word of the rest.
 */

function Fragment({ fragment }: { fragment: PromptFragment }) {
  const { save } = usePromptFragments();
  const [open, setOpen] = React.useState(false);
  const [text, setText] = React.useState(fragment.body);
  const changed = text !== fragment.body;

  return (
    <Card
      title={fragment.title}
      description={fragment.why}
      accent={fragment.applies_here ? "ok" : undefined}
      actions={
        <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center" }}>
          {fragment.applies_here !== undefined && (
            <Badge tone={fragment.applies_here ? "ok" : "neutral"}>
              {fragment.applies_here ? "applies here" : "not here"}
            </Badge>
          )}
          <span className="mono" style={{ fontSize: "0.75rem", color: "var(--ink-3)" }}>
            {fragment.langfuse_name}
          </span>
          <Button size="sm" variant="ghost" onClick={() => setOpen(!open)}>
            {open ? "Close" : "Edit"}
          </Button>
        </Stack>
      }
    >
      <Stack direction="row" gap="var(--s2)" wrap style={{ marginBottom: "var(--s2)" }}>
        {fragment.subjects.map((s) => (
          <Badge key={s} tone="neutral">
            {s}
          </Badge>
        ))}
        <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
          {fragment.grades.length
            ? `${fragment.grades[0]} → ${fragment.grades[fragment.grades.length - 1]}`
            : "every grade"}
          {" · "}
          {fragment.stations.join(", ")}
        </span>
      </Stack>

      {/* Domain knowledge is exactly where a prompt drifts away from the
          curriculum and towards what the author happens to know about the
          subject. Naming the design's own hook is what holds it. */}
      <p
        style={{
          fontSize: "var(--text-sm)",
          color: "var(--ink-2)",
          borderLeft: "2px solid var(--accent)",
          paddingLeft: "var(--s3)",
          margin: "0 0 var(--s3)",
        }}
      >
        <strong>What the KICD design asks for: </strong>
        {fragment.kicd}
      </p>

      {open ? (
        <>
          <Textarea
            rows={20}
            value={text}
            spellCheck={false}
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setText(e.target.value)}
            style={{ fontFamily: "var(--mono, monospace)", fontSize: "var(--text-sm)" }}
          />
          <Stack direction="row" gap="var(--s2)" style={{ marginTop: "var(--s2)" }}>
            <Button
              size="sm"
              disabled={!changed || save.isPending}
              onClick={() => save.mutate({ name: fragment.name, body: text })}
            >
              {save.isPending ? "Saving…" : "Save to Langfuse"}
            </Button>
            <Button size="sm" variant="ghost" disabled={!changed} onClick={() => setText(fragment.body)}>
              Back to the built-in
            </Button>
          </Stack>
          <p style={{ marginTop: "var(--s2)", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
            Saved under <code>{fragment.langfuse_name}</code>, versioned like every
            other prompt. The built-in text stays in the code as the default, so a
            fresh deployment works with no prompt store at all.
          </p>
          {save.error && <ErrorNotice error={save.error} />}
        </>
      ) : (
        <pre
          style={{
            margin: 0,
            maxHeight: 220,
            overflow: "auto",
            fontSize: "var(--text-sm)",
            background: "var(--surface-2)",
            padding: "var(--s3)",
            borderRadius: "var(--radius-sm)",
            whiteSpace: "pre-wrap",
          }}
        >
          {fragment.body}
        </pre>
      )}
    </Card>
  );
}

export function PromptFragments({
  subject = "",
  grade = "",
  station = "",
  compact = false,
}: {
  subject?: string;
  grade?: string;
  station?: string;
  /** On the board, only what applies here. On its own screen, all of them. */
  compact?: boolean;
}) {
  const [filter, setFilter] = React.useState(subject);
  const { list } = usePromptFragments(compact ? subject : filter, grade, station);

  if (list.isLoading) return <LoadingBlock rows={4} label="Loading the domain prompts" />;
  if (list.isError) return <ErrorNotice error={list.error} />;

  const all = list.data?.fragments || [];
  const shown = compact ? all.filter((f) => f.applies_here) : all;

  if (compact && !shown.length) {
    return (
      <p style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
        No domain prompt applies to {subject || "this subject"} at this stage —
        which is usually right. A lesson plan about God needs no paragraph on
        mortise and tenon joints.
      </p>
    );
  }

  return (
    <Stack gap="var(--s3)" style={{ marginTop: compact ? "var(--s3)" : 0 }}>
      {!compact && (
        <Field label="Show what applies to" hint="Leave empty to see all of them">
          {(a11y) => (
            <Input
              {...a11y}
              value={filter}
              placeholder="Geography, Chemistry, Music…"
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setFilter(e.target.value)}
            />
          )}
        </Field>
      )}
      {shown.map((f) => (
        <Fragment key={f.name} fragment={f} />
      ))}
    </Stack>
  );
}
