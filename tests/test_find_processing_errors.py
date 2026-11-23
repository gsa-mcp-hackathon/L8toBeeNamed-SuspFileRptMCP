"""Unit and integration tests for the find_processing_errors MCP tool.

All test data is built from synthetic 200-character strings written to
temporary files via pytest's tmp_path fixture. No contents of
AI_HACK_TEST_ONE.DAT are used or referenced here.

The tool is tested via FastMCP.call_tool(), which exercises the full
registered function including argument coercion. Settings are monkeypatched
so each test controls its own temporary data file.
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from example_server.parser import RECORD_LENGTH
from example_server.tools import find_processing_errors as fpe_module

# ---------------------------------------------------------------------------
# Synthetic record builder (same field positions as other test modules)
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
    """Build a synthetic 200-character record string."""
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


def _make_ref_line(
    docu_type: str = "030",
    err_mess_no: str = "001",
    err_mess_des: str = "SYNTHETIC DESCRIPTION",
) -> str:
    """Build a synthetic 75-character reference line."""
    line = (
        "047"
        + docu_type[:3].ljust(3)
        + err_mess_no[:3].ljust(3)
        + err_mess_des[:50].ljust(50)
        + "06231980"
        + "12312049"
    )
    assert len(line) == 75
    return line


# ---------------------------------------------------------------------------
# Shared fixture: a FastMCP instance with only this tool registered
# ---------------------------------------------------------------------------


@pytest.fixture()
def tool_mcp() -> FastMCP:
    """A minimal FastMCP instance with find_processing_errors registered."""
    m = FastMCP("test-fpe")
    fpe_module.register(m)
    return m


# ---------------------------------------------------------------------------
# Helper: call the tool via FastMCP.call_tool()
# ---------------------------------------------------------------------------


async def _call(
    tool_mcp: FastMCP,
    monkeypatch,
    tmp_file: str,
    ref_file: str | None = None,
    **kwargs,
) -> dict:
    """Call the tool, pointing settings at synthetic tmp files.

    Uses FastMCP.call_tool() which exercises the full registered function
    including argument coercion. Returns structured_content directly.

    ref_file: path to a synthetic reference file. When None, an empty
    synthetic reference file is used so tests that do not care about
    descriptions still work without touching the real reference file.
    """
    import example_server.tools.find_processing_errors as _fpe

    monkeypatch.setattr(
        _fpe.settings, "dat_file_path", tmp_file, raising=True
    )
    if ref_file is not None:
        monkeypatch.setattr(
            _fpe.settings, "reference_file_path", ref_file, raising=True
        )
    result = await tool_mcp.call_tool("find_processing_errors", kwargs)
    return result.structured_content


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    @pytest.mark.asyncio
    async def test_tool_is_discoverable(self, tool_mcp: FastMCP):
        tools = await tool_mcp.list_tools()
        names = {t.name for t in tools}
        assert "find_processing_errors" in names

    @pytest.mark.asyncio
    async def test_tool_name_is_exact(self, tool_mcp: FastMCP):
        tools = await tool_mcp.list_tools()
        names = [t.name for t in tools]
        assert names.count("find_processing_errors") == 1


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


class TestOutputShape:
    @pytest.mark.asyncio
    async def test_top_level_keys(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text(_make_record() + "\n", encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert set(result.keys()) == {"filters_applied", "summary", "results"}

    @pytest.mark.asyncio
    async def test_filters_applied_keys(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text(_make_record() + "\n", encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert set(result["filters_applied"].keys()) == {
            "gvt_sub_agency",
            "company",
            "docu_type",
            "source",
            "sinq_error",
            "has_sinq_error",
        }

    @pytest.mark.asyncio
    async def test_summary_keys(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text(_make_record() + "\n", encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert set(result["summary"].keys()) == {
            "total_valid_records",
            "parse_error_count",
            "matched_record_count",
            "returned_record_count",
            "sinq_error_count",
            "has_more",
            "next_offset",
        }

    @pytest.mark.asyncio
    async def test_result_item_has_exactly_eight_keys(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text(_make_record() + "\n", encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert len(result["results"]) == 1
        assert set(result["results"][0].keys()) == {
            "line_number",
            "gvt_sub_agency",
            "company",
            "docu_type",
            "source",
            "sinq_error",
            "ref_description",
            "has_sinq_error",
        }

    @pytest.mark.asyncio
    async def test_result_item_has_no_raw_indicator_fields(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """gwebess_raw, powrdocs_raw, and sinq_message must never appear."""
        f = tmp_path / "test.dat"
        f.write_text(_make_record() + "\n", encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        for item in result["results"]:
            assert "gwebess_raw" not in item
            assert "powrdocs_raw" not in item
            assert "sinq_message" not in item

    @pytest.mark.asyncio
    async def test_filters_applied_echoes_supplied_values(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text(_make_record() + "\n", encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f),
            gvt_sub_agency="12", company="34",
        )
        fa = result["filters_applied"]
        assert fa["gvt_sub_agency"] == "12"
        assert fa["company"] == "34"
        assert fa["docu_type"] is None
        assert fa["source"] is None
        assert fa["sinq_error"] is None
        assert fa["has_sinq_error"] is None


# ---------------------------------------------------------------------------
# No-filter behaviour
# ---------------------------------------------------------------------------


class TestNoFilter:
    @pytest.mark.asyncio
    async def test_returns_all_valid_records_when_no_filters(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = (
            _make_record(gvt_sub_agency="12") + "\n"
            + _make_record(gvt_sub_agency="34") + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert result["summary"]["matched_record_count"] == 2
        assert result["summary"]["returned_record_count"] == 2
        assert len(result["results"]) == 2

    @pytest.mark.asyncio
    async def test_parse_errors_are_counted_not_returned(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = _make_record() + "\n" + "TOOSHORT\n"
        f.write_text(content, encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert result["summary"]["total_valid_records"] == 1
        assert result["summary"]["parse_error_count"] == 1
        assert result["summary"]["matched_record_count"] == 1
        assert len(result["results"]) == 1

    @pytest.mark.asyncio
    async def test_total_valid_records_reflects_whole_file(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """total_valid_records counts the whole file, not just matched."""
        f = tmp_path / "test.dat"
        content = (
            _make_record(gvt_sub_agency="12") + "\n"
            + _make_record(gvt_sub_agency="99") + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), gvt_sub_agency="12"
        )
        assert result["summary"]["total_valid_records"] == 2
        assert result["summary"]["matched_record_count"] == 1


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestFiltering:
    @pytest.mark.asyncio
    async def test_filter_by_gvt_sub_agency(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = (
            _make_record(gvt_sub_agency="12") + "\n"
            + _make_record(gvt_sub_agency="99") + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), gvt_sub_agency="12"
        )
        assert result["summary"]["matched_record_count"] == 1
        assert result["results"][0]["gvt_sub_agency"] == "12"

    @pytest.mark.asyncio
    async def test_filter_by_company(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = (
            _make_record(company="AB") + "\n"
            + _make_record(company="ZZ") + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), company="AB"
        )
        assert result["summary"]["matched_record_count"] == 1
        assert result["results"][0]["company"] == "AB"

    @pytest.mark.asyncio
    async def test_filter_by_source_empowhr(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = (
            _make_record(powrdocs="POWRDOCS") + "\n"
            + _make_record() + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), source="EmpowHR"
        )
        assert result["summary"]["matched_record_count"] == 1
        assert result["results"][0]["source"] == "EmpowHR"

    @pytest.mark.asyncio
    async def test_filter_by_source_employee_personal_page(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = (
            _make_record(gwebess="GWEBESS") + "\n"
            + _make_record() + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f),
            source="Employee Personal Page",
        )
        assert result["summary"]["matched_record_count"] == 1
        assert result["results"][0]["source"] == "Employee Personal Page"

    @pytest.mark.asyncio
    async def test_filter_by_sinq_error_code(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = (
            _make_record(sinq_error="E01") + "\n"
            + _make_record(sinq_error="E02") + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), sinq_error="E01"
        )
        assert result["summary"]["matched_record_count"] == 1
        assert result["results"][0]["sinq_error"] == "E01"

    @pytest.mark.asyncio
    async def test_filter_by_has_sinq_error_true(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = (
            _make_record(sinq_error="E01") + "\n"
            + _make_record() + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), has_sinq_error=True
        )
        assert result["summary"]["matched_record_count"] == 1
        assert result["results"][0]["has_sinq_error"] is True

    @pytest.mark.asyncio
    async def test_filter_by_has_sinq_error_false(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = (
            _make_record(sinq_error="E01") + "\n"
            + _make_record() + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), has_sinq_error=False
        )
        assert result["summary"]["matched_record_count"] == 1
        assert result["results"][0]["has_sinq_error"] is False

    @pytest.mark.asyncio
    async def test_combined_and_filters(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = (
            _make_record(gvt_sub_agency="12", powrdocs="POWRDOCS") + "\n"
            + _make_record(gvt_sub_agency="12") + "\n"
            + _make_record(gvt_sub_agency="99", powrdocs="POWRDOCS") + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f),
            gvt_sub_agency="12", source="EmpowHR",
        )
        assert result["summary"]["matched_record_count"] == 1

    @pytest.mark.asyncio
    async def test_filter_case_insensitive_source(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text(_make_record(powrdocs="POWRDOCS") + "\n", encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), source="empowhr"
        )
        assert result["summary"]["matched_record_count"] == 1

    @pytest.mark.asyncio
    async def test_no_match_returns_empty_results(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text(_make_record(gvt_sub_agency="12") + "\n", encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), gvt_sub_agency="99"
        )
        assert result["summary"]["matched_record_count"] == 0
        assert result["summary"]["returned_record_count"] == 0
        assert result["results"] == []


# ---------------------------------------------------------------------------
# SINQ error count in summary
# ---------------------------------------------------------------------------


class TestSinqErrorCount:
    @pytest.mark.asyncio
    async def test_sinq_error_count_reflects_matched_set(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """sinq_error_count counts matched records, not the whole file."""
        f = tmp_path / "test.dat"
        content = (
            _make_record(gvt_sub_agency="12", sinq_error="E01") + "\n"
            + _make_record(gvt_sub_agency="12") + "\n"
            + _make_record(gvt_sub_agency="99", sinq_error="E02") + "\n"
        )
        f.write_text(content, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f), gvt_sub_agency="12"
        )
        # Only the two agency-12 records are matched; only one has SINQ error.
        assert result["summary"]["matched_record_count"] == 2
        assert result["summary"]["sinq_error_count"] == 1

    @pytest.mark.asyncio
    async def test_sinq_error_count_zero_when_none_matched(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text(_make_record() + "\n", encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert result["summary"]["sinq_error_count"] == 0


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    @pytest.mark.asyncio
    async def test_first_page_has_more_when_records_exceed_limit(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        lines = "".join(
            _make_record(gvt_sub_agency=str(i).zfill(2)) + "\n"
            for i in range(5)
        )
        f.write_text(lines, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f),
            pagination={"limit": 3, "offset": 0},
        )
        assert result["summary"]["matched_record_count"] == 5
        assert result["summary"]["returned_record_count"] == 3
        assert len(result["results"]) == 3
        assert result["summary"]["has_more"] is True
        assert result["summary"]["next_offset"] == 3

    @pytest.mark.asyncio
    async def test_second_page_returns_remaining_records(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        lines = "".join(
            _make_record(gvt_sub_agency=str(i).zfill(2)) + "\n"
            for i in range(5)
        )
        f.write_text(lines, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f),
            pagination={"limit": 3, "offset": 3},
        )
        assert result["summary"]["returned_record_count"] == 2
        assert len(result["results"]) == 2
        assert result["summary"]["has_more"] is False
        assert result["summary"]["next_offset"] is None

    @pytest.mark.asyncio
    async def test_offset_past_end_returns_empty_results(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text(_make_record() + "\n", encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f),
            pagination={"limit": 10, "offset": 100},
        )
        assert result["summary"]["returned_record_count"] == 0
        assert result["results"] == []
        assert result["summary"]["has_more"] is False

    @pytest.mark.asyncio
    async def test_matched_record_count_is_before_pagination(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """matched_record_count must reflect the full filtered set."""
        f = tmp_path / "test.dat"
        lines = "".join(_make_record() + "\n" for _ in range(10))
        f.write_text(lines, encoding="utf-8")
        result = await _call(
            tool_mcp, monkeypatch, str(f),
            pagination={"limit": 3, "offset": 0},
        )
        assert result["summary"]["matched_record_count"] == 10
        assert result["summary"]["returned_record_count"] == 3

    @pytest.mark.asyncio
    async def test_no_pagination_uses_default_limit(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """When pagination is omitted, default limit (50) is used."""
        f = tmp_path / "test.dat"
        # Write 60 records — more than the default limit of 50.
        lines = "".join(_make_record() + "\n" for _ in range(60))
        f.write_text(lines, encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert result["summary"]["matched_record_count"] == 60
        assert result["summary"]["returned_record_count"] == 50
        assert result["summary"]["has_more"] is True


# ---------------------------------------------------------------------------
# Empty file and edge cases
# ---------------------------------------------------------------------------


class TestEmptyAndEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_file_all_counts_zero(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text("", encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        s = result["summary"]
        assert s["total_valid_records"] == 0
        assert s["parse_error_count"] == 0
        assert s["matched_record_count"] == 0
        assert s["returned_record_count"] == 0
        assert s["sinq_error_count"] == 0
        assert s["has_more"] is False
        assert s["next_offset"] is None
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_file_with_only_parse_errors(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        f.write_text("TOOSHORT\n" + "ALSOTOOSHORT\n", encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        s = result["summary"]
        assert s["total_valid_records"] == 0
        assert s["parse_error_count"] == 2
        assert s["matched_record_count"] == 0
        assert result["results"] == []

    @pytest.mark.asyncio
    async def test_blank_lines_are_skipped_not_counted(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        f = tmp_path / "test.dat"
        content = "\n" + _make_record() + "\n" + "\n"
        f.write_text(content, encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert result["summary"]["total_valid_records"] == 1
        assert result["summary"]["parse_error_count"] == 0

    @pytest.mark.asyncio
    async def test_150_char_line_is_parse_error_not_result(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """A 150-character line (like line 1288) must be a parse error."""
        f = tmp_path / "test.dat"
        f.write_text("X" * 150 + "\n", encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(f))
        assert result["summary"]["parse_error_count"] == 1
        assert result["summary"]["total_valid_records"] == 0
        assert result["results"] == []


# ---------------------------------------------------------------------------
# Missing or unreadable file
# ---------------------------------------------------------------------------


class TestMissingFile:
    @pytest.mark.asyncio
    async def test_missing_file_returns_error_dict(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        missing = str(tmp_path / "does_not_exist.dat")
        result = await _call(tool_mcp, monkeypatch, missing)
        assert "error" in result
        assert "filters_applied" not in result
        assert "results" not in result

    @pytest.mark.asyncio
    async def test_error_message_contains_filename_not_path(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """The error must name the file but not expose its full directory."""
        missing = str(tmp_path / "does_not_exist.dat")
        result = await _call(tool_mcp, monkeypatch, missing)
        assert "does_not_exist.dat" in result["error"]
        # The full tmp_path directory must not appear in the error message.
        assert str(tmp_path) not in result["error"]

    @pytest.mark.asyncio
    async def test_error_does_not_expose_stack_trace(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        missing = str(tmp_path / "does_not_exist.dat")
        result = await _call(tool_mcp, monkeypatch, missing)
        assert "Traceback" not in result["error"]
        assert "File " not in result["error"]


# ---------------------------------------------------------------------------
# DOCU_TYPE filter and reference description
# ---------------------------------------------------------------------------


class TestDocuTypeAndReference:
    @pytest.mark.asyncio
    async def test_filter_by_docu_type(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        dat = tmp_path / "test.dat"
        content = (
            _make_record(docu_type="030", sinq_error="001") + "\n"
            + _make_record(docu_type="054", sinq_error="019") + "\n"
        )
        dat.write_text(content, encoding="utf-8")
        result = await _call(tool_mcp, monkeypatch, str(dat), docu_type="030")
        assert result["summary"]["matched_record_count"] == 1
        assert result["results"][0]["docu_type"] == "030"

    @pytest.mark.asyncio
    async def test_docu_type_in_result_item(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        dat = tmp_path / "test.dat"
        dat.write_text(
            _make_record(docu_type="054") + "\n", encoding="utf-8"
        )
        result = await _call(tool_mcp, monkeypatch, str(dat))
        assert "docu_type" in result["results"][0]
        assert result["results"][0]["docu_type"] == "054"

    @pytest.mark.asyncio
    async def test_ref_description_matching_lookup(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """A matching (DOCU_TYPE, SINQ_ERROR) pair returns the approved description."""
        dat = tmp_path / "test.dat"
        dat.write_text(
            _make_record(docu_type="030", sinq_error="001") + "\n",
            encoding="utf-8",
        )
        ref = tmp_path / "ref.txt"
        ref.write_text(
            _make_ref_line(docu_type="030", err_mess_no="001",
                           err_mess_des="OUT OF BALANCE") + "\n",
            encoding="utf-8",
        )
        result = await _call(
            tool_mcp, monkeypatch, str(dat), ref_file=str(ref)
        )
        assert result["results"][0]["ref_description"] == "OUT OF BALANCE"

    @pytest.mark.asyncio
    async def test_ref_description_no_match_returns_sentinel(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """When no reference entry matches, sentinel string is returned."""
        dat = tmp_path / "test.dat"
        dat.write_text(
            _make_record(docu_type="999", sinq_error="999") + "\n",
            encoding="utf-8",
        )
        ref = tmp_path / "ref.txt"
        ref.write_text(
            _make_ref_line(docu_type="030", err_mess_no="001") + "\n",
            encoding="utf-8",
        )
        result = await _call(
            tool_mcp, monkeypatch, str(dat), ref_file=str(ref)
        )
        assert result["results"][0]["ref_description"] == (
            "No approved reference available"
        )

    @pytest.mark.asyncio
    async def test_missing_reference_file_returns_safe_error(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """A missing reference file returns a safe error without path or traceback."""
        dat = tmp_path / "test.dat"
        dat.write_text(_make_record() + "\n", encoding="utf-8")
        missing_ref = str(tmp_path / "no_ref_here.txt")
        result = await _call(
            tool_mcp, monkeypatch, str(dat), ref_file=missing_ref
        )
        assert "error" in result
        assert "no_ref_here.txt" in result["error"]
        assert str(tmp_path) not in result["error"]
        assert "Traceback" not in result["error"]
        assert "results" not in result

    @pytest.mark.asyncio
    async def test_sinq_message_absent_from_results(
        self, tool_mcp: FastMCP, monkeypatch, tmp_path
    ):
        """sinq_message must never appear in MCP output under any key."""
        dat = tmp_path / "test.dat"
        dat.write_text(
            _make_record(sinq_error="001",
                         sinq_message="SECRETMSG" + " " * 40) + "\n",
            encoding="utf-8",
        )
        result = await _call(tool_mcp, monkeypatch, str(dat))
        for item in result["results"]:
            assert "sinq_message" not in item
            # The raw message content must not appear in any field value
            for v in item.values():
                assert "SECRETMSG" not in str(v)
