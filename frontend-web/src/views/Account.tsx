import React from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, Field, Input, PageHeader, Stack, useToast } from "../ui/components";
import { useApi } from "../lib/queries";
import { useAuth } from "../lib/auth";

/** Your account: your email address (confirmed by a link), and your own password. */
export function Account() {
  const api = useApi();
  const toast = useToast();
  const { username } = useAuth();
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [again, setAgain] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (next !== again) return setError("The new passwords do not match.");
    if (next.length < 10) return setError("Use 10 characters or more.");
    setBusy(true);
    try {
      await api("/api/v1/auth/password", { method: "POST", body: JSON.stringify({ current_password: current, new_password: next }) });
      setCurrent(""); setNext(""); setAgain("");
      toast("Password changed. Your other signed-in devices are signed out.", "ok");
    } catch (err) { setError(err instanceof Error ? err.message : "Could not change it."); }
    finally { setBusy(false); }
  }
  return (
    <div style={{ display: "grid", gap: "var(--s4)", maxWidth: 520 }}>
      <PageHeader eyebrow="Account" title="Email & password" description={`Signed in as ${username}.`} />
      <EmailCard />
      <Card>
        <h3 style={{ margin: "0 0 var(--s3)" }}>Change password</h3>
        <form onSubmit={save} style={{ display: "grid", gap: "var(--s3)" }}>
          <Field label="Current password" hint="If an admin reset it, the one you were shown.">
            {(p) => <Input {...p} type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />}
          </Field>
          <Field label="New password" hint="10 characters or more, not your username.">
            {(p) => <Input {...p} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />}
          </Field>
          <Field label="New password again" error={error || undefined}>
            {(p) => <Input {...p} type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />}
          </Field>
          <div><Button type="submit" variant="primary" loading={busy}>Change password</Button></div>
        </form>
      </Card>
    </div>
  );
}

type Mail = { configured: boolean; host: string; port: number; sender: string; security: string; public_address: string };
type EmailState = { email: string; email_verified: boolean; mail?: Mail };

/** The address a reset link goes to — confirmed by a link sent to it. */
function EmailCard() {
  const api = useApi();
  const qc = useQueryClient();
  const toast = useToast();
  const me = useQuery({ queryKey: ["my-email"], queryFn: () => api<EmailState>("/api/v1/auth/email") });
  const [email, setEmail] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  React.useEffect(() => { if (me.data) setEmail(me.data.email); }, [me.data?.email]);
  const said = (sent: string, to: string) =>
    sent === "sent" ? `A confirmation link is on its way to ${to}.` : sent === "verified" ? "Already confirmed."
      : sent === "not set up" ? "Saved, but email is not set up on the server yet — no link was sent." : "Saved, but the email could not be sent. Try again later.";
  async function run(what: string, fn: () => Promise<{ sent?: string; sent_to?: string }>) {
    setError(""); setBusy(what);
    try {
      const out = await fn();
      toast(out.sent_to ? `Test email sent to ${out.sent_to}.` : said(out.sent || "", email), out.sent === "sent" || out.sent_to ? "ok" : "info");
      qc.invalidateQueries({ queryKey: ["my-email"] });
    } catch (err) { setError(err instanceof Error ? err.message : "Something went wrong."); }
    finally { setBusy(""); }
  }
  const d = me.data;
  const changed = !!d && email.trim().toLowerCase() !== d.email;
  return (
    <Card>
      <form onSubmit={(e) => { e.preventDefault(); run("save", () => api("/api/v1/auth/email", { method: "PUT", body: JSON.stringify({ email }) })); }}
            style={{ display: "grid", gap: "var(--s3)" }}>
        <Stack direction="row" gap="var(--s2)" align="center">
          <h3 style={{ margin: 0, flex: 1 }}>Email address</h3>
          {d && d.email && (d.email_verified ? <Badge tone="ok">Confirmed</Badge> : <Badge tone="warn">Not confirmed</Badge>)}
        </Stack>
        <Field label="Email" hint="Where a reset link goes if you forget your password." error={error || undefined}>
          {(p) => <Input {...p} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />}
        </Field>
        <Stack direction="row" gap="var(--s2)" wrap>
          <Button type="submit" variant="primary" loading={busy === "save"} disabled={!changed}>Save and send a confirmation link</Button>
          {d && d.email && !d.email_verified && !changed && (
            <Button type="button" loading={busy === "resend"} onClick={() => run("resend", () => api("/api/v1/auth/email/confirm", { method: "POST" }))}>
              Send the link again</Button>)}
        </Stack>
        {d?.mail && (
          <div style={{ borderTop: "1px solid var(--line)", paddingTop: "var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-2)", display: "grid", gap: 6 }}>
            <strong>Platform email (admins only)</strong>
            <span>{d.mail.configured ? `Sending from ${d.mail.sender} through ${d.mail.host}:${d.mail.port} (${d.mail.security}).`
              : "Not set up: add SMTP_HOST, SMTP_USER and SMTP_PASSWORD (or CVPAP's MAIL_SERVER, ADMIN_EMAIL, ADMIN_EMAIL_PASSWORD) to the server's .env and restart the api."}</span>
            <span>{d.mail.public_address ? `Links point to ${d.mail.public_address}.` : "Links need the Public address: set it in Settings."}</span>
            <div><Button type="button" size="sm" loading={busy === "test"} disabled={!d.mail.configured || !d.email}
                         onClick={() => run("test", () => api("/api/v1/auth/email/test", { method: "POST" }))}>Send me a test email</Button></div>
          </div>
        )}
      </form>
    </Card>
  );
}
