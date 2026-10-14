import React from "react";
import { useAuth } from "../lib/auth";
import { Button, Card, Field, Input } from "../ui/components";
import { fetchJson } from "../api";

export function SignIn() {
  const { signIn, expiredReason } = useAuth();
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [mode, setMode] = React.useState<"signin" | "signup" | "forgot">("signin");
  const [sent, setSent] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [kind, setKind] = React.useState<"user" | "developer">("user");

  // A signup is a USER account (a parent or a teacher: the exam studio and
  // their own papers) or a developer's (the content API and their keys).
  async function signUp(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await fetchJson<any>("/api/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({ username, password, email: email.trim(), role: kind }),
      });
      await signIn(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-up failed.");
    } finally {
      setBusy(false);
    }
  }

  // A forgotten password: a reset link to the account's email address.
  async function forgot(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const out = await fetchJson<{ message: string }>("/api/v1/auth/forgot", {
        method: "POST",
        body: JSON.stringify({ who: username }),
      });
      setSent(out.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the link.");
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await signIn(username, password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "var(--s5)",
        background: "var(--ground)",
      }}
    >
      <div style={{ width: "min(24rem, 100%)", display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--s2)" }}>
          <h1>CBC Factory</h1>
          <p style={{ color: "var(--ink-2)", fontSize: "var(--text-sm)" }}>
            Curriculum-aligned content production for Kenyan basic education.
          </p>
        </div>

        {expiredReason && (
          <div
            role="status"
            style={{
              background: "var(--warn-wash)",
              border: "1px solid var(--warn)",
              borderRadius: "var(--radius)",
              padding: "var(--s3)",
              fontSize: "var(--text-sm)",
              color: "var(--warn)",
            }}
          >
            {expiredReason}
          </div>
        )}

        <Card>
          <form onSubmit={mode === "signup" ? signUp : mode === "forgot" ? forgot : submit} style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
            <div role="tablist" style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--line)" }}>
              {(["signin", "signup"] as const).map((m) => (
                <button key={m} type="button" role="tab" aria-selected={mode === m || (m === "signin" && mode === "forgot")} onClick={() => { setMode(m); setError(null); setSent(""); }}
                        style={{ background: "transparent", border: "none", padding: "6px 10px", cursor: "pointer", color: "var(--ink)",
                                 borderBottom: `2px solid ${mode === m || (m === "signin" && mode === "forgot") ? "var(--accent)" : "transparent"}`, fontWeight: mode === m ? 650 : 500 }}>
                  {m === "signin" ? "Sign in" : "Create an account"}
                </button>
              ))}
            </div>
            {mode === "signup" && (
              <fieldset style={{ border: 0, padding: 0, margin: 0, display: "grid", gap: 6 }}>
                <legend style={{ fontSize: "var(--text-sm)", fontWeight: 550, color: "var(--ink-2)", marginBottom: 4 }}>I am</legend>
                {([["user", "A parent or a teacher", "Build exam papers with marking schemes and print them."],
                   ["developer", "A developer", "Use the questions in my own app through the API."]] as const).map(([value, title, sub]) => (
                  <label key={value} style={{ display: "flex", gap: 8, alignItems: "flex-start", padding: "8px 10px", cursor: "pointer",
                                              border: `1px solid ${kind === value ? "var(--accent)" : "var(--line)"}`, borderRadius: "var(--radius)" }}>
                    <input type="radio" name="kind" value={value} checked={kind === value} onChange={() => setKind(value)} style={{ marginTop: 3 }} />
                    <span><strong style={{ fontSize: "var(--text-sm)" }}>{title}</strong><br />
                      <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{sub}</span></span>
                  </label>
                ))}
              </fieldset>
            )}
            {mode === "signup" && (
              <Field label="Email" hint="We send a link to confirm it — and to reset your password if you forget it.">
                {(props) => <Input {...props} type="email" value={email} autoComplete="email" onChange={(e) => setEmail(e.target.value)} required />}
              </Field>
            )}
            {mode === "forgot" && (
              <p style={{ margin: 0, fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                Enter your username or email address. We email you a link to choose a new password.
              </p>
            )}
            <Field label={mode === "forgot" ? "Username or email" : "Username"} error={mode === "forgot" ? error ?? undefined : undefined}>
              {(props) => (
                <Input
                  {...props}
                  value={username}
                  autoComplete={mode === "forgot" ? "email" : "username"}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              )}
            </Field>

            {mode !== "forgot" && <Field label="Password" error={error ?? undefined}>
              {(props) => (
                <Input
                  {...props}
                  type="password"
                  value={password}
                  autoComplete="current-password"
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              )}
            </Field>}
            {mode === "signin" && (
              <button type="button" onClick={() => { setMode("forgot"); setError(null); setSent(""); }}
                      style={{ background: "none", border: 0, padding: 0, color: "var(--accent)", cursor: "pointer",
                               fontSize: "var(--text-sm)", justifySelf: "start", textAlign: "left" }}>
                Forgot password?
              </button>
            )}
            {mode === "forgot" && sent && (
              <div role="status" style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", background: "var(--accent-wash, transparent)",
                                          border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "var(--s3)" }}>
                {sent}
              </div>
            )}

            <Button type="submit" variant="primary" loading={busy} style={{ justifyContent: "center" }}>
              {mode === "signup" ? (kind === "developer" ? "Create my developer account" : "Create account and open the studio")
                : mode === "forgot" ? (sent ? "Send it again" : "Email me a reset link") : "Sign in"}
            </Button>
            {mode === "forgot" && (
              <button type="button" onClick={() => { setMode("signin"); setError(null); setSent(""); }}
                      style={{ background: "none", border: 0, padding: 0, color: "var(--accent)", cursor: "pointer", fontSize: "var(--text-sm)" }}>
                Back to sign in
              </button>
            )}
            {mode === "signup" && (
              <p style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)", margin: 0 }}>
                {kind === "developer"
                  ? "100 free API calls a day (1,000 a month), then KSh 1.50 a question (KSh 2.50 with a figure), paid with M-Pesa."
                  : "Build exam papers from the question bank — topical, mid-term, end of term, with figures, marking schemes and answer sheets. Your first 10 questions are free."}
              </p>
            )}
          </form>
        </Card>

      </div>
    </div>
  );
}
