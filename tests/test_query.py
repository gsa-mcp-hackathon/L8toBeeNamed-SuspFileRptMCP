"""Unit tests for the read-only filtering service (query.py).

All test data is built from synthetic 200-character strings constructed
inline. No contents of AI_HACK_TEST_ONE.DAT are used or referenced here.

The _make_record helper is duplicated from test_parser.py so that each test
module is self-contained and changes to one do not break the other.
"""

from __future__ import annotations

from example_server.parser import RECORD_LENGTH, ParsedRecord, ParseError
from example_server.query import (
    ProcessingMonitor,
    QuerySummary,
    RecordFilter,
    _matches,
    load_monitor,
)

# ---------------------------------------------------------------------------
# Synthetic record builder (same field positions as test_parser.py)
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
    """Build a synthetic 200-character record string.

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


def _parsed(
    gvt_sub_agency: str = "",
    company: str = "",
    docu_type: str = "",
    source: str = "Unknown",
    sinq_error: str = "",
    sinq_message: str = "",
    line_number: int = 1,
) -> ParsedRecord:
    """Build a ParsedRecord directly for tests that do not need parse_line."""
    return ParsedRecord(
        line_number=line_number,
        gvt_sub_agency=gvt_sub_agency,
        company=company,
        docu_type=docu_type,
        gwebess_raw="GWEBESS" if source == "Employee Personal Page" else "",
        sinq_error=sinq_error,
        sinq_message=sinq_message,
        powrdocs_raw="POWRDOCS" if source == "EmpowHR" else "",
        source=source,
        has_sinq_error=sinq_error != "",
    )


def _error(line_number: int = 99) -> ParseError:
    return ParseError(
        line_number=line_number,
        reason=f"Expected 200 characters; got 10 on line {line_number}.",
    )


def _monitor(*records: ParsedRecord | ParseError) -> ProcessingMonitor:
    """Build a ProcessingMonitor directly from a sequence of records/errors."""
    return ProcessingMonitor(list(records))


# ---------------------------------------------------------------------------
# RecordFilter dataclass defaults
# ---------------------------------------------------------------------------


class TestRecordFilterDefaults:
    def test_all_fields_default_to_none(self):
        f = RecordFilter()
        assert f.gvt_sub_agency is None
        assert f.company is None
        assert f.docu_type is None
        assert f.source is None
        assert f.sinq_error is None
        assert f.has_sinq_error is None


# ---------------------------------------------------------------------------
# _matches — single-field filter logic
# ---------------------------------------------------------------------------


class TestMatchesSingleField:
    def test_gvt_sub_agency_match(self):
        r = _parsed(gvt_sub_agency="12")
        assert _matches(r, RecordFilter(gvt_sub_agency="12"))

    def test_gvt_sub_agency_no_match(self):
        r = _parsed(gvt_sub_agency="12")
        assert not _matches(r, RecordFilter(gvt_sub_agency="99"))

    def test_company_match(self):
        r = _parsed(company="34")
        assert _matches(r, RecordFilter(company="34"))

    def test_company_no_match(self):
        r = _parsed(company="34")
        assert not _matches(r, RecordFilter(company="00"))

    def test_source_empowhr_match(self):
        r = _parsed(source="EmpowHR")
        assert _matches(r, RecordFilter(source="EmpowHR"))

    def test_source_employee_personal_page_match(self):
        r = _parsed(source="Employee Personal Page")
        assert _matches(r, RecordFilter(source="Employee Personal Page"))

    def test_source_unknown_match(self):
        r = _parsed(source="Unknown")
        assert _matches(r, RecordFilter(source="Unknown"))

    def test_source_no_match(self):
        r = _parsed(source="EmpowHR")
        assert not _matches(r, RecordFilter(source="Unknown"))

    def test_sinq_error_code_match(self):
        r = _parsed(sinq_error="E01")
        assert _matches(r, RecordFilter(sinq_error="E01"))

    def test_sinq_error_code_no_match(self):
        r = _parsed(sinq_error="E01")
        assert not _matches(r, RecordFilter(sinq_error="E99"))

    def test_has_sinq_error_true_matches_nonblank(self):
        r = _parsed(sinq_error="E01")
        assert _matches(r, RecordFilter(has_sinq_error=True))

    def test_has_sinq_error_true_rejects_blank(self):
        r = _parsed(sinq_error="")
        assert not _matches(r, RecordFilter(has_sinq_error=True))

    def test_has_sinq_error_false_matches_blank(self):
        r = _parsed(sinq_error="")
        assert _matches(r, RecordFilter(has_sinq_error=False))

    def test_has_sinq_error_false_rejects_nonblank(self):
        r = _parsed(sinq_error="E01")
        assert not _matches(r, RecordFilter(has_sinq_error=False))

    def test_has_sinq_error_none_matches_either(self):
        assert _matches(_parsed(sinq_error="E01"), RecordFilter(has_sinq_error=None))
        assert _matches(_parsed(sinq_error=""),    RecordFilter(has_sinq_error=None))

    def test_docu_type_match(self):
        r = _parsed(docu_type="060")
        assert _matches(r, RecordFilter(docu_type="060"))

    def test_docu_type_no_match(self):
        r = _parsed(docu_type="060")
        assert not _matches(r, RecordFilter(docu_type="999"))

    def test_docu_type_none_matches_all(self):
        r = _parsed(docu_type="060")
        assert _matches(r, RecordFilter(docu_type=None))

    def test_no_constraints_matches_any_record(self):
        r = _parsed(
            gvt_sub_agency="12", company="34", source="EmpowHR", sinq_error="E01"
        )
        assert _matches(r, RecordFilter())


# ---------------------------------------------------------------------------
# _matches — case-insensitive comparisons
# ---------------------------------------------------------------------------


class TestMatchesCaseInsensitive:
    def test_gvt_sub_agency_lowercase_filter(self):
        r = _parsed(gvt_sub_agency="AB")
        assert _matches(r, RecordFilter(gvt_sub_agency="ab"))

    def test_gvt_sub_agency_mixed_case_filter(self):
        r = _parsed(gvt_sub_agency="ab")
        assert _matches(r, RecordFilter(gvt_sub_agency="AB"))

    def test_company_case_insensitive(self):
        r = _parsed(company="Xy")
        assert _matches(r, RecordFilter(company="xY"))

    def test_source_lowercase_filter(self):
        r = _parsed(source="EmpowHR")
        assert _matches(r, RecordFilter(source="empowhr"))

    def test_sinq_error_code_case_insensitive(self):
        r = _parsed(sinq_error="e01")
        assert _matches(r, RecordFilter(sinq_error="E01"))

    def test_docu_type_case_insensitive(self):
        r = _parsed(docu_type="abc")
        assert _matches(r, RecordFilter(docu_type="ABC"))


# ---------------------------------------------------------------------------
# _matches — AND logic with multiple filters
# ---------------------------------------------------------------------------


class TestMatchesAndLogic:
    def test_all_fields_match(self):
        r = _parsed(
            gvt_sub_agency="12", company="34", source="EmpowHR", sinq_error="E01"
        )
        f = RecordFilter(
            gvt_sub_agency="12", company="34", source="EmpowHR", sinq_error="E01"
        )
        assert _matches(r, f)

    def test_one_field_mismatch_rejects_record(self):
        r = _parsed(gvt_sub_agency="12", company="34", source="EmpowHR")
        f = RecordFilter(gvt_sub_agency="12", company="99")  # company mismatch
        assert not _matches(r, f)

    def test_sinq_error_code_and_has_sinq_error_true_both_match(self):
        r = _parsed(sinq_error="E01")
        f = RecordFilter(sinq_error="E01", has_sinq_error=True)
        assert _matches(r, f)

    def test_sinq_error_code_present_but_has_sinq_error_false_rejects(self):
        """Contradictory filter: specific code set but has_sinq_error=False."""
        r = _parsed(sinq_error="E01")
        f = RecordFilter(sinq_error="E01", has_sinq_error=False)
        assert not _matches(r, f)

    def test_source_and_gvt_sub_agency_combined(self):
        r = _parsed(gvt_sub_agency="12", source="EmpowHR")
        assert _matches(r, RecordFilter(gvt_sub_agency="12", source="EmpowHR"))
        assert not _matches(r, RecordFilter(gvt_sub_agency="12", source="Unknown"))


# ---------------------------------------------------------------------------
# ProcessingMonitor.filter_records
# ---------------------------------------------------------------------------


class TestFilterRecords:
    def test_no_filter_returns_all_valid_records(self):
        r1 = _parsed(gvt_sub_agency="12", line_number=1)
        r2 = _parsed(gvt_sub_agency="34", line_number=2)
        m = _monitor(r1, r2)
        assert m.filter_records() == [r1, r2]

    def test_none_filter_returns_all_valid_records(self):
        r1 = _parsed(line_number=1)
        m = _monitor(r1)
        assert m.filter_records(None) == [r1]

    def test_parse_errors_are_never_in_results(self):
        r = _parsed(line_number=1)
        e = _error(line_number=2)
        m = _monitor(r, e)
        results = m.filter_records()
        assert all(isinstance(x, ParsedRecord) for x in results)
        assert len(results) == 1

    def test_parse_errors_excluded_even_with_empty_filter(self):
        e = _error()
        m = _monitor(e)
        assert m.filter_records(RecordFilter()) == []

    def test_filter_by_gvt_sub_agency(self):
        r1 = _parsed(gvt_sub_agency="12", line_number=1)
        r2 = _parsed(gvt_sub_agency="99", line_number=2)
        m = _monitor(r1, r2)
        assert m.filter_records(RecordFilter(gvt_sub_agency="12")) == [r1]

    def test_filter_by_company(self):
        r1 = _parsed(company="AB", line_number=1)
        r2 = _parsed(company="ZZ", line_number=2)
        m = _monitor(r1, r2)
        assert m.filter_records(RecordFilter(company="AB")) == [r1]

    def test_filter_by_source_empowhr(self):
        r1 = _parsed(source="EmpowHR", line_number=1)
        r2 = _parsed(source="Unknown", line_number=2)
        m = _monitor(r1, r2)
        assert m.filter_records(RecordFilter(source="EmpowHR")) == [r1]

    def test_filter_by_source_employee_personal_page(self):
        r1 = _parsed(source="Employee Personal Page", line_number=1)
        r2 = _parsed(source="EmpowHR", line_number=2)
        m = _monitor(r1, r2)
        assert m.filter_records(RecordFilter(source="Employee Personal Page")) == [r1]

    def test_filter_by_sinq_error_code(self):
        r1 = _parsed(sinq_error="E01", line_number=1)
        r2 = _parsed(sinq_error="E02", line_number=2)
        r3 = _parsed(sinq_error="",    line_number=3)
        m = _monitor(r1, r2, r3)
        assert m.filter_records(RecordFilter(sinq_error="E01")) == [r1]

    def test_filter_by_has_sinq_error_true(self):
        r1 = _parsed(sinq_error="E01", line_number=1)
        r2 = _parsed(sinq_error="",    line_number=2)
        m = _monitor(r1, r2)
        assert m.filter_records(RecordFilter(has_sinq_error=True)) == [r1]

    def test_filter_by_has_sinq_error_false(self):
        r1 = _parsed(sinq_error="E01", line_number=1)
        r2 = _parsed(sinq_error="",    line_number=2)
        m = _monitor(r1, r2)
        assert m.filter_records(RecordFilter(has_sinq_error=False)) == [r2]

    def test_filter_no_match_returns_empty_list(self):
        r1 = _parsed(gvt_sub_agency="12")
        m = _monitor(r1)
        assert m.filter_records(RecordFilter(gvt_sub_agency="99")) == []

    def test_filter_combined_company_and_source(self):
        r1 = _parsed(company="34", source="EmpowHR",   line_number=1)
        r2 = _parsed(company="34", source="Unknown",   line_number=2)
        r3 = _parsed(company="99", source="EmpowHR",   line_number=3)
        m = _monitor(r1, r2, r3)
        result = m.filter_records(RecordFilter(company="34", source="EmpowHR"))
        assert result == [r1]

    def test_filter_preserves_file_order(self):
        r1 = _parsed(gvt_sub_agency="12", line_number=1)
        r2 = _parsed(gvt_sub_agency="12", line_number=5)
        r3 = _parsed(gvt_sub_agency="12", line_number=9)
        m = _monitor(r1, r2, r3)
        result = m.filter_records(RecordFilter(gvt_sub_agency="12"))
        assert [r.line_number for r in result] == [1, 5, 9]

    def test_filter_case_insensitive_source(self):
        r = _parsed(source="EmpowHR")
        m = _monitor(r)
        assert m.filter_records(RecordFilter(source="empowhr")) == [r]

    def test_filter_returns_new_list_not_internal_reference(self):
        """Mutating the returned list must not affect the monitor's data."""
        r = _parsed()
        m = _monitor(r)
        result = m.filter_records()
        result.clear()
        assert m.filter_records() == [r]


# ---------------------------------------------------------------------------
# ProcessingMonitor.summarize
# ---------------------------------------------------------------------------


class TestSummarize:
    def test_empty_monitor_all_counts_zero(self):
        m = _monitor()
        s = m.summarize()
        assert s.total_valid == 0
        assert s.parse_error_count == 0
        assert s.by_source == {}
        assert s.sinq_error_count == 0
        assert s.parse_errors == []

    def test_total_valid_count(self):
        m = _monitor(_parsed(line_number=1), _parsed(line_number=2))
        assert m.summarize().total_valid == 2

    def test_parse_error_count(self):
        m = _monitor(
            _parsed(line_number=1), _error(line_number=2), _error(line_number=3)
        )
        assert m.summarize().parse_error_count == 2

    def test_by_source_single_source(self):
        m = _monitor(
            _parsed(source="EmpowHR", line_number=1),
            _parsed(source="EmpowHR", line_number=2),
        )
        assert m.summarize().by_source == {"EmpowHR": 2}

    def test_by_source_multiple_sources(self):
        m = _monitor(
            _parsed(source="EmpowHR",             line_number=1),
            _parsed(source="Employee Personal Page", line_number=2),
            _parsed(source="Unknown",             line_number=3),
            _parsed(source="EmpowHR",             line_number=4),
        )
        s = m.summarize()
        assert s.by_source["EmpowHR"] == 2
        assert s.by_source["Employee Personal Page"] == 1
        assert s.by_source["Unknown"] == 1

    def test_sinq_error_count(self):
        m = _monitor(
            _parsed(sinq_error="E01", line_number=1),
            _parsed(sinq_error="",    line_number=2),
            _parsed(sinq_error="E02", line_number=3),
        )
        assert m.summarize().sinq_error_count == 2

    def test_sinq_error_count_zero_when_none_present(self):
        m = _monitor(_parsed(sinq_error=""), _parsed(sinq_error=""))
        assert m.summarize().sinq_error_count == 0

    def test_parse_errors_list_is_included_in_summary(self):
        e1 = _error(line_number=5)
        e2 = _error(line_number=10)
        m = _monitor(_parsed(line_number=1), e1, e2)
        s = m.summarize()
        assert s.parse_errors == [e1, e2]

    def test_parse_errors_list_empty_when_no_errors(self):
        m = _monitor(_parsed())
        assert m.summarize().parse_errors == []

    def test_summary_is_a_query_summary_instance(self):
        m = _monitor()
        assert isinstance(m.summarize(), QuerySummary)

    def test_parse_errors_not_counted_in_total_valid(self):
        m = _monitor(_parsed(line_number=1), _error(line_number=2))
        s = m.summarize()
        assert s.total_valid == 1
        assert s.parse_error_count == 1

    def test_by_source_excludes_parse_errors(self):
        """ParseError records must not contribute to the by_source counts."""
        m = _monitor(_parsed(source="EmpowHR"), _error())
        assert m.summarize().by_source == {"EmpowHR": 1}


# ---------------------------------------------------------------------------
# load_monitor — file I/O integration (tmp_path, synthetic data)
# ---------------------------------------------------------------------------


class TestLoadMonitor:
    def test_returns_processing_monitor(self, tmp_path):
        f = tmp_path / "test.dat"
        f.write_text("", encoding="utf-8")
        result = load_monitor(f)
        assert isinstance(result, ProcessingMonitor)

    def test_accepts_string_path(self, tmp_path):
        f = tmp_path / "test.dat"
        f.write_text("", encoding="utf-8")
        result = load_monitor(str(f))
        assert isinstance(result, ProcessingMonitor)

    def test_accepts_pathlib_path(self, tmp_path):
        f = tmp_path / "test.dat"
        f.write_text("", encoding="utf-8")
        result = load_monitor(f)
        assert isinstance(result, ProcessingMonitor)

    def test_empty_file_has_zero_counts(self, tmp_path):
        f = tmp_path / "test.dat"
        f.write_text("", encoding="utf-8")
        s = load_monitor(f).summarize()
        assert s.total_valid == 0
        assert s.parse_error_count == 0

    def test_valid_line_appears_in_filter_results(self, tmp_path):
        f = tmp_path / "test.dat"
        line = _make_record(gvt_sub_agency="12", powrdocs="POWRDOCS") + "\n"
        f.write_text(line, encoding="utf-8")
        m = load_monitor(f)
        results = m.filter_records(RecordFilter(gvt_sub_agency="12"))
        assert len(results) == 1
        assert results[0].gvt_sub_agency == "12"
        assert results[0].source == "EmpowHR"

    def test_short_line_becomes_parse_error(self, tmp_path):
        f = tmp_path / "test.dat"
        f.write_text("TOOSHORT\n", encoding="utf-8")
        m = load_monitor(f)
        s = m.summarize()
        assert s.total_valid == 0
        assert s.parse_error_count == 1
        assert len(s.parse_errors) == 1
        assert s.parse_errors[0].line_number == 1

    def test_mixed_file_counts_correctly(self, tmp_path):
        f = tmp_path / "test.dat"
        valid1 = _make_record(gvt_sub_agency="12", sinq_error="E01") + "\n"
        bad    = "BAD\n"
        valid2 = _make_record(gvt_sub_agency="34") + "\n"
        f.write_text(valid1 + bad + valid2, encoding="utf-8")
        m = load_monitor(f)
        s = m.summarize()
        assert s.total_valid == 2
        assert s.parse_error_count == 1
        assert s.sinq_error_count == 1

    def test_filter_excludes_parse_errors_from_file(self, tmp_path):
        f = tmp_path / "test.dat"
        valid = _make_record(gvt_sub_agency="12") + "\n"
        bad   = "BAD\n"
        f.write_text(valid + bad, encoding="utf-8")
        m = load_monitor(f)
        results = m.filter_records()
        assert len(results) == 1
        assert isinstance(results[0], ParsedRecord)

    def test_150_char_line_is_a_parse_error(self, tmp_path):
        """A 150-character non-blank line must produce a ParseError, not a record."""
        f = tmp_path / "test.dat"
        f.write_text("X" * 150 + "\n", encoding="utf-8")
        m = load_monitor(f)
        s = m.summarize()
        assert s.total_valid == 0
        assert s.parse_error_count == 1
        assert s.parse_errors[0].line_number == 1
