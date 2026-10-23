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
import re
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


def animated(q: dict[str, Any], step: str) -> bool:
    """A card made as a short silent animation (a GIF): for the chemistry items
    (Integrated Science) for now — the teaser like breaking news, the question
    then its options, the answer swept across."""
    return step in ANIMATED_STEPS and isinstance(q.get("chemistry"), dict)


ANIMATED_STEPS = ("teaser", "question", "answer")
SECONDS, FPS = 5.0, 12


def _key(q: dict[str, Any], step: str, b: dict[str, Any]) -> str:
    if step == "kicd":            # the design's words, not the question's: a re-ingested design is a new card
        basis = "|".join([VERSION, step, repr(sorted((k, str(v)) for k, v in design_row(q).items())),
                          repr(sorted(b.items())), repr(q.get("curriculum") or {}),
                          # a chemistry item's KICD card is narrowed to its question: its own card, not a repeat
                          str(q.get("question_text") or "") if isinstance(q.get("chemistry"), dict) else ""])
        return hashlib.sha256(basis.encode()).hexdigest()[:16]
    letter, text = _answer(q)
    basis = "|".join([VERSION, step, str(q.get("question_text") or ""), str(q.get("stimulus_context") or ""),
                      repr(q.get("options") or []), letter, text, repr(sorted(b.items())), _chem_figure(q, step),
                      ("anim2" + _chem_clip(q, step)) if animated(q, step) else ""])   # anim2: past any still a Mac kept as a GIF
    return hashlib.sha256(basis.encode()).hexdigest()[:16]


def _chem_figure(q: dict[str, Any], step: str) -> str:
    """A chemistry item's picture for its card: the set-up on the question card,
    the result on the answer card (from its animation; "" until it is made)."""
    if step not in ("question", "answer") or not isinstance(q.get("chemistry"), dict):
        return ""
    from . import chem_stills

    return chem_stills.card_image(str(q.get("question_id") or ""), q, step)


def _chem_clip(q: dict[str, Any], step: str) -> str:
    """The same picture moving (its step's run-up), for an animated card."""
    if step not in ("question", "answer") or not isinstance(q.get("chemistry"), dict):
        return ""
    from . import chem_stills

    return chem_stills.card_image(str(q.get("question_id") or ""), q, step, moving=True)


def object_name(question_id: str, step: str, key: str) -> str:
    return f"{PREFIX}/{question_id}/{step}-{key}.jpg"


# A chemistry item's step pictures as cards of the series, after the answer:
# "steps0", "steps1"… (up to four steps on a picture, with their words) and
# "anim0", "anim1"… (the same pictures animated — GIFs, which Facebook plays);
# the series carries the animated ones, the Library and comments both.
CHEM_STEP = re.compile(r"^(steps|anim)(\d)$")


def chem_steps(q: dict[str, Any]) -> list[str]:
    """The step-picture cards a chemistry item has (worked out without making them)."""
    if not isinstance(q.get("chemistry"), dict):
        return []
    from . import chem_stills

    try:
        _, _, ms, _ = chem_stills._plan(q)
    except Exception:  # noqa: BLE001
        return []
    n = len(chem_stills._groups(ms))
    return ([f"steps{g}" for g in range(n)] + [f"anim{g}" for g in range(n)]) if n else []


def series_chem_steps(q: dict[str, Any]) -> list[str]:
    """The step cards that go out in the series: the steps animated (the still
    pictures stay in the Library and the comments)."""
    return [s for s in chem_steps(q) if s.startswith("anim")]


def is_card(q: dict[str, Any], step: str) -> bool:
    return step in CARDS or step in chem_steps(q)


def status(question_id: str, step: str, q: dict[str, Any] | None = None) -> dict[str, Any]:
    from ..infra.storage import object_storage, public_object_url
    from .social import brand

    q = q or _q(question_id)
    m = CHEM_STEP.match(step)
    if m:
        from . import chem_stills

        grids = chem_stills.status(question_id, q).get("grids") or []
        g = int(m.group(2))
        key = "jpg" if m.group(1) == "steps" else "gif"
        url = grids[g].get(key) if g < len(grids) else ""
        extra = {"gif_url": url, "still_url": grids[g]["jpg"]} if url and key == "gif" and grids[g].get("jpg") else {}
        return {"status": "ready", "url": url, "object_name": grids[g][f"{key}_name"], **extra} if url else \
               {"status": "none", "object_name": grids[g][f"{key}_name"] if g < len(grids) else ""}
    name = object_name(question_id, step, _key(q, step, brand()))
    if animated(q, step):
        gif = name[:-4] + ".gif"
        if object_storage.object_exists(gif):
            return {"status": "ready", "url": public_object_url(gif), "object_name": gif, "gif_url": public_object_url(gif),
                    **({"still_url": public_object_url(name)} if object_storage.object_exists(name) else {})}
        return {"status": "none", "object_name": gif}
    if object_storage.object_exists(name):
        return {"status": "ready", "url": public_object_url(name), "object_name": name}
    return {"status": "none", "object_name": name}


# ── the cards ────────────────────────────────────────────────────────────────

def page(q: dict[str, Any], step: str, b: dict[str, Any], animate: bool = False) -> str:
    """The card as one HTML page (KaTeX from its CDN draws the maths).
    `animate`: with the card's 5-second animation (paused: window.__at(ms) sets the moment)."""
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
        still = _chem_figure(q, step)
        clip = _chem_clip(q, step) if animate else ""
        span = (0.2, 3.0) if step == "answer" else (1.4, 3.8)          # when on the card's clock it plays
        if not figure and clip:
            figure = (f"<video class='clip' src='{esc(clip)}' poster='{esc(still)}' muted playsinline preload='auto' "
                      f"data-from='{span[0]}' data-to='{span[1]}' crossorigin='anonymous' "
                      "style='width:100%;max-height:34rem;object-fit:contain;border-radius:18px;background:#fff'></video>")
        elif not figure and still:
            figure = f"<img src='{esc(still)}' alt='' style='width:100%;max-height:30rem;object-fit:contain;border-radius:18px'>"
    options = "".join(
        f"<li style='--i:{i}' class='{'right' if step == 'answer' and o.get('id') == letter else ''}'><b>{esc(o.get('id'))})</b> "
        f"<span class='m'>{esc(o.get('text'))}</span></li>"
        for i, o in enumerate(o for o in (q.get("options") or []) if isinstance(o, dict)))
    if step == "teaser":
        body = ((f"<div class='breaking'><span class='live'></span>BREAKING · NEW QUESTION</div>" if animate else "")
                + f"<div class='big'>{esc(b.get('hook') or 'Can you solve this?')}</div>"
                f"<div class='topic'>{esc(topic)}</div>"
                "<div class='soon'>🧠 The question is coming up next — get your pen ready.</div>"
                + (f"<div class='ticker'><span>{esc(('🧪 ' + topic + '  ·  a new question today  ·  try it before the answer  ·  ') * 4)}</span></div>"
                   if animate else ""))
    else:
        context = f"<p class='ctx m'>{esc(display(q.get('stimulus_context') or ''))}</p>" if q.get("stimulus_context") else ""
        fig = f"<div class='fig'>{figure}</div>" if figure else ""
        if step == "question":
            tail = "<div class='ask'>✍️ Your answer in the comments — the answer comes later today.</div>"
        else:
            steps = "".join(f"<li style='--i:{i}' class='m'>{esc(s)}</li>" for i, s in enumerate(_working(q)))
            tail = (f"<div class='ans'>✅ Answer: {esc(letter + ') ') if letter else ''}<span class='m'>{esc(answer)}</span><i class='line'></i></div>"
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
</style>{_ANIM_CSS.replace("ACCENT", b['accent']) if animate else ""}</head><body class="{('a-' + step) if animate else ''}"><div class="card">{body}</div><div class="foot">{esc(foot)}</div>
<script>
 // The animation, paused: each frame of the GIF is one moment of it.
 window.__at = function(ms){{ document.getAnimations().forEach(function(a){{ a.pause(); a.currentTime = ms; }}); }};
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


# The cards' 5-second animations (silent). Times in seconds; every animation
# fills both ways, so any moment can be set and photographed.
_ANIM_CSS = """<style>
 @keyframes slideL{from{transform:translateX(-110%)}to{transform:none}}
 @keyframes slideR{from{transform:translateX(60%);opacity:0}to{transform:none;opacity:1}}
 @keyframes up{from{transform:translateY(40px);opacity:0}to{transform:none;opacity:1}}
 @keyframes fade{from{opacity:0}to{opacity:1}}
 @keyframes dim{from{opacity:1}to{opacity:.4}}
 @keyframes reveal{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
 @keyframes pop{0%{transform:scale(.6);opacity:0}70%{transform:scale(1.08);opacity:1}100%{transform:scale(1)}}
 @keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.06)}}
 @keyframes blink{0%,100%{opacity:1}50%{opacity:.2}}
 @keyframes tick{from{transform:translateX(0)}to{transform:translateX(-50%)}}
 @keyframes sweep{from{transform:scaleX(0)}to{transform:scaleX(1)}}
 @keyframes shine{from{background-position:-150% 0}to{background-position:250% 0}}
 body[class^=a-] *,body[class^=a-] *::before,body[class^=a-] *::after{animation-fill-mode:both!important}
 .breaking{align-self:flex-start;background:#dc2626;color:#fff;font-weight:900;letter-spacing:.12em;font-size:3.4rem;
           padding:1rem 2.4rem;border-radius:10px;display:flex;align-items:center;gap:1.4rem;animation:slideL .55s 0s}
 .live{width:1.8rem;height:1.8rem;border-radius:50%;background:#fff;animation:blink 1s 0s 5 linear}
 .a-teaser .big{animation:reveal .9s .5s;background:linear-gradient(100deg,transparent 40%,rgba(255,255,255,.55) 50%,transparent 60%) no-repeat;
                background-size:60% 100%;-webkit-background-clip:text}
 .a-teaser .big::after{content:""}
 .a-teaser .topic{animation:up .5s 1.4s} .a-teaser .soon{animation:up .5s 2s}
 .ticker{overflow:hidden;white-space:nowrap;background:rgba(0,0,0,.35);border-top:4px solid ACCENT;margin:0 -72px;padding:1.4rem 0;font-size:3rem}
 .ticker span{display:inline-block;animation:tick 5s 0s linear}
 .a-question .topic{animation:fade .4s 0s} .a-question .stem{animation:reveal 1.3s .2s} .a-question .ctx{animation:fade .5s .1s}
 .a-question .fig{animation:up .5s 1.4s}
 .a-question .opts li{animation:slideR .45s calc(2s + var(--i) * .35s)}
 .a-question .ask{animation:fade .4s 3.6s, pulse .7s 4.1s}
 .a-answer .topic,.a-answer .stem,.a-answer .ctx{animation:fade .5s 0s}
 .a-answer .opts li{animation:fade .4s calc(.3s + var(--i) * .12s)}
 .a-answer .opts li:not(.right){animation:fade .4s calc(.3s + var(--i) * .12s), dim .5s 1.3s}
 .a-answer .opts li.right{position:relative;background:rgba(255,255,255,.1);color:inherit;overflow:hidden;
                          animation:fade .4s calc(.3s + var(--i) * .12s), pulse .6s 2.4s}
 .a-answer .opts li.right::before{content:"";position:absolute;inset:0;background:ACCENT;transform-origin:left;z-index:-1;
                                   animation:sweep .9s 1.4s}
 .a-answer .opts li.right{z-index:0} .a-answer .opts li.right b,.a-answer .opts li.right span{position:relative;color:#111}
 .a-answer .ans{animation:reveal .9s 2.7s;position:relative;padding-bottom:.8rem}
 .a-answer .ans .line{position:absolute;left:0;right:0;bottom:0;height:.7rem;border-radius:1rem;background:ACCENT;
                      transform-origin:left;animation:sweep 1s 3.4s}
 .a-answer .fig,.a-question .fig{position:relative} .fig video,.fig img{box-shadow:0 0 0 6px rgba(255,255,255,.12)}
 .a-answer .fig{animation:pop .6s .2s} .a-answer .work li{animation:up .4s calc(3.5s + var(--i) * .3s)}
 .a-answer .ask{animation:fade .4s 4.4s}
</style>"""


async def _shoot_animated(doc: str) -> tuple[bytes, bytes]:
    """A card's 5 seconds, frame by frame, as a silent GIF (and its last frame as a still)."""
    import subprocess
    import tempfile
    from pathlib import Path

    from .browser import open_browser
    from .whiteboard import ffmpeg_binary

    ffmpeg = ffmpeg_binary()
    async with open_browser() as browser:
        context = await browser.new_context(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        try:
            pg = await context.new_page()
            await pg.set_content(doc, wait_until="networkidle", timeout=45_000)
            try:
                await pg.wait_for_function("window.__ready === true", timeout=8_000)
            except Exception:  # noqa: BLE001
                pass
            try:                                      # the step clips loaded before the first frame
                await pg.wait_for_function("[...document.querySelectorAll('video.clip')].every(v => v.readyState >= 2)",
                                           timeout=20_000)
            except Exception:  # noqa: BLE001
                pass
            frames = []
            for i in range(int(SECONDS * FPS) + 1):
                await pg.evaluate("ms => window.__at(ms)", i * 1000 / FPS)
                # The step's own clip plays under it (a <video>, set to the same moment).
                await pg.evaluate("""ms => Promise.all([...document.querySelectorAll('video.clip')].map(v => new Promise(ok => {
                    const a = +v.dataset.from, b = +v.dataset.to, d = v.duration || 0;
                    if (!d) return ok();
                    const t = Math.max(0, Math.min(1, (ms / 1000 - a) / (b - a))) * (d - 0.05);
                    if (Math.abs(v.currentTime - t) < 0.01) return ok();
                    v.addEventListener('seeked', () => ok(), {once: true}); v.currentTime = t; setTimeout(ok, 1500); })))""",
                                  i * 1000 / FPS)
                frames.append(await pg.screenshot(type="jpeg", quality=82, full_page=False))
            still = frames[-1]
        finally:
            await context.close()
    if not ffmpeg:
        return still, b""
    with tempfile.TemporaryDirectory() as tmp:
        mp4, gif = Path(tmp) / "a.mp4", Path(tmp) / "a.gif"
        enc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg",
                                "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)], stdin=subprocess.PIPE)
        for f in frames + [still] * int(FPS * 1.5):          # then it holds on the finished card
            enc.stdin.write(f)  # type: ignore[union-attr]
        enc.stdin.close()  # type: ignore[union-attr]
        enc.wait(timeout=300)
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(mp4), "-vf",
                        f"fps={FPS},scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                        "-loop", "0", str(gif)], capture_output=True, timeout=300, check=False)
        return still, (gif.read_bytes() if gif.exists() else b"")


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

    q = q or _q(question_id)
    if CHEM_STEP.match(step):                   # made with the item's step pictures
        from . import chem_stills

        chem_stills.render(question_id, q)
        return status(question_id, step, q)
    if step not in CARDS:
        raise ValueError(f"A card is one of {', '.join(CARDS)}.")
    st = status(question_id, step, q)
    if st["status"] == "ready":
        return st
    if animated(q, step):
        still, gif = asyncio.run(_shoot_animated(page(q, step, brand(), animate=True)))
        object_storage.save_bytes(st["object_name"][:-4] + ".jpg", still, "image/jpeg")
        if gif:
            object_storage.save_bytes(st["object_name"], gif, "image/gif")
        return status(question_id, step, q)
    jpeg = asyncio.run(_shoot(page(q, step, brand())))
    object_storage.save_bytes(st["object_name"], jpeg, "image/jpeg")
    return status(question_id, step, q)


def enqueue(question_id: str, *, queued_by: str = "cards") -> dict[str, Any]:
    """Queue the cards a question does not have yet."""
    from . import job_queue

    q = _q(question_id)
    chem_ready = True
    if isinstance(q.get("chemistry"), dict):
        from . import chem_stills

        chem_ready = chem_stills.status(question_id, q)["status"] == "ready"
    if chem_ready and all(status(question_id, s, q)["status"] == "ready" for s in CARDS):
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
    stills = None
    if isinstance(q.get("chemistry"), dict):
        # The animation's pictures first: the cards show them, and the comments carry them.
        from . import chem_stills

        try:
            stills = chem_stills.render(qid, q)["status"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chemistry stills for %s failed: %s", qid, exc)
    made = {step: render(qid, step, q)["status"] for step in CARDS}
    return {"status": "done", "question_id": qid, "cards": made, **({"stills": stills} if stills else {})}


# ── what each post says ──────────────────────────────────────────────────────

# Facebook plays a GIF in a comment (a photo post may show it still): an
# animated card goes out as its finished picture, its animation the first comment.
GIF_COMMENTS = {"teaser": "▶️ Breaking — watch the question arrive 👇",
                "question": "▶️ The question, animated — then pick your answer in the comments.",
                "answer": "▶️ The answer, animated — watch it unfold."}


def gif_comment(step: str) -> str:
    """The words with an animated card's GIF in its post's first comment."""
    m = CHEM_STEP.match(step)
    if m:
        return "▶️ Every step, animated — watch each one happen."
    return GIF_COMMENTS.get(step, "▶️ Animated.")


def caption(q: dict[str, Any], step: str, b: dict[str, Any] | None = None) -> str:
    from .grade_order import grade_label
    from .social import brand, display, hashtags

    b = b or brand()
    if step == "kicd":
        return kicd_caption(q, b)
    m = CHEM_STEP.match(step)
    if m:
        n = sum(1 for x in chem_steps(q) if x.startswith("steps"))
        part = f" ({int(m.group(2)) + 1} of {n})" if n > 1 else ""
        head = (f"🧩 Every step of the answer{part} — save it for revision." if m.group(1) == "steps"
                else f"🎞️ The steps, animated{part} — watch each one happen.")
        lines = [head, "", display(q.get("question_text") or "")]
        if b.get("website"):
            lines += ["", f"🌐 {b['website']}"]
        lines += ["", " ".join(hashtags(q, b))]
        return "\n".join(lines).strip() + "\n"
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


_STOP = set("the a an of to and in on for is are be by with as at or from this that which what how why its it their "
             "learner learners should able use using during e g eg such".split())


def _words(t: str) -> set[str]:
    return {w[:7] for w in re.findall(r"[a-z]{3,}", t.lower()) if w not in _STOP}


def focused(q: dict[str, Any], items: list[str], n: int) -> list[str]:
    """The design's lines nearest this question (its words, its substances and
    methods), best first — so a chemistry item's KICD card is about its own
    question, not the same whole sub-strand each time. Kept in the design's order."""
    if not items:
        return []
    chem = q.get("chemistry") if isinstance(q.get("chemistry"), dict) else {}
    want = _words(" ".join([str(q.get("question_text") or ""), str(q.get("correct_answer") or ""),
                            " ".join(str(v) for v in chem.values() if isinstance(v, (str, list)))]).replace("_", " "))
    ranked = sorted(range(len(items)), key=lambda i: (-len(_words(items[i]) & want), i))
    return [items[i] for i in sorted(ranked[:n])]


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
    narrow = isinstance(q.get("chemistry"), dict)       # about this question only
    slos = focused(q, _texts(row.get("slos")), 2) if narrow else _texts(row.get("slos"))[:5]
    exps = focused(q, _texts(row.get("learning_experiences")), 2) if narrow else _texts(row.get("learning_experiences"))[:4]
    kiqs = focused(q, _texts(row.get("key_inquiry_questions")), 1) if narrow else _texts(row.get("key_inquiry_questions"))[:3]
    asked = str(q.get("question_text") or "") if narrow else ""
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
   <h1>{esc(grade)} {esc(subject)}</h1><h2>{"The outcome this question tests" if narrow else "Where today's question comes from"} — quoted from the design</h2></div>
 <div class="body">
  <table>
   <tr><th>Strand</th><th>Sub-strand</th></tr>
   <tr><td><b>{esc(strand)}</b></td><td><b>{esc(sub)}</b>{f" ({esc(hours)})" if hours and len(hours) < 30 else ""}</td></tr>
  </table>
  <table>
   {f"<tr><td class='lbl'>Today's question</td><td><b>{esc(asked)}</b></td></tr>" if asked else ""}
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
    slos = focused(q, _texts(row.get("slos")), 2) if isinstance(q.get("chemistry"), dict) else _texts(row.get("slos"))[:3]
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
