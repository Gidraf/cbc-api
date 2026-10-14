import React from "react";
import { Badge, Button, Card, ErrorNotice, Field, Input, LoadingBlock, PageHeader, Stack, Stat, Table, useToast } from "../ui/components";
import { useCreatePortalKey, usePortalKeys, useRevokePortalKey, useWallet } from "../lib/queries";
import { TopUp } from "./Wallet";

const DOCS = "/api/v1/content/docs";

/** A developer's home: keys, today's free calls, the wallet, the docs. */
export function Developer() {
  const wallet = useWallet();
  const keys = usePortalKeys();
  const create = useCreatePortalKey();
  const revoke = useRevokePortalKey();
  const toast = useToast();
  const [label, setLabel] = React.useState("My app");
  const [fresh, setFresh] = React.useState<string>("");
  const w = wallet.data;

  async function make(e: React.FormEvent) {
    e.preventDefault();
    try {
      const out = await create.mutateAsync({ label: label || "My app", role: "" });
      setFresh(out.api_key);
    } catch (err) { toast(err instanceof Error ? err.message : "Could not make the key.", "danger"); }
  }
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); toast("Copied.", "ok"); } catch { toast("Select it and copy.", "info"); }
  }

  if (wallet.error) return <ErrorNotice error={wallet.error} />;
  if (!w) return <LoadingBlock rows={4} label="Loading" />;
  const sample = `import os
import requests

r = requests.get("${window.location.origin}/api/v1/content/questions",
                 headers={"X-API-Key": os.environ["CBC_API_KEY"]},
                 params={"grade": "Grade 9", "subject": "Mathematics", "limit": 5},
                 timeout=30)
r.raise_for_status()
for q in r.json()["items"]:
    print(q["question"], "→", q["answer"])`;
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader title="Developer" eyebrow="Content API"
                  description="CBC questions with answers, marking schemes and figures, for your own app."
                  actions={<a href={DOCS} target="_blank" rel="noreferrer"><Button variant="primary">Read the docs ↗</Button></a>} />
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: "var(--s3)" }}>
        <Stat label="Free calls left today" value={w.api.free_left_today}
              sub={`${w.prices.api.free_calls_per_day} a day, ${w.prices.api.free_calls_per_month.toLocaleString()} a month`} />
        <Stat label="Calls this month" value={w.api.calls_this_month.toLocaleString()} />
        <Stat label="Spent this month" value={`KSh ${w.api.charged_this_month_ksh}`} />
        <Stat label="Wallet" value={`KSh ${w.balance_ksh}`} tone={w.balance_ksh > 0 ? "ok" : undefined}
              sub={`then KSh ${w.prices.api.text_ksh} a text question, KSh ${w.prices.api.diagram_ksh} with a figure`} />
      </div>

      <Card title="API keys" description="Send one in the X-API-Key header. A key is shown once: keep it on your server, never in an app or a web page.">
        <form onSubmit={make} style={{ display: "flex", gap: "var(--s2)", alignItems: "flex-end", flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 240px", maxWidth: 360 }}>
            <Field label="Name it after the app that uses it">{(p) => <Input {...p} value={label} onChange={(e) => setLabel(e.target.value)} />}</Field>
          </div>
          <Button type="submit" loading={create.isPending}>Make a key</Button>
        </form>
        {fresh && (
          <div style={{ marginTop: "var(--s3)", padding: "var(--s3)", border: "1px solid var(--accent)", borderRadius: "var(--radius)", display: "grid", gap: "var(--s2)" }}>
            <strong>Your new key — copy it now; it is not shown again.</strong>
            <code style={{ wordBreak: "break-all", fontSize: "var(--text-sm)" }}>{fresh}</code>
            <Stack direction="row" gap="var(--s2)"><Button size="sm" onClick={() => copy(fresh)}>Copy</Button>
              <Button size="sm" variant="ghost" onClick={() => setFresh("")}>I have saved it</Button></Stack>
          </div>
        )}
        {keys.data?.api_keys?.length ? (
          <div style={{ marginTop: "var(--s3)" }}>
            <Table caption="Your API keys">
              <thead><tr><th style={{ textAlign: "left" }}>Name</th><th style={{ textAlign: "left" }}>Made</th>
                <th style={{ textAlign: "left" }}>Last used</th><th /></tr></thead>
              <tbody>
                {keys.data.api_keys.map((k) => (
                  <tr key={k.key_id} style={{ borderTop: "1px solid var(--line)" }}>
                    <td style={{ padding: "6px 8px" }}>{k.label} {!k.is_active && <Badge tone="neutral">off</Badge>}</td>
                    <td style={{ padding: "6px 8px" }}>{new Date(k.created_at).toLocaleDateString()}</td>
                    <td style={{ padding: "6px 8px" }}>{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
                    <td style={{ padding: "6px 8px", textAlign: "right" }}>
                      <Button size="sm" variant="ghost" onClick={async () => {
                        if (!window.confirm(`Revoke "${k.label}"? Apps using it stop working at once.`)) return;
                        await revoke.mutateAsync(k.key_id);
                      }}>Revoke</Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        ) : null}
      </Card>

      <Card title="Your first call" description="Python with requests. The docs have JavaScript, curl, every filter, the errors and the prices.">
        <pre style={{ margin: 0, padding: "var(--s3)", background: "var(--surface-2, #f4f4f2)", borderRadius: "var(--radius)",
                      overflowX: "auto", fontSize: "var(--text-xs)" }}><code>{sample}</code></pre>
        <div style={{ marginTop: "var(--s2)" }}><Button size="sm" variant="ghost" onClick={() => copy(sample)}>Copy</Button></div>
      </Card>

      <TopUp min={w.prices.topup.min_ksh} max={w.prices.topup.max_ksh} ready={w.topups_ready} note={w.topups_note} />
    </div>
  );
}
