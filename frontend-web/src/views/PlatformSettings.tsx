import React from "react";
import { Badge, Button, Card, ErrorNotice, Field, Input, Stack, useToast } from "../ui/components";
import { useApi, usePlatformSettings, useSavePlatformSettings, useTestWebhook, type PlatformSetting } from "../lib/queries";
import { useAuth } from "../lib/auth";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

/**
 * The knobs that used to be environment variables, on a page. Each shows
 * where its value comes from — the console, the environment, or the default —
 * because an operator who cannot see that will change the wrong one.
 */
export function PlatformSettings() {
  const toast = useToast();
  const settings = usePlatformSettings();
  const save = useSavePlatformSettings();
  const test = useTestWebhook();
  const [draft, setDraft] = React.useState<Record<string, string>>({});

  const rows = settings.data?.settings || [];
  const groups = Array.from(new Set(rows.map((r) => r.group)));

  function shown(row: PlatformSetting): string {
    if (row.key in draft) return draft[row.key];
    if (row.kind === "secret") return "";
    if (row.kind === "list") return (row.value || []).join(", ");
    return row.value === null || row.value === undefined ? "" : String(row.value);
  }

  async function saveAll() {
    const values: Record<string, any> = {};
    for (const [key, value] of Object.entries(draft)) {
      const row = rows.find((r) => r.key === key);
      if (!row) continue;
      values[key] = row.kind === "list" ? value.split(",").map((s) => s.trim()).filter(Boolean)
        : row.kind === "int" ? (value === "" ? "" : Number(value)) : value;
    }
    try {
      await save.mutateAsync(values);
      setDraft({});
      toast("Settings saved. They take effect within seconds in every process.", "ok");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not save.", "danger");
    }
  }

  return (
    <Stack gap="var(--s4)">
      <DriveCard />
      {settings.error && <ErrorNotice error={settings.error} />}
      {groups.map((group) => (
        <Card key={group} title={group}
              description={group === "Webhooks" ? "A POST to your URL when a job, an order, a frozen paper or an agent task finishes — signed with the secret." : undefined}>
          <Stack gap="var(--s3)">
            {rows.filter((r) => r.group === group).map((row) => (
              <Field key={row.key} label={row.title}
                     hint={`${row.help}${row.env ? ` (env: ${row.env})` : ""}`}>
                {(p) => (
                  <Stack direction="row" gap="var(--s2)" align="center" wrap>
                    {row.kind === "bool" ? (
                      <select {...p} value={(shown(row) || String(row.default ?? "false")).toLowerCase() === "true" ? "true" : "false"}
                              onChange={(e) => setDraft({ ...draft, [row.key]: e.target.value })}
                              style={{ minWidth: "22rem" }}>
                        <option value="false">Off</option>
                        <option value="true">On</option>
                      </select>
                    ) : (
                    <Input {...p} type={row.kind === "secret" ? "password" : row.kind === "int" ? "number" : "text"}
                           value={shown(row)}
                           placeholder={row.kind === "secret" && row.value ? "(set — type to replace)" : String(row.default ?? "")}
                           onChange={(e) => setDraft({ ...draft, [row.key]: e.target.value })}
                           style={{ minWidth: "22rem" }} />
                    )}
                    <Badge tone={row.source === "console" ? "ok" : row.source === "environment" ? "info" : "neutral"}>
                      {row.source}
                    </Badge>
                    {row.key in draft && <Badge tone="warn">unsaved</Badge>}
                  </Stack>
                )}
              </Field>
            ))}
            {group === "Webhooks" && (
              <Stack direction="row" gap="var(--s2)" align="center" wrap>
                <Button variant="secondary" disabled={test.isPending}
                        onClick={() => test.mutateAsync().then((r) => toast(r.ok ? `Delivered (${r.status}).` : `Failed: ${r.status} ${r.error}`, r.ok ? "ok" : "danger")).catch((e) => toast(e.message, "danger"))}>
                  {test.isPending ? "Sending…" : "Send a test event"}
                </Button>
                <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
                  Events: {(settings.data?.webhook_events || []).join(", ")}. Header X-CBC-Signature: sha256=HMAC(secret, body).
                </span>
              </Stack>
            )}
          </Stack>
        </Card>
      ))}
      <Stack direction="row" gap="var(--s2)">
        <Button variant="primary" disabled={Object.keys(draft).length === 0 || save.isPending} onClick={saveAll}>
          {save.isPending ? "Saving…" : "Save settings"}
        </Button>
        <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)", alignSelf: "center" }}>
          Clear a field and save to fall back to the environment or the default.
        </span>
      </Stack>
    </Stack>
  );
}


type DriveStatus = { connected: boolean; source: string; has_client: boolean; client_id_hint: string; connected_at: string;
                     folder_id: string; redirect_uri: string; moved_files: number; moved_gb: number; still_shared: number };

/** Google Drive, connected here by an admin: where finished videos go,
 *  privately — viewers always stream them through the platform. */
function DriveCard() {
  const { role } = useAuth();
  const api = useApi();
  const qc = useQueryClient();
  const toast = useToast();
  const status = useQuery({ queryKey: ["drive"], queryFn: () => api<DriveStatus>("/api/v1/admin/drive"), enabled: role === "admin" });
  const [clientId, setClientId] = React.useState("");
  const [secret, setSecret] = React.useState("");
  const [folder, setFolder] = React.useState("");
  const act = useMutation({
    mutationFn: (v: { path: string; method: string; body?: any }) =>
      api<any>(v.path, { method: v.method, body: v.body ? JSON.stringify(v.body) : undefined }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["drive"] }),
  });
  React.useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("drive");
    if (!q) return;
    const said: Record<string, [string, "ok" | "danger"]> = {
      connected: ["Google Drive is connected. Videos move there every half hour, privately.", "ok"],
      refused: ["Google Drive was not connected: access was refused.", "danger"],
      expired: ["That sign-in took too long. Press Connect again.", "danger"],
      failed: ["Google did not give a sign-in. Check the client ID, secret and redirect URI, then press Connect again.", "danger"],
    };
    const [msg, tone] = said[q] || ["", "ok"];
    if (msg) toast(msg, tone);
    window.history.replaceState(null, "", window.location.pathname);
  }, [toast]);
  if (role !== "admin") return null;
  const d = status.data;
  async function run(path: string, method = "POST", body?: any, done?: string) {
    try { const out = await act.mutateAsync({ path, method, body }); if (done) toast(done, "ok"); return out; }
    catch (err) { toast(err instanceof Error ? err.message : "That did not work.", "danger"); return null; }
  }
  async function connect() {
    const out = await run("/api/v1/admin/drive/connect", "GET");
    if (out?.auth_url) window.location.href = out.auth_url;
  }
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); toast("Copied.", "ok"); } catch { toast("Select it and copy.", "info"); }
  }
  return (
    <Card title="Google Drive" description="Finished videos move to your Drive and the server's copies are freed. The files are private: nobody can open them from Drive — viewers stream them through the platform, which checks who may watch.">
      {status.error ? <ErrorNotice error={status.error} /> : !d ? null : (
        <Stack gap="var(--s3)">
          <Stack direction="row" gap="var(--s2)" align="center" wrap>
            <Badge tone={d.connected ? "ok" : "neutral"}>{d.connected ? "Connected" : "Not connected"}</Badge>
            {d.connected && d.source === "environment" && <Badge tone="neutral">from .env</Badge>}
            {d.connected_at && <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>since {new Date(d.connected_at).toLocaleString()}</span>}
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>{d.moved_files} file(s) moved · {d.moved_gb} GB</span>
            {d.still_shared > 0 && <Badge tone="warn">{d.still_shared} still shared by link</Badge>}
          </Stack>
          <ol style={{ margin: 0, paddingLeft: 18, fontSize: "var(--text-sm)", display: "grid", gap: 6 }}>
            <li>In Google Cloud Console → APIs & Services: enable the <b>Google Drive API</b>, then Credentials → Create credentials →
              OAuth client ID → <b>Web application</b>. Under “Authorised redirect URIs” add exactly:
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 4 }}>
                <code style={{ wordBreak: "break-all", fontSize: "var(--text-xs)" }}>{d.redirect_uri}</code>
                <Button size="sm" variant="ghost" onClick={() => copy(d.redirect_uri)}>Copy</Button>
              </div>
            </li>
            <li>Paste the client ID and secret here{d.has_client ? ` (saved: ${d.client_id_hint})` : ""}:
              <Stack direction="row" gap="var(--s2)" wrap style={{ marginTop: 4 }}>
                <Input placeholder="Client ID (…apps.googleusercontent.com)" value={clientId} onChange={(e) => setClientId(e.target.value)} style={{ minWidth: 280, flex: "1 1 280px" }} />
                <Input placeholder="Client secret" type="password" value={secret} onChange={(e) => setSecret(e.target.value)} style={{ minWidth: 180 }} />
                <Input placeholder="Folder ID (optional)" value={folder} onChange={(e) => setFolder(e.target.value)} style={{ minWidth: 160 }} />
                <Button disabled={!clientId || !secret} onClick={async () => {
                  if (await run("/api/v1/admin/drive/client", "PUT", { client_id: clientId, client_secret: secret, folder_id: folder }, "Saved.")) { setSecret(""); }
                }}>Save</Button>
              </Stack>
            </li>
            <li>Press Connect and allow access (only to the files the platform makes):
              <div style={{ marginTop: 4 }}><Button variant="primary" disabled={!d.has_client} onClick={connect}>{d.connected ? "Connect again" : "Connect Google Drive"}</Button></div>
            </li>
          </ol>
          {d.connected && (
            <Stack direction="row" gap="var(--s2)" wrap>
              <Button size="sm" onClick={() => run("/api/v1/admin/drive/move-now", "POST", undefined, "Moving now — see the Queue.")}>Move videos now</Button>
              {d.still_shared > 0 && <Button size="sm" onClick={() => run("/api/v1/admin/drive/privatize", "POST", undefined, "Done: those files are private now.")}>Make older files private</Button>}
              {d.source === "console" && <Button size="sm" variant="ghost" onClick={() => { if (window.confirm("Disconnect Google Drive? Files stay in Drive; nothing more moves, and moved videos cannot be streamed until you connect again.")) run("/api/v1/admin/drive/disconnect", "POST", undefined, "Disconnected."); }}>Disconnect</Button>}
            </Stack>
          )}
        </Stack>
      )}
    </Card>
  );
}
