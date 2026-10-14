import React from "react";
import { Badge, Button, Card, EmptyState, ErrorNotice, Stack, useToast } from "../ui/components";
import { useCardLibrary, useMakeCards, usePhotoPosts, usePosterCommand, type CardRow, type PhotoPost } from "../lib/queries";

const STEP: Record<string, { label: string; icon: string }> = {
  teaser: { label: "Can you solve this?", icon: "🤔" },
  question: { label: "The question", icon: "❓" },
  answer: { label: "The answer", icon: "✅" },
};

/** A card, full size, over the page. */
function Lightbox({ src, title, onClose }: { src: string; title: string; onClose: () => void }) {
  React.useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div role="dialog" aria-label={title} onClick={onClose}
         style={{ position: "fixed", inset: 0, zIndex: 100, background: "rgba(0,0,0,.8)", display: "grid", placeItems: "center", padding: 16 }}>
      <figure style={{ margin: 0, display: "grid", gap: 8, justifyItems: "center" }} onClick={(e) => e.stopPropagation()}>
        <img src={src} alt={title} style={{ maxHeight: "86vh", maxWidth: "92vw", borderRadius: 12, boxShadow: "0 10px 40px rgba(0,0,0,.5)" }} />
        <figcaption style={{ color: "#fff", fontSize: "var(--text-sm)" }}>{title} · <a href={src} target="_blank" rel="noreferrer" style={{ color: "#fff" }}>open</a> · <button onClick={onClose} style={{ background: "none", border: 0, color: "#fff", textDecoration: "underline", cursor: "pointer" }}>close</button></figcaption>
      </figure>
    </div>
  );
}

function Thumb({ src, label, onOpen }: { src?: string | null; label: string; onOpen: (src: string, label: string) => void }) {
  const box: React.CSSProperties = { width: 72, height: 90, borderRadius: 6, border: "1px solid var(--line)", flexShrink: 0 };
  if (!src) return <div title={`${label} — not made yet`} style={{ ...box, display: "grid", placeItems: "center", color: "var(--ink-3)", fontSize: 11, background: "var(--surface-2, transparent)" }}>—</div>;
  return (
    <button title={`${label} — click to see it`} onClick={() => onOpen(src, label)} style={{ padding: 0, background: "none", cursor: "zoom-in", ...box, overflow: "hidden" }}>
      <img src={src} alt={label} loading="lazy" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} />
    </button>
  );
}

/** The photo side of social: each question's three cards, the series booking, and the photo schedule. */
export function PhotoStudio({ grade, subject, subStrand, bookSeries }: {
  grade: string; subject: string; subStrand: string; bookSeries: React.ReactNode;
}) {
  const [view, setView] = React.useState<{ src: string; label: string } | null>(null);
  const open = (src: string, label: string) => setView({ src, label });
  return (
    <>
      <PhotoSchedule onOpen={open} />
      <Card title="Book photo + video series" description="Each question told in steps through the day: “Can you solve this?”, the question, the answer, then its video.">
        {grade ? bookSeries : <p style={{ margin: 0, color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>Choose a grade and subject above.</p>}
      </Card>
      <CardLibrary grade={grade} subject={subject} subStrand={subStrand} onOpen={open} />
      {view && <Lightbox src={view.src} title={view.label} onClose={() => setView(null)} />}
    </>
  );
}

function CardLibrary({ grade, subject, subStrand, onOpen }: { grade: string; subject: string; subStrand: string; onOpen: (src: string, label: string) => void }) {
  const lib = useCardLibrary(grade, subject, subStrand);
  const make = useMakeCards();
  const toast = useToast();
  const [figuresOnly, setFiguresOnly] = React.useState(false);
  const [filter, setFilter] = React.useState<"all" | "ready" | "missing">("all");
  async function makeAll() {
    try {
      const out = await make.mutateAsync({ grade, subject, sub_strand: subStrand || undefined, figures_only: figuresOnly });
      const c = out.counts || {};
      toast(`Cards: ${c.queued || 0} questions queued, ${c.ready || 0} already made.`, "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not make the cards.", "danger"); }
  }
  async function makeOne(qid: string) {
    try { await make.mutateAsync({ grade, subject, question_id: qid }); toast("Making its cards…", "ok"); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not make them.", "danger"); }
  }
  const rows = (lib.data?.items || []).filter((r: CardRow) =>
    (!figuresOnly || r.has_figure) && (filter === "all" || (filter === "ready" ? r.status === "ready" : r.status !== "ready")));
  return (
    <Card title="Photo cards"
          description="Every question's three cards. Click a card to see it full size."
          actions={grade ? (
            <Stack direction="row" gap="var(--s2)" align="center" wrap>
              <label style={{ fontSize: "var(--text-sm)", display: "inline-flex", gap: 4, alignItems: "center" }}>
                <input type="checkbox" checked={figuresOnly} onChange={(e) => setFiguresOnly(e.target.checked)} /> With a figure
              </label>
              <select value={filter} onChange={(e) => setFilter(e.target.value as any)} style={{ fontSize: "var(--text-sm)" }}>
                <option value="all">All</option><option value="ready">Made</option><option value="missing">Not made</option>
              </select>
              <Button size="sm" variant="primary" disabled={make.isPending} onClick={makeAll}>📸 Make cards for {subStrand ? "this topic" : "this subject"}</Button>
            </Stack>
          ) : undefined}>
      {!grade ? <p style={{ margin: 0, color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>Choose a grade and subject above.</p>
        : lib.error ? <ErrorNotice error={lib.error} />
        : !lib.data ? <p style={{ margin: 0, color: "var(--ink-3)" }}>Loading the cards…</p>
        : rows.length === 0 ? <EmptyState title="No questions here" description="Change the topic or the filter." />
        : (
          <div style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>{lib.data.ready} of {lib.data.items.length} questions have all three cards.</span>
            {rows.map((r) => (
              <div key={r.question_id} style={{ display: "flex", gap: "var(--s2)", alignItems: "center", padding: "6px 0", borderBottom: "1px solid var(--line-2)", flexWrap: "wrap" }}>
                <Stack direction="row" gap="4px">
                  {(["teaser", "question", "answer"] as const).map((s) => <Thumb key={s} src={r.cards[s]?.url} label={STEP[s].label} onOpen={onOpen} />)}
                </Stack>
                <span style={{ flex: 1, minWidth: 200, fontSize: "var(--text-sm)" }}>{r.question_text}</span>
                {r.has_figure && <span title="Has a figure">📐</span>}
                <Badge tone={r.status === "ready" ? "ok" : r.status === "making" ? "info" : "neutral"}>
                  {{ ready: "3 cards", making: "making…", partial: "some made", none: "not made" }[r.status]}</Badge>
                {r.status !== "ready" && r.status !== "making" && <Button size="sm" variant="ghost" onClick={() => makeOne(r.question_id)}>Make</Button>}
              </div>
            ))}
          </div>
        )}
    </Card>
  );
}

function day(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
}

function PhotoSchedule({ onOpen }: { onOpen: (src: string, label: string) => void }) {
  const posts = usePhotoPosts();
  const command = usePosterCommand();
  const toast = useToast();
  const [showPosted, setShowPosted] = React.useState(false);
  const data = posts.data;
  async function run(action: "dry_run" | "run_now", p: PhotoPost) {
    if (action === "run_now" && !window.confirm(`Post this ${STEP[p.step]?.label.toLowerCase() || "card"} to Facebook now?`)) return;
    try {
      const out = await command.mutateAsync({ action, platform: p.platform, post_id: p.post_id });
      if (out?.error) toast(String(out.error), "danger");
      else toast(out?.message || (action === "dry_run" ? "Dry run sent to the poster — see its screenshot in Auto-post." : "Sent to the poster."), "info");
    } catch (err) { toast(err instanceof Error ? err.message : "The poster did not answer.", "danger"); }
  }
  const list = (data?.posts || []).filter((p) => showPosted || !p.posted_at);
  const byDay: [string, PhotoPost[]][] = [];
  for (const p of list) {
    const key = day((p.posted_at || p.scheduled_for || new Date().toISOString()) as string);
    const last = byDay[byDay.length - 1];
    if (last && last[0] === key) last[1].push(p); else byDay.push([key, [p]]);
  }
  return (
    <Card title={`Scheduled photos${data ? ` · ${data.upcoming} coming up` : ""}`}
          description="Every photo post booked, with its card. Dry run goes through every step but the last; Post now puts it out."
          actions={<label style={{ fontSize: "var(--text-sm)", display: "inline-flex", gap: 4, alignItems: "center" }}>
            <input type="checkbox" checked={showPosted} onChange={(e) => setShowPosted(e.target.checked)} /> Show the last 3 days' posted
          </label>}>
      {posts.error ? <ErrorNotice error={posts.error} /> : !data ? <p style={{ margin: 0, color: "var(--ink-3)" }}>Loading…</p>
        : list.length === 0 ? <EmptyState title="No photo posts booked" description="Book photo + video series below." />
        : (
          <div style={{ display: "grid", gap: "var(--s3)" }}>
            {data.cards_missing > 0 && <span style={{ fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>⏳ {data.cards_missing} booked card(s) are still being made — they post once made.</span>}
            {byDay.map(([d, ps]) => (
              <div key={d}>
                <strong style={{ fontSize: "var(--text-sm)" }}>{d}</strong>
                <div style={{ display: "grid", gap: 4, marginTop: 4 }}>
                  {ps.map((p) => (
                    <div key={p.post_id} style={{ display: "flex", gap: "var(--s2)", alignItems: "center", flexWrap: "wrap", padding: "4px 0", borderBottom: "1px solid var(--line-2)" }}>
                      <Thumb src={p.card_url} label={`${STEP[p.step]?.label || p.step} — ${p.question_text.slice(0, 60)}`} onOpen={onOpen} />
                      <span style={{ fontVariantNumeric: "tabular-nums", fontSize: "var(--text-sm)", minWidth: 48 }}>
                        {new Date((p.posted_at || p.scheduled_for) as string).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                      </span>
                      <Badge tone="neutral">{STEP[p.step]?.icon} {STEP[p.step]?.label || p.step}</Badge>
                      <span style={{ flex: 1, minWidth: 180, fontSize: "var(--text-sm)" }}>{p.question_text}</span>
                      {p.posted_at ? <Badge tone="ok">posted{p.url ? "" : ""}</Badge>
                        : p.status === "failed" ? <Badge tone="danger" title={p.last_error}>failed ({p.attempts})</Badge>
                        : p.card_status !== "ready" ? <Badge tone="info">card being made</Badge> : <Badge tone="neutral">booked</Badge>}
                      {!p.posted_at && p.card_status === "ready" && (
                        <Stack direction="row" gap="4px">
                          <Button size="sm" variant="ghost" disabled={command.isPending} onClick={() => run("dry_run", p)}>Dry run</Button>
                          <Button size="sm" disabled={command.isPending} onClick={() => run("run_now", p)}>Post now</Button>
                        </Stack>
                      )}
                      {p.url && <a href={p.url} target="_blank" rel="noreferrer" style={{ fontSize: "var(--text-xs)" }}>view ↗</a>}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
    </Card>
  );
}
