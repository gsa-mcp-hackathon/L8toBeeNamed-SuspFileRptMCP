"""Dashboard HTTP routes for the Personnel Processing Monitor.

Serves a read-only HTML dashboard at GET /dashboard, a record detail page at
GET /dashboard/record/{line_number}, and a CSV download at
GET /dashboard/download.  Reads the configured flat file via the existing
query service.  Supports optional filtering and cursor-based pagination
through GET query parameters.

Security properties:
  - The data file path and reference file path come from settings only.
  - OSError on either file read returns a safe HTTP 500; no path or traceback
    exposed.
  - Six safe structured fields reach the dashboard table template:
    line_number, gvt_sub_agency, company, docu_type, source, sinq_error.
  - The detail template receives eight fields: the six above plus
    has_sinq_error and ref_description.  sinq_message is never included.
  - ref_description comes from the reference file only; it is never derived
    from sinq_message.
  - sinq_message, gwebess_raw, powrdocs_raw, and raw lines are stripped
    before any template rendering or CSV serialisation.
  - The SINQ error breakdown exposes only error codes, doc types, counts, and
    approved reference descriptions — no sinq_message, no per-record data.
  - The ?back= parameter on the detail page is validated to be a relative
    /dashboard path; external or invalid values fall back to /dashboard.
  - CSV output is protected against formula injection: cell values beginning
    with =, +, -, or @ are prefixed with a single-quote so Excel treats them
    as plain text.
  - CSV export is capped at CSV_EXPORT_LIMIT rows.
  - No write, update, or delete operations exist.
"""

from __future__ import annotations

import csv
import io
import math
from pathlib import Path
from urllib.parse import urlencode

from fastmcp import FastMCP
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

from example_server.ask import ask_watsonx, build_context
from example_server.config import settings
from example_server.parser import ParsedRecord
from example_server.query import RecordFilter, load_monitor
from example_server.reference import load_reference
from example_server.utils import paginate

# Absolute path to the templates directory so it works regardless of cwd.
_TEMPLATES_DIR = Path(__file__).parent / "templates"

_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)
_JINJA_ENV.filters["format_int"] = lambda v: f"{v:,}"

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200
_BREAKDOWN_LIMIT = 10

# Maximum rows written to a CSV export (excludes comment and header rows).
CSV_EXPORT_LIMIT = 10_000

# Characters that trigger Excel formula injection if they appear at the start
# of a cell value.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_int(value: str | None, default: int, minimum: int = 0) -> int:
    """Parse a query-string integer, clamping to [minimum, ∞) on bad input."""
    if value is None:
        return default
    try:
        return max(minimum, int(value))
    except (ValueError, TypeError):
        return default


def _parse_has_sinq(value: str | None) -> bool | None:
    """Parse the has_sinq_error query parameter.

    Returns True for 'true', False for 'false', None for anything else.
    """
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _sanitise_csv_cell(value: str) -> str:
    """Prefix formula-injection characters so Excel treats the cell as text."""
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _group_sinq_errors(
    records: list[ParsedRecord],
    ref_table,
) -> list[dict]:
    """Group SINQ errors by (SINQ_ERROR, DOCU_TYPE) with reference descriptions.

    Returns a list of outer-group dicts sorted by descending total count, then
    ascending SINQ_ERROR code.  Each outer group contains a sorted list of
    inner sub-group dicts.

    Outer group schema:
        {
          "code":   str,    # sinq_error value
          "total":  int,    # sum of counts across all docu_type sub-groups
          "groups": [       # sorted by descending count, then ascending docu_type
            {
              "docu_type":   str,
              "count":       int,
              "description": str,  # exact ref lookup result or sentinel
            },
            ...
          ]
        }

    Only records with a non-blank sinq_error are included.
    sinq_message and all other fields are ignored.
    """
    # Count (sinq_error, docu_type) pairs.
    pair_counts: dict[tuple[str, str], int] = {}
    for r in records:
        if r.sinq_error:
            key = (r.sinq_error, r.docu_type)
            pair_counts[key] = pair_counts.get(key, 0) + 1

    # Aggregate into per-sinq_error outer groups.
    outer: dict[str, dict] = {}
    for (sinq_error, docu_type), count in pair_counts.items():
        if sinq_error not in outer:
            outer[sinq_error] = {"code": sinq_error, "total": 0, "groups": []}
        outer[sinq_error]["total"] += count
        outer[sinq_error]["groups"].append(
            {
                "docu_type":   docu_type,
                "count":       count,
                "description": ref_table.lookup(docu_type, sinq_error),
            }
        )

    # Sort inner sub-groups: descending count, then ascending docu_type.
    for grp in outer.values():
        grp["groups"].sort(key=lambda g: (-g["count"], g["docu_type"]))

    # Sort outer groups: descending total, then ascending code.
    return sorted(outer.values(), key=lambda g: (-g["total"], g["code"]))


def _build_filter_url(base_params: dict, offset: int) -> str:
    """Build a /dashboard URL preserving active filters but replacing offset."""
    params = {k: v for k, v in base_params.items() if v}
    params["offset"] = str(offset)
    return "/dashboard?" + urlencode(params)


def _build_breakdown_url(filter_params: dict, show_all: bool) -> str:
    """Build a /dashboard URL preserving active filters with show_all toggled.

    Offset is intentionally reset to 0 (omitted) so pagination starts fresh
    when the user expands or collapses the breakdown list.
    """
    params = {k: v for k, v in filter_params.items() if v}
    if show_all:
        params["show_all"] = "1"
    return "/dashboard?" + urlencode(params) if params else "/dashboard"


def _safe_back_url(raw: str | None) -> str:
    """Validate and return a safe back-navigation URL.

    Accepts only relative paths that start with /dashboard (no scheme, no
    host, no path-traversal).  Any other value falls back to /dashboard.
    """
    if raw and raw.startswith("/dashboard") and not raw.startswith("//"):
        return raw
    return "/dashboard"


def _build_download_url(filter_params: dict) -> str:
    """Build the /dashboard/download URL preserving all active filter params."""
    params = {k: v for k, v in filter_params.items() if v}
    if params:
        return "/dashboard/download?" + urlencode(params)
    return "/dashboard/download"


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def register_dashboard(mcp: FastMCP) -> None:
    """Register the dashboard, detail, and download routes with the MCP server."""

    @mcp.custom_route("/dashboard/ask", methods=["POST"])
    async def dashboard_ask(request: Request) -> JSONResponse:
        """Answer a natural-language question about the current data.

        Accepts: JSON body {"question": "<text>"}
        Returns: JSON body {"answer": "<text>"}

        Only aggregate statistics are sent to the LLM — no raw lines,
        no SINQ_MESSAGE, no individual record data.
        """
        # ── Parse request body ──────────────────────────────────────────────
        try:
            body = await request.json()
            question = str(body.get("question", "")).strip()
        except Exception:  # noqa: BLE001
            return JSONResponse({"error": "Invalid request body."}, status_code=400)

        if not question:
            return JSONResponse(
                {"error": "Question must not be empty."}, status_code=400
            )

        # Truncate to prevent excessively long inputs.
        question = question[:500]

        # ── Load data ───────────────────────────────────────────────────────
        try:
            monitor = load_monitor(settings.dat_file_path)
        except OSError:
            return JSONResponse(
                {"answer": "Data file is currently unavailable."},
                status_code=200,
            )

        try:
            ref_table = load_reference(settings.reference_file_path)
        except OSError:
            return JSONResponse(
                {"answer": "Reference file is currently unavailable."},
                status_code=200,
            )

        # ── Build context and call watsonx.ai ───────────────────────────────
        context = build_context(monitor, ref_table)
        answer = ask_watsonx(question, context, settings)

        return JSONResponse({"answer": answer}, status_code=200)

    @mcp.custom_route("/dashboard/record/{line_number}", methods=["GET"])
    async def record_detail(request: Request) -> HTMLResponse:
        tmpl = _JINJA_ENV.get_template("record_detail.html")

        # ── Validate path parameter ─────────────────────────────────────────
        raw_ln = request.path_params.get("line_number", "")
        try:
            line_number = int(raw_ln)
            if line_number < 1:
                raise ValueError("line_number must be >= 1")
        except (ValueError, TypeError):
            html = tmpl.render(error="bad_request")
            return HTMLResponse(html, status_code=400)

        # ── Validate back URL ───────────────────────────────────────────────
        back_url = _safe_back_url(request.query_params.get("back"))

        # ── Load transaction file ───────────────────────────────────────────
        try:
            monitor = load_monitor(settings.dat_file_path)
        except OSError:
            html = tmpl.render(error="unavailable", back_url=back_url)
            return HTMLResponse(html, status_code=500)

        # ── Load reference file ─────────────────────────────────────────────
        try:
            ref_table = load_reference(settings.reference_file_path)
        except OSError:
            html = tmpl.render(error="unavailable", back_url=back_url)
            return HTMLResponse(html, status_code=500)

        # ── Locate the record by line number ────────────────────────────────
        record = next(
            (r for r in monitor.filter_records() if r.line_number == line_number),
            None,
        )
        if record is None:
            html = tmpl.render(
                error="not_found", line_number=line_number, back_url=back_url
            )
            return HTMLResponse(html, status_code=404)

        # ── Pass only eight approved fields — never the full object ─────────
        # sinq_message is intentionally excluded; ref_description comes from
        # the reference file, not from sinq_message.
        detail = {
            "line_number":     record.line_number,
            "gvt_sub_agency":  record.gvt_sub_agency,
            "company":         record.company,
            "docu_type":       record.docu_type,
            "source":          record.source,
            "sinq_error":      record.sinq_error,
            "ref_description": ref_table.lookup(record.docu_type, record.sinq_error),
            "has_sinq_error":  record.has_sinq_error,
        }

        html = tmpl.render(error=None, record=detail, back_url=back_url)
        return HTMLResponse(html, status_code=200)

    @mcp.custom_route("/dashboard/download", methods=["GET"])
    async def dashboard_download(request: Request) -> StreamingResponse | HTMLResponse:
        """Return a CSV of the currently filtered records.

        Columns (in order): line_number, gvt_sub_agency, company, docu_type,
        source, sinq_error, has_sinq_error, approved_description.

        sinq_message, gwebess_raw, powrdocs_raw, and raw lines are excluded.
        Parse-error records are never included.
        Export is capped at CSV_EXPORT_LIMIT rows.
        String cells are protected against Excel formula injection.
        """
        q = request.query_params

        gvt_sub_agency  = q.get("gvt_sub_agency", "").strip() or None
        company         = q.get("company", "").strip() or None
        source          = q.get("source", "").strip() or None
        sinq_error      = q.get("sinq_error", "").strip() or None
        has_sinq_error  = _parse_has_sinq(q.get("has_sinq_error"))
        has_sinq_raw    = q.get("has_sinq_error", "")
        if has_sinq_raw not in ("true", "false"):
            has_sinq_raw = ""
        docu_type_filter = q.get("docu_type", "").strip() or None

        # ── Load transaction file ───────────────────────────────────────────
        try:
            monitor = load_monitor(settings.dat_file_path)
        except OSError:
            return HTMLResponse(
                "<h1>Data file unavailable</h1>"
                "<p>The data file could not be read. "
                "Please contact your system administrator.</p>",
                status_code=500,
            )

        # ── Load reference file ─────────────────────────────────────────────
        try:
            ref_table = load_reference(settings.reference_file_path)
        except OSError:
            return HTMLResponse(
                "<h1>Reference file unavailable</h1>"
                "<p>The reference file could not be read. "
                "Please contact your system administrator.</p>",
                status_code=500,
            )

        record_filter = RecordFilter(
            gvt_sub_agency=gvt_sub_agency,
            company=company,
            docu_type=docu_type_filter,
            source=source,
            sinq_error=sinq_error,
            has_sinq_error=has_sinq_error,
        )
        matched = monitor.filter_records(record_filter)

        # ── Build CSV in memory ─────────────────────────────────────────────
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\r\n")

        # Comment rows: filter metadata (placed before the CSV header row).
        # These lines begin with # and are ignored by csv.reader but are
        # human-readable in any text editor.
        filter_parts = []
        for label, val in [
            ("gvt_sub_agency",  gvt_sub_agency  or ""),
            ("company",         company         or ""),
            ("docu_type",       docu_type_filter or ""),
            ("source",          source          or ""),
            ("sinq_error",      sinq_error      or ""),
            ("has_sinq_error",  has_sinq_raw),
        ]:
            filter_parts.append(f"{label}={val}")
        filters_str = ", ".join(filter_parts)

        output.write("# Personnel Processing Monitor - filtered export\r\n")
        output.write(f"# Filters: {filters_str}\r\n")

        truncated = len(matched) > CSV_EXPORT_LIMIT
        if truncated:
            output.write(
                f"# WARNING: results truncated at {CSV_EXPORT_LIMIT} rows "
                f"({len(matched)} matched)\r\n"
            )

        # CSV header row.
        writer.writerow([
            "line_number",
            "gvt_sub_agency",
            "company",
            "docu_type",
            "source",
            "sinq_error",
            "has_sinq_error",
            "approved_description",
        ])

        # Data rows — capped at CSV_EXPORT_LIMIT.
        for r in matched[:CSV_EXPORT_LIMIT]:
            desc = ref_table.lookup(r.docu_type, r.sinq_error)
            writer.writerow([
                r.line_number,
                _sanitise_csv_cell(r.gvt_sub_agency),
                _sanitise_csv_cell(r.company),
                _sanitise_csv_cell(r.docu_type),
                _sanitise_csv_cell(r.source),
                _sanitise_csv_cell(r.sinq_error),
                r.has_sinq_error,
                _sanitise_csv_cell(desc),
            ])

        csv_bytes = output.getvalue().encode("utf-8")

        return StreamingResponse(
            iter([csv_bytes]),
            status_code=200,
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="processing_monitor_export.csv"'
                ),
            },
        )

    @mcp.custom_route("/dashboard", methods=["GET"])
    async def dashboard(request: Request) -> HTMLResponse:
        tmpl = _JINJA_ENV.get_template("dashboard.html")

        # ── Parse query parameters ──────────────────────────────────────────
        q = request.query_params

        gvt_sub_agency = q.get("gvt_sub_agency", "").strip() or None
        company        = q.get("company", "").strip() or None
        source         = q.get("source", "").strip() or None
        sinq_error     = q.get("sinq_error", "").strip() or None
        has_sinq_error = _parse_has_sinq(q.get("has_sinq_error"))

        # has_sinq_error raw string for repopulating the filter form
        has_sinq_raw = q.get("has_sinq_error", "")
        if has_sinq_raw not in ("true", "false"):
            has_sinq_raw = ""

        offset = _parse_int(q.get("offset"), default=0, minimum=0)
        limit  = _parse_int(q.get("limit"), default=_DEFAULT_LIMIT, minimum=1)
        limit  = min(limit, _MAX_LIMIT)

        # ── Load transaction file ───────────────────────────────────────────
        try:
            monitor = load_monitor(settings.dat_file_path)
        except OSError:
            html = tmpl.render(error=True)
            return HTMLResponse(html, status_code=500)

        # ── Load reference file ─────────────────────────────────────────────
        try:
            ref_table = load_reference(settings.reference_file_path)
        except OSError:
            html = tmpl.render(error=True)
            return HTMLResponse(html, status_code=500)

        # ── Summary: always the full file ───────────────────────────────────
        summary = monitor.summarize()

        # ── SINQ error breakdown: always the full file ──────────────────────
        all_records = monitor.filter_records()
        sinq_groups = _group_sinq_errors(all_records, ref_table)

        show_all         = q.get("show_all", "") == "1"
        sinq_groups_top  = sinq_groups[:_BREAKDOWN_LIMIT]
        sinq_groups_rest = sinq_groups[_BREAKDOWN_LIMIT:]

        # ── Filtered result set ─────────────────────────────────────────────
        record_filter = RecordFilter(
            gvt_sub_agency=gvt_sub_agency,
            company=company,
            source=source,
            sinq_error=sinq_error,
            has_sinq_error=has_sinq_error,
        )
        # docu_type filter — parsed separately so it does not affect URL params
        docu_type_filter = q.get("docu_type", "").strip() or None
        record_filter.docu_type = docu_type_filter
        matched = monitor.filter_records(record_filter)
        matched_count = len(matched)

        # Clamp offset to valid range after we know the matched count.
        if offset >= matched_count and matched_count > 0:
            offset = 0

        page_result = paginate(matched, limit, offset)

        # ── filter_params dict — used for pagination, breakdown, download URLs
        filter_params = {
            "gvt_sub_agency": gvt_sub_agency or "",
            "company":        company or "",
            "docu_type":      docu_type_filter or "",
            "source":         source or "",
            "sinq_error":     sinq_error or "",
            "has_sinq_error": has_sinq_raw,
            "limit":          str(limit) if limit != _DEFAULT_LIMIT else "",
        }

        # ── Six safe fields + ref_description; nothing else ─────────────────
        # sinq_message, gwebess_raw, powrdocs_raw, and raw lines are excluded.
        # review_url removed — Review column no longer appears in the table.
        rows = [
            {
                "line_number":     r.line_number,
                "gvt_sub_agency":  r.gvt_sub_agency,
                "company":         r.company,
                "docu_type":       r.docu_type,
                "source":          r.source,
                "sinq_error":      r.sinq_error,
                "ref_description": ref_table.lookup(r.docu_type, r.sinq_error),
            }
            for r in page_result["items"]
        ]

        # ── Pagination metadata ─────────────────────────────────────────────
        total_pages = max(1, math.ceil(matched_count / limit))
        current_page = (offset // limit) + 1

        prev_offset = max(0, offset - limit)
        next_offset = page_result["next_offset"] or offset

        # show_all / show_fewer URLs preserve active filters, reset offset to 0
        show_all_url   = _build_breakdown_url(filter_params, show_all=True)
        show_fewer_url = _build_breakdown_url(filter_params, show_all=False)

        # download URL preserves all active filters
        download_url = _build_download_url(filter_params)

        html = tmpl.render(
            error=False,
            summary=summary,
            sinq_groups=sinq_groups,
            sinq_groups_top=sinq_groups_top,
            sinq_groups_rest=sinq_groups_rest,
            show_all=show_all,
            show_all_url=show_all_url,
            show_fewer_url=show_fewer_url,
            filters={
                "gvt_sub_agency": gvt_sub_agency,
                "company":        company,
                "docu_type":      docu_type_filter,
                "source":         source,
                "sinq_error":     sinq_error,
                "has_sinq_error": has_sinq_raw,
            },
            matched_count=matched_count,
            rows=rows,
            offset=offset,
            has_more=page_result["has_more"],
            has_prev=offset > 0,
            page=current_page,
            total_pages=total_pages,
            next_url=_build_filter_url(filter_params, next_offset),
            prev_url=_build_filter_url(filter_params, prev_offset),
            download_url=download_url,
        )
        return HTMLResponse(html, status_code=200)
