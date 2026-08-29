import React from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, Card, CopyButton, EmptyState, ErrorNotice, Grid, Label, LoadingBlock, PageHeader, ProgressBar, QueryState, Select, Stack, Table, Td, Th, useToast } from "../ui/components";
import { Link } from "react-router-dom";
import { CurriculumStructure } from "./CurriculumStructure";
import { HourWorkbench } from "./HourWorkbench";
import { PromptInspector, type Inspection } from "./PromptInspector";
import { QueuePanel } from "./QueuePanel";
import { ResetPanel } from "./ResetPanel";
import { VersionReview } from "./VersionReview";
import { stationToText } from "../lib/serialize";
import { useArtifacts, useDesigns, useInspect, profileFor, useProfiles, gradeOptionLabel, subjectOptionLabel, useApi, useGrades, useProgress, useQueuedJob, useSavedSubstrands, useStoredStructure, useSubjects, STATION_KIND } from "../lib/queries";
import { useQueryClient } from "@tanstack/react-query";

/**
 * The production stations have a real dependency order: notes ground the
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
    id: "media",
    n: 3,
    // A diagram is SVG: generated as code and editable afterwards. A photo and
    // a video are neither, so what this station produces is the prompt, the
    // shot list and the alt text. The asset is made elsewhere and uploaded back.
    label: "Photos & videos",
    endpoint: "/api/v1/curriculum/factory/generate-media-prompts",
    blurb: "Prompts and shot lists for photographs and video, to produce and upload back.",
    requires: "notes",
  },
  {
    id: "simulations",
    n: 4,
    // A diagram is a still picture of a thing; a simulation is the thing
    // behaving. What this station produces is the build brief — the model, the
    // controls, the acceptance criteria — not the code.
    label: "Interactive simulations",
    endpoint: "/api/v1/curriculum/factory/generate-simulations",
    blurb: "Build briefs for simulations a learner manipulates: pull a spring, push a piston, run a cross.",
    requires: "notes",
  },
  {
    id: "practicals",
    n: 5,
    label: "Activities & experiments",
    endpoint: "/api/v1/curriculum/factory/plan-activities",
    blurb: "Hands-on tasks with the safety guidance their materials require.",
    requires: "notes",
  },
  {
    id: "questions",
    n: 6,
    label: "Questions",
    endpoint: "/api/v1/questions/factory/generate-batch",
    blurb: "Assessment items derived from the notes, diagrams and practicals above.",
    requires: "visuals",
  },
] as const;

/** Which artifact kind each station files. A station that does not version its
 *  output yet is absent rather than mapped to a guess. */
const STATION_ARTIFACT_KIND: Record<string, string | undefined> = {
  notes: "notes",
  visuals: "diagram",
  simulations: "simulation",
  practicals: "activity",
};

/**
 * The versions this station filed for this sub-strand, and their review.
 *
 * The artifacts are found by asking the server, not by rebuilding its identity
 * rule here: a client-side copy of that rule reports "no versions yet" for
 * content that exists the moment the two drift.
 */
function StationVersions({
  kind,
  grade,
  subject,
  subStrand,
}: {
  kind: string;
  grade: string;
  subject: string;
  subStrand: string;
}) {
  const artifacts = useArtifacts({ grade, subject, kind, sub_strand: subStrand });
  const rows = artifacts.data?.artifacts || [];
  const [chosen, setChosen] = React.useState("");

  const active = chosen || rows[0]?.artifact_id || "";

  if (artifacts.isLoading) return <LoadingBlock rows={3} label="Loading versions" />;
  if (!rows.length) {
    return (
      <EmptyState
        title="Nothing filed yet"
        description="A version is filed each time this station generates. Generate once, then review and approve it here."
      />
    );
  }

  return (
    <Stack gap="var(--s3)">
      {rows.length > 1 && (
        <Stack direction="row" gap="var(--s2)" wrap>
          {rows.map((a: any) => (
            <Button
              key={a.artifact_id}
              size="sm"
              variant={a.artifact_id === active ? "primary" : "ghost"}
              onClick={() => setChosen(a.artifact_id)}
            >
              {a.title || a.sub_strand_name || `v${a.version}`}
            </Button>
          ))}
        </Stack>
      )}
      <VersionReview artifactId={active} />
    </Stack>
  );
}

/** One station's coverage, or a zeroed stand-in when coverage does not measure it.
 *
 *  Stations and coverage dimensions are not the same list and never will be:
 *  a station is added the moment its generator exists, and weighting it in
 *  coverage is a separate decision with its own consequences. Reading the
 *  dimension directly meant adding the simulations station crashed the whole
 *  screen with "Cannot read properties of undefined". */
function dimensionFor(report: Record<string, any>, id: string) {
  const found = report?.[id];
  if (found && typeof found === "object") return found;
  return {
    generated_count: 0,
    required_count: 0,
    remaining_count: 0,
    percentage: 0,
    estimated: true,
    unmeasured: true,
  };
}

/** A coverage report for a sub-strand nothing has been produced for yet.
 *
 *  Shaped exactly like a measured one so every station renders and reads zero,
 *  rather than the whole factory disappearing because coverage has not run. */
function emptyReport(row: Record<string, any>) {
  const dimension = { generated_count: 0, required_count: 0, remaining_count: 0,
                      percentage: 0, estimated: true };
  return {
    sub_strand_name: String(row.sub_strand_name || ""),
    allocated_hours: String(row.allocated_hours || "not stated"),
    overall_percentage: 0,
    approved_percentage: 0,
    production_ready: false,
    approved: false,
    notes: { ...dimension, generated_hours: 0, required_hours: 0 },
    visuals: { ...dimension },
    media: { ...dimension },
    simulations: { ...dimension },
    practicals: { ...dimension },
    questions: { ...dimension },
    slo_coverage: { ...dimension },
    unmeasured: true,
  };
}

/** What the worker's review loop did: generate, save, review, revise, save.
 *
 *  Worth showing rather than burying. A station that scored 76 and then 89 is a
 *  different thing from one that scored 89 first time, and an operator deciding
 *  whether to trust the output needs to see which it was. */
function ReviewCycles({ report }: { report: any }) {
  const cycles: any[] = report?.cycles || [];
  if (!cycles.length) return null;

  const why: Record<string, string> = {
    approved: "the gate passed",
    no_improvement: "the next pass did not improve on the last",
    max_cycles: "it ran out of cycles",
    no_actionable_findings: "the gate failed but named nothing to fix",
    generation_failed: "a generation failed",
  };

  return (
    <div
      style={{
        marginTop: "var(--s3)",
        padding: "var(--s3)",
        background: "var(--surface-2)",
        borderRadius: "var(--radius-sm)",
        fontSize: "var(--text-sm)",
      }}
    >
      <Stack direction="row" gap="var(--s2)" align="center" wrap>
        <strong>
          {cycles.length} review cycle{cycles.length === 1 ? "" : "s"}
        </strong>
        {report.final_passed ? (
          <Badge tone="ok">passed at {report.best_score}/100</Badge>
        ) : (
          <Badge tone="warn">best {report.best_score}/100, not passed</Badge>
        )}
        <span style={{ color: "var(--ink-3)" }}>
          Stopped because {why[report.stopped_because] || report.stopped_because}.
        </span>
      </Stack>

      <ul style={{ margin: "var(--s2) 0 0", paddingLeft: "1.2em" }}>
        {cycles.map((c) => (
          <li key={c.cycle}>
            Cycle {c.cycle}: <strong>{c.score}/100</strong>
            {c.version ? ` — filed as version ${c.version}` : ""}
            {c.weakest ? `, weakest ${String(c.weakest).replace(/_/g, " ")}` : ""}
            {c.error ? ` — failed: ${c.error}` : ""}
            {c.directives_sent?.length ? (
              <div style={{ color: "var(--ink-3)" }}>
                Sent back to the generator: {c.directives_sent.join("; ")}
              </div>
            ) : null}
          </li>
        ))}
      </ul>

      {report.note && (
        <p style={{ marginTop: "var(--s2)", marginBottom: 0 }}>
          <strong>{report.note}</strong>
        </p>
      )}
    </div>
  );
}

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
  React.useEffect(() => {
    setNotes(null);
    setLastResult(null);
  }, [substrand, subject, effectiveGrade]);


  // Coverage measures what has been produced. It is not the list of what
  // EXISTS to produce for, and using it as one meant a grade whose coverage
  // came back empty had no selectable sub-strand — so no stations rendered, and
  // notes and media were unreachable while the sub-strands sat in the database.
  const saved = useSavedSubstrands(effectiveGrade, subject || undefined);

  const fromProgress = React.useMemo(() => {
    const out: { subject: string; strand: string; name: string; pct: number; report: any }[] = [];
    for (const subj of progress.data?.subjects ?? []) {
      if (subject && subj.subject !== subject) continue;
      for (const st of subj.strands) {
        for (const ss of st.substrands) {
          out.push({
            subject: subj.subject,
            strand: st.strand_name,
            name: ss.sub_strand_name,
            pct: ss.overall_percentage,
            report: ss,
          });
        }
      }
    }
    return out;
  }, [progress.data, subject]);

  const allSubstrands = React.useMemo(() => {
    if (fromProgress.length) return fromProgress;
    // Nothing measured yet: offer what is stored, with a zeroed report so the
    // stations render and say honestly that nothing has been produced.
    return (saved.data || []).map((row: any) => ({
      subject: String(row.subject || ""),
      strand: String(row.strand_name || ""),
      name: String(row.sub_strand_name || ""),
      pct: 0,
      report: emptyReport(row),
    }));
  }, [fromProgress, saved.data]);

  // Which strands still have nothing under them. Without this the operator has
  // to remember which of five they have done, and the builder that would tell
  // them was the thing that disappeared.
  // What is actually ingested, so the empty state can say which of the three
  // situations the operator is in rather than assuming the worst one.
  const designs = useDesigns();
  const designsForGrade = React.useMemo(() => {
    const want = effectiveGrade.replace("grade-", "").toLowerCase();
    return (designs.data || []).filter(
      (d) => String(d.grade || "").replace("grade-", "").toLowerCase() === want
    ).length;
  }, [designs.data, effectiveGrade]);

  const structure = useStoredStructure(effectiveGrade, subject);
  const strandsRemaining = React.useMemo(() => {
    const strands = structure.data?.strands || [];
    return strands.filter((s) => (s.sub_strands || []).length === 0).length;
  }, [structure.data]);

  const selected = React.useMemo(() => {
    if (!substrand) return null;
    const hit = allSubstrands.find((s) => s.name === substrand);
    return hit ? { subject: hit.subject, strand: hit.strand, report: hit.report } : null;
  }, [allSubstrands, substrand]);

  /** Queue a station and follow it, rather than holding the browser open on it.
   *
   *  A station used to generate on the HTTP request that asked for it. Notes
   *  take about a minute, media longer — so a refresh, a navigation, a proxy
   *  timeout or a deploy threw away a run that was already paid for, and left
   *  nothing behind saying what had been running.
   *
   *  Now the request records the work and returns. Celery runs it in another
   *  process, the job id is kept in the URL, and reopening this page picks the
   *  same job back up — finished, mid-flight, or failed with its reason. */
  async function runStation(station: (typeof STATIONS)[number]) {
    if (!selected) return;
    const kind = STATION_KIND[station.id];
    if (!kind) return;

    setRunning(station.id);
    try {
      const res = await api<{ jobs?: { job_id: string }[]; queued: number }>(
        "/api/v1/curriculum/factory/queue",
        {
          method: "POST",
          body: JSON.stringify({
            grade: effectiveGrade,
            subject: selected.subject,
            strand: selected.strand,
            sub_strands: [substrand],
            kinds: [kind],
          }),
        }
      );

      const jobId = res.jobs?.[0]?.job_id || "";
      if (!jobId) {
        toast(`${station.label} could not be queued.`, "danger");
        return;
      }
      // In the URL, not in component state: that is what makes it survive the
      // refresh, and what lets the operator send somebody the link.
      setParam({ job: jobId, station: station.id });
      toast(`${station.label} queued. You can leave this page.`, "ok");
      qc.invalidateQueries({ queryKey: ["queue"] });
    } catch (err) {
      toast(err instanceof Error ? err.message : `${station.label} failed.`, "danger");
    } finally {
      setRunning(null);
    }
  }

  // The job this page is watching, and the station that queued it. Both live
  // in the URL so a refresh, a navigation away and back, or a link pasted to a
  // colleague all land on the same running or finished work.
  const watchedJob = params.get("job") || "";
  const watchedStation = params.get("station") || "";
  const job = useQueuedJob(watchedJob || null);
  const jobRunning = job.data?.status === "queued" || job.data?.status === "running";

  // A finished job's result is read back into the station panel, so the output
  // appears exactly where a synchronous run used to put it.
  React.useEffect(() => {
    const data = job.data;
    if (!data || data.status !== "done" || !watchedStation) return;
    setLastResult({ station: watchedStation, res: data.result });
    if (watchedStation === "notes") setNotes(data.result?.notes ?? data.result);
    qc.invalidateQueries({ queryKey: ["progress"] });
    qc.invalidateQueries({ queryKey: ["bundle"] });
  }, [job.data, watchedStation, qc]);

  // Changing sub-strand abandons the job that belonged to the old one, rather
  // than leaving the console showing another sub-strand's output under this
  // one's heading.
  React.useEffect(() => {
    if (watchedJob && job.data && job.data.sub_strand !== substrand) {
      setParam({ job: "", station: "" });
    }
  }, [substrand, job.data, watchedJob]);

  const [lastResult, setLastResult] = React.useState<{ station: string; res: any } | null>(null);
  // The notes are the source for every per-hour asset, so they are held for the
  // workbench rather than only shown as the last station's output.
  const [notes, setNotes] = React.useState<any>(null);
  // A subject with no skill still generates — with a generic profile. That is
  // invisible in the output, so say it before the tokens are spent.
  const profiles = useProfiles();
  const inspect = useInspect(effectiveGrade, subject);
  const [inspection, setInspection] = React.useState<Inspection | null>(null);
  const skill = profileFor(profiles.data, subject, effectiveGrade);

  return (
    <>
      <PageHeader
        eyebrow="Produce"
        title="Content factory"
        description="Work one sub-strand at a time through the production stations. Each station is unlocked by the one before it, because its output is what the next station is grounded in."
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
                  {gradeOptionLabel(g)}
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
                  {subjectOptionLabel(s)}
                </option>
              ))}
            </Select>
          </>
        }
      />

      <QueryState query={grades} label="Loading grades" rows={2} />
      <QueryState query={saved} label="Loading sub-strands" rows={4} />

      {/* A design can ingest cleanly and still yield no sub-strands when its
          layout defeats the text parser — Pre-Primary is organised by activity
          areas, not "STRAND 1.0" headings. Everything downstream is keyed on
          sub-strands, so offer a way to create them rather than a dead end. */}
      {subject && profiles.data && !skill && (
        <EmptyState
          title={`No teaching skill for ${subject}`}
          description="Notes, diagrams, activities and questions for this subject will be generated with a generic profile rather than its own expertise."
          tone="warn"
          action={
            <Link to="/skills">
              <Button size="sm">Define the skill</Button>
            </Link>
          }
        />
      )}

      {/* ONE element, always in the same position in the tree.

          Rendering the builder from a ternary — bare when nothing was saved,
          wrapped in <details> once something was — put it at two different
          positions, so the first save UNMOUNTED it and mounted a fresh one.
          Every draft it was holding for the other strands went with it:
          generate all five, save one, and the other four disappeared, with no
          error and no record they had existed.

          The wrapper is now constant and only its summary and open state
          change, so the builder keeps its identity — and its drafts — across
          the save that used to destroy them. */}
      {!substrand && !saved.isLoading && (
        <details
          open={allSubstrands.length === 0 || strandsRemaining > 0}
          style={{ marginBottom: "var(--s4)" }}
        >
          <summary
            style={{
              cursor: "pointer",
              fontSize: "var(--text-md)",
              fontWeight: 600,
              padding: "var(--s3)",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius)",
            }}
          >
            {allSubstrands.length === 0
              ? "Build the curriculum structure"
              : "Build more of the structure"}
            {allSubstrands.length === 0 ? null : strandsRemaining > 0 ? (
              <>
                {" "}
                <Badge tone="warn">
                  {strandsRemaining} strand{strandsRemaining === 1 ? "" : "s"} with
                  no sub-strands yet
                </Badge>
              </>
            ) : (
              <> <Badge tone="ok">every strand has sub-strands</Badge></>
            )}
          </summary>
          <div style={{ marginTop: "var(--s3)" }}>
            <CurriculumStructure
              grade={effectiveGrade}
              subject={subject}
              onSaved={() => {
                saved.refetch();
                progress.refetch();
              }}
            />
          </div>
        </details>
      )}

      {!substrand && subject && allSubstrands.length > 0 && (
        <QueuePanel grade={effectiveGrade} subject={subject} />
      )}

      {!substrand && (
        <Card
          title="Choose a sub-strand"
          description={`${allSubstrands.length} available in this selection`}
          actions={
            // Content generated by a pipeline that has since changed is worse
            // than no content: it looks finished and nothing flags it.
            <ResetPanel
              grade={effectiveGrade}
              subject={subject || undefined}
              label={subject ? `Clear ${subject}…` : "Clear this grade…"}
              onDone={() => {
                saved.refetch();
                progress.refetch();
              }}
            />
          }
        >
          {allSubstrands.length === 0 ? (
            /* This used to say "Ingest a curriculum design for this grade"
               whatever the reason was. With seven designs already ingested for
               the grade — the picker above literally reads 7/1 — that is a
               guess presented as a diagnosis, and it sends the operator to
               re-ingest something that is already there. Say which of the three
               things is actually true. */
            !subject ? (
              <EmptyState
                title="Choose a subject"
                description={`${designsForGrade} design(s) are ingested for this grade. Pick a learning area above to see its sub-strands, or build them below.`}
              />
            ) : designsForGrade > 0 ? (
              <EmptyState
                title={`No sub-strands stored for ${subject}`}
                description="The design is ingested, so there is nothing to re-ingest. Generate this subject's strands and sub-strands in the builder above, then save them."
              />
            ) : (
              <EmptyState
                title="No sub-strands here yet"
                description="No curriculum design has been ingested for this grade. Ingest one before producing content."
              />
            )
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

      {substrand && !selected && !saved.isLoading && (
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
              <ProgressBar
                value={selected.report.overall_percentage ?? 0}
                height={10}
                label="Sub-strand completion"
              />
              <Grid min="150px" gap="var(--s3)">
                {(["notes", "visuals", "media", "practicals", "questions", "slo_coverage"] as const).map((k) => {
                  const d: any = dimensionFor(selected.report, k);
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
              const dim: any = dimensionFor(selected.report, station.id);
              const done = dim.percentage >= 100;
              const gate = station.requires
                ? dimensionFor(selected.report, station.requires)
                : null;
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
                      disabled={locked || (jobRunning && watchedStation === station.id)}
                      loading={running === station.id || (jobRunning && watchedStation === station.id)}
                      onClick={() => runStation(station)}
                      title={
                        locked
                          ? `Generate ${gateLabel?.toLowerCase()} first — this station is grounded in it.`
                          : "Runs in the background. You can refresh or navigate away."
                      }
                    >
                      {jobRunning && watchedStation === station.id
                        ? job.data?.status === "running"
                          ? "Generating…"
                          : "Queued"
                        : done
                        ? "Generate more"
                        : "Generate"}
                    </Button>
                  }
                >
                  <Stack direction="row" gap="var(--s4)" align="center" wrap>
                    <div style={{ flex: 1, minWidth: "14rem" }}>
                      <ProgressBar value={dim.percentage} label={station.label} />
                    </div>
                    <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", whiteSpace: "nowrap" }}>
                      {dim.unmeasured ? (
                        "not counted in coverage yet"
                      ) : (
                        <>
                          {dim.generated_count ?? dim.generated_hours ?? 0} of{" "}
                          {dim.required_count ?? dim.required_hours ?? 0} produced
                          {dim.estimated ? " (requirement estimated)" : ""}
                        </>
                      )}
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

                  {watchedStation === station.id && jobRunning && (
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
                      {job.data?.status === "running"
                        ? `Generating ${station.label.toLowerCase()} in the background.`
                        : `Queued behind other work.`}{" "}
                      This runs in its own worker — refresh, navigate away or close
                      the tab and it carries on. The result appears here when it
                      lands, and this page reopens onto it.
                    </p>
                  )}

                  {watchedStation === station.id && job.data?.status === "failed" && (
                    <p
                      style={{
                        marginTop: "var(--s3)",
                        fontSize: "var(--text-sm)",
                        color: "var(--ink-2)",
                        background: "var(--surface-2)",
                        padding: "var(--s3)",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--warn-border, var(--line))",
                      }}
                    >
                      <strong>{station.label} failed</strong> after {job.data.attempts}{" "}
                      attempt{job.data.attempts === 1 ? "" : "s"}: {job.data.error}
                    </p>
                  )}

                  {watchedStation === station.id &&
                    job.data?.status === "done" &&
                    job.data.result?.review_cycles && (
                      <ReviewCycles report={job.data.result.review_cycles} />
                    )}

                  {lastResult?.station === station.id && (
                    <>
                      <Stack direction="row" justify="flex-end" gap="var(--s2)" style={{ marginTop: "var(--s2)" }}>
                        {station.id === "notes" && selected && (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={inspect.notes.isPending}
                            title="See the document, skill, research sources and compiled prompt"
                            onClick={async () =>
                              setInspection(
                                await inspect.notes.mutateAsync({
                                  strand: selected.strand,
                                  sub_strand: selected.report.sub_strand_name,
                                })
                              )
                            }
                          >
                            {inspect.notes.isPending ? "Loading…" : "Inspect prompt"}
                          </Button>
                        )}
                        <CopyButton
                          label={`Copy ${station.label.toLowerCase()}`}
                          title="Copy this station's output to check it in another model"
                          getText={() =>
                            stationToText(station.label, lastResult.res, {
                              grade: effectiveGrade,
                              subject: selected?.subject,
                              strand: selected?.strand,
                              "sub strand": selected?.report.sub_strand_name,
                            })
                          }
                        />
                      </Stack>
                      <StationResult result={lastResult.res} />
                    </>
                  )}

                  {/* Sending the operator to another screen to see what changed
                      and then back to decide made them hold the previous screen
                      in their head. The versions, their diffs, the layered
                      review and the labels all live here, beside the station
                      that produced them. */}
                  {selected && STATION_ARTIFACT_KIND[station.id] && (
                    <details style={{ marginTop: "var(--s3)" }}>
                      <summary
                        style={{
                          cursor: "pointer",
                          fontSize: "var(--text-sm)",
                          color: "var(--ink-2)",
                          fontWeight: 550,
                        }}
                      >
                        Versions, review and approval
                      </summary>
                      <div style={{ marginTop: "var(--s3)" }}>
                        <StationVersions
                          kind={STATION_ARTIFACT_KIND[station.id]!}
                          grade={effectiveGrade}
                          subject={selected.subject}
                          subStrand={selected.report.sub_strand_name}
                        />
                      </div>
                    </details>
                  )}
                </Card>
              );
            })}

            {/* Assets belong to an hour, not to the sub-strand as a whole:
                KICD allocates hours, the notes return one module per hour, and
                each diagram, photo prompt, video prompt, experiment and
                activity is produced against a specific hour. */}
            <PromptInspector
              inspection={inspection}
              onClose={() => setInspection(null)}
              // Inspecting is the step before generating. Closing the panel and
              // hunting for the station's own button loses the reason the
              // operator inspected in the first place.
              generating={running === "notes" || (jobRunning && watchedStation === "notes")}
              generateLabel="Generate the notes"
              onGenerate={async () => {
                const station = STATIONS.find((st) => st.id === "notes");
                if (!station) return;
                setInspection(null);
                await runStation(station);
              }}
              onAttached={async () => {
                if (!selected) return;
                setInspection(
                  await inspect.notes.mutateAsync({
                    strand: selected.strand,
                    sub_strand: selected.report.sub_strand_name,
                  })
                );
              }}
            />

            {notes && selected && (
              <HourWorkbench
                grade={effectiveGrade}
                subject={selected.subject}
                strand={selected.strand}
                subStrand={selected.report.sub_strand_name}
                notes={notes}
                allocatedHours={selected.report.allocated_hours}
              />
            )}
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
