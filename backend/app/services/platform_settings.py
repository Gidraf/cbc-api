"""Settings an operator changes from the console, not from a shell.

Every knob here used to be an environment variable: the address the
platform is reached at, the name printed on every paper, how long logs are
kept, where to send a webhook. An environment variable is set by whoever
deploys, once, by editing a file on the box — which is the wrong person and
the wrong place for "what name goes on the papers".

Each key has an environment variable it falls back to, so a deployment that
already sets them keeps working, and the console shows which is in force.
Values are read from the table with a short cache; the console's save
takes effect within seconds in every process.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("cbc-platform-settings")

_TTL_SECONDS = 20.0


@dataclass(frozen=True)
class Setting:
    key: str
    env: str
    kind: str            # "string" | "int" | "bool" | "list" | "secret"
    title: str
    help: str
    default: Any = ""
    group: str = "General"


SETTINGS: tuple[Setting, ...] = (
    Setting("public_base_url", "PUBLIC_BASE_URL", "string", "Public address",
            "Where this platform is reached from outside — e.g. https://papers.example.co.ke. It is written "
            "into links the platform creates when no browser is asking: the QR code on a paper frozen by a "
            "queued order, the print links in an order's result, webhook payloads. A request from the console "
            "uses the address it arrived on; a background job has no such address, and without this it "
            "writes http://localhost.",
            "", "Papers"),
    Setting("paper_series_name", "PAPER_SERIES_NAME", "string", "Series name on papers",
            "Printed at the head and foot of every paper composed from the bank — your brand.", "", "Papers"),
    Setting("paper_default_count", "", "int", "Questions per paper",
            "The default item count the composer and orders start from.", 30, "Papers"),
    Setting("log_retention_days", "LOG_RETENTION_DAYS", "int", "Log retention (days)",
            "Service log lines older than this are pruned every hour.", 7, "Operations"),
    Setting("log_keep_rows", "LOG_KEEP_ROWS", "int", "Log rows to keep",
            "At most this many log lines are kept, whatever their age.", 20000, "Operations"),
    Setting("byom_step_timeout_seconds", "BYOM_STEP_TIMEOUT_SECONDS", "int", "Agent step timeout (seconds)",
            "How long a station driven by an outside agent waits for one prompt to be answered.",
            2700, "Agents"),
    Setting("open_images_enabled", "OPEN_IMAGES_ENABLED", "bool", "Photographs from Wikimedia Commons",
            "A question figure of kind 'image' fetches a credited, freely-licensed photograph from Wikimedia "
            "Commons (no key) and files it for reuse. Off, such figures are dropped and the item goes on "
            "without one.", True, "Builder"),
    Setting("users_may_generate", "USERS_MAY_GENERATE", "bool", "User accounts may generate",
            "When on, a signed-up user can ask the builder to write new questions and to run an AI review — "
            "both spend this platform's provider tokens. Off, users compose from the bank only.",
            False, "Builder"),
    Setting("auto_ingest_enabled", "AUTO_INGEST_ENABLED", "bool", "Auto-ingest from Langfuse",
            "When on, every grade's dataset is synced from Langfuse on a schedule and any design not yet "
            "ingested is queued, with strands and sub-strands built behind it — the same pass as the "
            "Datasets screen's Ingest everything, without the press.", False, "Datasets"),
    Setting("auto_ingest_interval_minutes", "AUTO_INGEST_INTERVAL_MINUTES", "int", "Auto-ingest every (minutes)",
            "How often the watch looks at Langfuse. Five at the least.", 30, "Datasets"),
    Setting("narration_voice", "TTS_VOICE", "string", "Narration voice",
            "The voice that reads walkthroughs and whiteboard videos — a Microsoft neural voice name. "
            "Women's voices: en-KE-AsiliaNeural (Kenyan), en-US-AvaMultilingualNeural and "
            "en-US-EmmaMultilingualNeural (the most natural), en-GB-SoniaNeural, en-ZA-LeahNeural, "
            "en-NG-EzinneNeural. Kiswahili lessons keep sw-KE-ZuriNeural. Empty: the Kenyan default.",
            "", "Voice"),
    Setting("narration_rate", "TTS_RATE", "string", "Narration speed",
            "How fast the voice reads, as a change from normal: -10% is a calm classroom pace, +0% normal.",
            "-8%", "Voice"),
    Setting("video_makers", "VIDEO_MAKERS", "list", "Video makers",
            "Usernames, besides admins, who may make whiteboard videos and social posts — rendering takes "
            "minutes of server time each. Comma-separated.", ["gidraf"], "Social"),
    Setting("poster_enabled", "POSTER_ENABLED", "bool", "Auto-post with the browser",
            "When on, the poster's browser publishes scheduled social posts on the platforms you are logged into.",
            False, "Auto-post"),
    Setting("poster_daily_cap", "POSTER_DAILY_CAP", "int", "Posts a day (all channels)",
            "The most the poster publishes in a day across every platform. 30 at most.", 30, "Auto-post"),
    Setting("poster_platform_cap", "POSTER_PLATFORM_CAP", "int", "Posts a day per platform",
            "The most on any one platform in a day.", 8, "Auto-post"),
    Setting("poster_min_gap_minutes", "POSTER_MIN_GAP_MINUTES", "int", "Minutes between posts",
            "The shortest gap between two posts, on any platform.", 20, "Auto-post"),
    Setting("poster_hours", "POSTER_HOURS", "string", "Posting hours (EAT)",
            "When the poster may publish, e.g. 06:00-22:00.", "06:00-22:00", "Auto-post"),
    Setting("poster_platforms", "POSTER_PLATFORMS", "list", "Platforms to post to",
            "tiktok, instagram, facebook, youtube, linkedin.", ["tiktok", "instagram", "facebook", "youtube", "linkedin"],
            "Auto-post"),
    Setting("poster_ahead_platforms", "POSTER_AHEAD_PLATFORMS", "list", "Upload ahead on",
            "Platforms where the poster uploads booked videos early and sets the platform's own Schedule, so "
            "the platform publishes on time even if the computer is off. facebook.", ["facebook"], "Auto-post"),
    Setting("poster_ahead_days", "POSTER_AHEAD_DAYS", "int", "Upload how far ahead (days)",
            "How far ahead the poster schedules on the platform. Facebook accepts up to 29.", 28, "Auto-post"),
    Setting("poster_videos_per_day", "POSTER_VIDEOS_PER_DAY", "int", "Videos a day (per platform)",
            "Walkthrough videos the poster puts out on a platform in a day.", 8, "Auto-post"),
    Setting("poster_photos_per_day", "POSTER_PHOTOS_PER_DAY", "int", "Photos a day (per platform)",
            "Photo cards a day — a question's teaser, the question, then its answer, before its video.", 8, "Auto-post"),
    Setting("poster_auto_book", "POSTER_AUTO_BOOK", "bool", "Auto-book",
            "Keep the calendar full by itself: every two hours the next days are topped up with new questions "
            "(their videos queued at once). No question is ever booked twice.", False, "Auto-post"),
    Setting("poster_auto_book_per_day", "POSTER_AUTO_BOOK_PER_DAY", "int", "Auto-book: videos a day", "", 10, "Auto-post"),
    Setting("poster_auto_book_days", "POSTER_AUTO_BOOK_DAYS", "int", "Auto-book: days ahead",
            "How far ahead to keep booked (Facebook is handed each post within 29 days of its time).", 30, "Auto-post"),
    Setting("poster_auto_book_scopes", "POSTER_AUTO_BOOK_SCOPES", "list", "Auto-book: from",
            "grade|subject pairs to book from, mixed day by day, e.g. grade-9|Mathematics. Empty: the grades and "
            "subjects booked before.", [], "Auto-post"),
    Setting("poster_comment_thread", "POSTER_COMMENT_THREAD", "bool", "Question in the caption, the rest in comments",
            "The caption is the question; the poster then comments the choices and \"can you solve it?\", and a minute "
            "later the answer and its working (with the answer card) — on posts that go out live at once, on scheduled "
            "ones once they are out. Comments only go up within posting hours.", False, "Auto-post"),
    Setting("poster_answer_delay_seconds", "POSTER_ANSWER_DELAY_SECONDS", "int", "Seconds before the answer comments",
            "How long after the choices the answer is commented.", 60, "Auto-post"),
    Setting("poster_live_per_day", "POSTER_LIVE_PER_DAY", "int", "Live posts a day, besides the booked",
            "When the computer is on and the day has room, the poster also posts up to this many finished videos "
            "that no booking uses, live. 0 turns it off.", 0, "Auto-post"),
    Setting("poster_group_shares_per_day", "POSTER_GROUP_SHARES_PER_DAY", "int", "Group shares a day",
            "How many of a day's videos are also shared to your ticked groups (one in the morning, one later). "
            "0 turns group sharing off.", 2, "Auto-post"),
    Setting("poster_groups_per_post", "POSTER_GROUPS_PER_POST", "int", "Groups per post (1-5)",
            "How many groups one shared video goes to. Each share takes the next groups in turn, the ones "
            "rested longest, until every ticked group has had one; then it goes round again.", 5, "Auto-post"),
    Setting("poster_group_rest_days", "POSTER_GROUP_REST_DAYS", "int", "Days between shares to a group",
            "A group gets at most one share in this many days — more reads as spam to members and admins.", 7,
            "Auto-post"),
    Setting("billing_free_questions", "BILLING_FREE_QUESTIONS", "int", "Free questions per account",
            "Questions a parent's or teacher's account may put on downloaded papers before paying.", 10, "Billing"),
    Setting("billing_paper_text_ksh", "BILLING_PAPER_TEXT_KSH", "string", "Paper: text question (KSh)",
            "Paid once per account, the first time the question is on a paper they download.", "5", "Billing"),
    Setting("billing_paper_diagram_ksh", "BILLING_PAPER_DIAGRAM_KSH", "string", "Paper: diagram question (KSh)",
            "A question that prints a figure.", "8", "Billing"),
    Setting("billing_api_free_daily", "BILLING_API_FREE_DAILY", "int", "API: free calls a day",
            "Content API calls a developer key makes free each day (Nairobi time).", 100, "Billing"),
    Setting("billing_api_free_monthly", "BILLING_API_FREE_MONTHLY", "int", "API: free calls a month",
            "Past either free limit, each question a call returns is charged.", 1000, "Billing"),
    Setting("billing_api_text_ksh", "BILLING_API_TEXT_KSH", "string", "API: text question (KSh)",
            "Per question returned, past the free calls.", "1.5", "Billing"),
    Setting("billing_api_diagram_ksh", "BILLING_API_DIAGRAM_KSH", "string", "API: diagram question (KSh)",
            "Per question with a figure returned, past the free calls.", "2.5", "Billing"),
    Setting("billing_free_play_items", "BILLING_FREE_PLAY_ITEMS", "int", "Free plays per account",
            "Questions an account may open in Play free — video, game and walkthrough — before it needs the pass.",
            100, "Billing"),
    Setting("billing_video_plan_ksh", "BILLING_VIDEO_PLAN_KSH", "string", "Play pass price (KSh)",
            "One period of the pass: every video (streamed, never downloaded), game and animated walkthrough. "
            "0 = not on sale.", "50", "Billing"),
    Setting("billing_video_plan_days", "BILLING_VIDEO_PLAN_DAYS", "int", "Play pass period (days)", "", 1, "Billing"),
    Setting("video_daily_target", "VIDEO_DAILY_TARGET", "int", "Videos made a day",
            "The daily job keeps making lesson videos for questions that have none until this many are made "
            "that day. 0 stops it.", 200, "Videos"),
    Setting("billing_min_topup_ksh", "BILLING_MIN_TOPUP_KSH", "int", "Smallest top-up (KSh)", "", 10, "Billing"),
    Setting("billing_max_topup_ksh", "BILLING_MAX_TOPUP_KSH", "int", "Largest top-up (KSh)",
            "M-Pesa's own limit per transaction is higher; this caps one top-up.", 70000, "Billing"),
    Setting("social_hook", "", "string", "Hook line",
            "The line over every social video's question.", "Can you solve this?", "Social"),
    Setting("social_bg_from", "", "string", "Background colour (top)", "A hex colour, e.g. #2f4d8a.", "#2f4d8a", "Social"),
    Setting("social_bg_to", "", "string", "Background colour (bottom)", "A hex colour, e.g. #141d36.", "#141d36", "Social"),
    Setting("social_accent", "", "string", "Highlight colour",
            "The hook, the spoken word in the captions and the countdown ring. A hex colour.", "#facc15", "Social"),
    Setting("social_text", "", "string", "Text colour", "Captions and the footer. A hex colour.", "#ffffff", "Social"),
    Setting("social_brand_name", "", "string", "Brand on social videos",
            "The name in the top corner of every social video and written on its end card. Empty: the "
            "series name on papers.", "", "Social"),
    Setting("social_handle", "", "string", "Social handle",
            "Your account, e.g. @cbcmaths — shown on every video, written on the end card, said aloud and "
            "put in each post.", "", "Social"),
    Setting("social_website", "", "string", "Website on social videos",
            "Shown under the captions and in each post. Empty: the public address.", "", "Social"),
    Setting("social_cta", "", "string", "Call to action",
            "Said and written at the end of every social video.", "Follow for a new question every day", "Social"),
    Setting("social_cover", "SOCIAL_COVER", "bool", "Open on a cover",
            "Every social video opens on a bright cover for a second — a big hook, the question and its choices, the "
            "teacher pointing at the viewer — which is also its thumbnail. The look and the hook change from question to "
            "question.", True, "Social"),
    Setting("social_teacher", "SOCIAL_TEACHER", "string", "Teacher in social videos",
            "A 3D teacher reads the question, thinks through the countdown, cheers the answer and asks \"Did you get it "
            "right?\". off, female, male, or alternate (half and half, by question). A woman teacher speaks with "
            "the Kenyan woman's voice (Asilia), a man with the Kenyan man's (Chilemba). Videos already made keep "
            "serving until they are made again.", "off", "Social"),
    Setting("social_countdown_seconds", "", "int", "Countdown (seconds)",
            "How long a social video counts down after the question, for the viewer to pause and try. 3–10.",
            3, "Social"),
    Setting("social_hashtags", "", "string", "Extra hashtags",
            "Added to every post after the ones made from the grade and topic, e.g. #MathsWithMwalimu.",
            "", "Social"),
    Setting("social_logo_url", "", "string", "Logo on social videos",
            "A square PNG or SVG shown beside the brand. Upload it from Play → Social posts.", "", "Social"),
    Setting("social_music_url", "", "string", "Background music",
            "An MP3 played quietly under the voice. Use a track you own or that is royalty-free for social "
            "media. Upload it from Play → Social posts. Empty: no music.", "", "Social"),
    Setting("whiteboard_hand_style", "", "string", "Whiteboard hand",
            "Which hand writes on the whiteboard: emoji-dark (✍🏿, the default), emoji-medium-dark (✍🏾) or "
            "drawn. An uploaded hand photo, below, takes the place of all three.", "emoji-dark", "Whiteboard"),
    Setting("whiteboard_hand_image", "", "string", "Whiteboard hand photo",
            "A PNG with a transparent background of a hand holding a pen, used instead of the drawn hand. "
            "Upload it from Play → Whiteboard videos, where you also click the pen's tip. Use a photo you "
            "own or are licensed to use. Empty: the drawn hand.", "", "Whiteboard"),
    Setting("whiteboard_hand_tip", "", "string", "Pen tip in the hand photo",
            "Where the pen's tip is in the photo, as x,y pixels.", "", "Whiteboard"),
    Setting("whiteboard_hand_width", "", "int", "Hand photo width on the board",
            "How wide the hand photo is drawn, in board pixels (the board is 1280 wide).", 300, "Whiteboard"),
    Setting("openai_writer_model", "OPENAI_DEFAULT_MODEL", "string", "Writing model (OpenAI)",
            "The model every writing station runs on unless bound otherwise: notes, questions, diagrams, "
            "activities, review. Changed here by an approved model-scout recommendation, and back again "
            "by rolling it back.", "gpt-6-sol", "Models"),
    Setting("openai_reader_model", "OPENAI_LIGHT_MODEL", "string", "Reading model (OpenAI)",
            "The model the reading stations run on: extracting strands, classifying a subject, research "
            "summaries.", "gpt-6-luna", "Models"),
    Setting("model_scout_enabled", "MODEL_SCOUT_ENABLED", "bool", "Weekly model scout",
            "Once a week, read the provider's prices and try any cheaper or newer model on a fixed set of "
            "sub-strands, without saving what it writes. Admins are told the result and approve any switch.",
            True, "Models"),
    Setting("model_scout_budget_usd", "MODEL_SCOUT_BUDGET_USD", "string", "Model scout budget (USD)",
            "The most one weekly run may spend on trials. It stops trying models once it is spent.",
            "5", "Models"),
    Setting("webhook_url", "WEBHOOK_URL", "string", "Webhook URL",
            "Where to POST an event when something finishes: a job, an order, a frozen paper, an agent task. "
            "Empty means no webhooks.", "", "Webhooks"),
    Setting("webhook_secret", "WEBHOOK_SECRET", "secret", "Webhook secret",
            "Each delivery carries X-CBC-Signature: sha256=HMAC(secret, body). Verify it on your side.",
            "", "Webhooks"),
    Setting("webhook_events", "WEBHOOK_EVENTS", "list", "Webhook events",
            "Which events to send: job.done, job.failed, order.done, paper.frozen, agent_task.done, "
            "agent_task.failed. Empty means all.", [], "Webhooks"),
)
_BY_KEY = {s.key: s for s in SETTINGS}

_cache: dict[str, Any] = {}
_cache_at = 0.0
_lock = threading.Lock()


def _coerce(setting: Setting, value: Any) -> Any:
    if value is None:
        return setting.default
    if setting.kind == "int":
        try:
            return int(value)
        except (TypeError, ValueError):
            return setting.default
    if setting.kind == "bool":
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if setting.kind == "list":
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return [v.strip() for v in str(value).split(",") if v.strip()]
    return str(value)


def _from_env(setting: Setting) -> Any | None:
    if not setting.env:
        return None
    raw = os.getenv(setting.env)
    if raw is None or raw == "":
        return None
    return _coerce(setting, raw)


def _load() -> dict[str, Any]:
    global _cache_at
    with _lock:
        if time.time() - _cache_at < _TTL_SECONDS:
            return _cache
        try:
            from ..infra.db import fetch_all

            rows = fetch_all("SELECT key, value FROM platform_settings")
            _cache.clear()
            for row in rows:
                _cache[str(row["key"])] = row.get("value")
        except Exception as exc:  # noqa: BLE001
            logger.debug("platform_settings not readable (%s); using the environment", exc)
        _cache_at = time.time()
        return _cache


def get(key: str, default: Any = None) -> Any:
    """The value in force: the console's, else the environment's, else the default."""
    setting = _BY_KEY.get(key)
    stored = _load().get(key)
    if stored is not None and stored != "":
        return _coerce(setting, stored) if setting else stored
    if setting is None:
        return default
    from_env = _from_env(setting)
    if from_env is not None:
        return from_env
    return setting.default if default is None else default


def source_of(key: str) -> str:
    setting = _BY_KEY.get(key)
    stored = _load().get(key)
    if stored is not None and stored != "":
        return "console"
    if setting is not None and _from_env(setting) is not None:
        return "environment"
    return "default"


def set_many(values: dict[str, Any], *, updated_by: str = "") -> dict[str, Any]:
    """Store what the console sent. An empty value clears the console's
    setting so the environment or the default applies again."""
    from ..infra.db import execute, to_json

    written: dict[str, Any] = {}
    for key, value in values.items():
        setting = _BY_KEY.get(key)
        if setting is None:
            continue
        if value is None or value == "" or value == []:
            execute("DELETE FROM platform_settings WHERE key = :key", {"key": key})
            written[key] = None
            continue
        clean = _coerce(setting, value)
        execute(
            """
            INSERT INTO platform_settings (key, value, updated_by, updated_at)
            VALUES (:key, CAST(:value AS jsonb), :by, NOW())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_by = EXCLUDED.updated_by,
                                            updated_at = NOW()
            """,
            {"key": key, "value": to_json(clean), "by": updated_by},
        )
        written[key] = clean
    global _cache_at
    _cache_at = 0.0
    return written


def describe() -> list[dict[str, Any]]:
    """Every setting with its value in force, where it comes from, and its help."""
    out = []
    for setting in SETTINGS:
        value = get(setting.key)
        shown = ("••••••" if setting.kind == "secret" and value else value)
        out.append({"key": setting.key, "title": setting.title, "help": setting.help,
                    "kind": setting.kind, "group": setting.group, "env": setting.env,
                    "value": shown, "source": source_of(setting.key), "default": setting.default})
    return out


_INTERNAL_HOST = ("api", "backend", "localhost", "127.0.0.1", "0.0.0.0", "web", "frontend", "nginx")


def _reachable(host: str) -> bool:
    """A host a person's machine could resolve: not a compose service
    name, not the loopback. `api:8000` is what the console's proxy calls
    the API and nothing outside the box can."""
    name = host.split(":")[0].strip().lower()
    if not name or name in _INTERNAL_HOST:
        return False
    return "." in name


def public_base_url(request: Any = None) -> str:
    """The address to write into a link.

    The configured public address first — it exists for exactly this. Then
    what the request can tell us, most trustworthy first: the forwarded
    host a proxy set, the browser's Origin or Referer, and only then the
    bare Host — which behind the console's proxy is `api:8000`, and was
    written into a download link nobody could use.
    """
    configured = str(get("public_base_url") or "").rstrip("/")
    if configured:
        return configured
    if request is not None:
        try:
            headers = request.headers
            forwarded_proto = headers.get("x-forwarded-proto", "").split(",")[0].strip()
            forwarded_host = headers.get("x-forwarded-host", "").split(",")[0].strip()
            if forwarded_host and _reachable(forwarded_host):
                return f"{forwarded_proto or request.url.scheme}://{forwarded_host}".rstrip("/")
            for header in ("origin", "referer"):
                value = str(headers.get(header) or "").strip()
                if value.startswith(("http://", "https://")):
                    scheme, rest = value.split("://", 1)
                    host = rest.split("/", 1)[0]
                    if _reachable(host):
                        return f"{scheme}://{host}"
            host = headers.get("host", "") or request.url.netloc
            if host and _reachable(host):
                return f"{request.url.scheme}://{host}".rstrip("/")
        except Exception:  # noqa: BLE001
            pass
    return "http://localhost:8000"
