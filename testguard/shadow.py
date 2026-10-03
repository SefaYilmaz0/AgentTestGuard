"""Git Shadow Diff & Isolation Engine for TestGuard.

Extracts modified files between branches/refs and isolates baseline test
definitions directly from git history to prevent test manipulation gaming.
"""

import os
import subprocess
from typing import Optional


class BaseRefError(Exception):
    """Raised when the base ref cannot be resolved to a commit.

    Comparing against an unresolvable ref would silently diff nothing and pass,
    so the gate must fail closed instead.
    """


def ensure_base_ref(base_ref: str, cwd: str = ".") -> None:
    """Raise BaseRefError unless base_ref resolves to a commit in the repo at cwd."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}"],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        raise BaseRefError(f"Cannot run git to resolve base ref '{base_ref}': {exc}") from exc
    if res.returncode != 0:
        raise BaseRefError(
            f"Base ref '{base_ref}' could not be resolved to a commit in '{cwd}'. "
            "Fetch it first (e.g. `git fetch origin <branch>`) or pass a valid --base."
        )


_TEST_DIRS = ("tests", "test", "__tests__", "spec", "specs", "e2e", "__mocks__")

_TEST_SUFFIXES = tuple(
    f".{kind}.{ext}"
    for kind in ("test", "spec", "e2e", "e2e-spec", "cy")
    for ext in ("js", "ts", "jsx", "tsx", "mjs", "cjs", "mts", "cts")
) + ("_test.py", ".test.py", "_tests.py")

_TEST_BASENAMES = ("conftest.py", "tests.py")


def is_test_file(path: str) -> bool:
    """Determine whether a given file path is a test file.

    Detects Python, JS/TS, and general test file conventions:
    - Directories: tests/, test/, __tests__/, spec/, specs/, e2e/, __mocks__/ (at any depth)
    - Python: test_*.py, *_test.py, *_tests.py, tests.py, conftest.py
    - JS/TS: *.test|spec|e2e|e2e-spec|cy.[jt]sx? and the m/c variants (.mjs .cjs .mts .cts)
    """
    normalized = path.replace("\\", "/").lower()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    parts = [p for p in normalized.split("/") if p]
    if not parts:
        return False
    basename = parts[-1]

    in_test_dir = any(d in _TEST_DIRS for d in parts[:-1])
    has_test_name = (
        basename.startswith("test_")
        or basename in _TEST_BASENAMES
        or basename.endswith(_TEST_SUFFIXES)
    )
    return in_test_dir or has_test_name


def get_changed_files(base_ref: str, cwd: str = ".") -> list[str]:
    """Retrieve list of files changed between base_ref and working tree,
    including untracked files in the working tree.
    
    Raises BaseRefError if base_ref cannot be resolved (fail closed).
    Returns normalized forward-slash paths preserving uniqueness and order.
    """
    ensure_base_ref(base_ref, cwd=cwd)
    changed: list[str] = []
    seen: set[str] = set()

    def add_path(p: str) -> None:
        norm = p.strip().replace("\\", "/")
        if norm.startswith("./"):
            norm = norm[2:]
        if norm and norm not in seen:
            seen.add(norm)
            changed.append(norm)

    # 1. Tracked modified / added files from git diff
    try:
        cmd = ["git", "diff", "--name-only", "-M20%", base_ref]
        res = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if res.returncode != 0:
            raise BaseRefError(f"git diff against '{base_ref}' failed: {res.stderr.strip()}")
        for line in res.stdout.splitlines():
            add_path(line)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    # 2. Untracked files in working tree (excluding standard ignored files)
    try:
        cmd = ["git", "ls-files", "--others", "--exclude-standard"]
        res = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                add_path(line)
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        pass

    return changed


def get_renamed_files(base_ref: str, cwd: str = ".") -> dict[str, str]:
    """Map new path -> old path for files renamed/moved between base_ref and the working tree."""
    ensure_base_ref(base_ref, cwd=cwd)
    renames: dict[str, str] = {}
    try:
        res = subprocess.run(
            ["git", "diff", "--name-status", "-M20%", "-z", base_ref],
            cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return renames
    if res.returncode != 0:
        return renames
    fields = res.stdout.split("\0")
    i = 0
    while i < len(fields):
        status = fields[i]
        if status.startswith(("R", "C")) and i + 2 < len(fields):
            old, new = fields[i + 1], fields[i + 2]
            if status.startswith("R"):
                renames[new.replace("\\", "/")] = old.replace("\\", "/")
            i += 3
        else:
            i += 2
    return renames


def get_file_content_at_ref(ref: str, file_path: str, cwd: str = ".") -> Optional[str]:
    """Retrieve the content of a file at a specific git ref (e.g. base branch).
    
    Returns None if the file did not exist at that ref or if git fails.
    """
    try:
        if os.path.isabs(file_path):
            file_path = os.path.relpath(file_path, cwd)
        normalized_path = file_path.replace("\\", "/")
        if normalized_path.startswith("./"):
            normalized_path = normalized_path[2:]
        elif normalized_path.startswith("/"):
            normalized_path = normalized_path[1:]

        cmd = ["git", "show", f"{ref}:{normalized_path}"]
        res = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if res.returncode == 0:
            return res.stdout
        return None
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None
