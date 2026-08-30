import React from "react";

import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  ProgressBar,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import { AutoRunActivity } from "./AutoRunActivity";
import {
  PIPELINE_STEPS,
  STEP_LABEL,
  useAutoRunStatus,
  useStartAutoRun,
  useStopAutoRun,
  useSubjects,
} from "../lib/queries";

/**
 * Generate a grade unattended, and stop when quality falls through the floor.
 *
 * Set it going, come back, download everything, review it at leisure. The floor
 * is what makes that safe: unattended generation that keeps producing while
 * quality collapses yields a grade of unusable content, at full price, and the
 * operator finds out at the end.
 *
 * The score is what the pipeline's own validators measured — grounding, lesson
 * coverage, citations that resolve, rubrics read from the design, the local
 * gate. It is NOT the accuracy a person reading against the KICD design would
 * give, and the panel says so, because a floor of 95 means nothing if the
 * operator thinks it means the other thing.
 */
export function AutoRunPanel({ grade }: { grade: string }) {
  const status = useAutoRunStatus(grade);
  const start = useStartAutoRun(grade);
  const stop = useStopAutoRun();
  const subjects = useSubjects(grade);

  const [floor, setFloor] = React.useState(95);
  const [cycles, setCycles] = React.useState(3);
  // What runs unattended. Everything not ticked stays yours to run by hand —
  // which is the point: the expensive or judgement-heavy stages are often the
  // ones worth watching, and an all-or-nothing auto mode forces a choice
  // between doing everything by hand and trusting everything to the machine.
  const [autoSteps, setAutoSteps] = React.useState<string[]>([
    "substrands", "notes", "diagram", "media", "activity", "questions",
  ]);
  const [autoSubjects, setAutoSubjects] = React.useState<string[]>([]);

  function toggle(list: string[], set: (v: string[]) => void, value: string) {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  }

  const manualSteps = PIPELINE_STEPS.filter((s) => !autoSteps.includes(s));

  const run = status.data;
  const running = Boolean(run?.running);
  const halted = run?.status === "halted";
  const queue = run?.queue;

  return (
    <Card
      title="Auto mode"
      description="Generate everything for this grade unattended, then come back and download it."
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
            <div>
              <strong style={{ fontSize: "var(--text-sm)" }}>
                What runs unattended
              </strong>
              <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", margin: "4px 0 var(--s2)" }}>
                Untick a stage to keep it for yourself. The run stops at the last
                ticked stage and leaves the rest for you to do by hand.
              </div>
              <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
                {PIPELINE_STEPS.map((step) => (
                  <Button
                    key={step}
                    size="sm"
                    variant={autoSteps.includes(step) ? "primary" : "secondary"}
                    onClick={() => toggle(autoSteps, setAutoSteps, step)}
                  >
                    {autoSteps.includes(step) ? "auto " : "manual "}
                    {STEP_LABEL[step] || step}
                  </Button>
                ))}
              </Stack>
              {manualSteps.length > 0 && (
                <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", marginTop: "var(--s2)" }}>
                  You will run these yourself:{" "}
                  {manualSteps.map((s) => STEP_LABEL[s] || s).join(", ")}.
                </div>
              )}
            </div>

            <div>
              <strong style={{ fontSize: "var(--text-sm)" }}>
                Which learning areas
              </strong>
              <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", margin: "4px 0 var(--s2)" }}>
                {autoSubjects.length === 0
                  ? "None ticked — every learning area with an ingested design will run."
                  : `${autoSubjects.length} selected.`}{" "}
                Start with one and read the weakest-items table before turning the
                rest loose.
              </div>
              <Stack direction="row" gap="var(--s2)" style={{ flexWrap: "wrap" }}>
                {(subjects.data || []).map((s) => (
                  <Button
                    key={s.name}
                    size="sm"
                    variant={autoSubjects.includes(s.name) ? "primary" : "secondary"}
                    onClick={() => toggle(autoSubjects, setAutoSubjects, s.name)}
                  >
                    {autoSubjects.includes(s.name) ? "✓ " : ""}
                    {s.name}
                  </Button>
                ))}
              </Stack>
            </div>

            <Stack direction="row" gap="var(--s2)" align="center" wrap>
              <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                Review cycles per item
              </label>
              <input
                type="number"
                min={1}
                max={5}
                value={cycles}
                onChange={(e) => setCycles(Number(e.target.value))}
                aria-label="Review cycles"
                style={{ width: "4rem", padding: "6px 8px", borderRadius: "var(--radius-sm)" }}
              />
              <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
                Each cycle re-runs a failing generation with the review's findings.
                Three is thorough and three times the bill across a grade; one is
                cheapest.
              </span>
            </Stack>

            <Stack direction="row" gap="var(--s2)" align="center" wrap>
              <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                Stop if quality drops below
              </label>
              <input
                type="number"
                min={0}
                max={100}
                value={floor}
                onChange={(e) => setFloor(Number(e.target.value))}
                aria-label="Quality floor"
                style={{ width: "5rem", padding: "6px 8px", borderRadius: "var(--radius-sm)" }}
              />
              <Button
                disabled={!grade || start.isPending}
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
            <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", margin: 0 }}>
              Runs one item at a time. Each finished item is
              scored on what its own validators checked — whether it was grounded
              in the design, whether every funded lesson was planned and none of
              them too thin, whether its page references resolve, how many rubrics
              came from KICD rather than being written from outcomes, and the local
              review gate.
              <br />
              <br />
              <strong>That is not the same number as a person reading the output
              against the design.</strong> It catches absence, contradiction and
              ungroundedness — it cannot tell whether a rubric measures the right
              thing. Treat it as "nothing measurable is wrong", and review what
              comes out.
            </p>
          </>
        )}

        {start.error && <ErrorNotice error={start.error} />}

        {/* The live picture: what it is doing, producing and spending. A
            progress bar alone answers only "how far". */}
        {(running || halted) && <AutoRunActivity grade={grade} running={running} />}

        {run && run.items_scored !== undefined && run.items_scored > 0 && (
          <>
            <Stack direction="row" gap="var(--s3)" align="center" wrap>
              <Badge tone={(run.recent_median ?? 0) >= (run.floor ?? 95) ? "ok" : "danger"}>
                median {run.recent_median} of the last {run.window}
              </Badge>
              <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                mean {run.average} across {run.items_counted} scored item(s) ·
                floor {run.floor}
              </span>
            </Stack>

            {halted && run.halted_reason && (
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
                  Fix what the weakest items point at — a prompt, a design that
                  will not parse, a provider returning short output — then start
                  it again. What it already produced is saved and downloadable.
                </div>
              </div>
            )}

            {(run.weakest_items || []).length > 0 && (
              <details>
                <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                  The {run.weakest_items!.length} weakest items so far
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
                    {run.weakest_items!.map((item, i) => (
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
          </>
        )}
      </Stack>
    </Card>
  );
}
