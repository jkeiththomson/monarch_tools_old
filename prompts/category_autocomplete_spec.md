# Category Autocomplete Spec

This spec describes a **fast, forgiving, keyboard-first autocomplete** for the provided category list. fileciteturn0file0

---

## Goals

1. **Find the intended category in 1–3 keystrokes** for most inputs.
2. **Handle partial words, typos, and spacing** (e.g., `gas elec` → *Gas & Electric*).
3. **Stable + predictable ranking** (results shouldn’t “jump around” unexpectedly).
4. **Accessible** (screen readers, ARIA combobox pattern).
5. **Deterministic** (same input → same results).

Non-goals:
- Full NLP intent classification. This is autocomplete over a finite set.

---

## Data model

Each category becomes an item:

```json
{
  "id": "gas-electric",          // stable, URL-safe slug
  "label": "Gas & Electric",     // what user sees
  "norm": "gas and electric",    // normalized label used for matching
  "tokens": ["gas","and","electric"],
  "aliases": ["gas electric"]    // optional extra phrases
}
```

### Normalization rules (critical)
Normalize both the **user input** and each **label** the same way:

1. Unicode normalize (NFKD) then remove diacritics
2. Lowercase
3. Replace `&` with `and`
4. Convert punctuation to spaces: `/ - , . ' ( )` → space
5. Collapse whitespace to single spaces
6. Trim

Examples:
- `"Arts & Crafts"` → `"arts and crafts"`
- `"Taxi & Ride Shares"` → `"taxi and ride shares"`
- `"Restaurants & Bars"` → `"restaurants and bars"`

---

## Matching strategy

Use a **hybrid** approach:
1. **Token prefix matching** (best UX)
2. **Subsequence matching** (for “gse” type inputs)
3. **Fuzzy edit-distance** (for minor typos: `securty` → *Social Securty*)
4. **Exact/contains** boosts for strong signals

### Step 1 — Parse input
Given `q_raw`, compute:
- `q_norm`
- `q_tokens` = split on spaces
- `q_compact` = remove spaces (for subsequence checks)

If `q_norm` is empty → show **top / recent** list (see below).

### Step 2 — Candidate generation
To keep it fast, generate candidates with cheap checks first:

Candidate if any is true:
- Any token in `q_tokens` is a prefix of any label token
- `q_norm` is a substring of `label.norm`
- `q_compact` is a subsequence of `label.norm` (letters in order)
- Fuzzy threshold (only run if previous checks didn’t find enough results)

> Optimization: build an **inverted index** from token prefixes → category ids (see Performance).

### Step 3 — Scoring (deterministic)
Compute a score per candidate and sort descending, with deterministic tie-breakers.

Recommended scoring components (tunable):

| Component | Description | Example | Points |
|---|---|---:|---:|
| Exact label match | `q_norm == label.norm` | `groceries` | +1000 |
| Token starts-with | each query token matches start of any label token | `gas` in *Gas & Electric* | +200 per matched token |
| Whole-word match | token equals a label token | `gas` | +80 |
| Substring match | `q_norm in label.norm` | `ride` in *Taxi & Ride Shares* | +60 |
| Tokens in order | query tokens appear in label tokens in same order (not necessarily adjacent) | `postage ship` | +80 |
| Starts-with label | label.norm starts with q_norm | `art` → *Art* | +120 |
| Length penalty | prefer shorter labels when close | *Art* vs *Arts & Crafts* | −0.5 × (len(label.norm) − len(q_norm)) |
| Fuzzy distance | if using edit distance (Damerau-Levenshtein) | `securty` | +max(0, 50 − 10×distance) |

**Tie-breakers (in order):**
1. Higher score
2. Higher “prefix coverage” (more query tokens matched as prefixes)
3. Shorter `label.norm` length
4. Alphabetical by `label` (case-insensitive)
5. Stable by `id`

---

## UI/UX behavior

### Control type
Use an **ARIA combobox** with:
- input box
- popup listbox
- active descendant for highlighted item

### Interactions
- Typing filters results live (debounce 20–50ms if needed)
- **Arrow Down/Up** moves highlight
- **Enter** selects highlighted item
- **Tab** accepts highlighted item (optional; common UX)
- **Escape** closes popup (does not clear input)
- **Cmd/Ctrl+K** (optional) focuses the field

### Display formatting
Each suggestion row shows:
- **Label** (as-is)
- Highlight matched parts (bold) by prefix/token match
- Optional right-side hint (e.g., “exact”, “close match”) during debugging only

### Empty states
- If no matches:
  - Show “No matches”
  - Offer “Keep as typed” only if your product allows free-form categories; otherwise disable.

### Default suggestions (when input empty)
Show one of:
1. **Most recently used categories** (best)
2. Or fixed “top” categories (e.g., *Groceries, Gas, Restaurants & Bars, Mortgage*) if you can’t track recency.

---

## Handling synonyms & aliases (recommended)

Some categories are easier with aliases:
- *Gas & Electric* ⇐ `utilities`, `electric`, `pg&e`
- *Internet & Cable* ⇐ `wifi`, `broadband`, `comcast`
- *Taxi & Ride Shares* ⇐ `uber`, `lyft`, `rideshare`
- *Restaurants & Bars* ⇐ `restaurant`, `bar`, `pub`
- *Health Insurance* ⇐ `medical insurance`
- *Rx* ⇐ `prescription`, `pharmacy`

Implementation:
- Maintain an optional `aliases[]` array per item.
- During scoring, treat alias norms as additional searchable strings with a slightly lower base score than label.

---

## Performance considerations

Even with ~85 items, brute-force per keystroke is fine, but do it cleanly.

### Indexing (optional but “best way”)
Build:
- `token_prefix_index[prefix] -> set(category_id)` for prefixes length 1..N (cap at 6)
- `label_norm_strings` array for quick substring checks

Candidate generation becomes:
1. Union of ids from prefixes of each query token
2. Plus substring/subsequence fallbacks

### Complexity target
- Under 1–2ms per keystroke on a typical laptop

---

## Edge cases

- `&` vs `and`: already normalized
- Multiple spaces / punctuation: normalized
- Common typos: fuzzy fallback
- Similar labels: prefer shorter exact/prefix (*Art* before *Arts & Crafts*)
- “Other” vs “Uncategorized”: if user types `unc`, push *Uncategorized* above *Other*

---

## Testing checklist

1. Prefix matches:
   - `art` → *Art*, *Arts & Crafts*
2. Multi-token:
   - `post ship` → *Postage & Shipping*
3. Ampersand:
   - `gas elec` → *Gas & Electric*
4. Typos:
   - `securty` → *Social Securty*
5. Short tokens:
   - `rx` → *Rx*
6. Ranking stability:
   - adding a character should only narrow/re-rank logically

---

## Reference category list (input)

- Accessories
- Apps
- Art
- Arts & Crafts
- Auto Fees
- Auto Insurance
- Beer & Wine
- Books
- Charity
- Check
- Christmas
- Clothing
- Coffee Shops
- Coin Storage
- Computer
- Credit Card Fees
- Dance
- Dentist
- Doctor
- Electronics
- Fitness
- Food
- Furniture
- Garage
- Gas
- Gas & Electric
- Gifts
- Groceries
- Halloween
- Health Insurance
- HOA
- Home Insurance
- Housekeeping
- Housewares
- Internet & Cable
- KB Pilates LLC
- Labs
- Landscaping
- LeakSentinel
- Life Insurance
- Lodging
- Magazines
- Maintenance & Repairs
- Mass Transit
- Meals
- Miscellaneous
- Mortgage
- Movies
- Museums
- Music
- Newspapers
- OTC
- Other
- Other Income
- Outdoor
- Parking
- Parking & Tolls
- Parties
- Personal
- Pet Insurance
- Phone
- Podcasts
- Postage & Shipping
- Rental Cars
- Restaurants & Bars
- Rx
- Services
- Sightseeing
- SJWS
- Social Securty
- Sports
- Starting Balance
- Storage
- Taxes
- Taxi & Ride Shares
- Theater
- Toys
- Trash & Recycling
- Travel
- Tuition
- Uncategorized
- Video Games
- Videos
- Vision
- Water
