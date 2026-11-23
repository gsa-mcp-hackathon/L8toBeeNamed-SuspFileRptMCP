"""Read-only filtering service for personnel processing return records.

Sits on top of parser.parse_file and provides:

  - RecordFilter   — optional filter criteria (AND logic, case-insensitive)
  - QuerySummary   — counts produced by ProcessingMonitor.summarize()
  - ProcessingMonitor — holds parsed results; exposes filter_records and summarize
  - load_monitor   — single entry point: parse a file and return a monitor

ParseError records are always excluded from filter_records results.
They are counted in QuerySummary.parse_error_count.

No data is written, modified, or sent anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from example_server.parser import ParsedRecord, ParseError, parse_file

# ---------------------------------------------------------------------------
# Public data structures
# ---------------------------------------------------------------------------


@dataclass
class RecordFilter:
    """Optional filter criteria for querying valid records.

    All fields default to None, which means "no constraint on this field."
    When multiple fields are set, all constraints must match simultaneously
    (AND logic). Comparisons are case-insensitive.

    Fields:
        gvt_sub_agency: Match records whose gvt_sub_agency equals this value.
        company:        Match records whose company equals this value.
        docu_type:      Match records whose docu_type equals this value.
                        Case-insensitive; None means no constraint.
        source:         Match records whose source equals this value.
                        Expected values: "EmpowHR", "Employee Personal Page",
                        "Unknown".
        sinq_error:     Match records whose sinq_error equals this specific
                        error code.
        has_sinq_error: True  → sinq_error field must be nonblank.
                        False → sinq_error field must be blank.
                        None  → no constraint on error presence.
    """

    gvt_sub_agency: str | None = None
    company: str | None = None
    docu_type: str | None = None
    source: str | None = None
    sinq_error: str | None = None
    has_sinq_error: bool | None = None


@dataclass
class QuerySummary:
    """Summary counts for all records in a loaded file.

    Fields:
        total_valid:       Number of successfully parsed records.
        parse_error_count: Number of malformed lines (ParseError instances).
        by_source:         Mapping of source name → count of valid records.
        sinq_error_count:  Number of valid records that have a nonblank
                           SINQ_ERROR value.
        parse_errors:      List of ParseError objects (line number + reason),
                           ordered as they appeared in the file.
    """

    total_valid: int
    parse_error_count: int
    by_source: dict[str, int]
    sinq_error_count: int
    parse_errors: list[ParseError] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core service class
# ---------------------------------------------------------------------------


class ProcessingMonitor:
    """Holds all parsed results for one file and answers read-only queries.

    Construct via load_monitor(path) rather than directly.
    """

    def __init__(self, results: list[ParsedRecord | ParseError]) -> None:
        # Separate valid records from parse errors once at construction time.
        self._records: list[ParsedRecord] = []
        self._errors: list[ParseError] = []
        for item in results:
            if isinstance(item, ParsedRecord):
                self._records.append(item)
            else:
                self._errors.append(item)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter_records(self, f: RecordFilter | None = None) -> list[ParsedRecord]:
        """Return valid records that match all supplied filter criteria.

        ParseError records are never included in results.

        Args:
            f: A RecordFilter instance. Pass None (or omit) to return all
               valid records with no filtering applied.

        Returns:
            A list of ParsedRecord objects in file order.
        """
        if f is None:
            return list(self._records)

        results: list[ParsedRecord] = []
        for record in self._records:
            if _matches(record, f):
                results.append(record)
        return results

    def summarize(self) -> QuerySummary:
        """Return summary counts for all records in the loaded file.

        Returns:
            A QuerySummary with total valid count, parse error count,
            per-source counts, SINQ error count, and the list of ParseErrors.
        """
        by_source: dict[str, int] = {}
        sinq_error_count = 0

        for record in self._records:
            by_source[record.source] = by_source.get(record.source, 0) + 1
            if record.has_sinq_error:
                sinq_error_count += 1

        return QuerySummary(
            total_valid=len(self._records),
            parse_error_count=len(self._errors),
            by_source=by_source,
            sinq_error_count=sinq_error_count,
            parse_errors=list(self._errors),
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_monitor(path: str | Path) -> ProcessingMonitor:
    """Parse a flat file and return a ProcessingMonitor ready for queries.

    This is the single entry point callers should use. It accepts both str
    and pathlib.Path values, delegating the actual path conversion to
    parse_file.

    Args:
        path: Path to the fixed-width flat file.

    Returns:
        A ProcessingMonitor populated with all parsed records and errors.
    """
    return ProcessingMonitor(parse_file(path))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _matches(record: ParsedRecord, f: RecordFilter) -> bool:
    """Return True when a record satisfies every non-None filter constraint."""
    if f.gvt_sub_agency is not None:
        if record.gvt_sub_agency.lower() != f.gvt_sub_agency.lower():
            return False

    if f.company is not None:
        if record.company.lower() != f.company.lower():
            return False

    if f.docu_type is not None:
        if record.docu_type.lower() != f.docu_type.lower():
            return False

    if f.source is not None:
        if record.source.lower() != f.source.lower():
            return False

    if f.sinq_error is not None:
        if record.sinq_error.lower() != f.sinq_error.lower():
            return False

    if f.has_sinq_error is not None:
        if record.has_sinq_error != f.has_sinq_error:
            return False

    return True
