import React from "react";

import {
  Badge,
  Button,
  Card,
  CopyButton,
  ErrorNotice,
  Stack,
  Table,
  Td,
  Textarea,
  Th,
} from "../ui/components";
import { useReadDesign } from "../lib/queries";

/**
 * Paste a curriculum design and see how the parser reads it.
 *
 * Every ingest problem so far has been diagnosed by inference: a count is
 * wrong on one screen, so something upstream must be misreading a cover.
 * Sixteen Grade 9 designs were filed under Grade 7 for want of a way to ask
 * the parser "what grade do you think this is?"
 *
 * Nothing is written. This reads the text and reports what WOULD be filed — so
 * a document can be checked before it is ingested, and a document that went in
 * wrong can be checked after.
 */
export function ReadDesign({ grade = "" }: { grade?: string }) {
  const read = useReadDesign();
  const [text, setText] = React.useState("");
  const r = read.data;

  return (
    <Card
      title="Read a design without ingesting it"
      description="Paste the document's text. Nothing is written — this shows what the parser makes of it: the grade it would file under, the learning area, the strands it finds, and which references are actually scripture."
      actions={
        <Stack direction="row" gap="var(--s2)">
          {text.length > 0 && (
            <CopyButton getText={() => text} label="Copy the text" />
          )}
          <Button
            size="sm"
            disabled={text.trim().length < 200 || read.isPending}
            loading={read.isPending}
            onClick={() => read.mutateAsync({ text, grade })}
          >
            Read it
          </Button>
        </Stack>
      }
    >
      <Stack gap="var(--s3)">
        <Textarea
          aria-label="Design document text"
          value={text}
          rows={10}
          placeholder="Paste the whole document here — cover page included, because the cover is where the grade and the learning area are read from."
          onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setText(e.target.value)}
          className="mono"
          style={{ fontSize: "var(--text-sm)" }}
        />
        <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
          {text.length.toLocaleString()} characters
          {text.length > 0 && text.trim().length < 200 &&
            " — a design is tens of thousands; this looks like a fragment."}
        </div>

        {read.error && <ErrorNotice error={read.error} />}

        {r && (
          <>
            <div
              style={{
                border: "1px solid var(--line)",
                borderLeft: "4px solid var(--accent)",
                borderRadius: "var(--radius)",
                padding: "var(--s3)",
              }}
            >
              <Stack direction="row" gap="var(--s3)" align="center" wrap>
                <strong>Would file under</strong>
                <Badge tone={r.grade.would_file_under ? "ok" : "danger"}>
                  {r.grade.would_file_under || "no grade"}
                </Badge>
                <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                  {r.parsed.subject || "no learning area read"} · {r.grade.level || "no level"}
                </span>
              </Stack>
              <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)", marginTop: 4 }}>
                {r.grade.note} Cover says{" "}
                <strong>{r.grade.read_from_cover || "nothing"}</strong>; the dataset
                says <strong>{r.grade.declared_by_dataset || "nothing"}</strong>.
                {r.grade.read_from_cover &&
                  r.grade.declared_by_dataset &&
                  r.grade.read_from_cover !== r.grade.declared_by_dataset && (
                    <>
                      {" "}
                      <span style={{ color: "var(--warn)" }}>
                        They disagree — the cover wins, so this document would go to
                        a different grade than the one you are ingesting.
                      </span>
                    </>
                  )}
              </div>
            </div>

            {r.error && (
              <div style={{ color: "var(--danger)", fontSize: "var(--text-sm)" }}>
                The parser could not read it: {r.error}
              </div>
            )}

            <div style={{ fontSize: "var(--text-sm)" }}>
              <strong>{r.parsed.sub_strand_count ?? 0} sub-strand(s)</strong> across{" "}
              {(r.parsed.strands || []).length} strand(s)
              {(r.parsed.sub_strand_count ?? 0) === 0 && (
                <span style={{ color: "var(--warn)" }}>
                  {" "}— nothing was read, so this would ingest as an empty design.
                </span>
              )}
            </div>

            {(r.parsed.sub_strands || []).length > 0 && (
              <details>
                <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                  What it found
                </summary>
                <Table caption="Strands and sub-strands read from the document">
                  <thead>
                    <tr><Th>Strand</Th><Th>Sub-strand</Th><Th>Lessons</Th><Th numeric>SLOs</Th></tr>
                  </thead>
                  <tbody>
                    {r.parsed.sub_strands!.map((s, i) => (
                      <tr key={i}>
                        <Td>{s.strand}</Td>
                        <Td>{s.name}</Td>
                        <Td>{s.lessons}</Td>
                        <Td numeric>{s.slos}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </details>
            )}

            {/* Scripture, separated from the page:line addresses that look
                exactly like it. */}
            <div>
              <strong style={{ fontSize: "var(--text-sm)" }}>
                Scripture this design names ({r.scripture.references.length})
              </strong>
              <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)", margin: "2px 0 6px" }}>
                {r.scripture.note}
              </div>
              <div className="mono" style={{ fontSize: "var(--text-sm)" }}>
                {r.scripture.references.join(" · ") || "none"}
              </div>
              {r.scripture.impossible.map((m, i) => (
                <div key={i} style={{ color: "var(--danger)", fontSize: "var(--text-sm)", marginTop: 4 }}>
                  {m}
                </div>
              ))}
              {r.scripture.not_a_book.map((m, i) => (
                <div key={i} style={{ color: "var(--warn)", fontSize: "var(--text-sm)", marginTop: 4 }}>
                  {m} — written as a reference, but no such book of the Bible.
                </div>
              ))}
            </div>
          </>
        )}
      </Stack>
    </Card>
  );
}
