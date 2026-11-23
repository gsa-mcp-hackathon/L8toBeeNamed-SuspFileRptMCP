"""Tests for the PINE/NFC SINQ error reference parser and lookup service.

All tests use synthetic in-memory reference lines constructed as
75-character fixed-width strings matching the documented layout.
The actual reference file on disk is never read by any test here.

Reference layout (Python slices, zero-based):
  TBLE_CODE   line[0:3]
  DOCU_TYPE   line[3:6]
  ERR_MESS_NO line[6:9]
  ERR_MESS_DES line[9:59]   (50 characters)
  BEGIN_DT    line[59:67]   (8 characters)
  END_DT      line[67:75]   (8 characters)
"""

from __future__ import annotations

from pathlib import Path

from example_server.reference import (
    NO_REFERENCE_AVAILABLE,
    REFERENCE_RECORD_LENGTH,
    ReferenceParseError,
    ReferenceRecord,
    ReferenceTable,
    ReferenceValidationError,
    load_reference,
    parse_reference_line,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ref_line(
    tble_code: str = "047",
    docu_type: str = "030",
    err_mess_no: str = "001",
    err_mess_des: str = "OUT OF BALANCE",
    begin_dt: str = "06231980",
    end_dt: str = "12312049",
) -> str:
    """Build a valid synthetic 75-character reference line.

    Each argument is padded or truncated to exactly fill its field width.
    The resulting string is exactly REFERENCE_RECORD_LENGTH characters with
    no trailing newline.
    """
    line = (
        tble_code[:3].ljust(3)
        + docu_type[:3].ljust(3)
        + err_mess_no[:3].ljust(3)
        + err_mess_des[:50].ljust(50)
        + begin_dt[:8].ljust(8)
        + end_dt[:8].ljust(8)
    )
    assert len(line) == REFERENCE_RECORD_LENGTH, (
        f"make_ref_line produced {len(line)} chars, "
        f"expected {REFERENCE_RECORD_LENGTH}"
    )
    return line


# ---------------------------------------------------------------------------
# TestParseReferenceLine — individual line parsing
# ---------------------------------------------------------------------------


class TestParseReferenceLine:
    """Tests for parse_reference_line()."""

    def test_valid_line_returns_record(self) -> None:
        line = make_ref_line() + "\n"
        result = parse_reference_line(line, 1)
        assert isinstance(result, ReferenceRecord)

    def test_blank_line_returns_none(self) -> None:
        assert parse_reference_line("", 1) is None
        assert parse_reference_line("\n", 1) is None
        assert parse_reference_line("   \n", 1) is None

    def test_short_line_returns_parse_error(self) -> None:
        short = "047030001" + "X" * 30 + "\n"   # 39 chars of data
        result = parse_reference_line(short, 5)
        assert isinstance(result, ReferenceParseError)
        assert result.line_number == 5
        assert "39" in result.reason
        assert str(REFERENCE_RECORD_LENGTH) in result.reason

    def test_long_line_returns_parse_error(self) -> None:
        long_line = make_ref_line() + "EXTRA\n"   # 80 chars of data
        result = parse_reference_line(long_line, 7)
        assert isinstance(result, ReferenceParseError)
        assert result.line_number == 7
        assert "80" in result.reason

    def test_parse_error_reason_does_not_contain_raw_content(self) -> None:
        """Error reason must be safe — no raw line content."""
        sensitive = (
            "047030001" + "SENSITIVE DATA" * 3 + "    " + "06231980" + "12312049"
        )
        result = parse_reference_line(sensitive + "EXTRA", 2)
        assert isinstance(result, ReferenceParseError)
        assert "SENSITIVE" not in result.reason

    def test_tble_code_extracted(self) -> None:
        line = make_ref_line(tble_code="047") + "\n"
        record = parse_reference_line(line, 1)
        assert isinstance(record, ReferenceRecord)
        assert record.tble_code == "047"

    def test_docu_type_extracted_with_leading_zeroes(self) -> None:
        line = make_ref_line(docu_type="030") + "\n"
        record = parse_reference_line(line, 1)
        assert isinstance(record, ReferenceRecord)
        assert record.docu_type == "030"

    def test_err_mess_no_extracted_with_leading_zeroes(self) -> None:
        line = make_ref_line(err_mess_no="007") + "\n"
        record = parse_reference_line(line, 1)
        assert isinstance(record, ReferenceRecord)
        assert record.err_mess_no == "007"

    def test_err_mess_des_trimmed(self) -> None:
        line = make_ref_line(err_mess_des="OUT OF BALANCE") + "\n"
        record = parse_reference_line(line, 1)
        assert isinstance(record, ReferenceRecord)
        assert record.err_mess_des == "OUT OF BALANCE"

    def test_begin_dt_raw_eight_chars(self) -> None:
        line = make_ref_line(begin_dt="06231980") + "\n"
        record = parse_reference_line(line, 1)
        assert isinstance(record, ReferenceRecord)
        assert record.begin_dt == "06231980"

    def test_end_dt_raw_eight_chars(self) -> None:
        line = make_ref_line(end_dt="12312049") + "\n"
        record = parse_reference_line(line, 1)
        assert isinstance(record, ReferenceRecord)
        assert record.end_dt == "12312049"

    def test_begin_dt_not_parsed_as_date(self) -> None:
        """BEGIN_DT must be a plain string, not a date object."""
        line = make_ref_line(begin_dt="06231980") + "\n"
        record = parse_reference_line(line, 1)
        assert isinstance(record, ReferenceRecord)
        assert isinstance(record.begin_dt, str)

    def test_end_dt_not_parsed_as_date(self) -> None:
        """END_DT must be a plain string, not a date object."""
        line = make_ref_line(end_dt="12312049") + "\n"
        record = parse_reference_line(line, 1)
        assert isinstance(record, ReferenceRecord)
        assert isinstance(record.end_dt, str)

    def test_line_number_in_parse_error(self) -> None:
        short = "047\n"
        result = parse_reference_line(short, 42)
        assert isinstance(result, ReferenceParseError)
        assert result.line_number == 42

    def test_crlf_line_ending_handled(self) -> None:
        line = make_ref_line() + "\r\n"
        result = parse_reference_line(line, 1)
        assert isinstance(result, ReferenceRecord)

    def test_no_trailing_newline_handled(self) -> None:
        line = make_ref_line()   # no newline
        result = parse_reference_line(line, 1)
        assert isinstance(result, ReferenceRecord)


# ---------------------------------------------------------------------------
# TestReferenceRecordFields — field-level correctness
# ---------------------------------------------------------------------------


class TestReferenceRecordFields:
    """Field extraction covers all six documented positions."""

    def test_all_fields_present(self) -> None:
        line = make_ref_line(
            tble_code="047",
            docu_type="054",
            err_mess_no="019",
            err_mess_des="DUPLICATE DOCUMENTS",
            begin_dt="05011981",
            end_dt="12312049",
        )
        record = parse_reference_line(line + "\n", 1)
        assert isinstance(record, ReferenceRecord)
        assert record.tble_code == "047"
        assert record.docu_type == "054"
        assert record.err_mess_no == "019"
        assert record.err_mess_des == "DUPLICATE DOCUMENTS"
        assert record.begin_dt == "05011981"
        assert record.end_dt == "12312049"

    def test_err_mess_des_max_length(self) -> None:
        """ERR_MESS_DES field is 50 characters; trailing spaces are trimmed."""
        long_desc = "A" * 50
        line = make_ref_line(err_mess_des=long_desc)
        record = parse_reference_line(line + "\n", 1)
        assert isinstance(record, ReferenceRecord)
        assert record.err_mess_des == "A" * 50

    def test_err_mess_des_trailing_spaces_stripped(self) -> None:
        line = make_ref_line(err_mess_des="SHORT DESC")
        record = parse_reference_line(line + "\n", 1)
        assert isinstance(record, ReferenceRecord)
        assert record.err_mess_des == "SHORT DESC"
        assert not record.err_mess_des.endswith(" ")


# ---------------------------------------------------------------------------
# TestReferenceTableLookup — lookup service
# ---------------------------------------------------------------------------


class TestReferenceTableLookup:
    """Tests for ReferenceTable.lookup()."""

    def _table_from_records(
        self,
        records: list[ReferenceRecord],
    ) -> ReferenceTable:
        return ReferenceTable(records, [], [])

    def test_lookup_exact_match(self) -> None:
        record = ReferenceRecord(
            tble_code="047",
            docu_type="030",
            err_mess_no="001",
            err_mess_des="OUT OF BALANCE",
            begin_dt="06231980",
            end_dt="12312049",
        )
        table = self._table_from_records([record])
        assert table.lookup("030", "001") == "OUT OF BALANCE"

    def test_lookup_missing_key_returns_sentinel(self) -> None:
        table = self._table_from_records([])
        assert table.lookup("999", "999") == NO_REFERENCE_AVAILABLE

    def test_lookup_wrong_docu_type_returns_sentinel(self) -> None:
        record = ReferenceRecord(
            tble_code="047",
            docu_type="030",
            err_mess_no="001",
            err_mess_des="OUT OF BALANCE",
            begin_dt="06231980",
            end_dt="12312049",
        )
        table = self._table_from_records([record])
        assert table.lookup("054", "001") == NO_REFERENCE_AVAILABLE

    def test_lookup_wrong_err_mess_no_returns_sentinel(self) -> None:
        record = ReferenceRecord(
            tble_code="047",
            docu_type="030",
            err_mess_no="001",
            err_mess_des="OUT OF BALANCE",
            begin_dt="06231980",
            end_dt="12312049",
        )
        table = self._table_from_records([record])
        assert table.lookup("030", "002") == NO_REFERENCE_AVAILABLE

    def test_lookup_multiple_records_correct_one_returned(self) -> None:
        records = [
            ReferenceRecord(
                "047", "030", "001", "OUT OF BALANCE", "06231980", "12312049"
            ),
            ReferenceRecord(
                "047", "054", "019", "DUPLICATE DOCUMENTS", "05011981", "12312049"
            ),
            ReferenceRecord(
                "047", "030", "002", "FORCE RETAINED IN SUSPENSE",
                "06231980", "12312049"
            ),
        ]
        table = self._table_from_records(records)
        assert table.lookup("054", "019") == "DUPLICATE DOCUMENTS"
        assert table.lookup("030", "002") == "FORCE RETAINED IN SUSPENSE"

    def test_no_reference_available_constant_value(self) -> None:
        assert NO_REFERENCE_AVAILABLE == "No approved reference available"

    def test_sentinel_is_string(self) -> None:
        table = self._table_from_records([])
        result = table.lookup("000", "000")
        assert isinstance(result, str)
        assert result == NO_REFERENCE_AVAILABLE

    def test_empty_table_always_returns_sentinel(self) -> None:
        table = self._table_from_records([])
        assert table.lookup("047", "030") == NO_REFERENCE_AVAILABLE


# ---------------------------------------------------------------------------
# TestDuplicateKeyHandling — duplicate detection and retention
# ---------------------------------------------------------------------------


class TestDuplicateKeyHandling:
    """First occurrence is retained; subsequent duplicates become validation errors."""

    def _build_table_from_lines(
        self, lines: list[str], tmp_path: Path
    ) -> ReferenceTable:
        ref_file = tmp_path / "synthetic_ref.txt"
        ref_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return load_reference(ref_file)

    def test_duplicate_key_retains_first(self, tmp_path: Path) -> None:
        first = make_ref_line(
            docu_type="030", err_mess_no="001", err_mess_des="FIRST DESCRIPTION"
        )
        second = make_ref_line(
            docu_type="030", err_mess_no="001", err_mess_des="SECOND DESCRIPTION"
        )
        table = self._build_table_from_lines([first, second], tmp_path)
        assert table.lookup("030", "001") == "FIRST DESCRIPTION"

    def test_duplicate_key_recorded_as_validation_error(self, tmp_path: Path) -> None:
        first = make_ref_line(
            docu_type="030", err_mess_no="001", err_mess_des="FIRST"
        )
        second = make_ref_line(
            docu_type="030", err_mess_no="001", err_mess_des="SECOND"
        )
        table = self._build_table_from_lines([first, second], tmp_path)
        assert len(table.validation_errors) == 1
        err = table.validation_errors[0]
        assert isinstance(err, ReferenceValidationError)
        assert err.docu_type == "030"
        assert err.err_mess_no == "001"
        assert err.line_number == 2

    def test_no_duplicate_produces_no_validation_errors(self, tmp_path: Path) -> None:
        line_a = make_ref_line(docu_type="030", err_mess_no="001")
        line_b = make_ref_line(docu_type="030", err_mess_no="002")
        table = self._build_table_from_lines([line_a, line_b], tmp_path)
        assert table.validation_errors == []

    def test_triple_duplicate_two_validation_errors(self, tmp_path: Path) -> None:
        line = make_ref_line(docu_type="030", err_mess_no="001")
        table = self._build_table_from_lines([line, line, line], tmp_path)
        assert len(table.validation_errors) == 2
        assert table.lookup("030", "001") == make_ref_line(
            docu_type="030", err_mess_no="001"
        )[9:59].strip()


# ---------------------------------------------------------------------------
# TestMalformedLineHandling — parse errors do not stop processing
# ---------------------------------------------------------------------------


class TestMalformedLineHandling:
    """Malformed lines are recorded and processing continues."""

    def _build_table_from_lines(
        self, lines: list[str], tmp_path: Path
    ) -> ReferenceTable:
        ref_file = tmp_path / "synthetic_ref.txt"
        ref_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return load_reference(ref_file)

    def test_short_line_recorded_as_parse_error(self, tmp_path: Path) -> None:
        short = "047030001TOOSHORT"
        valid = make_ref_line(docu_type="030", err_mess_no="002")
        table = self._build_table_from_lines([short, valid], tmp_path)
        assert len(table.parse_errors) == 1
        assert table.parse_errors[0].line_number == 1

    def test_processing_continues_after_malformed_line(self, tmp_path: Path) -> None:
        short = "047030001TOOSHORT"
        valid = make_ref_line(
            docu_type="030", err_mess_no="002", err_mess_des="GOOD RECORD"
        )
        table = self._build_table_from_lines([short, valid], tmp_path)
        assert table.lookup("030", "002") == "GOOD RECORD"

    def test_long_line_recorded_as_parse_error(self, tmp_path: Path) -> None:
        long_line = make_ref_line() + "EXTRAEXTRA"
        valid = make_ref_line(docu_type="030", err_mess_no="003")
        table = self._build_table_from_lines([long_line, valid], tmp_path)
        assert len(table.parse_errors) == 1

    def test_blank_lines_silently_skipped(self, tmp_path: Path) -> None:
        valid = make_ref_line(docu_type="030", err_mess_no="001")
        table = self._build_table_from_lines(["", valid, "   ", valid[:0]], tmp_path)
        assert table.parse_errors == []
        assert table.lookup("030", "001") == make_ref_line(
            docu_type="030", err_mess_no="001"
        )[9:59].strip()

    def test_multiple_malformed_lines_all_recorded(self, tmp_path: Path) -> None:
        lines = [
            "SHORT",
            make_ref_line(),
            "ALSOSHORT",
            make_ref_line(docu_type="054", err_mess_no="019"),
        ]
        table = self._build_table_from_lines(lines, tmp_path)
        assert len(table.parse_errors) == 2
        assert table.parse_errors[0].line_number == 1
        assert table.parse_errors[1].line_number == 3


# ---------------------------------------------------------------------------
# TestLoadReference — file-level loading
# ---------------------------------------------------------------------------


class TestLoadReference:
    """Tests for load_reference() using synthetic tmp_path files."""

    def test_empty_file_returns_empty_table(self, tmp_path: Path) -> None:
        ref_file = tmp_path / "empty.txt"
        ref_file.write_text("", encoding="utf-8")
        table = load_reference(ref_file)
        assert table.lookup("030", "001") == NO_REFERENCE_AVAILABLE
        assert table.parse_errors == []
        assert table.validation_errors == []

    def test_single_valid_record(self, tmp_path: Path) -> None:
        line = make_ref_line(
            tble_code="047",
            docu_type="030",
            err_mess_no="001",
            err_mess_des="OUT OF BALANCE",
            begin_dt="06231980",
            end_dt="12312049",
        )
        ref_file = tmp_path / "ref.txt"
        ref_file.write_text(line + "\n", encoding="utf-8")
        table = load_reference(ref_file)
        assert table.lookup("030", "001") == "OUT OF BALANCE"
        assert table.parse_errors == []

    def test_multiple_valid_records(self, tmp_path: Path) -> None:
        lines = [
            make_ref_line(
                docu_type="030", err_mess_no="001", err_mess_des="OUT OF BALANCE"
            ),
            make_ref_line(
                docu_type="030", err_mess_no="002", err_mess_des="FORCE RETAINED"
            ),
            make_ref_line(
                docu_type="054", err_mess_no="019", err_mess_des="DUPLICATE DOCS"
            ),
        ]
        ref_file = tmp_path / "ref.txt"
        ref_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        table = load_reference(ref_file)
        assert table.lookup("030", "001") == "OUT OF BALANCE"
        assert table.lookup("030", "002") == "FORCE RETAINED"
        assert table.lookup("054", "019") == "DUPLICATE DOCS"

    def test_tble_code_preserved_in_record(self, tmp_path: Path) -> None:
        """TBLE_CODE is preserved even though it is not part of the lookup key."""
        line = make_ref_line(tble_code="047", docu_type="030", err_mess_no="001")
        ref_file = tmp_path / "ref.txt"
        ref_file.write_text(line + "\n", encoding="utf-8")
        table = load_reference(ref_file)
        # Retrieve the internal record to verify tble_code is stored
        record = table._table.get(("030", "001"))
        assert record is not None
        assert record.tble_code == "047"

    def test_string_path_accepted(self, tmp_path: Path) -> None:
        line = make_ref_line()
        ref_file = tmp_path / "ref.txt"
        ref_file.write_text(line + "\n", encoding="utf-8")
        table = load_reference(str(ref_file))
        assert table.lookup("030", "001") is not None

    def test_pathlib_path_accepted(self, tmp_path: Path) -> None:
        line = make_ref_line()
        ref_file = tmp_path / "ref.txt"
        ref_file.write_text(line + "\n", encoding="utf-8")
        table = load_reference(ref_file)
        assert table.lookup("030", "001") is not None


# ---------------------------------------------------------------------------
# TestDocuTypeFallback — 063 → 060 fallback mapping
# ---------------------------------------------------------------------------


class TestDocuTypeFallback:
    """DOCU_TYPE_FALLBACK: when primary (docu_type, sinq_error) misses,
    lookup() retries with the mapped fallback DOCU_TYPE before returning
    the sentinel.  All tests use synthetic in-memory reference lines only.
    """

    def _table_with(self, lines: list[str]) -> ReferenceTable:
        """Build a ReferenceTable directly from synthetic lines."""
        from example_server.reference import ReferenceRecord, parse_reference_line

        records: list[ReferenceRecord] = []
        for i, line in enumerate(lines, start=1):
            result = parse_reference_line(line, i)
            if isinstance(result, ReferenceRecord):
                records.append(result)
        return ReferenceTable(records, [], [])

    def test_063_falls_back_to_060_when_063_has_no_entry(self) -> None:
        """lookup('063', '005') must return the '060' description when the
        reference contains a ('060', '005') entry but no ('063', '005') entry.

        This covers the real-world case where DOCU_TYPE 063 shares low-numbered
        SINQ error codes with DOCU_TYPE 060 in the reference file.
        """
        # Reference has 060/005 but NOT 063/005.
        line_060 = make_ref_line(docu_type="060", err_mess_no="005",
                                 err_mess_des="SSNO NOT FOUND ON DATA BASE")
        table = self._table_with([line_060])

        result = table.lookup("063", "005")
        assert result == "SSNO NOT FOUND ON DATA BASE", (
            f"Expected fallback description from 060/005, got {result!r}"
        )

    def test_063_primary_takes_precedence_over_fallback(self) -> None:
        """When the reference contains a ('063', '113') entry, lookup() must
        return that description — the 060 fallback must not override it.
        """
        line_063 = make_ref_line(docu_type="063", err_mess_no="113",
                                 err_mess_des="NOAC NOT COMPATIBLE WITH WORK SCHEDULE")
        line_060 = make_ref_line(docu_type="060", err_mess_no="113",
                                 err_mess_des="NOA NOT COMPATIBLE WITH WORK SCHEDULE")
        table = self._table_with([line_063, line_060])

        result = table.lookup("063", "113")
        assert result == "NOAC NOT COMPATIBLE WITH WORK SCHEDULE", (
            f"Primary 063/113 should win over fallback 060/113, got {result!r}"
        )

    def test_non_fallback_docu_type_returns_sentinel_on_miss(self) -> None:
        """A DOCU_TYPE that has no entry in DOCU_TYPE_FALLBACK must still
        return NO_REFERENCE_AVAILABLE when no direct match is found.
        No unexpected fallback should fire.
        """
        line_060 = make_ref_line(docu_type="060", err_mess_no="005",
                                 err_mess_des="SSNO NOT FOUND ON DATA BASE")
        table = self._table_with([line_060])

        # 030 has no fallback mapping; 030/005 is not in the table.
        result = table.lookup("030", "005")
        assert result == NO_REFERENCE_AVAILABLE, (
            f"Expected sentinel for 030/005 (no fallback for 030), got {result!r}"
        )
