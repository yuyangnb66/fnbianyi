"""结构化编译错误与警告。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional


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
    suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        loc = ""
        if self.line > 0:
            # 列号为0时统一显示为第1列
            show_col = self.col if self.col != 0 else 1
            loc = f"第{self.line}行第{show_col}列"

        prefix = "警告" if self.severity == Severity.WARNING.value else "错误"
        code = f"[{self.code}] " if self.code else ""

        full_msg = f"{prefix} [{self.stage}] {loc}: {code}{self.message}"
        if self.suggestion:
            full_msg += f"\n  建议：{self.suggestion}"

        return full_msg


def diagnostic(
    stage: Stage | str,
    message: str,
    *,
    line: int = 0,
    col: int = 0,
    severity: Severity = Severity.ERROR,
    code: str = "",
    suggestion: str = "",
) -> CompileDiagnostic:
    stage_val = stage.value if isinstance(stage, Stage) else stage
    return CompileDiagnostic(
        stage=stage_val,
        message=message,
        line=line,
        col=col,
        severity=severity.value,
        code=code,
        suggestion=suggestion,
    )