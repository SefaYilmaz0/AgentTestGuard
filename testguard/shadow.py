"""Git Shadow Diff & Isolation Engine for TestGuard.

Extracts modified files between branches/refs and isolates baseline test
definitions directly from git history to prevent test manipulation gaming.
"""

import os
import subprocess
from typing import Optional


def is_test_file(path: str) -> bool:
    """Determine whether a given file path is a test file.
    
    Detects Python, JS/TS, and general test file conventions:
    - Directories: tests/, test/, __tests__/
    - Basenames: test_*, *_test.py, *.test.[jt]sx?, *.spec.[jt]sx?
    """
    normalized = path.replace("\\", "/").lower()
    basename = os.path.basename(normalized)

    in_test_dir = (
        "/tests/" in normalized
        or "/test/" in normalized
        or "/__tests__/" in normalized
        or normalized.startswith("tests/")
        or normalized.startswith("test/")
        or normalized.startswith("__tests__/")
    )

    test_suffixes = (
        "_test.py",
        ".test.py",
        ".test.js",
        ".test.ts",
        ".test.jsx",
        ".test.tsx",
        ".spec.js",
        ".spec.ts",
        ".spec.jsx",
        ".spec.tsx",
    )

    has_test_name = (
        basename.startswith("test_")
        or basename.endswith(test_suffixes)
    )

    return in_test_dir or has_test_name


def get_changed_files(base_ref: str, cwd: str = ".") -> list[str]:
    """Retrieve list of files changed between base_ref and working tree.
    
    Falls back to diff against HEAD if base_ref is invalid or unavailable.
    Returns normalized forward-slash paths.
    """
    try:
        cmd = ["git", "diff", "--name-only", base_ref]
        res = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if res.returncode != 0:
            # Fallback to diff against HEAD if base_ref fails
            cmd = ["git", "diff", "--name-only", "HEAD"]
            res = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
            )
            if res.returncode != 0:
                return []
        return [line.strip().replace("\\", "/") for line in res.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []


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
