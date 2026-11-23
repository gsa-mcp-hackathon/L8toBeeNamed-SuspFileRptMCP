"""MCP tool: find_processing_errors.

Read-only tool that queries personnel processing return records from the
configured local flat file. Supports optional filtering by sub-agency, company,
document type, source system, SINQ error code, and SINQ error presence.
Results are paginated.

Security properties:
  - The data file path and reference file path come from settings (environment
    config). MCP callers cannot supply or change either path.
  - ParseError records (malformed lines) are never included in results.
  - Raw record contents are never returned. sinq_message is intentionally
    excluded — raw SINQ message text must never be exposed.
  - gwebess_raw, powrdocs_raw, and raw 200-character lines are never returned.
  - ref_description comes from the approved reference file only; it is never
    derived from sinq_message.
  - No external systems, databases, or shell commands are used.
  - The tool is declared read-only via MCP annotations.

Output fields per result record (8 total):
  line_number, gvt_sub_agency, company, docu_type, source,
  sinq_error, ref_description, has_sinq_error
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP

from example_server.config import settings
from example_server.models import PaginationParams
from example_server.query import RecordFilter, load_monitor
from example_server.reference import load_reference
from example_server.utils import paginate

# Eight result keys returned per record.
# sinq_message is intentionally absent — raw SINQ text must never be exposed.
# gwebess_raw and powrdocs_raw are internal indicator fields, also absent.
_RESULT_KEYS = (
    "line_number",
    "gvt_sub_agency",
    "company",
    "docu_type",
    "source",
    "sinq_error",
    "ref_description",
    "has_sinq_error",
)

# Default page size for this tool. The model cap is 200.
_DEFAULT_LIMIT = 50


def register(mcp: FastMCP) -> None:
    """Register the find_processing_errors tool with the MCP server."""

    @mcp.tool(
        name="find_processing_errors",
        annotations={
            "title": "Find Processing Errors",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def find_processing_errors(
        gvt_sub_agency: Annotated[
            str | None,
            "Filter by GVT sub-agency code (e.g. '12'). Case-insensitive.",
        ] = None,
        company: Annotated[
            str | None,
            "Filter by company code (e.g. '34'). Case-insensitive.",
        ] = None,
        docu_type: Annotated[
            str | None,
            "Filter by document type code (e.g. '030'). Case-insensitive.",
        ] = None,
        source: Annotated[
            str | None,
            (
                "Filter by source system. "
                "One of: 'EmpowHR', 'Employee Personal Page', 'Unknown'. "
                "Case-insensitive."
            ),
        ] = None,
        sinq_error: Annotated[
            str | None,
            "Filter by a specific SINQ error code. Case-insensitive.",
        ] = None,
        has_sinq_error: Annotated[
            bool | None,
            (
                "true = only records with any SINQ error; "
                "false = only records without a SINQ error; "
                "null / omit = no filter on error presence."
            ),
        ] = None,
        pagination: Annotated[
            PaginationParams | None,
            (
                "Pagination controls. "
                f"Default limit: {_DEFAULT_LIMIT}. Maximum limit: 200."
            ),
        ] = None,
    ) -> dict[str, Any]:
        """Find personnel processing return records, with optional filters.

        Reads the configured local flat file, applies all supplied filters
        simultaneously (AND logic), and returns a paginated result set.
        Each result includes an approved reference description looked up from
        the configured SINQ error reference file using (docu_type, sinq_error).

        Parse errors (malformed lines) are counted in the summary but are
        never included in results. Raw record contents are never returned.
        sinq_message is intentionally excluded from all output.

        Args:
            gvt_sub_agency: Filter by sub-agency code. Case-insensitive.
            company:        Filter by company code. Case-insensitive.
            docu_type:      Filter by document type code. Case-insensitive.
            source:         Filter by source system name. Case-insensitive.
            sinq_error:     Filter by specific SINQ error code.
            has_sinq_error: Filter by presence or absence of any SINQ error.
            pagination:     Page size (limit, default 50, max 200) and offset.

        Returns:
            A dict with filters_applied, summary, and results keys.
            Each result item contains eight fields; sinq_message is absent.
        """
        # Resolve pagination, applying this tool's default limit.
        page_params = pagination or PaginationParams(limit=_DEFAULT_LIMIT)

        # Load transaction file — path is never caller-supplied.
        try:
            monitor = load_monitor(settings.dat_file_path)
        except OSError as exc:
            filename = settings.dat_file_path.rsplit("/", 1)[-1]
            return {
                "error": (
                    f"Could not read data file: {filename}. "
                    f"Reason: {type(exc).__name__}."
                )
            }

        # Load reference file — path is never caller-supplied.
        try:
            ref_table = load_reference(settings.reference_file_path)
        except OSError as exc:
            filename = settings.reference_file_path.rsplit("/", 1)[-1]
            return {
                "error": (
                    f"Could not read reference file: {filename}. "
                    f"Reason: {type(exc).__name__}."
                )
            }

        file_summary = monitor.summarize()
        record_filter = RecordFilter(
            gvt_sub_agency=gvt_sub_agency,
            company=company,
            docu_type=docu_type,
            source=source,
            sinq_error=sinq_error,
            has_sinq_error=has_sinq_error,
        )
        matched = monitor.filter_records(record_filter)

        # Count SINQ errors across the full matched set (before pagination).
        sinq_error_count = sum(1 for r in matched if r.has_sinq_error)

        # Paginate the matched records.
        page = paginate(matched, page_params.limit, page_params.offset)

        # Serialize only the eight permitted fields.
        # sinq_message, gwebess_raw, powrdocs_raw, and raw lines are excluded.
        # ref_description comes from the reference file, never from sinq_message.
        results = [
            {
                "line_number":     r.line_number,
                "gvt_sub_agency":  r.gvt_sub_agency,
                "company":         r.company,
                "docu_type":       r.docu_type,
                "source":          r.source,
                "sinq_error":      r.sinq_error,
                "ref_description": ref_table.lookup(r.docu_type, r.sinq_error),
                "has_sinq_error":  r.has_sinq_error,
            }
            for r in page["items"]
        ]

        return {
            "filters_applied": {
                "gvt_sub_agency": gvt_sub_agency,
                "company":        company,
                "docu_type":      docu_type,
                "source":         source,
                "sinq_error":     sinq_error,
                "has_sinq_error": has_sinq_error,
            },
            "summary": {
                "total_valid_records":   file_summary.total_valid,
                "parse_error_count":     file_summary.parse_error_count,
                "matched_record_count":  len(matched),
                "returned_record_count": page["count"],
                "sinq_error_count":      sinq_error_count,
                "has_more":              page["has_more"],
                "next_offset":           page["next_offset"],
            },
            "results": results,
        }
