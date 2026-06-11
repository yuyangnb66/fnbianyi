# 语法分析器：递归下降，支持函数、循环、数组、字符串与逻辑运算

""" 语法分析错误统一 E2xx
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
from typing import List, Optional, Set

from .ast_nodes import (
    ArrayAccessExpr,
    AssignStmt,
    BinaryExpr,
    Block,
    BreakStmt,
    CallExpr,
    ContinueStmt,
    DeclStmt,
    Expr,
    FloatLit,
    ForStmt,
    FuncDecl,
    IfStmt,
    IntLit,
    InputStmt,
    PrintStmt,
    Program,
    RelExpr,
    ReturnStmt,
    Stmt,
    StringLit,
    UnaryExpr,
    VarExpr,
    WriteStmt,
    WhileStmt,
)
from .errors import CompileDiagnostic, Stage, diagnostic
from .lexer import Token


@dataclass
class ParseResult:
    program: Optional[Program] = None
    errors: List[CompileDiagnostic] = field(default_factory=list)


# 递归下降语法分析器
class Parser:
    STMT_START = frozenset({
        "IF", "WHILE", "FOR", "PRINT", "PRINTN", "INPUT", "WRITE",
        "INT", "FLOAT", "STRING", "IDENT", "RETURN", "BREAK",
        "CONTINUE", "LBRACE",
        # 支持左大括号单独作为语句开头（如while/if/for的左大括号单独换行）
    })
    STMT_BOUNDARY = frozenset({"SEMI", "RBRACE", "EOF"})
    TYPE_TOKENS = frozenset({"INT", "FLOAT", "STRING", "BOOL"})
    EXPR_BOUNDARY = frozenset({"PLUS", "MINUS", "STAR", "SLASH", "SEMI", "RPAREN", "COMMA", "RBRACKET"})

    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0
        self.errors: List[CompileDiagnostic] = []

    def _peek(self, offset: int = 0) -> Token:
        i = self.pos + offset
        return self.tokens[i] if i < len(self.tokens) else self.tokens[-1]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def _safe_peek_kind(self, offset: int) -> str:
        t = self._peek(offset)
        return t.kind

    def _match(self, *kinds: str) -> Optional[Token]:
        if self._peek().kind in kinds:
            return self._advance()
        return None

    # 统一错误入口：强制绑定行列号，所有错误必带建议
    def _error(self, message: str, tok: Optional[Token] = None, code: str = "E201", suggestion: str = "") -> None:
        t = tok or self._peek()
        self.errors.append(diagnostic(
            Stage.SYNTAX,
            message,
            line=t.line,
            col=t.col,
            code=code,
            suggestion=suggestion
        ))

    def _expect(self, kind: str, msg: str = "") -> Optional[Token]:
        tok = self._peek()
        if tok.kind != kind:
            hint_map = {
                "SEMI": ("语句末尾缺少分号 ';'", "在语句末尾添加分号 ';'"),
                "RPAREN": ("缺少右括号 ')'", "在当前位置添加右括号 ')'"),
                "RBRACE": ("缺少右大括号 '}'", "在当前位置添加右大括号 '}'"),
                "RBRACKET": ("缺少右中括号 ']'", "在当前位置添加右中括号 ']'"),
                "LPAREN": ("缺少左括号 '('", "在当前位置添加左括号 '('"),
                "LBRACE": ("缺少左大括号 '{'", "在当前位置添加左大括号 '{'"),
                "LBRACKET": ("缺少左中括号 '['", "在当前位置添加左中括号 '['"),
                "IDENT": ("期望标识符", "输入一个合法的变量名或函数名"),
                "INT_LIT": ("期望整数", "输入一个整数"),
                "FLOAT_LIT": ("期望浮点数", "输入一个浮点数"),
                "STRING_LIT": ("期望字符串", "输入一个双引号包裹的字符串"),
            }
            default_hint = f"语法错误，期望 {kind}"
            default_suggestion = "检查代码语法是否正确"
            hint, suggestion = hint_map.get(kind, (default_hint, default_suggestion))
            hint = msg or hint

            code_map = {
                "SEMI": "E204",
                "RPAREN": "E202",
                "RBRACE": "E205",
                "RBRACKET": "E218",
                "LPAREN": "E202",
                "LBRACE": "E202",
                "LBRACKET": "E202",
            }
            code = code_map.get(kind, "E201")
            self._error(hint, tok, code, suggestion)
            return None
        return self._advance()

    # 跳过当前残余，停在指定同步点
    def _sync_to_next(self, sync_points: Optional[Set[str]] = None) -> None:
        if self._peek().kind == "EOF":
            return
        sync = sync_points or (self.STMT_START | self.STMT_BOUNDARY)
        while self._peek().kind not in sync:
            self._advance()

    # 语句解析失败，同步到安全位置
    def _recover_stmt(self) -> None:
        if self._peek().kind == "EOF":
            return
        start = self.pos
        self._sync_to_next()
        if self.pos == start:
            self._advance()
        while self._peek().kind == "SEMI":
            self._advance()

    # 语句结束处：显式绑定错误位置
    def _finish_stmt(self) -> None:
        if self._peek().kind == "SEMI":
            self._advance()
        else:
            current_tok = self._peek()
            self._error(
                "语句末尾缺少分号 ';'",
                tok=current_tok,
                code="E204",
                suggestion="每条语句请以分号结尾"
            )
            # 仅单步前进1个Token
            if self._peek().kind != "EOF":
                self._advance()

    def _is_function(self) -> bool:
        return (
            self._peek().kind in self.TYPE_TOKENS
            and self._safe_peek_kind(1) == "IDENT"
            and self._safe_peek_kind(2) == "LPAREN"
        )


    def parse(self) -> ParseResult:
        functions: List[FuncDecl] = []
        statements: List[Stmt] = []
        limit = len(self.tokens) + 1
        steps = 0
        while self._peek().kind != "EOF":
            steps += 1
            if steps > limit:
                self._error(
                    "语法分析错误恢复停滞，已中止",
                    tok=self._peek(),
                    code="E220",
                    suggestion="检查代码是否存在严重语法错误"
                )
                break
            if self._is_function():
                fn = self._parse_function()
                # 仅非None（合法函数）加入AST
                if fn is not None:
                    functions.append(fn)
                else:
                    self._recover_stmt()
            else:
                stmt = self._parse_stmt()
                # 仅非None（合法语句）加入AST
                if stmt is not None:
                    statements.append(stmt)
                else:
                    self._recover_stmt()
        if self._peek().kind == "EOF":
            self._advance()
        return ParseResult(program=Program(functions, statements), errors=list(self.errors))

    def _parse_function(self) -> Optional[FuncDecl]:
        ret_tok = self._advance()
        name_tok = self._expect("IDENT", "函数名应为标识符")
        # 函数名/左括号缺失，直接返回None，不生成FuncDecl
        if not name_tok or not self._expect("LPAREN"):
            self._sync_to_next({"RPAREN", "LBRACE"})
            if self._peek().kind == "RPAREN":
                self._advance()
            return None
        params: List[tuple[str, str]] = []
        if self._peek().kind in self.TYPE_TOKENS:
            params = self._parse_params()
        if not self._expect("RPAREN"):
            self._sync_to_next({"LBRACE"})
        body = self._parse_block()
        # 函数体解析失败，返回None
        if not body:
            return None
        return FuncDecl(ret_tok.value.lower(), name_tok.value, params, body, ret_tok.line, ret_tok.col)

    def _parse_params(self) -> List[tuple[str, str]]:
        params: List[tuple[str, str]] = []
        while True:
            pt = self._advance()
            if pt.kind not in self.TYPE_TOKENS:
                self._error(
                    "函数参数缺少类型声明",
                    tok=pt,
                    code="E211",
                    suggestion="参数需要类型声明，例如：int a, float b"
                )
                self._sync_to_next({"COMMA", "RPAREN"})
                if self._peek().kind == "COMMA":
                    self._advance()
                    continue
                break
            name = self._expect("IDENT", "参数名应为标识符")
            if name:
                params.append((pt.value.lower(), name.value))
            if not self._match("COMMA"):
                break
        return params

    def _parse_stmt_list(self) -> List[Stmt]:
        stmts: List[Stmt] = []
        limit = len(self.tokens) + 1
        steps = 0
        while self._peek().kind in self.STMT_START:
            steps += 1
            if steps > limit:
                self._error(
                    "语法分析错误恢复停滞（错误恢复陷入死循环，已中止）",
                    tok=self._peek(),
                    code="E220",
                    suggestion="检查代码是否存在严重语法错误"
                )
                break
            stmt = self._parse_stmt()
            # 过滤非法语句
            if stmt:
                stmts.append(stmt)
            else:
                self._recover_stmt()
        return stmts

    # 解析独立函数调用语句
    def _parse_call_stmt(self) -> Optional[Expr]:
        call_expr = self._parse_factor()
        if not call_expr:
            return None
        self._finish_stmt()
        return call_expr

    def _parse_stmt(self) -> Optional[Stmt]:
        tok = self._peek()
        try:
            if tok.kind in self.TYPE_TOKENS:
                return self._parse_decl()
            if tok.kind == "IF":
                return self._parse_if()
            if tok.kind == "WHILE":
                return self._parse_while()
            if tok.kind == "FOR":
                return self._parse_for()
            if tok.kind == "PRINT":
                return self._parse_print(newline=True)
            if tok.kind == "PRINTN":
                return self._parse_print(newline=False)
            if tok.kind == "INPUT":
                return self._parse_input()
            if tok.kind == "WRITE":
                return self._parse_write()
            if tok.kind == "RETURN":
                return self._parse_return()
            if tok.kind == "BREAK":
                self._advance()
                self._expect("SEMI")
                return BreakStmt(tok.line, tok.col)
            if tok.kind == "CONTINUE":
                self._advance()
                self._expect("SEMI")
                return ContinueStmt(tok.line, tok.col)
            if tok.kind == "LBRACE":
                return self._parse_block()
            if tok.kind == "IDENT":
                # 区分函数调用 / 赋值语句
                if self._safe_peek_kind(1) == "LPAREN":
                    return self._parse_call_stmt()
                return self._parse_assign()

            self._error(
                "无法解析语句开头",
                tok=tok,
                code="E203",
                suggestion="使用合法关键字或标识符作为语句起始"
            )
            self._advance()
            return None
        except Exception:
            self._error(
                "语法分析内部错误（解析器运行时异常）",
                tok=tok,
                code="E221",
                suggestion="这是编译器内部错误，请简化代码重试"
            )
            self._recover_stmt()
            return None

    def _parse_decl(self) -> Optional[DeclStmt]:
        type_tok = self._advance()
        if self._peek().kind != "IDENT":
            self._error(
                "类型声明 '{}' 后应跟变量名".format(type_tok.value),
                tok=type_tok,
                code="E201",
                suggestion="类型后必须填写合法变量名"
            )
            # 同步到语句边界，彻底离开错误区域
            self._sync_to_next(self.STMT_BOUNDARY)
            # 强制再前进一步，避免循环重复报错
            if self._peek().kind != "EOF":
                self._advance()
            return None

        name_tok = self._advance()
        array_size = None
        if self._match("LBRACKET"):
            size_tok = self._expect("INT_LIT", "数组大小应为正整数")
            if size_tok:
                array_size = int(size_tok.value)
            self._expect("RBRACKET")
        self._finish_stmt()
        return DeclStmt(type_tok.value.lower(), name_tok.value, array_size, type_tok.line, type_tok.col)


    def _parse_assign(self) -> Optional[AssignStmt]:
        name_tok = self._advance()
        index = None
        if self._match("LBRACKET"):
            index = self._parse_logic()
            if not self._expect("RBRACKET"):
                self._sync_to_next(self.EXPR_BOUNDARY)
                return None
        # 缺少赋值号=，返回None
        if not self._expect("ASSIGN"):
            self._sync_to_next(self.EXPR_BOUNDARY)
            return None
        value = self._parse_logic()
        # 右侧表达式解析失败，返回None
        if not value:
            self._sync_to_next(self.EXPR_BOUNDARY)
            return None
        self._finish_stmt()
        return AssignStmt(name_tok.value, value, index, name_tok.line, name_tok.col)


    def _parse_if(self) -> Optional[IfStmt]:
        tok = self._advance()
        line = tok.line
        col = tok.col       
        if self._peek().kind != "LPAREN":
            self._error(
                "缺少左括号 '('",
                tok=self._peek(),
                code="E202",
                suggestion="在当前位置添加左括号 '('"
            )
            self._sync_to_next({"LBRACE"})
            return None
        self._advance()
        cond = self._parse_logic()
        if cond is None:
            self._sync_to_next({"RPAREN", "LBRACE"})
            return None
        if self._peek().kind != "RPAREN":
            self._error(
                "if语句条件缺少右括号 ')'",
                tok=self._peek(),
                code="E215",
                suggestion="在'{'前补充右括号"
            )
            self._sync_to_next({"LBRACE"})
            return None
        self._advance()
        then_block = self._parse_block()
        if not then_block:
            return None
        else_block = None
        if self._match("ELSE"):
            else_block = self._parse_block()
        return IfStmt(cond, then_block, else_block, line, col)

    def _parse_while(self) -> Optional[WhileStmt]:
        tok = self._advance()
        line = tok.line
        col = tok.col
        if self._peek().kind != "LPAREN":
            self._error(
                "缺少左括号 '('",
                tok=self._peek(),
                code="E202",
                suggestion="在当前位置添加左括号 '('"
            )
            self._sync_to_next({"LBRACE"})
            return None
        self._advance()
        cond = self._parse_logic()
        # 条件表达式解析失败，直接返回None
        if cond is None:
            self._sync_to_next({"RPAREN", "LBRACE"})
            return None
        if self._peek().kind != "RPAREN":
            self._error(
                "while语句条件缺少右括号 ')'",
                tok=self._peek(),
                code="E216",
                suggestion="在'{'前补充右括号"
            )
            self._sync_to_next({"LBRACE"})
            return None
        self._advance()
        body = self._parse_block()
        if not body:
            return None
        return WhileStmt(cond, body, line, col)

    def _parse_for(self) -> Optional[ForStmt]:
        tok = self._advance()
        line = tok.line
        col = tok.col
        if self._peek().kind != "LPAREN":
            self._error(
                "缺少左括号 '('",
                tok=self._peek(),
                code="E202",
                suggestion="在当前位置添加左括号 '('"
            )
            self._sync_to_next({"LBRACE"})
            return None
        self._advance()
        init = None
        if self._peek().kind == "IDENT":
            init = self._parse_assign_in_for()
        # 无论是否有初始化语句，都必须有第一个分号
        if not self._expect("SEMI"):
            self._sync_to_next({"SEMI", "RPAREN"})
            if self._peek().kind == "SEMI":
                self._advance()
            else:
                return None
        cond = None
        if self._peek().kind != "SEMI":
            cond = self._parse_logic()
        if not self._expect("SEMI"):
            return None
        update = None
        if self._peek().kind == "IDENT":
            update = self._parse_assign_in_for()
        if self._peek().kind != "RPAREN":
            self._error(
                "for循环头部缺少右括号 ')'",
                tok=self._peek(),
                code="E217",
                suggestion="在'{'前补充右括号"
            )
            self._sync_to_next({"LBRACE"})
            return None
        self._advance()
        body = self._parse_block()
        if not body:
            return None
        return ForStmt(init, cond, update, body, line, col)

    def _parse_assign_in_for(self) -> Optional[AssignStmt]:
        name_tok = self._advance()
        index = None
        if self._match("LBRACKET"):
            index = self._parse_logic()
            if not self._expect("RBRACKET"):
                return None
        if not self._expect("ASSIGN"):
            return None
        value = self._parse_logic()
        if not value:
            return None
        if self._peek().kind == "SEMI":
            self._advance()
        return AssignStmt(name_tok.value, value, index, name_tok.line, name_tok.col)

    def _parse_return(self) -> Optional[ReturnStmt]:
        tok = self._advance()
        line = tok.line
        col = tok.col
        value = None
        if self._peek().kind != "SEMI":
            value = self._parse_logic()
        self._finish_stmt()
        return ReturnStmt(value, line, col)

    def _parse_input(self) -> Optional[InputStmt]:
        tok = self._advance()
        line = tok.line
        col = tok.col
        if not self._expect("LPAREN"):
            self._sync_to_next(self.EXPR_BOUNDARY)
            return None
        names: List[str] = []
        first = self._expect("IDENT", "input需要至少一个变量名")
        if not first:
            self._sync_to_next({"RPAREN"})
            self._expect("RPAREN")
            self._finish_stmt()
            return None
        names.append(first.value)
        prompt = None
        while self._match("COMMA"):
            if self._peek().kind == "IDENT":
                names.append(self._advance().value)
            else:
                prompt = self._parse_logic()
                break
        if not self._expect("RPAREN"):
            return None
        self._finish_stmt()
        return InputStmt(names, prompt, line=line, col=col)

    def _parse_write(self) -> Optional[WriteStmt]:
        tok = self._advance()
        line = tok.line
        col = tok.col
        if not self._expect("LPAREN"):
            self._sync_to_next(self.EXPR_BOUNDARY)
            return None
        path = self._parse_logic()
        if not self._expect("COMMA"):
            self._sync_to_next({"RPAREN"})
            self._expect("RPAREN")
            self._finish_stmt()
            return None
        value = self._parse_logic()
        if not self._expect("RPAREN"):
            return None
        self._finish_stmt()
        return WriteStmt(path or StringLit(""), value or StringLit(""), line, col)

    def _parse_print(self, newline: bool = True) -> Optional[PrintStmt]:
        tok = self._advance()
        line = tok.line
        col = tok.col
        if not self._expect("LPAREN"):
            self._sync_to_next(self.EXPR_BOUNDARY)
            return None
        values: List[Expr] = []
        first = self._parse_logic()
        if first:
            values.append(first)
        while self._peek().kind == "COMMA":
            self._advance()
            if self._peek().kind == "RPAREN":
                break
            part = self._parse_logic()
            if part:
                values.append(part)
        if not self._expect("RPAREN"):
            return None
        self._finish_stmt()
        return PrintStmt(values, newline, line, col)

    def _parse_block(self) -> Optional[Block]:
        lbrace = self._expect("LBRACE")
        if not lbrace:
            return None
        stmts = self._parse_stmt_list()
        if not self._match("RBRACE"):
            self._error(
                "代码块未闭合，缺少 '}'",
                tok=self._peek(),
                code="E205",
                suggestion="在代码块末尾添加右大括号 '}'"
            )
        return Block(stmts)
    
    # 全表达式链路短路保护，出错返回None
    def _parse_logic(self) -> Optional[Expr]:
        node = self._parse_logic_and()
        if node is None:
            return None
        while self._match("OR"):
            op_tok = self.tokens[self.pos - 1]
            right = self._parse_logic_and()
            if not right:
                self._error(
                    "逻辑或 '||' 后缺少表达式",
                    tok=op_tok,
                    code="E212",
                    suggestion="在'||'后补充条件表达式"
                )
                self._sync_to_next(self.EXPR_BOUNDARY)
                return node
            node = BinaryExpr("||", node, right, line=op_tok.line, col=op_tok.col)
            node.type_name = "int"
        return node

    def _parse_logic_and(self) -> Optional[Expr]:
        node = self._parse_logic_not()
        if node is None:
            return None
        while self._match("AND"):
            op_tok = self.tokens[self.pos - 1]
            right = self._parse_logic_not()
            if not right:
                self._error(
                    "逻辑与 '&&' 后缺少表达式",
                    tok=op_tok,
                    code="E213",
                    suggestion="在'&&'后补充条件表达式"
                )
                self._sync_to_next(self.EXPR_BOUNDARY)
                return node
            node = BinaryExpr("&&", node, right, line=op_tok.line, col=op_tok.col)
            node.type_name = "int"
        return node

    def _parse_logic_not(self) -> Optional[Expr]:
        if self._match("NOT"):
            op_tok = self.tokens[self.pos - 1]
            inner = self._parse_logic_not()
            if not inner:
                self._error(
                    "逻辑非 '!' 后缺少表达式",
                    tok=op_tok,
                    code="E214",
                    suggestion="在'!'后补充条件表达式"
                )
                return None
            node = UnaryExpr("!", inner, line=op_tok.line, col=op_tok.col)
            node.type_name = "int"
        else:
            node = self._parse_rel_expr()
        return node

    def _parse_rel_expr(self) -> Optional[Expr]:
        left = self._parse_expr()
        if left is None:
            return None
        rel_ops = {"EQ", "NE", "LT", "LE", "GT", "GE"}
        if self._peek().kind in rel_ops:
            op_tok = self._advance()
            right = self._parse_expr()
            if not right:
                self._error(
                    "关系运算符后缺少右操作数",
                    tok=op_tok,
                    code="E206",
                    suggestion="在关系运算符右侧补充表达式"
                )
                self._sync_to_next(self.EXPR_BOUNDARY)
                return left
            return RelExpr(op_tok.value, left, right, line=op_tok.line, col=op_tok.col)
        return left

    def _parse_expr(self) -> Optional[Expr]:
        node = self._parse_term()
        if node is None:
            return None
        while self._match("PLUS", "MINUS"):
            op_tok = self.tokens[self.pos - 1]
            op = op_tok.value
            right = self._parse_term()
            if not right:
                self._error(
                    "加减运算符后缺少右操作数",
                    tok=op_tok,
                    code="E207",
                    suggestion="在运算符右侧补充操作数"
                )
                self._sync_to_next(self.EXPR_BOUNDARY)
                return node
            node = BinaryExpr(op, node, right, line=op_tok.line, col=op_tok.col)
        return node

    def _parse_term(self) -> Optional[Expr]:
        node = self._parse_factor()
        if node is None:
            return None
        while self._match("STAR", "SLASH"):
            op_tok = self.tokens[self.pos - 1]
            op = op_tok.value
            right = self._parse_factor()
            if not right:
                self._error(
                    "乘除运算符后缺少右操作数",
                    tok=op_tok,
                    code="E208",
                    suggestion="在运算符右侧补充操作数"
                )
                self._sync_to_next(self.EXPR_BOUNDARY)
                return node
            node = BinaryExpr(op, node, right, line=op_tok.line, col=op_tok.col)
        return node

    # 因子解析错误：不生成非法Expr节点，返回None
    def _parse_factor(self) -> Optional[Expr]:
        tok = self._peek()
        stmt_keywords = {"IF", "WHILE", "FOR", "RETURN", "BREAK", "CONTINUE"}
        if self._peek().kind in stmt_keywords:
            self._error(
                "表达式中不允许出现语句关键字",
                tok=self._peek(),
                code="E210",
                suggestion="表达式请使用变量、数字、运算符等合法元素"
            )
            self._recover_stmt()
            return None

        if self._match("MINUS"):
            op_tok = self.tokens[self.pos - 1]
            inner = self._parse_factor()
            if not inner:
                self._error(
                    "一元 '-' 后缺少操作数",
                    tok=op_tok,
                    code="E209",
                    suggestion="在负号后补充数字或变量"
                )
                return None
            return UnaryExpr("-", inner, line=op_tok.line, col=op_tok.col)
        
        if self._match("INT_LIT"):
            tok = self.tokens[self.pos - 1]
            return IntLit(int(tok.value), tok.line, tok.col)
        if self._match("FLOAT_LIT"):
            tok = self.tokens[self.pos - 1]
            return FloatLit(float(tok.value), tok.line, tok.col)
        if self._match("STRING_LIT"):
            tok = self.tokens[self.pos - 1]
            return StringLit(tok.value, tok.line, tok.col)
        if self._match("IDENT"):
            name = self.tokens[self.pos - 1].value
            # 函数调用解析
            if self._match("LPAREN"):
                args: List[Expr] = []
                if self._peek().kind != "RPAREN":
                    arg = self._parse_logic()
                    if arg:
                        args.append(arg)
                    while self._match("COMMA"):
                        before = self.pos
                        a = self._parse_logic()
                        if a:
                            args.append(a)
                        else:
                            # 空参数检测
                            self._error(
                                f"函数调用 {name} 存在空参数",
                                tok=self._peek(),
                                code="E219",
                                suggestion="删除多余的逗号，或补充参数值"
                            )
                            if self.pos == before and self._peek().kind not in ("RPAREN", "EOF"):
                                self._advance()
                sync = {"COMMA", "RPAREN", "SEMI"}
                while self._peek().kind not in sync:
                    self._advance()
                if not self._expect("RPAREN"):
                    return None
                tok = self.tokens[self.pos - 1]
                return CallExpr(name, args, line=tok.line, col=tok.col)
            # 数组下标访问
            if self._match("LBRACKET"):
                idx = self._parse_logic()
                if not self._expect("RBRACKET"):
                    return None
                if not idx:
                    return None
                tok = self.tokens[self.pos - 1]
                return ArrayAccessExpr(name, idx, line=tok.line, col=tok.col)
            # 普通变量引用
            tok = self.tokens[self.pos - 1]
            return VarExpr(name, line=tok.line, col=tok.col)
        # 括号表达式
        if self._match("LPAREN"):
            if self._peek().kind == "RPAREN":
                self._error(
                    "括号内缺少表达式",
                    tok=self._peek(),
                    code="E222",
                    suggestion="在括号内添加合法表达式"
                )
                self._advance()
                return None
            expr = self._parse_logic()
            if expr is None:
                self._error(
                    "括号内表达式解析失败",
                    tok=self._peek(),
                    code="E222",
                    suggestion="在括号内添加合法表达式"
                )
                return None
            if self._peek().kind != "RPAREN":
                self._expect("RPAREN")
            else:
                self._advance()
            return expr

        if tok.kind not in self.EXPR_BOUNDARY:
            self._error(
                "无法解析表达式基本元素",
                tok=tok,
                code="E210",
                suggestion="使用变量、数字、字符串等合法表达式元素"
            )
        return None
    