import unittest
from testguard.models import ViolationType
from testguard.js_diff import (
    analyze_js_test_code,
    analyze_js_test_diff,
    extract_js_test_literals,
)


class TestJsDiffSkipping(unittest.TestCase):
    def test_detect_test_skip_and_it_skip(self):
        code = """
describe("AuthModule", () => {
    test.skip("should login with oauth", () => {
        expect(login()).toBe(true);
    });

    it.skip("should refresh expired session", () => {
        expect(refresh()).toBe(true);
    });
});
"""
        violations = analyze_js_test_code(code, file_path="auth.test.ts")
        skip_violations = [v for v in violations if v.type == ViolationType.TEST_SKIPPED]
        self.assertEqual(len(skip_violations), 2)
        symbols = [v.symbol_name for v in skip_violations]
        self.assertIn("should login with oauth", symbols)
        self.assertIn("should refresh expired session", symbols)

    def test_detect_describe_skip(self):
        code = """
describe.skip("Payment Gateway", () => {
    it("charges card", () => {
        expect(charge()).toBe(true);
    });
});
"""
        violations = analyze_js_test_code(code, file_path="payment.test.js")
        skip_violations = [v for v in violations if v.type == ViolationType.TEST_SKIPPED]
        self.assertTrue(any(v.symbol_name == "Payment Gateway" for v in skip_violations))

    def test_detect_xit_and_xtest_and_xdescribe(self):
        code = """
xit("legacy unit test", () => {
    expect(oldMethod()).toBe(1);
});

xtest("unstable integration test", async () => {
    expect(await fetchApi()).toBe(200);
});

xdescribe("deprecated suite", () => {
    it("inner", () => {
        expect(true).toBe(true);
    });
});
"""
        violations = analyze_js_test_code(code, file_path="suite.spec.js")
        skip_violations = [v for v in violations if v.type == ViolationType.TEST_SKIPPED]
        self.assertEqual(len(skip_violations), 3)
        symbols = [v.symbol_name for v in skip_violations]
        self.assertIn("legacy unit test", symbols)
        self.assertIn("unstable integration test", symbols)
        self.assertIn("deprecated suite", symbols)

    def test_skip_inside_comments_or_strings_not_flagged(self):
        code = """
// it.skip("commented out skip", () => {});
/*
test.skip("block commented", () => {});
*/
describe("Comments", () => {
    it("does not trigger on string mentions", () => {
        const message = "do not call it.skip or xtest here";
        expect(message).toBeDefined();
    });
});
"""
        violations = analyze_js_test_code(code, file_path="safe.test.ts")
        skip_violations = [v for v in violations if v.type == ViolationType.TEST_SKIPPED]
        self.assertEqual(len(skip_violations), 0)


class TestJsDiffAssertionRemoval(unittest.TestCase):
    def test_assertion_count_decrease_detected(self):
        base_code = """
describe("Calculator", () => {
    it("performs basic operations", () => {
        expect(add(1, 2)).toBe(3);
        expect(sub(5, 3)).toBe(2);
        expect(mul(2, 4)).toBe(8);
    });
});
"""
        head_code = """
describe("Calculator", () => {
    it("performs basic operations", () => {
        expect(add(1, 2)).toBe(3);
    });
});
"""
        violations = analyze_js_test_diff(base_code, head_code, file_path="calc.test.ts")
        removal_violations = [v for v in violations if v.type == ViolationType.ASSERTION_REMOVED]
        self.assertEqual(len(removal_violations), 1)
        self.assertIn("performs basic operations", removal_violations[0].symbol_name)
        self.assertIn("3 -> 1", removal_violations[0].message)

    def test_entire_test_block_removed(self):
        base_code = """
test("feature A", () => {
    expect(a()).toBe(1);
});

test("feature B", () => {
    expect(b()).toBe(2);
});
"""
        head_code = """
test("feature B", () => {
    expect(b()).toBe(2);
});
"""
        violations = analyze_js_test_diff(base_code, head_code, file_path="features.test.js")
        removal_violations = [v for v in violations if v.type == ViolationType.ASSERTION_REMOVED]
        self.assertEqual(len(removal_violations), 1)
        self.assertEqual(removal_violations[0].symbol_name, "feature A")

    def test_assert_style_assertion_removal(self):
        base_code = """
it("asserts values", () => {
    assert.strictEqual(calc(1), 10);
    assert.ok(isValid());
});
"""
        head_code = """
it("asserts values", () => {
    assert.ok(isValid());
});
"""
        violations = analyze_js_test_diff(base_code, head_code, file_path="assert.test.js")
        removal_violations = [v for v in violations if v.type == ViolationType.ASSERTION_REMOVED]
        self.assertEqual(len(removal_violations), 1)
        self.assertIn("2 -> 1", removal_violations[0].message)


class TestJsDiffExceptionSwallowing(unittest.TestCase):
    def test_empty_catch_block_flagged(self):
        code = """
test("handles exception", () => {
    try {
        riskyOp();
    } catch (e) {
    }
});
"""
        violations = analyze_js_test_code(code, file_path="try.test.ts")
        swallow = [v for v in violations if v.type == ViolationType.EXCEPTION_SWALLOWED]
        self.assertEqual(len(swallow), 1)
        self.assertEqual(swallow[0].symbol_name, "handles exception")

    def test_catch_with_only_console_or_return_flagged(self):
        code = """
it("ignores failures silently", () => {
    try {
        throw new Error("fail");
    } catch (err) {
        console.log("swallowing error:", err);
        return;
    }
});
"""
        violations = analyze_js_test_code(code, file_path="silent.test.js")
        swallow = [v for v in violations if v.type == ViolationType.EXCEPTION_SWALLOWED]
        self.assertEqual(len(swallow), 1)

    def test_catch_with_expect_or_throw_is_safe(self):
        code = """
test("properly asserts on error", () => {
    try {
        riskyOp();
    } catch (err) {
        expect(err.message).toBe("Expected failure");
    }
});

test("rethrows error", () => {
    try {
        anotherOp();
    } catch (err) {
        throw err;
    }
});
"""
        violations = analyze_js_test_code(code, file_path="safe_try.test.ts")
        swallow = [v for v in violations if v.type == ViolationType.EXCEPTION_SWALLOWED]
        self.assertEqual(len(swallow), 0)


class TestJsDiffCleanSuite(unittest.TestCase):
    def test_clean_tests_pass_without_violations(self):
        base_code = """
describe("CleanSuite", () => {
    it("works properly", () => {
        expect(1 + 1).toBe(2);
    });
});
"""
        head_code = """
describe("CleanSuite", () => {
    it("works properly", () => {
        expect(1 + 1).toBe(2);
        expect(2 + 2).toBe(4);
    });

    it("adds another test", () => {
        expect(true).toBe(true);
    });
});
"""
        violations = analyze_js_test_diff(base_code, head_code, file_path="clean.test.ts")
        self.assertEqual(len(violations), 0)


class TestJsDiffLiteralExtraction(unittest.TestCase):
    def test_extract_js_test_literals(self):
        code = """
describe("UserAuthService", () => {
    const API_URL = "https://api.example.com/v1/users";
    
    it("authenticates admin user", async () => {
        const username = 'admin_super_user';
        const timeoutMs = 5000;
        const ratio = 3.1415;
        const template = `Bearer secret_token_xyz`;

        // Ignored in comments: "commented_literal"
        /*
        "block_comment_literal"
        */
        const trivial = "";
        const boolVal = true;
        const zero = 0;
        const one = 1;

        expect(login(username, 42)).toBe(true);
    });
});
"""
        literals = extract_js_test_literals(code)
        self.assertIn("https://api.example.com/v1/users", literals)
        self.assertIn("admin_super_user", literals)
        self.assertIn(5000, literals)
        self.assertIn(42, literals)
        self.assertIn("Bearer secret_token_xyz", literals)
        
        # Ignored
        self.assertNotIn("commented_literal", literals)
        self.assertNotIn("block_comment_literal", literals)
        self.assertNotIn("", literals)
        self.assertNotIn(0, literals)
        self.assertNotIn(1, literals)


class TestJsVerdictIntegration(unittest.TestCase):
    def setUp(self):
        import tempfile
        import subprocess
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_dir = self.temp_dir.name
        subprocess.run(["git", "init"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.repo_dir, check=True, capture_output=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write(self, rel_path: str, content: str):
        import os
        full = os.path.join(self.repo_dir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)

    def test_verdict_vetoes_js_assertion_decrease(self):
        import subprocess
        from testguard.verdict import evaluate_changes
        from testguard.models import Verdict, ViolationType

        self._write("tests/calc.test.ts", """
test("addition", () => {
    expect(1 + 1).toBe(2);
    expect(2 + 2).toBe(4);
});
""")
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo_dir, check=True, capture_output=True)

        # Cheating change: drop 1 assertion
        self._write("tests/calc.test.ts", """
test("addition", () => {
    expect(1 + 1).toBe(2);
});
""")
        report = evaluate_changes("HEAD", cwd=self.repo_dir)
        self.assertEqual(report.verdict, Verdict.VETO)
        types = [v.type for v in report.violations]
        self.assertIn(ViolationType.ASSERTION_REMOVED, types)

    def test_verdict_vetoes_hardcoded_cheat_against_js_literal(self):
        import subprocess
        from testguard.verdict import evaluate_changes
        from testguard.models import Verdict, ViolationType

        self._write("tests/auth.test.js", """
test("authenticates user", () => {
    expect(login("secret_special_user")).toBe(true);
});
""")
        self._write("src/auth.py", """
def login(user):
    return False
""")
        subprocess.run(["git", "add", "."], cwd=self.repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.repo_dir, check=True, capture_output=True)

        # Cheating: hardcode return in python for JS test literal
        self._write("src/auth.py", """
def login(user):
    if user == "secret_special_user":
        return True
    return False
""")
        report = evaluate_changes("HEAD", cwd=self.repo_dir)
        self.assertEqual(report.verdict, Verdict.VETO)
        types = [v.type for v in report.violations]
        self.assertIn(ViolationType.HARDCODED_CHEAT, types)


if __name__ == "__main__":
    unittest.main()
