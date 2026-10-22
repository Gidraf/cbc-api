"""Social posts: a question as a vertical video and the post that goes with it.

The whiteboard walkthrough, cut for TikTok, Reels, Shorts and WhatsApp
Status:

* 1080×1920, with the platforms' safe areas kept clear: nothing that
  matters in the top 120 px, the bottom 330 px or the right-hand 130 px
  where the app draws its buttons and caption.
* A hook — "Can you solve this?" — over the question as the hand writes
  it, then a countdown with a tick each second: pause and try.
* Captions burned in, a phrase at a time with the spoken word lit, for
  the people who scroll with the sound off.
* The solution without the wrong-option explanations: 20–40 seconds.
* An end card the hand writes: the brand, the handle, the call to follow.
* Music, if one has been uploaded, quietly under the voice.

Beside the video: a thumbnail (the question under the hook) and the post
text — the question, its options, the answer and the working the video
explains, then hashtags from the grade and the topic.

Brand, handle, website, the call to action, the countdown and extra
hashtags are console settings (group "Social").
"""
from __future__ import annotations

import copy
import hashlib
import html
import json
import logging
import re
from typing import Any

logger = logging.getLogger("cbc-social")

JOB_KIND = "social"
PREFIX = "social"
VERSION = "so1"


# ── the brand ────────────────────────────────────────────────────────────────

_SCIENCES = re.compile(r"chem|physic|biolog|integrated science|^science|science and technology|environmental", re.I)
# What CBC calls science at each level (KICD): the separate sciences only in Senior School.
_LEVEL_SCIENCE = {"Pre-Primary": "Environmental Activities", "Lower Primary": "Environmental Activities",
                  "Upper Primary": "Science and Technology", "Junior School": "Integrated Science"}


def subject_label(q: dict[str, Any] | None) -> str:
    """The subject as CBC names it for this question: by its grade — Integrated
    Science in Grades 7–9, Chemistry (or Physics, Biology) only in Senior School,
    Science and Technology in Grades 4–6 — or, with no grade (a lab mix, the
    API), by how hard the chemistry is: separating mixtures and the structure
    of an atom are Junior School work; bonding, balancing and reactions Senior."""
    q = q or {}
    link = q.get("curriculum") or {}
    subject = str(link.get("subject") or "").strip()
    if not subject or not _SCIENCES.search(subject):
        return subject
    from .grade_order import grade_level

    level = grade_level(str(link.get("grade") or ""))
    if level in _LEVEL_SCIENCE:
        return _LEVEL_SCIENCE[level]
    if level == "Senior School":
        return "Chemistry" if re.search(r"integrated|^science", subject, re.I) and q.get("chemistry") else subject
    chem = q.get("chemistry") if isinstance(q.get("chemistry"), dict) else {}
    hard = str((q.get("pedagogy") or {}).get("difficulty") or "").lower() in ("hard", "challenging", "advanced")
    if chem and not hard:
        junior = bool(chem.get("separate")) or (bool(chem.get("atom")) and not chem.get("focus") == "ion")
        return "Integrated Science" if junior else "Chemistry"
    return "Chemistry" if chem else subject


def brand_name(b: dict[str, Any], q: dict[str, Any] | None = None, subject: str = "") -> str:
    """The brand for a question's subject: Settings → Brand per subject
    ("Chemistry=CBC Chemistry; Biology=CBC Biology"), or else the brand with
    its subject word swapped ("CBC Maths" on a chemistry video: "CBC Chemistry")."""
    name = str(b.get("name") or "")
    subject = (subject or subject_label(q)).strip()
    if not subject:
        return name
    from . import platform_settings

    try:
        table = str(platform_settings.get("social_brand_by_subject", "") or "")
    except Exception:  # noqa: BLE001
        table = ""
    for part in re.split(r"[;\n]", table):
        key, _, value = part.partition("=")
        if key.strip() and value.strip() and key.strip().lower() == subject.lower():
            return value.strip()
    if re.search(r"\bmath", subject, re.I):
        return name
    return re.sub(r"\b(?:Mathematics|Maths|Math)\b", subject.title() if subject.islower() else subject, name)


def brand() -> dict[str, Any]:
    from . import platform_settings

    def get(key: str, default: Any = "") -> Any:
        try:
            return platform_settings.get(key, default)
        except Exception:  # noqa: BLE001
            return default

    name = str(get("social_brand_name", "") or get("paper_series_name", "") or "CBC Maths").strip()
    website = str(get("social_website", "") or "").strip()
    if not website:
        base = str(get("public_base_url", "") or "")
        website = re.sub(r"^https?://", "", base).rstrip("/")
    handle = str(get("social_handle", "") or "").strip()
    if handle and not handle.startswith("@"):
        handle = "@" + handle
    try:
        countdown = max(3, min(int(get("social_countdown_seconds", 3) or 3), 10))
    except (TypeError, ValueError):
        countdown = 3
    def colour(key: str, default: str) -> str:
        value = str(get(key, default) or default).strip()
        return value if re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", value) else default

    return {
        "hook": str(get("social_hook", "") or "Can you solve this?").strip(),
        "bg_from": colour("social_bg_from", "#2f4d8a"), "bg_to": colour("social_bg_to", "#141d36"),
        "accent": colour("social_accent", "#facc15"), "text": colour("social_text", "#ffffff"),
        "name": name, "handle": handle, "website": website,
        "cta": str(get("social_cta", "") or "Follow for a new question every day").strip(),
        "countdown": countdown,
        "hashtags": str(get("social_hashtags", "") or "").strip(),
        "logo_url": str(get("social_logo_url", "") or "").strip(),
        "music_url": str(get("social_music_url", "") or "").strip(),
        "teacher": _teacher_mode(),
        "cover": bool(get("social_cover", True)),
        "marketing": bool(get("social_marketing", True)),
    }


# The cover's looks: background from, to, and the headline's colour.
COVER_PALETTES = [("#ff006e", "#3a0ca3", "#ffbe0b"), ("#06d6a0", "#118ab2", "#ffd166"), ("#f72585", "#7209b7", "#4cc9f0"),
                  ("#ff5400", "#c9184a", "#ffee32"), ("#00b4d8", "#03045e", "#fca311"), ("#ffbe0b", "#fb5607", "#ffffff"),
                  ("#ef233c", "#2b2d42", "#ffd60a"), ("#2ec4b6", "#011627", "#ff9f1c")]
COVER_HOOKS = ["Can you solve this? 🤔", "Bet you can't solve this 😏", "Solve it in 10 seconds ⏱️",
               "Think you're smart? 🧠", "Test your brain! 🔥", "Quick! What's the answer? ⚡",
               "Don't scroll — try it! ✋", "Can you get it right? 🎯"]
COVER_EMOJI = ["🤔", "😱", "🧠", "🔥", "⚡", "🎯", "👀", "💯"]


def cover_for(q: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """What the cover shows — its look and hook picked by the question, so
    each video looks different and the same video always looks the same."""
    qid = str(q.get("question_id") or q.get("question_text") or "")
    n = int(hashlib.sha256(qid.encode()).hexdigest(), 16)
    bg_from, bg_to, accent = COVER_PALETTES[n % len(COVER_PALETTES)]
    link = q.get("curriculum") or {}
    text = " ".join(display(q.get("question_text") or "").split())
    if len(text) > 110:
        text = text[:107].rsplit(" ", 1)[0] + "…"
    options = [o for o in (q.get("options") or []) if isinstance(o, dict)][:4]
    chips = []
    for o in options:
        t = " ".join(display(o.get("text") or "").split())
        chips.append(f"{o.get('id')}) " + (t if len(t) <= 22 else t[:20] + "…"))
    return {"bg_from": bg_from, "bg_to": bg_to, "accent": accent,
            "hook": COVER_HOOKS[(n // 7) % len(COVER_HOOKS)], "emoji": COVER_EMOJI[(n // 11) % len(COVER_EMOJI)],
            "tilt": [-4, -2, 2, 3][(n // 13) % 4],
            "tag": " · ".join(x for x in (_grade_label(str(link.get("grade") or "")).upper(),
                                          subject_label(q).upper()) if x),
            "question": text, "choices": chips, "brand": brand_name(b, q), "figure": _cover_figure(q)}


def _cover_figure(q: dict[str, Any]) -> str:
    """The question's figure as an image for the cover, or "" — a diagram
    question shows its diagram on the thumbnail, so the feed sees the puzzle."""
    if not isinstance(q.get("diagram"), dict):
        return ""
    import base64

    from .whiteboard import figure_scene

    scene = figure_scene(q)
    if not scene:
        return ""
    return "data:image/svg+xml;base64," + base64.b64encode(scene["svg"].encode()).decode()


def _teacher_mode() -> str:
    from . import teacher

    return teacher.mode()


# ── the cut ──────────────────────────────────────────────────────────────────

_DROP = {"trap"}


def script(data: dict[str, Any], q: dict[str, Any], b: dict[str, Any] | None = None) -> dict[str, Any]:
    """The walkthrough cut for a feed: the hook on the question, a silent
    countdown, the solution without the traps, an end card."""
    b = b or brand()
    out = copy.deepcopy(data)
    scenes: list[dict[str, Any]] = []
    for scene in data.get("scenes") or []:
        if scene.get("scene") in _DROP:
            continue
        scene = copy.deepcopy(scene)
        if scene.get("scene") == "setup" and data.get("kind") in ("number_line", "balance", "fraction_bar"):
            continue  # the picture that follows says it; a feed has no time for both
        if scene.get("scene") == "answer":
            # The answer, without the paragraph after it — that is in the post.
            opt = f"{scene['option']}: " if scene.get("option") else ""
            scene["say"] = _answer_line(scene, opt)
        if scene.get("scene") == "title":
            scene["say"] = f"{b.get('hook') or 'Can you solve this?'} {scene.get('say') or ''}".strip()
            scenes.append(scene)
            scenes.append({"scene": "countdown", "hold": b["countdown"], "say": "",
                           "caption": "Pause the video and try it!"})
            continue
        scenes.append(scene)
    if b.get("teacher", "off") != "off":
        from . import teacher

        # The teacher comes back to ask: the viewer answers in the comments.
        scenes.append({"scene": "check", "say": teacher.CHECK_LINE, "caption": teacher.CHECK_CAPTION})
    # The figure goes up with the question, before the countdown: it is on
    # the board while the viewer works it out, and stays for the solution.
    for k in range(len(scenes) - 1):
        if scenes[k].get("scene") == "countdown" and scenes[k + 1].get("scene") == "figure":
            scenes[k], scenes[k + 1] = scenes[k + 1], scenes[k]
            break
    if b.get("marketing"):
        scenes.append(marketing_scene(q, b))
    who = b["handle"] or brand_name(b, q)
    scenes.append({"scene": "outro", "name": brand_name(b, q), "handle": b["handle"], "website": b["website"],
                   "cta": b["cta"], "say": f"{b['cta']}. Follow {spoken_handle(who)}.",
                   "caption": f"{b['cta']}: {who}"})
    if b.get("teacher", "off") != "off" and not b.get("single"):
        from . import teacher

        cast = teacher.cast_for(str(q.get("question_id") or data.get("question_id") or ""), b["teacher"], b.get("students"))
        scenes = teacher.classroom_script(scenes, cast)
    out["scenes"] = scenes
    return out


# What every video says about the platform, a few seconds before the end: to
# teachers and parents (set a paper, test the class online) or to students
# (practise, marked at once, with the video answers) — by question, so the
# feed sees both. The screen is the console's own (static/promo).
MARKETING = [
    ("start", "Teachers! Set a full CBC exam like this, with its marking scheme, in two minutes. Free to start at {site}.",
     "Teachers: set this exam free at {site}"),
    ("test", "Teachers, turn any paper into an online test your class takes on their phones, marked for you. Try it at {site}.",
     "Online tests, marked for you: {site}"),
    ("student_result", "Students! Practise questions like this one, get your marks at once, and watch how to solve each one. Go to {site}.",
     "Practise free: {site}"),
    ("print", "Parents and teachers: print CBC papers with marking schemes for any grade. Start free at {site}.",
     "Print CBC papers free: {site}"),
]


def marketing_scene(q: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    from . import promo

    qid = str(q.get("question_id") or "")
    shot, say, caption = MARKETING[int(hashlib.sha256(f"mk:{qid}".encode()).hexdigest(), 16) % len(MARKETING)]
    site = (b.get("website") or "cbc.gidraf.dev").replace("https://", "").replace("http://", "").rstrip("/")
    spoken = site.replace(".", " dot ")
    return {"scene": "screen", "marketing": True, "shot": shot, "img": promo._image(shot),
            "box": (promo._shots().get(shot) or {}).get("box") or [0, 0, 0, 0],
            "say": say.format(site=spoken), "caption": caption.format(site=site)}


def _answer_line(scene: dict[str, Any], opt: str) -> str:
    from .play_engine import _speakable
    from .speech_text import for_speech

    return for_speech(f"So the answer is {opt}{_speakable(scene.get('text') or '')}.")


def spoken_handle(handle: str) -> str:
    """'@cbc_maths' is said 'at C B C maths'."""
    h = handle.lstrip("@").replace("_", " ").replace(".", " dot ")
    h = re.sub(r"\b([A-Z]{2,5})\b", lambda m: " ".join(m.group(1)), h)
    return ("at " if handle.startswith("@") else "") + h


def frame_payload(q: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """What the vertical frame shows around the board."""
    from . import teacher
    from .whiteboard import _hand_bytes

    link = q.get("curriculum") or {}
    tag = " · ".join(x for x in (_grade_label(str(link.get("grade") or "")), subject_label(q),
                                 str(link.get("sub_strand") or "")) if x)
    logo = None
    if b.get("logo_url"):
        import base64

        raw = _hand_bytes(b["logo_url"])
        if raw:
            kind = "image/svg+xml" if raw.lstrip()[:1] == b"<" else "image/png"
            logo = f"data:{kind};base64," + base64.b64encode(raw).decode()
    return {"hook": b.get("hook") or "Can you solve this?", "tag": tag, "brand": brand_name(b, q), "handle": b["handle"],
            "bg_from": b["bg_from"], "bg_to": b["bg_to"], "accent": b["accent"], "text": b["text"],
            "website": b["website"], "countdown": b["countdown"], "logo": logo, "music_url": b["music_url"],
            **({"cover": cover_for(q, b)} if b.get("cover", True) else {}),
            **_teacher_frame(q, b)}


def _teacher_frame(q: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """The teacher (or the classroom) the frame draws."""
    from . import teacher

    qid = str(q.get("question_id") or "")
    how = b.get("teacher", "off")
    if how == "off":
        return {}
    cast = teacher.cast_for(qid, how, b.get("students"))
    return {"teacher": {"gender": cast["teacher"]["gender"], "mode": "classroom",
                        "cast": [{"id": c["id"], "model": c["model"], "x": c["x"], "ry": c["ry"]} for c in cast.values()]}}


def _grade_label(grade: str) -> str:
    m = re.search(r"(\d+)", grade)
    return f"Grade {m.group(1)}" if m else grade


def cache_key(sdata: dict[str, Any], voice: str, b: dict[str, Any], gender: str = "") -> str:
    from . import teacher, whiteboard

    look = {k: b.get(k) for k in ("name", "handle", "website", "cta", "countdown", "logo_url", "music_url",
                                  "hook", "bg_from", "bg_to", "accent", "text")}
    if gender:                  # a video without a teacher keeps the key it always had
        look["teacher"] = f"{teacher.VERSION}:{gender}:{b.get('teacher', '')}"
        if b.get("cast"):           # who is in it: a new cast is a new video
            look["teacher"] += ":" + teacher.signature(b["cast"])
    blob = json.dumps({"v": VERSION, "board": whiteboard.cache_key(sdata, voice), "brand": look}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


# ── the post ─────────────────────────────────────────────────────────────────

def snippets(text: str) -> list[str]:
    """The middle and the end of a question — 8 words each — to find its post
    by when Facebook folds or cuts the opening."""
    words = str(text or "").split()
    if len(words) < 14:
        return []
    mid = len(words) // 2
    return [" ".join(words[mid - 4:mid + 4]), " ".join(words[-8:])]


def display(text: Any) -> str:
    """LaTeX as a phone shows it: 3/4, x², ∛216, ≤, 45°."""
    from .latex_text import to_unicode

    return re.sub(r"\s+", " ", to_unicode(str(text or ""))).strip()


def _steps(scenes: list[dict[str, Any]]) -> list[str]:
    """The working, in the notation the board writes — the post explains
    what the video explains."""
    out: list[str] = []
    for s in scenes:
        kind = s.get("scene")
        if kind == "setup":
            out.append(f"Write it as one calculation: {display(s.get('expression'))}")
        elif kind == "rewrite":
            st = s.get("step") or {}
            right = st.get("right")
            right = f"({right})" if str(right).startswith("-") else right
            out.append(f"{st.get('left')} {st.get('op')} {right} = {st.get('result')} — {st.get('why')}")
        elif kind == "number_line_start":
            out.append(f"Start at {s['spec']['start']} on the number line.")
        elif kind == "number_line_jump":
            move = s.get("move")
            out.append(f"{'+' if move > 0 else '−'}{abs(move)}: move {abs(move)} "
                       f"{'right' if move > 0 else 'left'} to {s.get('to')}.")
        elif kind == "balance_move":
            sp, move = s.get("spec") or {}, s.get("move") or {}
            k = (sp.get("moves") or []).index(move) if move in (sp.get("moves") or []) else -1
            state = (sp.get("states") or [])[k] if k >= 0 and k < len(sp.get("states") or []) else None
            line = f"{move.get('why')}"
            out.append(line + (f" → {state[0]} = {state[1]}" if state else ""))
        elif kind == "fraction_bars" and s.get("phase") == "common":
            sp = s.get("spec") or {}
            out.append(f"Use {sp.get('common')} as the common denominator: "
                       f"{sp['first'][0]}/{sp['first'][1]} = {sp['first_as'][0]}/{sp['common']}, "
                       f"{sp['second'][0]}/{sp['second'][1]} = {sp['second_as'][0]}/{sp['common']}.")
        elif kind == "working":
            out.append(display(s.get("text")))
        elif kind == "fraction_bars" and s.get("phase") == "result":
            sp = s.get("spec") or {}
            out.append(f"{sp['first_as'][0]}/{sp['common']} {sp.get('op')} {sp['second_as'][0]}/{sp['common']} "
                       f"= {sp['result'][0]}/{sp['result'][1]}")
    return out


def hashtags(q: dict[str, Any], b: dict[str, Any] | None = None) -> list[str]:
    b = b or brand()
    link = q.get("curriculum") or {}
    grade = re.search(r"(\d+)", str(link.get("grade") or ""))
    subject = re.sub(r"[^A-Za-z]", "", str(link.get("subject") or "Maths").title()) or "Maths"
    subject = {"Mathematics": "Maths"}.get(subject, subject)
    topic = re.sub(r"[^A-Za-z0-9]", "", str(link.get("sub_strand") or "").title())
    tags = ["#CBC", "#CBE", f"#{subject}", f"#{subject}Challenge"]
    if grade:
        g = grade.group(1)
        tags += [f"#Grade{g}", f"#Grade{g}{subject}"]
        tags += {"6": ["#KPSEA"], "9": ["#KJSEA"]}.get(g, [])
    if topic:
        tags.append(f"#{topic}")
    tags += ["#Kenya", "#KenyanTeachers", "#LearnOnTikTok"]
    for extra in re.split(r"[\s,]+", b.get("hashtags") or ""):
        if extra:
            tags.append(extra if extra.startswith("#") else f"#{extra}")
    seen: list[str] = []
    for t in tags:
        if t.lower() not in [x.lower() for x in seen]:
            seen.append(t)
    return seen


def post_text(q: dict[str, Any], data: dict[str, Any], b: dict[str, Any] | None = None) -> str:
    """The caption: the question, its options, pause-and-try, the answer and
    the working the video explains, the call to follow, hashtags."""
    b = b or brand()
    link = q.get("curriculum") or {}
    head = " · ".join(x for x in (_grade_label(str(link.get("grade") or "")), str(link.get("subject") or ""),
                                  str(link.get("sub_strand") or "")) if x)
    lines = [f"🧮 {b.get('hook') or 'Can you solve this?'}{f' ({head})' if head else ''}", ""]
    context = display(q.get("stimulus_context") or "")
    if context:
        lines += [context, ""]
    lines.append(display(q.get("question_text") or ""))
    options = q.get("options") or []
    if options:
        lines.append("")
        for o in options:
            if isinstance(o, dict):
                lines.append(f"{o.get('id')}) {display(o.get('text'))}")
    lines += ["", "⏸️ Pause and try it before you watch the answer!", ""]
    scenes = data.get("scenes") or []
    answer = next((s for s in scenes if s.get("scene") == "answer"), None)
    if answer:
        opt = f"{answer.get('option')}) " if answer.get("option") else ""
        lines.append(f"✅ Answer: {opt}{display(answer.get('text'))}")
    steps = _steps(scenes)
    if steps:
        lines += ["", "💡 How to solve it:"]
        lines += [f"{n}. {step}" for n, step in enumerate(steps, 1)]
    key = next((o for o in options if isinstance(o, dict) and (o.get("is_correct") or o.get("correct"))), None)
    why = display((key or {}).get("distractor_rationale") or (key or {}).get("why") or "")
    if why:
        lines += ["", f"Why: {why}"]
    lines.append("")
    follow = f"📚 {b['cta']}" + (f" — {b['handle']}" if b["handle"] else "")
    lines.append(follow)
    if b["website"]:
        lines.append(f"🌐 {b['website']}")
    lines += ["", " ".join(hashtags(q, b))]
    return "\n".join(lines).strip() + "\n"


def thread(q: dict[str, Any], data: dict[str, Any], b: dict[str, Any] | None = None) -> dict[str, Any]:
    """The post as a conversation: the question as the caption, then four
    comments — the choices, "can you solve it?", the answer, and the answer
    with its working — so every post opens with people answering in it.

    `find` is what the poster looks for to find the post again once it is
    out (the question's opening words, as the caption shows them)."""
    b = b or brand()
    question = display(q.get("question_text") or "")
    context = display(q.get("stimulus_context") or "")
    options = [o for o in (q.get("options") or []) if isinstance(o, dict)]
    caption_lines = [context, ""] if context else []
    caption_lines += [question, "", "👇 The choices are in the comments — can you solve it?" if options
                      else "👇 Can you solve it? Answer in the comments!", "", " ".join(hashtags(q, b))]
    scenes = data.get("scenes") or []
    answer = next((s for s in scenes if s.get("scene") == "answer"), None)
    letter = f"{answer.get('option')}) " if answer and answer.get("option") else ""
    answer_line = f"✅ Answer: {letter}{display(answer.get('text'))}" if answer else ""
    choices = ("Choices:\n" + "\n".join(f"{o.get('id')}) {display(o.get('text'))}" for o in options)) if options else ""
    ask = ("🤔 Can you solve it? Drop your answer (" + ", ".join(str(o.get("id")) for o in options) + ") below — "
           "the answer comes in a minute! ⏳") if options else "🤔 Can you solve it? Drop your answer below — the answer comes in a minute! ⏳"
    steps = _steps(scenes)
    key = next((o for o in options if o.get("is_correct") or o.get("correct")), None)
    why = display((key or {}).get("distractor_rationale") or (key or {}).get("why") or "")
    explain = [answer_line] if answer_line else []
    if steps:
        explain += ["", "💡 How to solve it:"] + [f"{n}. {step}" for n, step in enumerate(steps, 1)]
    if why:
        explain += ["", f"Why: {why}"]
    explain += ["", f"📚 {b['cta']}" + (f" — {b['handle']}" if b["handle"] else "")]
    if b["website"]:
        explain.append(f"🌐 {b['website']}")
    first = [c for c in (choices, ask) if c]
    later = [c for c in (answer_line, "\n".join(explain).strip()) if c]
    find = " ".join(question.split())[:60]
    # Older captions open with the context, or the hook and the topic: the
    # poster looks for any of these when the question's words are folded away.
    also = [" ".join(context.split())[:60]] if context else []
    also += snippets(question)          # its middle and its end: a caption folded at the start still shows them
    return {"caption": "\n".join(caption_lines).strip() + "\n", "first": first, "later": later, "find": find,
            "find_also": also}


def _curriculum_row(q: dict[str, Any]) -> dict[str, Any]:
    """The sub-strand this question comes from, as the curriculum design gives it."""
    from ..infra.db import fetch_one

    link = q.get("curriculum") or {}
    try:
        return fetch_one("""SELECT strand_name, sub_strand_name, slos, key_inquiry_questions, core_competencies, values,
                                   source_pages FROM curriculum_substrands
                            WHERE LOWER(grade) = LOWER(:g) AND LOWER(subject) = LOWER(:s)
                              AND LOWER(sub_strand_name) = LOWER(:ss) LIMIT 1""",
                         {"g": str(link.get("grade") or ""), "s": str(link.get("subject") or ""),
                          "ss": str(link.get("sub_strand") or "")}) or {}
    except Exception:  # noqa: BLE001
        return {}


def _texts(items: Any) -> list[str]:
    out = []
    for x in items or []:
        if isinstance(x, dict):
            x = x.get("text") or x.get("description") or x.get("name") or x.get("statement") or ""
        x = " ".join(display(str(x)).split())
        if x:
            out.append(x)
    return out


def _pages(pages: Any) -> str:
    nums = sorted({int(p) for p in (pages or []) if str(p).isdigit()})
    if not nums:
        return ""
    return f"page {nums[0]}" if len(nums) == 1 else f"pages {nums[0]}–{nums[-1]}"


def _similar(q: dict[str, Any]) -> dict[str, Any] | None:
    """Another question from the same sub-strand, to try next."""
    try:
        from . import question_rows
        from .question_dna import question_dna_service

        link = q.get("curriculum") or {}
        rows = question_dna_service.list_questions(grade=link.get("grade") or None, subject=link.get("subject") or None,
                                                   sub_strand=link.get("sub_strand") or None, limit=40)
        others = [r for r in question_rows.flatten_all(rows)
                  if str(r.get("question_id")) != str(q.get("question_id")) and r.get("question_text")
                  and str(r.get("status") or "") not in ("needs_review", "rejected", "superseded")]
        if not others:
            return None
        n = int(hashlib.sha256(str(q.get("question_id")).encode()).hexdigest(), 16)
        return others[n % len(others)]
    except Exception:  # noqa: BLE001
        return None


def comment_library(q: dict[str, Any], data: dict[str, Any], b: dict[str, Any] | None = None) -> list[str]:
    """Every comment a post can carry, in the order they go up: the thread
    (choices, can you solve it, the answer, the working) and then the ones the
    engagement loop adds while a post is quiet — where it sits in the KICD
    curriculum design, what it tests, why each wrong choice is wrong, a hint, a
    similar question, a question back to the reader. Up to twenty."""
    b = b or brand()
    t = thread(q, data, b)
    out: list[str] = [*t["first"], *t["later"]]
    link = q.get("curriculum") or {}
    grade = _grade_label(str(link.get("grade") or ""))
    subject = str(link.get("subject") or "")
    row = _curriculum_row(q)
    strand, sub = str(row.get("strand_name") or ""), str(row.get("sub_strand_name") or link.get("sub_strand") or "")
    where = " › ".join(x for x in (strand, sub) if x)
    pages = _pages(row.get("source_pages"))
    if where:
        out.append(f"📘 From the KICD {grade} {subject} curriculum design — {where}" + (f" ({pages})." if pages else "."))
    slos = _texts(row.get("slos"))
    if slos:
        out.append(f"🎯 What this question tests: {slos[0]}")
    options = [o for o in (q.get("options") or []) if isinstance(o, dict)]
    for o in options:
        if o.get("is_correct") or o.get("correct"):
            continue
        why = " ".join(display(o.get("distractor_rationale") or o.get("why") or "").split())
        if why:
            out.append(f"❌ Why not {o.get('id')}) {display(o.get('text'))}? {why}")
    kiq = _texts(row.get("key_inquiry_questions"))
    if kiq:
        out.append(f"🤔 Think about it: {kiq[0]}")
    comps, values = _texts(row.get("core_competencies")), _texts(row.get("values"))
    if comps or values:
        out.append("🌱 This builds " + " and ".join(x for x in (
            f"the competency of {comps[0].rstrip('.')}" if comps else "", f"the value of {values[0].rstrip('.')}" if values else "") if x) + ".")
    steps = _steps(data.get("scenes") or [])
    if steps:
        out.append(f"💡 Stuck? Start here: {steps[0]}")
    other = _similar(q)
    if other:
        lines = [f"🔁 Try a similar one: {display(other.get('question_text'))}"]
        for o in (other.get("options") or [])[:4]:
            if isinstance(o, dict):
                lines.append(f"{o.get('id')}) {display(o.get('text'))}")
        out.append("\n".join(lines))
    out += [
        "👍 Was this one easy or 😮 hard? Tell us below!",
        "👥 Tag a friend who should try this one!",
        f"📄 Teachers and parents: printable {grade} {subject} papers with marking schemes are at {b['website']}." if b.get("website") else "",
        f"📚 {b['cta']}" + (f" — {b['handle']}" if b.get("handle") else "") + " 🔔",
    ]
    return [c for c in out if c][:20]


# ── the campaign: up to 150 comments a post can carry, none repeated ─────────

KICD_DESIGNS = "https://kicd.ac.ke/cbc-materials/curriculum-designs/"
CAMPAIGN_MAX = 150


def _practice(q: dict[str, Any], limit: int = 75) -> list[dict[str, Any]]:
    """Other questions from the same sub-strand, with their choices and answers."""
    try:
        from . import question_rows
        from .question_dna import question_dna_service

        link = q.get("curriculum") or {}
        rows = question_dna_service.list_questions(grade=link.get("grade") or None, subject=link.get("subject") or None,
                                                   sub_strand=link.get("sub_strand") or None, limit=limit + 1)
        return [r for r in question_rows.flatten_all(rows)
                if str(r.get("question_id")) != str(q.get("question_id")) and r.get("question_text")
                and str(r.get("status") or "") not in ("needs_review", "rejected", "superseded")][:limit]
    except Exception:  # noqa: BLE001
        return []


def campaign_comments(q: dict[str, Any], data: dict[str, Any], b: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Every comment a post can carry, in order: the twenty of the engagement
    loop, then the question and its answer as pictures, every outcome, inquiry
    question, competency and value of its KICD sub-strand (quoted and credited
    to KICD, with where to read the design), the walkthrough and the
    platform's features, and practice questions from the same sub-strand —
    each one, and its answer a comment later. Up to 150, none repeated."""
    from . import social_cards

    b = b or brand()
    out: list[dict[str, str]] = [{"text": t} for t in comment_library(q, data, b)]
    qid = str(q.get("question_id") or "")
    link = q.get("curriculum") or {}
    grade = _grade_label(str(link.get("grade") or ""))
    subject = str(link.get("subject") or "")
    site = (b.get("website") or "").rstrip("/")
    row = _curriculum_row(q)
    sub = str(row.get("sub_strand_name") or link.get("sub_strand") or "")
    pages = _pages(row.get("source_pages"))
    credit = (f"— KICD, {grade} {subject} Curriculum Design" + (f", {pages}" if pages else "")
              + f". © Kenya Institute of Curriculum Development. Read the design: {KICD_DESIGNS}")
    for step, line in (("question", "🖼️ Here is the question as a card — save it and try it later."),
                       ("answer", "✅ The answer, worked out on one card."),
                       ("teaser", "🤔 One to share with a friend who likes a challenge.")):
        try:
            card = social_cards.status(qid, step, q)
            if card.get("status") == "ready" and card.get("url"):
                out.append({"text": line, "image_url": card["url"]})
        except Exception:  # noqa: BLE001
            pass
    if isinstance(q.get("chemistry"), dict):
        # Chemistry: the animation picture by picture — every step of the reaction, the atoms, the separation.
        from . import chem_stills

        try:
            out += chem_stills.comments(qid, q)
        except Exception:  # noqa: BLE001
            pass
    for n, slo in enumerate(_texts(row.get("slos")), start=1):
        out.append({"text": f"🎯 Learning outcome {n} for {sub}: “{slo}” {credit}"})
    for kiq in _texts(row.get("key_inquiry_questions")):
        out.append({"text": f"💭 Key inquiry question from KICD: “{kiq}” What would you answer? {credit}"})
    for comp in _texts(row.get("core_competencies")):
        out.append({"text": f"🌱 Core competency this develops (KICD): {comp}. {credit}"})
    for value in _texts(row.get("values")):
        out.append({"text": f"🤝 Value it builds (KICD): {value}. {credit}"})
    out.append({"text": f"📄 Where this comes from: the KICD {grade} {subject} curriculum design, {sub}"
                        + (f" ({pages})" if pages else "") + f". All KICD curriculum designs: {KICD_DESIGNS}"})
    if site:
        out += [{"text": f"🎬 Watch this question worked out step by step: {site}/play"},
                {"text": f"📝 Teachers: set a full {grade} {subject} exam with its marking scheme in two minutes — free to start at {site}"},
                {"text": f"🔀 Give every student their own random questions, in their own order, so nobody copies: online tests at {site}"},
                {"text": f"🖨️ Print papers, marking schemes and answer sheets for any grade at {site}"},
                {"text": f"📲 Share a test link with your class or your child — they answer on a phone, marked at once: {site}"},
                {"text": f"👨‍👩‍👧 Parents: practise {subject} at home with tests that mark themselves: {site}"}]
    practice = _practice(q)
    previous = None
    for k, other in enumerate(practice, start=1):
        lines = [f"🔁 Practice {k} ({sub}): {display(other.get('question_text'))}"]
        for o in (other.get("options") or [])[:4]:
            if isinstance(o, dict):
                lines.append(f"{o.get('id')}) {display(o.get('text'))}")
        lines.append("Answer below 👇")
        out.append({"text": "\n".join(lines)})
        if previous is not None:
            out.append({"text": _practice_answer(previous[0], previous[1])})
        previous = (k, other)
        if len(out) >= CAMPAIGN_MAX + 20:
            break
    if previous is not None:
        out.append({"text": _practice_answer(previous[0], previous[1])})
    seen, unique = set(), []
    for c in out:
        key = c["text"].strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(c)
    return unique[:CAMPAIGN_MAX]


def _practice_answer(k: int, other: dict[str, Any]) -> str:
    key = next((o for o in (other.get("options") or []) if isinstance(o, dict) and (o.get("is_correct") or o.get("correct"))), None)
    answer = f"{key.get('id')}) {display(key.get('text'))}" if key else display(other.get("correct_answer") or "")
    why = display((key or {}).get("distractor_rationale") or other.get("model_answer") or "")
    return f"✅ Practice {k} answer: {answer}" + (f" — {why[:220]}" if why else "")


# ── the queue ────────────────────────────────────────────────────────────────

def _prepare(q: dict[str, Any], voice: str = "", *, teacher_mode: str | None = None, students: int | None = None
             ) -> tuple[dict[str, Any], dict[str, Any], str, str, dict[str, Any], str]:
    """The cut, its voice and its key. With a teacher, the voice is the
    teacher's: a woman's face speaks with a woman's voice, a man's with a man's."""
    from . import teacher, whiteboard

    b = brand()
    qid = str(q.get("question_id") or "")
    if b.get("teacher", "off") != "off" or teacher_mode:
        picked = teacher.choice(qid)              # what was asked for this question in Play
        if picked["teacher"]:
            b["teacher"] = picked["teacher"]
        b["students"] = picked["students"] if picked["students"] is not None else teacher.students_setting()
    if teacher_mode is not None:
        b["teacher"] = teacher_mode
    if students is not None:
        b["students"] = students
    gender, lead = "", ""
    if b.get("teacher", "off") != "off":
        cast = teacher.cast_for(qid, b["teacher"], b.get("students"))
        from .math_engine.tts_service import is_science, science_voice

        if is_science(str((q.get("curriculum") or {}).get("subject") or "")):
            # A science video: the teacher speaks with a British or American voice.
            cast = {**cast, "teacher": {**cast["teacher"], "voice": science_voice(cast["teacher"]["gender"], qid)}}
        b["cast"] = cast
        gender, lead = cast["teacher"]["gender"], cast["teacher"]["voice"]
    data, voice, title = whiteboard._script_for(q, voice or lead)
    sdata = script(data, q, b)
    return data, sdata, voice, title, b, cache_key(sdata, voice, b, gender)


def _single_teacher_keys(q: dict[str, Any]) -> list[tuple[str, str]]:
    """The keys a one-teacher video had (Settings: female, male or alternate),
    before every teacher video became a cast."""
    from . import teacher, whiteboard

    qid = str(q.get("question_id") or "")
    out = []
    for how in ("alternate", "female", "male"):
        gender = how if how != "alternate" else (
            "female" if int(hashlib.sha256(qid.encode()).hexdigest(), 16) % 2 == 0 else "male")
        b = {**brand(), "teacher": how, "single": True}
        data, voice, _ = whiteboard._script_for(q, teacher.voice_for(gender))
        key = cache_key(script(data, q, b), voice, {k: v for k, v in b.items() if k != "single"}, gender)
        if (gender, key) not in out:
            out.append((gender, key))
    return out


def _on_server(name: str) -> bool:
    """The file is on this server's storage itself (not moved to Drive)."""
    from ..infra.storage import object_storage
    from ..settings import settings

    try:
        object_storage._get_client().stat_object(settings.minio_bucket, name)
        return True
    except Exception:  # noqa: BLE001
        return False


def _serve_older() -> bool:
    from . import platform_settings

    try:
        return bool(platform_settings.get("social_serve_older", True))
    except Exception:  # noqa: BLE001
        return True


def status(question_id: str, q: dict[str, Any] | None = None, voice: str = "", *, legacy: bool = True,
           older: bool = True) -> dict[str, Any]:
    from ..infra.db import fetch_one
    from ..infra.storage import object_storage
    from . import whiteboard

    from . import teacher

    q = q or whiteboard.load(question_id)
    asked_voice = voice
    data, sdata, voice, _, b, key = _prepare(q, voice)
    name = f"{PREFIX}/{question_id}/{key}.mp4"
    # Which teacher this video has ('' for none) — the console marks and filters by it.
    out: dict[str, Any] = {"question_id": question_id, "key": key, "scenes": len(data.get("scenes") or []),
                           "post": post_text(q, data, b), "thread": thread(q, data, b),
                           "teacher": (b.get("cast") or {}).get("teacher", {}).get("gender", "")}
    if object_storage.object_exists(name):
        return {**out, "status": "ready", "url": whiteboard.public_url(name),
                "thumbnail_url": whiteboard.public_url(f"{PREFIX}/{question_id}/{key}.jpg")}
    out["marketing"] = bool(b.get("marketing"))
    # With the marketing on, the videos made before it are being replaced: they
    # no longer serve, so every post from now carries it.
    if legacy and b.get("teacher", "off") != "off" and not asked_voice and not b.get("marketing"):
        # Turning the teacher on does not unmake what was made: a video cut
        # before it still serves until it is made again with the teacher.
        # A video with one teacher, made before the classroom, serves too.
        for gender, old in [*_single_teacher_keys(q), ("", _prepare(q, teacher_mode="off")[5])]:
            if object_storage.object_exists(f"{PREFIX}/{question_id}/{old}.mp4"):
                return {**out, "status": "ready", "key": old, "url": whiteboard.public_url(f"{PREFIX}/{question_id}/{old}.mp4"),
                        "thumbnail_url": whiteboard.public_url(f"{PREFIX}/{question_id}/{old}.jpg"), "teacher": gender,
                        "teacher_pending": not gender}
    if legacy and older and not asked_voice and _serve_older():
        # Settings → Post older videos while new ones are made: the newest
        # video this question already has goes out, while the new one is made
        # (the factory, which asks with legacy=False, still makes it).
        made = fetch_one("""SELECT object_name FROM question_videos WHERE question_id = :q AND kind = 'social'
                            ORDER BY made_at DESC LIMIT 1""", {"q": question_id})
        obj = str((made or {}).get("object_name") or "")
        if obj and _on_server(obj):              # not one only on Drive: streaming it back can fail the post
            return {**out, "status": "ready", "older": True, "key": obj.rsplit("/", 1)[-1][:-4],
                    "url": whiteboard.public_url(obj), "thumbnail_url": whiteboard.public_url(obj[:-4] + ".jpg"),
                    "marketing": False}
    job = fetch_one(
        "SELECT job_id, status, error FROM jobs WHERE kind = :kind "
        "AND payload->>'question_id' = :qid ORDER BY created_at DESC LIMIT 1",
        {"kind": JOB_KIND, "qid": question_id})
    if job and str(job.get("status")) in ("queued", "running"):
        return {**out, "status": str(job["status"]), "job_id": job["job_id"]}
    if job and str(job.get("status")) == "failed":
        return {**out, "status": "failed", "job_id": job["job_id"], "error": str(job.get("error") or "")[:400]}
    return {**out, "status": "none"}


def enqueue(question_id: str, *, queued_by: str = "", batch_id: str = "", voice: str = "",
            fresh: bool = False, priority: int = 0, teacher: str | None = None,
            students: int | None = None, on_demand: bool = False, dispatch: bool = True) -> dict[str, Any]:
    """Queue the cut. `fresh`: make it as the settings say now (with the
    teacher) even when a video cut before the teacher still serves — with a
    new cast. `teacher` / `students`: kept for this question (from Play)."""
    from . import job_queue, whiteboard
    from . import teacher as teachers

    q = whiteboard.load(question_id)
    if fresh or teacher is not None or students is not None:
        if teacher is None and students is None:
            was = teachers.choice(question_id)
            teacher, students = was["teacher"], was["students"]
        teachers.choose(question_id, teacher=teacher or "", students=students, new_take=True)
    now = status(question_id, q, voice, legacy=not fresh, older=False)     # an older video is no reason not to make the new one
    if on_demand and now["status"] == "queued" and now.get("job_id"):
        # Already waiting in the batch: moved to the standby worker, first.
        from ..infra.db import execute

        execute("""UPDATE jobs SET payload = payload || '{"on_demand": true, "priority": 50}'::jsonb
                   WHERE job_id = :id AND status = 'queued'""", {"id": now["job_id"]})
        job_queue.dispatch(now["job_id"])
        return {**now, "on_demand": True}
    if now["status"] in ("ready", "queued", "running"):
        return now
    if not now["scenes"]:
        return {**now, "status": "skipped", "error": "Nothing to draw for this item."}
    link = q.get("curriculum") or {}
    job = job_queue.enqueue(
        JOB_KIND, str(link.get("grade") or ""), str(link.get("subject") or ""),
        {"artifact_id": f"social:{question_id}", "question_id": question_id, "voice": voice,
         # What the batch screen shows while it renders.
         "title": " ".join(str(q.get("question_text") or "").split())[:90],
         **({"priority": max(priority, 50) if on_demand else priority} if priority or on_demand else {}),
         **({"on_demand": True} if on_demand else {})},
        strand=str(link.get("strand") or ""), sub_strand=str(link.get("sub_strand") or ""),
        batch_id=batch_id, queued_by=queued_by or "social")
    if dispatch:
        job_queue.dispatch(job.job_id)      # the render runs in the worker, not in the API
    return {**now, "status": "queued", "job_id": job.job_id}


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    from ..infra.storage import object_storage
    from . import run_log, whiteboard

    payload = dict(job.get("payload") or {})
    qid = str(payload.get("question_id") or "")
    if not qid:
        return {"status": "skipped", "reason": "no question_id"}
    q = whiteboard.load(qid)
    data, sdata, voice, title, b, key = _prepare(q, str(payload.get("voice") or ""))
    run_log.step("Script", f"{len(sdata['scenes'])} scenes · vertical · {voice}")
    last = {"stage": ""}
    from .job_queue import Live

    # Stage and percentage on the job's row as the render goes, for the batch
    # screen; the run log keeps the narration.
    live = Live(str(job.get("job_id") or ""))
    live("script", 1, 1)

    def tick(stage: str, n: int, total: int) -> None:
        live(stage, n, total)
        if stage != last["stage"]:
            run_log.step({"voice": "Narrating", "draw": "Drawing", "mux": "Mixing sound",
                          "save": "Saving"}.get(stage, stage), f"{total} to do" if total > 1 else "")
            last["stage"] = stage

    made = whiteboard.render(sdata, title=title, voice=voice, progress=tick, social=frame_payload(q, b),
                             prefix=PREFIX, key=key)
    post = post_text(q, data, b)
    object_storage.save_text(f"{PREFIX}/{qid}/{key}.txt", post)
    live.done()
    run_log.step("Saved", made["url"])
    try:                                      # someone pressed Post now while it was being made: post it now
        from . import social_export

        if social_export.hand_when_made(qid):
            run_log.step("Posting", "Post now was waiting for this video")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not hand %s to the poster: %s", qid, exc)
    return {"status": "done", "question_id": qid, "post": post, **made}


def live_page(q: dict[str, Any], voice: str = "", *, teacher_mode: str | None = None,
              students: int | None = None) -> str:
    """The vertical cut in the console, voiced by the server. `teacher_mode`
    previews it with a teacher (or none) whatever the setting says."""
    import base64

    from . import whiteboard

    _, sdata, voice, title, b, _ = _prepare(q, voice, teacher_mode=teacher_mode, students=students)
    clips = whiteboard.speak_all(sdata["scenes"], voice)
    audio = ["data:audio/mpeg;base64," + base64.b64encode(a).decode() if a else None for a, _ in clips]
    durations = [float(sc["hold"]) if sc.get("hold") else round(d, 3) for sc, (_, d) in zip(sdata["scenes"], clips)]
    lang = "-".join(voice.split("-")[:2]) or "en-KE"
    framing = frame_payload(q, b)
    if framing.get("teacher"):
        from . import teacher

        ffmpeg = whiteboard.ffmpeg_binary()
        if ffmpeg:
            mouth = teacher.mouth_envelopes(ffmpeg, [a for a, _ in clips], 30)
            framing["teacher"] = {**framing["teacher"], "fps": 30, "mouth": mouth,
                                  "shapes": [teacher.visemes(str(sc.get("say") or ""), env)
                                             for sc, env in zip(sdata["scenes"], mouth)]}
    return whiteboard.page(sdata, title=title, voice=lang, durations=durations, audio=audio, social=framing)


# ── the frame ────────────────────────────────────────────────────────────────

def frame(social: dict[str, Any]) -> str:
    """The vertical page: the whiteboard page's own scripts, inside a 9:16
    frame with the hook, captions, countdown and brand."""
    logo = f'<img class="logo" src="{social["logo"]}" alt="">' if social.get("logo") else ""
    brand_line = html.escape(social.get("brand") or "")
    handle = html.escape(social.get("handle") or "")
    website = html.escape(social.get("website") or "")
    colours = (f"--bg-from:{social.get('bg_from') or '#2f4d8a'};--bg-to:{social.get('bg_to') or '#141d36'};"
               f"--accent:{social.get('accent') or '#facc15'};--ink:{social.get('text') or '#ffffff'}")
    return (_FRAME.replace("__COLOURS__", colours).replace("__LOGO__", logo).replace("__BRAND__", brand_line)
            .replace("__HOOK__", html.escape(social.get("hook") or "Can you solve this?"))
            .replace("__TAG__", html.escape(social.get("tag") or ""))
            .replace("__HANDLE__", handle).replace("__WEBSITE__", website))


_FRAME = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Patrick+Hand&family=Baloo+2:wght@600;800&display=swap" rel="stylesheet">
<style>
 :root{__COLOURS__}
 html,body{margin:0;background:var(--bg-to);font-family:'Baloo 2',system-ui,sans-serif;color:var(--ink)}
 #social{position:relative;width:1080px;height:1920px;overflow:hidden;
   background:radial-gradient(120% 70% at 50% 0%,var(--bg-from) 0%,color-mix(in srgb,var(--bg-from) 45%,var(--bg-to)) 55%,var(--bg-to) 100%)}
 body.live #social{transform-origin:top left}
 .top{position:absolute;left:60px;right:150px;top:130px}
 .chip{display:inline-flex;align-items:center;gap:14px;background:rgba(255,255,255,.12);border-radius:40px;
   padding:8px 26px 8px 10px;font-size:34px;font-weight:600}
 .chip .logo{width:56px;height:56px;border-radius:50%;object-fit:cover;background:#fff}
 .chip .dot{width:22px;height:22px;border-radius:50%;background:var(--accent);margin-left:12px}
 .hook{margin:26px 0 6px;font-size:92px;line-height:1;font-weight:800;color:var(--accent);letter-spacing:-1px}
 .tag{font-size:36px;opacity:.85;font-weight:600}
 #wb{position:absolute;left:40px;top:470px;width:960px;border-radius:22px;overflow:hidden;
   box-shadow:0 18px 40px rgba(0,0,0,.35);background:#fdfdfb}
 #sc-caption{position:absolute;left:60px;right:150px;top:1040px;min-height:300px;font-size:60px;line-height:1.18;
   font-weight:800;text-align:left;text-shadow:0 3px 0 rgba(0,0,0,.25)}
 #sc-caption .w{opacity:.55}
 #sc-caption .w.on{opacity:1;color:var(--accent)}
 #sc-caption .w.past{opacity:1}
 #sc-count{position:absolute;left:0;right:0;top:1030px;display:none;text-align:center}
 #sc-count .ring{display:inline-flex;align-items:center;justify-content:center;width:260px;height:260px;
   border-radius:50%;border:16px solid var(--accent);font-size:150px;font-weight:800;color:var(--ink);background:rgba(0,0,0,.15)}
 #sc-count .say{font-size:56px;font-weight:800;margin-top:24px}
 .foot{position:absolute;left:60px;right:150px;top:1440px;font-size:40px;font-weight:600;opacity:.95}
 .foot b{color:var(--accent)}
 body.live{background:#0f172a;overflow:hidden}
 /* The cover: the first second of the video, and its thumbnail. */
 #cover{position:absolute;inset:0;z-index:5;display:none;overflow:hidden;font-family:'Baloo 2',system-ui,sans-serif}
 #cover .rays{position:absolute;inset:-40%;background:repeating-conic-gradient(from 0deg at 50% 45%,rgba(255,255,255,.13) 0deg 9deg,transparent 9deg 18deg)}
 #cover .tag{position:absolute;left:60px;top:140px;background:#111;color:#fff;border-radius:40px;padding:10px 30px;font-size:38px;font-weight:800;letter-spacing:1px}
 #cover .hook{position:absolute;left:50px;right:140px;top:225px;margin:0;font-size:124px;line-height:.98;font-weight:800;
   -webkit-text-stroke:7px #111;paint-order:stroke fill;text-shadow:0 12px 0 rgba(0,0,0,.35);transform-origin:left center}
 #cover .emoji{position:absolute;right:150px;top:150px;font-size:130px;transform:rotate(12deg)}
 #cover .card{position:absolute;left:50px;right:150px;top:680px;background:#fff;color:#111;border-radius:34px;padding:34px 38px;
   box-shadow:0 22px 0 rgba(0,0,0,.28);font-size:52px;line-height:1.18;font-weight:700}
 #cover .card .q{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
 #cover .fig{display:none;margin:18px 0 0;height:360px;background:#fff;border-radius:18px;text-align:center}
 #cover .fig img{height:100%;max-width:100%;object-fit:contain}
 #cover.has-fig .card{font-size:44px}
 #cover.has-fig .card .q{-webkit-line-clamp:3}
 #cover.has-fig .fig{display:block}
 #cover.has-fig .sticker{top:1420px}
 #cover .chips{display:flex;flex-wrap:wrap;gap:14px;margin-top:22px}
 #cover .chips span{font-size:36px;font-weight:800;padding:8px 20px;border-radius:18px;background:#111;color:#fff}
 #cover .sticker{position:absolute;left:60px;top:1330px;background:#111;color:#fff;font-size:50px;font-weight:800;
   padding:16px 34px;border-radius:22px;transform:rotate(-4deg);box-shadow:0 10px 0 rgba(0,0,0,.3)}
 #cover .sticker b{color:var(--cover-accent)}
 /* The figure, pinned below the board while the solution is worked: the board turns pages, the figure stays. */
 #sc-fig{position:absolute;left:330px;right:60px;top:1370px;height:300px;display:none;background:#fff;border-radius:24px;
   padding:14px;box-shadow:0 14px 0 rgba(0,0,0,.25);text-align:center;z-index:3}
 #sc-fig img{height:100%;max-width:100%;object-fit:contain}
 .bar{position:fixed;left:0;right:0;bottom:0;height:54px;display:flex;gap:8px;align-items:center;justify-content:center;
   background:#0f172a}
 .bar button{font:inherit;font-size:18px;padding:4px 16px;border-radius:8px;border:0;cursor:pointer}
 .bar span{color:#cbd5e1;font-size:15px}
 .bar p{display:none}
</style></head><body class="__BODY_CLASS__">
<div id="social">
  <div id="cover"><div class="rays"></div><div class="tag"></div><h1 class="hook"></h1><div class="emoji"></div>
    <div class="card"><div class="q"></div><div class="fig"></div><div class="chips"></div></div><div class="sticker">ANSWER INSIDE <b>▶</b></div></div>
  <div class="top">
    <div class="chip">__LOGO__<span class="dot"></span><span>__BRAND__</span></div>
    <div class="hook">__HOOK__</div>
    <div class="tag">__TAG__</div>
  </div>
  <div id="wb"></div>
  <div id="sc-caption"></div>
  <div id="sc-fig"></div>
  <div id="sc-count"><div class="ring"><span id="sc-n"></span></div><div class="say">Pause and try it!</div></div>
  <div class="foot"><b>__HANDLE__</b> &nbsp; __WEBSITE__</div>
</div>
<script>__GSAP__</script>
<script>window.WB_DATA = __DATA__;</script>
<script>
 // The cover: shown for the first second (the lead-in), then it slides away.
 (function () {
   const c = (window.WB_DATA.social || {}).cover, el = document.getElementById("cover");
   if (!c || !el) return;
   const lead = window.WB_DATA.lead || 1.3, set = (s, v) => { el.querySelector(s).textContent = v; };
   el.style.background = `linear-gradient(160deg, ${c.bg_from}, ${c.bg_to})`;
   el.style.setProperty("--cover-accent", c.accent);
   set(".tag", c.tag || c.brand); set(".hook", c.hook); set(".emoji", c.emoji); set(".q", c.question);
   const hook = el.querySelector(".hook");
   hook.style.color = c.accent; hook.style.transform = `rotate(${c.tilt}deg)`;
   el.querySelector(".chips").innerHTML = (c.choices || []).map((x) => `<span>${x.replace(/[<&>]/g, "")}</span>`).join("");
   if (c.figure) {
     const img = new Image();
     img.src = c.figure;
     window.__coverReady = img.decode().catch(() => null);   // on the thumbnail, the first frame
     el.querySelector(".fig").appendChild(img);
     el.classList.add("has-fig");
   }
   if ((window.WB_DATA.social || {}).teacher) el.querySelector(".emoji").style.display = "none";
   window.__coverUntil = lead - 0.1;
   window.__onCover = (t) => {
     const out = Math.min(1, Math.max(0, (t - (lead - 0.4)) / 0.3));
     el.style.display = out >= 1 ? "none" : "block";
     el.style.opacity = String(1 - out);
     el.style.transform = `translateY(${-out * 120}px)`;
     const s = el.querySelector(".sticker");
     s.style.transform = `rotate(-4deg) scale(${1 + 0.06 * Math.sin(t * 9)})`;
   };
   window.__onCover(0);
 })();
</script>
<script>
 // The figure stays in sight from the pause to the answer: the board's
 // copy goes when the page turns, this one does not. It gives way to the
 // big teacher (the question, the check, the end card).
 (function () {
   const scenes = window.WB_DATA.scenes || [], el = document.getElementById("sc-fig");
   const at = scenes.findIndex((s) => s.scene === "figure");
   if (at < 0 || !el) return;
   const svg = String(scenes[at].svg || "");
   const img = new Image();
   img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
   el.appendChild(img);
   const BIG = { title: 1, countdown: 1, check: 1, outro: 1, figure: 1 };
   window.__onFigure = (t) => {
     const starts = window.__starts || [];
     let i = -1;
     for (let k = 0; k < starts.length; k++) if (t >= starts[k]) i = k;
     const sc = scenes[i] || {};
     const show = i > at && !BIG[sc.scene];
     const into = show ? Math.min(1, (t - starts[i]) / 0.4) : 0;
     const prev = scenes[i - 1] || {};
     const k = show && (i - 1 > at && !BIG[prev.scene]) ? 1 : into;   // already showing: no fade again
     el.style.display = k > 0 ? "block" : "none";
     el.style.opacity = String(k);
   };
 })();
</script>
<script>__ENGINE__</script>
__TEACHER__
__CONTROLS__
<script>
 // In the console the 1080×1920 frame is scaled to fit the window.
 if (document.body.classList.contains("live")) {
   const fit = () => { const k = Math.min(innerWidth / 1080, (innerHeight - 70) / 1920);
     const el = document.getElementById("social"); el.style.transform = `scale(${k})`;
     document.body.style.height = `${1920 * k + 70}px`; el.style.marginLeft = `${(innerWidth - 1080 * k) / 2}px`; };
   addEventListener("resize", fit); fit();
 }
</script>
</body></html>"""
