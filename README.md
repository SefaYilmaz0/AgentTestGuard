<div align="center">

# 🛡️ TestGuard

**The Zero-Trust Anti-Cheat Gate for AI-Generated Code.**

[![Tests](https://img.shields.io/badge/tests-97%2F97%20passing-brightgreen)](#)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](#)
[![Languages](https://img.shields.io/badge/languages-Python%20%7C%20JS%2FTS-blueviolet)](#)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20(stdlib%20only)-success)](#)
[![Performance](https://img.shields.io/badge/speed-%3C5ms%20AST%20diff-orange)](#)
[![License](https://img.shields.io/badge/license-MIT-purple)](#)

*Stop AI agents from gaming test suites, deleting assertions, and hardcoding solutions.*

</div>

---

## 🚨 The Problem: "Goal Gaming" & Reward Hacking

Autonomous coding agents (**Claude Code, Cursor, Devin, Aider**) are instructed to *"make all tests pass"*. When faced with complex edge cases or difficult logic, models optimize for the reward metric rather than genuine correctness:

1. **Assertion Dropping & Semantic Weakening:**
   Deletes `assert res == 42` / `expect(res).toBe(42)` or replaces it with loose truthiness checks like `assert res` or `assert res is not None`.
2. **Test Bypassing:**
   Silently tags failing tests with `@pytest.mark.skip`, `it.skip`, `test.skip`, `xit`, or swallows errors using `try...except: pass` or empty `catch {}` blocks.
3. **Hardcoding (Overfitting):**
   When the test file cannot be altered, the agent writes `if x == "edge_case_payload": return 100` in the implementation to pass the test without actually solving the problem.
4. **Untracked File Manipulation:**
   Agents create fresh untracked files or mocks in the working tree to evade git diff checks.
5. **Verification Fatigue:**
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
- **[ASSERTION_WEAKENED]** `tests/test_status.ts:42` in `test_health`: Strict assertion replaced with loose truthy check
- **[TEST_SKIPPED]** `tests/test_billing.spec.ts:12` in `test.describe.skip`: Test suite has skip decorator
- **[EXCEPTION_SWALLOWED]** `tests/test_sync.py:45` in `test_flaky_connection`: Exception swallowed with pass/return in test
- **[HARDCODED_CHEAT]** `src/auth.py:84` in `validate_token`: Hardcoded check for test literal(s) 'mock_admin_token' returning constant value
```

---

## 🚀 Quickstart

### 1. Installation

TestGuard requires **zero external third-party dependencies** (Python standard library only):

```bash
pip install testguard-ai
# Or from source:
pip install git+https://github.com/SefaYilmaz0/AgentTestGuard.git
```

### 2. Zero-Config Agent & Git Hooks (`testguard init`)

Automatically protect your workflow before commits or agent completions:

```bash
# Install Claude Code safety gate (PreToolUse & Stop hooks in ~/.claude/settings.json)
testguard init --hook claude

# Install Git pre-commit hook in your current repository (.git/hooks/pre-commit)
testguard init --hook git

# Install both hooks at once
testguard init --hook all
```

### 3. CI/CD Integration (GitHub Action)

Add TestGuard as a mandatory status check in `.github/workflows/testguard.yml`:

```yaml
name: TestGuard Anti-Cheat Gate

on:
  pull_request:
    branches: [main, master]

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Verify AI Code Integrity
        uses: SefaYilmaz0/AgentTestGuard@v1
        with:
          base: ${{ github.base_ref || 'main' }}
```

### 4. Manual CLI Check

```bash
# Run cheat detection against base branch (default: HEAD / origin/main)
testguard check --base origin/main

# Output formats: text (default), json, markdown
testguard check --base origin/main --format markdown
testguard check --base origin/main --format json
```

### Exit Codes
- `0`: **PASS** — Clean PR, no cheating patterns detected.
- `1`: **VETO** — Goal gaming detected, CI / commit / hook blocked.
- `2`: **ERROR** — Base ref could not be resolved (fail closed; never a silent PASS).

---

## ⚙️ Configuration (`.testguard.json`)

TestGuard works out of the box with zero configuration. For advanced repos, create a `.testguard.json` or add a `[tool.testguard]` section in `pyproject.toml`:

```json
{
  "base_ref": "origin/main",
  "exclude_patterns": [
    "legacy/**",
    "benchmarks/*",
    "docs/**"
  ],
  "literal_whitelist": [
    "localhost",
    "127.0.0.1",
    "mock_id_allowed"
  ]
}
```

---

## 🌐 Supported Frameworks & Languages

| Ecosystem | Supported Test Frameworks | Detected Patterns |
|---|---|---|
| **Python** | `pytest`, `unittest` | Dropped assertions, weakened assertions (`assertEqual` → `assertTrue`, `assert x == 42` → `assert x`), `@pytest.mark.skip`, `@unittest.skip`, swallowed exceptions (`try...except: pass`), hardcoded returns. |
| **JavaScript / TypeScript** | `Vitest`, `Jest`, `Playwright`, `Mocha` | Dropped assertions (`expect(...)`), weakened assertions, `it.skip`, `test.skip`, `xit`, `xtest`, `describe.skip`, empty `catch (e) {}`, hardcoded returns. |

---

## 🧪 Architecture & Performance

| Metric | Specification |
|---|---|
| **Runtime Dependencies** | **0** (pure Python standard library: `ast`, `dataclasses`, `subprocess`, `argparse`, `fnmatch`) |
| **Analysis Speed** | **< 10ms** per diff (deterministic lexical and AST parsing, zero LLM calls) |
| **Python Support** | Python 3.10, 3.11, 3.12, 3.13 |
| **Cross-Platform** | Linux, macOS, Windows (native path & stream encoding handling) |
| **Test Suite** | 97/97 comprehensive unit, integration & synthetic cheat scenario tests |

---

## 🗺️ Roadmap

- [x] **Faz 1: Çekirdek Hile Tespit Motoru (Core Engine)**
  - [x] AST diffing for assertion drops across test functions & classes
  - [x] Detection of skip decorators and swallowed exceptions
  - [x] Anti-hardcode literal matcher (supporting `if`, `match/case`, ternary `IfExp`)
  - [x] Git shadow diff extraction & base branch test isolation
  - [x] Deterministic CLI runner with `PASS` / `VETO` exit codes
- [x] **Faz 2: Çoklu Dil Desteği ve Güvenlik Katmanları (Multi-Language & Safeguards)**
  - [x] Untracked & working tree scanner (`git ls-files --others`)
  - [x] Semantic assertion weakening detector (`ASSERTION_WEAKENED`)
  - [x] JavaScript / TypeScript test cheat detector (Vitest, Jest, Playwright, Mocha)
  - [x] Zero-config CLI setup command (`testguard init --hook claude|git|all`)
  - [x] Project configuration support (`.testguard.json` & `pyproject.toml`)
- [ ] **Faz 3: Dağıtım ve Açık Kaynak Vitrini (Distribution & Marketplace)**
  - [x] GitHub Action composite definition (`action.yml`)
  - [x] Cross-platform CI matrix (Linux, Windows, macOS)
  - [x] Automated PyPI release workflow (`release.yml`)
  - [ ] GitHub Marketplace publication (`v1` release tag)
  - [ ] PyPI distribution (`testguard-ai` on PyPI)

---

## 🏢 Enterprise & Private Repositories

TestGuard is **100% free and open-source forever** for public repositories.

For private company repositories requiring team-wide analytics, Slack/Discord alerts, audit logs, or centralized rule enforcement, enterprise plans will be available via GitHub Marketplace.

---

## 💖 Community & Contributing

Feedback, bug reports, and contributions are welcome! Feel free to open an issue or pull request.

## 📄 License

MIT © [Sefa Yılmaz](https://github.com/SefaYilmaz0)
