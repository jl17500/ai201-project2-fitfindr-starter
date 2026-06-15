"""
agent.py

The FitFindr planning loop. Orchestrates the four tools in response to a
natural language user query, passing state between them via a session dict.

Usage:
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card, compare_price


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """Initialize a fresh session dict for one user interaction."""
    return {
        "query": query,
        "parsed": {},
        "search_results": [],
        "selected_item": None,
        "wardrobe": wardrobe,
        "outfit_suggestion": None,
        "fit_card": None,
        "error": None,
        # stretch additions:
        "retry_notes": [],          # list of strings describing any auto-loosening
        "price_assessment": None,   # dict returned by compare_price
    }


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """Pull description, size, and max_price out of a natural-language query
    using regex. Predictable, fast, and doesn't burn an LLM call per request.
    """
    parsed = {
        "description": query.strip() if query else "",
        "size": None,
        "max_price": None,
    }

    if not query or not query.strip():
        return parsed

    price_match = re.search(
        r"(?:under|less than|below|max(?:imum)?|up to)\s*\$?\s*(\d+(?:\.\d+)?)",
        query, re.IGNORECASE,
    )
    if not price_match:
        price_match = re.search(r"\$\s*(\d+(?:\.\d+)?)", query)
    if price_match:
        try:
            parsed["max_price"] = float(price_match.group(1))
        except ValueError:
            pass

    size_match = re.search(r"size\s+([A-Za-z0-9]+)", query, re.IGNORECASE)
    if size_match:
        parsed["size"] = size_match.group(1).upper()

    desc = query
    if price_match:
        desc = desc.replace(price_match.group(0), "")
    if size_match:
        desc = desc.replace(size_match.group(0), "")
    desc = re.sub(r"\s+", " ", desc).strip()
    parsed["description"] = desc if desc else query.strip()

    return parsed


# ── planning loop ─────────────────────────────────────────────────────────────

def _search_with_retry(parsed: dict) -> tuple[list, list[str]]:
    """Run search_listings, and if it returns [], retry with loosened filters.

    Order of retries:
        1. First attempt: original params (description, size, max_price).
        2. If empty AND size was provided: retry without size.
        3. If still empty AND max_price was set: retry without size and with
           the price cap raised to 2x the original.

    Returns:
        (results, retry_notes) — retry_notes is a list of human-readable
        strings describing what (if anything) was adjusted.
    """
    retry_notes = []

    # Attempt 1: original
    results = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )
    if results:
        return results, retry_notes

    # Attempt 2: drop the size filter
    if parsed["size"]:
        results = search_listings(
            description=parsed["description"],
            size=None,
            max_price=parsed["max_price"],
        )
        if results:
            retry_notes.append(
                f"no matches in size {parsed['size']}, so I dropped the size filter"
            )
            return results, retry_notes

    # Attempt 3: drop size AND raise price ceiling
    if parsed["max_price"] is not None:
        loosened_price = parsed["max_price"] * 2
        results = search_listings(
            description=parsed["description"],
            size=None,
            max_price=loosened_price,
        )
        if results:
            note = f"no matches under ${parsed['max_price']:.0f}"
            if parsed["size"]:
                note += f" in size {parsed['size']}"
            note += f", so I raised the cap to ${loosened_price:.0f}"
            if parsed["size"]:
                note += " and dropped the size filter"
            retry_notes.append(note)
            return results, retry_notes

    # All attempts failed
    return [], retry_notes


def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for one interaction
    and returns the completed session dict.

    The loop branches on what search_listings returns:
        - results == []     after retries → set session["error"], return early.
                            suggest_outfit and create_fit_card do NOT run.
        - results == [...]  → pick the top result, run compare_price, then
                            continue through suggest_outfit and create_fit_card.
                            Both downstream tools handle their own internal
                            failure modes by returning error-prefixed strings,
                            so the flow never crashes mid-run.
    """
    # Step 1: Initialize the session
    session = _new_session(query, wardrobe)

    # Step 2: Parse the query
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]

    # Step 3: Search listings, with retry-on-empty
    results, retry_notes = _search_with_retry(parsed)
    session["search_results"] = results
    session["retry_notes"] = retry_notes

    # Branch: no matches even after retries → early exit
    if not session["search_results"]:
        filters = []
        if parsed["size"]:
            filters.append(f"size {parsed['size']}")
        if parsed["max_price"] is not None:
            filters.append(f"under ${parsed['max_price']:.0f}")
        filter_str = " (" + ", ".join(filters) + ")" if filters else ""
        session["error"] = (
            f"No listings matched '{parsed['description']}'{filter_str}, even after "
            f"loosening the size and price filters. Try a broader description."
        )
        return session

    # Step 4: Pick the top-ranked result
    session["selected_item"] = session["search_results"][0]

    # Step 5: Price comparison (pure-Python, no LLM)
    session["price_assessment"] = compare_price(session["selected_item"])

    # Step 6: Suggest an outfit (handles empty wardrobe and LLM errors internally)
    session["outfit_suggestion"] = suggest_outfit(
        new_item=session["selected_item"],
        wardrobe=wardrobe,
    )

    # Step 7: Generate a fit card (detects upstream errors and short-circuits)
    session["fit_card"] = create_fit_card(
        outfit=session["outfit_suggestion"],
        new_item=session["selected_item"],
    )

    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"Price assessment: {session['price_assessment']['message']}")
        if session["retry_notes"]:
            print(f"Retry notes: {session['retry_notes']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== Retry path: very tight constraints that get loosened ===\n")
    session_r = run_agent(
        query="vintage graphic tee size XS under $10",
        wardrobe=get_example_wardrobe(),
    )
    if session_r["error"]:
        print(f"Error: {session_r['error']}")
    else:
        print(f"Found: {session_r['selected_item']['title']}")
        print(f"Retry notes: {session_r['retry_notes']}")

    print("\n\n=== No-results path (even retries fail) ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
    print(f"outfit_suggestion (should be None): {session2['outfit_suggestion']}")
    print(f"fit_card (should be None): {session2['fit_card']}")