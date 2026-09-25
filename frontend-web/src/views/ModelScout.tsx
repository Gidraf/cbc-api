import React from "react";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Grid,
  LoadingBlock,
  PageHeader,
  Stack,
  Stat,
  Table,
  Td,
  Th,
  useToast,
} from "../ui/components";
import {
  useModelScout,
  useRefreshPrices,
  useRunModelScout,
  useScoutDecision,
  type ScoutMetrics,
  type ScoutRecommendation,
} from "../lib/queries";

const TIER: Record<string, string> = { writer: "Writing", reader: "Reading" };
const STATUS_TONE: Record<string, "ok" | "warn" | "danger" | "info" | "neutral" | "accent"> = {
  pending: "accent", approved: "ok", rejected: "neutral", rolled_back: "warn",
  superseded: "neutral", not_recommended: "neutral",
};

const usd = (n: number | string | null | undefined, digits = 4) =>
  n === null || n === undefined || n === "" ? "—" : `$${Number(n).toFixed(digits)}`;
const pct = (n: number) => `${Math.round(n * 100)}%`;
const when = (s: string | null | undefined) => (s ? new Date(s).toLocaleString() : "—");

/**
 * The weekly model scout, for admins: which models are in use, what a cheaper
 * or newer one did on the same sub-strands this week, and the switch — which
 * happens only when an admin approves it here, and can be undone here.
 */
export function ModelScout() {
  const scout = useModelScout();
  const run = useRunModelScout();
  const refresh = useRefreshPrices();
  const decide = useScoutDecision();
  const toast = useToast();
  const d = scout.data;

  async function act(rec: ScoutRecommendation, action: "approve" | "reject" | "rollback") {
    if (action === "approve" && !window.confirm(
      `Switch every ${TIER[rec.tier].toLowerCase()} station from ${rec.current_model} to ${rec.candidate_model}?`)) return;
    if (action === "rollback" && !window.confirm(`Put ${rec.current_model} back?`)) return;
    try {
      await decide.mutateAsync({ rec_id: rec.rec_id, action });
      toast(action === "approve" ? `${TIER[rec.tier]} now runs on ${rec.candidate_model}.`
        : action === "rollback" ? `${TIER[rec.tier]} is back on ${rec.current_model}.` : "Rejected.", "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not do that.", "danger"); }
  }

  async function runNow() {
    try {
      const out = await run.mutateAsync();
      toast(`Queued (${out.job_id}). It takes its turn on the Queue board; results appear here.`, "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not queue a run.", "danger"); }
  }

  async function readPrices() {
    try {
      const out = await refresh.mutateAsync();
      toast(out.problems?.length ? `Prices not updated: ${out.problems.join("; ")}`
        : `Read ${out.read} prices: ${out.new?.length || 0} new, ${out.changed?.length || 0} changed.`,
        out.problems?.length ? "danger" : "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not read prices.", "danger"); }
  }

  const header = (
    <PageHeader
      eyebrow="Operate"
      title="Model scout"
      description="Once a week the scout reads OpenAI's prices and tries any cheaper or new model on the same sub-strands as the models in use, through the real questions station, keeping nothing it writes. It recommends; only an admin switches."
      actions={
        <Stack direction="row" gap="var(--s2)" wrap>
          <Button size="sm" variant="secondary" loading={refresh.isPending} onClick={readPrices}
                  title="Read the pricing page now. No trials, no spend.">
            Read prices
          </Button>
          <Button size="sm" variant="primary" loading={run.isPending} onClick={runNow}
                  title="Queue a full run now instead of waiting for Monday">
            Run now
          </Button>
        </Stack>
      }
    />
  );

  if (scout.isPending) return <>{header}<LoadingBlock rows={4} label="Reading the scout" /></>;
  if (scout.error) return <>{header}<ErrorNotice error={scout.error} onRetry={() => scout.refetch()} /></>;
  if (!d) return header;

  const pending = d.recommendations.filter((r) => r.status === "pending");
  const decided = d.recommendations.filter((r) => ["approved", "rejected", "rolled_back"].includes(r.status));
  const tried = d.recommendations.filter((r) => r.status === "not_recommended").slice(0, 8);
  const lastRun = d.runs[0];

  return (
    <>
      {header}
      <Grid min="11rem">
        <Stat label="Writing model" value={d.in_use.writer} sub="notes, questions, diagrams, review" />
        <Stat label="Reading model" value={d.in_use.reader} sub="extraction, classifying, research" />
        <Stat label="To approve" value={pending.length} tone={pending.length ? "accent" : undefined} />
        <Stat label="Last run" value={lastRun ? lastRun.status : "never"}
              tone={lastRun?.status === "failed" ? "danger" : undefined}
              sub={lastRun ? `${when(lastRun.started_at)} · ${usd(lastRun.cost_usd, 2)}` : `weekly, Monday 02:00 · budget ${usd(d.budget_usd, 0)}`} />
      </Grid>
      {!d.enabled && (
        <Card accent="warn" title="The weekly run is switched off">
          Turn on “Weekly model scout” in Settings to have it run every Monday. “Run now” still works.
        </Card>
      )}

      <Card title="Waiting for your decision"
            description="Tried this week on the same sub-strands as the model in use, and at least as good for less per kept question.">
        {pending.length === 0 ? (
          <EmptyState title="Nothing to approve" description={lastRun?.summary?.notes?.[0] || "The next run is on Monday at 02:00."} />
        ) : (
          <Stack gap="var(--s3)">
            {pending.map((r) => <Recommendation key={r.rec_id} rec={r} busy={decide.isPending} onAct={act} />)}
          </Stack>
        )}
      </Card>

      {decided.length > 0 && (
        <Card title="Decisions" description="Every switch made here, and the one in force can be put back.">
          <Table>
            <thead><tr><Th>When</Th><Th>Tier</Th><Th>Switch</Th><Th>Status</Th><Th>By</Th><Th> </Th></tr></thead>
            <tbody>
              {decided.map((r) => {
                const inForce = r.status === "approved" && d.in_use[r.tier] === r.candidate_model;
                return (
                  <tr key={r.rec_id}>
                    <Td>{when(r.decided_at)}</Td>
                    <Td>{TIER[r.tier]}</Td>
                    <Td><span className="mono">{r.current_model} → {r.candidate_model}</span></Td>
                    <Td><Badge tone={STATUS_TONE[r.status]}>{r.status.replace("_", " ")}</Badge></Td>
                    <Td>{r.decided_by || "—"}</Td>
                    <Td>{inForce && (
                      <Button size="sm" variant="secondary" disabled={decide.isPending} onClick={() => act(r, "rollback")}>
                        Roll back
                      </Button>
                    )}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        </Card>
      )}

      {tried.length > 0 && (
        <Card title="Tried and not recommended" description="Cheaper, but not good enough on the panel — kept so you can see why, and approve anyway if you disagree.">
          <Stack gap="var(--s3)">
            {tried.map((r) => <Recommendation key={r.rec_id} rec={r} busy={decide.isPending} onAct={act} muted />)}
          </Stack>
        </Card>
      )}

      {d.latest_trials.length > 0 && (
        <Card title="Latest run, sub-strand by sub-strand" description="Every trial the most recent run made. Nothing here was saved to the bank.">
          <Table>
            <thead><tr><Th>Model</Th><Th>Sub-strand</Th><Th>Gate</Th><Th numeric>Score</Th><Th numeric>Kept</Th><Th numeric>Cost</Th><Th numeric>Time</Th></tr></thead>
            <tbody>
              {d.latest_trials.map((t) => (
                <tr key={t.id}>
                  <Td><span className="mono">{t.role === "baseline" ? "in use" : t.model}</span></Td>
                  <Td>{t.subject} · {t.sub_strand}</Td>
                  <Td>{t.error ? <Badge tone="danger" title={t.error}>failed</Badge>
                    : <Badge tone={t.passed ? "ok" : "warn"}>{t.passed ? "passed" : "not passed"}</Badge>}</Td>
                  <Td numeric>{t.error ? "—" : t.score}</Td>
                  <Td numeric>{t.accepted}/{t.requested}</Td>
                  <Td numeric>{usd(t.cost_usd)}</Td>
                  <Td numeric>{Math.round(Number(t.seconds))}s</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <Card title="Prices" description="Standard tier, short context, per 1M tokens — read from OpenAI's pricing page and used to cost every run.">
        {d.prices.length === 0 ? (
          <EmptyState title="No prices read yet" description="Press “Read prices”, or wait for the weekly run." />
        ) : (
          <Table>
            <thead><tr><Th>Model</Th><Th numeric>Input</Th><Th numeric>Cached</Th><Th numeric>Output</Th><Th>First seen</Th></tr></thead>
            <tbody>
              {d.prices.map((p) => (
                <tr key={p.model}>
                  <Td>
                    <span className="mono">{p.model}</span>{" "}
                    {p.model === d.in_use.writer && <Badge tone="accent">writing</Badge>}{" "}
                    {p.model === d.in_use.reader && <Badge tone="info">reading</Badge>}
                  </Td>
                  <Td numeric>{usd(p.input_usd, 2)}</Td>
                  <Td numeric>{usd(p.cached_usd, 3)}</Td>
                  <Td numeric>{usd(p.output_usd, 2)}</Td>
                  <Td>{when(p.first_seen)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      {d.runs.length > 0 && (
        <Card title="Runs">
          <Table>
            <thead><tr><Th>Started</Th><Th>How</Th><Th>Status</Th><Th numeric>Spent</Th><Th>Notes</Th></tr></thead>
            <tbody>
              {d.runs.map((r) => (
                <tr key={r.run_id}>
                  <Td>{when(r.started_at)}</Td>
                  <Td>{r.trigger}</Td>
                  <Td><Badge tone={r.status === "done" ? "ok" : r.status === "failed" ? "danger" : "accent"}>{r.status}</Badge></Td>
                  <Td numeric>{usd(r.cost_usd, 2)}</Td>
                  <Td style={{ maxWidth: "32rem" }}>{r.error || (r.summary?.notes || []).join(" ") || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
    </>
  );
}

function Recommendation({ rec, busy, onAct, muted }: {
  rec: ScoutRecommendation; busy: boolean; muted?: boolean;
  onAct: (rec: ScoutRecommendation, action: "approve" | "reject" | "rollback") => void;
}) {
  const c = rec.metrics.candidate;
  const b = rec.metrics.baseline;
  return (
    <Card accent={muted ? undefined : "accent"}
          title={<span>{TIER[rec.tier]}: <span className="mono">{rec.current_model}</span> → <span className="mono">{rec.candidate_model}</span></span>}
          description={`Tried because it is ${rec.metrics.why_tried}. ${when(rec.created_at)}.`}
          actions={
            <Stack direction="row" gap="var(--s2)">
              <Button size="sm" variant={muted ? "secondary" : "primary"} disabled={busy} onClick={() => onAct(rec, "approve")}>
                {muted ? "Approve anyway" : "Approve switch"}
              </Button>
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => onAct(rec, "reject")}>Reject</Button>
            </Stack>
          }>
      <Table>
        <thead><tr><Th> </Th><Th numeric>Passed gate</Th><Th numeric>Mean score</Th><Th numeric>Kept items</Th><Th numeric>Failed runs</Th><Th numeric>Per kept question</Th><Th numeric>Time per run</Th></tr></thead>
        <tbody>
          <MetricRow label={`${rec.candidate_model} (trial)`} m={c} />
          <MetricRow label={`${rec.current_model} (in use)`} m={b} />
        </tbody>
      </Table>
      <ul style={{ margin: "var(--s3) 0 0", paddingLeft: "1.2rem", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
        {rec.reasons.map((reason, i) => <li key={i}>{reason}</li>)}
      </ul>
    </Card>
  );
}

function MetricRow({ label, m }: { label: string; m: ScoutMetrics }) {
  return (
    <tr>
      <Td><span className="mono">{label}</span></Td>
      <Td numeric>{m.passed}/{m.runs} ({pct(m.pass_rate)})</Td>
      <Td numeric>{m.mean_score}</Td>
      <Td numeric>{m.accepted}/{m.requested} ({pct(m.acceptance)})</Td>
      <Td numeric>{m.errors}</Td>
      <Td numeric>{usd(m.cost_per_accepted)}</Td>
      <Td numeric>{Math.round(m.mean_seconds)}s</Td>
    </tr>
  );
}
