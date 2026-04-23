"""Tokenizer for the policy DSL."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator


KEYWORDS = {
    "and", "or", "not", "in", "matches", "startswith", "endswith", "contains",
    "true", "false", "null",
}


@dataclass
class Token:
    kind: str
    value: str
    pos: int


class LexError(Exception):
    def __init__(self, message: str, pos: int):
        super().__init__(f"{message} at column {pos}")
        self.pos = pos


_SINGLE_CHAR = {
    "(": "LPAREN", ")": "RPAREN",
    "[": "LBRACK", "]": "RBRACK",
    ",": "COMMA",  ".": "DOT",
}


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]

        if ch.isspace():
            i += 1
            continue

        # Multi-char operators: ==, !=, <=, >=
        if ch in "=!<>":
            if i + 1 < n and source[i + 1] == "=":
                tokens.append(Token("OP", ch + "=", i))
                i += 2
                continue
            if ch in "<>":
                tokens.append(Token("OP", ch, i))
                i += 1
                continue
            raise LexError(f"unexpected '{ch}'", i)

        if ch in _SINGLE_CHAR:
            tokens.append(Token(_SINGLE_CHAR[ch], ch, i))
            i += 1
            continue

        # Numbers (int + float)
        if ch.isdigit() or (ch == "-" and i + 1 < n and source[i + 1].isdigit()):
            j = i + 1
            while j < n and (source[j].isdigit() or source[j] == "."):
                j += 1
            tokens.append(Token("NUMBER", source[i:j], i))
            i = j
            continue

        # Strings (single or double quoted). No interpolation.
        if ch in ("'", '"'):
            quote = ch
            j = i + 1
            out = []
            while j < n and source[j] != quote:
                if source[j] == "\\" and j + 1 < n:
                    escape = source[j + 1]
                    out.append({
                        "n": "\n", "t": "\t", "r": "\r",
                        "\\": "\\", "'": "'", '"': '"',
                    }.get(escape, escape))
                    j += 2
                    continue
                out.append(source[j])
                j += 1
            if j >= n:
                raise LexError("unterminated string", i)
            tokens.append(Token("STRING", "".join(out), i))
            i = j + 1
            continue

        # Identifiers + keywords
        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            word = source[i:j]
            if word in KEYWORDS:
                tokens.append(Token("KEYWORD", word, i))
            else:
                tokens.append(Token("IDENT", word, i))
            i = j
            continue

        raise LexError(f"unexpected character {ch!r}", i)

    tokens.append(Token("EOF", "", n))
    return tokens
