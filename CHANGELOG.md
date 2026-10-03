# Changelog

## 0.3.0

### Security / behavior changes
- **Fail closed on an unresolvable base ref.** `testguard check --base <ref>` now exits **2** with an error instead of silently diffing nothing and passing. The GitHub Action reports `verdict=ERROR`. In CI use `fetch-depth: 0` or a valid `base`.
- **GitHub Action hardening.** Inputs are passed through `env:` (no shell injection), `violations-count` is the real count, bare branch names resolve via `origin/`, and the base fetch no longer uses a broken refspec or `--depth=1`.

### Added
- **Shadow Test Runner** (`--shadow-run`, `shadow_run` config, `shadow-run` Action input): restores every base-ref test file in a temporary copy of the working tree and runs them against the modified sources. Configurable via `shadow_command` and `shadow_timeout`. New violation type `SHADOW_TEST_FAILED`.
- **Anti-hardcode for JS/TS sources** (`if`, ternary, `switch/case`, lookup tables).
- **New Python anti-hardcode patterns:** call-wrapped returns, dict lookup tables, single-assignment constant aliases (also in JS/TS).
- **Broader test file detection:** `conftest.py`, `*_tests.py`, `.spec/.e2e/.e2e-spec/.cy` variants, `.mjs/.cjs/.mts/.cts`, `spec/ specs/ e2e/ __mocks__/` directories.
- **Rename tracking:** moved or renamed tests are compared against their old content, so moving a test out of `tests/` no longer hides removed assertions.

### Fixed
- Clearer message when a test file disappears (`details.file_deleted`) instead of a misleading "removed entirely".
- Removed placeholder author email from package metadata; silenced pytest collection warning for `TestGuardConfig`.

### Known limits
- JS/TS detection is token-based, not a full AST.
- Cross-file constant indirection is not detected.
- `--shadow-run` runs JS tests only when `shadow_command` is set.

## 0.2.0
- Multi-language test analysis (Vitest, Jest, Playwright, Mocha), `testguard init`, `.testguard.json` / `pyproject.toml` configuration, GitHub Action, release workflow.
