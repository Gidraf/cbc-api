import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  Field,
  Input,
  LoadingBlock,
  PageHeader,
  Select,
  Stack,
  Table,
  Td,
  Textarea,
  Th,
} from "../ui/components";
import { AutoRunActivity } from "./AutoRunActivity";
import { PromptFragments } from "./PromptFragments";
import { AutoRunPanel } from "./AutoRunPanel";
import {
  usePipeline,
  usePipelines,
  useStageAction,
  useStageLogs,
  useStageRequirements,
  useStagePolicies,
  useStageUnits,
  type BoardBranch,
  type BoardRun,
  type BoardStage,
  type AssetRequirement,
  type StagePolicy,
  type StageUnit,
} from "../lib/queries";

/**
 * The pipeline board.
 *
 * Everything needed to answer "where is this grade?" existed and was spread
 * across five screens: coverage said what percentage was generated, the queue
 * said what was running, the artifact list said what versions existed, the
 * review panel said what one version scored. None of them said, for one grade,
 * which stage of which subject is holding everything else up.
 *
 * The shape people already know for this is a build board, so this is one:
 * a GRADE is the project, a SUBJECT is a branch of it, a STAGE is a build step,
 * and the reviewers are that step's tests.
 *
 * Read top-down. A subject is only as far along as its earliest unfinished
 * stage, because that is what is actually blocking it — a board showing ten
 * reds tells you ten things when one of them caused the other nine.
 */

// The stations that build FROM the plan, and so have something the plan can
// have asked them for.
const STATION_STAGES = new Set(["diagram", "media", "simulation", "activity"]);

const TONE: Record<string, "ok" | "warn" | "danger" | "accent" | "neutral"> = {
  approved: "ok",
  reviewed: "accent",
  built: "warn",
  running: "accent",
  failing: "danger",
  blocked: "neutral",
  not_started: "neutral",
};

const WORDS: Record<string, string> = {
  approved: "approved",
  reviewed: "awaiting sign-off",
  built: "built, not through the gate",
  running: "running",
  failing: "failing",
  blocked: "waiting upstream",
  not_started: "not started",
};

function StageCell({ stage, onOpen }: { stage: BoardStage; onOpen: () => void }) {
  const tone = TONE[stage.status] || "neutral";
  return (
    <button
      onClick={onOpen}
      title={stage.blocked_by || `${stage.label} — ${WORDS[stage.status]}`}
      style={{
        display: "block",
        width: "100%",
        textAlign: "left",
        cursor: "pointer",
        background: `var(--${tone}-wash, var(--surface-2))`,
        border: `1px solid var(--${tone === "neutral" ? "line" : tone})`,
        borderRadius: "var(--radius-sm)",
        padding: "var(--s2)",
        font: "inherit",
        color: "inherit",
      }}
    >
      <div style={{ fontSize: "var(--text-sm)", fontWeight: 550 }}>{stage.label}</div>
      <div className="mono" style={{ fontSize: "0.75rem", color: "var(--ink-3)" }}>
        {stage.expected ? `${stage.built}/${stage.expected}` : stage.built || "—"}
        {stage.failed > 0 && ` · ${stage.failed} failed`}
        {stage.running > 0 && ` · ${stage.running} running`}
      </div>
      {/* The bar is the only thing scannable across a row of ten stages. */}
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
            width: `${stage.percentage}%`,
            height: "100%",
            background: `var(--${tone === "neutral" ? "ink-3" : tone})`,
          }}
        />
      </div>
    </button>
  );
}

/**
 * What this stage's jobs did, newest first, with the steps each one wrote.
 *
 * A stage that says "2 failed" and cannot say what failed is a red light with
 * no wiring behind it. The worker already writes its steps to the job row as it
 * works, so a run in flight narrates itself here and a finished one keeps the
 * narration.
 */
function StageLog({
  grade,
  stage,
  subject,
}: {
  grade: string;
  stage: string;
  subject: string;
}) {
  const logs = useStageLogs(grade, stage, subject, true);
  const [open, setOpen] = React.useState<string>("");

  if (logs.isLoading) return <LoadingBlock rows={3} label="Loading the log" />;
  if (logs.isError) return <ErrorNotice error={logs.error} />;

  const runs = logs.data?.runs || [];
  if (!runs.length) {
    return (
      <p style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
        This stage has not run for {subject} yet.
      </p>
    );
  }

  return (
    <div style={{ marginTop: "var(--s3)" }}>
      {runs.map((r: BoardRun) => {
        const steps = r.progress?.steps || [];
        const tone =
          r.status === "failed" ? "danger" : r.status === "done" ? "ok" : "accent";
        return (
          <div
            key={r.job_id}
            style={{
              borderTop: "1px solid var(--line)",
              padding: "var(--s2) 0",
              fontSize: "var(--text-sm)",
            }}
          >
            <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
              <Badge tone={tone as any}>{r.status}</Badge>
              <strong>{r.sub_strand || r.strand || subject}</strong>
              {r.attempts > 1 && (
                <span style={{ color: "var(--ink-3)" }}>attempt {r.attempts}</span>
              )}
              <span className="mono" style={{ color: "var(--ink-3)", fontSize: "0.75rem" }}>
                {r.llm_calls > 0 && `${r.llm_calls} call(s) · $${Number(r.cost_usd).toFixed(4)}`}
              </span>
              {steps.length > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setOpen(open === r.job_id ? "" : r.job_id)}
                >
                  {open === r.job_id ? "Hide steps" : `${steps.length} steps`}
                </Button>
              )}
            </Stack>

            {/* A failure with no reason is the same red light again. */}
            {r.error && (
              <p style={{ margin: "4px 0 0", color: "var(--danger)" }}>{r.error}</p>
            )}

            {open === r.job_id && (
              <div style={{ marginTop: "var(--s2)", display: "grid", gap: 2 }}>
                {steps.map((st, i) => (
                  <div
                    key={i}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "3.5rem 1fr",
                      gap: "var(--s2)",
                      alignItems: "baseline",
                    }}
                  >
                    <span
                      className="mono"
                      style={{ color: "var(--ink-3)", textAlign: "right", fontSize: "0.75rem" }}
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
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}


/**
 * The individual versions at a stage, and what each still needs.
 *
 * A stage that says "5 of 7 not reviewed" and cannot say WHICH five leaves a
 * person to go and find them, which is the work the board was supposed to
 * remove. Selecting some and signing for them is the same gate as approving
 * one — a version that cannot be approved is reported here rather than quietly
 * left out, because a bulk action that silently does less than it says is worse
 * than one that refuses.
 */
/**
 * What the lesson plans ask this station for, in their own words.
 *
 * The plan already names its assets — "visual aids for gestures", "observe
 * pictures of Adam and Eve". Nothing was reading them: each asset station was
 * given the sub-strand's title and outcomes and asked to plan from scratch. So
 * an asset the plan asked for was never guaranteed to exist, and one it never
 * mentioned could be produced, reviewed on its own terms and approved.
 */
function StageRequirements({
  grade,
  subject,
  station,
}: {
  grade: string;
  subject: string;
  station: string;
}) {
  const wanted = useStageRequirements(grade, subject, station, true);

  if (wanted.isLoading) return <LoadingBlock rows={3} label="Reading the plans" />;
  if (wanted.isError) return <ErrorNotice error={wanted.error} />;

  const items = wanted.data?.items || [];
  if (!wanted.data?.plans_read) {
    return (
      <p style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
        No lesson plan is filed yet, so nothing has asked for anything. This
        station plans from the plan.
      </p>
    );
  }
  if (!items.length) {
    return (
      <p style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
        Read {wanted.data.plans_read} plan(s); none of them asks this station
        for anything. It will plan from what each lesson teaches instead.
      </p>
    );
  }

  const byLesson = new Map<string, AssetRequirement[]>();
  for (const item of items) {
    const key = item.module_title;
    byLesson.set(key, [...(byLesson.get(key) || []), item]);
  }

  return (
    <div style={{ marginTop: "var(--s3)" }}>
      <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", margin: "0 0 var(--s2)" }}>
        <strong>{items.length}</strong> asked for across{" "}
        {wanted.data.plans_read} plan(s).{" "}
        {Object.entries(wanted.data.by_kind || {})
          .map(([k, n]) => `${n} ${k}`)
          .join(" · ")}
      </p>
      <div style={{ maxHeight: 260, overflow: "auto" }}>
        {[...byLesson.entries()].map(([lesson, rows]) => (
          <div key={lesson} style={{ marginBottom: "var(--s2)" }}>
            <div style={{ fontSize: "var(--text-sm)", fontWeight: 550 }}>{lesson}</div>
            <ul style={{ margin: "2px 0 0", paddingLeft: "1.2rem", fontSize: "var(--text-sm)" }}>
              {rows.map((r, i) => (
                <li key={i} style={{ color: "var(--ink-2)" }}>
                  <Badge tone="neutral">{r.kind}</Badge> {r.what}
                  {r.topic && (
                    <span style={{ color: "var(--ink-3)" }}> — in “{r.topic}”</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}


function StageUnits({
  grade,
  stage,
  subject,
}: {
  grade: string;
  stage: string;
  subject: string;
}) {
  const units = useStageUnits(grade, stage, subject, true);
  const { approve } = useStageAction();
  const [picked, setPicked] = React.useState<string[]>([]);
  const [note, setNote] = React.useState("");
  const [signing, setSigning] = React.useState(false);

  if (units.isLoading) return <LoadingBlock rows={3} label="Loading the versions" />;
  if (units.isError) return <ErrorNotice error={units.error} />;

  const rows = units.data?.units || [];
  if (units.data?.note) {
    return (
      <p style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
        {units.data.note}
      </p>
    );
  }
  if (!rows.length) {
    return (
      <p style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
        Nothing filed at this stage yet.
      </p>
    );
  }

  const ready = rows.filter((u) => u.can_approve).map((u) => u.artifact_id);
  const toggle = (id: string) =>
    setPicked(picked.includes(id) ? picked.filter((p) => p !== id) : [...picked, id]);

  return (
    <div style={{ marginTop: "var(--s3)" }}>
      <Table caption="Versions at this stage">
        <thead>
          <tr>
            <Th />
            <Th>Sub-strand</Th>
            <Th numeric>Version</Th>
            <Th>Layers</Th>
            <Th>Latest verdict</Th>
            <Th>What it still needs</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {rows.map((u: StageUnit) => (
            <tr key={u.artifact_id}>
              <Td>
                <input
                  type="checkbox"
                  checked={picked.includes(u.artifact_id)}
                  disabled={!u.can_approve}
                  onChange={() => toggle(u.artifact_id)}
                  title={u.can_approve ? "Approve this one" : u.blockers.join("; ")}
                />
              </Td>
              <Td>{u.sub_strand_name || u.strand_name || u.subject}</Td>
              <Td numeric>v{u.version}</Td>
              <Td>
                {u.layers_run.length
                  ? u.layers_run.map((l) => (
                      <Badge key={l} tone="neutral">
                        L{l}
                      </Badge>
                    ))
                  : "—"}
              </Td>
              <Td>
                {u.verdict ? (
                  <Badge tone={u.verdict === "pass" ? "ok" : u.verdict === "reject" ? "danger" : "warn"}>
                    {u.verdict} {u.confidence}%
                  </Badge>
                ) : (
                  "—"
                )}
              </Td>
              <Td>
                <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
                  {u.can_approve
                    ? u.requires_override
                      ? "approvable over an objection"
                      : "ready to sign"
                    : u.blockers[0] || "—"}
                </span>
              </Td>
              <Td>
                <Link to={`/approvals?artifact=${encodeURIComponent(u.artifact_id)}`}>
                  <Button size="sm" variant="ghost">
                    Open
                  </Button>
                </Link>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>

      <Stack direction="row" gap="var(--s2)" style={{ marginTop: "var(--s2)", flexWrap: "wrap", alignItems: "center" }}>
        <Button
          size="sm"
          variant="ghost"
          disabled={!ready.length}
          onClick={() => setPicked(picked.length === ready.length ? [] : ready)}
        >
          {picked.length === ready.length && ready.length
            ? "Select none"
            : `Select the ${ready.length} ready`}
        </Button>
        <Button size="sm" disabled={!picked.length} onClick={() => setSigning(true)}>
          Approve {picked.length || ""}
        </Button>
      </Stack>

      {signing && (
        <div
          style={{
            marginTop: "var(--s2)",
            padding: "var(--s3)",
            border: "1px solid var(--accent)",
            borderRadius: "var(--radius)",
          }}
        >
          <strong style={{ fontSize: "var(--text-sm)" }}>
            You are signing for {picked.length} version
            {picked.length === 1 ? "" : "s"}
          </strong>
          <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", margin: "6px 0" }}>
            The review layers narrow what reaches you; they do not replace you.
            Coverage counts approved work as taught-ready, so this is your
            signature under that claim.
          </p>
          <Textarea
            rows={2}
            value={note}
            placeholder="Optional: what you checked, or what you accepted despite."
            onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setNote(e.target.value)}
          />
          <Stack direction="row" gap="var(--s2)" style={{ marginTop: "var(--s2)" }}>
            <Button
              size="sm"
              disabled={approve.isPending}
              onClick={() =>
                approve.mutate(
                  { artifact_ids: picked, reviewed_by_me: true, note },
                  {
                    onSuccess: () => {
                      setSigning(false);
                      setPicked([]);
                      setNote("");
                    },
                  }
                )
              }
            >
              {approve.isPending ? "Approving…" : "I have read these — approve"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSigning(false)}>
              Cancel
            </Button>
          </Stack>
        </div>
      )}

      {approve.data && (
        <p
          style={{
            marginTop: "var(--s2)",
            fontSize: "var(--text-sm)",
            color: approve.data.counts.refused ? "var(--warn)" : "var(--ok)",
          }}
        >
          {approve.data.counts.approved} approved
          {approve.data.counts.refused > 0 && (
            <>
              , {approve.data.counts.refused} refused:
              <ul style={{ margin: "4px 0 0", paddingLeft: "1.1rem" }}>
                {approve.data.refused.map((r) => (
                  <li key={r.artifact_id}>{r.reason}</li>
                ))}
              </ul>
            </>
          )}
        </p>
      )}
      {approve.error && <ErrorNotice error={approve.error} />}
    </div>
  );
}


function BranchRow({
  grade,
  branch,
  open,
  onToggle,
}: {
  grade: string;
  branch: BoardBranch;
  open: boolean;
  onToggle: () => void;
}) {
  const [stage, setStage] = React.useState<BoardStage | null>(null);
  const [logs, setLogs] = React.useState(false);
  const [units, setUnits] = React.useState(false);
  const [wanted, setWanted] = React.useState(false);
  const [domain, setDomain] = React.useState(false);
  const { act } = useStageAction();

  return (
    <Card
      title={branch.subject}
      description={
        branch.blocking_stage
          ? `Blocked at ${branch.blocking_stage}: ${branch.blocked_by}`
          : "Every stage approved."
      }
      actions={
        <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center" }}>
          <Badge tone={TONE[branch.status] || "neutral"}>{WORDS[branch.status]}</Badge>
          {branch.cost_usd > 0 && (
            <span className="mono" style={{ fontSize: "0.75rem", color: "var(--ink-3)" }}>
              ${branch.cost_usd.toFixed(4)}
            </span>
          )}
          <Button size="sm" variant="ghost" onClick={onToggle}>
            {open ? "Hide stages" : "Show stages"}
          </Button>
        </Stack>
      }
    >
      {open && (
        <>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
              gap: "var(--s2)",
            }}
          >
            {branch.stages.map((s) => (
              <StageCell key={s.stage} stage={s} onOpen={() => setStage(s)} />
            ))}
          </div>

          {stage && (
            <div
              style={{
                marginTop: "var(--s3)",
                padding: "var(--s3)",
                border: "1px solid var(--line)",
                borderRadius: "var(--radius)",
              }}
            >
              <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
                <strong>{stage.label}</strong>
                <Badge tone={TONE[stage.status] || "neutral"}>{WORDS[stage.status]}</Badge>
                <Button size="sm" variant="ghost" onClick={() => setStage(null)}>
                  Close
                </Button>
              </Stack>

              {stage.blocked_by && (
                <p style={{ margin: "var(--s2) 0 0", fontSize: "var(--text-sm)" }}>
                  {stage.blocked_by}
                </p>
              )}

              <Table caption={`${stage.label} counts`}>
                <thead>
                  <tr>
                    <Th numeric>Expected</Th>
                    <Th numeric>Built</Th>
                    <Th numeric>Reviewed</Th>
                    <Th numeric>Approved</Th>
                    <Th numeric>Running</Th>
                    <Th numeric>Failed</Th>
                    <Th numeric>Spent</Th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <Td numeric>{stage.expected || "—"}</Td>
                    <Td numeric>{stage.built}</Td>
                    <Td numeric>{stage.reviewed}</Td>
                    <Td numeric>{stage.approved}</Td>
                    <Td numeric>{stage.running}</Td>
                    <Td numeric>{stage.failed}</Td>
                    <Td numeric>${stage.cost_usd.toFixed(4)}</Td>
                  </tr>
                </tbody>
              </Table>

              <p style={{ margin: "var(--s2) 0 0", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                <strong>Gate:</strong>{" "}
                {stage.policy.required_layers.length
                  ? `layer ${stage.policy.required_layers.join(" and ")} from ${
                      stage.policy.min_vendors
                    } vendor${stage.policy.min_vendors === 1 ? "" : "s"}, ${
                      stage.policy.overall_target
                    }/${stage.policy.dimension_target}`
                  : "no review required"}
                {stage.policy.requires_human && ", a person signs"}
                {stage.policy.blocks_downstream && ", blocks what comes after"}.
              </p>

              <Stack direction="row" gap="var(--s2)" style={{ marginTop: "var(--s3)", flexWrap: "wrap" }}>
                {/* Everything a stage can be asked for, where the stage is.
                    Each of these already existed on a different screen, asking
                    for the same grade and subject again. */}
                <Button
                  size="sm"
                  disabled={act.isPending}
                  loading={act.isPending}
                  onClick={() =>
                    act.mutate({ grade, stage: stage.stage, subject: branch.subject, action: "run" })
                  }
                  title={`Queue ${stage.label.toLowerCase()} for every sub-strand in ${branch.subject}`}
                >
                  Run
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={act.isPending || !stage.built}
                  title={
                    stage.built
                      ? `Send all ${stage.built} for an independent read`
                      : "Nothing built to review yet"
                  }
                  onClick={() =>
                    act.mutate({ grade, stage: stage.stage, subject: branch.subject, action: "review", layer: 2 })
                  }
                >
                  Review
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={act.isPending || !stage.reviewed}
                  title={
                    stage.reviewed
                      ? "Run the approving layer's work — approval itself stays a person's decision"
                      : "Review it first; the approver reads the review"
                  }
                  onClick={() =>
                    act.mutate({ grade, stage: stage.stage, subject: branch.subject, action: "approval" })
                  }
                >
                  Send to the approver
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={act.isPending || !stage.reviewed}
                  title="Write the next version from what the reviews found"
                  onClick={() =>
                    act.mutate({ grade, stage: stage.stage, subject: branch.subject, action: "regenerate" })
                  }
                >
                  Regenerate from findings
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setUnits(!units)}>
                  {units ? "Hide the versions" : "Versions & approve"}
                </Button>
                {STATION_STAGES.has(stage.stage) && (
                  <Button size="sm" variant="ghost" onClick={() => setWanted(!wanted)}>
                    {wanted ? "Hide what the plan asks for" : "What the plan asks for"}
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => setDomain(!domain)}>
                  {domain ? "Hide the domain prompts" : "Domain prompts"}
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setLogs(!logs)}>
                  {logs ? "Hide the log" : "Show the log"}
                </Button>
                <Link to={`/factory?grade=${encodeURIComponent(grade)}&subject=${encodeURIComponent(branch.subject)}`}>
                  <Button size="sm" variant="ghost">Open in the factory</Button>
                </Link>
              </Stack>
              {act.data && (
                <p style={{ margin: "var(--s2) 0 0", fontSize: "var(--text-sm)", color: "var(--ok)" }}>
                  {act.data.queued} job(s) queued for {act.data.action}. The log below follows them.
                </p>
              )}
              {act.error && <ErrorNotice error={act.error} />}
              {units && (
                <StageUnits grade={grade} stage={stage.stage} subject={branch.subject} />
              )}
              {domain && (
                <PromptFragments
                  subject={branch.subject}
                  grade={grade}
                  station={stage.stage}
                  compact
                />
              )}
              {wanted && (
                <StageRequirements
                  grade={grade}
                  subject={branch.subject}
                  station={stage.stage}
                />
              )}
              {logs && (
                <StageLog
                  grade={grade}
                  stage={stage.stage}
                  subject={branch.subject}
                />
              )}
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function PolicyEditor() {
  const { list, save, reset } = useStagePolicies();
  const [stage, setStage] = React.useState("");

  if (list.isLoading) return <LoadingBlock rows={4} label="Loading the gates" />;
  if (list.isError) return <ErrorNotice error={list.error} />;

  const policies = list.data?.policies || [];
  const chosen = policies.find((p) => p.stage === stage) || policies[0];
  if (!chosen) return null;

  function change(patch: Partial<StagePolicy>) {
    save.mutate({ stage: chosen.stage, ...patch });
  }

  return (
    <Card
      title="What each stage has to pass"
      description="One rule for the whole pipeline meant running a two-vendor review chain on reading a strand list out of a table — or turning the gate off, and losing it for the lesson plan too."
    >
      <Stack direction="row" gap="var(--s3)" style={{ flexWrap: "wrap", alignItems: "end" }}>
        <Field label="Stage">
          {(a11y) => (
            <Select {...a11y} value={chosen.stage} onChange={(e) => setStage(e.target.value)}>
              {policies.map((p) => (
                <option key={p.stage} value={p.stage}>
                  {p.stage}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Vendors" hint="Two models from one vendor share failure modes">
          {(a11y) => (
            <Input
              {...a11y}
              type="number"
              min={1}
              max={3}
              value={chosen.min_vendors}
              onChange={(e) => change({ min_vendors: Number(e.target.value) })}
            />
          )}
        </Field>
        <Field label="Overall target">
          {(a11y) => (
            <Input
              {...a11y}
              type="number"
              min={0}
              max={100}
              value={chosen.overall_target}
              onChange={(e) => change({ overall_target: Number(e.target.value) })}
            />
          )}
        </Field>
        <Field label="Every dimension">
          {(a11y) => (
            <Input
              {...a11y}
              type="number"
              min={0}
              max={100}
              value={chosen.dimension_target}
              onChange={(e) => change({ dimension_target: Number(e.target.value) })}
            />
          )}
        </Field>
        <Field label="Refine cycles" hint="How many times it may try before giving up">
          {(a11y) => (
            <Input
              {...a11y}
              type="number"
              min={0}
              max={6}
              value={chosen.max_refine_cycles}
              onChange={(e) => change({ max_refine_cycles: Number(e.target.value) })}
            />
          )}
        </Field>
      </Stack>

      <Stack direction="row" gap="var(--s3)" style={{ marginTop: "var(--s3)", flexWrap: "wrap" }}>
        {[1, 2, 3].map((layer) => (
          <label key={layer} style={{ fontSize: "var(--text-sm)", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={chosen.required_layers.includes(layer)}
              onChange={(e) =>
                change({
                  required_layers: e.target.checked
                    ? [...chosen.required_layers, layer]
                    : chosen.required_layers.filter((n) => n !== layer),
                })
              }
            />{" "}
            Layer {layer} required
          </label>
        ))}
        <label style={{ fontSize: "var(--text-sm)", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={chosen.requires_human}
            onChange={(e) => change({ requires_human: e.target.checked })}
          />{" "}
          A person signs
        </label>
        <label style={{ fontSize: "var(--text-sm)", cursor: "pointer" }}>
          <input
            type="checkbox"
            checked={chosen.blocks_downstream}
            onChange={(e) => change({ blocks_downstream: e.target.checked })}
          />{" "}
          Blocks what comes after
        </label>
        <Button size="sm" variant="ghost" onClick={() => reset.mutate(chosen.stage)}>
          Back to the default
        </Button>
      </Stack>

      <p style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
        {chosen.why}
      </p>
      {save.error && <ErrorNotice error={save.error} />}
    </Card>
  );
}

export function Pipelines() {
  const [params, setParams] = useSearchParams();
  const grade = params.get("grade") || "";
  const projects = usePipelines();
  const project = usePipeline(grade);
  const [open, setOpen] = React.useState<string>("");

  if (projects.isLoading) return <LoadingBlock rows={5} label="Loading the board" />;
  if (projects.isError) return <ErrorNotice error={projects.error} />;

  const rows = projects.data?.projects || [];

  if (!grade) {
    return (
      <>
        <PageHeader
          title="Pipelines"
          description={
            `${rows.filter((p) => p.ingested).length} of ${rows.length} grades started. ` +
            "A grade is a project, a subject is a branch of it, and each stage is a build step with its own gate."
          }
        />
        {/* Every grade, not only the ingested ones. Listing what has been
            started answers "what have I done" and hides the question actually
            being asked — a grade with nothing in it is the most actionable row
            here, because it is the one to start next. */}
        <Table caption="Projects">
          <thead>
            <tr>
              <Th>Grade</Th>
              <Th>Level</Th>
              <Th numeric>Subjects</Th>
              <Th numeric>Sub-strands</Th>
              <Th>State</Th>
              <Th numeric>Spent</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.grade} style={{ opacity: p.ingested ? 1 : 0.6 }}>
                <Td>{p.label}</Td>
                <Td>
                  <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
                    {p.level}
                  </span>
                </Td>
                <Td numeric>{p.subjects || "—"}</Td>
                <Td numeric>{p.sub_strands || "—"}</Td>
                <Td>
                  {!p.ingested ? (
                    <Badge tone="neutral">not ingested</Badge>
                  ) : p.failed > 0 ? (
                    <Badge tone="danger">{p.failed} failed</Badge>
                  ) : p.running > 0 ? (
                    <Badge tone="accent">{p.running} running</Badge>
                  ) : (
                    <span style={{ color: "var(--ink-3)" }}>idle</span>
                  )}
                </Td>
                <Td numeric>{p.cost_usd > 0 ? `$${p.cost_usd.toFixed(4)}` : "—"}</Td>
                <Td>
                  {p.ingested ? (
                    <Button size="sm" onClick={() => setParams({ grade: p.grade })}>
                      Open
                    </Button>
                  ) : (
                    <Link to="/datasets">
                      <Button size="sm" variant="ghost">
                        Read the design in
                      </Button>
                    </Link>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>

        <div style={{ marginTop: "var(--s4)" }}>
          <PolicyEditor />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title={project.data?.label || grade}
        description="Each subject is a branch. Read left to right: a branch is only as far along as its earliest unfinished stage."
        actions={
          <Button size="sm" variant="ghost" onClick={() => setParams({})}>
            All projects
          </Button>
        }
      />
      {project.isLoading && <LoadingBlock rows={4} label="Loading the branches" />}
      {project.isError && <ErrorNotice error={project.error} />}
      {/* An unattended run IS a pipeline run, so it belongs on the board
          rather than in a panel of its own with its own words for the same
          stages. */}
      <div style={{ marginBottom: "var(--s4)" }}>
        <AutoRunPanel grade={grade} />
        <AutoRunActivity grade={grade} running />
      </div>

      <Stack gap="var(--s3)">
        {(project.data?.subjects || []).map((b) => (
          <BranchRow
            key={b.subject}
            grade={grade}
            branch={b}
            open={open === b.subject}
            onToggle={() => setOpen(open === b.subject ? "" : b.subject)}
          />
        ))}
      </Stack>
      <div style={{ marginTop: "var(--s4)" }}>
        <PolicyEditor />
      </div>
    </>
  );
}
