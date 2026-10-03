"""Shadow Test Runner (Layer 1).

Runs the *base branch* test files against the *working tree* source code.
The working tree is copied into a throwaway directory, every test file from
base_ref is restored over it (undoing edits and deletions), and the test
command runs there. An agent that tampered with a test cannot influence the
outcome, because the tampered file never executes.
"""

import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

from testguard.config import TestGuardConfig, is_file_excluded
from testguard.models import Violation, ViolationType
from testguard.shadow import BaseRefError, ensure_base_ref, get_file_content_at_ref, is_test_file

# Not copied into the shadow workspace.
_SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".venv", "venv", ".tox", ".mypy_cache"}
# Symlinked instead of copied (large, read-only dependency trees).
_LINK_DIRS = {"node_modules"}
_OUTPUT_TAIL = 2000


def list_base_test_files(base_ref: str, cwd: str = ".") -> list[str]:
    """Test files (as recorded in base_ref) that exist at base_ref."""
    ensure_base_ref(base_ref, cwd=cwd)
    res = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", base_ref],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if res.returncode != 0:
        raise BaseRefError(f"git ls-tree '{base_ref}' failed: {res.stderr.strip()}")
    return [p for p in res.stdout.splitlines() if p and is_test_file(p)]


def _copy_workspace(src: str, dst: str) -> None:
    for root, dirs, files in os.walk(src):
        rel_root = os.path.relpath(root, src)
        target_root = dst if rel_root == "." else os.path.join(dst, rel_root)
        os.makedirs(target_root, exist_ok=True)
        keep = []
        for d in dirs:
            if d in _SKIP_DIRS:
                continue
            if d in _LINK_DIRS:
                try:
                    os.symlink(os.path.abspath(os.path.join(root, d)), os.path.join(target_root, d))
                except OSError:
                    pass
                continue
            keep.append(d)
        dirs[:] = keep
        for f in files:
            try:
                shutil.copy2(os.path.join(root, f), os.path.join(target_root, f))
            except OSError:
                pass


def _build_command(config: TestGuardConfig, py_files: list[str], other_files: list[str]) -> Optional[list[str]]:
    if config.shadow_command:
        cmd = shlex.split(config.shadow_command, posix=(os.name != "nt"))
        if os.name == "nt":
            # non-POSIX shlex keeps the surrounding quotes; strip them like a shell would
            cmd = [t[1:-1] if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'" else t for t in cmd]
        if "{files}" in cmd:
            i = cmd.index("{files}")
            return cmd[:i] + py_files + other_files + cmd[i + 1:]
        return cmd
    if py_files:
        return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *py_files]
    return None


def run_shadow_tests(base_ref: str, cwd: str = ".", config: Optional[TestGuardConfig] = None) -> list[Violation]:
    """Run base-branch tests against current sources; return violations on failure."""
    config = config or TestGuardConfig()
    base_tests = [
        p for p in list_base_test_files(base_ref, cwd=cwd)
        if not (config.exclude_patterns and is_file_excluded(p, config.exclude_patterns))
    ]
    if not base_tests:
        return []

    py_files = [p for p in base_tests if p.endswith(".py") and os.path.basename(p) != "conftest.py"]
    other_files = [p for p in base_tests if not p.endswith(".py")]

    with tempfile.TemporaryDirectory(prefix="testguard-shadow-") as tmp:
        _copy_workspace(os.path.abspath(cwd), tmp)

        # Force every base test file (and conftest/fixtures under test dirs) back to its base content.
        for rel in base_tests:
            content = get_file_content_at_ref(base_ref, rel, cwd=cwd)
            if content is None:
                continue
            dest = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8", newline="") as f:
                f.write(content)

        cmd = _build_command(config, py_files, other_files)
        if cmd is None:
            return []

        env = dict(os.environ)
        env["PYTHONPATH"] = tmp + os.pathsep + env.get("PYTHONPATH", "")
        try:
            res = subprocess.run(
                cmd, cwd=tmp, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=config.shadow_timeout,
            )
        except subprocess.TimeoutExpired:
            return [Violation(
                type=ViolationType.SHADOW_TEST_FAILED,
                file_path="<shadow-run>",
                message=f"Base-branch tests timed out after {config.shadow_timeout}s",
                details={"command": cmd},
            )]
        except (OSError, subprocess.SubprocessError) as exc:
            return [Violation(
                type=ViolationType.SHADOW_TEST_FAILED,
                file_path="<shadow-run>",
                message=f"Could not run shadow test command: {exc}",
                details={"command": cmd},
            )]

    if res.returncode == 0:
        return []
    output = (res.stdout + res.stderr).strip()
    return [Violation(
        type=ViolationType.SHADOW_TEST_FAILED,
        file_path="<shadow-run>",
        message=f"Base-branch tests fail against the modified sources (exit {res.returncode})",
        details={"command": cmd, "output_tail": output[-_OUTPUT_TAIL:]},
    )]
