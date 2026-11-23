# Personnel Processing Monitor — Project Log

> **Classification:** Internal working document.
> Contains no real personnel records, PII, SINQ messages, credentials, or
> sensitive government data.  All sample data referenced here is synthetic.

---

## Project Objective

Build a read-only MCP server and web dashboard that parses USDA NFC
fixed-width flat-file personnel processing return records, classifies each
record by source system, surfaces SINQ error codes for analysis, and
presents the results through both an MCP tool (for LLM clients) and a
Starlette/Jinja2 HTML dashboard (for human reviewers).

The project must:
- Never connect to NFC, the mainframe, EmpowHR, FESI, or any external API.
- Never expose raw fixed-width lines, SINQ messages, or PII to the dashboard
  or MCP tool output.
- Remain entirely read-only — no write, update, delete, or resubmit paths.
- Use a single local flat file as its only data source.

---

## Fixed-Width File Layout

Each valid data record is exactly **200 characters** (after stripping
line-ending characters).  Blank lines are skipped.  Lines that are non-blank
but not exactly 200 characters are recorded as parse errors.

| Field | 1-based positions | Python slice | Notes |
|-------|------------------|--------------|-------|
| `GVT_SUB_AGENCY` | 10–11 | `[9:11]` | Trimmed |
| `COMPANY` | 16–17 | `[15:17]` | Trimmed |
| `DOCU_TYPE` | 18–20 | `[17:20]` | Document type code; string, leading zeroes preserved |
| `GWEBESS` | 45–51 | `[44:51]` | Indicator field; trimmed |
| `SINQ_ERROR` | 52–54 | `[51:54]` | 3-char error code; trimmed |
| `SINQ_MESSAGE` | 55–103 | `[54:103]` | Free-text message; **never exposed** |
| `POWRDOCS` | 186–193 | `[185:193]` | Indicator field; trimmed |

**Source classification** (EmpowHR takes precedence when both indicators fire):

| Condition | Assigned source |
|-----------|----------------|
| `POWRDOCS == "POWRDOCS"` | `"EmpowHR"` |
| `GWEBESS == "GWEBESS"` | `"Employee Personal Page"` |
| Neither | `"Unknown"` |

**Active data file:** `sample-data/AI_HACK_TEST_TWO.DAT`
(gitignored — never committed; operator-configured via `DAT_FILE_PATH` env var)

---

## Completed Milestones

### Milestone 1 — Fixed-width parser (`parser.py`)

- `ParsedRecord` dataclass: seven extracted fields plus `has_sinq_error` flag.
- `ParseError` dataclass: line number and human-readable reason only.
- `parse_line()`: strips line endings, validates length, extracts and trims
  all confirmed fields, classifies source.
- `parse_file()`: iterates a file, skips blank lines, collects results.
- `RECORD_LENGTH = 200` constant.

### Milestone 2 — Query service (`query.py`)

- `RecordFilter` dataclass: five optional filter fields, all `None` by default.
  AND logic, case-insensitive comparisons.
- `QuerySummary` dataclass: total valid, parse error count, by-source mapping,
  SINQ error count, list of `ParseError` objects.
- `ProcessingMonitor`: holds parsed results; exposes `filter_records()` and
  `summarize()`.  `ParseError` records are **never** returned by
  `filter_records()`.
- `load_monitor(path)`: single public entry point.

### Milestone 3 — MCP tool (`tools/find_processing_errors.py`)

- Tool name: `find_processing_errors`
- Registered as read-only via MCP annotations
  (`readOnlyHint=True`, `destructiveHint=False`, `idempotentHint=True`,
  `openWorldHint=False`).
- Accepts five optional filters: `gvt_sub_agency`, `company`, `source`,
  `sinq_error`, `has_sinq_error`.
- Accepts `PaginationParams` (default limit 50, max 200).
- Returns exactly **seven** safe fields per record:
  `line_number`, `gvt_sub_agency`, `company`, `source`,
  `sinq_error`, `sinq_message`, `has_sinq_error`.
  `gwebess_raw`, `powrdocs_raw`, and raw lines are never returned.
- File path comes from `settings.dat_file_path` only; callers cannot supply
  or override it.
- `OSError` on file read returns a sanitised error dict — no path, traceback,
  or exception type in the response.

### Milestone 4 — Read-only web dashboard (`dashboard.py`, `templates/dashboard.html`)

- Route: `GET /dashboard` served by Starlette via `mcp.custom_route()`.
- Same process and port as the MCP endpoint (`/mcp`); no second server.
- **Summary cards** (always full-file): valid records, parse errors,
  SINQ error count, by-source breakdown.
- **Filter form**: GET-based, five fields matching the MCP tool filters.
  Invalid or empty inputs default gracefully; no 400 errors.
- **Results table**: five columns only — `line_number`, `gvt_sub_agency`,
  `company`, `source`, `sinq_error`.  `sinq_message`, `gwebess_raw`,
  `powrdocs_raw`, and raw lines are stripped in Python before the template
  is rendered.
- **Pagination**: `offset`/`limit` query parameters; invalid `offset` clamped
  to 0; `limit` clamped to [1, 200]; default 50 rows per page.
- **Error state**: `OSError` returns HTTP 500 with a user-friendly message;
  no path, traceback, or exception text in the response body.
- Template engine: Jinja2 3.x with `select_autoescape(["html"])`.
- Added `jinja2>=3.1.6` to `pyproject.toml` and `requirements.txt`.

### Milestone 5A — SINQ error breakdown

- New `_group_sinq_errors(records)` helper in `dashboard.py`:
  counts non-blank `sinq_error` values across **all valid records**
  (full-file, not the filtered set); sorts by descending count then ascending
  code; exposes only `{"code": str, "count": int}` to the template.
- Dashboard section between filter form and results table:
  shows distinct code count, total error count, proportional CSS bar,
  percentage, clickable code links.
- Clicking a code applies `sinq_error=<code>` filter; active code highlighted
  in red with a `●` indicator.
- `sinq_message` and all other fields are **never** included in the grouped
  section.

### Milestone 5B — Improved drill-down view

- **Top-10 / Show all**: only the 10 most-frequent codes shown by default.
  A `?Show all N codes?` server-rendered link (no JS) reveals all codes;
  `?Show fewer?` collapses back to 10.  Both links preserve active filters
  and reset `offset` to 0.
- **`#results` fragment**: every error-code link now includes `#results` so
  the browser scrolls to the filtered table without JavaScript.
- **`<section id="results">`**: wraps the results header, table, and
  pagination controls.
- **Active-filter banner**: a blue-tinted `<div class="filter-banner">` appears
  above the results section only when `sinq_error` is set.  Displays the
  selected code, matching record count, and a `✕ Clear filter → /dashboard`
  link.  Clear filter returns to `/dashboard` with **no** query parameters.
- **URL rules**:
  - Error-code links: `/dashboard?sinq_error=<code>#results` — no offset,
    no other filters, `#results` fragment.
  - Show-all link: all active filters preserved, `show_all=1` appended,
    `offset` omitted (resets to 0).
  - Show-fewer link: all active filters preserved, `show_all` omitted,
    `offset` omitted.
  - Clear-filter: `href="/dashboard"` — no query parameters whatsoever.
  - Pagination Prev/Next: all active filters preserved via
    `_build_filter_url()`.
- Compact row layout replaces the previous `<table>`-based breakdown;
  each row is a flex `<div class="bd-row">` with narrower bars and tighter
  padding.

### Milestone 7 — Hierarchical SINQ grouping, Review-column removal, CSV download

**A. Hierarchical SINQ_ERROR / DOCU_TYPE breakdown**

- `_group_sinq_errors()` in `dashboard.py` updated to group by
  `(SINQ_ERROR, DOCU_TYPE)` pairs.  Each outer group (one per `SINQ_ERROR`)
  carries a `total` count and a `groups` list of inner sub-groups.
- Each inner sub-group exposes: `docu_type`, `count`, and `description`
  (approved reference description or the `NO_REFERENCE_AVAILABLE` sentinel).
- Outer groups sorted by descending total, then ascending `SINQ_ERROR` code.
  Inner sub-groups sorted by descending count, then ascending `DOCU_TYPE`.
- Template updated: outer heading shows error code and total; each inner row
  shows `DOCU_TYPE`, count, proportional bar, and truncated description with
  full text in the `title` attribute.
- The existing top-10 / Show-all / Show-fewer toggle is preserved unchanged.
- `SINQ_MESSAGE` and all per-record raw fields remain entirely absent from the
  breakdown section.

**B. Review column removed from the main results table**

- `review_url` key removed from the `rows` dict in `dashboard.py`.
- Review column `<th>` and `<td>` cells removed from `dashboard.html`.
- The direct `GET /dashboard/record/{line_number}` detail route is retained.
- `TestRecordDetail::test_review_link_absent_from_dashboard_table` confirms
  neither the `Review` heading nor any `review-link` CSS class appears in the
  rendered table.

**C. CSV download — `GET /dashboard/download`**

- New read-only route registered in `dashboard.py`.
- Respects all active dashboard filters: `gvt_sub_agency`, `company`,
  `docu_type`, `source`, `sinq_error`, `has_sinq_error`.
- Exactly **eight columns** in order:
  `line_number`, `gvt_sub_agency`, `company`, `docu_type`, `source`,
  `sinq_error`, `has_sinq_error`, `approved_description`.
- Two comment rows precede the CSV header:
  `# Personnel Processing Monitor - filtered export` and
  `# Filters: <active filter values>`.
- If the matched set exceeds 10,000 rows a third comment is added:
  `# WARNING: results truncated at 10000 rows (<n> matched)`.
- Data rows are capped at `CSV_EXPORT_LIMIT = 10_000`.
- String cells beginning with `=`, `+`, `-`, or `@` are prefixed with `'`
  to prevent Excel formula injection.
- `ParseError` records are excluded; HTTP 200 with header-only CSV is returned
  for zero matching records.
- UTF-8 encoding; `Content-Disposition: attachment;
  filename="processing_monitor_export.csv"`.
- No output file written to disk; response streamed from `io.StringIO`.
- Download link on the dashboard HTML preserves all active filters via
  `_build_download_url()`.
- `SINQ_MESSAGE`, `gwebess_raw`, `powrdocs_raw`, and raw 200-character lines
  are never written to the CSV.

**Files changed:** `src/example_server/dashboard.py`,
`src/example_server/templates/dashboard.html`, `tests/test_dashboard.py`.
No parser, query service, reference parser, MCP tool, config, or other files
were modified.

---

### Milestone 11 — Local fallback for Ask box (`answer_locally`)

**Feature:** When watsonx.ai is unconfigured or unreachable, `ask_watsonx()`
now falls back to `answer_locally()` — a pure-Python pattern-matcher that
answers common questions directly from the in-memory context string, with no
network call.

**Motivation:** The project's watsonx.ai Runtime service instance was not
associated with the IBM Cloud account, so the LLM endpoint returned HTTP 403.
Rather than surfacing a configuration error to users, the system now gives
useful answers locally for the most common question types.

**Patterns handled by `answer_locally()`:**

| Question type | Example |
|---|---|
| Total SINQ error count | "how many total sinq errors" |
| Total valid record count | "how many total records" |
| Parse error count | "are there any parse errors?" |
| Most common / top error | "what is the most common error" |
| Specific 3-digit error code | "how many 507 errors", "tell me about error 021" |
| DOCU_TYPE breakdown | "show records by docu type" |
| List all error codes | "list all error codes" |
| Unrecognised question | returns `None` → caller returns `_FALLBACK_UNKNOWN` |

**Fallback strategy in `ask_watsonx()`:**
1. If `WATSONX_API_KEY` and `WATSONX_PROJECT_ID` are set → try LLM.
   On success, return the LLM answer.
2. On LLM failure or when unconfigured → call `answer_locally()`.
   If it returns a string, return that.
3. If neither strategy matches → return `_FALLBACK_UNKNOWN`.

**Security / privacy:**
- `answer_locally()` reads only the aggregate context string — no raw lines,
  no SINQ_MESSAGE, no individual record data.
- `WATSONX_NOT_CONFIGURED` sentinel is retained as an importable constant
  for future use but is no longer the primary return value.

**Files changed:**

| File | Change |
|------|--------|
| `src/example_server/ask.py` | Added `answer_locally()`; `ask_watsonx()` now falls back to it |
| `tests/test_ask.py` | Fixed stale `WATSONX_NOT_CONFIGURED` assertion; added `TestAnswerLocally` (13 tests); added `test_unconfigured_returns_local_or_fallback` |

**Baseline after Milestone 11:** 384 tests passed, 0 failed, Ruff clean.

---

### Milestone 10 — Natural-language Ask box (watsonx.ai)

**Feature:** A plain-text question box on the dashboard — positioned between
the summary cards and the filter form — that sends the user's question to
watsonx.ai and displays the answer on the same page without a reload.

**How it works:**
1. User types a question and clicks **Ask** (or presses Ctrl+Enter).
2. The browser sends `POST /dashboard/ask` with `{"question": "..."}`.
3. The route loads the current data, calls `build_context()` to produce a
   compact aggregate summary (counts only — no raw lines, no SINQ_MESSAGE),
   then calls `ask_watsonx()` which exchanges an IAM token and calls the
   watsonx.ai `/ml/v1/text/generation` endpoint via `httpx`.
4. The plain-text answer is returned as `{"answer": "..."}` and displayed
   in the response area below the box.

**Security / privacy properties:**
- Only aggregate statistics reach the LLM: total records, SINQ error counts
  with approved descriptions, DOCU_TYPE counts, source counts.
- Raw transaction lines, SINQ_MESSAGE, gwebess_raw, and powrdocs_raw are
  never included in the context.
- The API key is read from settings only; it is never logged or returned.
- Network and API errors produce a user-safe message — no traceback exposed.
- When `WATSONX_API_KEY` is unset the route returns a configuration hint.
- The route is read-only (POST body → answer only; no data is modified).

**Configuration (set in `.env` — never committed to Git):**

| Variable | Purpose | Default |
|---|---|---|
| `WATSONX_API_KEY` | IBM Cloud API key | _(required)_ |
| `WATSONX_PROJECT_ID` | watsonx.ai project ID | _(required)_ |
| `WATSONX_URL` | Regional endpoint | `https://us-south.ml.cloud.ibm.com` |
| `WATSONX_MODEL_ID` | Model identifier | `ibm/granite-3-3-8b-instruct` |

**Files changed:**

| File | Change |
|------|--------|
| `src/example_server/ask.py` | **New** — `build_context()`, `ask_watsonx()`, constants |
| `src/example_server/config.py` | 4 new watsonx settings added |
| `src/example_server/dashboard.py` | `POST /dashboard/ask` route + imports |
| `src/example_server/templates/dashboard.html` | Ask box, response area, 25-line fetch script |
| `.env.example` | 4 new variables documented |
| `tests/test_ask.py` | **New** — 9 tests (context builder + route) |
| `docs/PROJECT_LOG.md` | This entry |

**No new runtime packages required** — `httpx` was already a project
dependency and is used directly for the watsonx REST call.

**Post-fix baseline:** 370 tests passed, 0 failed, Ruff clean.

---

### Milestone 9 — DOCU_TYPE 063 → 060 reference fallback

**Root cause:** DOCU_TYPE `063` transaction records carry SINQ_ERROR codes
(`005`–`098`, `507`, `522`, `605`) that exist in the reference file only under
DOCU_TYPE `060`.  The reference file does have 063-specific entries, but only
for the higher-numbered range (`113`–`874`).  The direct lookup
`("063", sinq_error)` therefore returned the sentinel for all low-numbered
codes, even though the correct description was present under `("060", sinq_error)`.

**Fix:** Added `DOCU_TYPE_FALLBACK: dict[str, str] = {"063": "060"}` to
`reference.py`.  `ReferenceTable.lookup()` now retries with the fallback
DOCU_TYPE when the primary lookup misses.  The primary key is always tried
first, so any `063`-specific entries (e.g. `113`–`874`) continue to be
returned without change.

**Files changed:**

| File | Change |
|------|--------|
| `src/example_server/reference.py` | `DOCU_TYPE_FALLBACK` dict added; `lookup()` extended with 4-line fallback retry |
| `tests/test_reference.py` | `TestDocuTypeFallback` class added (3 tests) |
| `docs/PROJECT_LOG.md` | This entry |

**Verification:** All 9 `(063, sinq_error)` pairs in the current transaction
file now resolve to full descriptions via the `060` fallback.  No pair returns
the sentinel.

**Post-fix baseline:** 361 tests passed, 0 failed, Ruff clean.

---

### Milestone 8 — DOCU_TYPE position correction: `[34:37]` → `[17:20]`

**Root cause:** The original transaction-file layout spec stated DOCU_TYPE at
positions 35–37 (`line[34:37]`).  The confirmed correct position is 18–20
(`line[17:20]`).  This was a spec error, not a code error; no implementation
logic was otherwise wrong.

**Changes made:**

| File | Change |
|------|--------|
| `src/example_server/parser.py` | Extraction slice `data[34:37]` → `data[17:20]`; module docstring and `ParsedRecord` field comment updated |
| `tests/test_parser.py` | `_make_record` builder `_place(docu_type, 34, 3)` → `_place(docu_type, 17, 3)`; docstring comment updated; `test_docu_type_reads_from_positions_18_to_20` added |
| `tests/test_query.py` | `_make_record` builder offset and docstring comment updated |
| `tests/test_find_processing_errors.py` | `_make_record` builder offset updated |
| `tests/test_dashboard.py` | `_make_record` builder offset and header comment updated |
| `docs/PROJECT_LOG.md` | Layout table and Milestone 6 Phase 2 narrative corrected; this entry added |

**Files not changed:** `query.py`, `dashboard.py`, `reference.py`, `config.py`,
all templates, MCP tool implementation, `TEAM_RUNBOOK.md`.

**New explicit position test (`test_docu_type_reads_from_positions_18_to_20`):**
Places a three-character marker directly at `buf[17:20]` in a raw 200-character
buffer, leaves `buf[34:37]` (the old wrong position) as spaces, and asserts
`result.docu_type == "XYZ"`.  This test is independent of `_make_record` and
fails immediately if the parser ever reverts to the old slice.

**Post-fix baseline:** 358 tests passed, 0 failed, Ruff clean.

---

### Milestone 6 — Reference file lookup + `DOCU_TYPE` field (Phase 1 & 2)

**Phase 1 — Reference file parser (`reference.py`)**

- `ReferenceRecord` dataclass: `tble_code`, `docu_type`, `err_mess_no`,
  `err_mess_des`, `begin_dt` (raw string), `end_dt` (raw string).
- `ReferenceTable`: dict-backed; lookup key `(docu_type, err_mess_no)`;
  returns `err_mess_des` or the `NO_REFERENCE_AVAILABLE` sentinel.
- `load_reference(path)`: public entry point; validates 75-char fixed width;
  records `ReferenceParseError` for malformed lines and
  `ReferenceValidationError` for duplicate keys (first value kept).
- `NO_REFERENCE_AVAILABLE = "No approved reference available"` — module
  constant; returned instead of raising on a missing lookup key.
- `config.py`: `reference_file_path` setting added
  (default `reference-data/sinq_error_reference.txt`).
- 42 new tests in `tests/test_reference.py`.

**Phase 2 — `DOCU_TYPE` field + 8-field MCP output schema**

- `parser.py`: `docu_type` field added to `ParsedRecord`; extracted at
  `line[17:20]` (positions 18–20); stored as string; leading zeroes preserved.
  *(Slice corrected from the original `[34:37]` in Milestone 8 — see below.)*
- `query.py`: `docu_type: str | None` added to `RecordFilter`; case-insensitive
  match; default `None` matches all records.
- `tools/find_processing_errors.py`: **schema break** — `sinq_message` removed,
  `docu_type` + `ref_description` added; reference file loaded per call;
  `docu_type` filter added; output is now exactly **8 fields**:
  `line_number`, `gvt_sub_agency`, `company`, `docu_type`, `source`,
  `sinq_error`, `ref_description`, `has_sinq_error`.
- `dashboard.py`: reference table loaded per request in both routes;
  `docu_type` + `ref_description` added to table rows and detail dict;
  `docu_type` query param parsed.
- `templates/dashboard.html`: Doc Type column + filter input added;
  `colspan` updated to 7.
- `templates/record_detail.html`: Document Type row + Approved Description row
  added in SINQ section.
- 5 new `TestParseLineDocuType` tests in `test_parser.py`.
  *(A 6th test, `test_docu_type_reads_from_positions_18_to_20`, was added in Milestone 8.)*
- 5 new tests in `test_query.py` (docu_type filter, case-insensitive match).
- 6 new `TestDocuTypeAndReference` tests in `test_find_processing_errors.py`.
- 10 new tests in `test_dashboard.py` (doc-type column, ref description,
  missing reference file).
- `config.py` default updated from `AI_HACK_TEST_ONE.DAT` to
  `AI_HACK_TEST_TWO.DAT`.

### Files Created or Modified (Milestone 7 additions)

| File | Change |
|------|--------|
| `src/example_server/dashboard.py` | `_group_sinq_errors()` updated for `(SINQ_ERROR, DOCU_TYPE)` hierarchy; `review_url` removed; `GET /dashboard/download` route added |
| `src/example_server/templates/dashboard.html` | Outer/inner breakdown markup; Review column removed; download bar added |
| `tests/test_dashboard.py` | 32 new tests: `TestGroupedBreakdown` (6), `TestCsvDownload` (16), `TestCsvFilterPreservation` (4), `TestCsvFormulaInjection` (4), `TestCsvTruncation` (2) |

---

## Files Created or Modified

### Created

| File | Purpose |
|------|---------|
| `src/example_server/parser.py` | Fixed-width record parser |
| `src/example_server/query.py` | Filter/query service on top of parser |
| `src/example_server/tools/find_processing_errors.py` | MCP tool |
| `src/example_server/dashboard.py` | Dashboard HTTP route handler |
| `src/example_server/templates/dashboard.html` | Jinja2 SSR template |
| `src/example_server/reference.py` | Reference file parser + `ReferenceTable` |
| `tests/test_parser.py` | Parser unit tests |
| `tests/test_query.py` | Query service unit tests |
| `tests/test_find_processing_errors.py` | MCP tool integration tests |
| `tests/test_dashboard.py` | Dashboard HTTP tests |
| `tests/test_reference.py` | Reference file unit tests |
| `docs/PROJECT_LOG.md` | This file |

### Modified

| File | Change |
|------|--------|
| `src/example_server/routes.py` | +2 lines: import + `register_dashboard(mcp)` call |
| `src/example_server/tools/__init__.py` | Registered `find_processing_errors` tool |
| `src/example_server/models.py` | Added `PaginationParams` Pydantic model |
| `src/example_server/app.py` | Minor wiring changes for tool registration |
| `src/example_server/config.py` | Added `reference_file_path`; updated `dat_file_path` default |
| `pyproject.toml` | Added `jinja2>=3.1.6` runtime dependency |
| `requirements.txt` | Added `jinja2>=3.0.0` runtime dependency |

### Unchanged (intentionally not modified)

`utils.py`, `__init__.py`, all existing test files outside the ones listed
above, deploy configs, eval scaffolding.

---

## Test Results

### Data-safety distinction

All **automated tests** use **synthetic temporary files only**, created via
pytest's `tmp_path` fixture as in-memory 200-character transaction strings and
75-character reference strings.  No operator-supplied `.DAT` or reference file
is ever opened by the test suite.

The **configured runtime files** are:

- `sample-data/AI_HACK_TEST_TWO.DAT` — operator-supplied, real-format,
  gitignored.  Used only when the server is started manually by an operator.
  Must not be committed, archived, printed, or shared without explicit approval.
- `reference-data/sinq_error_reference.txt` — reference lookup table,
  committed to the repository.

| Test file | Classes | Tests |
|-----------|---------|-------|
| `test_dashboard.py` | 19 | 137 |
| `test_find_processing_errors.py` | 9 | 41 |
| `test_parser.py` | 7 | 43 |
| `test_query.py` | 7 | 68 |
| `test_reference.py` | 7 | 45 |
| `test_server.py` | — | 9 |
| `test_http_security.py` | — | 18 |
| `test_ask.py` | 2 | 9 |
| **Total** | | **370** |

**Latest run:** 370 passed, 0 failed, 0 warnings — `4.93s`

**Dashboard test classes:**

| Class | Tests | Covers |
|-------|-------|--------|
| `TestDashboardLoads` | 3 | HTTP 200, summary labels, filter form |
| `TestSummaryCounts` | 3 | Valid count, parse error count, SINQ count |
| `TestTableColumns` | 4 | Forbidden-field absence, no Review column |
| `TestNoRawLines` | 1 | 200-char raw string never in HTML |
| `TestFiltering` | 4 | SINQ yes/no, no-match, form repopulation |
| `TestPagination` | 4 | First page, offset, invalid offset, negative offset |
| `TestMissingFile` | 4 | HTTP 500, no path, no traceback, friendly message |
| `TestClearFiltersLink` | 1 | `/dashboard` clear link present |
| `TestSinqGroups` | 13 | Sort order, links, active code, forbidden fields |
| `TestDrillDown` | 22 | Banner, anchor, fragment, top-10, show-all, URLs |
| `TestRecordDetail` | 17 | Record detail route, safe fields, Review column absent |
| `TestRecordDetailGrid` | 19 | Grid layout, field rendering, missing-file 500 |
| `TestDocuTypeColumn` | 4 | Doc Type header, value, filter input, narrowing |
| `TestRefDescriptionDashboard` | 6 | Approved description, sentinel, missing ref file |
| `TestGroupedBreakdown` | 6 | Hierarchical SINQ/DOCU_TYPE grouping, descriptions, totals |
| `TestCsvDownload` | 16 | Status, content-type, filename, columns, data, empty, parse-error exclusion, forbidden fields |
| `TestCsvFilterPreservation` | 4 | Filter propagation to download URL and route |
| `TestCsvFormulaInjection` | 4 | `=`, `+`, `-`, `@` prefix protection |
| `TestCsvTruncation` | 2 | 10,000-row cap, truncation warning comment |

**Ruff:** `0 errors` (rules E, F, I; line-length 88; target Python 3.11)

> **Note:** The `test_query.py` count above reflects 68 collected tests;
> the previous log entry of 69 was off by one.  The actual count has been
> confirmed with `--collect-only`.

---

## Current Dashboard Capabilities

Accessible at `GET /dashboard` when the server runs in HTTP mode.

| Feature | Status |
|---------|--------|
| Summary cards (full-file) | ✅ |
| Filter form — GVT Sub-Agency | ✅ |
| Filter form — Company | ✅ |
| Filter form — Source (dropdown) | ✅ |
| Filter form — SINQ Error Code | ✅ |
| Filter form — Has SINQ Error (yes/no/any) | ✅ |
| Filter form — Doc Type | ✅ |
| Results table (7 safe columns: Line, GVT Sub-Agency, Company, Doc Type, Source, SINQ Error, Approved Description) | ✅ |
| Review column removed from results table | ✅ |
| Approved Description column in results table | ✅ |
| Record detail — Document Type field | ✅ |
| Record detail — Approved Description (ref lookup) | ✅ |
| Pagination (50/page, max 200) | ✅ |
| Hierarchical SINQ breakdown: outer by SINQ_ERROR, inner by DOCU_TYPE | ✅ |
| Approved description per DOCU_TYPE sub-row in breakdown | ✅ |
| Missing-reference sentinel in breakdown | ✅ |
| Top-10 default / Show all toggle | ✅ |
| Active-filter banner with matched count | ✅ |
| `#results` scroll fragment on code links | ✅ |
| `id="results"` anchor | ✅ |
| CSV download — `GET /dashboard/download` | ✅ |
| CSV download preserves all active filters | ✅ |
| CSV export limit 10,000 rows with truncation warning | ✅ |
| CSV formula-injection protection | ✅ |
| HTTP 500 safe error page | ✅ |
| Read-only (no write/delete paths) | ✅ |
| No JavaScript | ✅ |
| No raw lines or SINQ messages exposed | ✅ |

---

## Security and Scope Decisions

| Decision | Rationale |
|----------|-----------|
| File path from `settings.dat_file_path` only | Callers (MCP or HTTP) cannot supply or change the path |
| `sinq_message` never returned by tool or dashboard | Free-text field may contain PII or sensitive data |
| `gwebess_raw`, `powrdocs_raw` never returned | Internal indicator fields; not useful to callers |
| Raw 200-char lines never exposed | Prevent inadvertent data leakage in structured output |
| `OSError` caught and sanitised | Prevent path disclosure in error responses |
| Jinja2 autoescaping enabled | Prevent XSS from any user-controlled values rendered in HTML |
| `urlencode` on all query-param values | Prevent URL injection in generated links |
| No authentication added | Explicitly deferred; dashboard is on internal network only |
| Dashboard is GET-only, no forms POST | Enforces read-only constraint at HTTP verb level |
| SINQ breakdown shows codes and counts only | Aggregate statistics — no per-record data |
| Tests use synthetic `tmp_path` files only | No production or sensitive data in test suite |
| `ParseError` records excluded from tool results | Malformed lines are counted but never serialised to callers |

---

## Open Questions

1. **Field layout confirmation** — The field positions in `parser.py` were
   derived from sample file analysis.  The full NFC layout spec should be
   confirmed against official documentation before production use.

2. **SINQ_MESSAGE display policy** — The 49-character free-text SINQ message
   is parsed but intentionally never displayed.  A decision is needed on
   whether it may be shown under any circumstances, and if so, with what
   redaction or access controls.

3. **Additional extracted fields** — Only six fields are currently extracted
   from the 200-character record.  The remaining positions are unexplored.
   A layout walk-through with a subject-matter expert would identify other
   useful fields (pay plan, master record number, submitting office number,
   department code, agency code).

4. **Multi-file support** — The current design reads one configured flat file.
   If multiple agency files need to be monitored simultaneously, the
   `ProcessingMonitor` / `load_monitor` pattern would need to be extended.

5. **File freshness** — The file is re-read on every HTTP request and every
   tool call.  For large files or high-traffic use, a cache with a TTL or
   inotify-based invalidation should be considered.

6. **Authentication** — Explicitly deferred.  Before any deployment beyond a
   local workstation, an auth layer should be added.

7. **`sinq_error` case sensitivity** — The `sinq_error` filter is
   case-insensitive in `query.py`, but error codes in the file are uppercase.
   Confirm with NFC whether mixed-case codes can appear.

---

## How to Run the Dashboard Locally

```bash
# 1. Install dependencies (first time only)
uv sync --group dev

# 2. Start the server in HTTP mode
MCP_TRANSPORT=streamable-http uv run example-server

# 3. Open the dashboard in a browser (Linux)
xdg-open http://localhost:8000/dashboard

# 4. MCP endpoint remains available at the same address
#    http://localhost:8000/mcp
```

---

## Presentation / Demo Steps

1. **Start server** — `MCP_TRANSPORT=streamable-http uv run example-server`
2. **Open dashboard** — `xdg-open http://localhost:8000/dashboard`
3. **Show summary cards** — point out that all four cards reflect the full
   1,288-record file regardless of any filters applied below.
4. **Show SINQ error breakdown** — scroll to the breakdown; explain top-10
   default and "Show all" toggle; note no messages or raw lines are shown.
5. **Click a SINQ error code** — browser scrolls to the active-filter banner
   and filtered results table; point out the banner showing the selected code
   and matched-record count.
6. **Click ✕ Clear filter** — returns to unfiltered `/dashboard`.
7. **Use the filter form** — demonstrate `has_sinq_error = Yes` and `Source`
   dropdown; show pagination on a large filtered set.
8. **Show MCP tool** — in Claude or another MCP client, call
   `find_processing_errors` with and without filters to show the same
   underlying data in a structured JSON response.
9. **Show test suite** — `uv run pytest tests/ -v` — 325 tests, 0 failures.
10. **Show Ruff** — `uv run ruff check .` — 0 errors.

---

## Deferred Enhancements

| Feature | Reason for deferral |
|---------|---------------------|
| Authentication / login | Not needed for local demo; required before any production deployment |
| AI-generated SINQ message explanations | Planned for a future milestone (Milestone 6) |
| `sinq_message` display in table | Pending display-policy decision |
| Additional extracted fields (pay plan, MRN, etc.) | Requires field-layout confirmation |
| JSON export | Not requested; CSV is implemented |
| Column sorting in results table | Requires JS or extra server round-trips |
| Distinct-value dropdowns for filters | Extra query pass per field; text inputs are simpler |
| File cache / TTL | Not needed for 1,288-record file; required at scale |
| Multi-file / multi-agency support | Architecture change; deferred |
| Write / resubmit / delete actions | Explicitly out of scope for this project |
| Auto-refresh / polling | Static local file; not needed |
| AI chat interface in dashboard | Explicitly deferred |
| Evaluation harness (Phoenix / eval/) | Scaffolding exists; not built for this milestone |

---

## Runtime Dependencies

| Package | Version constraint | Added by |
|---------|--------------------|----------|
| `fastmcp` | `>=2.0.0` | Template |
| `httpx` | `>=0.27.0` | Template |
| `jinja2` | `>=3.1.6` | Milestone 4 |
| `pydantic` | `>=2.0.0` | Template |
| `pydantic-settings` | `>=2.0.0` | Template |

Dev-only (not installed in production): `pytest`, `pytest-asyncio`, `ruff`.

---

*Last updated: Milestone 10 complete — 370 tests passed, 0 warnings, Ruff clean; natural-language Ask box added (watsonx.ai via httpx); POST /dashboard/ask route live; no new runtime packages.*
