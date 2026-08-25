import React from "react";
import { useSearchParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  Grid,
  Input,
  Label,
  LoadingBlock,
  QueryState,
  PageHeader,
  Stack,
  Table,
  Td,
  Th,
} from "../ui/components";
import { API_BASE_URL } from "../api";
import { useApi, useDiagram } from "../lib/queries";
import { useQuery } from "@tanstack/react-query";

/**
 * Diagrams are structured now: a scene document names each part, marks which
 * layers can be removed, and defines croppable regions. That is what lets one
 * diagram render as both an unlabelled question figure and a labelled answer
 * figure, and lets a question test a single region of a larger drawing.
 *
 * This screen makes that visible so an operator can see what a question will
 * actually print before composing a paper around it.
 */
export function DiagramLibrary() {
  const [params, setParams] = useSearchParams();
  const api = useApi();
  const diagramId = params.get("id") || "";
  const [lookup, setLookup] = React.useState(diagramId);

  const diagram = useDiagram(diagramId || null);

  const [hidden, setHidden] = React.useState<string[]>([]);
  const [region, setRegion] = React.useState<string>("");
  const [highlight, setHighlight] = React.useState<string[]>([]);

  React.useEffect(() => {
    setHidden([]);
    setRegion("");
    setHighlight([]);
  }, [diagramId]);

  const renderUrl = React.useMemo(() => {
    if (!diagramId) return "";
    const qs = new URLSearchParams();
    if (hidden.length) qs.set("hide_layers", hidden.join(","));
    if (region) qs.set("region_id", region);
    if (highlight.length) qs.set("highlight", highlight.join(","));
    return `${API_BASE_URL}/api/v1/public/diagrams/${encodeURIComponent(diagramId)}/render?${qs}`;
  }, [diagramId, hidden, region, highlight]);

  const svg = useQuery({
    queryKey: ["diagram-svg", renderUrl],
    queryFn: async () => {
      const res = await fetch(renderUrl);
      if (!res.ok) throw new Error(`Could not render diagram (HTTP ${res.status})`);
      return res.text();
    },
    enabled: Boolean(renderUrl),
  });

  return (
    <>
      <PageHeader
        eyebrow="Assess"
        title="Diagram library"
        description="Inspect a diagram's structure and preview exactly how it will print — with labels for the marking scheme, without them for the learner's paper, or cropped to one region."
        actions={
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const next = new URLSearchParams(params);
              lookup ? next.set("id", lookup) : next.delete("id");
              setParams(next, { replace: true });
            }}
            style={{ display: "flex", gap: "var(--s2)" }}
          >
            <Input
              aria-label="Diagram ID"
              placeholder="diag-…"
              value={lookup}
              onChange={(e) => setLookup(e.target.value)}
              style={{ width: "16rem" }}
            />
            <Button type="submit" variant="primary">
              Open
            </Button>
          </form>
        }
      />

      {!diagramId && (
        <EmptyState
          title="Enter a diagram ID"
          description="Diagram IDs appear on any question that carries a visual, and in the bundle for each sub-strand."
        />
      )}

      <QueryState query={diagram} label="Loading diagram" rows={4} />

      {diagram.data && (
        <Grid min="320px" gap="var(--s5)">
          <Card
            title="Preview"
            description={
              hidden.length || region
                ? `Rendering with ${hidden.length ? `${hidden.join(", ")} hidden` : "all layers"}${region ? `, cropped to ${region}` : ""}`
                : "Full diagram, all layers"
            }
          >
            <div
              style={{
                background: "var(--surface-2)",
                border: "1px solid var(--line)",
                borderRadius: "var(--radius-sm)",
                padding: "var(--s3)",
                minHeight: "18rem",
                display: "grid",
                placeItems: "center",
                overflow: "hidden",
              }}
            >
              <QueryState query={svg} label="Rendering diagram" rows={1} />
              {svg.data && (
                <div
                  style={{ width: "100%", maxHeight: "22rem", display: "grid", placeItems: "center" }}
                  // The SVG comes from our own registry and was sanitised on ingest.
                  dangerouslySetInnerHTML={{ __html: svg.data }}
                />
              )}
            </div>

            <Stack gap="var(--s3)" style={{ marginTop: "var(--s4)" }}>
              <div>
                <Label>Layers</Label>
                <Stack direction="row" gap="var(--s2)" wrap style={{ marginTop: "var(--s2)" }}>
                  {diagram.data.layers.map((layer) => (
                    <label
                      key={layer.layer_id}
                      style={{
                        display: "inline-flex",
                        alignItems: "center",
                        gap: "var(--s2)",
                        fontSize: "var(--text-sm)",
                        opacity: layer.removable ? 1 : 0.5,
                      }}
                    >
                      <input
                        type="checkbox"
                        disabled={!layer.removable}
                        checked={!hidden.includes(layer.layer_id)}
                        onChange={(e) =>
                          setHidden((h) =>
                            e.target.checked ? h.filter((x) => x !== layer.layer_id) : [...h, layer.layer_id]
                          )
                        }
                      />
                      {layer.label}
                      {!layer.removable && <Badge tone="neutral">fixed</Badge>}
                    </label>
                  ))}
                </Stack>
              </div>

              {diagram.data.regions.length > 0 && (
                <div>
                  <Label>Crop to region</Label>
                  <Stack direction="row" gap="var(--s2)" wrap style={{ marginTop: "var(--s2)" }}>
                    <Button size="sm" variant={region ? "secondary" : "primary"} onClick={() => setRegion("")}>
                      Whole diagram
                    </Button>
                    {diagram.data.regions.map((r) => (
                      <Button
                        key={r.region_id}
                        size="sm"
                        variant={region === r.region_id ? "primary" : "secondary"}
                        onClick={() => setRegion(r.region_id)}
                      >
                        {r.label || r.region_id}
                      </Button>
                    ))}
                  </Stack>
                </div>
              )}

              <Stack direction="row" gap="var(--s2)" wrap>
                <Button
                  size="sm"
                  onClick={() => {
                    setHidden(diagram.data!.layers.filter((l) => l.removable).map((l) => l.layer_id));
                    setRegion("");
                  }}
                >
                  Preview as question paper
                </Button>
                <Button size="sm" onClick={() => { setHidden([]); setRegion(""); setHighlight([]); }}>
                  Preview as marking scheme
                </Button>
              </Stack>
            </Stack>
          </Card>

          <Stack gap="var(--s4)">
            <Card title={diagram.data.title || diagram.data.diagram_id}>
              <Stack gap="var(--s3)">
                <Stack direction="row" gap="var(--s2)" wrap>
                  {diagram.data.grade && <Badge tone="neutral">{diagram.data.grade}</Badge>}
                  {diagram.data.subject && <Badge tone="neutral">{diagram.data.subject}</Badge>}
                  <Badge tone={diagram.data.reuse_count > 1 ? "ok" : "neutral"}>
                    reused {diagram.data.reuse_count}×
                  </Badge>
                </Stack>
                <div>
                  <Label>Alt text</Label>
                  <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                    {diagram.data.accessibility.alt_text || "— missing —"}
                  </p>
                </div>
                <div>
                  <Label>Tactile description</Label>
                  <p style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                    {diagram.data.accessibility.tactile_description || "— missing —"}
                  </p>
                </div>
              </Stack>
            </Card>

            <Card
              title="Addressable parts"
              description="A question can name any of these, so it can ask about one part rather than the whole figure."
              padded={false}
            >
              {diagram.data.parts.length === 0 ? (
                <div style={{ padding: "var(--s4)" }}>
                  <EmptyState
                    title="No addressable parts"
                    description="This diagram predates the scene document. Regenerate it to make its parts addressable."
                    tone="warn"
                  />
                </div>
              ) : (
                <Table caption="Diagram parts">
                  <thead>
                    <tr>
                      <Th>Part</Th>
                      <Th>Layer</Th>
                      <Th>Assessable</Th>
                      <Th />
                    </tr>
                  </thead>
                  <tbody>
                    {diagram.data.parts.map((p) => (
                      <tr key={p.part_id}>
                        <Td>
                          <span style={{ fontWeight: 550 }}>{p.label}</span>
                          <div className="mono" style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
                            {p.part_id}
                          </div>
                        </Td>
                        <Td>{p.layer}</Td>
                        <Td>{p.assessable ? <Badge tone="ok">yes</Badge> : <Badge tone="neutral">no</Badge>}</Td>
                        <Td>
                          <Button
                            size="sm"
                            variant={highlight.includes(p.part_id) ? "primary" : "ghost"}
                            onClick={() =>
                              setHighlight((h) =>
                                h.includes(p.part_id) ? h.filter((x) => x !== p.part_id) : [...h, p.part_id]
                              )
                            }
                          >
                            Highlight
                          </Button>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card>
          </Stack>
        </Grid>
      )}
    </>
  );
}
