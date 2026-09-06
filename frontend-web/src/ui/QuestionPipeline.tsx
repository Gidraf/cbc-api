import React from "react";
import { Badge, Button, ErrorNotice, LoadingBlock, Stack } from "./components";
import {
  useQuestionStructure,
  useQuestionThroughput,
  useSetQuestionTarget,
} from "../lib/queries";

/**
 * The question factory as a funnel, not as a list.
 *
 * Three separate daily rates that only balance over weeks: what a machine can
 * write, what a person can actually read, and what somebody will put their
 * name to. Showing them as three numbers invites reading them as a ratio; the
 * useful picture is the funnel with the QUEUES between the stages drawn in,
 * because the number that kills this operation is not "we generated 400
 * today" — it is "3,000 are waiting to be read and nobody noticed".
 */

const STAGE_LABEL: Record<string, string> = {
  generated: "Written",
  reviewed: "Read",
  approved: "Signed for",
};

function Funnel({
  stages,
  awaitingReview,
  awaitingApproval,
  blocked,
}: {
  stages: Array<{ stage: string; done: number; target: number; share: number; short_by: number }>;
  awaitingReview: number;
  awaitingApproval: number;
  blocked: number;
}) {
  // Widths are proportional to the TARGETS, so the funnel narrows the way the
  // operation is meant to. The fill inside each is the day's progress.
  const widest = Math.max(...stages.map((s) => s.target || 1), 1);
  const queues = [null, awaitingReview, awaitingApproval];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {stages.map((s, i) => {
        const width = Math.max(18, ((s.target || 1) / widest) * 100);
        const met = s.target > 0 && s.done >= s.target;
        const queue = queues[i];
        return (
          <React.Fragment key={s.stage}>
            {queue !== null && queue !== undefined && (
              <div style={{ display: "flex", justifyContent: "center", padding: "2px 0" }}>
                <span
                  style={{
                    fontSize: "var(--text-xs)",
                    color: queue > (stages[i]?.target || 0) * 5 ? "var(--danger, #a1281e)" : "var(--ink-2)",
                    fontVariantNumeric: "tabular-nums",
                  }}
                  title="Waiting between these two stages"
                >
                  ↓ {queue.toLocaleString()} waiting
                </span>
              </div>
            )}
            <div style={{ display: "flex", justifyContent: "center" }}>
              <div
                style={{
                  width: `${width}%`,
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)",
                  overflow: "hidden",
                  background: "var(--surface-2)",
                  position: "relative",
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    inset: 0,
                    width: `${s.share}%`,
                    background: met ? "var(--ok-bg, #d8efe1)" : "var(--accent-bg, #dbe7f6)",
                    transition: "width 300ms ease",
                  }}
                />
                <div
                  style={{
                    position: "relative",
                    padding: "10px 12px",
                    display: "flex",
                    alignItems: "baseline",
                    gap: "var(--s2)",
                    flexWrap: "wrap",
                  }}
                >
                  <strong style={{ fontSize: "var(--text-sm)" }}>
                    {STAGE_LABEL[s.stage] || s.stage}
                  </strong>
                  <span style={{ fontVariantNumeric: "tabular-nums", fontSize: "var(--text-sm)" }}>
                    {s.done.toLocaleString()} / {s.target.toLocaleString()}
                  </span>
                  <span style={{ marginLeft: "auto", fontSize: "var(--text-xs)", color: "var(--ink-2)" }}>
                    {met ? "target met" : `${s.short_by.toLocaleString()} short`}
                  </span>
                </div>
              </div>
            </div>
          </React.Fragment>
        );
      })}
      {blocked > 0 && (
        <div style={{ textAlign: "center", marginTop: "var(--s2)", fontSize: "var(--text-xs)", color: "var(--ink-2)" }}>
          {blocked.toLocaleString()} held by the structure gate today — never reached a reviewer
        </div>
      )}
    </div>
  );
}

function History({
  rows,
}: {
  rows: Array<{ on: string; generated: number; reviewed: number; approved: number }>;
}) {
  if (!rows.length) return null;
  // Whether the queue is GROWING is the only question this chart answers, so
  // written and read are drawn against each other rather than separately.
  const peak = Math.max(1, ...rows.map((r) => Math.max(r.generated, r.reviewed, r.approved)));
  return (
    <div style={{ marginTop: "var(--s3)" }}>
      <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)", marginBottom: "var(--s1)" }}>
        Written against read, last {rows.length} day{rows.length === 1 ? "" : "s"}
      </div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 3, height: 74 }}>
        {rows.map((r) => (
          <div
            key={r.on}
            title={`${r.on} — ${r.generated} written, ${r.reviewed} read, ${r.approved} signed`}
            style={{ flex: 1, display: "flex", alignItems: "flex-end", gap: 1, height: "100%" }}
          >
            <div style={{ flex: 1, height: `${(r.generated / peak) * 100}%`, background: "var(--accent-bg, #dbe7f6)", minHeight: 1 }} />
            <div style={{ flex: 1, height: `${(r.reviewed / peak) * 100}%`, background: "var(--ink-2)", opacity: 0.55, minHeight: 1 }} />
            <div style={{ flex: 1, height: `${(r.approved / peak) * 100}%`, background: "var(--ok, #1b6b3a)", minHeight: 1 }} />
          </div>
        ))}
      </div>
    </div>
  );
}

export function QuestionPipeline({
  grade,
  subject,
  strand,
  subStrand,
}: {
  grade: string;
  subject: string;
  strand?: string;
  subStrand?: string;
}) {
  const board = useQuestionThroughput({ grade, subject, strand });
  const structure = useQuestionStructure({ grade, subject, sub_strand: subStrand });
  const setTarget = useSetQuestionTarget();
  const [editing, setEditing] = React.useState(false);
  const [plan, setPlan] = React.useState({ generate: 500, review: 250, approve: 50 });

  React.useEffect(() => {
    const t = board.data?.target;
    if (t) setPlan({ generate: t.generate_per_day, review: t.review_per_day, approve: t.approve_per_day });
  }, [board.data?.target]);

  if (board.isPending) return <LoadingBlock rows={3} label="Reading today's numbers" />;
  if (board.isError) return <ErrorNotice error={board.error} />;
  const data = board.data!;

  return (
    <Stack gap="var(--s3)" style={{ marginTop: "var(--s3)" }}>
      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: "var(--text-sm)" }}>Today&rsquo;s pipeline</strong>
        <Badge tone="neutral">{data.on}</Badge>
        <Button size="sm" variant="ghost" onClick={() => setEditing(!editing)}>
          {editing ? "Cancel" : "Set the day's plan"}
        </Button>
      </Stack>

      {editing && (
        <Stack direction="row" gap="var(--s2)" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
          {(["generate", "review", "approve"] as const).map((k) => (
            <label key={k} style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)" }}>
              <div style={{ marginBottom: 2 }}>{k} / day</div>
              <input
                type="number"
                min={0}
                value={plan[k]}
                onChange={(e) => setPlan({ ...plan, [k]: Number(e.target.value) })}
                style={{
                  width: 90, padding: "5px 7px", borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--line)", background: "var(--surface-2)",
                  color: "var(--ink-1)",
                }}
              />
            </label>
          ))}
          <Button
            size="sm"
            loading={setTarget.isPending}
            onClick={() =>
              setTarget
                .mutateAsync({
                  grade, subject, strand: strand || "",
                  generate_per_day: plan.generate,
                  review_per_day: plan.review,
                  approve_per_day: plan.approve,
                })
                .then(() => setEditing(false))
            }
          >
            Save the plan
          </Button>
          {setTarget.error && <ErrorNotice error={setTarget.error} />}
        </Stack>
      )}

      <Funnel
        stages={data.stages}
        awaitingReview={data.awaiting_review}
        awaitingApproval={data.awaiting_approval}
        blocked={data.blocked_today}
      />

      {data.warnings.map((w, i) => (
        <div
          key={i}
          style={{
            padding: "var(--s2)", fontSize: "var(--text-sm)",
            background: "var(--warn-bg, #fff8e6)", borderRadius: "var(--radius-sm)",
          }}
        >
          {w}
        </div>
      ))}

      <History rows={data.history} />

      {/* The funnel is a DAY. This is the whole grade, which is the number
          that says whether there is a product to sell. 500 written is a good
          day and still 3% of a curriculum. */}
      {data.coverage && data.coverage.substrands > 0 && (
        <div
          style={{
            border: "1px solid var(--line)", borderRadius: "var(--radius-sm)",
            padding: "var(--s3)",
          }}
        >
          <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ fontSize: "var(--text-sm)" }}>Curriculum produced</strong>
            <Badge tone={data.coverage.percentage >= 80 ? "ok" : "warn"}>
              {data.coverage.percentage}%
            </Badge>
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              {data.coverage.measured} of {data.coverage.substrands} sub-strands have
              anything filed
            </span>
          </Stack>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
              gap: "var(--s2)", marginTop: "var(--s2)",
            }}
          >
            {Object.entries(data.coverage.dimensions).map(([name, d]) => (
              <div key={name} title={d.says}>
                <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)", textTransform: "capitalize" }}>
                  {name}
                  {d.estimated && " · est."}
                </div>
                <div style={{ fontSize: "var(--text-sm)", fontVariantNumeric: "tabular-nums" }}>
                  {d.generated.toLocaleString()} / {d.required.toLocaleString()}
                  {d.remaining > 0 && (
                    <span style={{ color: "var(--ink-2)" }}> · {d.remaining.toLocaleString()} left</span>
                  )}
                </div>
                <div style={{ height: 3, marginTop: 3, borderRadius: 2, background: "var(--line)", overflow: "hidden" }}>
                  <div style={{ width: `${d.percentage}%`, height: "100%", background: "var(--ok, #1b6b3a)" }} />
                </div>
              </div>
            ))}
          </div>
          {(data.coverage.unmatched_generations || []).map((line, i) => (
            <div key={i} style={{ marginTop: "var(--s2)", fontSize: "var(--text-sm)", color: "var(--ink-2)", whiteSpace: "pre-wrap" }}>
              {line}
            </div>
          ))}
        </div>
      )}

      {/* The gate, as a number an operator can act on. Items held here never
          reached a reviewer, so they are invisible everywhere else. */}
      {structure.data && structure.data.total > 0 && (
        <div
          style={{
            border: "1px solid var(--line)", borderRadius: "var(--radius-sm)",
            padding: "var(--s3)",
          }}
        >
          <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ fontSize: "var(--text-sm)" }}>Structure of what is filed</strong>
            <Badge tone={structure.data.blocked ? "warn" : "ok"}>
              {structure.data.clean} of {structure.data.total} clean
            </Badge>
            {structure.data.blocked > 0 && (
              <Badge tone="warn">{structure.data.blocked} would be held</Badge>
            )}
          </Stack>
          {Object.keys(structure.data.by_finding).length > 0 && (
            <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "1.1rem", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              {Object.entries(structure.data.by_finding).slice(0, 6).map(([code, n]) => (
                <li key={code}>
                  <b>{n}</b> × {code.replace(/_/g, " ")}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Stack>
  );
}
