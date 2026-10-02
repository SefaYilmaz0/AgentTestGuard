"""Configuration loader and schema for TestGuard.

Supports `.testguard.json` and `pyproject.toml` [tool.testguard] configurations
for path exclusions, mock literal whitelisting, and default base branches.
"""

from dataclasses import dataclass, field
import fnmatch
import json
import os
import sys
from typing import Any, Optional

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore


@dataclass
class TestGuardConfig:
    __test__ = False  # not a pytest test class

    exclude_patterns: list[str] = field(default_factory=list)
    literal_whitelist: set = field(default_factory=set)
    base_ref: Optional[str] = None
    shadow_run: bool = False
    shadow_command: Optional[str] = None
    shadow_timeout: int = 300

    def __post_init__(self) -> None:
        if not isinstance(self.exclude_patterns, list):
            self.exclude_patterns = list(self.exclude_patterns)
        self.exclude_patterns = [str(p).strip() for p in self.exclude_patterns if p and str(p).strip()]
        if not isinstance(self.literal_whitelist, set):
            self.literal_whitelist = set(self.literal_whitelist)


def is_file_excluded(file_path: str, patterns: list[str]) -> bool:
    """Check if a file path matches any exclusion pattern."""
    if not patterns:
        return False
    norm_path = file_path.replace("\\", "/").lstrip("/")
    for pat in patterns:
        if not pat or not str(pat).strip():
            continue
        pat_norm = str(pat).replace("\\", "/").strip().lstrip("/")
        if not pat_norm:
            continue
        if fnmatch.fnmatch(norm_path, pat_norm) or fnmatch.fnmatch(norm_path, f"*/{pat_norm}"):
            return True
        pat_dir = pat_norm.rstrip("/")
        if norm_path == pat_dir or norm_path.startswith(pat_dir + "/"):
            return True
        if not pat_norm.endswith("*"):
            if fnmatch.fnmatch(norm_path, f"{pat_norm}/*") or fnmatch.fnmatch(norm_path, f"*/{pat_norm}/*"):
                return True
    return False


def _parse_dict_to_config(data: dict[str, Any]) -> TestGuardConfig:
    raw_patterns = data.get("exclude_patterns", [])
    if isinstance(raw_patterns, (list, set, tuple)):
        exclude_patterns = [str(p).strip() for p in raw_patterns if p and str(p).strip()]
    else:
        exclude_patterns = []

    raw_whitelist = data.get("literal_whitelist", [])
    if isinstance(raw_whitelist, (list, set, tuple)):
        literal_whitelist = set(raw_whitelist)
    else:
        literal_whitelist = set()

    base_ref = data.get("base_ref")
    if base_ref is not None:
        base_ref = str(base_ref)

    shadow_command = data.get("shadow_command")
    shadow_command = str(shadow_command) if shadow_command else None
    try:
        shadow_timeout = int(data.get("shadow_timeout", 300))
        if shadow_timeout <= 0:
            shadow_timeout = 300
    except (TypeError, ValueError):
        shadow_timeout = 300

    return TestGuardConfig(
        exclude_patterns=exclude_patterns,
        literal_whitelist=literal_whitelist,
        base_ref=base_ref,
        shadow_run=data.get("shadow_run") is True,
        shadow_command=shadow_command,
        shadow_timeout=shadow_timeout,
    )


def _parse_toml_fallback(content: str) -> dict[str, Any]:
    """Fallback line-based parser for pyproject.toml [tool.testguard] section."""
    result: dict[str, Any] = {}
    in_section = False
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_section = (line == "[tool.testguard]")
            continue
        if in_section and "=" in line:
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip()
            try:
                parsed_val = json.loads(val)
            except Exception:
                parsed_val = val.strip('"\'')
            result[key] = parsed_val
    return result


def _load_toml_file(file_path: str) -> Optional[TestGuardConfig]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if tomllib is not None:
            data = tomllib.loads(content)
            tg_data = data.get("tool", {}).get("testguard")
        else:
            tg_data = _parse_toml_fallback(content)

        if tg_data and isinstance(tg_data, dict):
            return _parse_dict_to_config(tg_data)
        return None
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to parse TOML configuration '{file_path}': {e}\n")
        return TestGuardConfig()


def _load_json_file(file_path: str) -> TestGuardConfig:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Config root must be a JSON object")
        return _parse_dict_to_config(data)
    except Exception as e:
        sys.stderr.write(f"Warning: Failed to parse configuration file '{file_path}': {e}\n")
        return TestGuardConfig()


def load_config(cwd: str = ".", config_path: Optional[str] = None) -> TestGuardConfig:
    """Load TestGuard configuration from file or defaults.

    Checks config_path or os.path.join(cwd, ".testguard.json"), then pyproject.toml.
    Fails open safely by returning default configuration if file is missing or malformed.
    """
    if config_path:
        target_path = config_path if os.path.isabs(config_path) else os.path.join(cwd, config_path)
        if not os.path.isfile(target_path):
            sys.stderr.write(f"Warning: Configuration file not found: {target_path}\n")
            return TestGuardConfig()

        if target_path.endswith(".toml"):
            cfg = _load_toml_file(target_path)
            return cfg if cfg is not None else TestGuardConfig()
        return _load_json_file(target_path)

    json_path = os.path.join(cwd, ".testguard.json")
    if os.path.isfile(json_path):
        return _load_json_file(json_path)

    toml_path = os.path.join(cwd, "pyproject.toml")
    if os.path.isfile(toml_path):
        cfg = _load_toml_file(toml_path)
        if cfg is not None:
            return cfg

    return TestGuardConfig()
