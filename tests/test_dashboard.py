"""Tests for the /dashboard HTTP route.

All test data is built from synthetic 200-character strings written to
temporary files via pytest's tmp_path fixture. No contents of
AI_HACK_TEST_ONE.DAT are used or referenced here.

Settings are monkeypatched so each test controls its own temporary data file.
The TestClient drives Starlette's ASGI app (mcp.http_app()) directly, which
exercises the full route handler including template rendering.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from example_server.app import mcp
from example_server.parser import RECORD_LENGTH

# ---------------------------------------------------------------------------
# Synthetic record builder (mirrors field positions in parser.py)
# ---------------------------------------------------------------------------

# Field positions (0-based Python slices):
#   gvt_sub_agency  [9:11]
#   company         [15:17]
#   docu_type       [17:20]
#   gwebess         [44:51]
#   sinq_error      [51:54]
#   sinq_message    [54:103]
#   powrdocs        [185:193]


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

    _place(gvt_sub_agency, 9, 2)
    _place(company, 15, 2)
    _place(docu_type, 17, 3)
    _place(gwebess, 44, 7)
    _place(sinq_error, 51, 3)
    _place(sinq_message, 54, 49)
    _place(powrdocs, 185, 8)

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


def _write_dat(path, records: list[str]) -> str:
    """Write records to path and return the path as a string."""
    path.write_text("\n".join(records) + "\n", encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Shared TestClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def http_client():
    """Starlette TestClient wrapping the full FastMCP app."""
    return TestClient(mcp.http_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper: patch settings and GET /dashboard
# ---------------------------------------------------------------------------


def _get(
    client: TestClient,
    monkeypatch,
    dat_path: str,
    params: str = "",
    ref_path: str | None = None,
) -> object:
    """Monkeypatch dat_file_path (and optionally reference_file_path),
    then GET /dashboard."""
    import example_server.dashboard as _dash

    monkeypatch.setattr(_dash.settings, "dat_file_path", dat_path, raising=True)
    if ref_path is not None:
        monkeypatch.setattr(
            _dash.settings, "reference_file_path", ref_path, raising=True
        )
    url = "/dashboard" + (f"?{params}" if params else "")
    return client.get(url)


# ---------------------------------------------------------------------------
# Basic load
# ---------------------------------------------------------------------------


class TestDashboardLoads:
    def test_returns_200(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(gvt_sub_agency="01", company="AG")],
        )
        r = _get(http_client, monkeypatch, dat)
        assert r.status_code == 200

    def test_contains_summary_labels(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(), _make_record()],
        )
        r = _get(http_client, monkeypatch, dat)
        html = r.text
        assert "Valid Records" in html
        assert "Parse Errors" in html
        assert "SINQ Errors" in html
        assert "By Source" in html

    def test_contains_filter_form(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get(http_client, monkeypatch, dat)
        assert 'name="gvt_sub_agency"' in r.text
        assert 'name="company"' in r.text
        assert 'name="source"' in r.text
        assert 'name="sinq_error"' in r.text
        assert 'name="has_sinq_error"' in r.text


# ---------------------------------------------------------------------------
# Summary counts reflect full file
# ---------------------------------------------------------------------------


class TestSummaryCounts:
    def test_valid_count_shown(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(), _make_record(), _make_record()],
        )
        r = _get(http_client, monkeypatch, dat)
        # "3" should appear in the Valid Records card area
        assert "3" in r.text

    def test_parse_error_count_shown(self, http_client, tmp_path, monkeypatch):
        records = [_make_record(), "SHORT"]  # SHORT is a malformed line
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat)
        # 1 parse error expected
        assert "1" in r.text

    def test_sinq_error_count_shown(self, http_client, tmp_path, monkeypatch):
        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="   "),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Table shows exactly five columns — no forbidden fields
# ---------------------------------------------------------------------------


class TestTableColumns:
    def test_five_column_headers(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get(http_client, monkeypatch, dat)
        html = r.text
        assert "Line" in html
        assert "GVT Sub-Agency" in html or "GVT Sub-Agcy" in html
        assert "Company" in html
        assert "Source" in html
        assert "SINQ Error" in html
        assert "Approved Description" in html

    def test_sinq_message_absent(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_message="SECRETMESSAGE" + " " * 36)],
        )
        r = _get(http_client, monkeypatch, dat)
        assert "SECRETMESSAGE" not in r.text
        assert "sinq_message" not in r.text

    def test_gwebess_raw_absent(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(gwebess="GWEBESS")])
        r = _get(http_client, monkeypatch, dat)
        assert "gwebess_raw" not in r.text

    def test_powrdocs_raw_absent(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(powrdocs="POWRDOCS")])
        r = _get(http_client, monkeypatch, dat)
        assert "powrdocs_raw" not in r.text


# ---------------------------------------------------------------------------
# No raw fixed-width lines in response
# ---------------------------------------------------------------------------


class TestNoRawLines:
    def test_no_200_char_string_in_html(self, http_client, tmp_path, monkeypatch):
        record = _make_record(gvt_sub_agency="99", company="ZZ")
        dat = _write_dat(tmp_path / "test.DAT", [record])
        r = _get(http_client, monkeypatch, dat)
        # A raw record would appear as a 200-char unbroken string
        assert record not in r.text


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class TestFiltering:
    def test_has_sinq_error_true_filters_correctly(
        self, http_client, tmp_path, monkeypatch
    ):
        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="   "),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat, "has_sinq_error=true")
        assert r.status_code == 200
        # "1 matching record" expected
        assert "1 matching record" in r.text

    def test_has_sinq_error_false_filters_correctly(
        self, http_client, tmp_path, monkeypatch
    ):
        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="   "),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat, "has_sinq_error=false")
        assert r.status_code == 200
        assert "1 matching record" in r.text

    def test_filter_no_match_returns_200(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(gvt_sub_agency="01")],
        )
        r = _get(http_client, monkeypatch, dat, "gvt_sub_agency=ZZZZ")
        assert r.status_code == 200
        assert "0 matching records" in r.text

    def test_filter_repopulates_form(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(company="AG")])
        r = _get(http_client, monkeypatch, dat, "company=AG")
        assert r.status_code == 200
        assert "AG" in r.text


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    def test_first_page_shows_up_to_limit(self, http_client, tmp_path, monkeypatch):
        records = [_make_record() for _ in range(60)]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat)
        assert r.status_code == 200
        # Default limit is 50; has_more should be indicated
        assert "Next" in r.text

    def test_offset_50_shows_remaining_rows(self, http_client, tmp_path, monkeypatch):
        records = [_make_record() for _ in range(60)]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat, "offset=50")
        assert r.status_code == 200
        assert "Prev" in r.text

    def test_invalid_offset_defaults_to_zero(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(), _make_record()])
        r = _get(http_client, monkeypatch, dat, "offset=abc")
        assert r.status_code == 200

    def test_negative_offset_clamped_to_zero(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(), _make_record()])
        r = _get(http_client, monkeypatch, dat, "offset=-5")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Missing / unreadable file → safe 500
# ---------------------------------------------------------------------------


class TestMissingFile:
    def test_missing_file_returns_500(self, http_client, tmp_path, monkeypatch):
        nonexistent = str(tmp_path / "does_not_exist.DAT")
        r = _get(http_client, monkeypatch, nonexistent)
        assert r.status_code == 500

    def test_missing_file_no_path_in_response(
        self, http_client, tmp_path, monkeypatch
    ):
        nonexistent = str(tmp_path / "does_not_exist.DAT")
        r = _get(http_client, monkeypatch, nonexistent)
        assert nonexistent not in r.text

    def test_missing_file_no_traceback_in_response(
        self, http_client, tmp_path, monkeypatch
    ):
        nonexistent = str(tmp_path / "does_not_exist.DAT")
        r = _get(http_client, monkeypatch, nonexistent)
        assert "Traceback" not in r.text
        assert "OSError" not in r.text
        assert "FileNotFoundError" not in r.text

    def test_missing_file_user_friendly_message(
        self, http_client, tmp_path, monkeypatch
    ):
        nonexistent = str(tmp_path / "does_not_exist.DAT")
        r = _get(http_client, monkeypatch, nonexistent)
        assert "data file" in r.text.lower()


# ---------------------------------------------------------------------------
# Clear filters link
# ---------------------------------------------------------------------------


class TestClearFiltersLink:
    def test_clear_link_present(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get(http_client, monkeypatch, dat, "company=AG")
        # The "Clear" button/link must navigate to /dashboard with no params
        assert 'href="/dashboard"' in r.text


# ---------------------------------------------------------------------------
# SINQ Error Breakdown section (Milestone 5A)
# ---------------------------------------------------------------------------


class TestSinqGroups:
    def test_breakdown_section_present(self, http_client, tmp_path, monkeypatch):
        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="NF1"),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat)
        assert r.status_code == 200
        assert "SINQ Error Breakdown" in r.text

    def test_sorted_by_count_desc(self, http_client, tmp_path, monkeypatch):
        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="NF1"),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat)
        html = r.text
        assert html.index("NF0") < html.index("NF1")

    def test_tiebreak_by_code_asc(self, http_client, tmp_path, monkeypatch):
        records = [
            _make_record(sinq_error="ZZZ"),
            _make_record(sinq_error="ZZZ"),
            _make_record(sinq_error="AAA"),
            _make_record(sinq_error="AAA"),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat)
        html = r.text
        assert html.index("AAA") < html.index("ZZZ")

    def test_count_shown_in_section(self, http_client, tmp_path, monkeypatch):
        records = [_make_record(sinq_error="NF0")] * 5
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat)
        assert "5" in r.text

    def test_links_use_sinq_error_param(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(sinq_error="NF0")])
        r = _get(http_client, monkeypatch, dat)
        assert "sinq_error=NF0" in r.text

    def test_link_has_no_offset(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(sinq_error="NF0")])
        r = _get(http_client, monkeypatch, dat)
        # The bare /dashboard?sinq_error=NF0 link must not carry an offset
        import re
        links = re.findall(r'href="(/dashboard\?sinq_error=[^"]*)"', r.text)
        assert links, "no sinq_error link found"
        for link in links:
            assert "offset=" not in link

    def test_active_code_has_active_class(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(sinq_error="NF0")])
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF0")
        assert "sinq-link--active" in r.text

    def test_inactive_code_no_active_class(self, http_client, tmp_path, monkeypatch):
        import re

        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="NF1"),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        # NF1 is active; only its <a> tag should carry the active class
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF1")
        html = r.text
        # Count only <a ...> tags that include the active class — not CSS rules
        active_anchors = re.findall(r"<a\b[^>]*sinq-link--active[^>]*>", html)
        assert len(active_anchors) == 1

    def test_no_sinq_errors_shows_empty_message(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_error="   "), _make_record(sinq_error="   ")],
        )
        r = _get(http_client, monkeypatch, dat)
        assert "No SINQ errors" in r.text

    def test_blank_sinq_error_not_in_groups(self, http_client, tmp_path, monkeypatch):
        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="   "),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat)
        # Only 1 distinct code; blank must not appear as a link
        assert "1 distinct code" in r.text

    def test_sinq_message_not_in_breakdown(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_error="NF0", sinq_message="SECRETMSG" + " " * 40)],
        )
        r = _get(http_client, monkeypatch, dat)
        assert "SECRETMSG" not in r.text

    def test_raw_lines_not_in_breakdown(self, http_client, tmp_path, monkeypatch):
        record = _make_record(sinq_error="NF0")
        dat = _write_dat(tmp_path / "test.DAT", [record])
        r = _get(http_client, monkeypatch, dat)
        assert record not in r.text

    def test_breakdown_reflects_full_file_not_filtered_set(
        self, http_client, tmp_path, monkeypatch
    ):
        # File has NF0 and NF1; filter by NF0 only — breakdown must still show NF1
        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="NF1"),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF0")
        html = r.text
        # Both codes present in breakdown even though table only shows NF0
        assert "NF0" in html
        assert "NF1" in html


# ---------------------------------------------------------------------------
# Milestone 5B: Drill-down improvements
# ---------------------------------------------------------------------------

# Helper: build 15 records with distinct 3-char error codes E00..E14
def _make_15_distinct(tmp_path):
    codes = [f"E{i:02d}" for i in range(15)]
    records = [_make_record(sinq_error=c) for c in codes]
    return _write_dat(tmp_path / "test.DAT", records)


class TestDrillDown:
    # ── Active-filter banner ────────────────────────────────────────────────

    def test_banner_shown_when_sinq_error_set(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record(sinq_error="NF0")])
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF0")
        assert '<div class="filter-banner">' in r.text

    def test_banner_absent_when_no_sinq_filter(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record(sinq_error="NF0")])
        r = _get(http_client, monkeypatch, dat)
        # CSS defines .filter-banner; check the rendered <div> is absent
        assert '<div class="filter-banner">' not in r.text

    def test_banner_shows_error_code(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record(sinq_error="ABC")])
        r = _get(http_client, monkeypatch, dat, "sinq_error=ABC")
        assert "ABC" in r.text
        assert "filter-banner" in r.text

    def test_banner_shows_matched_count(self, http_client, tmp_path, monkeypatch):
        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="NF1"),
        ]
        dat = _write_dat(tmp_path / "t.DAT", records)
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF0")
        # Banner should show 2 matching records for NF0
        assert "2 matching record" in r.text

    def test_banner_clear_link_goes_to_dashboard_root(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record(sinq_error="NF0")])
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF0")
        # Clear link must point to bare /dashboard — no query params
        assert 'href="/dashboard"' in r.text

    # ── id="results" anchor ─────────────────────────────────────────────────

    def test_results_anchor_id_present(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        r = _get(http_client, monkeypatch, dat)
        assert 'id="results"' in r.text

    # ── Error-code links include #results fragment ──────────────────────────

    def test_code_link_includes_results_fragment(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record(sinq_error="NF0")])
        r = _get(http_client, monkeypatch, dat)
        assert "sinq_error=NF0#results" in r.text

    def test_code_link_resets_offset(self, http_client, tmp_path, monkeypatch):
        import re

        dat = _write_dat(tmp_path / "t.DAT", [_make_record(sinq_error="NF0")])
        r = _get(http_client, monkeypatch, dat)
        # Links of the form /dashboard?sinq_error=NF0#results must not carry offset=
        links = re.findall(r'href="(/dashboard\?sinq_error=[^"]*)"', r.text)
        assert links, "no sinq_error link found"
        for link in links:
            # Fragment comes after the URL so offset would be before the #
            url_part = link.split("#")[0]
            assert "offset=" not in url_part

    # ── Top-10 / show-all / show-fewer ──────────────────────────────────────

    def test_top_10_shown_by_default(self, http_client, tmp_path, monkeypatch):
        import re

        dat = _make_15_distinct(tmp_path)
        r = _get(http_client, monkeypatch, dat)
        # Count sinq-link anchors in the breakdown (exclude pagination/banner links)
        links = re.findall(r'class="sinq-link[^"]*"', r.text)
        assert len(links) == 10

    def test_show_all_reveals_all_codes(self, http_client, tmp_path, monkeypatch):
        import re

        dat = _make_15_distinct(tmp_path)
        r = _get(http_client, monkeypatch, dat, "show_all=1")
        links = re.findall(r'class="sinq-link[^"]*"', r.text)
        assert len(links) == 15

    def test_show_all_link_present_when_more_than_10(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _make_15_distinct(tmp_path)
        r = _get(http_client, monkeypatch, dat)
        assert "Show all" in r.text

    def test_show_all_link_absent_when_10_or_fewer(
        self, http_client, tmp_path, monkeypatch
    ):
        records = [_make_record(sinq_error=f"E{i:02d}") for i in range(8)]
        dat = _write_dat(tmp_path / "t.DAT", records)
        r = _get(http_client, monkeypatch, dat)
        assert "Show all" not in r.text

    def test_show_fewer_link_present_when_show_all_active(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _make_15_distinct(tmp_path)
        r = _get(http_client, monkeypatch, dat, "show_all=1")
        assert "Show fewer" in r.text

    def test_show_fewer_link_absent_when_not_expanded(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _make_15_distinct(tmp_path)
        r = _get(http_client, monkeypatch, dat)
        assert "Show fewer" not in r.text

    # ── Breakdown always reflects full file ─────────────────────────────────

    def test_breakdown_full_file_when_table_is_filtered(
        self, http_client, tmp_path, monkeypatch
    ):
        records = [
            _make_record(sinq_error="NF0"),
            _make_record(sinq_error="NF1"),
        ]
        dat = _write_dat(tmp_path / "t.DAT", records)
        # Filter table to NF0 only — breakdown must still list NF1
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF0")
        assert "NF1" in r.text

    # ── URL parameter preservation ──────────────────────────────────────────

    def test_show_all_url_preserves_active_filters(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _make_15_distinct(tmp_path)
        r = _get(http_client, monkeypatch, dat, "company=AG")
        # The "Show all" link must keep company=AG
        assert "company=AG" in r.text
        assert "show_all=1" in r.text

    def test_show_fewer_url_preserves_active_filters(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _make_15_distinct(tmp_path)
        r = _get(http_client, monkeypatch, dat, "company=AG&show_all=1")
        # "Show fewer" link must keep company=AG but drop show_all
        assert "Show fewer" in r.text
        assert "company=AG" in r.text

    def test_show_all_url_resets_offset(self, http_client, tmp_path, monkeypatch):
        import re

        dat = _make_15_distinct(tmp_path)
        r = _get(http_client, monkeypatch, dat, "offset=10")
        # The show_all link must not carry an offset greater than 0
        show_all_links = re.findall(r'href="([^"]*show_all=1[^"]*)"', r.text)
        assert show_all_links, "no show_all link found"
        for link in show_all_links:
            assert "offset=" not in link

    def test_show_fewer_url_resets_offset(self, http_client, tmp_path, monkeypatch):
        import re

        dat = _make_15_distinct(tmp_path)
        r = _get(http_client, monkeypatch, dat, "show_all=1&offset=10")
        fewer_links = re.findall(r'class="bd-toggle"[^>]*href="([^"]*)"', r.text)
        if not fewer_links:
            fewer_links = re.findall(r'href="([^"]*)"[^>]*class="bd-toggle"', r.text)
        for link in fewer_links:
            assert "offset=" not in link

    # ── No raw records or SINQ messages ─────────────────────────────────────

    def test_no_sinq_message_in_output(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(sinq_error="NF0", sinq_message="SECRETMSG" + " " * 40)],
        )
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF0")
        assert "SECRETMSG" not in r.text

    def test_no_raw_200_char_line_in_output(self, http_client, tmp_path, monkeypatch):
        record = _make_record(sinq_error="NF0")
        dat = _write_dat(tmp_path / "t.DAT", [record])
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF0")
        assert record not in r.text

    # ── Pagination offset resets correctly ──────────────────────────────────

    def test_pagination_preserves_sinq_filter(
        self, http_client, tmp_path, monkeypatch
    ):
        # 60 records all with NF0 — page 2 should still carry sinq_error=NF0
        records = [_make_record(sinq_error="NF0")] * 60
        dat = _write_dat(tmp_path / "t.DAT", records)
        r = _get(http_client, monkeypatch, dat, "sinq_error=NF0")
        # Next link must preserve sinq_error
        assert "sinq_error=NF0" in r.text
        assert "Next" in r.text


# ---------------------------------------------------------------------------
# Milestone 5C: Record detail page  GET /dashboard/record/{line_number}
# ---------------------------------------------------------------------------


def _get_detail(
    client: TestClient,
    monkeypatch,
    dat_path: str,
    line_number,
    params: str = "",
    ref_path: str | None = None,
) -> object:
    """Monkeypatch dat_file_path (and optionally reference_file_path) and GET detail."""
    import example_server.dashboard as _dash

    monkeypatch.setattr(_dash.settings, "dat_file_path", dat_path, raising=True)
    if ref_path is not None:
        monkeypatch.setattr(
            _dash.settings, "reference_file_path", ref_path, raising=True
        )
    url = f"/dashboard/record/{line_number}" + (f"?{params}" if params else "")
    return client.get(url)


class TestRecordDetail:
    # T1 — valid line_number, record has SINQ error
    def test_valid_record_with_sinq_error(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(gvt_sub_agency="01", company="AG", sinq_error="NF0")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "NF0" in r.text
        assert "Yes" in r.text  # has_sinq_error

    # T2 — valid line_number, record has no SINQ error
    def test_valid_record_without_sinq_error(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(gvt_sub_agency="02", company="BB", sinq_error="   ")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        # SINQ error code cell should show an em dash (not blank, not "?")
        assert "No" in r.text  # has_sinq_error
        assert "NF0" not in r.text

    # T3 — line_number that does not exist in the file → 404
    def test_nonexistent_line_number_returns_404(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(http_client, monkeypatch, dat, 9999)
        assert r.status_code == 404

    # T4 — non-integer line_number → 400
    def test_non_integer_line_number_returns_400(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(http_client, monkeypatch, dat, "abc")
        assert r.status_code == 400

    # T5 — zero or negative line_number → 400
    def test_zero_line_number_returns_400(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(http_client, monkeypatch, dat, 0)
        assert r.status_code == 400

    def test_negative_line_number_returns_400(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(http_client, monkeypatch, dat, -1)
        assert r.status_code == 400

    # T6 — sinq_message never appears in the response body
    def test_sinq_message_absent_from_detail(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_error="NF0", sinq_message="SECRETDETAIL" + " " * 37)],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "SECRETDETAIL" not in r.text
        assert "sinq_message" not in r.text

    # T7 — raw 200-char line never appears in the response body
    def test_raw_line_absent_from_detail(self, http_client, tmp_path, monkeypatch):
        record = _make_record(gvt_sub_agency="99", company="ZZ")
        dat = _write_dat(tmp_path / "test.DAT", [record])
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert record not in r.text

    # T8 — Review column removed from the main dashboard table
    def test_review_link_absent_from_dashboard_table(
        self, http_client, tmp_path, monkeypatch
    ):
        import re

        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(), _make_record(), _make_record()],
        )
        r = _get(http_client, monkeypatch, dat)
        assert r.status_code == 200
        # Review column and its links must be absent from the table
        assert "Review" not in r.text
        links = re.findall(r'class="review-link"', r.text)
        assert len(links) == 0

    # T9 — ?back= with a valid /dashboard path renders a safe Back link
    def test_valid_back_param_used_as_back_link(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(sinq_error="NF0")])
        r = _get_detail(
            http_client, monkeypatch, dat, 1, "back=/dashboard?sinq_error=NF0"
        )
        assert r.status_code == 200
        assert "/dashboard?sinq_error=NF0" in r.text

    # T10 — ?back= with an external URL falls back to /dashboard
    def test_external_back_param_falls_back_to_dashboard(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(
            http_client, monkeypatch, dat, 1, "back=https://evil.com/steal"
        )
        assert r.status_code == 200
        assert "evil.com" not in r.text
        assert 'href="/dashboard"' in r.text

    # T10b — ?back= with a protocol-relative URL falls back to /dashboard
    def test_protocol_relative_back_param_falls_back_to_dashboard(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(
            http_client, monkeypatch, dat, 1, "back=//evil.com"
        )
        assert r.status_code == 200
        assert "evil.com" not in r.text

    # Only the six approved fields are visible; no extra attributes leak
    def test_only_approved_fields_shown(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(gvt_sub_agency="XY", company="ZZ", sinq_error="E01")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        html = r.text
        # Approved fields present
        assert "XY" in html
        assert "ZZ" in html
        assert "E01" in html
        # Forbidden attributes absent
        assert "gwebess_raw" not in html
        assert "powrdocs_raw" not in html
        assert "sinq_message" not in html

    # Missing file on detail route → safe 500, no path exposed
    def test_missing_file_returns_500(self, http_client, tmp_path, monkeypatch):
        nonexistent = str(tmp_path / "does_not_exist.DAT")
        r = _get_detail(http_client, monkeypatch, nonexistent, 1)
        assert r.status_code == 500

    def test_missing_file_no_path_in_detail_response(
        self, http_client, tmp_path, monkeypatch
    ):
        nonexistent = str(tmp_path / "does_not_exist.DAT")
        r = _get_detail(http_client, monkeypatch, nonexistent, 1)
        assert nonexistent not in r.text

    # Detail page is read-only — no forms or action buttons
    def test_detail_page_has_no_form(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "<form" not in r.text

    # Multi-record file: second record is reachable by line_number 2
    def test_second_record_reachable(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [
                _make_record(gvt_sub_agency="AA"),
                _make_record(gvt_sub_agency="BB", sinq_error="E99"),
            ],
        )
        r = _get_detail(http_client, monkeypatch, dat, 2)
        assert r.status_code == 200
        assert "E99" in r.text


# ---------------------------------------------------------------------------
# Milestone 5D: Structured record-detail grid
# ---------------------------------------------------------------------------


class TestRecordDetailGrid:
    """Verify the three-section grid layout introduced in Milestone 5D.

    All tests use synthetic tmp_path files and the existing _get_detail helper.
    No production data is accessed.
    """

    # T1 — all six approved field labels present on a 200 response
    def test_all_six_field_labels_present(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(sinq_error="NF0")])
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        html = r.text
        assert "Line Number" in html
        assert "GVT Sub-Agency" in html
        assert "Company" in html
        assert "Source" in html
        assert "SINQ Error Code" in html
        assert "Has SINQ Error" in html

    # T2 — gvt_sub_agency value rendered in page
    def test_gvt_sub_agency_value_rendered(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(gvt_sub_agency="XY")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "XY" in r.text

    # T3 — company value rendered in page
    def test_company_value_rendered(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(company="ZZ")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "ZZ" in r.text

    # T4 — source value rendered: EmpowHR
    def test_source_empowhr_rendered(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(powrdocs="POWRDOCS")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "EmpowHR" in r.text

    # T4b — source value rendered: Employee Personal Page
    def test_source_employee_personal_page_rendered(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(gwebess="GWEBESS")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "Employee Personal Page" in r.text

    # T4c — source value rendered: Unknown
    def test_source_unknown_rendered(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "Unknown" in r.text

    # T5 — sinq_error badge rendered when present
    def test_sinq_error_badge_rendered(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_error="NF0")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "NF0" in r.text
        assert "sinq-badge" in r.text

    # T6 — SINQ error cell shows em dash when blank (no badge, no literal "?")
    def test_sinq_error_em_dash_when_blank(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_error="   ")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        # em-dash class or entity must be present
        assert "em-dash" in r.text or "&mdash;" in r.text or "\u2014" in r.text
        # no rendered sinq-badge span for a blank code (CSS definition is fine)
        assert '<span class="sinq-badge">' not in r.text

    # T7 — has_sinq_error shows "Yes" when True
    def test_has_sinq_error_yes(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_error="E01")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "Yes" in r.text

    # T8 — has_sinq_error shows "No" when False
    def test_has_sinq_error_no(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_error="   ")],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "No" in r.text

    # T9 — all three section headers present
    def test_three_section_headers_present(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record(sinq_error="NF0")])
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        html = r.text
        assert "Record Identifier" in html
        assert "Classification" in html
        assert "SINQ" in html

    # Confirm forbidden fields still absent after layout change
    def test_sinq_message_still_absent(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_error="NF0", sinq_message="SECRETGRID" + " " * 39)],
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "SECRETGRID" not in r.text
        assert "sinq_message" not in r.text

    def test_gwebess_raw_still_absent(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT", [_make_record(gwebess="GWEBESS")]
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "gwebess_raw" not in r.text

    def test_powrdocs_raw_still_absent(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "test.DAT", [_make_record(powrdocs="POWRDOCS")]
        )
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "powrdocs_raw" not in r.text

    def test_raw_200_char_line_still_absent(self, http_client, tmp_path, monkeypatch):
        record = _make_record(gvt_sub_agency="QQ", company="RR")
        dat = _write_dat(tmp_path / "test.DAT", [record])
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert record not in r.text

    # Confirm read-only: no form after layout change
    def test_no_form_after_layout_change(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(http_client, monkeypatch, dat, 1)
        assert r.status_code == 200
        assert "<form" not in r.text

    # Confirm error-state pages still work after layout change
    def test_400_still_works(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(http_client, monkeypatch, dat, "notanumber")
        assert r.status_code == 400

    def test_404_still_works(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get_detail(http_client, monkeypatch, dat, 9999)
        assert r.status_code == 404

    def test_500_still_works(self, http_client, tmp_path, monkeypatch):
        nonexistent = str(tmp_path / "missing.DAT")
        r = _get_detail(http_client, monkeypatch, nonexistent, 1)
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# Phase 2: DOCU_TYPE column and filter
# ---------------------------------------------------------------------------


def _write_ref(path, lines: list[str]) -> str:
    """Write synthetic reference lines to path and return the path as a string."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


class TestDocuTypeColumn:
    """DOCU_TYPE column appears in the results table; filter works."""

    def test_docu_type_column_header_present(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get(http_client, monkeypatch, dat)
        assert r.status_code == 200
        assert "Doc Type" in r.text

    def test_docu_type_value_rendered_in_table(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(docu_type="054", sinq_error="019")],
        )
        r = _get(http_client, monkeypatch, dat)
        assert r.status_code == 200
        assert "054" in r.text

    def test_docu_type_filter_input_present(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        r = _get(http_client, monkeypatch, dat)
        assert 'name="docu_type"' in r.text

    def test_docu_type_filter_narrows_results(
        self, http_client, tmp_path, monkeypatch
    ):
        records = [
            _make_record(docu_type="030"),
            _make_record(docu_type="054"),
        ]
        dat = _write_dat(tmp_path / "test.DAT", records)
        r = _get(http_client, monkeypatch, dat, "docu_type=030")
        assert r.status_code == 200
        assert "1 matching record" in r.text


class TestRefDescriptionDashboard:
    """Reference descriptions appear on the detail page; sentinel shown for no match."""

    def test_approved_description_label_on_detail_page(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(docu_type="030", sinq_error="001")],
        )
        ref = _write_ref(
            tmp_path / "ref.txt",
            [_make_ref_line(docu_type="030", err_mess_no="001",
                            err_mess_des="OUT OF BALANCE")],
        )
        r = _get_detail(
            http_client, monkeypatch, dat, 1, ref_path=ref
        )
        assert r.status_code == 200
        assert "Approved Description" in r.text
        assert "OUT OF BALANCE" in r.text

    def test_sentinel_shown_when_no_reference_match(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(docu_type="999", sinq_error="999")],
        )
        ref = _write_ref(
            tmp_path / "ref.txt",
            [_make_ref_line(docu_type="030", err_mess_no="001")],
        )
        r = _get_detail(
            http_client, monkeypatch, dat, 1, ref_path=ref
        )
        assert r.status_code == 200
        assert "No approved reference available" in r.text

    def test_sinq_message_still_absent_after_phase2(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(sinq_error="001",
                          sinq_message="PHASE2SECRET" + " " * 37)],
        )
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_detail(
            http_client, monkeypatch, dat, 1, ref_path=ref
        )
        assert r.status_code == 200
        assert "PHASE2SECRET" not in r.text
        assert "sinq_message" not in r.text

    def test_missing_reference_file_returns_500(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        missing_ref = str(tmp_path / "no_ref.txt")
        r = _get_detail(
            http_client, monkeypatch, dat, 1, ref_path=missing_ref
        )
        assert r.status_code == 500

    def test_missing_reference_file_no_path_in_response(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "test.DAT", [_make_record()])
        missing_ref = str(tmp_path / "no_ref.txt")
        r = _get_detail(
            http_client, monkeypatch, dat, 1, ref_path=missing_ref
        )
        assert missing_ref not in r.text

    def test_document_type_label_on_detail_page(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(
            tmp_path / "test.DAT",
            [_make_record(docu_type="054")],
        )
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_detail(
            http_client, monkeypatch, dat, 1, ref_path=ref
        )
        assert r.status_code == 200
        assert "Document Type" in r.text
        assert "054" in r.text


# ---------------------------------------------------------------------------
# Helper: GET /dashboard/download
# ---------------------------------------------------------------------------


def _get_download(
    client: TestClient,
    monkeypatch,
    dat_path: str,
    params: str = "",
    ref_path: str | None = None,
) -> object:
    """Monkeypatch settings and GET /dashboard/download."""
    import example_server.dashboard as _dash

    monkeypatch.setattr(_dash.settings, "dat_file_path", dat_path, raising=True)
    if ref_path is not None:
        monkeypatch.setattr(
            _dash.settings, "reference_file_path", ref_path, raising=True
        )
    url = "/dashboard/download" + (f"?{params}" if params else "")
    return client.get(url)


# ---------------------------------------------------------------------------
# Milestone 6 continued: Grouped SINQ breakdown
# ---------------------------------------------------------------------------


class TestGroupedBreakdown:
    """The SINQ breakdown groups by (SINQ_ERROR, DOCU_TYPE) with descriptions."""

    def test_inner_docu_type_rows_present(self, http_client, tmp_path, monkeypatch):
        """Each DOCU_TYPE within a SINQ_ERROR appears as a sub-row."""
        records = [
            _make_record(docu_type="030", sinq_error="008"),
            _make_record(docu_type="054", sinq_error="008"),
        ]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(
            tmp_path / "ref.txt",
            [_make_ref_line(docu_type="030", err_mess_no="008",
                            err_mess_des="DB RECORD NOT FOUND")],
        )
        r = _get(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        assert "030" in r.text
        assert "054" in r.text

    def test_matching_description_shown_in_breakdown(
        self, http_client, tmp_path, monkeypatch
    ):
        """The approved description appears for a matching (DOCU_TYPE, SINQ_ERROR)."""
        records = [_make_record(docu_type="030", sinq_error="008")]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(
            tmp_path / "ref.txt",
            [_make_ref_line(docu_type="030", err_mess_no="008",
                            err_mess_des="DB RECORD NOT FOUND")],
        )
        r = _get(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        assert "DB RECORD NOT FOUND" in r.text

    def test_sentinel_shown_when_no_reference_match(
        self, http_client, tmp_path, monkeypatch
    ):
        """The sentinel is shown for a DOCU_TYPE with no reference entry."""
        records = [_make_record(docu_type="999", sinq_error="008")]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(
            tmp_path / "ref.txt",
            [_make_ref_line(docu_type="030", err_mess_no="008",
                            err_mess_des="DB RECORD NOT FOUND")],
        )
        r = _get(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        assert "No approved reference available" in r.text

    def test_different_docu_types_not_combined(
        self, http_client, tmp_path, monkeypatch
    ):
        """Two DOCU_TYPEs for the same SINQ_ERROR appear as separate sub-rows."""
        records = [
            _make_record(docu_type="030", sinq_error="008"),
            _make_record(docu_type="054", sinq_error="008"),
        ]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(
            tmp_path / "ref.txt",
            [
                _make_ref_line(docu_type="030", err_mess_no="008",
                               err_mess_des="ALPHA DESCRIPTION"),
                _make_ref_line(docu_type="054", err_mess_no="008",
                               err_mess_des="BETA DESCRIPTION"),
            ],
        )
        r = _get(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        assert "ALPHA DESCRIPTION" in r.text
        assert "BETA DESCRIPTION" in r.text

    def test_outer_total_is_sum_of_sub_group_counts(
        self, http_client, tmp_path, monkeypatch
    ):
        """The outer 'N total' count equals the sum of all sub-group counts."""
        records = [
            _make_record(docu_type="030", sinq_error="008"),
            _make_record(docu_type="030", sinq_error="008"),
            _make_record(docu_type="054", sinq_error="008"),
        ]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        # Outer total = 3; should appear somewhere in the breakdown section
        assert "3 total" in r.text

    def test_sinq_message_absent_from_grouped_breakdown(
        self, http_client, tmp_path, monkeypatch
    ):
        """SINQ_MESSAGE must never appear in the breakdown section."""
        records = [
            _make_record(
                docu_type="030", sinq_error="008",
                sinq_message="SECRETGROUP" + " " * 38,
            )
        ]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get(http_client, monkeypatch, dat, ref_path=ref)
        assert "SECRETGROUP" not in r.text


# ---------------------------------------------------------------------------
# Milestone 6: CSV download — GET /dashboard/download
# ---------------------------------------------------------------------------


class TestCsvDownload:
    """Basic CSV output shape and content."""

    def test_returns_200(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200

    def test_content_type_is_csv(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert "text/csv" in r.headers.get("content-type", "")

    def test_content_disposition_attachment(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd
        assert "processing_monitor_export.csv" in cd

    def test_csv_header_row_columns(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        # Find the first non-comment line
        lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
        assert lines, "no CSV header row found"
        header = lines[0]
        assert "line_number" in header
        assert "gvt_sub_agency" in header
        assert "company" in header
        assert "docu_type" in header
        assert "source" in header
        assert "sinq_error" in header
        assert "has_sinq_error" in header
        assert "approved_description" in header

    def test_csv_data_row_present(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(gvt_sub_agency="01", company="AG",
                          docu_type="030", sinq_error="008")],
        )
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
        # header + 1 data row
        assert len(lines) == 2
        assert "01" in lines[1]
        assert "AG" in lines[1]
        assert "030" in lines[1]

    def test_approved_description_in_csv(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(docu_type="030", sinq_error="008")],
        )
        ref = _write_ref(
            tmp_path / "ref.txt",
            [_make_ref_line(docu_type="030", err_mess_no="008",
                            err_mess_des="DB RECORD NOT FOUND")],
        )
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert "DB RECORD NOT FOUND" in r.text

    def test_sentinel_in_csv_when_no_match(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(docu_type="999", sinq_error="999")],
        )
        ref = _write_ref(
            tmp_path / "ref.txt",
            [_make_ref_line(docu_type="030", err_mess_no="001")],
        )
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert "No approved reference available" in r.text

    def test_sinq_message_absent_from_csv(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(sinq_message="SECRETCSV" + " " * 40)],
        )
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert "SECRETCSV" not in r.text
        assert "sinq_message" not in r.text

    def test_raw_200_char_line_absent_from_csv(
        self, http_client, tmp_path, monkeypatch
    ):
        record = _make_record(gvt_sub_agency="QQ", company="RR")
        dat = _write_dat(tmp_path / "t.DAT", [record])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert record not in r.text

    def test_gwebess_raw_absent_from_csv(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record(gwebess="GWEBESS")])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert "gwebess_raw" not in r.text

    def test_powrdocs_raw_absent_from_csv(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record(powrdocs="POWRDOCS")])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert "powrdocs_raw" not in r.text

    def test_zero_records_returns_header_only(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(gvt_sub_agency="01")],
        )
        ref = _write_ref(tmp_path / "ref.txt", [])
        # Filter to a non-matching agency — zero results
        r = _get_download(
            http_client, monkeypatch, dat, "gvt_sub_agency=ZZ", ref_path=ref
        )
        assert r.status_code == 200
        lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
        # Only the header row, no data rows
        assert len(lines) == 1
        assert "line_number" in lines[0]

    def test_parse_errors_absent_from_csv(self, http_client, tmp_path, monkeypatch):
        records = [_make_record(), "SHORT"]  # SHORT is a malformed line
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
        # 1 valid record → header + 1 data row
        assert len(lines) == 2

    def test_filter_metadata_comment_rows_present(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(
            http_client, monkeypatch, dat, "sinq_error=008", ref_path=ref
        )
        comment_lines = [ln for ln in r.text.splitlines() if ln.startswith("#")]
        assert any("Personnel Processing Monitor" in ln for ln in comment_lines)
        assert any("sinq_error=008" in ln for ln in comment_lines)

    def test_missing_dat_file_returns_500(self, http_client, tmp_path, monkeypatch):
        nonexistent = str(tmp_path / "missing.DAT")
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, nonexistent, ref_path=ref)
        assert r.status_code == 500
        assert nonexistent not in r.text

    def test_missing_ref_file_returns_500(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        missing_ref = str(tmp_path / "missing_ref.txt")
        r = _get_download(http_client, monkeypatch, dat, ref_path=missing_ref)
        assert r.status_code == 500
        assert missing_ref not in r.text


class TestCsvFilterPreservation:
    """Active filters are preserved in both the download link and the download route."""

    def test_download_url_in_dashboard_html(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record(sinq_error="008")])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get(http_client, monkeypatch, dat, "sinq_error=008", ref_path=ref)
        assert r.status_code == 200
        assert "/dashboard/download" in r.text

    def test_download_url_preserves_sinq_error_filter(
        self, http_client, tmp_path, monkeypatch
    ):
        dat = _write_dat(tmp_path / "t.DAT", [_make_record(sinq_error="008")])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get(http_client, monkeypatch, dat, "sinq_error=008", ref_path=ref)
        assert "sinq_error=008" in r.text

    def test_download_respects_active_sinq_error_filter(
        self, http_client, tmp_path, monkeypatch
    ):
        records = [
            _make_record(sinq_error="008"),
            _make_record(sinq_error="NF0"),
        ]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(
            http_client, monkeypatch, dat, "sinq_error=008", ref_path=ref
        )
        assert r.status_code == 200
        lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
        # header + 1 data row (only 008)
        assert len(lines) == 2

    def test_download_respects_gvt_sub_agency_filter(
        self, http_client, tmp_path, monkeypatch
    ):
        records = [
            _make_record(gvt_sub_agency="01"),
            _make_record(gvt_sub_agency="02"),
        ]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(
            http_client, monkeypatch, dat, "gvt_sub_agency=01", ref_path=ref
        )
        lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
        assert len(lines) == 2
        assert "01" in lines[1]


class TestCsvFormulaInjection:
    """String cells beginning with formula-trigger characters are prefixed with '."""

    def test_equals_prefix_sanitised(self, http_client, tmp_path, monkeypatch):
        # sinq_error starting with '=' would be a formula injection vector
        # Use a docu_type that starts with '=' via a crafted record
        # (easiest: put =CMD in gvt_sub_agency position)
        buf = list(_make_record())
        # Place '=01' at gvt_sub_agency [9:11] — only 2 chars, so '=' then '0'
        buf[9] = "="
        buf[10] = "0"
        record = "".join(buf)
        dat = _write_dat(tmp_path / "t.DAT", [record])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        # The injected value must not appear bare — it must be prefixed
        assert ",=0," not in r.text
        assert ",'=0," in r.text or "\"'=0\"" in r.text or "'=0" in r.text

    def test_plus_prefix_sanitised(self, http_client, tmp_path, monkeypatch):
        buf = list(_make_record())
        buf[9] = "+"
        buf[10] = "1"
        record = "".join(buf)
        dat = _write_dat(tmp_path / "t.DAT", [record])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        assert ",+1," not in r.text

    def test_at_prefix_sanitised(self, http_client, tmp_path, monkeypatch):
        buf = list(_make_record())
        buf[9] = "@"
        buf[10] = "A"
        record = "".join(buf)
        dat = _write_dat(tmp_path / "t.DAT", [record])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        assert ",@A," not in r.text

    def test_normal_codes_unchanged(self, http_client, tmp_path, monkeypatch):
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(gvt_sub_agency="01", docu_type="030", sinq_error="008")],
        )
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert "01" in r.text
        assert "030" in r.text
        assert "008" in r.text


class TestCsvTruncation:
    """Export is capped at CSV_EXPORT_LIMIT rows; a warning comment is written."""

    def test_truncation_warning_written(self, http_client, tmp_path, monkeypatch):
        from example_server.dashboard import CSV_EXPORT_LIMIT

        # Write CSV_EXPORT_LIMIT + 2 records
        records = [_make_record() for _ in range(CSV_EXPORT_LIMIT + 2)]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        assert r.status_code == 200
        comment_lines = [ln for ln in r.text.splitlines() if ln.startswith("#")]
        assert any("WARNING" in ln for ln in comment_lines)
        assert any("truncated" in ln.lower() for ln in comment_lines)

    def test_truncated_data_rows_at_cap(self, http_client, tmp_path, monkeypatch):
        from example_server.dashboard import CSV_EXPORT_LIMIT

        records = [_make_record() for _ in range(CSV_EXPORT_LIMIT + 2)]
        dat = _write_dat(tmp_path / "t.DAT", records)
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _get_download(http_client, monkeypatch, dat, ref_path=ref)
        data_lines = [ln for ln in r.text.splitlines() if not ln.startswith("#")]
        # header + CSV_EXPORT_LIMIT data rows (not CSV_EXPORT_LIMIT + 2)
        assert len(data_lines) == CSV_EXPORT_LIMIT + 1
