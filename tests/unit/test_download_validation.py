"""Unit tests for download content validation + retry classification.

Hardens insar_download_scene against the failure seen in practice: the ASF
burst service returns an HTML URS login page (HTTP 200) when concurrent OAuth
is throttled. That must be detected and treated as a *retryable* failure
rather than accepted as data.
"""

from __future__ import annotations

from insar_agent.mcp.tools import prepare_tools as pt


def test_downloaded_content_error_flags_html_login_page(tmp_path):
    p = tmp_path / "burst.tiff"
    p.write_bytes(b"<html>\n  <head><title>ASF-URS | Logging in</title></head>\n</html>")
    err = pt._downloaded_content_error(p)
    assert err == pt._LOGIN_PAGE_ERROR
    assert pt._is_retryable_download_error(err) is True


def test_downloaded_content_error_accepts_valid_tiff(tmp_path):
    p = tmp_path / "burst.tiff"
    p.write_bytes(b"II*\x00" + b"\x00" * 200)
    assert pt._downloaded_content_error(p) is None


def test_downloaded_content_error_flags_truncated_tiff_as_retryable(tmp_path):
    p = tmp_path / "burst.tiff"
    p.write_bytes(b"not-a-tiff-header" + b"\x00" * 50)
    err = pt._downloaded_content_error(p)
    assert err is not None and "TIFF" in err
    # A truncated/corrupt download is worth retrying.
    assert pt._is_retryable_download_error(err) is True


def test_downloaded_content_error_accepts_valid_xml(tmp_path):
    p = tmp_path / "burst.xml"
    p.write_bytes(b"<?xml version='1.0'?><burst><meta>1</meta></burst>")
    assert pt._downloaded_content_error(p) is None


def test_downloaded_content_error_flags_malformed_xml(tmp_path):
    p = tmp_path / "burst.xml"
    p.write_bytes(b"<?xml version='1.0'?><burst><unclosed>")
    err = pt._downloaded_content_error(p)
    assert err is not None and "well-formed" in err
    assert pt._is_retryable_download_error(err) is True


def test_is_retryable_download_error_false_for_none():
    assert pt._is_retryable_download_error(None) is False


def test_extraction_pending_stub_detected(tmp_path):
    # ASF serves bursts on demand: the first request returns HTTP 202 with a tiny
    # {"message": "Accepted"} body while the burst is generated. That stub must be
    # recognised as "still extracting", not accepted as data.
    p = tmp_path / "burst.tiff"
    p.write_bytes(b'{"message": "Accepted"}')
    assert pt._is_extraction_pending_payload(p) is True


def test_extraction_pending_false_for_real_tiff(tmp_path):
    p = tmp_path / "burst.tiff"
    p.write_bytes(b"II*\x00" + b"\x00" * 200)
    assert pt._is_extraction_pending_payload(p) is False


def test_extraction_pending_stub_is_retryable_via_content_check(tmp_path):
    # Safety net: even without HTTP-status sniffing, the stub written to a .tiff is
    # a retryable content error, never silently accepted as data.
    p = tmp_path / "burst.tiff"
    p.write_bytes(b'{"message": "Accepted"}')
    err = pt._downloaded_content_error(p)
    assert err is not None
    assert pt._is_retryable_download_error(err) is True
