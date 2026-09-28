import io
import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from testguard.models import Report, Verdict, Violation, ViolationType
from testguard.verdict import evaluate_changes, format_markdown_report, run_testguard
from testguard.cli import main


class TestCLI(unittest.TestCase):
    def test_format_markdown_report_pass(self):
        report = Report(verdict=Verdict.PASS, violations=[])
        md = format_markdown_report(report)
        self.assertIn("PASSED", md)
        self.assertIn("🛡️", md)

    def test_format_markdown_report_veto(self):
        v = Violation(
            type=ViolationType.ASSERTION_REMOVED,
            file_path="tests/test_x.py",
            line_number=10,
            symbol_name="test_fn",
            message="1 assertion removed",
        )
        report = Report(verdict=Verdict.VETO, violations=[v])
        md = format_markdown_report(report)
        self.assertIn("VETO", md)
        self.assertIn("🚨", md)
        self.assertIn("tests/test_x.py", md)
        self.assertIn("ASSERTION_REMOVED", md)
        self.assertIn("`test_fn`", md)

    def test_cli_help(self):
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                main(["--help"])
            self.assertEqual(cm.exception.code, 0)

    def test_cli_check_help(self):
        with patch("sys.stdout", io.StringIO()), patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                main(["check", "--help"])
            self.assertEqual(cm.exception.code, 0)

    @patch("testguard.cli.evaluate_changes")
    def test_cli_check_json_pass(self, mock_eval):
        mock_eval.return_value = Report(
            verdict=Verdict.PASS,
            violations=[],
            summary="0 violations detected, verified clean",
            execution_time_ms=12.5,
        )
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["check", "--format", "json"])

        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["verdict"], "PASS")
        self.assertEqual(output["summary"], "0 violations detected, verified clean")

    @patch("testguard.cli.evaluate_changes")
    def test_cli_check_json_veto(self, mock_eval):
        v = Violation(
            type=ViolationType.HARDCODED_CHEAT,
            file_path="src/login.py",
            line_number=42,
            symbol_name="login",
            message="Hardcoded check for test literal",
        )
        mock_eval.return_value = Report(
            verdict=Verdict.VETO,
            violations=[v],
            summary="1 violations detected",
            execution_time_ms=25.0,
        )
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["check", "--format", "json"])

        self.assertEqual(code, 1)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output["verdict"], "VETO")
        self.assertEqual(len(output["violations"]), 1)

    @patch("testguard.cli.evaluate_changes")
    def test_cli_check_markdown_veto(self, mock_eval):
        v = Violation(
            type=ViolationType.TEST_SKIPPED,
            file_path="tests/test_x.py",
            line_number=5,
            symbol_name="test_foo",
            message="Test 'test_foo' has skip decorator",
        )
        mock_eval.return_value = Report(
            verdict=Verdict.VETO,
            violations=[v],
            summary="1 violations detected",
            execution_time_ms=10.0,
        )
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["check", "--format", "markdown"])

        self.assertEqual(code, 1)
        self.assertIn("🚨 **TestGuard: VETO**", stdout.getvalue())
        self.assertIn("TEST_SKIPPED", stdout.getvalue())

    @patch("testguard.cli.evaluate_changes")
    def test_cli_default_text_pass(self, mock_eval):
        mock_eval.return_value = Report(
            verdict=Verdict.PASS,
            violations=[],
            summary="0 violations detected, verified clean",
            execution_time_ms=5.0,
        )
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main([])

        self.assertEqual(code, 0)
        self.assertIn("PASSED", stdout.getvalue())

    @patch("testguard.cli.evaluate_changes")
    def test_cli_text_veto(self, mock_eval):
        v = Violation(
            type=ViolationType.ASSERTION_REMOVED,
            file_path="tests/test_bar.py",
            line_number=15,
            symbol_name="test_bar",
            message="Assertion count decreased",
        )
        mock_eval.return_value = Report(
            verdict=Verdict.VETO,
            violations=[v],
            summary="1 violations detected",
            execution_time_ms=8.0,
        )
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = main(["check", "--format", "text"])

        self.assertEqual(code, 1)
        self.assertIn("VETO", stdout.getvalue())
        self.assertIn("tests/test_bar.py:15", stdout.getvalue())

    def test_evaluate_changes_in_real_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup git repo
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "TestUser"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, check=True)

            tests_dir = os.path.join(tmpdir, "tests")
            src_dir = os.path.join(tmpdir, "src")
            os.makedirs(tests_dir)
            os.makedirs(src_dir)

            test_file = os.path.join(tests_dir, "test_calc.py")
            src_file = os.path.join(src_dir, "calc.py")

            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_add():\n    assert add(2, 3) == 5\n    assert add(0, 0) == 0\n")

            with open(src_file, "w", encoding="utf-8") as f:
                f.write("def add(a, b):\n    return a + b\n")

            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmpdir, check=True)

            # Test 1: Clean - no changes
            rep_clean = evaluate_changes("HEAD", cwd=tmpdir)
            self.assertTrue(rep_clean.is_passed)
            self.assertEqual(len(rep_clean.violations), 0)

            # Test 2: AI removed assertion in test_calc.py
            with open(test_file, "w", encoding="utf-8") as f:
                f.write("def test_add():\n    assert add(2, 3) == 5\n")

            rep_cheated = evaluate_changes("HEAD", cwd=tmpdir)
            self.assertFalse(rep_cheated.is_passed)
            self.assertEqual(rep_cheated.verdict, Verdict.VETO)
            self.assertTrue(any(v.type == ViolationType.ASSERTION_REMOVED for v in rep_cheated.violations))

            # Test run_testguard alias
            rep_alias = run_testguard("HEAD", cwd=tmpdir)
            self.assertEqual(rep_alias.verdict, Verdict.VETO)


if __name__ == "__main__":
    unittest.main()
