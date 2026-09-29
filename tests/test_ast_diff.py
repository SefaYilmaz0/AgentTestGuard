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

    def test_detects_class_level_skip_decorator(self):
        code = """
import unittest
import pytest

@unittest.skip("Skipping whole class")
class TestLegacyFeature(unittest.TestCase):
    def test_legacy(self):
        self.assertTrue(True)

@pytest.mark.skip(reason="Not ready")
class TestNewFeature:
    def test_new(self):
        assert True
"""
        violations = analyze_test_code(code, file_path="tests/test_suite.py")
        skip_violations = [v for v in violations if v.type == ViolationType.TEST_SKIPPED]
        self.assertEqual(len(skip_violations), 2)
        symbols = {v.symbol_name for v in skip_violations}
        self.assertEqual(symbols, {"TestLegacyFeature", "TestNewFeature"})

    def test_detects_swallowed_exception_with_return(self):
        code = """
def test_swallow_return():
    try:
        risky_call()
    except Exception:
        return

def test_swallow_return_none():
    try:
        risky_call()
    except Exception:
        return None
"""
        violations = analyze_test_code(code, file_path="tests/test_swallow.py")
        swallowed = [v for v in violations if v.type == ViolationType.EXCEPTION_SWALLOWED]
        self.assertEqual(len(swallowed), 2)
        symbols = {v.symbol_name for v in swallowed}
        self.assertEqual(symbols, {"test_swallow_return", "test_swallow_return_none"})

    def test_does_not_flag_exception_with_raise_or_assertion(self):
        code = """
def test_proper_handling():
    try:
        risky_call()
    except ValueError:
        raise
    except KeyError:
        assert False, "Key error should not occur"
"""
        violations = analyze_test_code(code, file_path="tests/test_ok.py")
        swallowed = [v for v in violations if v.type == ViolationType.EXCEPTION_SWALLOWED]
        self.assertEqual(len(swallowed), 0)

    def test_class_scoped_test_function_names(self):
        base_code = """
class TestAuth:
    def test_exec(self):
        assert check_auth() == True
        assert get_role() == "admin"

class TestBilling:
    def test_exec(self):
        assert charge() == 100
        assert verify_invoice() == True
"""
        # Cheating: AI removes assertion only in TestBilling.test_exec
        head_code = """
class TestAuth:
    def test_exec(self):
        assert check_auth() == True
        assert get_role() == "admin"

class TestBilling:
    def test_exec(self):
        assert charge() == 100
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_services.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.ASSERTION_REMOVED)
        self.assertEqual(violations[0].symbol_name, "TestBilling.test_exec")
        self.assertEqual(violations[0].details["base_count"], 2)
        self.assertEqual(violations[0].details["head_count"], 1)

    def test_non_python_file_path_ignored(self):
        json_code = '{"test": true, "key": "value"}'
        self.assertEqual(analyze_test_code(json_code, file_path="tests/fixtures.json"), [])
        self.assertEqual(analyze_ast_diff(json_code, json_code, file_path="tests/fixtures.json"), [])

    def test_assertion_weakened_from_equality_to_truthiness(self):
        base_code = """
def test_calc():
    res = compute_value()
    assert res == 42
"""
        head_code = """
def test_calc():
    res = compute_value()
    assert res
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_calc.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.ASSERTION_WEAKENED)
        self.assertEqual(violations[0].symbol_name, "test_calc")
        self.assertIn("Assertion weakened", violations[0].message)

    def test_assertion_weakened_from_equality_to_not_none(self):
        base_code = """
def test_calc():
    res = compute_value()
    assert res == 42
"""
        head_code = """
def test_calc():
    res = compute_value()
    assert res is not None
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_calc.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.ASSERTION_WEAKENED)
        self.assertEqual(violations[0].symbol_name, "test_calc")
        self.assertIn("Assertion weakened", violations[0].message)

    def test_assertion_weakened_unittest_style(self):
        base_code = """
def test_calc(self):
    self.assertEqual(compute_value(), 42)
"""
        head_code = """
def test_calc(self):
    self.assertTrue(compute_value())
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_calc.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.ASSERTION_WEAKENED)
        self.assertEqual(violations[0].symbol_name, "test_calc")

    def test_assertion_weakened_attribute_truthiness_exact_line(self):
        base_code = """
def test_status():
    res = get_response()
    assert res.status_code == 200
"""
        head_code = """
def test_status():
    res = get_response()
    assert res.is_valid
"""
        violations = analyze_ast_diff(base_code, head_code, file_path="tests/test_status.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.ASSERTION_WEAKENED)
        self.assertEqual(violations[0].symbol_name, "test_status")
        # Line number should point directly to the assert line (line 4) rather than def (line 2)
        self.assertEqual(violations[0].line_number, 4)


if __name__ == "__main__":
    unittest.main()

