import React from "react";
import { Badge, Button, ErrorNotice, Stack } from "./components";
import { useDrawVisual, useEditVisualSvg } from "../lib/queries";

/**
 * Draw the visuals a diagram plan describes.
 *
 * The station writes a brief per visual — a title, what it must show, and a
 * scene of addressable parts so a question can point at one region. Turning
 * that into an actual picture had no button anywhere, so every brief sat in an
 * artifact and the book printed a hatched rectangle next to it.
 *
 * A drawn visual is filed against its own title, which is what the book
 * matches on, so the plate fills on the next render.
 */
export function DrawVisuals({
  artifactId,
  content,
}: {
  artifactId: string;
  content: any;
}) {
  const draw = useDrawVisual();
  // Editing ONE drawing. The whole-artifact JSON editor was the only way in,
  // and in it every SVG is a single enormous line among the briefs — so a
  // drawing that was nearly right got redrawn from scratch instead of nudged.
  const edit = useEditVisualSvg();
  const [editing, setEditing] = React.useState<number | null>(null);
  const [draft, setDraft] = React.useState("");
  const [busy, setBusy] = React.useState<number | null>(null);

  const visuals: any[] = React.useMemo(() => {
    const found = content?.visuals || content?.diagrams;
    return Array.isArray(found) ? found.filter((v) => v && typeof v === "object") : [];
  }, [content]);

  if (!visuals.length) return null;

  const drawnCount = visuals.filter((v) => v.diagram_svg).length;

  function drawOne(index: number) {
    setBusy(index);
    draw.mutate(
      { artifact_id: artifactId, index },
      { onSettled: () => setBusy(null) }
    );
  }

  return (
    <Stack gap="var(--s3)">
      <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
        <strong style={{ fontSize: "var(--text-sm)" }}>Planned visuals</strong>
        <Badge tone={drawnCount === visuals.length ? "ok" : "warn"}>
          {drawnCount} of {visuals.length} drawn
        </Badge>
        <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
          Drawing one files it where the book looks, so its plate fills.
        </span>
      </Stack>

      {draw.error && <ErrorNotice error={draw.error} />}

      {visuals.map((visual, index) => {
        const title = visual.diagram_title || visual.title || `Visual ${index + 1}`;
        const parts = visual?.scene?.parts;
        const svg: string = visual.diagram_svg || "";
        // Only the drawing just returned carries a measurement; a visual read
        // back from a stored version has none, and shows the picture alone.
        const fit =
          edit.data?.index === index
            ? edit.data.layout
            : draw.data?.index === index
              ? draw.data.layout
              : undefined;
        const isBusy = busy === index && draw.isPending;
        const stored =
          edit.data?.index === index
            ? edit.data.stored_in_minio
            : draw.data?.stored_in_minio;

        return (
          <div
            key={index}
            style={{
              border: "1px solid var(--line)",
              borderRadius: "var(--radius-sm)",
              padding: "var(--s3)",
            }}
          >
            <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", flexWrap: "wrap" }}>
              <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)", letterSpacing: "0.06em" }}>
                DIAGRAM 1.{index + 1}
              </span>
              <strong style={{ fontSize: "var(--text-sm)" }}>{title}</strong>
              {svg ? <Badge tone="ok">drawn</Badge> : <Badge tone="warn">brief only</Badge>}
              {Array.isArray(parts) && parts.length > 0 && (
                <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                  {parts.length} addressable part{parts.length === 1 ? "" : "s"}
                </span>
              )}
              <Button
                size="sm"
                variant={svg ? "secondary" : "primary"}
                disabled={draw.isPending}
                loading={isBusy}
                onClick={() => drawOne(index)}
                title={
                  svg
                    ? "Draw it again — the new one replaces this."
                    : "Turn this brief into an SVG the book can print."
                }
              >
                {isBusy ? "Drawing…" : svg ? "Draw again" : "Draw it"}
              </Button>
              {svg && (
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={draw.isPending || edit.isPending}
                  title="Change this drawing's SVG by hand, without touching the others"
                  onClick={() => {
                    setEditing(editing === index ? null : index);
                    setDraft(svg);
                  }}
                >
                  {editing === index ? "Cancel" : "Edit this one"}
                </Button>
              )}
            </Stack>

            {editing === index && (
              <div style={{ marginTop: "var(--s3)" }}>
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  spellCheck={false}
                  style={{
                    width: "100%",
                    minHeight: 220,
                    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                    fontSize: 12,
                    lineHeight: 1.45,
                    padding: "var(--s2)",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--line)",
                    background: "var(--surface-2)",
                    color: "var(--ink-1)",
                  }}
                />
                <Stack direction="row" gap="var(--s2)" style={{ marginTop: "var(--s2)", alignItems: "center" }}>
                  <Button
                    size="sm"
                    disabled={edit.isPending || !draft.trim()}
                    loading={edit.isPending}
                    onClick={() =>
                      edit
                        .mutateAsync({ artifact_id: artifactId, index, svg: draft })
                        .then(() => setEditing(null))
                    }
                  >
                    {edit.isPending ? "Saving…" : "Save this drawing"}
                  </Button>
                  <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                    Files a new version and re-files the picture, so the book
                    shows it on the next refresh.
                  </span>
                </Stack>
                {edit.error && <ErrorNotice error={edit.error} />}
              </div>
            )}

            {visual.vivid_prompt && (
              <p style={{ margin: "var(--s2) 0 0", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                {visual.vivid_prompt}
              </p>
            )}

            {svg && (
              // The station's own output, shown AT THE SIZE IT PRINTS. This
              // panel used to stretch the drawing across its full width, and
              // a reviewer looking at a 700px picture cannot see that its
              // labels resolve to 2mm in the book. The book's figure is 85mm
              // — one column of a two-column A4 page — so the preview is
              // 85mm, with the plate's reserved height marked beside it.
              <div style={{ marginTop: "var(--s3)" }}>
                <Stack direction="row" gap="var(--s2)" style={{ alignItems: "center", marginBottom: "var(--s1)" }}>
                  <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-2)" }}>
                    Actual size in the book — 85mm column
                  </span>
                  {fit && (
                    <Badge tone={stored ? "ok" : "warn"}>
                      {stored ? "stored" : "not in storage"}
                    </Badge>
                  )}
                </Stack>
                <div
                  style={{
                    width: "85mm",
                    maxWidth: "100%",
                    padding: 0,
                    background: "#fff",
                    border: "1px solid var(--line)",
                    borderRadius: "var(--radius-sm)",
                  }}
                  dangerouslySetInnerHTML={{ __html: svg }}
                />
                {fit && (fit.repairs?.length ?? 0) > 0 && (
                  // A repair that worked leaves nothing wrong to report, so
                  // without this the operator never learns their drawing was
                  // altered before it was filed.
                  <div style={{ marginTop: "var(--s2)", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                    Adjusted before filing: {fit.repairs!.join(" ")}
                  </div>
                )}
                {fit && !fit.fits && (
                  // Measured server-side against that same column. The model
                  // is asked to redraw once; what survives is reported rather
                  // than filed quietly.
                  <div
                    style={{
                      marginTop: "var(--s2)",
                      padding: "var(--s2)",
                      fontSize: "var(--text-sm)",
                      background: "var(--warn-bg, #fff8e6)",
                      borderRadius: "var(--radius-sm)",
                    }}
                  >
                    <strong>This drawing does not fit the page</strong>
                    <ul style={{ margin: "var(--s1) 0 0", paddingLeft: "1.2em" }}>
                      {(fit.findings || []).map((f: string, i: number) => (
                        <li key={i}>{f}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
    </Stack>
  );
}
