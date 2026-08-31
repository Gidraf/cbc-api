import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Field,
  Input,
  LoadingBlock,
  PageHeader,
  Select,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import {
  usePipeline,
  usePipelines,
  useStagePolicies,
  type BoardBranch,
  type BoardStage,
  type StagePolicy,
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
                <Link to={`/factory?grade=${encodeURIComponent(grade)}&subject=${encodeURIComponent(branch.subject)}`}>
                  <Button size="sm">Open in the factory</Button>
                </Link>
                <Link to="/queue">
                  <Button size="sm" variant="ghost">
                    See the queue
                  </Button>
                </Link>
              </Stack>
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
          description="A grade is a project, a subject is a branch of it, and each stage is a build step with its own gate."
        />
        {!rows.length ? (
          <EmptyState
            title="Nothing ingested yet"
            description="A grade appears here once its design has been read in."
          />
        ) : (
          <Table caption="Projects">
            <thead>
              <tr>
                <Th>Grade</Th>
                <Th numeric>Subjects</Th>
                <Th numeric>Sub-strands</Th>
                <Th>State</Th>
                <Th numeric>Spent</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={p.grade}>
                  <Td>{p.label}</Td>
                  <Td numeric>{p.subjects}</Td>
                  <Td numeric>{p.sub_strands}</Td>
                  <Td>
                    {p.failed > 0 && <Badge tone="danger">{p.failed} failed</Badge>}{" "}
                    {p.running > 0 && <Badge tone="accent">{p.running} running</Badge>}
                    {!p.failed && !p.running && <span style={{ color: "var(--ink-3)" }}>idle</span>}
                  </Td>
                  <Td numeric>${p.cost_usd.toFixed(4)}</Td>
                  <Td>
                    <Button size="sm" onClick={() => setParams({ grade: p.grade })}>
                      Open
                    </Button>
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
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
