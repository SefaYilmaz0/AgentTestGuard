"""Automated hook installer for Claude Code and Git repositories.

Provides zero-config installation for:
- Claude Code hooks (PreToolUse commit gate and Stop verification gate)
- Git pre-commit hooks
"""

import json
import os
import sys
from typing import Optional


CLAUDE_HOOK_COMMAND = 'python "$HOME/.claude/hooks/testguard_gate.py" commit'
CLAUDE_STOP_COMMAND = 'python "$HOME/.claude/hooks/testguard_gate.py" stop'

TESTGUARD_GATE_SCRIPT = '''"""Claude Code hook: run `testguard check` and block on VETO.

Modes:
  commit - PreToolUse(Bash|PowerShell). Runs only for `git commit` commands; VETO blocks the commit.
  stop   - Stop. VETO forces Claude to keep working instead of finishing.

Exit 2 = block (stderr goes back to Claude). Anything else fails open so a
missing tool or non-git folder never wedges the session.
"""
import json
import os
import re
import subprocess
import sys

# Ensure UTF-8 output on consoles and hooks
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


GIT_COMMIT = re.compile(r"\\bgit\\b((?:\\s+-[Cc]\\s+(?:\"[^\"]+\"|'[^']+'|\\S+))*)\\s+commit\\b")
GIT_DASH_C = re.compile(r"-C\\s+(\"[^\"]+\"|'[^']+'|\\S+)")
CD = re.compile(r"(?:^|[;&|]\\s*)(?:cd|Set-Location|pushd)\\s+(\"[^\"]+\"|'[^']+'|[^\\s;&|]+)")


def commit_dir(command, cwd):
    """Determine the repo directory targeted by git commit."""
    match = GIT_COMMIT.search(command)
    if not match:
        return None
    dash_c = GIT_DASH_C.findall(match.group(1))
    cds = CD.findall(command[: match.start()])
    target = (dash_c or cds or [None])[-1]
    if not target:
        return cwd
    target = os.path.expanduser(target.strip("\"'"))
    return os.path.normpath(os.path.join(cwd, target))


FIX_HINT = (
    "Do not delete tests, add @skip / .skip / xfail, or weaken assertions. "
    "Fix the source code properly, then verify with `testguard check`."
)


def run_testguard(cwd):
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "testguard", "check", "--cwd", cwd],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"testguard execution failed: {exc}"
    out = re.sub(r"\\x1b\\[[0-9;]*m", "", (proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "commit"
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    cwd = payload.get("cwd") or "."

    if mode == "commit":
        command = (payload.get("tool_input") or {}).get("command", "")
        cwd = commit_dir(command, cwd)
        if cwd is None:
            return 0

    code, out = run_testguard(cwd)
    if code != 1:  # 0 = PASSED; other codes = tool error or clean, fail open
        return 0

    if mode == "commit":
        sys.stderr.write(f"Commit blocked: TestGuard VETO.\\n{out}\\n\\n{FIX_HINT}\\n")
        return 2

    # Stop: block once; if Claude already retried after a block, let it stop but warn the user.
    if payload.get("stop_hook_active"):
        print(json.dumps({"systemMessage": f"TestGuard still reporting VETO:\\n{out}"}, ensure_ascii=False))
        return 0
    sys.stderr.write(f"Task incomplete: TestGuard VETO.\\n{out}\\n\\n{FIX_HINT}\\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
'''

GIT_PRE_COMMIT_SCRIPT = """#!/bin/sh
# TestGuard pre-commit hook
# The Zero-Trust Anti-Cheat Gate for AI-Generated Code.

if command -v testguard >/dev/null 2>&1; then
    testguard check
elif command -v python3 >/dev/null 2>&1; then
    python3 -m testguard check
elif command -v python >/dev/null 2>&1; then
    python -m testguard check
elif command -v py >/dev/null 2>&1; then
    py -m testguard check
else
    echo "⚠️  TestGuard: Python or testguard executable not found in PATH." >&2
    exit 0
fi

exit $?
"""


def _has_command_in_hooks(hook_entries: list, pattern: str) -> bool:
    """Check if a command pattern already exists in a list of hook entries."""
    for entry in hook_entries:
        if isinstance(entry, dict):
            if pattern in entry.get("command", ""):
                return True
            for sub in entry.get("hooks", []):
                if isinstance(sub, dict) and pattern in sub.get("command", ""):
                    return True
    return False


def install_claude_hook(claude_dir: Optional[str] = None) -> bool:
    """Install TestGuard hooks into Claude Code configuration.

    - Creates `hooks/testguard_gate.py` with UTF-8 configuration.
    - Updates `settings.json` safely:
      - Adds `Bash(testguard *)` to `permissions.allow`.
      - Adds `PreToolUse` hook running `testguard_gate.py commit`.
      - Adds `Stop` hook running `testguard_gate.py stop`.
      - Preserves all other user settings.

    Returns True on success, False on failure.
    """
    try:
        if claude_dir is None:
            claude_dir = os.path.expanduser("~/.claude")

        claude_dir = os.path.abspath(claude_dir)
        hooks_dir = os.path.join(claude_dir, "hooks")
        os.makedirs(hooks_dir, exist_ok=True)

        # 1. Write hooks/testguard_gate.py
        gate_path = os.path.join(hooks_dir, "testguard_gate.py")
        with open(gate_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(TESTGUARD_GATE_SCRIPT)

        try:
            os.chmod(gate_path, 0o755)
        except OSError:
            pass

        # 2. Read or create settings.json
        settings_path = os.path.join(claude_dir, "settings.json")
        settings: dict = {}
        if os.path.isfile(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        settings = data
            except Exception:
                settings = {}

        # 3. Update permissions.allow
        permissions = settings.setdefault("permissions", {})
        if not isinstance(permissions, dict):
            permissions = {}
            settings["permissions"] = permissions

        allow_list = permissions.setdefault("allow", [])
        if not isinstance(allow_list, list):
            allow_list = []
            permissions["allow"] = allow_list

        allow_entry = "Bash(testguard *)"
        if allow_entry not in allow_list:
            allow_list.append(allow_entry)

        # 4. Update hooks.PreToolUse and hooks.Stop
        hooks_dict = settings.setdefault("hooks", {})
        if not isinstance(hooks_dict, dict):
            hooks_dict = {}
            settings["hooks"] = hooks_dict

        pre_tool_list = hooks_dict.setdefault("PreToolUse", [])
        if not isinstance(pre_tool_list, list):
            pre_tool_list = []
            hooks_dict["PreToolUse"] = pre_tool_list

        if not _has_command_in_hooks(pre_tool_list, "testguard_gate.py"):
            pre_tool_list.append({
                "matcher": "Bash|PowerShell",
                "hooks": [
                    {
                        "type": "command",
                        "command": CLAUDE_HOOK_COMMAND,
                    }
                ],
            })

        stop_list = hooks_dict.setdefault("Stop", [])
        if not isinstance(stop_list, list):
            stop_list = []
            hooks_dict["Stop"] = stop_list

        if not _has_command_in_hooks(stop_list, "testguard_gate.py"):
            stop_list.append({
                "hooks": [
                    {
                        "type": "command",
                        "command": CLAUDE_STOP_COMMAND,
                    }
                ],
            })

        # 5. Write back settings.json with UTF-8 and indent=2
        with open(settings_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
            f.write("\n")

        return True
    except Exception as exc:
        print(f"Error installing Claude hook: {exc}", file=sys.stderr)
        return False


def install_git_hook(git_dir: Optional[str] = None) -> bool:
    """Install TestGuard pre-commit hook into Git repository.

    - Resolves `.git` directory from current directory or custom path.
    - Writes `.git/hooks/pre-commit`.
    - Sets executable permissions (0o755).

    Returns True on success, False on failure.
    """
    try:
        if git_dir is None:
            git_dir = os.path.abspath(".git")
        else:
            git_dir = os.path.abspath(git_dir)
            if os.path.isdir(os.path.join(git_dir, ".git")):
                git_dir = os.path.join(git_dir, ".git")

        if not os.path.isdir(git_dir):
            print(f"Error: Git directory not found at '{git_dir}'. Make sure you are inside a git repository.", file=sys.stderr)
            return False

        hooks_dir = os.path.join(git_dir, "hooks")
        os.makedirs(hooks_dir, exist_ok=True)

        hook_path = os.path.join(hooks_dir, "pre-commit")
        with open(hook_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(GIT_PRE_COMMIT_SCRIPT)

        try:
            os.chmod(hook_path, 0o755)
        except OSError:
            pass

        return True
    except Exception as exc:
        print(f"Error installing Git hook: {exc}", file=sys.stderr)
        return False
