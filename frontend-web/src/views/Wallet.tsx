import React from "react";
import { Badge, Button, Card, ErrorNotice, Field, Input, LoadingBlock, PageHeader, Stack, Stat, Table, useToast } from "../ui/components";
import { usePlan, useSubscribe, useTopUp, useTopUpStatus, useWallet } from "../lib/queries";

const KIND_LABEL: Record<string, string> = {
  topup: "M-Pesa top-up", paper: "Paper", api: "API calls", admin: "Added by CBC", refund: "Refund", plan: "Video plan",
};

function ksh(n: number) {
  return `KSh ${Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: n % 1 ? 2 : 0, maximumFractionDigits: 2 })}`;
}

/** The wallet: balance, an M-Pesa top-up, and every shilling in and out. */
export function Wallet() {
  const wallet = useWallet();
  const w = wallet.data;
  if (wallet.error) return <ErrorNotice error={wallet.error} />;
  if (!w) return <LoadingBlock rows={4} label="Loading your wallet" />;
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader title="Wallet" eyebrow="Account"
                  description="Top up with M-Pesa and pay for papers and API calls from here." />
      {w.exempt && <Card><Badge tone="accent">Staff</Badge> Your account is never charged.</Card>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "var(--s3)" }}>
        <Stat label="Balance" value={ksh(w.balance_ksh)} tone={w.balance_ksh > 0 ? "ok" : undefined} />
        <Stat label="Free questions left" value={w.free_questions_left}
              sub={`of ${w.prices.paper.free_questions}, for papers you download`} />
        <Stat label="Paper prices" value={`${ksh(w.prices.paper.text_ksh)} · ${ksh(w.prices.paper.diagram_ksh)}`}
              sub="a text question · a diagram question, paid once each" />
      </div>
      <TopUp min={w.prices.topup.min_ksh} max={w.prices.topup.max_ksh} ready={w.topups_ready} note={w.topups_note} />
      {!w.exempt && <PlanCard balance={w.balance_ksh} />}
      <Card title="History" description="Every top-up and every charge.">
        {w.entries.length ? (
          <Table caption="Wallet history">
            <thead><tr><th style={{ textAlign: "left" }}>When</th><th style={{ textAlign: "left" }}>What</th>
              <th style={{ textAlign: "left" }}>Details</th><th style={{ textAlign: "right" }}>Amount</th></tr></thead>
            <tbody>
              {w.entries.map((e, i) => (
                <tr key={i} style={{ borderTop: "1px solid var(--line)" }}>
                  <td style={{ padding: "6px 8px", whiteSpace: "nowrap" }}>{new Date(e.at).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                  <td style={{ padding: "6px 8px" }}>{KIND_LABEL[e.kind] || e.kind}</td>
                  <td style={{ padding: "6px 8px", color: "var(--ink-3)" }}>{e.note || e.ref}</td>
                  <td style={{ padding: "6px 8px", textAlign: "right", fontVariantNumeric: "tabular-nums",
                               color: e.amount_ksh > 0 ? "var(--ok)" : undefined }}>
                    {e.amount_ksh > 0 ? "+" : "−"}{ksh(Math.abs(e.amount_ksh))}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        ) : <p style={{ margin: 0, color: "var(--ink-3)" }}>Nothing yet.</p>}
      </Card>
    </div>
  );
}

/** Phone and amount, then the PIN prompt on the phone, then the result. */
export function TopUp({ min, max, ready, note, suggested }: { min: number; max: number; ready: boolean; note?: string; suggested?: number }) {
  const topUp = useTopUp();
  const toast = useToast();
  const [phone, setPhone] = React.useState(() => { try { return localStorage.getItem("cbc_mpesa_phone") || ""; } catch { return ""; } });
  const [amount, setAmount] = React.useState<number>(Math.max(min, Math.ceil(suggested || 100)));
  const [checkout, setCheckout] = React.useState("");
  const status = useTopUpStatus(checkout);
  const s = status.data;
  React.useEffect(() => { if (suggested) setAmount(Math.max(min, Math.ceil(suggested))); }, [suggested, min]);
  async function send(e: React.FormEvent) {
    e.preventDefault();
    try {
      const out = await topUp.mutateAsync({ phone, amount });
      try { localStorage.setItem("cbc_mpesa_phone", phone); } catch { /* private window */ }
      setCheckout(out.checkout_request_id);
      toast(out.message || "Check your phone and enter your M-Pesa PIN.", "info");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not start the payment.", "danger"); }
  }
  const done = s && s.status !== "pending";
  return (
    <Card title="Top up with M-Pesa" description="Your phone asks for your M-Pesa PIN. The money is in your wallet as soon as you enter it.">
      {!ready ? <p style={{ margin: 0, color: "var(--ink-3)" }}>Top-ups are not switched on yet. {note}</p> : (
        <form onSubmit={send} style={{ display: "grid", gap: "var(--s3)", maxWidth: 520 }}>
          <Stack direction="row" gap="var(--s3)" wrap>
            <div style={{ flex: "1 1 220px" }}>
              <Field label="M-Pesa number">{(p) => <Input {...p} inputMode="tel" placeholder="0712 345 678" value={phone}
                                                           onChange={(e) => setPhone(e.target.value)} required />}</Field>
            </div>
            <div style={{ flex: "0 1 160px" }}>
              <Field label="Amount (KSh)" hint={`${min}–${max.toLocaleString()}`}>{(p) => (
                <Input {...p} type="number" min={min} max={max} step={1} value={amount}
                       onChange={(e) => setAmount(Math.round(Number(e.target.value)))} required />)}</Field>
            </div>
          </Stack>
          <Stack direction="row" gap="var(--s2)" wrap>
            {[50, 100, 200, 500].filter((v) => v >= min && v <= max).map((v) => (
              <Button key={v} type="button" size="sm" variant={amount === v ? "primary" : "ghost"} onClick={() => setAmount(v)}>KSh {v}</Button>
            ))}
          </Stack>
          <div>
            <Button type="submit" variant="primary" loading={topUp.isPending} disabled={Boolean(checkout && !done)}>
              Pay KSh {amount || 0} with M-Pesa
            </Button>
          </div>
          {checkout && (
            <p role="status" style={{ margin: 0, fontSize: "var(--text-sm)" }}>
              {!s || s.status === "pending" ? "⏳ Waiting for your PIN… (this page updates by itself)"
                : s.status === "paid" ? `✅ Paid${s.receipt ? ` (${s.receipt})` : ""}. Your balance is KSh ${s.balance_ksh}.`
                : s.status === "cancelled" ? "You cancelled the prompt. Nothing was charged."
                : `It did not go through: ${s.message || "try again"}. Nothing was charged.`}
              {done && <> <Button type="button" size="sm" variant="ghost" onClick={() => setCheckout("")}>Another top-up</Button></>}
            </p>
          )}
        </form>
      )}
    </Card>
  );
}


/** The video plan: every video (streamed), and every question's games and walkthroughs. */
function PlanCard({ balance }: { balance: number }) {
  const plan = usePlan();
  const subscribe = useSubscribe();
  const toast = useToast();
  const p = plan.data;
  if (!p || !p.on_sale) return null;
  const until = p.until ? new Date(p.until).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
  async function go() {
    try {
      const out = await subscribe.mutateAsync();
      toast(`Video plan on until ${new Date(out.until).toLocaleDateString()}.`, "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not start the plan.", "danger"); }
  }
  return (
    <Card title={p.active ? `Video plan — on until ${until}` : `Video plan — KSh ${p.price_ksh} for ${p.days} days`}
          description="Every question's whiteboard video, game and animated walkthrough — watched here, not downloaded.">
      <Stack direction="row" gap="var(--s2)" align="center" wrap>
        <Button variant={p.active ? "ghost" : "primary"} loading={subscribe.isPending} disabled={balance < p.price_ksh} onClick={go}>
          {p.active ? `Add ${p.days} more days (KSh ${p.price_ksh})` : `Start it — KSh ${p.price_ksh}`}
        </Button>
        {balance < p.price_ksh && <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>Top up first: the wallet has KSh {balance}.</span>}
      </Stack>
    </Card>
  );
}
