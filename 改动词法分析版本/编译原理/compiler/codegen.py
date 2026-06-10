"""目标代码生成 — 支持函数、数组、字符串与逻辑运算。"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Set, Union
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
from .tac import TACInstr, TACProgram


class CodeGenerator:
    def generate(self, program: Program, tac: TACProgram) -> str:
        lines = [
            "# MiniLang 编译器生成的目标代码 (Python)",
            "from compiler.runtime import ml_input as _ml_input, ml_write as _ml_write, "
            "ml_split_line as _ml_split_line, ml_getint as _ml_getint",
            "_vars = {}",
            "",
        ]
        for fn in program.functions:
            lines.extend(self._gen_function_ast(fn))
            lines.append("")
        lines.append("def _run():")
        main_blocks, order = self._split_blocks(tac.instructions)
        lines.extend(self._gen_blocks(main_blocks, order, indent=1))
        lines.extend([
            "    _dispatch = {",
        ])
        for label in order:
            lines.append(f"        {label!r}: {label},")
        lines.extend([
            "    }",
            "    pc = '_entry'",
            "    while pc is not None:",
            "        fn = _dispatch[pc]",
            "        pc = fn()",
            "",
            "_run()",
        ])
        return "\n".join(lines) + "\n"

    def _gen_function_ast(self, fn: FuncDecl) -> List[str]:
        params = {p[1] for p in fn.params}
        locals_set = self._collect_locals(fn.body) | params
        lines = [f"def _ml_{fn.name}({', '.join(p[1] for p in fn.params)}):"]
        body = self._gen_block_ast(fn.body, indent=1, params=params, locals_set=locals_set)
        if not body:
            lines.append("    pass")
        else:
            lines.extend(body)
        return lines

    @staticmethod
    def _collect_locals(block: Block) -> Set[str]:
        names: Set[str] = set()
        for stmt in block.statements:
            if isinstance(stmt, DeclStmt):
                names.add(stmt.name)
            elif isinstance(stmt, Block):
                names |= CodeGenerator._collect_locals(stmt)
            elif isinstance(stmt, IfStmt):
                names |= CodeGenerator._collect_locals(stmt.then_block)
                if stmt.else_block:
                    names |= CodeGenerator._collect_locals(stmt.else_block)
            elif isinstance(stmt, WhileStmt):
                names |= CodeGenerator._collect_locals(stmt.body)
            elif isinstance(stmt, ForStmt):
                if stmt.init and isinstance(stmt.init, AssignStmt):
                    pass
                names |= CodeGenerator._collect_locals(stmt.body)
        return names

    def _gen_block_ast(
        self, block: Block, indent: int, params: Set[str],
        locals_set: Optional[Set[str]] = None, loop: Optional[tuple] = None,
    ) -> List[str]:
        loc = locals_set or params
        lines: List[str] = []
        for stmt in block.statements:
            lines.extend(self._gen_stmt_ast(stmt, indent, params, loc, loop))
        return lines

    def _gen_stmt_ast(
        self, stmt: Stmt, indent: int, params: Set[str],
        locals_set: Set[str], loop: Optional[tuple] = None,
    ) -> List[str]:
        pad = " " * (4 * indent)
        if isinstance(stmt, DeclStmt):
            if stmt.array_size:
                d = "0.0" if stmt.type_name == "float" else "0"
                return [f"{pad}{stmt.name} = [{d}] * {stmt.array_size}"]
            return [f"{pad}{stmt.name} = {self._default(stmt.type_name)}"]
        if isinstance(stmt, AssignStmt):
            val = self._gen_expr_ast(stmt.value, params, locals_set)
            if stmt.index:
                idx = self._gen_expr_ast(stmt.index, params, locals_set)
                base = self._var_ref(stmt.name, params, locals_set)
                return [f"{pad}{base}[int({idx})] = {val}"]
            return [f"{pad}{self._var_ref(stmt.name, params, locals_set)} = {val}"]
        if isinstance(stmt, PrintStmt):
            parts = ", ".join(
                self._gen_expr_ast(v, params, locals_set) for v in stmt.values
            )
            if stmt.newline:
                return [f"{pad}print({parts})"]
            return [f"{pad}print({parts}, end=\"\")"]
        if isinstance(stmt, InputStmt):
            prompt = self._gen_expr_ast(stmt.prompt, params, locals_set) if stmt.prompt else '""'
            pad = " " * (4 * indent)
            refs = [self._var_ref(n, params, locals_set) for n in stmt.names]
            types = stmt.type_names or ["int"] * len(stmt.names)
            return [
                f"{pad}{line}"
                for line in self._gen_multi_input_lines(refs, types, prompt)
            ]
        if isinstance(stmt, WriteStmt):
            path = self._gen_expr_ast(stmt.path, params, locals_set)
            val = self._gen_expr_ast(stmt.value, params, locals_set)
            return [f"{pad}_ml_write(str({path}), str({val}))"]
        if isinstance(stmt, ReturnStmt):
            if stmt.value:
                return [f"{pad}return {self._gen_expr_ast(stmt.value, params, locals_set)}"]
            return [f"{pad}return 0"]
        if isinstance(stmt, BreakStmt):
            return [f"{pad}break"] if loop else []
        if isinstance(stmt, ContinueStmt):
            return [f"{pad}continue"] if loop else []
        if isinstance(stmt, IfStmt):
            cond = self._gen_expr_ast(stmt.condition, params, locals_set)
            lines = [f"{pad}if {cond}:"]
            then_b = self._gen_block_ast(stmt.then_block, indent + 1, params, locals_set, loop)
            lines.extend(then_b or [f"{' ' * 4 * (indent + 1)}pass"])
            if stmt.else_block:
                lines.append(f"{pad}else:")
                else_b = self._gen_block_ast(stmt.else_block, indent + 1, params, locals_set, loop)
                lines.extend(else_b or [f"{' ' * 4 * (indent + 1)}pass"])
            return lines
        if isinstance(stmt, WhileStmt):
            cond = self._gen_expr_ast(stmt.condition, params, locals_set)
            lines = [f"{pad}while {cond}:"]
            inner = self._gen_block_ast(stmt.body, indent + 1, params, locals_set, loop=("break", "continue"))
            lines.extend(inner or [f"{' ' * 4 * (indent + 1)}pass"])
            return lines
        if isinstance(stmt, ForStmt):
            lines: List[str] = []
            if stmt.init:
                lines.extend(self._gen_stmt_ast(stmt.init, indent, params, locals_set, loop))
            cond = self._gen_expr_ast(stmt.condition, params, locals_set)
            lines.append(f"{pad}while {cond}:")
            inner = self._gen_block_ast(stmt.body, indent + 1, params, locals_set, loop=("break", "continue"))
            lines.extend(inner or [f"{' ' * 4 * (indent + 1)}pass"])
            if stmt.update:
                upd = self._gen_stmt_ast(stmt.update, indent + 1, params, locals_set, loop=("break", "continue"))
                lines.extend(upd)
            return lines
        if isinstance(stmt, Block):
            return self._gen_block_ast(stmt, indent, params, locals_set, loop)
        return []

    @staticmethod
    def _var_ref(name: str, params: Set[str], locals_set: Set[str]) -> str:
        if name in params or name in locals_set:
            return name
        return f"_vars[{name!r}]"

    def _gen_expr_ast(self, expr: Expr, params: Set[str], locals_set: Set[str]) -> str:
        if isinstance(expr, IntLit):
            return str(expr.value)
        if isinstance(expr, FloatLit):
            return str(expr.value)
        if isinstance(expr, StringLit):
            return json.dumps(expr.value, ensure_ascii=False)
        if isinstance(expr, VarExpr):
            return self._var_ref(expr.name, params, locals_set)
        if isinstance(expr, ArrayAccessExpr):
            base = self._var_ref(expr.name, params, locals_set)
            idx = self._gen_expr_ast(expr.index, params, locals_set)
            return f"{base}[int({idx})]"
        if isinstance(expr, CallExpr):
            if expr.name == "len":
                args = ", ".join(self._gen_expr_ast(a, params, locals_set) for a in expr.args)
                return f"len({args})"
            if expr.name == "getint":
                line = self._gen_expr_ast(expr.args[0], params, locals_set)
                idx = self._gen_expr_ast(expr.args[1], params, locals_set)
                return f"_ml_getint(str({line}), int({idx}))"
            args = ", ".join(self._gen_expr_ast(a, params, locals_set) for a in expr.args)
            return f"_ml_{expr.name}({args})"
        if isinstance(expr, UnaryExpr):
            if expr.op == "!":
                return f"(not {self._gen_expr_ast(expr.operand, params, locals_set)})"
            return f"(-{self._gen_expr_ast(expr.operand, params, locals_set)})"
        if isinstance(expr, BinaryExpr):
            left = self._gen_expr_ast(expr.left, params, locals_set)
            right = self._gen_expr_ast(expr.right, params, locals_set)
            if expr.op == "&&":
                return f"({left} and {right})"
            if expr.op == "||":
                return f"({left} or {right})"
            if expr.op == "+" and isinstance(expr.left, (VarExpr, StringLit, ArrayAccessExpr)):
                lt = getattr(expr.left, "type_name", "")
                rt = getattr(expr.right, "type_name", "")
                if lt == "string" or rt == "string":
                    return f"str({left}) + str({right})"
            return f"({left} {expr.op} {right})"
        if isinstance(expr, RelExpr):
            left = self._gen_expr_ast(expr.left, params, locals_set)
            right = self._gen_expr_ast(expr.right, params, locals_set)
            return f"({left} {expr.op} {right})"
        return "0"

    def _gen_blocks(
        self, blocks: Dict[str, List[TACInstr]], order: List[str], indent: int
    ) -> List[str]:
        pad = " " * (4 * indent)
        lines: List[str] = []
        for idx, label in enumerate(order):
            instrs = blocks[label]
            fallthrough = order[idx + 1] if idx + 1 < len(order) else None
            lines.append(f"{pad}def {label}():")
            emitted: List[str] = []
            for ins in instrs:
                emitted.extend(f"{pad}    {s}" for s in self._emit_main(ins))
            lines.extend(emitted)
            ends_with_jump = emitted and (
                emitted[-1].strip().startswith("return ")
                or emitted[-1].strip().startswith("raise ")
            )
            if fallthrough and not ends_with_jump:
                lines.append(f"{pad}    return {fallthrough!r}")
            else:
                lines.append(f"{pad}    return None")
            lines.append("")
        return lines

    def _split_blocks(self, instrs: List[TACInstr]) -> tuple[Dict[str, List[TACInstr]], List[str]]:
        labels: Set[str] = {"_entry"}
        order: List[str] = ["_entry"]
        for ins in instrs:
            if ins.op == "label":
                labels.add(ins.result)
                if ins.result not in order:
                    order.append(ins.result)
            elif ins.op in ("goto", "ifFalse"):
                labels.add(ins.result)

        blocks: Dict[str, List[TACInstr]] = {lb: [] for lb in labels}
        current = "_entry"
        for ins in instrs:
            if ins.op == "label":
                current = ins.result
                if current not in blocks:
                    blocks[current] = []
                if current not in order:
                    order.append(current)
            else:
                blocks.setdefault(current, []).append(ins)
        for lb in labels:
            blocks.setdefault(lb, [])
        return blocks, order

    def _emit_main(self, ins: TACInstr) -> List[str]:
        if ins.op == "decl":
            return [f"_vars[{ins.result!r}] = {self._default(ins.arg1)}"]
        if ins.op == "decl_array":
            elem = "0.0" if ins.arg2 == "float" else "0"
            return [f"_vars[{ins.result!r}] = [{elem}] * {ins.arg1}"]
        if ins.op == "assign":
            if ins.arg1.startswith(('"', "'")):
                return [f"_vars[{ins.result!r}] = {ins.arg1}"]
            return [f"_vars[{ins.result!r}] = {self._ref(ins.arg1)}"]
        if ins.op == "array_set":
            return [f"_vars[{ins.result!r}][int({self._ref(ins.arg1)})] = {self._ref(ins.arg2)}"]
        if ins.op == "array_get":
            return [f"_vars[{ins.result!r}] = _vars[{ins.arg2!r}][int({self._ref(ins.arg1)})]"]
        if ins.op == "call":
            if ins.arg1 == "len":
                arg = ins.arg2.split(",")[0].strip() if ins.arg2 else ""
                return [f"_vars[{ins.result!r}] = len({self._ref(arg)})"]
            if ins.arg1 == "getint":
                args = ins.arg2.split(",") if ins.arg2 else []
                line = self._ref(args[0].strip()) if args else '""'
                idx = self._ref(args[1].strip()) if len(args) > 1 else "0"
                return [f"_vars[{ins.result!r}] = _ml_getint(str({line}), int({idx}))"]
            args = ins.arg2.split(",") if ins.arg2 else []
            call_args = ", ".join(self._ref(a.strip()) for a in args if a.strip())
            return [f"_vars[{ins.result!r}] = _ml_{ins.arg1}({call_args})"]
        if ins.op in ("+", "-", "*", "/"):
            return [f"_vars[{ins.result!r}] = {self._ref(ins.arg1)} {ins.op} {self._ref(ins.arg2)}"]
        if ins.op in ("==", "!=", "<", "<=", ">", ">="):
            return [f"_vars[{ins.result!r}] = int({self._ref(ins.arg1)} {ins.op} {self._ref(ins.arg2)})"]
        if ins.op in ("&&", "||"):
            py_op = "and" if ins.op == "&&" else "or"
            return [f"_vars[{ins.result!r}] = int(bool({self._ref(ins.arg1)}) {py_op} bool({self._ref(ins.arg2)}))"]
        if ins.op == "uminus":
            return [f"_vars[{ins.result!r}] = -{self._ref(ins.arg1)}"]
        if ins.op == "not":
            return [f"_vars[{ins.result!r}] = int(not {self._ref(ins.arg1)})"]
        if ins.op in ("print", "printn"):
            parts = ", ".join(
                self._ref(p.strip()) for p in ins.arg1.split(",") if p.strip()
            )
            if ins.op == "printn":
                return [f"print({parts}, end=\"\")"]
            return [f"print({parts})"]
        if ins.op == "input":
            names = [n.strip() for n in ins.result.split(",") if n.strip()]
            types = [t.strip() for t in (ins.arg2 or "int").split(",")]
            while len(types) < len(names):
                types.append("int")
            refs = [f"_vars[{n!r}]" for n in names]
            return self._gen_multi_input_lines(refs, types, self._ref(ins.arg1))
        if ins.op == "call" and ins.arg1 == "getint":
            args = ins.arg2.split(",") if ins.arg2 else []
            line = self._ref(args[0].strip()) if args else '""'
            idx = self._ref(args[1].strip()) if len(args) > 1 else "0"
            return [f"_vars[{ins.result!r}] = _ml_getint(str({line}), int({idx}))"]
        if ins.op == "write":
            return [f"_ml_write(str({self._ref(ins.arg1)}), str({self._ref(ins.arg2)}))"]
        if ins.op == "goto":
            return [f"return {ins.result!r}"]
        if ins.op == "ifFalse":
            return [
                f"if not {self._ref(ins.arg1)}:",
                f"    return {ins.result!r}",
            ]
        return []

    @staticmethod
    def _gen_input_lines(var: str, prompt_expr: str, type_name: str) -> List[str]:
        return CodeGenerator._gen_multi_input_lines([var], [type_name], prompt_expr)

    @staticmethod
    def _gen_multi_input_lines(
        vars: List[str], type_names: List[str], prompt_expr: str
    ) -> List[str]:
        lines = [f"_raw = _ml_input(str({prompt_expr})).strip()"]
        if len(vars) == 1:
            return lines + CodeGenerator._assign_from_part(vars[0], "_raw", type_names[0])
        lines.append("_parts = _ml_split_line(_raw)")
        for i, (var, tn) in enumerate(zip(vars, type_names)):
            lines.extend(CodeGenerator._assign_from_part(var, f"_parts[{i}] if {i} < len(_parts) else ''", tn))
        return lines

    @staticmethod
    def _assign_from_part(var: str, part_expr: str, type_name: str) -> List[str]:
        if type_name == "string":
            return [f"{var} = str({part_expr})"]
        if type_name == "float":
            return [
                f"try:",
                f"    {var} = float({part_expr})",
                f"except ValueError:",
                f"    {var} = 0.0",
            ]
        return [
            f"try:",
            f"    {var} = int({part_expr})",
            f"except ValueError:",
            f"    try:",
            f"        {var} = int(float({part_expr}))",
            f"    except ValueError:",
            f"        {var} = 0",
        ]

    @staticmethod
    def _default(type_name: str) -> str:
        if type_name == "float":
            return "0.0"
        if type_name == "string":
            return '""'
        return "0"

    @staticmethod
    def _ref(operand: str) -> str:
        if not operand:
            return "0"
        if re.match(r"^-?\d+(\.\d+)?$", operand):
            return operand
        if operand.startswith('"') and operand.endswith('"'):
            return operand
        return f"_vars[{operand!r}]"


