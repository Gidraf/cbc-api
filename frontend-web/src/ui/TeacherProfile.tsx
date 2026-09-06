import React from "react";
import { Badge, Button, ErrorNotice, LoadingBlock, Stack } from "./components";
import { useFitCheck, useTeacherProfile } from "../lib/queries";

/**
 * Who the content is written for, on both sides — and whether it landed.
 *
 * The learner register has always shaped every prompt and was only visible in
 * the prompt inspector. The person READING the guide was described nowhere at
 * all, which is how a Grade 9 lesson came to explain which key on a calculator
 * is the minus sign: correct for its learner, wrong for its reader.
 *
 * The check beside it answers the two questions counting cannot. Ten questions
 * all testing one outcome look identical to ten covering the sub-strand until
 * somebody reads them.
 */
export function TeacherProfile({
  grade,
  subject,
  artifactId,
}: {
  grade: string;
  subject?: string;
  artifactId?: string;
}) {
  const profile = useTeacherProfile(grade, subject);
  const fit = useFitCheck();

  if (profile.isPending) return <LoadingBlock rows={2} label="Reading the profile" />;
  if (profile.isError) return <ErrorNotice error={profile.error} />;
  const data = profile.data!;

  return (
    <Stack gap="var(--s3)" style={{ marginTop: "var(--s3)" }}>
      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: "var(--text-sm)" }}>Who this is written for</strong>
        <Badge tone="neutral">{data.level}</Badge>
        {artifactId && (
          <Button
            size="sm"
            variant="secondary"
            loading={fit.isPending}
            disabled={fit.isPending}
            title="Does it serve the outcomes, and is it pitched at this grade and this teacher?"
            onClick={() => fit.mutate({ artifact_id: artifactId })}
          >
            Check the fit
          </Button>
        )}
      </Stack>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
          gap: "var(--s3)",
        }}
      >
        <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "var(--s3)" }}>
          <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)", letterSpacing: "0.06em" }}>
            THE LEARNER
          </div>
          <div style={{ fontSize: "var(--text-sm)", marginTop: 3 }}>
            {data.learner.audience}, {data.learner.typical_ages}
          </div>
          <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", marginTop: 3 }}>
            {data.learner.literacy}
          </div>
          {data.learner.builds_on && (
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", marginTop: "var(--s2)" }}>
              Arrives having completed <b>{data.learner.builds_on}</b>; goes on to{" "}
              <b>{data.learner.prepares_for}</b>.
            </div>
          )}
        </div>

        <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "var(--s3)" }}>
          <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)", letterSpacing: "0.06em" }}>
            THE TEACHER READING IT
          </div>
          {data.teacher.known ? (
            <>
              <div style={{ fontSize: "var(--text-sm)", marginTop: 3 }}>
                {data.teacher.trained_as}
              </div>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)", marginTop: "var(--s2)" }}>
                Assumed, never explained
              </div>
              <ul style={{ margin: "2px 0 0", paddingLeft: "1.1rem", fontSize: "var(--text-sm)" }}>
                {data.teacher.assumed.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
              {data.teacher.never && (
                <div style={{ marginTop: "var(--s2)", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                  <b>Never:</b> {data.teacher.never}
                </div>
              )}
            </>
          ) : (
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", marginTop: 3 }}>
              This grade has no band, so the generators are told nothing about
              the reader — rather than told a guess.
            </div>
          )}
        </div>
      </div>

      {fit.error && <ErrorNotice error={fit.error} />}
      {fit.data && (
        <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius-sm)", padding: "var(--s3)" }}>
          <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
            <strong style={{ fontSize: "var(--text-sm)" }}>How it landed</strong>
            <Badge tone={fit.data.uncovered.length ? "warn" : "ok"}>
              {fit.data.coverage_percentage}% of outcomes served
            </Badge>
            {fit.data.level_status && (
              <Badge tone={fit.data.level_score >= 80 ? "ok" : "warn"}>
                pitch {fit.data.level_score}/100 · {fit.data.level_status}
              </Badge>
            )}
          </Stack>
          <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", marginTop: "var(--s2)" }}>
            {fit.data.says}
          </div>

          {fit.data.uncovered.length > 0 && (
            <>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)", marginTop: "var(--s2)" }}>
                Outcomes with nothing serving them
              </div>
              <ul style={{ margin: "2px 0 0", paddingLeft: "1.1rem", fontSize: "var(--text-sm)" }}>
                {fit.data.uncovered.map((u, i) => <li key={i}>{u}</li>)}
              </ul>
            </>
          )}

          {fit.data.level_feedback.length > 0 && (
            <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "1.1rem", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              {fit.data.level_feedback.map((f, i) => (
                <li key={i}>
                  <b>{f.aspect}</b> — {f.comment}
                </li>
              ))}
            </ul>
          )}

          {fit.data.errors.map((e, i) => (
            <div key={i} style={{ marginTop: "var(--s2)", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              {e}
            </div>
          ))}
        </div>
      )}
    </Stack>
  );
}
