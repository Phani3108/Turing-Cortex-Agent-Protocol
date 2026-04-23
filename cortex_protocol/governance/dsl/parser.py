"""Recursive-descent parser for the policy DSL.

Precedence (lowest → highest):
  or
  and
  not
  binary (compare | in | matches | startswith | endswith | contains)
  primary (literal | attribute access | call | parenthesized | list)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .lexer import LexError, Token, tokenize


# ---------------------------------------------------------------------------
# AST nodes — all frozen, Python-pickleable
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Literal:
    value: object

@dataclass(frozen=True)
class ListExpr:
    items: tuple

@dataclass(frozen=True)
class NameExpr:
    # `foo.bar.baz` → parts = ("foo", "bar", "baz")
    parts: tuple[str, ...]

@dataclass(frozen=True)
class CallExpr:
    name: str
    args: tuple

@dataclass(frozen=True)
class UnaryExpr:
    op: str       # "not"
    operand: object

@dataclass(frozen=True)
class BinaryExpr:
    op: str       # "==" | "!=" | "<" | "<=" | ">" | ">="
                  # | "and" | "or"
                  # | "in" | "not in" | "matches"
                  # | "startswith" | "endswith" | "contains"
    left: object
    right: object


class ParseError(Exception):
    def __init__(self, message: str, pos: int):
        super().__init__(f"{message} at column {pos}")
        self.pos = pos


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0

    def _peek(self, offset: int = 0) -> Token:
        return self._tokens[self._pos + offset]

    def _advance(self) -> Token:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _eat(self, kind: str, value: str | None = None) -> Token:
        tok = self._peek()
        if tok.kind != kind or (value is not None and tok.value != value):
            raise ParseError(
                f"expected {kind}{' ' + repr(value) if value else ''}, got {tok.kind} {tok.value!r}",
                tok.pos,
            )
        return self._advance()

    def parse(self):
        node = self._parse_or()
        tok = self._peek()
        if tok.kind != "EOF":
            raise ParseError(f"unexpected trailing {tok.kind} {tok.value!r}", tok.pos)
        return node

    # or
    def _parse_or(self):
        left = self._parse_and()
        while self._peek().kind == "KEYWORD" and self._peek().value == "or":
            self._advance()
            right = self._parse_and()
            left = BinaryExpr("or", left, right)
        return left

    # and
    def _parse_and(self):
        left = self._parse_not()
        while self._peek().kind == "KEYWORD" and self._peek().value == "and":
            self._advance()
            right = self._parse_not()
            left = BinaryExpr("and", left, right)
        return left

    # not
    def _parse_not(self):
        if self._peek().kind == "KEYWORD" and self._peek().value == "not":
            self._advance()
            operand = self._parse_not()
            return UnaryExpr("not", operand)
        return self._parse_binary()

    # comparison / membership / string ops — all at the same precedence;
    # at most one operator between two primary expressions.
    _COMPARE_OPS = {"==", "!=", "<", "<=", ">", ">="}
    _WORD_BINARY_OPS = {"in", "matches", "startswith", "endswith", "contains"}

    def _parse_binary(self):
        left = self._parse_unary_primary()
        tok = self._peek()

        if tok.kind == "OP" and tok.value in self._COMPARE_OPS:
            op = self._advance().value
            right = self._parse_unary_primary()
            return BinaryExpr(op, left, right)

        if tok.kind == "KEYWORD" and tok.value in self._WORD_BINARY_OPS:
            op = self._advance().value
            right = self._parse_unary_primary()
            return BinaryExpr(op, left, right)

        # `not in` — special-case: not-then-in
        if tok.kind == "KEYWORD" and tok.value == "not":
            save = self._pos
            self._advance()
            if self._peek().kind == "KEYWORD" and self._peek().value == "in":
                self._advance()
                right = self._parse_unary_primary()
                return BinaryExpr("not in", left, right)
            self._pos = save  # rewind; this `not` belongs upstream
        return left

    def _parse_unary_primary(self):
        # A primary or a `not primary` (for nested `not`) — but `not`
        # lives in the dedicated level; here we just forward.
        return self._parse_primary()

    # primary
    def _parse_primary(self):
        tok = self._peek()

        if tok.kind == "NUMBER":
            self._advance()
            value: object
            if "." in tok.value:
                value = float(tok.value)
            else:
                value = int(tok.value)
            return Literal(value)

        if tok.kind == "STRING":
            self._advance()
            return Literal(tok.value)

        if tok.kind == "KEYWORD" and tok.value in {"true", "false", "null"}:
            self._advance()
            return Literal({"true": True, "false": False, "null": None}[tok.value])

        if tok.kind == "LBRACK":
            self._advance()
            items = []
            if self._peek().kind != "RBRACK":
                items.append(self._parse_or())
                while self._peek().kind == "COMMA":
                    self._advance()
                    items.append(self._parse_or())
            self._eat("RBRACK")
            return ListExpr(tuple(items))

        if tok.kind == "LPAREN":
            self._advance()
            inner = self._parse_or()
            self._eat("RPAREN")
            return inner

        if tok.kind == "IDENT":
            head = self._advance().value
            # function call?
            if self._peek().kind == "LPAREN":
                self._advance()
                args = []
                if self._peek().kind != "RPAREN":
                    args.append(self._parse_or())
                    while self._peek().kind == "COMMA":
                        self._advance()
                        args.append(self._parse_or())
                self._eat("RPAREN")
                return CallExpr(head, tuple(args))
            # attribute access chain?
            parts = [head]
            while self._peek().kind == "DOT":
                self._advance()
                next_tok = self._eat("IDENT")
                parts.append(next_tok.value)
            return NameExpr(tuple(parts))

        raise ParseError(f"unexpected token {tok.kind} {tok.value!r}", tok.pos)


def parse(source: str):
    tokens = tokenize(source)
    return _Parser(tokens).parse()
