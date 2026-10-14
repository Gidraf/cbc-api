import React from "react";
import { useNavigate, useParams } from "react-router-dom";
import { fetchJson } from "../api";
import { MathText } from "../ui/MathBlock";
import { Badge, Button, Card, Input, Stack } from "../ui/components";

// A student's page: no account. The test code, then the attempt's own token,
// kept in this browser so a reload or a dropped connection loses nothing.

type Q = { question_id: string; type: string; context: string; question: string; marks: number; figure: string;
           options: { letter: string; text: string }[]; parts: { label: string; text: string }[] };
type Attempt = { token: string; title: string; minutes: number; name: string; questions: Q[]; started_at?: string };
type Result = { submitted: true; name: string; title: string; score: number; out_of: number; to_mark: number; answers_shown: boolean;
                late: boolean; items: { question_id: string; status: string; score: number; out_of: number; given: string;
                question?: string; answer?: string; right_letter?: string | null; marking_scheme?: string; worked_answer?: string;
                walkthrough_url?: string }[] };

const KEY = (code: string) => `cbc_test_${code}`;
const page: React.CSSProperties = { minHeight: "100vh", background: "var(--ground)", padding: "var(--s4) var(--s3)", display: "flex", justifyContent: "center" };
const col: React.CSSProperties = { width: "min(46rem, 100%)", display: "grid", gap: "var(--s3)", alignContent: "start" };

function store(code: string, v: Record<string, any> | null) {
  try { if (v) localStorage.setItem(KEY(code), JSON.stringify(v)); else localStorage.removeItem(KEY(code)); } catch { /* private window */ }
}
function recall(code: string): Record<string, any> | null {
  try { return JSON.parse(localStorage.getItem(KEY(code)) || "null"); } catch { return null; }
}

export function TakeTest() {
  const { code: raw = "" } = useParams();
  const code = raw.toUpperCase();
  const nav = useNavigate();
  const [typed, setTyped] = React.useState("");
  if (!code) {
    return (
      <div style={page}><div style={col}>
        <h1>Take a test</h1>
        <Card title="Type the code your teacher gave you">
          <form onSubmit={(e) => { e.preventDefault(); if (typed.trim()) nav(`/t/${typed.trim().toUpperCase()}`); }}>
            <Stack direction="row" gap="var(--s2)">
              <Input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="e.g. K7Q2MX" autoCapitalize="characters" maxLength={12}
                     style={{ fontSize: "var(--text-lg)", letterSpacing: ".15em" }} />
              <Button type="submit" variant="primary">Open</Button>
            </Stack>
          </form>
        </Card>
      </div></div>
    );
  }
  return <Test code={code} />;
}

function Test({ code }: { code: string }) {
  const saved = recall(code);
  const [info, setInfo] = React.useState<{ title: string; questions: number; minutes: number; open: boolean } | null>(null);
  const [error, setError] = React.useState("");
  const [name, setName] = React.useState("");
  const [attempt, setAttempt] = React.useState<Attempt | null>(null);
  const [answers, setAnswers] = React.useState<Record<string, string>>(saved?.answers || {});
  const [result, setResult] = React.useState<Result | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [now, setNow] = React.useState(Date.now());

  React.useEffect(() => {
    (async () => {
      try {
        if (saved?.token) {
          const out = await fetchJson<any>(`/api/v1/tests/attempts/${saved.token}`);
          if (out.submitted) setResult(out as Result); else setAttempt(out as Attempt);
          return;
        }
        setInfo(await fetchJson(`/api/v1/tests/${encodeURIComponent(code)}`));
      } catch (err) {
        if (saved?.token) { store(code, null); window.location.reload(); return; }
        setError(err instanceof Error ? err.message : "This test could not be opened.");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);
  React.useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  React.useEffect(() => { if (attempt) store(code, { token: attempt.token, answers }); }, [answers, attempt, code]);

  async function begin(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError("");
    try {
      const out = await fetchJson<Attempt>(`/api/v1/tests/${encodeURIComponent(code)}/start`, { method: "POST", body: JSON.stringify({ name }) });
      setAttempt({ ...out, started_at: new Date().toISOString() });
      store(code, { token: out.token, answers: {} });
    } catch (err) { setError(err instanceof Error ? err.message : "Could not start."); } finally { setBusy(false); }
  }
  async function handIn() {
    if (!attempt) return;
    const blank = attempt.questions.filter((q) => !(answers[q.question_id] || "").trim()).length;
    if (blank && !window.confirm(`${blank} question(s) have no answer. Hand in anyway?`)) return;
    setBusy(true);
    try {
      const out = await fetchJson<Result>(`/api/v1/tests/attempts/${attempt.token}/submit`, { method: "POST", body: JSON.stringify({ answers }) });
      setResult(out); setAttempt(null);
      store(code, { token: attempt.token, answers });
    } catch (err) { setError(err instanceof Error ? err.message : "Could not hand in. Check your connection and try again."); }
    finally { setBusy(false); }
  }

  if (result) return <ResultView r={result} />;
  if (attempt) {
    const started = attempt.started_at ? new Date(attempt.started_at).getTime() : now;
    const left = attempt.minutes ? Math.max(0, started + attempt.minutes * 60_000 - now) : null;
    const answered = attempt.questions.filter((q) => (answers[q.question_id] || "").trim()).length;
    return (
      <div style={page}><div style={col}>
        <div style={{ position: "sticky", top: 0, zIndex: 5, background: "var(--ground)", padding: "var(--s2) 0", display: "flex", gap: "var(--s2)", alignItems: "center", flexWrap: "wrap" }}>
          <strong style={{ flex: 1, minWidth: 160 }}>{attempt.title}</strong>
          <Badge tone="neutral">{attempt.name}</Badge>
          <Badge tone="info">{answered} / {attempt.questions.length} answered</Badge>
          {left !== null && <Badge tone={left < 5 * 60_000 ? "danger" : "neutral"}>⏱ {Math.floor(left / 60_000)}:{String(Math.floor(left / 1000) % 60).padStart(2, "0")}</Badge>}
        </div>
        {left === 0 && <Card><strong>Time is up — hand in now.</strong></Card>}
        {attempt.questions.map((q, i) => (
          <Card key={q.question_id} title={`Question ${i + 1}`} actions={<span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>{q.marks} mark{q.marks === 1 ? "" : "s"}</span>}>
            <div style={{ display: "grid", gap: "var(--s2)" }}>
              {q.context && <MathText text={q.context} style={{ color: "var(--ink-2)" }} />}
              <MathText text={q.question} />
              {q.figure && <div style={{ background: "#fff", borderRadius: "var(--radius)", padding: 8, maxWidth: 420 }} dangerouslySetInnerHTML={{ __html: q.figure }} />}
              {q.parts.map((p, n) => <MathText key={n} text={`${p.label} ${p.text}`} />)}
              {q.options.length ? (
                <div style={{ display: "grid", gap: 6 }}>
                  {q.options.map((o) => (
                    <label key={o.letter} style={{ display: "flex", gap: 8, alignItems: "center", padding: "8px 10px", cursor: "pointer",
                                                   border: `1px solid ${answers[q.question_id] === o.letter ? "var(--accent)" : "var(--line)"}`, borderRadius: "var(--radius)" }}>
                      <input type="radio" name={q.question_id} checked={answers[q.question_id] === o.letter}
                             onChange={() => setAnswers({ ...answers, [q.question_id]: o.letter })} />
                      <strong>{o.letter}.</strong> <MathText text={o.text} />
                    </label>
                  ))}
                </div>
              ) : q.type === "structured" ? (
                <textarea value={answers[q.question_id] || ""} onChange={(e) => setAnswers({ ...answers, [q.question_id]: e.target.value })}
                          style={{ width: "100%", minHeight: 110, padding: 8, borderRadius: "var(--radius)", border: "1px solid var(--line)", background: "var(--surface)", color: "var(--ink)", font: "inherit" }} />
              ) : (
                <Input value={answers[q.question_id] || ""} placeholder="Your answer" onChange={(e) => setAnswers({ ...answers, [q.question_id]: e.target.value })} />
              )}
            </div>
          </Card>
        ))}
        {error && <Card><span style={{ color: "var(--danger)" }}>{error}</span></Card>}
        <Button variant="primary" loading={busy} onClick={handIn} style={{ justifyContent: "center", padding: "12px" }}>Hand in</Button>
        <p style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)", margin: 0 }}>Your answers are kept on this phone as you go: you can close the page and come back.</p>
      </div></div>
    );
  }
  return (
    <div style={page}><div style={col}>
      <h1>{info?.title || "Test"}</h1>
      {error && <Card><span style={{ color: "var(--danger)" }}>{error}</span></Card>}
      {info && (info.open ? (
        <Card title="Start" description={`${info.questions} questions${info.minutes ? `, ${info.minutes} minutes` : ""}. Your questions are not the same as your neighbour's.`}>
          <form onSubmit={begin} style={{ display: "grid", gap: "var(--s3)" }}>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your name" maxLength={60} required autoComplete="name" />
            <Button type="submit" variant="primary" loading={busy}>Begin</Button>
          </form>
        </Card>
      ) : <Card>This test is closed.</Card>)}
    </div></div>
  );
}

function ResultView({ r }: { r: Result }) {
  const pct = r.out_of ? Math.round((r.score / r.out_of) * 100) : 0;
  const [watch, setWatch] = React.useState("");
  return (
    <div style={page}><div style={col}>
      <h1>{r.title}</h1>
      <Card>
        <div style={{ display: "grid", gap: 4 }}>
          <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)", textTransform: "uppercase", letterSpacing: ".08em" }}>{r.name}</span>
          <span style={{ fontSize: "2.4rem", fontWeight: 700 }}>{r.score} / {r.out_of} <span style={{ fontSize: "1.2rem", color: "var(--ink-3)" }}>({pct}%)</span></span>
          {r.to_mark > 0 && <span>{r.to_mark} written answer(s) are waiting for your teacher to mark.</span>}
          {r.late && <span style={{ color: "var(--warn, #b45309)" }}>Handed in after the time.</span>}
        </div>
      </Card>
      {r.items.map((it, i) => (
        <Card key={it.question_id} title={`Question ${i + 1}`}
              actions={<Badge tone={it.status === "right" ? "ok" : it.status === "wrong" ? "danger" : "neutral"}>
                {it.status === "right" ? `✓ ${it.score}/${it.out_of}` : it.status === "wrong" ? `✗ 0/${it.out_of}` : it.status === "marked" ? `${it.score}/${it.out_of}` : "to be marked"}
              </Badge>}>
          <div style={{ display: "grid", gap: 6, fontSize: "var(--text-sm)" }}>
            {it.question && <MathText text={it.question} />}
            <span>Your answer: <strong>{it.given || "(none)"}</strong></span>
            {r.answers_shown && (
              <>
                <span>Right answer: <strong>{it.right_letter ? `${it.right_letter}. ` : ""}<MathText text={it.answer || ""} /></strong></span>
                {it.worked_answer && <MathText text={it.worked_answer} style={{ color: "var(--ink-2)" }} />}
                {it.marking_scheme && <span style={{ color: "var(--ink-3)" }}>Marking scheme: <MathText text={it.marking_scheme} /></span>}
                {it.walkthrough_url && (
                  <div><Button size="sm" variant="ghost" onClick={() => setWatch(watch === it.question_id ? "" : it.question_id)}>
                    {watch === it.question_id ? "Hide the walkthrough" : "▶ Watch it worked out"}</Button></div>
                )}
                {watch === it.question_id && it.walkthrough_url && (
                  <iframe title="Walkthrough" src={it.walkthrough_url} style={{ width: "100%", height: 420, border: "1px solid var(--line)", borderRadius: "var(--radius)", background: "#fff" }} />
                )}
              </>
            )}
          </div>
        </Card>
      ))}
      {!r.answers_shown && <p style={{ color: "var(--ink-3)" }}>Your teacher will go through the answers.</p>}
    </div></div>
  );
}
