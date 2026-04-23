"""Compile parsed AST into a callable predicate.

The compiled form is a closure `(ctx: dict) -> value`. For rule
evaluation we only care about boolean outcomes, but intermediate nodes
can return any JSON-like value (string, number, list, bool) — the
runtime layer applies the final truthiness check.

Design choices:
  - No arbitrary Python eval. Every operation dispatches to an explicit
    handler, so a malicious expression can't import `os` or touch
    disk.
  - `ctx` is a plain dict; attribute access (`tool_input.amount`) maps
    to nested dict/list lookups. Missing keys return `None` rather than
    raising, which keeps predicates defensive.
  - Regex is compiled lazily and cached per call site.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from .lexer import LexError
from .parser import (
    BinaryExpr,
    CallExpr,
    Literal,
    ListExpr,
    NameExpr,
    ParseError,
    UnaryExpr,
    parse,
)


class RuleError(Exception):
    """Compilation-time error in a DSL rule."""


Predicate = Callable[[dict], Any]


# ---------------------------------------------------------------------------
# Builtins — the only "functions" a rule can call.
# ---------------------------------------------------------------------------

def _fn_len(args):
    if len(args) != 1:
        raise RuleError("len() takes exactly 1 argument")
    v = args[0]
    if v is None:
        return 0
    return len(v)


def _fn_lower(args):
    if len(args) != 1:
        raise RuleError("lower() takes exactly 1 argument")
    v = args[0]
    return "" if v is None else str(v).lower()


def _fn_upper(args):
    if len(args) != 1:
        raise RuleError("upper() takes exactly 1 argument")
    v = args[0]
    return "" if v is None else str(v).upper()


def _fn_int(args):
    if len(args) != 1:
        raise RuleError("int() takes exactly 1 argument")
    v = args[0]
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


BUILTINS: dict[str, Callable[[list], Any]] = {
    "len": _fn_len,
    "lower": _fn_lower,
    "upper": _fn_upper,
    "int": _fn_int,
}


# ---------------------------------------------------------------------------
# Compilation
# ---------------------------------------------------------------------------

def compile_expression(source: str) -> Predicate:
    """Compile a DSL source string into a predicate callable."""
    try:
        ast = parse(source)
    except (LexError, ParseError) as e:
        raise RuleError(str(e)) from None
    return _compile_node(ast)


def compile_rule(rule: dict) -> "CompiledRule":
    """Compile a dict `{when, action, reason?}` into a CompiledRule."""
    when = rule.get("when")
    action = rule.get("action")
    if not when or not isinstance(when, str):
        raise RuleError("rule missing 'when' expression")
    if action not in {"deny", "require_approval", "allow"}:
        raise RuleError(f"rule has invalid action {action!r}; "
                        f"expected deny|require_approval|allow")
    predicate = compile_expression(when)
    return CompiledRule(
        when_source=when,
        action=action,
        reason=str(rule.get("reason") or ""),
        predicate=predicate,
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _compile_node(node) -> Predicate:
    if isinstance(node, Literal):
        value = node.value
        return lambda ctx, _v=value: _v

    if isinstance(node, ListExpr):
        compiled_items = [_compile_node(i) for i in node.items]
        return lambda ctx, _items=compiled_items: [fn(ctx) for fn in _items]

    if isinstance(node, NameExpr):
        parts = node.parts
        return lambda ctx, _parts=parts: _lookup(ctx, _parts)

    if isinstance(node, CallExpr):
        fn = BUILTINS.get(node.name)
        if fn is None:
            raise RuleError(f"unknown function: {node.name}()")
        compiled_args = [_compile_node(a) for a in node.args]
        return lambda ctx, _fn=fn, _args=compiled_args: _fn([f(ctx) for f in _args])

    if isinstance(node, UnaryExpr):
        operand = _compile_node(node.operand)
        if node.op == "not":
            return lambda ctx, _o=operand: not _o(ctx)
        raise RuleError(f"unknown unary operator {node.op}")

    if isinstance(node, BinaryExpr):
        return _compile_binary(node)

    raise RuleError(f"unknown AST node {type(node).__name__}")


def _lookup(ctx: dict, parts: tuple[str, ...]):
    cur: Any = ctx
    for p in parts:
        if isinstance(cur, dict):
            cur = cur.get(p)
        else:
            cur = getattr(cur, p, None)
        if cur is None:
            return None
    return cur


def _compile_binary(node: BinaryExpr) -> Predicate:
    left = _compile_node(node.left)
    right = _compile_node(node.right)
    op = node.op

    if op == "and":
        return lambda ctx: bool(left(ctx)) and bool(right(ctx))
    if op == "or":
        return lambda ctx: bool(left(ctx)) or bool(right(ctx))

    if op in {"==", "!=", "<", "<=", ">", ">="}:
        return _cmp(left, right, op)

    if op == "in":
        return lambda ctx: _in(left(ctx), right(ctx))
    if op == "not in":
        return lambda ctx: not _in(left(ctx), right(ctx))

    if op == "matches":
        return _matches(left, right)

    if op == "startswith":
        return lambda ctx: _safe_str(left(ctx)).startswith(_safe_str(right(ctx)))
    if op == "endswith":
        return lambda ctx: _safe_str(left(ctx)).endswith(_safe_str(right(ctx)))
    if op == "contains":
        return lambda ctx: _safe_str(right(ctx)) in _safe_str(left(ctx))

    raise RuleError(f"unknown binary operator {op}")


def _cmp(left: Predicate, right: Predicate, op: str) -> Predicate:
    def go(ctx):
        lv = left(ctx)
        rv = right(ctx)
        try:
            if op == "==":
                return lv == rv
            if op == "!=":
                return lv != rv
            if op == "<":
                return lv < rv
            if op == "<=":
                return lv <= rv
            if op == ">":
                return lv > rv
            if op == ">=":
                return lv >= rv
        except TypeError:
            return False
        return False
    return go


def _in(needle, haystack) -> bool:
    if haystack is None:
        return False
    try:
        return needle in haystack
    except TypeError:
        return False


def _matches(left: Predicate, right: Predicate) -> Predicate:
    cache: dict[str, re.Pattern] = {}

    def go(ctx):
        text = _safe_str(left(ctx))
        pattern = _safe_str(right(ctx))
        if not pattern:
            return False
        if pattern not in cache:
            try:
                cache[pattern] = re.compile(pattern)
            except re.error:
                return False
        return cache[pattern].search(text) is not None

    return go


def _safe_str(v) -> str:
    if v is None:
        return ""
    return str(v)


# ---------------------------------------------------------------------------
# Compiled rule wrapper — used by runtime.evaluate_rules
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass(frozen=True)
class CompiledRule:
    when_source: str
    action: str
    reason: str
    predicate: Predicate
