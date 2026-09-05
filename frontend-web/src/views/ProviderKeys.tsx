import React from "react";
import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  Field,
  Input,
  QueryState,
  Stack,
} from "../ui/components";
import { useProviders, useSaveProviderKey, type ProviderConfig } from "../lib/queries";

/**
 * Where the API keys live.
 *
 * They were environment variables, so changing one — a rotated key, a new
 * provider, a key that had run out of credit — meant editing `.env`, rebuilding
 * the image and restarting the service. The store behind this screen has always
 * been there: keys are encrypted and written to `provider_configs`, and read
 * back on the next call. Only the screen was missing.
 *
 * A saved key is never sent back to the browser. There is nothing to show but
 * whether one is set, so that is all this shows.
 */

const WHAT_FOR: Record<string, string> = {
  anthropic: "Notes, lesson material, questions, and SVG diagrams.",
  openai: "Generation, and the narration audio for maths walkthroughs.",
  gemini: "Generation, and image assets.",
  ollama: "A model running on your own machine. No key — just the address.",
};

const GET_A_KEY: Record<string, string> = {
  anthropic: "console.anthropic.com",
  openai: "platform.openai.com",
  gemini: "aistudio.google.com",
};

function ProviderRow({ config }: { config: ProviderConfig }) {
  const save = useSaveProviderKey();
  const isLocal = config.provider === "ollama";

  const [key, setKey] = React.useState("");
  const [baseUrl, setBaseUrl] = React.useState(config.base_url || "");
  const [saved, setSaved] = React.useState(false);

  const dirty = key.trim().length > 0 || baseUrl.trim() !== (config.base_url || "");

  function submit(event: React.FormEvent) {
    event.preventDefault();
    save.mutate(
      {
        provider: config.provider,
        api_key: key.trim() || undefined,
        base_url: baseUrl.trim() || undefined,
      },
      {
        onSuccess: () => {
          setKey("");
          setSaved(true);
          window.setTimeout(() => setSaved(false), 2600);
        },
      }
    );
  }

  return (
    <form
      onSubmit={submit}
      style={{
        border: "1px solid var(--line)",
        borderRadius: "var(--radius-sm)",
        padding: "var(--s3)",
        background: "var(--surface)",
      }}
    >
      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ textTransform: "capitalize" }}>{config.provider}</strong>
        {isLocal ? (
          <Badge tone="neutral">local</Badge>
        ) : config.has_api_key ? (
          <Badge tone="ok">key saved</Badge>
        ) : (
          <Badge tone="warn">no key</Badge>
        )}
        {saved && <Badge tone="ok">saved</Badge>}
      </Stack>

      <p style={{ margin: "var(--s1) 0 var(--s3)", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
        {WHAT_FOR[config.provider] || "Used by the stations bound to it."}
        {!isLocal && GET_A_KEY[config.provider] && (
          <> Keys come from <span className="mono">{GET_A_KEY[config.provider]}</span>.</>
        )}
      </p>

      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "flex-end", flexWrap: "wrap" }}>
        {!isLocal && (
          <Field
            label={config.has_api_key ? "Replace the key" : "API key"}
            hint={config.has_api_key ? "Leave blank to keep the one already saved." : undefined}
          >
            {(a11y) => (
              <Input
                {...a11y}
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={key}
                placeholder={config.has_api_key ? "•••••••• already saved" : "paste the key"}
                onChange={(e) => setKey(e.target.value)}
                style={{ minWidth: "22rem" }}
              />
            )}
          </Field>
        )}

        <Field label={isLocal ? "Address" : "Base URL"} hint="Blank uses the provider's own.">
          {(a11y) => (
            <Input
              {...a11y}
              value={baseUrl}
              placeholder={isLocal ? "http://localhost:11434" : "default"}
              onChange={(e) => setBaseUrl(e.target.value)}
              style={{ minWidth: "18rem" }}
            />
          )}
        </Field>

        <Button type="submit" disabled={!dirty || save.isPending} loading={save.isPending}>
          {save.isPending ? "Saving…" : "Save"}
        </Button>
      </Stack>

      {save.error && <ErrorNotice error={save.error} />}
    </form>
  );
}

export function ProviderKeys() {
  const providers = useProviders();

  return (
    <Card
      title="API keys"
      description="Saved encrypted and read on the next call, so a key can be added, replaced or rotated without rebuilding anything. A saved key is never sent back to this page — only whether one is set."
    >
      <QueryState query={providers} label="Reading the provider configuration" rows={4} />
      {providers.data && (
        <Stack gap="var(--s3)">
          {providers.data.providers.map((config) => (
            <ProviderRow key={config.provider} config={config} />
          ))}
        </Stack>
      )}
    </Card>
  );
}
