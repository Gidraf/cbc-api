import React from "react";
import { Badge, Button, Card, Field, Input, Select, Stack, useToast } from "../ui/components";
import { useOrderJob, useOrderScope, usePlaceOrder, useStoredStructure } from "../lib/queries";

/**
 * One request, one printed product.
 *
 * "A Grade 7 mid-term 1 paper" was eleven buttons across three screens. This
 * is one: the order works out which sub-strands the term covers, runs what
 * is missing (guides, figures, items), composes the paper in the national
 * format, freezes it, and hands back the print links here.
 */
export function ProducePanel({ grade, subject }: { grade: string; subject: string }) {
  const toast = useToast();
  const [kind, setKind] = React.useState<"term" | "topical" | "strand">("term");
  const [term, setTerm] = React.useState(1);
  const [strand, setStrand] = React.useState("");
  const [subStrand, setSubStrand] = React.useState("");
  const [count, setCount] = React.useState(30);
  const [jobId, setJobId] = React.useState("");

  const structure = useStoredStructure(grade, subject);
  const strands = structure.data?.strands || [];
  const subStrands = (strands.find((s) => s.strand_name === strand)?.sub_strands || []) as any[];
  const scope = useOrderScope({ grade, subject, kind, term, strand, sub_strand: subStrand });
  const place = usePlaceOrder();
  const job = useOrderJob(jobId);

  async function produce() {
    try {
      const res = await place.mutateAsync({ grade, subject, kind, term, strand, sub_strand: subStrand, count });
      setJobId(res.job.job_id);
      toast(`Order queued for ${res.scope.length} sub-strand(s). This page follows it.`, "ok");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not place the order.", "danger");
    }
  }

  const rows = scope.data?.scope || [];
  const missing = rows.filter((r) => !r.has_notes || r.items < 20).length;
  const status = job.data?.status;
  const result = job.data?.result || {};
  const urls: Record<string, string> = result.render_urls || result.paper?.render_urls || {};
  const progress: { what: string; detail: string; status: string }[] = result.progress || [];

  return (
    <Card title="Produce a paper" description="One order: the guides, figures and questions it still needs, then the paper, frozen and ready to print." accent="accent">
      <Stack gap="var(--s3)">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "var(--s3)" }}>
          <Field label="Paper">
            {(p) => (
              <Select {...p} value={kind} onChange={(e) => setKind(e.target.value as any)}>
                <option value="term">End of term / mid-term</option>
                <option value="strand">End of strand</option>
                <option value="topical">Topical test</option>
              </Select>
            )}
          </Field>
          {kind === "term" && (
            <Field label="Term">
              {(p) => (
                <Select {...p} value={term} onChange={(e) => setTerm(Number(e.target.value))}>
                  <option value={1}>Term 1</option><option value={2}>Term 2</option><option value={3}>Term 3</option>
                </Select>
              )}
            </Field>
          )}
          {kind !== "term" && (
            <Field label="Strand">
              {(p) => (
                <Select {...p} value={strand} onChange={(e) => { setStrand(e.target.value); setSubStrand(""); }}>
                  <option value="">Choose a strand</option>
                  {strands.map((s) => <option key={s.strand_name} value={s.strand_name}>{s.strand_name}</option>)}
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
                    <option key={ss.sub_strand_name || ss.name} value={ss.sub_strand_name || ss.name}>{ss.sub_strand_name || ss.name}</option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <Field label="Questions">
            {(p) => <Input {...p} type="number" min={10} max={100} value={count} onChange={(e) => setCount(Number(e.target.value) || 30)} />}
          </Field>
        </div>

        {rows.length > 0 && (
          <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            <Stack direction="row" gap="var(--s2)" wrap>
              <span>Covers {rows.length} sub-strand{rows.length === 1 ? "" : "s"}:</span>
              {rows.map((r) => (
                <Badge key={r.sub_strand} tone={r.has_notes && r.items >= 20 ? "ok" : "warn"}
                       title={`${r.has_notes ? "guide filed" : "no guide"} · ${r.figures} figure(s) · ${r.items} item(s) in the bank`}>
                  {r.sub_strand}
                </Badge>
              ))}
            </Stack>
            <div style={{ marginTop: "var(--s1)" }}>
              {missing === 0 ? "Everything exists; the order composes and freezes the paper."
                : `${missing} sub-strand(s) still need a guide or items — the order writes them first (this is the part that takes time and money).`}
            </div>
          </div>
        )}

        <Stack direction="row" gap="var(--s2)" wrap align="center">
          <Button variant="primary" disabled={!grade || !subject || rows.length === 0 || place.isPending} onClick={produce}>
            {place.isPending ? "Placing…" : "Produce"}
          </Button>
          {status && <Badge tone={status === "done" ? "ok" : status === "failed" ? "danger" : "info"}>{status}</Badge>}
          {job.data?.error && <span style={{ color: "var(--danger)", fontSize: "var(--text-sm)" }}>{job.data.error}</span>}
        </Stack>

        {progress.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: "1.2em", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            {progress.map((p, i) => <li key={i}><b>{p.what}</b> — {p.detail}</li>)}
          </ul>
        )}

        {status === "done" && urls.paper && (
          <div style={{ border: "1px solid var(--ok)", borderRadius: "var(--radius-sm)", padding: "var(--s3)" }}>
            <Stack gap="var(--s2)">
              <strong>{result.paper?.title || "Paper"} — {result.paper?.question_count} questions, {result.paper?.total_marks} marks</strong>
              <Stack direction="row" gap="var(--s2)" wrap>
                <a href={urls.paper} target="_blank" rel="noreferrer"><Button variant="primary">Print paper</Button></a>
                <a href={urls.marking_scheme} target="_blank" rel="noreferrer"><Button>Marking scheme</Button></a>
                <a href={urls.booklet_pdf} target="_blank" rel="noreferrer"><Button variant="ghost">Booklet PDF</Button></a>
              </Stack>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
                Frozen as <code>{result.paper?.exam_id}</code>. The paper carries a QR code to its marking scheme.
              </div>
            </Stack>
          </div>
        )}
      </Stack>
    </Card>
  );
}
