import React from "react";

import {
  Badge,
  Button,
  Card,
  ErrorNotice,
  QueryState,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import { useSetStageBinding, useStageBindings } from "../lib/queries";

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
export function StageModels() {
  const bindings = useStageBindings();
  const save = useSetStageBinding();
  const [draft, setDraft] = React.useState<Record<string, { provider: string; model: string }>>({});

  const rows = bindings.data?.stages || [];
  const providers = bindings.data?.providers || [];

  function valueFor(name: string, field: "provider" | "model") {
    const row = rows.find((r) => r.name === name);
    return draft[name]?.[field] ?? (row ? row[field] : "");
  }

  function edit(name: string, field: "provider" | "model", value: string) {
    const row = rows.find((r) => r.name === name);
    setDraft((d) => ({
      ...d,
      [name]: {
        provider: field === "provider" ? value : d[name]?.provider ?? row?.provider ?? "",
        model: field === "model" ? value : d[name]?.model ?? row?.model ?? "",
      },
    }));
  }

  return (
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
                    draft[row.name].model !== row.model);
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
                      <select
                        aria-label={`Provider for ${row.label}`}
                        value={valueFor(row.name, "provider")}
                        onChange={(e) => edit(row.name, "provider", e.target.value)}
                        style={{ padding: "6px 8px", borderRadius: "var(--radius-sm)" }}
                      >
                        {providers.map((p) => (
                          <option key={p} value={p}>{p}</option>
                        ))}
                      </select>
                    </Td>
                    <Td>
                      <input
                        aria-label={`Model for ${row.label}`}
                        value={valueFor(row.name, "model")}
                        onChange={(e) => edit(row.name, "model", e.target.value)}
                        placeholder="model id"
                        style={{ width: "13rem", padding: "6px 8px", borderRadius: "var(--radius-sm)" }}
                      />
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
  );
}
