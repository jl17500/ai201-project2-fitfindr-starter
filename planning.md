# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

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

**What happens if it fails or returns nothing:**
If nothing returns or fails, empty list `[]` would return instead of crashing. Planning loop would see the empty list and writes a message to `session["error"]`. Return early, hence, `suggest_outfit` and `create_fit_card` don't run. 

---

### Tool 2: suggest_outfit

**What it does:**
Takes 1 listing (new piece) and the user's wardrobe, then have Groq LLM `llama-3.3-70b-versatile` suggest how to wear the new pieve with 1-3 pieces the user already owns. Suggestion mentions wardrobe items by name and have specific styling tips, such as tucking or layering. If in the case that user wardrobe is empty, it switches to a different prompt that gives general styling ideas that uses more of the common basics styling logic.

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `new_item` (dict): 1 listing dict from `search_listing`. It is then dropped into the prompt, which the LLM uses, from `title`, `description`, `colors`, `style_tags`, and `category`, to determine what to pair it with.

- `wardrobe` (dict): wardrobe in the format `{"items": [...]}`, divided into `id`, `name`, `category`, `colors`, `style_tags`,  `notes`. Empty wardrobe is just `{"items": []}`.

**What it returns:**
String that is usually 2-5 sentences that describes 1 outfit that mixes the new piece with owned wardrobe pieces (or basics if user wardrobe is empty). If LLM call fails, then return string `"[suggest_outfit error]"` such that the next tool is able to see that something went wrong. 

**What happens if it fails or returns nothing:**
- One reason could be because of empty wardrobe `wardrobe["items"] == [], which isn't actually an error. But the function should notice this and utilize the fallback prompt that produces a general styling advice.
- Another could because of the LLM call breaking, like network error, bad API key, or rate limit, which will be caught with try except. Returns `"[suggest_outfit error]...{short reason}."` It would then continue to `create_fit_card`, which would check for the [suggest_outfit error] prefix and skip the LLM call. 

---

### Tool 3: create_fit_card

**What it does:**
Take outfit suggestion and the new item and ask LLM to write a short (1-3 sentence) caption like the one you see on Instagram. Uses high temperature such that running it twice on same input would give diff captions. 

**Input parameters:**
<!-- List each parameter, its type, and what it represents -->
- `outfit` (str): Styling string from `suggest_outfit` used so that the caption talks about the same pieces.
- `new_item` (dict): Same listing dict from `search_listing` and used such that the caption can mention the price, platform or brand. 


**What it returns:**
String 1-3 sentences in casual lowercase voice with at most 1 emoji. Diff each time due to high temperature.

**What happens if it fails or returns nothing:**
- Outfit string is empty or starts with `[suggest_outfit error]`and returns `[create_fit_card error] No outfit was generated, so there's nothing to caption yet. Try a different query.` and never calls LLM. 

- LLM call breaks that is caught with try except and returns `"[create_fit_card error] Caption generation failed {short reason}."`

---

### Additional Tools (if any)
`compare_price` in stretch feature section (look below)

---

## Planning Loop

**How does your agent decide which tool to call next?**
Loop from top to bottom but there are branches in between to stop it. 
Whether or not the next tool runs depends on if the previous tool returns or not.

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


---

## State Management

**How does information from one tool get passed to the next?**
A `session` dict is created at the start of `run_agent()` and is updates upon each step. Every key starts at `None`.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool              | Failure mode                          | Agent response |
| ----------------- | ------------------------------------- | -------------- |
| search\_listings  | No listings match the query           | Makes `session["error"]`: *"No listings matched '{description}' in size {size} under ${max_price}. Try a broader description, removing the size filter, or raising your max price."* Returns early in that `suggest_outfit` and `create_fit_card` don't run. UI shows the error and leaves the other two panels blank. |
| suggest\_outfit   | Wardrobe is empty                     | Not error. Function notices `wardrobe["items"] == []` and use fallback prompt that suggests styling with general advice on basics instead of wardrobe items. A normal string comes back and the flow keeps going. |
| suggest\_outfit   | LLM call raises an exception          | try/except catches. Returns `"[suggest_outfit error] Could not generate an outfit right now — {reason}. You can still see the item details above."` Rest continues and `create_fit_card` sees the prefix and skips its own call. |
| create\_fit\_card | Outfit input is missing or broken     | Checks `outfit == ""` or `outfit.startswith("[suggest_outfit error]")`. Returns `"[create_fit_card error] No outfit was generated, so there's nothing to caption yet. Try a different query."` without calling the LLM. |
| create\_fit\_card | LLM call raises an exception          | try/except catches. Returns `"[create_fit_card error] Caption generation failed — {reason}."` |

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

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

Use Claude for one tool at a time not all 3 in 1 big prompt. 

- `search_listings`: Paste Tool 1 block from this `planning.md` and the listing schema from `data/listing.json` then ask Claude to write the function using `load_listings()` from `utils/data_loader.py`. Now before even running anything, I'll first check: does it filter by all 3 parameters, returns `[]` rather than crashing when nothing matches, keyword matching at `title`, `description`, AND `style_tags`, size matching use substring so that `"30"` can match with `"W30 L30"`. Then test all 3 queries.

- `suggest_outfit`: Paste Tool 2 block and alos one example listing and one wardrobve item from the data files and ask Claude to implement such with Groq. Then I'll check if theres a separate branch for the empty wardrobe case, whether Groq call is wrapped in `try except` such that it returns the `[suggest_outfit error]` rather than crash, prompt actually include wardrobe item names such that the output can mention them. Then run it once with `get_example_wardrobe()` and once with `get_empty_wardrove()`.

- `create_fit_card`: Same thing. Check if temp 0.9 or greater, if empty error outfit case return documented erorr string and not call LLM, if propt ask for the causal voice. Then call 3 times on same input and make sure the captions are diff.

**Milestone 4 — Planning loop and state management:**

Paste the whole Planning Loop section, State Management table and ASCII diagram into Claude and have it support me in developing `run_agent(query, wardrobe)` in `agent.py`. Before running going to check if `session` fict with all 6 keys created at top, empty results branch return early (so like no calls to `suggest_outfit` after that), `session["selected_item"]` set from `results[0]` before downstream call, any hardcoded items between steps that should've been reading from `session`. Then run 2 queries with one happy and one impossible and print the session dict each time to confirm rigght keys being populated.


---

## A Complete Interaction (Step by Step)

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.


FitFindr is a multi tool agent that assist its users in finding a secondhand piece, figure out ways to wear it with what they already own, and even get a shareable caption for posting on social media. How it works is by you just typing what you're looking for and the agent essentially takes it from there.First it searches through the listings for matches, then it looks through your wardrobe to suggest how to wear the top result, and finally it writes a short caption that you can actually post. If the search comes up empty, it stops and gives you suggestion on how you can broaden your search rather than guessing through the rest of the steps.

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


