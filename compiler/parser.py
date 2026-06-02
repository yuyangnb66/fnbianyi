"""语法分析器 — 递归下降，依据 grammar/grammar.json 中的 BNF 规则构建 AST。"""

from __future__ import annotations

from typing import List, Optional

from .ast_nodes import (
    AssignStmt,
    BinaryExpr,
    Block,
    DeclStmt,
    Expr,
    FloatLit,
    IfStmt,
    IntLit,
    PrintStmt,
    Program,
    RelExpr,
    Stmt,
    UnaryExpr,
    VarExpr,
    WhileStmt,
)
from .lexer import LexerError, Token


class ParseError(Exception):
    pass


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.kind != "EOF":
            self.pos += 1
        return tok

    def _match(self, *kinds: str) -> Optional[Token]:
        if self._peek().kind in kinds:
            return self._advance()
        return None

    def _expect(self, kind: str, msg: str = "") -> Token:
        tok = self._peek()
        if tok.kind != kind:
            hint = msg or f"期望 {kind}，实际为 {tok.kind} ({tok.value!r})"
            raise ParseError(f"语法错误 L{tok.line}: {hint}")
        return self._advance()

    def parse(self) -> Program:
        stmts = self._parse_stmt_list()
        self._expect("EOF")
        return Program(stmts)

    def _parse_stmt_list(self) -> List[Stmt]:
        stmts: List[Stmt] = []
        while self._peek().kind in ("INT", "FLOAT", "IF", "WHILE", "PRINT", "IDENT", "LBRACE"):
            stmts.append(self._parse_stmt())
        return stmts

    def _parse_stmt(self) -> Stmt:
        tok = self._peek()
        if tok.kind in ("INT", "FLOAT"):
            return self._parse_decl()
        if tok.kind == "IF":
            return self._parse_if()
        if tok.kind == "WHILE":
            return self._parse_while()
        if tok.kind == "PRINT":
            return self._parse_print()
        if tok.kind == "LBRACE":
            return self._parse_block()
        if tok.kind == "IDENT":
            return self._parse_assign()
        raise ParseError(f"语法错误 L{tok.line}: 无法解析语句，遇到 {tok.kind}")

    def _parse_decl(self) -> DeclStmt:
        type_tok = self._advance()
        name_tok = self._expect("IDENT")
        self._expect("SEMI")
        return DeclStmt(type_tok.value.lower(), name_tok.value, type_tok.line)

    def _parse_assign(self) -> AssignStmt:
        name_tok = self._advance()
        self._expect("ASSIGN")
        expr = self._parse_rel_expr()
        self._expect("SEMI")
        return AssignStmt(name_tok.value, expr, name_tok.line)

    def _parse_if(self) -> IfStmt:
        line = self._advance().line
        self._expect("LPAREN")
        cond = self._parse_rel_expr()
        self._expect("RPAREN")
        then_block = self._parse_block()
        else_block = None
        if self._match("ELSE"):
            else_block = self._parse_block()
        return IfStmt(cond, then_block, else_block, line)

    def _parse_while(self) -> WhileStmt:
        line = self._advance().line
        self._expect("LPAREN")
        cond = self._parse_rel_expr()
        self._expect("RPAREN")
        body = self._parse_block()
        return WhileStmt(cond, body, line)

    def _parse_print(self) -> PrintStmt:
        line = self._advance().line
        self._expect("LPAREN")
        expr = self._parse_rel_expr()
        self._expect("RPAREN")
        self._expect("SEMI")
        return PrintStmt(expr, line)

    def _parse_block(self) -> Block:
        self._expect("LBRACE")
        stmts = self._parse_stmt_list()
        self._expect("RBRACE")
        return Block(stmts)

    def _parse_rel_expr(self) -> Expr:
        left = self._parse_expr()
        rel_ops = {"EQ", "NE", "LT", "LE", "GT", "GE"}
        if self._peek().kind in rel_ops:
            op_tok = self._advance()
            right = self._parse_expr()
            return RelExpr(op_tok.value, left, right)
        return left

    def _parse_expr(self) -> Expr:
        node = self._parse_term()
        while self._match("PLUS", "MINUS"):
            op = self.tokens[self.pos - 1].value
            right = self._parse_term()
            node = BinaryExpr(op, node, right)
        return node

    def _parse_term(self) -> Expr:
        node = self._parse_factor()
        while self._match("STAR", "SLASH"):
            op = self.tokens[self.pos - 1].value
            right = self._parse_factor()
            node = BinaryExpr(op, node, right)
        return node

    def _parse_factor(self) -> Expr:
        tok = self._peek()
        if self._match("MINUS"):
            return UnaryExpr("-", self._parse_factor())
        if self._match("INT_LIT"):
            return IntLit(int(self.tokens[self.pos - 1].value))
        if self._match("FLOAT_LIT"):
            return FloatLit(float(self.tokens[self.pos - 1].value))
        if self._match("IDENT"):
            return VarExpr(self.tokens[self.pos - 1].value)
        if self._match("LPAREN"):
            expr = self._parse_rel_expr()
            self._expect("RPAREN")
            return expr
        raise ParseError(f"语法错误 L{tok.line}: 无法解析表达式，遇到 {tok.kind}")
