import React from "react";
import { Badge, Button, ErrorNotice, LoadingBlock, Stack } from "./components";
import { useDeleteDrawing, useDiagramLibrary, useEditDrawing } from "../lib/queries";

/**
 * Every drawing a sub-strand has, numbered as the BOOK numbers them.
 *
 * The console listed visuals per diagram ARTIFACT VERSION, and the page
 * numbers its figures across the whole lesson — so `DIAGRAM 1.2` on the page
 * lived in a different version from `1.1`, behind a row of version tabs every
 * one of which was labelled "Integers". An operator could see a figure on the
 * page and had no way whatsoever to reach it.
 *
 * This is the same deduplicated list the page renders from. What is here is
 * what prints.
 */
export function DiagramLibrary({
  grade,
  subject,
  subStrand,
}: {
  grade: string;
  subject: string;
  subStrand: string;
}) {
  const library = useDiagramLibrary({ grade, subject, sub_strand: subStrand });
  const edit = useEditDrawing();
  const remove = useDeleteDrawing();
  const [editing, setEditing] = React.useState<string | null>(null);
  const [draft, setDraft] = React.useState("");
  const [confirming, setConfirming] = React.useState<string | null>(null);

  if (library.isPending) return <LoadingBlock />;
  const rows = library.data?.diagrams || [];
  if (!rows.length) return null;

  return (
    <Stack gap="var(--s3)" style={{ marginTop: "var(--s3)" }}>
      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: "var(--text-sm)" }}>Diagrams in the book</strong>
        <Badge tone="ok">{rows.length}</Badge>
        <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          Numbered as the page numbers them. Changing one here changes what prints.
        </span>
      </Stack>

      {library.error && <ErrorNotice error={library.error} />}
      {edit.error && <ErrorNotice error={edit.error} />}
      {remove.error && <ErrorNotice error={remove.error} />}

      {rows.map((row) => {
        const bad = row.layout && !row.layout.fits;
        return (
          <div
            key={row.asset_id || row.number}
            style={{
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-sm)",
              padding: "var(--s3)",
            }}
          >
            <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)", letterSpacing: "0.06em" }}>
                DIAGRAM {row.number}
              </span>
              <strong style={{ fontSize: "var(--text-sm)" }}>{row.title}</strong>
              <Badge tone={bad ? "warn" : "ok"}>
                {bad ? `${row.layout!.overlapping_labels} label(s) collide` : "reads cleanly"}
              </Badge>

              {bad && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={edit.isPending}
                  title="Cut the explanations off the labels and raise anything too small. Measured, and kept only if it reads better."
                  onClick={() => edit.mutate({ asset_id: row.asset_id, repair: true })}
                >
                  Fix the labels
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                disabled={!row.editable}
                onClick={() => {
                  setEditing(editing === row.asset_id ? null : row.asset_id);
                  setDraft(row.svg);
                }}
              >
                {editing === row.asset_id ? "Cancel" : "Edit"}
              </Button>
              {confirming === row.asset_id ? (
                <>
                  <Button
                    size="sm"
                    variant="danger"
                    loading={remove.isPending}
                    onClick={() =>
                      remove.mutateAsync(row.asset_id).finally(() => setConfirming(null))
                    }
                  >
                    Delete it
                  </Button>
                  <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                    Its plate returns to the brief. The plan is untouched.
                  </span>
                </>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => setConfirming(row.asset_id)}>
                  Delete
                </Button>
              )}
            </Stack>

            {bad && (
              <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "1.1rem", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                {row.layout!.findings.map((f, i) => (
                  <li key={i}>{f}</li>
                ))}
              </ul>
            )}

            {editing === row.asset_id && (
              <div style={{ marginTop: "var(--s3)" }}>
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  spellCheck={false}
                  style={{
                    width: "100%",
                    minHeight: 220,
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                    fontSize: 12,
                    lineHeight: 1.45,
                    padding: "var(--s2)",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--line)",
                    background: "var(--surface-2)",
                    color: "var(--ink-1)",
                  }}
                />
                <Button
                  size="sm"
                  style={{ marginTop: "var(--s2)" }}
                  disabled={edit.isPending || !draft.trim()}
                  loading={edit.isPending}
                  onClick={() =>
                    edit
                      .mutateAsync({ asset_id: row.asset_id, svg: draft })
                      .then(() => setEditing(null))
                  }
                >
                  Save this drawing
                </Button>
              </div>
            )}

            {row.svg && (
              // At the size it prints. A drawing stretched across this panel
              // hides the very faults that make it unreadable on the page.
              <div style={{ marginTop: "var(--s3)" }}>
                <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)", marginBottom: "var(--s1)" }}>
                  Actual size in the book — 85mm column
                </div>
                <div
                  style={{
                    width: "85mm",
                    maxWidth: "100%",
                    background: "#fff",
                    border: "1px solid var(--line)",
                    borderRadius: "var(--radius-sm)",
                  }}
                  dangerouslySetInnerHTML={{ __html: row.svg }}
                />
              </div>
            )}
          </div>
        );
      })}
    </Stack>
  );
}
