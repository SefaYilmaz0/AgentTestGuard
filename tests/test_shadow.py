import unittest
import os
import subprocess
import tempfile
from testguard.cli import main
from testguard.shadow import BaseRefError, is_test_file, get_changed_files, get_file_content_at_ref

class TestShadowRunner(unittest.TestCase):
    def test_is_test_file(self):
        self.assertTrue(is_test_file("tests/test_auth.py"))
        self.assertTrue(is_test_file("tests/auth_test.py"))
        self.assertTrue(is_test_file("src/test/java/TestAuth.java"))
        self.assertFalse(is_test_file("src/auth.py"))
        self.assertFalse(is_test_file("testguard/models.py"))
        self.assertFalse(is_test_file("testguard/shadow.py"))

    def test_is_test_file_extended_patterns(self):
        # Windows backslashes
        self.assertTrue(is_test_file("tests\\test_auth.py"))
        self.assertTrue(is_test_file(".\\tests\\auth_test.py"))
        
        # JS / TS conventions
        self.assertTrue(is_test_file("frontend/src/app.test.ts"))
        self.assertTrue(is_test_file("frontend/src/app.test.js"))
        self.assertTrue(is_test_file("frontend/src/app.spec.tsx"))
        self.assertTrue(is_test_file("src/__tests__/utils.ts"))
        
        # Non-test files
        self.assertFalse(is_test_file("testing_utils.py"))
        self.assertFalse(is_test_file("testament.py"))

    def test_git_operations_in_repo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Init repo
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "TestUser"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, check=True)
            
            # Initial commit
            file1 = os.path.join(tmpdir, "test_file.py")
            with open(file1, "w", encoding="utf-8") as f:
                f.write("initial = True\n")
            
            sub_dir = os.path.join(tmpdir, "sub")
            os.makedirs(sub_dir, exist_ok=True)
            file2 = os.path.join(sub_dir, "nested.py")
            with open(file2, "w", encoding="utf-8") as f:
                f.write("nested = 1\n")

            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmpdir, check=True)

            # Modify file in working tree
            with open(file1, "w", encoding="utf-8") as f:
                f.write("initial = False\nmodified = True\n")

            # Add a new file in working tree
            file3 = os.path.join(tmpdir, "new_file.py")
            with open(file3, "w", encoding="utf-8") as f:
                f.write("brand_new = True\n")
            subprocess.run(["git", "add", "new_file.py"], cwd=tmpdir, check=True)

            changed = get_changed_files("HEAD", cwd=tmpdir)
            self.assertIn("test_file.py", changed)
            self.assertIn("new_file.py", changed)

            base_content = get_file_content_at_ref("HEAD", "test_file.py", cwd=tmpdir)
            self.assertEqual(base_content, "initial = True\n")

            # Check nested file with backslashes (Windows-style)
            nested_content = get_file_content_at_ref("HEAD", "sub\\nested.py", cwd=tmpdir)
            self.assertEqual(nested_content, "nested = 1\n")

            # Non-existent file in HEAD
            non_existent = get_file_content_at_ref("HEAD", "non_existent.py", cwd=tmpdir)
            self.assertIsNone(non_existent)

            # Newly added file doesn't exist in HEAD
            new_file_base = get_file_content_at_ref("HEAD", "new_file.py", cwd=tmpdir)
            self.assertIsNone(new_file_base)

    def test_git_operations_fallback_and_errors(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Not a git repo
            with self.assertRaises(BaseRefError):
                get_changed_files("HEAD", cwd=tmpdir)
            
            content = get_file_content_at_ref("HEAD", "file.py", cwd=tmpdir)
            self.assertIsNone(content)

    def test_invalid_base_ref_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "T"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmpdir, check=True)
            with open(os.path.join(tmpdir, "a.py"), "w", encoding="utf-8") as f:
                f.write("a = 1\n")
            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True, capture_output=True)
            with self.assertRaises(BaseRefError):
                get_changed_files("origin/nonexistent", cwd=tmpdir)
            self.assertEqual(main(["check", "--base", "origin/nonexistent", "--cwd", tmpdir]), 2)

    def test_get_changed_files_includes_untracked_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "TestUser"], cwd=tmpdir, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir, check=True)

            tracked_file = os.path.join(tmpdir, "tracked.py")
            with open(tracked_file, "w", encoding="utf-8") as f:
                f.write("tracked = True\n")
            gitignore_file = os.path.join(tmpdir, ".gitignore")
            with open(gitignore_file, "w", encoding="utf-8") as f:
                f.write("*.log\n")

            subprocess.run(["git", "add", "."], cwd=tmpdir, check=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True)

            # Modify tracked file
            with open(tracked_file, "w", encoding="utf-8") as f:
                f.write("tracked = False\n")

            # Create an untracked file (not added to git)
            untracked_file = os.path.join(tmpdir, "untracked.py")
            with open(untracked_file, "w", encoding="utf-8") as f:
                f.write("untracked = True\n")

            # Create an ignored file
            ignored_file = os.path.join(tmpdir, "debug.log")
            with open(ignored_file, "w", encoding="utf-8") as f:
                f.write("log data\n")

            changed = get_changed_files("HEAD", cwd=tmpdir)
            self.assertCountEqual(changed, ["tracked.py", "untracked.py"])
            self.assertIn("tracked.py", changed)
            self.assertIn("untracked.py", changed)
            self.assertNotIn("debug.log", changed)

if __name__ == "__main__":
    unittest.main()


class TestTestFileDetectionAndRenames(unittest.TestCase):
    def test_extended_test_file_patterns(self):
        for p in [
            "conftest.py", "pkg/conftest.py", "tests.py", "pkg/foo_tests.py",
            "src/a.test.mjs", "src/a.spec.cjs", "src/a.test.mts", "src/a.spec.cts",
            "src/a.e2e-spec.ts", "cypress/login.cy.ts", "src/a.e2e.ts",
            "spec/helpers.js", "app/specs/x.ts", "e2e/login.ts", "src/__mocks__/api.ts",
            "./tests/test_a.py",
        ]:
            self.assertTrue(is_test_file(p), p)

    def test_non_test_files_not_matched(self):
        for p in ["src/auth.py", "src/contest.py", "src/latest.py", "src/inspector.ts",
                  "src/testing_utils.py", "docs/spec_notes.md", "src/a.testing.ts"]:
            self.assertFalse(is_test_file(p), p)

    def test_renamed_test_is_compared_with_old_content(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
            git("init"); git("config", "user.name", "T"); git("config", "user.email", "t@e.com")
            os.makedirs(os.path.join(d, "tests"))
            body = "def test_a():\n    assert f(1) == 11\n    assert f(2) == 22\n"
            with open(os.path.join(d, "tests/test_a.py"), "w") as fh:
                fh.write(body)
            git("add", "."); git("commit", "-m", "base")
            # pure rename inside tests: clean
            git("mv", "tests/test_a.py", "tests/test_b.py")
            self.assertEqual(main(["check", "--base", "HEAD", "--cwd", d]), 0)
            # move out of the test dirs and drop an assertion: must still be caught
            os.makedirs(os.path.join(d, "checks"))
            git("mv", "tests/test_b.py", "checks/a.py")
            with open(os.path.join(d, "checks/a.py"), "w") as fh:
                fh.write("def test_a():\n    assert f(1) == 11\n")
            self.assertEqual(main(["check", "--base", "HEAD", "--cwd", d]), 1)

    def test_small_rename_with_removed_assertion_reports_decrease_not_removal(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
            git("init"); git("config", "user.name", "T"); git("config", "user.email", "t@e.com")
            os.makedirs(os.path.join(d, "tests"))
            with open(os.path.join(d, "tests/test_app.py"), "w") as fh:
                fh.write("from app import f\ndef test_f():\n    assert f(21) == 42\n    assert f(2) == 4\n")
            git("add", "."); git("commit", "-m", "base")
            git("mv", "tests/test_app.py", "tests/test_renamed.py")
            with open(os.path.join(d, "tests/test_renamed.py"), "w") as fh:
                fh.write("def test_f():\n    assert f(21) == 42\n")
            git("add", ".")
            import io, json
            from unittest.mock import patch
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                self.assertEqual(main(["check", "--base", "HEAD", "--cwd", d, "--format", "json"]), 1)
            msgs = [v["message"] for v in json.loads(buf.getvalue())["violations"]]
            self.assertTrue(any("decreased" in m for m in msgs), msgs)
            self.assertFalse(any("removed entirely" in m for m in msgs), msgs)

    def test_deleted_test_file_message_says_file_is_gone(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
            git("init"); git("config", "user.name", "T"); git("config", "user.email", "t@e.com")
            os.makedirs(os.path.join(d, "tests"))
            with open(os.path.join(d, "tests/test_app.py"), "w") as fh:
                fh.write("def test_f():\n    assert f(1) == 11\n")
            git("add", "."); git("commit", "-m", "base")
            os.remove(os.path.join(d, "tests/test_app.py"))
            from testguard.verdict import evaluate_changes
            vios = evaluate_changes("HEAD", cwd=d).violations
            self.assertEqual(len(vios), 1)
            self.assertIn("no longer exists", vios[0].message)
            self.assertTrue(vios[0].details["file_deleted"])
