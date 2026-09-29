# Phase 2: Multi-Language & Safeguards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand TestGuard with untracked working-tree scanning, assertion weakening detection, JavaScript/TypeScript test cheat detection, zero-config CLI setup (`testguard init`), and configuration file support.

**Architecture:** Extend the deterministic zero-dependency Python core with an untracked git scanner, AST semantic degradation analyzer, a self-contained JS/TS test cheat parser, an automated hook installer for Claude Code & Git, and configuration loading.

**Tech Stack:** Python 3.10+, built-in `ast`, `re`, `subprocess`, `unittest`, `json`, `dataclasses`. Zero external runtime dependencies.

## Global Constraints

- Pure Python standard library only (zero external runtime dependencies).
- Fast execution (<100ms for typical git diffs).
- Deterministic behavior with 100% test coverage for all new detectors.
- Windows and Linux/macOS cross-platform compatibility (forward slash normalization, UTF-8 encoding).

---

### Task 1: Untracked & Working-Tree Scanner

**Files:**
- Modify: `testguard/shadow.py`
- Test: `tests/test_shadow.py`

**Interfaces:**
- Consumes: `get_changed_files(base_ref: str, cwd: str = ".") -> list[str]`
- Produces: Enhanced `get_changed_files` that returns both tracked modified files and untracked files (`git ls-files --others --exclude-standard`).

- [ ] **Step 1: Write failing test in `tests/test_shadow.py` for untracked files**

```python
    def test_get_changed_files_includes_untracked_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "TestUser"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, check=True)

            init_file = os.path.join(tmpdir, "initial.py")
            with open(init_file, "w", encoding="utf-8") as f:
                f.write("x = 1\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True)

            # Create untracked file without git add
            untracked = os.path.join(tmpdir, "untracked_test.py")
            with open(untracked, "w", encoding="utf-8") as f:
                f.write("def test_foo(): pass\n")

            changed = get_changed_files("HEAD", cwd=tmpdir)
            self.assertIn("untracked_test.py", changed)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_shadow.py`
Expected: FAIL (`AssertionError: 'untracked_test.py' not found in []`)

- [ ] **Step 3: Update `testguard/shadow.py` to include untracked files**

In `get_changed_files`, add `git ls-files --others --exclude-standard` and merge results maintaining unique paths.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_shadow.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add testguard/shadow.py tests/test_shadow.py
git commit -m "feat: include untracked files in shadow changed files scanner"
```

---

### Task 2: Assertion Weakening / Semantic Degradation Detection

**Files:**
- Modify: `testguard/models.py`
- Modify: `testguard/ast_diff.py`
- Test: `tests/test_ast_diff.py`

**Interfaces:**
- Consumes: `ViolationType` in `models.py`
- Produces: `ViolationType.ASSERTION_WEAKENED`, AST analysis detecting when strict comparisons (`==`, `in`, `is`) are degraded to loose boolean assertions (`assert x`, `assert x is not None`).

- [ ] **Step 1: Add `ASSERTION_WEAKENED` to `ViolationType` in `testguard/models.py`**

```python
class ViolationType(str, Enum):
    ASSERTION_REMOVED = "ASSERTION_REMOVED"
    ASSERTION_WEAKENED = "ASSERTION_WEAKENED"
    TEST_SKIPPED = "TEST_SKIPPED"
    EXCEPTION_SWALLOWED = "EXCEPTION_SWALLOWED"
    HARDCODED_CHEAT = "HARDCODED_CHEAT"
    SYNTAX_ERROR = "SYNTAX_ERROR"
```

- [ ] **Step 2: Write failing test in `tests/test_ast_diff.py`**

```python
    def test_assertion_weakened_from_equality_to_truthiness(self):
        base_code = """
def test_calc():
    res = compute(10)
    assert res == 42
"""
        head_code = """
def test_calc():
    res = compute(10)
    assert res is not None
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="test_calc.py")
        types = [v.type for v in violations]
        self.assertIn(ViolationType.ASSERTION_WEAKENED, types)
```

- [ ] **Step 3: Implement weakening detection in `testguard/ast_diff.py`**

Inspect AST assert nodes within matching test functions: if a strict comparison (`Compare` with `Eq`, `In`, `Is`) is replaced by a loose assertion (`Name`, `Compare` with `IsNot None`, `UnaryOp Not`), record `ViolationType.ASSERTION_WEAKENED`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests/test_ast_diff.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add testguard/models.py testguard/ast_diff.py tests/test_ast_diff.py
git commit -m "feat: detect semantic assertion weakening in AST diff engine"
```

---

### Task 3: JavaScript & TypeScript Test Cheat Detector

**Files:**
- Create: `testguard/js_diff.py`
- Modify: `testguard/verdict.py`
- Test: `tests/test_js_diff.py`

**Interfaces:**
- Consumes: JS/TS test file contents (`.test.ts`, `.test.js`, `.spec.ts`, `.spec.js`)
- Produces: `analyze_js_test_diff(base_code: str, head_code: str, file_path: str) -> list[Violation]` and `analyze_js_test_code(code: str, file_path: str) -> list[Violation]`.

Detects:
1. `it.skip(...)`, `test.skip(...)`, `describe.skip(...)`, `xit(...)`, `xtest(...)`, `xdescribe(...)`.
2. Assertion drops (`expect(...)` / `assert(...)` calls removed or count reduced).
3. Exception swallowing (`try { ... } catch (e) {}` with empty body).

- [ ] **Step 1: Write unit tests in `tests/test_js_diff.py`**

Test cases:
- Detect `test.skip("should login", () => { ... })` and `it.skip(...)`.
- Detect `xit(...)` and `xtest(...)`.
- Detect removing 3 `expect(res).toBe(42)` assertions down to 1.
- Detect empty `try { ... } catch (err) {}`.
- Clean JS test suite passes without violations.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_js_diff.py`
Expected: FAIL (`ModuleNotFoundError: No module named 'testguard.js_diff'`)

- [ ] **Step 3: Implement `testguard/js_diff.py`**

Implement deterministic regex & token-based JS/TS parser extracting tests, assertions (`expect`, `assert`), skips (`.skip`, `xit`, `xtest`, `xdescribe`), and empty catch blocks.

- [ ] **Step 4: Integrate JS/TS detection into `testguard/verdict.py`**

In `evaluate_changes`, route `.js`, `.ts`, `.jsx`, `.tsx` test files through `analyze_js_test_diff` and `analyze_js_test_code`.

- [ ] **Step 5: Run tests to verify all pass**

Run: `python -m unittest tests/test_js_diff.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add testguard/js_diff.py testguard/verdict.py tests/test_js_diff.py
git commit -m "feat: add JavaScript and TypeScript test cheat detection engine"
```

---

### Task 4: Zero-Config CLI Setup Command (`testguard init`)

**Files:**
- Create: `testguard/installer.py`
- Modify: `testguard/cli.py`
- Test: `tests/test_installer.py`

**Interfaces:**
- Consumes: CLI argument `testguard init --hook claude|git`
- Produces: `install_claude_hook(claude_dir: Optional[str] = None) -> bool`, `install_git_hook(git_dir: Optional[str] = None) -> bool`.

- [ ] **Step 1: Write unit tests in `tests/test_installer.py`**

Test installing Claude hook into temporary directory:
- Verifies `hooks/testguard_gate.py` is created with UTF-8 configuration and `ensure_ascii=False`.
- Verifies `settings.json` is safely updated with `PreToolUse` and `Stop` hooks without destroying existing settings.
- Verifies Git pre-commit hook is installed and executable in temporary `.git` directory.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_installer.py`
Expected: FAIL

- [ ] **Step 3: Implement `testguard/installer.py` and register subcommands in `testguard/cli.py`**

Implement template generation for `testguard_gate.py`, JSON settings merger, git hook writer, and add `init` subparser to `cli.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests/test_installer.py tests/test_cli.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add testguard/installer.py testguard/cli.py tests/test_installer.py
git commit -m "feat: add zero-config testguard init command for Claude Code and Git"
```

---

### Task 5: Project Configuration Support (`.testguard.json`)

**Files:**
- Create: `testguard/config.py`
- Modify: `testguard/verdict.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: Optional `.testguard.json` in repo root.
- Produces: `TestGuardConfig(exclude_patterns: list[str], literal_whitelist: list[str], base_ref: str)`.

- [ ] **Step 1: Write unit tests in `tests/test_config.py`**

Test loading configuration:
- Test custom exclude patterns skipping directories (e.g. `legacy/**`).
- Test whitelist literals ignoring specific strings/numbers during anti-hardcode detection.
- Test fallback to default config when file is missing.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/test_config.py`
Expected: FAIL

- [ ] **Step 3: Implement `testguard/config.py` and connect to `testguard/verdict.py`**

Implement `load_config(cwd: str = ".") -> TestGuardConfig` and apply filters in `evaluate_changes`.

- [ ] **Step 4: Run full test suite**

Run: `python -m unittest discover tests`
Expected: 100% tests pass.

- [ ] **Step 5: Commit**

```bash
git add testguard/config.py testguard/verdict.py tests/test_config.py
git commit -m "feat: add project configuration support via .testguard.json"
```
