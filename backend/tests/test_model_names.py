"""A stage bound to a model must send THAT model.

A run failed with "Model 'gemini-1.5-pro' not found on gemini". Nobody had
bound a stage to gemini-1.5-pro: the router's alias table matched on the bare
word "pro" and rewrote every Gemini model containing it — gemini-2.5-pro
included — to a model Google has since retired.
"""
from __future__ import annotations

from app.services import review_vendors
from app.services.provider_router import normalize_model_name as normalise


# ── a name that is already a model id is left alone ─────────────────────────


def test_a_current_gemini_model_is_not_rewritten_to_a_retired_one():
    assert normalise("gemini", "gemini-2.5-pro") == "gemini-2.5-pro"
    assert normalise("gemini", "gemini-2.5-flash") == "gemini-2.5-flash"


def test_a_gemini_model_that_does_not_exist_yet_still_passes_through():
    """A mapping table that must be edited before a new model can be used is a
    mapping table that is out of date every time one ships."""
    assert normalise("gemini", "gemini-3-pro-preview") == "gemini-3-pro-preview"


def test_a_current_anthropic_model_is_not_rewritten_to_a_2024_one():
    """`"opus" in lower` sent every Opus binding to claude-3-opus-20240229."""
    assert normalise("anthropic", "claude-opus-4-20250514") == "claude-opus-4-20250514"
    assert normalise("anthropic", "claude-sonnet-4-5") == "claude-sonnet-4-5"


def test_gpt_5_is_no_longer_treated_as_a_typo_for_gpt_4o_mini():
    """It was listed as a typo, written when no such model existed. A stage
    bound to it was served something cheaper and the run SUCCEEDED, which is
    the version of this bug that never gets reported."""
    assert normalise("openai", "gpt-5") == "gpt-5"


# ── a name that is only a family still resolves ─────────────────────────────


def test_a_bare_family_name_still_becomes_a_real_model():
    assert normalise("gemini", "pro").startswith("gemini-")
    assert normalise("gemini", "flash").startswith("gemini-")
    assert normalise("anthropic", "sonnet").startswith("claude-")
    assert normalise("openai", "4o") == "gpt-4o"


def test_an_empty_binding_falls_back_rather_than_failing():
    for provider, prefix in (("gemini", "gemini-"), ("anthropic", "claude-"),
                             ("openai", "gpt-")):
        for empty in ("", "  ", "default", "none", "null"):
            assert normalise(provider, empty).startswith(prefix)


# ── the catalogue does not offer retired models ─────────────────────────────


def test_the_review_catalogue_does_not_offer_a_retired_gemini_model():
    gemini = review_vendors.REVIEW_MODELS["gemini"]

    assert "gemini-1.5-pro" not in gemini["models"]
    assert "gemini-1.5-flash" not in gemini["models"]
    assert gemini["default"] in gemini["models"]


def test_every_vendor_default_is_one_of_its_own_models():
    for vendor, meta in review_vendors.REVIEW_MODELS.items():
        assert meta["default"] in meta["models"], vendor


def test_retired_models_keep_their_prices():
    """An old job's recorded cost still has to resolve after the model is
    gone, or the spend history quietly reads as zero."""
    from app.services.cost_tracker import MODEL_PRICING

    assert "gemini-1.5-pro" in MODEL_PRICING


# ── asking the provider instead of guessing ─────────────────────────────────


def test_bindings_can_be_checked_before_a_run_rather_than_during_one():
    from app.services import model_catalogue

    assert hasattr(model_catalogue, "live_models")
    assert hasattr(model_catalogue, "check_bindings")
    assert set(model_catalogue._LISTERS) == {"openai", "anthropic", "gemini", "ollama"}


def test_the_check_reports_the_name_that_will_be_sent():
    """The typed name and the sent name differed, and that difference is half
    this bug — so a check on the typed name would have passed."""
    import inspect

    source = inspect.getsource(model_catalogue_check())
    assert "normalize_model_name(provider, raw)" in source
    assert '"typed"' in source


def model_catalogue_check():
    from app.services import model_catalogue

    return model_catalogue.check_bindings


def test_gemini_listing_keeps_only_models_that_can_generate():
    """The list also carries embedding and vision-only models, which would 400
    on generateContent — a second dead binding of exactly the same shape."""
    import inspect

    from app.services import model_catalogue

    assert "generateContent" in inspect.getsource(model_catalogue._gemini)
