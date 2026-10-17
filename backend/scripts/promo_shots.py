"""Screens of the real console for the marketing videos — taken locally.

    cd frontend-web && npx vite build --outDir /tmp/promo-dist
    python backend/scripts/promo_shots.py /tmp/promo-dist backend/app/static/promo

The built console is served inside Playwright on a local name and its API
answered with sample data (a teacher, a paper, a test, a class), so no
account, password or server is involved. Each screen is a 1280×720 PNG — the
whiteboard's own size — and its call-out (what the hand points at) goes to
promo/shots.json as a box on that board.
"""
from __future__ import annotations

import json
import mimetypes
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

HOST = "http://promo.localhost"
NOW = "2026-10-17T08:00:00Z"
TEACHER = "mwalimu.achieng"

QUESTIONS = [
    ("Wanjiru bought 3 exercise books at KSh 45 each and a pen at KSh 20. How much did she spend?", "multiple_choice", "Money"),
    ("Work out: 2 457 + 3 896", "numeric", "Addition"),
    ("A rectangular garden is 12 m long and 8 m wide. Find its perimeter.", "multiple_choice", "Length"),
    ("Which fraction is equivalent to 3/4?", "multiple_choice", "Fractions"),
    ("Explain why 0.5 and 1/2 are the same number.", "short_answer", "Decimals"),
    ("The angle shown is a right angle. What is its size in degrees?", "multiple_choice", "Angles"),
    ("Round 7 864 to the nearest hundred.", "numeric", "Whole numbers"),
    ("A bus carries 64 pupils. How many buses are needed for 300 pupils?", "numeric", "Division"),
]


def draft(n_items: int = 8) -> dict:
    return {"draft_id": "d1", "owner": TEACHER, "title": "Grade 6 Mathematics — End of Term 2", "grade": "grade-6",
            "subject": "Mathematics", "kind": "end_term", "term": 2, "scope": {"mode": "smart"},
            "items": [{"question_id": f"q{k}", "overrides": {}} for k in range(n_items)], "snapshot": {},
            "settings": {}, "status": "draft", "exam_id": None, "created_at": NOW, "updated_at": NOW,
            "item_count": n_items}


def item(k: int) -> dict:
    text, kind, sub = QUESTIONS[k % len(QUESTIONS)]
    return {"question_id": f"q{k}", "question": {"question_text": text, "question_type": kind, "diagram": k == 5},
            "overrides": {}, "curriculum": {"sub_strand": sub}, "pedagogy": {"max_marks": 2 if kind == "short_answer" else 1},
            "provenance": {}, "review_audit": {}, "working": {"source": "", "answer": "", "steps": []}, "findings": [], "rung": ""}


PAPER = """<html><body style="font-family:'Times New Roman',serif;margin:28px 36px;color:#111">
<div style="text-align:center"><b style="font-size:20px">KAMUKUNJI PRIMARY SCHOOL</b><br>
<span style="font-size:16px">GRADE 6 MATHEMATICS — END OF TERM 2 EXAMINATION</span><br>
<span style="font-size:13px">Time: 1 hour 30 minutes</span></div>
<p style="font-size:13px">Name: ____________________________ &nbsp; Class: ________ &nbsp; Adm No: ______</p>
<hr><ol style="font-size:14px;line-height:1.7">
<li>Wanjiru bought 3 exercise books at KSh 45 each and a pen at KSh 20. How much did she spend?<br>
&nbsp; A. KSh 135 &nbsp; B. KSh 155 &nbsp; C. KSh 65 &nbsp; D. KSh 175</li>
<li>Work out: 2 457 + 3 896 ______________________</li>
<li>A rectangular garden is 12 m long and 8 m wide. Find its perimeter.<br>
&nbsp; A. 20 m &nbsp; B. 40 m &nbsp; C. 96 m &nbsp; D. 48 m</li>
<li>Which fraction is equivalent to 3/4?<br>&nbsp; A. 6/8 &nbsp; B. 4/3 &nbsp; C. 3/8 &nbsp; D. 9/16</li>
<li>Explain why 0.5 and 1/2 are the same number. <i>(2 marks)</i><br>_________________________________________</li>
<li>The angle shown is a right angle. What is its size in degrees?<br>
<svg width="120" height="80"><line x1="20" y1="70" x2="110" y2="70" stroke="#111" stroke-width="2"/><line x1="20" y1="70" x2="20" y2="8" stroke="#111" stroke-width="2"/><rect x="20" y="58" width="12" height="12" fill="none" stroke="#111"/></svg></li>
</ol></body></html>"""

TEST = {"test_id": "t1", "title": "Grade 6 Mathematics — End of Term 2", "code": "K7Q2MX", "per_student": 8, "minutes": 40,
        "show_answers": "after_submit", "shuffle_options": True, "status": "open", "pool_size": 8, "created_at": NOW,
        "closes_at": "2026-10-31T08:00:00Z", "draft_id": "d1", "started": 34, "handed_in": 31}

STUDENT_QS = [{"question_id": f"q{k}", "type": "multiple_choice" if k in (0, 2, 3) else "numeric", "context": "",
               "question": QUESTIONS[k][0], "marks": 1, "figure": "",
               "options": ([{"letter": l, "text": t} for l, t in zip("ABCD", ["KSh 135", "KSh 155", "KSh 65", "KSh 175"])] if k == 0 else
                           [{"letter": l, "text": t} for l, t in zip("ABCD", ["20 m", "40 m", "96 m", "48 m"])] if k == 2 else
                           [{"letter": l, "text": t} for l, t in zip("ABCD", ["6/8", "4/3", "3/8", "9/16"])] if k == 3 else []),
               "parts": []} for k in (0, 1, 2, 3)]

NAMES = ["Juma Otieno", "Nekesa Wafula", "Kamau Njoroge", "Wanjiku Mwangi", "Amina Hassan", "Baraka Kiprop", "Zawadi Mutua"]
RESULTS = {"test": TEST, "questions": {"q4": {"question": QUESTIONS[4][0], "answer": "They are both one half.",
                                              "marking_scheme": "1 mark: 0.5 = 5/10; 1 mark: 5/10 = 1/2", "marks": 2}},
           "attempts": [{"attempt_id": f"a{k}", "name": n, "score": [8, 7, 9, 6, 8, 5, 7][k], "out_of": 9, "late": False,
                         "submitted": True, "to_mark": ([{"question_id": "q4", "given": "Because 5 tenths is half of ten tenths", "out_of": 2}]
                                                        if k == 1 else [])} for k, n in enumerate(NAMES)]}


def api(method: str, path: str, query: str) -> object:
    if path == "/api/v1/auth/email":
        return {"email": "achieng@example.com", "email_verified": True}
    if path == "/api/v1/admin/langfuse/datasets":
        return {"datasets": [{"name": f"Grade {g}", "slug": f"grade-{g}", "label": f"Grade {g}", "level": "primary",
                              "ordinal": g, "has_data": True} for g in range(1, 10)]}
    if re.fullmatch(r"/api/v1/admin/langfuse/datasets/[^/]+/subjects", path):
        return {"subjects": [{"name": s, "ingested": True} for s in ("Mathematics", "English", "Science and Technology",
                                                                     "Kiswahili", "Social Studies")]}
    if path == "/api/v1/builder/kinds":
        return {"kinds": {"end_term": "End of term", "mid_term": "Mid-term", "topical": "Topical", "opener": "Opener"},
                "print_presets": {}}
    if path == "/api/v1/builder/drafts":
        return {"drafts": [draft()]} if STATE["papers"] else {"drafts": []}
    if path == "/api/v1/builder/drafts/d1":
        return draft()
    if path == "/api/v1/builder/drafts/d1/items":
        return {"items": [item(k) for k in range(8)]}
    if path == "/api/v1/builder/drafts/d1/bank":
        return {"sub_strands": [{"strand": "Numbers", "sub_strand": s, "items": n, "with_figures": f, "held": 0,
                                 "has_notes": True, "writing": None}
                                for s, n, f in (("Whole numbers", 46, 3), ("Fractions", 38, 9), ("Decimals", 27, 2),
                                                ("Money", 31, 1), ("Length", 22, 8), ("Angles", 19, 12))]}
    if path == "/api/v1/builder/drafts/d1/quote":
        return {"exempt": False, "paid": True, "total_ksh": 0, "unpaid": 0, "owned": 8, "free": 8, "free_left": 2,
                "prices": WALLET["prices"]}
    if path.startswith("/api/v1/builder/drafts/d1/preview.html"):
        return PAPER
    if path == "/api/v1/billing/wallet":
        return WALLET
    if path == "/api/v1/classroom/tests":
        return {"tests": [TEST]} if STATE["tests"] else {"tests": []}
    if path == "/api/v1/classroom/tests/t1/results":
        return RESULTS
    if path == "/api/v1/tests/K7Q2MX":
        return {"code": "K7Q2MX", "title": TEST["title"], "minutes": 40, "questions": 8, "open": True}
    if path == "/api/v1/tests/K7Q2MX/start":
        return {"token": "tok", "title": TEST["title"], "minutes": 40, "name": "Nekesa Wafula", "questions": STUDENT_QS,
                "started_at": NOW}
    if path == "/api/v1/tests/attempts/tok/submit":
        return {"submitted": True, "name": "Nekesa Wafula", "title": TEST["title"], "score": 7, "out_of": 8, "to_mark": 1,
                "answers_shown": True, "late": False,
                "items": [{"question_id": q["question_id"], "status": "right" if k != 2 else "wrong", "score": 1 if k != 2 else 0,
                           "out_of": 1, "given": "", "question": q["question"], "answer": "", "right_letter": "B" if k == 2 else None}
                          for k, q in enumerate(STUDENT_QS)]}
    return {}


WALLET = {"owner": TEACHER, "exempt": False, "balance_ksh": 250, "free_questions_left": 2,
          "api": {"calls_today": 0, "calls_this_month": 0, "free_left_today": 0, "charged_this_month_ksh": 0, "balance_ksh": 0, "prices": {}},
          "prices": {"paper": {"text_ksh": 5, "diagram_ksh": 8, "free_questions": 10},
                     "api": {"text_ksh": 1.5, "diagram_ksh": 2.5, "free_calls_per_day": 100, "free_calls_per_month": 1000},
                     "topup": {"min_ksh": 10, "max_ksh": 150000}},
          "topups_ready": True, "topups_note": "", "entries": []}
STATE = {"papers": True, "tests": True}


def serve(dist: Path):
    def handle(route):
        url = route.request.url
        rest = url[len(HOST):]
        path, _, query = rest.partition("?")
        if path.startswith(("/api", "/admin", "/auth", "/generate", "/health")):
            body = api(route.request.method, path, query)
            if isinstance(body, str):
                return route.fulfill(status=200, content_type="text/html", body=body)
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        f = dist / path.lstrip("/")
        if not f.is_file():
            f = dist / "index.html"
        route.fulfill(status=200, body=f.read_bytes(), content_type=mimetypes.guess_type(str(f))[0] or "text/html")
    return handle


def box(page: Page, selector: str) -> list[int]:
    """Where an element is, in board pixels (the screen is the board, 1280×720)."""
    b = page.locator(selector).first.bounding_box()
    return [round(b["x"]), round(b["y"]), round(b["width"]), round(b["height"])] if b else [0, 0, 0, 0]


def main() -> None:
    dist, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    shots: dict[str, dict] = {}
    signed_in = (f"localStorage.setItem('cbc_token','x.eyJleHAiOjk5OTk5OTk5OTl9.y');"
                 f"localStorage.setItem('cbc_role','user');localStorage.setItem('cbc_username','{TEACHER}')")
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)

        def context(auth: bool):
            ctx = br.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
            ctx.route(f"{HOST}/**", serve(dist))
            if auth:
                ctx.add_init_script(signed_in)
            return ctx

        def take(page: Page, name: str, target: str, top: bool = False) -> None:
            page.wait_for_timeout(900)
            if top:
                page.evaluate("window.scrollTo(0, 0); document.querySelectorAll('main, [style*=overflow]').forEach(e => e.scrollTop = 0)")
            elif target:
                page.locator(target).first.evaluate("e => e.scrollIntoView({block: 'center'})")
                page.wait_for_timeout(300)
            page.screenshot(path=str(out / f"{name}.png"))
            shots[name] = {"box": box(page, target) if target else [0, 0, 0, 0]}

        # 1. Sign up: a parent or a teacher.
        ctx = context(False)
        pg = ctx.new_page()
        pg.goto(HOST + "/")
        pg.get_by_role("tab", name="Create an account").click()
        pg.get_by_label("Email").fill("achieng@example.com")
        pg.get_by_label("Username").fill(TEACHER)
        pg.get_by_label("Password").fill("x" * 12)
        pg.evaluate("document.body.style.zoom = '0.86'")
        take(pg, "signup", "button[type=submit]")
        ctx.close()

        ctx = context(True)
        # 2. Start a paper: grade, subject, kind, title.
        STATE["papers"] = False
        pg = ctx.new_page()
        pg.goto(HOST + "/studio")
        pg.wait_for_timeout(1200)
        selects = pg.locator("select")
        selects.nth(0).select_option("grade-6")
        pg.wait_for_timeout(600)
        selects.nth(1).select_option("Mathematics")
        selects.nth(2).select_option("end_term")
        selects.nth(3).select_option("2")
        pg.get_by_label("Title on the paper").fill("Grade 6 Mathematics — End of Term 2")
        take(pg, "start", "text=Open the studio")
        STATE["papers"] = True

        # 3. The paper: filled from the bank, as it prints.
        pg.goto(HOST + "/studio/d1")
        pg.wait_for_timeout(1500)
        pg.get_by_role("tab", name="Questions").click()
        take(pg, "paper", "text=Fill from the bank")

        # 4. Print: download the paper, the marking scheme — or take it online.
        pg.get_by_role("tab", name="Print").click()
        pg.wait_for_timeout(800)
        take(pg, "print", "text=Take it online")

        # 5. The online test and its link.
        pg.goto(HOST + "/classroom")
        take(pg, "test", "text=Copy the link for the class")

        # 6. The class's results, marked as they hand in.
        pg.get_by_role("button", name=re.compile(r"^Results")).click()
        pg.wait_for_timeout(1200)
        take(pg, "results", "text=Juma Otieno")
        ctx.close()

        # 7. A student on the link: no account, a name and go.
        ctx = context(False)
        pg = ctx.new_page()
        pg.goto(HOST + "/t/K7Q2MX")
        pg.wait_for_timeout(1200)
        inp = pg.locator("input").first
        inp.fill("Nekesa Wafula")
        take(pg, "student_start", "button[type=submit]")
        pg.locator("button[type=submit]").first.click()
        pg.wait_for_timeout(1200)
        pg.get_by_text("KSh 155").first.click()
        take(pg, "student_test", "text=KSh 155")
        pg.on("dialog", lambda d: d.accept())
        pg.get_by_role("button", name=re.compile(r"hand in", re.I)).last.click()
        pg.wait_for_timeout(1200)
        take(pg, "student_result", "text=(88%)", top=True)
        ctx.close()
        br.close()
    (out / "shots.json").write_text(json.dumps(shots, indent=1))
    print("Took", ", ".join(shots))


if __name__ == "__main__":
    main()
