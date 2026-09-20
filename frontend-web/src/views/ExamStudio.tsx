import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Input,
  Modal,
  Select,
  Stack,
  Textarea,
  useToast,
} from "../ui/components";
import { useAuth } from "../lib/auth";
import {
  gradeOptionLabel,
  subjectOptionLabel,
  useBuilderKinds,
  useCreateDraft,
  useDeleteDraft,
  useDraft,
  useDraftBank,
  useDraftCandidates,
  useDraftItems,
  useDraftPdf,
  useDraftPreview,
  useDrafts,
  useDuplicateDraft,
  useFillDraft,
  useFreezeDraft,
  useGenerateForDraft,
  useGrades,
  useOverrideItem,
  usePatchDraft,
  useProviders,
  useReorderDraft,
  useReviewDraft,
  useStoredStructure,
  useSubjects,
  type DraftItemDetail,
  type DraftScope,
  type ExamDraft,
} from "../lib/queries";

/**
 * The exam studio: a paper built in sections on the left and shown, as it
 * will print, on the right. Setup → Scope → Questions → Design → Review →
 * Print. Every change re-renders the page through the platform's own
 * renderer, so the preview is the print.
 */
export function ExamStudio() {
  const { draftId = "" } = useParams();
  return draftId ? <Studio draftId={draftId} /> : <DraftList />;
}

// ── the list ────────────────────────────────────────────────────────────────

function DraftList() {
  const drafts = useDrafts();
  const create = useCreateDraft();
  const remove = useDeleteDraft();
  const duplicate = useDuplicateDraft();
  const grades = useGrades();
  const kinds = useBuilderKinds();
  const nav = useNavigate();
  const toast = useToast();
  const [grade, setGrade] = React.useState("");
  const [subject, setSubject] = React.useState("");
  const [kind, setKind] = React.useState("endterm");
  const [title, setTitle] = React.useState("");
  const [term, setTerm] = React.useState<number>(1);
  const subjects = useSubjects(grade);

  async function start() {
    if (!grade || !subject) return;
    try {
      const d = await create.mutateAsync({
        grade, subject, kind, title: title || defaultTitle(kind, term), term: kind === "topical" ? null : term,
        scope: kind === "topical" ? { mode: "topical" } : { mode: "smart" },
      });
      nav(`/studio/${d.draft_id}`);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not start the paper.", "danger");
    }
  }

  return (
    <Stack gap="var(--s5)">
      <Card title="Start a paper" description="Pick the grade and subject; name it what your school calls it. Everything else is chosen inside.">
        <Stack direction="row" gap="var(--s3)" wrap align="end">
          <label style={lbl}>Grade
            <Select value={grade} onChange={(e) => { setGrade(e.target.value); setSubject(""); }}>
              <option value="">Choose…</option>
              {(grades.data || []).map((g) => <option key={g.slug || g.name} value={g.slug || g.name}>{gradeOptionLabel(g)}</option>)}
            </Select>
          </label>
          <label style={lbl}>Subject
            <Select value={subject} disabled={!grade} onChange={(e) => setSubject(e.target.value)}>
              <option value="">Choose…</option>
              {(subjects.data || []).filter((s: any) => s.ingested !== false).map((s: any) => (
                <option key={s.name} value={s.name}>{subjectOptionLabel(s)}</option>
              ))}
            </Select>
          </label>
          <label style={lbl}>Kind
            <Select value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(kinds.data?.kinds || {}).map(([k, v]) => <option key={k} value={k}>{v || "Custom name"}</option>)}
            </Select>
          </label>
          {kind !== "topical" && (
            <label style={lbl}>Term
              <Select value={String(term)} onChange={(e) => setTerm(Number(e.target.value))}>
                <option value="1">Term 1</option><option value="2">Term 2</option><option value="3">Term 3</option>
              </Select>
            </label>
          )}
          <label style={{ ...lbl, minWidth: "16rem" }}>Title on the paper
            <Input value={title} placeholder={defaultTitle(kind, term)} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <Button variant="primary" disabled={!grade || !subject || create.isPending} onClick={start}>
            {create.isPending ? "Starting…" : "Open the studio"}
          </Button>
        </Stack>
        {create.error && <ErrorNotice error={create.error} />}
      </Card>

      <Card title="Your papers" description="Drafts pick up where you left them; a frozen paper keeps its links.">
        {(drafts.data || []).length === 0 && <EmptyState title="No papers yet" description="Start one above." />}
        {(drafts.data || []).map((d) => (
          <div key={d.draft_id} style={{ display: "flex", gap: "var(--s3)", alignItems: "center", padding: "var(--s2) 0", borderBottom: "1px solid var(--line-2)" }}>
            <Badge tone={d.status === "frozen" ? "ok" : "neutral"}>{d.status}</Badge>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600 }}>{d.title || "(untitled)"}</div>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
                {d.grade} · {d.subject} · {d.kind}{d.term ? ` · Term ${d.term}` : ""} · {d.item_count ?? 0} items · {when(d.updated_at)}
                {d.owner && !d.owner.startsWith("user:") ? "" : ` · ${d.owner.replace("user:", "")}`}
              </div>
            </div>
            <Button size="sm" onClick={() => nav(`/studio/${d.draft_id}`)}>{d.status === "frozen" ? "Open" : "Continue"}</Button>
            <Button size="sm" variant="ghost" onClick={() => duplicate.mutate({ draft_id: d.draft_id })}>Copy</Button>
            <Button size="sm" variant="ghost" style={{ color: "var(--danger)" }}
                    onClick={() => { if (window.confirm(`Delete "${d.title}"?`)) remove.mutate({ draft_id: d.draft_id }); }}>Delete</Button>
          </div>
        ))}
      </Card>
    </Stack>
  );
}

function defaultTitle(kind: string, term: number) {
  return { topical: "Topical Assessment", midterm: `Mid-Term ${term} Examination`, endterm: `End of Term ${term} Examination`,
           assessment: "Assessment", opener: `Term ${term} Opener`, cat: "Continuous Assessment Test", mock: "Mock Examination",
           custom: "" }[kind] ?? "";
}

// ── the studio ──────────────────────────────────────────────────────────────

const SECTIONS = [
  { id: "setup", label: "Setup" }, { id: "scope", label: "Scope" }, { id: "questions", label: "Questions" },
  { id: "design", label: "Design" }, { id: "review", label: "Review" }, { id: "print", label: "Print" },
];

function Studio({ draftId }: { draftId: string }) {
  const draft = useDraft(draftId);
  const patch = usePatchDraft();
  const toast = useToast();
  const nav = useNavigate();
  const [section, setSection] = React.useState("setup");
  const [view, setView] = React.useState<"paper" | "scheme" | "booklet" | "sheet">("paper");
  // Design knobs are tried live and saved with a button, so a slider never
  // writes a draft on every pixel.
  const [tryout, setTryout] = React.useState<Record<string, any>>({});
  const d = draft.data;
  const settings = { ...(d?.settings || {}), ...tryout };
  const previewParams = {
    ...pickPrint(settings),
    answers: view === "scheme", with_scheme: view === "booklet", answer_sheet: view === "sheet",
  };
  const preview = useDraftPreview(draftId, previewParams);

  if (draft.isError) return <ErrorNotice error={draft.error} onRetry={() => draft.refetch()} />;
  if (!d) return <div style={{ color: "var(--ink-3)" }}>Loading the paper…</div>;

  const frozen = d.status === "frozen";
  async function save(p: Record<string, any>) {
    try { await patch.mutateAsync({ draft_id: draftId, patch: p }); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not save.", "danger"); }
  }

  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--s4)", minHeight: "80vh", alignItems: "stretch" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--s3)", minWidth: 0, flex: "1 1 24rem", maxWidth: "38rem" }}>
        <Stack direction="row" gap="var(--s2)" align="center" wrap>
          <Button size="sm" variant="ghost" onClick={() => nav("/studio")}>← Papers</Button>
          <b style={{ flex: 1 }}>{d.title || "(untitled)"}</b>
          <Badge tone={frozen ? "ok" : "neutral"}>{frozen ? `frozen · ${d.exam_id}` : "draft"}</Badge>
        </Stack>
        <div role="tablist" style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line)", overflowX: "auto" }}>
          {SECTIONS.map((s) => (
            <button key={s.id} role="tab" aria-selected={section === s.id} onClick={() => setSection(s.id)}
                    style={{ background: "transparent", border: "none", padding: "6px 10px", cursor: "pointer",
                             borderBottom: `2px solid ${section === s.id ? "var(--accent)" : "transparent"}`,
                             fontWeight: section === s.id ? 650 : 500, color: "var(--ink)" }}>
              {s.label}
            </button>
          ))}
        </div>
        <div style={{ overflowY: "auto", paddingRight: 4 }}>
          {section === "setup" && <SetupSection d={d} save={save} frozen={frozen} />}
          {section === "scope" && <ScopeSection d={d} save={save} frozen={frozen} />}
          {section === "questions" && <QuestionsSection d={d} frozen={frozen} />}
          {section === "design" && <DesignSection d={d} tryout={tryout} setTryout={setTryout} save={save} frozen={frozen} />}
          {section === "review" && <ReviewSection d={d} />}
          {section === "print" && <PrintSection d={d} params={previewParams} />}
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--s2)", minWidth: 0, flex: "2 1 30rem" }}>
        <Stack direction="row" gap="var(--s2)" align="center" wrap>
          {(["paper", "scheme", "booklet", "sheet"] as const).map((v) => (
            <Button key={v} size="sm" variant={view === v ? "primary" : "secondary"} onClick={() => setView(v)}>
              {{ paper: "Question paper", scheme: "Marking scheme", booklet: "Booklet", sheet: "Answer sheet" }[v]}
            </Button>
          ))}
          <span style={{ flex: 1 }} />
          <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
            {preview.isFetching ? "Rendering…" : "As it prints"}
          </span>
        </Stack>
        <iframe title="Paper preview" srcDoc={preview.data || "<p style='font-family:sans-serif;color:#666;padding:2rem'>Fill the paper to see it.</p>"}
                style={{ flex: 1, minHeight: "78vh", width: "100%", border: "1px solid var(--line)", borderRadius: "var(--radius)", background: "#fff" }} />
      </div>
    </div>
  );
}

const PRINT_KEYS = ["density", "font_pt", "line_height", "margins_mm", "columns", "answer_lines", "line_mm",
                    "question_gap_px", "figure_max_mm", "masthead_scale", "scheme_font_pt", "scheme_detail", "split_long_items"];
function pickPrint(settings: Record<string, any>) {
  const out: Record<string, any> = {};
  for (const k of PRINT_KEYS) if (settings[k] !== undefined && settings[k] !== null && settings[k] !== "") out[k] = settings[k];
  return out;
}

// ── Setup ───────────────────────────────────────────────────────────────────

function SetupSection({ d, save, frozen }: { d: ExamDraft; save: (p: any) => Promise<void>; frozen: boolean }) {
  const kinds = useBuilderKinds();
  const grades = useGrades();
  const subjects = useSubjects(d.grade);
  const [title, setTitle] = React.useState(d.title);
  React.useEffect(() => setTitle(d.title), [d.title]);
  return (
    <Card title="Setup" description="What the paper is called and what it is for. The kind sets the line under the subject; the title is yours.">
      <Stack gap="var(--s3)">
        <label style={lbl}>Title on the paper
          <Input value={title} disabled={frozen} onChange={(e) => setTitle(e.target.value)} onBlur={() => title !== d.title && save({ title })} />
        </label>
        <label style={lbl}>Kind
          <Select value={d.kind} disabled={frozen} onChange={(e) => save({ kind: e.target.value })}>
            {Object.entries(kinds.data?.kinds || {}).map(([k, v]) => <option key={k} value={k}>{v || "Custom (the title is the kind line)"}</option>)}
          </Select>
        </label>
        {d.kind !== "topical" && (
          <label style={lbl}>Term
            <Select value={String(d.term || "")} disabled={frozen} onChange={(e) => save({ term: e.target.value ? Number(e.target.value) : null })}>
              <option value="">—</option><option value="1">Term 1</option><option value="2">Term 2</option><option value="3">Term 3</option>
            </Select>
          </label>
        )}
        <Stack direction="row" gap="var(--s3)" wrap>
          <label style={lbl}>Grade
            <Select value={d.grade} disabled={frozen} onChange={(e) => save({ grade: e.target.value, subject: "" })}>
              {(grades.data || []).map((g) => <option key={g.slug || g.name} value={g.slug || g.name}>{gradeOptionLabel(g)}</option>)}
            </Select>
          </label>
          <label style={lbl}>Subject
            <Select value={d.subject} disabled={frozen} onChange={(e) => save({ subject: e.target.value })}>
              <option value="">Choose…</option>
              {(subjects.data || []).map((s: any) => <option key={s.name} value={s.name}>{subjectOptionLabel(s)}</option>)}
            </Select>
          </label>
        </Stack>
        <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
          Changing the grade or subject empties the paper; refill it from Questions.
        </div>
      </Stack>
    </Card>
  );
}

// ── Scope ───────────────────────────────────────────────────────────────────

function ScopeSection({ d, save, frozen }: { d: ExamDraft; save: (p: any) => Promise<void>; frozen: boolean }) {
  const structure = useStoredStructure(d.grade, d.subject);
  const strands = (structure.data?.strands || []) as any[];
  const scope: DraftScope = d.scope || { mode: "smart" };
  const chosen = new Set(scope.sub_strands || []);

  function setMode(mode: DraftScope["mode"]) {
    save({ scope: { ...scope, mode } });
  }
  function toggle(name: string) {
    const next = new Set(chosen);
    next.has(name) ? next.delete(name) : next.add(name);
    save({ scope: { mode: "topics", sub_strands: Array.from(next) } });
  }

  return (
    <Card title="Scope" description="What the paper covers. Smart assist splits the design by the hours KICD gives each sub-strand; or tick the topics yourself.">
      <Stack gap="var(--s3)">
        <Stack direction="row" gap="var(--s2)" wrap>
          {([["smart", "Smart assist (term by hours)"], ["topical", "One sub-strand"], ["topics", "Choose topics"]] as const).map(([m, label]) => (
            <Button key={m} size="sm" variant={scope.mode === m ? "primary" : "secondary"} disabled={frozen} onClick={() => setMode(m)}>{label}</Button>
          ))}
        </Stack>
        {scope.mode === "smart" && (
          <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            {d.term ? `Term ${d.term}: ` : "The whole year: "}
            {(d.scope_sub_strands || []).map((s) => s.sub_strand).join(" · ") || "no sub-strands yet — the design may not be ingested"}
          </div>
        )}
        {scope.mode === "topical" && (
          <label style={lbl}>Sub-strand
            <Select value={scope.sub_strand || ""} disabled={frozen}
                    onChange={(e) => { const ss = e.target.value; const st = strands.find((s) => (s.sub_strands || []).some((x: any) => (x.sub_strand_name || x.name) === ss));
                                       save({ scope: { mode: "topical", sub_strand: ss, strand: st?.strand_name || "" } }); }}>
              <option value="">Choose…</option>
              {strands.flatMap((s) => (s.sub_strands || []).map((x: any) => {
                const name = x.sub_strand_name || x.name;
                return <option key={name} value={name}>{s.strand_name} — {name}</option>;
              }))}
            </Select>
          </label>
        )}
        {scope.mode === "topics" && (
          <div style={{ maxHeight: "22rem", overflowY: "auto", border: "1px solid var(--line-2)", borderRadius: "var(--radius-sm)", padding: "var(--s2)" }}>
            {strands.length === 0 && <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>No structure stored for this subject yet.</div>}
            {strands.map((s) => (
              <div key={s.strand_name} style={{ marginBottom: "var(--s2)" }}>
                <div style={{ fontWeight: 600, fontSize: "var(--text-sm)" }}>{s.strand_name}</div>
                {(s.sub_strands || []).map((x: any) => {
                  const name = x.sub_strand_name || x.name;
                  return (
                    <label key={name} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: "var(--text-sm)", padding: "2px 0 2px 12px" }}>
                      <input type="checkbox" checked={chosen.has(name)} disabled={frozen} onChange={() => toggle(name)} />
                      {name}{x.allocated_hours ? <span style={{ color: "var(--ink-3)" }}> · {x.allocated_hours}</span> : null}
                    </label>
                  );
                })}
              </div>
            ))}
          </div>
        )}
      </Stack>
    </Card>
  );
}

// ── Questions ───────────────────────────────────────────────────────────────

function QuestionsSection({ d, frozen }: { d: ExamDraft; frozen: boolean }) {
  const bank = useDraftBank(d.draft_id);
  const items = useDraftItems(d.draft_id);
  const fill = useFillDraft();
  const generate = useGenerateForDraft();
  const reorder = useReorderDraft();
  const toast = useToast();
  const { role } = useAuth();
  const [count, setCount] = React.useState<number>(d.settings?.count || 30);
  const [diagrams, setDiagrams] = React.useState<number>(d.settings?.diagram_count ?? 4);
  const [editing, setEditing] = React.useState<DraftItemDetail | null>(null);
  const [adding, setAdding] = React.useState<string | null>(null);
  const total = (bank.data || []).reduce((n, s) => n + s.items, 0);
  const figures = (bank.data || []).reduce((n, s) => n + s.with_figures, 0);

  async function doFill(seed?: string) {
    try {
      const out = await fill.mutateAsync({ draft_id: d.draft_id, count, diagram_count: diagrams, seed });
      toast(`${out.items} questions on the paper, ${out.with_figures} with figures${out.shortfall ? ` — ${out.shortfall}` : ""}.`, out.shortfall ? "info" : "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not fill.", "danger"); }
  }
  async function doGenerate(sub_strand?: string) {
    try {
      const out = await generate.mutateAsync({ draft_id: d.draft_id, count, sub_strand });
      const fresh = out.queued.filter((q: any) => !q.already);
      toast(fresh.length
        ? `Writing ${sub_strand ? "for " + sub_strand : "for " + fresh.map((q: any) => q.sub_strand).join(", ")} — the row shows progress; fill again when it lands.`
        : out.queued.length ? "Already being written." : "The bank already has enough for this scope.", "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not queue.", "danger"); }
  }
  const anyWriting = (bank.data || []).some((s) => s.writing);
  const wasWriting = React.useRef(false);
  React.useEffect(() => {
    // The moment the worker finishes, the counts are new: refill an empty
    // paper on its own, and say so.
    if (wasWriting.current && !anyWriting) {
      if (!(items.data || []).length) doFill();
      else toast("New questions landed in the bank. Deal again to bring them onto the paper.", "info");
    }
    wasWriting.current = anyWriting;
  }, [anyWriting]);  // eslint-disable-line react-hooks/exhaustive-deps
  function move(qid: string, dir: -1 | 1) {
    const ids = (items.data || []).map((i) => i.question_id);
    const i = ids.indexOf(qid); const j = i + dir;
    if (i < 0 || j < 0 || j >= ids.length) return;
    [ids[i], ids[j]] = [ids[j], ids[i]];
    reorder.mutate({ draft_id: d.draft_id, question_ids: ids });
  }
  function drop(qid: string) {
    reorder.mutate({ draft_id: d.draft_id, question_ids: (items.data || []).map((i) => i.question_id).filter((x) => x !== qid) });
  }

  return (
    <Stack gap="var(--s3)">
      <Card title="From the bank" description="What already exists for this scope, checked and engine-verified. Pick from it, or write more.">
        <Stack gap="var(--s2)">
          {(bank.data || []).map((s) => (
            <div key={s.sub_strand} style={{ display: "flex", gap: "var(--s2)", alignItems: "center", fontSize: "var(--text-sm)", flexWrap: "wrap" }}>
              <span style={{ flex: 1, minWidth: "10rem" }}>{s.sub_strand}</span>
              <Badge tone={s.items >= 10 ? "ok" : s.items ? "warn" : "danger"}>{s.items} items</Badge>
              <Badge tone="neutral">{s.with_figures} with figures</Badge>
              {!s.has_notes && !s.writing && <Badge tone="warn">no guide</Badge>}
              {s.writing && (
                <Badge tone="accent">
                  {s.writing.status === "running" ? "writing" : "queued"} · {s.writing.stage === "notes" ? "the guide first" : s.writing.stage || "…"}
                </Badge>
              )}
              {s.items ? (
                <Button size="sm" variant="ghost" disabled={frozen} onClick={() => setAdding(s.sub_strand)}>Pick by hand</Button>
              ) : null}
              {s.items < 10 && !s.writing && (
                <Button size="sm" variant={s.items ? "ghost" : "secondary"} disabled={frozen || generate.isPending}
                        title={s.has_notes ? "Write questions for this sub-strand now" : "Writes the teacher's guide first, then the questions — a longer job"}
                        onClick={() => doGenerate(s.sub_strand)}>
                  {s.items ? "Write more" : "Write questions"}
                </Button>
              )}
            </div>
          ))}
          <Stack direction="row" gap="var(--s3)" align="end" wrap>
            <label style={lbl}>Questions<Input type="number" min={1} max={120} value={count} onChange={(e) => setCount(Number(e.target.value))} style={{ width: "6rem" }} /></label>
            <label style={lbl}>With figures (at least)<Input type="number" min={0} max={60} value={diagrams} onChange={(e) => setDiagrams(Number(e.target.value))} style={{ width: "6rem" }} /></label>
            <Button variant="primary" disabled={frozen || fill.isPending || !total} onClick={() => doFill()}>{fill.isPending ? "Filling…" : "Fill from the bank"}</Button>
            <Button variant="secondary" disabled={frozen || fill.isPending || !(items.data || []).length} onClick={() => doFill(Math.random().toString(36).slice(2, 8))}>Deal again</Button>
            <Button variant="ghost" disabled={frozen || generate.isPending} onClick={() => doGenerate()}
                    title={role === "user" ? "Writes new questions with the platform's model; the operator decides whether user accounts may" : "Write the questions this scope is short of"}>
              {generate.isPending ? "Queuing…" : "Generate more"}
            </Button>
          </Stack>
          <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{total} usable items in scope, {figures} with figures.</div>
        </Stack>
      </Card>

      <Card title={`On the paper (${(items.data || []).length})`} description="Open any question to read it with its DNA and correct it; corrections print here and reach the bank when you freeze.">
        {(items.data || []).length === 0 && <EmptyState title="Nothing on the paper yet" description="Fill from the bank above." />}
        {(items.data || []).map((it, index) => {
          const q = it.question;
          const type = String(q.question_type || "").replace(/_/g, " ");
          return (
            <div key={it.question_id} style={{ display: "flex", gap: "var(--s2)", alignItems: "flex-start", padding: "var(--s2) 0", borderBottom: "1px solid var(--line-2)" }}>
              <b style={{ minWidth: "2em" }}>{index + 1}.</b>
              <div style={{ flex: 1, minWidth: 0 }}>
                <button onClick={() => setEditing(it)} style={{ background: "none", border: "none", padding: 0, textAlign: "left", cursor: "pointer", color: "var(--ink)", font: "inherit" }}>
                  {String(q.question_text || "").slice(0, 120)}{String(q.question_text || "").length > 120 ? "…" : ""}
                </button>
                <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)", display: "flex", gap: 6, flexWrap: "wrap", marginTop: 2 }}>
                  <span>{type}</span><span>· {it.pedagogy?.max_marks ?? q.pedagogy?.max_marks ?? 1} mk</span>
                  <span>· {it.curriculum?.sub_strand}</span>
                  {q.diagram && <Badge tone="info">figure</Badge>}
                  {Object.keys(it.overrides || {}).length > 0 && <Badge tone="accent">edited</Badge>}
                  {it.findings?.length > 0 && <Badge tone="warn">{it.findings.length} finding{it.findings.length === 1 ? "" : "s"}</Badge>}
                  {it.rung && <span>· {it.rung.toLowerCase()}</span>}
                  <Badge tone={it.status === "approved" ? "ok" : "neutral"}>{it.status}</Badge>
                </div>
              </div>
              {!frozen && (
                <Stack direction="row" gap="2px">
                  <Button size="sm" variant="ghost" onClick={() => move(it.question_id, -1)} title="Move up">↑</Button>
                  <Button size="sm" variant="ghost" onClick={() => move(it.question_id, 1)} title="Move down">↓</Button>
                  <Button size="sm" variant="ghost" onClick={() => drop(it.question_id)} title="Remove" style={{ color: "var(--danger)" }}>×</Button>
                </Stack>
              )}
            </div>
          );
        })}
      </Card>

      {editing && <ItemEditor d={d} item={editing} frozen={frozen} onClose={() => setEditing(null)} />}
      {adding && <Picker d={d} subStrand={adding} onClose={() => setAdding(null)} />}
    </Stack>
  );
}

function Picker({ d, subStrand, onClose }: { d: ExamDraft; subStrand: string; onClose: () => void }) {
  const cands = useDraftCandidates(d.draft_id, subStrand);
  const reorder = useReorderDraft();
  const items = useDraftItems(d.draft_id);
  function add(qid: string) {
    reorder.mutate({ draft_id: d.draft_id, question_ids: [...(items.data || []).map((i) => i.question_id), qid] });
  }
  return (
    <Modal open onClose={onClose} title={`Pick from the bank — ${subStrand}`}>
      <Stack gap="var(--s2)">
        {(cands.data || []).length === 0 && <div style={{ color: "var(--ink-3)" }}>Nothing left to add for this sub-strand.</div>}
        {(cands.data || []).map((q: any) => (
          <div key={q.question_id} style={{ display: "flex", gap: "var(--s2)", alignItems: "flex-start", borderBottom: "1px solid var(--line-2)", padding: "var(--s2) 0" }}>
            <div style={{ flex: 1, fontSize: "var(--text-sm)" }}>
              {String(q.question_text || "").slice(0, 160)}
              <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
                {String(q.question_type || "").replace(/_/g, " ")} · {q.pedagogy?.max_marks ?? 1} mk {q.diagram ? "· figure" : ""} · {q.status}
              </div>
            </div>
            <Button size="sm" onClick={() => add(q.question_id)}>Add</Button>
          </div>
        ))}
      </Stack>
    </Modal>
  );
}

// ── the item editor, with its DNA ───────────────────────────────────────────

function ItemEditor({ d, item, frozen, onClose }: { d: ExamDraft; item: DraftItemDetail; frozen: boolean; onClose: () => void }) {
  const override = useOverrideItem();
  const toast = useToast();
  const q = item.question;
  const [text, setText] = React.useState(String(q.question_text || ""));
  const [stim, setStim] = React.useState(String(q.stimulus_context || ""));
  const [scheme, setScheme] = React.useState(String(q.marking_scheme || ""));
  const [model, setModel] = React.useState(String(q.model_answer || ""));
  const [expr, setExpr] = React.useState(String(q.expression || ""));
  const [marks, setMarks] = React.useState<number>(Number(item.pedagogy?.max_marks ?? q.pedagogy?.max_marks ?? 1));
  const [options, setOptions] = React.useState<any[]>(Array.isArray(q.options) ? q.options.map((o: any) => ({ ...o })) : []);
  const [parts, setParts] = React.useState<any[]>(Array.isArray(q.structured_parts) ? q.structured_parts.map((p: any) => ({ ...p })) : []);
  const [tab, setTab] = React.useState<"edit" | "dna">("edit");

  async function saveIt() {
    const fields: Record<string, any> = { question_text: text, stimulus_context: stim, marking_scheme: scheme, model_answer: model, expression: expr, max_marks: marks };
    if (options.length) fields.options = options;
    if (parts.length) fields.structured_parts = parts;
    try {
      await override.mutateAsync({ draft_id: d.draft_id, question_id: item.question_id, fields });
      toast("Saved on the paper. It reaches the bank when you freeze.", "ok");
      onClose();
    } catch (err) { toast(err instanceof Error ? err.message : "Could not save.", "danger"); }
  }
  async function revert() {
    await override.mutateAsync({ draft_id: d.draft_id, question_id: item.question_id, fields: {} });
    onClose();
  }

  return (
    <Modal open onClose={onClose} title={`Question · ${item.question_id}`}
           footer={<>
             {Object.keys(item.overrides || {}).length > 0 && <Button variant="ghost" onClick={revert}>Revert to the bank's</Button>}
             <Button onClick={onClose}>Close</Button>
             {!frozen && <Button variant="primary" loading={override.isPending} onClick={saveIt}>Save correction</Button>}
           </>}>
      <div role="tablist" style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line)", marginBottom: "var(--s3)" }}>
        {(["edit", "dna"] as const).map((t) => (
          <button key={t} role="tab" onClick={() => setTab(t)}
                  style={{ background: "transparent", border: "none", padding: "6px 10px", cursor: "pointer",
                           borderBottom: `2px solid ${tab === t ? "var(--accent)" : "transparent"}`, fontWeight: tab === t ? 650 : 500, color: "var(--ink)" }}>
            {t === "edit" ? "Question & answer" : "DNA"}
          </button>
        ))}
      </div>
      {tab === "edit" && (
        <Stack gap="var(--s3)">
          <label style={lbl}>Situation (optional)<Textarea rows={2} value={stim} disabled={frozen} onChange={(e) => setStim(e.target.value)} /></label>
          <label style={lbl}>Question<Textarea rows={4} value={text} disabled={frozen} onChange={(e) => setText(e.target.value)} /></label>
          {options.length > 0 && (
            <div>
              <div style={{ ...lbl, marginBottom: 4 }}>Options — tick the key</div>
              {options.map((o, i) => (
                <div key={o.id || i} style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                  <input type="radio" name="key" checked={!!o.is_correct} disabled={frozen}
                         onChange={() => setOptions(options.map((x, j) => ({ ...x, is_correct: j === i })))} />
                  <b style={{ width: "1.5em" }}>{o.id}.</b>
                  <Input value={o.text || ""} disabled={frozen} onChange={(e) => setOptions(options.map((x, j) => j === i ? { ...x, text: e.target.value } : x))} style={{ flex: 1 }} />
                  <Input value={o.distractor_rationale || o.rationale || ""} placeholder="why a learner picks this" disabled={frozen}
                         onChange={(e) => setOptions(options.map((x, j) => j === i ? { ...x, distractor_rationale: e.target.value } : x))} style={{ flex: 1 }} />
                </div>
              ))}
            </div>
          )}
          {parts.length > 0 && (
            <div>
              <div style={{ ...lbl, marginBottom: 4 }}>Parts</div>
              {parts.map((p, i) => (
                <div key={p.part_id || i} style={{ display: "grid", gridTemplateColumns: "3em 1fr 4em", gap: 6, marginBottom: 4 }}>
                  <b>{p.part_id}</b>
                  <Stack gap="4px">
                    <Input value={p.sub_question || ""} disabled={frozen} onChange={(e) => setParts(parts.map((x, j) => j === i ? { ...x, sub_question: e.target.value } : x))} />
                    <Input value={p.model_answer || ""} placeholder="model answer" disabled={frozen} onChange={(e) => setParts(parts.map((x, j) => j === i ? { ...x, model_answer: e.target.value } : x))} />
                  </Stack>
                  <Input type="number" min={0} value={p.marks ?? 1} disabled={frozen} onChange={(e) => setParts(parts.map((x, j) => j === i ? { ...x, marks: Number(e.target.value) } : x))} />
                </div>
              ))}
            </div>
          )}
          <Stack direction="row" gap="var(--s3)" wrap>
            <label style={lbl}>Marks<Input type="number" min={0} value={marks} disabled={frozen} onChange={(e) => setMarks(Number(e.target.value))} style={{ width: "6rem" }} /></label>
            <label style={{ ...lbl, flex: 1 }}>Expression the engine works (word problems)<Input value={expr} disabled={frozen} onChange={(e) => setExpr(e.target.value)} placeholder="-250 + 600 - 180 + 120/4" /></label>
          </Stack>
          <label style={lbl}>Marking scheme<Textarea rows={3} value={scheme} disabled={frozen} onChange={(e) => setScheme(e.target.value)} /></label>
          <label style={lbl}>Model answer / explanation<Textarea rows={3} value={model} disabled={frozen} onChange={(e) => setModel(e.target.value)} /></label>
          {item.findings?.length > 0 && (
            <div style={{ border: "1px solid var(--warn)", background: "var(--warn-wash)", borderRadius: "var(--radius-sm)", padding: "var(--s2)", fontSize: "var(--text-sm)" }}>
              <b>The checks say:</b>
              <ul style={{ margin: "4px 0 0", paddingLeft: "1.2em" }}>{item.findings.map((f, i) => <li key={i}>{f.says} {f.fix && <i>— {f.fix}</i>}</li>)}</ul>
            </div>
          )}
        </Stack>
      )}
      {tab === "dna" && (
        <Stack gap="var(--s3)" style={{ fontSize: "var(--text-sm)" }}>
          <DnaBlock title="Curriculum" data={item.curriculum} />
          <DnaBlock title="Pedagogy" data={item.pedagogy} />
          <div>
            <b>Engine working</b> <span style={{ color: "var(--ink-3)" }}>({item.working?.source || "none"} → {item.working?.answer || "—"})</span>
            <ol style={{ margin: "4px 0 0", paddingLeft: "1.4em" }}>
              {(item.working?.steps || []).map((s, i) => <li key={i}><code>{s.text}</code>{s.why && <span style={{ color: "var(--ink-3)" }}> — {s.why}</span>}</li>)}
            </ol>
          </div>
          <div><b>Demand:</b> {item.rung || "—"}</div>
          <DnaBlock title="Provenance" data={item.provenance} />
          <DnaBlock title="Review audit" data={item.review_audit} />
        </Stack>
      )}
    </Modal>
  );
}

function DnaBlock({ title, data }: { title: string; data: Record<string, any> }) {
  const entries = Object.entries(data || {}).filter(([, v]) => v !== "" && v !== null && v !== undefined && !(Array.isArray(v) && !v.length));
  if (!entries.length) return null;
  return (
    <div>
      <b>{title}</b>
      <dl style={{ display: "grid", gridTemplateColumns: "10rem 1fr", gap: "2px 8px", margin: "4px 0 0", fontSize: "var(--text-xs)" }}>
        {entries.map(([k, v]) => <React.Fragment key={k}><dt style={{ color: "var(--ink-3)" }}>{k.replace(/_/g, " ")}</dt><dd style={{ margin: 0, wordBreak: "break-word" }}>{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd></React.Fragment>)}
      </dl>
    </div>
  );
}

// ── Design ──────────────────────────────────────────────────────────────────

const KNOBS: { key: string; label: string; min: number; max: number; step: number }[] = [
  { key: "font_pt", label: "Font size (pt)", min: 6.5, max: 13, step: 0.2 },
  { key: "line_height", label: "Line height", min: 1.0, max: 1.8, step: 0.02 },
  { key: "margins_mm", label: "Page margins (mm)", min: 5, max: 25, step: 1 },
  { key: "answer_lines", label: "Working space (× lines per mark)", min: 0, max: 2, step: 0.1 },
  { key: "line_mm", label: "Writing line height (mm)", min: 3, max: 9, step: 0.2 },
  { key: "question_gap_px", label: "Space between questions", min: 0, max: 20, step: 1 },
  { key: "figure_max_mm", label: "Tallest figure (mm)", min: 25, max: 120, step: 5 },
  { key: "masthead_scale", label: "Masthead size", min: 0.5, max: 1.2, step: 0.05 },
];

function DesignSection({ d, tryout, setTryout, save, frozen }: {
  d: ExamDraft; tryout: Record<string, any>; setTryout: (t: Record<string, any>) => void; save: (p: any) => Promise<void>; frozen: boolean;
}) {
  const kinds = useBuilderKinds();
  const presets = kinds.data?.print_presets || {};
  const current = { ...(presets[(d.settings?.density || "compact")] || presets.compact || {}), ...(d.settings || {}), ...tryout };
  const dirty = Object.keys(tryout).length > 0;
  function set(key: string, value: any) { setTryout({ ...tryout, [key]: value }); }
  function preset(name: string) {
    setTryout({ ...Object.fromEntries(PRINT_KEYS.filter((k) => k !== "density").map((k) => [k, presets[name]?.[k]])), density: name });
  }
  return (
    <Card title="Design" description="Move a knob and the page on the right changes. Compact is about a third fewer pages than the national layout; dense about half.">
      <Stack gap="var(--s3)">
        <Stack direction="row" gap="var(--s2)" wrap>
          {Object.keys(presets).map((p) => (
            <Button key={p} size="sm" variant={String(current.density || "").replace("*", "") === p ? "primary" : "secondary"} disabled={frozen} onClick={() => preset(p)}>{p}</Button>
          ))}
        </Stack>
        {KNOBS.map((k) => (
          <label key={k.key} style={{ ...lbl, display: "grid", gridTemplateColumns: "1fr 5rem", gap: 8, alignItems: "center" }}>
            <span>{k.label}<input type="range" min={k.min} max={k.max} step={k.step} value={Number(current[k.key] ?? k.min)} disabled={frozen}
                                   onChange={(e) => set(k.key, Number(e.target.value))} style={{ width: "100%" }} /></span>
            <Input type="number" min={k.min} max={k.max} step={k.step} value={Number(current[k.key] ?? k.min)} disabled={frozen} onChange={(e) => set(k.key, Number(e.target.value))} />
          </label>
        ))}
        <Stack direction="row" gap="var(--s3)" wrap>
          <label style={lbl}>Columns
            <Select value={String(current.columns ?? 2)} disabled={frozen} onChange={(e) => set("columns", Number(e.target.value))}>
              <option value="1">One</option><option value="2">Two</option>
            </Select>
          </label>
          <label style={lbl}>Marking scheme
            <Select value={String(current.scheme_detail || "full")} disabled={frozen} onChange={(e) => set("scheme_detail", e.target.value)}>
              <option value="full">Full — working, reasons, why not</option>
              <option value="brief">Brief — the scheme's lines</option>
              <option value="key">Key only</option>
            </Select>
          </label>
          <label style={{ ...lbl, flexDirection: "row", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={!!current.split_long_items} disabled={frozen} onChange={(e) => set("split_long_items", e.target.checked)} />
            Let long questions continue in the next column
          </label>
        </Stack>
        <Stack direction="row" gap="var(--s2)">
          <Button variant="primary" disabled={frozen || !dirty} onClick={async () => { await save({ settings: { ...(d.settings || {}), ...tryout } }); setTryout({}); }}>Save design</Button>
          <Button variant="ghost" disabled={!dirty} onClick={() => setTryout({})}>Discard changes</Button>
        </Stack>
      </Stack>
    </Card>
  );
}

// ── Review ──────────────────────────────────────────────────────────────────

function ReviewSection({ d }: { d: ExamDraft }) {
  const items = useDraftItems(d.draft_id);
  const review = useReviewDraft();
  const providers = useProviders();
  const toast = useToast();
  const { role } = useAuth();
  const [provider, setProvider] = React.useState("");
  const [model, setModel] = React.useState("");
  const flagged = (items.data || []).filter((i) => i.findings?.length);
  const edited = (items.data || []).filter((i) => Object.keys(i.overrides || {}).length);
  const unexplained = (items.data || []).filter((i) => !i.working?.steps?.length && !i.question?.marking_scheme);
  return (
    <Stack gap="var(--s3)">
      <Card title="What the checks say now" description="Engine keys, repeats, demand, figures — run on the paper as it stands, no model.">
        <Stack gap="var(--s2)" style={{ fontSize: "var(--text-sm)" }}>
          <div><Badge tone={flagged.length ? "warn" : "ok"}>{flagged.length}</Badge> item{flagged.length === 1 ? "" : "s"} with a finding</div>
          <div><Badge tone="neutral">{edited.length}</Badge> corrected by hand</div>
          <div><Badge tone={unexplained.length ? "warn" : "ok"}>{unexplained.length}</Badge> without working or a scheme</div>
          {flagged.map((i) => (
            <div key={i.question_id} style={{ borderLeft: "3px solid var(--warn)", paddingLeft: 8 }}>
              <b>{String(i.question?.question_text || "").slice(0, 80)}…</b>
              <ul style={{ margin: "2px 0 0", paddingLeft: "1.2em" }}>{i.findings.map((f, k) => <li key={k}>{f.says}</li>)}</ul>
            </div>
          ))}
        </Stack>
      </Card>
      <Card title="Review with AI" description="A second model reads every item on this paper's sub-strands cold, checks the key and the story against the sum, and fixes what fails before you print. Spends that vendor's tokens.">
        <Stack gap="var(--s3)">
          <Stack direction="row" gap="var(--s3)" wrap>
            <label style={lbl}>Reader
              <Select value={provider} onChange={(e) => { setProvider(e.target.value); setModel(""); }}>
                <option value="">Platform's review binding</option>
                {(providers.data?.providers || []).filter((p) => p.has_api_key || p.provider === "ollama").map((p) => <option key={p.provider} value={p.provider}>{p.provider}</option>)}
              </Select>
            </label>
            {provider && <label style={lbl}>Model<Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="model name" /></label>}
            <Button variant="primary" loading={review.isPending}
                    title={role === "user" ? "The operator decides whether user accounts may spend tokens" : undefined}
                    onClick={async () => {
                      try { const out = await review.mutateAsync({ draft_id: d.draft_id, provider, model }); toast(`Review queued: ${out.queued} job(s). Watch the Queue board; then re-open this paper.`, "ok"); }
                      catch (err) { toast(err instanceof Error ? err.message : "Could not queue.", "danger"); }
                    }}>Queue review</Button>
          </Stack>
          {review.error && <ErrorNotice error={review.error} />}
        </Stack>
      </Card>
    </Stack>
  );
}

// ── Print ───────────────────────────────────────────────────────────────────

function PrintSection({ d, params }: { d: ExamDraft; params: Record<string, any> }) {
  const pdf = useDraftPdf();
  const freeze = useFreezeDraft();
  const toast = useToast();
  const [links, setLinks] = React.useState<Record<string, string> | null>(null);
  const frozen = d.status === "frozen";
  async function doFreeze() {
    if (!window.confirm("Freeze this paper? Corrections are written to the bank, the exact questions are locked, and share links with a QR code to the marking scheme are made. The draft cannot change after this (copy it to make another).")) return;
    try {
      const out = await freeze.mutateAsync({ draft_id: d.draft_id });
      setLinks(out.render_urls);
      toast(`Frozen as ${out.exam_id}: ${out.question_count} questions, ${out.total_marks} marks.`, "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not freeze.", "danger"); }
  }
  const base = { ...params };
  return (
    <Stack gap="var(--s3)">
      <Card title="Download" description="PDFs of the paper as previewed. Freezing is what makes the links a school can be handed.">
        <Stack direction="row" gap="var(--s2)" wrap>
          <Button onClick={() => pdf.mutate({ draft_id: d.draft_id, params: { ...base, answers: false, with_scheme: false, answer_sheet: false } })}>Question paper PDF</Button>
          <Button onClick={() => pdf.mutate({ draft_id: d.draft_id, params: { ...base, answers: true, with_scheme: false, answer_sheet: false } })}>Marking scheme PDF</Button>
          <Button onClick={() => pdf.mutate({ draft_id: d.draft_id, params: { ...base, answers: false, with_scheme: true, answer_sheet: true } })}>Booklet + answer sheet PDF</Button>
        </Stack>
        {pdf.error && <ErrorNotice error={pdf.error} />}
      </Card>
      <Card title={frozen ? "Frozen" : "Freeze"} description={frozen ? `This paper is ${d.exam_id}. Its links keep working; the questions are locked.` : "Lock the exact questions, write your corrections to the bank, and get share links (no sign-in needed) with the QR code to the scheme."}>
        {!frozen && <Button variant="primary" loading={freeze.isPending} onClick={doFreeze}>Freeze this paper</Button>}
        {links && (
          <Stack gap="4px" style={{ fontSize: "var(--text-sm)", marginTop: "var(--s2)" }}>
            {Object.entries(links).map(([k, v]) => <div key={k}><b>{k.replace(/_/g, " ")}:</b> <a href={v} target="_blank" rel="noreferrer">{v}</a></div>)}
          </Stack>
        )}
      </Card>
    </Stack>
  );
}

const lbl: React.CSSProperties = { fontSize: "var(--text-sm)", fontWeight: 550, display: "flex", flexDirection: "column", gap: 4 };
function when(iso: string) { const t = new Date(iso); return isNaN(t.getTime()) ? iso : t.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }); }
