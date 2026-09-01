import React from "react";
import { Link } from "react-router-dom";

import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import { AutoRunActivity } from "./AutoRunActivity";
import { TONE, WORDS, rollupStages } from "./pipelineVocabulary";
import {
  PIPELINE_STEPS,
  STEP_LABEL,
  useAutoRunStatus,
  usePipeline,
  useStartAutoRun,
  useStopAutoRun,
  type BoardBranch,
  type BoardStage,
} from "../lib/queries";

/**
 * Generate a grade unattended, planned against the board rather than beside it.
 *
 * This used to be a wall of identical toggle buttons — "auto Sub-strands",
 * "manual Simulations" — wrapping onto two rows, so the chain's ORDER was
 * invisible and the tiles said nothing about the work. You chose which stages
 * to run unattended with no idea which of them were already done, already
 * failing, or waiting on something upstream, and then read the answer on a
 * different screen.
 *
 * So the picker IS the board's stage row: the same tiles, the same words, the
 * same counts, in the order the work depends on itself. Clicking one holds it
 * back for you to run by hand.
 *
 * The floor is what makes leaving it safe. Unattended generation that keeps
 * producing while quality collapses yields a grade of unusable content, at full
 * price, discovered at the end. The score is what the pipeline's own validators
 * measured — grounding, lesson coverage, citations that resolve, rubrics read
 * from the design, the local gate — and NOT the accuracy a person reading
 * against the KICD design would give. The panel says so, because a floor of 95
 * means nothing if the operator thinks it means the other thing.
 */

const DEFAULT_AUTO = [
  "substrands", "notes", "diagram", "media", "activity", "questions",
];

function money(usd?: number) {
  if (!usd) return "$0.00";
  return usd < 0.01 ? `$${usd.toFixed(4)}` : `$${usd.toFixed(2)}`;
}

/**
 * One stage of the chain, as a choice.
 *
 * Deliberately the board's tile: same tone, same counts, same progress bar. The
 * only thing added is whether this run will touch it, because that is the only
 * question being asked here.
 */
function StagePick({
  stage,
  label,
  on,
  onToggle,
}: {
  stage?: BoardStage;
  label: string;
  on: boolean;
  onToggle: () => void;
}) {
  const tone = stage ? TONE[stage.status] || "neutral" : "neutral";
  const state = stage ? WORDS[stage.status] || stage.status : "no data yet";
  return (
    <button
      onClick={onToggle}
      aria-pressed={on}
      title={
        on
          ? `${label} — ${state}. Will run unattended. Click to keep it for yourself.`
          : `${label} — ${state}. You will run this one. Click to hand it to the run.`
      }
      style={{
        flex: "0 0 9.5rem",
        textAlign: "left",
        cursor: "pointer",
        font: "inherit",
        color: "inherit",
        padding: "var(--s2)",
        borderRadius: "var(--radius-sm)",
        // Held-back stages recede rather than disappear: the chain has to stay
        // readable as a chain, or the order stops meaning anything.
        opacity: on ? 1 : 0.55,
        background: on ? `var(--${tone}-wash, var(--surface-2))` : "transparent",
        border: on
          ? `1px solid var(--${tone === "neutral" ? "line" : tone})`
          : "1px dashed var(--line)",
      }}
    >
      <div style={{ fontSize: "var(--text-sm)", fontWeight: 550 }}>{label}</div>
      <div className="mono" style={{ fontSize: "0.75rem", color: "var(--ink-3)" }}>
        {stage
          ? (stage.expected ? `${stage.built}/${stage.expected}` : stage.built || "—") +
            (stage.failed > 0 ? ` · ${stage.failed} failed` : "") +
            (stage.running > 0 ? ` · ${stage.running} running` : "")
          : "—"}
      </div>
      <div
        style={{
          height: 3,
          margin: "4px 0",
          borderRadius: 2,
          background: "var(--line)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${stage?.percentage ?? 0}%`,
            height: "100%",
            background: `var(--${tone === "neutral" ? "ink-3" : tone})`,
          }}
        />
      </div>
      <div style={{ fontSize: "0.7rem", color: on ? "var(--accent)" : "var(--ink-3)" }}>
        {on ? "▶ runs unattended" : "✋ you run this"}
      </div>
    </button>
  );
}

/** A learning area, with the state the board already knows about it. */
function SubjectPick({
  branch,
  on,
  onToggle,
}: {
  branch: BoardBranch;
  on: boolean;
  onToggle: () => void;
}) {
  const tone = TONE[branch.status] || "neutral";
  return (
    <button
      onClick={onToggle}
      aria-pressed={on}
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--s2)",
        cursor: "pointer",
        font: "inherit",
        color: "inherit",
        textAlign: "left",
        padding: "6px var(--s2)",
        borderRadius: "var(--radius-sm)",
        background: on ? "var(--accent-wash)" : "transparent",
        border: `1px solid var(--${on ? "accent" : "line"})`,
      }}
    >
      <span aria-hidden style={{ color: on ? "var(--accent)" : "var(--ink-3)" }}>
        {on ? "☑" : "☐"}
      </span>
      <span style={{ fontSize: "var(--text-sm)" }}>{branch.subject}</span>
      <Badge tone={tone}>{WORDS[branch.status] || branch.status}</Badge>
      {branch.cost_usd > 0 && (
        <span className="mono" style={{ fontSize: "0.7rem", color: "var(--ink-3)" }}>
          {money(branch.cost_usd)}
        </span>
      )}
    </button>
  );
}

export function AutoRunPanel({ grade }: { grade: string }) {
  const status = useAutoRunStatus(grade);
  const start = useStartAutoRun(grade);
  const stop = useStopAutoRun();
  // The board, not a separate list of subject names: it carries each learning
  // area's state and each stage's counts, which is what makes this a plan
  // rather than a form.
  const board = usePipeline(grade);

  const [floor, setFloor] = React.useState(95);
  const [cycles, setCycles] = React.useState(3);
  const [autoSteps, setAutoSteps] = React.useState<string[]>(DEFAULT_AUTO);
  const [autoSubjects, setAutoSubjects] = React.useState<string[]>([]);

  function toggle(list: string[], set: (v: string[]) => void, value: string) {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  }

  const branches = board.data?.subjects || [];
  // No ticks means every learning area, so the chain must summarise every
  // learning area — otherwise the tiles describe a narrower run than the one
  // the button will start.
  const chosen = autoSubjects.length
    ? branches.filter((b) => autoSubjects.includes(b.subject))
    : branches;
  const rolled = React.useMemo(() => rollupStages(chosen), [chosen]);

  const manualSteps = PIPELINE_STEPS.filter((s) => !autoSteps.includes(s));
  const ingest = rolled.get("ingest");
  // A run over a grade whose design was never imported produces nothing and
  // says so only at the end. The dataset is the first stage for a reason.
  const nothingImported =
    branches.length === 0 ||
    (ingest?.dataset ? ingest.dataset.state === "not_imported" : false);

  const run = status.data;
  const running = Boolean(run?.running);
  const halted = run?.status === "halted";
  const scored = (run?.items_counted ?? 0) > 0;

  const willBuild = autoSteps.reduce(
    (n, step) => n + Math.max(0, (rolled.get(step)?.expected || 0) - (rolled.get(step)?.built || 0)),
    0
  );

  return (
    <Card
      title="Auto run"
      description="Plan it against the board, start it, and come back. It follows the same chain the board shows and stops itself if quality falls through the floor."
      actions={
        running ? (
          <Stack direction="row" gap="var(--s2)" align="center">
            <Badge tone="accent">running</Badge>
            <Button
              size="sm"
              variant="danger"
              disabled={stop.isPending || !run?.run_id}
              loading={stop.isPending}
              onClick={() => run?.run_id && stop.mutateAsync(run.run_id)}
            >
              Stop
            </Button>
          </Stack>
        ) : halted ? (
          <Badge tone="danger">halted</Badge>
        ) : null
      }
    >
      <Stack gap="var(--s3)">
        {!running && (
          <>
            {nothingImported && (
              <div
                style={{
                  border: "1px solid var(--warn)",
                  background: "var(--warn-wash)",
                  borderRadius: "var(--radius)",
                  padding: "var(--s3)",
                  fontSize: "var(--text-sm)",
                }}
              >
                <strong>There is no design to read for this grade.</strong> The
                chain starts at the Langfuse dataset — import it first, or the
                run will spend a night producing nothing.{" "}
                <Link to={`/datasets?grade=${encodeURIComponent(grade)}`}>
                  Import the design
                </Link>
              </div>
            )}

            <div>
              <Stack direction="row" gap="var(--s2)" align="baseline" wrap>
                <strong style={{ fontSize: "var(--text-sm)" }}>The chain</strong>
                <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
                  Same stages, same state, same order as the board. Click one to
                  hold it back and run it yourself.
                </span>
              </Stack>
              {/* One row, scrolled — never wrapped. Wrapping put Questions
                  underneath Read the design, which reads as a grid of unrelated
                  options rather than a sequence that depends on itself. */}
              <div
                style={{
                  display: "flex",
                  alignItems: "stretch",
                  gap: 6,
                  overflowX: "auto",
                  padding: "var(--s2) 0",
                }}
              >
                {PIPELINE_STEPS.map((step, i) => (
                  <React.Fragment key={step}>
                    {i > 0 && (
                      <span
                        aria-hidden
                        style={{
                          alignSelf: "center",
                          color: "var(--ink-3)",
                          fontSize: "0.8rem",
                        }}
                      >
                        →
                      </span>
                    )}
                    <StagePick
                      stage={rolled.get(step)}
                      label={STEP_LABEL[step] || step}
                      on={autoSteps.includes(step)}
                      onToggle={() => toggle(autoSteps, setAutoSteps, step)}
                    />
                  </React.Fragment>
                ))}
              </div>
              <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
                {manualSteps.length === 0
                  ? "Everything runs unattended."
                  : `Held back for you: ${manualSteps
                      .map((s) => STEP_LABEL[s] || s)
                      .join(", ")}. The run does not skip past a held-back stage — it stops there.`}
              </div>
            </div>

            <div>
              <Stack direction="row" gap="var(--s2)" align="baseline" wrap>
                <strong style={{ fontSize: "var(--text-sm)" }}>Learning areas</strong>
                <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
                  {autoSubjects.length === 0
                    ? `None ticked — all ${branches.length} will run.`
                    : `${autoSubjects.length} of ${branches.length} ticked.`}
                </span>
                {autoSubjects.length > 0 && (
                  <Button size="sm" variant="ghost" onClick={() => setAutoSubjects([])}>
                    Clear
                  </Button>
                )}
                <Link to="/pipelines" style={{ fontSize: "var(--text-sm)" }}>
                  Open the board
                </Link>
              </Stack>
              <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
                {branches.map((b) => (
                  <SubjectPick
                    key={b.subject}
                    branch={b}
                    on={autoSubjects.includes(b.subject)}
                    onToggle={() => toggle(autoSubjects, setAutoSubjects, b.subject)}
                  />
                ))}
              </Stack>
              <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", marginTop: 4 }}>
                Start with one and read the weakest-items table before turning the
                rest loose.
              </div>
            </div>

            {/* The two numbers that decide the bill, together, because they are
                one decision: how hard to try and when to give up. */}
            <Stack direction="row" gap="var(--s3)" align="flex-end" wrap>
              <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                <div>Review cycles per item</div>
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={cycles}
                  onChange={(e) => setCycles(Number(e.target.value))}
                  aria-label="Review cycles per item"
                  style={{ width: "5rem", padding: "6px 8px", borderRadius: "var(--radius-sm)" }}
                />
              </label>
              <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                <div>Stop below quality</div>
                <input
                  type="number"
                  min={0}
                  max={100}
                  value={floor}
                  onChange={(e) => setFloor(Number(e.target.value))}
                  aria-label="Quality floor"
                  style={{ width: "5rem", padding: "6px 8px", borderRadius: "var(--radius-sm)" }}
                />
              </label>
              <Button
                disabled={!grade || start.isPending || autoSteps.length === 0}
                loading={start.isPending}
                onClick={() =>
                  start.mutateAsync({
                    floor,
                    review_cycles: cycles,
                    steps: autoSteps,
                    subjects: autoSubjects,
                  })
                }
              >
                {start.isPending ? "Starting…" : "Start auto run"}
              </Button>
            </Stack>

            {/* What the button is about to do, in one sentence, from the same
                numbers the tiles are showing. */}
            <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", margin: 0 }}>
              {autoSteps.length === 0 ? (
                <>Every stage is held back, so there is nothing for the run to do.</>
              ) : (
                <>
                  <strong>{autoSteps.length}</strong> stage(s) across{" "}
                  <strong>{chosen.length || branches.length}</strong> learning
                  area(s){willBuild > 0 && <>, about <strong>{willBuild}</strong> item(s) still to build</>}
                  , up to <strong>{cycles}</strong> review cycle(s) each, stopping
                  if the recent median falls below <strong>{floor}</strong>.
                </>
              )}
            </p>

            <details>
              <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                What that quality number is, and what it is not
              </summary>
              <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
                Each finished item is scored on what its own validators checked —
                whether it was grounded in the design, whether every funded lesson
                was planned and none of them too thin, whether its page references
                resolve, how many rubrics came from KICD rather than being written
                from outcomes, and the local review gate.
                <br />
                <br />
                <strong>
                  That is not the same number as a person reading the output
                  against the design.
                </strong>{" "}
                It catches absence, contradiction and ungroundedness — it cannot
                tell whether a rubric measures the right thing. Treat it as
                "nothing measurable is wrong", and review what comes out.
              </p>
            </details>
          </>
        )}

        {start.error && <ErrorNotice error={start.error} />}

        {/* The live picture: what it is doing, producing and spending. A
            progress bar alone answers only "how far". */}
        {(running || halted) && <AutoRunActivity grade={grade} running={running} />}

        {/* Only once something has actually been scored. "median 0 of the last
            5 · mean 0 across 0 scored item(s)" was shown before a run had ever
            started, and a red zero reads as a failure. */}
        {run && scored && (
          <Stack direction="row" gap="var(--s3)" align="center" wrap>
            <Badge tone={(run.recent_median ?? 0) >= (run.floor ?? 95) ? "ok" : "danger"}>
              median {run.recent_median} of the last {run.window}
            </Badge>
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              mean {run.average} across {run.items_counted} scored item(s) · floor{" "}
              {run.floor}
            </span>
          </Stack>
        )}

        {halted && run?.halted_reason && (
          <div
            style={{
              border: "1px solid var(--danger)",
              borderRadius: "var(--radius)",
              padding: "var(--s3)",
              fontSize: "var(--text-sm)",
            }}
          >
            <strong>The run stopped itself.</strong>
            <div style={{ marginTop: 4 }}>{run.halted_reason}</div>
            <div style={{ color: "var(--ink-3)", marginTop: "var(--s2)" }}>
              Fix what the weakest items point at — a prompt, a design that will
              not parse, a provider returning short output — then start it again.
              What it already produced is saved and downloadable.
            </div>
          </div>
        )}

        {(run?.weakest_items || []).length > 0 && (
          <details>
            <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              The {run!.weakest_items!.length} weakest items so far
            </summary>
            <Table caption="Lowest-scoring items">
              <thead>
                <tr>
                  <Th>Item</Th>
                  <Th numeric>Score</Th>
                  <Th>Let down by</Th>
                </tr>
              </thead>
              <tbody>
                {run!.weakest_items!.map((item, i) => (
                  <tr key={i}>
                    <Td>{item.label}</Td>
                    <Td numeric>{item.score}</Td>
                    <Td>{String(item.weakest || "—").replace(/_/g, " ")}</Td>
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
