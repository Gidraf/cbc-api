import React from "react";
import { Link } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Grid,
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
import { gradeOptionLabel, useCostSummary, useDailyTarget, useGrades, useProgress } from "../lib/queries";

export function Overview() {
  const grades = useGrades();
  const [grade, setGrade] = React.useState("");
  const effectiveGrade = grade || grades.data?.[0]?.slug || grades.data?.[0]?.name || "";

  const progress = useProgress(effectiveGrade);
  const costs = useCostSummary();
  const target = useDailyTarget();

  const report = progress.data;
  // The API omits these on some payloads, so read them through a default
  // rather than assuming the shape the type describes.
  const recommendations = report?.focus_recommendations ?? [];
  const subjects = report?.subjects ?? [];
  const totalSubstrands = report?.total_substrands ?? 0;
  const hasCurriculum = totalSubstrands > 0;
  const overallPct = report?.overall_grade_percentage;
  const todayPct = target.data?.target_count
    ? Math.round((target.data.completed_count / target.data.target_count) * 100)
    : 0;

  return (
    <>
      <PageHeader
        eyebrow="Produce"
        title="Overview"
        description="Where the factory stands today, and the single most useful thing to do next."
        actions={
          <Select
            aria-label="Grade"
            value={effectiveGrade}
            onChange={(e) => setGrade(e.target.value)}
            style={{ width: "auto" }}
          >
            {(grades.data || []).map((g) => (
              <option key={g.slug || g.name} value={g.slug || g.name}>
                {gradeOptionLabel(g)}
              </option>
            ))}
          </Select>
        }
      />

      <Grid min="200px">
        <Stat
          label="Today's target"
          value={`${target.data?.completed_count ?? 0}/${target.data?.target_count ?? 0}`}
          progress={todayPct}
          sub={`${target.data?.approved_count ?? 0} approved, ${target.data?.rejected_count ?? 0} rejected`}
        />
        <Stat
          label={report?.grade_label ? `${report.grade_label} coverage` : "Grade coverage"}
          value={overallPct === undefined ? "—" : `${overallPct}%`}
          progress={overallPct ?? 0}
          sub={
            !report
              ? undefined
              : hasCurriculum
              ? `${report.completed_substrands ?? 0} of ${totalSubstrands} sub-strands complete`
              : "No curriculum ingested for this grade"
          }
        />
        <Stat
          label="SLO coverage"
          value={report ? `${report.slo_coverage_totals?.percentage ?? 0}%` : "—"}
          progress={report?.slo_coverage_totals?.percentage ?? 0}
          sub="Learning outcomes with at least one question"
        />
        <Stat
          label="Spend to date"
          value={`$${(costs.data?.total_cost_usd ?? 0).toFixed(2)}`}
          sub={`${(costs.data?.total_tokens ?? 0).toLocaleString()} tokens`}
        />
      </Grid>

      <QueryState query={grades} label="Loading grades" rows={2} />
      {grades.data?.length === 0 && (
        <EmptyState
          title="No curriculum ingested yet"
          description="The factory needs at least one KICD curriculum design before it can produce or measure anything."
          tone="warn"
        />
      )}

      <QueryState query={progress} label="Loading overview" rows={4} />

      {report && (
        <Grid min="360px" gap="var(--s5)">
          <Card
            title="Next actions"
            description="Highest-leverage work first, respecting the station dependency order."
            actions={
              <Link to="/coverage">
                <Button size="sm">Full coverage</Button>
              </Link>
            }
          >
            {recommendations.length === 0 ? (
              hasCurriculum ? (
                <EmptyState title="Nothing outstanding" description="This grade is fully produced." />
              ) : (
                <EmptyState
                  title="No curriculum ingested"
                  description="Ingest this grade's KICD curriculum designs before anything can be produced."
                  tone="warn"
                />
              )
            ) : (
              <Stack gap="var(--s2)">
                {recommendations.slice(0, 6).map((rec, i) => (
                  <Link
                    key={i}
                    to={
                      `/factory?grade=${encodeURIComponent(effectiveGrade)}` +
                      `&subject=${encodeURIComponent(rec.subject)}` +
                      `&strand=${encodeURIComponent(rec.strand)}` +
                      `&substrand=${encodeURIComponent(rec.sub_strand)}`
                    }
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "var(--s3)",
                      padding: "var(--s3)",
                      border: "1px solid var(--line-2)",
                      borderRadius: "var(--radius-sm)",
                      textDecoration: "none",
                      color: "inherit",
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
                    <span style={{ flex: 1, fontSize: "var(--text-sm)" }}>{rec.message}</span>
                    <span aria-hidden="true" style={{ color: "var(--ink-3)" }}>→</span>
                  </Link>
                ))}
              </Stack>
            )}
          </Card>

          <Card title="Coverage by subject" description="Weighted by allocated teaching hours.">
            {subjects.length === 0 ? (
              <EmptyState title="No curriculum designs" description="Ingest a design for this grade first." />
            ) : (
              <Table caption="Subject coverage">
                <thead>
                  <tr>
                    <Th>Subject</Th>
                    <Th>Progress</Th>
                    <Th numeric>Complete</Th>
                  </tr>
                </thead>
                <tbody>
                  {[...subjects]
                    .sort((a, b) => a.subject_percentage - b.subject_percentage)
                    .map((s) => (
                      <tr key={s.subject}>
                        <Td>
                          <Link to={`/coverage?grade=${encodeURIComponent(effectiveGrade)}&subject=${encodeURIComponent(s.subject)}`}>
                            {s.subject}
                          </Link>
                          {s.estimated && (
                            <span style={{ marginLeft: "var(--s2)" }}>
                              <Badge tone="warn">est</Badge>
                            </span>
                          )}
                        </Td>
                        <Td>
                          <ProgressBar value={s.subject_percentage} label={`${s.subject} coverage`} />
                        </Td>
                        <Td numeric>
                          {s.completed_substrands}/{s.total_substrands}
                        </Td>
                      </tr>
                    ))}
                </tbody>
              </Table>
            )}
          </Card>
        </Grid>
      )}
    </>
  );
}
