# Quickstart — Personnel Processing Monitor

This guide takes you from a fresh clone to a running dashboard in about
10 minutes. No production data or credentials are required to complete
most steps — a synthetic test run is included.

---

## 1. Prerequisites

| Tool | Minimum version | How to check |
|------|----------------|--------------|
| **Python** | 3.11 | `python3 --version` |
| **uv** | any recent | `uv --version` |
| **Git** | any | `git --version` |

If `uv` is not installed:

```bash
pip install uv          # or: brew install uv  (macOS)
```

---

## 2. Clone and install

```bash
git clone <repository-url>
cd mcp-hackathon-template
uv sync
```

`uv sync` creates a `.venv/` and installs every dependency at the pinned
versions from `uv.lock`. You do not need to activate the virtual environment —
`uv run` handles that automatically.

---

## 3. Configure your environment

```bash
cp .env.example .env
```

Open `.env` and set at least these two variables:

```
DAT_FILE_PATH=sample-data/AI_HACK_TEST_TWO.DAT
REFERENCE_FILE_PATH=reference-data/sinq_error_reference.txt
```

- `DAT_FILE_PATH` — path to your NFC return `.DAT` file. The `sample-data/`
  directory is gitignored — place operator-supplied files there.
- `REFERENCE_FILE_PATH` — the approved SINQ error reference table. The file
  `reference-data/sinq_error_reference.txt` is already in the repository.

> **Never commit a filled-in `.env` to Git.** The `.gitignore` excludes `.env`
> automatically, but double-check before pushing.

Optional — to enable the natural-language Ask box on the dashboard:

```
WATSONX_API_KEY=<your IBM Cloud API key>
WATSONX_PROJECT_ID=<your watsonx.ai project ID>
```

Leave these blank to use the built-in local fallback, which answers common
questions about SINQ error counts, record totals, and DOCU_TYPE breakdowns
without any network call.

---

## 4. Verify — run the tests

All tests use synthetic, in-memory data. No `.DAT` file is required.

```bash
uv run pytest tests/ -v
```

A healthy run ends with:

```
384 passed, 0 failed
```

Run the linter too:

```bash
uv run ruff check .
```

Both must be clean before opening a pull request.

---

## 5. Start the server

```bash
MCP_TRANSPORT=streamable-http uv run example-server
```

The server starts on **port 8000**. Leave this terminal open.

---

## 6. Open the dashboard

```
http://localhost:8000/dashboard
```

On Linux: `xdg-open http://localhost:8000/dashboard`
On macOS: `open http://localhost:8000/dashboard`
On Windows: paste the URL into your browser.

The dashboard shows:

- **Summary cards** — total valid records, parse-error count, total SINQ
  errors, records with SINQ errors, source breakdown.
- **SINQ error breakdown** — hierarchical view: outer group by error code
  (sorted by descending count), inner rows by DOCU_TYPE with the approved
  reference description for each combination.
- **Results table** — paginated list with columns: line number,
  GVT_SUB_AGENCY, COMPANY, DOCU_TYPE, source, SINQ_ERROR, and approved
  description. No raw 200-character lines or SINQ_MESSAGE text is shown.
- **Filter form** — filter by sub-agency, company, DOCU_TYPE, source,
  SINQ error code, or whether a SINQ error is present.
- **CSV download** — click "Download CSV" to export the currently filtered
  results (capped at 10,000 rows).
- **Ask box** — type a natural-language question (e.g. "what is the most
  common SINQ error?") and get an answer from the data.

---

## 7. Use the MCP tool (optional)

The server also exposes a `find_processing_errors` tool over the MCP protocol.
To connect a local MCP client (Claude Desktop or Claude Code), add this to
your client's MCP config — replace the path with the absolute path to this
repository:

```json
{
  "mcpServers": {
    "personnel-monitor": {
      "command": "uv",
      "args": ["run", "example-server"],
      "cwd": "/absolute/path/to/mcp-hackathon-template"
    }
  }
}
```

Then ask your client: *"Use find_processing_errors to summarise the current
processing errors."*

---

## 8. Stop the server

Press `Ctrl+C` in the terminal where the server is running. No data is written
during a normal shutdown.

---

## 9. Data safety rules

- **Never place production `.DAT` files in the repository.** The `sample-data/`
  directory is gitignored. Keep operator-supplied files there or in any path
  outside the repository.
- **Never commit your `.env` file.**
- **All automated tests use synthetic data only.** See any file in `tests/`
  for examples of how to build safe fixed-width test records.
- The dashboard and MCP tool are **read-only** — they never write, update,
  delete, or resubmit records.

---

*For a detailed description of the field layout, source classification rules,
reference-file format, and milestone history, see
[docs/PROJECT_LOG.md](docs/PROJECT_LOG.md).*
