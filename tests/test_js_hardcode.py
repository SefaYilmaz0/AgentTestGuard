import os
import subprocess
import tempfile
import unittest

from testguard.cli import main
from testguard.js_hardcode import detect_js_hardcoded_cheats
from testguard.models import ViolationType

LITS = {"user_123", "admin_token", 4242, "session_xyz"}


def detect(src):
    return detect_js_hardcoded_cheats(src, LITS, file_path="src/auth.ts")


class TestJsHardcode(unittest.TestCase):
    def test_if_return_literal(self):
        v = detect('function login(u) {\n  if (u === "user_123") {\n    return "session_xyz";\n  }\n  return real(u);\n}\n')
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].type, ViolationType.HARDCODED_CHEAT)
        self.assertEqual(v[0].symbol_name, "login")
        self.assertEqual(v[0].line_number, 2)

    def test_if_single_statement_and_arrow(self):
        v = detect('const f = (id) => {\n  if (id == 4242) return 99;\n  return calc(id);\n};\n')
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].symbol_name, "f")

    def test_wrapped_literal_return(self):
        v = detect('function g(u) { if (u === "user_123") { return new Result("session_xyz"); } return h(u); }')
        self.assertEqual(len(v), 1)

    def test_ternary(self):
        v = detect('function g(u) { return u === "user_123" ? "session_xyz" : compute(u); }')
        self.assertEqual(len(v), 1)
        self.assertIn("ternary", v[0].message)

    def test_switch_case(self):
        v = detect('function g(u) {\n switch (u) {\n  case "user_123":\n   return 1000;\n  default:\n   return compute(u);\n }\n}')
        self.assertEqual(len(v), 1)
        self.assertIn("case", v[0].message)

    def test_lookup_table_inline_and_named(self):
        self.assertEqual(len(detect('function g(u) { return ({ "user_123": "ok", other: "no" })[u]; }')), 1)
        self.assertEqual(len(detect('const TABLE = { user_123: "ok" };\nfunction g(u) { return TABLE[u]; }')), 1)

    def test_constant_alias(self):
        v = detect('const SECRET = "user_123";\nfunction g(u) {\n  if (u === SECRET) { return 42; }\n  return h(u);\n}\n')
        self.assertEqual(len(v), 1)
        self.assertEqual(v[0].line_number, 3)
        # reassigned name is not a constant alias
        self.assertEqual(detect('let SECRET = "user_123";\nSECRET = load();\nfunction g(u) { if (u === SECRET) { return 42; } return h(u); }'), [])

    def test_clean_code_not_flagged(self):
        clean = [
            'function g(u) { if (u === "user_123") { return lookup(u); } return h(u); }',
            'function g(u) { if (u > 0) { return 42; } return 1; }',
            'function g(u) { return u ? compute(u) : fallback(u); }',
            'function g(a, b) { return a?.x ?? b; }',
            'const CONFIG = { user_123: "ok" };\nfunction g() { return CONFIG; }',
            '// if (u === "user_123") return 1;\nfunction g() { return 2; }',
        ]
        for src in clean:
            self.assertEqual(detect(src), [], src)

    def test_no_literals_no_violations(self):
        self.assertEqual(detect_js_hardcoded_cheats('if (x === "a") return 1;', set()), [])


class TestJsHardcodeEndToEnd(unittest.TestCase):
    def test_cli_vetoes_ts_source_cheat(self):
        with tempfile.TemporaryDirectory() as d:
            def git(*a):
                subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
            git("init"); git("config", "user.name", "T"); git("config", "user.email", "t@e.com")
            os.makedirs(os.path.join(d, "src")); os.makedirs(os.path.join(d, "tests"))
            with open(os.path.join(d, "src/auth.ts"), "w") as f:
                f.write("export function login(u: string) { return real(u); }\n")
            with open(os.path.join(d, "tests/auth.test.ts"), "w") as f:
                f.write("test('login', () => { expect(login('user_123')).toBe('session_xyz'); });\n")
            git("add", "."); git("commit", "-m", "base")
            self.assertEqual(main(["check", "--base", "HEAD", "--cwd", d]), 0)
            with open(os.path.join(d, "src/auth.ts"), "w") as f:
                f.write("export function login(u: string) { if (u === 'user_123') { return 'session_xyz'; } return real(u); }\n")
            self.assertEqual(main(["check", "--base", "HEAD", "--cwd", d]), 1)


if __name__ == "__main__":
    unittest.main()
