import React from "react";
import { Badge, Button, Card, ErrorNotice, Field, Input, Stack, useToast } from "../ui/components";
import { usePlatformSettings, useSavePlatformSettings, useTestWebhook, type PlatformSetting } from "../lib/queries";

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
                    <Input {...p} type={row.kind === "secret" ? "password" : row.kind === "int" ? "number" : "text"}
                           value={shown(row)}
                           placeholder={row.kind === "secret" && row.value ? "(set — type to replace)" : String(row.default ?? "")}
                           onChange={(e) => setDraft({ ...draft, [row.key]: e.target.value })}
                           style={{ minWidth: "22rem" }} />
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
