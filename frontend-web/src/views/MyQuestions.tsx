import React from "react";
import { Badge, Button, Card, EmptyState, ErrorNotice, Input, LoadingBlock, PageHeader, Select, Stack, useToast } from "../ui/components";
import { useAddToPaper, useDeleteMyQuestion, useDrafts, useMyQuestions, useSaveMyQuestion,
         type OwnQuestion, type OwnQuestionInput } from "../lib/queries";

const lbl: React.CSSProperties = { fontSize: "var(--text-sm)", fontWeight: 550, display: "flex", flexDirection: "column", gap: 4 };
const area: React.CSSProperties = { width: "100%", minHeight: 70, padding: 8, borderRadius: "var(--radius)", border: "1px solid var(--line)",
                                    background: "var(--surface)", color: "var(--ink)", font: "inherit", fontSize: "var(--text-sm)" };

const EMPTY: OwnQuestionInput = {
  question_text: "", question_type: "short_answer", stimulus_context: "", options: [], correct_answer: "",
  marking_scheme: "", model_answer: "", marks: 1, grade: "", subject: "",
};

function toInput(q: OwnQuestion): OwnQuestionInput {
  return {
    question_text: q.question_text, question_type: q.question_type, stimulus_context: q.stimulus_context || "",
    options: (q.options || []).map((o) => ({ text: o.text, is_correct: o.is_correct })), correct_answer: q.correct_answer || "",
    marking_scheme: q.marking_scheme || "", model_answer: q.model_answer || "", marks: q.pedagogy?.max_marks || 1,
    grade: q.curriculum?.grade || "", subject: q.curriculum?.subject || "", strand: q.curriculum?.strand || "",
    sub_strand: q.curriculum?.sub_strand || "",
  };
}

/** A teacher's own questions: private, free, on their papers and online tests. */
export function MyQuestions() {
  const mine = useMyQuestions();
  const del = useDeleteMyQuestion();
  const toast = useToast();
  const [editing, setEditing] = React.useState<{ id?: string; body: OwnQuestionInput } | null>(null);
  const [picked, setPicked] = React.useState<string[]>([]);
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader eyebrow="Classroom" title="My questions"
        description="Write your own questions. Only you see them; they cost nothing; they go on your papers and your online tests, and a question with a calculation plays as a game with an animated walkthrough."
        actions={<Button variant="primary" onClick={() => setEditing({ body: { ...EMPTY } })}>+ New question</Button>} />
      {editing && <Editor key={editing.id || "new"} start={editing} onDone={() => setEditing(null)} />}
      {mine.error && <ErrorNotice error={mine.error} />}
      {!mine.data ? <LoadingBlock rows={3} label="Loading your questions" /> : mine.data.length === 0 ? (
        <EmptyState title="No questions of your own yet" description="Press “New question” to write one." />
      ) : (
        <Card title={`${mine.data.length} question(s)`} actions={picked.length ? <ToPaper ids={picked} onDone={() => setPicked([])} /> : undefined}>
          <div style={{ display: "grid", gap: 2 }}>
            {mine.data.map((q) => (
              <div key={q.question_id} style={{ display: "flex", gap: "var(--s2)", alignItems: "center", padding: "6px 0", borderBottom: "1px solid var(--line-2)", fontSize: "var(--text-sm)" }}>
                <input type="checkbox" aria-label="Pick for a paper" checked={picked.includes(q.question_id)}
                       onChange={() => setPicked(picked.includes(q.question_id) ? picked.filter((x) => x !== q.question_id) : [...picked, q.question_id])} />
                <Badge tone="neutral">{q.question_type.replace("_", " ")}</Badge>
                <span style={{ flex: 1, minWidth: 0 }}>{q.question_text.slice(0, 160)}</span>
                <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{[q.curriculum?.subject, q.curriculum?.sub_strand].filter(Boolean).join(" · ")}</span>
                <Button size="sm" variant="ghost" onClick={() => setEditing({ id: q.question_id, body: toInput(q) })}>Edit</Button>
                <Button size="sm" variant="ghost" onClick={async () => {
                  if (!window.confirm("Delete this question? Papers that have it will no longer print it.")) return;
                  try { await del.mutateAsync(q.question_id); } catch (err) { toast(err instanceof Error ? err.message : "Could not delete.", "danger"); }
                }}>Delete</Button>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function ToPaper({ ids, onDone }: { ids: string[]; onDone: () => void }) {
  const drafts = useDrafts();
  const add = useAddToPaper();
  const toast = useToast();
  const [draft, setDraft] = React.useState("");
  return (
    <Stack direction="row" gap="var(--s2)" align="center">
      <Select value={draft} onChange={(e) => setDraft(e.target.value)} style={{ width: "auto" }}>
        <option value="">Put {ids.length} on a paper…</option>
        {(drafts.data || []).filter((d) => d.status !== "frozen").map((d) => <option key={d.draft_id} value={d.draft_id}>{d.title || "(untitled)"}</option>)}
      </Select>
      <Button size="sm" disabled={!draft || add.isPending} onClick={async () => {
        try { const out = await add.mutateAsync({ draft_id: draft, question_ids: ids }); toast(`The paper has ${out.items} questions now.`, "ok"); onDone(); }
        catch (err) { toast(err instanceof Error ? err.message : "Could not add them.", "danger"); }
      }}>Add</Button>
    </Stack>
  );
}

function Editor({ start, onDone }: { start: { id?: string; body: OwnQuestionInput }; onDone: () => void }) {
  const save = useSaveMyQuestion();
  const toast = useToast();
  const [q, setQ] = React.useState<OwnQuestionInput>(start.body);
  const choice = q.question_type === "multiple_choice" || q.question_type === "true_false";
  const set = (patch: Partial<OwnQuestionInput>) => setQ({ ...q, ...patch });
  React.useEffect(() => {
    if (q.question_type === "true_false" && q.options.length !== 2) set({ options: [{ text: "True", is_correct: true }, { text: "False", is_correct: false }] });
    if (q.question_type === "multiple_choice" && q.options.length < 2)
      set({ options: [{ text: "", is_correct: true }, { text: "", is_correct: false }, { text: "", is_correct: false }, { text: "", is_correct: false }] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.question_type]);
  async function store() {
    try {
      await save.mutateAsync({ id: start.id, body: { ...q, options: choice ? q.options.filter((o) => o.text.trim()) : [] } });
      toast(start.id ? "Saved." : "Added to your questions.", "ok");
      onDone();
    } catch (err) { toast(err instanceof Error ? err.message : "Could not save.", "danger"); }
  }
  return (
    <Card title={start.id ? "Edit your question" : "A new question"}>
      <div style={{ display: "grid", gap: "var(--s3)", maxWidth: 760 }}>
        <Stack direction="row" gap="var(--s3)" wrap>
          <label style={lbl}>Kind
            <Select value={q.question_type} onChange={(e) => set({ question_type: e.target.value })} style={{ width: "auto" }}>
              <option value="short_answer">Short answer</option>
              <option value="multiple_choice">Multiple choice</option>
              <option value="true_false">True or false</option>
              <option value="structured">Written / structured</option>
            </Select>
          </label>
          <label style={lbl}>Marks<Input type="number" min={0.5} max={50} step={0.5} value={q.marks} onChange={(e) => set({ marks: Number(e.target.value) })} style={{ width: "5rem" }} /></label>
          <label style={lbl}>Grade<Input value={q.grade} placeholder="e.g. Grade 9" onChange={(e) => set({ grade: e.target.value })} style={{ width: "8rem" }} /></label>
          <label style={lbl}>Subject<Input value={q.subject} placeholder="e.g. Mathematics" onChange={(e) => set({ subject: e.target.value })} /></label>
          <label style={lbl}>Topic<Input value={q.sub_strand || ""} placeholder="e.g. Integers" onChange={(e) => set({ sub_strand: e.target.value })} /></label>
        </Stack>
        <label style={lbl}>The situation (optional)<textarea style={area} value={q.stimulus_context} onChange={(e) => set({ stimulus_context: e.target.value })} /></label>
        <label style={lbl}>The question<textarea style={area} value={q.question_text} onChange={(e) => set({ question_text: e.target.value })} required /></label>
        {choice ? (
          <div style={{ display: "grid", gap: 6 }}>
            <span style={lbl as any}>Options — tick the right one</span>
            {q.options.map((o, i) => (
              <Stack key={i} direction="row" gap="var(--s2)" align="center">
                <input type="radio" name="right" checked={o.is_correct} aria-label={`Option ${"ABCDEFGH"[i]} is right`}
                       onChange={() => set({ options: q.options.map((x, j) => ({ ...x, is_correct: j === i })) })} />
                <strong>{"ABCDEFGH"[i]}</strong>
                <Input value={o.text} disabled={q.question_type === "true_false"}
                       onChange={(e) => set({ options: q.options.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)) })} />
              </Stack>
            ))}
            {q.question_type === "multiple_choice" && q.options.length < 8 && (
              <div><Button size="sm" variant="ghost" onClick={() => set({ options: [...q.options, { text: "", is_correct: false }] })}>+ Option</Button></div>
            )}
          </div>
        ) : (
          <label style={lbl}>The answer (marks the online tests: for a number, write just the number)
            <Input value={q.correct_answer} onChange={(e) => set({ correct_answer: e.target.value })} />
          </label>
        )}
        <label style={lbl}>Marking scheme (optional)<textarea style={area} value={q.marking_scheme} placeholder="e.g. M1 for the method, A1 for 3" onChange={(e) => set({ marking_scheme: e.target.value })} /></label>
        <label style={lbl}>Worked answer (optional — the walkthrough reads it)<textarea style={area} value={q.model_answer} onChange={(e) => set({ model_answer: e.target.value })} /></label>
        <Stack direction="row" gap="var(--s2)">
          <Button variant="primary" loading={save.isPending} onClick={store}>{start.id ? "Save" : "Add the question"}</Button>
          <Button variant="ghost" onClick={onDone}>Cancel</Button>
        </Stack>
      </div>
    </Card>
  );
}
