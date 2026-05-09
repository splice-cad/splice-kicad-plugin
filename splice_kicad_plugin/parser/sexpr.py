"""S-expression tokenizer and tree walker.

Direct port of ``kicadParser.ts:17-188`` from the splice frontend. Pure functions,
no third-party deps. Behavior is preserved as closely as reasonable so that the
cross-language parity tests in ``RFC-003e`` §3 produce identical output.

A note on a quirk preserved from the TS source: the tokenizer stores quoted
strings with their surrounding quotes intact (``'"value"'``) so the parser can
distinguish them from bare atoms at walk time. The walker strips the surrounding
quotes on emit. The end result is that ``"foo"`` in the input parses to the
string ``foo`` — same as if it were a bare atom — but characters that would
otherwise terminate an atom (whitespace, parens, quotes) survive inside the
quoted form.
"""

from __future__ import annotations  # PEP 563 — defers `X | None` to strings (Py 3.9 compat)

from typing import Union

from ..errors import SExprParseError

SExpr = Union[str, list["SExpr"]]


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


def tokenize(text: str) -> list[str]:
    """Tokenize an S-expression string into a flat list of tokens.

    Quoted strings are stored with their surrounding quotes (``'"value"'``)
    so the parser can distinguish them from bare atoms. Backslash escapes
    drop the backslash and emit the following character verbatim.
    """
    tokens: list[str] = []
    current = 0
    n = len(text)

    while current < n:
        char = text[current]

        # Whitespace
        if char.isspace():
            current += 1
            continue

        # Parentheses
        if char == "(" or char == ")":
            tokens.append(char)
            current += 1
            continue

        # Quoted string
        if char == '"':
            value = ""
            current += 1  # skip opening quote
            while current < n and text[current] != '"':
                if text[current] == "\\" and current + 1 < n:
                    current += 1
                    value += text[current]
                else:
                    value += text[current]
                current += 1
            current += 1  # skip closing quote
            tokens.append(f'"{value}"')
            continue

        # Atom — accumulate until whitespace, paren, or quote
        atom = ""
        while current < n and not text[current].isspace() and text[current] not in '()"':
            atom += text[current]
            current += 1
        if atom:
            tokens.append(atom)

    return tokens


# ---------------------------------------------------------------------------
# Walker
# ---------------------------------------------------------------------------


class _Cursor:
    """Mutable index into a token stream. Internal helper for ``parse_tokens``."""

    __slots__ = ("tokens", "i")

    def __init__(self, tokens: list[str]) -> None:
        self.tokens = tokens
        self.i = 0


def _walk(c: _Cursor) -> SExpr:
    if c.i >= len(c.tokens):
        return ""
    token = c.tokens[c.i]

    if token == "(":
        c.i += 1
        out: list[SExpr] = []
        while c.i < len(c.tokens) and c.tokens[c.i] != ")":
            out.append(_walk(c))
        if c.i >= len(c.tokens):
            raise SExprParseError(None, "Unexpected end of input - missing closing parenthesis")
        c.i += 1  # skip ')'
        return out

    if token == ")":
        raise SExprParseError(None, "Unexpected closing parenthesis")

    c.i += 1
    if len(token) >= 2 and token.startswith('"') and token.endswith('"'):
        return token[1:-1]
    return token or ""


def parse_tokens(tokens: list[str]) -> SExpr:
    """Parse a token stream into an S-expression tree.

    If the stream contains multiple top-level forms, they are wrapped in a list,
    matching the JS behavior at ``kicadParser.ts:106-115``.
    """
    c = _Cursor(tokens)
    result = _walk(c)

    if c.i < len(c.tokens):
        results: list[SExpr] = [result]
        while c.i < len(c.tokens):
            results.append(_walk(c))
        return results

    return result


def parse_sexpr(text: str) -> SExpr:
    """Parse an S-expression string into a tree."""
    tokens = tokenize(text)
    if not tokens:
        return []
    return parse_tokens(tokens)


# ---------------------------------------------------------------------------
# KiCad-specific tree helpers (port of kicadParser.ts:138-188)
# ---------------------------------------------------------------------------


def is_list(expr: SExpr | None, head: str | None = None) -> bool:
    """True if ``expr`` is a list and (optionally) starts with ``head``."""
    if expr is None or not isinstance(expr, list):
        return False
    if head is None:
        return True
    return len(expr) > 0 and expr[0] == head


def get_string(expr: SExpr | None) -> str:
    """Return the string value of ``expr``, or empty string for non-strings."""
    if isinstance(expr, str):
        return expr
    return ""


def find_child(expr: list[SExpr], head: str) -> list[SExpr] | None:
    """Find the first child list of ``expr`` that starts with ``head``."""
    for child in expr:
        if is_list(child, head):
            assert isinstance(child, list)  # narrowing for the type checker
            return child
    return None


def find_all_children(expr: list[SExpr], head: str) -> list[list[SExpr]]:
    """Find all child lists of ``expr`` that start with ``head``."""
    out: list[list[SExpr]] = []
    for child in expr:
        if is_list(child, head):
            assert isinstance(child, list)
            out.append(child)
    return out


def get_property(properties: list[list[SExpr]], name: str) -> str | None:
    """Return ``properties[i][2]`` for the first ``properties[i][1] == name``.

    KiCad format: ``(property "name" "value" ...)``.
    """
    for prop in properties:
        if len(prop) >= 3 and get_string(prop[1]) == name:
            return get_string(prop[2])
    return None
