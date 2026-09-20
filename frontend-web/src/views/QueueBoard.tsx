import React from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Grid,
  Input,
  PageHeader,
  Select,
  Stack,
  Stat,
  Table,
  Td,
  Th,
  useToast,
} from "../ui/components";
import {
  STEP_LABEL,
  gradeOptionLabel,
  useCancelQueue,
  useGrades,
  useQueueBoard,
  useRetryFailed,
  useSweepQueue,
  type QueueBoardJob,
} from "../lib/queries";

const _KIND: Record<string, string> = {
  notes: "Lesson notes", diagram: "Diagrams", media: "Photos & videos", simulation: "Simulations",
  activity: "Activities & experiments", questions: "Questions", material: "Lesson material",
  substrands: "Sub-strands", strands: "Strands", ingest: "Read the design", dataset_item: "Ingest a design",
  review: "AI review", approval: "Approver", regeneration: "Regeneration", regenerate: "Regeneration",
  pipeline: "Full run", order: "Order (paper)",
};

/**
 * Every job in the queue, live: what is running and what it is doing right
 * now, what waits and where in the line, what finished and what it cost,
 * what failed and why. Polled every three seconds while anything moves.
 */
export function QueueBoard() {
  const [status, setStatus] = React.useState("queued,running,paused");
  const [kind, setKind] = React.useState("");
  const [grade, setGrade] = React.useState("");
  const [search, setSearch] = React.useState("");
  const [open, setOpen] = React.useState<string | null>(null);
  const grades = useGrades();
  const board = useQueueBoard({ status, kind, grade, search, limit: 300 });
  const sweep = useSweepQueue();
  const cancel = useCancelQueue();
  const retry = useRetryFailed(grade || "grade-9");
  const toast = useToast();
  const d = board.data;
  const counts = d?.counts || {};
  const jobs = (d?.jobs || []) as QueueBoardJob[];
  const running = jobs.filter((j) => j.status === "running");

  async function sweepNow() {
    try {
      const out = await sweep.mutateAsync();
      toast(`Swept: ${out.recovered} abandoned job(s) requeued, ${out.redispatched} stranded job(s) dispatched again.`, "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not sweep.", "danger"); }
  }

  return (
    <>
      <PageHeader
        eyebrow="Operate"
        title="Queue"
        description="Every job, live. A running job reports what it is doing and that it is alive; a queued one its place in the line; a finished one what it cost; a failed one why."
        actions={
          <Stack direction="row" gap="var(--s2)" wrap>
            <Badge tone={d?.runs_on === "celery" ? "ok" : d?.runs_on === "in_process" ? "warn" : "danger"}>
              {d?.runs_on === "celery" ? "workers: Celery" : d?.runs_on === "in_process" ? "worker: in the API" : "no worker running"}
            </Badge>
            <Button size="sm" variant="secondary" disabled={sweep.isPending} onClick={sweepNow}
                    title="Requeue running jobs whose heartbeat stopped; dispatch queued jobs nothing claimed">
              {sweep.isPending ? "Sweeping…" : "Sweep now"}
            </Button>
          </Stack>
        }
      />
      {board.error && <ErrorNotice error={board.error} onRetry={() => board.refetch()} />}

      {d && (
        <Grid min="9rem">
          <Stat label="Running" value={counts.running ?? 0} tone={counts.running ? "accent" : undefined} />
          <Stat label="Queued" value={counts.queued ?? 0} sub={d.queue_depth ? `${d.queue_depth} in the line` : undefined} />
          <Stat label="Paused" value={counts.paused ?? 0} tone={counts.paused ? "warn" : undefined} />
          <Stat label="Done" value={counts.done ?? 0} tone="ok" />
          <Stat label="Failed" value={counts.failed ?? 0} tone={counts.failed ? "danger" : undefined} />
          <Stat label="Cancelled" value={counts.cancelled ?? 0} />
        </Grid>
      )}

      {running.length > 0 && (
        <Card title={`Running now (${running.length})`} description="What each worker is doing, as the station reports it. A heartbeat older than a minute means the process behind it may be gone — the sweeper requeues it after five.">
          <Stack gap="var(--s2)">
            {running.map((j) => <RunningRow key={j.job_id} j={j} />)}
          </Stack>
        </Card>
      )}

      <Card
        title="All jobs"
        actions={
          <Stack direction="row" gap="var(--s2)" wrap>
            <Select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
              <option value="queued,running,paused">Live (queued · running · paused)</option>
              <option value="running">Running</option>
              <option value="queued">Queued</option>
              <option value="paused">Paused</option>
              <option value="failed">Failed</option>
              <option value="done">Done</option>
              <option value="cancelled">Cancelled</option>
              <option value="">Everything</option>
            </Select>
            <Select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)} style={{ width: "auto" }}>
              <option value="">Any kind</option>
              {["pipeline", "notes", "diagram", "questions", "material", "activity", "media", "simulation", "review", "order",
                "dataset_item", "strands", "substrands", "regeneration"].map((k) => <option key={k} value={k}>{_KIND[k] || k}</option>)}
            </Select>
            <Select aria-label="Grade" value={grade} onChange={(e) => setGrade(e.target.value)} style={{ width: "auto" }}>
              <option value="">Any grade</option>
              {(grades.data || []).map((g) => <option key={g.slug || g.name} value={g.slug || g.name}>{gradeOptionLabel(g)}</option>)}
            </Select>
            <Input aria-label="Search" value={search} placeholder="sub-strand, subject, job id, error…" onChange={(e) => setSearch(e.target.value)} style={{ width: "16rem" }} />
          </Stack>
        }
      >
        {jobs.length === 0 && <EmptyState title="Nothing here" description="No jobs match these filters." />}
        {jobs.length > 0 && (
          <div style={{ overflowX: "auto" }}>
          <Table>
            <thead>
              <tr>
                <Th>Status</Th><Th>What</Th><Th>Scope</Th><Th>Line</Th><Th>Time</Th><Th>Alive</Th><Th>Spent</Th><Th>By</Th><Th> </Th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => {
                const isOpen = open === j.job_id;
                return (
                  <React.Fragment key={j.job_id}>
                    <tr>
                      <Td><Badge tone={TONE[j.status] || "neutral"}>{j.status}</Badge>{j.attempts > 1 && <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}> · try {j.attempts}</span>}</Td>
                      <Td style={{ minWidth: "14rem" }}>
                        <div>{what(j)}</div>
                        {j.last_step && j.status === "running" && (
                          <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{j.last_step.step}: {String(j.last_step.detail || "").slice(0, 80)}</div>
                        )}
                      </Td>
                      <Td style={{ minWidth: "12rem" }}>
                        <div>{[j.grade, j.subject].filter(Boolean).join(" · ")}</div>
                        <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{[j.strand, j.sub_strand].filter(Boolean).join(" › ")}</div>
                      </Td>
                      <Td>{j.status === "queued" && j.position ? `#${j.position}` : "—"}</Td>
                      <Td>
                        {j.status === "running" ? `running ${dur(j.age_s)}` :
                         j.status === "queued" || j.status === "paused" ? `waiting ${dur(j.age_s)}` :
                         j.finished_at ? when(j.finished_at) : when(j.created_at || "")}
                      </Td>
                      <Td>{j.status === "running" ? <Alive age={j.heartbeat_age_s} /> : "—"}</Td>
                      <Td style={{ whiteSpace: "nowrap" }}>{spent(j)}</Td>
                      <Td style={{ fontSize: "var(--text-xs)" }}>{j.queued_by || "—"}</Td>
                      <Td>
                        <Stack direction="row" gap="2px">
                          {(j.error || j.last_step) && <Button size="sm" variant="ghost" onClick={() => setOpen(isOpen ? null : j.job_id)}>{isOpen ? "Hide" : "Detail"}</Button>}
                          {(j.status === "queued" || j.status === "paused") && (
                            <Button size="sm" variant="ghost" style={{ color: "var(--danger)" }} onClick={() => cancel.mutate({ job_id: j.job_id })}>Cancel</Button>
                          )}
                          {j.status === "failed" && (
                            <Button size="sm" variant="ghost" onClick={() => retry.mutate({ job_id: j.job_id })}>Retry</Button>
                          )}
                        </Stack>
                      </Td>
                    </tr>
                    {isOpen && (
                      <tr>
                        <Td colSpan={9}>
                          {j.error && <div style={{ color: "var(--danger)", fontSize: "var(--text-sm)", marginBottom: 4 }}>{j.error}{j.failed_under_build ? ` (build ${j.failed_under_build})` : ""}</div>}
                          {j.last_step && <div style={{ fontSize: "var(--text-sm)" }}><b>Last:</b> {j.last_step.step} — {j.last_step.detail}</div>}
                          <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{j.job_id}{j.batch_id ? ` · batch ${j.batch_id}` : ""}</div>
                        </Td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </Table>
          </div>
        )}
      </Card>
    </>
  );
}

function RunningRow({ j }: { j: QueueBoardJob }) {
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "var(--s2) var(--s3)", display: "flex", gap: "var(--s3)", alignItems: "center", flexWrap: "wrap" }}>
      <Badge tone="accent">running</Badge>
      <div style={{ flex: "1 1 16rem", minWidth: 0 }}>
        <div><b>{what(j)}</b> — {[j.grade, j.subject, j.sub_strand || j.strand].filter(Boolean).join(" · ")}</div>
        <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          {j.last_step ? <>{j.last_step.step}: {j.last_step.detail}</> : "starting…"}
        </div>
      </div>
      <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)", whiteSpace: "nowrap" }}>{dur(j.age_s)} · {spent(j)}</div>
      <Alive age={j.heartbeat_age_s} />
    </div>
  );
}

function Alive({ age }: { age?: number | null }) {
  if (age == null) return <Badge tone="neutral">no heartbeat yet</Badge>;
  if (age < 75) return <Badge tone="ok">alive · {age}s</Badge>;
  if (age < 300) return <Badge tone="warn">quiet · {Math.round(age / 60)} min</Badge>;
  return <Badge tone="danger">gone · {Math.round(age / 60)} min</Badge>;
}

const TONE: Record<string, "ok" | "warn" | "danger" | "accent" | "neutral" | "info"> = {
  done: "ok", running: "accent", queued: "neutral", paused: "warn", failed: "danger", cancelled: "warn",
};

function what(j: QueueBoardJob) {
  const step = j.step ? (STEP_LABEL[j.step] || j.step) : "";
  const base = _KIND[j.kind] || j.kind;
  return j.kind === "pipeline" && step ? `${step}` : step && step !== base ? `${base} · ${step}` : base;
}
function spent(j: QueueBoardJob) {
  const calls = j.llm_calls || 0;
  const cost = Number(j.cost_usd || 0);
  if (!calls && !cost) return "—";
  return `${calls} call${calls === 1 ? "" : "s"}${cost ? ` · $${cost.toFixed(3)}` : ""}`;
}
function dur(s?: number | null) {
  if (s == null) return "";
  s = Math.max(0, s);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}
function when(iso: string) {
  const t = new Date(iso);
  return isNaN(t.getTime()) ? iso : t.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
