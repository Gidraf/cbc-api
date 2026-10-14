import React from "react";
import { Button, Card, Field, Input, PageHeader, useToast } from "../ui/components";
import { useApi } from "../lib/queries";
import { useAuth } from "../lib/auth";

/** Your account: set your own password. */
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
      <PageHeader eyebrow="Account" title="Change password" description={`Signed in as ${username}.`} />
      <Card>
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
