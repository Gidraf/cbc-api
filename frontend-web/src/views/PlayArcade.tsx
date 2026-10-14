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
  useClearHandPhoto,
  useDeletePost,
  useExportSocial,
  useBookAhead,
  useSaveGroups,
  useVideoBatches,
  useDriveStatus,
  useMoveToDrive,
  useQueueBatch,
  useBatchAction,
  type VideoBatch,
  type BookingPlan,
  type PosterGroup,
  useSavePost,
  useSocialPosts,
  useHandPhoto,
  useMakeSocial,
  usePosterCommand,
  usePosterMacLink,
  usePosterOverview,
  usePosterShot,
  useMakeSocials,
  useMakeVideo,
  useSaveBrand,
  useSocialAsset,
  useSocialBrand,
  useSocialHtml,
  useSocialLibrary,
  useSocialStatus,
  useSetHandPhoto,
  useMakeVideos,
  useVideoLibrary,
  useVideoStatus,
  useVoices,
  useWalkthroughHtml,
  useWhiteboardHtml,
  type PlayItem,
  type PosterOverview,
  type PostRollup,
  type SocialBrand,
  type TrackedPost,
  type SocialState,
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
  const [showLibrary, setShowLibrary] = React.useState(false);
  const [socialWatch, setSocialWatch] = React.useState<string | null>(null);

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
              <Button size="sm" variant="ghost" onClick={() => setWatching(it.question_id)}>✎ Whiteboard</Button>
            </div>
          ))}
        </Card>
      )}

      {grade && (items.data?.items || []).length > 0 && (
        <VideoLibrary grade={grade} subject={subject} subStrand={subStrand} open={showLibrary}
                      onToggle={() => setShowLibrary((v) => !v)} onWatch={(qid) => setWatching(qid)} />
      )}

      {grade && (items.data?.items || []).length > 0 && (
        <SocialLibrary grade={grade} subject={subject} subStrand={subStrand} topics={subStrands} onWatch={(qid) => setSocialWatch(qid)} />
      )}
      {grade && <Performance grade={grade} subject={subject} subStrand={subStrand} />}
      <AutoPost />

      {playing && <Round items={playing} onClose={() => setPlaying(null)} onWatch={(qid) => setWatching(qid)} />}
      {watching && <WatchModal questionId={watching} onClose={() => setWatching(null)} />}
      {socialWatch && <WatchModal questionId={socialWatch} start="social" onClose={() => setSocialWatch(null)} />}
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

function WatchModal({ questionId, onClose, start = "whiteboard" }: { questionId: string; onClose: () => void; start?: "whiteboard" | "classic" | "social" }) {
  const [view, setView] = React.useState<"whiteboard" | "classic" | "social">(start);
  const [voice, setVoice] = React.useState("");
  const board = useWhiteboardHtml(view === "whiteboard" ? questionId : "", voice);
  const classic = useWalkthroughHtml(view === "classic" ? questionId : "");
  const vertical = useSocialHtml(view === "social" ? questionId : "", voice);
  const page = view === "whiteboard" ? board : view === "classic" ? classic : vertical;
  const frame = (
    <iframe key={view} title="Walkthrough" srcDoc={page.data || "<p style='font-family:sans-serif;padding:2rem'>Preparing — the voice is being recorded…</p>"}
            allow="autoplay" style={{ width: view === "social" ? "min(420px, 100%)" : "100%", height: view === "social" ? "62vh" : "72vh", border: "1px solid var(--line)", borderRadius: "var(--radius)", background: view === "social" ? "#0f172a" : "#e9e7e1" }} />
  );
  return (
    <Modal open onClose={onClose} title="Walkthrough — press Play to hear it" width="min(1100px, 96vw)"
           footer={<Button onClick={onClose}>Close</Button>}>
      <Stack direction="row" gap="var(--s2)" wrap align="center" style={{ marginBottom: "var(--s3)" }}>
        <Button size="sm" variant={view === "whiteboard" ? "primary" : "ghost"} onClick={() => setView("whiteboard")}>✎ Whiteboard</Button>
        <Button size="sm" variant={view === "social" ? "primary" : "ghost"} onClick={() => setView("social")}>📱 Social post</Button>
        <Button size="sm" variant={view === "classic" ? "primary" : "ghost"} onClick={() => setView("classic")}>Animated</Button>
        <VoicePicker value={voice} onChange={setVoice} label="Voice" />
        <span style={{ flex: 1 }} />
        {view !== "social" && <VideoControl questionId={questionId} voice={voice} />}
      </Stack>
      {page.error && <ErrorNotice error={page.error} />}
      {view === "social" ? (
        <div style={{ display: "flex", gap: "var(--s4)", flexWrap: "wrap", alignItems: "flex-start" }}>
          {frame}
          <div style={{ flex: "1 1 320px", minWidth: 0 }}><SocialControl questionId={questionId} voice={voice} /></div>
        </div>
      ) : frame}
    </Modal>
  );
}

/** The item's social post: the vertical MP4, its thumbnail, and the text to paste. */
function SocialControl({ questionId, voice }: { questionId: string; voice: string }) {
  const social = useSocialStatus(questionId, voice);
  const make = useMakeSocial();
  const toast = useToast();
  const v = social.data;
  async function start() {
    try { await make.mutateAsync({ questionId, voice }); toast("Social video queued — drawn, voiced and captioned in the worker.", "ok"); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not queue it.", "danger"); }
  }
  if (!v) return <p style={{ color: "var(--ink-3)" }}>{social.isLoading ? "Loading the post…" : ""}</p>;
  return (
    <div style={{ display: "grid", gap: "var(--s3)" }}>
      <Stack direction="row" gap="var(--s2)" wrap align="center">
        {v.status === "ready" && v.url ? (
          <>
            <Badge tone="ok">Video ready</Badge>
            <a href={v.url} download target="_blank" rel="noreferrer"><Button size="sm" variant="primary">⬇ Video (MP4)</Button></a>
            {v.thumbnail_url && <a href={v.thumbnail_url} download target="_blank" rel="noreferrer"><Button size="sm">⬇ Thumbnail</Button></a>}
          </>
        ) : v.status === "queued" || v.status === "running" ? (
          <Badge tone="info">{v.status === "running" ? "Making the video…" : "Video queued…"}</Badge>
        ) : (
          <>
            {v.status === "failed" && <Badge tone="danger" title={v.error}>Last attempt failed</Badge>}
            <Button size="sm" variant="primary" disabled={make.isPending || !v.scenes} onClick={start}>📱 Make the social video</Button>
          </>
        )}
      </Stack>
      <PostText post={v.post} />
    </div>
  );
}

function PostText({ post }: { post: string }) {
  const toast = useToast();
  async function copy() {
    try { await navigator.clipboard.writeText(post); toast("Post copied — paste it as the caption.", "ok"); }
    catch { toast("Could not copy — select the text and copy it.", "danger"); }
  }
  return (
    <div>
      <Stack direction="row" gap="var(--s2)" align="center" style={{ marginBottom: 6 }}>
        <strong style={{ fontSize: "var(--text-sm)" }}>Post text</strong>
        <span style={{ flex: 1 }} />
        <Button size="sm" onClick={copy}>📋 Copy post</Button>
      </Stack>
      <textarea readOnly value={post} rows={14}
                style={{ width: "100%", boxSizing: "border-box", font: "inherit", fontSize: "var(--text-sm)", padding: 10,
                         borderRadius: "var(--radius)", border: "1px solid var(--line)", background: "var(--surface-2)", color: "var(--ink)" }} />
    </div>
  );
}

/** Every item in the scope as a post for TikTok, Reels, Shorts and Status. */
function SocialLibrary({ grade, subject, subStrand, topics, onWatch }: {
  grade: string; subject: string; subStrand: string; topics: string[]; onWatch: (qid: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const library = useSocialLibrary(grade, subject, subStrand, open);
  const makeAll = useMakeSocials();
  const brand = useSocialBrand();
  const asset = useSocialAsset();
  const toast = useToast();
  const rows = library.data?.items || [];
  const busy = rows.filter((v) => v.status === "queued" || v.status === "running").length;
  const b = brand.data;
  async function all() {
    try {
      const out = await makeAll.mutateAsync({ grade, subject, sub_strand: subStrand || undefined, limit: 60 });
      const c = out.counts;
      setOpen(true);
      toast(`Social posts: ${c.queued || 0} queued, ${c.ready || 0} already made${c.failed ? `, ${c.failed} failed` : ""}.`, "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not queue the posts.", "danger"); }
  }
  async function upload(kind: "logo" | "music", file: File | null) {
    try { await asset.mutateAsync({ kind, file }); toast(file ? `${kind === "logo" ? "Logo" : "Music"} saved.` : `${kind === "logo" ? "Logo" : "Music"} removed.`, "ok"); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not save it.", "danger"); }
  }
  async function copy(post: string) {
    try { await navigator.clipboard.writeText(post); toast("Post copied.", "ok"); } catch { toast("Could not copy.", "danger"); }
  }
  return (
    <Card title="Social posts"
          actions={<Stack direction="row" gap="var(--s2)">
            <Button size="sm" variant="ghost" onClick={() => setOpen((x) => !x)}>{open ? "Hide" : "Show the posts"}</Button>
            <Button size="sm" variant="primary" disabled={makeAll.isPending} onClick={all}>
              📱 Make posts for {subStrand ? "this topic" : "this subject"}
            </Button>
          </Stack>}>
      <p style={{ margin: 0, color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
        Each question as a vertical video for TikTok, Reels, Shorts and WhatsApp Status — a hook, a countdown to pause and
        try, the solution with captions, your brand at the end — with a thumbnail and the post text (question, answer,
        working, hashtags) ready to paste.
      </p>
      {b && <BrandEditor brand={b} />}
      <VideoBatches grade={grade} subject={subject} subStrand={subStrand} topics={topics} />
      <BookAhead grade={grade} subject={subject} subStrand={subStrand} />
      <ScheduleExport grade={grade} subject={subject} subStrand={subStrand} ready={library.data?.ready} />
      {b && (
        <Stack direction="row" gap="var(--s3)" wrap align="center" style={{ marginTop: "var(--s2)", fontSize: "var(--text-sm)" }}>
          <label style={{ cursor: "pointer" }}>
            <input type="file" accept="image/png,image/svg+xml" style={{ display: "none" }} onChange={(e) => upload("logo", e.target.files?.[0] || null)} />
            <span style={{ textDecoration: "underline" }}>{b.logo_url ? "Replace the logo" : "Upload a logo (PNG/SVG)"}</span>
          </label>
          {b.logo_url && <Button size="sm" variant="ghost" onClick={() => upload("logo", null)}>Remove logo</Button>}
          <label style={{ cursor: "pointer" }}>
            <input type="file" accept="audio/mpeg" style={{ display: "none" }} onChange={(e) => upload("music", e.target.files?.[0] || null)} />
            <span style={{ textDecoration: "underline" }}>{b.music_url ? "Replace the music" : "Add background music (MP3)"}</span>
          </label>
          {b.music_url && <Button size="sm" variant="ghost" onClick={() => upload("music", null)}>No music</Button>}
          <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>Use music you own or that is royalty-free for social media.</span>
        </Stack>
      )}
      {open && library.error && <ErrorNotice error={library.error} />}
      {open && rows.length > 0 && (
        <>
          <p style={{ fontSize: "var(--text-sm)", margin: "var(--s3) 0 var(--s2)" }}>
            <strong>{library.data?.ready || 0}</strong> of {rows.length} ready{busy ? ` · ${busy} being made` : ""}
          </p>
          {rows.map((v: SocialState) => (
            <div key={v.question_id} style={{ display: "flex", gap: "var(--s2)", alignItems: "center", padding: "6px 0", borderBottom: "1px solid var(--line-2)", fontSize: "var(--text-sm)" }}>
              {v.thumbnail_url && v.status === "ready"
                ? <img src={v.thumbnail_url} alt="" style={{ width: 36, height: 64, objectFit: "cover", borderRadius: 4 }} />
                : <span style={{ width: 36 }} />}
              <Badge tone={v.status === "ready" ? "ok" : v.status === "failed" ? "danger" : v.status === "none" ? "neutral" : "info"}>
                {{ ready: "ready", queued: "queued", running: "making", failed: "failed", none: "not made", skipped: "skipped" }[v.status]}
              </Badge>
              <span style={{ flex: 1, minWidth: 0 }} title={v.error}>{plain(v.question_text || "").slice(0, 110)}</span>
              <Button size="sm" variant="ghost" onClick={() => onWatch(v.question_id)}>Preview</Button>
              <Button size="sm" variant="ghost" onClick={() => copy(v.post)}>📋 Post</Button>
              {v.status === "ready" && v.url && (
                <a href={v.url} download target="_blank" rel="noreferrer"><Button size="sm">⬇ MP4</Button></a>
              )}
            </div>
          ))}
        </>
      )}
    </Card>
  );
}

/** The item's MP4: make it, watch it, download it. */
function VideoControl({ questionId, voice = "" }: { questionId: string; voice?: string }) {
  const video = useVideoStatus(questionId, voice);
  const make = useMakeVideo();
  const toast = useToast();
  const [show, setShow] = React.useState(false);
  const v = video.data;
  async function start() {
    try { await make.mutateAsync({ questionId, voice }); toast("Video queued — it is drawn and voiced in the worker.", "ok"); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not queue the video.", "danger"); }
  }
  if (!v) return <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{video.isLoading ? "Checking video…" : ""}</span>;
  if (v.status === "ready" && v.url) {
    return (
      <>
        <Badge tone="ok">MP4 ready</Badge>
        <Button size="sm" variant="ghost" onClick={() => setShow((x) => !x)}>{show ? "Hide video" : "▶ Video"}</Button>
        <a href={v.url} download target="_blank" rel="noreferrer"><Button size="sm">⬇ Download MP4</Button></a>
        {show && (
          <video src={v.url} controls autoPlay style={{ flexBasis: "100%", width: "100%", borderRadius: "var(--radius)", background: "#000" }} />
        )}
      </>
    );
  }
  if (v.status === "queued" || v.status === "running") {
    return <Badge tone="info">{v.status === "running" ? "Drawing the video…" : "Video queued…"}</Badge>;
  }
  return (
    <>
      {v.status === "failed" && <Badge tone="danger" title={v.error}>Last video failed</Badge>}
      <Button size="sm" disabled={make.isPending || !v.scenes} onClick={start}>🎬 {v.status === "failed" ? "Try the MP4 again" : "Make MP4"}</Button>
    </>
  );
}

/** Every item in the scope with its video — content to download and post. */
function VideoLibrary({ grade, subject, subStrand, open, onToggle, onWatch }: {
  grade: string; subject: string; subStrand: string; open: boolean; onToggle: () => void; onWatch: (qid: string) => void;
}) {
  const library = useVideoLibrary(grade, subject, subStrand, open);
  const makeAll = useMakeVideos();
  const toast = useToast();
  const rows = library.data?.items || [];
  const busy = rows.filter((v) => v.status === "queued" || v.status === "running").length;
  async function all() {
    try {
      const out = await makeAll.mutateAsync({ grade, subject, sub_strand: subStrand || undefined, limit: 60 });
      const c = out.counts;
      toast(`Videos: ${c.queued || 0} queued, ${c.ready || 0} already made${c.failed ? `, ${c.failed} failed` : ""}.`, "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not queue the videos.", "danger"); }
  }
  return (
    <Card title="Whiteboard videos"
          actions={<Stack direction="row" gap="var(--s2)">
            <Button size="sm" variant="ghost" onClick={onToggle}>{open ? "Hide" : "Show the library"}</Button>
            <Button size="sm" variant="primary" disabled={makeAll.isPending} onClick={all}>
              🎬 Make videos for {subStrand ? "this topic" : "this subject"}
            </Button>
          </Stack>}>
      <p style={{ margin: 0, color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
        Each item drawn on a whiteboard and narrated in the Kenyan voice, as an MP4 you can post or play in class.
        Made once and kept; an edited item gets a new video.
      </p>
      {open && <HandPicker />}
      {open && library.error && <ErrorNotice error={library.error} />}
      {open && rows.length > 0 && (
        <>
          <p style={{ fontSize: "var(--text-sm)", margin: "var(--s3) 0 var(--s2)" }}>
            <strong>{library.data?.ready || 0}</strong> of {rows.length} ready{busy ? ` · ${busy} being made` : ""}
          </p>
          {rows.map((v) => (
            <div key={v.question_id} style={{ display: "flex", gap: "var(--s2)", alignItems: "center", padding: "6px 0", borderBottom: "1px solid var(--line-2)", fontSize: "var(--text-sm)" }}>
              <Badge tone={v.status === "ready" ? "ok" : v.status === "failed" ? "danger" : v.status === "none" ? "neutral" : "info"}>
                {{ ready: "ready", queued: "queued", running: "drawing", failed: "failed", none: "not made", skipped: "skipped" }[v.status]}
              </Badge>
              <span style={{ flex: 1, minWidth: 0 }} title={v.error}>{plain(v.question_text || "").slice(0, 120)}</span>
              <Button size="sm" variant="ghost" onClick={() => onWatch(v.question_id)}>✎ Open</Button>
              {v.status === "ready" && v.url && (
                <a href={v.url} download target="_blank" rel="noreferrer"><Button size="sm">⬇ MP4</Button></a>
              )}
            </div>
          ))}
        </>
      )}
    </Card>
  );
}

/** The hand that writes: the drawn one, or a photo of a real hand. Upload a
 *  PNG cut out on a transparent background, click the pen's tip, save. */
function HandPicker() {
  const current = useHandPhoto();
  const save = useSetHandPhoto();
  const clear = useClearHandPhoto();
  const toast = useToast();
  const [file, setFile] = React.useState<File | null>(null);
  const [preview, setPreview] = React.useState<string | null>(null);
  const [tip, setTip] = React.useState<{ x: number; y: number } | null>(null);
  const [width, setWidth] = React.useState(300);
  const imgRef = React.useRef<HTMLImageElement>(null);

  React.useEffect(() => {
    const c = current.data;
    if (!c) return;
    setWidth(c.width || 300);
    if (c.tip && !file) {
      const [x, y] = c.tip.split(",").map(Number);
      setTip({ x, y });
    }
  }, [current.data, file]);
  React.useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);

  const shown = preview || current.data?.image || null;
  function pick(f: File | null) {
    if (!f) return;
    if (f.type !== "image/png") return toast("Use a PNG cut out on a transparent background.", "danger");
    setFile(f); setTip(null); setPreview(URL.createObjectURL(f));
  }
  function mark(e: React.MouseEvent<HTMLImageElement>) {
    const img = imgRef.current;
    if (!img) return;
    const r = img.getBoundingClientRect();
    setTip({ x: Math.round((e.clientX - r.left) * (img.naturalWidth / r.width)),
             y: Math.round((e.clientY - r.top) * (img.naturalHeight / r.height)) });
  }
  async function submit() {
    if (!tip) return toast("Click the pen's tip on the photo first.", "info");
    try {
      await save.mutateAsync({ file, tip_x: tip.x, tip_y: tip.y, width });
      setFile(null); setPreview(null);
      toast("Hand saved — the whiteboard writes with it now. Videos re-render with it.", "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not save the hand.", "danger"); }
  }
  async function useDrawn() {
    try { await clear.mutateAsync(); setTip(null); setFile(null); setPreview(null); toast("Back to the drawn hand.", "ok"); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not change the hand.", "danger"); }
  }
  const img = imgRef.current;
  const dot = tip && img && img.naturalWidth
    ? { left: `${(tip.x / img.naturalWidth) * 100}%`, top: `${(tip.y / img.naturalHeight) * 100}%` } : null;

  return (
    <div style={{ marginTop: "var(--s3)", padding: "var(--s3)", border: "1px solid var(--line-2)", borderRadius: "var(--radius)" }}>
      <Stack direction="row" gap="var(--s2)" wrap align="center">
        <strong style={{ fontSize: "var(--text-sm)" }}>The hand</strong>
        <Badge tone={current.data?.image ? "ok" : "neutral"}>{current.data?.image ? "Photo of a real hand" : "Drawn hand"}</Badge>
        <span style={{ flex: 1 }} />
        <label style={{ cursor: "pointer" }}>
          <input type="file" accept="image/png" style={{ display: "none" }} onChange={(e) => pick(e.target.files?.[0] || null)} />
          <span style={{ fontSize: "var(--text-sm)", textDecoration: "underline" }}>Upload a hand photo (PNG)</span>
        </label>
        {current.data?.image && <Button size="sm" variant="ghost" disabled={clear.isPending} onClick={useDrawn}>Use the drawn hand</Button>}
      </Stack>
      <p style={{ margin: "var(--s2) 0", color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
        A photo of a hand holding a pen, cut out on a transparent background (remove.bg or any photo editor does it).
        Use a photo you took or are licensed to use. Then click the pen's tip.
      </p>
      {shown && (
        <Stack direction="row" gap="var(--s3)" wrap align="start">
          <div style={{ position: "relative", display: "inline-block", background: "repeating-conic-gradient(#eee 0 25%, #fff 0 50%) 0 0/16px 16px", borderRadius: 6 }}>
            <img ref={imgRef} src={shown} alt="Hand" onClick={mark} onLoad={() => setTip((t) => (t ? { ...t } : t))}
                 style={{ display: "block", maxWidth: 260, maxHeight: 260, cursor: "crosshair" }} />
            {dot && <span style={{ position: "absolute", ...dot, width: 12, height: 12, marginLeft: -6, marginTop: -6, borderRadius: 6, background: "#dc2626", border: "2px solid #fff", pointerEvents: "none" }} />}
          </div>
          <div style={{ fontSize: "var(--text-sm)", display: "grid", gap: "var(--s2)" }}>
            <span>{tip ? `Pen tip at ${tip.x}, ${tip.y}` : "Click the pen's tip on the photo."}</span>
            <label>Size on the board: {width}px
              <input type="range" min={140} max={600} step={10} value={width} onChange={(e) => setWidth(Number(e.target.value))} style={{ display: "block", width: 200 }} />
            </label>
            <Button size="sm" variant="primary" disabled={save.isPending || !tip} onClick={submit}>Save the hand</Button>
          </div>
        </Stack>
      )}
    </div>
  );
}

/** One voice from Microsoft's list; empty means the brand's default. */
function VoicePicker({ value, onChange, label, includeDefault = true }: {
  value: string; onChange: (v: string) => void; label: string; includeDefault?: boolean;
}) {
  const voices = useVoices();
  return (
    <label style={{ fontSize: "var(--text-sm)", display: "inline-flex", gap: 6, alignItems: "center" }}>{label}
      <Select value={value} onChange={(e) => onChange(e.target.value)} style={{ maxWidth: 260 }}>
        {includeDefault && <option value="">Default voice</option>}
        {(voices.data?.voices || []).map((v) => (
          <option key={v.name} value={v.name}>
            {v.name.replace(/Neural$/, "").replace(/^([a-z]{2}-[A-Z]{2})-/, "$1 · ")} — {v.gender === "Female" ? "woman" : v.gender === "Male" ? "man" : v.gender}
          </option>
        ))}
      </Select>
    </label>
  );
}

/** The look and voice of every video: brand, colours, hook, default voice. */
function BrandEditor({ brand }: { brand: SocialBrand }) {
  const save = useSaveBrand();
  const toast = useToast();
  const [form, setForm] = React.useState<SocialBrand>(brand);
  React.useEffect(() => setForm(brand), [brand]);
  const set = (k: keyof SocialBrand) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm((f) => ({ ...f, [k]: k === "countdown" ? Number(e.target.value) : e.target.value }));
  async function submit() {
    try {
      await save.mutateAsync({ name: form.name, handle: form.handle, website: form.website, cta: form.cta, hook: form.hook,
        countdown: form.countdown, hashtags: form.hashtags, bg_from: form.bg_from, bg_to: form.bg_to, accent: form.accent,
        text: form.text, voice: form.voice, rate: form.rate });
      toast("Brand saved — new videos use it.", "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not save the brand.", "danger"); }
  }
  const field = (label: string, k: keyof SocialBrand, placeholder = "") => (
    <label style={{ display: "grid", gap: 4, fontSize: "var(--text-xs)" }}>{label}
      <Input value={String(form[k] ?? "")} placeholder={placeholder} onChange={set(k)} />
    </label>
  );
  const colour = (label: string, k: keyof SocialBrand) => (
    <label style={{ display: "inline-flex", gap: 6, alignItems: "center", fontSize: "var(--text-xs)" }}>
      <input type="color" value={String(form[k] || "#000000")} onChange={set(k)} style={{ width: 36, height: 28, border: 0, padding: 0, background: "none" }} />
      {label}
    </label>
  );
  return (
    <details style={{ marginTop: "var(--s3)" }}>
      <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)" }}>
        Brand & voice — <strong>{brand.name}</strong> {brand.handle || ""} · {brand.voice || "default voice"}
      </summary>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "var(--s2)", marginTop: "var(--s2)" }}>
        {field("Brand name", "name")}
        {field("Handle", "handle", "@yourhandle")}
        {field("Website", "website")}
        {field("Hook line", "hook", "Can you solve this?")}
        {field("Call to action", "cta")}
        {field("Extra hashtags", "hashtags", "#MathsWithMwalimu")}
        <label style={{ display: "grid", gap: 4, fontSize: "var(--text-xs)" }}>Countdown (seconds)
          <Input type="number" min={3} max={10} value={String(form.countdown)} onChange={set("countdown")} />
        </label>
        <label style={{ display: "grid", gap: 4, fontSize: "var(--text-xs)" }}>Speaking speed
          <Select value={form.rate || "-8%"} onChange={set("rate")}>
            {["-15%", "-10%", "-8%", "-5%", "+0%", "+5%", "+10%"].map((r) => <option key={r} value={r}>{r === "+0%" ? "Normal" : r}</option>)}
          </Select>
        </label>
      </div>
      <Stack direction="row" gap="var(--s3)" wrap align="center" style={{ marginTop: "var(--s2)" }}>
        {colour("Background top", "bg_from")}
        {colour("Background bottom", "bg_to")}
        {colour("Highlight", "accent")}
        {colour("Text", "text")}
        <span style={{ width: 120, height: 28, borderRadius: 6, background: `linear-gradient(${form.bg_from}, ${form.bg_to})`,
                       color: form.accent, fontWeight: 800, fontSize: 12, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
          {form.hook || "Can you solve this?"}
        </span>
      </Stack>
      <Stack direction="row" gap="var(--s3)" wrap align="center" style={{ marginTop: "var(--s2)" }}>
        <VoicePicker value={form.voice || ""} onChange={(v) => setForm((f) => ({ ...f, voice: v }))} label="Default voice" />
        <Button size="sm" variant="primary" disabled={save.isPending} onClick={submit}>Save brand</Button>
      </Stack>
    </details>
  );
}

const PLATFORM_LABEL: Record<string, string> = { tiktok: "TikTok", instagram: "Instagram", youtube: "YouTube Shorts",
  facebook: "Facebook", whatsapp: "WhatsApp", x: "X" };

/** The finished posts of the scope as one zip, with a posting calendar. */
/** Queue batches of new social videos and follow them to the end. */
function VideoBatches({ grade, subject, subStrand, topics }: { grade: string; subject: string; subStrand: string; topics: string[] }) {
  const [open, setOpen] = React.useState(false);
  const batches = useVideoBatches(open);
  const drive = useDriveStatus(open);
  const moveToDrive = useMoveToDrive();
  const queue = useQueueBatch();
  const act = useBatchAction();
  const toast = useToast();
  const [count, setCount] = React.useState(50);
  const [mix, setMix] = React.useState(true);
  const [label, setLabel] = React.useState("");
  const [picked, setPicked] = React.useState<string[]>(subStrand ? [subStrand] : []);
  React.useEffect(() => setPicked(subStrand ? [subStrand] : []), [subStrand]);
  const toggle = (t: string) => setPicked((xs) => (xs.includes(t) ? xs.filter((x) => x !== t) : [...xs, t]));
  async function go() {
    try {
      const out = await queue.mutateAsync({ grade, subject, sub_strands: picked, count, mix, label });
      const had = Object.entries(out.already || {}).map(([k, v]) => `${v} ${k}`).join(", ");
      toast(out.queued ? `Queued ${out.queued} videos${had ? ` (skipped: ${had})` : ""}.` : out.note || "Nothing new to make here.",
            out.queued ? "ok" : "info");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not queue the batch.", "danger"); }
  }
  async function batchAction(b: VideoBatch, action: "cancel" | "retry") {
    try {
      const out = await act.mutateAsync({ batch_id: b.batch_id, action });
      toast(action === "cancel" ? `Cancelled ${out.cancelled ?? 0} waiting video(s).` : `Retrying ${out.retried ?? 0} failed video(s).`, "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not do that.", "danger"); }
  }
  const eta = (s: number | null) => (s == null ? "" : s < 90 ? "about a minute" : s < 5400 ? `about ${Math.round(s / 60)} min` : `about ${(s / 3600).toFixed(1)} h`);
  // Time a render has been going: exact, not an estimate.
  const elapsed = (s: number) => (s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`);
  const list = batches.data?.batches || [];
  return (
    <details style={{ marginTop: "var(--s3)" }} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)" }}>
        🎬 Video batches{list.some((b) => !b.finished) ? ` — ${list.filter((b) => !b.finished).length} in progress` : ""}
      </summary>
      <p style={{ margin: "var(--s2) 0", color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
        Queue new videos in one go: only questions with no video made or on its way are picked, from the whole subject or
        the topics you tick, mixed unless you say otherwise. Videos render {batches.data?.renders_at_once ?? 1} at a time
        {batches.data?.seconds_per_video ? `, about ${Math.round(batches.data.seconds_per_video / 60) || 1} min each` : ""}.
        Book them for the poster once they are made.
      </p>
      <Stack direction="row" gap="var(--s3)" wrap align="end">
        <label style={lbl}>Videos<Input type="number" min={1} max={500} value={count} onChange={(e) => setCount(Math.max(1, Number(e.target.value) || 1))} style={{ width: 90 }} /></label>
        <label style={lbl}>Name (optional)<Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. October week 2" style={{ width: 180 }} /></label>
        <label style={{ display: "inline-flex", gap: 4, alignItems: "center", fontSize: "var(--text-sm)" }}>
          <input type="checkbox" checked={mix} onChange={() => setMix((x) => !x)} />Mix the topics
        </label>
        <Button size="sm" variant="primary" disabled={queue.isPending || !grade || !subject} onClick={go}>
          {queue.isPending ? "Queueing…" : `Queue ${count} videos`}
        </Button>
      </Stack>
      {topics.length > 0 && (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: "var(--text-xs)", marginTop: "var(--s2)" }}>
          <span style={{ color: "var(--ink-3)" }}>{picked.length ? `${picked.length} topic(s):` : "Whole subject — or tick topics:"}</span>
          {topics.map((t) => (
            <label key={t} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
              <input type="checkbox" checked={picked.includes(t)} onChange={() => toggle(t)} />{t}
            </label>
          ))}
        </div>
      )}
      {drive.data && (
        <div style={{ marginTop: "var(--s2)", fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
          {!drive.data.configured ? (
            <>☁️ Google Drive is not set up — videos stay on the server. Run <code>backend/scripts/drive_auth.py</code> and add its three lines to the server's .env.</>
          ) : (
            <Stack direction="row" gap="var(--s2)" align="center" wrap>
              <span>
                ☁️ Google Drive: {drive.data.moved ?? 0} file(s) moved ({drive.data.moved_mb ?? 0} MB)
                {drive.data.freed ? ` · ${drive.data.freed_mb} MB freed on the server` : ""}
                {` · the server keeps its copy ${drive.data.keep_local_days} day(s)`}
              </span>
              {drive.data.job ? (
                <Badge tone="info">
                  moving{drive.data.job.live?.total ? ` ${drive.data.job.live.n}/${drive.data.job.live.total}` : "…"}
                </Badge>
              ) : (
                <Button size="sm" variant="ghost" disabled={moveToDrive.isPending}
                        onClick={async () => {
                          try { await moveToDrive.mutateAsync(); toast("Moving finished videos to Google Drive.", "ok"); }
                          catch (err) { toast(err instanceof Error ? err.message : "Could not start the move.", "danger"); }
                        }}>Move to Drive now</Button>
              )}
            </Stack>
          )}
        </div>
      )}
      {list.length > 0 && (
        <div style={{ display: "grid", gap: 6, marginTop: "var(--s3)" }}>
          {list.map((b) => {
            const pct = b.progress_pct ?? (b.total ? Math.round((100 * b.done) / b.total) : 0);
            return (
              <div key={b.batch_id} style={{ border: "1px solid var(--line-2)", borderRadius: "var(--radius)", padding: "6px 10px", fontSize: "var(--text-sm)" }}>
                <Stack direction="row" gap="var(--s2)" align="center" wrap>
                  <strong>{b.label || b.batch_id}</strong>
                  <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{new Date(b.created_at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
                  <span style={{ flex: 1 }} />
                  <span>{b.done}/{b.total} made</span>
                  {b.running > 0 && <Badge tone="info">{b.running} rendering</Badge>}
                  {b.waiting > 0 && <Badge tone="neutral">{b.waiting} waiting</Badge>}
                  {b.failed > 0 && <Badge tone="danger">{b.failed} failed</Badge>}
                  {b.cancelled > 0 && <Badge tone="neutral">{b.cancelled} cancelled</Badge>}
                  {b.finished ? <Badge tone="ok">finished</Badge> : b.eta_seconds ? <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>done in {eta(b.eta_seconds)}</span> : null}
                  {b.waiting > 0 && <Button size="sm" variant="ghost" disabled={act.isPending} onClick={() => batchAction(b, "cancel")}>Cancel waiting</Button>}
                  {b.failed > 0 && <Button size="sm" variant="ghost" disabled={act.isPending} onClick={() => batchAction(b, "retry")}>Retry failed</Button>}
                </Stack>
                <div style={{ height: 4, background: "var(--line-2)", borderRadius: 2, marginTop: 4 }}>
                  <div style={{ width: `${pct}%`, height: 4, background: "var(--ok, #16a34a)", borderRadius: 2, transition: "width 0.6s ease" }} />
                </div>
                {(b.rendering || []).map((r) => (
                  <div key={r.job_id} style={{ marginTop: 6, fontSize: "var(--text-xs)" }}>
                    <Stack direction="row" gap="var(--s2)" align="center" wrap>
                      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={r.title}>
                        🎞️ {r.title || r.question_id}
                      </span>
                      <span style={{ color: "var(--ink-3)" }}>
                        {r.stage}{r.frame ? ` · frame ${r.frame}` : ""} · {Math.round(r.pct)}% · {elapsed(r.seconds)}
                      </span>
                      {r.resumed && <Badge tone="neutral">resumed after a restart</Badge>}
                    </Stack>
                    <div style={{ height: 3, background: "var(--line-2)", borderRadius: 2, marginTop: 2 }}>
                      <div style={{ width: `${r.pct}%`, height: 3, background: "var(--accent, #2563eb)", borderRadius: 2, transition: "width 0.6s ease" }} />
                    </div>
                  </div>
                ))}
                {(b.resumed || 0) > 0 && !(b.rendering || []).length && !b.finished && (
                  <div style={{ marginTop: 4, fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
                    {b.resumed} video(s) were cut off by a restart and put back in the queue — nothing lost.
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </details>
  );
}

/** The owner's groups: which take turns in the day's shares. */
function Groups({ groups, sharesPerDay, restDays, perPost, busy, online, onRead }: {
  groups: PosterGroup[]; sharesPerDay: number; restDays: number; perPost: number; busy: boolean; online: boolean; onRead: () => void;
}) {
  const save = useSaveGroups();
  const toast = useToast();
  const [picked, setPicked] = React.useState<string[] | null>(null);
  const chosen = picked ?? groups.filter((g) => g.enabled).map((g) => g.name);
  const dirty = picked !== null;
  const toggle = (n: string) => setPicked((chosen.includes(n) ? chosen.filter((x) => x !== n) : [...chosen, n]));
  async function store() {
    try { await save.mutateAsync(chosen); setPicked(null); toast(`${chosen.length} group(s) will get shares.`, "ok"); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not save.", "danger"); }
  }
  const when = (t: string | null) => (t ? new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "never");
  return (
    <details>
      <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)" }}>
        👥 Facebook groups — {groups.filter((g) => g.enabled).length} ticked{sharesPerDay ? `, ${sharesPerDay} share(s) a day` : ", sharing off"}
      </summary>
      <p style={{ margin: "var(--s2) 0", color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
        Each day {sharesPerDay === 2 ? "two videos (one before 1 pm, one after) are" : `${sharesPerDay} video(s) are`} also
        shared to the next {perPost} ticked group{perPost === 1 ? "" : "s"} in turn, the ones rested longest — so the shares go round
        every ticked group before any gets a second. A group gets at most one share in {restDays} days. Facebook will
        not schedule a reel that goes to a group, so those go out live at their time: keep the Mac awake for them. Tick only
        groups that welcome teaching posts.
      </p>
      <Stack direction="row" gap="var(--s2)" wrap align="center">
        <Button size="sm" variant="ghost" disabled={busy || !online} onClick={onRead}>Read my groups from Facebook</Button>
        {dirty && <Button size="sm" variant="primary" disabled={save.isPending} onClick={store}>Save</Button>}
      </Stack>
      {groups.length ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 4, marginTop: "var(--s2)", fontSize: "var(--text-sm)" }}>
          {groups.map((g) => (
            <label key={g.name} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="checkbox" checked={chosen.includes(g.name)} onChange={() => toggle(g.name)} />
              <span style={{ flex: 1 }}>{g.name}</span>
              <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{when(g.last_shared_for)}</span>
            </label>
          ))}
        </div>
      ) : <p style={{ margin: "var(--s2) 0 0", fontSize: "var(--text-xs)" }}>No groups yet — press "Read my groups from Facebook".</p>}
    </details>
  );
}

const MAX_GROUPS_PER_POST = 5;

/** Up to five of the owner's groups, picked by hand, for the next video now. */
function PickGroups({ groups, busy, onPost }: { groups: PosterGroup[]; busy: boolean; onPost: (names: string[]) => void }) {
  const [picked, setPicked] = React.useState<string[]>([]);
  const full = picked.length >= MAX_GROUPS_PER_POST;
  const toggle = (n: string) => setPicked((xs) => (xs.includes(n) ? xs.filter((x) => x !== n) : full ? xs : [...xs, n]));
  const when = (t: string | null) => (t ? new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "never");
  // Rested longest first: the groups that have waited go to the top.
  const order = [...groups].sort((a, b) => (a.last_shared_for || "").localeCompare(b.last_shared_for || "") || a.name.localeCompare(b.name));
  return (
    <div style={{ border: "1px solid var(--line-2)", borderRadius: "var(--radius)", padding: "var(--s2)", display: "grid", gap: "var(--s2)" }}>
      <Stack direction="row" gap="var(--s2)" align="center" wrap style={{ fontSize: "var(--text-sm)" }}>
        <strong>Pick up to {MAX_GROUPS_PER_POST} groups</strong>
        <span style={{ color: "var(--ink-3)" }}>{picked.length} of {MAX_GROUPS_PER_POST} picked — the next video goes to your feed and these, now.</span>
        <span style={{ flex: 1 }} />
        <Button size="sm" variant="primary" disabled={busy || !picked.length} onClick={() => onPost(picked)}>
          Post now to {picked.length || ""} group{picked.length === 1 ? "" : "s"}
        </Button>
      </Stack>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 4, fontSize: "var(--text-sm)" }}>
        {order.map((g) => (
          <label key={g.name} style={{ display: "flex", gap: 6, alignItems: "center", opacity: full && !picked.includes(g.name) ? 0.5 : 1 }}>
            <input type="checkbox" checked={picked.includes(g.name)} disabled={full && !picked.includes(g.name)} onChange={() => toggle(g.name)} />
            <span style={{ flex: 1 }}>{g.name}</span>
            <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>last {when(g.last_shared_for)}</span>
          </label>
        ))}
      </div>
    </div>
  );
}

/** Set the poster up on another Mac: one command to paste in its Terminal. */
function AnotherMac() {
  const link = usePosterMacLink();
  const toast = useToast();
  const got = link.data;
  async function make() {
    try { await link.mutateAsync(); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not make the link.", "danger"); }
  }
  async function copy() {
    try { await navigator.clipboard.writeText(got?.command || ""); toast("Copied — paste it in the other Mac's Terminal.", "ok"); }
    catch { toast("Select the command and copy it.", "info"); }
  }
  return (
    <details>
      <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)" }}>💻 Set up the poster on another Mac</summary>
      <div style={{ display: "grid", gap: "var(--s2)", marginTop: "var(--s2)", fontSize: "var(--text-sm)" }}>
        <p style={{ margin: 0, color: "var(--ink-3)" }}>
          Run the poster on a Mac you don't use much, so it posts while you work. That Mac needs Google Chrome and Python 3.10
          or newer. Make a link, then paste the command in that Mac's Terminal. It installs the poster with a new key for your
          account, so you don't copy anything across. Only one Mac posts at a time: the one started most recently. Any other
          Mac waits on standby, so nothing is posted twice.
        </p>
        <Stack direction="row" gap="var(--s2)" wrap align="center">
          <Button size="sm" disabled={link.isPending} onClick={make}>{got ? "Make a new link" : "Make an install link"}</Button>
          {got && <Button size="sm" variant="ghost" onClick={copy}>Copy command</Button>}
          {got && <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>Works once, for {got.expires_in_minutes} minutes.</span>}
        </Stack>
        {got && (
          <code style={{ display: "block", padding: "var(--s2)", background: "var(--surface-2, #f4f4f2)", borderRadius: "var(--radius)",
                         wordBreak: "break-all", fontSize: "var(--text-xs)" }}>{got.command}</code>
        )}
        {got && <p style={{ margin: 0, color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{got.note} Then, on that Mac: bash ~/.cbc/poster/login.sh to log in to each site.</p>}
      </div>
    </details>
  );
}

/** Keep the next weeks booked for the browser poster. */
function BookAhead({ grade, subject, subStrand }: { grade: string; subject: string; subStrand: string }) {
  const book = useBookAhead();
  const toast = useToast();
  const [days, setDays] = React.useState(25);
  const [low, setLow] = React.useState(5);
  const [high, setHigh] = React.useState(15);
  const [wholeSubject, setWholeSubject] = React.useState(true);
  const [platforms, setPlatforms] = React.useState<string[]>(["facebook"]);
  const [total, setTotal] = React.useState(0);
  const [readyOnly, setReadyOnly] = React.useState(false);
  const [plan, setPlan] = React.useState<BookingPlan | null>(null);
  const toggle = (p: string) => setPlatforms((xs) => (xs.includes(p) ? xs.filter((x) => x !== p) : [...xs, p]));
  async function go(dry: boolean) {
    try {
      const out = await book.mutateAsync({ grade, subject, sub_strand: wholeSubject ? "" : subStrand, days, low, high, platforms, dry, total, ready_only: readyOnly });
      setPlan(out);
      if (!dry) toast(out.posts ? `Booked ${out.videos} videos (${out.posts} posts) from ${out.first_day} to ${out.last_day}.`
                                : out.notes[0] || "Nothing to add.", out.posts ? "ok" : "info");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not book.", "danger"); }
  }
  const fmt = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  return (
    <details style={{ marginTop: "var(--s3)" }}>
      <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)" }}>🗓 Book the next weeks for the auto-poster</summary>
      <p style={{ margin: "var(--s2) 0", color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
        Each day gets a random number of videos at random times within posting hours; each video goes to every platform you
        tick at its own time. Videos not made yet are queued now, the soonest first. No question is booked twice. Run it
        every two weeks or every month — it starts after the last booked day and fills up to {days} days ahead. On Facebook
        the poster uploads them early with Facebook's own Schedule (up to 29 days ahead).
      </p>
      <Stack direction="row" gap="var(--s3)" wrap align="end">
        <Button size="sm" variant="ghost" onClick={() => { setDays(7); setTotal(100); setLow(5); setHigh(15); setReadyOnly(false); }}>100 in a week</Button>
        <label style={{ display: "inline-flex", gap: 4, alignItems: "center", fontSize: "var(--text-sm)" }}>
          <input type="checkbox" checked={readyOnly} onChange={() => setReadyOnly((x) => !x)} />Only videos already made
        </label>
        <label style={lbl}>Days ahead<Input type="number" min={1} max={62} value={days} onChange={(e) => setDays(Number(e.target.value) || 25)} style={{ width: 80 }} /></label>
        <label style={lbl}>Videos in all (0 = as the day ranges give)<Input type="number" min={0} max={1000} value={total} onChange={(e) => setTotal(Math.max(0, Number(e.target.value) || 0))} style={{ width: 100 }} /></label>
        <label style={lbl}>Videos a day, at least<Input type="number" min={1} max={30} value={low} onChange={(e) => setLow(Number(e.target.value) || 1)} style={{ width: 80 }} /></label>
        <label style={lbl}>at most<Input type="number" min={1} max={30} value={high} onChange={(e) => setHigh(Number(e.target.value) || 1)} style={{ width: 80 }} /></label>
        <label style={{ display: "inline-flex", gap: 4, alignItems: "center", fontSize: "var(--text-sm)" }}>
          <input type="checkbox" checked={wholeSubject || !subStrand} disabled={!subStrand} onChange={() => setWholeSubject((x) => !x)} />
          Whole subject{subStrand && !wholeSubject ? "" : " (all topics, mixed)"}
        </label>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: "var(--text-sm)" }}>
          {["facebook", "tiktok", "instagram", "youtube", "linkedin"].map((p) => (
            <label key={p} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
              <input type="checkbox" checked={platforms.includes(p)} onChange={() => toggle(p)} />{PLATFORM_LABEL[p] || p}
            </label>
          ))}
        </div>
        <Button size="sm" variant="ghost" disabled={book.isPending || !platforms.length || !subject} onClick={() => go(true)}>Preview</Button>
        <Button size="sm" variant="primary" disabled={book.isPending || !platforms.length || !subject} onClick={() => go(false)}>
          {book.isPending ? "Booking…" : `Book ${days} days`}
        </Button>
      </Stack>
      {plan && (
        <div style={{ marginTop: "var(--s2)", fontSize: "var(--text-sm)", display: "grid", gap: 6 }}>
          <strong>
            {plan.booked ? "Booked" : "Preview"}: {plan.videos} videos, {plan.posts} posts
            {plan.first_day ? ` · ${fmt(plan.first_day)} – ${fmt(plan.last_day || plan.first_day)}` : ""}
            {plan.to_render ? ` · ${plan.to_render} videos ${plan.booked ? "queued to be made" : "to make"}` : ""}
          </strong>
          {plan.notes.map((n) => <span key={n} style={{ color: "var(--warn, var(--ink-2))" }}>{n}</span>)}
          {plan.days.length > 0 && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: 6 }}>
              {plan.days.map((d) => (
                <div key={d.date} title={d.times.join("\n")}
                     style={{ border: "1px solid var(--line-2)", borderRadius: "var(--radius)", padding: "4px 8px", fontSize: "var(--text-xs)" }}>
                  <strong>{fmt(d.date)}</strong> · {d.videos} video{d.videos === 1 ? "" : "s"}
                  <div style={{ color: "var(--ink-3)" }}>{d.times.slice(0, 3).map((t) => t.split(" ")[0]).join(", ")}{d.times.length > 3 ? " …" : ""}</div>
                </div>
              ))}
            </div>
          )}
          {!plan.booked && plan.posts > 0 && <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>Nothing is booked until you press "Book". Hover a day for its times.</span>}
        </div>
      )}
    </details>
  );
}

function ScheduleExport({ grade, subject, subStrand, ready }: { grade: string; subject: string; subStrand: string; ready?: number }) {
  const exportZip = useExportSocial();
  const toast = useToast();
  const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10);
  const [start, setStart] = React.useState(tomorrow);
  const [perDay, setPerDay] = React.useState(1);
  const [times, setTimes] = React.useState("19:00");
  const [platforms, setPlatforms] = React.useState<string[]>(["tiktok", "instagram", "youtube"]);
  async function go() {
    try {
      const name = await exportZip.mutateAsync({ grade, subject, sub_strand: subStrand || undefined, start, per_day: perDay, times, platforms });
      toast(`Downloaded ${name}. The schedule is also in Performance.`, "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not build the download.", "danger"); }
  }
  const toggle = (p: string) => setPlatforms((xs) => (xs.includes(p) ? xs.filter((x) => x !== p) : [...xs, p]));
  return (
    <details style={{ marginTop: "var(--s3)" }}>
      <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)" }}>
        ⬇ Download all for scheduling{ready ? ` — ${ready} ready` : ""}
      </summary>
      <p style={{ margin: "var(--s2) 0", color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
        One zip: every finished video, thumbnail and caption, numbered in posting order, with a schedule.csv for your
        scheduling tool (Buffer, Metricool, Meta Business Suite, YouTube Studio…). Make the videos first; only finished
        ones are included.
      </p>
      <Stack direction="row" gap="var(--s3)" wrap align="end">
        <label style={lbl}>First day<Input type="date" value={start} onChange={(e) => setStart(e.target.value)} /></label>
        <label style={lbl}>Posts a day
          <Select value={String(perDay)} onChange={(e) => {
            const n = Number(e.target.value); setPerDay(n);
            setTimes(["19:00", "07:00,19:00", "07:00,13:00,19:00"][n - 1] || "19:00");
          }}>{[1, 2, 3].map((n) => <option key={n} value={n}>{n}</option>)}</Select>
        </label>
        <label style={lbl}>Times (EAT)<Input value={times} onChange={(e) => setTimes(e.target.value)} placeholder="07:00,19:00" /></label>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", fontSize: "var(--text-sm)" }}>
          {["tiktok", "instagram", "youtube", "facebook", "whatsapp"].map((p) => (
            <label key={p} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
              <input type="checkbox" checked={platforms.includes(p)} onChange={() => toggle(p)} />{PLATFORM_LABEL[p]}
            </label>
          ))}
        </div>
        <Button size="sm" variant="primary" disabled={exportZip.isPending || !platforms.length} onClick={go}>
          {exportZip.isPending ? "Building the zip…" : "⬇ Download zip"}
        </Button>
      </Stack>
    </details>
  );
}

/** How each video did, platform by platform and topic by topic. */
function Performance({ grade, subject, subStrand }: { grade: string; subject: string; subStrand: string }) {
  const posts = useSocialPosts(grade, subject, subStrand);
  const [platform, setPlatform] = React.useState("");
  const data = posts.data;
  if (!data || !data.posts.length) {
    return (
      <Card title="Performance">
        <p style={{ margin: 0, color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
          Nothing tracked yet. Download posts for scheduling (in Social posts) and each one appears here, per platform,
          ready for its link and numbers.
        </p>
      </Card>
    );
  }
  const rows = data.posts.filter((p) => !platform || p.platform === platform);
  const s = data.summary;
  return (
    <Card title="Performance">
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(170px, 1fr))", gap: "var(--s2)" }}>
        <Rollup title="All platforms" r={s.overall} />
        {Object.entries(s.by_platform).map(([p, r]) => <Rollup key={p} title={PLATFORM_LABEL[p] || p} r={r} />)}
      </div>
      {Object.keys(s.by_topic).length > 1 && (
        <div style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)" }}>
          <strong>By topic</strong>
          {Object.entries(s.by_topic).sort((a, b) => b[1].views_per_post - a[1].views_per_post).map(([t, r]) => (
            <div key={t} style={{ display: "flex", gap: "var(--s3)", padding: "2px 0" }}>
              <span style={{ flex: 1 }}>{t}</span><span>{r.views_per_post} views/post</span>
              <span>{r.engagement_rate}% engaged</span><span>{r.follows} follows</span>
            </div>
          ))}
        </div>
      )}
      <Stack direction="row" gap="var(--s2)" wrap align="center" style={{ margin: "var(--s3) 0 var(--s2)" }}>
        <strong style={{ fontSize: "var(--text-sm)" }}>Posts</strong>
        <Select value={platform} onChange={(e) => setPlatform(e.target.value)}>
          <option value="">All platforms</option>
          {Object.keys(s.by_platform).map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p] || p}</option>)}
        </Select>
        <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
          Paste the link when a post goes out; update the numbers from each app's insights every few days.
        </span>
      </Stack>
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--text-xs)" }}>
          <thead><tr style={{ textAlign: "left", color: "var(--ink-3)" }}>
            {["When", "Platform", "Question", "Link", "Views", "Likes", "Comments", "Shares", "Saves", "Follows", "Watched %", ""].map((h) => <th key={h} style={{ padding: 4 }}>{h}</th>)}
          </tr></thead>
          <tbody>{rows.map((p) => <PostRow key={p.post_id} post={p} />)}</tbody>
        </table>
      </div>
    </Card>
  );
}

function Rollup({ title, r }: { title: string; r: PostRollup }) {
  return (
    <div style={{ border: "1px solid var(--line-2)", borderRadius: "var(--radius)", padding: "var(--s2)", fontSize: "var(--text-xs)" }}>
      <div style={{ fontWeight: 700, fontSize: "var(--text-sm)" }}>{title}</div>
      <div>{r.posts} posted{r.planned ? ` · ${r.planned} planned` : ""}</div>
      <div><strong>{r.views.toLocaleString()}</strong> views · {r.views_per_post} per post</div>
      <div>{r.engagement_rate}% engaged · {r.follows} follows ({r.follows_per_1000_views}/1k views)</div>
      {r.avg_watch_pct != null && <div>{r.avg_watch_pct}% watched on average</div>}
    </div>
  );
}

function PostRow({ post }: { post: TrackedPost }) {
  const save = useSavePost();
  const remove = useDeletePost();
  const toast = useToast();
  const [draft, setDraft] = React.useState(post);
  React.useEffect(() => setDraft(post), [post]);
  const when = post.posted_at || post.scheduled_for;
  async function commit(changes: Partial<TrackedPost> & { posted?: boolean }) {
    try { await save.mutateAsync({ post_id: post.post_id, ...changes }); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not save.", "danger"); }
  }
  const num = (k: "views" | "likes" | "comments" | "shares" | "saves" | "follows") => (
    <td style={{ padding: 2 }}>
      <input type="number" min={0} value={draft[k]} style={{ width: 64 }}
             onChange={(e) => setDraft({ ...draft, [k]: Number(e.target.value) })}
             onBlur={() => draft[k] !== post[k] && commit({ [k]: draft[k] })} />
    </td>
  );
  return (
    <tr style={{ borderTop: "1px solid var(--line-2)" }}>
      <td style={{ padding: 4, whiteSpace: "nowrap" }}>
        {when ? new Date(when).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—"}
        <div>{post.posted_at
          ? (post.platform_scheduled && new Date(post.posted_at) > new Date() ? <Badge tone="info">scheduled on {PLATFORM_LABEL[post.platform] || post.platform}</Badge> : <Badge tone="ok">posted</Badge>)
          : <Button size="sm" variant="ghost" onClick={() => commit({ posted: true })}>Mark posted</Button>}</div>
        {((post.destinations || []).length > 0 || (post.groups || []).length > 0) && (
          <div style={{ display: "flex", gap: 3, flexWrap: "wrap", marginTop: 2 }}>
            {(post.destinations || []).map((d) => <Badge key={d} tone="neutral">{d}</Badge>)}
            {(post.groups || []).map((g) => <Badge key={g} tone="neutral">👥 {g}</Badge>)}
          </div>
        )}
      </td>
      <td style={{ padding: 4 }}>{PLATFORM_LABEL[post.platform] || post.platform}</td>
      <td style={{ padding: 4, maxWidth: 260 }}>{plain(post.question_text || "").slice(0, 90)}</td>
      <td style={{ padding: 2 }}>
        <input value={draft.url} placeholder="paste link" style={{ width: 150 }}
               onChange={(e) => setDraft({ ...draft, url: e.target.value })}
               onBlur={() => draft.url !== post.url && commit({ url: draft.url, ...(draft.url && !post.posted_at ? { posted: true } : {}) })} />
        {post.url && <a href={post.url} target="_blank" rel="noreferrer" style={{ marginLeft: 4 }}>↗</a>}
      </td>
      {num("views")}{num("likes")}{num("comments")}{num("shares")}{num("saves")}{num("follows")}
      <td style={{ padding: 2 }}>
        <input type="number" min={0} max={100} value={draft.watch_pct ?? ""} style={{ width: 56 }}
               onChange={(e) => setDraft({ ...draft, watch_pct: e.target.value === "" ? null : Number(e.target.value) })}
               onBlur={() => draft.watch_pct !== post.watch_pct && draft.watch_pct != null && commit({ watch_pct: draft.watch_pct })} />
      </td>
      <td style={{ padding: 2 }}>
        <Button size="sm" variant="ghost" onClick={() => remove.mutate(post.post_id)}>✕</Button>
      </td>
    </tr>
  );
}

/** The browser poster: its screen, its logins, its queue. It posts from the
 *  sessions logged into on its screen, within the server's rules. */
function AutoPost() {
  const [open, setOpen] = React.useState(false);
  const overview = usePosterOverview(open);
  const command = usePosterCommand();
  const toast = useToast();
  const o = overview.data;
  const [picking, setPicking] = React.useState(false);
  async function run(action: "login" | "check" | "dry_run" | "run_now" | "pause" | "resume" | "groups", platform = "",
                     options?: { share?: "feed" | "groups"; groups?: string[] }) {
    try {
      const out = await command.mutateAsync({ action, platform, options });
      if (out?.error) toast(String(out.error), "danger");
      else if (out?.message) toast(String(out.message), "info");
      else if (action === "dry_run") toast(out?.ok ? `Dry run on ${platform} reached the last step — see the screenshot.` : `Dry run stopped: ${out?.error || "see the screenshot"}`, out?.ok ? "ok" : "danger");
      else toast("Done.", "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "The poster did not answer.", "danger"); }
  }
  const states = Object.fromEntries((o?.states || []).map((s) => [s.platform, s]));
  const platforms = o?.live?.online ? ["tiktok", "instagram", "facebook", "youtube", "linkedin"] : (o?.rules.platforms || []);
  const today = Object.values(o?.posted_today || {}).reduce((a, b) => a + b, 0);
  const local = o?.live?.mode === "local";
  return (
    <Card title="Auto-post (browser)"
          actions={<Button size="sm" variant="ghost" onClick={() => setOpen((x) => !x)}>{open ? "Hide" : "Open"}</Button>}>
      <p style={{ margin: 0, color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
        A real browser — Chrome on your Mac, or the one on the server — publishes your scheduled posts from the accounts you
        log into yourself — at most
        {` ${o?.rules.daily_cap ?? 30}`} a day across every channel, spaced out, within posting hours. It stops for any
        "is this you?" check for you to finish. Posting through the websites is against the platforms' rules: keep the volume
        low and watch the first runs.
      </p>
      {open && overview.error && <ErrorNotice error={overview.error} />}
      {open && o && (
        <div style={{ display: "grid", gap: "var(--s3)", marginTop: "var(--s3)" }}>
          <Stack direction="row" gap="var(--s2)" wrap align="center" style={{ fontSize: "var(--text-sm)" }}>
            <Badge tone={o.live.online ? (o.live.paused ? "warn" : "ok") : "danger"}>
              {o.live.online ? (o.live.paused ? "Paused" : o.live.busy || "Running") : "Poster offline"}
            </Badge>
            {o.live.online && <Badge tone="neutral">{local ? `On ${o.live.poster_id || "your Mac"}` : "On the server"}</Badge>}
            <Badge tone={o.rules.enabled ? "ok" : "neutral"}>{o.rules.enabled ? "Auto-post on" : "Auto-post off (Settings → Auto-post)"}</Badge>
            <span>{today} of {o.rules.daily_cap} posted today · {o.rules.min_gap_minutes} min apart · {o.rules.hours.start}–{o.rules.hours.end} EAT</span>
            <span style={{ flex: 1 }} />
            {o.live.online && (o.live.paused
              ? <Button size="sm" onClick={() => run("resume")}>▶ Resume</Button>
              : <Button size="sm" variant="ghost" onClick={() => run("pause")}>❚❚ Pause</Button>)}
            {o.live.online && <Button size="sm" variant="ghost" disabled={command.isPending} onClick={() => run("run_now")}
                                      title="The next post, now, with any group share it carries">Post next now</Button>}
          </Stack>
          {o.live.online && (
            <Stack direction="row" gap="var(--s2)" wrap align="center" style={{ fontSize: "var(--text-sm)" }}>
              <span style={{ color: "var(--ink-3)" }}>Post the next video now:</span>
              <Button size="sm" variant="ghost" disabled={command.isPending} onClick={() => run("run_now", "", { share: "feed" })}>
                Post to feed
              </Button>
              <Button size="sm" variant="ghost" disabled={command.isPending || !(o.groups || []).some((g) => g.enabled)}
                      title="Facebook: your feed and the next ticked groups in turn, the ones rested longest"
                      onClick={() => run("run_now", "facebook", { share: "groups" })}>
                Post to feed + {o.rules.groups_per_post ?? 5} groups
              </Button>
              <Button size="sm" variant={picking ? "primary" : "ghost"} disabled={!(o.groups || []).length}
                      onClick={() => setPicking((x) => !x)}>Pick groups…</Button>
            </Stack>
          )}
          {o.live.online && picking && (
            <PickGroups groups={o.groups || []} busy={command.isPending}
                        onPost={async (names) => { await run("run_now", "facebook", { share: "groups", groups: names }); setPicking(false); }} />
          )}
          {!o.live.online && <p style={{ margin: 0, fontSize: "var(--text-sm)" }}>{o.live.error || "No poster is running. On your Mac: bash poster/mac/install.sh — or start the social-poster service on the server."}</p>}
          <AnotherMac />
          {o.live.note && <p style={{ margin: 0, fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{o.live.note}</p>}

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))", gap: "var(--s2)" }}>
            {platforms.map((p) => {
              const st = states[p];
              return (
                <div key={p} style={{ border: "1px solid var(--line-2)", borderRadius: "var(--radius)", padding: "var(--s2)", fontSize: "var(--text-xs)", display: "grid", gap: 6 }}>
                  <Stack direction="row" gap="var(--s2)" align="center">
                    <strong style={{ fontSize: "var(--text-sm)" }}>{PLATFORM_LABEL[p] || p}</strong>
                    <Badge tone={st ? (st.logged_in ? "ok" : "danger") : "neutral"}>{st ? (st.logged_in ? "logged in" : "needs login") : "not checked"}</Badge>
                  </Stack>
                  <span>{o.posted_today[p] || 0} posted today</span>
                  {st?.note && !st.logged_in && <span style={{ color: "var(--danger)" }}>{st.note}</span>}
                  <Stack direction="row" gap="4px" wrap>
                    <Button size="sm" variant="ghost" disabled={!o.live.online || command.isPending} onClick={() => run("login", p)}>Log in</Button>
                    <Button size="sm" variant="ghost" disabled={!o.live.online || command.isPending} onClick={() => run("check", p)}>Check</Button>
                    <Button size="sm" disabled={!o.live.online || command.isPending} onClick={() => run("dry_run", p)}>Dry run</Button>
                  </Stack>
                </div>
              );
            })}
          </div>

          {local ? (
            <p style={{ margin: 0, fontSize: "var(--text-sm)" }}>
              The browser is Chrome on <strong>{o.live.poster_id || "your Mac"}</strong>, in a window of its own. Press "Log in"
              and sign in there yourself; it picks up commands within a few seconds. Keep the Mac on and the lid open while it posts.
            </p>
          ) : o.view_url ? (
            <div>
              <Stack direction="row" gap="var(--s2)" align="center" style={{ marginBottom: 6, fontSize: "var(--text-sm)" }}>
                <strong>The browser's screen</strong>
                <a href={o.view_url} target="_blank" rel="noreferrer" style={{ fontSize: "var(--text-xs)" }}>open in a new tab ↗</a>
                <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>Press "Log in", then sign in here. It asks for the screen password.</span>
              </Stack>
              <iframe title="Poster screen" src={o.view_url} style={{ width: "100%", height: 560, border: "1px solid var(--line)", borderRadius: "var(--radius)", background: "#000" }} />
            </div>
          ) : (
            <p style={{ margin: 0, fontSize: "var(--text-sm)" }}>Set Settings → Public address to show the browser's screen here.</p>
          )}

          {(o.scheduled_ahead?.count || o.handed_today || o.waiting) ? (
            <p style={{ margin: 0, fontSize: "var(--text-sm)" }}>
              {o.scheduled_ahead?.count ? <>📅 <strong>{o.scheduled_ahead.count}</strong> scheduled on Facebook
                {o.scheduled_ahead.until ? ` (to ${new Date(o.scheduled_ahead.until).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })})` : ""} — Facebook
                publishes them even with the Mac off. </> : null}
              {o.waiting ? <>{o.waiting} booked and waiting. </> : null}
              {o.handed_today ? <>{o.handed_today} uploaded or posted today.</> : null}
            </p>
          ) : null}

          <Groups groups={o.groups || []} sharesPerDay={o.rules.group_shares_per_day ?? 2} restDays={o.rules.group_rest_days ?? 7}
                  perPost={o.rules.groups_per_post ?? 5}
                  busy={command.isPending} online={o.live.online} onRead={() => run("groups", "facebook")} />

          {o.live.last && <LastAttempt last={o.live.last} />}

          {o.queue.length > 0 && (
            <details>
              <summary style={{ cursor: "pointer", fontSize: "var(--text-sm)" }}>Queue — {o.queue.length} waiting</summary>
              {o.queue.map((q) => (
                <div key={q.post_id} style={{ display: "flex", gap: "var(--s2)", fontSize: "var(--text-xs)", padding: "3px 0", borderBottom: "1px solid var(--line-2)" }}>
                  <span style={{ width: 140 }}>{q.scheduled_for ? new Date(q.scheduled_for).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—"}</span>
                  <span style={{ width: 90 }}>{PLATFORM_LABEL[q.platform] || q.platform}</span>
                  <span style={{ flex: 1 }}>{q.question_id}</span>
                  {q.attempts > 0 && <span title={q.last_error} style={{ color: "var(--danger)" }}>{q.attempts} failed</span>}
                </div>
              ))}
            </details>
          )}
        </div>
      )}
    </Card>
  );
}

function LastAttempt({ last }: { last: NonNullable<PosterOverview["live"]["last"]> }) {
  const img = usePosterShot(last.shot || "");
  return (
    <div style={{ fontSize: "var(--text-sm)" }}>
      <strong>Last {last.dry_run ? "dry run" : "attempt"}:</strong> {PLATFORM_LABEL[last.platform] || last.platform} —{" "}
      {last.ok ? <span style={{ color: "var(--ok)" }}>{last.dry_run ? "reached the last step" : "posted"}</span>
               : <span style={{ color: "var(--danger)" }}>{last.error}</span>}
      {last.url && <> · <a href={last.url} target="_blank" rel="noreferrer">view ↗</a></>}
      {img.data && <img src={img.data} alt="What the browser showed" style={{ display: "block", marginTop: 6, maxWidth: "100%", maxHeight: 360, border: "1px solid var(--line)", borderRadius: 6 }} />}
    </div>
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
