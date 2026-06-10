"""MiniLang 简单编译器 — 完整编译流水线。"""

from .compiler import Compiler, CompileResult
from .lexer import Lexer, Token
from .parser import Parser
from .semantic import SemanticAnalyzer
from .tac import TACGenerator, TACProgram
from .optimizer import Optimizer
from .codegen import CodeGenerator

__all__ = [
    "Compiler",
    "CompileResult",
    "Lexer",
    "Token",
    "Parser",
    "SemanticAnalyzer",
    "TACGenerator",
    "TACProgram",
    "Optimizer",
    "CodeGenerator",
]
