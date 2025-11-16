# monarch-tools

CLI toolbox to help transform credit card statement PDFs into Monarch Money–ready CSVs.

It currently includes these commands:

- `hello` — prints a simple test message
- `name <your_name>` — greets the provided name
- `help` — prints a short command summary
- `activity <type> <pdf>` — parses a statement PDF into an `*.activity.csv`
- `categorize <categories.txt> <rules.json> <activity>` — converts `*.activity.csv` into Monarch‑format CSVs and maintains your merchant/category rules

---

## 1. Installation & setup

From the project root (this folder, containing `pyproject.toml`):

```bash
python3 -m venv .venv
source .venv/bin/activate      # On macOS / Linux

# On Windows (PowerShell)
#   python -m venv .venv
#   .venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -e .
```

If you had an older install:

```bash
python -m pip uninstall -y monarch-tools
pip install -e .
```

After that, you should have a `monarch-tools` CLI on your PATH inside the venv:

```bash
monarch-tools help
```

If PATH is being fussy, you can always run it module‑style:

```bash
python -m monarch_tools.console help
```

---

## 2. High‑level workflow

The intended workflow is:

1. **Extract activity from a statement PDF** → `*.activity.csv`
2. **Categorize merchants** using `categories.txt` and `rules.json`  
   → `*.activity.monarch.csv`
3. **Review uncategorized merchants** using the generated review CSV  
   → edit `rules.json`, rerun `categorize` until satisfied.

The tool keeps:

- A **master** `data/categories.txt` and `data/rules.json`
- **Per‑activity snapshots** of categories and rules (`*.categories.txt`, `*.rules.json`) alongside each `.activity.csv`.

---

## 3. Command reference

### 3.1 `hello`

Sanity check that the CLI is installed and runnable.

```bash
monarch-tools hello
```

### 3.2 `name`

Simple greeting with a name:

```bash
monarch-tools name Keith
```

### 3.3 `help`

Lists available commands briefly:

```bash
monarch-tools help
```

---

### 3.4 `activity` — extract statement activity

```bash
monarch-tools activity <account_type> <statement_pdf> [--debug]
```

Arguments:

- `account_type` — one of:
  - `chase`
  - `citi`
  - `amex`
- `statement_pdf` — either:
  - an absolute/relative filesystem path to the PDF, **or**
  - a filename or relative path that will be resolved under the local `./statements` tree.

The command:

1. Finds the PDF (using a helper that searches under `./statements` if needed).
2. Parses the statement pages.
3. Writes a CSV named like:

   - Input: `statements/chase/9391/2018/20180112-statements-9391.pdf`
   - Output: `statements/chase/9391/2018/20180112-statements-9391.activity.csv`

4. If `--debug` is supplied, it prints diagnostic information (sample parsed lines, counts, etc.) to help tune parsers.

Example:

```bash
monarch-tools activity chase statements/chase/9391/2018/20180112-statements-9391.pdf
```

---

### 3.5 `categorize` — apply merchant rules & generate Monarch CSVs

```bash
monarch-tools categorize [--no-update-rules] <categories.txt> <rules.json> <activity_path>
```

Arguments:

- `categories.txt` — master list of categories (one per line).  
  Recommended location: `data/categories.txt`.
- `rules.json` — master merchant→category rules file.  
  Recommended location: `data/rules.json`.
- `activity_path` — either:
  - a single `*.activity.csv` file, or
  - a directory containing one or more `*.activity.csv` files.

Options:

- `--no-update-rules`  
  Run in a “read‑only” mode: apply existing rules and categories, but do **not** modify `categories.txt` or `rules.json`, and do not write per‑activity snapshots.

---

#### 3.5.1 Expected data files

**`categories.txt`**

Plain text file, one category per line, for example:

```text
Groceries
Dining
Shopping
Travel
Uncategorized
```

`categorize` will:

- Add any *new* categories it discovers (from incoming CSV category fields or rules) to this file.
- Keep the list deduplicated and sorted on write.

**`rules.json`**

JSON document with two main sections:

```json
{
  "rules_version": 1,
  "patterns": [
    {
      "pattern": "SAFEWAY",
      "flags": "i",
      "normalized": "Safeway",
      "category": "Groceries"
    }
  ],
  "exact": {
    "Taco Naco": { "category": "Dining" },
    "AMAZON MKTPLACE PMTS AMZN.COM/BILL WA": { "category": null }
  }
}
```

- `"patterns"` — regex‑based rules (first match wins).  
  `flags` uses Python regex flags letters (`i`, `m`, `s`, `x`).
- `"exact"` — literal, case‑insensitive merchant matches:
  - `{"category": "Groceries"}` → fully defined rule.
  - `{"category": null}` → **stub** rule: known merchant, category not chosen yet.

You do **not** have to maintain the sort order; the tool will keep `"exact"` keys sorted when writing.

---

#### 3.5.2 What `categorize` does per run

For each `*.activity.csv` under `activity_path`:

1. **Detect columns** flexibly:
   - Required:
     - Date (e.g. `Date`, `Transaction Date`, `Posted Date`, …)
     - Amount (`Amount`, `Transaction Amount`, …)
     - Merchant/Payee (`Merchant`, `Payee`, `Description`, …)
   - Optional:
     - Notes (`Notes`, `Note`, `Memo`, …)
     - Category (`Category`, `Categories`)

2. **For each row**:
   - If the CSV already has a **Category** value:
     - That category wins.
     - It is added to `categories.txt` if new.
     - An exact rule is created/updated in `rules.json` for this merchant.
   - Else, try **pattern rules** (`patterns` list).
   - Else, try **exact rules** (`exact` dict).
   - If still no category:
     - Assign `"Uncategorized"`.
     - Ensure `"Uncategorized"` exists in `categories.txt`.
     - Add a stub exact rule with `"category": null` for that merchant.

3. **Write Monarch‑style CSV**

   For each input `foo.activity.csv`, it writes:

   ```text
   foo.activity.monarch.csv
   ```

   with columns:

   ```text
   Date,Payee,Category,Notes,Amount
   ```

   - `Payee` is the normalized merchant (from pattern/ exact rules when applicable).
   - `Notes` combines any Notes/Memo field plus `Original: <raw merchant>` if it differs from the normalized payee.
   - `Amount` is copied from the activity CSV (no sign flip here; the extractor is responsible for that).

4. **Update rules & categories**

   Unless `--no-update-rules` is used:

   - Master `categories.txt` is updated (deduped, sorted).
   - Master `rules.json` is updated (new categories, stub rules, sorted `"exact"` keys).
   - Per‑file snapshots are written next to each `.activity.csv`:

     ```text
     foo.activity.categories.txt
     foo.activity.rules.json
     ```

5. **Generate a review CSV**

   After processing all files, `categorize` builds a **review list** of merchants that are effectively uncategorized and writes:

   ```text
   data/rules.review.csv
   ```

   (same folder as your master `rules.json`).

   This CSV contains:

   ```text
   Merchant,CurrentCategory,CountInThisRun
   AMAZON MKTPLACE PMTS AMZN.COM/BILL WA,,7
   SAFEWAY #1138 BELMONT CA,,8
   ...
   ```

   - `Merchant` — canonical merchant name (normalized payee).
   - `CurrentCategory` — whatever is currently stored in `rules.json` (blank if `null`).
   - `CountInThisRun` — how many times this merchant ended up as `Uncategorized` in this categorize run.

   The console summary also prints:

   - New categories discovered
   - New stub merchants added
   - A short list of merchants still `Uncategorized`.

---

## 4. Recommended iterative workflow

### Step 1 — Extract an activity CSV

```bash
monarch-tools activity chase statements/chase/9391/2018/20180112-statements-9391.pdf
```

This should produce:

```text
statements/chase/9391/2018/20180112-statements-9391.activity.csv
```

### Step 2 — First categorize pass

Assuming:

- `data/categories.txt`
- `data/rules.json`

exist (they may start almost empty):

```bash
monarch-tools categorize data/categories.txt data/rules.json     statements/chase/9391/2018/20180112-statements-9391.activity.csv
```

Results:

- `20180112-statements-9391.activity.monarch.csv`
- Updated `data/categories.txt`
- Updated `data/rules.json`
- Per‑file snapshots:
  - `20180112-statements-9391.activity.categories.txt`
  - `20180112-statements-9391.activity.rules.json`
- A `data/rules.review.csv` file listing merchants that still need categories, with counts.

### Step 3 — Review and assign categories

1. Open `data/rules.review.csv` in a spreadsheet (Numbers / Excel / Sheets).
2. Sort by `CountInThisRun` (descending) to focus on the most common uncategorized merchants first.
3. For each merchant you care about, edit `data/rules.json`:

   ```json
   "AMAZON MKTPLACE PMTS AMZN.COM/BILL WA": { "category": "Shopping" }
   ```

4. If you introduce brand‑new category names, `categorize` will automatically add them to `categories.txt` on the next run.

### Step 4 — Re‑run `categorize`

Run the same command again:

```bash
monarch-tools categorize data/categories.txt data/rules.json     statements/chase/9391/2018/20180112-statements-9391.activity.csv
```

You should see:

- Fewer merchants in `rules.review.csv`.
- `*.activity.monarch.csv` now filled with real categories for the merchants you just configured.

Repeat Steps 3–4 until `rules.review.csv` is empty or only contains merchants you don’t care to categorize.

---

## 5. Notes

- All parsing and categorization logic lives in `src/monarch_tools/console.py`.
- The entry point is exposed via `pyproject.toml` under `[project.scripts]` as `monarch-tools`.
- For IDEs like PyCharm, you can run the module directly:

  ```bash
  python -m monarch_tools.console categorize data/categories.txt data/rules.json path/to/activity
  ```

- The `help` text for each command is always available:

  ```bash
  monarch-tools activity --help
  monarch-tools categorize --help
  ```

This README describes the “current workflow as programmed” — extract activity, categorize with iterative rules, and review uncategorized merchants using the generated CSV.
