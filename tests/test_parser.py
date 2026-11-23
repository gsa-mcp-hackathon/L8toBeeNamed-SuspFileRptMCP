"""Unit tests for the fixed-width flat file parser.

All test inputs are synthetic strings constructed inline. No contents of
AI_HACK_TEST_ONE.DAT are used or referenced here.

Synthetic record construction:
  A valid record is exactly 200 characters. Fields are placed at their
  confirmed zero-based slice positions; the rest is filled with spaces.
"""

from __future__ import annotations

from example_server.parser import (
    RECORD_LENGTH,
    ParsedRecord,
    ParseError,
    _classify_source,
    parse_file,
    parse_line,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    gvt_sub_agency: str = "  ",
    company: str = "  ",
    docu_type: str = "   ",
    gwebess: str = "       ",
    sinq_error: str = "   ",
    sinq_message: str = " " * 49,
    powrdocs: str = "        ",
) -> str:
    """Build a synthetic 200-character record from individual field values.

    Callers pass field values; the helper places them at the correct slice
    positions and fills the rest with spaces.

    Slice positions (zero-based, end-exclusive):
      gvt_sub_agency  [9:11]    → 2 chars
      company         [15:17]   → 2 chars
      docu_type       [17:20]   → 3 chars  (positions 18–20)
      gwebess         [44:51]   → 7 chars
      sinq_error      [51:54]   → 3 chars
      sinq_message    [54:103]  → 49 chars
      powrdocs        [185:193] → 8 chars
    """
    buf = [" "] * RECORD_LENGTH

    def _place(value: str, start: int, length: int) -> None:
        """Left-justify value into buf[start:start+length], padding with spaces."""
        padded = value[:length].ljust(length)
        for i, ch in enumerate(padded):
            buf[start + i] = ch

    _place(gvt_sub_agency, 9,   2)
    _place(company,         15,  2)
    _place(docu_type,       17,  3)
    _place(gwebess,         44,  7)
    _place(sinq_error,      51,  3)
    _place(sinq_message,    54, 49)
    _place(powrdocs,        185, 8)

    return "".join(buf)


# ---------------------------------------------------------------------------
# _classify_source
# ---------------------------------------------------------------------------

class TestClassifySource:
    def test_powrdocs_indicator_gives_empowhr(self):
        assert _classify_source("", "POWRDOCS") == "EmpowHR"

    def test_gwebess_indicator_gives_employee_personal_page(self):
        assert _classify_source("GWEBESS", "") == "Employee Personal Page"

    def test_neither_indicator_gives_unknown(self):
        assert _classify_source("", "") == "Unknown"

    def test_empowhr_takes_precedence_when_both_present(self):
        """EmpowHR must win when both POWRDOCS and GWEBESS are set."""
        assert _classify_source("GWEBESS", "POWRDOCS") == "EmpowHR"

    def test_partial_powrdocs_does_not_match(self):
        assert _classify_source("", "POWRDOC") == "Unknown"

    def test_partial_gwebess_does_not_match(self):
        assert _classify_source("GWBESS", "") == "Unknown"


# ---------------------------------------------------------------------------
# parse_line — blank and malformed lines
# ---------------------------------------------------------------------------

class TestParseLineBlankAndMalformed:
    def test_empty_string_returns_none(self):
        assert parse_line("", 1) is None

    def test_whitespace_only_returns_none(self):
        assert parse_line("   \t  ", 1) is None

    def test_line_with_only_newline_returns_none(self):
        assert parse_line("\n", 1) is None

    def test_line_with_crlf_only_returns_none(self):
        assert parse_line("\r\n", 1) is None

    def test_short_nonblank_line_returns_parse_error(self):
        short_line = "X" * 50
        result = parse_line(short_line, 5)
        assert isinstance(result, ParseError)
        assert result.line_number == 5

    def test_long_nonblank_line_returns_parse_error(self):
        long_line = "X" * 201
        result = parse_line(long_line, 7)
        assert isinstance(result, ParseError)
        assert result.line_number == 7

    def test_parse_error_reason_mentions_expected_and_actual_length(self):
        result = parse_line("A" * 10, 3)
        assert isinstance(result, ParseError)
        assert "200" in result.reason
        assert "10" in result.reason

    def test_trailing_newline_is_not_counted_in_length(self):
        """A 200-char record followed by \n must parse successfully."""
        record = _make_record() + "\n"
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)

    def test_trailing_crlf_is_not_counted_in_length(self):
        """A 200-char record followed by \r\n must parse successfully."""
        record = _make_record() + "\r\n"
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)


# ---------------------------------------------------------------------------
# parse_line — source classification
# ---------------------------------------------------------------------------

class TestParseLineSourceClassification:
    def test_empowhr_source(self):
        record = _make_record(powrdocs="POWRDOCS")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.source == "EmpowHR"

    def test_employee_personal_page_source(self):
        record = _make_record(gwebess="GWEBESS")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.source == "Employee Personal Page"

    def test_unknown_source(self):
        record = _make_record()
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.source == "Unknown"

    def test_empowhr_takes_precedence_over_gwebess(self):
        record = _make_record(gwebess="GWEBESS", powrdocs="POWRDOCS")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.source == "EmpowHR"


# ---------------------------------------------------------------------------
# parse_line — SINQ error detection
# ---------------------------------------------------------------------------

class TestParseLineSinqError:
    def test_nonblank_sinq_error_sets_has_sinq_error(self):
        record = _make_record(sinq_error="E01", sinq_message="Missing data")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.has_sinq_error is True
        assert result.sinq_error == "E01"

    def test_blank_sinq_error_clears_has_sinq_error(self):
        record = _make_record(sinq_error="   ")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.has_sinq_error is False
        assert result.sinq_error == ""

    def test_sinq_message_is_trimmed(self):
        record = _make_record(sinq_error="E02", sinq_message="  hello  ")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.sinq_message == "hello"


# ---------------------------------------------------------------------------
# parse_line — field extraction and trimming
# ---------------------------------------------------------------------------

class TestParseLineFieldExtraction:
    def test_gvt_sub_agency_is_extracted_and_trimmed(self):
        record = _make_record(gvt_sub_agency="12")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.gvt_sub_agency == "12"

    def test_company_is_extracted_and_trimmed(self):
        record = _make_record(company="34")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.company == "34"

    def test_padded_fields_are_trimmed(self):
        """Single-character values padded with a trailing space must trim correctly."""
        record = _make_record(gvt_sub_agency="9 ", company="5 ")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.gvt_sub_agency == "9"
        assert result.company == "5"

    def test_line_number_is_preserved(self):
        record = _make_record()
        result = parse_line(record, 42)
        assert isinstance(result, ParsedRecord)
        assert result.line_number == 42

    def test_powrdocs_raw_is_trimmed(self):
        record = _make_record(powrdocs="POWRDOCS")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.powrdocs_raw == "POWRDOCS"

    def test_gwebess_raw_is_trimmed(self):
        record = _make_record(gwebess="GWEBESS")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.gwebess_raw == "GWEBESS"

    def test_all_blank_fields_produce_empty_strings(self):
        record = _make_record()
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.gvt_sub_agency == ""
        assert result.company == ""
        assert result.docu_type == ""
        assert result.gwebess_raw == ""
        assert result.sinq_error == ""
        assert result.sinq_message == ""
        assert result.powrdocs_raw == ""


# ---------------------------------------------------------------------------
# parse_line — DOCU_TYPE field extraction
# ---------------------------------------------------------------------------

class TestParseLineDocuType:
    def test_docu_type_extracted_and_trimmed(self):
        record = _make_record(docu_type="060")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.docu_type == "060"

    def test_docu_type_preserves_leading_zeroes(self):
        record = _make_record(docu_type="001")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.docu_type == "001"

    def test_docu_type_blank_gives_empty_string(self):
        record = _make_record(docu_type="   ")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.docu_type == ""

    def test_docu_type_is_string_not_integer(self):
        record = _make_record(docu_type="030")
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert isinstance(result.docu_type, str)

    def test_docu_type_independent_of_sinq_message(self):
        """DOCU_TYPE at [17:20] must not overlap SINQ_MESSAGE at [54:103]."""
        record = _make_record(docu_type="054", sinq_message="XYZABC" + " " * 43)
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.docu_type == "054"
        assert result.sinq_message == "XYZABC"

    def test_docu_type_reads_from_positions_18_to_20(self):
        """Explicit position test: marker placed directly at buf[17:20].

        Bytes 34:37 (old incorrect position) are left as spaces.
        parse_line must return the marker from docu_type, proving extraction
        uses line[17:20] and not line[34:37].
        """
        buf = [" "] * RECORD_LENGTH
        # Place marker at the correct position only.
        buf[17] = "X"
        buf[18] = "Y"
        buf[19] = "Z"
        # Bytes 34–36 remain spaces (the old wrong position).
        record = "".join(buf)
        result = parse_line(record, 1)
        assert isinstance(result, ParsedRecord)
        assert result.docu_type == "XYZ", (
            "docu_type should be 'XYZ' from line[17:20]; "
            "got %r — parser may still use the old slice [34:37]" % result.docu_type
        )


# ---------------------------------------------------------------------------
# parse_file — integration smoke test (tmp_path, no real data file)
# ---------------------------------------------------------------------------

class TestParseFile:
    def test_parse_file_returns_list(self, tmp_path):
        """parse_file must return a list (may be empty for a blank file)."""
        f = tmp_path / "test.dat"
        f.write_text("", encoding="utf-8")
        result = parse_file(f)
        assert isinstance(result, list)

    def test_parse_file_accepts_string_path(self, tmp_path):
        f = tmp_path / "test.dat"
        f.write_text("", encoding="utf-8")
        result = parse_file(str(f))
        assert isinstance(result, list)

    def test_parse_file_skips_blank_lines(self, tmp_path):
        f = tmp_path / "test.dat"
        f.write_text("\n\n\n", encoding="utf-8")
        result = parse_file(f)
        assert result == []

    def test_parse_file_records_parse_error_for_short_line(self, tmp_path):
        f = tmp_path / "test.dat"
        f.write_text("TOOSHORT\n", encoding="utf-8")
        result = parse_file(f)
        assert len(result) == 1
        assert isinstance(result[0], ParseError)
        assert result[0].line_number == 1

    def test_parse_file_returns_parsed_record_for_valid_line(self, tmp_path):
        f = tmp_path / "test.dat"
        valid_line = _make_record(powrdocs="POWRDOCS") + "\n"
        f.write_text(valid_line, encoding="utf-8")
        result = parse_file(f)
        assert len(result) == 1
        assert isinstance(result[0], ParsedRecord)
        assert result[0].source == "EmpowHR"

    def test_parse_file_processes_mixed_lines(self, tmp_path):
        """Blank → ParsedRecord → ParseError must all appear in the right order."""
        f = tmp_path / "test.dat"
        valid_line   = _make_record(gwebess="GWEBESS") + "\n"
        bad_line     = "BAD\n"
        content      = "\n" + valid_line + bad_line
        f.write_text(content, encoding="utf-8")
        result = parse_file(f)
        assert len(result) == 2
        assert isinstance(result[0], ParsedRecord)
        assert result[0].source == "Employee Personal Page"
        assert isinstance(result[1], ParseError)

    def test_parse_file_line_numbers_are_correct(self, tmp_path):
        """Line numbers must reflect position in the original file.

        Blank lines count toward the line number but are not returned.
        """
        f = tmp_path / "test.dat"
        valid_line = _make_record() + "\n"
        content    = "\n" + valid_line   # line 1 blank, line 2 valid
        f.write_text(content, encoding="utf-8")
        result = parse_file(f)
        assert len(result) == 1
        assert result[0].line_number == 2

    def test_parse_file_counts_sinq_errors_correctly(self, tmp_path):
        """Multiple records with SINQ errors should all have has_sinq_error=True."""
        f = tmp_path / "test.dat"
        r1 = _make_record(sinq_error="E01") + "\n"
        r2 = _make_record(sinq_error="   ") + "\n"
        r3 = _make_record(sinq_error="E02") + "\n"
        f.write_text(r1 + r2 + r3, encoding="utf-8")
        result = parse_file(f)
        assert len(result) == 3
        sinq_flags = [r.has_sinq_error for r in result if isinstance(r, ParsedRecord)]
        assert sinq_flags == [True, False, True]
