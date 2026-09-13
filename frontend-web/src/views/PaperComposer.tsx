import React from "react";
import { Badge, Button, Card, ErrorNotice, Field, Input, Select, Stack, useToast } from "../ui/components";
import {
  gradeOptionLabel,
  subjectOptionLabel,
  useComposedPaper,
  useGrades,
  useOpenPaper,
  usePaperPdf,
  useStoredStructure,
  useSubjects,
  type PaperRequest,
} from "../lib/queries";

/**
 * A paper from the bank in one click: a topical test on a sub-strand, an
 * end-of-strand assessment, or an end-of-term examination over the subject.
 *
 * The composition is shown before anything opens — sections, marks, which
 * sub-strands it draws on, and whether the bank ran short — because a paper
 * that came back 23 marks of the 50 asked for is a paper the school pads by
 * hand, and the operator should know that before printing it.
 */
export function PaperComposer() {
  const toast = useToast();
  const grades = useGrades();
  const [grade, setGrade] = React.useState("");
  const [subject, setSubject] = React.useState("");
  const [kind, setKind] = React.useState<PaperRequest["kind"]>("topical");
  const [strand, setStrand] = React.useState("");
  const [subStrand, setSubStrand] = React.useState("");
  const [marks, setMarks] = React.useState(50);
  const [seed, setSeed] = React.useState("");
  const [drafts, setDrafts] = React.useState(true);
  const [title, setTitle] = React.useState("");

  const subjects = useSubjects(grade);
  const structure = useStoredStructure(grade, subject);
  const strands = structure.data?.strands || [];
  const subStrands = (strands.find((s) => s.strand_name === strand)?.sub_strands || []) as any[];

  const request: PaperRequest | null =
    grade && subject
      ? { grade, subject, kind, strand, sub_strand: subStrand, marks, seed, drafts, title }
      : null;
  const composed = useComposedPaper(request);
  const open = useOpenPaper();
  const pdf = usePaperPdf();

  async function show(opts: { answers?: boolean; withScheme?: boolean }) {
    if (!request) return;
    try {
      await open.mutateAsync({ request, ...opts });
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not open the paper.", "danger");
    }
  }

  async function download(opts: { answers?: boolean; withScheme?: boolean }) {
    if (!request) return;
    try {
      await pdf.mutateAsync({ request, ...opts });
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not render the PDF.", "danger");
    }
  }

  const paper = composed.data;
  const ready = Boolean(paper && paper.question_count > 0);

  return (
    <Card title="Compose a paper from the bank" accent="info">
      <Stack gap="var(--s4)">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: "var(--s3)",
          }}
        >
          <Field label="Grade">
            {(p) => (
              <Select {...p} value={grade} onChange={(e) => { setGrade(e.target.value); setSubject(""); setStrand(""); setSubStrand(""); }}>
                <option value="">Choose a grade</option>
                {(grades.data || []).map((g) => (
                  <option key={g.slug || g.name} value={g.slug || g.name}>{gradeOptionLabel(g)}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Subject">
            {(p) => (
              <Select {...p} value={subject} disabled={!grade} onChange={(e) => { setSubject(e.target.value); setStrand(""); setSubStrand(""); }}>
                <option value="">Choose a subject</option>
                {(subjects.data || []).map((s) => (
                  <option key={s.name} value={s.name}>{subjectOptionLabel(s)}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Paper" hint="Topical: one sub-strand. Strand: every sub-strand under it. Term: the whole subject.">
            {(p) => (
              <Select {...p} value={kind} onChange={(e) => setKind(e.target.value as PaperRequest["kind"])}>
                <option value="topical">Topical test</option>
                <option value="strand">End of strand</option>
                <option value="term">End of term</option>
              </Select>
            )}
          </Field>
          {kind !== "term" && (
            <Field label="Strand">
              {(p) => (
                <Select {...p} value={strand} disabled={!subject} onChange={(e) => { setStrand(e.target.value); setSubStrand(""); }}>
                  <option value="">Choose a strand</option>
                  {strands.map((s) => (
                    <option key={s.strand_id || s.strand_name} value={s.strand_name}>{s.strand_name}</option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          {kind === "topical" && (
            <Field label="Sub-strand">
              {(p) => (
                <Select {...p} value={subStrand} disabled={!strand} onChange={(e) => setSubStrand(e.target.value)}>
                  <option value="">Choose a sub-strand</option>
                  {subStrands.map((ss: any) => (
                    <option key={ss.sub_strand_name || ss.name} value={ss.sub_strand_name || ss.name}>
                      {ss.sub_strand_name || ss.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <Field label="Marks">
            {(p) => (
              <Input {...p} type="number" min={5} max={200} value={marks} onChange={(e) => setMarks(Number(e.target.value) || 50)} />
            )}
          </Field>
          <Field label="Set" hint="A different word deals a different paper from the same bank — Paper 1 and Paper 2 for two streams.">
            {(p) => <Input {...p} value={seed} placeholder="e.g. stream-b" onChange={(e) => setSeed(e.target.value)} />}
          </Field>
          <Field label="Title" hint="Leave blank for the standard title.">
            {(p) => <Input {...p} value={title} onChange={(e) => setTitle(e.target.value)} />}
          </Field>
        </div>

        <label style={{ display: "flex", gap: "var(--s2)", alignItems: "center", fontSize: "var(--text-sm)" }}>
          <input type="checkbox" checked={drafts} onChange={(e) => setDrafts(e.target.checked)} />
          Include unapproved items (the page is stamped DRAFT)
        </label>

        {composed.isError && <ErrorNotice error={composed.error} />}

        {paper && (
          <div
            style={{
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-sm)",
              padding: "var(--s3)",
              background: "var(--surface-2)",
              fontSize: "var(--text-sm)",
            }}
          >
            <Stack gap="var(--s2)">
              <Stack direction="row" gap="var(--s2)" wrap>
                <strong>{paper.title}</strong>
                <Badge tone={paper.shortfall ? "warn" : "ok"}>
                  {paper.total_marks} / {paper.asked_for} marks
                </Badge>
                <Badge tone="neutral">{paper.question_count} questions</Badge>
                <Badge tone="neutral">{paper.time_allowed}</Badge>
                {paper.has_drafts && <Badge tone="warn">contains drafts</Badge>}
                <span className="mono" style={{ color: "var(--ink-3)" }}>set {paper.seed}</span>
              </Stack>
              <div style={{ color: "var(--ink-2)" }}>
                {paper.sections.map((s) => (
                  <span key={s.letter} style={{ marginRight: "var(--s3)" }}>
                    {s.heading || "Questions"}: {s.count} for {s.marks} marks
                  </span>
                ))}
              </div>
              {Object.keys(paper.covers).length > 0 && (
                <div style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
                  Draws on {Object.entries(paper.covers).map(([name, n]) => `${name} (${n})`).join(", ")}
                </div>
              )}
              {paper.shortfall && (
                <div style={{ color: "var(--danger)" }}>Incomplete: {paper.shortfall}.</div>
              )}
            </Stack>
          </div>
        )}

        <Stack direction="row" gap="var(--s2)" wrap>
          <Button variant="primary" disabled={!ready || open.isPending} onClick={() => show({})}>
            Open paper
          </Button>
          <Button disabled={!ready || open.isPending} onClick={() => show({ answers: true })}>
            Marking scheme
          </Button>
          <Button disabled={!ready || open.isPending} onClick={() => show({ withScheme: true })}>
            Booklet (paper + scheme)
          </Button>
          <Button variant="ghost" disabled={!ready || pdf.isPending} onClick={() => download({ withScheme: true })}>
            {pdf.isPending ? "Rendering PDF…" : "Download booklet PDF"}
          </Button>
        </Stack>
      </Stack>
    </Card>
  );
}
