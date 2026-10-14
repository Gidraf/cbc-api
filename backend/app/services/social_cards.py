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
    foot = " · ".join(x for x in (b.get("name"), b.get("handle"), b.get("website")) if x)
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

    if step not in STEPS:
        raise ValueError(f"A card is one of {', '.join(STEPS)}.")
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
    if all(status(question_id, s, q)["status"] == "ready" for s in STEPS):
        return {"status": "ready"}
    link = q.get("curriculum") or {}
    job = job_queue.enqueue(JOB_KIND, str(link.get("grade") or ""), str(link.get("subject") or ""),
                            {"artifact_id": question_id, "question_id": question_id},
                            strand=str(link.get("strand") or ""), sub_strand=str(link.get("sub_strand") or ""),
                            queued_by=queued_by)
    job_queue.start_worker()
    return {"status": "queued", "job_id": job.job_id}


def run_job(job: dict[str, Any]) -> dict[str, Any]:
    qid = str((job.get("payload") or {}).get("question_id") or "")
    if not qid:
        return {"status": "skipped"}
    q = _q(qid)
    made = {step: render(qid, step, q)["status"] for step in STEPS}
    return {"status": "done", "question_id": qid, "cards": made}


# ── what each post says ──────────────────────────────────────────────────────

def caption(q: dict[str, Any], step: str, b: dict[str, Any] | None = None) -> str:
    from .grade_order import grade_label
    from .social import brand, display, hashtags

    b = b or brand()
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
