"""Command Line Interface for TestGuard.

Provides `check` command to detect AI cheating, assertions removal, skips,
exception swallowing, and hardcoded test values against a git base ref.
"""

import argparse
import json
import sys
from typing import Optional

from testguard.config import load_config
from testguard.shadow import BaseRefError
from testguard.installer import install_claude_hook, install_git_hook
from testguard.verdict import evaluate_changes, format_markdown_report


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "utf-8") or "utf-8"
        print(text.encode(encoding, errors="replace").decode(encoding))


def main(argv: Optional[list[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--base", default="HEAD", help="Base ref/branch to compare against (default: HEAD)"
    )
    common.add_argument(
        "--format", choices=["text", "json", "markdown"], default="text", help="Output format"
    )
    common.add_argument("--cwd", default=".", help="Directory to run check in")
    common.add_argument(
        "--config", default=None, help="Path to configuration file (.testguard.json or pyproject.toml)"
    )

    common.add_argument(
        "--shadow-run",
        action="store_true",
        help="Also run the base branch's tests against the modified sources (Shadow Test Runner)",
    )

    parser = argparse.ArgumentParser(
        prog="testguard",
        description="The Zero-Trust Anti-Cheat Gate for AI-Generated Code.",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    subparsers.add_parser(
        "check",
        parents=[common],
        help="Run cheat detection against base git branch",
    )

    init_parser = subparsers.add_parser(
        "init",
        help="Install TestGuard hooks for Claude Code or Git",
    )
    init_parser.add_argument(
        "--hook",
        choices=["claude", "git", "all"],
        default="claude",
        help="Hook to install: 'claude', 'git', or 'all' (default: claude)",
    )
    init_parser.add_argument(
        "--claude-dir",
        default=None,
        help="Target Claude configuration directory (default: ~/.claude)",
    )
    init_parser.add_argument(
        "--git-dir",
        default=None,
        help="Target Git directory (default: .git)",
    )

    args = parser.parse_args(argv)

    if args.command == "init":
        success = True
        if args.hook in ("claude", "all"):
            if install_claude_hook(claude_dir=args.claude_dir):
                _safe_print("🛡️  TestGuard Claude Code hook installed successfully.")
            else:
                _safe_print("🚨 Failed to install TestGuard Claude Code hook.")
                success = False

        if args.hook in ("git", "all"):
            if install_git_hook(git_dir=args.git_dir):
                _safe_print("🛡️  TestGuard Git pre-commit hook installed successfully.")
            else:
                _safe_print("🚨 Failed to install TestGuard Git pre-commit hook.")
                success = False

        return 0 if success else 1

    config = load_config(cwd=args.cwd, config_path=args.config)
    if args.shadow_run:
        config.shadow_run = True
    try:
        report = evaluate_changes(base_ref=args.base, cwd=args.cwd, config=config)
    except BaseRefError as exc:
        print(f"TestGuard error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        _safe_print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    elif args.format == "markdown":
        _safe_print(format_markdown_report(report))
    else:
        # Terminal human-readable
        if report.is_passed:
            _safe_print(f"\033[92m🛡️  TestGuard: PASSED\033[0m ({report.execution_time_ms:.1f}ms)")
            _safe_print(f"   {report.summary}")
        else:
            _safe_print(f"\033[91m🚨 TestGuard: VETO\033[0m ({report.execution_time_ms:.1f}ms)")
            _safe_print(f"   {report.summary}")
            for v in report.violations:
                loc = f"{v.file_path}:{v.line_number}" if v.line_number else v.file_path
                _safe_print(f"   - [{v.type.value}] {loc}: {v.message}")
                tail = v.details.get("output_tail")
                if tail:
                    for line in tail.splitlines()[-15:]:
                        _safe_print(f"       | {line}")

    return 0 if report.is_passed else 1


if __name__ == "__main__":
    sys.exit(main())
