import React from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, Card, Input, LoadingBlock, PageHeader, Stack, useToast } from "../ui/components";
import {
  useDeviceHistory, useDevices, useForgetDevice, useNameDevice, usePosterCommand, useSavePlatformSettings,
  type DeviceHelper, type DevicePoster,
} from "../lib/queries";
import { SetupCommands, WorkingHours } from "./PlayArcade";

const PLATFORMS: [string, string][] = [["facebook", "Facebook"], ["instagram", "Instagram"], ["linkedin", "LinkedIn"],
                                       ["tiktok", "TikTok"], ["youtube", "YouTube"]];
const JOBS: [string, string, string][] = [
  ["post", "Posting", "puts the booked videos out, and each post's own comments (choices, then the answer)"],
  ["comments", "Comment campaign", "comments under the posts to the floor and the top posts to the target; reads their insights"],
  ["likes", "Liking back", "likes the comments under your posts and a few posts of each person who commented"],
];
const POSTER_COUNTS: [string, string, string][] = [["posts", "Posts", "#2563eb"], ["comments", "Comments", "#16a34a"],
  ["shares", "Shares", "#9333ea"], ["likes", "Likes", "#db2777"], ["boosts", "Boosts", "#ea580c"], ["readings", "Readings", "#0891b2"],
  ["failures", "Failed", "#dc2626"]];
const RENDER_COUNTS: [string, string, string][] = [["made", "Videos made", "#2563eb"], ["failed", "Failed", "#dc2626"]];

type Selected = { kind: "poster"; d: DevicePoster } | { kind: "render"; d: DeviceHelper };

const ago = (iso: string) => {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  return s < 90 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} d ago`;
};
const dot = (on: boolean) => <span style={{ display: "inline-block", width: 9, height: 9, borderRadius: 5, background: on ? "#16a34a" : "#9ca3af", flex: "none" }} />;

/** Every Mac in one place: pick one to see its accounts, its jobs, its day by day, and to control it. */
export function Devices() {
  const devices = useDevices();
  const [params, setParams] = useSearchParams();
  const d = devices.data;
  const all: Selected[] = [...(d?.posters || []).map((p) => ({ kind: "poster" as const, d: p })),
                           ...(d?.helpers || []).map((h) => ({ kind: "render" as const, d: h }))];
  const key = (s: Selected) => `${s.kind}:${s.kind === "poster" ? s.d.poster_id : s.d.worker}`;
  const picked = all.find((s) => key(s) === params.get("d")) || all.find((s) => s.d.online) || all[0];
  const label = (s: Selected) => s.d.name || (s.kind === "poster" ? s.d.machine?.host || s.d.poster_id : s.d.worker.replace(/^mac-/, ""));
  return (
    <div style={{ display: "grid", gap: "var(--s4)" }}>
      <PageHeader eyebrow="Social" title="Devices"
        description="The Macs that post, comment and make videos. Pick one to see its accounts and its day by day, log it in or out of each platform, set its jobs, pause it, rename it, or remove it." />
      {!d ? <LoadingBlock rows={4} label="Loading the Macs" /> : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(14rem, 18rem) 1fr", gap: "var(--s4)", alignItems: "start" }}>
          <Card title={`Macs (${all.length})`}>
            <div style={{ display: "grid", gap: 4 }}>
              {all.length === 0 && <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>No Mac has checked in this week.</span>}
              {all.map((s) => {
                const on = picked && key(s) === key(picked);
                return (
                  <button key={key(s)} onClick={() => setParams({ d: key(s) })}
                          style={{ display: "grid", gap: 2, textAlign: "left", padding: "8px 10px", cursor: "pointer", font: "inherit",
                                   color: "var(--ink)", borderRadius: "var(--radius)", border: `1px solid ${on ? "var(--accent)" : "var(--line-2)"}`,
                                   background: on ? "var(--accent-wash, rgba(15,118,110,.08))" : "transparent" }}>
                    <span style={{ display: "flex", gap: 8, alignItems: "center" }}>{dot(s.d.online)}<b>{label(s)}</b></span>
                    <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>
                      {s.kind === "poster" ? "poster" : "render helper"} · {s.d.online ? "online" : `seen ${ago(s.d.seen_at)}`}
                      {s.kind === "poster" && Object.values(s.d.logins || {}).some((l) => !l.logged_in) ? " · ⚠ logged out" : ""}
                    </span>
                  </button>
                );
              })}
            </div>
            <div style={{ marginTop: "var(--s3)" }}><SetupCommands /></div>
          </Card>
          {picked ? (picked.kind === "poster" ? <PosterDetail p={picked.d} label={label(picked)} />
                                              : <HelperDetail h={picked.d} label={label(picked)} />) : <span />}
        </div>
      )}
    </div>
  );
}

/** The name, the state and the controls every Mac has. */
function Header({ id, kind, label, online, seenAt, sub, children }: {
  id: string; kind: "poster" | "render"; label: string; online: boolean; seenAt: string; sub: string; children?: React.ReactNode;
}) {
  const rename = useNameDevice();
  const forget = useForgetDevice();
  const toast = useToast();
  const [name, setName] = React.useState(label);
  React.useEffect(() => setName(label), [label]);
  return (
    <Card>
      <div style={{ display: "grid", gap: "var(--s2)" }}>
        <Stack direction="row" gap="var(--s2)" align="center" wrap>
          {dot(online)}
          <Input value={name} onChange={(e) => setName(e.target.value)} style={{ width: "16rem", fontWeight: 650 }} aria-label="This Mac's name" />
          {name !== label && (
            <Button size="sm" loading={rename.isPending} onClick={async () => {
              try { await rename.mutateAsync({ device: id, name }); toast("Renamed.", "ok"); }
              catch (err) { toast(err instanceof Error ? err.message : "Could not rename.", "danger"); } }}>Save name</Button>
          )}
          <Badge tone="neutral">{kind === "poster" ? "poster" : "render helper"}</Badge>
          <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>{online ? "online" : `offline · last seen ${ago(seenAt)}`}</span>
          <span style={{ flex: 1 }} />
          <Button size="sm" variant="ghost" style={{ color: "var(--danger)" }} onClick={async () => {
            if (!window.confirm(`Take ${label} off the list? It comes back if it checks in again — uninstall it to stop that.`)) return;
            try { await forget.mutateAsync({ device: id, kind }); toast("Taken off the list.", "ok"); }
            catch (err) { toast(err instanceof Error ? err.message : "Could not.", "danger"); } }}>Forget this Mac</Button>
        </Stack>
        <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{sub}</span>
        {children}
      </div>
    </Card>
  );
}

function PosterDetail({ p, label }: { p: DevicePoster; label: string }) {
  const command = usePosterCommand();
  const save = useSavePlatformSettings();
  const devices = useDevices();
  const toast = useToast();
  async function send(action: "login" | "logout" | "check" | "pause" | "resume" | "uninstall", platform = "", said = "") {
    try {
      const out = await command.mutateAsync({ action, platform, target: p.poster_id });
      toast(out?.message || out?.error || said || "Sent to the Mac.", out?.ok === false ? "danger" : "ok");
      devices.refetch();
    } catch (err) { toast(err instanceof Error ? err.message : "Could not reach that Mac.", "danger"); }
  }
  async function toggleJob(job: string) {
    const roles = Object.fromEntries((devices.data?.posters || []).map((m) => [m.poster_id, m.jobs]));
    const mine = new Set(roles[p.poster_id] || []);
    if (mine.has(job)) mine.delete(job); else mine.add(job);
    roles[p.poster_id] = [...mine];
    try { await save.mutateAsync({ poster_roles: JSON.stringify(roles) }); devices.refetch(); toast("Saved.", "ok"); }
    catch (err) { toast(err instanceof Error ? err.message : "Could not save.", "danger"); }
  }
  const off = !p.online;
  return (
    <div style={{ display: "grid", gap: "var(--s3)" }}>
      <Header id={p.poster_id} kind="poster" label={label} online={p.online} seenAt={p.seen_at}
              sub={[p.machine?.os, p.machine?.code ? `code of ${p.machine.code}` : "", p.browser ? `browser: ${p.browser}` : "", p.paused ? "⏸ paused" : ""].filter(Boolean).join(" · ")}>
        {p.busy && <span style={{ fontSize: "var(--text-sm)" }}>⏳ {p.busy}</span>}
        <Stack direction="row" gap="var(--s2)" wrap>
          <Button size="sm" disabled={off || command.isPending} onClick={() => send(p.paused ? "resume" : "pause")}>{p.paused ? "▶ Resume" : "⏸ Pause"}</Button>
          <Button size="sm" variant="ghost" disabled={off || command.isPending} onClick={() => send("check", "", "Checked.")}>Check every login</Button>
          <Button size="sm" variant="ghost" style={{ color: "var(--danger)" }} disabled={off || command.isPending} onClick={() => {
            if (window.confirm(`Remove the poster from ${label}? Its logins are kept; install it again with the one-line command.`)) send("uninstall");
          }}>Uninstall from this Mac</Button>
        </Stack>
        {off && <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>Offline: the buttons work once the Mac is on and the poster is running.</span>}
      </Header>

      <Card title="Accounts" description="Log in opens ordinary Chrome on this Mac at the platform's login: log in there (answer any code), then quit Chrome with Cmd+Q. Log out clears that platform from this Mac's poster.">
        <div style={{ display: "grid", gap: 6 }}>
          {PLATFORMS.map(([pl, title]) => {
            const l = p.logins?.[pl];
            return (
              <Stack key={pl} direction="row" gap="var(--s2)" align="center" wrap>
                <b style={{ width: "6.5rem" }}>{title}</b>
                {l ? <Badge tone={l.logged_in ? "ok" : "danger"}>{l.logged_in ? `logged in${l.account ? ` as ${l.account}` : ""}` : "logged out"}</Badge>
                   : <Badge tone="neutral">not set up</Badge>}
                <span style={{ flex: 1 }} />
                <Button size="sm" variant={l?.logged_in ? "ghost" : "secondary"} disabled={off || command.isPending} onClick={() => send("login", pl)}>
                  🔑 {l?.logged_in ? "Log in again" : l ? "Log in" : "Add this account"}</Button>
                <Button size="sm" variant="ghost" disabled={off || command.isPending || !l?.logged_in} onClick={() => {
                  if (window.confirm(`Log ${label} out of ${title}?`)) send("logout", pl);
                }}>Log out</Button>
                <Button size="sm" variant="ghost" disabled={off || command.isPending} onClick={() => send("check", pl, "Checked.")}>Check</Button>
              </Stack>
            );
          })}
        </div>
      </Card>

      <Card title="Jobs" description="Each job goes to the newest Mac that has it ticked; a Mac with none set does them all.">
        <div style={{ display: "grid", gap: 6 }}>
          {JOBS.map(([job, title, note]) => (
            <label key={job} style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: "var(--text-sm)" }}>
              <input type="checkbox" checked={p.jobs.includes(job)} disabled={save.isPending} onChange={() => toggleJob(job)} style={{ marginTop: 3 }} />
              <span><b>{title}</b>{p.doing.includes(job) ? <Badge tone="ok">doing it now</Badge> : null}<br />
                <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{note}</span></span>
            </label>
          ))}
        </div>
      </Card>

      <History id={p.poster_id} kind="poster" counts={POSTER_COUNTS} today={p.today} />
    </div>
  );
}

function HelperDetail({ h, label }: { h: DeviceHelper; label: string }) {
  return (
    <div style={{ display: "grid", gap: "var(--s3)" }}>
      <Header id={h.worker} kind="render" label={label} online={h.online} seenAt={h.seen_at}
              sub={[h.machine?.os, `${h.slots || "?"} videos at once`, `Manim ${h.manim ? "ready" : "not installed"}`].filter(Boolean).join(" · ")}>
        <span style={{ fontSize: "var(--text-sm)" }}>{h.online ? (h.resting ? `😴 Resting — ${h.resting}` : "🎬 Working") : "Offline"}</span>
        {h.jobs.map((j) => <span key={j.job_id} style={{ fontSize: "var(--text-sm)" }}>🎬 {j.question_id} — {j.stage} {Math.round(j.pct)}%</span>)}
      </Header>
      <Card title="Working hours" description="Every Mac that renders follows these (by its own clock); a video it has started is always finished.">
        <WorkingHours />
      </Card>
      <History id={h.worker} kind="render" counts={RENDER_COUNTS} today={h.today} />
    </div>
  );
}

/** A Mac's last two weeks, a bar per day for each kind of work. */
function History({ id, kind, counts, today }: { id: string; kind: "poster" | "render"; counts: [string, string, string][];
                                                today: Record<string, number | string> }) {
  const hist = useDeviceHistory(id, kind);
  const days = hist.data?.days || [];
  const total = (k: string) => days.reduce((a, d) => a + Number(d[k] || 0), 0);
  const shown = counts.filter(([k]) => total(k) > 0 || Number(today?.[k] || 0) > 0);
  return (
    <Card title="The last two weeks" description={`Today: ${counts.filter(([k]) => Number(today?.[k] || 0) > 0).map(([k, t]) => `${today[k]} ${t.toLowerCase()}`).join(" · ") || "nothing yet"}`}>
      {days.length === 0 ? <span style={{ color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>No days recorded yet — they fill in as the Mac works.</span> : (
        <div style={{ display: "grid", gap: "var(--s3)" }}>
          {shown.map(([k, title, colour]) => {
            const top = Math.max(1, ...days.map((d) => Number(d[k] || 0)));
            return (
              <div key={k}>
                <span style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{title} — {total(k)} in {days.length} day(s)</span>
                <div style={{ display: "flex", gap: 3, alignItems: "flex-end", height: 48 }}>
                  {days.map((d) => (
                    <div key={d.day} title={`${d.day}: ${Number(d[k] || 0)} ${title.toLowerCase()}`}
                         style={{ flex: 1, height: `${(100 * Number(d[k] || 0)) / top}%`, minHeight: 2, background: colour, borderRadius: 2, opacity: 0.85 }} />
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}
