import React from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Grid,
  PageHeader,
  QueryState,
  Stack,
  Stat,
  Table,
  Td,
  Th,
} from "../ui/components";
import {
  useAgentTasks,
  useCancelAgentTask,
  type AgentLedgerRow,
  type AgentTask,
  type AgentTaskProgress,
} from "../lib/queries";

/**
 * What outside agents (Antigravity, Claude Code, Codex, Ollama) are doing
 * on this platform right now, and what they did. A task is one station
 * driven by an agent's own model; an order is a whole paper. Each is hours
 * of prompts, and until now the only window on it was the agent's chat.
 */
export function AgentTasks() {
  const tasks = useAgentTasks();
  const cancel = useCancelAgentTask();
  const live = tasks.data?.live ?? [];
  const ledger = tasks.data?.ledger ?? [];
  const awaiting = live.filter((t) => t.status === "awaiting");
  const running = live.filter((t) => t.status === "running");

  return (
    <>
      <PageHeader
        eyebrow="Operate"
        title="Agent tasks"
        description="Stations driven by an outside agent's model — the platform hands out the prompts, the agent answers them. A task waiting on the agent shows what it is waiting for; an order shows how far through the paper it is."
      />
      <QueryState query={tasks} label="Loading agent tasks" rows={3} />
      {cancel.error && <ErrorNotice error={cancel.error} />}

      {tasks.data && (
        <Grid min="12rem">
          <Stat label="Live tasks" value={live.length}
                sub={live.length ? `${awaiting.length} waiting on the agent · ${running.length} working` : "nothing running"}
                tone={live.length ? "accent" : undefined} />
          <Stat label="Waiting longest"
                value={awaiting.length ? ago(Math.min(...awaiting.map((t) => t.step ? (tail(t.history)?.answered_at ?? t.created_at) : t.created_at))) : "—"}
                sub={awaiting.length ? "since the last answer — a step unanswered for 45 min fails the task" : undefined}
                tone={awaiting.length && oldestWait(awaiting) > 20 * 60 ? "warn" : undefined} />
          <Stat label="Finished today"
                value={ledger.filter((r) => isToday(r.finished_at)).length}
                sub={`${ledger.filter((r) => isToday(r.finished_at) && r.status === "done").length} done · ${ledger.filter((r) => isToday(r.finished_at) && r.status !== "done").length} failed or cancelled`} />
        </Grid>
      )}

      {live.length > 0 && (
        <Card title="Live" description="Newest first. Cancel stops a task at its next prompt; what it already wrote stays in the bank.">
          <Stack gap="var(--s3)">
            {live.map((t) => (
              <LiveTask key={t.task_id} task={t} busy={cancel.isPending}
                        onCancel={() => {
                          if (window.confirm(`Cancel ${t.task_id}? Guides and questions it already filed are kept.`))
                            cancel.mutate(t.task_id);
                        }} />
            ))}
          </Stack>
        </Card>
      )}

      {tasks.data && live.length === 0 && (
        <EmptyState title="No agent is working right now"
                    description="Ask your agent for a paper — it starts an order here." />
      )}

      {ledger.length > 0 && (
        <Card title="Ledger" description="The last hundred finished tasks. A failed order names the sub-strand it died on.">
          <Table>
            <thead>
              <tr>
                <Th>When</Th><Th>Station</Th><Th>Scope</Th><Th>By</Th><Th>Steps</Th><Th>Model</Th><Th>Outcome</Th>
              </tr>
            </thead>
            <tbody>
              {ledger.map((r) => <LedgerRow key={r.task_id} row={r} />)}
            </tbody>
          </Table>
        </Card>
      )}
    </>
  );
}

function LiveTask({ task, busy, onCancel }: { task: AgentTask; busy: boolean; onCancel: () => void }) {
  const [open, setOpen] = React.useState(false);
  const last = tail(task.history);
  const waitingSince = task.status === "awaiting" ? (last?.answered_at ?? task.created_at) : null;
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "var(--s3)" }}>
      <Stack gap="var(--s2)">
        <Stack direction="row" gap="var(--s2)" align="center" wrap>
          <Badge tone={task.status === "awaiting" ? "warn" : "accent"}>{task.status}</Badge>
          <b>{scope(task.station, task.params)}</b>
          <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
            {task.task_id} · by {task.created_by} · {task.steps_completed} step{task.steps_completed === 1 ? "" : "s"} answered
            {task.replayed > 0 && ` (${task.replayed} replayed)`} · running {duration(task.elapsed_seconds)}
            {task.joined > 0 && ` · joined ${task.joined}×`}
          </span>
          <span style={{ flex: 1 }} />
          <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)}>{open ? "Hide" : "Details"}</Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={onCancel} style={{ color: "var(--danger)" }}>Cancel</Button>
        </Stack>
        {task.status === "awaiting" && task.step && (
          <div style={{ fontSize: "var(--text-sm)" }}>
            Waiting on the agent for step <b>{task.step.number}</b> ({task.step.stage.replace(/_/g, " ")})
            {waitingSince != null && <> — asked {ago(waitingSince)}</>}
            {waitingSince != null && nowSeconds() - waitingSince > 20 * 60 && (
              <span style={{ color: "var(--warn)" }}> · the agent has gone quiet; a step unanswered for 45 min fails the task</span>
            )}
          </div>
        )}
        {task.status === "running" && (
          <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            The platform is working (checks, figures, composing) — no prompt pending.
          </div>
        )}
        {task.progress.length > 0 && <ProgressLine notes={task.progress} />}
        {open && (
          <Stack gap="var(--s2)">
            {task.progress.length > 0 && <ProgressList notes={task.progress} />}
            {task.history.length > 0 && (
              <Table>
                <thead><tr><Th>#</Th><Th>Stage</Th><Th>Answered by</Th><Th>Took</Th><Th>Answer</Th></tr></thead>
                <tbody>
                  {task.history.slice(-30).map((s) => (
                    <tr key={s.number}>
                      <Td>{s.number}</Td>
                      <Td>{s.stage.replace(/_/g, " ")}</Td>
                      <Td>{s.model_used || "—"}</Td>
                      <Td>{s.asked_at && s.answered_at ? duration(s.answered_at - s.asked_at) : "—"}</Td>
                      <Td>{s.chars != null ? `${s.chars.toLocaleString()} chars` : "—"}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Stack>
        )}
      </Stack>
    </div>
  );
}

function LedgerRow({ row }: { row: AgentLedgerRow }) {
  const [open, setOpen] = React.useState(false);
  const urls = row.result?.render_urls || null;
  const progress = row.result?.progress || [];
  const tone = row.status === "done" ? "ok" : row.status === "cancelled" ? "warn" : "danger";
  return (
    <>
      <tr>
        <Td>{when(row.created_at)}</Td>
        <Td>{row.station}</Td>
        <Td>{scope(row.station, row.params)}</Td>
        <Td>{row.created_by}</Td>
        <Td>{row.steps}</Td>
        <Td style={{ maxWidth: "12rem", overflow: "hidden", textOverflow: "ellipsis" }}>{row.model_used || "—"}</Td>
        <Td>
          <Stack direction="row" gap="var(--s2)" align="center" wrap>
            <Badge tone={tone}>{row.status}</Badge>
            {urls?.print && <a href={urls.print} target="_blank" rel="noreferrer">paper</a>}
            {urls?.scheme && <a href={urls.scheme} target="_blank" rel="noreferrer">scheme</a>}
            {(row.error || progress.length > 0) && (
              <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)}>{open ? "Hide" : "Why"}</Button>
            )}
          </Stack>
        </Td>
      </tr>
      {open && (
        <tr>
          <Td colSpan={7}>
            <Stack gap="var(--s2)">
              {row.error && <div style={{ color: "var(--danger)", fontSize: "var(--text-sm)" }}>{row.error}</div>}
              {progress.length > 0 && <ProgressList notes={progress} />}
            </Stack>
          </Td>
        </tr>
      )}
    </>
  );
}

function ProgressLine({ notes }: { notes: AgentTaskProgress[] }) {
  const last = tail(notes)!;
  const done = notes.filter((n) => n.status === "skip").length;
  return (
    <div style={{ fontSize: "var(--text-sm)" }}>
      <b>{last.what}</b> — {last.detail}
      {done > 0 && <span style={{ color: "var(--ink-3)" }}> · {done} step{done === 1 ? "" : "s"} skipped as already filed</span>}
    </div>
  );
}

function ProgressList({ notes }: { notes: AgentTaskProgress[] }) {
  return (
    <ol style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "var(--text-sm)" }}>
      {notes.map((n, i) => (
        <li key={i} style={{ color: n.status === "warn" ? "var(--warn)" : n.status === "skip" ? "var(--ink-3)" : undefined }}>
          <b>{n.what}</b> — {n.detail}{n.status === "skip" && " (skipped)"}
        </li>
      ))}
    </ol>
  );
}

function scope(station: string, p: Record<string, any>): string {
  const bits = [p.grade, p.subject, p.kind === "term" && p.term ? `Term ${p.term}` : p.kind, p.sub_strand || p.strand]
    .filter(Boolean);
  return `${station}: ${bits.join(" · ")}`;
}

function tail<T>(xs: T[]): T | undefined { return xs[xs.length - 1]; }
function nowSeconds() { return Date.now() / 1000; }
function oldestWait(tasks: AgentTask[]) {
  return Math.max(...tasks.map((t) => nowSeconds() - (tail(t.history)?.answered_at ?? t.created_at)));
}
function ago(epoch: number) {
  return `${duration(nowSeconds() - epoch)} ago`;
}
function duration(s: number) {
  s = Math.max(0, Math.round(s));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}
function when(iso: string) {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function isToday(iso: string | null) {
  if (!iso) return false;
  const d = new Date(iso), n = new Date();
  return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
}
