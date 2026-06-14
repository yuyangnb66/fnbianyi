"""中间代码生成 — 三地址码 (Three-Address Code, TAC)。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .input_check import while_getint_bound
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
    WhileStmt,
    WriteStmt,
)


@dataclass
class TACInstr:
    op: str
    arg1: str = ""
    arg2: str = ""
    result: str = ""

    def __str__(self) -> str:
        ops = {
            "label": lambda: f"{self.result}:",
            "goto": lambda: f"goto {self.result}",
            "ifFalse": lambda: f"ifFalse {self.arg1} goto {self.result}",
            "print": lambda: f"print {self.arg1}",
            "input": lambda: f"input {self.result} {self.arg1}",
            "write": lambda: f"write {self.arg1} {self.arg2}",
            "assign": lambda: f"{self.result} = {self.arg1}",
            "array_set": lambda: f"{self.result}[{self.arg1}] = {self.arg2}",
            "array_get": lambda: f"{self.result} = {self.arg2}[{self.arg1}]",
            "decl": lambda: f"decl {self.result} {self.arg1}",
            "decl_array": lambda: f"decl_array {self.result} {self.arg1} {self.arg2}",
            "return": lambda: f"return {self.arg1}",
            "call": lambda: f"{self.result} = call {self.arg1}({self.arg2})",
            "func": lambda: f"func {self.result}({self.arg1}) -> {self.arg2}",
            "endfunc": lambda: f"endfunc {self.result}",
            "uminus": lambda: f"{self.result} = -{self.arg1}",
            "not": lambda: f"{self.result} = !{self.arg1}",
        }
        if self.op in ops:
            return ops[self.op]()
        if self.op in ("+", "-", "*", "/", "==", "!=", "<", "<=", ">", ">=", "&&", "||"):
            return f"{self.result} = {self.arg1} {self.op} {self.arg2}"
        return f"{self.op} {self.arg1} {self.arg2} {self.result}".strip()


@dataclass
class TACProgram:
    instructions: List[TACInstr] = field(default_factory=list)
    functions: List[TACInstr] = field(default_factory=list)


class TACGenerator:
    def __init__(self):
        self.program = TACProgram()
        self.temp_count = 0
        self.label_count = 0
        self.loop_stack: List[Tuple[str, str]] = []
        self.getint_bound_stack: List[Optional[Tuple[str, str]]] = []

    def _new_temp(self) -> str:
        self.temp_count += 1
        return f"t{self.temp_count}"

    def _new_label(self, prefix: str = "L") -> str:
        self.label_count += 1
        return f"{prefix}{self.label_count}"

    def generate(self, program: Program) -> TACProgram:
        main_fn = next((fn for fn in program.functions if fn.name == "main"), None)
        for fn in program.functions:
            if fn.name != "main":
                self._gen_function(fn)
        for stmt in program.statements:
            if isinstance(stmt, DeclStmt):
                self._gen_stmt(stmt)
        if not main_fn:
            exec_stmts = [s for s in program.statements if not isinstance(s, DeclStmt)]
            self._gen_stmt_list(exec_stmts, self.program.instructions)
        return self.program

    def _gen_function(self, fn: FuncDecl) -> None:
        params = ",".join(p[1] for p in fn.params)
        self.program.functions.append(
            TACInstr("func", fn.name, params, fn.return_type)
        )
        for ptype, pname in fn.params:
            self.program.functions.append(TACInstr("decl", ptype, "", pname))
        self._gen_stmt_list(fn.body.statements, self.program.functions)
        self.program.functions.append(TACInstr("endfunc", fn.name))

    def _gen_stmt_list(self, stmts: List[Stmt], out: List[TACInstr]) -> None:
        for i, stmt in enumerate(stmts):
            self._gen_stmt(stmt, out, stmts[i + 1 :])

    def _gen_stmt(self, stmt: Stmt, target: Optional[List[TACInstr]] = None, following: Optional[List[Stmt]] = None) -> None:
        out = target if target is not None else self.program.instructions
        old_out = getattr(self, "_out", None)
        self._out = out
        try:
            if isinstance(stmt, DeclStmt):
                for name, arr_size in zip(stmt.names, stmt.array_sizes):
                    if arr_size is not None:
                        out.append(TACInstr("decl_array", str(arr_size), stmt.type_name, name))
                    else:
                        default = stmt.type_name
                        out.append(TACInstr("decl", default, "", name))
            elif isinstance(stmt, AssignStmt):
                val = self._gen_expr(stmt.value, out)
                if stmt.index:
                    idx = self._gen_expr(stmt.index, out)
                    out.append(TACInstr("array_set", idx, val, stmt.name))
                else:
                    out.append(TACInstr("assign", val, "", stmt.name))
            elif isinstance(stmt, PrintStmt):
                parts = [self._gen_expr(v, out) for v in stmt.values]
                op = "printn" if not stmt.newline else "print"
                out.append(TACInstr(op, ",".join(parts)))
            elif isinstance(stmt, InputStmt):
                prompt = self._gen_expr(stmt.prompt, out) if stmt.prompt else '""'
                types = ",".join(stmt.type_names) if stmt.type_names else "int"
                names = ",".join(stmt.names)
                out.append(TACInstr("input", prompt, types, names))
            elif isinstance(stmt, WriteStmt):
                path = self._gen_expr(stmt.path, out)
                val = self._gen_expr(stmt.value, out)
                out.append(TACInstr("write", path, val))
            elif isinstance(stmt, IfStmt):
                self._gen_if(stmt, out)
            elif isinstance(stmt, WhileStmt):
                self._gen_while(stmt, out)
            elif isinstance(stmt, ForStmt):
                self._gen_for(stmt, out)
            elif isinstance(stmt, ReturnStmt):
                val = self._gen_expr(stmt.value, out) if stmt.value else "0"
                out.append(TACInstr("return", val))
            elif isinstance(stmt, BreakStmt):
                if self.loop_stack:
                    out.append(TACInstr("goto", "", "", self.loop_stack[-1][0]))
            elif isinstance(stmt, ContinueStmt):
                if self.loop_stack:
                    out.append(TACInstr("goto", "", "", self.loop_stack[-1][1]))
            elif isinstance(stmt, Block):
                self._gen_stmt_list(stmt.statements, out)
        finally:
            self._out = old_out if old_out is not None else self.program.instructions

    def _gen_if(self, stmt: IfStmt, out: List[TACInstr]) -> None:
        end_label = self._new_label("endif")
        elif_count = len(stmt.elif_blocks)
        has_else = bool(stmt.else_block)
        total_targets = elif_count + (1 if has_else else 0)

        if total_targets == 0:
            cond = self._gen_condition(stmt.condition, out)
            out.append(TACInstr("ifFalse", cond, "", end_label))
            self._gen_stmt(stmt.then_block, out)
        else:
            next_labels = [self._new_label("elif") for _ in range(total_targets)]

            cond = self._gen_condition(stmt.condition, out)
            out.append(TACInstr("ifFalse", cond, "", next_labels[0]))
            self._gen_stmt(stmt.then_block, out)
            out.append(TACInstr("goto", "", "", end_label))

            for i, (elif_cond, elif_block) in enumerate(stmt.elif_blocks):
                out.append(TACInstr("label", "", "", next_labels[i]))
                cond = self._gen_condition(elif_cond, out)
                next_idx = i + 1
                if next_idx < len(next_labels):
                    out.append(TACInstr("ifFalse", cond, "", next_labels[next_idx]))
                else:
                    out.append(TACInstr("ifFalse", cond, "", end_label))
                self._gen_stmt(elif_block, out)
                out.append(TACInstr("goto", "", "", end_label))

            if stmt.else_block:
                out.append(TACInstr("label", "", "", next_labels[-1]))
                self._gen_stmt(stmt.else_block, out)

        out.append(TACInstr("label", "", "", end_label))

    def _gen_while(self, stmt: WhileStmt, out: List[TACInstr]) -> None:
        start = self._new_label("while")
        end = self._new_label("endwhile")
        self.loop_stack.append((end, start))
        self.getint_bound_stack.append(while_getint_bound(stmt.condition, stmt.body))
        out.append(TACInstr("label", "", "", start))
        cond = self._gen_condition(stmt.condition, out)
        out.append(TACInstr("ifFalse", cond, "", end))
        self._gen_stmt_list(stmt.body.statements, out)
        out.append(TACInstr("goto", "", "", start))
        out.append(TACInstr("label", "", "", end))
        self.loop_stack.pop()
        self.getint_bound_stack.pop()

    def _gen_for(self, stmt: ForStmt, out: List[TACInstr]) -> None:
        if stmt.init:
            self._gen_stmt(stmt.init, out)
        start = self._new_label("for")
        update = self._new_label("forupd")
        end = self._new_label("endfor")
        self.loop_stack.append((end, update))
        out.append(TACInstr("label", "", "", start))
        cond = self._gen_condition(stmt.condition, out)
        out.append(TACInstr("ifFalse", cond, "", end))
        self._gen_stmt_list(stmt.body.statements, out)
        out.append(TACInstr("label", "", "", update))
        if stmt.update:
            self._gen_stmt(stmt.update, out)
        out.append(TACInstr("goto", "", "", start))
        out.append(TACInstr("label", "", "", end))
        self.loop_stack.pop()

    def _gen_condition(self, expr: Expr, out: List[TACInstr]) -> str:
        if isinstance(expr, RelExpr):
            left = self._gen_expr(expr.left, out)
            right = self._gen_expr(expr.right, out)
            temp = self._new_temp()
            out.append(TACInstr(expr.op, left, right, temp))
            return temp
        if isinstance(expr, BinaryExpr) and expr.op in ("&&", "||"):
            return self._gen_expr(expr, out)
        return self._gen_expr(expr, out)

    def _gen_expr(self, expr: Optional[Expr], out: List[TACInstr]) -> str:
        if expr is None:
            return "0"
        if isinstance(expr, IntLit):
            temp = self._new_temp()
            out.append(TACInstr("assign", str(expr.value), "", temp))
            return temp
        if isinstance(expr, FloatLit):
            temp = self._new_temp()
            out.append(TACInstr("assign", str(expr.value), "", temp))
            return temp
        if isinstance(expr, StringLit):
            temp = self._new_temp()
            out.append(TACInstr("assign", json.dumps(expr.value, ensure_ascii=False), "", temp))
            return temp
        if isinstance(expr, VarExpr):
            return expr.name
        if isinstance(expr, ArrayAccessExpr):
            idx = self._gen_expr(expr.index, out)
            temp = self._new_temp()
            out.append(TACInstr("array_get", idx, expr.name, temp))
            return temp
        if isinstance(expr, CallExpr):
            if expr.name == "getint" and len(expr.args) == 2:
                line = self._gen_expr(expr.args[0], out)
                idx = expr.args[1]
                idx_name = idx.name if isinstance(idx, VarExpr) else self._gen_expr(idx, out)
                temp = self._new_temp()
                bound = self.getint_bound_stack[-1] if self.getint_bound_stack else None
                if bound and isinstance(idx, VarExpr) and idx.name == bound[0]:
                    out.append(TACInstr("getint_checked", line, f"{idx.name}|{bound[1]}", temp))
                else:
                    out.append(TACInstr("call", "getint", f"{line},{idx_name}", temp))
                return temp
            args = ",".join(self._gen_expr(a, out) for a in expr.args)
            temp = self._new_temp()
            out.append(TACInstr("call", expr.name, args, temp))
            return temp
        if isinstance(expr, UnaryExpr):
            operand = self._gen_expr(expr.operand, out)
            temp = self._new_temp()
            if expr.op == "!":
                out.append(TACInstr("not", operand, "", temp))
            else:
                out.append(TACInstr("uminus", operand, "", temp))
            return temp
        if isinstance(expr, BinaryExpr):
            left = self._gen_expr(expr.left, out)
            right = self._gen_expr(expr.right, out)
            temp = self._new_temp()
            out.append(TACInstr(expr.op, left, right, temp))
            return temp
        if isinstance(expr, RelExpr):
            return self._gen_condition(expr, out)
        raise ValueError(f"未知表达式: {type(expr)}")
