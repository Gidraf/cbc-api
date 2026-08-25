import React from "react";
import { useSearchParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Grid,
  Label,
  LoadingBlock,
  QueryState,
  PageHeader,
  ProgressBar,
  Select,
  Stack,
  Table,
  Td,
  Th,
  useToast,
} from "../ui/components";
import { useApi, useGrades, useProgress, useSubjects } from "../lib/queries";
import { useQueryClient } from "@tanstack/react-query";

/**
 * The four production stations have a real dependency order: notes ground the
 * diagrams and activities, and all three ground the questions. The previous
 * console presented them as four independently clickable panels, so an operator
 * could open the questions station for a sub-strand with no notes and get an
 * error from the API instead of an explanation.
 */
const STATIONS = [
  {
    id: "notes",
    n: 1,
    label: "Lesson notes",
    endpoint: "/api/v1/curriculum/factory/generate-notes",
    blurb: "Hour-by-hour teaching notes grounded in the sub-strand's learning outcomes.",
    requires: null as string | null,
  },
  {
    id: "visuals",
    n: 2,
    label: "Diagrams",
    endpoint: "/api/v1/curriculum/factory/plan-visuals",
    blurb: "Vector diagrams with addressable parts, so questions can test one region.",
    requires: "notes",
  },
  {
    id: "practicals",
    n: 3,
    label: "Activities & experiments",
    endpoint: "/api/v1/curriculum/factory/plan-activities",
    blurb: "Hands-on tasks with the safety guidance their materials require.",
    requires: "notes",
  },
  {
    id: "questions",
    n: 4,
    label: "Questions",
    endpoint: "/api/v1/questions/factory/generate-batch",
    blurb: "Assessment items derived from the notes, diagrams and practicals above.",
    requires: "visuals",
  },
] as const;

export function ContentFactory() {
  const [params, setParams] = useSearchParams();
  const toast = useToast();
  const api = useApi();
  const qc = useQueryClient();

  const grade = params.get("grade") || "";
  const subject = params.get("subject") || "";
  const strand = params.get("strand") || "";
  const substrand = params.get("substrand") || "";

  const grades = useGrades();
  const effectiveGrade = grade || grades.data?.[0]?.slug || grades.data?.[0]?.name || "";
  const subjects = useSubjects(effectiveGrade);
  const progress = useProgress(effectiveGrade, subject || undefined);

  const [running, setRunning] = React.useState<string | null>(null);

  function setParam(patch: Record<string, string>) {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  }

  // Locate the selected sub-strand's coverage record.
  const selected = React.useMemo(() => {
    if (!progress.data || !substrand) return null;
    for (const subj of progress.data.subjects) {
      if (subject && subj.subject !== subject) continue;
      for (const st of subj.strands) {
        for (const ss of st.substrands) {
          if (ss.sub_strand_name === substrand) {
            return { subject: subj.subject, strand: st.strand_name, report: ss };
          }
        }
      }
    }
    return null;
  }, [progress.data, subject, substrand]);

  const allSubstrands = React.useMemo(() => {
    if (!progress.data) return [];
    const out: { subject: string; strand: string; name: string; pct: number }[] = [];
    for (const subj of progress.data.subjects) {
      if (subject && subj.subject !== subject) continue;
      for (const st of subj.strands) {
        for (const ss of st.substrands) {
          out.push({ subject: subj.subject, strand: st.strand_name, name: ss.sub_strand_name, pct: ss.overall_percentage });
        }
      }
    }
    return out;
  }, [progress.data, subject]);

  async function runStation(station: (typeof STATIONS)[number]) {
    if (!selected) return;
    setRunning(station.id);
    try {
      const body =
        station.id === "questions"
          ? {
              grade: effectiveGrade,
              subject: selected.subject,
              strand: selected.strand,
              sub_strand: substrand,
              batch_count: 5,
            }
          : {
              grade: effectiveGrade,
              subject: selected.subject,
              strand: selected.strand,
              sub_strand: substrand,
            };

      const res = await api<any>(station.endpoint, { method: "POST", body: JSON.stringify(body) });

      const rejected = res?.rejected_count ?? 0;
      const gate = res?.quality_gate;
      if (rejected > 0) {
        toast(
          `${station.label}: ${res.batch_count ?? 0} accepted, ${rejected} rejected by validation.`,
          "danger"
        );
      } else if (gate && gate.passed === false) {
        toast(`${station.label} generated but the quality gate flagged it. See the panel below.`, "danger");
      } else {
        toast(`${station.label} generated.`, "ok");
      }

      qc.invalidateQueries({ queryKey: ["progress"] });
      qc.invalidateQueries({ queryKey: ["bundle"] });
      setLastResult({ station: station.id, res });
    } catch (err) {
      toast(err instanceof Error ? err.message : `${station.label} failed.`, "danger");
    } finally {
      setRunning(null);
    }
  }

  const [lastResult, setLastResult] = React.useState<{ station: string; res: any } | null>(null);

  return (
    <>
      <PageHeader
        eyebrow="Produce"
        title="Content factory"
        description="Work one sub-strand at a time through the four stations. Each station is unlocked by the one before it, because its output is what the next station is grounded in."
        actions={
          <>
            <Select
              aria-label="Grade"
              value={effectiveGrade}
              onChange={(e) => setParam({ grade: e.target.value, subject: "", strand: "", substrand: "" })}
              style={{ width: "auto" }}
            >
              {(grades.data || []).map((g) => (
                <option key={g.slug || g.name} value={g.slug || g.name}>
                  {g.label || g.name}
                </option>
              ))}
            </Select>
            <Select
              aria-label="Subject"
              value={subject}
              onChange={(e) => setParam({ subject: e.target.value, strand: "", substrand: "" })}
              style={{ width: "auto" }}
            >
              <option value="">All subjects</option>
              {(subjects.data || []).map((s) => (
                <option key={s.name} value={s.name}>
                  {s.name}
                </option>
              ))}
            </Select>
          </>
        }
      />

      <QueryState query={grades} label="Loading grades" rows={2} />
      <QueryState query={progress} label="Loading sub-strands" rows={4} />

      {progress.data && !substrand && (
        <Card title="Choose a sub-strand" description={`${allSubstrands.length} available in this selection`}>
          {allSubstrands.length === 0 ? (
            <EmptyState
              title="No sub-strands here yet"
              description="Ingest a curriculum design for this grade before producing content."
            />
          ) : (
            <Table caption="Sub-strands">
              <thead>
                <tr>
                  <Th>Sub-strand</Th>
                  <Th>Subject</Th>
                  <Th>Strand</Th>
                  <Th numeric>Complete</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {allSubstrands.map((s) => (
                  <tr key={`${s.subject}-${s.strand}-${s.name}`}>
                    <Td>
                      <strong>{s.name}</strong>
                    </Td>
                    <Td>{s.subject}</Td>
                    <Td>{s.strand}</Td>
                    <Td numeric>{s.pct}%</Td>
                    <Td>
                      <Button
                        size="sm"
                        variant="primary"
                        onClick={() => setParam({ subject: s.subject, strand: s.strand, substrand: s.name })}
                      >
                        Open
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      )}

      {substrand && !selected && progress.data && (
        <EmptyState
          title={`"${substrand}" is not in this grade`}
          description="It may belong to a different grade or subject, or the curriculum design may have changed."
          action={<Button onClick={() => setParam({ substrand: "", strand: "" })}>Choose another</Button>}
          tone="warn"
        />
      )}

      {selected && (
        <>
          <Card
            title={selected.report.sub_strand_name}
            description={`${selected.subject} · ${selected.strand} · ${selected.report.allocated_hours}`}
            actions={
              <>
                <Badge tone={selected.report.production_ready ? "ok" : "warn"}>
                  {selected.report.production_ready ? "Production ready" : "In progress"}
                </Badge>
                <Button size="sm" onClick={() => setParam({ substrand: "", strand: "" })}>
                  Change sub-strand
                </Button>
              </>
            }
          >
            <Stack gap="var(--s3)">
              <ProgressBar value={selected.report.overall_percentage} height={10} label="Sub-strand completion" />
              <Grid min="150px" gap="var(--s3)">
                {(["notes", "visuals", "practicals", "questions", "slo_coverage"] as const).map((k) => {
                  const d: any = (selected.report as any)[k];
                  const gen = d.generated_count ?? d.generated_hours ?? 0;
                  const req = d.required_count ?? d.required_hours ?? 0;
                  return (
                    <div key={k} style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                      <Label>{k.replace(/_/g, " ")}</Label>
                      <span style={{ fontVariantNumeric: "tabular-nums", fontWeight: 600 }}>
                        {gen}/{req}
                      </span>
                      <ProgressBar value={d.percentage} height={5} label={k} />
                    </div>
                  );
                })}
              </Grid>
            </Stack>
          </Card>

          <Stack gap="var(--s3)">
            {STATIONS.map((station) => {
              const dim: any = (selected.report as any)[station.id];
              const done = dim.percentage >= 100;
              const gate = station.requires ? (selected.report as any)[station.requires] : null;
              const locked = Boolean(gate && gate.percentage <= 0);
              const gateLabel = STATIONS.find((s) => s.id === station.requires)?.label;

              return (
                <Card
                  key={station.id}
                  accent={done ? "ok" : locked ? undefined : "accent"}
                  title={
                    <div style={{ display: "flex", alignItems: "center", gap: "var(--s3)" }}>
                      <span
                        aria-hidden="true"
                        style={{
                          width: "1.6rem",
                          height: "1.6rem",
                          display: "grid",
                          placeItems: "center",
                          borderRadius: "50%",
                          fontSize: "var(--text-xs)",
                          fontWeight: 700,
                          background: done ? "var(--ok)" : locked ? "var(--surface-3)" : "var(--accent)",
                          color: done || !locked ? "var(--accent-ink)" : "var(--ink-3)",
                        }}
                      >
                        {done ? "✓" : station.n}
                      </span>
                      <h3>{station.label}</h3>
                      {done && <Badge tone="ok">complete</Badge>}
                      {locked && <Badge tone="neutral">locked</Badge>}
                    </div>
                  }
                  description={station.blurb}
                  actions={
                    <Button
                      variant={done ? "secondary" : "primary"}
                      size="sm"
                      disabled={locked}
                      loading={running === station.id}
                      onClick={() => runStation(station)}
                      title={
                        locked
                          ? `Generate ${gateLabel?.toLowerCase()} first — this station is grounded in it.`
                          : undefined
                      }
                    >
                      {done ? "Generate more" : "Generate"}
                    </Button>
                  }
                >
                  <Stack direction="row" gap="var(--s4)" align="center" wrap>
                    <div style={{ flex: 1, minWidth: "14rem" }}>
                      <ProgressBar value={dim.percentage} label={station.label} />
                    </div>
                    <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", whiteSpace: "nowrap" }}>
                      {dim.generated_count ?? dim.generated_hours ?? 0} of{" "}
                      {dim.required_count ?? dim.required_hours ?? 0} produced
                      {dim.estimated ? " (requirement estimated)" : ""}
                    </span>
                  </Stack>

                  {locked && (
                    <p
                      style={{
                        marginTop: "var(--s3)",
                        fontSize: "var(--text-sm)",
                        color: "var(--ink-2)",
                        background: "var(--surface-2)",
                        padding: "var(--s3)",
                        borderRadius: "var(--radius-sm)",
                      }}
                    >
                      Blocked: this station is grounded in the {gateLabel?.toLowerCase()}, and none exist yet
                      for this sub-strand. Generating now would produce content with nothing to be accurate
                      against.
                    </p>
                  )}

                  {lastResult?.station === station.id && <StationResult result={lastResult.res} />}
                </Card>
              );
            })}
          </Stack>
        </>
      )}
    </>
  );
}

/**
 * Surfaces what the quality gate actually found. The gate has always returned
 * per-metric scores, risk flags and both auditors' reasoning; the previous
 * console discarded all of it and showed a spinner then a success message.
 */
function StationResult({ result }: { result: any }) {
  const gate = result?.quality_gate;
  const rejected: any[] = result?.rejected || [];

  if (!gate && !rejected.length) return null;

  return (
    <div style={{ marginTop: "var(--s4)", display: "flex", flexDirection: "column", gap: "var(--s3)" }}>
      {rejected.length > 0 && (
        <div
          style={{
            border: "1px solid var(--danger)",
            background: "var(--danger-wash)",
            borderRadius: "var(--radius-sm)",
            padding: "var(--s3)",
          }}
        >
          <strong style={{ color: "var(--danger)", fontSize: "var(--text-sm)" }}>
            {rejected.length} item{rejected.length === 1 ? "" : "s"} rejected before saving
          </strong>
          <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "1.1rem", fontSize: "var(--text-sm)" }}>
            {rejected.slice(0, 5).map((r, i) => (
              <li key={i} style={{ marginBottom: "4px" }}>
                <span className="mono">{r.display_label || `#${r.index}`}</span> — {r.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {gate && (
        <div
          style={{
            border: `1px solid var(--${gate.passed ? "ok" : "warn"})`,
            background: `var(--${gate.passed ? "ok" : "warn"}-wash)`,
            borderRadius: "var(--radius-sm)",
            padding: "var(--s3)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--s2)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "var(--s2)", flexWrap: "wrap" }}>
            <Badge tone={gate.passed ? "ok" : "warn"}>{gate.passed ? "gate passed" : "needs revision"}</Badge>
            <strong style={{ fontSize: "var(--text-sm)" }}>{gate.overall_score}/100</strong>
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>{gate.summary_message}</span>
          </div>

          {gate.blocking_reasons?.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "var(--text-sm)", color: "var(--danger)" }}>
              {gate.blocking_reasons.map((r: string, i: number) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          )}

          {gate.reviewer?.feedback?.length > 0 && (
            <details>
              <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)", fontWeight: 550 }}>
                Measured criteria, weakest first
              </summary>
              <Table caption="Quality criteria">
                <thead>
                  <tr>
                    <Th>Criterion</Th>
                    <Th numeric>Score</Th>
                    <Th>How it was measured</Th>
                  </tr>
                </thead>
                <tbody>
                  {gate.reviewer.feedback.slice(0, 12).map((f: any, i: number) => (
                    <tr key={i}>
                      <Td>
                        <Badge
                          tone={
                            f.status === "pass" ? "ok" : f.status === "warn" ? "warn" : f.status === "pending" ? "neutral" : "danger"
                          }
                        >
                          {f.status}
                        </Badge>{" "}
                        {f.aspect.replace(/_/g, " ")}
                      </Td>
                      <Td numeric>{f.status === "pending" ? "—" : f.score.toFixed(2)}</Td>
                      <Td style={{ color: "var(--ink-2)" }}>{f.comment}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
