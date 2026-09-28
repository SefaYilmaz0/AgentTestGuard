import unittest
import os
import subprocess
import tempfile
from testguard.shadow import is_test_file, get_changed_files, get_file_content_at_ref

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
            changed = get_changed_files("HEAD", cwd=tmpdir)
            self.assertEqual(changed, [])
            
            content = get_file_content_at_ref("HEAD", "file.py", cwd=tmpdir)
            self.assertIsNone(content)

if __name__ == "__main__":
    unittest.main()
