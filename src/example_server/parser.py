"""Fixed-width flat file parser for personnel processing return records.

Reads sample-data/AI_HACK_TEST_TWO.DAT (or any compatible file) one line at
a time and extracts the confirmed fields using the positions documented in the
project spec. No external systems, databases, or network calls are used.

Field positions (1-based, inclusive → Python zero-based, end-exclusive):
  GVT_SUB_AGENCY  positions 10–11  →  line[9:11]
  COMPANY         positions 16–17  →  line[15:17]
  DOCU_TYPE       positions 18–20  →  line[17:20]
  GWEBESS         positions 45–51  →  line[44:51]
  SINQ_ERROR      positions 52–54  →  line[51:54]
  SINQ_MESSAGE    positions 55–103 →  line[54:103]
  POWRDOCS        positions 186–193 → line[185:193]

Source classification (EmpowHR takes precedence):
  1. POWRDOCS field == "POWRDOCS"  → "EmpowHR"
  2. GWEBESS  field == "GWEBESS"   → "Employee Personal Page"
  3. Otherwise                     → "Unknown"
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Every valid data record is exactly this many characters (after stripping
# the line-ending characters so a normal trailing newline is not counted).
RECORD_LENGTH = 200


@dataclass
class ParsedRecord:
    """All extracted fields from one valid 200-character record."""

    line_number: int
    gvt_sub_agency: str
    company: str
    # trimmed; positions 18–20, line[17:20]; string — leading zeroes preserved
    docu_type: str
    gwebess_raw: str        # trimmed value of the GWEBESS indicator field
    sinq_error: str         # trimmed; nonblank means a SINQ error is present
    sinq_message: str       # trimmed SINQ message text; never exposed externally
    powrdocs_raw: str       # trimmed value of the POWRDOCS indicator field
    source: str             # "EmpowHR" | "Employee Personal Page" | "Unknown"
    has_sinq_error: bool    # True when sinq_error is nonblank


@dataclass
class ParseError:
    """Describes one malformed (non-blank, non-200-character) line."""

    line_number: int
    reason: str             # human-readable description; does not include raw data


def _classify_source(gwebess_raw: str, powrdocs_raw: str) -> str:
    """Return the source classification for one record.

    EmpowHR takes precedence when both indicators are present.
    """
    if powrdocs_raw == "POWRDOCS":
        return "EmpowHR"
    if gwebess_raw == "GWEBESS":
        return "Employee Personal Page"
    return "Unknown"


def parse_line(line: str, line_number: int) -> ParsedRecord | ParseError | None:
    """Parse one raw line from the flat file.

    Args:
        line:        The raw line exactly as read from the file (may include
                     line-ending characters; they are stripped internally).
        line_number: 1-based line number used for error reporting.

    Returns:
        None          – the line is blank (skip it).
        ParseError    – the line is non-blank but not exactly 200 data chars.
        ParsedRecord  – the line is valid; all fields are extracted and trimmed.
    """
    # Remove line-ending characters only (not other whitespace) so that a
    # normal trailing newline is not counted as part of the 200-char record.
    data = line.rstrip("\r\n")

    # Skip completely blank lines — defined as lines that are empty or contain
    # only whitespace AND are shorter than the required record length.
    # A 200-character record that happens to contain all spaces is still a
    # valid-length record and must be parsed, not skipped.
    if len(data) < RECORD_LENGTH and data.strip() == "":
        return None

    # Validate the fixed width.
    if len(data) != RECORD_LENGTH:
        return ParseError(
            line_number=line_number,
            reason=(
                f"Expected {RECORD_LENGTH} characters; "
                f"got {len(data)} on line {line_number}."
            ),
        )

    # Extract and trim each confirmed field.
    gvt_sub_agency = data[9:11].strip()
    company        = data[15:17].strip()
    docu_type      = data[17:20].strip()   # positions 18–20; preserved as string
    gwebess_raw    = data[44:51].strip()
    sinq_error     = data[51:54].strip()
    sinq_message   = data[54:103].strip()
    powrdocs_raw   = data[185:193].strip()

    source = _classify_source(gwebess_raw, powrdocs_raw)

    return ParsedRecord(
        line_number=line_number,
        gvt_sub_agency=gvt_sub_agency,
        company=company,
        docu_type=docu_type,
        gwebess_raw=gwebess_raw,
        sinq_error=sinq_error,
        sinq_message=sinq_message,
        powrdocs_raw=powrdocs_raw,
        source=source,
        has_sinq_error=sinq_error != "",
    )


def parse_file(path: str | Path) -> list[ParsedRecord | ParseError]:
    """Read the flat file and return a list of parsed records and errors.

    Blank lines are silently skipped and do not appear in the result.
    Malformed lines produce a ParseError entry.

    Args:
        path: Path to the fixed-width flat file (str or pathlib.Path).

    Returns:
        A list containing ParsedRecord and/or ParseError objects in file order.
    """
    results: list[ParsedRecord | ParseError] = []
    file_path = Path(path)

    with file_path.open(encoding="utf-8") as fh:
        for line_number, raw_line in enumerate(fh, start=1):
            result = parse_line(raw_line, line_number)
            if result is not None:
                results.append(result)

    return results
