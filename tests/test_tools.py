"""
tests/test_tools.py

Tests for the FitFindr tools and planning loop. At least one test per
failure mode. Run with: pytest tests/ -v
"""
from tools import search_listings, suggest_outfit, create_fit_card, compare_price
from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── search_listings ──────────────────────────────────────────────────────────

def test_search_returns_results():
    """Happy path: normal query returns at least one matching listing."""
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    assert "title" in results[0]
    assert "price" in results[0]


def test_search_empty_results_no_exception():
    """Failure mode: impossible query returns [] without raising."""
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter_enforced():
    """Price cap must be respected — no result above max_price."""
    results = search_listings("jeans", size=None, max_price=25)
    assert all(item["price"] <= 25 for item in results)


def test_search_size_substring_match():
    """Size matching is substring, so '30' should match 'W30 L30'."""
    results = search_listings("jeans", size="30", max_price=100)
    for item in results:
        assert "30" in (item.get("size") or "").lower()


# ── suggest_outfit ───────────────────────────────────────────────────────────

def test_suggest_outfit_empty_wardrobe_no_error_prefix():
    """Failure mode: empty wardrobe must NOT return an error-prefixed string.
    The fallback prompt should produce a real styling suggestion using basics."""
    listings = search_listings("vintage graphic tee", None, 50)
    assert listings, "search_listings should return at least one result"
    result = suggest_outfit(listings[0], get_empty_wardrobe())
    assert isinstance(result, str)
    assert len(result) > 20
    assert not result.startswith("[suggest_outfit error]")


def test_suggest_outfit_malformed_item_returns_error_string():
    """Failure mode: malformed/missing item returns an error-prefixed string,
    not a Python exception."""
    result = suggest_outfit({}, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.startswith("[suggest_outfit error]")


# ── create_fit_card ──────────────────────────────────────────────────────────

def test_fit_card_empty_outfit_returns_error_string():
    """Failure mode: empty outfit string returns an error-prefixed string,
    no LLM call needed."""
    listings = search_listings("vintage graphic tee", None, 50)
    assert listings
    result = create_fit_card("", listings[0])
    assert isinstance(result, str)
    assert result.startswith("[create_fit_card error]")


def test_fit_card_upstream_error_short_circuits():
    """Failure mode: if outfit carries [suggest_outfit error], fit card must
    detect it and short-circuit with its own error — no LLM call."""
    listings = search_listings("vintage graphic tee", None, 50)
    assert listings
    upstream_error = "[suggest_outfit error] Something went wrong upstream."
    result = create_fit_card(upstream_error, listings[0])
    assert result.startswith("[create_fit_card error]")


def test_fit_card_malformed_item_returns_error_string():
    """Failure mode: empty item dict returns an error-prefixed string."""
    result = create_fit_card("Wear this with your jeans.", {})
    assert isinstance(result, str)
    assert result.startswith("[create_fit_card error]")


# ── compare_price (stretch tool) ─────────────────────────────────────────────

def test_compare_price_returns_assessment():
    """Happy path: a real listing produces a structured assessment."""
    listings = search_listings("vintage graphic tee", None, 50)
    assert listings
    result = compare_price(listings[0])
    assert isinstance(result, dict)
    assert result["verdict"] in {
        "great deal", "fair price", "slightly above average", "above average"
    }
    assert isinstance(result["message"], str) and len(result["message"]) > 20
    assert result["comparables_count"] >= 2


def test_compare_price_handles_missing_fields():
    """Failure mode: malformed item returns an 'unknown' verdict, no crash."""
    result = compare_price({})
    assert result["verdict"] == "unknown"
    assert result["message"].startswith("[compare_price error]")


def test_compare_price_with_empty_pool():
    """Failure mode: not enough comparables → 'unknown' verdict, no crash."""
    fake_item = {"id": "x", "category": "bottoms", "price": 30, "style_tags": []}
    result = compare_price(fake_item, all_listings=[])
    assert result["verdict"] == "unknown"
    assert result["comparables_count"] == 0


# ── retry-with-fallback (stretch in run_agent) ───────────────────────────────

def test_run_agent_retries_when_tight_constraints_fail():
    """Stretch: a tight query that returns [] should be retried with loosened
    filters, succeed, and report what was adjusted in session['retry_notes']."""
    # This query is likely too tight on first pass (size XS + $10 cap),
    # but should succeed after dropping size / raising price.
    session = run_agent(
        query="vintage graphic tee size XS under $10",
        wardrobe=get_example_wardrobe(),
    )

    # Either the retry succeeded (with notes) or even retries failed (clean error)
    if session["selected_item"] is not None:
        assert session["retry_notes"], "Should have logged at least one retry note"
        assert session["fit_card"] is not None
    else:
        assert session["error"] and "broader description" in session["error"].lower()


def test_run_agent_no_retries_on_happy_path():
    """Stretch: a normal query that succeeds immediately should NOT log retries."""
    session = run_agent(
        query="vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    assert session["selected_item"] is not None
    assert session["retry_notes"] == []