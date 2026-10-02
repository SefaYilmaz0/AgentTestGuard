"""Verdict Generation Engine for TestGuard.

Coordinates git shadow diffs, test AST change analysis, test literal extraction,
and anti-hardcoding heuristic checks across modified code to produce deterministic
pass/veto gate verdicts.
"""

import os
import time
from typing import Optional

from testguard.anti_hardcode import detect_hardcoded_cheats, extract_test_literals
from testguard.ast_diff import analyze_ast_diff, analyze_test_code
from testguard.js_hardcode import detect_js_hardcoded_cheats
from testguard.js_diff import (
    JS_TS_EXTENSIONS,
    analyze_js_test_code,
    analyze_js_test_diff,
    extract_js_test_literals,
)
from testguard.config import TestGuardConfig, is_file_excluded, load_config
from testguard.models import Report, Verdict, Violation
from testguard.shadow_runner import run_shadow_tests
from testguard.shadow import get_changed_files, get_file_content_at_ref, get_renamed_files, is_test_file


def _mark_file_deleted(violations: list[Violation], file_path: str) -> None:
    """Make clear the tests vanished because their file is gone, not edited in place."""
    for v in violations:
        v.details["file_deleted"] = True
        if v.message.endswith("was removed entirely"):
            v.message = (
                f"{v.message[:-len('was removed entirely')]}was removed: "
                f"its file '{file_path}' no longer exists (deleted, or moved without a trackable rename)"
            )


def evaluate_changes(
    base_ref: str = "HEAD",
    cwd: str = ".",
    config: Optional[TestGuardConfig] = None,
) -> Report:
    """Evaluate repository changes against base_ref and return a comprehensive verification Report.

    Inspects changed test files for assertion decreases, skips, or swallowed exceptions.
    Inspects changed source files for hardcoded cheating against test literals.
    """
    if config is None:
        config = load_config(cwd=cwd)

    if base_ref == "HEAD" and config.base_ref:
        base_ref = config.base_ref

    start_time = time.perf_counter()
    violations: list[Violation] = []

    changed_files = get_changed_files(base_ref, cwd=cwd)
    if config.exclude_patterns:
        changed_files = [f for f in changed_files if not is_file_excluded(f, config.exclude_patterns)]
    renames = get_renamed_files(base_ref, cwd=cwd)
    # A test moved to a non-test-looking path is still a test (compared against its old content).
    def _is_test(f: str) -> bool:
        return is_test_file(f) or (f in renames and is_test_file(renames[f]))

    test_files = [f for f in changed_files if _is_test(f)]
    src_files = [
        f for f in changed_files
        if not _is_test(f)
        and (f.endswith(".py") or (f.endswith(JS_TS_EXTENSIONS) and not f.endswith(".d.ts")))
    ]

    collected_literals: set = set()

    for test_file in test_files:
        is_py = test_file.endswith(".py")
        is_js = any(test_file.endswith(ext) for ext in JS_TS_EXTENSIONS)
        if not (is_py or is_js):
            continue

        full_path = os.path.join(cwd, test_file)
        if not os.path.exists(full_path):
            base_content = get_file_content_at_ref(base_ref, renames.get(test_file, test_file), cwd=cwd)
            if base_content is not None:
                if is_py:
                    deleted = analyze_ast_diff(base_content, "", file_path=test_file)
                    _mark_file_deleted(deleted, test_file)
                    violations.extend(deleted)
                elif is_js:
                    deleted = analyze_js_test_diff(base_content, "", file_path=test_file)
                    _mark_file_deleted(deleted, test_file)
                    violations.extend(deleted)
            continue

        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            head_content = f.read()

        base_content = get_file_content_at_ref(base_ref, renames.get(test_file, test_file), cwd=cwd)

        if is_py:
            collected_literals.update(extract_test_literals(head_content))
            if base_content is not None:
                collected_literals.update(extract_test_literals(base_content))
                violations.extend(analyze_ast_diff(base_content, head_content, file_path=test_file))
            else:
                violations.extend(analyze_test_code(head_content, file_path=test_file))
        elif is_js:
            collected_literals.update(extract_js_test_literals(head_content))
            if base_content is not None:
                collected_literals.update(extract_js_test_literals(base_content))
                violations.extend(analyze_js_test_diff(base_content, head_content, file_path=test_file))
            else:
                violations.extend(analyze_js_test_code(head_content, file_path=test_file))

    # When src_files are present, collect literals from all existing test files in repo
    # to ensure untouched tests also protect modified source files
    if src_files:
        excluded_dirs = {
            ".git", ".venv", "venv", "__pycache__", ".pytest_cache",
            "node_modules", ".tox", "build", "dist", ".superpowers",
        }
        for root, dirs, files in os.walk(cwd):
            dirs[:] = [d for d in dirs if d not in excluded_dirs]
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), cwd).replace("\\", "/")
                if config.exclude_patterns and is_file_excluded(rel_path, config.exclude_patterns):
                    continue
                if is_test_file(rel_path):
                    if file.endswith(".py"):
                        try:
                            with open(os.path.join(root, file), "r", encoding="utf-8", errors="ignore") as f:
                                collected_literals.update(extract_test_literals(f.read()))
                        except OSError:
                            pass
                    elif any(file.endswith(ext) for ext in JS_TS_EXTENSIONS):
                        try:
                            with open(os.path.join(root, file), "r", encoding="utf-8", errors="ignore") as f:
                                collected_literals.update(extract_js_test_literals(f.read()))
                        except OSError:
                            pass

    if config.literal_whitelist:
        whitelist = set(config.literal_whitelist)
        for item in list(whitelist):
            if isinstance(item, (int, float)):
                whitelist.add(str(item))
        collected_literals = {
            lit for lit in collected_literals
            if lit not in whitelist and str(lit) not in whitelist
        }

    for src_file in src_files:
        full_path = os.path.join(cwd, src_file)
        if not os.path.exists(full_path):
            continue
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            src_content = f.read()
        if src_file.endswith(".py"):
            violations.extend(detect_hardcoded_cheats(src_content, collected_literals, file_path=src_file))
        else:
            violations.extend(detect_js_hardcoded_cheats(src_content, collected_literals, file_path=src_file))

    if config.shadow_run:
        violations.extend(run_shadow_tests(base_ref, cwd=cwd, config=config))

    elapsed_ms = (time.perf_counter() - start_time) * 1000.0
    verdict = Verdict.VETO if violations else Verdict.PASS
    summary = f"{len(violations)} violations detected" if violations else "0 violations detected, verified clean"

    return Report(
        verdict=verdict,
        violations=violations,
        summary=summary,
        execution_time_ms=elapsed_ms,
    )


def run_testguard(
    base_ref: str = "HEAD",
    cwd: str = ".",
    config: Optional[TestGuardConfig] = None,
) -> Report:
    """Alias for evaluate_changes."""
    return evaluate_changes(base_ref=base_ref, cwd=cwd, config=config)


def format_markdown_report(report: Report) -> str:
    """Format a verification Report into a standard GitHub PR markdown comment."""
    if report.is_passed:
        return "🛡️ **TestGuard: PASSED** – *0 assertions removed, verified against base branch test suite, no hardcoded cheating patterns detected.*"

    lines = [
        "🚨 **TestGuard: VETO** – *Goal gaming / reward hacking detected:*",
        "",
    ]
    for v in report.violations:
        loc = f"`{v.file_path}`"
        if v.line_number:
            loc += f":{v.line_number}"
        sym = f" in `{v.symbol_name}`" if v.symbol_name else ""
        lines.append(f"- **[{v.type.value}]** {loc}{sym}: {v.message}")

    return "\n".join(lines)
