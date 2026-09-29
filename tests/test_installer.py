import io
import json
import os
import py_compile
import stat
import tempfile
import unittest
from unittest.mock import patch

from testguard.cli import main
from testguard.installer import (
    CLAUDE_HOOK_COMMAND,
    CLAUDE_STOP_COMMAND,
    install_claude_hook,
    install_git_hook,
)


class TestInstaller(unittest.TestCase):
    def test_install_claude_hook_creates_gate_and_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            success = install_claude_hook(claude_dir=tmpdir)
            self.assertTrue(success)

            # 1. Verify testguard_gate.py created and compiles as valid Python
            gate_path = os.path.join(tmpdir, "hooks", "testguard_gate.py")
            self.assertTrue(os.path.isfile(gate_path))
            py_compile.compile(gate_path, doraise=True)

            with open(gate_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("sys.stdout.reconfigure", content)
            self.assertIn("sys.stderr.reconfigure", content)
            self.assertIn("ensure_ascii=False", content)
            self.assertIn("stop_hook_active", content)
            self.assertIn("testguard", content)

            # 2. Verify settings.json created with correct configuration
            settings_path = os.path.join(tmpdir, "settings.json")
            self.assertTrue(os.path.isfile(settings_path))
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)

            self.assertIn("Bash(testguard *)", settings.get("permissions", {}).get("allow", []))

            pre_tool = settings.get("hooks", {}).get("PreToolUse", [])
            self.assertTrue(any(
                entry.get("matcher") == "Bash|PowerShell" and
                any("testguard_gate.py" in h.get("command", "") for h in entry.get("hooks", []))
                for entry in pre_tool
            ))

            stop_hooks = settings.get("hooks", {}).get("Stop", [])
            self.assertTrue(any(
                any("testguard_gate.py" in h.get("command", "") for h in entry.get("hooks", []))
                for entry in stop_hooks
            ))

    def test_install_claude_hook_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, "settings.json")
            initial_settings = {
                "theme": "dark",
                "customSetting": 42,
                "permissions": {
                    "allow": ["Bash(npm *)", "Read(*)"]
                },
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "python",
                            "hooks": [{"type": "command", "command": "echo test"}]
                        }
                    ]
                }
            }
            with open(settings_path, "w", encoding="utf-8") as f:
                json.dump(initial_settings, f, indent=2)

            success = install_claude_hook(claude_dir=tmpdir)
            self.assertTrue(success)

            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)

            # Preserved verbatim
            self.assertEqual(settings.get("theme"), "dark")
            self.assertEqual(settings.get("customSetting"), 42)
            self.assertIn("Bash(npm *)", settings["permissions"]["allow"])
            self.assertIn("Read(*)", settings["permissions"]["allow"])
            self.assertIn("Bash(testguard *)", settings["permissions"]["allow"])

            # Existing PreToolUse preserved, new one appended
            pre_tool = settings["hooks"]["PreToolUse"]
            self.assertEqual(len(pre_tool), 2)
            self.assertEqual(pre_tool[0]["matcher"], "python")
            self.assertEqual(pre_tool[1]["matcher"], "Bash|PowerShell")

    def test_install_claude_hook_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertTrue(install_claude_hook(claude_dir=tmpdir))
            self.assertTrue(install_claude_hook(claude_dir=tmpdir))

            settings_path = os.path.join(tmpdir, "settings.json")
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)

            allow = settings.get("permissions", {}).get("allow", [])
            self.assertEqual(allow.count("Bash(testguard *)"), 1)

            pre_tool = settings.get("hooks", {}).get("PreToolUse", [])
            self.assertEqual(len(pre_tool), 1)

            stop_hooks = settings.get("hooks", {}).get("Stop", [])
            self.assertEqual(len(stop_hooks), 1)

    def test_install_git_hook_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir)

            success = install_git_hook(git_dir=git_dir)
            self.assertTrue(success)

            hook_path = os.path.join(git_dir, "hooks", "pre-commit")
            self.assertTrue(os.path.isfile(hook_path))
            with open(hook_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("testguard check", content)
            self.assertIn("#!/bin/sh", content)

    def test_install_git_hook_with_repo_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir)

            # Passing repo dir containing .git
            success = install_git_hook(git_dir=tmpdir)
            self.assertTrue(success)

            hook_path = os.path.join(git_dir, "hooks", "pre-commit")
            self.assertTrue(os.path.isfile(hook_path))

    def test_install_git_hook_fails_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            non_existent = os.path.join(tmpdir, "not_git")
            success = install_git_hook(git_dir=non_existent)
            self.assertFalse(success)

    def test_cli_init_claude(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = io.StringIO()
            with patch("sys.stdout", out):
                code = main(["init", "--hook", "claude", "--claude-dir", tmpdir])
            self.assertEqual(code, 0)
            self.assertIn("Claude Code hook installed", out.getvalue())
            self.assertTrue(os.path.isfile(os.path.join(tmpdir, "hooks", "testguard_gate.py")))

    def test_cli_init_git(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir)
            out = io.StringIO()
            with patch("sys.stdout", out):
                code = main(["init", "--hook", "git", "--git-dir", git_dir])
            self.assertEqual(code, 0)
            self.assertIn("Git pre-commit hook installed", out.getvalue())
            self.assertTrue(os.path.isfile(os.path.join(git_dir, "hooks", "pre-commit")))

    def test_cli_init_git_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = os.path.join(tmpdir, "nonexistent_git")
            out = io.StringIO()
            with patch("sys.stdout", out):
                code = main(["init", "--hook", "git", "--git-dir", git_dir])
            self.assertEqual(code, 1)
            self.assertIn("Failed", out.getvalue())

    def test_cli_init_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = os.path.join(tmpdir, "claude")
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir)
            out = io.StringIO()
            with patch("sys.stdout", out):
                code = main(["init", "--hook", "all", "--claude-dir", claude_dir, "--git-dir", git_dir])
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(os.path.join(claude_dir, "hooks", "testguard_gate.py")))
            self.assertTrue(os.path.isfile(os.path.join(git_dir, "hooks", "pre-commit")))

    def test_install_claude_hook_fails_on_malformed_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, "settings.json")
            with open(settings_path, "w", encoding="utf-8") as f:
                f.write("{ invalid json")

            err = io.StringIO()
            with patch("sys.stderr", err):
                success = install_claude_hook(claude_dir=tmpdir)
            self.assertFalse(success)
            self.assertIn("Malformed settings.json", err.getvalue())

            # Verify corrupted file was not overwritten
            with open(settings_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "{ invalid json")

    def test_install_claude_hook_fails_on_non_dict_settings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            settings_path = os.path.join(tmpdir, "settings.json")
            with open(settings_path, "w", encoding="utf-8") as f:
                f.write("[1, 2, 3]")

            err = io.StringIO()
            with patch("sys.stderr", err):
                success = install_claude_hook(claude_dir=tmpdir)
            self.assertFalse(success)
            self.assertIn("expected JSON object", err.getvalue())

            # Verify original content was not overwritten
            with open(settings_path, "r", encoding="utf-8") as f:
                self.assertEqual(f.read(), "[1, 2, 3]")


if __name__ == "__main__":
    unittest.main()
