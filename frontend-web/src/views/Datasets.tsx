import React from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Grid,
  PageHeader,
  ProgressBar,
  QueryState,
  Select,
  Stack,
  Stat,
  Table,
  Td,
  Th,
} from "../ui/components";
import {
  gradeOptionLabel,
  useGrades,
  useIngestActions,
  useIngestStatus,
  type DatasetItem,
  type IngestStatus,
} from "../lib/queries";

const STATUS_TONE: Record<IngestStatus, "ok" | "warn" | "danger" | "info"> = {
  ingested: "ok",
  processing: "info",
  selected: "info",
  pending: "warn",
  failed: "danger",
};

const STATUS_LABEL: Record<IngestStatus, string> = {
  ingested: "Ingested",
  processing: "Processing",
  selected: "Queued",
  pending: "Not processed",
  failed: "Failed",
};

export function Datasets() {
  const grades = useGrades();
  const [grade, setGrade] = React.useState("");
  const effectiveGrade = grade || grades.data?.[0]?.slug || grades.data?.[0]?.name || "";

  const status = useIngestStatus(effectiveGrade);
  const actions = useIngestActions(effectiveGrade);

  const state = status.data;
  const items = state?.items ?? [];
  const counts = state?.counts;
  const pending = items.filter((i) => i.status === "pending" || i.status === "selected");
  const failed = items.filter((i) => i.status === "failed");

  const busy =
    actions.sync.isPending || actions.process.isPending || actions.retry.isPending;

  function processAll() {
    if (!pending.length) return;
    actions.process.mutate({ item_ids: pending.map((i) => i.item_id) });
  }

  function uningest(item: DatasetItem) {
    const purge = window.confirm(
      `Un-ingest "${item.resolved_subject || item.title}"?\n\n` +
        `Its curriculum design and sub-strands are removed and the document goes ` +
        `back to Not processed.\n\n` +
        `OK — also delete the notes, diagrams, activities and questions generated ` +
        `from it (this throws away real token spend).\n` +
        `Cancel — keep that generated content.`
    );
    // Cancel means "keep the generated content", not "abort", so ask once more
    // rather than letting a stray Escape do something unintended.
    if (!purge && !window.confirm("Un-ingest but keep the generated content?")) return;
    actions.uningest.mutate({ item_ids: [item.item_id], purge_generated: purge });
  }

  function reprocess(item: DatasetItem) {
    // Replacing ingested work is destructive enough to be worth a sentence.
    const ok = window.confirm(
      `Re-process "${item.resolved_subject || item.title}"?\n\n` +
        `The curriculum design it produced will be replaced. Sub-strands it no longer ` +
        `contains are deleted, so nothing from the previous run survives.`
    );
    if (ok) actions.process.mutate({ item_ids: [item.item_id], force: true });
  }

  return (
    <>
      <PageHeader
        eyebrow="Operate"
        title="Datasets"
        description="Curriculum designs waiting in each grade's Langfuse dataset, and how far each has got. A document is ingested once; processing it again replaces what it produced rather than adding to it."
        actions={
          <Stack direction="row" gap="var(--s2)">
            <Select
              aria-label="Grade"
              value={effectiveGrade}
              onChange={(e) => setGrade(e.target.value)}
              style={{ width: "auto" }}
            >
              {(grades.data || []).map((g) => (
                <option key={g.slug || g.name} value={g.slug || g.name}>
                  {gradeOptionLabel(g)}
                </option>
              ))}
            </Select>
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || !effectiveGrade}
              onClick={() => actions.sync.mutate()}
            >
              {actions.sync.isPending ? "Syncing…" : "Sync from Langfuse"}
            </Button>
          </Stack>
        }
      />

      <Grid min="180px">
        <Stat
          label="Ingested"
          value={`${counts?.ingested ?? 0}/${state?.total ?? 0}`}
          progress={state?.ingested_percentage ?? 0}
          sub={`${state?.ingested_percentage ?? 0}% of this grade's dataset`}
        />
        <Stat label="Not processed" value={`${counts?.pending ?? 0}`} sub="Waiting to be run" />
        <Stat label="In progress" value={`${state?.in_progress ?? 0}`} sub="Queued or running" />
        <Stat label="Failed" value={`${counts?.failed ?? 0}`} sub="Need a retry" />
      </Grid>

      {/* "Ingested" above means the document was PROCESSED. It does not mean a
          design came out of it — and those two facts were reported by two
          different screens, counting two different tables, with nothing saying
          so. A grade could read "16 of 16 ingested" here and "1/16" in the
          grade list, and the gap is real work missing rather than a display
          quirk. */}
      {(state?.designs_missing?.length ?? 0) > 0 && (
        <div
          role="alert"
          style={{
            border: "1px solid var(--warn)",
            background: "var(--warn-wash)",
            borderRadius: "var(--radius)",
            padding: "var(--s3)",
            fontSize: "var(--text-sm)",
          }}
        >
          <strong>
            {state!.designs_missing!.length} document(s) are marked ingested but
            produced no curriculum design.
          </strong>{" "}
          They were read and nothing was written, so nothing downstream can be
          built from them — the grade list counts designs and will show a lower
          number than the one above. Re-process them.
          <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "18px" }}>
            {state!.designs_missing!.slice(0, 10).map((d) => (
              <li key={d.item_id}>
                {d.resolved_subject || d.declared_subject || d.title}
                {d.char_count ? ` — ${Math.round(d.char_count / 1000)}k characters read` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {actions.process.error && <ErrorNotice error={actions.process.error} />}
      {actions.sync.error && <ErrorNotice error={actions.sync.error} />}

      <QueryState query={status} label="Loading dataset" rows={4} />

      {state && (
        <Card
          title={`${items.length} document${items.length === 1 ? "" : "s"}`}
          description="Each row is one curriculum design. Titles and subjects shown are the ones resolved from the document itself, not the catalogue label."
          actions={
            <Stack direction="row" gap="var(--s2)">
              {(counts?.ingested ?? 0) > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    const done = items.filter((i) => i.status === "ingested");
                    if (
                      window.confirm(
                        `Un-ingest all ${done.length} ingested document(s) for this grade?\n\n` +
                          `Their designs and sub-strands are removed and they return to ` +
                          `Not processed. Generated content is kept.`
                      )
                    ) {
                      actions.uningest.mutate({ item_ids: done.map((i) => i.item_id) });
                    }
                  }}
                >
                  Un-ingest all
                </Button>
              )}
              {failed.length > 0 && (
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={busy}
                  onClick={() => actions.retry.mutate({})}
                >
                  Retry {failed.length} failed
                </Button>
              )}
              <Button size="sm" disabled={busy || !pending.length} onClick={processAll}>
                {actions.process.isPending
                  ? "Processing…"
                  : `Process ${pending.length} remaining`}
              </Button>
            </Stack>
          }
        >
          {items.length === 0 ? (
            <EmptyState
              title="Nothing in this grade's dataset"
              description="Upload this grade's curriculum designs to Langfuse, then press Sync from Langfuse."
              tone="warn"
            />
          ) : (
            <>
              <div style={{ marginBottom: "var(--s4)" }}>
                <ProgressBar
                  value={state.ingested_percentage}
                  label={`${effectiveGrade} ingestion progress`}
                />
              </div>
              <Table caption="Dataset items">
                <thead>
                  <tr>
                    <Th>Status</Th>
                    <Th>Document</Th>
                    <Th>Subject</Th>
                    <Th numeric>Length</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.item_id}>
                      <Td>
                        <Badge tone={STATUS_TONE[item.status]}>{STATUS_LABEL[item.status]}</Badge>
                      </Td>
                      <Td>
                        <div>{item.title || item.file_id}</div>
                        {item.error && (
                          <div
                            style={{
                              color: "var(--danger)",
                              fontSize: "var(--text-xs)",
                              marginTop: 2,
                            }}
                          >
                            {item.error}
                          </div>
                        )}
                      </Td>
                      <Td>
                        {item.resolved_subject ? (
                          <span>{item.resolved_subject}</span>
                        ) : (
                          // Before ingest all we have is the pathway heading the
                          // link sat under, which for senior school is a group
                          // rather than a learning area.
                          <span style={{ color: "var(--ink-3)" }}>
                            {item.declared_subject || "—"}
                          </span>
                        )}
                      </Td>
                      <Td numeric>
                        {item.char_count ? `${(item.char_count / 1000).toFixed(1)}k` : "—"}
                      </Td>
                      <Td>
                        {item.status === "ingested" ? (
                          <Stack direction="row" gap="var(--s2)">
                            <Button size="sm" variant="ghost" disabled={busy}
                                    onClick={() => reprocess(item)}>
                              Re-process
                            </Button>
                            <Button size="sm" variant="ghost" disabled={busy}
                                    onClick={() => uningest(item)}>
                              Un-ingest
                            </Button>
                          </Stack>
                        ) : item.status === "processing" ? (
                          <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
                            Running…
                          </span>
                        ) : (
                          <Button
                            size="sm"
                            disabled={busy}
                            onClick={() =>
                              actions.process.mutate({ item_ids: [item.item_id] })
                            }
                          >
                            Process
                          </Button>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </>
          )}
        </Card>
      )}
    </>
  );
}
