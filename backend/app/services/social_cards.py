"""Photo posts: one question told in steps, to keep an audience coming back.

A question becomes a short series spread through a day:

    teaser    a card: "Can you solve this?" — the topic, the grade, no question yet
    question  the question (and its figure, its options), no answer
    answer    the question again with the answer marked and the first steps of the working
    (video)   then the whiteboard walkthrough, posted as the video it already is

Each card is 1080×1350 (the portrait size Facebook and Instagram show
largest), in the brand's colours, drawn as HTML and photographed by the same
Chromium the papers print in. Cards are stored per (question, step, content)
and made once; a changed question or brand makes new ones.
"""
from __future__ import annotations

import hashlib
import html
import logging
from typing import Any

logger = logging.getLogger("cbc-social-cards")

JOB_KIND = "social_card"
PREFIX = "social_cards"
STEPS = ("teaser", "question", "answer")
# Every card a question has: the series' three, and the KICD card — the page
# of the curriculum design the question comes from (in the series and the
# first comments).
CARDS = STEPS + ("kicd",)
VERSION = "c2"
WIDTH, HEIGHT = 1080, 1350


def _q(question_id: str) -> dict[str, Any]:
    from .whiteboard import load

    return load(question_id)


def _answer(q: dict[str, Any]) -> tuple[str, str]:
    """(the option letter or "", the answer text)."""
    key = next((o for o in (q.get("options") or []) if isinstance(o, dict) and o.get("is_correct")), None)
    if key:
        return str(key.get("id") or ""), str(key.get("text") or "")
    return "", str(q.get("correct_answer") or "")


def _working(q: dict[str, Any], limit: int = 3) -> list[str]:
    from . import play_engine
    from .social import _steps

    try:
        data = play_engine.walkthrough(q, grade=str((q.get("curriculum") or {}).get("grade") or ""))
        return _steps(data.get("scenes") or [])[:limit]
    except Exception:  # noqa: BLE001
        return []


def _key(q: dict[str, Any], step: str, b: dict[str, Any]) -> str:
    if step == "kicd":            # the design's words, not the question's: a re-ingested design is a new card
        basis = "|".join([VERSION, step, repr(sorted((k, str(v)) for k, v in design_row(q).items())),
                          repr(sorted(b.items())), repr(q.get("curriculum") or {})])
        return hashlib.sha256(basis.encode()).hexdigest()[:16]
    letter, text = _answer(q)
    basis = "|".join([VERSION, step, str(q.get("question_text") or ""), str(q.get("stimulus_context") or ""),
                      repr(q.get("options") or []), letter, text, repr(sorted(b.items()))])
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def object_name(question_id: str, step: str, key: str) -> str:
    return f"{PREFIX}/{question_id}/{step}-{key}.jpg"


def status(question_id: str, step: str, q: dict[str, Any] | None = None) -> dict[str, Any]:
    from ..infra.storage import object_storage, public_object_url
    from .social import brand

    q = q or _q(question_id)
    name = object_name(question_id, step, _key(q, step, brand()))
    if object_storage.object_exists(name):
        return {"status": "ready", "url": public_object_url(name), "object_name": name}
    return {"status": "none", "object_name": name}


# ── the cards ────────────────────────────────────────────────────────────────

def page(q: dict[str, Any], step: str, b: dict[str, Any]) -> str:
    """The card as one HTML page (KaTeX from its CDN draws the maths)."""
    if step == "kicd":
        return kicd_page(q, b)
    from .grade_order import grade_label
    from .question_paper import figure_markup, figures_for
    from .social import display

    esc = lambda t: html.escape(str(t or ""))  # noqa: E731
    link = q.get("curriculum") or {}
    topic = " · ".join(x for x in (grade_label(str(link.get("grade") or "")), str(link.get("subject") or ""),
                                   str(link.get("sub_strand") or "")) if x)
    letter, answer = _answer(q)
    figure = ""
    if step in ("question", "answer"):
        try:
            figure = figure_markup(q, figures_for([q]), answers=False) or ""
        except Exception:  # noqa: BLE001
            figure = ""
    options = "".join(
        f"<li class='{'right' if step == 'answer' and o.get('id') == letter else ''}'><b>{esc(o.get('id'))})</b> "
        f"<span class='m'>{esc(o.get('text'))}</span></li>"
        for o in (q.get("options") or []) if isinstance(o, dict))
    if step == "teaser":
        body = (f"<div class='big'>{esc(b.get('hook') or 'Can you solve this?')}</div>"
                f"<div class='topic'>{esc(topic)}</div>"
                "<div class='soon'>🧠 The question is coming up next — get your pen ready.</div>")
    else:
        context = f"<p class='ctx m'>{esc(display(q.get('stimulus_context') or ''))}</p>" if q.get("stimulus_context") else ""
        fig = f"<div class='fig'>{figure}</div>" if figure else ""
        if step == "question":
            tail = "<div class='ask'>✍️ Your answer in the comments — the answer comes later today.</div>"
        else:
            steps = "".join(f"<li class='m'>{esc(s)}</li>" for s in _working(q))
            tail = (f"<div class='ans'>✅ Answer: {esc(letter + ') ') if letter else ''}<span class='m'>{esc(answer)}</span></div>"
                    + (f"<ol class='work'>{steps}</ol>" if steps else "")
                    + "<div class='ask'>🎬 The full walkthrough video is next.</div>")
        body = (f"<div class='topic small'>{esc(topic)}</div>{context}"
                f"<p class='stem m'>{esc(display(q.get('question_text') or ''))}</p>{fig}"
                + (f"<ul class='opts'>{options}</ul>" if options else "") + tail)
    from .social import brand_name

    foot = " · ".join(x for x in (brand_name(b, q), b.get("handle"), b.get("website")) if x)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.11/dist/contrib/auto-render.min.js"></script>
<style>
 *{{box-sizing:border-box}} html{{font-size:10px}} html,body{{margin:0;width:{WIDTH}px;height:{HEIGHT}px}}
 body{{background:linear-gradient(160deg,{b['bg_from']},{b['bg_to']});color:{b['text']};
      font-family:'Inter','Segoe UI',system-ui,sans-serif;display:flex;flex-direction:column;padding:70px 72px 50px}}
 .card{{flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column;justify-content:center;gap:2.4rem}}
 .big{{font-size:11rem;font-weight:800;line-height:1.05;color:{b['accent']}}}
 .topic{{font-size:4.2rem;opacity:.9}} .topic.small{{font-size:3rem;opacity:.75}}
 .soon,.ask{{font-size:3.6rem;opacity:.95}} .ctx{{font-size:3.3rem;opacity:.85;margin:0}}
 .stem{{font-size:4.8rem;font-weight:650;line-height:1.25;margin:0}}
 .fig{{background:#fff;border-radius:22px;padding:1.6rem;display:flex;justify-content:center;flex-shrink:0}}
 .fig svg{{max-height:{'26' if step == 'answer' else '40'}rem;width:auto;max-width:100%}}
 .opts{{list-style:none;padding:0;margin:0;display:grid;gap:1rem;font-size:3.8rem}}
 .opts li{{background:rgba(255,255,255,.1);border-radius:16px;padding:.9rem 2rem}}
 .opts li.right{{background:{b['accent']};color:#111}}
 .ans{{font-size:4.6rem;font-weight:750;color:{b['accent']}}}
 .work{{font-size:3.3rem;margin:0;padding-left:4.4rem;display:grid;gap:.5rem;opacity:.95}}
 .foot{{font-size:28px;opacity:.75;text-align:center;flex-shrink:0;padding-top:16px}}
</style></head><body><div class="card">{body}</div><div class="foot">{esc(foot)}</div>
<script>
 document.querySelectorAll('.m').forEach(function(el){{ try {{ renderMathInElement(el, {{delimiters:[{{left:'$',right:'$',display:false}}], throwOnError:false}}); }} catch(e){{}} }});
 // Long questions shrink to fit the card: everything is sized from one root size.
 (function fit(){{
   var card = document.querySelector('.card'), size = 10;
   while (card.scrollHeight > card.clientHeight + 2 && size > 5.2) {{
     size -= 0.3; document.documentElement.style.fontSize = size + 'px';
   }}
 }})();
 window.__ready = true;
</script></body></html>"""


async def _shoot(doc: str) -> bytes:
    from .browser import open_browser

    async with open_browser() as browser:
        context = await browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        try:
            pg = await context.new_page()
            await pg.set_content(doc, wait_until="networkidle", timeout=45_000)
            try:
                await pg.wait_for_function("window.__ready === true", timeout=8_000)
            except Exception:  # noqa: BLE001
                pass
            return await pg.screenshot(type="jpeg", quality=90, full_page=False)
        finally:
            await context.close()


def render(question_id: str, step: str, q: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make one card (or find it made). Returns its status."""
    import asyncio

    from ..infra.storage import object_storage
    from .social import brand

    if step not in CARDS:
        raise ValueError(f"A card is one of {', '.join(CARDS)}.")
    q = q or _q(question_id)
    st = status(question_id, step, q)
    if st["status"] == "ready":
        return st
    jpeg = asyncio.run(_shoot(page(q, step, brand())))
    object_storage.save_bytes(st["object_name"], jpeg, "image/jpeg")
    return status(question_id, step, q)


def enqueue(question_id: str, *, queued_by: str = "cards") -> dict[str, Any]:
    """Queue the cards a question does not have yet."""
    from . import job_queue

    q = _q(question_id)
    if all(status(question_id, s, q)["status"] == "ready" for s in CARDS):
        return {"status": "ready"}
    link = q.get("curriculum") or {}
    job = job_queue.enqueue(JOB_KIND, str(link.get("grade") or ""), str(link.get("subject") or ""),
                            {"artifact_id": question_id, "question_id": question_id},
                            strand=str(link.get("strand") or ""), sub_strand=str(link.get("sub_strand") or ""),
                            queued_by=queued_by)
    job_queue.dispatch(job.job_id)          # the render runs in the worker, not in the API
    return {"status": "queued", "job_id": job.job_id}


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    qid = str((job.get("payload") or {}).get("question_id") or "")
    if not qid:
        return {"status": "skipped"}
    q = _q(qid)
    made = {step: render(qid, step, q)["status"] for step in CARDS}
    return {"status": "done", "question_id": qid, "cards": made}


# ── what each post says ──────────────────────────────────────────────────────

def caption(q: dict[str, Any], step: str, b: dict[str, Any] | None = None) -> str:
    from .grade_order import grade_label
    from .social import brand, display, hashtags

    b = b or brand()
    if step == "kicd":
        return kicd_caption(q, b)
    link = q.get("curriculum") or {}
    topic = " · ".join(x for x in (grade_label(str(link.get("grade") or "")), str(link.get("subject") or ""),
                                   str(link.get("sub_strand") or "")) if x)
    letter, answer = _answer(q)
    tags = " ".join(hashtags(q, b))
    follow = f"📚 {b['cta']}" + (f" — {b['handle']}" if b.get("handle") else "")
    if step == "teaser":
        lines = [f"🤔 {b.get('hook') or 'Can you solve this?'}", f"{topic}" if topic else "",
                 "", "A new question is coming up today. Get your pen ready ✍️ — and tag a friend who loves a challenge!"]
    elif step == "question":
        lines = [f"🧮 {b.get('hook') or 'Can you solve this?'}", ""]
        if q.get("stimulus_context"):
            lines += [display(q.get("stimulus_context")), ""]
        lines.append(display(q.get("question_text") or ""))
        for o in q.get("options") or []:
            if isinstance(o, dict):
                lines.append(f"{o.get('id')}) {display(o.get('text'))}")
        lines += ["", "💬 Drop your answer in the comments — the answer comes later today!"]
    else:
        lines = [f"✅ The answer: {letter + ') ' if letter else ''}{display(answer)}", ""]
        steps = _working(q)
        if steps:
            lines += ["💡 How:"] + [f"{n}. {s}" for n, s in enumerate(steps, 1)] + [""]
        lines.append("Did you get it right? 🎬 The full walkthrough video is coming next!")
    lines += ["", follow] + ([f"🌐 {b['website']}"] if b.get("website") else []) + ["", tags]
    return "\n".join(x for x in lines if x is not None).strip() + "\n"


# ── the KICD card: where the question comes from ─────────────────────────────

def design_row(q: dict[str, Any]) -> dict[str, Any]:
    """The sub-strand as the KICD curriculum design states it (the ingested design)."""
    from ..infra.db import fetch_one

    link = q.get("curriculum") or {}
    try:
        return fetch_one("""SELECT s.strand_name, s.sub_strand_name, s.allocated_hours, s.slos, s.learning_experiences,
                                   s.key_inquiry_questions, s.core_competencies, s.values, s.pertinent_contemporary_issues,
                                   s.link_to_other_learning_areas, s.source_pages
                            FROM curriculum_substrands s
                            WHERE LOWER(s.grade) = LOWER(:g) AND LOWER(s.subject) = LOWER(:s)
                              AND LOWER(s.sub_strand_name) = LOWER(:ss) LIMIT 1""",
                         {"g": str(link.get("grade") or ""), "s": str(link.get("subject") or ""),
                          "ss": str(link.get("sub_strand") or "")}) or {}
    except Exception:  # noqa: BLE001
        return {}


def kicd_page(q: dict[str, Any], b: dict[str, Any]) -> str:
    """A page in the manner of the KICD design itself: the learning area and
    grade at the head, then the design's own table for this sub-strand —
    strand, sub-strand, specific learning outcomes, suggested learning
    experiences, key inquiry questions — with its competencies and values,
    the pages it comes from, and KICD's credit."""
    from .grade_order import grade_label
    from .social import KICD_DESIGNS, _pages, _texts

    esc = lambda t: html.escape(str(t or ""))  # noqa: E731
    link = q.get("curriculum") or {}
    row = design_row(q)
    grade = grade_label(str(link.get("grade") or ""))
    subject = str(link.get("subject") or "")
    strand = str(row.get("strand_name") or link.get("strand") or "")
    sub = str(row.get("sub_strand_name") or link.get("sub_strand") or "")
    slos = _texts(row.get("slos"))[:5]
    exps = _texts(row.get("learning_experiences"))[:4]
    kiqs = _texts(row.get("key_inquiry_questions"))[:3]
    comps = _texts(row.get("core_competencies"))[:3]
    vals = _texts(row.get("values"))[:3]
    pages = _pages(row.get("source_pages") or [])
    hours = str(row.get("allocated_hours") or "")
    letters = "abcdefgh"
    ol = lambda items: "".join(f"<li><b>{letters[k]})</b> {esc(t)}</li>" for k, t in enumerate(items))  # noqa: E731
    extra = "".join(
        f"<div class='box'><h3>{title}</h3><p>{esc('; '.join(items))}</p></div>"
        for title, items in (("Core competencies to be developed", comps), ("Values", vals)) if items)
    source = (f"Source: KICD {grade} {subject} Curriculum Design" + (f", {pages}" if pages else "")
              + ". © Kenya Institute of Curriculum Development.")
    from .social import brand_name

    foot = " · ".join(x for x in (brand_name(b, subject=str(subject)), b.get("website")) if x)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
 *{{box-sizing:border-box}} html{{font-size:10px}} html,body{{margin:0;width:{WIDTH}px;height:{HEIGHT}px}}
 body{{background:#e9e6df;font-family:'Times New Roman',Georgia,serif;color:#111;padding:44px}}
 .paper{{background:#fff;height:100%;box-shadow:0 10px 40px rgba(0,0,0,.25);padding:52px 56px 34px;display:flex;flex-direction:column}}
 .head{{text-align:center;border-bottom:3px double #111;padding-bottom:1.6rem}}
 .kicd{{font-family:'Inter','Segoe UI',sans-serif;font-size:2.2rem;letter-spacing:.3em;font-weight:700;color:#7a1f1f}}
 h1{{font-size:4.4rem;margin:.8rem 0 .2rem;text-transform:uppercase}}
 h2{{font-size:2.8rem;margin:0;font-weight:400;font-style:italic}}
 .body{{flex:1;min-height:0;overflow:hidden;display:flex;flex-direction:column;gap:1.6rem;margin-top:2rem}}
 table{{border-collapse:collapse;width:100%;font-size:2.35rem;line-height:1.3}}
 th{{background:#efe9dc;font-family:'Inter','Segoe UI',sans-serif;font-size:1.9rem;text-transform:uppercase;letter-spacing:.06em}}
 th,td{{border:2px solid #222;padding:1rem 1.1rem;vertical-align:top;text-align:left}}
 td.lbl{{width:24%;font-weight:700}}
 ol{{list-style:none;margin:0;padding:0;display:grid;gap:.5rem}}
 .box{{border:2px solid #222;padding:1rem 1.2rem}} .box h3{{margin:0 0 .4rem;font-size:2.2rem;font-family:'Inter','Segoe UI',sans-serif}}
 .box p{{margin:0;font-size:2.3rem}}
 .src{{font-size:1.9rem;font-style:italic;border-top:1px solid #999;padding-top:1rem;margin-top:1.2rem}}
 .foot{{font-family:'Inter','Segoe UI',sans-serif;font-size:1.8rem;color:#555;text-align:center;margin-top:.6rem}}
</style></head><body><div class="paper">
 <div class="head"><div class="kicd">FROM THE KICD CURRICULUM DESIGN</div>
   <h1>{esc(grade)} {esc(subject)}</h1><h2>Where today's question comes from — quoted from the design</h2></div>
 <div class="body">
  <table>
   <tr><th>Strand</th><th>Sub-strand</th></tr>
   <tr><td><b>{esc(strand)}</b></td><td><b>{esc(sub)}</b>{f" ({esc(hours)})" if hours and len(hours) < 30 else ""}</td></tr>
  </table>
  <table>
   {f"<tr><td class='lbl'>Specific learning outcomes</td><td><i>By the end of the sub-strand, the learner should be able to:</i><ol>{ol(slos)}</ol></td></tr>" if slos else ""}
   {f"<tr><td class='lbl'>Suggested learning experiences</td><td><ol>{ol(exps)}</ol></td></tr>" if exps else ""}
   {f"<tr><td class='lbl'>Key inquiry question(s)</td><td><ol>{''.join(f'<li>{esc(t)}</li>' for t in kiqs)}</ol></td></tr>" if kiqs else ""}
  </table>
  {extra}
 </div>
 <div class="src">{esc(source)} All designs: {esc(KICD_DESIGNS)}</div>
 <div class="foot">{esc(foot)}</div>
</div>
<script>
 (function fit(){{
   var body = document.querySelector('.body'), size = 10;
   while (body.scrollHeight > body.clientHeight + 2 && size > 5.6) {{
     size -= 0.25; document.documentElement.style.fontSize = size + 'px';
   }}
 }})();
 window.__ready = true;
</script></body></html>"""


def kicd_caption(q: dict[str, Any], b: dict[str, Any] | None = None) -> str:
    """The words with the KICD card: the sub-strand, its outcomes, and the source."""
    from .grade_order import grade_label
    from .social import KICD_DESIGNS, _pages, _texts, brand, hashtags

    b = b or brand()
    link = q.get("curriculum") or {}
    row = design_row(q)
    grade, subject = grade_label(str(link.get("grade") or "")), str(link.get("subject") or "")
    sub = str(row.get("sub_strand_name") or link.get("sub_strand") or "")
    slos = _texts(row.get("slos"))[:3]
    pages = _pages(row.get("source_pages") or [])
    lines = [f"📘 Straight from the KICD curriculum design — {grade} {subject}, {sub}", ""]
    if slos:
        lines += ["By the end of this sub-strand, the learner should be able to:"] + [f"• {s}" for s in slos] + [""]
    lines += [f"Source: KICD {grade} {subject} Curriculum Design" + (f", {pages}" if pages else "")
              + ". © Kenya Institute of Curriculum Development.", f"All designs: {KICD_DESIGNS}"]
    if b.get("website"):
        lines += ["", f"🌐 {b['website']}"]
    lines += ["", " ".join(hashtags(q, b))]
    return "\n".join(lines).strip() + "\n"


def kicd_comment(q: dict[str, Any]) -> str:
    """The comment that carries the KICD card: short, with the source."""
    from .grade_order import grade_label
    from .social import KICD_DESIGNS, _pages

    link = q.get("curriculum") or {}
    row = design_row(q)
    grade, subject = grade_label(str(link.get("grade") or "")), str(link.get("subject") or "")
    sub = str(row.get("sub_strand_name") or link.get("sub_strand") or "")
    pages = _pages(row.get("source_pages") or [])
    return (f"📘 Straight from the KICD curriculum design: {grade} {subject} — {sub}"
            + (f" ({pages})" if pages else "") + f". © Kenya Institute of Curriculum Development. All designs: {KICD_DESIGNS}")
