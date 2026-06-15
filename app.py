"""
app.py

Gradio interface for FitFindr. Calls run_agent() and maps the session results
to the output panels.

Run with:
    python app.py
"""

import gradio as gr

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── query handler ────────────────────────────────────────────────────────────

def _format_listing(item: dict, price_assessment: dict | None = None) -> str:
    """Render a listing dict + price assessment as a readable block."""
    if not item:
        return ""
    title = item.get("title", "Untitled")
    price = item.get("price", "?")
    brand = item.get("brand", "")
    platform = item.get("platform", "")
    condition = item.get("condition", "")
    size = item.get("size", "")
    colors = ", ".join(item.get("colors") or [])
    tags = ", ".join(item.get("style_tags") or [])
    description = item.get("description", "")

    lines = [
        f"{title}",
        f"${price} · {platform} · {condition} condition",
        f"Brand: {brand}" if brand else "",
        f"Size: {size}" if size else "",
        f"Colors: {colors}" if colors else "",
        f"Tags: {tags}" if tags else "",
        "",
        description,
    ]

    if price_assessment and price_assessment.get("message"):
        lines.extend(["", "— Price check —", price_assessment["message"]])

    return "\n".join(line for line in lines if line != "" or line == "")


def handle_query(user_query: str, wardrobe_choice: str) -> tuple[str, str, str]:
    """Called by Gradio. Returns three strings, one per output panel:
        (listing_text, outfit_suggestion, fit_card)
    """
    # Guard 1: empty query
    if not user_query or not user_query.strip():
        return (
            "Please type what you're looking for above — e.g. 'vintage graphic tee under $30'.",
            "",
            "",
        )

    # Pick wardrobe based on the radio button
    if wardrobe_choice == "Empty wardrobe (new user)":
        wardrobe = get_empty_wardrobe()
    else:
        wardrobe = get_example_wardrobe()

    # Run the agent — all four tools, retry logic, planning loop, etc.
    session = run_agent(query=user_query, wardrobe=wardrobe)

    # Branch 1: search returned nothing even after retries → error in first panel
    if session["error"]:
        return (session["error"], "", "")

    # Branch 2: happy path — build the listing text, possibly with a retry note
    listing_text = _format_listing(session["selected_item"], session.get("price_assessment"))

    if session.get("retry_notes"):
        retry_banner = "⚙️  Auto-adjusted your search: " + "; ".join(session["retry_notes"]) + "\n\n"
        listing_text = retry_banner + listing_text

    outfit_text = session["outfit_suggestion"] or ""
    fit_card_text = session["fit_card"] or ""
    return (listing_text, outfit_text, fit_card_text)


# ── interface ────────────────────────────────────────────────────────────────

EXAMPLE_QUERIES = [
    "vintage graphic tee under $30",
    "90s track jacket in size M",
    "flowy midi skirt under $40",
    "black combat boots size 8",
    "vintage graphic tee size XS under $10",   # triggers retry-with-fallback
    "designer ballgown size XXS under $5",     # deliberate no-results test
]

def build_interface():
    with gr.Blocks(title="FitFindr") as demo:
        gr.Markdown("""
# FitFindr 🛍️
Find secondhand pieces and get outfit ideas based on your wardrobe.
Describe what you're looking for — include size and price if you want to filter.
        """)

        with gr.Row():
            query_input = gr.Textbox(
                label="What are you looking for?",
                placeholder="e.g. vintage graphic tee under $30, size M",
                lines=2,
                scale=3,
            )
            wardrobe_choice = gr.Radio(
                choices=["Example wardrobe", "Empty wardrobe (new user)"],
                value="Example wardrobe",
                label="Wardrobe",
                scale=1,
            )

        submit_btn = gr.Button("Find it", variant="primary")

        with gr.Row():
            listing_output = gr.Textbox(
                label="🛍️ Top listing found",
                lines=10,
                interactive=False,
            )
            outfit_output = gr.Textbox(
                label="👗 Outfit idea",
                lines=10,
                interactive=False,
            )
            fitcard_output = gr.Textbox(
                label="✨ Your fit card",
                lines=10,
                interactive=False,
            )

        gr.Examples(
            examples=[[q, "Example wardrobe"] for q in EXAMPLE_QUERIES],
            inputs=[query_input, wardrobe_choice],
            label="Try these queries",
        )

        submit_btn.click(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )
        query_input.submit(
            fn=handle_query,
            inputs=[query_input, wardrobe_choice],
            outputs=[listing_output, outfit_output, fitcard_output],
        )

    return demo


if __name__ == "__main__":
    demo = build_interface()
    demo.launch()