import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from testguard.config import TestGuardConfig, load_config
from testguard.models import Verdict, ViolationType
from testguard.verdict import evaluate_changes
from testguard.cli import main


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_file(self, rel_path: str, content: str) -> str:
        full_path = os.path.join(self.cwd, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        return full_path

    def test_default_config_when_no_file_exists(self):
        cfg = load_config(cwd=self.cwd)
        self.assertIsInstance(cfg, TestGuardConfig)
        self.assertEqual(cfg.exclude_patterns, [])
        self.assertEqual(cfg.literal_whitelist, set())
        self.assertIsNone(cfg.base_ref)

    def test_load_valid_json_config(self):
        config_data = {
            "exclude_patterns": ["legacy/**", "benchmarks/*"],
            "literal_whitelist": ["mock_user", "localhost", 42],
            "base_ref": "main",
        }
        self._write_file(".testguard.json", json.dumps(config_data))

        cfg = load_config(cwd=self.cwd)
        self.assertEqual(cfg.exclude_patterns, ["legacy/**", "benchmarks/*"])
        self.assertEqual(cfg.literal_whitelist, {"mock_user", "localhost", 42})
        self.assertEqual(cfg.base_ref, "main")

    def test_load_explicit_config_path(self):
        config_data = {
            "exclude_patterns": ["vendor/**"],
            "literal_whitelist": ["test_token"],
            "base_ref": "master",
        }
        custom_path = self._write_file("configs/custom.json", json.dumps(config_data))

        cfg = load_config(cwd=self.cwd, config_path=custom_path)
        self.assertEqual(cfg.exclude_patterns, ["vendor/**"])
        self.assertEqual(cfg.literal_whitelist, {"test_token"})
        self.assertEqual(cfg.base_ref, "master")

    def test_load_pyproject_toml_config(self):
        toml_content = """
[project]
name = "my-project"

[tool.testguard]
base_ref = "origin/main"
exclude_patterns = ["legacy/*", "archive/**"]
literal_whitelist = ["localhost", "127.0.0.1", 8080]
"""
        self._write_file("pyproject.toml", toml_content)

        cfg = load_config(cwd=self.cwd)
        self.assertEqual(cfg.base_ref, "origin/main")
        self.assertEqual(cfg.exclude_patterns, ["legacy/*", "archive/**"])
        self.assertEqual(cfg.literal_whitelist, {"localhost", "127.0.0.1", 8080})

    def test_malformed_json_fails_open_with_default_config(self):
        self._write_file(".testguard.json", "{ this is not valid json :(")
        stderr_capture = io.StringIO()

        with patch("sys.stderr", stderr_capture):
            cfg = load_config(cwd=self.cwd)

        self.assertIsInstance(cfg, TestGuardConfig)
        self.assertEqual(cfg.exclude_patterns, [])
        self.assertEqual(cfg.literal_whitelist, set())
        self.assertIsNone(cfg.base_ref)
        self.assertIn("Warning", stderr_capture.getvalue())

    def test_nonexistent_explicit_config_fails_open_with_warning(self):
        stderr_capture = io.StringIO()
        with patch("sys.stderr", stderr_capture):
            cfg = load_config(cwd=self.cwd, config_path="nonexistent.json")

        self.assertIsInstance(cfg, TestGuardConfig)
        self.assertEqual(cfg.exclude_patterns, [])
        self.assertEqual(cfg.literal_whitelist, set())
        self.assertIsNone(cfg.base_ref)
        self.assertIn("Warning", stderr_capture.getvalue())

    def test_exclude_patterns_sanitization(self):
        cfg = TestGuardConfig(exclude_patterns=["", "   ", "legacy/*", "archive/**"])
        self.assertEqual(cfg.exclude_patterns, ["legacy/*", "archive/**"])

        # Check parsing with empty or whitespace patterns from JSON
        self._write_file(".testguard.json", json.dumps({"exclude_patterns": ["", "  ", "tests/fixtures/*"]}))
        loaded = load_config(cwd=self.cwd)
        self.assertEqual(loaded.exclude_patterns, ["tests/fixtures/*"])


class TestConfigIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = self.temp_dir.name
        self._run_git(["init"])
        self._run_git(["config", "user.name", "Test Agent"])
        self._run_git(["config", "user.email", "agent@example.com"])

    def tearDown(self):
        self.temp_dir.cleanup()

    def _run_git(self, args: list[str]) -> str:
        res = subprocess.run(
            ["git"] + args,
            cwd=self.repo_dir,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        return res.stdout.strip()

    def _write_file(self, rel_path: str, content: str) -> None:
        full_path = os.path.join(self.repo_dir, rel_path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

    def test_evaluate_changes_filters_excluded_files(self):
        # Base commit
        self._write_file("src/math.py", "def add(a, b): return a + b\n")
        self._write_file(
            "tests/test_math.py",
            "from src.math import add\ndef test_add(): assert add(1, 2) == 3\n",
        )
        self._write_file(
            "legacy/test_legacy.py",
            "def test_old():\n    assert 1 == 1\n    assert 2 == 2\n",
        )
        self._run_git(["add", "."])
        self._run_git(["commit", "-m", "initial commit"])

        # Agent cheats in legacy/test_legacy.py by deleting an assertion
        self._write_file(
            "legacy/test_legacy.py",
            "def test_old():\n    assert 1 == 1\n",
        )

        # Without exclusion -> VETO
        report_without = evaluate_changes(base_ref="HEAD", cwd=self.repo_dir)
        self.assertEqual(report_without.verdict, Verdict.VETO)

        # With exclude_patterns -> PASS
        cfg = TestGuardConfig(exclude_patterns=["legacy/**"])
        report_with = evaluate_changes(base_ref="HEAD", cwd=self.repo_dir, config=cfg)
        self.assertEqual(report_with.verdict, Verdict.PASS)

    def test_evaluate_changes_ignores_whitelisted_literals(self):
        # Base commit
        self._write_file("src/server.py", "def get_host(name):\n    return '0.0.0.0'\n")
        self._write_file(
            "tests/test_server.py",
            "from src.server import get_host\ndef test_host():\n    assert get_host('localhost') == '127.0.0.1'\n",
        )
        self._run_git(["add", "."])
        self._run_git(["commit", "-m", "initial commit"])

        # Agent cheats: hardcodes check for test literal 'localhost'
        self._write_file(
            "src/server.py",
            "def get_host(name):\n    if name == 'localhost':\n        return '127.0.0.1'\n    return '0.0.0.0'\n",
        )

        # Without whitelist -> VETO due to HARDCODED_CHEAT
        report_without = evaluate_changes(base_ref="HEAD", cwd=self.repo_dir)
        self.assertEqual(report_without.verdict, Verdict.VETO)
        self.assertTrue(any(v.type == ViolationType.HARDCODED_CHEAT for v in report_without.violations))

        # With 'localhost' in literal_whitelist -> PASS
        cfg = TestGuardConfig(literal_whitelist={"localhost"})
        report_with = evaluate_changes(base_ref="HEAD", cwd=self.repo_dir, config=cfg)
        self.assertEqual(report_with.verdict, Verdict.PASS)

    def test_config_base_ref_applied_when_evaluating_head(self):
        # 1. Base commit on stable_base with 2 assertions
        self._write_file(
            "tests/test_feature.py",
            "def test_feature():\n    assert 1 == 1\n    assert 2 == 2\n",
        )
        self._run_git(["add", "."])
        self._run_git(["commit", "-m", "commit on stable_base"])
        self._run_git(["branch", "stable_base"])

        # 2. Next commit: assertion removed and .testguard.json added pointing to stable_base
        self._write_file(
            "tests/test_feature.py",
            "def test_feature():\n    assert 1 == 1\n",
        )
        self._write_file(".testguard.json", json.dumps({"base_ref": "stable_base"}))
        self._run_git(["add", "."])
        self._run_git(["commit", "-m", "remove assertion and add config"])

        # Working tree is clean relative to HEAD.
        # If evaluated against HEAD, there would be no changes (PASS).
        # But evaluate_changes(base_ref="HEAD") must resolve base_ref to "stable_base" via config -> VETO.
        report = evaluate_changes(base_ref="HEAD", cwd=self.repo_dir)
        self.assertEqual(report.verdict, Verdict.VETO)
        self.assertTrue(any(v.type == ViolationType.ASSERTION_REMOVED for v in report.violations))

    def test_cli_config_flag(self):
        # Setup repo with cheat that is whitelisted via custom config file
        self._write_file("src/net.py", "def get_ip(name):\n    return '0.0.0.0'\n")
        self._write_file(
            "tests/test_net.py",
            "from src.net import get_ip\ndef test_ip():\n    assert get_ip('mock_net') == '127.0.0.1'\n",
        )
        self._run_git(["add", "."])
        self._run_git(["commit", "-m", "init"])

        # Hardcode cheat checking 'mock_net'
        self._write_file(
            "src/net.py",
            "def get_ip(name):\n    if name == 'mock_net':\n        return '127.0.0.1'\n    return '0.0.0.0'\n",
        )

        # Create custom config whitelisting 'mock_net'
        config_path = os.path.join(self.repo_dir, "custom.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump({"literal_whitelist": ["mock_net"]}, f)

        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            exit_code = main(["check", "--cwd", self.repo_dir, "--config", config_path, "--format", "json"])

        self.assertEqual(exit_code, 0)
        data = json.loads(stdout.getvalue())
        self.assertEqual(data["verdict"], "PASS")
