import React from "react";
import { Badge, Button, Card, ErrorNotice, Field, Input, LoadingBlock, PageHeader, Select, Stack, useToast } from "../ui/components";
import { useChemLabHtml, useChemReact, useChemSeparations, useChemSubstances, useSeparationBank, type ChemMix } from "../lib/queries";

const CONDITIONS: [string, string][] = [["", "Mixed (room temperature)"], ["heat", "Heated"], ["steam", "With steam"],
                                         ["molten", "Molten (no water)"], ["boil", "Boiled"]];

/** The chemistry lab: pick two substances (or one, and heat it), mix them, and
 *  watch what happens — the reaction worked out by the chemistry engine,
 *  balanced, with what you would see, and the walkthrough on the whiteboard. */
export function ChemLab() {
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
      <PageHeader eyebrow="Play" title="Chemistry lab"
        description="Pick two substances — or one, and heat it — and mix; or pick an element for its electron arrangement, two elements to see them bond, or a mixture to separate. The chemistry engine works out what happens by the rules of school chemistry (the reactivity series, acids, bases, carbonates, solubility, burning, heating): the balanced equation, what you would see, how to test the gas, and where it is used — then explains it on the whiteboard." />
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
                      onClick={() => setParts((cur) => cur.includes(m) ? cur.filter((x) => x !== m) : [...cur, m].slice(-3))}>{m}</Button>
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
      {mode === "separate" && <SeparationBank />}
      <style>{`@media (max-width: 900px) { .chem-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}

const FOCUS_LABELS: Record<string, string> = { method: "Which method", order: "Order of steps", residue: "Residue / filtrate",
  layer: "Which layer", first: "What distils first", why: "Why it works", apparatus: "Which apparatus" };

/** Every mixture the separation rules decide, as questions in the bank — so
 *  Social batches can make a video of each. */
function SeparationBank() {
  const sum = useChemSeparations();
  const save = useSeparationBank();
  const toast = useToast();
  const [grade, setGrade] = React.useState("Grade 7");
  const [subject, setSubject] = React.useState("Integrated Science");
  const [strand, setStrand] = React.useState("Mixtures, Elements and Compounds");
  const [subStrand, setSubStrand] = React.useState("Mixtures");
  const [limit, setLimit] = React.useState(500);
  const [focuses, setFocuses] = React.useState<string[]>([]);
  const d = sum.data;
  const run = () => save.mutate({ grade, subject, strand, sub_strand: subStrand, limit, focuses }, {
    onSuccess: (r) => toast(`${r.saved} new questions saved${r.already ? ` (${r.already} were already there)` : ""}. Make their videos in Play → Social batches.`, "ok"),
    onError: (e) => toast(String((e as Error).message || e), "danger"),
  });
  return (
    <Card title="Separation questions for videos">
      {sum.isLoading && <LoadingBlock rows={2} label="Counting the mixtures" />}
      {d && (
        <div style={{ display: "grid", gap: "var(--s3)" }}>
          <div>
            The rules know <b>{d.substances}</b> substances and decide <b>{d.mixtures.toLocaleString()}</b> mixtures of two or three
            parts — <b>{d.questions.toLocaleString()}</b> questions, each with its own animated walkthrough.
          </div>
          <Stack direction="row" gap="var(--s2)" wrap>
            {Object.entries(d.by_method).map(([m, n]) => <Badge key={m}>{m.replace(/_/g, " ")}: {n.toLocaleString()}</Badge>)}
          </Stack>
          <details><summary style={{ cursor: "pointer" }}>Some of the questions</summary>
            <ul style={{ margin: 0, paddingLeft: "1.2rem" }}>{d.sample.map((q) => <li key={q}>{q}</li>)}</ul>
          </details>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(12rem, 1fr))", gap: "var(--s2)" }}>
            <Field label="Grade">{(p) => <Input {...p} value={grade} onChange={(e) => setGrade(e.target.value)} />}</Field>
            <Field label="Subject">{(p) => <Input {...p} value={subject} onChange={(e) => setSubject(e.target.value)} />}</Field>
            <Field label="Strand">{(p) => <Input {...p} value={strand} onChange={(e) => setStrand(e.target.value)} />}</Field>
            <Field label="Sub-strand">{(p) => <Input {...p} value={subStrand} onChange={(e) => setSubStrand(e.target.value)} />}</Field>
            <Field label="How many">{(p) => <Input {...p} type="number" min={1} max={5000} value={limit} onChange={(e) => setLimit(Math.max(1, Math.min(5000, Number(e.target.value) || 1)))} />}</Field>
          </div>
          <Stack direction="row" gap="var(--s2)" wrap align="center">
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>Kinds (none picked: all):</span>
            {Object.entries(FOCUS_LABELS).map(([f, l]) => (
              <Button key={f} size="sm" variant={focuses.includes(f) ? "primary" : "ghost"}
                      onClick={() => setFocuses((cur) => cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f])}>{l}</Button>
            ))}
          </Stack>
          <div>
            <Button variant="primary" onClick={run} disabled={save.isPending || !grade || !subject || !subStrand}>
              {save.isPending ? "Saving…" : `💾 Save ${limit.toLocaleString()} questions to the bank`}
            </Button>
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)", marginTop: 6 }}>
              Spread across every method and kind; saving again adds only new ones. Check the grade, subject and sub-strand
              match your curriculum, then make their videos in Play → Social batches.
            </div>
          </div>
        </div>
      )}
      {sum.error && <ErrorNotice error={sum.error} />}
    </Card>
  );
}
