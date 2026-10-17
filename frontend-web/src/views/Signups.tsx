import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Badge, Card, ErrorNotice, LoadingBlock, PageHeader, Select, Stack } from "../ui/components";
import { useApi } from "../lib/queries";

type Account = { username: string; role: string; email: string; email_verified: boolean; is_active: boolean;
  created_at: string | null; balance_cents: number; paid_ksh: number; payments: number; last_paid_at: string | null; spent_cents: number };
type Totals = { signups: number; revenue_ksh: number; payers: number };
type Data = { accounts: Account[]; mpesa_ready: boolean; mpesa_note: string;
  totals: { today: Totals; week: Totals; period: Totals }; all: { accounts: number; paying: number; revenue_ksh: number } };

const ksh = (n: number) => `KSh ${Math.round(n).toLocaleString()}`;
const when = (s: string | null) => (s ? new Date(s).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "—");

/** Admin: who signed up, when, and who pays. */
export function Signups() {
  const api = useApi();
  const [days, setDays] = React.useState(30);
  const [filter, setFilter] = React.useState<"all" | "paying" | "not" | "user" | "api">("all");
  const q = useQuery({ queryKey: ["admin-accounts", days], queryFn: () => api<Data>(`/api/v1/billing/admin/accounts?days=${days}`), refetchInterval: 60_000 });
  const d = q.data;
  const rows = (d?.accounts || []).filter((a) =>
    filter === "all" || (filter === "paying" ? a.payments > 0 : filter === "not" ? a.payments === 0 : a.role === filter));
  const stat = (label: string, t: Totals) => (
    <Card>
      <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{label}</div>
      <div style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>{t.signups} signups</div>
      <div style={{ fontSize: "var(--text-sm)" }}>{ksh(t.revenue_ksh)} from {t.payers} paying</div>
    </Card>
  );
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader eyebrow="Admin" title="Accounts & payments" description="Every parent, teacher and developer who signed up, and who pays — M-Pesa top-ups as they land." />
      {q.error && <ErrorNotice error={q.error} />}
      {!d ? <LoadingBlock rows={4} label="Loading accounts" /> : (
        <>
          {!d.mpesa_ready && <Card><span style={{ color: "var(--warn)" }}>⚠️ {d.mpesa_note} Nobody can top up until it is.</span></Card>}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "var(--s3)" }}>
            {stat("Today", d.totals.today)}{stat("Last 7 days", d.totals.week)}{stat(`Last ${days} days`, d.totals.period)}
            <Card>
              <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>All time</div>
              <div style={{ fontSize: "var(--text-xl)", fontWeight: 700 }}>{d.all.accounts} accounts</div>
              <div style={{ fontSize: "var(--text-sm)" }}>{d.all.paying} paying · {ksh(d.all.revenue_ksh)}</div>
            </Card>
          </div>
          <Card>
            <Stack direction="row" gap="var(--s2)" wrap align="center" style={{ marginBottom: "var(--s2)" }}>
              <Select value={filter} onChange={(e) => setFilter(e.target.value as any)} style={{ width: "auto" }}>
                <option value="all">Everyone</option><option value="paying">Paying</option><option value="not">Not paid yet</option>
                <option value="user">Parents & teachers</option><option value="api">Developers</option>
              </Select>
              <Select value={String(days)} onChange={(e) => setDays(Number(e.target.value))} style={{ width: "auto" }}>
                {[7, 30, 90, 365].map((n) => <option key={n} value={n}>Totals over {n} days</option>)}
              </Select>
              <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{rows.length} shown · accounts made before signup dates were kept show their last change</span>
            </Stack>
            <div style={{ overflowX: "auto" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "var(--text-sm)" }}>
                <thead><tr style={{ textAlign: "left", color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
                  <th>Account</th><th>Kind</th><th>Email</th><th>Joined</th><th>Paid</th><th>Last paid</th><th>Wallet</th><th>Spent</th></tr></thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.username} style={{ borderTop: "1px solid var(--line-2)", opacity: a.is_active ? 1 : 0.5 }}>
                      <td style={{ padding: "5px 4px", fontWeight: 600 }}>{a.username}</td>
                      <td><Badge tone={a.role === "api" ? "info" : "neutral"}>{a.role === "api" ? "developer" : "parent/teacher"}</Badge></td>
                      <td>{a.email || "—"} {a.email && (a.email_verified ? <span title="Confirmed">✅</span> : <span title="Not confirmed">⏳</span>)}</td>
                      <td>{when(a.created_at)}</td>
                      <td>{a.payments ? <strong>{ksh(a.paid_ksh)}</strong> : <span style={{ color: "var(--ink-3)" }}>not yet</span>}{a.payments > 1 ? ` (${a.payments}×)` : ""}</td>
                      <td>{when(a.last_paid_at)}</td>
                      <td>{ksh(a.balance_cents / 100)}</td>
                      <td>{ksh(a.spent_cents / 100)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
