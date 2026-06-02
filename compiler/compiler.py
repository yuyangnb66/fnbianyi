"""编译器流水线 — 串联各阶段。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .ast_nodes import Program
from .codegen import CodeGenerator
from .lexer import Lexer, Token
from .optimizer import Optimizer
from .parser import Parser
from .semantic import SemanticAnalyzer, Scope
from .tac import TACProgram, TACGenerator


@dataclass
class CompileResult:
    source: str
    tokens: List[Token] = field(default_factory=list)
    ast: Optional[Program] = None
    symbol_table: Optional[Scope] = None
    tac: Optional[TACProgram] = None
    optimized_tac: Optional[TACProgram] = None
    target_code: str = ""
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not self.errors


class Compiler:
    def __init__(self, grammar_dir: Optional[Path] = None):
        self.grammar_dir = grammar_dir or Path(__file__).parent.parent / "grammar"
        self.tokens_path = self.grammar_dir / "tokens.json"

    def compile(self, source: str, optimize: bool = True) -> CompileResult:
        result = CompileResult(source=source)
        try:
            lexer = Lexer(source, self.tokens_path)
            result.tokens = lexer.tokenize()
            parser = Parser(result.tokens)
            result.ast = parser.parse()
            analyzer = SemanticAnalyzer()
            result.symbol_table = analyzer.analyze(result.ast)
            gen = TACGenerator()
            result.tac = gen.generate(result.ast)
            tac = result.tac
            if optimize:
                opt = Optimizer()
                result.optimized_tac = opt.optimize(tac)
                tac = result.optimized_tac
            cg = CodeGenerator()
            result.target_code = cg.generate(tac)
        except Exception as e:
            result.errors.append(str(e))
        return result

    def compile_file(self, path: Path, optimize: bool = True) -> CompileResult:
        source = path.read_text(encoding="utf-8")
        return self.compile(source, optimize=optimize)
