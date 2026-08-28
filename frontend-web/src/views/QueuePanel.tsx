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
  QUEUEABLE_KINDS,
  useCancelQueue,
  useQueueStatus,
  useQueueWork,
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
  activity: "Activities",
};

export function QueuePanel({
  grade,
  subject,
  strand,
}: {
  grade: string;
  subject: string;
  strand?: string;
}) {
  const queue = useQueueWork(grade, subject);
  const cancel = useCancelQueue();
  const status = useQueueStatus(grade, subject, queue.data?.batch_id);
  const [kinds, setKinds] = React.useState<string[]>(["notes"]);

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
        data?.worker_running === false && (
          <Badge tone="danger" title="Queued work will not run until the API restarts">
            worker stopped
          </Badge>
        )
      }
    >
      <Stack gap="var(--s3)">
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

            {data.now_running && (
              <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", margin: 0 }}>
                Running now: {KIND_LABEL[data.now_running.kind] || data.now_running.kind} for{" "}
                <strong>{data.now_running.sub_strand}</strong>
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
                <ul style={{ margin: "6px 0 0", paddingLeft: "1.1em", color: "var(--ink-3)" }}>
                  {data.jobs
                    .filter((j) => j.status === "failed")
                    .slice(0, 5)
                    .map((j) => (
                      <li key={j.job_id}>
                        {KIND_LABEL[j.kind] || j.kind} · {j.sub_strand}: {j.error}
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
                    <Th>Station</Th>
                    <Th>Sub-strand</Th>
                    <Th>Status</Th>
                  </tr>
                </thead>
                <tbody>
                  {data.jobs.map((job) => (
                    <tr key={job.job_id}>
                      <Td>{KIND_LABEL[job.kind] || job.kind}</Td>
                      <Td>{job.sub_strand || job.strand || "—"}</Td>
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
