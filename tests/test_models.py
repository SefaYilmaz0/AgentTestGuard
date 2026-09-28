# tests/test_models.py
import unittest
from testguard.models import ViolationType, Violation, Verdict, Report, CheckResult

class TestModels(unittest.TestCase):
    def test_violation_creation_and_serialization(self):
        v = Violation(
            type=ViolationType.ASSERTION_REMOVED,
            file_path="tests/test_demo.py",
            line_number=12,
            symbol_name="test_addition",
            message="Assertion count dropped from 2 to 1"
        )
        self.assertEqual(v.type, ViolationType.ASSERTION_REMOVED)
        self.assertEqual(v.line_number, 12)
        d = v.to_dict()
        self.assertEqual(d["type"], "ASSERTION_REMOVED")
        self.assertEqual(d["file_path"], "tests/test_demo.py")

    def test_report_verdict(self):
        v = Violation(
            type=ViolationType.TEST_SKIPPED,
            file_path="tests/test_demo.py",
            line_number=5,
            symbol_name="test_skip",
            message="Test skipped"
        )
        report = Report(verdict=Verdict.VETO, violations=[v], summary="Goal gaming detected")
        self.assertEqual(report.verdict, Verdict.VETO)
        self.assertFalse(report.is_passed)
        self.assertEqual(len(report.violations), 1)

    def test_pass_report_and_check_result_alias(self):
        report = CheckResult(verdict=Verdict.PASS, summary="Clean")
        self.assertTrue(report.is_passed)
        self.assertEqual(len(report.violations), 0)
        d = report.to_dict()
        self.assertEqual(d["verdict"], "PASS")
        self.assertEqual(d["violations"], [])

if __name__ == "__main__":
    unittest.main()
