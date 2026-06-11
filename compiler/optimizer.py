"""中间代码优化 — 常量折叠、复制传播、死代码消除（简单实现）。"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from .tac import TACInstr, TACProgram


class Optimizer:
    def optimize(self, program: TACProgram) -> TACProgram:
        instrs = list(program.instructions)
        instrs = self._constant_fold(instrs)
        instrs = self._copy_propagation(instrs)
        instrs = self._dead_code_elimination(instrs)
        return TACProgram(instrs)

    def _is_literal(self, s: str) -> bool:
        if not s:
            return False
        try:
            float(s)
            return True
        except ValueError:
            return False

    def _eval_binary(self, op: str, a: str, b: str) -> Optional[str]:
        try:
            fa, fb = float(a), float(b)
            ia, ib = float(a).is_integer() and float(b).is_integer(), True
            ia, ib = int(float(a)), int(float(b))
            ops = {
                "+": ia + ib if float(a).is_integer() and float(b).is_integer() else fa + fb,
                "-": ia - ib if float(a).is_integer() and float(b).is_integer() else fa - fb,
                "*": ia * ib if float(a).is_integer() and float(b).is_integer() else fa * fb,
                "/": fa / fb if fb != 0 else None,
                "==": int(fa == fb),
                "!=": int(fa != fb),
                "<": int(fa < fb),
                "<=": int(fa <= fb),
                ">": int(fa > fb),
                ">=": int(fa >= fb),
            }
            if op not in ops or ops[op] is None:
                return None
            val = ops[op]
            if isinstance(val, float) and val == int(val):
                return str(int(val))
            return str(val)
        except (ValueError, ZeroDivisionError):
            return None

    def _constant_fold(self, instrs: List[TACInstr]) -> List[TACInstr]:
        result: List[TACInstr] = []
        for ins in instrs:
            if ins.op in ("+", "-", "*", "/", "==", "!=", "<", "<=", ">", ">="):
                if self._is_literal(ins.arg1) and self._is_literal(ins.arg2):
                    folded = self._eval_binary(ins.op, ins.arg1, ins.arg2)
                    if folded is not None:
                        result.append(TACInstr("assign", folded, "", ins.result))
                        continue
            if ins.op == "uminus" and self._is_literal(ins.arg1):
                result.append(TACInstr("assign", str(-float(ins.arg1)).rstrip("0").rstrip("."), "", ins.result))
                continue
            result.append(ins)
        return result

    def _copy_propagation(self, instrs: List[TACInstr]) -> List[TACInstr]:
        copies: Dict[str, str] = {}
        result: List[TACInstr] = []

        def resolve(v: str) -> str:
            seen: Set[str] = set()
            while v in copies and v not in seen:
                seen.add(v)
                v = copies[v]
            return v

        for ins in instrs:
            if ins.op == "assign" and ins.arg1 and not self._is_literal(ins.arg1):
                if re.match(r"^t\d+$", ins.result) and re.match(r"^t\d+$", ins.arg1):
                    copies[ins.result] = resolve(ins.arg1)
                    result.append(ins)
                    continue
            if ins.op == "assign" and ins.arg1 and re.match(r"^[a-zA-Z_]", ins.arg1):
                arg1 = resolve(ins.arg1)
                result.append(TACInstr(ins.op, arg1, ins.arg2, ins.result))
                continue
            new_ins = TACInstr(
                ins.op,
                resolve(ins.arg1) if ins.arg1 else ins.arg1,
                resolve(ins.arg2) if ins.arg2 else ins.arg2,
                ins.result,
            )
            if ins.op in ("+", "-", "*", "/", "==", "!=", "<", "<=", ">", ">="):
                if new_ins.arg1 == new_ins.arg2 and new_ins.op in ("-", "/"):
                    pass
            result.append(new_ins)
            if ins.op != "assign" or not re.match(r"^t\d+$", ins.result or ""):
                copies.pop(ins.result, None)
        return result

    def _dead_code_elimination(self, instrs: List[TACInstr]) -> List[TACInstr]:
        used: Set[str] = set()
        for ins in reversed(instrs):
            if ins.op in ("print", "printn"):
                used.add(ins.arg1)
            elif ins.op == "ifFalse":
                used.add(ins.arg1)
            elif ins.op in ("+", "-", "*", "/", "==", "!=", "<", "<=", ">", ">="):
                used.add(ins.arg1)
                used.add(ins.arg2)
                used.add(ins.result)
            elif ins.op == "uminus":
                used.add(ins.arg1)
                used.add(ins.result)
            elif ins.op == "assign":
                if ins.result in used or not re.match(r"^t\d+$", ins.result or ""):
                    used.add(ins.arg1)
            elif ins.op == "decl":
                pass

        used_vars: Set[str] = set()
        for ins in instrs:
            if ins.op == "assign" and ins.result and not re.match(r"^t\d+$", ins.result):
                used_vars.add(ins.result)
            if ins.op in ("print", "printn"):
                used_vars.add(ins.arg1)
            if ins.op == "ifFalse":
                used_vars.add(ins.arg1)

        for ins in reversed(instrs):
            for field in (ins.arg1, ins.arg2, ins.result):
                if field and re.match(r"^[a-zA-Z_]", field):
                    used_vars.add(field)

        result: List[TACInstr] = []
        for ins in instrs:
            if ins.op == "assign" and re.match(r"^t\d+$", ins.result or ""):
                if ins.result not in used and ins.result not in used_vars:
                    continue
            result.append(ins)
        return result
