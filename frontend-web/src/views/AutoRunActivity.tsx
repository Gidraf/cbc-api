import React from "react";

import { Badge, ProgressBar, Stack, Table, Td, Th } from "../ui/components";
import { STEP_LABEL, useAutoRunActivity } from "../lib/queries";

/**
 * What the run is doing, what it produced, and what it has cost.
 *
 * A progress bar answers "how far" and nothing else. The three questions an
 * operator actually has while a grade generates unattended are: what is it
 * doing right now, is what it is producing any good, and how much have I
 * spent. The last was unanswerable until the bill arrived.
 */

function money(usd?: number) {
  if (!usd) return "$0.00";
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

function duration(seconds?: number) {
  const s = Math.round(seconds || 0);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

const STAGE_TONE: Record<string, string> = {
  done: "ok",
  running: "accent",
  queued: "warn",
  failing: "danger",
  not_reached: "neutral",
};

function scoreTone(score?: string, floor = 95) {
  const n = Number(score);
  if (!Number.isFinite(n)) return "neutral" as const;
  if (n >= floor) return "ok" as const;
  if (n >= floor - 15) return "warn" as const;
  return "danger" as const;
}

export function AutoRunActivity({ grade, running }: { grade: string; running: boolean }) {
  const activity = useAutoRunActivity(grade, running);
  const data = activity.data;
  if (!data || !data.run_id) return null;

  const progress = data.progress;
  const spend = data.spend;
  const nowRunning = data.now_running || [];
  const recent = data.recent || [];
  const stages = data.stages || [];
  const subjects = data.subjects || [];

  return (
    <Stack gap="var(--s3)" style={{ marginTop: "var(--s3)" }}>
      {/* ── the three numbers ───────────────────────────────────────────── */}
      <Stack direction="row" gap="var(--s3)" wrap>
        <Figure
          label="Spent so far"
          value={money(spend?.cost_usd)}
          hint={`${(spend?.tokens || 0).toLocaleString()} tokens · ${money(spend?.per_item_usd)} an item`}
          tone="accent"
        />
        <Figure
          label="Done"
          value={`${progress?.finished ?? 0} / ${progress?.total ?? 0}`}
          hint={
            data.pace?.items_per_hour
              ? `${data.pace.items_per_hour}/hour · running ${duration(data.pace.elapsed_seconds)}`
              : "measuring pace…"
          }
        />
        <Figure
          label="Quality"
          value={`${data.recent_median ?? 0}`}
          hint={`median of the recent window · floor ${data.floor ?? 95}`}
          tone={(data.recent_median ?? 0) >= (data.floor ?? 95) ? "ok" : "danger"}
        />
        {progress?.remaining ? (
          <Figure
            label="Left to run, roughly"
            value={money(spend?.projected_remaining_usd)}
            hint={`${progress.remaining} item(s) at the rate so far — an estimate, not a quote`}
            tone="warn"
          />
        ) : null}
      </Stack>

      {progress && progress.total > 0 && (
        <ProgressBar
          value={progress.percentage}
          height={10}
          label={`${progress.finished} of ${progress.total} finished`}
        />
      )}

      {/* The run in the pipeline's own vocabulary. A percentage answers "how
          far" and nothing about WHERE — and an operator watching a grade run
          overnight is asking which stage is slow, not what fraction is done. */}
      {stages.length > 0 && (
        <div>
          <div
            style={{
              fontSize: "var(--text-sm)",
              fontWeight: 550,
              marginBottom: "var(--s2)",
            }}
          >
            Stages
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
              gap: "var(--s2)",
            }}
          >
            {stages.map((st) => {
              const tone = STAGE_TONE[st.status] || "neutral";
              const reached = st.total > 0;
              return (
                <div
                  key={st.stage}
                  title={
                    reached
                      ? `${st.done} done, ${st.running} running, ${st.queued} queued, ${st.failed} failed`
                      : "Not reached yet"
                  }
                  style={{
                    border: `1px solid var(--${tone === "neutral" ? "line" : tone})`,
                    background: reached
                      ? `var(--${tone}-wash, var(--surface-2))`
                      : "transparent",
                    borderRadius: "var(--radius-sm)",
                    padding: "var(--s2)",
                    opacity: reached ? 1 : 0.45,
                  }}
                >
                  <div style={{ fontSize: "var(--text-sm)", fontWeight: 550 }}>
                    {st.label}
                  </div>
                  <div
                    className="mono"
                    style={{ fontSize: "0.75rem", color: "var(--ink-3)" }}
                  >
                    {reached ? `${st.done}/${st.total}` : "—"}
                    {st.failed > 0 && ` · ${st.failed} failed`}
                    {st.running > 0 && ` · ${st.running} now`}
                  </div>
                  <div
                    style={{
                      height: 3,
                      marginTop: 4,
                      borderRadius: 2,
                      background: "var(--line)",
                      overflow: "hidden",
                    }}
                  >
                    <div
                      style={{
                        width: `${st.percentage}%`,
                        height: "100%",
                        background: `var(--${tone === "neutral" ? "ink-3" : tone})`,
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Which branch of this project the run has finished. */}
      {subjects.length > 1 && (
        <Table caption="Subjects">
          <thead>
            <tr>
              <Th>Subject</Th>
              <Th numeric>Done</Th>
              <Th numeric>In flight</Th>
              <Th numeric>Failed</Th>
              <Th numeric>Spent</Th>
            </tr>
          </thead>
          <tbody>
            {subjects.map((s) => (
              <tr key={s.subject}>
                <Td>{s.subject}</Td>
                <Td numeric>
                  {s.done}/{s.total}
                </Td>
                <Td numeric>{s.active || "—"}</Td>
                <Td numeric>
                  {s.failed > 0 ? (
                    <Badge tone="danger">{s.failed}</Badge>
                  ) : (
                    "—"
                  )}
                </Td>
                <Td numeric>{money(s.cost)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}

      {/* ── on the bench right now ──────────────────────────────────────── */}
      {nowRunning.length > 0 && (
        <div
          style={{
            border: "1px solid var(--accent, var(--line))",
            borderRadius: "var(--radius)",
            padding: "var(--s3)",
            fontSize: "var(--text-sm)",
          }}
        >
          <strong>Running now</strong>
          {nowRunning.map((job) => {
            // The steps the worker writes to the job row as it works. Without
            // them "running · 94s" reads the same whether it is thinking or
            // wedged, which is the whole question an operator has at 94s.
            const steps = job.progress?.steps || [];
            return (
              <div key={job.job_id} style={{ marginTop: "var(--s2)" }}>
                <Badge tone="accent">{STEP_LABEL[job.step || job.kind] || job.kind}</Badge>{" "}
                {job.sub_strand || job.strand || job.subject}
                <span style={{ color: "var(--ink-3)" }}>
                  {" "}· {duration(job.seconds)}
                  {job.attempts > 1 ? ` · attempt ${job.attempts}` : ""}
                </span>
                {steps.slice(-4).map((st, i) => (
                  <div
                    key={i}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "3.2rem 1fr",
                      gap: "var(--s2)",
                      marginTop: 2,
                      paddingLeft: "var(--s2)",
                    }}
                  >
                    <span
                      className="mono"
                      style={{ color: "var(--ink-3)", textAlign: "right", fontSize: "0.72rem" }}
                    >
                      {st.at}s
                    </span>
                    <span style={{ color: "var(--ink-2)" }}>
                      <strong
                        style={{
                          color:
                            st.status === "fail"
                              ? "var(--danger)"
                              : st.status === "warn"
                              ? "var(--warn)"
                              : "var(--ink-1)",
                        }}
                      >
                        {st.step}
                      </strong>
                      {st.detail ? ` — ${st.detail}` : ""}
                      {i === Math.min(steps.length, 4) - 1 && (
                        <span style={{ color: "var(--ink-3)" }}> …</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}

      {/* ── what it has produced, newest first ──────────────────────────── */}
      {recent.length > 0 && (
        <details open>
          <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)", fontWeight: 600 }}>
            What it has produced ({recent.length} most recent)
          </summary>
          <Table caption="Finished items, newest first">
            <thead>
              <tr>
                <Th>Step</Th>
                <Th>Item</Th>
                <Th numeric>Score</Th>
                <Th>Weakest</Th>
                <Th numeric>Cost</Th>
              </tr>
            </thead>
            <tbody>
              {recent.map((job) => (
                <tr key={job.job_id}>
                  <Td>{STEP_LABEL[job.step || job.kind] || job.kind}</Td>
                  <Td>
                    {job.sub_strand || job.strand || job.subject}
                    {job.status === "failed" && (
                      <div style={{ color: "var(--danger)", fontSize: "var(--text-sm)" }}>
                        failed: {job.error}
                      </div>
                    )}
                    {job.cycles && Number(job.cycles) > 1 && (
                      <span style={{ color: "var(--ink-3)" }}> · {job.cycles} cycles</span>
                    )}
                  </Td>
                  <Td numeric>
                    {job.score ? (
                      <Badge tone={scoreTone(job.score, data.floor)}>{job.score}</Badge>
                    ) : (
                      "—"
                    )}
                  </Td>
                  <Td style={{ color: "var(--ink-3)" }}>
                    {String(job.weakest || "—").replace(/_/g, " ")}
                  </Td>
                  <Td numeric>{money(Number(job.cost_usd || 0))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </details>
      )}

      {/* ── where the money went ────────────────────────────────────────── */}
      {spend && spend.by_station?.length > 0 && (
        <details>
          <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            Where the money went
          </summary>
          <Table caption="Spend by station">
            <thead>
              <tr>
                <Th>Station</Th>
                <Th numeric>Items</Th>
                <Th numeric>Calls</Th>
                <Th numeric>Tokens</Th>
                <Th numeric>Cost</Th>
              </tr>
            </thead>
            <tbody>
              {spend.by_station.map((row) => (
                <tr key={row.kind}>
                  <Td>{STEP_LABEL[row.kind] || row.kind}</Td>
                  <Td numeric>{row.jobs}</Td>
                  <Td numeric>{row.calls ?? 0}</Td>
                  <Td numeric>{(row.tokens ?? 0).toLocaleString()}</Td>
                  <Td numeric>{money(Number(row.cost || 0))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </details>
      )}
    </Stack>
  );
}

function Figure({
  label, value, hint, tone,
}: {
  label: string; value: string; hint?: string;
  tone?: "ok" | "warn" | "danger" | "accent";
}) {
  const colour =
    tone === "ok" ? "var(--ok, var(--ink-1))"
      : tone === "danger" ? "var(--danger)"
      : tone === "warn" ? "var(--warn, var(--ink-1))"
      : "var(--ink-1)";
  return (
    <div
      style={{
        flex: "1 1 10rem",
        minWidth: "10rem",
        border: "1px solid var(--line)",
        borderRadius: "var(--radius)",
        padding: "var(--s3)",
      }}
    >
      <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>{label}</div>
      <div style={{ fontSize: "1.6rem", fontWeight: 600, color: colour, lineHeight: 1.2 }}>
        {value}
      </div>
      {hint && (
        <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)", marginTop: 2 }}>
          {hint}
        </div>
      )}
    </div>
  );
}
