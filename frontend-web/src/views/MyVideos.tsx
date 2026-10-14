import React from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge, Button, Card, EmptyState, ErrorNotice, LoadingBlock, PageHeader, Select, Stack, useToast } from "../ui/components";
import { MathText } from "../ui/MathBlock";
import { StreamedVideo } from "../ui/StreamedVideo";
import { useApi, useDrafts } from "../lib/queries";

type Item = { question_id: string; question_text: string; grade: string; subject: string; sub_strand: string;
              has_figure: boolean; video: "ready" | "being made" | "failed" | "none" };
type Library = { items: Item[]; ready: number; being_made: number };

/** Every question the account bought, as a video: watch it here, or have it made. */
export function MyVideos() {
  const api = useApi();
  const qc = useQueryClient();
  const toast = useToast();
  const drafts = useDrafts();
  const [params, setParams] = useSearchParams();
  const draft = params.get("draft") || "";
  const [watching, setWatching] = React.useState("");
  const [filter, setFilter] = React.useState<"all" | "ready" | "figures">("all");
  const lib = useQuery({
    queryKey: ["my-videos", draft],
    queryFn: () => api<Library>(`/api/v1/classroom/library${draft ? `?draft_id=${encodeURIComponent(draft)}` : ""}`),
    refetchInterval: (q) => ((q.state.data?.being_made || 0) > 0 ? 20_000 : false),
  });
  const make = useMutation({
    mutationFn: () => api<{ queued: number }>(`/api/v1/classroom/library/make${draft ? `?draft_id=${encodeURIComponent(draft)}` : ""}`, { method: "POST" }),
    onSuccess: (out) => {
      toast(out.queued ? `${out.queued} video(s) are being made — first in line.` : "Nothing to make: every video is made or on its way.", "ok");
      qc.invalidateQueries({ queryKey: ["my-videos"] });
      // They are queued in the background: look again once they are.
      setTimeout(() => qc.invalidateQueries({ queryKey: ["my-videos"] }), 6000);
    },
  });
  const all = lib.data?.items || [];
  const shown = all.filter((i) => filter === "all" || (filter === "ready" ? i.video === "ready" : i.has_figure));
  const missing = all.filter((i) => i.video === "none" || i.video === "failed").length;
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader eyebrow="Classroom" title="My videos"
        description="Every question you bought, worked out on a whiteboard and narrated — watch it here. A question you bought without a video gets one made, before anyone else's." />
      <Card>
        <Stack direction="row" gap="var(--s3)" wrap align="center">
          <Select value={draft} onChange={(e) => setParams(e.target.value ? { draft: e.target.value } : {})} style={{ width: "auto" }}>
            <option value="">Every question I bought</option>
            {(drafts.data || []).map((d) => <option key={d.draft_id} value={d.draft_id}>{d.title || "(untitled)"}</option>)}
          </Select>
          <Select value={filter} onChange={(e) => setFilter(e.target.value as any)} style={{ width: "auto" }}>
            <option value="all">All</option>
            <option value="ready">Videos ready</option>
            <option value="figures">With a figure</option>
          </Select>
          <span style={{ flex: 1, fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
            {lib.data ? `${lib.data.ready} ready · ${lib.data.being_made} being made${missing ? ` · ${missing} not made yet` : ""}` : ""}
          </span>
          {missing > 0 && <Button variant="primary" loading={make.isPending} onClick={() => make.mutate()}>Make the {missing} missing video(s)</Button>}
        </Stack>
      </Card>
      {lib.error && <ErrorNotice error={lib.error} />}
      {!lib.data ? <LoadingBlock rows={4} label="Loading your videos" /> : shown.length === 0 ? (
        <EmptyState title={all.length ? "Nothing matches" : "No bought questions yet"}
                    description={all.length ? "Change the filter." : "Buy a paper in the Exam studio: every question on it becomes yours, video and all."} />
      ) : (
        <div style={{ display: "grid", gap: "var(--s2)" }}>
          {shown.map((it) => (
            <Card key={it.question_id}>
              <div style={{ display: "grid", gap: "var(--s2)" }}>
                <Stack direction="row" gap="var(--s2)" align="center" wrap>
                  <span style={{ flex: 1, minWidth: 220, fontSize: "var(--text-sm)" }}><MathText text={it.question_text.slice(0, 220)} /></span>
                  {it.has_figure && <span title="Has a figure">📐</span>}
                  <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{[it.subject, it.sub_strand].filter(Boolean).join(" · ")}</span>
                  {it.video === "ready"
                    ? <Button size="sm" variant={watching === it.question_id ? "ghost" : "primary"} onClick={() => setWatching(watching === it.question_id ? "" : it.question_id)}>
                        {watching === it.question_id ? "Close" : "▶ Watch"}</Button>
                    : <Badge tone={it.video === "being made" ? "info" : it.video === "failed" ? "danger" : "neutral"}>
                        {it.video === "being made" ? "Being made…" : it.video === "failed" ? "Failed — make again" : "No video yet"}</Badge>}
                </Stack>
                {watching === it.question_id && <StreamedVideo questionId={it.question_id} />}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
