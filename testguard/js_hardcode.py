"""Anti-Hardcode detector for JavaScript / TypeScript source files.

Token-based (zero dependency) counterpart of the Python detector. Flags
branches that compare against a literal copied from the tests and return a
constant: `if (x === "user_123") return 42`, ternaries, `switch/case` and
object lookup tables keyed by test literals.
"""

import re
from typing import Any, Optional

from testguard.js_diff import IGNORED_LITERALS, JsToken, _tokenize, _unquote_str
from testguard.models import Violation, ViolationType

_CONTROL = {"if", "for", "while", "switch", "catch", "with", "function", "return"}
_COMPARE_OPS = {"==", "===", "!=", "!==", "<=", ">=", "=>"}
_CONST_IDENTS = {"true", "false", "null", "undefined", "NaN", "Infinity"}
_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = {")", "]", "}"}


def _literal(tok: JsToken) -> Optional[Any]:
    """Python value of a string/number token, or None."""
    if tok.type in ("STRING_DOUBLE", "STRING_SINGLE"):
        return _unquote_str(tok.value).strip()
    if tok.type == "STRING_TEMPLATE":
        if "${" in tok.value:
            return None
        return _unquote_str(tok.value).strip()
    if tok.type == "NUMBER":
        try:
            if tok.value.lower().startswith("0x"):
                return int(tok.value, 16)
            if any(c in tok.value for c in ".eE"):
                return float(tok.value)
            return int(tok.value)
        except ValueError:
            return None
    return None


def _test_literal_match(tok: JsToken, test_literals: set[Any]) -> Optional[Any]:
    val = _literal(tok)
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, str) and (len(val) < 3 or val.lower() in IGNORED_LITERALS):
        return None
    if not isinstance(val, str) and val in IGNORED_LITERALS:
        return None
    return val if val in test_literals else None


def _match_close(toks: list[JsToken], i: int) -> int:
    depth = 0
    for j in range(i, len(toks)):
        v = toks[j].value
        if toks[j].type == "PUNCT" and v in _OPEN:
            depth += 1
        elif toks[j].type == "PUNCT" and v in _CLOSE:
            depth -= 1
            if depth == 0:
                return j
    return len(toks) - 1


def _match_open(toks: list[JsToken], i: int) -> int:
    depth = 0
    for j in range(i, -1, -1):
        if toks[j].type == "PUNCT" and toks[j].value in _CLOSE:
            depth += 1
        elif toks[j].type == "PUNCT" and toks[j].value in _OPEN:
            depth -= 1
            if depth == 0:
                return j
    return 0


def _is_hardcoded_expr(expr: list[JsToken], test_literals: set[Any]) -> bool:
    """Empty, literal-only, or wrapping a test literal (e.g. `Result("session_xyz")`)."""
    if not expr:
        return True
    has_test_literal = any(_test_literal_match(t, test_literals) is not None for t in expr)
    if has_test_literal:
        return True
    for t in expr:
        if t.type == "IDENT" and t.value not in _CONST_IDENTS:
            return False
    return True


def _function_names(toks: list[JsToken]) -> list[str]:
    """Enclosing function name for each token index (best effort)."""
    result = [""] * len(toks)
    stack: list[tuple[str, bool]] = []  # (name, is_function)
    for i, t in enumerate(toks):
        if t.type == "PUNCT" and t.value == "{":
            name: Optional[str] = None
            j = i - 1
            if j >= 0 and toks[j].value == ")":
                o = _match_open(toks, j)
                k = o - 1
                if k >= 0 and toks[k].type == "IDENT" and toks[k].value not in _CONTROL:
                    name = toks[k].value
                elif k >= 0 and toks[k].value == "=" and k >= 1 and toks[k - 1].type == "IDENT":
                    name = toks[k - 1].value
            elif j >= 0 and toks[j].value == "=>":
                k = j - 1
                if k >= 0 and toks[k].value == ")":
                    k = _match_open(toks, k) - 1
                if k >= 1 and toks[k].value == "=" and toks[k - 1].type == "IDENT":
                    name = toks[k - 1].value
                elif k >= 0:
                    name = "<anonymous>"
            stack.append((name or "", name is not None))
        elif t.type == "PUNCT" and t.value == "}":
            if stack:
                stack.pop()
        enclosing = next((n for n, is_fn in reversed(stack) if is_fn and n), "<module>")
        result[i] = enclosing
    return result


def _return_exprs(toks: list[JsToken]) -> list[list[JsToken]]:
    """Expressions following `return` at any depth inside toks (nested functions excluded)."""
    exprs: list[list[JsToken]] = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.type == "IDENT" and t.value == "function":
            # skip nested function body
            j = i
            while j < len(toks) and toks[j].value != "{":
                j += 1
            i = _match_close(toks, j) + 1 if j < len(toks) else len(toks)
            continue
        if t.type == "IDENT" and t.value == "return":
            j = i + 1
            depth = 0
            expr: list[JsToken] = []
            while j < len(toks):
                v = toks[j]
                if v.type == "PUNCT" and v.value in _OPEN:
                    depth += 1
                elif v.type == "PUNCT" and v.value in _CLOSE:
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and v.type == "PUNCT" and v.value == ";":
                    break
                elif depth == 0 and v.line_no != t.line_no and not expr:
                    break
                elif depth == 0 and v.line_no != t.line_no and expr and expr[-1].type != "OTHER":
                    break
                expr.append(v)
                j += 1
            exprs.append(expr)
            i = j
            continue
        i += 1
    return exprs


def _single_statement(toks: list[JsToken], start: int) -> list[JsToken]:
    out: list[JsToken] = []
    depth = 0
    j = start
    while j < len(toks):
        v = toks[j]
        if v.type == "PUNCT" and v.value in _OPEN:
            depth += 1
        elif v.type == "PUNCT" and v.value in _CLOSE:
            if depth == 0:
                break
            depth -= 1
        elif depth == 0 and v.type == "PUNCT" and v.value == ";":
            out.append(v)
            break
        out.append(v)
        j += 1
    return out


def _violation(file_path: str, line: int, func: str, matched: list[Any], kind: str) -> Violation:
    shown = ", ".join(repr(x) for x in sorted(matched, key=str))
    return Violation(
        type=ViolationType.HARDCODED_CHEAT,
        file_path=file_path,
        line_number=line,
        symbol_name=func,
        message=f"Hardcoded {kind} for test literal(s) {shown} in '{func}'",
        details={"matched_literals": sorted(matched, key=str)},
    )


def _inline_constant_aliases(toks: list[JsToken]) -> list[JsToken]:
    """Replace single-assignment `const NAME = <literal>;` identifiers by their literal."""
    declared: dict[str, JsToken] = {}
    assign_count: dict[str, int] = {}
    for i, t in enumerate(toks):
        if t.type != "IDENT" or i + 1 >= len(toks) or toks[i + 1].value not in ("=", "+=", "-=", "*=", "/="):
            continue
        if i > 0 and toks[i - 1].value == ".":
            continue
        assign_count[t.value] = assign_count.get(t.value, 0) + 1
        if (
            toks[i + 1].value == "="
            and i + 2 < len(toks)
            and _literal(toks[i + 2]) is not None
            and (i + 3 >= len(toks) or toks[i + 3].value in (";", ",") or toks[i + 3].line_no != toks[i + 2].line_no)
        ):
            declared[t.value] = toks[i + 2]
    aliases = {n: lit for n, lit in declared.items() if assign_count.get(n) == 1}
    if not aliases:
        return toks
    out: list[JsToken] = []
    for i, t in enumerate(toks):
        is_ref = (
            t.type == "IDENT" and t.value in aliases
            and not (i > 0 and toks[i - 1].value == ".")
            and not (i + 1 < len(toks) and toks[i + 1].value in ("=", ":"))
        )
        if is_ref:
            lit = aliases[t.value]
            out.append(JsToken(type=lit.type, value=lit.value, line_no=t.line_no, col=t.col))
        else:
            out.append(t)
    return out


def detect_js_hardcoded_cheats(src_code: str, test_literals: set[Any], file_path: str = "") -> list[Violation]:
    """Analyze JS/TS source for branches / tables that hardcode test literals."""
    if not test_literals:
        return []
    toks = [
        t for t in _tokenize(src_code)
        if t.type not in ("WS", "NEWLINE", "COMMENT_LINE", "COMMENT_BLOCK")
    ]
    toks = _inline_constant_aliases(toks)
    funcs = _function_names(toks)
    violations: list[Violation] = []
    seen: set[tuple[int, str]] = set()

    def add(line: int, func: str, matched: list[Any], kind: str) -> None:
        key = (line, kind)
        if key in seen:
            return
        seen.add(key)
        violations.append(_violation(file_path, line, func, matched, kind))

    indexed_names = {
        toks[i].value for i in range(len(toks) - 1)
        if toks[i].type == "IDENT" and toks[i + 1].type == "PUNCT" and toks[i + 1].value == "["
    }

    for i, t in enumerate(toks):
        # if (cond) <body>
        if t.type == "IDENT" and t.value == "if" and i + 1 < len(toks) and toks[i + 1].value == "(":
            close = _match_close(toks, i + 1)
            matched = [m for m in (_test_literal_match(c, test_literals) for c in toks[i + 2:close]) if m is not None]
            if matched and close + 1 < len(toks):
                if toks[close + 1].value == "{":
                    end = _match_close(toks, close + 1)
                    body = toks[close + 2:end]
                else:
                    body = _single_statement(toks, close + 1)
                if any(_is_hardcoded_expr(e, test_literals) for e in _return_exprs(body)):
                    add(t.line_no, funcs[i], matched, "check")

        # switch case <literal>: ... return ...
        elif t.type == "IDENT" and t.value == "case" and i + 2 < len(toks):
            m = _test_literal_match(toks[i + 1], test_literals)
            if m is not None and toks[i + 2].value == ":":
                j, depth, body = i + 3, 0, []
                while j < len(toks):
                    v = toks[j]
                    if v.type == "PUNCT" and v.value in _OPEN:
                        depth += 1
                    elif v.type == "PUNCT" and v.value in _CLOSE:
                        if depth == 0:
                            break
                        depth -= 1
                    elif depth == 0 and v.type == "IDENT" and v.value in ("case", "default"):
                        break
                    body.append(v)
                    j += 1
                if any(_is_hardcoded_expr(e, test_literals) for e in _return_exprs(body)):
                    add(t.line_no, funcs[i], [m], "case")

        # cond ? a : b
        elif (
            t.type == "PUNCT" and t.value == "?"
            and not (i + 1 < len(toks) and toks[i + 1].value in ("?", "."))
            and not (i > 0 and toks[i - 1].value == "?")
        ):
            # condition: walk back to a statement/argument boundary
            j, depth, cond = i - 1, 0, []
            while j >= 0:
                v = toks[j]
                if v.type == "PUNCT" and v.value in _CLOSE:
                    depth += 1
                elif v.type == "PUNCT" and v.value in _OPEN:
                    if depth == 0:
                        break
                    depth -= 1
                elif depth == 0 and (
                    (v.type == "PUNCT" and v.value in (";", ",", ":"))
                    or (v.type == "IDENT" and v.value == "return")
                    or (v.type == "OTHER" and v.value.endswith("=") and v.value not in _COMPARE_OPS)
                    or (v.type == "OTHER" and v.value == "=>")
                ):
                    break
                cond.append(v)
                j -= 1
            matched = [m for m in (_test_literal_match(c, test_literals) for c in cond) if m is not None]
            if matched:
                # branches: up to matching ':' then to end of expression
                j, depth, nested, cons = i + 1, 0, 0, []
                while j < len(toks):
                    v = toks[j]
                    if v.type == "PUNCT" and v.value in _OPEN:
                        depth += 1
                    elif v.type == "PUNCT" and v.value in _CLOSE:
                        if depth == 0:
                            break
                        depth -= 1
                    elif depth == 0 and v.type == "PUNCT" and v.value == "?":
                        nested += 1
                    elif depth == 0 and v.type == "PUNCT" and v.value == ":":
                        if nested == 0:
                            break
                        nested -= 1
                    cons.append(v)
                    j += 1
                alt = _single_statement(toks, j + 1)
                alt = [a for a in alt if not (a.type == "PUNCT" and a.value == ";")]
                if _is_hardcoded_expr(cons, test_literals) or _is_hardcoded_expr(alt, test_literals):
                    add(t.line_no, funcs[i], matched, "ternary check")

        # lookup table: { "user_123": 42, ... }[x]  or  const T = {...}; T[x]
        elif t.type == "PUNCT" and t.value == "{":
            close = _match_close(toks, i)
            used = False
            nxt = toks[close + 1] if close + 1 < len(toks) else None
            if nxt is not None and nxt.value == "[":
                used = True
            elif nxt is not None and nxt.value == ")" and close + 2 < len(toks) and toks[close + 2].value == "[":
                used = True
            elif i >= 2 and toks[i - 1].value == "=" and toks[i - 2].type == "IDENT" and toks[i - 2].value in indexed_names:
                used = True
            if not used:
                continue
            entries: list[list[JsToken]] = [[]]
            depth = 0
            for v in toks[i + 1:close]:
                if v.type == "PUNCT" and v.value in _OPEN:
                    depth += 1
                elif v.type == "PUNCT" and v.value in _CLOSE:
                    depth -= 1
                if depth == 0 and v.type == "PUNCT" and v.value == ",":
                    entries.append([])
                else:
                    entries[-1].append(v)
            entries = [e for e in entries if e]
            matched_keys: list[Any] = []
            ok = bool(entries)
            for e in entries:
                if len(e) < 3 or e[1].value != ":":
                    ok = False
                    break
                if not _is_hardcoded_expr(e[2:], test_literals):
                    ok = False
                    break
                key = _test_literal_match(e[0], test_literals)
                if key is None and e[0].type == "IDENT" and e[0].value in test_literals:
                    key = e[0].value
                if key is not None:
                    matched_keys.append(key)
            if ok and matched_keys:
                add(t.line_no, funcs[i], matched_keys, "lookup table")

    return violations
