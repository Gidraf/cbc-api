import React from "react";
import { Badge, Button, ErrorNotice, Stack } from "./components";
import { useDrawVisual } from "../lib/queries";

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
        const isBusy = busy === index && draw.isPending;

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
            </Stack>

            {visual.vivid_prompt && (
              <p style={{ margin: "var(--s2) 0 0", fontSize: "var(--text-sm)", color: "var(--ink-2)" }}>
                {visual.vivid_prompt}
              </p>
            )}

            {svg && (
              // The station's own output, shown as it will print. It has been
              // sanitised server-side before it was ever stored.
              <div
                style={{
                  marginTop: "var(--s3)",
                  padding: "var(--s3)",
                  background: "#fff",
                  borderRadius: "var(--radius-sm)",
                }}
                dangerouslySetInnerHTML={{ __html: svg }}
              />
            )}
          </div>
        );
      })}
    </Stack>
  );
}
