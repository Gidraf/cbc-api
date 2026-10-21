import React from "react";
import { Badge, Button, Card, ErrorNotice, LoadingBlock, PageHeader, Select, Stack } from "../ui/components";
import { useChemLabHtml, useChemReact, useChemSubstances } from "../lib/queries";

const CONDITIONS: [string, string][] = [["", "Mixed (room temperature)"], ["heat", "Heated"], ["steam", "With steam"],
                                         ["molten", "Molten (no water)"], ["boil", "Boiled"]];

/** The chemistry lab: pick two substances (or one, and heat it), mix them, and
 *  watch what happens — the reaction worked out by the chemistry engine,
 *  balanced, with what you would see, and the walkthrough on the whiteboard. */
export function ChemLab() {
  const shelf = useChemSubstances();
  const [a, setA] = React.useState("Zn");
  const [b, setB] = React.useState("CuSO4");
  const [condition, setCondition] = React.useState("");
  const [mix, setMix] = React.useState<{ a: string; b: string; condition: string } | null>(null);
  const result = useChemReact(mix);
  const board = useChemLabHtml(mix);
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
        description="Pick two substances — or one, and heat it — and mix. The chemistry engine works out what happens by the rules of school chemistry (the reactivity series, acids, bases, carbonates, solubility, burning, heating): the balanced equation, what you would see, how to test the gas, and where it is used — then explains it on the whiteboard." />
      <Card>
        {!shelf.data ? <LoadingBlock rows={2} label="Loading the shelf" /> : (
          <Stack direction="row" gap="var(--s2)" wrap align="center">
            {picker(a, setA)}
            <span style={{ fontSize: 22 }}>+</span>
            {picker(b, setB, true)}
            <Select value={condition} onChange={(e) => setCondition(e.target.value)} style={{ width: "auto" }}>
              {CONDITIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </Select>
            <Button variant="primary" onClick={() => setMix({ a, b, condition })}>⚗️ Mix</Button>
          </Stack>
        )}
      </Card>
      {result.error && <ErrorNotice error={result.error} />}
      {mix && !r && result.isLoading && <Card><LoadingBlock rows={3} label="Working it out" /></Card>}
      {r && (
        <div className="chem-grid" style={{ display: "grid", gridTemplateColumns: "minmax(18rem, 26rem) 1fr", gap: "var(--s4)", alignItems: "start" }}>
          <Card title={r.reacts ? "It reacts" : r.covered ? "No reaction" : "Not covered"}>
            <div style={{ display: "grid", gap: "var(--s2)", fontSize: "var(--text-sm)" }}>
              {r.reacts ? (
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
            {board.isLoading && <LoadingBlock rows={4} label="Drawing and voicing it" />}
            {board.error && <ErrorNotice error={board.error} />}
            {board.data && <iframe title="chemistry walkthrough" srcDoc={board.data}
                                   style={{ width: "100%", aspectRatio: "16 / 9.6", border: 0, borderRadius: 8, background: "#fdfdfb" }} />}
          </Card>
        </div>
      )}
      <style>{`@media (max-width: 900px) { .chem-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}
