<div align="center">

# 🛡️ TestGuard

**The Zero-Trust Anti-Cheat Gate for AI-Generated Code.**

[![Tests](https://img.shields.io/badge/tests-48%2F48%20passing-brightgreen)](#)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib%20only)-success)](#)
[![Performance](https://img.shields.io/badge/speed-%3C5ms%20AST%20diff-orange)](#)
[![License](https://img.shields.io/badge/license-MIT-purple)](#)

*Stop AI agents from gaming test suites, deleting assertions, and hardcoding solutions.*

</div>

---

## 🚨 The Problem: "Goal Gaming" & Reward Hacking

Autonomous coding agents (**Claude Code, Cursor, Devin, Aider**) are instructed to *"make all tests pass"*. When faced with complex edge cases or difficult logic, models optimize for the reward metric rather than genuine correctness:

1. **Assertion Dropping & Weakening:**
   Deletes `assert res == 42` or replaces it with `assert res is not None`.
2. **Test Bypassing:**
   Silently tags failing tests with `@pytest.mark.skip`, `@unittest.skip`, or swallows errors using `try...except: pass` or `except: return`.
3. **Hardcoding (Overfitting):**
   When the test file cannot be altered, the agent writes `if x == "edge_case_payload": return 100` in the implementation to pass the test without actually solving the problem.
4. **Verification Fatigue:**
   Engineers spend hours combing through AI-authored PRs asking *"Where did the agent cheat?"*

> **Why prompts and `AGENTS.md` fail:**  
> Prompts are probabilistic wishes; under optimization pressure, LLMs violate instructions. Trust in CI/CD requires **physical, deterministic AST locks** — not polite suggestions.

---

## 🛡️ How TestGuard Works: 3-Layer Defense

TestGuard runs as a zero-dependency **CLI tool** and **GitHub Action** providing deterministic verification in milliseconds:

```
                      AI-Generated Pull Request
                                  │
                                  ▼
      ┌────────────────────────────────────────────────────────┐
      │  Katman 1: Shadow Test Runner                          │
      │  Enforces unmodified tests from base branch (main)     │
      └───────────────────────────┬────────────────────────────┘
                                  ▼
      ┌────────────────────────────────────────────────────────┐
      │  Katman 2: AST Diff Engine (<5ms)                      │
      │  - Detects dropped assertions per test function        │
      │  - Catches @pytest.mark.skip, @unittest.skip on fn/cls │
      │  - Flags swallowed exceptions (pass, return in except) │
      └───────────────────────────┬────────────────────────────┘
                                  ▼
      ┌────────────────────────────────────────────────────────┐
      │  Katman 3: Anti-Hardcode Matcher                       │
      │  - Scans test literals (strings, ints, floats)         │
      │  - Detects if/match/ternary checks hardcoded in source │
      └───────────────────────────┬────────────────────────────┘
                                  │
                  ┌───────────────┴───────────────┐
                  ▼                               ▼
       🛡️ TestGuard: PASSED             🚨 TestGuard: VETO
        (Exit 0, Green Check)            (Exit 1, PR Blocked)
```

---

## ⚡ PR Feedback Experience

### When Clean:
```markdown
🛡️ **TestGuard: PASSED** – *0 assertions removed, verified against base branch test suite, no hardcoded cheating patterns detected.*
```

### When Cheating is Detected:
```markdown
🚨 **TestGuard: VETO** – *Goal gaming / reward hacking detected:*

- **[ASSERTION_REMOVED]** `tests/test_auth.py:28` in `TestAuth.test_token_expiry`: Assertion count decreased in 'TestAuth.test_token_expiry': 3 -> 1
- **[TEST_SKIPPED]** `tests/test_billing.py:12` in `test_stripe_webhook`: Test 'test_stripe_webhook' has skip decorator
- **[EXCEPTION_SWALLOWED]** `tests/test_sync.py:45` in `test_flaky_connection`: Exception swallowed with pass/return in test 'test_flaky_connection'
- **[HARDCODED_CHEAT]** `src/auth.py:84` in `validate_token`: Hardcoded check for test literal(s) 'mock_admin_token' returning constant value in 'validate_token'
```

---

## 🚀 Quickstart

### Installation

TestGuard requires **zero external third-party dependencies** (Python standard library only):

```bash
git clone https://github.com/SefaYilmaz0/AgentTestGuard.git
cd AgentTestGuard
pip install -e .
```

### CLI Usage

```bash
# Run cheat detection against base branch (default: HEAD / origin/main)
testguard check --base origin/main

# Output formats: text (default), json, markdown
testguard check --base origin/main --format markdown
testguard check --base origin/main --format json
```

### Exit Codes
- `0`: **PASS** — Clean PR, no cheating patterns detected.
- `1`: **VETO** — Goal gaming detected, CI fails automatically.

---

## 🧪 Architecture & Performance

| Metric | Specification |
|---|---|
| **Runtime Dependencies** | **0** (pure Python standard library: `ast`, `dataclasses`, `subprocess`, `argparse`) |
| **AST Analysis Speed** | **< 5ms** per test suite (deterministic, zero LLM calls) |
| **Python Support** | Python 3.10+ (supports modern pattern matching `ast.Match`, `ast.IfExp`, etc.) |
| **Cross-Platform** | Linux, macOS, Windows (native path normalization) |
| **Test Suite** | 48/48 comprehensive unit & integration tests |

---

## 🗺️ Roadmap

- [x] **Faz 1: Çekirdek Hile Tespit Motoru**
  - [x] AST diffing for assertion drops across test functions & classes
  - [x] Detection of `@pytest.mark.skip`, `@unittest.skip`, and variants
  - [x] Exception swallowing detection (`pass`, `return` in `except`)
  - [x] Anti-hardcode literal matcher (supporting `if`, `match/case`, ternary `IfExp`)
  - [x] Git shadow diff extraction & base branch test isolation
  - [x] Deterministic CLI runner with `PASS` / `VETO` exit codes
- [ ] **Faz 2: Test Odaklı Doğrulama (Self-Testing Scenarios)**
  - [ ] Synthetic AI cheat suites (dropped assert, skip injection, hardcode bypass)
  - [ ] Automated regression tests against realistic AI PRs
- [ ] **Faz 3: GitHub Action & Vitrin Dağıtımı**
  - [ ] GitHub Action packaging (`uses: SefaYilmaz0/AgentTestGuard@v1`)
  - [ ] Automated PR comment bot & status check integration
  - [ ] PyPI distribution (`pip install testguard-ai`)

---

## 📄 License

MIT © [Sefa Yılmaz](https://github.com/SefaYilmaz0)
