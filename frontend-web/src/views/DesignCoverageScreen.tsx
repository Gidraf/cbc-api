import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Card,
  EmptyState,
  PageHeader,
  Select,
  Stack,
} from "../ui/components";
import { DesignCoverage } from "../ui/DesignCoverage";
import { gradeOptionLabel, useGrades, useSubjects } from "../lib/queries";

/**
 * What of the KICD design the questions actually cover.
 *
 * Its own screen rather than a panel in the content factory. The factory is
 * where somebody GENERATES — one sub-strand at a time, with a station open and
 * a run in flight — and this is the question they ask afterwards, across a
 * whole subject: what is still not covered. Two different jobs, and putting
 * the second inside the first meant scrolling past a run to reach it.
 *
 * `/curriculum-coverage` counts what has been PRODUCED. This names what is
 * MISSING, element by element, which is the only version of the number
 * somebody selling the content can act on.
 */
export function DesignCoverageScreen() {
  const [params, setParams] = useSearchParams();
  const grade = params.get("grade") || "";
  const subject = params.get("subject") || "";
  const strand = params.get("strand") || "";

  const grades = useGrades();
  const effectiveGrade = grade || grades.data?.[0]?.slug || grades.data?.[0]?.name || "";
  const subjects = useSubjects(effectiveGrade);

  function setParam(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    // A subject from the previous grade is not a subject of this one, and a
    // strand of the previous subject is not a strand of this one.
    if (key === "grade") {
      next.delete("subject");
      next.delete("strand");
    }
    if (key === "subject") next.delete("strand");
    setParams(next, { replace: true });
  }

  return (
    <Stack gap="var(--s4)">
      <PageHeader
        title="KICD design coverage"
        description={
          "Every outcome, inquiry question, competency, value, required diagram " +
          "and experiment the design states — and which of them has a question " +
          "against it. A sub-strand can read 100% produced with three of its " +
          "five outcomes never assessed."
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
            <Select
              aria-label="Subject"
              value={subject}
              onChange={(e) => setParam("subject", e.target.value)}
              style={{ width: "auto" }}
            >
              <option value="">Choose a subject…</option>
              {(subjects.data || []).map((s: any) => (
                <option key={s.name || s} value={s.name || s}>
                  {s.name || s}
                </option>
              ))}
            </Select>
          </>
        }
      />

      {strand && (
        <Card>
          <Stack direction="row" gap="var(--s2)" align="center" wrap>
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              Showing one strand: <b>{strand}</b>
            </span>
            <Link to={`/design-coverage?grade=${encodeURIComponent(effectiveGrade)}&subject=${encodeURIComponent(subject)}`}>
              Show the whole subject
            </Link>
          </Stack>
        </Card>
      )}

      {!subject ? (
        <EmptyState
          title="Choose a subject"
          description="Coverage is read against each sub-strand's own design, so it is reported one subject at a time."
        />
      ) : (
        <DesignCoverage
          grade={effectiveGrade}
          subject={subject}
          strand={strand || undefined}
        />
      )}
    </Stack>
  );
}
