from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional

class ViolationType(str, Enum):
    ASSERTION_REMOVED = "ASSERTION_REMOVED"
    ASSERTION_WEAKENED = "ASSERTION_WEAKENED"
    TEST_SKIPPED = "TEST_SKIPPED"
    EXCEPTION_SWALLOWED = "EXCEPTION_SWALLOWED"
    HARDCODED_CHEAT = "HARDCODED_CHEAT"
    SYNTAX_ERROR = "SYNTAX_ERROR"

class Verdict(str, Enum):
    PASS = "PASS"
    VETO = "VETO"

@dataclass
class Violation:
    type: ViolationType
    file_path: str
    line_number: Optional[int] = None
    symbol_name: Optional[str] = None
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value
        return d

@dataclass
class Report:
    verdict: Verdict
    violations: list[Violation] = field(default_factory=list)
    summary: str = ""
    execution_time_ms: float = 0.0

    @property
    def is_passed(self) -> bool:
        return self.verdict == Verdict.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "violations": [v.to_dict() for v in self.violations],
            "summary": self.summary,
            "execution_time_ms": self.execution_time_ms,
        }

CheckResult = Report
