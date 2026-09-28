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
from testguard.models import Report, Verdict, Violation
from testguard.shadow import get_changed_files, get_file_content_at_ref, is_test_file


def evaluate_changes(base_ref: str = "HEAD", cwd: str = ".") -> Report:
    """Evaluate repository changes against base_ref and return a comprehensive verification Report.

    Inspects changed test files for assertion decreases, skips, or swallowed exceptions.
    Inspects changed source files for hardcoded cheating against test literals.
    """
    start_time = time.perf_counter()
    violations: list[Violation] = []

    changed_files = get_changed_files(base_ref, cwd=cwd)
    test_files = [f for f in changed_files if is_test_file(f)]
    src_files = [f for f in changed_files if not is_test_file(f) and f.endswith(".py")]

    collected_literals: set = set()

    for test_file in test_files:
        if not test_file.endswith(".py"):
            continue
        full_path = os.path.join(cwd, test_file)
        if not os.path.exists(full_path):
            base_content = get_file_content_at_ref(base_ref, test_file, cwd=cwd)
            if base_content is not None:
                violations.extend(analyze_ast_diff(base_content, "", file_path=test_file))
            continue

        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            head_content = f.read()

        collected_literals.update(extract_test_literals(head_content))
        base_content = get_file_content_at_ref(base_ref, test_file, cwd=cwd)

        if base_content is not None:
            collected_literals.update(extract_test_literals(base_content))
            violations.extend(analyze_ast_diff(base_content, head_content, file_path=test_file))
        else:
            violations.extend(analyze_test_code(head_content, file_path=test_file))

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
                if is_test_file(rel_path) and file.endswith(".py"):
                    try:
                        with open(os.path.join(root, file), "r", encoding="utf-8", errors="ignore") as f:
                            collected_literals.update(extract_test_literals(f.read()))
                    except OSError:
                        pass

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
        execution_time_ms=elapsed_ms,
    )


def run_testguard(base_ref: str = "HEAD", cwd: str = ".") -> Report:
    """Alias for evaluate_changes."""
    return evaluate_changes(base_ref=base_ref, cwd=cwd)


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
