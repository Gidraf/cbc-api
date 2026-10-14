"""The content API: CBC questions for developers' apps, metered.

Its documentation is this module: the guide below is the OpenAPI
description, and /api/v1/content/docs renders it with Redoc (open source).
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from ..errors import raise_api_error
from ..services.auth import AuthContext, require_roles

router = APIRouter(prefix="/api/v1/content", tags=["Content API"])

_ROLE = require_roles("api", "developer", "admin", "operator")


def DEVELOPER(auth: AuthContext = Depends(_ROLE)) -> AuthContext:  # noqa: N802 — used as a dependency like the others
    """A developer's call: the role, then the per-minute limit."""
    from ..services import rate_limit

    rate_limit.hit("content_key", auth.subject)
    return auth

GUIDE = """
Questions written for Kenya's **Competency-Based Curriculum (CBC)**, from Grade 1 to Grade 12. Each one
comes with its answer, a marking scheme, a worked answer, its marks, where it sits in the curriculum
(grade → subject → strand → sub-strand), and — for diagram questions — the figure as SVG.

Use it to power a revision app, a school portal, a WhatsApp bot, or a practice tool for your own pupils.

# Getting started

1. **Sign up as a developer** at the CBC console (choose *Developer* when you register).
2. **Create an API key** under *API keys*. It is shown once — keep it in an environment variable, never
   in your code or in a public repository.
3. **Call the API** with the key in the `X-API-Key` header.

```python
import os
import requests

BASE = "https://cbc.gidraf.dev/api/v1/content"
HEADERS = {"X-API-Key": os.environ["CBC_API_KEY"]}

r = requests.get(f"{BASE}/questions", headers=HEADERS,
                 params={"grade": "Grade 9", "subject": "Mathematics", "sub_strand": "Integers", "limit": 5},
                 timeout=30)
r.raise_for_status()
for q in r.json()["items"]:
    print(q["question"])
    print("Answer:", q["answer"])
```

```javascript
const BASE = "https://cbc.gidraf.dev/api/v1/content";

const res = await fetch(`${BASE}/questions?grade=Grade%209&subject=Mathematics&limit=5`, {
  headers: { "X-API-Key": process.env.CBC_API_KEY },
});
if (!res.ok) throw new Error(`CBC API: ${res.status}`);
const { items } = await res.json();
items.forEach((q) => console.log(q.question, "→", q.answer));
```

```bash
curl -H "X-API-Key: $CBC_API_KEY" \\
  "https://cbc.gidraf.dev/api/v1/content/questions?grade=Grade%209&subject=Mathematics&limit=5"
```

# Find what to ask for

`GET /curriculum` lists every grade, subject, strand and sub-strand that has questions, with how many
(and how many carry a figure). It is free and never counted. Use its names exactly as filters.

```python
tree = requests.get(f"{BASE}/curriculum", headers=HEADERS, timeout=30).json()["items"]
maths9 = [row for row in tree if row["grade"] == "grade-9" and row["subject"] == "Mathematics"]
```

# Free calls and prices

| | Free | Then |
|---|---|---|
| Calls a day (Nairobi time) | **100** | — |
| Calls a month | **1,000** | — |
| Each question returned, past either free limit | — | **KSh 1.50** text · **KSh 2.50** with a figure |

* A call is free while you are under **both** free limits. Past either, each question it returns is
  charged to your wallet: a call that returns 20 text questions costs KSh 30.
* `GET /curriculum` and `GET /usage` are always free and never counted.
* At most **120 calls a minute** per account; past that the API answers 429 for a moment.
* Top up your wallet with **M-Pesa** (below). When it runs out, paid calls answer **402** and nothing is
  charged.
* Questions do not change often: **store what you fetch** (by `id`) and you pay for a question once.

```python
usage = requests.get(f"{BASE}/usage", headers=HEADERS, timeout=30).json()
print(usage["free_left_today"], "free calls left today; wallet:", usage["balance_ksh"], "KSh")
```

# Top up with M-Pesa

`POST /api/v1/billing/topup` sends an M-Pesa PIN prompt to the phone; your wallet is credited the moment
you enter your PIN. Check the result with `GET /api/v1/billing/topup/{checkout_request_id}`.

```python
r = requests.post("https://cbc.gidraf.dev/api/v1/billing/topup", headers=HEADERS,
                  json={"phone": "0712345678", "amount": 500}, timeout=30)
checkout = r.json()["checkout_request_id"]

import time
for _ in range(20):
    status = requests.get(f"https://cbc.gidraf.dev/api/v1/billing/topup/{checkout}",
                          headers=HEADERS, timeout=30).json()
    if status["status"] != "pending":
        break
    time.sleep(5)
print(status["status"], status["balance_ksh"])
```

You can also top up from the console under *Wallet*.

# The question

```json
{
  "id": "q-grade-9-math-integers-apply-intege-mu02dhacaf40d3",
  "grade": "grade-9", "subject": "Mathematics", "strand": "Numbers", "sub_strand": "Integers",
  "type": "diagram_based",
  "context": "A thermometer outside a school laboratory records a temperature of $-5^\\\\circ\\\\text{C}$ …",
  "question": "Study the thermometer figure. Explain why the rise is represented by $+8$ …",
  "options": [],
  "answer": "$-5+8=3^\\\\circ\\\\text{C}$",
  "correct_option": null,
  "worked_answer": "A rise means movement towards greater values …",
  "marking_scheme": "M1: Represents the rise as $+8$. A1: Calculates $-5+8=3$ …",
  "marks": 3,
  "has_figure": true,
  "figure": { "title": "Thermometer", "svg": "<svg …>…</svg>" }
}
```

* **Maths is LaTeX** between `$…$` — render it with [KaTeX](https://katex.org) or MathJax.
* **Multiple choice**: `options` holds `{id, text}`; `correct_option` is the right `id`.
* **Figures** are SVG as a learner sees them (anything the learner must fill in is left blank). Put the
  string straight into your page, or save it as a `.svg` file. Ask for `figures=only` to get only
  diagram questions, or `figures=none` for text only.
* `marking_scheme` uses the KNEC style: **M** marks for method, **A** for accuracy, **B** for a stated fact.

# Embed a video on your page

Every question with a video can be played on your own site in an `<iframe>`, like a YouTube video — streamed
from us, watched by your visitors, never downloaded. Give it your own heading and colour (or let us pick a colour).

```python
r = requests.get(f"{BASE}/questions/{question_id}/embed", headers=HEADERS, timeout=30,
                 params={"heading": "Integers in real life", "color": "#0f766e"})
iframe = r.json()["iframe"]          # put this in your page
```

The link works for 7 days: fetch a fresh one when you build the page. Each embed link is counted and charged like
fetching the question.

# Pages of results

`limit` is 1–50 (default 20); `offset` skips that many. `total` says how many match.

```python
offset, everything = 0, []
while True:
    page = requests.get(f"{BASE}/questions", headers=HEADERS, timeout=30,
                        params={"grade": "Grade 9", "subject": "Mathematics", "limit": 50, "offset": offset}).json()
    everything += page["items"]
    offset += len(page["items"])
    if offset >= page["total"] or not page["items"]:
        break
```

Every page is a call, and is charged for the questions on it once you are past the free calls.

# Errors

Every error answers with the HTTP status below and this body — `code` for your program, `message` for a
person:

```json
{
  "status": "failed",
  "errors": [
    {
      "code": "PAYMENT_REQUIRED",
      "message": "This costs KSh 30 and the wallet has KSh 4. Top up with M-Pesa. Free calls are used up for now.",
      "retryable": false,
      "detail": { "needed_ksh": 26, "price_ksh": 30, "balance_ksh": 4 }
    }
  ]
}
```

| Status | Code | What to do |
|---|---|---|
| 401 | `UNAUTHORIZED_ACCESS` | The `X-API-Key` header is missing, or the key was revoked. |
| 402 | `PAYMENT_REQUIRED` | Past the free calls and the wallet is short: top up. `errors[0].detail.needed_ksh` says by how much. Nothing was charged. |
| 403 | `FORBIDDEN` | This key's account may not use the content API. |
| 404 | `NOT_FOUND` | No such question (or it was withdrawn). |
| 400 | `VALIDATION_FAILED` | A filter has a value the API does not know. |
| 429 | `RATE_LIMITED` | More than 120 calls in a minute. Wait `errors[0].detail.retry_after_seconds` and retry. |

```python
r = requests.get(f"{BASE}/questions", headers=HEADERS, params={"grade": "Grade 9"}, timeout=30)
if r.status_code == 402:
    error = r.json()["errors"][0]
    print("Top up:", error["detail"]["needed_ksh"], "KSh more needed")
```

# Good practice

* Keep the key on your server. A key in a mobile app or a web page can be read and used by anyone.
* Cache what you fetch; a question's `id` never changes.
* Show the marking scheme to teachers and parents, not to the learner answering the question.
"""


# ── what the reference shows ─────────────────────────────────────────────────

class Figure(BaseModel):
    title: str = Field(examples=["Thermometer"])
    svg: str | None = Field(None, description="The figure as a learner sees it; null if it could not be drawn",
                            examples=["<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 300'>…</svg>"])


class Option(BaseModel):
    id: str = Field(examples=["A"])
    text: str = Field(examples=["$3^\\circ\\text{C}$"])


class Question(BaseModel):
    id: str = Field(examples=["q-grade-9-math-integers-apply-intege-mu02dhacaf40d3"])
    grade: str = Field(examples=["grade-9"])
    subject: str = Field(examples=["Mathematics"])
    strand: str = Field(examples=["Numbers"])
    sub_strand: str = Field(examples=["Integers"])
    learning_outcome: str = Field("", examples=["apply Integers to real-life situations"])
    type: str = Field(examples=["diagram_based"])
    context: str = Field("", description="The situation the question is set in (may be empty)",
                         examples=["A thermometer outside a school laboratory records $-5^\\circ\\text{C}$ …"])
    question: str = Field(examples=["Study the thermometer figure. Explain why the rise is represented by $+8$ …"])
    parts: list[Any] = Field(default_factory=list, description="Sub-questions (a), (b)… of a structured question")
    options: list[Option] = Field(default_factory=list, description="Multiple choice only")
    answer: str = Field(examples=["$-5+8=3^\\circ\\text{C}$"])
    correct_option: str | None = Field(None, description="Multiple choice: the right option's id")
    worked_answer: str = Field("", examples=["A rise means movement towards greater values …"])
    marking_scheme: str = Field("", examples=["M1: Represents the rise as $+8$. A1: Calculates $-5+8=3$ …"])
    marks: float = Field(examples=[3])
    difficulty: float | None = Field(None, description="0 (easiest) to 1 (hardest)", examples=[0.45])
    bloom_level: str = Field("", examples=["apply"])
    estimated_minutes: float | None = Field(None, examples=[4])
    has_figure: bool = Field(examples=[True])
    figure: Figure | None = None
    math_format: str = Field("LaTeX between $…$", examples=["LaTeX between $…$"])


class QuestionPage(BaseModel):
    items: list[Question]
    total: int = Field(description="How many questions match the filters", examples=[312])
    limit: int = Field(examples=[20])
    offset: int = Field(examples=[0])
    charged_ksh: float = Field(description="What this call cost; 0 while you are within the free calls", examples=[0])


class QuestionOne(Question):
    charged_ksh: float = Field(examples=[0])


class CurriculumRow(BaseModel):
    grade: str = Field(examples=["grade-9"])
    subject: str = Field(examples=["Mathematics"])
    strand: str = Field(examples=["Numbers"])
    sub_strand: str = Field(examples=["Integers"])
    questions: int = Field(examples=[48])
    with_figures: int = Field(examples=[17])


class CurriculumList(BaseModel):
    items: list[CurriculumRow]


class Usage(BaseModel):
    calls_today: int = Field(examples=[12])
    calls_this_month: int = Field(examples=[240])
    free_left_today: int = Field(description="Free calls left now: the smaller of the day's and the month's",
                                 examples=[88])
    charged_this_month_ksh: float = Field(examples=[0])
    balance_ksh: float = Field(examples=[150])
    prices: dict[str, Any] = Field(examples=[{"text_ksh": 1.5, "diagram_ksh": 2.5, "free_calls_per_day": 100,
                                              "free_calls_per_month": 1000}])


class ErrorItem(BaseModel):
    code: str = Field(examples=["PAYMENT_REQUIRED"])
    message: str = Field(examples=["This costs KSh 30 and the wallet has KSh 4. Top up with M-Pesa."])
    retryable: bool = Field(examples=[False])
    detail: dict[str, Any] | None = Field(None, examples=[{"needed_ksh": 26, "price_ksh": 30, "balance_ksh": 4}])


class ErrorBody(BaseModel):
    status: str = Field(examples=["failed"])
    errors: list[ErrorItem]


ERRORS = {401: {"model": ErrorBody, "description": "No key, or a revoked one"},
          402: {"model": ErrorBody, "description": "Past the free calls and the wallet is short — nothing was charged"},
          403: {"model": ErrorBody, "description": "This account may not use the content API"}}


def samples(path: str, params: str = "") -> dict[str, Any]:
    """Ready-to-copy calls for the reference's right-hand panel."""
    query = f"?{params}" if params else ""
    py_params = ""
    if params:
        pairs = [p.split("=", 1) for p in params.split("&")]
        py_params = (",\n                 params={" + ", ".join(f'"{k}": "{v.replace("%20", " ")}"' for k, v in pairs)
                     + "}")
    return {"x-codeSamples": [
        {"lang": "Python", "label": "Python (requests)", "source":
            "import os\nimport requests\n\n"
            f'r = requests.get("https://cbc.gidraf.dev{path}",\n'
            f'                 headers={{"X-API-Key": os.environ["CBC_API_KEY"]}}{py_params},\n'
            "                 timeout=30)\n"
            "r.raise_for_status()\nprint(r.json())"},
        {"lang": "JavaScript", "label": "JavaScript (fetch)", "source":
            f'const res = await fetch("https://cbc.gidraf.dev{path}{query}", {{\n'
            '  headers: { "X-API-Key": process.env.CBC_API_KEY },\n});\n'
            "if (!res.ok) throw new Error(`CBC API: ${res.status}`);\nconsole.log(await res.json());"},
        {"lang": "Shell", "label": "curl", "source":
            f'curl -H "X-API-Key: $CBC_API_KEY" "https://cbc.gidraf.dev{path}{query}"'},
    ]}


def _usage_headers(owner: str) -> dict[str, str]:
    from ..services import billing

    u = billing.api_usage(owner)
    return {"X-Free-Calls-Left-Today": str(u["free_left_today"]), "X-Wallet-Balance-KSh": str(u["balance_ksh"])}


def _charge(auth: AuthContext, items: list[dict[str, Any]], ref: str) -> dict[str, Any]:
    from ..services import billing

    try:
        return billing.meter_api(auth.subject, auth.role, items, ref=ref)
    except billing.PaymentRequired as exc:
        raise_api_error("PAYMENT_REQUIRED", f"{exc} Free calls are used up for now.", detail=exc.detail())
    return {}


@router.get("/curriculum", summary="Grades, subjects, strands and sub-strands with questions",
            response_model=CurriculumList, responses=ERRORS, openapi_extra=samples("/api/v1/content/curriculum"))
def content_curriculum(auth: AuthContext = Depends(DEVELOPER)) -> dict[str, Any]:
    """Free and never counted. Use the names as filters on `/questions`."""
    from ..services import content_api

    return {"items": content_api.curriculum()}


@router.get("/questions", summary="Questions, filtered by curriculum", response_model=QuestionPage, responses=ERRORS,
            openapi_extra=samples("/api/v1/content/questions", "grade=Grade%209&subject=Mathematics&limit=5"))
def content_questions(
    grade: str = Query("", description='e.g. "Grade 9" or "grade-9"'),
    subject: str = Query("", description='e.g. "Mathematics"'),
    strand: str = Query("", description='e.g. "Numbers"'),
    sub_strand: str = Query("", description='e.g. "Integers"'),
    type: str = Query("", description="multiple_choice, short_answer, diagram_based, structured, …"),
    figures: Literal["any", "only", "none"] = Query("any", description="only: diagram questions; none: text only"),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(DEVELOPER),
) -> JSONResponse:
    """Counted as one call. Past the free calls, each question returned is charged
    (KSh 1.50 text, KSh 2.50 with a figure)."""
    from ..services import content_api

    rows, total = content_api.search({"grade": grade, "subject": subject, "strand": strand, "sub_strand": sub_strand,
                                      "question_type": type, "figures": figures}, limit=limit, offset=offset)
    items = [content_api.public(r) for r in rows]
    bill = _charge(auth, items, ref=f"questions?grade={grade}&subject={subject}&offset={offset}")
    return JSONResponse({"items": items, "total": total, "limit": limit, "offset": offset,
                         "charged_ksh": bill.get("charged_ksh", 0)}, headers=_usage_headers(auth.subject))


@router.get("/questions/{question_id}", summary="One question", response_model=QuestionOne,
            responses={**ERRORS, 404: {"model": ErrorBody, "description": "No such question"}},
            openapi_extra=samples("/api/v1/content/questions/q-grade-9-math-integers-apply-intege-mu02dhacaf40d3"))
def content_question(question_id: str, auth: AuthContext = Depends(DEVELOPER)) -> JSONResponse:
    """Counted as one call; charged as one question past the free calls."""
    from ..services import content_api

    row = content_api.one(question_id)
    if not row:
        raise_api_error("NOT_FOUND", "No such question.")
    item = content_api.public(row)
    bill = _charge(auth, [item], ref=f"question {question_id}")
    return JSONResponse({**item, "charged_ksh": bill.get("charged_ksh", 0)}, headers=_usage_headers(auth.subject))


@router.get("/usage", summary="Free calls left, this month's spend, and the wallet", response_model=Usage,
            responses=ERRORS, openapi_extra=samples("/api/v1/content/usage"))
def content_usage(auth: AuthContext = Depends(DEVELOPER)) -> dict[str, Any]:
    """Free and never counted."""
    from ..services import billing

    return billing.api_usage(auth.subject)


# ── the documentation ────────────────────────────────────────────────────────

PUBLIC_PATHS = ("/api/v1/content/", "/api/v1/billing/topup", "/api/v1/billing/wallet")


@router.get("/openapi.json", include_in_schema=False)
def content_openapi(request: Request) -> dict[str, Any]:
    """The content API alone, with the guide, for the docs and for code generators."""
    from fastapi.openapi.utils import get_openapi

    from ..services import platform_settings

    app = request.app
    routes = [r for r in app.routes if getattr(r, "path", "").startswith(PUBLIC_PATHS)
              and getattr(r, "include_in_schema", True)]
    spec = get_openapi(title="CBC Content API", version="1.0", description=GUIDE, routes=routes)
    spec["servers"] = [{"url": platform_settings.public_base_url(request)}]
    spec.setdefault("components", {})["securitySchemes"] = {
        "ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}
    spec["security"] = [{"ApiKey": []}]
    for path in spec.get("paths", {}).values():       # the key is the only way in; hide the internal header
        for op in path.values():
            op["parameters"] = [p for p in op.get("parameters", []) if p.get("name") not in ("authorization", "x-api-key")]
    spec["x-tagGroups"] = [{"name": "Reference", "tags": ["Content API", "Billing"]}]
    return spec


DOCS = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>CBC Content API</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>body{margin:0}</style></head>
<body><redoc spec-url="/api/v1/content/openapi.json"
  theme='{"colors":{"primary":{"main":"#1d4ed8"}},"typography":{"fontFamily":"Inter, sans-serif","code":{"fontFamily":"JetBrains Mono, monospace"}}}'
  hide-download-button="false" required-props-first="true" path-in-middle-panel="true"></redoc>
<script src="https://cdn.jsdelivr.net/npm/redoc@2.1.5/bundles/redoc.standalone.js"></script>
</body></html>"""


@router.get("/docs", include_in_schema=False, response_class=HTMLResponse)
def content_docs() -> HTMLResponse:
    """The developer documentation (Redoc), open to everyone."""
    return HTMLResponse(DOCS)


# ── the embeddable player (an iframe, like YouTube's) ────────────────────────

embed = APIRouter(prefix="/api/v1/embed", tags=["Content API"])
EMBED_DAYS = 7
PALETTE = ("#1d4ed8", "#7c3aed", "#0f766e", "#b45309", "#be185d", "#15803d", "#c2410c", "#0369a1", "#4338ca")


def _embed_secret() -> str:
    from ..settings import settings

    return "embed:" + settings.jwt_secret


class EmbedLink(BaseModel):
    embed_url: str = Field(examples=["https://cbc.gidraf.dev/api/v1/embed/eyJhbGciOi…"])
    iframe: str = Field(examples=['<iframe src="https://cbc.gidraf.dev/api/v1/embed/eyJ…" width="640" height="400" '
                                  'allow="fullscreen" style="border:0"></iframe>'])
    expires_in_days: int = Field(examples=[EMBED_DAYS])
    charged_ksh: float = Field(examples=[0])


@router.get("/questions/{question_id}/embed", summary="An embeddable video player for one question",
            response_model=EmbedLink, responses={**ERRORS, 404: {"model": ErrorBody, "description": "No video yet"}},
            openapi_extra=samples("/api/v1/content/questions/q-grade-9-math-integers-apply-intege-mu02dhacaf40d3/embed",
                                  "heading=Integers%20in%20real%20life&color=%230f766e"))
def content_embed(question_id: str, request: Request,
                  heading: str = Query("", max_length=80, description="Your own heading over the video"),
                  color: str = Query("", description="Your colour, e.g. #0f766e — a random one if left out"),
                  auth: AuthContext = Depends(DEVELOPER)) -> JSONResponse:
    """The question's whiteboard video as an `<iframe>` for your page. It
    streams from us — your visitors watch it, never download it. Counted and
    charged like fetching the question; the link works for 7 days, so fetch a
    fresh one when you build the page."""
    import re
    import secrets as _secrets
    import time

    import jwt

    from ..services import content_api, platform_settings, whiteboard

    row = content_api.one(question_id)
    if not row:
        raise_api_error("NOT_FOUND", "No such question.")
    q = whiteboard.load(question_id)
    st = whiteboard.status(question_id, q)
    if st.get("status") != "ready":
        raise_api_error("NOT_FOUND", "This question's video is not made yet.")
    if color and not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise_api_error("VALIDATION_FAILED", "A colour is #RRGGBB, e.g. #0f766e.")
    bill = _charge(auth, [content_api.public(row, figures=False)], ref=f"embed {question_id}")
    token = jwt.encode({"type": "embed", "sub": auth.subject, "q": question_id,
                        "obj": whiteboard.object_name(question_id, st["key"]),
                        "h": re.sub(r"\s+", " ", heading).strip()[:80], "c": color or _secrets.choice(PALETTE),
                        "exp": int(time.time()) + EMBED_DAYS * 86400}, _embed_secret(), algorithm="HS256")
    url = f"{platform_settings.public_base_url(request)}/api/v1/embed/{token}"
    iframe = f'<iframe src="{url}" width="640" height="400" allow="fullscreen" style="border:0;max-width:100%"></iframe>'
    return JSONResponse({"embed_url": url, "iframe": iframe, "expires_in_days": EMBED_DAYS,
                         "charged_ksh": bill.get("charged_ksh", 0)}, headers=_usage_headers(auth.subject))


PLAYER = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>__TITLE__</title>
<style>
 html,body{margin:0;height:100%;background:#0b0f17;font-family:Inter,system-ui,sans-serif;color:#fff}
 .wrap{height:100%;display:flex;flex-direction:column}
 header{padding:10px 14px;background:linear-gradient(135deg,__COLOR__,#0b0f17);font-weight:600;font-size:15px;
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
 video{flex:1;width:100%;min-height:0;background:#000;outline:none}
 footer{font-size:11px;padding:4px 10px;color:#9aa4b2;text-align:right}
 footer a{color:#9aa4b2}
</style></head><body><div class="wrap">
__HEADER__
<video src="__SRC__" controls playsinline preload="metadata" controlsList="nodownload noplaybackrate"
       disablepictureinpicture disableremoteplayback oncontextmenu="return false"></video>
<footer>CBC lessons · <a href="__HOME__" target="_blank" rel="noopener">cbc.gidraf.dev</a></footer>
</div></body></html>"""


@embed.get("/{token}", include_in_schema=False)
def embed_player(token: str, request: Request) -> HTMLResponse:
    """The player a developer's page frames: their heading and colour, our
    stream. A fresh short-lived stream link is made on every view."""
    import html as _html

    import jwt

    from ..services import platform_settings, streaming

    try:
        claims = jwt.decode(token, _embed_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return HTMLResponse("<p style='font-family:sans-serif'>This video link has expired. Ask the site to refresh it.</p>",
                            status_code=410)
    if claims.get("type") != "embed" or not claims.get("obj"):
        return HTMLResponse("", status_code=404)
    src = streaming.watch_link(f"embed:{claims.get('sub')}", str(claims["obj"]))["stream_url"]
    heading = str(claims.get("h") or "")
    page = (PLAYER.replace("__TITLE__", _html.escape(heading or "CBC lesson"))
            .replace("__COLOR__", _html.escape(str(claims.get("c") or PALETTE[0])))
            .replace("__HEADER__", f"<header>{_html.escape(heading)}</header>" if heading else "")
            .replace("__SRC__", _html.escape(src))
            .replace("__HOME__", _html.escape(platform_settings.public_base_url(request))))
    # Meant to be framed by any site — the only page that is.
    return HTMLResponse(page, headers={"Content-Security-Policy": "default-src 'none'; media-src 'self'; "
                                       "style-src 'unsafe-inline'; frame-ancestors *",
                                       "Cache-Control": "no-store"})
