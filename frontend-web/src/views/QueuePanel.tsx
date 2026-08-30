import React from "react";

import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  ProgressBar,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import {
  PIPELINE_STEPS,
  QUEUEABLE_KINDS,
  STEP_LABEL,
  useCancelQueue,
  useQueuePipeline,
  useQueueRegenerate,
  useQueueReview,
  useQueueStatus,
  useQueueWork,
  useRetryFailed,
  useServerHealth,
} from "../lib/queries";

/**
 * Queue the long work and watch it.
 *
 * One sub-strand's notes take about a minute; a grade's worth take an
 * afternoon. Held open on a request that blocks a tab, times out at the proxy,
 * and loses everything on a refresh — so the work was done one item at a time
 * with somebody watching it.
 *
 * The queue runs sequentially on purpose: these calls cost money and hit
 * provider rate limits, and ten at once fails halfway with no way to tell which
 * half. Slower, and knowable.
 */

const STATUS_TONE: Record<string, "ok" | "warn" | "danger" | "accent" | "neutral"> = {
  done: "ok",
  running: "accent",
  queued: "neutral",
  failed: "danger",
  cancelled: "warn",
};

const KIND_LABEL: Record<string, string> = {
  notes: "Lesson notes",
  diagram: "Diagrams",
  media: "Photos & videos",
  simulation: "Simulations",
  activity: "Activities & experiments",
  questions: "Questions",
  substrands: "Sub-strands",
  review: "Review",
  approval: "Approver",
  ingest: "Read the design",
  strands: "Strands",
  regenerate: "Regeneration",
  pipeline: "Full run",
};

export function QueuePanel({
  grade,
  subject,
  strand,
  defaultKinds = ["notes"],
}: {
  grade: string;
  subject: string;
  strand?: string;
  /** What to preselect. The question bank opens this panel to queue questions,
   *  and preselecting notes there would have the operator regenerate the notes
   *  they came to make questions from. */
  defaultKinds?: string[];
}) {
  const queue = useQueueWork(grade, subject);
  const reviewQueue = useQueueReview(grade, subject);
  const pipeline = useQueuePipeline(grade, subject);
  const regenerate = useQueueRegenerate(grade, subject);
  const [from, setFrom] = React.useState<string>("substrands");
  const cancel = useCancelQueue();
  const retry = useRetryFailed(grade, subject);
  const health = useServerHealth();
  const status = useQueueStatus(grade, subject, queue.data?.batch_id);
  const [kinds, setKinds] = React.useState<string[]>(defaultKinds);

  const data = status.data;
  const outstanding = data ? (data.counts.queued ?? 0) + (data.counts.running ?? 0) : 0;
  const failed = data?.counts.failed ?? 0;

  function toggle(kind: string) {
    setKinds((current) =>
      current.includes(kind) ? current.filter((k) => k !== kind) : [...current, kind]
    );
  }

  return (
    <Card
      title="Queue a run"
      description={
        strand
          ? `Runs the chosen stations for every sub-strand in "${strand}", one at a time.`
          : "Runs the chosen stations for every stored sub-strand in this learning area, one at a time."
      }
      actions={
        <Stack direction="row" gap="var(--s2)" align="center">
          {data?.queue_depth ? (
            <Badge tone="neutral" title="Jobs waiting across the whole queue, not only this learning area">
              {data.queue_depth} waiting
            </Badge>
          ) : null}
          {data?.runs_on === "celery" && (
            <Badge tone="ok" title="Work runs in its own container. A refresh, a navigation or an API restart cannot touch it.">
              background worker
            </Badge>
          )}
          {data?.runs_on === "in_process" && (
            <Badge tone="warn" title="No Celery broker reachable, so jobs run inside the API process and stop if it restarts.">
              in-process fallback
            </Badge>
          )}
          {data?.runs_on === "nothing" && (
            <Badge tone="danger" title="Nothing is running queued work">
              no worker
            </Badge>
          )}
        </Stack>
      }
    >
      <Stack gap="var(--s3)">
        <div
          style={{
            border: "1px solid var(--line)",
            borderRadius: "var(--radius)",
            padding: "var(--s3)",
          }}
        >
          <strong>Run the whole thing</strong>
          <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", margin: "4px 0 var(--s2)" }}>
            Design in, questions out. Each stage fans out from what the stage
            before it saved, so the job count grows as the run proceeds — and
            every generation is reviewed and revised in the worker before it is
            filed. Start it and close the tab.
          </p>
          <Stack direction="row" gap="var(--s2)" align="center" wrap>
            <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              Start at
            </label>
            <select
              aria-label="First step of the run"
              value={from}
              onChange={(e) => setFrom(e.target.value)}
              style={{ padding: "6px 8px", borderRadius: "var(--radius-sm)" }}
            >
              {PIPELINE_STEPS.map((step) => (
                <option key={step} value={step}>
                  {STEP_LABEL[step] || step}
                </option>
              ))}
            </select>
            <Button
              disabled={!subject || pipeline.isPending}
              loading={pipeline.isPending}
              onClick={() =>
                pipeline.mutate({
                  steps: PIPELINE_STEPS.slice(PIPELINE_STEPS.indexOf(from as any)),
                  strand,
                })
              }
            >
              {pipeline.isPending ? "Queuing…" : "Queue the full run"}
            </Button>
          </Stack>
          {pipeline.error && <ErrorNotice error={pipeline.error} />}
          {pipeline.data && (
            <p style={{ fontSize: "var(--text-sm)", margin: "var(--s2) 0 0" }}>
              Started at <strong>{STEP_LABEL[pipeline.data.starting_step]}</strong> with{" "}
              {pipeline.data.queued} job(s). The remaining{" "}
              {pipeline.data.steps.length - 1} stage(s) queue themselves as each one
              finishes.
            </p>
          )}
        </div>

        <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          Or queue single stations:
        </div>
        <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
          {QUEUEABLE_KINDS.map((kind) => (
            <Button
              key={kind}
              size="sm"
              variant={kinds.includes(kind) ? "primary" : "secondary"}
              onClick={() => toggle(kind)}
            >
              {kinds.includes(kind) ? "✓ " : ""}
              {KIND_LABEL[kind] || kind}
            </Button>
          ))}
        </Stack>

        <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", margin: 0 }}>
          Stations run in the order listed: every sub-strand gets its notes before
          any gets diagrams, because the later stations are grounded in the earlier
          ones.
        </p>

        <Stack direction="row" gap="var(--s2)">
          <Button
            disabled={!kinds.length || !subject || queue.isPending}
            loading={queue.isPending}
            onClick={() => queue.mutate({ kinds, strand })}
          >
            {queue.isPending ? "Queuing…" : `Queue ${kinds.length} station(s)`}
          </Button>
          {outstanding > 0 && (
            <Button
              size="sm"
              variant="danger"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate({ batch_id: queue.data?.batch_id })}
              title="Stops what has not started. A running job is left to finish — the tokens are spent either way."
            >
              Cancel {data?.counts.queued ?? 0} not started
            </Button>
          )}
        </Stack>

        <div
          style={{
            borderTop: "1px solid var(--line)",
            paddingTop: "var(--s3)",
            fontSize: "var(--text-sm)",
          }}
        >
          <strong>Then send it for review.</strong>
          <p style={{ color: "var(--ink-3)", margin: "4px 0 var(--s2)" }}>
            The reviewers and the approver are model calls like the generators, and
            take as long. Queued, a grade can be generated and reviewed in one
            sitting and read the next morning. Approval itself stays yours —
            this gets each artifact to the point where that is a decision rather
            than an afternoon.
          </p>
          <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
            <Button
              size="sm"
              variant="secondary"
              disabled={!subject || reviewQueue.isPending}
              loading={reviewQueue.isPending}
              title="Runs an independent second-opinion review over every artifact in this selection"
              onClick={() => reviewQueue.mutate({ work: "review", strand, layer: 2 })}
            >
              Queue independent review
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={!subject || reviewQueue.isPending}
              loading={reviewQueue.isPending}
              title="Runs whatever review layers are missing, then reports what still blocks your sign-off"
              onClick={() => reviewQueue.mutate({ work: "approval", strand })}
            >
              Queue the approver's work
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={!subject || regenerate.isPending}
              loading={regenerate.isPending}
              title="Regenerates every reviewed version whose verdict was revise or reject, carrying the findings into the next version"
              onClick={() => regenerate.mutate({})}
            >
              Queue regeneration from findings
            </Button>
          </Stack>
          {regenerate.error && <ErrorNotice error={regenerate.error} />}
          {regenerate.data && (
            <p style={{ margin: "var(--s2) 0 0" }}>
              {regenerate.data.queued} regeneration(s) queued across{" "}
              {regenerate.data.artifacts} artifact(s).
            </p>
          )}
          {reviewQueue.error && <ErrorNotice error={reviewQueue.error} />}
          {reviewQueue.data && (
            <p style={{ margin: "var(--s2) 0 0" }}>
              {reviewQueue.data.queued} {reviewQueue.data.work} job(s) queued across{" "}
              {reviewQueue.data.artifacts} artifact(s).
            </p>
          )}
        </div>

        {queue.error && <ErrorNotice error={queue.error} />}
        {queue.data && (
          <p style={{ fontSize: "var(--text-sm)", margin: 0 }}>
            {queue.data.queued} job(s) queued across {queue.data.sub_strands} sub-strand(s).
          </p>
        )}

        {data && data.total > 0 && (
          <>
            <ProgressBar
              value={data.percentage}
              height={10}
              label={`${data.finished} of ${data.total} done`}
            />
            <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
              {Object.entries(data.counts).map(([state, count]) => (
                <Badge key={state} tone={STATUS_TONE[state] || "neutral"}>
                  {count} {state}
                </Badge>
              ))}
            </Stack>

            {data.counts_by_kind && Object.keys(data.counts_by_kind).length > 0 && (
              <Table caption="Progress by kind of work">
                <thead>
                  <tr>
                    <Th>Work</Th>
                    <Th numeric>Queued</Th>
                    <Th numeric>Running</Th>
                    <Th numeric>Done</Th>
                    <Th numeric>Failed</Th>
                  </tr>
                </thead>
                <tbody>
                  {Array.from(
                    new Set(
                      Object.keys(data.counts_by_kind).map((k) => k.split(":")[0])
                    )
                  ).map((kind) => {
                    const n = (state: string) =>
                      data.counts_by_kind?.[`${kind}:${state}`] ?? 0;
                    return (
                      <tr key={kind}>
                        <Td>{KIND_LABEL[kind] || kind}</Td>
                        <Td numeric>{n("queued")}</Td>
                        <Td numeric>{n("running")}</Td>
                        <Td numeric>{n("done")}</Td>
                        <Td numeric>{n("failed")}</Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            )}

            {data.now_running && (
              <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", margin: 0 }}>
                Running now: {KIND_LABEL[data.now_running.kind] || data.now_running.kind} for{" "}
                <strong>{data.now_running.sub_strand || data.now_running.strand}</strong>
              </p>
            )}

            {failed > 0 && (
              <div
                style={{
                  border: "1px solid var(--danger)",
                  borderRadius: "var(--radius)",
                  padding: "var(--s3)",
                  fontSize: "var(--text-sm)",
                }}
              >
                <strong>{failed} job(s) failed.</strong> Each was retried once; a job
                that crashes twice will crash a third time, so it is left for you
                rather than retried at cost.
                <div style={{ margin: "var(--s2) 0" }}>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={retry.isPending}
                    loading={retry.isPending}
                    title="Put these back in the queue with a full budget of attempts. Only worth doing once the cause is actually fixed — otherwise they fail again at the same price."
                    onClick={() => retry.mutateAsync({})}
                  >
                    Retry {failed} failed job(s)
                  </Button>
                  {retry.data && (
                    <span style={{ marginLeft: "var(--s2)", color: "var(--ink-3)" }}>
                      {retry.data.retried} requeued.
                    </span>
                  )}
                </div>
                <div style={{ color: "var(--ink-3)" }}>
                  If the failure was a bug that has since been fixed, the API and
                  the worker have to be restarted before a retry runs the new
                  code — otherwise it fails the same way.
                  {health.data && (
                    <div style={{ marginTop: 4 }}>
                      This API started{" "}
                      <strong>
                        {new Date(health.data.started_at).toLocaleString()}
                      </strong>{" "}
                      running generator <code>{health.data.generator}</code>. If
                      that time is older than the fix, restart before retrying.
                    </div>
                  )}
                </div>
                <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em", color: "var(--ink-3)" }}>
                  {data.jobs
                    .filter((j) => j.status === "failed")
                    .slice(0, 5)
                    .map((j) => (
                      <li key={j.job_id}>
                        {KIND_LABEL[j.kind] || j.kind} · {j.sub_strand}: {j.error}
                        {j.failed_under_build && health.data &&
                          j.failed_under_build !== health.data.generator && (
                            <div style={{ color: "var(--warn, var(--ink-3))" }}>
                              This failed under build{" "}
                              <code>{j.failed_under_build}</code>, and the API is
                              now running <code>{health.data.generator}</code> —
                              so it predates the code that is deployed. Retry it.
                            </div>
                          )}
                        {j.failed_under_build && health.data &&
                          j.failed_under_build === health.data.generator && (
                            <div style={{ color: "var(--danger)" }}>
                              This failed under the build that is running now, so
                              it is a live fault rather than a stale row.
                            </div>
                          )}
                      </li>
                    ))}
                </ul>
              </div>
            )}

            <details>
              <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                All {data.jobs.length} job(s)
              </summary>
              <Table caption="Queued work">
                <thead>
                  <tr>
                    <Th>Work</Th>
                    <Th>Sub-strand</Th>
                    <Th numeric>In line</Th>
                    <Th>Status</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.jobs.map((job) => (
                    <tr key={job.job_id}>
                      <Td>
                        {KIND_LABEL[job.kind] || job.kind}
                        {job.step ? ` · ${STEP_LABEL[job.step] || job.step}` : ""}
                      </Td>
                      <Td>{job.sub_strand || job.strand || "—"}</Td>
                      <Td numeric>{job.position ? `#${job.position}` : "—"}</Td>
                      <Td>
                        <Badge tone={STATUS_TONE[job.status] || "neutral"}>{job.status}</Badge>
                        {job.attempts > 1 && <> <Badge tone="warn">retried</Badge></>}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </details>
          </>
        )}

        {data && data.total === 0 && (
          <EmptyState
            title="Nothing queued"
            description="Choose the stations above and queue a run. You can leave the page — the work continues."
          />
        )}
      </Stack>
    </Card>
  );
}
