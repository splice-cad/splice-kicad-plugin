"""Tests for ``splice_kicad_plugin.parser.sexpr``.

Exercises the tokenizer, walker, and tree helpers on synthetic input. KiCad
fixture-driven tests come later (RFC-003e); these are the unit-test layer.
"""

import pytest

from splice_kicad_plugin.errors import SExprParseError
from splice_kicad_plugin.parser.sexpr import (
    find_all_children,
    find_child,
    get_property,
    get_string,
    is_list,
    parse_sexpr,
    tokenize,
)

# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def test_tokenize_empty():
    assert tokenize("") == []


def test_tokenize_whitespace_only():
    assert tokenize("  \t\n\r ") == []


def test_tokenize_single_atom():
    assert tokenize("hello") == ["hello"]


def test_tokenize_parens():
    assert tokenize("()") == ["(", ")"]
    assert tokenize("(a b)") == ["(", "a", "b", ")"]


def test_tokenize_quoted_string_keeps_outer_quotes():
    # Quotes are retained at the token layer so the parser can distinguish.
    assert tokenize('"foo bar"') == ['"foo bar"']


def test_tokenize_escape_drops_backslash():
    assert tokenize(r'"a\"b"') == ['"a"b"']
    assert tokenize(r'"a\\b"') == ['"a\\b"']


def test_tokenize_mixed_atoms_and_strings():
    assert tokenize('(at 1.0 "label" 2)') == ["(", "at", "1.0", '"label"', "2", ")"]


def test_tokenize_nested():
    assert tokenize("(a (b c) (d (e)))") == [
        "(",
        "a",
        "(",
        "b",
        "c",
        ")",
        "(",
        "d",
        "(",
        "e",
        ")",
        ")",
        ")",
    ]


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_empty_returns_empty_list():
    assert parse_sexpr("") == []


def test_parse_single_atom():
    assert parse_sexpr("hello") == "hello"


def test_parse_quoted_string_strips_quotes():
    assert parse_sexpr('"hello world"') == "hello world"


def test_parse_simple_list():
    assert parse_sexpr("(a b c)") == ["a", "b", "c"]


def test_parse_nested():
    assert parse_sexpr("(a (b c) d)") == ["a", ["b", "c"], "d"]


def test_parse_quoted_inside_list():
    assert parse_sexpr('(at "1.5" "0.0")') == ["at", "1.5", "0.0"]


def test_parse_multiple_top_level_wraps():
    # JS behavior at kicadParser.ts:108-115
    assert parse_sexpr("(a) (b)") == [["a"], ["b"]]


def test_parse_unbalanced_open_raises():
    with pytest.raises(SExprParseError):
        parse_sexpr("(a (b c)")


def test_parse_stray_close_raises():
    with pytest.raises(SExprParseError):
        parse_sexpr("a)")


def test_parse_kicad_footprint_fragment():
    src = (
        '(footprint "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Vertical" '
        '(layer "F.Cu") (at 100 50))'
    )
    out = parse_sexpr(src)
    assert isinstance(out, list)
    assert out[0] == "footprint"
    assert out[1] == "Connector_JST:JST_PH_S2B-PH-K_1x02_P2.00mm_Vertical"


# ---------------------------------------------------------------------------
# Tree helpers
# ---------------------------------------------------------------------------


def test_is_list_basic():
    assert is_list(["a"]) is True
    assert is_list([]) is True
    assert is_list("a") is False
    assert is_list(None) is False


def test_is_list_with_head():
    assert is_list(["pad", "1"], "pad") is True
    assert is_list(["pad", "1"], "footprint") is False
    assert is_list([], "pad") is False
    assert is_list("pad", "pad") is False


def test_get_string():
    assert get_string("hello") == "hello"
    assert get_string(["nope"]) == ""
    assert get_string(None) == ""
    assert get_string("") == ""


def test_find_child_returns_first_match():
    expr: list = [["pad", "1"], ["pad", "2"], ["at", "0", "0"]]
    assert find_child(expr, "pad") == ["pad", "1"]
    assert find_child(expr, "at") == ["at", "0", "0"]
    assert find_child(expr, "missing") is None


def test_find_all_children():
    expr: list = [["pad", "1"], ["pad", "2"], ["at", "0", "0"], ["pad", "3"]]
    pads = find_all_children(expr, "pad")
    assert len(pads) == 3
    assert all(p[0] == "pad" for p in pads)


def test_get_property():
    properties: list[list] = [
        ["property", "Reference", "J1"],
        ["property", "Value", "Conn_01x04"],
        ["property", "Footprint", "Connector_JST:JST_PH_S4B-PH-K"],
    ]
    assert get_property(properties, "Reference") == "J1"
    assert get_property(properties, "Value") == "Conn_01x04"
    assert get_property(properties, "Missing") is None


def test_get_property_skips_short_entries():
    properties: list[list] = [["property", "Reference"]]  # too short, must skip
    assert get_property(properties, "Reference") is None


# ---------------------------------------------------------------------------
# Round-trip on a realistic KiCad fragment
# ---------------------------------------------------------------------------


def test_round_trip_kicad_fragment():
    src = """
    (kicad_pcb (version 20240108)
      (footprint "Connector"
        (property "Reference" "J1")
        (property "Value" "Conn_01x02")
        (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7))
        (pad "2" thru_hole oval (at 2.54 0) (size 1.7 1.7))
      )
    )
    """
    out = parse_sexpr(src)
    assert isinstance(out, list)
    assert out[0] == "kicad_pcb"

    fp = find_child(out, "footprint")
    assert fp is not None

    props = find_all_children(fp, "property")
    assert get_property(props, "Reference") == "J1"
    assert get_property(props, "Value") == "Conn_01x02"

    pads = find_all_children(fp, "pad")
    assert len(pads) == 2
    assert pads[0][1] == "1"
    assert pads[1][1] == "2"
