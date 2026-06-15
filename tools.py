"""
tools.py

The FitFindr tools. Each tool is a standalone function that can be called
and tested independently before being wired into the agent loop.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
    compare_price(item, all_listings)               → dict   (stretch)
"""

import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Returns a list of matching listing dicts, sorted by relevance (best first).
    Returns [] if nothing matches — does NOT raise.
    """
    # Load listings — defensive against the loader failing
    try:
        listings = load_listings()
    except Exception as e:
        print(f"[search_listings] Could not load listings: {e}")
        return []

    # Split description into lowercase keywords
    keywords = description.lower().split() if description and description.strip() else []

    scored = []
    for listing in listings:
        # Price filter (skip listings priced above the cap)
        if max_price is not None:
            price = listing.get("price")
            if price is None or price > max_price:
                continue

        # Size filter — substring match, case-insensitive
        # So "30" matches "W30 L30" and "M" matches "S/M"
        if size is not None:
            listing_size = (listing.get("size") or "").lower()
            if size.lower() not in listing_size:
                continue

        # Score by keyword overlap against title + description + style_tags
        haystack = " ".join([
            listing.get("title") or "",
            listing.get("description") or "",
            " ".join(listing.get("style_tags") or []),
        ]).lower()
        score = sum(1 for kw in keywords if kw in haystack)

        # Drop zero-score listings (unless no keywords were given at all)
        if keywords and score == 0:
            continue

        scored.append((score, listing))

    # Sort by score, highest first
    scored.sort(key=lambda x: x[0], reverse=True)
    return [listing for _, listing in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 outfits.

    Returns a non-empty string with outfit suggestions. If the wardrobe is
    empty, offers general styling advice instead of raising or returning empty.
    On LLM failure, returns a string starting with "[suggest_outfit error]".
    """
    # Guard against malformed input
    if not isinstance(new_item, dict) or not new_item:
        return "[suggest_outfit error] No item was provided to style. Try a search first."

    # Pull the item details we want the LLM to see
    item_title = new_item.get("title", "this piece")
    item_desc = new_item.get("description", "")
    item_colors = ", ".join(new_item.get("colors") or []) or "unspecified colors"
    item_tags = ", ".join(new_item.get("style_tags") or [])
    item_category = new_item.get("category", "item")

    # Decide which prompt to use based on wardrobe
    items = (wardrobe or {}).get("items", [])

    if not items:
        # Empty wardrobe: ask for generic styling with basics, not an error
        prompt = f"""You're a casual personal stylist. The user just got a thrifted piece but hasn't told you what else they own. Give a short outfit suggestion (2-4 sentences) that pairs this piece with common basics (white tee, mid-wash denim, simple sneakers, etc.) and ends with one styling tip like tucking, layering, or rolling sleeves.

New piece: {item_title}
Category: {item_category}
Colors: {item_colors}
Style tags: {item_tags}
Description: {item_desc}

Sound conversational, not like a product description."""
    else:
        # Format the wardrobe so the LLM can reference items by name
        wardrobe_lines = []
        for w in items:
            name = w.get("name", "unnamed item")
            tags = ", ".join(w.get("style_tags") or [])
            colors = ", ".join(w.get("colors") or [])
            wardrobe_lines.append(
                f"- {name} (category: {w.get('category', '?')}, colors: {colors}, tags: {tags})"
            )
        wardrobe_text = "\n".join(wardrobe_lines)

        prompt = f"""You're a casual personal stylist. Suggest ONE complete outfit (2-4 sentences) that pairs this new thrifted piece with 1-3 items from the user's wardrobe. Reference wardrobe items by their exact name. End with one specific styling tip (tucking, layering, rolling sleeves, etc.).

New piece: {item_title}
Category: {item_category}
Colors: {item_colors}
Style tags: {item_tags}
Description: {item_desc}

User's wardrobe:
{wardrobe_text}

Be specific about how to wear it. Sound conversational, not like a product description."""

    # Call the LLM defensively — return an error-prefixed string on failure
    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        text = response.choices[0].message.content
        if not text or not text.strip():
            return "[suggest_outfit error] LLM returned an empty response. Try the query again."
        return text.strip()
    except Exception as e:
        return (
            f"[suggest_outfit error] Could not generate an outfit right now — "
            f"{type(e).__name__}: {e}. You can still see the item details above."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Returns a 1–3 sentence caption string. If the outfit is empty or carries
    an upstream "[suggest_outfit error]" prefix, returns a "[create_fit_card
    error] ..." string without calling the LLM.
    """
    # Guard 1: empty or whitespace-only outfit
    if not outfit or not outfit.strip():
        return ("[create_fit_card error] No outfit was generated, so there's "
                "nothing to caption yet. Try a different query.")

    # Guard 2: upstream tool errored — don't waste an LLM call on broken input
    if outfit.startswith("[suggest_outfit error]"):
        return ("[create_fit_card error] No outfit was generated (the outfit "
                "step failed), so there's nothing to caption yet.")

    # Guard 3: need a real listing to mention
    if not isinstance(new_item, dict) or not new_item:
        return "[create_fit_card error] No item details were provided."

    title = new_item.get("title", "this piece")
    price = new_item.get("price", "?")
    platform = new_item.get("platform", "")
    brand = new_item.get("brand", "")

    prompt = f"""Write a short (1-3 sentence) caption for an Instagram or TikTok post about this thrifted outfit. Voice: casual, lowercase, first-person, like a real OOTD post. Include the price and platform naturally (e.g. "thrifted this off depop for $22"). Mention the brand only if it's notable. At most one emoji. Do NOT sound like a product description.

Item: {title}
Brand: {brand}
Price: ${price}
Platform: {platform}

The outfit it's part of:
{outfit}

Give just the caption, no quotes or explanation."""

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.95,
            max_tokens=120,
        )
        text = response.choices[0].message.content
        if not text or not text.strip():
            return "[create_fit_card error] LLM returned an empty caption. Try again."
        return text.strip()
    except Exception as e:
        return f"[create_fit_card error] Caption generation failed — {type(e).__name__}: {e}."


# ── Tool 4 (stretch): compare_price ──────────────────────────────────────────

def compare_price(item: dict, all_listings: list[dict] | None = None) -> dict:
    """
    Assess whether a listing's price is fair compared to other listings
    in the same category. Pure-Python (no LLM call).

    Args:
        item:          A listing dict (typically session["selected_item"]).
        all_listings:  Full pool of listings to compare against. If None,
                       loads the full dataset.

    Returns:
        A dict with:
          - verdict:           "great deal" | "fair price"
                               | "slightly above average" | "above average"
                               | "unknown"
          - message:           A human-readable assessment string with reasoning
          - item_price:        the item's price
          - median:            median of comparable listings
          - mean:              mean of comparable listings
          - min, max:          range of comparable prices
          - comparables_count: how many comparables were used
          - style_matched_median: median of style-overlapping comparables (if any)
    """
    # Load comparison pool if not supplied
    if all_listings is None:
        try:
            all_listings = load_listings()
        except Exception as e:
            return {
                "verdict": "unknown",
                "message": f"[compare_price error] Could not load comparison data: {e}",
                "comparables_count": 0,
            }

    # Guard against missing fields
    if not isinstance(item, dict) or "price" not in item or "category" not in item:
        return {
            "verdict": "unknown",
            "message": "[compare_price error] Item is missing price or category.",
            "comparables_count": 0,
        }

    item_price = item.get("price")
    item_category = item.get("category")
    item_tags = set(item.get("style_tags") or [])
    item_id = item.get("id")

    # Find comparables: same category, exclude the item itself, must have numeric price
    comparables = [
        l for l in all_listings
        if l.get("category") == item_category
        and l.get("id") != item_id
        and isinstance(l.get("price"), (int, float))
    ]

    if len(comparables) < 2:
        return {
            "verdict": "unknown",
            "message": (
                f"Not enough comparable listings in the {item_category} category "
                f"to give a price assessment (found {len(comparables)}, need 2+)."
            ),
            "comparables_count": len(comparables),
        }

    prices = sorted(l["price"] for l in comparables)
    n = len(prices)
    median = prices[n // 2] if n % 2 == 1 else (prices[n // 2 - 1] + prices[n // 2]) / 2
    mean = sum(prices) / n
    pmin, pmax = prices[0], prices[-1]

    # Style-matched median: bias toward listings with overlapping style_tags
    style_matched_median = None
    if item_tags:
        weighted = []
        for c in comparables:
            overlap = len(set(c.get("style_tags") or []) & item_tags)
            if overlap > 0:
                weighted.append((overlap, c["price"]))
        if len(weighted) >= 2:
            weighted.sort(key=lambda x: x[0], reverse=True)
            top_prices = sorted(p for _, p in weighted[:5])
            m = len(top_prices)
            style_matched_median = (
                top_prices[m // 2] if m % 2 == 1
                else (top_prices[m // 2 - 1] + top_prices[m // 2]) / 2
            )

    # Verdict based on item_price vs median
    ratio = item_price / median if median > 0 else 1
    if ratio <= 0.75:
        verdict = "great deal"
        emoji = "🔥"
    elif ratio <= 1.10:
        verdict = "fair price"
        emoji = "✅"
    elif ratio <= 1.40:
        verdict = "slightly above average"
        emoji = "⚠️"
    else:
        verdict = "above average"
        emoji = "💸"

    message = (
        f"{emoji} {verdict.capitalize()}. "
        f"This ${item_price:.0f} {item_category} sits against {n} other {item_category} "
        f"listings ranging ${pmin:.0f}–${pmax:.0f} (median ${median:.0f}, mean ${mean:.0f})."
    )
    if style_matched_median is not None and style_matched_median != median:
        message += f" Style-matched median: ${style_matched_median:.0f}."

    return {
        "verdict": verdict,
        "message": message,
        "item_price": item_price,
        "median": median,
        "mean": round(mean, 2),
        "min": pmin,
        "max": pmax,
        "comparables_count": n,
        "style_matched_median": style_matched_median,
    }