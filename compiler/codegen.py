"""目标代码生成 — 将优化后的 TAC 翻译为可执行的 Python 代码。"""

from __future__ import annotations

import re
from typing import Dict, List, Set

from .tac import TACInstr, TACProgram


class CodeGenerator:
    def generate(self, program: TACProgram) -> str:
        blocks, order = self._split_blocks(program.instructions)
        lines: List[str] = [
            "# MiniLang 编译器生成的目标代码 (Python)",
            "_vars = {}",
            "",
            "def _run():",
        ]

        for idx, label in enumerate(order):
            instrs = blocks[label]
            fallthrough = order[idx + 1] if idx + 1 < len(order) else None
            lines.append(f"    def {label}():")
            emitted: List[str] = []
            for ins in instrs:
                emitted.extend(f"        {s}" for s in self._emit(ins))
            lines.extend(emitted)
            ends_with_jump = emitted and (
                emitted[-1].strip().startswith("return ")
                or (
                    len(emitted) >= 2
                    and emitted[-2].strip().startswith("if not ")
                    and emitted[-1].strip().startswith("return ")
                )
            )
            if fallthrough and not ends_with_jump:
                lines.append(f"        return {fallthrough!r}")
            else:
                lines.append("        return None")
            lines.append("")

        lines.append("    _dispatch = {")
        for label in order:
            lines.append(f"        {label!r}: {label},")
        lines.append("    }")
        lines.append("    pc = '_entry'")
        lines.append("    while pc is not None:")
        lines.append("        fn = _dispatch[pc]")
        lines.append("        pc = fn()")
        lines.append("")
        lines.append("_run()")
        return "\n".join(lines) + "\n"

    def _split_blocks(self, instrs: List[TACInstr]) -> tuple[Dict[str, List[TACInstr]], List[str]]:
        labels: Set[str] = {"_entry"}
        order: List[str] = ["_entry"]
        for ins in instrs:
            if ins.op == "label" and ins.result not in labels:
                labels.add(ins.result)
                order.append(ins.result)
            if ins.op == "goto" and ins.result not in labels:
                labels.add(ins.result)
                order.append(ins.result)
            if ins.op == "ifFalse" and ins.result not in labels:
                labels.add(ins.result)
                order.append(ins.result)

        blocks: Dict[str, List[TACInstr]] = {lb: [] for lb in order}
        current = "_entry"
        for ins in instrs:
            if ins.op == "label":
                current = ins.result
                if current not in blocks:
                    blocks[current] = []
                    order.append(current)
            else:
                blocks.setdefault(current, []).append(ins)
        return blocks, order

    def _emit(self, ins: TACInstr) -> List[str]:
        if ins.op == "decl":
            default = "0.0" if ins.arg1 == "float" else "0"
            return [f"_vars[{ins.result!r}] = {default}"]
        if ins.op == "assign":
            return [f"_vars[{ins.result!r}] = {self._ref(ins.arg1)}"]
        if ins.op in ("+", "-", "*", "/"):
            return [
                f"_vars[{ins.result!r}] = {self._ref(ins.arg1)} {ins.op} {self._ref(ins.arg2)}"
            ]
        if ins.op in ("==", "!=", "<", "<=", ">", ">="):
            return [
                f"_vars[{ins.result!r}] = int({self._ref(ins.arg1)} {ins.op} {self._ref(ins.arg2)})"
            ]
        if ins.op == "uminus":
            return [f"_vars[{ins.result!r}] = -{self._ref(ins.arg1)}"]
        if ins.op == "print":
            return [f"print({self._ref(ins.arg1)})"]
        if ins.op == "goto":
            return [f"return {ins.result!r}"]
        if ins.op == "ifFalse":
            return [f"if not {self._ref(ins.arg1)}:", f"    return {ins.result!r}"]
        return []

    @staticmethod
    def _ref(operand: str) -> str:
        if not operand:
            return "0"
        if re.match(r"^-?\d+(\.\d+)?$", operand):
            return operand
        return f"_vars[{operand!r}]"
