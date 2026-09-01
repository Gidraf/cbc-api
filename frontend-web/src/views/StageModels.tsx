import React from "react";

import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  Input,
  QueryState,
  Select,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import {
  useProviderModels,
  useSetStageBinding,
  useSetStageRoles,
  useStageBindings,
} from "../lib/queries";

/**
 * Which model runs which station.
 *
 * Six stages used to do the work of fourteen — `notes_generation` resolved the
 * notes AND the strand generator, the sub-strand generator, the design ingest,
 * the grade-scope derivation and the profile writer. Moving the notes to a
 * stronger model moved six other things with them, including two that read a
 * 296-page document and are billed by the page.
 *
 * Each station now has its own row. The notes are worth a strong model;
 * extracting a strand list from a table that is already correct is not.
 */
/**
 * Generate on your own machine; review on a vendor's.
 *
 * The bill here is generation — many long calls producing text nobody has read
 * yet — and review is a fraction of it. But review is also the one place a
 * weaker model is worth nothing: a reviewer that cannot see what the generator
 * missed agrees with it, and you have paid for a second opinion that is the
 * first one repeated. So the split is by what the work IS, not by what it
 * costs, and the review stays hosted in both presets.
 */
function LocalSplit() {
  const roles = useSetStageRoles();
  const [preset, setPreset] = React.useState("all");
  const [model, setModel] = React.useState("qwen3:14b");
  const [url, setUrl] = React.useState("http://host.docker.internal:11434");
  const catalogue = useProviderModels("ollama", url);
  const installed = catalogue.data?.models || [];

  return (
    <Card
      title="Run the bulk of it on your own machine"
      description="Bind every station at once by what its work actually is, instead of setting fourteen rows by hand."
    >
      <Stack gap="var(--s3)">
        <Stack direction="row" gap="var(--s3)" wrap style={{ alignItems: "flex-end" }}>
          <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            <div>How much goes local</div>
            <Select
              value={preset}
              aria-label="Split"
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setPreset(e.target.value)}
              style={{ minWidth: "22rem" }}
            >
              <option value="all">
                All generating stations — only the review stays hosted
              </option>
              <option value="most">
                Most — all but reading the design and the lesson plan
              </option>
              <option value="careful">
                Careful — material, photo briefs, activities, profiles
              </option>
            </Select>
          </label>
          <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            <div>Local model</div>
            {/* Asked of the server at that URL. Ollama names carry a tag —
                `llama3.1:8b`, not `llama3.1` — and a bare family name resolves
                only if `:latest` was pulled, which is how a station ends up
                bound to a model the machine does not have. */}
            <Select
              aria-label="Local model"
              value={model}
              onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setModel(e.target.value)}
              style={{ minWidth: "13rem" }}
            >
              {!installed.includes(model) && model && (
                <option value={model}>{model} (not installed there)</option>
              )}
              {installed.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </Select>
          </label>
          <label style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
            <div>Where Ollama is</div>
            <Input
              className="mono"
              aria-label="Ollama base URL"
              value={url}
              onChange={(e: React.ChangeEvent<HTMLInputElement>) => setUrl(e.target.value)}
              style={{ minWidth: "15rem" }}
            />
          </label>
          <Button
            disabled={!model.trim() || roles.isPending}
            loading={roles.isPending}
            onClick={() =>
              roles.mutateAsync({ preset, local_model: model, local_base_url: url })
            }
          >
            Apply
          </Button>
        </Stack>

        <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
          <strong>All</strong> puts every generating station on your own machine —
          the largest saving, and the largest risk: the lesson plan goes local
          too, and every other station is grounded in it, so a weak plan is felt
          everywhere downstream. <strong>Most</strong> keeps the plan and the
          design reading hosted. <strong>Careful</strong> moves only the short,
          repeated work that the plan has already told what to write.
          <br />
          <br />
          The review is hosted in all three and cannot be moved. A reviewer
          weaker than the generator agrees with it, which is worse than no
          review — it passes.
          <br />
          <br />
          Two things that will bite: the API runs in a container, so{" "}
          <code>localhost</code> is the container — use{" "}
          <code>host.docker.internal</code> or the host's IP. And Ollama defaults
          to a 4,096-token context whatever the model advertises, which silently
          truncates these prompts; serve it with{" "}
          <code>OLLAMA_CONTEXT_LENGTH=32768</code>.
        </div>

        {catalogue.data && (
          <div style={{ fontSize: "var(--text-sm)", color: catalogue.data.models.length ? "var(--ink-3)" : "var(--warn)" }}>
            {catalogue.data.note}
          </div>
        )}
        {roles.error && <ErrorNotice error={roles.error} />}
        {roles.data && <Badge tone="ok">{roles.data.note}</Badge>}
      </Stack>
    </Card>
  );
}

export function StageModels() {
  const bindings = useStageBindings();
  const save = useSetStageBinding();
  const [draft, setDraft] = React.useState<
    Record<string, { provider: string; model: string; base_url: string }>
  >({});

  // Providers this system reaches at a URL of yours rather than a vendor's.
  // Ollama on your own machine is free to run, which makes it the right place
  // to put the long, cheap, high-volume work.
  const SELF_HOSTED = new Set(["ollama"]);

  const rows = bindings.data?.stages || [];
  const providers = bindings.data?.providers || [];

  type Field = "provider" | "model" | "base_url";

  // One lookup per distinct Ollama URL on the screen, not one per row: every
  // station usually points at the same server.
  const ollamaUrl =
    rows.find((r) => r.provider === "ollama" && (draft[r.name]?.base_url ?? r.base_url))
      ? (draft[Object.keys(draft).find((k) => draft[k]?.base_url) || ""]?.base_url ??
         rows.find((r) => r.provider === "ollama" && r.base_url)?.base_url ?? "")
      : "";
  const catalogue = useProviderModels("ollama", ollamaUrl);

  function rowModels(_name: string) {
    return catalogue.data?.models || [];
  }

  function valueFor(name: string, field: Field) {
    const row = rows.find((r) => r.name === name);
    return draft[name]?.[field] ?? (row ? (row[field] ?? "") : "");
  }

  function edit(name: string, field: Field, value: string) {
    const row = rows.find((r) => r.name === name);
    const current = draft[name];
    setDraft((d) => ({
      ...d,
      [name]: {
        provider: field === "provider" ? value : current?.provider ?? row?.provider ?? "",
        model: field === "model" ? value : current?.model ?? row?.model ?? "",
        base_url: field === "base_url" ? value : current?.base_url ?? row?.base_url ?? "",
      },
    }));
  }

  return (
    <Stack gap="var(--s4)">
    <LocalSplit />
    <Card
      title="Model per station"
      description="Each stage of the pipeline can run on a different model. Spend where the work is hard; don't spend where it is extraction."
    >
      <QueryState query={bindings} label="Loading bindings" rows={4} />
      {save.error && <ErrorNotice error={save.error} />}

      {rows.length > 0 && (
        <>
          <p style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", marginTop: 0 }}>
            {bindings.data?.note}
          </p>
          <Table caption="Which model runs which station">
            <thead>
              <tr>
                <Th>Station</Th>
                <Th>Provider</Th>
                <Th>Model</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const dirty =
                  draft[row.name] &&
                  (draft[row.name].provider !== row.provider ||
                    draft[row.name].model !== row.model ||
                    draft[row.name].base_url !== (row.base_url ?? ""));
                const selfHosted = SELF_HOSTED.has(valueFor(row.name, "provider"));
                return (
                  <tr key={row.name}>
                    <Td>
                      <strong>{row.label}</strong>
                      {row.inherited_from && (
                        <>
                          {" "}
                          <Badge tone="warn" title={`No model set here; using the one bound to ${row.inherited_from}`}>
                            inherited
                          </Badge>
                        </>
                      )}
                      <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", marginTop: 2 }}>
                        {row.drives}
                      </div>
                      {row.guidance && (
                        <div style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)", marginTop: 4, fontStyle: "italic" }}>
                          {row.guidance}
                        </div>
                      )}
                    </Td>
                    <Td>
                      <Select
                        aria-label={`Provider for ${row.label}`}
                        value={valueFor(row.name, "provider")}
                        onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                          edit(row.name, "provider", e.target.value)
                        }
                        style={{ minWidth: "8rem" }}
                      >
                        {providers.map((p) => (
                          <option key={p} value={p}>{p}</option>
                        ))}
                      </Select>
                    </Td>
                    <Td>
                      {/* Free text for a vendor, whose catalogue moves faster
                          than any list here; the server's own answer for a
                          self-hosted one, which can simply be asked. */}
                      {selfHosted ? (
                        <Select
                          aria-label={`Model for ${row.label}`}
                          value={valueFor(row.name, "model")}
                          onChange={(e: React.ChangeEvent<HTMLSelectElement>) =>
                            edit(row.name, "model", e.target.value)
                          }
                          style={{ minWidth: "11rem" }}
                        >
                          <option value="">choose a model</option>
                          {!rowModels(row.name).includes(valueFor(row.name, "model")) &&
                            valueFor(row.name, "model") && (
                              <option value={valueFor(row.name, "model")}>
                                {valueFor(row.name, "model")} (not installed there)
                              </option>
                            )}
                          {rowModels(row.name).map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </Select>
                      ) : (
                        <Input
                          aria-label={`Model for ${row.label}`}
                          value={valueFor(row.name, "model")}
                          onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                            edit(row.name, "model", e.target.value)
                          }
                          placeholder="model id"
                          className="mono"
                          style={{ minWidth: "11rem" }}
                        />
                      )}
                      {/* Where the model actually is. Vendors have one address
                          and it is built in; your own Ollama does not, and
                          without this the station could be pointed at a local
                          model only by editing an environment variable and
                          restarting the API. */}
                      {selfHosted && (
                        <>
                          <Input
                            aria-label={`Base URL for ${row.label}`}
                            className="mono"
                            value={valueFor(row.name, "base_url")}
                            placeholder="http://host.docker.internal:11434"
                            onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                              edit(row.name, "base_url", e.target.value)
                            }
                            style={{ minWidth: "11rem", marginTop: 4 }}
                          />
                          <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)", marginTop: 2 }}>
                            The API runs in a container, so <code>localhost</code>{" "}
                            here means the container, not your machine. Use{" "}
                            <code>host.docker.internal</code> on Mac or Windows,
                            or the host's IP on Linux.
                          </div>
                        </>
                      )}
                    </Td>
                    <Td>
                      <Button
                        size="sm"
                        disabled={!dirty || save.isPending}
                        loading={save.isPending}
                        onClick={() =>
                          save.mutateAsync({
                            stage: row.name,
                            provider: valueFor(row.name, "provider"),
                            model: valueFor(row.name, "model"),
                            base_url: valueFor(row.name, "base_url") || null,
                          })
                        }
                      >
                        Save
                      </Button>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>

          <Stack gap="var(--s2)" style={{ marginTop: "var(--s3)" }}>
            <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
              <strong>Where the money goes.</strong> Reading the design is chunked
              page by page — a 296-page document is one call per chunk, and it is
              by far the highest token volume here. The notes are the longest
              writing and the place a weak model shows first. Everything else sits
              between the two.
            </div>
          </Stack>
        </>
      )}
    </Card>
    </Stack>
  );
}
