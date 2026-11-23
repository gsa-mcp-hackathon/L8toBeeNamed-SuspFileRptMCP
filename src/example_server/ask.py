"""Natural-language question answering over the Personnel Processing Monitor data.

Provides three public functions:

  build_context(monitor, ref_table) -> str
      Produces a compact plain-text summary of the loaded data suitable for
      inclusion in an LLM prompt.  Never includes raw transaction lines,
      individual record data, or SINQ_MESSAGE text.

  answer_locally(question, context) -> str | None
      Pattern-matches common questions against the context string and returns
      a plain-text answer without any network call.  Returns None when the
      question does not match any known pattern so the caller can try another
      strategy.

  ask_watsonx(question, context, settings) -> str
      Tries the watsonx.ai text-generation REST endpoint first.  Falls back to
      answer_locally() when the LLM is unconfigured or the API call fails.
      Returns a safe error string only when both strategies fail.
      No traceback, no API key value, no raw HTTP response body is ever exposed.

Security properties:
  - Only aggregate statistics (counts, codes, descriptions) reach the LLM.
  - Raw transaction lines, SINQ_MESSAGE, gwebess_raw, powrdocs_raw are never
    included in the context or the local answers.
  - The API key is read from settings only; it is never logged or returned.
  - Network errors and API errors fall back to local answering silently.
  - The route that calls this module is read-only (POST body → answer only).
"""

from __future__ import annotations

import re
from collections import Counter

import httpx

from example_server.query import ProcessingMonitor
from example_server.reference import ReferenceTable

# Returned when the watsonx API key is not configured.
WATSONX_NOT_CONFIGURED = (
    "The Ask feature is not configured. "
    "Set WATSONX_API_KEY and WATSONX_PROJECT_ID in your .env file."
)

# Returned when the watsonx call fails for any reason.
_WATSONX_ERROR = (
    "Could not get an answer from watsonx.ai. "
    "Check that your API key and project ID are correct, "
    "and that the server can reach the watsonx endpoint."
)

# Returned when neither the LLM nor the local matcher can answer.
_FALLBACK_UNKNOWN = (
    "I could not find an answer to that question in the current data. "
    "Try asking about total SINQ errors, a specific error code count, "
    "the most common error, or records by DOCU_TYPE."
)

# Hard limit: never send more than this many characters of context to the LLM.
_MAX_CONTEXT_CHARS = 3_000

# Timeout for the watsonx HTTP call (seconds).
_TIMEOUT = 30.0


def build_context(monitor: ProcessingMonitor, ref_table: ReferenceTable) -> str:
    """Build a compact plain-text data summary for use as LLM context.

    The summary contains only aggregate statistics:
      - Total valid records and parse-error count
      - Count of records with SINQ errors
      - Per-source record counts
      - Per-SINQ_ERROR counts with approved descriptions
      - Per-DOCU_TYPE counts

    Nothing in this output includes raw transaction lines, SINQ_MESSAGE text,
    gwebess_raw, powrdocs_raw, or any individual record identifiers.

    Args:
        monitor:   A loaded ProcessingMonitor instance.
        ref_table: A loaded ReferenceTable instance.

    Returns:
        A plain-text string suitable for inclusion in an LLM system prompt.
    """
    summary = monitor.summarize()
    all_records = monitor.filter_records()

    lines: list[str] = [
        "=== Personnel Processing Monitor — Data Summary ===",
        f"Total valid records : {summary.total_valid}",
        f"Parse errors        : {summary.parse_error_count}",
        f"Records with SINQ errors: {summary.sinq_error_count}",
        "",
        "Records by source:",
    ]
    for src, cnt in sorted(summary.by_source.items()):
        lines.append(f"  {src}: {cnt}")

    # SINQ_ERROR counts with approved descriptions (never sinq_message).
    sinq_counts: Counter[str] = Counter(
        r.sinq_error for r in all_records if r.sinq_error
    )
    lines.append("")
    lines.append("SINQ error counts (code: count — approved description):")
    for code, cnt in sinq_counts.most_common():
        # ref_table.lookup uses the DOCU_TYPE from the record; since all
        # records in the current file are one DOCU_TYPE we look up using the
        # first record that carries this code to get the right description.
        docu_type = next(
            (r.docu_type for r in all_records if r.sinq_error == code), ""
        )
        desc = ref_table.lookup(docu_type, code)
        lines.append(f"  {code}: {cnt} — {desc}")

    # DOCU_TYPE counts.
    docu_counts: Counter[str] = Counter(r.docu_type for r in all_records)
    lines.append("")
    lines.append("Records by DOCU_TYPE:")
    for dt, cnt in sorted(docu_counts.items()):
        lines.append(f"  {dt}: {cnt}")

    context = "\n".join(lines)
    # Safety cap — never send more than _MAX_CONTEXT_CHARS characters.
    return context[:_MAX_CONTEXT_CHARS]


def answer_locally(question: str, context: str) -> str | None:
    """Answer common questions by pattern-matching against the context string.

    Handles these question families without any network call:
      - Total SINQ error count
      - Total valid record count
      - Parse error count
      - Most common / top error code
      - Count for a specific SINQ error code  (e.g. "how many 507")
      - Description for a specific SINQ error code
      - Count for a specific DOCU_TYPE
      - List / summary of all error codes

    Args:
        question: The user's question, already stripped.
        context:  The plain-text summary produced by build_context().

    Returns:
        A plain-text answer string, or None if no pattern matched.
    """
    q = question.lower()

    # ── helpers: parse context into structured dicts ────────────────────────

    def _sinq_counts() -> dict[str, int]:
        """Return {code: count} from the context SINQ block."""
        counts: dict[str, int] = {}
        in_block = False
        for line in context.splitlines():
            if "sinq error counts" in line.lower():
                in_block = True
                continue
            if in_block:
                # Lines look like:  "  507: 8 — POSITION SUPERVISORY..."
                m = re.match(r"\s+(\w+):\s+(\d+)", line)
                if m:
                    counts[m.group(1)] = int(m.group(2))
                elif line.strip() == "":
                    break
        return counts

    def _sinq_descriptions() -> dict[str, str]:
        """Return {code: description} from the context SINQ block."""
        descs: dict[str, str] = {}
        in_block = False
        for line in context.splitlines():
            if "sinq error counts" in line.lower():
                in_block = True
                continue
            if in_block:
                # Lines look like:  "  507: 8 — POSITION SUPERVISORY..."
                m = re.match(r"\s+(\w+):\s+\d+\s+—\s+(.+)", line)
                if m:
                    descs[m.group(1)] = m.group(2).strip()
                elif line.strip() == "":
                    break
        return descs

    def _docu_counts() -> dict[str, int]:
        """Return {docu_type: count} from the context DOCU_TYPE block."""
        counts: dict[str, int] = {}
        in_block = False
        for line in context.splitlines():
            if "records by docu_type" in line.lower():
                in_block = True
                continue
            if in_block:
                m = re.match(r"\s+(\w+):\s+(\d+)", line)
                if m:
                    counts[m.group(1)] = int(m.group(2))
                elif line.strip() == "":
                    break
        return counts

    def _scalar(pattern: str) -> int | None:
        """Extract a number from a context line matching pattern."""
        for line in context.splitlines():
            if pattern.lower() in line.lower():
                m = re.search(r":\s*(\d+)", line)
                if m:
                    return int(m.group(1))
        return None

    # ── pattern matching ────────────────────────────────────────────────────

    # Total SINQ errors
    if re.search(r"(how many|total|count).*(sinq|error)", q):
        # Check if asking about a specific code first (handled below)
        code_m = re.search(r"\b(\d{3})\b", q)
        if not code_m:
            total = _scalar("Records with SINQ errors")
            if total is not None:
                return (
                    f"There are {total} records with SINQ errors in the current file."
                )

    # Total valid records
    if re.search(r"(how many|total).*(record|valid)", q):
        total = _scalar("Total valid records")
        if total is not None:
            return f"There are {total} total valid records in the current file."

    # Parse errors
    if re.search(r"parse.?error|malformed|bad.?line", q):
        count = _scalar("Parse errors")
        if count is not None:
            if count == 0:
                return "There are no parse errors — all lines in the file are valid."
            return f"There are {count} parse error(s) in the current file."

    # Most common / top / worst / highest error code
    if re.search(r"(most.?common|top|highest|most.?frequent|worst)", q):
        counts = _sinq_counts()
        if counts:
            descs = _sinq_descriptions()
            top_code = max(counts, key=lambda c: counts[c])
            top_count = counts[top_code]
            desc = descs.get(top_code, "")
            desc_part = f" — {desc}" if desc else ""
            return (
                f"The most common SINQ error is code {top_code} "
                f"with {top_count} record(s){desc_part}."
            )

    # Specific error code — count or description
    code_m = re.search(r"\b(\d{3})\b", q)
    if code_m:
        code = code_m.group(1)
        counts = _sinq_counts()
        descs = _sinq_descriptions()
        if code in counts:
            count = counts[code]
            desc = descs.get(code, "")
            desc_part = f" ({desc})" if desc else ""
            return (
                f"There are {count} record(s) with SINQ error {code}{desc_part}."
            )
        # Code not in SINQ counts — check if it is a DOCU_TYPE
        docu = _docu_counts()
        if code in docu:
            return (
                f"There are {docu[code]} record(s) with DOCU_TYPE {code}."
            )
        return (
            f"SINQ error code {code} does not appear in the current file."
        )

    # DOCU_TYPE questions
    if re.search(r"docu.?type|document.?type", q):
        docu = _docu_counts()
        if docu:
            lines = ["Records by DOCU_TYPE:"]
            for dt, cnt in sorted(docu.items()):
                lines.append(f"  {dt}: {cnt} record(s)")
            return "\n".join(lines)

    # List all error codes / summary
    if re.search(r"(list|show|all|summary).*(error|sinq|code)", q):
        counts = _sinq_counts()
        descs = _sinq_descriptions()
        if counts:
            lines = [f"{len(counts)} distinct SINQ error code(s):"]
            for code, cnt in sorted(counts.items(), key=lambda x: -x[1]):
                desc = descs.get(code, "")
                lines.append(f"  {code}: {cnt} record(s) — {desc}")
            return "\n".join(lines)

    # No pattern matched
    return None


def ask_watsonx(question: str, context: str, settings) -> str:  # type: ignore[type-arg]
    """Answer a question, trying watsonx.ai first and falling back locally.

    Strategy:
      1. If configured, call watsonx.ai.  On success, return the answer.
      2. If the LLM is unconfigured or the API call fails, call answer_locally().
      3. If answer_locally() also returns None, return _FALLBACK_UNKNOWN.

    Args:
        question: The user's plain-text question (already validated/trimmed).
        context:  The data summary produced by build_context().
        settings: The application Settings instance (provides API key, URL, etc.)

    Returns:
        A plain-text answer string.  The API key is never included in any
        return value.  No traceback is ever exposed.
    """
    llm_answer: str | None = None

    if settings.watsonx_api_key and settings.watsonx_project_id:
        system_prompt = (
            "You are a read-only analyst assistant for a USDA NFC Personnel "
            "Processing Monitor. Answer questions using only the data summary "
            "provided. Be concise and specific. Use exact numbers from the data. "
            "Do not invent data, do not reference fields not shown in the summary, "
            "and do not suggest actions that modify records."
        )
        url = (
            f"{settings.watsonx_url.rstrip('/')}"
            "/ml/v1/text/generation?version=2023-05-29"
        )
        payload = {
            "model_id": settings.watsonx_model_id,
            "project_id": settings.watsonx_project_id,
            "input": (
                f"{system_prompt}\n\n"
                f"{context}\n\n"
                f"Question: {question}\n\n"
                "Answer:"
            ),
            "parameters": {
                "decoding_method": "greedy",
                "max_new_tokens": 300,
                "stop_sequences": ["\n\n"],
            },
        }
        try:
            token_resp = httpx.post(
                "https://iam.cloud.ibm.com/identity/token",
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": settings.watsonx_api_key,
                },
                timeout=_TIMEOUT,
            )
            token_resp.raise_for_status()
            iam_token = token_resp.json()["access_token"]
            resp = httpx.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {iam_token}",
                    "Content-Type": "application/json",
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            llm_answer = resp.json()["results"][0]["generated_text"].strip()
        except Exception:  # noqa: BLE001
            llm_answer = None   # fall through to local answering

    if llm_answer:
        return llm_answer

    local = answer_locally(question, context)
    if local is not None:
        return local

    return _FALLBACK_UNKNOWN
