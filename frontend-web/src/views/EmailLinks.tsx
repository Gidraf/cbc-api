import React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Field, Input } from "../ui/components";
import { fetchJson } from "../api";
import { useApi } from "../lib/queries";
import { useAuth } from "../lib/auth";

/** The plain page the emailed links open on: signed in or not. */
function Plain({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ minHeight: "100vh", display: "grid", placeItems: "center", padding: "var(--s5)", background: "var(--ground)" }}>
      <div style={{ width: "min(24rem, 100%)", display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
        <h1>{title}</h1>
        <Card>{children}</Card>
        <p style={{ fontSize: "var(--text-sm)" }}><a href="/">Back to sign in</a></p>
      </div>
    </div>
  );
}

/** /reset?token=… — choose a new password with the emailed link. */
export function ResetPassword() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [next, setNext] = React.useState("");
  const [again, setAgain] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [done, setDone] = React.useState("");
  const valid = useQuery({
    queryKey: ["reset-link", token],
    queryFn: () => fetchJson<{ valid: boolean }>(`/api/v1/auth/reset/${encodeURIComponent(token)}`),
    enabled: !!token,
    retry: false,
  });
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (next !== again) return setError("The passwords do not match.");
    if (next.length < 10) return setError("Use 10 characters or more.");
    setBusy(true);
    try {
      const out = await fetchJson<{ username: string }>("/api/v1/auth/reset", {
        method: "POST", body: JSON.stringify({ token, new_password: next }) });
      setDone(out.username);
    } catch (err) { setError(err instanceof Error ? err.message : "Could not reset it."); }
    finally { setBusy(false); }
  }
  if (done) {
    return (
      <Plain title="Password changed">
        <p style={{ margin: 0 }}>The password for <strong>{done}</strong> is changed, and every device that was signed in is signed out.
          <a href="/"> Sign in</a> with the new one.</p>
      </Plain>
    );
  }
  if (!token || valid.data?.valid === false) {
    return (
      <Plain title="Link expired">
        <p style={{ margin: 0 }}>This reset link has expired or was already used. On the sign-in page, choose
          “Forgot password?” to get a new one.</p>
      </Plain>
    );
  }
  return (
    <Plain title="Choose a new password">
      <form onSubmit={save} style={{ display: "grid", gap: "var(--s3)" }}>
        <Field label="New password" hint="10 characters or more, not your username.">
          {(p) => <Input {...p} type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />}
        </Field>
        <Field label="New password again" error={error || (valid.error instanceof Error ? valid.error.message : undefined)}>
          {(p) => <Input {...p} type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} required />}
        </Field>
        <Button type="submit" variant="primary" loading={busy} disabled={valid.isLoading} style={{ justifyContent: "center" }}>
          Set my new password</Button>
      </form>
    </Plain>
  );
}

/** /verify?token=… — confirm an email address. */
export function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const { token: signedIn } = useAuth();
  const [state, setState] = React.useState<{ ok?: boolean; message?: string }>({});
  const sent = React.useRef(false);
  React.useEffect(() => {
    if (sent.current) return;
    sent.current = true;
    if (!token) return setState({ ok: false, message: "This link is missing its code." });
    fetchJson<{ username: string }>("/api/v1/auth/verify", { method: "POST", body: JSON.stringify({ token }) })
      .then(() => setState({ ok: true }))
      .catch((err) => setState({ ok: false, message: err instanceof Error ? err.message : "Could not confirm it." }));
  }, [token]);
  const home = signedIn ? <Link to="/">Open the studio</Link> : <a href="/">Sign in</a>;
  if (state.ok === undefined) return <Plain title="Confirming…"><p style={{ margin: 0 }}>One moment.</p></Plain>;
  return state.ok
    ? <Plain title="Email confirmed"><p style={{ margin: 0 }}>Thank you — your email address is confirmed. {home}.</p></Plain>
    : <Plain title="Not confirmed"><p style={{ margin: 0 }}>{state.message} {home}.</p></Plain>;
}

type EmailState = { email: string; email_verified: boolean };

/** A line at the top of the console until the account's email is confirmed. */
export function EmailBanner() {
  const api = useApi();
  const { role } = useAuth();
  const [hidden, setHidden] = React.useState(false);
  const [note, setNote] = React.useState("");
  const me = useQuery({ queryKey: ["my-email"], queryFn: () => api<EmailState>("/api/v1/auth/email"), staleTime: 60_000 });
  if (hidden || !me.data || me.data.email_verified || (role !== "user" && role !== "api")) return null;
  async function resend() {
    try {
      const out = await api<{ sent: string }>("/api/v1/auth/email/confirm", { method: "POST" });
      setNote(out.sent === "sent" ? `Sent — check ${me.data!.email} (and spam).` : out.sent === "verified" ? "Already confirmed."
        : "Email could not be sent right now. Try again later.");
    } catch (err) { setNote(err instanceof Error ? err.message : "Could not send it."); }
  }
  return (
    <div role="status" style={{ background: "var(--warn-wash)", border: "1px solid var(--warn)", borderRadius: "var(--radius)",
                                padding: "var(--s3)", fontSize: "var(--text-sm)", display: "flex", gap: "var(--s3)", flexWrap: "wrap", alignItems: "center" }}>
      <span style={{ flex: 1, minWidth: 220 }}>
        {me.data.email
          ? <>Confirm your email address: we sent a link to <strong>{me.data.email}</strong>. It is how you get back in if you forget your password.</>
          : <>Add your email address, so you can reset your password if you forget it.</>}
        {note && <> {note}</>}
      </span>
      {me.data.email ? <Button size="sm" onClick={resend}>Send the link again</Button> : null}
      <Link to="/account">{me.data.email ? "Change email" : "Add email"}</Link>
      <Button size="sm" variant="ghost" onClick={() => setHidden(true)} aria-label="Hide">✕</Button>
    </div>
  );
}
