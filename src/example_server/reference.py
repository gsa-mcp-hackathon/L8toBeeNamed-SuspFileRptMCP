"""Parser and lookup service for the PINE/NFC SINQ error reference file.

Reads a fixed-width reference file (one record per line, exactly 75
characters after stripping line-ending characters) and builds an in-memory
lookup table keyed by (DOCU_TYPE, ERR_MESS_NO).

Reference file layout (1-based positions, inclusive → Python slices):
  TBLE_CODE   positions  1– 3  →  line[0:3]
  DOCU_TYPE   positions  4– 6  →  line[3:6]
  ERR_MESS_NO positions  7– 9  →  line[6:9]
  ERR_MESS_DES positions 10–59 →  line[9:59]
  BEGIN_DT    positions 60–67  →  line[59:67]
  END_DT      positions 68–75  →  line[67:75]

All codes are preserved as trimmed strings (including leading zeroes).
BEGIN_DT and END_DT are stored as raw strings; the date format is not
assumed and no date parsing is performed here.

Lookup key: (DOCU_TYPE, ERR_MESS_NO) — both trimmed strings, matched
exactly (these are numeric codes; case is not a concern).

Duplicate keys: the first occurrence is kept deterministically; subsequent
rows with the same key are recorded as ReferenceValidationError entries and
do not overwrite the retained entry.

Missing key: lookup() returns the NO_REFERENCE_AVAILABLE sentinel string.

No transaction-file SINQ_MESSAGE values are processed here. No external
systems, databases, or network calls are used.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Sentinel returned by ReferenceTable.lookup() when no matching entry exists.
# Callers and tests should compare against this constant rather than
# hard-coding the string.
NO_REFERENCE_AVAILABLE: str = "No approved reference available"

# Fallback DOCU_TYPE mapping for reference lookups.
#
# Some transaction DOCU_TYPE codes share their low-numbered SINQ error codes
# with a related DOCU_TYPE in the reference file.  When a primary lookup by
# (docu_type, sinq_error) finds no entry, lookup() retries using the fallback
# DOCU_TYPE listed here before returning the sentinel.
#
# The primary key (docu_type, sinq_error) is always tried first; the fallback
# is only used when the primary produces no result.  This means that any
# 063-specific entries in the reference (e.g. ERR_MESS_NO 113–874) continue
# to be returned from the primary lookup without change.
DOCU_TYPE_FALLBACK: dict[str, str] = {
    "063": "060",  # DOCU_TYPE 063 shares low-numbered error codes with 060
}

# Every valid reference record is exactly this many characters after stripping
# line-ending characters.
REFERENCE_RECORD_LENGTH: int = 75


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class ReferenceRecord:
    """All fields extracted from one valid 75-character reference record."""

    tble_code: str     # trimmed; preserved even when not part of the lookup key
    docu_type: str     # trimmed; part of the lookup key
    err_mess_no: str   # trimmed; part of the lookup key
    err_mess_des: str  # trimmed approved description
    begin_dt: str      # raw 8-character string; date format not yet confirmed
    end_dt: str        # raw 8-character string; date format not yet confirmed


@dataclass
class ReferenceParseError:
    """Describes one malformed (non-blank, non-75-character) reference line."""

    line_number: int
    reason: str  # human-readable; does not include raw line content


@dataclass
class ReferenceValidationError:
    """Describes a duplicate (DOCU_TYPE, ERR_MESS_NO) key in the reference file.

    The first occurrence of the key is retained in the lookup table.
    Subsequent occurrences are recorded here and do not overwrite the
    retained entry.
    """

    line_number: int
    docu_type: str
    err_mess_no: str
    reason: str  # human-readable description


# ---------------------------------------------------------------------------
# Line-level parser
# ---------------------------------------------------------------------------


def parse_reference_line(
    line: str, line_number: int
) -> ReferenceRecord | ReferenceParseError | None:
    """Parse one raw line from the reference file.

    Args:
        line:        The raw line exactly as read from the file (may include
                     line-ending characters; they are stripped internally).
        line_number: 1-based line number used in error reporting.

    Returns:
        None                 – the line is blank (skip it).
        ReferenceParseError  – the line is non-blank but not exactly 75 chars.
        ReferenceRecord      – the line is valid; all fields extracted and trimmed.
    """
    data = line.rstrip("\r\n")

    # Skip blank lines (empty or all-whitespace shorter than the record length).
    if len(data) < REFERENCE_RECORD_LENGTH and data.strip() == "":
        return None

    if len(data) != REFERENCE_RECORD_LENGTH:
        return ReferenceParseError(
            line_number=line_number,
            reason=(
                f"Expected {REFERENCE_RECORD_LENGTH} characters; "
                f"got {len(data)} on line {line_number}."
            ),
        )

    return ReferenceRecord(
        tble_code=data[0:3].strip(),
        docu_type=data[3:6].strip(),
        err_mess_no=data[6:9].strip(),
        err_mess_des=data[9:59].strip(),
        begin_dt=data[59:67],   # raw; not trimmed — preserve all 8 characters
        end_dt=data[67:75],     # raw; not trimmed — preserve all 8 characters
    )


# ---------------------------------------------------------------------------
# Lookup table
# ---------------------------------------------------------------------------


class ReferenceTable:
    """In-memory lookup table built from a parsed reference file.

    Keyed by (docu_type, err_mess_no). The first occurrence of any duplicate
    key is retained; subsequent occurrences are recorded as
    ReferenceValidationError entries.

    Construct via load_reference(path) rather than directly.
    """

    def __init__(
        self,
        records: list[ReferenceRecord],
        parse_errors: list[ReferenceParseError],
        validation_errors: list[ReferenceValidationError],
    ) -> None:
        self._table: dict[tuple[str, str], ReferenceRecord] = {}
        self.parse_errors: list[ReferenceParseError] = list(parse_errors)
        self.validation_errors: list[ReferenceValidationError] = list(
            validation_errors
        )
        for record in records:
            self._table[(record.docu_type, record.err_mess_no)] = record

    def lookup(self, docu_type: str, sinq_error: str) -> str:
        """Return the approved description for (docu_type, sinq_error).

        Primary lookup uses (docu_type, sinq_error) exactly.  If no entry is
        found and docu_type has an entry in DOCU_TYPE_FALLBACK, the lookup is
        retried with the fallback DOCU_TYPE.  The sentinel NO_REFERENCE_AVAILABLE
        is returned only when both attempts fail.

        Args:
            docu_type:  DOCU_TYPE value from the transaction record (trimmed).
            sinq_error: SINQ_ERROR value from the transaction record (trimmed).

        Returns:
            The trimmed ERR_MESS_DES string if a match exists (primary or
            fallback), or NO_REFERENCE_AVAILABLE if no matching entry is found.
        """
        record = self._table.get((docu_type, sinq_error))
        if record is None:
            fallback = DOCU_TYPE_FALLBACK.get(docu_type)
            if fallback:
                record = self._table.get((fallback, sinq_error))
        if record is None:
            return NO_REFERENCE_AVAILABLE
        return record.err_mess_des


# ---------------------------------------------------------------------------
# File loader
# ---------------------------------------------------------------------------


def load_reference(path: str | Path) -> ReferenceTable:
    """Read the reference file and return a ReferenceTable ready for lookup.

    Malformed lines (wrong length) produce ReferenceParseError entries and
    do not stop processing. Duplicate (DOCU_TYPE, ERR_MESS_NO) keys produce
    ReferenceValidationError entries; the first occurrence is kept.

    Args:
        path: Path to the fixed-width reference file (str or pathlib.Path).

    Returns:
        A ReferenceTable populated with all valid records, parse errors,
        and validation errors.
    """
    file_path = Path(path)
    records: list[ReferenceRecord] = []
    parse_errors: list[ReferenceParseError] = []
    seen: dict[tuple[str, str], int] = {}   # key → first line_number
    validation_errors: list[ReferenceValidationError] = []

    with file_path.open(encoding="utf-8") as fh:
        for line_number, raw_line in enumerate(fh, start=1):
            result = parse_reference_line(raw_line, line_number)
            if result is None:
                continue
            if isinstance(result, ReferenceParseError):
                parse_errors.append(result)
                continue
            key = (result.docu_type, result.err_mess_no)
            if key in seen:
                validation_errors.append(
                    ReferenceValidationError(
                        line_number=line_number,
                        docu_type=result.docu_type,
                        err_mess_no=result.err_mess_no,
                        reason=(
                            f"Duplicate key ({result.docu_type!r}, "
                            f"{result.err_mess_no!r}) on line {line_number}; "
                            f"first seen on line {seen[key]}. "
                            f"First occurrence retained."
                        ),
                    )
                )
            else:
                seen[key] = line_number
                records.append(result)

    return ReferenceTable(records, parse_errors, validation_errors)
