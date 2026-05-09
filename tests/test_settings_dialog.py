"""Tests for ``splice_kicad_plugin.ui.settings_dialog``.

Only the pure-Python helpers are exercised — the wxPython SpliceSettingsDialog
needs a running KiCad to test.
"""

from splice_kicad_plugin.ui.settings_dialog import (
    format_prefixes,
    parse_prefixes,
    validate_config,
)


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


def test_empty_api_key_now_accepted() -> None:
    # API key is optional — desktop handoff doesn't need one. Saving with a
    # blank key is allowed; the plugin will simply have no web fallback.
    ok, err = validate_config("", "https://splice-cad.com")
    assert ok
    assert err is None


def test_empty_base_url_rejected() -> None:
    ok, err = validate_config("splice_abc12345", "")
    assert not ok
    assert "Server URL" in (err or "")


# ---------------------------------------------------------------------------
# Format checks
# ---------------------------------------------------------------------------


def test_api_key_must_start_with_splice_underscore() -> None:
    ok, err = validate_config("hello_world_123", "https://splice-cad.com")
    assert not ok
    assert "splice_" in (err or "")


def test_api_key_too_short_rejected() -> None:
    # Token portion under 8 chars.
    ok, err = validate_config("splice_abc", "https://splice-cad.com")
    assert not ok


def test_base_url_must_have_scheme() -> None:
    ok, err = validate_config("splice_abcdefgh", "splice-cad.com")
    assert not ok
    assert "http" in (err or "")


# ---------------------------------------------------------------------------
# Valid configs
# ---------------------------------------------------------------------------


def test_valid_config_https() -> None:
    ok, err = validate_config("splice_abcd1234", "https://splice-cad.com")
    assert ok
    assert err is None


def test_valid_config_http_localhost() -> None:
    ok, err = validate_config("splice_test1234", "http://localhost:5002")
    assert ok
    assert err is None


def test_valid_config_with_uuid_style_key() -> None:
    ok, err = validate_config(
        "splice_8c2e6e4a9e2b4d8a8c0a1a2b3c4d5e6f",
        "https://splice-cad.com",
    )
    assert ok
    assert err is None


# ---------------------------------------------------------------------------
# Prefix parsing
# ---------------------------------------------------------------------------


def test_parse_prefixes_blank_returns_none() -> None:
    assert parse_prefixes("") is None
    assert parse_prefixes("   ") is None
    assert parse_prefixes("\t\n") is None


def test_parse_prefixes_canonical() -> None:
    assert parse_prefixes("J, CN, CON, P, X") == ["J", "CN", "CON", "P", "X"]


def test_parse_prefixes_uppercases() -> None:
    assert parse_prefixes("j,cn,con") == ["J", "CN", "CON"]


def test_parse_prefixes_handles_extra_whitespace() -> None:
    assert parse_prefixes("  J  ,   CN ,P  ") == ["J", "CN", "P"]


def test_parse_prefixes_drops_empty_tokens() -> None:
    assert parse_prefixes("J, , ,CN,") == ["J", "CN"]


def test_parse_prefixes_rejects_invalid_token() -> None:
    # Starts with a digit — not a valid designator prefix.
    assert parse_prefixes("J, 1NOT_OK") is None
    # Contains punctuation.
    assert parse_prefixes("J, C-N") is None
    # Has a space inside the token.
    assert parse_prefixes("J, C N") is None


def test_parse_prefixes_allows_underscored_token() -> None:
    # Useful for libraries that use compound designators.
    assert parse_prefixes("J, MY_CONN") == ["J", "MY_CONN"]


def test_format_prefixes_round_trip() -> None:
    assert format_prefixes(["J", "CN", "CON"]) == "J, CN, CON"
    assert format_prefixes(None) == ""
    assert format_prefixes([]) == ""


# ---------------------------------------------------------------------------
# validate_config + prefixes
# ---------------------------------------------------------------------------


def test_validate_config_accepts_valid_prefixes() -> None:
    ok, err = validate_config(
        "splice_abcd1234",
        "https://splice-cad.com",
        prefixes_text="J, CN, X",
    )
    assert ok
    assert err is None


def test_validate_config_accepts_blank_prefixes() -> None:
    ok, err = validate_config(
        "splice_abcd1234",
        "https://splice-cad.com",
        prefixes_text="",
    )
    assert ok
    assert err is None


def test_validate_config_rejects_invalid_prefixes() -> None:
    ok, err = validate_config(
        "splice_abcd1234",
        "https://splice-cad.com",
        prefixes_text="J, 1bad",
    )
    assert not ok
    assert "Connector prefixes" in (err or "")
