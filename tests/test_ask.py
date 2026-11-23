"""Tests for the natural-language ask feature (ask.py and POST /dashboard/ask).

All tests use:
  - Synthetic 200-character transaction records via tmp_path.
  - Synthetic 75-character reference lines built in memory.
  - Monkeypatched settings — no real .env values required.
  - Monkeypatched httpx.post — no real network calls or API keys.

No real transaction files, reference files, or watsonx.ai credentials are
accessed by any test here.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from example_server.app import mcp
from example_server.ask import (
    _FALLBACK_UNKNOWN,
    WATSONX_NOT_CONFIGURED,
    answer_locally,
    build_context,
)
from example_server.parser import RECORD_LENGTH
from example_server.query import load_monitor
from example_server.reference import load_reference

# ---------------------------------------------------------------------------
# Synthetic builders (same field positions as other test modules)
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
    """Build a synthetic 200-character transaction record."""
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
    docu_type: str = "063",
    err_mess_no: str = "507",
    err_mess_des: str = "POSITION SUPERVISORY CODE MUST BE 2 OR 4",
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
    path.write_text("\n".join(records) + "\n", encoding="utf-8")
    return str(path)


def _write_ref(path, lines: list[str]) -> str:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Shared TestClient fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def http_client():
    return TestClient(mcp.http_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# build_context — unit tests (no HTTP, no watsonx)
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_contains_sinq_error_counts(self, tmp_path):
        """build_context must include SINQ_ERROR codes and their counts."""
        dat = _write_dat(
            tmp_path / "t.DAT",
            [
                _make_record(sinq_error="507"),
                _make_record(sinq_error="507"),
                _make_record(sinq_error="006"),
            ],
        )
        ref_lines = [_make_ref_line(docu_type="063", err_mess_no="507")]
        ref = _write_ref(tmp_path / "ref.txt", ref_lines)

        monitor = load_monitor(dat)
        ref_table = load_reference(ref)
        ctx = build_context(monitor, ref_table)

        assert "507" in ctx
        assert "2" in ctx   # count of 507
        assert "006" in ctx

    def test_contains_total_valid_records(self, tmp_path):
        """build_context must state the total valid record count."""
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(), _make_record(), _make_record()],
        )
        ref = _write_ref(tmp_path / "ref.txt", [])
        monitor = load_monitor(dat)
        ref_table = load_reference(ref)
        ctx = build_context(monitor, ref_table)
        assert "3" in ctx

    def test_excludes_sinq_message_text(self, tmp_path):
        """SINQ_MESSAGE text must never appear in the context string."""
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(sinq_error="507",
                          sinq_message="SECRETMESSAGE" + " " * 36)],
        )
        ref = _write_ref(tmp_path / "ref.txt", [])
        monitor = load_monitor(dat)
        ref_table = load_reference(ref)
        ctx = build_context(monitor, ref_table)
        assert "SECRETMESSAGE" not in ctx

    def test_excludes_raw_200_char_lines(self, tmp_path):
        """No 200-character raw record string must appear in the context."""
        record = _make_record(sinq_error="507")
        dat = _write_dat(tmp_path / "t.DAT", [record])
        ref = _write_ref(tmp_path / "ref.txt", [])
        monitor = load_monitor(dat)
        ref_table = load_reference(ref)
        ctx = build_context(monitor, ref_table)
        assert record not in ctx


# ---------------------------------------------------------------------------
# POST /dashboard/ask — HTTP route tests
# ---------------------------------------------------------------------------


def _post_ask(client, monkeypatch, dat_path: str, question: str,
              ref_path: str | None = None) -> object:
    """Monkeypatch settings and POST /dashboard/ask."""
    import example_server.dashboard as _dash
    monkeypatch.setattr(_dash.settings, "dat_file_path", dat_path, raising=True)
    if ref_path is not None:
        monkeypatch.setattr(
            _dash.settings, "reference_file_path", ref_path, raising=True
        )
    return client.post(
        "/dashboard/ask",
        json={"question": question},
    )


class TestAskRoute:
    def test_blank_question_returns_400(self, http_client, tmp_path, monkeypatch):
        """An empty question string must return HTTP 400."""
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        ref = _write_ref(tmp_path / "ref.txt", [])
        r = _post_ask(http_client, monkeypatch, dat, "", ref_path=ref)
        assert r.status_code == 400

    def test_missing_question_key_returns_400(
        self, http_client, tmp_path, monkeypatch
    ):
        """A POST body with no 'question' key must return HTTP 400."""
        import example_server.dashboard as _dash
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        monkeypatch.setattr(_dash.settings, "dat_file_path", dat, raising=True)
        r = http_client.post("/dashboard/ask", json={"other": "value"})
        assert r.status_code == 400

    def test_unconfigured_key_returns_safe_message(
        self, http_client, tmp_path, monkeypatch
    ):
        """When watsonx_api_key is blank, the route still returns HTTP 200 with
        a plain-text answer — no traceback, no key exposure.

        The new design falls back to local answering instead of returning the
        WATSONX_NOT_CONFIGURED sentinel.  The response must be HTTP 200, have
        an 'answer' key, and must not expose the API key or any traceback.
        """
        import example_server.dashboard as _dash
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        ref = _write_ref(tmp_path / "ref.txt", [])
        monkeypatch.setattr(_dash.settings, "dat_file_path", dat, raising=True)
        monkeypatch.setattr(
            _dash.settings, "reference_file_path", ref, raising=True
        )
        monkeypatch.setattr(_dash.settings, "watsonx_api_key", "", raising=True)
        monkeypatch.setattr(
            _dash.settings, "watsonx_project_id", "", raising=True
        )

        r = http_client.post("/dashboard/ask", json={"question": "how many?"})
        assert r.status_code == 200
        body = r.json()
        assert "answer" in body
        # The API key must never appear in the answer.
        assert "fake" not in body["answer"]
        assert "Traceback" not in body["answer"]
        # Either a local answer or the fallback message — both are acceptable.
        assert isinstance(body["answer"], str)
        assert len(body["answer"]) > 0

    def test_unconfigured_returns_local_or_fallback(
        self, http_client, tmp_path, monkeypatch
    ):
        """When unconfigured, a recognisable question returns a local answer
        (not the WATSONX_NOT_CONFIGURED sentinel)."""
        import example_server.dashboard as _dash
        dat = _write_dat(
            tmp_path / "t.DAT",
            [_make_record(sinq_error="507"), _make_record(sinq_error="507")],
        )
        ref = _write_ref(
            tmp_path / "ref.txt",
            [_make_ref_line(docu_type="063", err_mess_no="507")],
        )
        monkeypatch.setattr(_dash.settings, "dat_file_path", dat, raising=True)
        monkeypatch.setattr(
            _dash.settings, "reference_file_path", ref, raising=True
        )
        monkeypatch.setattr(_dash.settings, "watsonx_api_key", "", raising=True)
        monkeypatch.setattr(
            _dash.settings, "watsonx_project_id", "", raising=True
        )

        r = http_client.post(
            "/dashboard/ask", json={"question": "how many total sinq errors"}
        )
        assert r.status_code == 200
        body = r.json()
        assert "answer" in body
        # The local answer for SINQ error count must include the number 2.
        assert "2" in body["answer"]
        # Must not return the old not-configured sentinel.
        assert WATSONX_NOT_CONFIGURED not in body["answer"]

    def test_response_has_answer_key(self, http_client, tmp_path, monkeypatch):
        """A successful (mocked) call must return JSON with an 'answer' key."""
        import example_server.ask as _ask
        import example_server.dashboard as _dash

        dat = _write_dat(tmp_path / "t.DAT", [_make_record(sinq_error="507")])
        ref = _write_ref(
            tmp_path / "ref.txt",
            [_make_ref_line(docu_type="063", err_mess_no="507")],
        )
        monkeypatch.setattr(_dash.settings, "dat_file_path", dat, raising=True)
        monkeypatch.setattr(
            _dash.settings, "reference_file_path", ref, raising=True
        )
        monkeypatch.setattr(
            _dash.settings, "watsonx_api_key", "fake-key", raising=True
        )
        monkeypatch.setattr(
            _dash.settings, "watsonx_project_id", "fake-proj", raising=True
        )

        # Mock httpx.post to avoid any real network call.
        def _mock_post(url, **kwargs):
            mock = type("R", (), {})()
            if "identity/token" in url:
                mock.json = lambda: {"access_token": "fake-token"}
                mock.raise_for_status = lambda: None
            else:
                mock.json = lambda: {
                    "results": [{"generated_text": "There is 1 SINQ error."}]
                }
                mock.raise_for_status = lambda: None
            return mock

        monkeypatch.setattr(_ask.httpx, "post", _mock_post)

        r = http_client.post("/dashboard/ask", json={"question": "how many?"})
        assert r.status_code == 200
        body = r.json()
        assert "answer" in body
        assert isinstance(body["answer"], str)
        assert len(body["answer"]) > 0

    def test_ask_box_present_in_dashboard_html(
        self, http_client, tmp_path, monkeypatch
    ):
        """The dashboard HTML must contain the ask box and its button."""
        import example_server.dashboard as _dash
        dat = _write_dat(tmp_path / "t.DAT", [_make_record()])
        ref = _write_ref(tmp_path / "ref.txt", [])
        monkeypatch.setattr(_dash.settings, "dat_file_path", dat, raising=True)
        monkeypatch.setattr(
            _dash.settings, "reference_file_path", ref, raising=True
        )
        r = http_client.get("/dashboard")
        assert r.status_code == 200
        assert "ask-box" in r.text
        assert "Ask a question" in r.text
        assert "ask-btn" in r.text


# ---------------------------------------------------------------------------
# answer_locally — unit tests (no HTTP, no watsonx, no files)
# ---------------------------------------------------------------------------
#
# These tests build a minimal context string directly (like build_context would
# produce) and call answer_locally() to verify each pattern branch.
# ---------------------------------------------------------------------------

_SAMPLE_CONTEXT = """\
=== Personnel Processing Monitor — Data Summary ===
Total valid records : 10
Parse errors        : 1
Records with SINQ errors: 7

Records by source:
  EmpowHR: 5
  Employee Personal Page: 3
  Unknown: 2

SINQ error counts (code: count — approved description):
  507: 4 — POSITION SUPERVISORY CODE MUST BE 2 OR 4
  008: 2 — INVALID GRADE CODE
  021: 1 — No approved reference available

Records by DOCU_TYPE:
  060: 6
  032: 4
"""


class TestAnswerLocally:
    """Unit tests for answer_locally() — no network, no files."""

    def test_total_sinq_errors(self):
        """'how many total sinq errors' returns the correct total count."""
        result = answer_locally("how many total sinq errors", _SAMPLE_CONTEXT)
        assert result is not None
        assert "7" in result

    def test_total_valid_records(self):
        """'how many total records' returns the valid record count."""
        result = answer_locally("how many total records", _SAMPLE_CONTEXT)
        assert result is not None
        assert "10" in result

    def test_parse_error_count(self):
        """'parse errors' (no 'sinq'/'error' ambiguity) returns the count."""
        # Avoid "how many ... error" which the SINQ-total branch matches first.
        result = answer_locally("are there any parse errors?", _SAMPLE_CONTEXT)
        assert result is not None
        assert "1" in result

    def test_parse_error_zero(self):
        """'malformed lines' on a context with zero parse errors returns a
        'no parse errors' message."""
        ctx_no_errs = _SAMPLE_CONTEXT.replace("Parse errors        : 1",
                                               "Parse errors        : 0")
        result = answer_locally("any malformed lines?", ctx_no_errs)
        assert result is not None
        assert "no parse error" in result.lower()

    def test_most_common_error(self):
        """'most common error' returns code 507 (highest count in sample)."""
        result = answer_locally("what is the most common error", _SAMPLE_CONTEXT)
        assert result is not None
        assert "507" in result
        assert "4" in result

    def test_specific_error_code_count(self):
        """'how many 008' returns count and description for that code."""
        result = answer_locally("how many 008 errors", _SAMPLE_CONTEXT)
        assert result is not None
        assert "2" in result
        assert "008" in result

    def test_specific_error_code_missing_reference(self):
        """A code present in the data but with no approved reference shows
        the sentinel text in the answer."""
        result = answer_locally("tell me about error 021", _SAMPLE_CONTEXT)
        assert result is not None
        assert "021" in result
        assert "No approved reference available" in result

    def test_specific_error_code_not_in_file(self):
        """A 3-digit code that does not appear in the data returns a
        'does not appear' message."""
        result = answer_locally("how many 999 errors", _SAMPLE_CONTEXT)
        assert result is not None
        assert "999" in result
        assert "does not appear" in result.lower()

    def test_docu_type_question(self):
        """'records by docu type' returns DOCU_TYPE counts."""
        result = answer_locally("show records by docu type", _SAMPLE_CONTEXT)
        assert result is not None
        assert "060" in result
        assert "032" in result

    def test_list_all_error_codes(self):
        """'list all error codes' returns all codes present in the data."""
        result = answer_locally("list all error codes", _SAMPLE_CONTEXT)
        assert result is not None
        assert "507" in result
        assert "008" in result
        assert "021" in result

    def test_unrecognised_question_returns_none(self):
        """A question that matches no pattern must return None so the caller
        can fall through to _FALLBACK_UNKNOWN."""
        result = answer_locally(
            "what is the weather like today", _SAMPLE_CONTEXT
        )
        assert result is None

    def test_fallback_unknown_sentinel_exposed(self):
        """_FALLBACK_UNKNOWN is a non-empty string (used by ask_watsonx)."""
        assert isinstance(_FALLBACK_UNKNOWN, str)
        assert len(_FALLBACK_UNKNOWN) > 0

    def test_watsonx_not_configured_sentinel_exposed(self):
        """WATSONX_NOT_CONFIGURED is still importable even though it is no
        longer the primary return value when unconfigured."""
        assert isinstance(WATSONX_NOT_CONFIGURED, str)
        assert len(WATSONX_NOT_CONFIGURED) > 0
