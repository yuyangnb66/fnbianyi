"""语义分析 — 符号表、类型检查、函数与数组支持。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

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
    InputStmt,
    IntLit,
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
from .errors import CompileDiagnostic, Severity, Stage, diagnostic


@dataclass
class Symbol:
    name: str
    type_name: str
    declared_line: int
    is_array: bool = False
    array_size: int = 0
    used: bool = False


@dataclass
class FuncSymbol:
    name: str
    return_type: str
    params: List[Tuple[str, str]]
    line: int


@dataclass
class Scope:
    symbols: Dict[str, Symbol] = field(default_factory=dict)
    parent: Optional["Scope"] = None

    def define(self, sym: Symbol) -> Optional[CompileDiagnostic]:
        if sym.name in self.symbols:
            old = self.symbols[sym.name]
            return diagnostic(
                Stage.SEMANTIC,
                f"变量 '{sym.name}' 重复定义（首次定义于 L{old.declared_line}）",
                line=sym.declared_line,
                code="E301",
            )
        self.symbols[sym.name] = sym
        return None

    def lookup(self, name: str) -> Optional[Symbol]:
        if name in self.symbols:
            return self.symbols[name]
        if self.parent:
            return self.parent.lookup(name)
        return None

    def all_symbols(self) -> List[Symbol]:
        result = list(self.symbols.values())
        if self.parent:
            result.extend(self.parent.all_symbols())
        return result


@dataclass
class SemanticResult:
    scope: Optional[Scope] = None
    functions: Dict[str, FuncSymbol] = field(default_factory=dict)
    errors: List[CompileDiagnostic] = field(default_factory=list)
    warnings: List[CompileDiagnostic] = field(default_factory=list)


class SemanticAnalyzer:
    NUMERIC = {"int", "float"}
    LOGIC = {"int"}

    def __init__(self):
        self.global_scope = Scope()
        self.current_scope = self.global_scope
        self.functions: Dict[str, FuncSymbol] = {}
        self.current_function: Optional[FuncSymbol] = None
        self.errors: List[CompileDiagnostic] = []
        self.warnings: List[CompileDiagnostic] = []
        self.loop_depth = 0
        self.has_return = False

    def analyze(self, program: Program) -> SemanticResult:
        for fn in program.functions:
            self._analyze_function(fn)
        for stmt in program.statements:
            self._analyze_stmt(stmt)
        self._check_unused_globals()
        return SemanticResult(
            scope=self.global_scope,
            functions=self.functions,
            errors=list(self.errors),
            warnings=list(self.warnings),
        )

    def _err(self, message: str, line: int = 0, code: str = "E300") -> None:
        self.errors.append(diagnostic(Stage.SEMANTIC, message, line=line, code=code))

    def _warn(self, message: str, line: int = 0, code: str = "W300") -> None:
        self.warnings.append(
            diagnostic(Stage.SEMANTIC, message, line=line, severity=Severity.WARNING, code=code)
        )

    def _analyze_function(self, fn: FuncDecl) -> None:
        if fn.name in self.functions:
            self._err(f"函数 '{fn.name}' 重复定义", fn.line, "E310")
            return
        param_names: Set[str] = set()
        for ptype, pname in fn.params:
            if pname in param_names:
                self._err(f"函数 '{fn.name}' 参数 '{pname}' 重复", fn.line, "E311")
            param_names.add(pname)
        fs = FuncSymbol(fn.name, fn.return_type, list(fn.params), fn.line)
        self.functions[fn.name] = fs
        self.current_function = fs
        self.has_return = False
        self._push_scope()
        for ptype, pname in fn.params:
            dup = self.current_scope.define(Symbol(pname, ptype, fn.line))
            if dup:
                self.errors.append(dup)
        for stmt in fn.body.statements:
            self._analyze_stmt(stmt)
        self._pop_scope()
        if fn.return_type != "void" and not self.has_return:
            self._warn(f"函数 '{fn.name}' 可能缺少 return 语句", fn.line, "W310")
        self.current_function = None

    def _push_scope(self) -> None:
        self.current_scope = Scope(parent=self.current_scope)

    def _pop_scope(self) -> None:
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent

    def _analyze_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, DeclStmt):
            sym = Symbol(
                stmt.name, stmt.type_name, stmt.line,
                is_array=stmt.array_size is not None,
                array_size=stmt.array_size or 0,
            )
            if stmt.array_size is not None and stmt.array_size <= 0:
                self._err(f"数组 '{stmt.name}' 大小必须为正整数", stmt.line, "E312")
            if stmt.type_name == "string" and stmt.array_size:
                self._err("string 类型不支持数组声明", stmt.line, "E313")
            dup = self.current_scope.define(sym)
            if dup:
                self.errors.append(dup)
        elif isinstance(stmt, AssignStmt):
            sym = self.current_scope.lookup(stmt.name)
            if not sym:
                self._err(f"未声明的变量 '{stmt.name}'", stmt.line, "E303")
            else:
                sym.used = True
                if stmt.index:
                    if not sym.is_array:
                        self._err(f"'{stmt.name}' 不是数组，不能使用下标访问", stmt.line, "E314")
                    self._check_expr(stmt.index, stmt.line)
                val_type = self._check_expr(stmt.value, stmt.line)
                if sym and not stmt.index and val_type != "unknown":
                    if not self._compatible(sym.type_name, val_type):
                        self._err(
                            f"不能将 {val_type} 赋给 {sym.type_name} 变量 '{stmt.name}'",
                            stmt.line, "E304",
                        )
                if sym and stmt.index and val_type != "unknown":
                    if not self._compatible(sym.type_name, val_type):
                        self._err(f"数组元素类型不匹配", stmt.line, "E315")
        elif isinstance(stmt, IfStmt):
            self._check_condition(stmt.condition, stmt.line)
            if not stmt.then_block.statements:
                self._warn("if 分支代码块为空", stmt.line, "W302")
            self._analyze_block(stmt.then_block)
            if stmt.else_block:
                self._analyze_block(stmt.else_block)
        elif isinstance(stmt, WhileStmt):
            self._check_condition(stmt.condition, stmt.line)
            self.loop_depth += 1
            self._analyze_block(stmt.body)
            self.loop_depth -= 1
        elif isinstance(stmt, ForStmt):
            if stmt.init:
                self._analyze_stmt(stmt.init)
            self._check_condition(stmt.condition, stmt.line)
            self.loop_depth += 1
            self._analyze_block(stmt.body)
            self.loop_depth -= 1
            if stmt.update:
                self._analyze_stmt(stmt.update)
        elif isinstance(stmt, ReturnStmt):
            if not self.current_function:
                self._err("return 只能出现在函数内部", stmt.line, "E316")
            else:
                self.has_return = True
                if stmt.value:
                    rt = self._check_expr(stmt.value, stmt.line)
                    if rt != "unknown" and not self._compatible(self.current_function.return_type, rt):
                        self._err(
                            f"返回值类型 {rt} 与函数返回类型 {self.current_function.return_type} 不匹配",
                            stmt.line, "E317",
                        )
                elif self.current_function.return_type != "void":
                    self._err("函数需要返回表达式", stmt.line, "E318")
        elif isinstance(stmt, BreakStmt):
            if self.loop_depth == 0:
                self._err("break 只能出现在循环内部", stmt.line, "E319")
        elif isinstance(stmt, ContinueStmt):
            if self.loop_depth == 0:
                self._err("continue 只能出现在循环内部", stmt.line, "E320")
        elif isinstance(stmt, PrintStmt):
            for part in stmt.values:
                self._check_expr(part, stmt.line)
        elif isinstance(stmt, InputStmt):
            stmt.type_names = []
            for vname in stmt.names:
                sym = self.current_scope.lookup(vname)
                if not sym:
                    self._err(f"input 目标变量 '{vname}' 未声明", stmt.line, "E327")
                else:
                    sym.used = True
                    stmt.type_names.append(sym.type_name)
            if stmt.prompt:
                self._check_expr(stmt.prompt, stmt.line)
        elif isinstance(stmt, WriteStmt):
            pt = self._check_expr(stmt.path, stmt.line)
            if pt not in ("string", "unknown"):
                self._err("write 的文件路径应为 string", stmt.line, "E328")
            self._check_expr(stmt.value, stmt.line)
        elif isinstance(stmt, Block):
            self._analyze_block(stmt)

    def _analyze_block(self, block: Block) -> None:
        self._push_scope()
        for s in block.statements:
            self._analyze_stmt(s)
        self._pop_scope()

    def _check_condition(self, expr: Expr, line: int) -> None:
        t = self._check_expr(expr, line)
        if isinstance(expr, RelExpr):
            return
        if isinstance(expr, BinaryExpr) and expr.op in ("&&", "||"):
            return
        if t in self.NUMERIC or t in self.LOGIC:
            return
        if t != "unknown":
            self._err("条件表达式类型无效", line, "E305")

    def _check_expr(self, expr: Expr, default_line: int = 0) -> str:
        if isinstance(expr, IntLit):
            return "int"
        if isinstance(expr, FloatLit):
            return "float"
        if isinstance(expr, StringLit):
            return "string"
        if isinstance(expr, CallExpr):
            if expr.name == "len":
                if len(expr.args) != 1:
                    self._err("len() 需要 1 个参数", default_line, "E329")
                    return "int"
                at = self._check_expr(expr.args[0], default_line)
                if isinstance(expr.args[0], ArrayAccessExpr):
                    self._err("len 的参数应为变量名", default_line, "E330")
                elif isinstance(expr.args[0], VarExpr):
                    sym = self.current_scope.lookup(expr.args[0].name)
                    if sym and not sym.is_array and sym.type_name != "string":
                        self._err("len 仅支持 string 或数组", default_line, "E331")
                expr.type_name = "int"
                return "int"
            if expr.name == "getint":
                if len(expr.args) != 2:
                    self._err("getint() 需要 2 个参数: getint(行字符串, 第几个数)", default_line, "E332")
                    return "int"
                lt = self._check_expr(expr.args[0], default_line)
                if lt != "string" and lt != "unknown":
                    self._err("getint 第 1 个参数应为 string", default_line, "E333")
                rt = self._check_expr(expr.args[1], default_line)
                if rt not in self.NUMERIC and rt != "unknown":
                    self._err("getint 第 2 个参数应为整数下标", default_line, "E334")
                expr.type_name = "int"
                return "int"
            fn = self.functions.get(expr.name)
            if not fn:
                self._err(f"未定义的函数 '{expr.name}'", default_line, "E321")
                return "unknown"
            if len(expr.args) != len(fn.params):
                self._err(
                    f"函数 '{expr.name}' 期望 {len(fn.params)} 个参数，实际 {len(expr.args)} 个",
                    default_line, "E322",
                )
            for i, (arg, (pt, _)) in enumerate(zip(expr.args, fn.params)):
                at = self._check_expr(arg, default_line)
                if at != "unknown" and not self._compatible(pt, at):
                    self._err(
                        f"函数 '{expr.name}' 第 {i+1} 个参数类型不匹配（期望 {pt}，实际 {at}）",
                        default_line, "E323",
                    )
            expr.type_name = fn.return_type
            return fn.return_type
        if isinstance(expr, ArrayAccessExpr):
            sym = self.current_scope.lookup(expr.name)
            if not sym:
                self._err(f"未声明的变量 '{expr.name}'", default_line, "E303")
                return "unknown"
            if sym.is_array:
                sym.used = True
                self._check_expr(expr.index, default_line)
                expr.type_name = sym.type_name
                return sym.type_name
            if sym.type_name == "string":
                sym.used = True
                self._check_expr(expr.index, default_line)
                expr.type_name = "string"
                return "string"
            self._err(f"'{expr.name}' 不支持下标访问", default_line, "E314")
            return "unknown"
        if isinstance(expr, VarExpr):
            sym = self.current_scope.lookup(expr.name)
            if not sym:
                self._err(f"未声明的变量 '{expr.name}'", default_line, "E303")
                return "unknown"
            if sym.is_array:
                self._err(f"数组 '{expr.name}' 需要下标才能使用", default_line, "E324")
            sym.used = True
            expr.type_name = sym.type_name
            return sym.type_name
        if isinstance(expr, UnaryExpr):
            if expr.op == "!":
                self._check_expr(expr.operand, default_line)
                expr.type_name = "int"
                return "int"
            t = self._check_expr(expr.operand, default_line)
            if expr.op == "-" and t in self.NUMERIC:
                expr.type_name = t
                return t
            if t != "unknown":
                self._err("一元 '-' 只能用于数值类型", default_line, "E306")
            return "unknown"
        if isinstance(expr, BinaryExpr):
            if expr.op in ("&&", "||"):
                lt = self._check_expr(expr.left, default_line)
                rt = self._check_expr(expr.right, default_line)
                if lt not in self.NUMERIC | self.LOGIC and lt != "unknown":
                    self._warn(f"逻辑运算 '{expr.op}' 左操作数可能非布尔/数值", default_line, "W311")
                if rt not in self.NUMERIC | self.LOGIC and rt != "unknown":
                    self._warn(f"逻辑运算 '{expr.op}' 右操作数可能非布尔/数值", default_line, "W312")
                expr.type_name = "int"
                return "int"
            lt = self._check_expr(expr.left, default_line)
            rt = self._check_expr(expr.right, default_line)
            if expr.op == "/" and isinstance(expr.right, IntLit) and expr.right.value == 0:
                self._err("编译期检测到除以零", default_line, "E307")
            if expr.op == "/" and isinstance(expr.right, FloatLit) and expr.right.value == 0.0:
                self._err("编译期检测到除以零", default_line, "E307")
            if lt not in self.NUMERIC or rt not in self.NUMERIC:
                if lt != "unknown" and rt != "unknown":
                    if expr.op == "+" and lt == "string" and rt == "string":
                        expr.type_name = "string"
                        return "string"
                    if lt == "string" or rt == "string":
                        self._err(f"字符串不能使用算术运算 '{expr.op}'", default_line, "E325")
                    else:
                        self._err(
                            f"算术运算 '{expr.op}' 的操作数必须是数值类型（当前 {lt} 与 {rt}）",
                            default_line, "E308",
                        )
                return "unknown"
            result = "float" if "float" in (lt, rt) else "int"
            expr.type_name = result
            return result
        if isinstance(expr, RelExpr):
            lt = self._check_expr(expr.left, default_line)
            rt = self._check_expr(expr.right, default_line)
            if lt == "string" or rt == "string":
                if expr.op not in ("==", "!="):
                    self._err("字符串只能使用 == 或 != 比较", default_line, "E326")
            elif lt not in self.NUMERIC or rt not in self.NUMERIC:
                if lt != "unknown" and rt != "unknown":
                    self._err(f"关系运算 '{expr.op}' 的操作数必须是数值类型", default_line, "E309")
            return "int"
        return "unknown"

    def _check_unused_globals(self) -> None:
        seen: Set[str] = set()
        for sym in self.global_scope.all_symbols():
            if sym.name in seen:
                continue
            seen.add(sym.name)
            if not sym.used:
                self._warn(f"变量 '{sym.name}' 已声明但从未使用", sym.declared_line, "W305")

    @staticmethod
    def _compatible(declared: str, assigned: str) -> bool:
        if declared == assigned:
            return True
        if declared == "float" and assigned == "int":
            return True
        return False
