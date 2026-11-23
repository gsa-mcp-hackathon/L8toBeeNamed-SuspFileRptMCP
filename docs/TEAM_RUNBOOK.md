# Team Runbook — Personnel Processing Monitor

A beginner-friendly guide for getting the project running on your machine,
running checks, and exploring the dashboard. No production data or credentials
are required.

---

## 1. Prerequisites

Before you start, make sure the following are installed on your machine:

| Tool | Minimum version | How to check |
|------|----------------|--------------|
| **Python** | 3.11 | `python3 --version` |
| **uv** | any recent | `uv --version` |
| **Git** | any | `git --version` |
| **IBM Bob** | any | Installed as a desktop application |

If `uv` is not installed, follow the instructions at
<https://docs.astral.sh/uv/getting-started/installation/>.

---

## 2. Open the Repository in IBM Bob

1. Launch **IBM Bob** from your desktop or application menu.
2. Choose **Open Folder** (or press `Ctrl+K`, then `Ctrl+O`).
3. Navigate to the cloned repository folder and click **Open**.
4. Bob will index the workspace automatically. You can start chatting in the
   **Agent** tab once indexing finishes.

If you have not cloned the repository yet, run:

```bash
git clone <repository-url>
cd mcp-hackathon-template
```

Then open the resulting folder in Bob.

---

## 3. Install Dependencies with uv

From a terminal opened at the repository root, run:

```bash
uv sync
```

This reads `pyproject.toml` and `uv.lock`, creates a virtual environment in
`.venv/`, and installs every dependency at the pinned versions. You do **not**
need to create a virtual environment manually — `uv` handles it.

> **Tip:** Run `uv sync` again any time `pyproject.toml` or `uv.lock` changes
> (for example after pulling new commits).

---

## 4. Configure Your Environment

```bash
cp .env.example .env
```

Open `.env` and set these two paths:

```
DAT_FILE_PATH=sample-data/AI_HACK_TEST_TWO.DAT
REFERENCE_FILE_PATH=reference-data/sinq_error_reference.txt
```

- `DAT_FILE_PATH` — your NFC return `.DAT` file. Place it in `sample-data/`
  (which is gitignored) or any path outside the repository.
- `REFERENCE_FILE_PATH` — the approved SINQ error reference table. The file
  `reference-data/sinq_error_reference.txt` is already included in the repo.

**Never commit your `.env` file.** It is listed in `.gitignore` but verify
before every push.

---

## 5. Run Ruff (Linter)

[Ruff](https://docs.astral.sh/ruff/) checks the code for style and common
errors without modifying any files.

```bash
uv run ruff check .
```

A clean run prints nothing and exits with code `0`. If Ruff reports issues,
fix them before opening a pull request. Do **not** use `--fix` unless you
understand what will change.

---

## 6. Run the Tests

```bash
uv run pytest tests/ -v
```

All tests use synthetic, in-memory or `tmp_path` files — they never read
production data. A healthy run ends with output similar to:

```
384 passed, 0 failed
```

If any test fails, do not merge your changes until the failure is resolved.

---

## 7. Start the Dashboard in HTTP Mode

```bash
MCP_TRANSPORT=streamable-http uv run example-server
```

The server starts on **port 8000**. You will see startup log lines in the
terminal. Leave this terminal window open — closing it stops the server.

---

## 8. Open /dashboard

Once the server is running, open the dashboard in your browser:

```
http://localhost:8000/dashboard
```

On Linux: `xdg-open http://localhost:8000/dashboard`
On macOS: `open http://localhost:8000/dashboard`
On Windows: paste the URL into your browser.

The page shows:

- **Summary cards** — total valid records, parse-error count, total SINQ
  errors, records with SINQ errors, and a source breakdown (EmpowHR /
  Employee Personal Page / Unknown).
- **SINQ error breakdown** — hierarchical view: outer rows are SINQ error
  codes sorted by descending total count. Each outer row expands to show
  inner rows grouped by DOCU_TYPE, with the matching record count and the
  approved reference description for that (DOCU_TYPE, error code) pair.
  Click **Show all / Show fewer** to expand or collapse the full list.
- **Results table** — paginated records showing line number, GVT_SUB_AGENCY,
  COMPANY, DOCU_TYPE, source, SINQ_ERROR, and an approved description column.
  No raw 200-character lines or SINQ_MESSAGE text is ever displayed.
- **Filter form** — filter by sub-agency, company, DOCU_TYPE, source,
  SINQ error code, or whether a SINQ error is present. An active-filter
  banner confirms which filters are on; click **Clear filter** to reset.
- **CSV download bar** — a "Download CSV" button exports the currently
  filtered result set (up to 10,000 rows) as a UTF-8 CSV file. The same
  filters you have active in the browser are applied to the export.
- **Ask box** — type a plain-English question (e.g. "what is the most common
  error?", "how many records have SINQ error 507?") and click **Ask**. The
  answer appears instantly below the box. If watsonx.ai credentials are
  configured in `.env`, the LLM answers; otherwise the built-in local
  fallback handles common question types automatically.

### What a healthy dashboard looks like

When the app loads a real file you should see numbers in every summary card.
Here is a concrete example of what each panel looks like in normal operation:

**Summary cards (top of page)**
```
Total Records   Parse Errors   SINQ Errors   EmpowHR   Emp. Personal Page
    1,432             3            891          1,021          408
```
If "Total Records" is 0, the `DAT_FILE_PATH` in your `.env` is wrong or the
file is empty. If "Parse Errors" is non-zero, those lines were malformed
(not exactly 200 characters) — the app keeps processing and shows the count
as a warning.

**Ask box — example questions and expected answers**

| You type | App responds |
|---|---|
| `how many total records` | `There are 1432 total valid records in the current file.` |
| `how many total sinq errors` | `There are 891 records with SINQ errors in the current file.` |
| `what is the most common error` | `The most common SINQ error is code 008 with 312 record(s) — NATURE OF ACTION CODE IS INVALID FOR THIS TRANSACTION TYPE` |
| `how many 507` | `There are 204 record(s) with SINQ error 507 (POSITION SUPERVISORY CODE MUST BE 2 OR 4).` |
| `show records by docu type` | Lists each DOCU_TYPE code and its record count |
| `list all error codes` | Lists every distinct SINQ error code with counts and descriptions |

If the Ask box returns *"I could not find an answer"*, try rephrasing using
the exact keywords in the table above.

**SINQ error breakdown — example**
```
▸ ERROR 008 ── total 312
    DOCU_TYPE 060 │ 198 records │ NATURE OF ACTION CODE IS INVALID FOR THIS TRANSACTION TYPE
    DOCU_TYPE 032 │  72 records │ NATURE OF ACTION CODE IS INVALID FOR THIS TRANSACTION TYPE
    DOCU_TYPE 100 │  42 records │ No approved reference available

▸ ERROR 507 ── total 204
    DOCU_TYPE 060 │ 204 records │ POSITION SUPERVISORY CODE MUST BE 2 OR 4
```
"No approved reference available" means the (DOCU_TYPE, error code) pair has
no entry in `sinq_error_reference.txt`. That is expected for some combinations.

**Results table — example row**
```
Line │ Sub-Agency │ Company │ DOCU_TYPE │ Source    │ SINQ Error │ Description
   1 │ AG         │  01     │  060      │ EmpowHR   │ 008        │ NATURE OF ACTION...
```
Click any row's line number to open the record detail page, which shows all
six fields plus the full approved description.

**CSV download — what the file looks like**
```
# Personnel Processing Monitor - filtered export
# Filters: gvt_sub_agency=AG, company=, docu_type=, source=, sinq_error=, has_sinq_error=
line_number,gvt_sub_agency,company,docu_type,source,sinq_error,has_sinq_error,approved_description
1,AG,01,060,EmpowHR,008,True,NATURE OF ACTION CODE IS INVALID FOR THIS TRANSACTION TYPE
2,AG,01,060,EmpowHR,507,True,POSITION SUPERVISORY CODE MUST BE 2 OR 4
```
The first two lines (starting with `#`) are human-readable filter notes and
are ignored by Excel and Python's `csv` module. The third line is the header.

---

## 9. Using Filters

### Filter by field values

1. Type a value into any filter box (e.g. sub-agency `AG`, company `01`,
   DOCU_TYPE `060`, or SINQ error `507`).
2. Click **Apply filters**.
3. All sections — the breakdown table, the results table, and the download
   link — update to reflect only the matching records.
4. The active-filter banner lists all active filters and shows the matched
   count.

### Download filtered results as CSV

1. Apply any filters you want.
2. Click **Download CSV** in the download bar.
3. The browser downloads `processing_monitor_export.csv` containing the
   eight standard columns for all matched records (up to 10,000 rows).
4. If results are truncated, a comment row at the top of the file says so.

---

## 10. Stop the Server

Return to the terminal where the server is running and press:

```
Ctrl+C
```

The server shuts down gracefully. No data is written during a normal shutdown.

---

## 11. How to Avoid Using Real or Sensitive Data

This project is **read-only** — it never writes, updates, or resubmits
records. Even so, follow these rules:

- **Never place production `.DAT` files in the repository.** The
  `sample-data/` directory is git-ignored for this reason.
- **Use synthetic data for testing.** All automated tests generate temporary
  fixed-width records in memory or in `tmp_path`. See `tests/` for examples
  of how to construct safe test records.
- **Do not hard-code real employee IDs, agency codes, or any PII** in test
  files, fixtures, or documentation.
- **Do not share your `.env` file or any file that sets `DAT_FILE_PATH`** to
  a production location. Keep those settings local.
- **If you accidentally commit sensitive data**, contact your security team
  immediately — do not just delete the file in a follow-up commit, as the
  data remains in git history.
- The server only reads the file path configured in `settings.dat_file_path`.
  Callers (including the MCP tool) cannot supply an arbitrary path, which
  prevents path-traversal access to files outside the configured location.

---

*Questions? Open an issue in the repository or ask in the team chat.*
