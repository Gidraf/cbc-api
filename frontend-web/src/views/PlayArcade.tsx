import React from "react";
import gsap from "gsap";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Input,
  Modal,
  PageHeader,
  Select,
  Stack,
  useToast,
} from "../ui/components";
import {
  gradeOptionLabel,
  subjectOptionLabel,
  useGrades,
  usePlayItems,
  usePlayOne,
  usePlayRound,
  useStoredStructure,
  useSubjects,
  useWalkthroughHtml,
  type PlayItem,
  type PlaySpec,
} from "../lib/queries";

/**
 * Play: the bank as games, simulators and walkthroughs. Pick a scope, start
 * a round (mixed kinds, or the quiz race), or open any one item to play it
 * or watch a teacher walk through it. Every number comes from the maths
 * engine; this screen only plays it.
 */
const KIND_LABEL: Record<string, string> = {
  number_line: "Number line", balance: "Balance", bodmas: "Step by step", fraction_bar: "Fraction bars", choice: "Quiz",
};
const KIND_ICON: Record<string, string> = { number_line: "↔", balance: "⚖", bodmas: "①②③", fraction_bar: "▭", choice: "?" };

export function PlayArcade() {
  const grades = useGrades();
  const [grade, setGrade] = React.useState("");
  const [subject, setSubject] = React.useState("Mathematics");
  const [subStrand, setSubStrand] = React.useState("");
  const subjects = useSubjects(grade);
  const structure = useStoredStructure(grade, subject);
  const items = usePlayItems(grade, subject, subStrand);
  const round = usePlayRound();
  const one = usePlayOne();
  const toast = useToast();
  const [playing, setPlaying] = React.useState<PlayItem[] | null>(null);
  const [watching, setWatching] = React.useState<string | null>(null);

  async function startRound(mode: string) {
    try {
      const out = await round.mutateAsync({ grade, subject, sub_strand: subStrand || undefined, mode, count: 10 });
      setPlaying(out.items);
    } catch (err) { toast(err instanceof Error ? err.message : "Nothing to play yet.", "danger"); }
  }
  async function playOne(qid: string) {
    try {
      const out = await one.mutateAsync(qid);
      const spec = out.play.primary || out.play.choice;
      if (!spec) return toast("This item has nothing to play.", "info");
      setPlaying([{ question_id: qid, question_text: out.question.question_text, stimulus_context: out.question.stimulus_context, spec }]);
    } catch (err) { toast(err instanceof Error ? err.message : "Could not open it.", "danger"); }
  }

  const subStrands = ((structure.data?.strands || []) as any[]).flatMap((s) => (s.sub_strands || []).map((x: any) => x.sub_strand_name || x.name));
  const counts = items.data?.counts || {};

  return (
    <>
      <PageHeader eyebrow="Assess" title="Play"
        description="Every question in the bank as a game, a simulator and a narrated walkthrough. The numbers come from the maths engine, so a game can never teach a wrong sum." />
      <Card>
        <Stack direction="row" gap="var(--s3)" wrap align="end">
          <label style={lbl}>Grade
            <Select value={grade} onChange={(e) => { setGrade(e.target.value); setSubStrand(""); }}>
              <option value="">Choose…</option>
              {(grades.data || []).map((g) => <option key={g.slug || g.name} value={g.slug || g.name}>{gradeOptionLabel(g)}</option>)}
            </Select>
          </label>
          <label style={lbl}>Subject
            <Select value={subject} onChange={(e) => { setSubject(e.target.value); setSubStrand(""); }} disabled={!grade}>
              {(subjects.data || []).map((s: any) => <option key={s.name} value={s.name}>{subjectOptionLabel(s)}</option>)}
            </Select>
          </label>
          <label style={lbl}>Topic
            <Select value={subStrand} onChange={(e) => setSubStrand(e.target.value)} disabled={!grade}>
              <option value="">All topics</option>
              {subStrands.map((n: string) => <option key={n} value={n}>{n}</option>)}
            </Select>
          </label>
          <Button variant="primary" disabled={!grade || round.isPending} onClick={() => startRound("mixed")}>▶ Start a round</Button>
          <Button disabled={!grade || round.isPending} onClick={() => startRound("choice")}>Quiz race</Button>
        </Stack>
        {grade && Object.keys(counts).length > 0 && (
          <Stack direction="row" gap="var(--s2)" wrap style={{ marginTop: "var(--s3)" }}>
            {Object.entries(counts).map(([k, n]) => (
              <Button key={k} size="sm" variant="ghost" onClick={() => startRound(k)}>{KIND_ICON[k]} {KIND_LABEL[k] || k} · {n}</Button>
            ))}
          </Stack>
        )}
      </Card>

      {items.error && <ErrorNotice error={items.error} />}
      {grade && (items.data?.items || []).length === 0 && !items.isLoading && (
        <EmptyState title="Nothing playable here yet" description="Write questions for this topic in the Exam studio; every item with a calculation becomes a game." />
      )}
      {(items.data?.items || []).length > 0 && (
        <Card title={`${items.data!.items.length} playable items`}>
          {items.data!.items.map((it) => (
            <div key={it.question_id} style={{ display: "flex", gap: "var(--s2)", alignItems: "center", padding: "6px 0", borderBottom: "1px solid var(--line-2)", fontSize: "var(--text-sm)" }}>
              <Badge tone="info">{KIND_ICON[it.kind]} {KIND_LABEL[it.kind]}</Badge>
              <span style={{ flex: 1, minWidth: 0 }}>{plain(it.question_text).slice(0, 140)}</span>
              <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{it.sub_strand}</span>
              <Button size="sm" onClick={() => playOne(it.question_id)}>Play</Button>
              <Button size="sm" variant="ghost" onClick={() => setWatching(it.question_id)}>Watch</Button>
            </div>
          ))}
        </Card>
      )}

      {playing && <Round items={playing} onClose={() => setPlaying(null)} onWatch={(qid) => setWatching(qid)} />}
      {watching && <WatchModal questionId={watching} onClose={() => setWatching(null)} />}
    </>
  );
}

// ── a round ─────────────────────────────────────────────────────────────────

function Round({ items, onClose, onWatch }: { items: PlayItem[]; onClose: () => void; onWatch: (qid: string) => void }) {
  const [index, setIndex] = React.useState(0);
  const [score, setScore] = React.useState(0);
  const [done, setDone] = React.useState<boolean | null>(null);
  const item = items[index];
  const last = index === items.length - 1;
  function finish(correct: boolean) {
    setDone(correct);
    if (correct) setScore((s) => s + 1);
  }
  function next() { setDone(null); setIndex((i) => i + 1); }
  return (
    <Modal open onClose={onClose} title={`${KIND_LABEL[item?.spec.kind] || "Play"} · ${index + 1} of ${items.length} · score ${score}`}
           width="min(980px, 96vw)"
           footer={<>
             {item && <Button variant="ghost" onClick={() => onWatch(item.question_id)}>Watch the walkthrough</Button>}
             <Button onClick={onClose}>Close</Button>
             {done !== null && !last && <Button variant="primary" onClick={next}>Next ▶</Button>}
             {done !== null && last && <Button variant="primary" onClick={onClose}>Finish — {score}/{items.length}</Button>}
           </>}>
      {item && (
        <Stack gap="var(--s3)">
          {item.stimulus_context && <div style={{ fontStyle: "italic", color: "var(--ink-2)" }}>{plain(item.stimulus_context)}</div>}
          <div style={{ fontSize: "1.1rem" }}>{plain(item.question_text)}</div>
          <Game key={item.question_id} spec={item.spec} onDone={finish} />
          {done !== null && <div style={{ fontWeight: 600, color: done ? "var(--ok, #1f7a5c)" : "var(--warn)" }}>{done ? "Correct!" : "Not this time — the right path is shown."}</div>}
        </Stack>
      )}
    </Modal>
  );
}

function Game({ spec, onDone }: { spec: PlaySpec; onDone: (correct: boolean) => void }) {
  if (spec.kind === "number_line") return <NumberLineGame spec={spec} onDone={onDone} />;
  if (spec.kind === "balance") return <BalanceGame spec={spec} onDone={onDone} />;
  if (spec.kind === "bodmas") return <BodmasGame spec={spec} onDone={onDone} />;
  if (spec.kind === "fraction_bar") return <FractionGame spec={spec} onDone={onDone} />;
  return <ChoiceGame spec={spec} onDone={onDone} />;
}

// The quiz: a wrong pick shows why that answer is tempting and wrong.
function ChoiceGame({ spec, onDone }: { spec: PlaySpec; onDone: (c: boolean) => void }) {
  const [picked, setPicked] = React.useState<string | null>(null);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => { if (ref.current) gsap.from(ref.current.children, { y: 16, opacity: 0, stagger: 0.08, duration: 0.4 }); }, []);
  const options = (spec.options || []) as { id: string; text: string; correct: boolean; why: string }[];
  function pick(o: { id: string; correct: boolean }) {
    if (picked) return;
    setPicked(o.id);
    onDone(o.correct);
  }
  return (
    <div ref={ref} style={{ display: "grid", gap: 8 }}>
      {options.map((o) => {
        const state = picked ? (o.correct ? "ok" : o.id === picked ? "no" : "") : "";
        return (
          <button key={o.id} onClick={() => pick(o)} style={{ textAlign: "left", padding: "10px 14px", borderRadius: 10, cursor: picked ? "default" : "pointer",
            border: `2px solid ${state === "ok" ? "#1f7a5c" : state === "no" ? "#b5651d" : "var(--line)"}`,
            background: state === "ok" ? "rgba(31,122,92,.12)" : state === "no" ? "rgba(181,101,29,.12)" : "var(--surface)", color: "var(--ink)", font: "inherit" }}>
            <b>{o.id}.</b> {plain(o.text)}
            {picked && (o.id === picked || o.correct) && o.why && <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", marginTop: 4 }}>{o.why}</div>}
          </button>
        );
      })}
    </div>
  );
}

// Number line: after each jump is announced, click where you land.
function NumberLineGame({ spec, onDone }: { spec: PlaySpec; onDone: (c: boolean) => void }) {
  const [step, setStep] = React.useState(0);
  const [wrong, setWrong] = React.useState(0);
  const [finished, setFinished] = React.useState(false);
  const svg = React.useRef<SVGSVGElement>(null);
  const W = 900, x0 = 40, x1 = W - 40, lo = spec.min as number, hi = spec.max as number;
  const X = (v: number) => x0 + ((v - lo) * (x1 - x0)) / (hi - lo);
  const points = spec.points as number[];
  const moves = spec.moves as number[];
  const at = points[step];
  React.useEffect(() => {
    // Every earlier arc solid, whatever an interrupted tween left behind;
    // only the newest one draws itself.
    svg.current?.querySelectorAll<SVGPathElement>("path").forEach((p) => {
      gsap.killTweensOf(p); p.style.strokeDasharray = ""; p.style.strokeDashoffset = "";
    });
    const arc = svg.current?.querySelector<SVGPathElement>(`#arc-${step}`);
    if (arc) {
      const len = arc.getTotalLength();
      arc.style.strokeDasharray = `${len}`;
      gsap.fromTo(arc, { strokeDashoffset: len }, { strokeDashoffset: 0, duration: 0.9,
        onComplete: () => { arc.style.strokeDasharray = ""; arc.style.strokeDashoffset = ""; } });
    }
    // The radius, not a transform: React moves the circle between steps and a
    // transform tween keeps the origin of where it was.
    gsap.fromTo(svg.current?.querySelector("#dot") || {}, { attr: { r: 3 } }, { attr: { r: 10 }, duration: 0.45, delay: 0.5 });
  }, [step]);
  function click(v: number) {
    if (finished || step >= moves.length) return;
    if (v === points[step + 1]) {
      const nextStep = step + 1;
      setStep(nextStep);
      if (nextStep === moves.length) { setFinished(true); onDone(wrong === 0); }
    } else {
      setWrong((w) => w + 1);
      const dot = svg.current?.querySelector("#dot");
      if (dot) gsap.fromTo(dot, { attr: { r: 16, fill: "#b5651d" } }, { attr: { r: 10, fill: "#1f7a5c" }, duration: 0.6 });
    }
  }
  const ticks: number[] = [];
  for (let v = lo; v <= hi; v += spec.tick as number) ticks.push(v);
  return (
    <div>
      <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", marginBottom: 6 }}>
        {step < moves.length
          ? <>Start at <b>{points[0]}</b>. Now <b>{moves[step] > 0 ? "+" : ""}{moves[step]}</b> — click where you land.</>
          : <>You landed on <b>{at}</b>.</>}
        {wrong > 0 && <span style={{ color: "var(--warn)" }}> · {wrong} miss{wrong === 1 ? "" : "es"}</span>}
      </div>
      <svg ref={svg} viewBox={`0 0 ${W} 190`} width="100%" style={{ background: "#fff", borderRadius: 10, border: "1px solid var(--line)" }}>
        <line x1={x0} y1={130} x2={x1} y2={130} stroke="#14213d" strokeWidth={3} />
        {ticks.map((v) => (
          <g key={v} onClick={() => click(v)} style={{ cursor: "pointer" }}>
            <rect x={X(v) - 9} y={100} width={18} height={70} fill="transparent" />
            <line x1={X(v)} y1={122} x2={X(v)} y2={138} stroke="#14213d" />
            {(ticks.length <= 30 || v % ((spec.tick as number) * 5) === 0) && <text x={X(v)} y={160} textAnchor="middle" fontSize={13}>{v}</text>}
          </g>
        ))}
        {points.slice(1, step + 1).map((p, k) => {
          const a = X(points[k]), b = X(p), m = (a + b) / 2;
          return <g key={k}><path id={`arc-${k + 1}`} d={`M${a},120 Q${m},40 ${b},120`} fill="none" stroke="#1f7a5c" strokeWidth={3} />
            <text x={m} y={50} textAnchor="middle" fontSize={15} fill="#1f7a5c">{moves[k] > 0 ? "+" : ""}{moves[k]}</text></g>;
        })}
        <circle id="dot" cx={X(at)} cy={130} r={10} fill="#1f7a5c" />
      </svg>
    </div>
  );
}

// Balance: choose the move that keeps the scale level, then say what x is.
function BalanceGame({ spec, onDone }: { spec: PlaySpec; onDone: (c: boolean) => void }) {
  const moves = spec.moves as { op: string; value: string; why: string }[];
  const [step, setStep] = React.useState(0);
  const [wrong, setWrong] = React.useState(0);
  const [answer, setAnswer] = React.useState("");
  const [result, setResult] = React.useState<boolean | null>(null);
  const beam = React.useRef<SVGLineElement>(null);
  const options = React.useMemo(() => {
    if (step >= moves.length) return [];
    const right = moves[step];
    const decoys = [{ op: right.op === "-" ? "+" : "-", value: right.value }, { op: "×", value: right.value }];
    return shuffle([right, ...decoys]);
  }, [step]);  // eslint-disable-line react-hooks/exhaustive-deps
  function choose(o: { op: string; value: string }) {
    const right = moves[step];
    if (o.op === right.op && o.value === right.value) {
      gsap.fromTo(beam.current, { rotation: -5, transformOrigin: "450px 200px" }, { rotation: 0, duration: 1, ease: "elastic.out(1,.4)" });
      setStep((s) => s + 1);
    } else {
      setWrong((w) => w + 1);
      gsap.fromTo(beam.current, { rotation: 0, transformOrigin: "450px 200px" }, { rotation: 7, yoyo: true, repeat: 1, duration: 0.35 });
    }
  }
  function submit() {
    const ok = sameValue(answer, spec.target);
    setResult(ok);
    onDone(ok && wrong === 0);
  }
  return (
    <div>
      <svg viewBox="0 0 900 250" width="100%" style={{ background: "#fff", borderRadius: 10, border: "1px solid var(--line)" }}>
        <polygon points="450,200 430,240 470,240" fill="#14213d" />
        <line ref={beam} x1={150} y1={200} x2={750} y2={200} stroke="#14213d" strokeWidth={6} />
        <rect x={160} y={120} width={250} height={70} rx={10} fill="#e3f4ec" stroke="#1f7a5c" />
        <text x={285} y={165} textAnchor="middle" fontSize={28}>{spec.left}</text>
        <rect x={490} y={120} width={250} height={70} rx={10} fill="#e3f4ec" stroke="#1f7a5c" />
        <text x={615} y={165} textAnchor="middle" fontSize={28}>{spec.right}</text>
        {step > 0 && <text x={450} y={60} textAnchor="middle" fontSize={22} fill="#b5651d">both sides: {moves.slice(0, step).map((m) => `${m.op} ${m.value}`).join("   ")}</text>}
      </svg>
      {step < moves.length ? (
        <Stack direction="row" gap="var(--s2)" wrap style={{ marginTop: 8 }}>
          <span style={{ fontSize: "var(--text-sm)" }}>Do the same to both sides:</span>
          {options.map((o, k) => <Button key={k} onClick={() => choose(o)}>{o.op} {o.value}</Button>)}
        </Stack>
      ) : (
        <Stack direction="row" gap="var(--s2)" align="center" style={{ marginTop: 8 }}>
          <span>{spec.variable} =</span>
          <Input value={answer} onChange={(e) => setAnswer(e.target.value)} style={{ width: "8rem" }} disabled={result !== null}
                 onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
          <Button variant="primary" disabled={!answer || result !== null} onClick={submit}>Check</Button>
          {result === false && <span>It is <b>{String(spec.target)}</b>.</span>}
        </Stack>
      )}
      {step > 0 && step <= moves.length && <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", marginTop: 6 }}>{moves[step - 1].why}</div>}
    </div>
  );
}

// Step by step: pick the operation that comes next, then give its value.
function BodmasGame({ spec, onDone }: { spec: PlaySpec; onDone: (c: boolean) => void }) {
  const steps = spec.steps as { before: string; after: string; left: any; op: string; right: any; result: any; why: string }[];
  const [step, setStep] = React.useState(0);
  const [chosen, setChosen] = React.useState(false);
  const [value, setValue] = React.useState("");
  const [wrong, setWrong] = React.useState(0);
  const line = React.useRef<HTMLDivElement>(null);
  const current = steps[step];
  const choices = React.useMemo(() => {
    if (!current) return [];
    const others = steps.slice(step + 1).map((s) => `${s.left} ${s.op} ${s.right}`).filter((t) => t !== `${current.left} ${current.op} ${current.right}`);
    return shuffle([`${current.left} ${current.op} ${current.right}`, ...others.slice(0, 2)]);
  }, [step]);  // eslint-disable-line react-hooks/exhaustive-deps
  React.useEffect(() => { if (line.current) gsap.from(line.current, { opacity: 0, y: 10, duration: 0.4 }); }, [step]);
  function pick(c: string) {
    if (c === `${current.left} ${current.op} ${current.right}`) setChosen(true);
    else setWrong((w) => w + 1);
  }
  function give() {
    if (sameValue(value, current.result)) {
      setChosen(false); setValue("");
      if (step + 1 === steps.length) { setStep(step + 1); onDone(wrong === 0); }
      else setStep(step + 1);
    } else setWrong((w) => w + 1);
  }
  return (
    <div>
      <div ref={line} style={{ fontSize: "1.6rem", fontFamily: "Cambria Math, Georgia, serif", padding: "12px 0" }}>
        {plain(current ? current.before : steps[steps.length - 1].after)}
      </div>
      {current && !chosen && (
        <Stack direction="row" gap="var(--s2)" wrap>
          <span style={{ fontSize: "var(--text-sm)" }}>Which comes next?</span>
          {choices.map((c) => <Button key={c} onClick={() => pick(c)}>{c}</Button>)}
        </Stack>
      )}
      {current && chosen && (
        <Stack direction="row" gap="var(--s2)" align="center">
          <span>{current.left} {current.op} {current.right} =</span>
          <Input autoFocus value={value} onChange={(e) => setValue(e.target.value)} style={{ width: "8rem" }}
                 onKeyDown={(e) => { if (e.key === "Enter") give(); }} />
          <Button variant="primary" onClick={give}>Check</Button>
          <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>{current.why}</span>
        </Stack>
      )}
      {wrong > 0 && <div style={{ color: "var(--warn)", fontSize: "var(--text-sm)", marginTop: 6 }}>{wrong} slip{wrong === 1 ? "" : "s"} — BODMAS: brackets, orders, ÷ × left to right, then + − left to right.</div>}
    </div>
  );
}

// Fraction bars: find the common cut, then the answer.
function FractionGame({ spec, onDone }: { spec: PlaySpec; onDone: (c: boolean) => void }) {
  const [phase, setPhase] = React.useState<"cut" | "answer" | "done">("cut");
  const [wrong, setWrong] = React.useState(0);
  const [value, setValue] = React.useState("");
  const [a, b] = spec.first as number[];
  const [c, d] = spec.second as number[];
  const L = spec.common as number;
  const svg = React.useRef<SVGSVGElement>(null);
  React.useEffect(() => { if (svg.current) gsap.from(svg.current.querySelectorAll("rect"), { scaleX: 0, transformOrigin: "left", stagger: 0.02, duration: 0.3 }); }, [phase]);
  const cuts = React.useMemo(() => shuffle(Array.from(new Set([L, b * d, b + d, Math.max(b, d)])).slice(0, 4)), []);  // eslint-disable-line react-hooks/exhaustive-deps
  const bar = (n: number, den: number, color: string, y: number) =>
    Array.from({ length: den }, (_, k) => <rect key={`${y}-${k}`} x={60 + (k * 780) / den} y={y} width={780 / den} height={40} fill={k < n ? color : "#fff"} stroke="#14213d" />);
  const showCommon = phase !== "cut";
  return (
    <div>
      <svg ref={svg} viewBox="0 0 900 140" width="100%" style={{ background: "#fff", borderRadius: 10, border: "1px solid var(--line)" }}>
        {showCommon ? bar((spec.first_as as number[])[0], L, "#9bd3b8", 20) : bar(a, b, "#9bd3b8", 20)}
        {showCommon ? bar((spec.second_as as number[])[0], L, "#f4c27a", 80) : bar(c, d, "#f4c27a", 80)}
      </svg>
      {phase === "cut" && (
        <Stack direction="row" gap="var(--s2)" wrap style={{ marginTop: 8 }}>
          <span style={{ fontSize: "var(--text-sm)" }}>{a}/{b} {spec.op} {c}/{d}: cut both bars into how many equal pieces?</span>
          {cuts.map((n) => <Button key={n} onClick={() => (n === L ? setPhase("answer") : setWrong((w) => w + 1))}>{n}</Button>)}
        </Stack>
      )}
      {phase !== "cut" && (
        <Stack direction="row" gap="var(--s2)" align="center" style={{ marginTop: 8 }}>
          <span>{(spec.first_as as number[])[0]}/{L} {spec.op} {(spec.second_as as number[])[0]}/{L} =</span>
          <Input value={value} onChange={(e) => setValue(e.target.value)} disabled={phase === "done"} style={{ width: "8rem" }}
                 onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
          <Button variant="primary" disabled={phase === "done" || !value}
                  onClick={() => { const ok = sameValue(value, spec.target); setPhase("done"); onDone(ok && wrong === 0); }}>Check</Button>
          {phase === "done" && <span>= <b>{String(spec.target)}</b></span>}
        </Stack>
      )}
    </div>
  );
}

// ── the walkthrough ─────────────────────────────────────────────────────────

function WatchModal({ questionId, onClose }: { questionId: string; onClose: () => void }) {
  const page = useWalkthroughHtml(questionId);
  return (
    <Modal open onClose={onClose} title="Walkthrough — press Play to hear it" width="min(1040px, 96vw)"
           footer={<Button onClick={onClose}>Close</Button>}>
      {page.error && <ErrorNotice error={page.error} />}
      <iframe title="Walkthrough" srcDoc={page.data || "<p style='font-family:sans-serif;padding:2rem'>Preparing…</p>"}
              allow="autoplay" style={{ width: "100%", height: "70vh", border: "1px solid var(--line)", borderRadius: "var(--radius)", background: "#fbfaf6" }} />
    </Modal>
  );
}

// ── helpers ─────────────────────────────────────────────────────────────────

function plain(text: string) {
  return String(text || "").replace(/\$([^$]*)\$/g, "$1").replace(/\\times/g, "×").replace(/\\div/g, "÷")
    .replace(/\\left|\\right/g, "").replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, "$1/$2").replace(/\\[a-zA-Z]+/g, "").replace(/[{}]/g, "");
}

function toNumber(text: any): number | null {
  const t = String(text ?? "").replace(/\s+/g, "").replace(/−/g, "-");
  const m = t.match(/^(-?\d+(?:\.\d+)?)(?:\/(-?\d+(?:\.\d+)?))?$/);
  if (!m) return null;
  const n = parseFloat(m[1]); const d = m[2] ? parseFloat(m[2]) : 1;
  return d ? n / d : null;
}

function sameValue(given: any, expected: any) {
  const a = toNumber(given), b = toNumber(expected);
  return a !== null && b !== null && Math.abs(a - b) < 1e-9;
}

function shuffle<T>(xs: T[]): T[] {
  const out = [...xs];
  for (let i = out.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [out[i], out[j]] = [out[j], out[i]]; }
  return out;
}

const lbl: React.CSSProperties = { fontSize: "var(--text-sm)", fontWeight: 550, display: "flex", flexDirection: "column", gap: 4 };
