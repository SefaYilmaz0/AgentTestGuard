import ast
from typing import Optional, Union
from testguard.models import Violation, ViolationType

FunctionNodeType = Union[ast.FunctionDef, ast.AsyncFunctionDef]


def _count_assertions_in_node(node: ast.AST) -> int:
    count = 0
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            count += 1
        elif isinstance(child, ast.Call):
            # Detect self.assert* or unittest assertions
            if isinstance(child.func, ast.Attribute) and child.func.attr.startswith("assert"):
                count += 1
    return count


def _get_decorator_name(decorator: ast.AST) -> str:
    if isinstance(decorator, ast.Name):
        return decorator.id
    elif isinstance(decorator, ast.Attribute):
        parent = _get_decorator_name(decorator.value)
        return f"{parent}.{decorator.attr}" if parent else decorator.attr
    elif isinstance(decorator, ast.Call):
        return _get_decorator_name(decorator.func)
    return ""


def _has_skip_decorator(node: Union[ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef]) -> bool:
    for decorator in node.decorator_list:
        dec_name = _get_decorator_name(decorator)
        if any(skip_word in dec_name.lower() for skip_word in ("skip", "skipif", "xfail")):
            return True
    return False


def _has_raise_or_assertion(statements: list[ast.stmt]) -> bool:
    for stmt in statements:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Raise):
                return True
            if isinstance(node, ast.Assert):
                return True
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute) and (
                    node.func.attr.startswith("assert") or node.func.attr == "fail"
                ):
                    return True
                if isinstance(node.func, ast.Name) and (
                    node.func.id.startswith("assert") or node.func.id == "fail"
                ):
                    return True
    return False


def _find_swallowed_exceptions(
    func_node: FunctionNodeType, file_path: str, symbol_name: Optional[str] = None
) -> list[Violation]:
    sym = symbol_name or func_node.name
    violations: list[Violation] = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                is_pass_only = len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass)
                is_ellipsis = (
                    len(handler.body) == 1
                    and isinstance(handler.body[0], ast.Expr)
                    and isinstance(handler.body[0].value, ast.Constant)
                    and handler.body[0].value.value is Ellipsis
                )
                is_empty = len(handler.body) == 0
                is_return = any(
                    isinstance(stmt, ast.Return)
                    and (
                        stmt.value is None
                        or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)
                    )
                    for stmt in handler.body
                )
                if (is_pass_only or is_ellipsis or is_empty or is_return) and not _has_raise_or_assertion(handler.body):
                    msg = (
                        f"Exception swallowed with return in test '{sym}'"
                        if is_return
                        else f"Exception swallowed with pass in test '{sym}'"
                    )
                    violations.append(
                        Violation(
                            type=ViolationType.EXCEPTION_SWALLOWED,
                            file_path=file_path,
                            line_number=handler.lineno,
                            symbol_name=sym,
                            message=msg,
                        )
                    )
    return violations


def _extract_test_functions(tree: ast.AST) -> dict[str, FunctionNodeType]:
    functions: dict[str, FunctionNodeType] = {}

    class TestFuncVisitor(ast.NodeVisitor):
        def __init__(self):
            self.class_stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef):
            self.class_stack.append(node.name)
            self.generic_visit(node)
            self.class_stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self._handle_function(node)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self._handle_function(node)
            self.generic_visit(node)

        def _handle_function(self, node: FunctionNodeType):
            if node.name.startswith("test_") or node.name.endswith("_test"):
                if self.class_stack:
                    full_name = f"{'.'.join(self.class_stack)}.{node.name}"
                else:
                    full_name = node.name
                functions[full_name] = node

    visitor = TestFuncVisitor()
    visitor.visit(tree)
    return functions


def analyze_test_code(code: str, file_path: str) -> list[Violation]:
    if file_path and not file_path.endswith(".py"):
        return []

    try:
        tree = ast.parse(code, filename=file_path)
    except SyntaxError as e:
        return [
            Violation(
                type=ViolationType.SYNTAX_ERROR,
                file_path=file_path,
                line_number=e.lineno,
                message=f"Syntax error: {e.msg}",
            )
        ]

    violations: list[Violation] = []

    # Check class-level skip decorators
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if _has_skip_decorator(node):
                violations.append(
                    Violation(
                        type=ViolationType.TEST_SKIPPED,
                        file_path=file_path,
                        line_number=node.lineno,
                        symbol_name=node.name,
                        message=f"Test class '{node.name}' has skip decorator",
                    )
                )

    funcs = _extract_test_functions(tree)

    for func_name, func_node in funcs.items():
        if _has_skip_decorator(func_node):
            violations.append(
                Violation(
                    type=ViolationType.TEST_SKIPPED,
                    file_path=file_path,
                    line_number=func_node.lineno,
                    symbol_name=func_name,
                    message=f"Test '{func_name}' has skip decorator",
                )
            )
        violations.extend(_find_swallowed_exceptions(func_node, file_path, symbol_name=func_name))

    return violations


def analyze_ast_diff(base_code: str, head_code: str, file_path: str) -> list[Violation]:
    if file_path and not file_path.endswith(".py"):
        return []

    violations = analyze_test_code(head_code, file_path)

    try:
        base_tree = ast.parse(base_code, filename=file_path)
        head_tree = ast.parse(head_code, filename=file_path)
    except SyntaxError:
        return violations

    base_funcs = _extract_test_functions(base_tree)
    head_funcs = _extract_test_functions(head_tree)

    for func_name, base_node in base_funcs.items():
        base_count = _count_assertions_in_node(base_node)
        if func_name in head_funcs:
            head_node = head_funcs[func_name]
            head_count = _count_assertions_in_node(head_node)
            if head_count < base_count:
                violations.append(
                    Violation(
                        type=ViolationType.ASSERTION_REMOVED,
                        file_path=file_path,
                        line_number=head_node.lineno,
                        symbol_name=func_name,
                        message=f"Assertion count decreased in '{func_name}': {base_count} -> {head_count}",
                        details={"base_count": base_count, "head_count": head_count},
                    )
                )
        else:
            violations.append(
                Violation(
                    type=ViolationType.ASSERTION_REMOVED,
                    file_path=file_path,
                    symbol_name=func_name,
                    message=f"Test function '{func_name}' was removed entirely",
                    details={"base_count": base_count, "head_count": 0},
                )
            )

    return violations
