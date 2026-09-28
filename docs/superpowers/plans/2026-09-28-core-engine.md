# TestGuard Core Engine (Faz 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the zero-trust Phase 1 core cheat detection engine for AI-generated code, including AST diffing, anti-hardcoding heuristic, git shadow isolation, and CLI reporting.

**Architecture:** Python standard library (`ast`, `dataclasses`, `argparse`, `subprocess`) modular architecture comprising `models.py`, `ast_diff.py`, `anti_hardcode.py`, `shadow.py`, `verdict.py`, and `cli.py`.

**Tech Stack:** Python 3.10+, `unittest` (standard library), standard `ast` module, Git CLI.

## Global Constraints
- Zero external third-party runtime dependencies (standard library only for maximum portability).
- AST analysis must execute deterministically in under 50ms per test file.
- All tests run via `python -m unittest` without requiring virtual environments or pip installs.

---

### Task 1: Project Scaffolding & Core Models

**Files:**
- Create: `pyproject.toml`
- Create: `testguard/__init__.py`
- Create: `testguard/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Consumes: Python standard library (`dataclasses`, `enum`)
- Produces: `ViolationType`, `Violation`, `Verdict`, `CheckResult`, `Report` in `testguard.models`

- [ ] **Step 1: Write the failing test for models**

```python
# tests/test_models.py
import unittest
from testguard.models import ViolationType, Violation, Verdict, Report

class TestModels(unittest.TestCase):
    def test_violation_creation_and_serialization(self):
        v = Violation(
            type=ViolationType.ASSERTION_REMOVED,
            file_path="tests/test_demo.py",
            line_number=12,
            symbol_name="test_addition",
            message="Assertion count dropped from 2 to 1"
        )
        self.assertEqual(v.type, ViolationType.ASSERTION_REMOVED)
        self.assertEqual(v.line_number, 12)
        d = v.to_dict()
        self.assertEqual(d["type"], "ASSERTION_REMOVED")
        self.assertEqual(d["file_path"], "tests/test_demo.py")

    def test_report_verdict(self):
        v = Violation(
            type=ViolationType.TEST_SKIPPED,
            file_path="tests/test_demo.py",
            line_number=5,
            symbol_name="test_skip",
            message="Test skipped"
        )
        report = Report(verdict=Verdict.VETO, violations=[v], summary="Goal gaming detected")
        self.assertEqual(report.verdict, Verdict.VETO)
        self.assertFalse(report.is_passed)
        self.assertEqual(len(report.violations), 1)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_models.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'testguard'`

- [ ] **Step 3: Write minimal implementation**

Create `pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "testguard-ai"
version = "0.1.0"
description = "The Zero-Trust Anti-Cheat Gate for AI-Generated Code"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [{name = "TestGuard Contributors"}]

[project.scripts]
testguard = "testguard.cli:main"
```

Create `testguard/__init__.py`:
```python
"""TestGuard - The Zero-Trust Anti-Cheat Gate for AI-Generated Code."""
__version__ = "0.1.0"
```

Create `testguard/models.py`:
```python
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional

class ViolationType(str, Enum):
    ASSERTION_REMOVED = "ASSERTION_REMOVED"
    TEST_SKIPPED = "TEST_SKIPPED"
    EXCEPTION_SWALLOWED = "EXCEPTION_SWALLOWED"
    HARDCODED_CHEAT = "HARDCODED_CHEAT"
    SYNTAX_ERROR = "SYNTAX_ERROR"

class Verdict(str, Enum):
    PASS = "PASS"
    VETO = "VETO"

@dataclass
class Violation:
    type: ViolationType
    file_path: str
    line_number: Optional[int] = None
    symbol_name: Optional[str] = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        return d

@dataclass
class Report:
    verdict: Verdict
    violations: list[Violation] = field(default_factory=list)
    summary: str = ""
    execution_time_ms: float = 0.0

    @property
    def is_passed(self) -> bool:
        return self.verdict == Verdict.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "violations": [v.to_dict() for v in self.violations],
            "summary": self.summary,
            "execution_time_ms": self.execution_time_ms,
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_models.py`
Expected: PASS with 2 tests OK.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml testguard/__init__.py testguard/models.py tests/test_models.py
git commit -m "feat: scaffold project structure and define core data models"
```

---

### Task 2: AST Diff & Anti-Cheat Analyzer

**Files:**
- Create: `testguard/ast_diff.py`
- Test: `tests/test_ast_diff.py`

**Interfaces:**
- Consumes: `testguard.models` (`ViolationType`, `Violation`)
- Produces: `analyze_ast_diff(base_code: str, head_code: str, file_path: str) -> list[Violation]`, `analyze_test_code(head_code: str, file_path: str) -> list[Violation]`

- [ ] **Step 1: Write the failing tests for AST analysis**

```python
# tests/test_ast_diff.py
import unittest
from testguard.models import ViolationType
from testguard.ast_diff import analyze_ast_diff, analyze_test_code

class TestASTDiff(unittest.TestCase):
    def test_detects_removed_assertion(self):
        base_code = """
def test_calc():
    res = add(2, 3)
    assert res == 5
    assert res > 0
"""
        head_code = """
def test_calc():
    res = add(2, 3)
    assert res == 5
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_calc.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.ASSERTION_REMOVED)
        self.assertEqual(violations[0].symbol_name, "test_calc")

    def test_detects_added_skip_decorator(self):
        code = """
import pytest

@pytest.mark.skip(reason="Fails on AI")
def test_difficult():
    assert complex_operation() == 42
"""
        violations = analyze_test_code(code, file_path="tests/test_skip.py")
        self.assertTrue(any(v.type == ViolationType.TEST_SKIPPED for v in violations))
        self.assertEqual(violations[0].symbol_name, "test_difficult")

    def test_detects_swallowed_exception(self):
        code = """
def test_flaky():
    try:
        do_risky_call()
    except Exception:
        pass
"""
        violations = analyze_test_code(code, file_path="tests/test_swallow.py")
        self.assertTrue(any(v.type == ViolationType.EXCEPTION_SWALLOWED for v in violations))
        self.assertEqual(violations[0].symbol_name, "test_flaky")

    def test_no_violations_for_clean_modifications(self):
        base_code = "def test_ok(): assert 1 == 1"
        head_code = "def test_ok(): assert 1 == 1; assert 2 == 2"
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_clean.py")
        self.assertEqual(len(violations), 0)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_ast_diff.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'testguard.ast_diff'`

- [ ] **Step 3: Write implementation for `testguard/ast_diff.py`**

Create `testguard/ast_diff.py`:
```python
import ast
from typing import Optional
from testguard.models import Violation, ViolationType

def _count_assertions_in_node(node: ast.AST) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            count += 1
        elif isinstance(child, ast.Call):
            # Detect self.assert* or unittest assertions
            if isinstance(child.func, ast.Attribute) and child.func.attr.startswith("assert"):
                count += 1
    return count

def _has_skip_decorator(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in func_node.decorator_list:
        dec_name = ""
        if isinstance(decorator, ast.Name):
            dec_name = decorator.id
        elif isinstance(decorator, ast.Attribute):
            dec_name = decorator.attr
        elif isinstance(decorator, ast.Call):
            if isinstance(decorator.func, ast.Name):
                dec_name = decorator.func.id
            elif isinstance(decorator.func, ast.Attribute):
                dec_name = decorator.func.attr
        if any(skip_word in dec_name.lower() for skip_word in ("skip", "skipif", "xfail")):
            return True
    return False

def _find_swallowed_exceptions(func_node: ast.FunctionDef | ast.AsyncFunctionDef, file_path: str) -> list[Violation]:
    violations = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                is_pass_only = len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)
                is_empty = len(handler.body) == 0
                if is_pass_only or is_empty:
                    violations.append(Violation(
                        type=ViolationType.EXCEPTION_SWALLOWED,
                        file_path=file_path,
                        line_number=handler.lineno,
                        symbol_name=func_node.name,
                        message=f"Exception swallowed with pass in test '{func_node.name}'",
                    ))
    return violations

def _extract_test_functions(tree: ast.AST) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    functions = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_") or node.name.endswith("_test"):
                functions[node.name] = node
    return functions

def analyze_test_code(code: str, file_path: str) -> list[Violation]:
    try:
        tree = ast.parse(code, filename=file_path)
    except SyntaxError as e:
        return [Violation(
            type=ViolationType.SYNTAX_ERROR,
            file_path=file_path,
            line_number=e.lineno,
            message=f"Syntax error: {e.msg}"
        )]

    violations: list[Violation] = []
    funcs = _extract_test_functions(tree)

    for func_name, func_node in funcs.items():
        if _has_skip_decorator(func_node):
            violations.append(Violation(
                type=ViolationType.TEST_SKIPPED,
                file_path=file_path,
                line_number=func_node.lineno,
                symbol_name=func_name,
                message=f"Test '{func_name}' has skip decorator"
            ))
        violations.extend(_find_swallowed_exceptions(func_node, file_path))

    return violations

def analyze_ast_diff(base_code: str, head_code: str, file_path: str) -> list[Violation]:
    violations = analyze_test_code(head_code, file_path)

    try:
        base_tree = ast.parse(base_code, filename=file_path)
        head_tree = ast.parse(head_code, filename=file_path)
    except SyntaxError:
        return violations

    base_funcs = _extract_test_functions(base_tree)
    head_funcs = _extract_test_functions(head_tree)

    for func_name, base_node in base_funcs.items():
        base_count = _count_assertions_in_node(base_node)
        if func_name in head_funcs:
            head_node = head_funcs[func_name]
            head_count = _count_assertions_in_node(head_node)
            if head_count < base_count:
                violations.append(Violation(
                    type=ViolationType.ASSERTION_REMOVED,
                    file_path=file_path,
                    line_number=head_node.lineno,
                    symbol_name=func_name,
                    message=f"Assertion count decreased in '{func_name}': {base_count} -> {head_count}",
                    details={"base_count": base_count, "head_count": head_count}
                ))
        else:
            violations.append(Violation(
                type=ViolationType.ASSERTION_REMOVED,
                file_path=file_path,
                symbol_name=func_name,
                message=f"Test function '{func_name}' was removed entirely",
                details={"base_count": base_count, "head_count": 0}
            ))

    return violations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_ast_diff.py`
Expected: PASS with 4 tests OK.

- [ ] **Step 5: Commit**

```bash
git add testguard/ast_diff.py tests/test_ast_diff.py
git commit -m "feat: implement AST diff engine detecting assertion drops, skips, and swallowed exceptions"
```

---

### Task 3: Anti-Hardcode Pattern Matcher

**Files:**
- Create: `testguard/anti_hardcode.py`
- Test: `tests/test_anti_hardcode.py`

**Interfaces:**
- Consumes: `testguard.models` (`ViolationType`, `Violation`)
- Produces: `extract_test_literals(test_code: str) -> set[Any]`, `detect_hardcoded_cheats(src_code: str, test_literals: set[Any], file_path: str) -> list[Violation]`

- [ ] **Step 1: Write the failing tests for anti-hardcode**

```python
# tests/test_anti_hardcode.py
import unittest
from testguard.models import ViolationType
from testguard.anti_hardcode import extract_test_literals, detect_hardcoded_cheats

class TestAntiHardcode(unittest.TestCase):
    def test_extract_literals_from_test(self):
        test_code = """
def test_login():
    assert login("admin_special_user", 987654) == "session_xyz"
"""
        literals = extract_test_literals(test_code)
        self.assertIn("admin_special_user", literals)
        self.assertIn(987654, literals)
        self.assertIn("session_xyz", literals)
        # Verify common default values are ignored
        self.assertNotIn("", literals)
        self.assertNotIn(0, literals)

    def test_detects_hardcoded_if_return(self):
        src_code = """
def login(username, pin):
    if username == "admin_special_user":
        return "session_xyz"
    return perform_real_auth(username, pin)
"""
        test_literals = {"admin_special_user", "session_xyz"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/auth.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.HARDCODED_CHEAT)
        self.assertEqual(violations[0].symbol_name, "login")

    def test_ignores_non_cheating_code(self):
        src_code = """
def login(username, pin):
    token = hash_credentials(username, pin)
    return token
"""
        test_literals = {"admin_special_user"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/auth.py")
        self.assertEqual(len(violations), 0)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_anti_hardcode.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'testguard.anti_hardcode'`

- [ ] **Step 3: Write implementation for `testguard/anti_hardcode.py`**

Create `testguard/anti_hardcode.py`:
```python
import ast
from typing import Any
from testguard.models import Violation, ViolationType

IGNORED_LITERALS = {
    "", " ", "true", "false", "none", "null",
    0, 1, -1, True, False, None
}

def extract_test_literals(test_code: str) -> set[Any]:
    literals = set()
    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return literals

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant):
            val = node.value
            if isinstance(val, (str, int, float)) and not isinstance(val, bool):
                if isinstance(val, str) and (len(val.strip()) < 3 or val.lower() in IGNORED_LITERALS):
                    continue
                if isinstance(val, (int, float)) and val in IGNORED_LITERALS:
                    continue
                literals.add(val)
    return literals

def _extract_constants_from_expr(expr: ast.AST) -> set[Any]:
    constants = set()
    for child in ast.walk(expr):
        if isinstance(child, ast.Constant) and not isinstance(child.value, bool):
            constants.add(child.value)
    return constants

def detect_hardcoded_cheats(src_code: str, test_literals: set[Any], file_path: str) -> list[Violation]:
    if not test_literals:
        return []

    try:
        tree = ast.parse(src_code, filename=file_path)
    except SyntaxError:
        return []

    violations: list[Violation] = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_name = node.name
            for inner in ast.walk(node):
                if isinstance(inner, ast.If):
                    cond_constants = _extract_constants_from_expr(inner.test)
                    matched_literals = cond_constants.intersection(test_literals)
                    if matched_literals:
                        has_direct_return = any(isinstance(stmt, ast.Return) for stmt in inner.body)
                        if has_direct_return:
                            matched_str = ", ".join(repr(x) for x in matched_literals)
                            violations.append(Violation(
                                type=ViolationType.HARDCODED_CHEAT,
                                file_path=file_path,
                                line_number=inner.lineno,
                                symbol_name=func_name,
                                message=f"Hardcoded check for test literal(s) {matched_str} in '{func_name}'",
                                details={"matched_literals": list(matched_literals)}
                            ))
    return violations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_anti_hardcode.py`
Expected: PASS with 3 tests OK.

- [ ] **Step 5: Commit**

```bash
git add testguard/anti_hardcode.py tests/test_anti_hardcode.py
git commit -m "feat: implement anti-hardcode matcher detecting test literal gaming in source functions"
```

---

### Task 4: Git Shadow Diff & Isolation Engine

**Files:**
- Create: `testguard/shadow.py`
- Test: `tests/test_shadow.py`

**Interfaces:**
- Consumes: `testguard.models`, `subprocess`
- Produces: `get_changed_files(base_ref: str, cwd: str = ".") -> list[str]`, `get_file_content_at_ref(ref: str, file_path: str, cwd: str = ".") -> Optional[str]`, `is_test_file(path: str) -> bool`

- [ ] **Step 1: Write the failing tests for shadow isolation**

```python
# tests/test_shadow.py
import unittest
import os
import subprocess
import tempfile
from testguard.shadow import is_test_file, get_changed_files, get_file_content_at_ref

class TestShadowRunner(unittest.TestCase):
    def test_is_test_file(self):
        self.assertTrue(is_test_file("tests/test_auth.py"))
        self.assertTrue(is_test_file("tests/auth_test.py"))
        self.assertTrue(is_test_file("src/test/java/TestAuth.java"))
        self.assertFalse(is_test_file("src/auth.py"))
        self.assertFalse(is_test_file("testguard/models.py"))

    def test_git_operations_in_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Init repo
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "TestUser"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, check=True)
            
            # Initial commit
            file1 = os.path.join(tmpdir, "test_file.py")
            with open(file1, "w") as f:
                f.write("initial = True")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmpdir, check=True)

            # Modify file in working tree
            with open(file1, "w") as f:
                f.write("initial = False\nmodified = True")

            changed = get_changed_files("HEAD", cwd=tmpdir)
            self.assertIn("test_file.py", changed)

            base_content = get_file_content_at_ref("HEAD", "test_file.py", cwd=tmpdir)
            self.assertEqual(base_content, "initial = True")

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_shadow.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'testguard.shadow'`

- [ ] **Step 3: Write implementation for `testguard/shadow.py`**

Create `testguard/shadow.py`:
```python
import os
import subprocess
from typing import Optional

def is_test_file(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    basename = os.path.basename(normalized)
    in_test_dir = "/tests/" in normalized or "/test/" in normalized or normalized.startswith("tests/") or normalized.startswith("test/")
    has_test_name = basename.startswith("test_") or basename.endswith("_test.py") or basename.endswith(".test.js") or basename.endswith(".test.ts")
    return in_test_dir or has_test_name

def get_changed_files(base_ref: str, cwd: str = ".") -> list[str]:
    cmd = ["git", "diff", "--name-only", base_ref]
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode != 0:
        # Fallback to diff against HEAD if base_ref fails
        cmd = ["git", "diff", "--name-only", "HEAD"]
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
        if res.returncode != 0:
            return []
    return [line.strip() for line in res.stdout.splitlines() if line.strip()]

def get_file_content_at_ref(ref: str, file_path: str, cwd: str = ".") -> Optional[str]:
    normalized_path = file_path.replace("\\", "/")
    cmd = ["git", "show", f"{ref}:{normalized_path}"]
    res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if res.returncode == 0:
        return res.stdout
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_shadow.py`
Expected: PASS with 2 tests OK.

- [ ] **Step 5: Commit**

```bash
git add testguard/shadow.py tests/test_shadow.py
git commit -m "feat: implement shadow git diff and base ref file isolation extraction"
```

---

### Task 5: Verdict Engine & CLI Interface

**Files:**
- Create: `testguard/verdict.py`
- Create: `testguard/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `testguard.models`, `testguard.ast_diff`, `testguard.anti_hardcode`, `testguard.shadow`
- Produces: `run_testguard(base_ref: str, cwd: str) -> Report`, `main(args) -> int`

- [ ] **Step 1: Write integration and CLI tests**

```python
# tests/test_cli.py
import unittest
import json
from io import StringIO
from unittest.mock import patch
from testguard.models import ViolationType, Violation, Verdict, Report
from testguard.verdict import format_markdown_report, evaluate_changes
from testguard.cli import main

class TestCLI(unittest.TestCase):
    def test_format_markdown_report_pass(self):
        report = Report(verdict=Verdict.PASS, violations=[])
        md = format_markdown_report(report)
        self.assertIn("PASSED", md)
        self.assertIn("🛡️", md)

    def test_format_markdown_report_veto(self):
        v = Violation(
            type=ViolationType.ASSERTION_REMOVED,
            file_path="tests/test_x.py",
            line_number=10,
            symbol_name="test_fn",
            message="1 assertion removed"
        )
        report = Report(verdict=Verdict.VETO, violations=[v])
        md = format_markdown_report(report)
        self.assertIn("VETO", md)
        self.assertIn("🚨", md)
        self.assertIn("tests/test_x.py", md)

    def test_cli_help(self):
        with self.assertRaises(SystemExit) as cm:
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)

if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_cli.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'testguard.verdict'`

- [ ] **Step 3: Write implementation for `testguard/verdict.py` and `testguard/cli.py`**

Create `testguard/verdict.py`:
```python
import os
import time
from testguard.models import Verdict, Violation, Report
from testguard.ast_diff import analyze_ast_diff, analyze_test_code
from testguard.anti_hardcode import extract_test_literals, detect_hardcoded_cheats
from testguard.shadow import get_changed_files, get_file_content_at_ref, is_test_file

def evaluate_changes(base_ref: str = "HEAD", cwd: str = ".") -> Report:
    start_time = time.perf_counter()
    violations: list[Violation] = []
    
    changed_files = get_changed_files(base_ref, cwd=cwd)
    test_files = [f for f in changed_files if is_test_file(f)]
    src_files = [f for f in changed_files if not is_test_file(f) and f.endswith(".py")]

    collected_literals: set = set()

    for test_file in test_files:
        full_path = os.path.join(cwd, test_file)
        if not os.path.exists(full_path):
            continue
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            head_content = f.read()

        collected_literals.update(extract_test_literals(head_content))
        base_content = get_file_content_at_ref(base_ref, test_file, cwd=cwd)

        if base_content is not None:
            violations.extend(analyze_ast_diff(base_content, head_content, file_path=test_file))
        else:
            violations.extend(analyze_test_code(head_content, file_path=test_file))

    for src_file in src_files:
        full_path = os.path.join(cwd, src_file)
        if not os.path.exists(full_path):
            continue
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            src_content = f.read()
        violations.extend(detect_hardcoded_cheats(src_content, collected_literals, file_path=src_file))

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    verdict = Verdict.VETO if violations else Verdict.PASS
    summary = f"{len(violations)} violations detected" if violations else "0 violations detected, verified clean"

    return Report(
        verdict=verdict,
        violations=violations,
        summary=summary,
        execution_time_ms=elapsed_ms
    )

def format_markdown_report(report: Report) -> str:
    if report.is_passed:
        return "🛡️ **TestGuard: PASSED** – *0 assertions removed, verified against base branch test suite, no hardcoded cheating patterns detected.*"

    lines = [
        "🚨 **TestGuard: VETO** – *Goal gaming / reward hacking detected:*",
        ""
    ]
    for v in report.violations:
        loc = f"`{v.file_path}`"
        if v.line_number:
            loc += f":{v.line_number}"
        sym = f" in `{v.symbol_name}`" if v.symbol_name else ""
        lines.append(f"- **[{v.type.value}]** {loc}{sym}: {v.message}")

    return "\n".join(lines)
```

Create `testguard/cli.py`:
```python
import argparse
import json
import sys
from testguard.verdict import evaluate_changes, format_markdown_report

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="testguard",
        description="The Zero-Trust Anti-Cheat Gate for AI-Generated Code."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    check_parser = subparsers.add_parser("check", help="Run cheat detection against base git branch")
    check_parser.add_argument("--base", default="HEAD", help="Base ref/branch to compare against (default: HEAD)")
    check_parser.add_argument("--format", choices=["text", "json", "markdown"], default="text", help="Output format")
    check_parser.add_argument("--cwd", default=".", help="Directory to run check in")

    args = parser.parse_args(argv)

    if args.command is None:
        # Default behavior: run check
        args.base = "HEAD"
        args.format = "text"
        args.cwd = "."

    report = evaluate_changes(base_ref=args.base, cwd=args.cwd)

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    elif args.format == "markdown":
        print(format_markdown_report(report))
    else:
        # Terminal human-readable
        if report.is_passed:
            print(f"\033[92m🛡️  TestGuard: PASSED\033[0m ({report.execution_time_ms:.1f}ms)")
            print(f"   {report.summary}")
        else:
            print(f"\033[91m🚨 TestGuard: VETO\033[0m ({report.execution_time_ms:.1f}ms)")
            print(f"   {report.summary}")
            for v in report.violations:
                loc = f"{v.file_path}:{v.line_number}" if v.line_number else v.file_path
                print(f"   - [{v.type.value}] {loc}: {v.message}")

    return 0 if report.is_passed else 1

if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_cli.py`
Expected: PASS with 3 tests OK.

- [ ] **Step 5: Run full test suite to verify all tasks**

Run: `python -m unittest discover -s tests -p "test_*.py"`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add testguard/verdict.py testguard/cli.py tests/test_cli.py
git commit -m "feat: implement verdict generator and CLI check command"
```
