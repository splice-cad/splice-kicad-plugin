"""Tests for ``splice_kicad_plugin.detect.footprint_name``.

Faithfully exercises the TS-equivalent behavior, including the documented
``\\b``-boundary quirks where word boundaries inside compound tokens like
``PinHeader`` prevent the gender heuristics from firing.
"""

from splice_kicad_plugin.detect.footprint_name import (
    KNOWN_MANUFACTURERS,
    KNOWN_SERIES,
    ParsedFootprint,
    parse_footprint_name,
)

# ---------------------------------------------------------------------------
# Empty / sparse input
# ---------------------------------------------------------------------------


def test_empty_input_returns_sparse_result() -> None:
    r = parse_footprint_name("")
    assert r == ParsedFootprint(raw="")


def test_unknown_input_extracts_layout_and_pitch_only() -> None:
    r = parse_footprint_name("UnknownVendor_Mystery_1x04_P2.00mm")
    assert r.manufacturer is None
    assert r.series is None
    assert r.pitch_mm == 2.0
    assert r.pin_count == 4
    assert r.rows == 1


# ---------------------------------------------------------------------------
# Canonical KiCad library names
# ---------------------------------------------------------------------------


def test_canonical_jst_xh() -> None:
    r = parse_footprint_name("Connector_JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical")
    assert r.manufacturer == "JST"
    assert r.series == "XH"
    assert r.pitch_mm == 2.5
    assert r.pin_count == 4
    assert r.rows == 1
    assert r.mounting_style == "Vertical"
    assert r.mpn == "B4B-XH-A"


def test_canonical_jst_ph_with_library_prefix() -> None:
    r = parse_footprint_name("Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Vertical")
    assert r.manufacturer == "JST"
    assert r.series == "PH"
    assert r.pitch_mm == 2.0
    assert r.pin_count == 2
    assert r.mpn == "S2B-PH-K"


def test_molex_micro_fit_normalizes_series() -> None:
    r = parse_footprint_name("Connector_Molex_Micro-Fit_3.0_43025-0400_2x02_P3.00mm_Vertical")
    assert r.manufacturer == "Molex"
    assert r.series == "Micro-Fit 3.0"
    assert r.pin_count == 4
    assert r.rows == 2


def test_te_mta_uses_typical_pitch_when_name_omits_it() -> None:
    r = parse_footprint_name("Connector_TE_MTA_3-640456-3_1x04")
    assert r.manufacturer == "TE Connectivity"
    assert r.series == "MTA-100"
    # Pitch comes from KNOWN_SERIES["mta"].typical_pitch — name has no P-token.
    assert r.pitch_mm == 2.54


def test_explicit_pitch_overrides_series_typical_pitch() -> None:
    r = parse_footprint_name("Connector_JST_XH_B2B-XH-A_1x02_P3.00mm")
    assert r.series == "XH"
    assert r.pitch_mm == 3.0  # not 2.5


# ---------------------------------------------------------------------------
# Mounting-style normalization
# ---------------------------------------------------------------------------


def test_mounting_style_through_hole_via_tht() -> None:
    assert parse_footprint_name("PinHeader_1x04_P2.54mm_THT").mounting_style == "Through-Hole"


def test_mounting_style_through_hole_via_throughhole_token() -> None:
    assert (
        parse_footprint_name("PinHeader_1x04_P2.54mm_ThroughHole").mounting_style == "Through-Hole"
    )


def test_mounting_style_smd() -> None:
    assert parse_footprint_name("PinHeader_1x04_P1.27mm_SMD").mounting_style == "SMD"


def test_mounting_style_right_angle() -> None:
    assert parse_footprint_name("PinHeader_1x04_P2.54mm_RightAngle").mounting_style == "Right-Angle"


def test_mounting_style_horizontal_capitalizes() -> None:
    assert parse_footprint_name("PinHeader_1x04_P2.54mm_Horizontal").mounting_style == "Horizontal"


# ---------------------------------------------------------------------------
# Gender — faithful to the TS \b quirk.
#
# Both Python and JavaScript regex treat `_` as a word character (it is part of
# `\w`). So `\bheader\b` does NOT fire on `_Header_` — there is no word boundary
# between an underscore and a letter. In typical KiCad footprint names, where
# every separator is `_`, the gender heuristic is effectively silent. The
# heuristic only fires when the keyword sits at a string boundary or is
# separated by genuinely non-word characters (`-`, ` `, `:`).
#
# We preserve this behavior so cross-language parity (RFC-003e §3) holds.
# ---------------------------------------------------------------------------


def test_gender_undefined_for_underscore_separated_words() -> None:
    """`_` is a word char, so `\\bword\\b` doesn't fire on `_word_`."""
    assert parse_footprint_name("Connector_Header_1x04_P2.54mm").gender is None
    assert parse_footprint_name("Connector_Socket_1x04_P2.54mm").gender is None
    assert parse_footprint_name("USB_C_Receptacle").gender is None
    assert parse_footprint_name("USB_A_Plug_Vertical").gender is None


def test_gender_undefined_for_compound_tokens() -> None:
    # `PinHeader` / `PinSocket` have no \b inside (n→H, n→S are word→word).
    assert parse_footprint_name("PinHeader_1x04_P2.54mm_Vertical").gender is None
    assert parse_footprint_name("PinSocket_1x04_P2.54mm_Vertical").gender is None


def test_gender_male_when_keyword_is_entire_input() -> None:
    # Start- and end-of-string both count as \b.
    assert parse_footprint_name("Header").gender == "male"
    assert parse_footprint_name("Plug").gender == "male"


def test_gender_female_when_keyword_is_entire_input() -> None:
    assert parse_footprint_name("Socket").gender == "female"
    assert parse_footprint_name("Receptacle").gender == "female"


def test_gender_male_when_separator_is_hyphen() -> None:
    # Hyphen is a non-word character — \b fires on both sides.
    assert parse_footprint_name("USB-Plug-Vertical").gender == "male"


def test_gender_female_when_separator_is_hyphen() -> None:
    assert parse_footprint_name("USB-Receptacle").gender == "female"


# ---------------------------------------------------------------------------
# Pin layout
# ---------------------------------------------------------------------------


def test_pin_layout_2x05_yields_10_pins() -> None:
    r = parse_footprint_name("Connector_Generic_Conn_02x05_P2.54mm")
    assert r.rows == 2
    assert r.pin_count == 10


# ---------------------------------------------------------------------------
# MPN heuristic
# ---------------------------------------------------------------------------


def test_mpn_skips_manufacturer_and_series_tokens() -> None:
    r = parse_footprint_name("Connector_JST_XH_B4B-XH-A_1x04")
    assert r.mpn == "B4B-XH-A"


def test_mpn_skips_pin_layout_and_pitch_tokens() -> None:
    r = parse_footprint_name("Connector_JST_XH_S4B-XH-A_1x04_P2.50mm")
    assert r.mpn == "S4B-XH-A"


def test_no_mpn_for_simple_pinheader() -> None:
    # Generic PinHeader has nothing that looks like an MPN.
    r = parse_footprint_name("PinHeader_1x04_P2.54mm_Vertical")
    assert r.mpn is None


# ---------------------------------------------------------------------------
# Library-prefix normalization
# ---------------------------------------------------------------------------


def test_normalize_separators_finds_series_after_colon() -> None:
    # `:` is normalized to `_` for splitting.
    r = parse_footprint_name("Connector_JST:JST_PH_B2B-PH-K")
    assert r.series == "PH"
    assert r.manufacturer == "JST"


# ---------------------------------------------------------------------------
# Dictionary consistency invariant
# ---------------------------------------------------------------------------


def test_dictionaries_consistent() -> None:
    """Every series with a manufacturer points to a known manufacturer name."""
    known_mfr_names = set(KNOWN_MANUFACTURERS.values())
    for key, info in KNOWN_SERIES.items():
        if info.manufacturer is not None:
            assert info.manufacturer in known_mfr_names, (
                f"KNOWN_SERIES[{key!r}].manufacturer={info.manufacturer!r} "
                "is not in KNOWN_MANUFACTURERS values"
            )
