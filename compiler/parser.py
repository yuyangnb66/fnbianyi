"""语法分析器 — 表驱动 LL(1)/LR 系，自动选法，构建 AST。

语法分析错误统一 E2xx
E201: 通用语法错误（未归类的基础语法错误）
E202: 缺少括号/符号（左/右圆括号、左大括号、左中括号等成对符号缺失）
E203: 无法解析语句开头（遇到非法的语句起始token）
E204: 语句末尾缺少分号（MiniLang要求所有语句以分号结尾）
E205: 代码块未闭合（缺少右大括号'}'）
E206: 关系运算符后缺少右操作数（==/!=/<</>/<=/>= 右侧无表达式）
E207: 加减运算符后缺少右操作数（+/- 右侧无表达式）
E208: 乘除运算符后缺少右操作数（*// 右侧无表达式）
E209: 一元减号后缺少操作数（- 右侧无数字/变量/表达式）
E210: 无法解析表达式因子（遇到非法的表达式基本元素）
E211: 函数参数缺少类型声明（函数定义时参数未指定类型）
E212: 逻辑或'||'后缺少表达式（|| 右侧无条件表达式）
E213: 逻辑与'&&'后缺少表达式（&& 右侧无条件表达式）
E214: 逻辑非'!'后缺少表达式（! 右侧无条件表达式）
E215: if语句条件缺少右括号（if(condition) 缺少闭合的')'）
E216: while语句条件缺少右括号（while(condition) 缺少闭合的')'）
E217: for循环头缺少右括号（for(init;cond;update) 缺少闭合的')'）
E218: 数组下标缺少右中括号（array[index] 缺少闭合的']'）
E219: 函数调用参数无效（参数格式错误或存在空参数）
E220: 语法分析错误恢复停滞（错误恢复陷入死循环，已中止）
E221: 语法分析内部错误（解析器运行时异常）
E222: 括号内缺少表达式（空括号或括号内无有效内容）
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .ast_nodes import Program
from .errors import CompileDiagnostic
from .lexer import Token
from .parsing.ast_builder import build_program
from .parsing.parse_tree import PTNode
from .parsing.cfg import load_grammar
from .parsing.driver import parse_ll1, parse_lr
from .parser_rd import RecursiveDescentParser
from .parsing.selector import SelectedParser, select_parse_method


@dataclass
class ParseResult:
    program: Optional[Program] = None
    errors: List[CompileDiagnostic] = field(default_factory=list)
    parse_method: str = ""


# 递归下降语法分析器
class Parser:
    """表驱动语法分析器：LL(1) → LR(0) → SLR(1) → LALR(1) → LR(1) 自动选法。"""

    _cached: Optional[SelectedParser] = None
    _grammar_path: Optional[Path] = None

    def __init__(
        self,
        tokens: List[Token],
        grammar_path: Optional[Path] = None,
        method: str = "auto",
    ):
        self.tokens = tokens
        self.grammar_path = grammar_path or Path(__file__).parent.parent / "grammar" / "grammar.json"
        self.method_pref = method
        self.errors: List[CompileDiagnostic] = []
        self.parse_method = ""

    @classmethod
    def _get_selected(cls, grammar_path: Path, method: str) -> SelectedParser:
        if cls._cached is None or cls._grammar_path != grammar_path:
            cls._cached = select_parse_method(grammar_path, method)
            cls._grammar_path = grammar_path
        elif method != "auto" and cls._cached.method != method:
            cls._cached = select_parse_method(grammar_path, method)
        return cls._cached


    def parse(self) -> ParseResult:
        selected = self._get_selected(self.grammar_path, self.method_pref)
        self.parse_method = selected.method
        grammar = load_grammar(self.grammar_path)

        if selected.method == "LL1" and selected.ll1:
            drv = parse_ll1(self.tokens, grammar, selected.ll1)
        elif selected.lr:
            drv = parse_lr(self.tokens, grammar, selected.lr)
        else:
            self.errors.append(
                CompileDiagnostic(
                    stage="语法分析",
                    message="无法加载语法分析表",
                    code="E200",
                )
            )
            return ParseResult(None, list(self.errors), selected.method)

        self.errors.extend(drv.errors)
        program: Optional[Program] = None
        if drv.tree:
            root = drv.tree
            if root.symbol == "TopList":
                root = PTNode("Program", [root])
            if root.symbol == grammar.start:
                try:
                    program = build_program(root)
                except Exception as exc:
                    self.errors.append(
                        CompileDiagnostic(
                            stage="语法分析",
                            message=f"语法树构建失败: {exc}",
                            code="E202",
                        )
                    )
        elif not self.errors:
            self.errors.append(
                CompileDiagnostic(
                    stage="语法分析",
                    message="未能生成有效的语法树",
                    code="E299",
                )
            )

        if program is None and not any(e.code == "E298" for e in self.errors):
            fb = RecursiveDescentParser(self.tokens).parse()
            if fb.program and (fb.program.functions or fb.program.statements):
                program = fb.program
                self.errors.extend(fb.errors)
                self.parse_method = f"{selected.method}+RD"

        return ParseResult(program, list(self.errors), self.parse_method)
