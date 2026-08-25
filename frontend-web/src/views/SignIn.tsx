import React from "react";
import { useAuth } from "../lib/auth";
import { Button, Card, Field, Input } from "../ui/components";

export function SignIn() {
  const { signIn, expiredReason } = useAuth();
  const [username, setUsername] = React.useState("admin");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

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
          <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: "var(--s4)" }}>
            <Field label="Username">
              {(props) => (
                <Input
                  {...props}
                  value={username}
                  autoComplete="username"
                  onChange={(e) => setUsername(e.target.value)}
                  required
                />
              )}
            </Field>

            <Field label="Password" error={error ?? undefined}>
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
            </Field>

            <Button type="submit" variant="primary" loading={busy} style={{ justifyContent: "center" }}>
              Sign in
            </Button>
          </form>
        </Card>

        <p style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
          Lost the admin password? Reset it from the server with{" "}
          <code>cbc-cli reset-admin-password</code>.
        </p>
      </div>
    </div>
  );
}
