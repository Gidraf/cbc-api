import React from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, Card, EmptyState, ErrorNotice, Input, LoadingBlock, PageHeader, Select, Stack, Table, useToast } from "../ui/components";
import { MathText } from "../ui/MathBlock";
import { useCreateTest, useDrafts, useMarkAnswer, useTestAction, useTestResults, useTests, type OnlineTest } from "../lib/queries";

const lbl: React.CSSProperties = { fontSize: "var(--text-sm)", fontWeight: 550, display: "flex", flexDirection: "column", gap: 4 };

function testLink(code: string) {
  return `${window.location.origin}/t/${code}`;
}

/** Online tests: a bought paper, taken by a class on their phones. */
export function Classroom() {
  const tests = useTests();
  const [params] = useSearchParams();
  const [open, setOpen] = React.useState<string>("");
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader eyebrow="Classroom" title="Online tests"
        description="Turn a paper you bought into a test your class takes on their phones. Each student gets their own random questions in their own order, so neighbours cannot copy. Multiple choice and number answers are marked at once; written answers come to you with the marking scheme." />
      <NewTest initialDraft={params.get("draft") || ""} onMade={(id) => setOpen(id)} />
      {tests.error && <ErrorNotice error={tests.error} />}
      {!tests.data ? <LoadingBlock rows={3} label="Loading your tests" /> : tests.data.length === 0 ? (
        <EmptyState title="No tests yet" description="Make one above from a paper you have bought." />
      ) : (
        <Card title="Your tests">
          <div style={{ display: "grid", gap: "var(--s3)" }}>
            {tests.data.map((t) => <TestRow key={t.test_id} t={t} open={open === t.test_id} onToggle={() => setOpen(open === t.test_id ? "" : t.test_id)} />)}
          </div>
        </Card>
      )}
    </div>
  );
}

function NewTest({ initialDraft, onMade }: { initialDraft: string; onMade: (id: string) => void }) {
  const drafts = useDrafts();
  const create = useCreateTest();
  const toast = useToast();
  const [draft, setDraft] = React.useState(initialDraft);
  const [perStudent, setPerStudent] = React.useState(0);
  const [minutes, setMinutes] = React.useState(40);
  const [show, setShow] = React.useState("after_submit");
  const [days, setDays] = React.useState(14);
  const chosen = (drafts.data || []).find((d) => d.draft_id === draft);
  const pool = chosen?.item_count ?? chosen?.items?.length ?? 0;
  async function go() {
    try {
      const out = await create.mutateAsync({ draft_id: draft, per_student: perStudent, minutes, show_answers: show,
                                             shuffle_options: true, days_open: days });
      toast(`Test ready. Code: ${out.code}`, "ok");
      onMade(out.test_id);
    } catch (err) { toast(err instanceof Error ? err.message : "Could not make the test.", "danger"); }
  }
  return (
    <Card title="Make a test" description="From one of your papers. Buy it first in the Exam studio (Print tab) — the class sees every question on it.">
      <Stack direction="row" gap="var(--s3)" wrap align="end">
        <label style={{ ...lbl, minWidth: 240, flex: "1 1 240px" }}>Paper
          <Select value={draft} onChange={(e) => setDraft(e.target.value)}>
            <option value="">Choose a paper…</option>
            {(drafts.data || []).map((d) => <option key={d.draft_id} value={d.draft_id}>{d.title || "(untitled)"} — {d.item_count ?? d.items?.length ?? 0} questions</option>)}
          </Select>
        </label>
        <label style={lbl}>Questions each student gets
          <Select value={perStudent} onChange={(e) => setPerStudent(Number(e.target.value))} style={{ width: "auto" }}>
            <option value={0}>All of them{pool ? ` (${pool})` : ""}</option>
            {[5, 10, 15, 20, 25, 30, 40, 50].filter((n) => !pool || n < pool).map((n) => <option key={n} value={n}>{n}, chosen at random</option>)}
          </Select>
        </label>
        <label style={lbl}>Time (minutes)
          <Input type="number" min={0} max={600} value={minutes} onChange={(e) => setMinutes(Math.max(0, Number(e.target.value)))} style={{ width: "6rem" }} />
        </label>
        <label style={lbl}>After handing in, students see
          <Select value={show} onChange={(e) => setShow(e.target.value)} style={{ width: "auto" }}>
            <option value="after_submit">Their score, the answers and the walkthroughs</option>
            <option value="after_close">Their score; the answers once you close the test</option>
            <option value="never">Their score only</option>
          </Select>
        </label>
        <label style={lbl}>Open for (days)
          <Input type="number" min={1} max={180} value={days} onChange={(e) => setDays(Math.max(1, Number(e.target.value)))} style={{ width: "5rem" }} />
        </label>
        <Button variant="primary" loading={create.isPending} disabled={!draft} onClick={go}>Make the test</Button>
      </Stack>
    </Card>
  );
}

function TestRow({ t, open, onToggle }: { t: OnlineTest; open: boolean; onToggle: () => void }) {
  const action = useTestAction();
  const toast = useToast();
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); toast("Copied.", "ok"); } catch { toast("Select it and copy.", "info"); }
  }
  async function act(a: "open" | "closed" | "delete") {
    if (a === "delete" && !window.confirm(`Delete "${t.title}"? Every student's answers and name go with it.`)) return;
    try { await action.mutateAsync({ test_id: t.test_id, action: a }); } catch (err) { toast(err instanceof Error ? err.message : "Could not.", "danger"); }
  }
  const share = `Test: ${t.title}\nOpen ${testLink(t.code)} — or go to ${window.location.origin}/t and type the code ${t.code}.`;
  return (
    <div style={{ border: "1px solid var(--line-2)", borderRadius: "var(--radius)", padding: "var(--s3)", display: "grid", gap: "var(--s2)" }}>
      <Stack direction="row" gap="var(--s2)" align="center" wrap>
        <strong style={{ flex: 1, minWidth: 200 }}>{t.title}</strong>
        <Badge tone={t.status === "open" ? "ok" : "neutral"}>{t.status === "open" ? "open" : "closed"}</Badge>
        <code style={{ fontSize: "var(--text-lg)", letterSpacing: ".12em" }}>{t.code}</code>
      </Stack>
      <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
        {t.per_student} of {t.pool_size} questions each{t.minutes ? ` · ${t.minutes} minutes` : ""} · {t.handed_in} handed in, {t.started - t.handed_in} still writing
        {t.closes_at ? ` · closes ${new Date(t.closes_at).toLocaleDateString()}` : ""}
      </span>
      <Stack direction="row" gap="var(--s2)" wrap>
        <Button size="sm" onClick={() => copy(share)}>Copy the link for the class</Button>
        <Button size="sm" variant="ghost" onClick={onToggle}>{open ? "Hide results" : `Results (${t.handed_in})`}</Button>
        {t.status === "open"
          ? <Button size="sm" variant="ghost" onClick={() => act("closed")}>Close</Button>
          : <Button size="sm" variant="ghost" onClick={() => act("open")}>Open again</Button>}
        <Button size="sm" variant="ghost" onClick={() => act("delete")}>Delete</Button>
      </Stack>
      {open && <Results testId={t.test_id} />}
    </div>
  );
}

function Results({ testId }: { testId: string }) {
  const results = useTestResults(testId);
  const markIt = useMarkAnswer();
  const toast = useToast();
  const r = results.data;
  if (results.error) return <ErrorNotice error={results.error} />;
  if (!r) return <LoadingBlock rows={2} label="Loading results" />;
  const done = r.attempts.filter((a) => a.submitted);
  const pending = done.flatMap((a) => a.to_mark.map((m) => ({ ...m, attempt: a })));
  async function give(attemptId: string, questionId: string, score: number) {
    try { await markIt.mutateAsync({ test_id: testId, attempt_id: attemptId, question_id: questionId, score }); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not save the mark.", "danger"); }
  }
  const pct = (a: { score: number; out_of: number }) => (a.out_of ? Math.round((a.score / a.out_of) * 100) : 0);
  return (
    <div style={{ display: "grid", gap: "var(--s3)" }}>
      {done.length === 0 ? <p style={{ margin: 0, color: "var(--ink-3)" }}>Nobody has handed in yet.</p> : (
        <Table caption="Results">
          <thead><tr><th style={{ textAlign: "left" }}>Student</th><th style={{ textAlign: "right" }}>Score</th><th style={{ textAlign: "right" }}>%</th><th style={{ textAlign: "left" }}>Notes</th></tr></thead>
          <tbody>
            {[...done].sort((a, b) => pct(b) - pct(a)).map((a) => (
              <tr key={a.attempt_id} style={{ borderTop: "1px solid var(--line)" }}>
                <td style={{ padding: "6px 8px" }}>{a.name}</td>
                <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{a.score} / {a.out_of}</td>
                <td style={{ padding: "6px 8px", textAlign: "right" }}>{pct(a)}%</td>
                <td style={{ padding: "6px 8px", color: "var(--ink-3)" }}>{[a.late ? "late" : "", a.to_mark.length ? `${a.to_mark.length} to mark` : ""].filter(Boolean).join(" · ")}</td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {pending.length > 0 && (
        <Card title={`Written answers to mark (${pending.length})`} description="The question, the student's answer and the marking scheme. Pick the marks.">
          <div style={{ display: "grid", gap: "var(--s3)" }}>
            {pending.map((m) => {
              const q = r.questions[m.question_id];
              return (
                <div key={`${m.attempt.attempt_id}-${m.question_id}`} style={{ borderTop: "1px solid var(--line-2)", paddingTop: "var(--s2)", display: "grid", gap: 4, fontSize: "var(--text-sm)" }}>
                  <strong>{m.attempt.name}</strong>
                  <MathText text={q?.question || ""} />
                  <span style={{ background: "var(--surface-2, #f4f4f2)", padding: "6px 8px", borderRadius: "var(--radius)" }}>“{m.given || "(no answer)"}”</span>
                  <span style={{ color: "var(--ink-3)" }}>Answer: <MathText text={q?.answer || ""} />
                    {q?.marking_scheme ? <> · Scheme: <MathText text={q.marking_scheme} /></> : null}</span>
                  <Stack direction="row" gap="4px" wrap>
                    {Array.from({ length: Math.floor(m.out_of) + 1 }, (_, n) => (
                      <Button key={n} size="sm" variant="ghost" onClick={() => give(m.attempt.attempt_id, m.question_id, n)}>{n}</Button>
                    ))}
                    <span style={{ alignSelf: "center", color: "var(--ink-3)" }}>of {m.out_of}</span>
                  </Stack>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
