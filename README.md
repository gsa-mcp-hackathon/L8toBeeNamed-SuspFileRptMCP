# USDA NFC Personnel Processing Monitor

A read-only MCP server and web dashboard that parses USDA NFC fixed-width
flat-file personnel processing return records, classifies each record by
source system, surfaces SINQ error codes for analysis, and presents the results
through both an **MCP tool** (for LLM clients) and a **Starlette/Jinja2 HTML
dashboard** (for human reviewers).

Built with [FastMCP](https://github.com/jlowin/fastmcp) and
[uv](https://docs.astral.sh/uv/).

---

## What this project does

The NFC return file contains one fixed-width record (200 characters) per
personnel transaction. Each record may carry a SINQ error code indicating why
the transaction was rejected or held. This tool:

- Parses the fixed-width `.DAT` file without modifying it.
- Classifies each record as **EmpowHR**, **Employee Personal Page**, or
  **Unknown** based on indicator fields.
- Looks up each SINQ error code against an approved reference description table.
- Exposes a read-only MCP tool (`find_processing_errors`) that LLM clients can
  call to get a structured summary.
- Serves a filterable, paginated HTML dashboard at `GET /dashboard` with:
  - Summary cards (total records, SINQ error count, source breakdown).
  - Hierarchical SINQ error breakdown grouped by error code → DOCU_TYPE with
    approved reference descriptions.
  - A results table with an `approved_description` column.
  - CSV download (`GET /dashboard/download`) respecting all active filters.
  - A natural-language Ask box backed by watsonx.ai (with a local fallback for
    common questions when watsonx is not configured).

**This project is strictly read-only.** No write, update, delete, or resubmit
paths exist anywhere in the codebase.

---

## Dashboard preview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  USDA NFC Personnel Processing Monitor                     [Download CSV]   │
├──────────────┬──────────────┬──────────────┬──────────────┬─────────────────┤
│ Total Records│ Parse Errors │  SINQ Errors │  EmpowHR     │ Emp. Personal   │
│    1,432     │      3       │     891      │    1,021     │      408        │
├─────────────────────────────────────────────────────────────────────────────┤
│  Ask a question about the data...                              [Ask]        │
│  > "what is the most common SINQ error?"                                    │
│  ◀ The most common SINQ error is code 008 with 312 record(s) —              │
│    NATURE OF ACTION CODE IS INVALID FOR THIS TRANSACTION TYPE               │
├─────────────────────────────────────────────────────────────────────────────┤
│  SINQ ERROR BREAKDOWN                               [Show all 14 errors ▼] │
│                                                                             │
│  ▸ ERROR 008 ── total 312                                                   │
│      DOCU_TYPE 060 │ 198 records │ NATURE OF ACTION CODE IS INVALID...      │
│      DOCU_TYPE 032 │  72 records │ NATURE OF ACTION CODE IS INVALID...      │
│      DOCU_TYPE 100 │  42 records │ No approved reference available          │
│                                                                             │
│  ▸ ERROR 507 ── total 204                                                   │
│      DOCU_TYPE 060 │ 204 records │ POSITION SUPERVISORY CODE MUST BE 2 OR 4 │
│                                                                             │
│  ▸ ERROR 021 ── total 187                                                   │
│      DOCU_TYPE 060 │ 187 records │ EMPLOYEE NOT IN PAY STATUS               │
│    ·  ·  ·  (10 of 14 shown)                                                │
├─────────────────────────────────────────────────────────────────────────────┤
│  FILTER  Sub-agency [    ] Company [    ] DOCU_TYPE [    ] Source [      ▼] │
│          SINQ error [    ] Has SINQ error [any ▼]        [Apply] [Clear]    │
│  Showing 50 of 891 filtered records                                         │
├──────┬─────────────┬─────────┬──────────┬──────────────────┬───────────────┤
│ Line │ Sub-Agency  │ Company │ DOCU_TYPE│ Source           │ SINQ Error    │
│      │             │         │          │                  │ Description   │
├──────┼─────────────┼─────────┼──────────┼──────────────────┼───────────────┤
│    1 │ AG          │  01     │  060     │ EmpowHR          │ 008           │
│      │             │         │          │                  │ NATURE OF ... │
│    2 │ AG          │  01     │  060     │ EmpowHR          │ 507           │
│      │             │         │          │                  │ POSITION S... │
│    4 │ AG          │  02     │  032     │ Emp. Personal Pg │ 021           │
│      │             │         │          │                  │ EMPLOYEE N... │
│  ... │             │         │          │                  │               │
│      │  [◀ Prev]   │         │          │   Page 1 of 18   │  [Next ▶]    │
└──────┴─────────────┴─────────┴──────────┴──────────────────┴───────────────┘
```

> **Note for contributors:** To add a real screenshot, run the dashboard,
> take a full-page capture (Chrome: F12 → device toolbar → Capture full size
> screenshot), save it as `docs/images/dashboard.png`, and replace this block
> with `![Dashboard screenshot](docs/images/dashboard.png)`.

---

## Repository structure

```
mcp-hackathon-template/
├── README.md                      # This file
├── QUICKSTART.md                  # Setup and first-run guide
├── SECURITY.md                    # Vulnerability disclosure + data-privacy notes
├── main.py                        # Local entry point (uv run python main.py)
├── pyproject.toml                 # Package + dependencies (uv)
├── requirements.txt               # Mirror of runtime deps (for buildpack hosts)
├── .env.example                   # Copy to .env — fill in DAT_FILE_PATH
├── reference-data/
│   └── sinq_error_reference.txt  # 75-char fixed-width approved error descriptions
├── src/
│   └── example_server/
│       ├── app.py                 # FastMCP entry point, picks transport
│       ├── config.py              # Settings from env vars / .env
│       ├── parser.py              # Fixed-width DAT parser → ParsedRecord / ParseError
│       ├── query.py               # RecordFilter, ProcessingMonitor, load_monitor
│       ├── reference.py           # Reference-file parser, ReferenceTable, lookup()
│       ├── dashboard.py           # HTTP routes: /dashboard, /dashboard/download, /ask
│       ├── ask.py                 # build_context(), answer_locally(), ask_watsonx()
│       ├── models.py              # Pydantic models (PaginationParams)
│       ├── utils.py               # paginate() helper
│       ├── routes.py              # /health, /version routes
│       ├── tools/
│       │   ├── __init__.py        # register_tools() aggregator
│       │   └── find_processing_errors.py  # Read-only MCP tool
│       └── templates/
│           ├── dashboard.html     # Main dashboard page
│           └── record_detail.html # Individual record drill-down page
├── tests/                         # 384 tests — all synthetic data, no real DAT files
│   ├── test_parser.py
│   ├── test_query.py
│   ├── test_reference.py
│   ├── test_dashboard.py
│   ├── test_find_processing_errors.py
│   ├── test_ask.py
│   └── test_server.py
└── docs/
    ├── PROJECT_LOG.md             # Detailed milestone-by-milestone implementation log
    ├── TEAM_RUNBOOK.md            # Beginner setup and usage guide
    └── EVALUATION_REPORT.md       # Findings from AI_HACK_TEST_TWO.DAT evaluation
```

---

## Getting started

See **[QUICKSTART.md](QUICKSTART.md)** for the full step-by-step guide. The
short version:

```bash
cp .env.example .env
# Edit .env — set DAT_FILE_PATH to your .DAT file and REFERENCE_FILE_PATH
# to reference-data/sinq_error_reference.txt
uv sync
MCP_TRANSPORT=streamable-http uv run example-server
# Open http://localhost:8000/dashboard
```

---

## Transaction file layout

Each valid record is exactly **200 characters** after stripping line endings.

| Field | 1-based positions | Python slice |
|---|---|---|
| `GVT_SUB_AGENCY` | 10–11 | `line[9:11]` |
| `COMPANY` | 16–17 | `line[15:17]` |
| `DOCU_TYPE` | 18–20 | `line[17:20]` |
| `GWEBESS` | 45–51 | `line[44:51]` |
| `SINQ_ERROR` | 52–54 | `line[51:54]` |
| `SINQ_MESSAGE` | 55–103 | `line[54:103]` — **never exposed** |
| `POWRDOCS` | 186–193 | `line[185:193]` |

Source classification — EmpowHR takes precedence:

| Condition | Source |
|---|---|
| `POWRDOCS == "POWRDOCS"` | `EmpowHR` |
| `GWEBESS == "GWEBESS"` | `Employee Personal Page` |
| Neither | `Unknown` |

---

## Running checks

```bash
uv run ruff check .          # lint — must be clean before any PR
uv run pytest tests/ -v      # 384 tests, all synthetic data
```

---

## Security and data handling

- `.DAT` transaction files are **gitignored** — never commit them.
  Place them in `sample-data/` (also gitignored) or point `DAT_FILE_PATH` at
  any local path outside the repository.
- `SINQ_MESSAGE`, raw 200-character lines, `gwebess_raw`, and `powrdocs_raw`
  are stripped before any template rendering, MCP output, or CSV serialisation.
- The CSV download is capped at 10,000 rows and protected against Excel formula
  injection.
- See [SECURITY.md](SECURITY.md) for the full vulnerability disclosure policy
  and data-handling notes.

---

## Evaluation report

See **[docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md)** for a full
analysis of the test data file: parse quality, source classification findings,
SINQ error breakdown with approved descriptions, reference lookup coverage,
feature validation checklist, test suite summary, and remediation
recommendations.

---

## License

[MIT](LICENSE).
