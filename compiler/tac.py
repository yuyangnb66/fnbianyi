"""中间代码生成 — 三地址码 (Three-Address Code, TAC)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Union

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


@dataclass
class TACInstr:
    op: str
    arg1: str = ""
    arg2: str = ""
    result: str = ""

    def __str__(self) -> str:
        if self.op == "label":
            return f"{self.result}:"
        if self.op == "goto":
            return f"goto {self.result}"
        if self.op == "ifFalse":
            return f"ifFalse {self.arg1} goto {self.result}"
        if self.op == "print":
            return f"print {self.arg1}"
        if self.op == "assign":
            return f"{self.result} = {self.arg1}"
        if self.op in ("+", "-", "*", "/", "==", "!=", "<", "<=", ">", ">="):
            return f"{self.result} = {self.arg1} {self.op} {self.arg2}"
        if self.op == "uminus":
            return f"{self.result} = -{self.arg1}"
        if self.op == "decl":
            return f"decl {self.result} {self.arg1}"
        return f"{self.op} {self.arg1} {self.arg2} {self.result}".strip()


@dataclass
class TACProgram:
    instructions: List[TACInstr] = field(default_factory=list)


class TACGenerator:
    def __init__(self):
        self.program = TACProgram()
        self.temp_count = 0
        self.label_count = 0

    def _new_temp(self) -> str:
        self.temp_count += 1
        return f"t{self.temp_count}"

    def _new_label(self, prefix: str = "L") -> str:
        self.label_count += 1
        return f"{prefix}{self.label_count}"

    def generate(self, program: Program) -> TACProgram:
        for stmt in program.statements:
            self._gen_stmt(stmt)
        return self.program

    def _gen_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, DeclStmt):
            self.program.instructions.append(
                TACInstr("decl", stmt.type_name, "", stmt.name)
            )
        elif isinstance(stmt, AssignStmt):
            val = self._gen_expr(stmt.value)
            self.program.instructions.append(TACInstr("assign", val, "", stmt.name))
        elif isinstance(stmt, PrintStmt):
            val = self._gen_expr(stmt.value)
            self.program.instructions.append(TACInstr("print", val))
        elif isinstance(stmt, IfStmt):
            self._gen_if(stmt)
        elif isinstance(stmt, WhileStmt):
            self._gen_while(stmt)
        elif isinstance(stmt, Block):
            for s in stmt.statements:
                self._gen_stmt(s)

    def _gen_if(self, stmt: IfStmt) -> None:
        cond = self._gen_condition(stmt.condition)
        else_label = self._new_label("else")
        end_label = self._new_label("endif")
        if stmt.else_block:
            self.program.instructions.append(TACInstr("ifFalse", cond, "", else_label))
            self._gen_stmt(stmt.then_block)
            self.program.instructions.append(TACInstr("goto", "", "", end_label))
            self.program.instructions.append(TACInstr("label", "", "", else_label))
            self._gen_stmt(stmt.else_block)
            self.program.instructions.append(TACInstr("label", "", "", end_label))
        else:
            self.program.instructions.append(TACInstr("ifFalse", cond, "", end_label))
            self._gen_stmt(stmt.then_block)
            self.program.instructions.append(TACInstr("label", "", "", end_label))

    def _gen_while(self, stmt: WhileStmt) -> None:
        start = self._new_label("while")
        end = self._new_label("endwhile")
        self.program.instructions.append(TACInstr("label", "", "", start))
        cond = self._gen_condition(stmt.condition)
        self.program.instructions.append(TACInstr("ifFalse", cond, "", end))
        self._gen_stmt(stmt.body)
        self.program.instructions.append(TACInstr("goto", "", "", start))
        self.program.instructions.append(TACInstr("label", "", "", end))

    def _gen_condition(self, expr: Expr) -> str:
        if isinstance(expr, RelExpr):
            left = self._gen_expr(expr.left)
            right = self._gen_expr(expr.right)
            temp = self._new_temp()
            self.program.instructions.append(
                TACInstr(expr.op, left, right, temp)
            )
            return temp
        return self._gen_expr(expr)

    def _gen_expr(self, expr: Expr) -> str:
        if isinstance(expr, IntLit):
            temp = self._new_temp()
            self.program.instructions.append(
                TACInstr("assign", str(expr.value), "", temp)
            )
            return temp
        if isinstance(expr, FloatLit):
            temp = self._new_temp()
            self.program.instructions.append(
                TACInstr("assign", str(expr.value), "", temp)
            )
            return temp
        if isinstance(expr, VarExpr):
            return expr.name
        if isinstance(expr, UnaryExpr):
            operand = self._gen_expr(expr.operand)
            temp = self._new_temp()
            self.program.instructions.append(TACInstr("uminus", operand, "", temp))
            return temp
        if isinstance(expr, BinaryExpr):
            left = self._gen_expr(expr.left)
            right = self._gen_expr(expr.right)
            temp = self._new_temp()
            self.program.instructions.append(TACInstr(expr.op, left, right, temp))
            return temp
        if isinstance(expr, RelExpr):
            return self._gen_condition(expr)
        raise ValueError(f"未知表达式类型: {type(expr)}")
