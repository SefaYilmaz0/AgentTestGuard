import unittest
from testguard.models import ViolationType
from testguard.ast_diff import analyze_ast_diff, analyze_test_code


class TestASTDiff(unittest.TestCase):
    def test_detects_removed_assertion(self):
        base_code = """
def test_calc():
    res = add(2, 3)
    assert res == 5
    assert res > 0
"""
        head_code = """
def test_calc():
    res = add(2, 3)
    assert res == 5
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_calc.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.ASSERTION_REMOVED)
        self.assertEqual(violations[0].symbol_name, "test_calc")

    def test_detects_unittest_style_assertion_removal(self):
        base_code = """
def test_calc(self):
    self.assertEqual(add(2, 3), 5)
    self.assertTrue(5 > 0)
"""
        head_code = """
def test_calc(self):
    self.assertEqual(add(2, 3), 5)
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_calc.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.ASSERTION_REMOVED)
        self.assertEqual(violations[0].symbol_name, "test_calc")

    def test_detects_added_skip_decorator(self):
        code = """
import pytest

@pytest.mark.skip(reason="Fails on AI")
def test_difficult():
    assert complex_operation() == 42
"""
        violations = analyze_test_code(code, file_path="tests/test_skip.py")
        self.assertTrue(any(v.type == ViolationType.TEST_SKIPPED for v in violations))
        skip_violations = [v for v in violations if v.type == ViolationType.TEST_SKIPPED]
        self.assertEqual(skip_violations[0].symbol_name, "test_difficult")

    def test_detects_skipif_and_xfail_decorators(self):
        code = """
import pytest

@pytest.mark.skipif(condition=True, reason="Skip on CI")
def test_skipif():
    assert True

@pytest.mark.xfail
def test_xfail():
    assert False
"""
        violations = analyze_test_code(code, file_path="tests/test_skip_xfail.py")
        skip_violations = [v for v in violations if v.type == ViolationType.TEST_SKIPPED]
        self.assertEqual(len(skip_violations), 2)
        symbols = {v.symbol_name for v in skip_violations}
        self.assertEqual(symbols, {"test_skipif", "test_xfail"})

    def test_detects_swallowed_exception(self):
        code = """
def test_flaky():
    try:
        do_risky_call()
    except Exception:
        pass
"""
        violations = analyze_test_code(code, file_path="tests/test_swallow.py")
        self.assertTrue(any(v.type == ViolationType.EXCEPTION_SWALLOWED for v in violations))
        swallowed = [v for v in violations if v.type == ViolationType.EXCEPTION_SWALLOWED]
        self.assertEqual(swallowed[0].symbol_name, "test_flaky")

    def test_detects_removed_entire_test_function(self):
        base_code = """
def test_one():
    assert 1 == 1

def test_two():
    assert 2 == 2
"""
        head_code = """
def test_one():
    assert 1 == 1
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_removal.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.ASSERTION_REMOVED)
        self.assertEqual(violations[0].symbol_name, "test_two")

    def test_no_violations_for_clean_modifications(self):
        base_code = "def test_ok(): assert 1 == 1"
        head_code = "def test_ok(): assert 1 == 1; assert 2 == 2"
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_clean.py")
        self.assertEqual(len(violations), 0)

    def test_syntax_error_handled_gracefully(self):
        bad_code = "def test_syntax(: invalid python"
        violations = analyze_test_code(bad_code, file_path="tests/test_bad.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.SYNTAX_ERROR)

    def test_ast_diff_handles_syntax_error_in_head(self):
        base_code = "def test_ok(): assert 1 == 1"
        bad_head_code = "def test_syntax(: invalid python"
        violations = analyze_ast_diff(base_code, bad_head_code, file_path="tests/test_bad.py")
        self.assertTrue(any(v.type == ViolationType.SYNTAX_ERROR for v in violations))


if __name__ == "__main__":
    unittest.main()
