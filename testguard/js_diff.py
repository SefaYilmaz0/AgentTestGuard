"""JavaScript and TypeScript Test Cheat Detector for TestGuard.

Provides pure Python, zero-dependency AST/lexical cheat detection for modern
JS/TS test frameworks (Vitest, Jest, Playwright, Mocha).
Detects:
- Test skips (it.skip, test.skip, describe.skip, xit, xtest, xdescribe)
- Assertion drops (expect, assert count decreases or removed test blocks)
- Exception swallowing in try/catch blocks
- Test literal extraction for anti-hardcoding defense
"""

import re
from dataclasses import dataclass
from typing import Any, Optional, Union

from testguard.models import Violation, ViolationType

IGNORED_LITERALS: set[Any] = {
    "", " ", "true", "false", "none", "null", "undefined",
    0, 1, -1, True, False, None,
}

JS_TS_EXTENSIONS = (
    ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
)

SKIP_KEYWORDS = {"it", "test", "describe", "context", "suite"}
XSKIP_KEYWORDS = {"xit", "xtest", "xdescribe", "xcontext"}


@dataclass
class JsToken:
    type: str
    value: str
    line_no: int
    col: int


TOKEN_SPEC = [
    ("COMMENT_LINE", r"//[^\r\n]*"),
    ("COMMENT_BLOCK", r"/\*[\s\S]*?\*/"),
    ("STRING_DOUBLE", r'"(?:\\.|[^"\\])*"'),
    ("STRING_SINGLE", r"'(?:\\.|[^\'\\])*'"),
    ("STRING_TEMPLATE", r"`(?:\\.|[^`\\])*`"),
    ("NUMBER", r"\b0x[0-9a-fA-F]+\b|\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b"),
    ("IDENT", r"[a-zA-Z_$][a-zA-Z0-9_$]*"),
    ("PUNCT", r"[{}\(\)\[\]\.,;:?]"),
    ("NEWLINE", r"\r?\n"),
    ("WS", r"[ \t]+"),
    ("OTHER", r"[^\s\w{}\(\)\[\]\.,;:?]+"),
]

TOKEN_REGEX = re.compile("|".join(f"(?P<{name}>{pattern})" for name, pattern in TOKEN_SPEC))


def _tokenize(code: str) -> list[JsToken]:
    """Tokenize JS/TS source code into tokens preserving exact line and column numbers."""
    tokens: list[JsToken] = []
    line_no = 1
    col = 1

    for match in TOKEN_REGEX.finditer(code):
        tok_type = match.lastgroup or "OTHER"
        val = match.group(0)

        tokens.append(JsToken(type=tok_type, value=val, line_no=line_no, col=col))

        num_newlines = val.count("\n")
        if num_newlines > 0:
            line_no += num_newlines
            last_nl_pos = val.rfind("\n")
            col = len(val) - last_nl_pos
        else:
            col += len(val)

    return tokens


def _unquote_str(raw: str) -> str:
    """Remove quotes and unescape common escape sequences."""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'", "`"):
        inner = raw[1:-1]
        inner = (
            inner.replace(r"\\", "\\")
            .replace(r'\"', '"')
            .replace(r"\'", "'")
            .replace(r"\`", "`")
            .replace(r"\n", "\n")
            .replace(r"\r", "\r")
            .replace(r"\t", "\t")
        )
        return inner
    return raw


def extract_js_test_literals(code: str) -> set[Union[str, int, float]]:
    """Extract string and numeric constants from JS/TS test code for anti-hardcoding defense."""
    literals: set[Union[str, int, float]] = set()
    tokens = _tokenize(code)

    for tok in tokens:
        if tok.type in ("COMMENT_LINE", "COMMENT_BLOCK"):
            continue

        if tok.type in ("STRING_DOUBLE", "STRING_SINGLE"):
            val = _unquote_str(tok.value).strip()
            if len(val) >= 3 and val.lower() not in IGNORED_LITERALS:
                literals.add(val)

        elif tok.type == "STRING_TEMPLATE":
            raw_inner = tok.value[1:-1] if len(tok.value) >= 2 else ""
            parts = re.split(r"\$\{[^}]*\}", raw_inner)
            for part in parts:
                val = _unquote_str(f"`{part}`").strip()
                if len(val) >= 3 and val.lower() not in IGNORED_LITERALS:
                    literals.add(val)

        elif tok.type == "NUMBER":
            try:
                num: Union[int, float]
                if tok.value.startswith(("0x", "0X")):
                    num = int(tok.value, 16)
                elif "." in tok.value or "e" in tok.value or "E" in tok.value:
                    num = float(tok.value)
                else:
                    num = int(tok.value)

                if num not in IGNORED_LITERALS:
                    literals.add(num)
            except ValueError:
                pass

    return literals


@dataclass
class _JsTestBlock:
    full_name: str
    short_name: str
    line_no: int
    is_describe: bool
    assertions_count: int


def _count_assertions_in_tokens(tokens: list[JsToken]) -> int:
    """Count expect(...) and assert(...) assertion calls within a token sequence."""
    count = 0
    n = len(tokens)
    i = 0
    while i < n:
        tok = tokens[i]
        # expect(...)
        if tok.type == "IDENT" and tok.value == "expect":
            if i + 1 < n and tokens[i + 1].value == "(":
                count += 1
                i += 2
                continue
        # assert(...) or assert.equal(...) etc.
        elif tok.type == "IDENT" and tok.value == "assert":
            if i + 1 < n and tokens[i + 1].value == "(":
                count += 1
                i += 2
                continue
            elif i + 3 < n and tokens[i + 1].value == "." and tokens[i + 2].type == "IDENT" and tokens[i + 3].value == "(":
                count += 1
                i += 4
                continue
        i += 1
    return count


def _find_matching_brace(tokens: list[JsToken], start_idx: int) -> int:
    """Given tokens[start_idx] == '{', return the index of matching '}', or len(tokens)."""
    depth = 0
    for idx in range(start_idx, len(tokens)):
        if tokens[idx].value == "{":
            depth += 1
        elif tokens[idx].value == "}":
            depth -= 1
            if depth == 0:
                return idx
    return len(tokens)


def _find_matching_paren(tokens: list[JsToken], start_idx: int) -> int:
    """Given tokens[start_idx] == '(', return the index of matching ')', or len(tokens)."""
    depth = 0
    for idx in range(start_idx, len(tokens)):
        if tokens[idx].value == "(":
            depth += 1
        elif tokens[idx].value == ")":
            depth -= 1
            if depth == 0:
                return idx
    return len(tokens)


def _find_callback_body(toks: list[JsToken], open_paren_idx: int, close_paren_idx: int) -> Optional[list[JsToken]]:
    """Locate the tokens of the callback body passed to a test or describe call.

    Handles:
    - Arrow functions with destructuring or options: test('name', async ({ page }) => { ... })
    - Regular functions: test('name', function({ page }) { ... })
    - Expression-body arrow functions: test('name', () => expect(1).toBe(1))
    """
    # 1. Look for arrow function '=>'
    arrow_idx = None
    for k in range(open_paren_idx + 1, close_paren_idx):
        if toks[k].value == "=>":
            arrow_idx = k
            break

    if arrow_idx is not None:
        brace_start = None
        for k in range(arrow_idx + 1, close_paren_idx):
            if toks[k].value == "{":
                brace_start = k
                break

        if brace_start is not None:
            brace_end = _find_matching_brace(toks, brace_start)
            return toks[brace_start + 1:brace_end]
        else:
            return toks[arrow_idx + 1:close_paren_idx]

    # 2. Look for regular function 'function'
    func_idx = None
    for k in range(open_paren_idx + 1, close_paren_idx):
        if toks[k].type == "IDENT" and toks[k].value == "function":
            func_idx = k
            break

    if func_idx is not None:
        param_open = None
        for k in range(func_idx + 1, close_paren_idx):
            if toks[k].value == "(":
                param_open = k
                break

        search_start = func_idx + 1
        if param_open is not None:
            param_close = _find_matching_paren(toks, param_open)
            search_start = param_close + 1

        brace_start = None
        for k in range(search_start, close_paren_idx):
            if toks[k].value == "{":
                brace_start = k
                break

        if brace_start is not None:
            brace_end = _find_matching_brace(toks, brace_start)
            return toks[brace_start + 1:brace_end]

    # 3. Fallback: find any block '{ ... }'
    brace_start = None
    for k in range(open_paren_idx + 1, close_paren_idx):
        if toks[k].value == "{":
            brace_start = k
            break

    if brace_start is not None:
        brace_end = _find_matching_brace(toks, brace_start)
        return toks[brace_start + 1:brace_end]

    return None


def _parse_test_blocks(code: str) -> list[_JsTestBlock]:
    """Parse test suites and individual test cases, counting assertions within each block."""
    all_tokens = _tokenize(code)
    tokens = [
        t for t in all_tokens
        if t.type not in ("WS", "NEWLINE", "COMMENT_LINE", "COMMENT_BLOCK")
    ]

    blocks: list[_JsTestBlock] = []

    def walk_suite(toks: list[JsToken], suite_stack: list[str]) -> None:
        n = len(toks)
        i = 0
        while i < n:
            tok = toks[i]

            # Ensure not preceded by '.' (e.g. obj.test)
            if i > 0 and toks[i - 1].value == ".":
                i += 1
                continue

            is_skip_keyword = tok.value in SKIP_KEYWORDS
            is_xskip = tok.value in XSKIP_KEYWORDS

            if is_skip_keyword or is_xskip:
                line_no = tok.line_no

                # Collect method chain: e.g. test.describe, test.describe.skip, it.skip, test.only
                curr = i + 1
                chain = [tok.value]
                while is_skip_keyword and curr + 1 < n and toks[curr].value == "." and toks[curr + 1].type == "IDENT":
                    chain.append(toks[curr + 1].value)
                    curr += 2

                is_describe_suite = (
                    "describe" in chain
                    or "context" in chain
                    or "suite" in chain
                    or tok.value == "xdescribe"
                )
                target_kind = "describe" if is_describe_suite else "test"

                if curr < n and toks[curr].value == "(":
                    open_paren_idx = curr
                    close_paren_idx = _find_matching_paren(toks, open_paren_idx)

                    # Extract title from first string argument
                    title = ".".join(chain)
                    arg_idx = open_paren_idx + 1
                    if arg_idx < close_paren_idx and toks[arg_idx].type in ("STRING_DOUBLE", "STRING_SINGLE", "STRING_TEMPLATE"):
                        title = _unquote_str(toks[arg_idx].value)

                    # Locate callback body using _find_callback_body
                    body_toks = _find_callback_body(toks, open_paren_idx, close_paren_idx)

                    if body_toks is not None:
                        full_name = f"{' > '.join(suite_stack)} > {title}" if suite_stack else title

                        if target_kind == "describe":
                            walk_suite(body_toks, suite_stack + [title])
                        else:
                            assertions = _count_assertions_in_tokens(body_toks)
                            blocks.append(_JsTestBlock(
                                full_name=full_name,
                                short_name=title,
                                line_no=line_no,
                                is_describe=False,
                                assertions_count=assertions,
                            ))

                        i = close_paren_idx + 1
                        continue

            i += 1

    walk_suite(tokens, [])
    return blocks


def _detect_skips(tokens: list[JsToken], file_path: str) -> list[Violation]:
    """Detect test.skip, it.skip, describe.skip, test.describe.skip, xit, xtest, xdescribe calls."""
    violations: list[Violation] = []
    n = len(tokens)
    i = 0

    while i < n:
        tok = tokens[i]

        if i > 0 and tokens[i - 1].value == ".":
            i += 1
            continue

        if tok.value in SKIP_KEYWORDS:
            curr = i + 1
            chain = [tok.value]
            while curr + 1 < n and tokens[curr].value == "." and tokens[curr + 1].type == "IDENT":
                chain.append(tokens[curr + 1].value)
                curr += 2

            if "skip" in chain and curr < n and tokens[curr].value == "(":
                open_paren_idx = curr
                close_paren_idx = _find_matching_paren(tokens, open_paren_idx)
                call_repr = ".".join(chain)
                title = call_repr
                arg_idx = open_paren_idx + 1
                if arg_idx < close_paren_idx and tokens[arg_idx].type in ("STRING_DOUBLE", "STRING_SINGLE", "STRING_TEMPLATE"):
                    title = _unquote_str(tokens[arg_idx].value)

                violations.append(Violation(
                    type=ViolationType.TEST_SKIPPED,
                    file_path=file_path,
                    line_number=tok.line_no,
                    symbol_name=title,
                    message=f"Test '{title}' skipped with {call_repr}",
                ))
                i = close_paren_idx + 1
                continue

        elif tok.value in XSKIP_KEYWORDS:
            if i + 1 < n and tokens[i + 1].value == "(":
                open_paren_idx = i + 1
                close_paren_idx = _find_matching_paren(tokens, open_paren_idx)
                title = tok.value
                arg_idx = open_paren_idx + 1
                if arg_idx < close_paren_idx and tokens[arg_idx].type in ("STRING_DOUBLE", "STRING_SINGLE", "STRING_TEMPLATE"):
                    title = _unquote_str(tokens[arg_idx].value)

                violations.append(Violation(
                    type=ViolationType.TEST_SKIPPED,
                    file_path=file_path,
                    line_number=tok.line_no,
                    symbol_name=title,
                    message=f"Test '{title}' skipped with {tok.value}",
                ))
                i = close_paren_idx + 1
                continue

        i += 1

    return violations


def _detect_exception_swallowing(
    tokens: list[JsToken], file_path: str, test_blocks: list[_JsTestBlock]
) -> list[Violation]:
    """Detect empty or silent catch blocks that swallow test failures."""
    violations: list[Violation] = []
    n = len(tokens)
    i = 0

    while i < n:
        tok = tokens[i]

        if tok.type == "IDENT" and tok.value == "catch":
            # Exclude promise .catch(...)
            if i > 0 and tokens[i - 1].value == ".":
                i += 1
                continue

            curr = i + 1
            # Optional catch (err) parameter
            if curr < n and tokens[curr].value == "(":
                curr = _find_matching_paren(tokens, curr) + 1

            if curr < n and tokens[curr].value == "{":
                brace_start = curr
                brace_end = _find_matching_brace(tokens, brace_start)
                body_tokens = tokens[brace_start + 1:brace_end]

                # Check if catch body contains throw, expect, or assert
                has_rethrow_or_assert = False
                for b_tok in body_tokens:
                    if b_tok.type == "IDENT":
                        if b_tok.value in ("throw", "expect", "assert"):
                            has_rethrow_or_assert = True
                            break

                if not has_rethrow_or_assert:
                    # Find enclosing test block if any
                    enclosing_symbol: Optional[str] = None
                    for tb in test_blocks:
                        if tb.line_no <= tok.line_no:
                            enclosing_symbol = tb.short_name

                    violations.append(Violation(
                        type=ViolationType.EXCEPTION_SWALLOWED,
                        file_path=file_path,
                        line_number=tok.line_no,
                        symbol_name=enclosing_symbol,
                        message="Exception swallowed in catch block",
                    ))

                i = brace_end + 1
                continue

        i += 1

    return violations


def analyze_js_test_code(code: str, file_path: str) -> list[Violation]:
    """Analyze a single JS/TS test file for skips and swallowed exceptions."""
    all_tokens = _tokenize(code)
    filtered_tokens = [
        t for t in all_tokens
        if t.type not in ("WS", "NEWLINE", "COMMENT_LINE", "COMMENT_BLOCK")
    ]

    test_blocks = _parse_test_blocks(code)
    violations: list[Violation] = []

    violations.extend(_detect_skips(filtered_tokens, file_path))
    violations.extend(_detect_exception_swallowing(filtered_tokens, file_path, test_blocks))

    return violations


def analyze_js_test_diff(base_code: str, head_code: str, file_path: str) -> list[Violation]:
    """Analyze changes between base and head JS/TS test code for cheating behaviors."""
    violations = analyze_js_test_code(head_code, file_path)

    base_blocks = _parse_test_blocks(base_code)
    head_blocks = _parse_test_blocks(head_code)

    head_by_full = {tb.full_name: tb for tb in head_blocks}
    head_by_short = {tb.short_name: tb for tb in head_blocks}

    for base_block in base_blocks:
        match_block: Optional[_JsTestBlock] = None
        if base_block.full_name in head_by_full:
            match_block = head_by_full[base_block.full_name]
        elif base_block.short_name in head_by_short:
            match_block = head_by_short[base_block.short_name]

        if match_block is not None:
            if match_block.assertions_count < base_block.assertions_count:
                violations.append(Violation(
                    type=ViolationType.ASSERTION_REMOVED,
                    file_path=file_path,
                    line_number=match_block.line_no,
                    symbol_name=base_block.short_name,
                    message=f"Assertion count decreased in '{base_block.short_name}': {base_block.assertions_count} -> {match_block.assertions_count}",
                    details={
                        "base_count": base_block.assertions_count,
                        "head_count": match_block.assertions_count,
                    },
                ))
        else:
            violations.append(Violation(
                type=ViolationType.ASSERTION_REMOVED,
                file_path=file_path,
                line_number=None,
                symbol_name=base_block.short_name,
                message=f"Test '{base_block.short_name}' was removed entirely",
                details={
                    "base_count": base_block.assertions_count,
                    "head_count": 0,
                },
            ))

    # Global fallback if no blocks detected (flat test script)
    if not base_blocks:
        base_tokens = [
            t for t in _tokenize(base_code)
            if t.type not in ("WS", "NEWLINE", "COMMENT_LINE", "COMMENT_BLOCK")
        ]
        head_tokens = [
            t for t in _tokenize(head_code)
            if t.type not in ("WS", "NEWLINE", "COMMENT_LINE", "COMMENT_BLOCK")
        ]
        base_assertions = _count_assertions_in_tokens(base_tokens)
        head_assertions = _count_assertions_in_tokens(head_tokens)

        if head_assertions < base_assertions:
            violations.append(Violation(
                type=ViolationType.ASSERTION_REMOVED,
                file_path=file_path,
                line_number=1,
                symbol_name=None,
                message=f"Assertion count decreased: {base_assertions} -> {head_assertions}",
                details={"base_count": base_assertions, "head_count": head_assertions},
            ))

    return violations
