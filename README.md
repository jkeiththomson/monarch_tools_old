# monarch-tools

CLI toolbox to help transform credit card statement PDFs into Monarch Money–ready CSVs.

It currently includes these commands:

- `hello` — prints a simple test message
- `name <your_name>` — greets the provided name
- `help` — prints a short command summary
- `activity <type> <pdf>` — parses a statement PDF into an `*.activity.csv`
- `categorize <categories.txt> <groups.txt> <rules.json> <activity.csv>` — interactively maintains categories, groups, and merchant rules

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

### 3.5 `categorize` — interactively build categories, groups, and rules

```bash
monarch-tools categorize <categories.txt> <groups.txt> <rules.json> <activity_csv>
```

Arguments:

- `categories.txt` — master list of categories (one per line).  
  Recommended location: `data/categories.txt`.
- `groups.txt` — mapping of *groups* to categories (for nicer dashboards), in the format:

  ```text
  # Lines starting with # are comments
  [Essentials]
  Groceries
  Dining

  [Housing]
  Utilities
  Insurance

  [Other]
  Uncategorized
  ```

- `rules.json` — master merchant→category rules file.  
  Recommended location: `data/rules.json`.
- `activity_csv` — a single `<stem>.activity.csv` file produced by the `activity` command.

What `categorize` does:

1. Loads the existing `categories.txt`, `groups.txt`, and `rules.json` files (creating default structures in memory if they are missing).
2. Walks each row in the given `activity_csv`, focusing on the **Description** column.
3. For each raw merchant description:
   - Ensures there is a **canonical merchant name** in `raw_to_canonical`.
   - Ensures that canonical merchant has a **category** in `exact`.
   - Ensures that category appears in `categories.txt`.
   - Ensures that category belongs to a group in `groups.txt` (prompting you to pick or create a group if needed).
4. Writes updated versions of:
   - `categories.txt`
   - `groups.txt`
   - `rules.json`

This version of `categorize` is intentionally simple: it **does not** write a Monarch‑format CSV yet.  
Instead, it focuses on helping you interactively curate a clean set of merchants, categories, and groups that other tooling can reuse.
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

- The command‑line *wiring* lives in `src/monarch_tools/console.py`.
- The actual business logic is split by command in:
  - `src/monarch_tools/activity.py`
  - `src/monarch_tools/categorize.py`
  - `src/monarch_tools/hello.py`
  - `src/monarch_tools/name.py`
  - `src/monarch_tools/help.py`
- The CLI entry point is exposed via `pyproject.toml` under `[project.scripts]` as `monarch-tools`.

  That means you can run any command either as:

  ```bash
  monarch-tools activity chase statements/chase/9391/2018/20180112-statements-9391.pdf
  ```

  or, equivalently:

  ```bash
  python -m monarch_tools activity chase statements/chase/9391/2018/20180112-statements-9391.pdf
  ```

- The `--help` text for each command is always available:

  ```bash
  monarch-tools activity --help
  monarch-tools categorize --help
  monarch-tools hello --help
  monarch-tools name --help
  monarch-tools help
  ```

- `groups.txt` is treated as a required mapping from groups to categories. Whenever `categorize`
  adds a new category, it will prompt you to assign that category to a group and will write a
  consistent `groups.txt` file back to disk.
---
