# FitFindr

FitFindr is a multi-tool AI agent that helps you discover secondhand clothing and figure out how to wear it with what you currently have. Begin by typing your search criteria; the agent searches a mock listings dataset, proposes an outfit based on things in your wardrobe, and even generates a shareable caption for the look.

Python, Gradio, Groq API(`llama-3.3-70b-versatile`).

## What's Included

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example wardrobe
├── screenshots/               # Triggered-failure evidence for the demo
│   ├── no_results.png
│   ├── empty_wardrobe.png
│   └── empty_outfit.png
├── tests/
│   └── test_tools.py          # pytest tests for every failure mode (14 total)
├── utils/
│   └── data_loader.py         # Helper functions for loading the data
├── agent.py                   # Planning loop + session state + retry logic
├── app.py                     # Gradio UI
├── conftest.py                # Empty — tells pytest where the repo root is
├── planning.md                # The spec, written before implementation
├── README.md
├── requirements.txt
└── tools.py                   # The four tools (3 required + 1 stretch)
```

## Setup

```bash
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (get a free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

## Running It
 
Start the Gradio app:
```bash
python app.py
```
Open the localhost URL
 
Run the test suite:
```bash
pytest tests/ -v
```
 
Run the agent from the command line:
```bash
python agent.py
```

## Listing Dataset (mock)
`data/listings.json` has 40 mock secondhand listings ranging from a myraid of categories (tops, bottoms, outerwear, shoes, accessories) and styles (vintage, y2k, grunge, cottagecore, streetwear, etc).

Each listing has: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`

## Tool Set

The model uses 3 tools, each being a standable function within `tools.py`

### Tool 1: `search_listings(description, size, max_price)`

**What it does:**
Search through the 40 listings in `data/listing.json` and return the ones that matches the user's request. 

Look at the description's words, size, and price, and ranks the result by how many description words show up in the listing

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `description` (str): Search words the user wants to find, like `"vintage graphic tee"`, but split into individual words to be checked against each listing's `title`,`description`, and `style_tags`. For every word that shows up, add 1 to listing's score.

- `size` (str; None): Size to match, like `"M"` or `"30"`. Checked as substring so `"30"` would still work against `"W30 L30"`. None to skip size filter.

- `max_price` (float): Most user is willing to pay. Hence, listing priced higher than requested are dropped.

**What it returns:**
A list of listing dicts. Each with fields identical to the original: `id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, and `platform`. List is sorted highest score first and if nothing matches, then return empty list.

**Goal**: turn user's natural langaue query into a ranked list of matching items from dataset

---

### Tool 2: `suggest_outfit(new_item, wardrobe)`

**What it does:**
Takes 1 listing (new piece) and the user's wardrobe, then have Groq LLM `llama-3.3-70b-versatile` suggest how to wear the new pieve with 1-3 pieces the user already owns. Suggestion mentions wardrobe items by name and have specific styling tips, such as tucking or layering. If in the case that user wardrobe is empty, it switches to a different prompt that gives general styling ideas that uses more of the common basics styling logic.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): 1 listing dict from `search_listing`. It is then dropped into the prompt, which the LLM uses, from `title`, `description`, `colors`, `style_tags`, and `category`, to determine what to pair it with.

- `wardrobe` (dict): wardrobe in the format `{"items": [...]}`, divided into `id`, `name`, `category`, `colors`, `style_tags`,  `notes`. Empty wardrobe is just `{"items": []}`.

**What it returns:**
String that is usually 2-5 sentences that describes 1 outfit that mixes the new piece with owned wardrobe pieces (or basics if user wardrobe is empty). If LLM call fails, then return string `"[suggest_outfit error]"` such that the next tool is able to see that something went wrong. 

**Goal**: turn listing + wardrobe into styling advice

---

### Tool 3: `create_fit_card(outfit, new_item)`

**What it does:**
Take outfit suggestion and the new item and ask LLM to write a short (1-3 sentence) caption like the one you see on Instagram. Uses high temperature such that running it twice on same input would give diff captions. 

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (str): Styling string from `suggest_outfit` used so that the caption talks about the same pieces.
- `new_item` (dict): Same listing dict from `search_listing` and used such that the caption can mention the price, platform or brand. 


**What it returns:**
String 1-3 sentences in casual lowercase voice with at most 1 emoji. Diff each time due to high temperature.

**Goal**: turn outfit into sharable post caption

### Tool 4: `compare_price(item, all_listings)` (+2)

**Input parameters:**
- `item` (dict): the listing to assess, usually `session["selected_item"]`.
- `all_listings` (list[dict] | None): pool to compare against. `None` means load the full dataset.

**What it returns:**
dict with `verdict` ("great deal", "fair price", "slightly above average", "above average", or "unknown"), `message` (assessment with reasoning), underlying numbers(item_price, median, mean, min, max, comparables_count, style_matched_median)

**Goal**: tell user whether price is fair with reasoning based on comparable listings of the same category. Stretch feature section below goes more into detail.

---

## Planning Loop

**How does your agent decide which tool to call next?**
Loop lives in `agent.py::run_agent()`. Doesn't call all 3 tools unconditionally, depends on what `search_listing` returns. 


Loop from top to bottom but there are branches in between to stop it. Whether or not the next tool runs depends on if the previous tool returns or not.
```
1. Parse user query into (description, size, max_price). Small LLM call
   pulls these out of natural language. Defaults: description = the raw
   query, size = None, max_price = 9999.
 
2. Call search_listings(description, size, max_price).
   - if results == []:
       session["error"] = "No listings matched 'X' in size Y under $Z. Try a
                          broader description, removing the size filter, or
                          raising your max price."
       session["selected_item"] = None
       session["outfit_suggestion"] = None
       session["fit_card"] = None
       RETURN session   <-- early exit, the other two tools do NOT run
   - else:
       session["selected_item"] = results[0]   # top-ranked item
       continue
 
3. Call suggest_outfit(session["selected_item"], wardrobe).
       session["outfit_suggestion"] = whatever it return (could be normal
       styling string, empty wardrobe fallback string, or
       "[suggest_outfit error]").
       continue, don't stop here on an error string, create_fit_card will catch it.
 
4. Call create_fit_card(session["outfit_suggestion"], session["selected_item"]).
       session["fit_card"] = whatever it return (a caption, or
       "[create_fit_card error]" if the outfit was missing).
 
5. Return session.
```

Step 2 makes the agent adaptive. Normal query runs all 3 tools. Impossible query like "designer ballgown size XXS under $5" stops after step 2 with just an error message, `suggest_outfit` and `create_fit_card` never runs.

**Stretch additions**. Step 2 now goes through `_search_with_retry`, automatically loosen size and price filters 2x before saying no results. Between step 2 and 3, loop calls `compare_price(selected_item)`, stores result in `session["price_assessment"]` so UI can display a price check alongside the listing.

---

## State Management

**How does information from one tool get passed to the next?**
A `session` dict is created at the start of `run_agent()` and is updates upon each step. Every key starts at `None`.

| Key | Set by | Used by |
| --- | --- | --- |
| `query` | `run_agent()` entry | parser, debugging |
| `parsed` | `_parse_query()` | `search_listings` |
| `search_results` | `_search_with_retry()` | branch check, selection |
| `selected_item` | step 4 (top of results) | `suggest_outfit`, `create_fit_card`, `compare_price` |
| `wardrobe` | `run_agent()` entry | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit()` | `create_fit_card` |
| `fit_card` | `create_fit_card()` | UI |
| `error` | step 3 (only when results are empty after retries) | UI |
| `retry_notes` | `_search_with_retry()` | UI (banner) |
| `price_assessment` | `compare_price()` | UI |

`app.py::handle_query()` calls `run_agent(query, wardrobe)`, reads session, routes its keys into three Gradio panels. User never needs to reenter anything mid-flow, `selected_item` written after the search and read by all three downstream tools without user ever seeing dict.

---

## Error Handling

**Each tool failure modes:**

| Tool              | Failure mode                          | Agent response |
| ----------------- | ------------------------------------- | -------------- |
| search\_listings  | No listings match the query           | Makes `session["error"]`: *"No listings matched '{description}' in size {size} under ${max_price}. Try a broader description, removing the size filter, or raising your max price."* Returns early in that `suggest_outfit` and `create_fit_card` don't run. UI shows error and leaves other two panels blank. |
| suggest\_outfit   | Wardrobe is empty                     | Not error, function notices `wardrobe["items"] == []` and use fallback prompt that suggests styling with general advice on basics instead of wardrobe items. A normal string comes back and the flow keeps going. |
| suggest\_outfit   | LLM call raises an exception          | try/except catches, returns `"[suggest_outfit error] Could not generate an outfit right now — {reason}. You can still see the item details above."` Rest continues and `create_fit_card` sees prefix and skips own call. |
| create\_fit\_card | Outfit input is missing or broken     | Checks `outfit == ""` or `outfit.startswith("[suggest_outfit error]")`. Returns `"[create_fit_card error] No outfit was generated, so there's nothing to caption yet. Try a different query."` without calling the LLM. |
| create\_fit\_card | LLM call raises an exception          | try/except catches, returns `"[create_fit_card error] Caption generation failed — {reason}."` |
| `compare_price` (stretch) | Item missing `price` or `category` | Returns `verdict="unknown"` with a `[compare_price error]` prefix in message. No crash, planning loop stores it and continues |
| `compare_price` (stretch) | Fewer than 2 comparable listings | Returns `verdict="unknown"` with specific reason: *"Not enough comparable listings in the {category} category to give a price assessment."* |

**A concrete example from testing.** When I ran the query '"designer ballgown size XXS under $5"' through the 'python agent.py', the parser successfully extracted 'description="designer ballgown"`, `size="XXS"`, `max_price=5.0`. `search_listings` returned `[]`, retry loosened the size and raised the price cap, but nothing came back. The planning loop defined:

```
session["error"] = "No listings matched 'designer ballgown' (size XXS, under $5),
even after loosening the size and price filters. Try a broader description."
session["outfit_suggestion"] = None
session["fit_card"] = None
```

---

## Architecture

```
User query + wardrobe
    │
    ▼
Parse query → (description, size, max_price)
    │
    ▼
Planning Loop ───────────────────────────────────────────────┐
    │                                                        │
    ├─► search_listings(description, size, max_price)        │
    │       │ results=[]                                     │
    │       ├──► [ERROR] session["error"] = "..." → return   │
    │       │                                                │
    │       │ results=[item, ...]                            │
    │       ▼                                                │
    │   Session: selected_item = results[0]                  │
    │       │                                                │
    ├─► suggest_outfit(selected_item, wardrobe)              │
    │       │                                                │
    │   Session: outfit_suggestion = "..."                   │
    │   (normal string, empty-wardrobe fallback, or          │
    │    "[suggest_outfit error]" prefix on LLM failure)     │
    │       │                                                │
    └─► create_fit_card(outfit_suggestion, selected_item)    │
            │                                                │
        Session: fit_card = "..."                            │
        (caption, or "[create_fit_card error]" if outfit     │
         was empty or carried the suggest_outfit error)      │
            │                                                └─ error path returns here
            ▼
        Return session
            │
            ▼
        app.py renders item card, outfit text, fit card
        (or the error message)
```

---


## Spec Reflection

**Where spec helped:** 
Writing `planning.md` before any code required me to establish the failure modes ahead of time, particularly the distinction between *"empty wardrobe"* (not an error, switch to a fallback prompt) and *"LLM call broke"* (real error, return error prefixed string). When I implemented `suggest_outfit'`, I didn't have to pause and think about what should happen as the specification already indicated so. Same with `create_fit_card`: knowing ahead of time that an upstream `"[suggest_outfit error]"` prefix would short circuit the next LLM call allowed me to write the guard before creating the prompt, rather than adding it later.

**Where implementation diverged**:
The spec said that query parsing will involve a short LLM call. While implementing it, I found it was overkill as each interaction would have burnt a Groq call based just on parsing, with non-deterministic consequences. In `agent.py::_parse_query()`, I switched to a regex parser to catch typical patterns (*"under $30"*, *"size M"*, etc.) and then returned the raw query as the description. It is faster, free, and predictable. The trade-off is that unique phrasings may not be recognized, nevertheless, in practice, `search_listings` keyword-scoring still captures the majority of the intent because unparsed phrasing just becomes more keywords.


## Stretch Features
 
### Retry Logic with Fallback (+1)

Before the no result error, `search_listings` is retried with looser constraints. Lives in `agent.py::_search_with_retry()`

Order of Retries:
1. Original `(description, size, max_price)`
2. If empty and size provided, retry without size filter
3. If still empty and max_price set, retry without size filter and with price cap 2x the original

Each retry that succeedss add a human readable note to the `session["retry_notes"]`. Gradio UI should have some sort of display "Auto adjusted search" above the lsiting so the user knows what changed.

If all attempt still return empty, `session["error"]` is set as before but message now says `"even after loosening the size and price filters"` so user know we tried.

### Tool 4: compare_price (+2)

Takes listing and assess whether price makes sense compared to other listing within the same category. 

**Input parameters**:
- `item` (dict): listing to assess, usually `session["selected_item"]`
- `all_listings` (list[dict], None): pool to compare against. `None` mean load full dataset thru `load_listings()`.

**Returns**:
dict with `verdict`, `message`,  and `underlying numbers`

```
- verdict: ("great deal", "fair price", "slightly above average", "above average", "unknown")
- message:  (a human-readable assessment string with reasoning)
- underlying numbers: (`item_price`, `median`, `mean`, `min`, `max`, `comparables_count`, `style_matched_median`)
```

**How comparisons made:**
Filter dataset to listings in same `category` as the item (exclude item itself). Compute median, mean, min, max of those prices. Verdict based on ratio of item price to category median
- ratio <=  0.75 → great deal
- ratio <= 1.10 → fair price
- ratio <= 1.40 → slightly above avg
- ratio > 1.40 → above avg

`Styled matched median` also computed by weighing comparable that share the same `style_tags` with the item such that if it differs from all category median, it gets included in the msg so that the user sees both brand and style relevant content. 

**What happens if fail or return nothing**:
- Item missing `price` or `category`, returns `verdict="unknown"` with `[compare_price error]` prefix in message. No crash

- < 2 comparable listings in the category, returns `verdict="unknown"` with specific reason `"Not enough comparable listings in the bottoms category..."`

- `load_listings()` raises, returns `verdict="unknown"` with `[compare_price error]` prefix

Agent calls `compare_price` after `selected_item` set, stores returned dict in `session["price_assessment"]`, UI shows assessment msg bottom of listing panel.

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1:**
<!-- What does the agent do first? Which tool is called? With what input? -->
`search_listings`: Parser pulls out `description="vintage graphic tee"`, `size=None`, `max_price=30.0`, call `search_listings("vintage graphic tee", size=None, max_price=30.0)`, return sorted list of matching listing dicts. Top result may look like:

```
{"id": "lst_017", "title": "Faded Band Tee — Soft Cotton",
 "price": 22.0, "platform": "depop",
 "style_tags": ["vintage", "graphic", "grunge"], ...}
```

`session["selected_item"]` set to this dict.

**Step 2:**
<!-- What happens next? What was returned from step 1? What tool is called now? -->

`suggest_outfit`: call `suggest_outfit(session["selected_item"], example_wardrobe)`, LLM sees tee and 10 wardrobe items (which includes the jeans and chunky sneakers  user mentioned), returns 
```
"Pair this faded band tee with your baggy straight-leg jeans and chunky platform sneakers for a classic 90s grunge feel. Roll the sleeves once and tuck the front corner of the tee into the waistband to add shape, then layer a thin gold chain over the top."
```

`session["outfit_suggestion"]` set to this string

**Step 3:**
<!-- Continue until the full interaction is complete -->
`create_fit_card`: call `create_fit_card(session["outfit_suggestion"], session["selected_item"])`, LLM sees styling text and listing price $22, platform depop, and brand. Temp is high so the caption is different every run.
Return 
```
"thrifted this faded band tee off depop for $22 and honestly it was made for my baggy jeans 🖤 full look in stories"
```

`session["fit_card"]` set to this string
 

**Final output to user:**
<!-- What does the user actually see at the end? -->
- Item found: Faded Band Tee $22, Depop, Good condition
- How to style: the outfit text from Step 2
- Fit card: the caption from Step 3

If original query was impossible, like `"designer balenciaga Versace ballgown size XXXXXS under $5"`, Step 1 would have returned `[]`, `session["error"]` would set, Steps 2 and 3 no run, and UI would just show the error with suggestion to the user on how to broaden the search

---

## AI Usage

1. Implementing `search_listings.` Gave Tool 1 specification from `planning.md` and a sample listing dictionary for developing the implementation with `load_listings()`. Made sure it filtered by all three parameters, returned `[]` when no matches, matched keywords across `title` + `description` + `style_tags`, and utilized substring size matching such that `"30"` matched `"W30 L30"`. Tests initially produced no results since I had forgotten to save the file. (Claude helped me figure this out). After saving, it provided 29 results for "vintage graphic tee", [] for the impossible query, and adhered to the price limit. Used Claude to help me control my defensive `.get()` field access and `try except` around `load_listings()`.

2. Implementing the planning loop. Wrote run_agent() with the Planning Loop section, State Management table, and architectural diagram from planning.md as a reference. Early on, I chose a regex _parse_query() over the spec's LLM-based parser since it was faster, free, and deterministic, and aligned session key names with the scaffold (`parsed`, `search_results`). Used Claude to validate the branching logic and found that both paths worked: the joyful path filled all three session fields, and the impossible query branch correctly left outfit_suggestion and fit_card as None.

3. Stretch Features. Created compare_price in pure Python (no LLM) and computed `median/mean/min/max` across same category listings. Added a style matched median weighted by overlapping style_tags as same category goods might vary greatly by price tier. (Claude assisted me with the weighting logic). Created the three-step retry logic (original → drop size → drop size + double price cap) and utilized Claude to ensure each retrial only fired on empty result and that retry_notes appropriately represented what was loosened. New pytest tests for both increased the suite's passing rate from 9 to 14.

---