import os
import subprocess
import tempfile
import unittest

from testguard.cli import main
from testguard.config import TestGuardConfig, load_config
from testguard.models import ViolationType
from testguard.shadow import BaseRefError
from testguard.shadow_runner import run_shadow_tests


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _write(cwd, rel, content):
    path = os.path.join(cwd, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


class TestShadowRunner(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.cwd = self._tmp.name
        _git(self.cwd, "init")
        _git(self.cwd, "config", "user.name", "T")
        _git(self.cwd, "config", "user.email", "t@example.com")
        _write(self.cwd, "calc.py", "def double(x):\n    return x * 2\n")
        _write(self.cwd, "tests/test_calc.py",
               "from calc import double\n\ndef test_double():\n    assert double(21) == 42\n")
        _git(self.cwd, "add", ".")
        _git(self.cwd, "commit", "-m", "base")

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_change_passes(self):
        _write(self.cwd, "calc.py", "def double(x):\n    return x + x\n")
        self.assertEqual(run_shadow_tests("HEAD", cwd=self.cwd), [])

    def test_broken_source_fails_even_if_test_was_rewritten_to_pass(self):
        # Agent breaks the source, then rewrites the test to match the bug.
        _write(self.cwd, "calc.py", "def double(x):\n    return x * 3\n")
        _write(self.cwd, "tests/test_calc.py",
               "from calc import double\n\ndef test_double():\n    assert double(21) == 63\n")
        vios = run_shadow_tests("HEAD", cwd=self.cwd)
        self.assertEqual(len(vios), 1)
        self.assertEqual(vios[0].type, ViolationType.SHADOW_TEST_FAILED)
        self.assertIn("output_tail", vios[0].details)

    def test_deleted_test_file_is_restored_and_run(self):
        _write(self.cwd, "calc.py", "def double(x):\n    return 0\n")
        os.remove(os.path.join(self.cwd, "tests/test_calc.py"))
        vios = run_shadow_tests("HEAD", cwd=self.cwd)
        self.assertEqual(len(vios), 1)

    def test_working_tree_is_not_modified(self):
        _write(self.cwd, "tests/test_calc.py", "def test_double():\n    assert True\n")
        run_shadow_tests("HEAD", cwd=self.cwd)
        with open(os.path.join(self.cwd, "tests/test_calc.py"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "def test_double():\n    assert True\n")

    def test_custom_command_and_timeout(self):
        cfg = TestGuardConfig(shadow_command="python -c \"import sys; sys.exit(3)\"")
        vios = run_shadow_tests("HEAD", cwd=self.cwd, config=cfg)
        self.assertIn("exit 3", vios[0].message)
        cfg = TestGuardConfig(shadow_command="python -c \"import time; time.sleep(5)\"", shadow_timeout=1)
        vios = run_shadow_tests("HEAD", cwd=self.cwd, config=cfg)
        self.assertIn("timed out", vios[0].message)

    def test_invalid_base_ref_raises(self):
        with self.assertRaises(BaseRefError):
            run_shadow_tests("origin/nope", cwd=self.cwd)

    def test_cli_flag_vetoes(self):
        _write(self.cwd, "calc.py", "def double(x):\n    return 0\n")
        self.assertEqual(main(["check", "--base", "HEAD", "--cwd", self.cwd]), 0)
        self.assertEqual(main(["check", "--base", "HEAD", "--cwd", self.cwd, "--shadow-run"]), 1)

    def test_config_enables_shadow_run(self):
        _write(self.cwd, ".testguard.json", '{"shadow_run": true, "shadow_timeout": 60}')
        cfg = load_config(cwd=self.cwd)
        self.assertTrue(cfg.shadow_run)
        self.assertEqual(cfg.shadow_timeout, 60)


if __name__ == "__main__":
    unittest.main()
