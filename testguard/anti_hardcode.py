import ast
from typing import Any, Optional
from testguard.models import Violation, ViolationType

IGNORED_LITERALS = {
    "", " ", "true", "false", "none", "null",
    0, 1, -1, True, False, None
}

def _get_docstring_nodes(tree: ast.AST) -> set[ast.AST]:
    doc_nodes: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr) and
                    isinstance(node.body[0].value, ast.Constant) and
                    isinstance(node.body[0].value.value, str)):
                doc_nodes.add(node.body[0].value)
    return doc_nodes

def extract_test_literals(test_code: str) -> set[Any]:
    """Extract numeric and string constants from test code while filtering trivial/default values."""
    literals: set[Any] = set()
    try:
        tree = ast.parse(test_code)
    except SyntaxError:
        return literals

    doc_nodes = _get_docstring_nodes(tree)

    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node not in doc_nodes:
            val = node.value
            if isinstance(val, (str, int, float)) and not isinstance(val, bool):
                if isinstance(val, str):
                    if len(val.strip()) < 3 or val.lower() in IGNORED_LITERALS:
                        continue
                elif isinstance(val, (int, float)):
                    if val in IGNORED_LITERALS:
                        continue
                literals.add(val)
    return literals

def _extract_constants_from_expr(expr: ast.AST) -> set[Any]:
    constants: set[Any] = set()
    for child in ast.walk(expr):
        if isinstance(child, ast.Constant) and not isinstance(child.value, bool):
            constants.add(child.value)
    return constants

def _is_constant_or_literal(expr: Optional[ast.AST], test_literals: set[Any]) -> bool:
    if expr is None:
        return True
    if isinstance(expr, ast.Constant):
        return True
    if isinstance(expr, ast.UnaryOp) and isinstance(expr.operand, ast.Constant):
        return True
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_constant_or_literal(elt, test_literals) for elt in expr.elts)
    if isinstance(expr, ast.Dict):
        keys_ok = all(_is_constant_or_literal(k, test_literals) for k in expr.keys if k is not None)
        vals_ok = all(_is_constant_or_literal(v, test_literals) for v in expr.values)
        return keys_ok and vals_ok
    if isinstance(expr, (ast.Call, ast.Await)):
        return False
    constants = _extract_constants_from_expr(expr)
    if constants.intersection(test_literals):
        return True
    return False

def _has_hardcoded_return_in_body(body: list[ast.stmt], test_literals: set[Any]) -> bool:
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(stmt, ast.Return):
            if _is_constant_or_literal(stmt.value, test_literals):
                return True
        queue = [stmt]
        while queue:
            curr = queue.pop(0)
            if isinstance(curr, ast.Return):
                if _is_constant_or_literal(curr.value, test_literals):
                    return True
            for child in ast.iter_child_nodes(curr):
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    queue.append(child)
    return False

class _HardcodeCheatVisitor(ast.NodeVisitor):
    def __init__(self, test_literals: set[Any], file_path: str):
        self.test_literals = test_literals
        self.file_path = file_path
        self.current_function: Optional[str] = None
        self.violations: list[Violation] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        prev = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        prev = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = prev

    def visit_If(self, node: ast.If):
        cond_constants = _extract_constants_from_expr(node.test)
        matched_literals = cond_constants.intersection(self.test_literals)
        if matched_literals and _has_hardcoded_return_in_body(node.body, self.test_literals):
            matched_sorted = sorted(list(matched_literals), key=str)
            matched_str = ", ".join(repr(x) for x in matched_sorted)
            func_name = self.current_function or "<module>"
            self.violations.append(Violation(
                type=ViolationType.HARDCODED_CHEAT,
                file_path=self.file_path,
                line_number=node.lineno,
                symbol_name=func_name,
                message=f"Hardcoded check for test literal(s) {matched_str} in '{func_name}'",
                details={"matched_literals": matched_sorted}
            ))
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp):
        cond_constants = _extract_constants_from_expr(node.test)
        matched_literals = cond_constants.intersection(self.test_literals)
        if matched_literals and (
            _is_constant_or_literal(node.body, self.test_literals)
            or _is_constant_or_literal(node.orelse, self.test_literals)
        ):
            matched_sorted = sorted(list(matched_literals), key=str)
            matched_str = ", ".join(repr(x) for x in matched_sorted)
            func_name = self.current_function or "<module>"
            self.violations.append(Violation(
                type=ViolationType.HARDCODED_CHEAT,
                file_path=self.file_path,
                line_number=node.lineno,
                symbol_name=func_name,
                message=f"Hardcoded check for test literal(s) {matched_str} in '{func_name}'",
                details={"matched_literals": matched_sorted}
            ))
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match):
        for case in node.cases:
            pattern_constants: set[Any] = set()
            for child in ast.walk(case.pattern):
                if isinstance(child, ast.Constant) and not isinstance(child.value, bool):
                    pattern_constants.add(child.value)
            if getattr(case, "guard", None):
                for child in ast.walk(case.guard):
                    if isinstance(child, ast.Constant) and not isinstance(child.value, bool):
                        pattern_constants.add(child.value)
            matched_literals = pattern_constants.intersection(self.test_literals)
            if matched_literals and _has_hardcoded_return_in_body(case.body, self.test_literals):
                matched_sorted = sorted(list(matched_literals), key=str)
                matched_str = ", ".join(repr(x) for x in matched_sorted)
                func_name = self.current_function or "<module>"
                lineno = getattr(case.pattern, "lineno", node.lineno)
                self.violations.append(Violation(
                    type=ViolationType.HARDCODED_CHEAT,
                    file_path=self.file_path,
                    line_number=lineno,
                    symbol_name=func_name,
                    message=f"Hardcoded check for test literal(s) {matched_str} in '{func_name}'",
                    details={"matched_literals": matched_sorted}
                ))
        self.generic_visit(node)

def detect_hardcoded_cheats(src_code: str, test_literals: set[Any], file_path: str = "") -> list[Violation]:
    """Analyze source code AST for hardcoded test literals checked in condition branches that return."""
    if not test_literals:
        return []

    try:
        tree = ast.parse(src_code, filename=file_path)
    except SyntaxError:
        return []

    visitor = _HardcodeCheatVisitor(test_literals=test_literals, file_path=file_path)
    visitor.visit(tree)
    return visitor.violations
