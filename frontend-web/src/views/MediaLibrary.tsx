import React from "react";
import { useSearchParams } from "react-router-dom";

import {
  Badge,
  Button,
  Card,
  CopyButton,
  EmptyState,
  Field,
  PageHeader,
  QueryState,
  Select,
  Stack,
  Tabs,
} from "../ui/components";
import {
  gradeOptionLabel,
  subjectOptionLabel,
  useGrades,
  useSubstrandMedia,
  useSavedSubstrands,
  useSubjects,
  type MediaItem,
} from "../lib/queries";

/**
 * Every photograph and video the factory has planned, shown as pictures.
 *
 * A media brief is a wall of text describing an image, and reading it as text
 * is the one way you cannot tell whether it will produce the right picture. So
 * a produced asset renders, and a planned one renders as a labelled frame in
 * its own aspect ratio — the shape of the thing that is missing, sized as it
 * will actually appear, rather than a row in a table saying "planned".
 */

/** The frame a planned asset occupies before its file exists. */
function Placeholder({ item }: { item: MediaItem }) {
  const ratio = String(item.spec?.aspect_ratio || (item.kind === "video" ? "16:9" : "4:3"));
  const [w, h] = ratio.split(":").map((n) => Number(n) || 1);

  return (
    <div
      role="img"
      aria-label={item.alt_text || `${item.kind} not yet produced: ${item.title}`}
      style={{
        aspectRatio: `${w} / ${h}`,
        width: "100%",
        display: "grid",
        placeItems: "center",
        gap: "var(--s2)",
        background: "var(--surface-2)",
        border: "1px dashed var(--line)",
        borderRadius: "var(--radius-sm)",
        color: "var(--ink-3)",
        textAlign: "center",
        padding: "var(--s3)",
      }}
    >
      <div style={{ fontSize: "1.6rem" }} aria-hidden="true">
        {item.kind === "video" ? "▶" : "▣"}
      </div>
      <div style={{ fontSize: "var(--text-sm)", fontWeight: 550 }}>{item.title}</div>
      <div style={{ fontSize: "var(--text-xs)" }}>
        {ratio} · brief written, asset not produced yet
      </div>
    </div>
  );
}

function Asset({ item }: { item: MediaItem }) {
  if (!item.storage_url) return <Placeholder item={item} />;
  if (item.kind === "video") {
    return (
      <video
        controls
        src={item.storage_url}
        aria-label={item.alt_text || item.title}
        style={{ width: "100%", borderRadius: "var(--radius-sm)", background: "var(--surface-2)" }}
      />
    );
  }
  return (
    <img
      src={item.storage_url}
      alt={item.alt_text || item.title}
      style={{ width: "100%", borderRadius: "var(--radius-sm)", display: "block" }}
    />
  );
}

/** One asset: the picture, and the brief that would produce it. */
export function MediaCard({ item }: { item: MediaItem }) {
  const [tab, setTab] = React.useState("brief");
  const promptTokens = Math.round((item.generation_prompt || "").length / 4);

  const tabs = [
    { id: "brief", label: "Brief", badge: <Badge tone="neutral">{promptTokens} tok</Badge> },
    ...(item.kind === "video" && item.shot_list?.length
      ? [{ id: "shots", label: "Shots", badge: <Badge tone="neutral">{item.shot_list.length}</Badge> }]
      : []),
    { id: "alt", label: "Alt text" },
  ];

  return (
    <Card
      title={item.title}
      description={item.purpose}
      actions={
        <Stack direction="row" gap="var(--s2)">
          <Badge tone={item.kind === "video" ? "info" : "accent"}>{item.kind}</Badge>
          <Badge tone={item.status === "produced" ? "ok" : "warn"}>{item.status}</Badge>
          <CopyButton
            label="Copy prompt"
            title="Paste this into an image or video model to produce the asset"
            getText={() =>
              [
                item.generation_prompt || "",
                item.negative_prompt ? `\n\nNEGATIVE PROMPT:\n${item.negative_prompt}` : "",
                item.spec ? `\n\nSPEC: ${JSON.stringify(item.spec)}` : "",
              ].join("")
            }
          />
        </Stack>
      }
    >
      <Stack gap="var(--s3)">
        <Asset item={item} />

        {item.for_lesson && (
          <div style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
            For {item.for_lesson}
            {item.sub_strand_name ? ` · ${item.sub_strand_name}` : ""}
          </div>
        )}

        <Tabs tabs={tabs} active={tab} onChange={setTab} />

        {tab === "brief" && (
          <>
            {promptTokens < (item.kind === "video" ? 5000 : 1000) && (
              <div
                style={{
                  border: "1px solid var(--line)",
                  borderRadius: "var(--radius-sm)",
                  padding: "var(--s3)",
                  marginBottom: "var(--s2)",
                  fontSize: "var(--text-sm)",
                  color: "var(--ink-3)",
                }}
              >
                This brief is {promptTokens} tokens; {item.kind === "video" ? 5000 : 1000} are
                expected. An image model invents everything the brief leaves out.
              </div>
            )}
            <pre style={preStyle}>{item.generation_prompt || "— no brief —"}</pre>
            {item.negative_prompt && (
              <>
                <strong style={{ fontSize: "var(--text-sm)" }}>Must not appear</strong>
                <pre style={preStyle}>{item.negative_prompt}</pre>
              </>
            )}
          </>
        )}

        {tab === "shots" && (
          <pre style={preStyle}>
            {(item.shot_list || [])
              .map(
                (shot: any) =>
                  `Shot ${shot.shot} · ${shot.seconds}s · ${shot.camera || ""}\n` +
                  `${shot.on_screen || ""}\n` +
                  (shot.narration ? `NARRATION: ${shot.narration}\n` : "")
              )
              .join("\n")}
          </pre>
        )}

        {tab === "alt" && (
          <pre style={preStyle}>{item.alt_text || "— no alt text, which blocks approval —"}</pre>
        )}
      </Stack>
    </Card>
  );
}

const preStyle: React.CSSProperties = {
  margin: 0,
  maxHeight: 300,
  overflow: "auto",
  fontSize: "var(--text-sm)",
  background: "var(--surface-2)",
  padding: "var(--s3)",
  borderRadius: "var(--radius-sm)",
  whiteSpace: "pre-wrap",
};

export function MediaLibrary() {
  const [params, setParams] = useSearchParams();
  const grade = params.get("grade") || "";
  const subject = params.get("subject") || "";
  const subStrand = params.get("substrand") || "";
  const kind = params.get("kind") || "";

  const grades = useGrades();
  const effectiveGrade = grade || grades.data?.[0]?.slug || grades.data?.[0]?.name || "";
  const subjects = useSubjects(effectiveGrade);
  const substrands = useSavedSubstrands(effectiveGrade, subject || undefined);
  const media = useSubstrandMedia(effectiveGrade, subject, subStrand);

  function setParam(patch: Record<string, string>) {
    const next = new URLSearchParams(params);
    Object.entries(patch).forEach(([k, v]) => (v ? next.set(k, v) : next.delete(k)));
    setParams(next, { replace: true });
  }

  const items = (media.data?.media || []).filter((m) => !kind || m.kind === kind);
  const names = Array.from(
    new Set((substrands.data || []).map((r: any) => String(r.sub_strand_name || "")))
  ).filter(Boolean);

  return (
    <>
      <PageHeader
        eyebrow="Assess"
        title="Photo & video library"
        description="Every image and video the factory has planned, shown as pictures. A brief read as text is the one way you cannot tell whether it will produce the right picture."
        actions={
          <Select
            aria-label="Grade"
            value={effectiveGrade}
            onChange={(e) => setParam({ grade: e.target.value, subject: "", substrand: "" })}
            style={{ width: "auto" }}
          >
            {(grades.data || []).map((g) => (
              <option key={g.slug || g.name} value={g.slug || g.name}>
                {gradeOptionLabel(g)}
              </option>
            ))}
          </Select>
        }
      />

      <Card title="Filter">
        <Stack direction="row" gap="var(--s3)" style={{ flexWrap: "wrap" }}>
          <Field label="Subject">
            {(a11y) => (
              <Select
                {...a11y}
                value={subject}
                onChange={(e) => setParam({ subject: e.target.value, substrand: "" })}
              >
                <option value="">Choose a subject…</option>
                {(subjects.data || []).map((s) => (
                  <option key={s.name} value={s.name}>{subjectOptionLabel(s)}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Sub-strand">
            {(a11y) => (
              <Select
                {...a11y}
                value={subStrand}
                onChange={(e) => setParam({ substrand: e.target.value })}
              >
                <option value="">All sub-strands</option>
                {names.map((n) => <option key={n} value={n}>{n}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Kind">
            {(a11y) => (
              <Select {...a11y} value={kind} onChange={(e) => setParam({ kind: e.target.value })}>
                <option value="">Photos and videos</option>
                <option value="photo">Photos only</option>
                <option value="video">Videos only</option>
              </Select>
            )}
          </Field>
          {subject && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() =>
                (window.location.href =
                  `/factory?grade=${encodeURIComponent(effectiveGrade)}` +
                  `&subject=${encodeURIComponent(subject)}` +
                  (subStrand ? `&substrand=${encodeURIComponent(subStrand)}` : ""))
              }
            >
              Generate in the factory →
            </Button>
          )}
        </Stack>
      </Card>

      {!subject ? (
        <EmptyState
          title="Choose a subject"
          description="Media is planned per sub-strand, from what the teaching notes actually describe."
        />
      ) : (
        <>
          <QueryState query={media} label="Loading media" rows={4} />
          {media.data && (
            <Stack direction="row" gap="var(--s2)" style={{ marginBottom: "var(--s3)" }}>
              <Badge tone="warn">{media.data.planned} planned</Badge>
              <Badge tone="ok">{media.data.produced} produced</Badge>
            </Stack>
          )}
          {media.data && items.length === 0 ? (
            <EmptyState
              title="Nothing planned here yet"
              description="Run the Photos & videos station in the factory for a sub-strand. Every learning area needs images — a learner who cannot yet read learns almost entirely from the picture."
              tone="warn"
            />
          ) : (
            <Stack gap="var(--s4)">
              {items.map((item) => <MediaCard key={item.media_id} item={item} />)}
            </Stack>
          )}
        </>
      )}
    </>
  );
}
