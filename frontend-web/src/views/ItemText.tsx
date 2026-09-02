import React from "react";

import {
  Badge,
  CopyButton,
  ErrorNotice,
  LoadingBlock,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import { useItemText } from "../lib/queries";

/**
 * The document the ingest actually saw, beside what it made of it.
 *
 * "Read but no design" was chased for several sessions by inference — a count
 * is wrong on one screen, so something upstream must be misreading something.
 * The text was never visible, and neither was the gap between what the ingest
 * says it wrote and what the grade list counts.
 *
 * Three facts, one place: the text, the parse, and the design rows that exist
 * for this grade right now. Nothing here writes or re-runs anything.
 */
export function ItemText({ grade, itemId }: { grade: string; itemId: string }) {
  const q = useItemText(grade, itemId);

  if (q.isLoading) return <LoadingBlock rows={4} label="Reading the document" />;
  if (q.isError) return <ErrorNotice error={q.error} />;
  const d = q.data;
  if (!d) return null;

  const readsAs = d.parsed.grade || d.grade_reading.read_from_cover;
  const wrote = d.designs_for_this_grade.length;

  return (
    <Stack gap="var(--s3)" style={{ marginTop: "var(--s3)" }}>
      {/* The disagreement, first, because it is the reason to be here. */}
      <div
        style={{
          border: `1px solid var(--${d.claimed_but_absent.length || (d.status === "ingested" && !wrote) ? "danger" : "line"})`,
          borderRadius: "var(--radius)",
          padding: "var(--s3)",
          fontSize: "var(--text-sm)",
        }}
      >
        <Stack direction="row" gap="var(--s3)" align="center" wrap>
          <Badge tone={d.status === "ingested" ? "ok" : "warn"}>{d.status}</Badge>
          <span>
            reads as <strong>{readsAs || "no grade"}</strong> ·{" "}
            <strong>{d.parsed.subject || "no learning area"}</strong> ·{" "}
            <strong>{d.parsed.sub_strand_count ?? 0}</strong> sub-strand(s)
          </span>
          <span className="mono" style={{ color: "var(--ink-3)" }}>
            {d.characters.toLocaleString()} chars
          </span>
        </Stack>
        <div style={{ marginTop: 6, color: "var(--ink-2)" }}>
          Cover says <strong>{d.grade_reading.read_from_cover || "nothing"}</strong>;
          the dataset says <strong>{d.grade_reading.declared_by_dataset || "nothing"}</strong>.
          {" "}This grade holds <strong>{wrote}</strong> design row(s) right now.
        </div>
        {d.status === "ingested" && wrote === 0 && (
          <div style={{ color: "var(--danger)", marginTop: 6 }}>
            Marked ingested and this grade holds no designs at all. The ingest
            reported success and nothing was written — that is the failure, not
            the reading.
          </div>
        )}
        {d.claimed_but_absent.length > 0 && (
          <div style={{ color: "var(--danger)", marginTop: 6 }}>
            It claims design {d.claimed_but_absent.join(", ")}, which is not in the
            database. The row was written and is gone, or was never written.
          </div>
        )}
        {d.parse_error && (
          <div style={{ color: "var(--danger)", marginTop: 6 }}>
            The parser could not read it: {d.parse_error}
          </div>
        )}
        {d.error && (
          <div style={{ color: "var(--warn)", marginTop: 6 }}>
            Last recorded error: {d.error}
          </div>
        )}
      </div>

      {(d.parsed.sub_strands || []).length > 0 && (
        <details>
          <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            The {d.parsed.sub_strand_count} sub-strand(s) it reads
          </summary>
          <Table caption="Read from this document">
            <thead>
              <tr><Th>Strand</Th><Th>Sub-strand</Th><Th>Lessons</Th><Th numeric>SLOs</Th></tr>
            </thead>
            <tbody>
              {d.parsed.sub_strands!.map((s, i) => (
                <tr key={i}>
                  <Td>{s.strand}</Td><Td>{s.name}</Td>
                  <Td>{s.lessons}</Td><Td numeric>{s.slos}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </details>
      )}

      <div>
        <Stack direction="row" gap="var(--s2)" align="center" wrap>
          <strong style={{ fontSize: "var(--text-sm)" }}>The text, as the ingest receives it</strong>
          <CopyButton getText={() => d.text} label="Copy the whole document" />
          <CopyButton getText={() => d.cover} label="Copy the cover" />
          <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
            input keys: {d.input_keys.join(", ") || "none"}
          </span>
        </Stack>
        <pre
          className="mono"
          style={{
            marginTop: "var(--s2)",
            maxHeight: "26rem",
            overflow: "auto",
            background: "var(--surface-2)",
            border: "1px solid var(--line)",
            borderRadius: "var(--radius-sm)",
            padding: "var(--s3)",
            fontSize: "0.78rem",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {d.text || "This item carries no text at all — which would explain everything."}
        </pre>
      </div>
    </Stack>
  );
}
