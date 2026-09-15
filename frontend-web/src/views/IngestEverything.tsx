import React from "react";
import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  Grid,
  ProgressBar,
  Stack,
  Stat,
  Table,
  Td,
  Th,
} from "../ui/components";
import {
  useAutoIngest,
  useIngestControl,
  useIngestEverything,
  useIngestProgress,
  useStructureEverything,
  useUningestEverything,
  type IngestGradeProgress,
} from "../lib/queries";

/**
 * The whole curriculum on one card: every grade's ingest, what is being read
 * now, what waits, and the controls over it. The ingest is a set of queued
 * jobs, so pause / skip / stop are queue operations — the document being read
 * finishes (an extractor killed mid-design leaves half a design), and the
 * control takes effect at the next one.
 */
export function IngestEverything() {
  const progress = useIngestProgress();
  const everything = useIngestEverything();
  const structure = useStructureEverything();
  const control = useIngestControl();
  const auto = useAutoIngest();
  const uningest = useUningestEverything();
  const [interval, setInterval_] = React.useState<string>("");

  const p = progress.data;
  const watch = p?.watch;
  const busy = everything.isPending || control.isPending || uningest.isPending;
  const waitingCount = (p?.jobs?.queued ?? 0) + (p?.jobs?.paused ?? 0);

  function ingestEverything() {
    const ok = window.confirm(
      "Ingest everything?\n\n" +
        "Every grade's dataset is synced from Langfuse and every document not yet " +
        "ingested is queued — PP1 to Grade 12, every subject. Strands and sub-strands " +
        "are generated behind each document for any learning area that comes out " +
        "without them.\n\n" +
        "Documents run one at a time in the worker; a whole curriculum is hours, " +
        "not minutes. You can pause, skip or stop it here."
    );
    if (ok) everything.mutate({ then_structure: true });
  }

  function uningestEverything() {
    const purge = window.confirm(
      "Un-ingest EVERYTHING?\n\n" +
        "Every curriculum design and every sub-strand in every grade is removed, and " +
        "every document goes back to Not processed. Waiting ingest jobs are stopped first.\n\n" +
        "OK — also delete every note, diagram, activity and question generated from " +
        "them (this throws away all token spend so far).\n" +
        "Cancel — keep the generated content."
    );
    if (!purge && !window.confirm("Un-ingest everything but keep the generated content?")) return;
    const word = window.prompt("Type EVERYTHING to confirm.");
    if ((word || "").trim().toUpperCase() !== "EVERYTHING") return;
    uningest.mutate({ purge_generated: purge, purge_orphans: true, confirm: "EVERYTHING" });
  }

  function toggleAuto() {
    if (!watch) return;
    const minutes = interval ? Math.max(5, parseInt(interval, 10) || 30) : undefined;
    auto.mutate({ enabled: !watch.enabled, interval_minutes: minutes });
  }

  return (
    <Card
      title="Everything, every grade"
      description="One press syncs every grade from Langfuse, ingests every design and builds the strands and sub-strands behind it. The same pass runs on a schedule when auto-sync is on."
      actions={
        <Stack direction="row" gap="var(--s2)" wrap>
          {p?.active && !p.paused && (
            <Button size="sm" variant="secondary" disabled={busy}
                    onClick={() => control.mutate({ action: "pause" })}>
              Pause
            </Button>
          )}
          {p?.paused && (
            <Button size="sm" disabled={busy}
                    onClick={() => control.mutate({ action: "resume" })}>
              Resume
            </Button>
          )}
          {waitingCount > 0 && (
            <Button size="sm" variant="ghost" disabled={busy}
                    onClick={() => {
                      if (window.confirm(`Stop the ingest? ${waitingCount} waiting document(s) are cancelled; the one being read finishes.`))
                        control.mutate({ action: "stop" });
                    }}>
              Stop
            </Button>
          )}
          <Button size="sm" variant="ghost" disabled={busy || structure.isPending}
                  title="Strands and sub-strands for every ingested learning area that has none"
                  onClick={() => structure.mutate()}>
            {structure.isPending ? "Queuing…" : "Fill missing structure"}
          </Button>
          <Button size="sm" disabled={busy} onClick={ingestEverything}>
            {everything.isPending ? "Queuing everything…" : "Ingest everything"}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={uningestEverything}
                  style={{ color: "var(--danger)" }}>
            {uningest.isPending ? "Un-ingesting…" : "Un-ingest everything"}
          </Button>
        </Stack>
      }
    >
      <Stack gap="var(--s4)">
        {everything.error && <ErrorNotice error={everything.error} />}
        {structure.error && <ErrorNotice error={structure.error} />}
        {control.error && <ErrorNotice error={control.error} />}
        {auto.error && <ErrorNotice error={auto.error} />}
        {uningest.error && <ErrorNotice error={uningest.error} />}
        {progress.error && <ErrorNotice error={progress.error} onRetry={() => progress.refetch()} />}

        {p && (
          <Grid min="10rem">
            <Stat label="Documents ingested" value={`${p.ingested} / ${p.total}`}
                  progress={p.percentage}
                  tone={p.failed ? "warn" : p.total && p.ingested === p.total ? "ok" : undefined}
                  sub={p.failed ? `${p.failed} failed` : undefined} />
            <Stat label="Waiting" value={waitingCount}
                  sub={p.paused ? "paused" : p.jobs?.running ? "one being read now" : undefined}
                  tone={p.paused ? "warn" : undefined} />
            <Stat label="Now reading"
                  value={p.current ? `${gradeLabel(p, p.current.grade)} · ${p.current.subject}` : "—"}
                  sub={p.current?.progress ? describeProgress(p.current.progress) : undefined}
                  tone={p.current ? "accent" : undefined} />
            <Stat label="Auto-sync from Langfuse"
                  value={watch?.enabled ? `every ${watch.interval_minutes} min` : "off"}
                  tone={watch?.enabled ? "ok" : undefined}
                  sub={watch?.enabled
                    ? watch.last_error
                      ? `last run failed: ${watch.last_error}`
                      : watch.last_run_at
                        ? `last: ${timeAgo(watch.last_run_at)}, queued ${watch.last_queued ?? 0} · next in ${Math.round((watch.next_run_in_seconds ?? 0) / 60)} min`
                        : "first run within a minute"
                    : "new designs in Langfuse wait for a press"} />
          </Grid>
        )}

        {watch && (
          <Stack direction="row" gap="var(--s2)" align="center" wrap>
            <Button size="sm" variant={watch.enabled ? "ghost" : "secondary"} disabled={auto.isPending}
                    onClick={toggleAuto}>
              {auto.isPending ? "Saving…" : watch.enabled ? "Turn auto-sync off" : "Turn auto-sync on"}
            </Button>
            {!watch.enabled && (
              <label style={{ fontSize: "var(--text-sm)", display: "flex", gap: "var(--s2)", alignItems: "center" }}>
                every
                <input type="number" min={5} step={5} value={interval} placeholder={String(watch.interval_minutes)}
                       onChange={(e) => setInterval_(e.target.value)}
                       style={{ width: "5rem" }} aria-label="Auto-sync interval in minutes" />
                minutes
              </label>
            )}
            <span style={{ fontSize: "var(--text-sm)", color: "var(--muted)" }}>
              Also under Settings → Datasets.
            </span>
          </Stack>
        )}

        {everything.data && (
          <Notice>
            <strong>{everything.data.queued} document{everything.data.queued === 1 ? "" : "s"} queued</strong>{" "}
            across {everything.data.grades_synced} grades
            {everything.data.skipped > 0 && <> ({everything.data.skipped} already ingested or in progress, left alone)</>}.
            {Object.entries(everything.data.synced)
              .filter(([, v]) => "error" in v)
              .map(([g, v]) => (
                <div key={g} style={{ color: "var(--danger)" }}>{g}: {String(v.error)}</div>
              ))}
          </Notice>
        )}
        {structure.data && (
          <Notice>
            <strong>{structure.data.queued} learning area{structure.data.queued === 1 ? "" : "s"}</strong>{" "}
            queued for strands and sub-strands
            {structure.data.jobs.length > 0
              ? <>: {structure.data.jobs.map((j) => `${j.grade} ${j.subject}`).join(", ")}</>
              : <> — every ingested learning area already has its spine.</>}
          </Notice>
        )}
        {uningest.data && (
          <Notice>
            <strong>{uningest.data.uningested} document{uningest.data.uningested === 1 ? "" : "s"} un-ingested</strong>
            {uningest.data.failed > 0 && <>, {uningest.data.failed} could not be</>}
            {uningest.data.stopped > 0 && <>; {uningest.data.stopped} waiting job(s) stopped</>}.
            {Object.keys(uningest.data.removed).length > 0 && (
              <> Removed: {Object.entries(uningest.data.removed).map(([k, v]) => `${v} ${k}`).join(", ")}.</>
            )}
          </Notice>
        )}

        {p && p.grades.some((g) => g.total > 0) && (
          <Table>
            <thead>
              <tr>
                <Th>Grade</Th>
                <Th>Progress</Th>
                <Th>Ingested</Th>
                <Th>Waiting</Th>
                <Th>Failed</Th>
                <Th>Structure</Th>
                <Th> </Th>
              </tr>
            </thead>
            <tbody>
              {p.grades.filter((g) => g.total > 0).map((g) => (
                <GradeRow key={g.grade} g={g} busy={busy}
                          onSkip={() => {
                            if (window.confirm(`Skip ${g.label}? Its waiting documents are dropped from this run; nothing already ingested is touched.`))
                              control.mutate({ action: "skip", grade: g.grade });
                          }} />
              ))}
            </tbody>
          </Table>
        )}

        {p && p.waiting.length > 0 && (
          <details>
            <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)" }}>
              {p.waiting.length} waiting — in order
            </summary>
            <Table>
              <thead>
                <tr><Th>#</Th><Th>Grade</Th><Th>Subject</Th><Th>What</Th><Th>Status</Th><Th> </Th></tr>
              </thead>
              <tbody>
                {p.waiting.map((w, i) => (
                  <tr key={w.job_id}>
                    <Td>{i + 1}</Td>
                    <Td>{gradeLabel(p, w.grade)}</Td>
                    <Td>{w.subject}</Td>
                    <Td>{w.kind === "dataset_item" ? "Read design" : "Strands → sub-strands"}</Td>
                    <Td><Badge tone={w.status === "paused" ? "warn" : "neutral"}>{w.status}</Badge></Td>
                    <Td>
                      <Button size="sm" variant="ghost" disabled={busy}
                              onClick={() => control.mutate({ action: "skip", job_id: w.job_id })}>
                        Skip
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </details>
        )}
      </Stack>
    </Card>
  );
}

function GradeRow({ g, busy, onSkip }: { g: IngestGradeProgress; busy: boolean; onSkip: () => void }) {
  const c = g.counts;
  const waiting = (c.selected ?? 0) + (c.processing ?? 0);
  const pct = g.total ? Math.round(((c.ingested ?? 0) / g.total) * 100) : 0;
  return (
    <tr>
      <Td>{g.label}</Td>
      <Td style={{ minWidth: "10rem" }}>
        <ProgressBar value={pct} tone={c.failed ? "warn" : pct === 100 ? "ok" : undefined} label={`${pct}%`} />
      </Td>
      <Td>{c.ingested ?? 0} / {g.total}</Td>
      <Td>{waiting > 0 ? <Badge tone="info">{waiting}{c.processing ? " · reading" : ""}</Badge> : "—"}</Td>
      <Td>{c.failed ? <Badge tone="danger">{c.failed}</Badge> : "—"}</Td>
      <Td>
        {g.structure_running > 0
          ? <Badge tone="accent">building</Badge>
          : g.structure_queued > 0
            ? <Badge tone="neutral">{g.structure_queued} queued</Badge>
            : "—"}
      </Td>
      <Td>
        {waiting > 0 && (
          <Button size="sm" variant="ghost" disabled={busy} onClick={onSkip}>Skip grade</Button>
        )}
      </Td>
    </tr>
  );
}

function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div role="status"
         style={{ border: "1px solid var(--line)", background: "var(--surface-2, var(--surface))",
                  borderRadius: "var(--radius)", padding: "var(--s3)", fontSize: "var(--text-sm)" }}>
      {children}
    </div>
  );
}

function gradeLabel(p: { grades: IngestGradeProgress[] }, slug: string) {
  return p.grades.find((g) => g.grade === slug)?.label ?? slug;
}

function describeProgress(progress: any): string {
  if (!progress || typeof progress !== "object") return "";
  const step = progress.step || progress.stage || progress.status;
  const done = progress.done ?? progress.completed;
  const total = progress.total;
  return [step, done != null && total != null ? `${done}/${total}` : ""].filter(Boolean).join(" · ");
}

function timeAgo(epochSeconds: number): string {
  const s = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}
