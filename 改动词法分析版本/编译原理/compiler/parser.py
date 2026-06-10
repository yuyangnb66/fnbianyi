# 语法分析器：递归下降，支持函数、循环、数组、字符串与逻辑运算

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

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


class Parser:
    """递归下降语法分析器，带保证前进的 panic-mode 错误恢复。"""

    STMT_START = frozenset({
        "IF", "WHILE", "FOR", "PRINT", "PRINTN", "INPUT", "WRITE",
        "INT", "FLOAT", "STRING", "IDENT", "RETURN", "BREAK", "CONTINUE",
    })
    STMT_BOUNDARY = frozenset({"SEMI", "RBRACE", "EOF"})
    TYPE_TOKENS = frozenset({"INT", "FLOAT", "STRING"})

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

    def _match(self, *kinds: str) -> Optional[Token]:
        if self._peek().kind in kinds:
            return self._advance()
        return None

    def _error(self, message: str, tok: Optional[Token] = None, code: str = "E201") -> None:
        t = tok or self._peek()
        self.errors.append(diagnostic(Stage.SYNTAX, message, line=t.line, col=t.col, code=code))

    def _expect(self, kind: str, msg: str = "") -> Optional[Token]:
        tok = self._peek()
        if tok.kind != kind:
            hint = msg or f"期望 {kind}，实际为 {tok.kind} ({tok.value!r})"
            self._error(hint, tok, "E201")
            return None
        return self._advance()

    def _sync_to_next(self) -> None:
        """跳过当前语句残余，停在下一语句/块边界（不吞掉下一语句开头）。"""
        if self._peek().kind == "EOF":
            return
        while self._peek().kind not in self.STMT_START | self.STMT_BOUNDARY:
            self._advance()
        if self._peek().kind == "SEMI":
            self._advance()

    def _recover_stmt(self) -> None:
        """语句解析失败：同步到安全位置，且除非已到 EOF 否则至少前进 1 个 Token。"""
        if self._peek().kind == "EOF":
            return
        start = self.pos
        self._sync_to_next()
        if self.pos == start:
            self._advance()

    def _finish_stmt(self) -> None:
        """语句已基本解析，仅缺少或需要跳过分号。"""
        if self._peek().kind == "SEMI":
            self._advance()
        else:
            self._sync_to_next()

    def _is_function(self) -> bool:
        return (
            self._peek().kind in self.TYPE_TOKENS
            and self._peek(1).kind == "IDENT"
            and self._peek(2).kind == "LPAREN"
        )

    def parse(self) -> ParseResult:
        functions: List[FuncDecl] = []
        statements: List[Stmt] = []
        limit = len(self.tokens) + 1
        steps = 0
        while self._peek().kind != "EOF":
            steps += 1
            if steps > limit:
                self._error("语法分析错误恢复停滞，已中止", code="E298")
                break
            if self._is_function():
                fn = self._parse_function()
                if fn:
                    functions.append(fn)
                else:
                    self._recover_stmt()
            else:
                stmt = self._parse_stmt()
                if stmt:
                    statements.append(stmt)
                else:
                    self._recover_stmt()
        if self._peek().kind == "EOF":
            self._advance()
        return ParseResult(program=Program(functions, statements), errors=list(self.errors))

    def _parse_function(self) -> Optional[FuncDecl]:
        ret_tok = self._advance()
        name_tok = self._expect("IDENT", "函数名应为标识符")
        if not name_tok or not self._expect("LPAREN"):
            return None
        params: List[tuple[str, str]] = []
        if self._peek().kind in self.TYPE_TOKENS:
            params = self._parse_params()
        if not self._expect("RPAREN"):
            return None
        body = self._parse_block()
        if not body:
            return None
        return FuncDecl(ret_tok.value.lower(), name_tok.value, params, body, ret_tok.line)

    def _parse_params(self) -> List[tuple[str, str]]:
        params: List[tuple[str, str]] = []
        while True:
            pt = self._advance()
            if pt.kind not in self.TYPE_TOKENS:
                self._error("参数需要类型", pt, "E212")
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
        while self._peek().kind in (
            "INT", "FLOAT", "STRING", "IF", "WHILE", "FOR", "PRINT", "PRINTN", "INPUT", "WRITE",
            "IDENT", "LBRACE", "RETURN", "BREAK", "CONTINUE",
        ):
            steps += 1
            if steps > limit:
                self._error("代码块内错误恢复停滞，已中止", code="E298")
                break
            stmt = self._parse_stmt()
            if stmt:
                stmts.append(stmt)
            else:
                self._recover_stmt()
        return stmts

    def _parse_stmt(self) -> Optional[Stmt]:
        tok = self._peek()
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
            return BreakStmt(tok.line)
        if tok.kind == "CONTINUE":
            self._advance()
            self._expect("SEMI")
            return ContinueStmt(tok.line)
        if tok.kind == "LBRACE":
            return self._parse_block()
        if tok.kind == "IDENT":
            return self._parse_assign()
        self._error(f"无法解析语句，遇到 {tok.kind} ({tok.value!r})", tok, "E203")
        return None

    def _parse_decl(self) -> Optional[DeclStmt]:
        type_tok = self._advance()
        name_tok = self._expect("IDENT")
        if not name_tok:
            return None
        array_size = None
        if self._match("LBRACKET"):
            size_tok = self._expect("INT_LIT", "数组大小应为正整数")
            if size_tok:
                array_size = int(size_tok.value)
            if not self._expect("RBRACKET"):
                return None
        if not self._expect("SEMI"):
            self._finish_stmt()
        return DeclStmt(type_tok.value.lower(), name_tok.value, array_size, type_tok.line)

    def _parse_assign(self) -> Optional[AssignStmt]:
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
        if not self._expect("SEMI"):
            self._finish_stmt()
        return AssignStmt(name_tok.value, value, index, name_tok.line)

    def _parse_if(self) -> Optional[IfStmt]:
        line = self._advance().line
        if not self._expect("LPAREN"):
            return None
        cond = self._parse_logic()
        if not cond:
            return None
        if not self._expect("RPAREN"):
            if self._peek().kind == "LBRACE":
                self._error("if 条件缺少右括号 ')'，在 '{' 之前", code="E216")
            return None
        then_block = self._parse_block()
        if not then_block:
            return None
        else_block = None
        if self._match("ELSE"):
            else_block = self._parse_block()
        return IfStmt(cond, then_block, else_block, line)

    def _parse_while(self) -> Optional[WhileStmt]:
        line = self._advance().line
        if not self._expect("LPAREN"):
            return None
        cond = self._parse_logic()
        if not cond:
            return None
        if not self._expect("RPAREN"):
            if self._peek().kind == "LBRACE":
                self._error("while 条件缺少右括号 ')'，在 '{' 之前", code="E217")
            return None
        body = self._parse_block()
        if not body:
            return None
        return WhileStmt(cond, body, line)

    def _parse_for(self) -> Optional[ForStmt]:
        line = self._advance().line
        if not self._expect("LPAREN"):
            return None
        init = None
        if self._peek().kind == "IDENT":
            init = self._parse_assign_in_for()
        else:
            self._expect("SEMI")
        if self._peek().kind != "SEMI":
            cond = self._parse_logic()
        else:
            cond = IntLit(1)
        if not self._expect("SEMI"):
            return None
        update = None
        if self._peek().kind == "IDENT":
            update = self._parse_assign_in_for()
        if not self._expect("RPAREN"):
            if self._peek().kind == "LBRACE":
                self._error("for 头缺少右括号 ')'，在 '{' 之前", code="E218")
            return None
        body = self._parse_block()
        if not body:
            return None
        return ForStmt(init, cond, update, body, line)

    def _parse_assign_in_for(self) -> Optional[AssignStmt]:
        name_tok = self._advance()
        index = None
        if self._match("LBRACKET"):
            index = self._parse_logic()
            self._expect("RBRACKET")
        if not self._expect("ASSIGN"):
            return None
        value = self._parse_logic()
        if self._peek().kind == "SEMI":
            self._advance()
        return AssignStmt(name_tok.value, value, index, name_tok.line)

    def _parse_return(self) -> Optional[ReturnStmt]:
        line = self._advance().line
        value = None
        if self._peek().kind != "SEMI":
            value = self._parse_logic()
        self._expect("SEMI")
        return ReturnStmt(value, line)

    def _parse_input(self) -> Optional[InputStmt]:
        line = self._advance().line
        if not self._expect("LPAREN"):
            return None
        names: List[str] = []
        first = self._expect("IDENT", "input 需要至少一个变量名")
        if not first:
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
        if not self._expect("SEMI"):
            self._finish_stmt()
        return InputStmt(names, prompt, line=line)

    def _parse_write(self) -> Optional[WriteStmt]:
        line = self._advance().line
        if not self._expect("LPAREN"):
            return None
        path = self._parse_logic()
        if not self._expect("COMMA"):
            return None
        value = self._parse_logic()
        if not value or not self._expect("RPAREN"):
            return None
        if not self._expect("SEMI"):
            self._finish_stmt()
        return WriteStmt(path, value, line)

    def _parse_print(self, newline: bool = True) -> Optional[PrintStmt]:
        line = self._advance().line
        if not self._expect("LPAREN"):
            return None
        values: List[Expr] = []
        first = self._parse_logic()
        if not first:
            return None
        values.append(first)
        while self._match("COMMA"):
            if self._peek().kind == "RPAREN":
                break
            part = self._parse_logic()
            if part:
                values.append(part)
        if not self._expect("RPAREN"):
            return None
        if not self._expect("SEMI"):
            self._finish_stmt()
        return PrintStmt(values, newline, line)

    def _parse_block(self) -> Optional[Block]:
        if not self._expect("LBRACE"):
            return None
        stmts = self._parse_stmt_list()
        if not self._expect("RBRACE"):
            self._error("代码块未闭合，缺少 '}'", code="E205")
        return Block(stmts)

    def _parse_logic(self) -> Optional[Expr]:
        node = self._parse_logic_and()
        while self._match("OR"):
            right = self._parse_logic_and()
            if not right:
                self._error("逻辑或 '||' 后缺少表达式", code="E213")
                break
            node = BinaryExpr("||", node, right)
            node.type_name = "int"
        return node

    def _parse_logic_and(self) -> Optional[Expr]:
        node = self._parse_logic_not()
        while self._match("AND"):
            right = self._parse_logic_not()
            if not right:
                self._error("逻辑与 '&&' 后缺少表达式", code="E214")
                break
            node = BinaryExpr("&&", node, right)
            node.type_name = "int"
        return node

    def _parse_logic_not(self) -> Optional[Expr]:
        if self._match("NOT"):
            inner = self._parse_logic_not()
            if not inner:
                self._error("逻辑非 '!' 后缺少表达式", code="E215")
                return None
            node = UnaryExpr("!", inner)
            node.type_name = "int"
            return node
        return self._parse_rel_expr()

    def _parse_rel_expr(self) -> Optional[Expr]:
        left = self._parse_expr()
        if not left:
            return None
        rel_ops = {"EQ", "NE", "LT", "LE", "GT", "GE"}
        if self._peek().kind in rel_ops:
            op_tok = self._advance()
            right = self._parse_expr()
            if not right:
                self._error("关系运算符后缺少右操作数", code="E206")
                return left
            return RelExpr(op_tok.value, left, right)
        return left

    def _parse_expr(self) -> Optional[Expr]:
        node = self._parse_term()
        if not node:
            return None
        while self._match("PLUS", "MINUS"):
            op = self.tokens[self.pos - 1].value
            right = self._parse_term()
            if not right:
                self._error(f"运算符 '{op}' 后缺少右操作数", code="E207")
                break
            node = BinaryExpr(op, node, right)
        return node

    def _parse_term(self) -> Optional[Expr]:
        node = self._parse_factor()
        if not node:
            return None
        while self._match("STAR", "SLASH"):
            op = self.tokens[self.pos - 1].value
            right = self._parse_factor()
            if not right:
                self._error(f"运算符 '{op}' 后缺少右操作数", code="E208")
                break
            node = BinaryExpr(op, node, right)
        return node

    def _parse_factor(self) -> Optional[Expr]:
        tok = self._peek()
        if self._match("MINUS"):
            inner = self._parse_factor()
            if not inner:
                self._error("一元 '-' 后缺少操作数", code="E209")
                return None
            return UnaryExpr("-", inner)
        if self._match("INT_LIT"):
            return IntLit(int(self.tokens[self.pos - 1].value))
        if self._match("FLOAT_LIT"):
            return FloatLit(float(self.tokens[self.pos - 1].value))
        if self._match("STRING_LIT"):
            return StringLit(self.tokens[self.pos - 1].value)
        if self._match("IDENT"):
            name = self.tokens[self.pos - 1].value
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
                        elif self.pos == before and self._peek().kind not in ("RPAREN", "EOF"):
                            self._advance()
                self._expect("RPAREN")
                return CallExpr(name, args)
            if self._match("LBRACKET"):
                idx = self._parse_logic()
                self._expect("RBRACKET")
                return ArrayAccessExpr(name, idx) if idx else VarExpr(name)
            return VarExpr(name)
        if self._match("LPAREN"):
            expr = self._parse_logic()
            self._expect("RPAREN")
            return expr
        self._error(f"无法解析表达式，遇到 {tok.kind} ({tok.value!r})", tok, "E211")
        return None
