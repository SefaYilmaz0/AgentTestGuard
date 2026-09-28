"""Command Line Interface for TestGuard.

Provides `check` command to detect AI cheating, assertions removal, skips,
exception swallowing, and hardcoded test values against a git base ref.
"""

import argparse
import json
import sys
from typing import Optional

from testguard.verdict import evaluate_changes, format_markdown_report


def main(argv: Optional[list[str]] = None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--base", default="HEAD", help="Base ref/branch to compare against (default: HEAD)"
    )
    common.add_argument(
        "--format", choices=["text", "json", "markdown"], default="text", help="Output format"
    )
    common.add_argument("--cwd", default=".", help="Directory to run check in")

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

    args = parser.parse_args(argv)

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
