import React from "react";

import {
  Badge,
  Button,
  ErrorNotice,
  Input,
  Modal,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import { useFactoryReset } from "../lib/queries";

/**
 * Clear generated content and start again from the dataset.
 *
 * The Langfuse dataset holds the KICD design documents and is the source of
 * truth; nothing here touches it. Everything downstream — designs, sub-strands,
 * notes, media, artifacts, reviews, questions — is derived and reproducible,
 * which is what makes discarding it safe when the pipeline that produced it has
 * changed enough that reconciling the old output costs more than regenerating.
 *
 * The counts are shown before anything goes, and the confirmation is a phrase
 * rather than a button: a click is too easy to make by accident on a screen you
 * opened to look at something else.
 */
export function ResetPanel({
  grade,
  subject,
  label = "Clear generated content…",
  onDone,
}: {
  grade?: string;
  subject?: string;
  label?: string;
  onDone?: () => void;
}) {
  const reset = useFactoryReset();
  const [open, setOpen] = React.useState(false);
  const [typed, setTyped] = React.useState("");

  const report = reset.data;
  const phrase = report?.confirmation_required || "DELETE ALL GENERATED CONTENT";
  const armed = typed.trim() === phrase;
  const done = report && !report.dry_run;

  const scopeLabel = subject
    ? `${subject} in ${grade}`
    : grade
    ? grade
    : "every grade and every subject";

  function begin() {
    setOpen(true);
    setTyped("");
    reset.reset();
    reset.mutate({ grade, subject });
  }

  return (
    <>
      <Button size="sm" variant="ghost" onClick={begin}>
        {label}
      </Button>

      {open && (
        <Modal
          open
          title="Clear generated content"
          onClose={() => setOpen(false)}
          width="min(760px, 94vw)"
          footer={
            <Stack direction="row" gap="var(--s2)" justify="flex-end">
              <Button variant="ghost" onClick={() => setOpen(false)}>
                {done ? "Close" : "Cancel"}
              </Button>
              {!done && (
                <Button
                  variant="danger"
                  disabled={!armed || reset.isPending || !report || report.total_rows === 0}
                  loading={reset.isPending}
                  onClick={() => reset.mutate({ grade, subject, confirm: phrase })}
                >
                  Delete {report ? report.total_rows.toLocaleString() : ""} row(s)
                </Button>
              )}
            </Stack>
          }
        >
          <Stack gap="var(--s3)">
            <div style={{ fontSize: "var(--text-sm)" }}>
              <strong>Scope: {scopeLabel}</strong>
              <p style={{ color: "var(--ink-3)", margin: "6px 0 0" }}>
                The curriculum designs in your Langfuse dataset are not touched.
                Everything cleared here was derived from them and can be produced
                again by re-ingesting.
              </p>
            </div>

            {reset.error && <ErrorNotice error={reset.error} />}

            {report && (
              <>
                <div
                  style={{
                    padding: "var(--s3)",
                    borderRadius: "var(--radius)",
                    border: "1px solid var(--line)",
                    fontSize: "var(--text-sm)",
                  }}
                >
                  {report.message}
                </div>

                {report.total_rows > 0 && (
                  <Table caption="What would be cleared">
                    <thead>
                      <tr>
                        <Th>Table</Th>
                        <Th>What it holds</Th>
                        <Th numeric>Rows</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.tables
                        .filter((t) => t.rows > 0)
                        .map((t) => (
                          <tr key={t.table}>
                            <Td><code>{t.table}</code></Td>
                            <Td>{t.what}</Td>
                            <Td numeric>
                              {t.rows.toLocaleString()}
                              {t.deleted === true && <> <Badge tone="ok">cleared</Badge></>}
                              {t.deleted === false && <> <Badge tone="danger">failed</Badge></>}
                            </Td>
                          </tr>
                        ))}
                    </tbody>
                  </Table>
                )}

                {report.skipped.length > 0 && (
                  <details style={{ fontSize: "var(--text-sm)" }}>
                    <summary style={{ cursor: "pointer", color: "var(--ink-2)" }}>
                      {report.skipped.length} table(s) left alone by this scope
                    </summary>
                    <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em", color: "var(--ink-3)" }}>
                      {report.skipped.map((sk) => (
                        <li key={sk.table}><code>{sk.table}</code> — {sk.why}</li>
                      ))}
                    </ul>
                  </details>
                )}

                {report.failed.length > 0 && (
                  <div
                    style={{
                      border: "1px solid var(--danger)",
                      borderRadius: "var(--radius)",
                      padding: "var(--s3)",
                      fontSize: "var(--text-sm)",
                    }}
                  >
                    <strong>Some tables did not clear.</strong>
                    <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em" }}>
                      {report.failed.map((f, i) => (
                        <li key={i}><code>{f.table}</code>: {f.error}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {!done && report.total_rows > 0 && (
                  <div>
                    <label
                      htmlFor="reset-confirm"
                      style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}
                    >
                      Type <code>{phrase}</code> to confirm. This cannot be undone.
                    </label>
                    <Input
                      id="reset-confirm"
                      value={typed}
                      autoComplete="off"
                      placeholder={phrase}
                      onChange={(e) => setTyped(e.target.value)}
                      style={{ marginTop: "var(--s2)" }}
                    />
                  </div>
                )}

                {done && (
                  <Button
                    variant="primary"
                    onClick={() => {
                      setOpen(false);
                      onDone?.();
                    }}
                  >
                    Done — re-ingest from the dataset
                  </Button>
                )}
              </>
            )}
          </Stack>
        </Modal>
      )}
    </>
  );
}
