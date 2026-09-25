"""Once a week: are we paying for the right models?

Providers change prices and ship models more often than anyone here reads
their pricing page. A cheaper model that would do the job is money spent every
day it goes unnoticed; a cheaper model that would NOT do the job is worse than
none, because the content is sold and a switch shows up as a week of papers
four years too easy.

So the scout reads the prices, and for each tier (writer, reader) tries the
models that would cost less — and any new model not far above — on a fixed
panel of sub-strands, through the real questions station, with nothing saved.
The models in use run the same panel the same week, so the comparison is like
for like. The judge is the station's own gate, which scores by rule: no model
marks its own work.

It recommends; it never switches. An admin reads the numbers and approves, and
an approved switch can be rolled back the same way.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from . import model_policy
from .model_policy import READER, TIERS, WRITER

logger = logging.getLogger("cbc-model-scout")

PANEL_SIZE = 5            # sub-strands per trial: one per subject where possible
ITEMS_PER_TRIAL = 4       # questions asked of each run
MAX_CANDIDATES = {"writer": 2, "reader": 1}   # models tried per tier per week, cheapest first
RETRY_AFTER_DAYS = 28     # a model tried at these prices is not tried again for this long
NEW_MODEL_DAYS = 8        # "new" means first seen within this
NEW_MODEL_CEILING = 1.5   # a new model is tried if it costs up to this times the current one
MAX_SECONDS = 2700        # stop starting trials after this; the job has an hour

# Text models the stations can run. The page also lists pro, codex, image and
# audio models; none of them is a drop-in for a station.
_USABLE = re.compile(r"^gpt-\d+(\.\d+)?(-[a-z]+)?$")
_NOT_A_STATION_MODEL = ("pro", "codex", "audio", "realtime", "image", "tts", "transcribe", "search")


def usable(model: str) -> bool:
    name = (model or "").lower()
    return bool(_USABLE.match(name)) and not any(bit in name for bit in _NOT_A_STATION_MODEL) \
        and not model_policy.is_retired(name)


def blended(price: dict[str, Any] | None) -> float | None:
    """Price of a typical station call per 1M tokens: prompts run about twice
    the length of what comes back (8k in, 4k out)."""
    if not price or price.get("input") is None or price.get("output") is None:
        return None
    return round((2 * float(price["input"]) + float(price["output"])) / 3, 6)


# ── what to try ─────────────────────────────────────────────────────────────

def candidates(prices: dict[str, dict[str, Any]], current: dict[str, str],
               recently_tried: set[tuple[str, str]], now: float | None = None) -> list[dict[str, Any]]:
    """Which (tier, model) pairs are worth a trial this week, cheapest first.

    Cheaper than the tier's model: worth knowing whether it holds up. New and
    not far above: it may be better for little more. Everything else: no.
    """
    now = now or time.time()

    def stamp(price: dict[str, Any]) -> float | None:
        seen = price.get("first_seen")
        return seen.timestamp() if hasattr(seen, "timestamp") else None

    # The first read of the page sees every model for the first time. "New"
    # means new since then — otherwise week one tries everything on the page.
    stamps = [s for s in (stamp(p) for p in prices.values()) if s is not None]
    seeded = min(stamps) if stamps else now
    out: list[dict[str, Any]] = []
    for tier in (WRITER, READER):
        tier_out: list[dict[str, Any]] = []
        in_use = current[tier]
        base = blended(prices.get(in_use))
        if base is None:
            continue
        for model, price in prices.items():
            if model == in_use or not usable(model) or (tier, model) in recently_tried:
                continue
            cost = blended(price)
            if cost is None:
                continue
            seen_at = stamp(price)
            is_new = (seen_at is not None and now - seen_at < NEW_MODEL_DAYS * 86400
                      and seen_at - seeded > 86400)
            if cost < base:
                why = f"{round((1 - cost / base) * 100)}% cheaper than {in_use}"
            elif is_new and cost <= base * NEW_MODEL_CEILING:
                why = f"new this week, {round((cost / base - 1) * 100)}% dearer than {in_use}"
            else:
                continue
            tier_out.append({"tier": tier, "model": model, "current": in_use, "why": why,
                             "blended": cost, "current_blended": base})
        tier_out.sort(key=lambda c: c["blended"])
        out += tier_out[:MAX_CANDIDATES[tier]]
    return out


def panel(limit: int = PANEL_SIZE) -> list[dict[str, str]]:
    """The sub-strands every model is tried on: stable week to week.

    Sub-strands with a filed guide (the questions station needs one), one per
    subject before a second from any, in an order fixed by a hash — so this
    week's panel is last week's unless the guides changed.
    """
    from ..infra.db import fetch_all

    rows = fetch_all(
        """
        SELECT DISTINCT grade, subject, strand_name, sub_strand_name
        FROM artifacts
        WHERE kind = 'notes' AND sub_strand_name <> '' AND subject <> ''
        """) or []

    def order(r: dict[str, Any]) -> str:
        return hashlib.sha256(f"{r['grade']}|{r['subject']}|{r['sub_strand_name']}".encode()).hexdigest()

    by_subject: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(rows, key=order):
        by_subject.setdefault(str(row["subject"]).lower(), []).append(row)
    picked: list[dict[str, str]] = []
    while len(picked) < limit and any(by_subject.values()):
        for subject in sorted(by_subject):
            if by_subject[subject] and len(picked) < limit:
                r = by_subject[subject].pop(0)
                picked.append({"grade": str(r["grade"]), "subject": str(r["subject"]),
                               "strand": str(r.get("strand_name") or ""),
                               "sub_strand": str(r["sub_strand_name"])})
    return picked


# ── trying ──────────────────────────────────────────────────────────────────

@dataclass
class Outcome:
    tier: str
    model: str
    role: str                       # "baseline" | "candidate"
    grade: str = ""
    subject: str = ""
    strand: str = ""
    sub_strand: str = ""
    passed: bool = False
    score: int = 0
    requested: int = 0
    accepted: int = 0
    held: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    error: str = ""


def try_once(row: dict[str, str], *, tier: str, model: str, role: str,
             items: int = ITEMS_PER_TRIAL) -> Outcome:
    """One sub-strand, one model, through the real station, nothing kept."""
    from ..routes.questions import QuestionBatchGenerateRequest, factory_generate_questions_batch
    from . import model_trial, run_meter

    outcome = Outcome(tier=tier, model=model, role=role, requested=items, **row)
    started = time.monotonic()
    context = model_trial.trial(tier, model) if role == "candidate" else model_trial.dry_run()
    with context, run_meter.measure() as meter:
        try:
            result = factory_generate_questions_batch(
                QuestionBatchGenerateRequest(grade=row["grade"], subject=row["subject"],
                                             strand=row["strand"], sub_strand=row["sub_strand"],
                                             batch_count=items), None)
            gate = result.get("quality_gate") or {}
            outcome.passed = bool(gate.get("passed"))
            outcome.score = int(gate.get("overall_score") or 0)
            outcome.accepted = len(result.get("questions") or [])
            outcome.held = int(result.get("rejected_count") or 0)
        except Exception as exc:  # noqa: BLE001
            # A model that cannot produce the station's JSON is the finding.
            outcome.error = f"{type(exc).__name__}: {str(exc)[:300]}"
    outcome.cost_usd = round(meter.cost_usd, 6)
    outcome.seconds = round(time.monotonic() - started, 1)
    return outcome


def summarise(outcomes: list[Outcome]) -> dict[str, Any]:
    """One model's panel, as the numbers an admin decides on."""
    runs = len(outcomes)
    ok = [o for o in outcomes if not o.error]
    requested = sum(o.requested for o in outcomes)
    accepted = sum(o.accepted for o in ok)
    cost = sum(o.cost_usd for o in outcomes)
    return {
        "runs": runs,
        "errors": runs - len(ok),
        "passed": sum(1 for o in ok if o.passed),
        "pass_rate": round(sum(1 for o in ok if o.passed) / runs, 3) if runs else 0.0,
        "mean_score": round(sum(o.score for o in ok) / len(ok), 1) if ok else 0.0,
        "requested": requested,
        "accepted": accepted,
        "acceptance": round(accepted / requested, 3) if requested else 0.0,
        "cost_usd": round(cost, 4),
        "cost_per_accepted": round(cost / accepted, 5) if accepted else None,
        "mean_seconds": round(sum(o.seconds for o in outcomes) / runs, 1) if runs else 0.0,
    }


def verdict(candidate: dict[str, Any], baseline: dict[str, Any]) -> tuple[str, list[str]]:
    """Recommended or not, and each reason in words.

    A panel of five is small, so "as good" allows one sub-strand's difference.
    Cheaper must mean cheaper per ACCEPTED question — a model that is half the
    price and has half its items held back has saved nothing.
    """
    reasons: list[str] = []
    ok = True
    slack = 1 / max(1, baseline["runs"])

    if candidate["runs"] == 0:
        return "not_recommended", ["it was not tried: the budget or the time ran out first"]
    if candidate["errors"] > baseline["errors"]:
        ok = False
        reasons.append(f"{candidate['errors']} run(s) failed outright against {baseline['errors']} "
                       f"for the model in use — usually JSON the station could not read")
    if candidate["pass_rate"] + slack + 1e-9 < baseline["pass_rate"]:
        ok = False
        reasons.append(f"passed the gate on {candidate['passed']} of {candidate['runs']} against "
                       f"{baseline['passed']} of {baseline['runs']}")
    else:
        reasons.append(f"passed the gate on {candidate['passed']} of {candidate['runs']} "
                       f"(model in use: {baseline['passed']} of {baseline['runs']})")
    if candidate["mean_score"] + 3 < baseline["mean_score"]:
        ok = False
        reasons.append(f"scored {candidate['mean_score']} on average against {baseline['mean_score']}")
    if candidate["acceptance"] + 0.1 < baseline["acceptance"]:
        ok = False
        reasons.append(f"kept {round(candidate['acceptance'] * 100)}% of the items it wrote against "
                       f"{round(baseline['acceptance'] * 100)}%")

    mine, theirs = candidate["cost_per_accepted"], baseline["cost_per_accepted"]
    if mine is None:
        ok = False
        reasons.append("no item it wrote was kept, so it has no cost per question")
    elif theirs:
        change = mine / theirs - 1
        if change <= -0.1:
            reasons.append(f"${mine:.4f} a kept question against ${theirs:.4f} — {round(-change * 100)}% less")
        elif change < 0.5 and candidate["mean_score"] >= baseline["mean_score"] + 5 \
                and candidate["pass_rate"] >= baseline["pass_rate"] + slack:
            reasons.append(f"${mine:.4f} a kept question against ${theirs:.4f}, but clearly better work")
        else:
            ok = False
            reasons.append(f"${mine:.4f} a kept question against ${theirs:.4f} — not enough cheaper "
                           f"to be worth a switch")
    return ("recommended" if ok else "not_recommended"), reasons


# ── the weekly run ──────────────────────────────────────────────────────────

@dataclass
class Report:
    run_id: str
    prices: dict[str, Any] = field(default_factory=dict)
    tried: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"run_id": self.run_id, "prices": self.prices, "tried": self.tried,
                "recommendations": self.recommendations, "notes": self.notes,
                "cost_usd": round(self.cost_usd, 4)}


def _budget() -> float:
    from . import platform_settings

    try:
        return max(0.0, float(platform_settings.get("model_scout_budget_usd") or 5))
    except (TypeError, ValueError):
        return 5.0


def _recently_tried() -> set[tuple[str, str]]:
    """(tier, model) pairs tried within the retry window at the prices in force."""
    from ..infra.db import fetch_all

    rows = fetch_all(
        f"""
        SELECT DISTINCT t.tier, t.model
        FROM model_trials t
        LEFT JOIN model_prices p ON p.provider = 'openai' AND p.model = t.model
        WHERE t.role = 'candidate' AND t.created_at > NOW() - INTERVAL '{int(RETRY_AFTER_DAYS)} days'
          AND (p.last_seen IS NULL OR NOT EXISTS (
                SELECT 1 FROM model_price_history h
                WHERE h.provider = 'openai' AND h.model = t.model AND h.seen_at > t.created_at))
        """) or []
    return {(str(r["tier"]), str(r["model"])) for r in rows}


def _file(run_id: str, outcome: Outcome) -> None:
    from ..infra.db import execute

    execute(
        """
        INSERT INTO model_trials (run_id, tier, model, role, grade, subject, strand, sub_strand,
                                  passed, score, requested, accepted, held, cost_usd, seconds, error)
        VALUES (:run_id, :tier, :model, :role, :grade, :subject, :strand, :sub_strand,
                :passed, :score, :requested, :accepted, :held, :cost_usd, :seconds, :error)
        """, {"run_id": run_id, **outcome.__dict__, "error": outcome.error or None})


def run(trigger: str = "schedule", *, run_id: str = "") -> dict[str, Any]:
    """The weekly look. Files everything it does; returns the report."""
    from ..infra.db import execute, to_json
    from . import price_book

    run_id = run_id or f"scout_{time.strftime('%Y%m%d_%H%M%S')}"
    report = Report(run_id=run_id)
    execute("INSERT INTO model_scout_runs (run_id, trigger) VALUES (:id, :trigger) "
            "ON CONFLICT (run_id) DO NOTHING", {"id": run_id, "trigger": trigger})
    started = time.monotonic()
    status, error = "done", None
    try:
        report.prices = price_book.refresh("openai")
        if report.prices.get("problems"):
            report.notes.append("Prices were not updated: " + "; ".join(report.prices["problems"]))

        prices = price_book.known("openai")
        current = {tier: model_policy.tier_model(tier) for tier in TIERS}
        todo = candidates(prices, current, _recently_tried())
        if not todo:
            report.notes.append("No model is cheaper than the ones in use, and nothing new is worth a trial.")
        else:
            rows = panel()
            if not rows:
                report.notes.append("No sub-strand has a filed guide yet, so there is nothing to try models on.")
                todo = []
            budget = _budget()

            def spent() -> float:
                return report.cost_usd

            baseline: list[Outcome] = []
            for row in rows:
                if spent() >= budget or time.monotonic() - started > MAX_SECONDS:
                    break
                outcome = try_once(row, tier="", model=f"{current[WRITER]} / {current[READER]}",
                                   role="baseline")
                baseline.append(outcome)
                report.cost_usd += outcome.cost_usd
                _file(run_id, outcome)
            base_summary = summarise(baseline)

            for cand in todo:
                outcomes: list[Outcome] = []
                for row in rows[:len(baseline)]:
                    if spent() >= budget:
                        report.notes.append(f"Stopped at the ${budget:g} budget.")
                        break
                    if time.monotonic() - started > MAX_SECONDS:
                        report.notes.append("Stopped for time; the rest waits for next week.")
                        break
                    outcome = try_once(row, tier=cand["tier"], model=cand["model"], role="candidate")
                    outcomes.append(outcome)
                    report.cost_usd += outcome.cost_usd
                    _file(run_id, outcome)
                mine = summarise(outcomes)
                decided, reasons = verdict(mine, base_summary)
                entry = {**cand, "metrics": mine, "baseline": base_summary,
                         "verdict": decided, "reasons": reasons}
                report.tried.append(entry)
                if outcomes:
                    report.recommendations.append(_recommend(run_id, entry))
                if spent() >= budget or time.monotonic() - started > MAX_SECONDS:
                    break
    except Exception as exc:  # noqa: BLE001
        status, error = "failed", f"{type(exc).__name__}: {exc}"
        logger.exception("Model scout run %s failed", run_id)
        report.notes.append(f"The run failed: {error}")

    execute(
        """
        UPDATE model_scout_runs SET status = :status, finished_at = NOW(), cost_usd = :cost,
               summary = CAST(:summary AS jsonb), error = :error
        WHERE run_id = :id
        """, {"id": run_id, "status": status, "cost": round(report.cost_usd, 6),
              "summary": to_json(report.to_dict()), "error": error})
    _tell_admins(report, status)
    return {**report.to_dict(), "status": status}


def _recommend(run_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    """File one finding. A recommended one supersedes older weeks' pending
    ones for its tier: last month's numbers are not this month's."""
    from ..infra.db import execute, to_json

    rec_id = f"rec_{hashlib.sha256(f'{run_id}:{entry['tier']}:{entry['model']}'.encode()).hexdigest()[:12]}"
    status = "pending" if entry["verdict"] == "recommended" else "not_recommended"
    if status == "pending":
        # Earlier weeks' open proposals for this tier give way to this week's;
        # this week's stand side by side, and approving one retires the rest.
        execute("UPDATE model_recommendations SET status = 'superseded' "
                "WHERE tier = :tier AND status = 'pending' AND run_id <> :run_id",
                {"tier": entry["tier"], "run_id": run_id})
    execute(
        """
        INSERT INTO model_recommendations (rec_id, run_id, tier, current_model, candidate_model,
                                           verdict, reasons, metrics, status)
        VALUES (:id, :run_id, :tier, :current, :model, :verdict, CAST(:reasons AS jsonb),
                CAST(:metrics AS jsonb), :status)
        ON CONFLICT (rec_id) DO NOTHING
        """, {"id": rec_id, "run_id": run_id, "tier": entry["tier"], "current": entry["current"],
              "model": entry["model"], "verdict": entry["verdict"], "reasons": to_json(entry["reasons"]),
              "metrics": to_json({"candidate": entry["metrics"], "baseline": entry["baseline"],
                                  "why_tried": entry["why"]}),
              "status": status})
    return {"rec_id": rec_id, "tier": entry["tier"], "model": entry["model"],
            "verdict": entry["verdict"], "status": status}


def _tell_admins(report: Report, status: str) -> None:
    """Email the admin list and fire the webhook. Never raises."""
    try:
        from . import platform_settings, webhooks
        from .notifications import notification_service

        recommended = [t for t in report.tried if t["verdict"] == "recommended"]
        new = report.prices.get("new") or []
        changed = report.prices.get("changed") or []
        headline = (f"{len(recommended)} model switch(es) to approve" if recommended
                    else "nothing to switch this week")
        lines = [f"<p><strong>Model scout: {headline}.</strong> "
                 f"Trials cost ${report.cost_usd:.2f}. Run {report.run_id} ({status}).</p>"]
        if new or changed:
            lines.append("<p>Prices: " + ", ".join(
                [f"new {p['model']} (${p['input']}/${p['output']})" for p in new]
                + [f"{p['model']} now ${p['input']}/${p['output']}" for p in changed]) + "</p>")
        for t in report.tried:
            m, b = t["metrics"], t["baseline"]
            lines.append(
                f"<p>{t['tier']}: <strong>{t['model']}</strong> — {t['verdict'].replace('_', ' ')}. "
                f"Passed {m['passed']}/{m['runs']} (in use {b['passed']}/{b['runs']}), "
                f"${(m['cost_per_accepted'] or 0):.4f} a kept question "
                f"(in use ${(b['cost_per_accepted'] or 0):.4f}).</p>")
        for note in report.notes:
            lines.append(f"<p>{note}</p>")
        # Only the configured address: a background job has no request to
        # take one from, and a link to http://localhost helps nobody.
        base = str(platform_settings.get("public_base_url") or "")
        if base:
            lines.append(f'<p><a href="{base.rstrip("/")}/scout">Review and approve</a></p>')
        notification_service.send_admin_email(f"[CBC] Model scout: {headline}", "".join(lines))
        webhooks.emit("model_scout.done", {"run_id": report.run_id, "status": status,
                                           "recommended": [t["model"] for t in recommended],
                                           "cost_usd": round(report.cost_usd, 4)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not tell admins about scout run %s: %s", report.run_id, exc)


# ── deciding ────────────────────────────────────────────────────────────────

def _rec(rec_id: str) -> dict[str, Any]:
    from ..errors import raise_api_error
    from ..infra.db import fetch_one

    row = fetch_one("SELECT * FROM model_recommendations WHERE rec_id = :id", {"id": rec_id})
    if not row:
        raise_api_error("NOT_FOUND", f"No recommendation {rec_id}.")
    return dict(row)


def _tier_bindings(tier: str, model: str) -> list[dict[str, Any]]:
    """Stages of this tier bound, on OpenAI, to exactly this model."""
    from ..infra.db import fetch_all

    rows = fetch_all("SELECT pipeline_stage, provider, model FROM stage_bindings "
                     "WHERE provider = 'openai' AND model = :model", {"model": model}) or []
    return [dict(r) for r in rows if model_policy.tier_of(str(r["pipeline_stage"])) == tier]


def _reload_bindings() -> None:
    try:
        from ..state import runtime_state

        runtime_state.load_from_db()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bindings changed but could not be reloaded here: %s", exc)


_SETTING = {WRITER: "openai_writer_model", READER: "openai_reader_model"}


def approve(rec_id: str, *, by: str) -> dict[str, Any]:
    """Switch the tier to the candidate, remembering exactly what it replaced."""
    from ..errors import raise_api_error
    from ..infra.db import execute, fetch_one, to_json
    from . import platform_settings

    rec = _rec(rec_id)
    if rec["status"] not in ("pending", "not_recommended"):
        raise_api_error("VALIDATION_FAILED", f"This recommendation is {rec['status']}; nothing to approve.")
    tier, new, old = rec["tier"], rec["candidate_model"], rec["current_model"]
    if model_policy.tier_model(tier) != old:
        raise_api_error("VALIDATION_FAILED",
                        f"The {tier} model is now {model_policy.tier_model(tier)}, not {old}, which this "
                        f"trial was measured against. Run the scout again before switching.")

    key = _SETTING[tier]
    stored = fetch_one("SELECT value FROM platform_settings WHERE key = :key", {"key": key})
    bindings = _tier_bindings(tier, old)
    applied = {"setting": key, "previous_setting": (stored or {}).get("value"),
               "bindings": [b["pipeline_stage"] for b in bindings], "from": old, "to": new}

    platform_settings.set_many({key: new}, updated_by=by)
    for b in bindings:
        execute("UPDATE stage_bindings SET model = :model, updated_at = NOW() "
                "WHERE pipeline_stage = :stage", {"model": new, "stage": b["pipeline_stage"]})
    execute(
        """
        UPDATE model_recommendations SET status = 'approved', decided_by = :by, decided_at = NOW(),
               applied = CAST(:applied AS jsonb) WHERE rec_id = :id
        """, {"id": rec_id, "by": by, "applied": to_json(applied)})
    execute("UPDATE model_recommendations SET status = 'superseded' "
            "WHERE tier = :tier AND status = 'pending' AND rec_id <> :id", {"tier": tier, "id": rec_id})
    _reload_bindings()
    logger.info("Model scout: %s switched %s from %s to %s (%s).", by, tier, old, new, rec_id)
    return {**_rec(rec_id), "applied": applied}


def reject(rec_id: str, *, by: str) -> dict[str, Any]:
    from ..errors import raise_api_error
    from ..infra.db import execute

    rec = _rec(rec_id)
    if rec["status"] not in ("pending", "not_recommended"):
        raise_api_error("VALIDATION_FAILED", f"This recommendation is {rec['status']}.")
    execute("UPDATE model_recommendations SET status = 'rejected', decided_by = :by, decided_at = NOW() "
            "WHERE rec_id = :id", {"id": rec_id, "by": by})
    return _rec(rec_id)


def rollback(rec_id: str, *, by: str) -> dict[str, Any]:
    """Put back what an approval replaced — only while it is still in force."""
    from ..errors import raise_api_error
    from ..infra.db import execute
    from . import platform_settings

    rec = _rec(rec_id)
    applied = rec.get("applied") or {}
    if rec["status"] != "approved" or not applied:
        raise_api_error("VALIDATION_FAILED", "Only an approved switch can be rolled back.")
    tier = rec["tier"]
    if model_policy.tier_model(tier) != applied.get("to"):
        raise_api_error("VALIDATION_FAILED",
                        f"The {tier} model has changed since ({model_policy.tier_model(tier)}); roll back "
                        f"the later switch first.")

    previous = applied.get("previous_setting")
    platform_settings.set_many({applied["setting"]: previous if previous not in (None, "") else ""},
                               updated_by=by)
    for stage in applied.get("bindings") or []:
        execute("UPDATE stage_bindings SET model = :model, updated_at = NOW() "
                "WHERE pipeline_stage = :stage AND model = :now",
                {"model": applied["from"], "stage": stage, "now": applied["to"]})
    execute("UPDATE model_recommendations SET status = 'rolled_back', decided_by = :by, "
            "decided_at = NOW() WHERE rec_id = :id", {"id": rec_id, "by": by})
    _reload_bindings()
    logger.info("Model scout: %s rolled %s back to %s (%s).", by, tier, applied["from"], rec_id)
    return _rec(rec_id)


def overview() -> dict[str, Any]:
    """Everything the admin screen shows, in one read."""
    from ..infra.db import fetch_all

    recs = fetch_all("SELECT * FROM model_recommendations ORDER BY created_at DESC LIMIT 60") or []
    runs = fetch_all("SELECT run_id, status, trigger, started_at, finished_at, cost_usd, summary, error "
                     "FROM model_scout_runs ORDER BY started_at DESC LIMIT 12") or []
    prices = fetch_all("SELECT model, input_usd, cached_usd, cache_write_usd, output_usd, first_seen, "
                       "last_seen FROM model_prices WHERE provider = 'openai' ORDER BY output_usd") or []
    history = fetch_all("SELECT model, input_usd, output_usd, seen_at FROM model_price_history "
                        "WHERE provider = 'openai' ORDER BY seen_at DESC LIMIT 40") or []
    latest = runs[0]["run_id"] if runs else ""
    trials = fetch_all("SELECT * FROM model_trials WHERE run_id = :id ORDER BY id",
                       {"id": latest}) if latest else []
    from . import platform_settings

    return {
        "in_use": {tier: model_policy.tier_model(tier) for tier in TIERS},
        "enabled": bool(platform_settings.get("model_scout_enabled")),
        "budget_usd": _budget(),
        "recommendations": recs, "runs": runs, "prices": prices,
        "price_history": history, "latest_trials": trials or [],
    }
