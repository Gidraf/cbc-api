import React from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
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
  Stat,
  Table,
  Td,
  Th,
} from "../ui/components";
import { gradeOptionLabel, type SubstrandReport, useGrades, useProgress } from "../lib/queries";

const DIMENSIONS = [
  { key: "notes", label: "Lesson hours", noun: "hours" },
  { key: "visuals", label: "Diagrams", noun: "assets" },
  { key: "practicals", label: "Practicals", noun: "tasks" },
  { key: "questions", label: "Questions", noun: "items" },
  { key: "slo_coverage", label: "SLO coverage", noun: "outcomes" },
] as const;

function dimValue(d: any): { generated: number; required: number } {
  return {
    generated: d?.generated_count ?? d?.generated_hours ?? 0,
    required: d?.required_count ?? d?.required_hours ?? 0,
  };
}

export function Coverage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const grade = params.get("grade") || "";
  const subject = params.get("subject") || "";

  const grades = useGrades();
  const effectiveGrade = grade || grades.data?.[0]?.slug || grades.data?.[0]?.name || "";
  const progress = useProgress(effectiveGrade, subject || undefined);

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key === "grade") next.delete("subject");
    setParams(next, { replace: true });
  }

  const report = progress.data;
  const recommendations = report?.focus_recommendations ?? [];
  const subjects = report?.subjects ?? [];

  // A grade with no ingested designs has nothing to measure. That is a
  // different state from "everything is done", and saying the wrong one is
  // worse than saying nothing.
  const totalSubstrands = report?.total_substrands ?? 0;
  const hasCurriculum = totalSubstrands > 0;
  const overallPct = report?.overall_grade_percentage;
  const gradeLabel =
    report?.grade_label ||
    (grades.data || []).find((g) => (g.slug || g.name) === grade)?.label ||
    "Grade";

  return (
    <>
      <PageHeader
        eyebrow="Produce"
        title="Curriculum coverage"
        description={
          <>
            How much of each grade's curriculum has actually been produced. Requirements come from each
            sub-strand's own KICD design — allocated hours, required diagrams, experiments and learning
            outcomes — not from fixed targets. Anything marked <em>estimated</em> had no blueprint to
            measure against.
          </>
        }
        actions={
          <>
            <Select
              aria-label="Grade"
              value={effectiveGrade}
              onChange={(e) => setParam("grade", e.target.value)}
              style={{ width: "auto" }}
            >
              {(grades.data || []).map((g) => (
                <option key={g.slug || g.name} value={g.slug || g.name}>
                  {gradeOptionLabel(g)}
                </option>
              ))}
            </Select>
            <Button onClick={() => progress.refetch()} loading={progress.isFetching}>
              Refresh
            </Button>
          </>
        }
      />

      <QueryState query={grades} label="Loading grades" rows={3} />
      {grades.data?.length === 0 && (
        <EmptyState
          title="No grades available"
          description="No curriculum designs have been ingested yet, so there is nothing to measure. Ingest a KICD design from the advanced console first."
          tone="warn"
        />
      )}

      <QueryState query={progress} label="Calculating coverage" rows={5} />

      {report && (
        <>
          <Grid min="190px">
            <Stat
              label={`${gradeLabel} overall`}
              value={overallPct === undefined ? "—" : `${overallPct}%`}
              progress={overallPct ?? 0}
              sub={
                hasCurriculum
                  ? `${report.completed_substrands ?? 0} of ${totalSubstrands} sub-strands complete`
                  : "No curriculum ingested for this grade"
              }
            />
            {DIMENSIONS.map((d) => {
              const totals = (report as any)[`${d.key}_totals`];
              const { generated, required } = dimValue(totals);
              return (
                <Stat
                  key={d.key}
                  label={d.label}
                  value={`${totals?.percentage ?? 0}%`}
                  progress={totals?.percentage ?? 0}
                  sub={`${generated} of ${required} ${d.noun}`}
                />
              );
            })}
          </Grid>

          <MeasurementConfidence report={report} />

          <Card
            title="What to do next"
            description="Ordered by pipeline dependency — notes gate diagrams and activities, which gate questions."
          >
            {recommendations.length === 0 ? (
              hasCurriculum ? (
                <EmptyState title="Nothing outstanding" description="Every sub-strand in this grade is complete." />
              ) : (
                <EmptyState
                  title="No curriculum ingested"
                  description="Ingest this grade's KICD curriculum designs before coverage can be measured."
                  tone="warn"
                />
              )
            ) : (
              <Stack gap="var(--s2)">
                {recommendations.slice(0, 8).map((rec, i) => (
                  <div
                    key={i}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--s3)",
                      padding: "var(--s3)",
                      border: "1px solid var(--line-2)",
                      borderLeft: `3px solid var(--${
                        rec.priority === "high" ? "danger" : rec.priority === "medium" ? "warn" : rec.priority === "ready" ? "ok" : "info"
                      })`,
                      borderRadius: "var(--radius-sm)",
                      flexWrap: "wrap",
                    }}
                  >
                    <Badge
                      tone={
                        rec.priority === "high"
                          ? "danger"
                          : rec.priority === "medium"
                          ? "warn"
                          : rec.priority === "ready"
                          ? "ok"
                          : "info"
                      }
                    >
                      {rec.priority}
                    </Badge>
                    <span style={{ flex: 1, minWidth: "18rem", fontSize: "var(--text-sm)" }}>{rec.message}</span>
                    {rec.estimated_requirement && (
                      <Badge tone="warn" title="This requirement was estimated, not read from a blueprint">
                        estimated
                      </Badge>
                    )}
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() =>
                        navigate(
                          `/factory?grade=${encodeURIComponent(effectiveGrade)}` +
                            `&subject=${encodeURIComponent(rec.subject)}` +
                            `&strand=${encodeURIComponent(rec.strand)}` +
                            `&substrand=${encodeURIComponent(rec.sub_strand)}`
                        )
                      }
                    >
                      Open
                    </Button>
                  </div>
                ))}
              </Stack>
            )}
          </Card>

          {subjects.length === 0 ? (
            <EmptyState
              title="No curriculum designs for this grade"
              description="Ingest a KICD curriculum design before the factory can measure or produce anything."
            />
          ) : (
            subjects.map((subj) => (
              <SubjectPanel
                key={subj.subject}
                subject={subj}
                grade={effectiveGrade}
                onFilter={() => setParam("subject", subj.subject)}
              />
            ))
          )}
        </>
      )}
    </>
  );
}

function MeasurementConfidence({ report }: { report: any }) {
  const est = report.measurement_confidence?.substrands_with_estimated_requirements ?? 0;
  const measured = report.measurement_confidence?.substrands_measured_from_blueprint ?? 0;
  const total = est + measured;
  if (!total) return null;

  return (
    <Card
      accent={est ? "warn" : "ok"}
      title="Measurement confidence"
      description={`Roll-up weighted by allocated teaching hours, so a 10-hour sub-strand counts for more than a 2-hour one.`}
    >
      <Stack direction="row" gap="var(--s5)" wrap align="center">
        <div style={{ minWidth: "12rem", flex: 1 }}>
          <Label>Measured from blueprint</Label>
          <div style={{ display: "flex", alignItems: "baseline", gap: "var(--s2)" }}>
            <strong style={{ fontSize: "var(--text-xl)", fontVariantNumeric: "tabular-nums" }}>
              {measured}
            </strong>
            <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>of {total} sub-strands</span>
          </div>
          <ProgressBar value={(measured / total) * 100} tone={est ? "warn" : "ok"} label="Blueprint-measured" />
        </div>
        <p style={{ flex: 2, minWidth: "20rem", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          {report.measurement_confidence?.note}
        </p>
      </Stack>
      <div style={{ marginTop: "var(--s4)", display: "flex", gap: "var(--s3)", flexWrap: "wrap" }}>
        {Object.entries(report.weights || {}).map(([k, v]) => (
          <Badge key={k} tone="neutral" title={`${k} contributes ${Math.round(Number(v) * 100)}% of the score`}>
            {k.replace(/_/g, " ")} {Math.round(Number(v) * 100)}%
          </Badge>
        ))}
      </div>
    </Card>
  );
}

function SubjectPanel({
  subject,
  grade,
  onFilter,
}: {
  subject: any;
  grade: string;
  onFilter: () => void;
}) {
  const [open, setOpen] = React.useState(false);

  return (
    <Card
      title={
        <div style={{ display: "flex", alignItems: "center", gap: "var(--s3)", flexWrap: "wrap" }}>
          <h3>{subject.subject}</h3>
          <Badge tone={subject.subject_percentage >= 90 ? "ok" : subject.subject_percentage >= 40 ? "warn" : "danger"}>
            {subject.subject_percentage}%
          </Badge>
          {subject.estimated && <Badge tone="warn">partly estimated</Badge>}
        </div>
      }
      description={`${subject.completed_substrands} of ${subject.total_substrands} sub-strands production-ready`}
      actions={
        <>
          <Button size="sm" onClick={onFilter}>
            Focus
          </Button>
          <Button size="sm" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? "Hide sub-strands" : "Show sub-strands"}
          </Button>
        </>
      }
    >
      <ProgressBar value={subject.subject_percentage} height={10} label={`${subject.subject} coverage`} />

      {open && (
        <div style={{ marginTop: "var(--s4)", display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
          {subject.strands.map((strand: any) => (
            <div key={strand.strand_name}>
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: "var(--s2)",
                  gap: "var(--s3)",
                }}
              >
                <Label>{strand.strand_name}</Label>
                <span style={{ fontSize: "var(--text-sm)", fontVariantNumeric: "tabular-nums" }}>
                  {strand.strand_percentage}%
                </span>
              </div>

              <Table caption={`${strand.strand_name} sub-strand coverage`}>
                <thead>
                  <tr>
                    <Th>Sub-strand</Th>
                    <Th numeric>Hours</Th>
                    {DIMENSIONS.map((d) => (
                      <Th key={d.key} numeric>
                        {d.label}
                      </Th>
                    ))}
                    <Th numeric>Overall</Th>
                    <Th>Open</Th>
                  </tr>
                </thead>
                <tbody>
                  {strand.substrands.map((ss: SubstrandReport) => (
                    <tr key={ss.sub_strand_name}>
                      <Td>
                        <span style={{ fontWeight: 550 }}>{ss.sub_strand_name}</span>
                        {ss.estimated && (
                          <span style={{ marginLeft: "var(--s2)" }}>
                            <Badge tone="warn" title="No blueprint requirement; fallback used">
                              est
                            </Badge>
                          </span>
                        )}
                      </Td>
                      <Td numeric>{ss.weight_hours}</Td>
                      {DIMENSIONS.map((d) => {
                        const dim = (ss as any)[d.key];
                        const { generated, required } = dimValue(dim);
                        return (
                          <Td key={d.key} numeric>
                            <span
                              title={`${generated} of ${required} ${d.noun}`}
                              style={{
                                color:
                                  dim.percentage >= 100
                                    ? "var(--ok)"
                                    : dim.percentage >= 50
                                    ? "var(--ink)"
                                    : "var(--danger)",
                              }}
                            >
                              {generated}/{required}
                            </span>
                          </Td>
                        );
                      })}
                      <Td numeric>
                        <strong>{ss.overall_percentage}%</strong>
                      </Td>
                      <Td>
                        <Link
                          to={
                            `/factory?grade=${encodeURIComponent(grade)}` +
                            `&subject=${encodeURIComponent(subject.subject)}` +
                            `&strand=${encodeURIComponent(strand.strand_name)}` +
                            `&substrand=${encodeURIComponent(ss.sub_strand_name)}`
                          }
                        >
                          Open
                        </Link>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
