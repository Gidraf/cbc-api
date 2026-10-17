import React from "react";
import { Badge, Button, Card, Input, Select, Stack, useToast } from "../ui/components";
import { type MonthDay, type MonthPlan, type MonthView, useAutoBook, useAutoBookNow, useBookMonth, useLessonsResume,
         useSaveAutoBook, useSetLivePerDay, useSocialMonth, useTeacherNow } from "../lib/queries";
import { useAuth } from "../lib/auth";

const PLATFORMS: [string, string][] = [["facebook", "Facebook"], ["tiktok", "TikTok"], ["instagram", "Instagram"],
  ["youtube", "YouTube"], ["linkedin", "LinkedIn"]];
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const COLOR = { posted: "var(--ok)", on_platform: "var(--info)", booked: "var(--warn)", add: "var(--accent)" };

type Prefs = { perDay: number; gapMin: number; gapMax: number; platforms: string[]; readyOnly: boolean };
const DEFAULTS: Prefs = { perDay: 10, gapMin: 30, gapMax: 60, platforms: ["facebook"], readyOnly: false };

function loadPrefs(): Prefs {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("cbc_month_prefs") || "{}") }; } catch { return DEFAULTS; }
}

const monthName = (y: number, m: number) => new Date(y, m - 1, 15).toLocaleDateString(undefined, { month: "long", year: "numeric" });
const dayName = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
const short = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

/** Book a month for the poster: the month as a calendar, the room each day
 *  has, a preview of what booking adds, then one press to book it. */
export function MonthPlanner({ grade, subject, subStrand }: { grade: string; subject: string; subStrand: string }) {
  const toast = useToast();
  const now = new Date();
  const [ym, setYm] = React.useState<[number, number]>([now.getFullYear(), now.getMonth() + 1]);
  const [prefs, setPrefsState] = React.useState<Prefs>(loadPrefs);
  const setPrefs = (p: Partial<Prefs>) => setPrefsState((old) => {
    const next = { ...old, ...p };
    try { localStorage.setItem("cbc_month_prefs", JSON.stringify(next)); } catch { /* private window */ }
    return next;
  });
  const [wholeSubject, setWholeSubject] = React.useState(true);
  const [plan, setPlan] = React.useState<MonthPlan | null>(null);
  const [picked, setPicked] = React.useState<string>("");
  const month = useSocialMonth(ym[0], ym[1], prefs.perDay, prefs.platforms);
  const book = useBookMonth();
  const live = useSetLivePerDay();
  React.useEffect(() => { setPlan(null); setPicked(""); }, [ym[0], ym[1], prefs.perDay, prefs.gapMin, prefs.gapMax, prefs.platforms.join(","), prefs.readyOnly]);

  const v = month.data;
  const adds = Object.fromEntries((plan?.days || []).map((d) => [d.date, d]));
  const shift = (n: number) => setYm(([y, m]) => {
    const t = new Date(y, m - 1 + n, 1);
    return [t.getFullYear(), t.getMonth() + 1];
  });
  const isThisMonth = ym[0] === now.getFullYear() && ym[1] === now.getMonth() + 1;
  const maxAhead = (ym[0] - now.getFullYear()) * 12 + (ym[1] - now.getMonth() - 1) >= 12;
  const scope = [grade ? grade.replace("grade-", "Grade ") : "", subject, wholeSubject || !subStrand ? "all topics" : subStrand].filter(Boolean).join(" · ");

  async function go(dry: boolean) {
    if (!subject || !grade) return toast("Choose a grade and subject above first.", "info");
    try {
      const out = await book.mutateAsync({ grade, subject, sub_strand: wholeSubject ? "" : subStrand, year: ym[0], month: ym[1],
        per_day: prefs.perDay, gap_min: prefs.gapMin, gap_max: Math.max(prefs.gapMin, prefs.gapMax), platforms: prefs.platforms,
        ready_only: prefs.readyOnly, dry });
      if (dry) setPlan(out);
      else {
        setPlan(null);
        month.refetch();
        toast(out.posts ? `Booked ${out.posts} posts in ${monthName(ym[0], ym[1])}${out.to_render ? ` — ${out.to_render} videos queued to be made` : ""}.`
                        : out.notes[0] || "Nothing to add.", out.posts ? "ok" : "info");
      }
    } catch (err) { toast(err instanceof Error ? err.message : "Could not book.", "danger"); }
  }

  // Monday-first grid: blanks before the 1st.
  const lead = v ? (new Date(`${v.days[0].date}T12:00:00`).getDay() + 6) % 7 : 0;
  const pickedDay = v?.days.find((d) => d.date === picked);
  const totals = v ? v.days.reduce((a, d) => ({ booked: a.booked + d.booked, on: a.on + d.on_platform, posted: a.posted + d.posted }),
                                    { booked: 0, on: 0, posted: 0 }) : null;

  return (
    <Card title="🗓 Book a month"
          actions={<Stack direction="row" gap="4px" align="center">
            <Button size="sm" variant="ghost" aria-label="Previous month" disabled={isThisMonth} onClick={() => shift(-1)}>‹</Button>
            <strong style={{ minWidth: 130, textAlign: "center" }}>{monthName(ym[0], ym[1])}</strong>
            <Button size="sm" variant="ghost" aria-label="Next month" disabled={maxAhead} onClick={() => shift(1)}>›</Button>
          </Stack>}>
      <AutoBook grade={grade} subject={subject} onBooked={() => month.refetch()} />
      <p style={{ margin: "0 0 var(--s3)", color: "var(--ink-3)", fontSize: "var(--text-sm)" }}>
        Or book by hand: pick how many videos a day and how far apart; the calendar shows the room each day has. Booking fills only that room.
        The poster hands each post to Facebook's own scheduler once it is within {v ? "its 29-day window" : "29 days"} — so
        Facebook publishes on time even with the Mac off.
      </p>

      <Stack direction="row" gap="var(--s3)" wrap align="end">
        <label style={lbl}>Videos a day
          <Input type="number" min={1} max={30} value={prefs.perDay} onChange={(e) => setPrefs({ perDay: Math.max(1, Math.min(30, Number(e.target.value) || 1)) })} style={{ width: 80 }} />
        </label>
        <label style={lbl}>Apart (minutes)
          <span style={{ display: "flex", gap: 4, alignItems: "center" }}>
            <Input type="number" min={5} max={240} value={prefs.gapMin} onChange={(e) => setPrefs({ gapMin: Math.max(5, Number(e.target.value) || 30) })} style={{ width: 70 }} />
            to
            <Input type="number" min={5} max={480} value={prefs.gapMax} onChange={(e) => setPrefs({ gapMax: Math.max(5, Number(e.target.value) || 60) })} style={{ width: 70 }} />
          </span>
        </label>
        <div style={lbl}>Platforms
          <span style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {PLATFORMS.map(([id, name]) => {
              const on = prefs.platforms.includes(id);
              return (
                <button key={id} type="button" aria-pressed={on}
                        onClick={() => setPrefs({ platforms: on ? prefs.platforms.filter((p) => p !== id) : [...prefs.platforms, id] })}
                        style={{ padding: "4px 10px", borderRadius: 999, cursor: "pointer", fontSize: "var(--text-xs)",
                                 border: `1px solid ${on ? "var(--accent)" : "var(--line)"}`, background: on ? "var(--accent-wash)" : "transparent",
                                 color: "var(--ink)", fontWeight: on ? 650 : 500 }}>{name}</button>
              );
            })}
          </span>
        </div>
        <label style={{ ...lbl, flexDirection: "row", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={prefs.readyOnly} onChange={() => setPrefs({ readyOnly: !prefs.readyOnly })} />Only videos already made
        </label>
        {subStrand && (
          <label style={{ ...lbl, flexDirection: "row", alignItems: "center", gap: 6 }}>
            <input type="checkbox" checked={wholeSubject} onChange={() => setWholeSubject((x) => !x)} />Whole subject
          </label>
        )}
      </Stack>

      {v && totals && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: "var(--s2)", margin: "var(--s3) 0" }}>
          <Stat label="Days with room" value={v.open_days} hint={`${v.free} posts to fill at ${v.per_day} a day`} tone={v.open_days ? "warn" : "ok"} />
          <Stat label="Booked" value={totals.booked} hint="waiting for their time" />
          <Stat label="On Facebook" value={totals.on} hint={`scheduled there · holds to ${short(v.facebook_until)}`} />
          <Stat label="Posted" value={totals.posted} hint="this month" />
        </div>
      )}

      {month.isLoading && <p style={{ color: "var(--ink-3)" }}>Loading the month…</p>}
      {v && (
        <>
          <div role="grid" aria-label={`Bookings in ${monthName(ym[0], ym[1])}`}
               style={{ display: "grid", gridTemplateColumns: "repeat(7, minmax(0, 1fr))", gap: 4 }}>
            {WEEKDAYS.map((w) => <div key={w} style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)", textAlign: "center" }}>{w}</div>)}
            {Array.from({ length: lead }).map((_, i) => <div key={`b${i}`} />)}
            {v.days.map((d) => <DayCell key={d.date} day={d} perDay={v.per_day * v.platforms.length} add={adds[d.date]?.add ? adds[d.date].add * v.platforms.length : 0}
                                        today={d.date === v.today} picked={picked === d.date} onPick={() => setPicked(picked === d.date ? "" : d.date)} />)}
          </div>
          <Legend />
        </>
      )}

      {pickedDay && <DayDetail day={pickedDay} add={adds[pickedDay.date]?.times || []} />}

      <div style={{ borderTop: "1px solid var(--line)", marginTop: "var(--s3)", paddingTop: "var(--s3)", display: "grid", gap: "var(--s2)" }}>
        <Stack direction="row" gap="var(--s2)" wrap align="center">
          <span style={{ fontSize: "var(--text-sm)", flex: 1, minWidth: 220 }}>
            {grade && subject ? <>From <strong>{scope}</strong></> : <span style={{ color: "var(--warn)" }}>Choose a grade and subject above to book.</span>}
          </span>
          <Button variant="ghost" disabled={book.isPending || !v?.free || !prefs.platforms.length || !grade} onClick={() => go(true)}>
            {book.isPending && !plan ? "Working…" : "Preview"}</Button>
          <Button variant="primary" disabled={book.isPending || !v?.free || !prefs.platforms.length || !grade} onClick={() => go(false)}>
            {plan ? `Book these ${plan.posts} posts` : v?.free ? `Book ${v.free} open slots` : "Month is full"}</Button>
        </Stack>
        {plan && (
          <div role="status" style={{ fontSize: "var(--text-sm)", display: "grid", gap: 4 }}>
            <span><strong>Preview:</strong> {plan.posts} posts on {plan.days.length} days
              {plan.first_day ? ` (${short(plan.first_day)} – ${short(plan.last_day || plan.first_day)})` : ""} ·{" "}
              {plan.ready} videos made{plan.to_render ? `, ${plan.to_render} to make (queued when you book, soonest first)` : ""}.
              Days to be added are marked <span style={{ color: COLOR.add, fontWeight: 650 }}>+N</span>; tap a day for its times.</span>
            {plan.notes.map((n) => <span key={n} style={{ color: "var(--warn)" }}>{n}</span>)}
          </div>
        )}
        {v && (
          <Stack direction="row" gap="var(--s2)" wrap align="center" style={{ fontSize: "var(--text-sm)" }}>
            <span>⚡ Also post live when the Mac is on:</span>
            <Select value={String(v.rules.live_per_day)} disabled={live.isPending} style={{ width: "auto" }}
                    onChange={async (e) => {
                      try { await live.mutateAsync(Number(e.target.value)); month.refetch(); toast("Saved.", "ok"); }
                      catch (err) { toast(err instanceof Error ? err.message : "Could not save.", "danger"); }
                    }}>
              {[0, 2, 5, 10, 15, 20].map((n) => <option key={n} value={n}>{n ? `${n} a day` : "off"}</option>)}
            </Select>
            <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
              finished videos no booking uses, on Facebook, in posting hours ({v.rules.hours.start}–{v.rules.hours.end}),
              at least {v.rules.min_gap_minutes} min after the last post.
            </span>
          </Stack>
        )}
        {v && <TeacherSwitch view={v} onDone={() => month.refetch()} />}
      </div>
    </Card>
  );
}

/** Auto-book: the calendar keeps itself full with new questions. */
function AutoBook({ grade, subject, onBooked }: { grade: string; subject: string; onBooked: () => void }) {
  const state = useAutoBook();
  const save = useSaveAutoBook();
  const now = useAutoBookNow();
  const toast = useToast();
  const s = state.data;
  const [perDay, setPerDay] = React.useState(10);
  const [days, setDays] = React.useState(30);
  const [scopes, setScopes] = React.useState<string[]>([]);
  React.useEffect(() => { if (s) { setPerDay(s.per_day); setDays(s.days); setScopes(s.scopes); } }, [s?.per_day, s?.days, s?.scopes.join(",")]);
  if (!s) return null;
  const here = grade && subject ? `${grade}|${subject}` : "";
  const shown = scopes.length ? scopes : s.booked_before;
  const label = (x: string) => { const [g, sub] = x.split("|"); return `${g.replace("grade-", "Grade ")} · ${sub}`; };
  async function apply(enabled: boolean, next = scopes) {
    try {
      const out = await save.mutateAsync({ enabled, per_day: perDay, days, scopes: next });
      onBooked();
      toast(enabled ? `Auto-book on${out.booked.posts ? ` — ${out.booked.posts} posts booked now` : ""}. It tops up every two hours.` : "Auto-book off.", "ok");
    } catch (err) { toast(err instanceof Error ? err.message : "Could not save.", "danger"); }
  }
  return (
    <div style={{ border: `1px solid ${s.enabled ? "var(--ok)" : "var(--line)"}`, background: s.enabled ? "var(--ok-wash)" : "transparent",
                  borderRadius: "var(--radius)", padding: "var(--s3)", marginBottom: "var(--s3)", display: "grid", gap: "var(--s2)", fontSize: "var(--text-sm)" }}>
      <Stack direction="row" gap="var(--s2)" wrap align="center">
        <strong>⚙️ Auto-book</strong>
        <Badge tone={s.enabled ? "ok" : "neutral"}>{s.enabled ? "on — keeps the calendar full" : "off"}</Badge>
        <span style={{ flex: 1 }} />
        <label style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
          <Input type="number" min={1} max={30} value={perDay} onChange={(e) => setPerDay(Math.max(1, Math.min(30, Number(e.target.value) || 10)))} style={{ width: 64 }} /> a day,</label>
        <label style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
          <Input type="number" min={1} max={62} value={days} onChange={(e) => setDays(Math.max(1, Math.min(62, Number(e.target.value) || 30)))} style={{ width: 64 }} /> days ahead</label>
        <Button size="sm" variant={s.enabled ? "ghost" : "primary"} loading={save.isPending} onClick={() => apply(!s.enabled)}>
          {s.enabled ? "Turn off" : "Turn on"}</Button>
        {s.enabled && (perDay !== s.per_day || days !== s.days) && <Button size="sm" onClick={() => apply(true)}>Save</Button>}
        <Button size="sm" variant="ghost" loading={now.isPending}
                onClick={async () => { try { const out = await now.mutateAsync(); onBooked(); toast(out.posts ? `${out.posts} posts booked${out.to_render ? `, ${out.to_render} videos queued` : ""}.` : out.notes[0] || "Nothing to add.", out.posts ? "ok" : "info"); }
                                     catch (err) { toast(err instanceof Error ? err.message : "Could not book.", "danger"); } }}>Top up now</Button>
      </Stack>
      <Stack direction="row" gap="6px" wrap align="center">
        <span style={{ color: "var(--ink-3)" }}>From{scopes.length ? "" : " (booked before)"}:</span>
        {shown.map((x) => (
          <span key={x} style={{ display: "inline-flex", gap: 4, alignItems: "center", border: "1px solid var(--line)", borderRadius: 999, padding: "2px 4px 2px 10px" }}>
            {label(x)}
            {scopes.length > 0 && <button type="button" aria-label={`Remove ${label(x)}`} onClick={() => { const next = scopes.filter((y) => y !== x); setScopes(next); apply(s.enabled, next); }}
                                         style={{ border: 0, background: "transparent", cursor: "pointer", color: "var(--ink-3)" }}>✕</button>}
          </span>
        ))}
        {!shown.length && <span style={{ color: "var(--warn)" }}>nothing yet — add the subject chosen above</span>}
        {here && !scopes.includes(here) && (
          <Button size="sm" variant="ghost" onClick={() => { const next = [...(scopes.length ? scopes : s.booked_before), here].filter((x, i, a) => a.indexOf(x) === i); setScopes(next); apply(s.enabled, next); }}>
            + {label(here)}</Button>
        )}
      </Stack>
      <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>
        Every two hours the next {days} days are topped up to {perDay} a day with questions never posted — new ones as they
        reach the bank, subjects mixed. Their videos are queued at once (with the teacher, if it is on). No question is ever booked twice.
      </span>
    </div>
  );
}

/** Admins: render the booked posts' videos with the 3D teacher, first. */
function TeacherSwitch({ view, onDone }: { view: MonthView; onDone: () => void }) {
  const { role } = useAuth();
  const toast = useToast();
  const go = useTeacherNow();
  const resume = useLessonsResume();
  const [mode, setMode] = React.useState(view.rules.teacher === "off" ? "classroom" : view.rules.teacher);
  const [limit, setLimit] = React.useState(60);
  if (role !== "admin") return null;
  const on = view.rules.teacher !== "off";
  return (
    <Stack direction="row" gap="var(--s2)" wrap align="center" style={{ fontSize: "var(--text-sm)", borderTop: "1px dashed var(--line)", paddingTop: "var(--s2)" }}>
      <span>🎬 Teacher videos{on ? <> — <Badge tone="ok">on: {view.rules.teacher}</Badge></> : ""}</span>
      <Select value={mode} onChange={(e) => setMode(e.target.value as any)} style={{ width: "auto" }}>
        <option value="classroom">A class: any teacher, a new cast every video</option>
        <option value="alternate">Woman and man, half each</option>
        <option value="female">A woman teacher (young or older)</option>
        <option value="male">A man teacher (young or older)</option>
        <option value="female_young">Ms — young woman only</option>
        <option value="male_young">Mr — young man only</option>
        <option value="teacher_older_f">Mrs — older woman only</option>
        <option value="teacher_older_m">Mzee — older man only</option>
      </Select>
      <label style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>next
        <Input type="number" min={1} max={500} value={limit} onChange={(e) => setLimit(Math.max(1, Number(e.target.value) || 60))} style={{ width: 70 }} />
        booked videos</label>
      <Button size="sm" variant="primary" loading={go.isPending}
              onClick={async () => {
                try {
                  const out = await go.mutateAsync({ mode, limit, pause_lessons: true });
                  onDone();
                  toast(`Teacher on. ${out.queued} booked videos queued first${out.lessons_cancelled ? `; ${out.lessons_cancelled} lesson videos paused` : ""}.`, "ok");
                } catch (err) { toast(err instanceof Error ? err.message : "Could not start.", "danger"); }
              }}>Render them with the teacher now</Button>
      {view.rules.lessons_per_day === 0 && (
        <Button size="sm" variant="ghost" loading={resume.isPending}
                onClick={async () => { try { await resume.mutateAsync(200); onDone(); toast("Daily lesson videos back on: 200 a day.", "ok"); } catch (err) { toast(err instanceof Error ? err.message : "Could not.", "danger"); } }}>
          Lesson videos are paused — resume 200 a day</Button>
      )}
      <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)", flexBasis: "100%" }}>
        Pauses the daily lesson videos, then makes the booked posts' videos again with the teacher, the soonest post first.
        Until a new one is ready, the old video still posts. Posts already on Facebook keep the video Facebook has.
      </span>
    </Stack>
  );
}

function DayCell({ day, perDay, add, today, picked, onPick }: { day: MonthDay; perDay: number; add: number; today: boolean; picked: boolean; onPick: () => void }) {
  const held = day.posted + day.on_platform + day.booked;
  const n = Number(day.date.slice(8));
  const past = !day.bookable;
  const full = day.bookable && day.free === 0 && held > 0;
  const seg = (count: number, color: string, dashed = false) => count > 0 && (
    <span style={{ flex: count, background: dashed ? `repeating-linear-gradient(45deg, ${color}, ${color} 3px, transparent 3px, transparent 6px)` : color }} />
  );
  const label = `${dayName(day.date)}: ${held} of ${perDay}${add ? `, ${add} to add` : ""}${day.to_platform_on ? ` — goes to Facebook from ${short(day.to_platform_on)}` : ""}`;
  return (
    <button type="button" onClick={onPick} aria-label={label} title={label} aria-pressed={picked}
            style={{ textAlign: "left", padding: "6px 6px 5px", minHeight: 64, borderRadius: "var(--radius-sm)", cursor: "pointer",
                     display: "flex", flexDirection: "column", gap: 4, color: "var(--ink)", minWidth: 0,
                     background: picked ? "var(--accent-wash)" : past ? "var(--surface-2)" : "var(--surface)",
                     border: `1px solid ${picked ? "var(--accent)" : today ? "var(--ink-3)" : "var(--line)"}`, opacity: past && !held ? 0.55 : 1 }}>
      <span style={{ display: "flex", justifyContent: "space-between", gap: 2, fontSize: "var(--text-xs)" }}>
        <strong>{n}</strong>
        {add > 0 ? <span style={{ color: COLOR.add, fontWeight: 700 }}>+{add}</span>
          : full ? <span style={{ color: "var(--ok)" }} aria-hidden>✓</span>
          : day.to_platform_on && held ? <span aria-hidden title="Reaches Facebook later">⏳</span> : null}
      </span>
      <span style={{ display: "flex", height: 6, borderRadius: 3, overflow: "hidden", background: "var(--line-2)" }}>
        {seg(day.posted, COLOR.posted)}{seg(day.on_platform, COLOR.on_platform)}{seg(day.booked, COLOR.booked)}
        {seg(add, COLOR.add, true)}{seg(Math.max(0, perDay - held - add), "transparent")}
      </span>
      <span style={{ fontSize: 11, color: "var(--ink-3)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
        {held || add ? `${held + add}/${perDay}` : past ? "" : "open"}
      </span>
    </button>
  );
}

function DayDetail({ day, add }: { day: MonthDay; add: string[] }) {
  const STATE: Record<string, [string, "ok" | "info" | "warn" | "danger"]> = {
    posted: ["posted", "ok"], on_platform: ["on Facebook", "info"], booked: ["booked", "warn"], failed: ["gave up", "danger"] };
  return (
    <div style={{ marginTop: "var(--s3)", border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "var(--s3)", fontSize: "var(--text-sm)" }}>
      <strong>{dayName(day.date)}</strong>
      {day.to_platform_on && <span style={{ color: "var(--ink-3)" }}> · reaches Facebook's scheduler from {short(day.to_platform_on)}</span>}
      {day.posts.length === 0 && add.length === 0 && <p style={{ margin: "var(--s2) 0 0", color: "var(--ink-3)" }}>Nothing booked yet.</p>}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(170px, 1fr))", gap: 4, marginTop: "var(--s2)" }}>
        {day.posts.map((p, i) => (
          <span key={`p${i}`} style={{ display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontFamily: "var(--font-mono)" }}>{p.time}</span>
            <Badge tone={STATE[p.state]?.[1] || "neutral"}>{STATE[p.state]?.[0] || p.state}</Badge>
            {p.teacher && <span title={`With the ${p.teacher === "female" ? "woman" : "man"} teacher`}>🎓</span>}
            {p.platform !== "facebook" && <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{p.platform}</span>}
          </span>
        ))}
        {add.map((t, i) => {
          const [time, platform] = t.split(" ");
          return (
            <span key={`a${i}`} style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <span style={{ fontFamily: "var(--font-mono)" }}>{time}</span>
              <Badge tone="accent">to add</Badge>
              {platform !== "facebook" && <span style={{ color: "var(--ink-3)", fontSize: "var(--text-xs)" }}>{platform}</span>}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function Legend() {
  const item = (color: string, text: string, dashed = false) => (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span style={{ width: 12, height: 6, borderRadius: 3, display: "inline-block",
                     background: dashed ? `repeating-linear-gradient(45deg, ${color}, ${color} 3px, transparent 3px, transparent 6px)` : color }} />{text}
    </span>
  );
  return (
    <div style={{ display: "flex", gap: "var(--s3)", flexWrap: "wrap", fontSize: "var(--text-xs)", color: "var(--ink-3)", marginTop: "var(--s2)" }}>
      {item(COLOR.posted, "posted")}{item(COLOR.on_platform, "on Facebook")}{item(COLOR.booked, "booked")}{item(COLOR.add, "to add (preview)", true)}
      <span>⏳ reaches Facebook later</span>
    </div>
  );
}

function Stat({ label, value, hint, tone }: { label: string; value: number; hint: string; tone?: "ok" | "warn" }) {
  return (
    <div style={{ border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "8px 10px" }}>
      <div style={{ fontSize: "var(--text-xs)", color: "var(--ink-3)" }}>{label}</div>
      <div style={{ fontSize: "var(--text-xl)", fontWeight: 700, color: tone === "warn" ? "var(--warn)" : tone === "ok" ? "var(--ok)" : "var(--ink)" }}>{value}</div>
      <div style={{ fontSize: 11, color: "var(--ink-3)" }}>{hint}</div>
    </div>
  );
}

const lbl: React.CSSProperties = { fontSize: "var(--text-sm)", fontWeight: 550, display: "flex", flexDirection: "column", gap: 4 };
