"""结构化编译错误与警告。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


class Stage(str, Enum):
    LEXER = "词法分析"
    SYNTAX = "语法分析"
    SEMANTIC = "语义分析"
    VALIDATOR = "静态检查"
    CODEGEN = "代码生成"
    RUNTIME = "运行"


@dataclass
class CompileDiagnostic:
    stage: str
    message: str
    line: int = 0
    col: int = 0
    severity: str = Severity.ERROR.value
    code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        loc = f"L{self.line}" + (f":C{self.col}" if self.col else "")
        prefix = "警告" if self.severity == Severity.WARNING.value else "错误"
        code = f"[{self.code}] " if self.code else ""
        return f"{prefix} [{self.stage}] {loc}: {code}{self.message}"


def diagnostic(
    stage: Stage | str,
    message: str,
    *,
    line: int = 0,
    col: int = 0,
    severity: Severity = Severity.ERROR,
    code: str = "",
) -> CompileDiagnostic:
    stage_val = stage.value if isinstance(stage, Stage) else stage
    return CompileDiagnostic(
        stage=stage_val,
        message=message,
        line=line,
        col=col,
        severity=severity.value,
        code=code,
    )
