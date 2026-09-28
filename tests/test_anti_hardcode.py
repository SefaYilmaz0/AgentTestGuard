import unittest
from testguard.models import ViolationType
from testguard.anti_hardcode import extract_test_literals, detect_hardcoded_cheats

class TestAntiHardcode(unittest.TestCase):
    def test_extract_literals_from_test(self):
        test_code = """
def test_login():
    assert login("admin_special_user", 987654) == "session_xyz"
"""
        literals = extract_test_literals(test_code)
        self.assertIn("admin_special_user", literals)
        self.assertIn(987654, literals)
        self.assertIn("session_xyz", literals)
        # Verify common default values are ignored
        self.assertNotIn("", literals)
        self.assertNotIn(0, literals)
        self.assertNotIn(1, literals)
        self.assertNotIn(-1, literals)
        self.assertNotIn("ok", literals)
        self.assertNotIn(True, literals)
        self.assertNotIn(False, literals)

    def test_extract_literals_ignores_docstrings(self):
        test_code = """
\"\"\"Module docstring that should be ignored.\"\"\"
def test_foo():
    \"\"\"Function docstring that should also be ignored.\"\"\"
    assert compute("target_token_value") == 12345
"""
        literals = extract_test_literals(test_code)
        self.assertIn("target_token_value", literals)
        self.assertIn(12345, literals)
        self.assertNotIn("Module docstring that should be ignored.", literals)
        self.assertNotIn("Function docstring that should also be ignored.", literals)

    def test_extract_literals_syntax_error(self):
        self.assertEqual(extract_test_literals("def invalid_syntax(:"), set())

    def test_detects_hardcoded_if_return(self):
        src_code = """
def login(username, pin):
    if username == "admin_special_user":
        return "session_xyz"
    return perform_real_auth(username, pin)
"""
        test_literals = {"admin_special_user", "session_xyz"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/auth.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.HARDCODED_CHEAT)
        self.assertEqual(violations[0].symbol_name, "login")
        self.assertEqual(violations[0].file_path, "src/auth.py")
        self.assertIn("admin_special_user", violations[0].details["matched_literals"])

    def test_detects_hardcoded_in_operator(self):
        src_code = """
def authenticate(token):
    if "magic_bypass_token" in token:
        return True
    return False
"""
        test_literals = {"magic_bypass_token"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/auth.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.HARDCODED_CHEAT)
        self.assertEqual(violations[0].symbol_name, "authenticate")

    def test_detects_hardcoded_match_case(self):
        src_code = """
def parse_command(cmd):
    match cmd:
        case "secret_override_cmd":
            return 999
        case _:
            return 0
"""
        test_literals = {"secret_override_cmd"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/cli.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].type, ViolationType.HARDCODED_CHEAT)
        self.assertEqual(violations[0].symbol_name, "parse_command")

    def test_detects_hardcoded_async_function(self):
        src_code = """
async def fetch_user_data(user_id):
    if user_id == "mock_user_99":
        return {"name": "Mock"}
    return await db.get(user_id)
"""
        test_literals = {"mock_user_99"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/async_db.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].symbol_name, "fetch_user_data")

    def test_detects_nested_return_inside_if(self):
        src_code = """
def handle_request(req):
    if req.header == "special_cheat_header":
        if req.is_active:
            return 200
    return 400
"""
        test_literals = {"special_cheat_header"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/req.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].symbol_name, "handle_request")

    def test_ignores_non_cheating_code(self):
        src_code = """
def login(username, pin):
    token = hash_credentials(username, pin)
    return token
"""
        test_literals = {"admin_special_user"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/auth.py")
        self.assertEqual(len(violations), 0)

    def test_ignores_if_without_return(self):
        src_code = """
def audit_login(username):
    if username == "admin_special_user":
        log.warning("Admin logged in")
    perform_normal_actions(username)
"""
        test_literals = {"admin_special_user"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/auth.py")
        self.assertEqual(len(violations), 0)

    def test_empty_literals_and_syntax_error(self):
        self.assertEqual(detect_hardcoded_cheats("def foo(): pass", set(), "src/foo.py"), [])
        self.assertEqual(detect_hardcoded_cheats("invalid syntax :(", {"cheat_val"}, "src/foo.py"), [])

    def test_nested_function_attribution(self):
        src_code = """
def outer_service():
    def inner_helper(val):
        if val == "cheat_val_123":
            return "cheated"
        return "normal"
    return inner_helper
"""
        test_literals = {"cheat_val_123"}
        violations = detect_hardcoded_cheats(src_code, test_literals, file_path="src/service.py")
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0].symbol_name, "inner_helper")

if __name__ == "__main__":
    unittest.main()
