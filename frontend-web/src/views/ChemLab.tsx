import React from "react";
import { Badge, Button, Card, EmptyState, ErrorNotice, Field, Input, LoadingBlock, PageHeader, Select, Stack, useToast } from "../ui/components";
import { gradeOptionLabel, subjectOptionLabel, useChemAutopilot, useChemAutopilotPlan, useChemBank, useChemBankSummary, useChemLabHtml, useChemReact, useChemSubstances,
         useGrades, useStoredStructure, useSubjects, type ChemKind, type ChemMix } from "../lib/queries";
import { AutoPost, BookSeries, Performance, SocialLibrary, VideoLibrary, WatchModal } from "./PlayArcade";
import { MonthPlanner } from "./MonthPlanner";
import { PhotoStudio } from "./PhotoStudio";

const CONDITIONS: [string, string][] = [["", "Mixed (room temperature)"], ["heat", "Heated"], ["steam", "With steam"],
                                         ["molten", "Molten (no water)"], ["boil", "Boiled"]];

/** The chemistry lab: pick two substances (or one, and heat it), mix them, and
 *  watch what happens — the reaction worked out by the chemistry engine,
 *  balanced, with what you would see, and the walkthrough on the whiteboard. */
export function ChemLab() {
  type Tab = "lab" | "socials";
  const [tab, setTabState] = React.useState<Tab>(() => {
    try { return (localStorage.getItem("cbc_chem_tab") as Tab) || "lab"; } catch { return "lab"; }
  });
  const setTab = (t: Tab) => { setTabState(t); try { localStorage.setItem("cbc_chem_tab", t); } catch { /* private window */ } };
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader eyebrow="Assess" title="Chemistry lab"
        description="Pick two substances — or one, and heat it — and mix; or pick an element for its electron arrangement, two elements to see them bond, or a mixture to separate. The chemistry engine works out what happens by the rules of school chemistry, then explains it on the whiteboard. In Socials, the engine's questions become videos, photo series and posts, as in Play." />
      <div role="tablist" aria-label="Chemistry lab sections" style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line)", overflowX: "auto" }}>
        {([["lab", "🧪 Lab"], ["socials", "📣 Socials"]] as const).map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}
                  style={{ background: "transparent", border: "none", padding: "8px 14px", cursor: "pointer", whiteSpace: "nowrap",
                           borderBottom: `2px solid ${tab === id ? "var(--accent)" : "transparent"}`, fontWeight: tab === id ? 650 : 500, color: "var(--ink)" }}>
            {label}
          </button>
        ))}
      </div>
      {tab === "lab" ? <LabBench /> : <ChemSocials />}
    </div>
  );
}

/** The bench: mix, see the result, watch it on the whiteboard or as the social cut. */
function LabBench() {
  const shelf = useChemSubstances();
  const [mode, setMode] = React.useState<"react" | "atom" | "bond" | "separate">("react");
  const [a, setA] = React.useState("Zn");
  const [b, setB] = React.useState("CuSO4");
  const [condition, setCondition] = React.useState("");
  const [els, setEls] = React.useState<string[]>(["Na", "Cl"]);
  const [parts, setParts] = React.useState<string[]>(["sand", "salt"]);
  const [mix, setMix] = React.useState<ChemMix | null>(null);
  const go = () => setMix(mode === "react" ? { a, b, condition, mode }
    : mode === "atom" ? { a: els[0] || "Na", b: "", condition: "", mode }
    : mode === "bond" ? { a: els[0] || "Na", b: els[1] || "Cl", condition: "", mode }
    : { a: parts.join(","), b: "", condition: "", mode });
  const pick = (sym: string) => setEls((cur) => mode === "atom" ? [sym] : (cur.includes(sym) ? cur.filter((x) => x !== sym) : [...cur, sym].slice(-2)));
  const result = useChemReact(mix);
  const [view, setView] = React.useState<"board" | "social">("board");
  const board = useChemLabHtml(mix, view === "social");
  const r = result.data?.reaction;
  const picker = (value: string, set: (v: string) => void, allowNone = false) => (
    <Select value={value} onChange={(e) => set(e.target.value)} style={{ width: "auto", minWidth: "14rem" }}>
      {allowNone && <option value="">— nothing (heat the first) —</option>}
      {(shelf.data?.groups || []).map((g) => (
        <optgroup key={g.group} label={g.group}>
          {g.items.map((it) => <option key={it.formula} value={it.formula}>{it.pretty} — {it.name}</option>)}
        </optgroup>
      ))}
    </Select>
  );
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <Card>
        <Stack direction="row" gap="var(--s2)" wrap style={{ marginBottom: "var(--s3)" }}>
          {([["react", "⚗️ Reaction"], ["atom", "⚛️ Electron arrangement"], ["bond", "🔗 Bonding and formula"], ["separate", "🧪 Separating mixtures"]] as const).map(([m, l]) => (
            <Button key={m} size="sm" variant={mode === m ? "primary" : "ghost"} onClick={() => setMode(m)}>{l}</Button>
          ))}
        </Stack>
        {!shelf.data ? <LoadingBlock rows={2} label="Loading the shelf" /> : mode === "react" ? (
          <Stack direction="row" gap="var(--s2)" wrap align="center">
            {picker(a, setA)}
            <span style={{ fontSize: 22 }}>+</span>
            {picker(b, setB, true)}
            <Select value={condition} onChange={(e) => setCondition(e.target.value)} style={{ width: "auto" }}>
              {CONDITIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </Select>
            <Button variant="primary" onClick={go}>⚗️ Mix</Button>
          </Stack>
        ) : mode === "separate" ? (
          <Stack direction="row" gap="var(--s2)" wrap align="center">
            {shelf.data.mixtures.map((m) => (
              <Button key={m} size="sm" variant={parts.includes(m) ? "primary" : "ghost"}
                      onClick={() => setParts((cur) => cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m].slice(-4))}>{m}</Button>
            ))}
            <Button variant="primary" onClick={go} disabled={!parts.length}>🧪 Separate</Button>
          </Stack>
        ) : (
          <div style={{ display: "grid", gap: "var(--s2)" }}>
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
              {mode === "atom" ? "Pick an element." : "Pick two elements (a metal and a non-metal bond ionically; two non-metals share electrons)."}
            </span>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(18, minmax(2.1rem, 1fr))", gap: 3, maxWidth: 900 }}>
              {shelf.data.periodic.map((e) => (
                <button key={e.symbol} onClick={() => pick(e.symbol)} title={e.name}
                        style={{ gridColumn: e.group, gridRow: e.period, aspectRatio: "1", border: `2px solid ${els.includes(e.symbol) ? "var(--accent)" : "var(--line-2)"}`,
                                 borderRadius: 6, background: els.includes(e.symbol) ? "var(--accent-wash, #dff3ef)" : "transparent", cursor: "pointer",
                                 font: "inherit", color: "var(--ink)", padding: 2, display: "grid", lineHeight: 1.05 }}>
                  <span style={{ fontSize: 10, color: "var(--ink-3)" }}>{e.Z}</span>
                  <b style={{ fontSize: 15 }}>{e.symbol}</b>
                </button>
              ))}
            </div>
            <Stack direction="row" gap="var(--s2)" align="center">
              <span>{els.join(" + ") || "—"}</span>
              <Button variant="primary" onClick={go} disabled={mode === "bond" ? els.length < 2 : !els.length}>
                {mode === "atom" ? "⚛️ Show" : "🔗 Bond"}
              </Button>
            </Stack>
          </div>
        )}
      </Card>
      {result.error && <ErrorNotice error={result.error} />}
      {mix && !r && result.isLoading && <Card><LoadingBlock rows={3} label="Working it out" /></Card>}
      {r && (
        <div className="chem-grid" style={{ display: "grid", gridTemplateColumns: "minmax(18rem, 26rem) 1fr", gap: "var(--s4)", alignItems: "start" }}>
          <Card title={r.mode === "atom" ? `${r.arrangement}` : r.mode === "bond" ? `${r.formula || "No compound"}` : r.mode === "separate" ? "Method"
                       : r.reacts ? "It reacts" : r.covered ? "No reaction" : "Not covered"}>
            <div style={{ display: "grid", gap: "var(--s2)", fontSize: "var(--text-sm)" }}>
              {r.mode ? (
                <>
                  {r.mode === "atom" && <div>{r.protons} protons, {r.neutrons} neutrons · ion {r.ion}</div>}
                  {r.mode === "bond" && r.kind && <Badge tone="info">{r.kind}</Badge>}
                  {r.mode === "separate" && <div style={{ fontWeight: 600 }}>{(r.names || []).join(" → ")}</div>}
                  <div>{r.why}</div>
                  {(r.steps || []).length > 0 && <ol style={{ margin: 0, paddingLeft: "1.2rem" }}>{(r.steps || []).map((o) => <li key={o}>{o}</li>)}</ol>}
                  {(r.uses || []).length > 0 && <><b>Where it is used</b><ul style={{ margin: 0, paddingLeft: "1.2rem" }}>{(r.uses || []).map((o) => <li key={o}>{o}</li>)}</ul></>}
                </>
              ) : r.reacts ? (
                <>
                  <Badge tone="info">{(r.type || "").replace(/_/g, " ")}</Badge>
                  <div style={{ fontSize: "1.25rem", fontWeight: 600 }}>{r.equation_states}</div>
                  <div style={{ color: "var(--ink-3)" }}>{r.word}</div>
                  {r.note && <div style={{ color: "var(--warn, #b45309)" }}>{r.note}</div>}
                  <b>What you see</b>
                  <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>{(r.observations || []).map((o) => <li key={o}>{o}</li>)}</ul>
                  {r.gas_tests && Object.keys(r.gas_tests).length > 0 && (<>
                    <b>Testing the gas</b>
                    <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>{Object.entries(r.gas_tests).map(([g, t]) => <li key={g}><b>{g}</b>: {t}</li>)}</ul>
                  </>)}
                  <b>Where it is used</b>
                  <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>{(r.applications || []).map((o) => <li key={o}>{o}</li>)}</ul>
                  <details><summary style={{ cursor: "pointer" }}>The steps</summary>
                    <ol style={{ margin: 0, paddingLeft: "1.2rem" }}>{(r.steps || []).map((o) => <li key={o}>{o}</li>)}</ol>
                  </details>
                </>
              ) : <div>{r.why}</div>}
            </div>
          </Card>
          <Card title="On the whiteboard">
            <Stack direction="row" gap="var(--s2)" style={{ marginBottom: "var(--s3)" }}>
              <Button size="sm" variant={view === "board" ? "primary" : "ghost"} onClick={() => setView("board")}>🧑‍🏫 Board</Button>
              <Button size="sm" variant={view === "social" ? "primary" : "ghost"} onClick={() => setView("social")}>📱 Social (vertical)</Button>
            </Stack>
            {board.isLoading && <LoadingBlock rows={4} label={view === "social" ? "Making the vertical cut and voicing it" : "Drawing and voicing it"} />}
            {board.error && <ErrorNotice error={board.error} />}
            {board.data && (view === "social"
              ? <div style={{ display: "flex", justifyContent: "center" }}>
                  <iframe key="social" title="chemistry social cut" srcDoc={board.data} allow="autoplay"
                          style={{ width: "min(420px, 100%)", height: "74vh", border: 0, borderRadius: 8, background: "#0f172a" }} />
                </div>
              : <iframe key="board" title="chemistry walkthrough" srcDoc={board.data}
                        style={{ width: "100%", aspectRatio: "16 / 9.6", border: 0, borderRadius: 8, background: "#fdfdfb" }} />)}
          </Card>
        </div>
      )}
      <style>{`@media (max-width: 900px) { .chem-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}

const KINDS: [ChemKind, string, string][] = [
  ["reactions", "⚗️ Reactions", "What is seen, the balanced equation, the gas and its test, the type of reaction, why some do not react"],
  ["atoms", "⚛️ Electron arrangements", "The first twenty elements: arrangement, protons and neutrons, group and period, the ion"],
  ["bonding", "🔗 Bonding and formulae", "Every pair that bonds: the formula, ionic or covalent"],
  ["separations", "🧪 Separating mixtures", "Two or three parts: the method, the order, residue and filtrate, layers, why it works"],
];

/** The lab's socials: the engine's questions saved to the bank at a point of
 *  the curriculum, then Play's own tools on them — the videos and their
 *  social cuts, photo series, the posting calendar and auto-post. */
function ChemSocials() {
  const sum = useChemBankSummary();
  const save = useChemBank();
  const toast = useToast();
  const grades = useGrades();
  const [grade, setGrade] = React.useState("");
  const subjects = useSubjects(grade);
  const [subject, setSubject] = React.useState("");
  const structure = useStoredStructure(grade, subject);
  const [subStrand, setSubStrand] = React.useState("");
  const [kind, setKind] = React.useState<ChemKind>("separations");
  const [limit, setLimit] = React.useState(200);
  const [tool, setTool] = React.useState<"videos" | "photos" | "autopost">("videos");
  const [showLibrary, setShowLibrary] = React.useState(false);
  const [watching, setWatching] = React.useState<string | null>(null);
  const [socialWatch, setSocialWatch] = React.useState<string | null>(null);
  // The science subject of the grade: Integrated Science in Junior School, Chemistry in Senior School.
  React.useEffect(() => {
    const list = (subjects.data || []) as any[];
    if (!list.length || list.some((x) => x.name === subject)) return;
    const sci = list.find((x) => /chemistry/i.test(x.name)) || list.find((x) => /integrated science/i.test(x.name)) || list.find((x) => /science/i.test(x.name));
    setSubject(sci ? sci.name : list[0].name);
  }, [subjects.data, subject]);
  const topics = ((structure.data?.strands || []) as any[]).flatMap((st) =>
    (st.sub_strands || []).map((x: any) => ({ strand: String(st.strand_name || st.name || ""), name: String(x.sub_strand_name || x.name || "") })));
  const strand = topics.find((t) => t.name === subStrand)?.strand || "";
  const d = sum.data;
  const run = () => save.mutate({ kind, grade, subject, strand, sub_strand: subStrand, limit }, {
    onSuccess: (r) => toast(`${r.saved} new questions saved${r.already ? ` (${r.already} were already there)` : ""}. Make their videos and photos below.`, "ok"),
    onError: (e) => toast(String((e as Error).message || e), "danger"),
  });
  return (
    <>
      <Autopilot />
      <Card title="1. Make the questions">
        <div style={{ display: "grid", gap: "var(--s3)" }}>
          <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
            The chemistry engine writes and marks every question (multiple choice); each has the lab's animated walkthrough as its
            video. Choose what, and where in the curriculum it belongs.
          </div>
          {sum.isLoading && <LoadingBlock rows={2} label="Counting what the engine can make" />}
          {sum.error && <ErrorNotice error={sum.error} />}
          <Stack direction="row" gap="var(--s2)" wrap>
            {KINDS.map(([k, label, hint]) => (
              <Button key={k} size="sm" variant={kind === k ? "primary" : "ghost"} title={hint} onClick={() => setKind(k)}>
                {label}{d ? ` · ${d[k].questions.toLocaleString()}` : ""}
              </Button>
            ))}
          </Stack>
          {d && (
            <details><summary style={{ cursor: "pointer" }}>{KINDS.find(([k]) => k === kind)![2]} — examples</summary>
              <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>{d[kind].sample.map((q) => <li key={q}>{q}</li>)}</ul>
            </details>
          )}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(12rem, 1fr))", gap: "var(--s2)" }}>
            <Field label="Grade">{(p) => (
              <Select {...p} value={grade} onChange={(e) => { setGrade(e.target.value); setSubStrand(""); }}>
                <option value="">Choose…</option>
                {(grades.data || []).map((g) => <option key={g.slug || g.name} value={g.slug || g.name}>{gradeOptionLabel(g)}</option>)}
              </Select>)}</Field>
            <Field label="Subject">{(p) => (
              <Select {...p} value={subject} onChange={(e) => { setSubject(e.target.value); setSubStrand(""); }} disabled={!grade}>
                {((subjects.data || []) as any[]).map((x) => <option key={x.name} value={x.name}>{subjectOptionLabel(x)}</option>)}
              </Select>)}</Field>
            <Field label="Topic (sub-strand)">{(p) => (
              <Select {...p} value={subStrand} onChange={(e) => setSubStrand(e.target.value)} disabled={!grade || !subject}>
                <option value="">Choose…</option>
                {topics.map((t) => <option key={t.strand + t.name} value={t.name}>{t.name} — {t.strand}</option>)}
              </Select>)}</Field>
            <Field label="How many">{(p) => (
              <Input {...p} type="number" min={1} max={5000} value={limit} onChange={(e) => setLimit(Math.max(1, Math.min(5000, Number(e.target.value) || 1)))} />)}</Field>
          </div>
          <div>
            <Button variant="primary" onClick={run} disabled={save.isPending || !grade || !subject || !subStrand}>
              {save.isPending ? "Saving…" : `💾 Save ${limit.toLocaleString()} ${KINDS.find(([k]) => k === kind)![1].replace(/^\S+ /, "").toLowerCase()} questions to this topic`}
            </Button>
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)", marginTop: 6 }}>
              Spread across every sort of question; saving again adds only new ones. They go in the bank as approved items, so Play,
              the Library, papers and tests see them too.
            </div>
          </div>
        </div>
      </Card>

      <Card title="2. Videos, photos and posts">
        {!grade || !subject ? (
          <EmptyState title="Choose a grade and subject above" description="The videos, photo series and posting plan are per subject or topic, as in Play." />
        ) : (
          <>
            <div role="tablist" aria-label="Social tools" style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line)", marginBottom: "var(--s3)", overflowX: "auto" }}>
              {([["videos", "🎬 Videos"], ["photos", "📸 Photos"], ["autopost", "📤 Auto-post"]] as const).map(([id, label]) => (
                <button key={id} role="tab" aria-selected={tool === id} onClick={() => setTool(id)}
                        style={{ background: "transparent", border: "none", padding: "8px 14px", cursor: "pointer", whiteSpace: "nowrap",
                                 borderBottom: `2px solid ${tool === id ? "var(--accent)" : "transparent"}`, fontWeight: tool === id ? 650 : 500, color: "var(--ink)" }}>
                  {label}
                </button>
              ))}
            </div>
            {tool === "videos" && <>
              <VideoLibrary grade={grade} subject={subject} subStrand={subStrand} open={showLibrary}
                            onToggle={() => setShowLibrary((v) => !v)} onWatch={(qid) => setWatching(qid)} />
              <SocialLibrary grade={grade} subject={subject} subStrand={subStrand} topics={topics.map((t) => t.name)} onWatch={(qid) => setSocialWatch(qid)} />
              <Performance grade={grade} subject={subject} subStrand={subStrand} format="video" />
            </>}
            {tool === "photos" && (
              <PhotoStudio grade={grade} subject={subject} subStrand={subStrand}
                           bookSeries={<BookSeries grade={grade} subject={subject} subStrand={subStrand} />} />
            )}
            {tool === "autopost" && <>
              <MonthPlanner grade={grade} subject={subject} subStrand={subStrand} />
              <AutoPost />
            </>}
          </>
        )}
      </Card>
      {watching && <WatchModal questionId={watching} onClose={() => setWatching(null)} />}
      {socialWatch && <WatchModal questionId={socialWatch} start="social" onClose={() => setSocialWatch(null)} />}
    </>
  );
}

/** One button: the engine finds where each kind belongs in your stored KICD curriculum (Integrated Science
 *  or Chemistry, the grade and sub-strand), saves the questions there, books their videos into the open room
 *  of each day from tomorrow, books their photo series, and keeps booking them. */
function Autopilot() {
  const plan = useChemAutopilotPlan();
  const go = useChemAutopilot();
  const toast = useToast();
  const [perDay, setPerDay] = React.useState(0);
  const [photoDays, setPhotoDays] = React.useState(7);
  const [keep, setKeep] = React.useState(true);
  const [sepCount, setSepCount] = React.useState(1000);
  // A kind moved to another topic: its index in that kind's options (0 = the best match).
  const [choice, setChoice] = React.useState<Record<string, number>>({});
  const out = go.data;
  const rows = (out && !out.dry ? out.placements : plan.data?.placements) || [];
  const overrides: Record<string, { grade: string; subject: string; strand: string; sub_strand: string }> = {};
  for (const p of plan.data?.placements || []) {
    const o = p.options?.[choice[p.kind] || 0];
    if (o && choice[p.kind]) overrides[p.kind] = { grade: o.grade, subject: o.subject, strand: o.strand, sub_strand: o.sub_strand };
  }
  const run = () => go.mutate({ per_day: perDay, keep_booking: keep, photo_days: photoDays, counts: { separations: sepCount }, overrides }, {
    onSuccess: (r) => toast(`Booked ${(r.booked || []).reduce((a, b) => a + b.videos, 0)} videos` +
      `${(r.photos || []).length ? " and the photo series" : ""}. Videos not made yet are rendering now.`, "ok"),
    onError: (e) => toast(String((e as Error).message || e), "danger"),
  });
  return (
    <Card title="🚀 Do it all for me">
      <div style={{ display: "grid", gap: "var(--s3)" }}>
        <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
          The engine reads your KICD curriculum and puts each kind of chemistry where it is taught — Integrated Science in
          Junior School for mixtures and atoms, Chemistry in Senior School for bonding and reactions when that design is in —
          then saves the questions there, books their videos from tomorrow into each day's open room, books their photo series,
          and keeps booking them as long as there are questions.
        </div>
        {plan.isLoading && <LoadingBlock rows={2} label="Reading the curriculum" />}
        {plan.error && <ErrorNotice error={plan.error} />}
        {rows.length > 0 && (
          <div style={{ display: "grid", gap: 6 }}>
            {rows.map((p) => (
              <div key={p.kind} style={{ display: "flex", gap: "var(--s2)", flexWrap: "wrap", alignItems: "center", padding: "6px 0", borderBottom: "1px solid var(--line-2)" }}>
                <b style={{ minWidth: "11rem" }}>{p.label}</b>
                {out && !out.dry ? <span>{p.grade_label} · {p.subject} · {p.sub_strand}</span> : (
                  <Select value={String(choice[p.kind] || 0)} onChange={(e) => setChoice((c) => ({ ...c, [p.kind]: Number(e.target.value) }))}
                          style={{ width: "auto", maxWidth: "100%" }}>
                    {(p.options?.length ? p.options : [p]).map((o, i) => (
                      <option key={i} value={i}>{o.grade_label} · {o.subject} · {o.sub_strand}{i === 0 ? " (best match)" : ""}</option>
                    ))}
                  </Select>)}
                {p.kind === "separations" && !(out && !out.dry) ? (
                  <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "var(--text-sm)" }}>
                    <Input type="number" min={1} max={60000} value={sepCount} style={{ width: "7rem" }}
                           onChange={(e) => setSepCount(Math.max(1, Math.min(60000, Number(e.target.value) || 1)))} />
                    of {(p.available ?? 0).toLocaleString()}
                  </label>
                ) : (
                  <Badge>{(p.saved ?? p.questions).toLocaleString()}{p.saved == null ? ` — all ${(p.available ?? p.questions).toLocaleString()}` : " saved"}
                    {p.already ? ` (+${p.already} already there)` : ""}</Badge>
                )}
              </div>
            ))}
          </div>
        )}
        <Stack direction="row" gap="var(--s3)" wrap align="end">
          <Field label="Videos a day (0: your Auto-book setting)">{(p) => (
            <Input {...p} type="number" min={0} max={30} value={perDay} onChange={(e) => setPerDay(Math.max(0, Math.min(30, Number(e.target.value) || 0)))} />)}</Field>
          <Field label="Photo-series days per topic">{(p) => (
            <Input {...p} type="number" min={0} max={31} value={photoDays} onChange={(e) => setPhotoDays(Math.max(0, Math.min(31, Number(e.target.value) || 0)))} />)}</Field>
          <label style={{ display: "flex", gap: 6, alignItems: "center", fontSize: "var(--text-sm)" }}>
            <input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} /> Keep booking them (Auto-book)
          </label>
          <Button variant="primary" onClick={run} disabled={go.isPending || !rows.length}>
            {go.isPending ? "Saving and booking…" : "🚀 Save and schedule everything"}
          </Button>
        </Stack>
        {out && !out.dry && (
          <div style={{ fontSize: "var(--text-sm)", display: "grid", gap: 4 }}>
            {(out.booked || []).map((b) => <div key={b.month}>📅 {b.month}: {b.videos} videos booked, {b.to_render} rendering now{b.notes?.length ? ` — ${b.notes[0]}` : ""}</div>)}
            {(out.photos || []).map((p) => <div key={p.kind}>📸 {p.kind}: {p.error ? p.error : `${p.photos} photos and ${p.videos} videos, ${p.first_day} → ${p.last_day}`}</div>)}
            {out.auto_book?.enabled && <div>🔁 Auto-book is on{out.auto_book.added.length ? ` — added ${out.auto_book.added.length} chemistry topic(s)` : ""}.</div>}
          </div>
        )}
      </div>
    </Card>
  );
}
