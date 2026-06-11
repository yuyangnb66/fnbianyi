"""编译器流水线 — 串联各阶段，尽可能收集全部错误与警告。"""

from __future__ import annotations

import io
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .runtime import runtime_globals

from .ast_nodes import Program
from .codegen import CodeGenerator
from .errors import CompileDiagnostic, Severity
from .lexer import Lexer, Token
from .optimizer import Optimizer
from .parser import Parser
from .semantic import SemanticAnalyzer, Scope
from .tac import TACInstr, TACProgram, TACGenerator
from .validator import StaticValidator


@dataclass
class CompileResult:
    source: str
    tokens: List[Token] = field(default_factory=list)
    ast: Optional[Program] = None
    symbol_table: Optional[Scope] = None
    tac: Optional[TACProgram] = None
    optimized_tac: Optional[TACProgram] = None
    target_code: str = ""
    run_output: str = ""
    errors: List[CompileDiagnostic] = field(default_factory=list)
    warnings: List[CompileDiagnostic] = field(default_factory=list)
    stages_completed: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
            "stages_completed": self.stages_completed,
            "tokens": [t.to_dict() for t in self.tokens],
            "ast": repr(self.ast) if self.ast else "",
            "tac": [str(i) for i in (self.tac.instructions if self.tac else [])],
            "optimized_tac": [
                str(i) for i in (self.optimized_tac.instructions if self.optimized_tac else [])
            ],
            "target_code": self.target_code,
            "run_output": self.run_output,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


class Compiler:
    def __init__(self, grammar_dir: Optional[Path] = None):
        self.grammar_dir = grammar_dir or Path(__file__).parent.parent / "grammar"
        self.tokens_path = self.grammar_dir / "tokens.json"

    def compile(
        self,
        source: str,
        optimize: bool = True,
        run: bool = False,
        trace: bool = False,
    ) -> CompileResult:
        result = CompileResult(source=source)
        has_error_token = False

        # 1. 词法分析
        try:
            lex_result = Lexer(source, self.tokens_path, trace=trace).tokenize()
            result.tokens = lex_result.tokens
            result.errors.extend(lex_result.errors)
            has_error_token = any(t.kind == "ERROR" for t in result.tokens)
            result.stages_completed.append("词法分析")
        except Exception as e:
            debug_info = f"\n[编译器内部错误堆栈]\n{traceback.format_exc()}" if __debug__ else ""
            result.errors.append(
                CompileDiagnostic(
                    stage="词法分析",
                    message=f"词法分析器异常: {e}{debug_info}",
                    code="E000",
                )
            )
            return result

        # 2. 静态 Token 检查（尽可能多报错）
        try:
            validator = StaticValidator()
            static_diags = validator.validate(source, result.tokens)
            for d in static_diags:
                if d.severity == Severity.WARNING.value:
                    result.warnings.append(d)
                else:
                    result.errors.append(d)
            result.stages_completed.append("静态检查")
        except Exception as e:
            debug_info = f"\n[编译器内部错误堆栈]\n{traceback.format_exc()}" if __debug__ else ""
            result.warnings.append(
                CompileDiagnostic(
                    stage="静态检查",
                    message=f"静态检查异常: {e}{debug_info}",
                    severity=Severity.WARNING.value,
                    code="W000",
                )
            )

        # 3. 语法分析（表驱动 LL/LR，自动选法）
        parse_result = None
        try:
            parse_result = Parser(result.tokens).parse()
            result.errors.extend(parse_result.errors)
            result.ast = parse_result.program
            method_note = parse_result.parse_method or "auto"
            result.stages_completed.append(f"语法分析({method_note})")
        except Exception as e:
            debug_info = f"\n[编译器内部错误堆栈]\n{traceback.format_exc()}" if __debug__ else ""
            result.errors.append(
                CompileDiagnostic(
                    stage="语法分析",
                    message=f"语法分析器异常: {e}{debug_info}",
                    code="E200",
                )
            )

        # 仅当AST完全无效时才跳过后续阶段
        if not result.ast or (not result.ast.statements and not result.ast.functions):
            if not any(e.code.startswith("E") for e in result.errors if e.stage == "语法分析"):
                result.errors.append(
                    CompileDiagnostic(
                        stage="语法分析",
                        message="未能生成有效的语法树，跳过后续阶段",
                        code="E299",
                    )
                )
            return self._finalize(result)

        # 4. 语义分析（收集全部语义错误）
        try:
            sem = SemanticAnalyzer().analyze(result.ast)
            result.errors.extend(sem.errors)
            result.warnings.extend(sem.warnings)
            result.symbol_table = sem.scope
            result.stages_completed.append("语义分析")
        except Exception as e:
            debug_info = f"\n[编译器内部错误堆栈]\n{traceback.format_exc()}" if __debug__ else ""
            result.errors.append(
                CompileDiagnostic(
                    stage="语义分析",
                    message=f"语义分析器异常: {e}{debug_info}",
                    code="E300",
                )
            )
            return self._finalize(result)

        # 存在任何错误时，跳过代码生成阶段
        if result.errors:
            return self._finalize(result)

        # 5. 中间代码
        try:
            result.tac = TACGenerator().generate(result.ast)
            result.stages_completed.append("中间代码")
        except Exception as e:
            debug_info = f"\n[编译器内部错误堆栈]\n{traceback.format_exc()}" if __debug__ else ""
            result.errors.append(
                CompileDiagnostic(
                    stage="中间代码",
                    message=f"中间代码生成失败: {e}{debug_info}",
                    code="E400",
                )
            )
            return self._finalize(result)

        # 6. 优化
        tac = result.tac
        if optimize and tac:
            try:
                result.optimized_tac = Optimizer().optimize(tac)
                tac = result.optimized_tac
                result.stages_completed.append("优化")
            except Exception as e:
                debug_info = f"\n[编译器内部错误堆栈]\n{traceback.format_exc()}" if __debug__ else ""
                result.warnings.append(
                    CompileDiagnostic(
                        stage="优化",
                        message=f"优化阶段失败，使用未优化代码: {e}{debug_info}",
                        severity=Severity.WARNING.value,
                        code="W400",
                    )
                )
                result.optimized_tac = None

        # 7. 目标代码
        try:
            result.target_code = CodeGenerator().generate(result.ast, tac)
            result.stages_completed.append("目标代码")
        except Exception as e:
            debug_info = f"\n[编译器内部错误堆栈]\n{traceback.format_exc()}" if __debug__ else ""
            result.errors.append(
                CompileDiagnostic(
                    stage="代码生成",
                    message=f"目标代码生成失败: {e}{debug_info}",
                    code="E500",
                )
            )
            return self._finalize(result)

  
        return self._finalize(result)

    def compile_file(self, path: Path, optimize: bool = True, run: bool = False, trace: bool = False) -> CompileResult:
        source = path.read_text(encoding="utf-8")
        return self.compile(source, optimize=optimize, run=run, trace=trace)

    @staticmethod
    def _run_target(code: str) -> str:
        buf = io.StringIO()
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = buf
        sys.stderr = buf
        
        globs = {
            "__name__": "__main__",
            "__file__": "<generated>",
            "__doc__": None,
            "__package__": None,
        }
        globs.update(runtime_globals())
        
        try:
            exec(compile(code, "<generated>", "exec"), globs)
            return buf.getvalue()
        except Exception as e:
            return f"[运行错误] {type(e).__name__}: {e}\n{traceback.format_exc()}"
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    @staticmethod
    def _finalize(result: CompileResult) -> CompileResult:
        result.errors.sort(key=lambda e: (e.line, e.col, e.code))
        result.warnings.sort(key=lambda e: (e.line, e.col, e.code))
        return result