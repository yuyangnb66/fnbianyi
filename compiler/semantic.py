"""语义分析 — 符号表、类型检查、作用域管理。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

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


class SemanticError(Exception):
    pass


@dataclass
class Symbol:
    name: str
    type_name: str
    declared_line: int


@dataclass
class Scope:
    symbols: Dict[str, Symbol] = field(default_factory=dict)
    parent: Optional[Scope] = None

    def define(self, sym: Symbol) -> None:
        if sym.name in self.symbols:
            old = self.symbols[sym.name]
            raise SemanticError(
                f"语义错误 L{sym.declared_line}: 变量 '{sym.name}' 重复定义（首次定义于 L{old.declared_line}）"
            )
        self.symbols[sym.name] = sym

    def lookup(self, name: str) -> Optional[Symbol]:
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None


class SemanticAnalyzer:
    NUMERIC = {"int", "float"}

    def __init__(self):
        self.global_scope = Scope()
        self.current_scope = self.global_scope
        self.errors: List[str] = []

    def analyze(self, program: Program) -> Scope:
        for stmt in program.statements:
            self._analyze_stmt(stmt)
        if self.errors:
            raise SemanticError("\n".join(self.errors))
        return self.global_scope

    def _push_scope(self) -> Scope:
        scope = Scope(parent=self.current_scope)
        self.current_scope = scope
        return scope

    def _pop_scope(self) -> None:
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent

    def _analyze_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, DeclStmt):
            self.current_scope.define(Symbol(stmt.name, stmt.type_name, stmt.line))
        elif isinstance(stmt, AssignStmt):
            sym = self.current_scope.lookup(stmt.name)
            if not sym:
                raise SemanticError(f"语义错误 L{stmt.line}: 未声明的变量 '{stmt.name}'")
            val_type = self._check_expr(stmt.value)
            if not self._compatible(sym.type_name, val_type):
                raise SemanticError(
                    f"语义错误 L{stmt.line}: 不能将 {val_type} 赋给 {sym.type_name} 变量 '{stmt.name}'"
                )
        elif isinstance(stmt, IfStmt):
            self._check_condition(stmt.condition, stmt.line)
            self._analyze_block(stmt.then_block)
            if stmt.else_block:
                self._analyze_block(stmt.else_block)
        elif isinstance(stmt, WhileStmt):
            self._check_condition(stmt.condition, stmt.line)
            self._analyze_block(stmt.body)
        elif isinstance(stmt, PrintStmt):
            self._check_expr(stmt.value)
        elif isinstance(stmt, Block):
            self._analyze_block(stmt)

    def _analyze_block(self, block: Block) -> None:
        self._push_scope()
        for stmt in block.statements:
            self._analyze_stmt(stmt)
        self._pop_scope()

    def _check_condition(self, expr: Expr, line: int) -> None:
        t = self._check_expr(expr)
        if isinstance(expr, RelExpr):
            return
        if t not in self.NUMERIC:
            raise SemanticError(f"语义错误 L{line}: 条件表达式类型无效")

    def _check_expr(self, expr: Expr) -> str:
        if isinstance(expr, IntLit):
            return "int"
        if isinstance(expr, FloatLit):
            return "float"
        if isinstance(expr, VarExpr):
            sym = self.current_scope.lookup(expr.name)
            if not sym:
                raise SemanticError(f"语义错误: 未声明的变量 '{expr.name}'")
            expr.type_name = sym.type_name
            return sym.type_name
        if isinstance(expr, UnaryExpr):
            t = self._check_expr(expr.operand)
            if expr.op == "-" and t in self.NUMERIC:
                expr.type_name = t
                return t
            raise SemanticError("语义错误: 一元 '-' 只能用于数值类型")
        if isinstance(expr, BinaryExpr):
            lt = self._check_expr(expr.left)
            rt = self._check_expr(expr.right)
            if lt not in self.NUMERIC or rt not in self.NUMERIC:
                raise SemanticError(f"语义错误: 算术运算 '{expr.op}' 的操作数必须是数值类型")
            result = "float" if "float" in (lt, rt) else "int"
            expr.type_name = result
            return result
        if isinstance(expr, RelExpr):
            lt = self._check_expr(expr.left)
            rt = self._check_expr(expr.right)
            if lt not in self.NUMERIC or rt not in self.NUMERIC:
                raise SemanticError(f"语义错误: 关系运算 '{expr.op}' 的操作数必须是数值类型")
            return "int"
        return "unknown"

    @staticmethod
    def _compatible(declared: str, assigned: str) -> bool:
        if declared == assigned:
            return True
        return declared == "float" and assigned == "int"
