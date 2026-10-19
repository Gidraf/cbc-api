import React from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, Card, ErrorNotice, Input, LoadingBlock, PageHeader, Select, Stack, useToast } from "../ui/components";
import { MathText } from "../ui/MathBlock";
import {
  useBoostPost, useLibrary, useLibraryQuestion, useLibraryTree, useMakeSocial, usePostQuestion,
  type LibraryFilters, type LibraryItem, type LibraryPost, type LibraryQuestion,
} from "../lib/queries";

type Tone = "ok" | "info" | "warn" | "danger" | "neutral";

const when = (iso?: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";
const future = (iso?: string | null) => Boolean(iso && new Date(iso).getTime() > Date.now());

/** Where a post is, in words: out (with its link), waiting in Facebook's scheduler, booked, or stuck. */
function postState(p: { status: string; handed_at?: string | null; posted_at?: string | null; scheduled_for?: string | null;
                        url?: string; platform_scheduled?: boolean; notes?: string }): [string, Tone] {
  if (p.status === "gave_up") return ["Gave up", "danger"];
  if (p.notes === "scheduler-unverified") return ["Not verified — check Meta Business Suite", "warn"];
  if (p.handed_at) {
    const scheduler = p.platform_scheduled || p.status === "scheduled";
    if (scheduler && future(p.posted_at)) return [`Scheduled on Facebook · ${when(p.posted_at)}`, "info"];
    if (scheduler && !p.url) return [`Due ${when(p.posted_at)} · being looked for on the profile`, "warn"];
    return [`Posted · ${when(p.posted_at)}`, "ok"];
  }
  if (p.status === "failed") return [`Failed · retried · booked ${when(p.scheduled_for)}`, "danger"];
  if (p.scheduled_for) return [`Booked · ${when(p.scheduled_for)}`, "neutral"];
  return ["Not booked", "neutral"];
}

const VIDEO_TONE: Record<string, Tone> = { ready: "ok", queued: "info", running: "info", failed: "danger", none: "neutral" };
const VIDEO_WORD: Record<string, string> = { ready: "Video ready", queued: "Video queued", running: "Video being made",
                                             failed: "Video failed", none: "No current video" };

/** One place for every question: its video, where its posts are, their comments, boost and numbers. */
export function Library() {
  const [params, setParams] = useSearchParams();
  const [f, setF] = React.useState<LibraryFilters>({ grade: "", subject: "", sub_strand: "", search: "", show: "all", offset: 0 });
  const [typed, setTyped] = React.useState("");
  React.useEffect(() => {
    const t = setTimeout(() => setF((x) => (x.search === typed ? x : { ...x, search: typed, offset: 0 })), 350);
    return () => clearTimeout(t);
  }, [typed]);
  const tree = useLibraryTree();
  const list = useLibrary(f);
  const rows = tree.data?.rows || [];
  const grades = [...new Set(rows.map((r) => r.grade).filter(Boolean))];
  const subjects = [...new Set(rows.filter((r) => !f.grade || r.grade === f.grade).map((r) => r.subject).filter(Boolean))];
  const subStrands = [...new Set(rows.filter((r) => (!f.grade || r.grade === f.grade) && (!f.subject || r.subject === f.subject))
                                    .map((r) => r.sub_strand).filter(Boolean))];
  const items = list.data?.items || [];
  const picked = params.get("q") || "";
  const set = (patch: Partial<LibraryFilters>) => setF((x) => ({ ...x, ...patch, offset: 0 }));
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader eyebrow="Content" title="Library"
        description="Every question in one place: find it, then see its answer, its video, where each post of it is (posted, scheduled, booked), its comments and campaign, its boost and its numbers — and make its video, post it or boost it from here." />
      <Card>
        <Stack direction="row" gap="var(--s2)" wrap align="center">
          <Input value={typed} placeholder="Search the question's words…" style={{ flex: "1 1 16rem" }}
                 onChange={(e) => setTyped(e.target.value)} />
          <Select value={f.grade} style={{ width: "auto" }} onChange={(e) => set({ grade: e.target.value, subject: "", sub_strand: "" })}>
            <option value="">Every grade</option>
            {grades.map((g) => <option key={g} value={g}>{g.replace("grade-", "Grade ")}</option>)}
          </Select>
          <Select value={f.subject} style={{ width: "auto", maxWidth: "14rem" }} onChange={(e) => set({ subject: e.target.value, sub_strand: "" })}>
            <option value="">Every subject</option>
            {subjects.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
          <Select value={f.sub_strand} onChange={(e) => set({ sub_strand: e.target.value })} style={{ width: "auto", maxWidth: "16rem" }}>
            <option value="">Every sub-strand</option>
            {subStrands.map((s) => <option key={s} value={s}>{s}</option>)}
          </Select>
          <Select value={f.show} style={{ width: "auto" }} onChange={(e) => set({ show: e.target.value as LibraryFilters["show"] })}>
            <option value="all">All</option>
            <option value="video">With a video</option>
            <option value="no_video">Without a video</option>
            <option value="posted">Posted or scheduled</option>
            <option value="not_posted">Not posted yet</option>
            <option value="boosted">Boosted</option>
          </Select>
        </Stack>
        {list.data && (
          <p style={{ margin: "var(--s2) 0 0", fontSize: "var(--text-sm)", color: "var(--ink-3)" }}>
            {list.data.total.toLocaleString()} shown of {list.data.in_scope.toLocaleString()} questions ·{" "}
            {list.data.with_video.toLocaleString()} with a video · {list.data.posted.toLocaleString()} posted or scheduled
          </p>
        )}
      </Card>
      {list.error && <ErrorNotice error={list.error} />}
      <div className="library-grid" style={{ display: "grid", gridTemplateColumns: "minmax(18rem, 26rem) 1fr", gap: "var(--s4)", alignItems: "start" }}>
        <Card title="Questions">
          {!list.data ? <LoadingBlock rows={6} label="Loading the questions" /> : (
            <div style={{ display: "grid", gap: 4 }}>
              {items.length === 0 && <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>No question matches.</span>}
              {items.map((q) => <Row key={q.question_id} q={q} on={q.question_id === picked}
                                     onPick={() => setParams({ q: q.question_id })} />)}
              <Stack direction="row" gap="var(--s2)" align="center" style={{ marginTop: "var(--s2)" }}>
                <Button size="sm" variant="ghost" disabled={f.offset === 0}
                        onClick={() => setF((x) => ({ ...x, offset: Math.max(0, x.offset - 40) }))}>← Previous</Button>
                <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)", flex: 1, textAlign: "center" }}>
                  {list.data.total ? `${f.offset + 1}–${Math.min(f.offset + 40, list.data.total)} of ${list.data.total}` : ""}
                </span>
                <Button size="sm" variant="ghost" disabled={f.offset + 40 >= list.data.total}
                        onClick={() => setF((x) => ({ ...x, offset: x.offset + 40 }))}>Next →</Button>
              </Stack>
            </div>
          )}
        </Card>
        {picked ? <Detail id={picked} /> : (
          <Card><p style={{ margin: 0, color: "var(--ink-3)" }}>Pick a question to see everything about it.</p></Card>
        )}
      </div>
      <style>{`@media (max-width: 900px) { .library-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}

function Row({ q, on, onPick }: { q: LibraryItem; on: boolean; onPick: () => void }) {
  const [word, tone] = q.post ? postState(q.post) : ["Not booked", "neutral" as Tone];
  return (
    <button onClick={onPick}
            style={{ display: "grid", gridTemplateColumns: "56px 1fr", gap: 10, textAlign: "left", padding: 8, cursor: "pointer",
                     font: "inherit", color: "var(--ink)", borderRadius: "var(--radius)", alignItems: "center",
                     border: `1px solid ${on ? "var(--accent)" : "var(--line-2)"}`,
                     background: on ? "var(--accent-wash, rgba(15,118,110,.08))" : "transparent" }}>
      <span style={{ width: 56, height: 72, borderRadius: 6, overflow: "hidden", background: "var(--line-2)", display: "grid",
                     placeItems: "center", fontSize: 18 }}>
        {q.video?.thumbnail_url ? <img src={q.video.thumbnail_url} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          : q.video ? "🎬" : "—"}
      </span>
      <span style={{ display: "grid", gap: 4, minWidth: 0 }}>
        <span style={{ fontSize: "var(--text-sm)", overflow: "hidden", display: "-webkit-box", WebkitLineClamp: 2,
                       WebkitBoxOrient: "vertical" }}><MathText text={q.question_text} /></span>
        <span style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          <Badge tone={tone}>{word}</Badge>
          {q.post?.views ? <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{q.post.views} views · {q.post.comments ?? 0} comments</span> : null}
        </span>
        <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {[q.subject, q.sub_strand].filter(Boolean).join(" · ")}
        </span>
      </span>
    </button>
  );
}

function Detail({ id }: { id: string }) {
  const one = useLibraryQuestion(id);
  const make = useMakeSocial();
  const post = usePostQuestion();
  const toast = useToast();
  const q = one.data;
  if (one.error) return <ErrorNotice error={one.error} />;
  if (!q) return <Card><LoadingBlock rows={6} label="Loading the question" /></Card>;
  const cv = q.current_video || { status: "none" };
  const shown = cv.url || q.videos.find((v) => v.kind === "social")?.url || q.videos[0]?.url;
  const out = q.posts.some((p) => p.handed_at);
  async function makeVideo(fresh: boolean) {
    try { await make.mutateAsync({ questionId: id, fresh }); toast("Its video is being made — this page updates when it is ready.", "ok"); one.refetch(); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not make its video.", "danger"); }
  }
  async function postNow() {
    try {
      const r = await post.mutateAsync({ question_id: id, share: "feed" });
      toast(String(r?.error || r?.message || "Sent to the poster — it goes out in a minute or two."), r?.error ? (r?.making ? "info" : "danger") : "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not post it.", "danger"); }
  }
  return (
    <div style={{ display: "grid", gap: "var(--s3)" }}>
      <Card title="Question">
        <div style={{ display: "grid", gap: "var(--s2)" }}>
          <div style={{ fontSize: "var(--text-md, 1.05rem)" }}><MathText text={q.question_text} /></div>
          {q.options.length > 0 && (
            <ol type="A" style={{ margin: 0, paddingLeft: "1.4rem", display: "grid", gap: 2 }}>
              {q.options.map((o) => (
                <li key={o.id} style={{ fontWeight: o.is_correct ? 600 : 400, color: o.is_correct ? "var(--ok, #16a34a)" : undefined }}>
                  <MathText text={o.text} />{o.is_correct ? " ✓" : ""}
                </li>
              ))}
            </ol>
          )}
          {!q.options.length && q.answer ? <div><b>Answer: </b><MathText text={typeof q.answer === "string" ? q.answer : JSON.stringify(q.answer)} /></div> : null}
          {q.explanation && <details><summary style={{ cursor: "pointer" }}>Working</summary><MathText text={q.explanation} /></details>}
          <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
            {[q.grade?.replace("grade-", "Grade "), q.subject, q.strand, q.sub_strand].filter(Boolean).join(" · ")}
            {q.has_figure ? " · has a figure" : ""} · {q.status} · <code>{q.question_id}</code>
          </span>
        </div>
      </Card>

      <Card title="Video"
            actions={<Stack direction="row" gap="var(--s2)">
              <Button size="sm" variant="ghost" disabled={make.isPending || ["queued", "running"].includes(cv.status)}
                      onClick={() => makeVideo(cv.status === "ready")}>{cv.status === "ready" ? "Make again" : "Make video now"}</Button>
              {q.staff && <Button size="sm" variant="primary" disabled={post.isPending || out}
                                  title={out ? "Already posted or scheduled — it would go out twice" : "Live on Facebook now"}
                                  onClick={postNow}>Post now</Button>}
            </Stack>}>
        <div style={{ display: "grid", gridTemplateColumns: shown ? "minmax(9rem, 14rem) 1fr" : "1fr", gap: "var(--s3)", alignItems: "start" }}>
          {shown && <video src={shown} controls preload="metadata" poster={cv.thumbnail_url || undefined}
                           style={{ width: "100%", borderRadius: 8, background: "#000", aspectRatio: "9 / 16" }} />}
          <div style={{ display: "grid", gap: 6, fontSize: "var(--text-sm)" }}>
            <Stack direction="row" gap="var(--s2)" wrap>
              <Badge tone={VIDEO_TONE[cv.status] || "neutral"}>{VIDEO_WORD[cv.status] || cv.status}</Badge>
              {cv.teacher ? <Badge tone="neutral">{cv.teacher} teacher</Badge> : null}
              {cv.marketing ? <Badge tone="info">with marketing</Badge> : null}
              {cv.older ? <Badge tone="warn" title="Settings → Post older videos while new ones are made">older video — posts with it while the new one is made</Badge> : null}
            </Stack>
            {cv.status === "none" && q.videos.length > 0 && (
              <span style={{ color: "var(--ink-3)" }}>An older video exists (shown), made before the current settings — it is made again before it is posted.</span>
            )}
            {cv.error && <span style={{ color: "var(--danger, #dc2626)" }}>{cv.error}</span>}
            {q.videos.length > 0 && (
              <div style={{ display: "grid", gap: 2 }}>
                <b style={{ fontSize: "var(--text-xs)" }}>Made</b>
                {q.videos.map((v) => (
                  <a key={v.url} href={v.url} target="_blank" rel="noreferrer" style={{ fontSize: "var(--text-xs)" }}>
                    {v.kind === "social" ? "Social reel" : "Lesson"} · {when(v.made_at)}
                  </a>
                ))}
              </div>
            )}
          </div>
        </div>
      </Card>

      {q.staff && <Cards q={q} />}

      {q.staff && (
        <Card title={`Posts (${q.posts.length})`}>
          {q.posts.length === 0 ? (
            <p style={{ margin: 0, color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>Not booked or posted yet. Post now puts it out live; Auto-book books it in turn.</p>
          ) : <div style={{ display: "grid", gap: "var(--s3)" }}>{q.posts.map((p) => <PostBox key={p.post_id} p={p} />)}</div>}
          {q.earlier_posts.length > 0 && (
            <details style={{ marginTop: "var(--s3)", fontSize: "var(--text-sm)" }}>
              <summary style={{ cursor: "pointer" }}>Earlier posts of it ({q.earlier_posts.length}) — before it was posted again</summary>
              {q.earlier_posts.map((e) => (
                <div key={`${e.post_id}${e.archived_at}`} style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)", marginTop: 4 }}>
                  {e.platform} · {e.status} · {when(e.posted_at)} · {e.views} views · {e.comments} comments{" "}
                  {e.url && <a href={e.url} target="_blank" rel="noreferrer">open</a>}
                </div>
              ))}
            </details>
          )}
        </Card>
      )}
    </div>
  );
}

const CARD_STEPS: [string, string][] = [["teaser", "A question is coming"], ["question", "The question"],
                                        ["kicd", "KICD design page"], ["answer", "The answer"]];

/** Its photo cards in series order — each can go out now (to the feed or to groups),
 *  or the whole series from now, in order, a posting gap apart. */
function Cards({ q }: { q: LibraryQuestion }) {
  const post = usePostQuestion();
  const toast = useToast();
  const [share, setShare] = React.useState<"feed" | "groups">("feed");
  const out = new Set(q.posts.filter((p) => p.format === "photo" && p.handed_at).map((p) => p.step || ""));
  async function go(what: "teaser" | "question" | "kicd" | "answer" | "series") {
    try {
      const r = await post.mutateAsync({ question_id: q.question_id, what, share });
      toast(String(r?.error || r?.message || "Sent to the poster — it goes out in a minute or two."), r?.error ? "danger" : "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not post it.", "danger"); }
  }
  return (
    <Card title="Cards (photo posts)"
          actions={<Stack direction="row" gap="var(--s2)" align="center">
            <Select value={share} style={{ width: "auto" }} onChange={(e) => setShare(e.target.value as "feed" | "groups")}>
              <option value="feed">To the feed</option>
              <option value="groups">Feed + next groups</option>
            </Select>
            <Button size="sm" variant="primary" disabled={post.isPending} onClick={() => go("series")}
                    title="Each card, then the video — now, one after the other (the Mac makes any card not made yet)">Post the series now</Button>
          </Stack>}>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(8.5rem, 1fr))", gap: "var(--s2)" }}>
        {CARD_STEPS.map(([step, title]) => {
          const c = q.cards?.[step];
          return (
            <div key={step} style={{ display: "grid", gap: 6, fontSize: "var(--text-xs)" }}>
              <div style={{ aspectRatio: "4 / 5", borderRadius: 8, overflow: "hidden", background: "var(--line-2)", display: "grid", placeItems: "center" }}>
                {c?.url ? <a href={c.url} target="_blank" rel="noreferrer"><img src={c.url} alt={title} style={{ width: "100%", height: "100%", objectFit: "cover" }} /></a>
                  : <span style={{ color: "var(--ink-3)", padding: 8, textAlign: "center" }}>Made when it is posted</span>}
              </div>
              <b>{title}</b>
              <Button size="sm" variant="ghost" disabled={post.isPending || out.has(step)}
                      title={out.has(step) ? "Posted already" : "This card, live on Facebook now"}
                      onClick={() => go(step as "teaser" | "question" | "kicd" | "answer")}>{out.has(step) ? "Posted" : "Post now"}</Button>
            </div>
          );
        })}
      </div>
      <p style={{ margin: "var(--s2) 0 0", fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
        Auto-book also books a series like this before each day's first reels (Settings → Auto-post: photos a day, 4 per series).
        The question card and the KICD page also go in each reel's first comments.
      </p>
    </Card>
  );
}

function PostBox({ p }: { p: LibraryPost }) {
  const [word, tone] = postState(p);
  const boost = useBoostPost();
  const toast = useToast();
  const [daily, setDaily] = React.useState(p.boost_daily_ksh || 200);
  const [days, setDays] = React.useState(p.boost_days || 5);
  const ours = 4 + (p.campaign?.comment?.ok || 0);
  const thread: Record<string, string> = { pending: "first comments waiting", part: "answer comment waiting", done: "thread done",
                                           complete: "thread done", boost: "extra comments going", failed: "thread failed", "": "no comments yet" };
  async function doBoost() {
    try {
      const r = await boost.mutateAsync({ post_id: p.post_id, daily_ksh: daily, days, again: Boolean(p.boost_state) });
      toast(String(r?.message || r?.error || `Boost sent — KSh ${daily * days} in all.`), r?.error ? "danger" : "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not boost it.", "danger"); }
  }
  return (
    <div style={{ border: "1px solid var(--line-2)", borderRadius: "var(--radius)", padding: "var(--s3)", display: "grid", gap: 8,
                  fontSize: "var(--text-sm)" }}>
      <Stack direction="row" gap="var(--s2)" wrap align="center">
        <b style={{ textTransform: "capitalize" }}>{p.platform}</b>
        {p.format === "photo" && <Badge tone="neutral">card: {p.step || "photo"}</Badge>}
        <Badge tone={tone}>{word}</Badge>
        {p.marketing && <Badge tone="info">marketing</Badge>}
        {p.boost_state && <Badge tone={p.boost_state === "failed" ? "danger" : "warn"}>boost: {p.boost_state}</Badge>}
        <span style={{ flex: 1 }} />
        {p.url && <a href={p.url} target="_blank" rel="noreferrer">Open on {p.platform} ↗</a>}
      </Stack>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(7rem, 1fr))", gap: 6 }}>
        {[["Views", p.views], ["Reactions", p.likes], ["Comments", p.comments], ["Shares", p.shares]].map(([k, v]) => (
          <div key={String(k)} style={{ background: "var(--line-2)", borderRadius: 6, padding: "6px 8px" }}>
            <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{k}</div><b>{Number(v || 0).toLocaleString()}</b>
          </div>
        ))}
      </div>
      <div style={{ color: "var(--ink-2)" }}>
        💬 Our comments: <b>{ours}</b> (4 in the thread + {p.campaign?.comment?.ok || 0} campaign) · {thread[p.comments_state] ?? p.comments_state}
        {p.campaign_done ? " · campaign done" : ""}{p.campaign?.share?.ok ? ` · shared to groups ${p.campaign.share.ok}×` : ""}
        {p.comments_next_at && future(p.comments_next_at) ? ` · next at ${when(p.comments_next_at)}` : ""}
      </div>
      {(p.groups || []).length > 0 && <div style={{ color: "var(--ink-3)" }}>Groups: {p.groups.join(", ")}</div>}
      {p.last_error && <div style={{ color: "var(--danger, #dc2626)" }}>Posting: {p.last_error}</div>}
      {p.comments_error && <div style={{ color: "var(--warn, #b45309)" }}>Comments: {p.comments_error}</div>}
      {p.boost_error && <div style={{ color: "var(--danger, #dc2626)" }}>Boost: {p.boost_error}</div>}
      {p.daily.length > 0 && (
        <details>
          <summary style={{ cursor: "pointer" }}>Day by day ({p.daily.length})</summary>
          <table style={{ width: "100%", fontSize: "var(--text-xs)", borderCollapse: "collapse", marginTop: 4 }}>
            <thead><tr>{["Day", "Views", "Reactions", "Comments", "Shares"].map((h) => <th key={h} style={{ textAlign: "left", padding: 2 }}>{h}</th>)}</tr></thead>
            <tbody>{p.daily.map((d) => (
              <tr key={d.day}><td style={{ padding: 2 }}>{d.day}</td><td>{d.views}</td><td>{d.reactions}</td><td>{d.comments}</td><td>{d.shares}</td></tr>
            ))}</tbody>
          </table>
        </details>
      )}
      {p.platform === "facebook" && p.url && (
        <Stack direction="row" gap="var(--s2)" wrap align="center">
          <span style={{ color: "var(--ink-3)" }}>Boost: KSh</span>
          <Input type="number" min={50} max={5000} value={daily} style={{ width: 80 }}
                 onChange={(e) => setDaily(Math.max(50, Math.min(5000, Number(e.target.value) || 200)))} />
          <span style={{ color: "var(--ink-3)" }}>a day ×</span>
          <Input type="number" min={1} max={30} value={days} style={{ width: 60 }}
                 onChange={(e) => setDays(Math.max(1, Math.min(30, Number(e.target.value) || 5)))} />
          <span style={{ color: "var(--ink-3)" }}>days = KSh {(daily * days).toLocaleString()}</span>
          <Button size="sm" variant="ghost" disabled={boost.isPending || p.boost_state === "queued"} onClick={doBoost}>
            {p.boost_state ? "Boost again" : "Boost"}
          </Button>
        </Stack>
      )}
      <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
        {p.scheduled_for ? `Booked for ${when(p.scheduled_for)}` : ""}{p.created_by ? ` · by ${p.created_by}` : ""}
        {p.attempts ? ` · ${p.attempts} attempt(s)` : ""}{p.last_attempt_at ? ` · last tried ${when(p.last_attempt_at)}` : ""}
        {p.teacher ? ` · ${p.teacher} teacher` : ""} · <code>{p.post_id}</code>
      </span>
    </div>
  );
}
