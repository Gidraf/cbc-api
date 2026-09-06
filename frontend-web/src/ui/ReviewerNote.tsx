import React from "react";
import { Badge, Button, ErrorNotice, Stack } from "./components";
import { useReviewerNote, useReviewerNotes } from "../lib/queries";

/**
 * What a person read, and what has to be rebuilt because of it.
 *
 * A model reviewer scores dimensions. A person reads the thing and knows why
 * it is wrong — and that had nowhere to go but a conversation, so a systematic
 * fault had to be described to whoever runs the console rather than to the
 * pipeline.
 *
 * Nothing regenerates from here. Regeneration costs money and takes a station
 * out of service; what to rebuild and when is a decision. This makes the
 * consequence visible before the decision, which is the part that was missing.
 */
export function ReviewerNote({
  artifactId,
  kind,
}: {
  artifactId: string;
  kind: string;
}) {
  const note = useReviewerNote();
  const existing = useReviewerNotes(artifactId);
  const [body, setBody] = React.useState("");
  const [action, setAction] = React.useState("rewrite");

  const filed = existing.data?.notes || [];

  return (
    <Stack gap="var(--s2)" style={{ marginTop: "var(--s3)" }}>
      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: "var(--text-sm)" }}>Reviewer&rsquo;s note</strong>
        {filed.length > 0 && <Badge tone="warn">{filed.length} on this version</Badge>}
        <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          A regeneration of this version is given these to answer.
        </span>
      </Stack>

      {filed.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "var(--text-sm)" }}>
          {filed.map((n, i) => (
            <li key={i} style={{ marginBottom: 3 }}>{n}</li>
          ))}
        </ul>
      )}

      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        placeholder="What is wrong with this version, in your own words. Be specific enough that a regeneration can act on it — 'the worked example uses litres where the design says millilitres'."
        style={{
          width: "100%", minHeight: 92, padding: "var(--s2)",
          borderRadius: "var(--radius-sm)", border: "1px solid var(--line)",
          background: "var(--surface-2)", color: "var(--ink-1)",
          fontSize: "var(--text-sm)", lineHeight: 1.45,
        }}
      />

      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          style={{
            padding: "5px 8px", borderRadius: "var(--radius-sm)",
            border: "1px solid var(--line)", background: "var(--surface-2)",
            color: "var(--ink-1)", fontSize: "var(--text-sm)",
          }}
        >
          <option value="rewrite">Send it back — regenerate this version</option>
          <option value="amend">Keep it — fix what I named</option>
          <option value="note">Just a note — nothing to rebuild</option>
        </select>
        <Button
          size="sm"
          disabled={!body.trim() || note.isPending}
          loading={note.isPending}
          onClick={() =>
            note
              .mutateAsync({ artifact_id: artifactId, body, action })
              .then(() => setBody(""))
          }
        >
          File the note
        </Button>
        {action === "rewrite" && kind === "notes" && (
          <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            Everything built from this plan — material, diagrams, activities,
            experiments, questions — is marked stale, not deleted.
          </span>
        )}
      </Stack>

      {note.error && <ErrorNotice error={note.error} />}
      {note.data && (
        <div
          style={{
            padding: "var(--s2)", fontSize: "var(--text-sm)",
            background: note.data.stale_count ? "var(--warn-bg, #fff8e6)" : "var(--surface-2)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          {note.data.says}
        </div>
      )}
    </Stack>
  );
}
