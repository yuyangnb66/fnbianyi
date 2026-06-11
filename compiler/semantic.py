"""语义分析 — 符号表、类型检查、函数与数组支持。

语义分析错误统一 E3xx
E301: 变量重复定义
E302: 使用未声明的变量
E303: 赋值语句左右两侧类型不兼容
E304: 条件表达式类型不符合要求
E305: 一元负号运算符作用于非数值类型
E306: 编译阶段检测到除零运算
E307: 算术运算符操作数非数值类型
E308: 关系运算符操作数非数值类型
E309: 函数重复定义
E310: 函数参数列表存在重复参数名
E311: 数组声明大小不是正整数
E312: string 类型不支持数组形式声明
E313: 对非数组变量使用下标访问
E314: 数组元素赋值类型不匹配
E315: return 语句出现在函数外部
E316: 函数返回值类型与定义类型不匹配
E317: 非void函数缺少return返回表达式
E318: break 语句出现在循环外部
E319: continue 语句出现在循环外部
E320: 调用未定义的自定义函数
E321: 函数调用参数数量与定义不匹配
E322: 函数调用参数类型与定义不匹配
E323: 数组类型变量未使用下标直接引用
E324: 字符串类型使用算术运算符运算
E325: 字符串使用非法关系运算符（仅支持 ==、!=）
E326: input 语句目标变量未声明
E327: write 语句文件路径参数非 string 类型
E328: 内置函数 len() 传入参数数量错误
E329: 内置函数 len() 不能传入数组下标访问表达式
E330: 内置函数 len() 仅支持 string 类型或数组变量
E331: 内置函数 getint() 传入参数数量错误
E332: 内置函数 getint() 第一个参数非 string 类型
E333: 内置函数 getint() 第二个参数非数值类型

语义分析警告统一 W3xx
W301: if 语句分支代码块为空
W302: 变量已声明但全程未使用
W303: 非void类型函数可能缺少 return 语句
W304: 逻辑运算左操作数类型非常规数值/逻辑类型
W305: 逻辑运算右操作数类型非常规数值/逻辑类型
"""
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
    ExprStmt,
)
from .errors import CompileDiagnostic, Severity, Stage, diagnostic


@dataclass
class Symbol:
    name: str
    type_name: str
    declared_line: int
    declared_col: int = 0
    is_array: bool = False
    array_size: int = 0
    used: bool = False
    array_initialized: bool = False


@dataclass
class FuncSymbol:
    name: str
    return_type: str
    params: List[Tuple[str, str]]
    line: int
    col: int


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
                col=sym.declared_col,
                code="E301",
                suggestion="修改变量名，不要重复定义同名变量"
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
    # 类型系统：数值内部兼容，bool与数值严格不互通
    NUMERIC = {"int", "float"}
    LOGIC = {"int"}
    RET_NEVER = 0
    RET_MAYBE = 1
    RET_ALWAYS = 2

    def __init__(self):
        self.global_scope = Scope()
        self.current_scope = self.global_scope
        self.functions: Dict[str, FuncSymbol] = {}
        self.current_function: Optional[FuncSymbol] = None
        self.errors: List[CompileDiagnostic] = []
        self.warnings: List[CompileDiagnostic] = []
        self.loop_depth = 0

    def analyze(self, program: Program) -> SemanticResult:
        main_fns = [fn for fn in program.functions if fn.name == "main"]
        if len(main_fns) > 1:
            self._err("main 函数重复定义", main_fns[1].line, "E341")
        main_fn = main_fns[0] if main_fns else None
        for stmt in program.statements:
            if isinstance(stmt, DeclStmt):
                self._analyze_stmt(stmt)
        for fn in program.functions:
            if fn.name != "main":
                self._analyze_function(fn)
        if main_fn:
            self._analyze_main(main_fn)
        self._check_entry_point(program, main_fn)
        if not main_fn:
            for stmt in program.statements:
                if not isinstance(stmt, DeclStmt):
                    self._analyze_stmt(stmt)
        self._check_unused_globals()
        return SemanticResult(
            scope=self.global_scope,
            functions=self.functions,
            errors=list(self.errors),
            warnings=list(self.warnings),
        )

    def _check_entry_point(self, program: Program, main_fn: Optional[FuncDecl]) -> None:
        exec_stmts = [s for s in program.statements if not isinstance(s, DeclStmt)]
        if main_fn:
            if exec_stmts:
                line = exec_stmts[0].line
                self._err(
                    "程序入口代码应写在 int main() { ... } 内，顶层只能声明全局变量",
                    line,
                    "E339",
                )
            return
        if exec_stmts:
            self._warn(
                "建议使用 int main() { ... } 作为程序入口（类似 C 语言）",
                exec_stmts[0].line,
                "W315",
            )
        elif not program.statements and not program.functions:
            self._err("源程序为空", 0, "E340")
        elif not exec_stmts and not main_fn:
            self._err("缺少程序入口，请定义 int main() { ... }", 0, "E340")

    def _analyze_main(self, fn: FuncDecl) -> None:
        if fn.return_type != "int":
            self._err("main 函数必须声明为 int main()", fn.line, code="E337")
        if fn.params:
            self._err("main 函数不接受参数，请使用 int main()", fn.line, code="E338")
        self._analyze_function(fn, is_main=True)

    def _err(
        self,
        message: str,
        line: int = 0,
        col: int | str = 0,
        code: str = "E300",
        suggestion: str = "",
    ) -> None:
        if isinstance(col, str):
            code = col
            col = 0
        self.errors.append(
            diagnostic(
                Stage.SEMANTIC,
                message,
                line=line,
                col=col,
                code=code,
                suggestion=suggestion,
            )
        )

    def _warn(self, message: str, line: int, col: int, code: str = "W300", suggestion: str = "") -> None:
        self.warnings.append(
            diagnostic(
                Stage.SEMANTIC,
                message,
                line=line,
                col=col,
                severity=Severity.WARNING,
                code=code,
                suggestion=suggestion
            )
        )

    def _analyze_function(self, fn: FuncDecl, is_main: bool = False) -> None:
        if fn.name in self.functions:
            self._err(
                f"函数 '{fn.name}' 重复定义",
                fn.line,
                fn.col,
                "E309",
                "修改函数名称，避免重复定义同名函数"
            )
            return
        param_names: Set[str] = set()
        for ptype, pname in fn.params:
            if pname in param_names:
                self._err(
                    f"函数 '{fn.name}' 参数名 '{pname}' 重复",
                    fn.line,
                    fn.col,
                    "E310",
                    "修改重复的参数名，保证参数列表名称唯一"
                )
            param_names.add(pname)

        fs = FuncSymbol(fn.name, fn.return_type, list(fn.params), fn.line, fn.col)
        self.functions[fn.name] = fs
        self.current_function = fs
        self._push_scope()
        # 注册函数形参
        param_sym_list: List[Symbol] = []
        for ptype, pname in fn.params:
            sym = Symbol(pname, ptype, fn.line, fn.col)
            param_sym_list.append(sym)
            dup = self.current_scope.define(sym)
            if dup:
                self.errors.append(dup)
        self._analyze_stmt_list(fn.body.statements)
        ret_state = self._block_return_state(fn.body)
        if fn.return_type != "void":
            if ret_state == self.RET_NEVER:
                if is_main:
                    self._warn("main 函数缺少 return，将默认返回 0", fn.line, "W316")
                else:
                    self._err(f"函数 '{fn.name}' 缺少 return 语句", fn.line, "E335")
            elif ret_state == self.RET_MAYBE and not is_main:
                self._warn(
                    f"函数 '{fn.name}' 存在未覆盖 return 的分支（如 if 缺少 else）",
                    fn.line,
                    "W313",
                )
        self._pop_scope()
        self.current_function = None

    # 进入新作用域（代码块/函数）
    def _push_scope(self) -> None:
        self.current_scope = Scope(parent=self.current_scope)

    # 退出当前作用域
    def _pop_scope(self) -> None:
        if not self.current_scope.parent:
            return
        for sym in self.current_scope.symbols.values():
            if not sym.used:
                self._warn(
                    f"局部变量 '{sym.name}' 已声明但从未使用",
                    sym.declared_line,
                    sym.declared_col,
                    "W302",
                    "删除无用变量，或补充使用逻辑"
                )
            if sym.is_array and not sym.array_initialized:
                self._warn(
                    f"数组 '{sym.name}' 声明后未进行初始化赋值",
                    sym.declared_line,
                    sym.declared_col,
                    "W302",
                    "删除无用变量，或补充使用逻辑"
                )
        self.current_scope = self.current_scope.parent

    # 语句总入口
    def _analyze_stmt(self, stmt: Stmt) -> None:
        if stmt is None:
            return

        if isinstance(stmt, DeclStmt):
            sym = Symbol(
                stmt.name, stmt.type_name, stmt.line,
                declared_col=stmt.col,
                is_array=stmt.array_size is not None,
                array_size=stmt.array_size or 0,
            )
            if stmt.array_size is not None and stmt.array_size <= 0:
                self._err(f"数组 '{stmt.name}' 大小必须为正整数", stmt.line, "E312")
            dup = self.current_scope.define(sym)
            if dup:
                self.errors.append(dup)

        elif isinstance(stmt, AssignStmt):
            sym = self.current_scope.lookup(stmt.name)
            if not sym:
                if stmt.name not in self.undeclared_reported:
                    self._err(
                        f"未声明的变量 '{stmt.name}'",
                        stmt.line,
                        stmt.col,
                        "E302",
                        "使用变量前先进行变量声明"
                    )
                    self.undeclared_reported.add(stmt.name)
                return

            sym.used = True
            if stmt.index:
                if not sym.is_array:
                    self._err(
                        f"'{stmt.name}' 不是数组，不能使用下标访问",
                        stmt.line,
                        stmt.col,
                        "E313",
                        "移除下标，或将该变量声明为数组"
                    )
                idx_type = self._check_expr(stmt.index)
                if idx_type is None:
                    return
                if idx_type != "int":
                    self._err(
                        f"数组下标必须为 int 类型，当前类型为 {idx_type}",
                        stmt.line,
                        stmt.col,
                        "E307",
                        "将数组下标修改为整数类型表达式"
                    )
                if sym.is_array:
                    sym.array_initialized = True

            val_type = self._check_expr(stmt.value)
            if val_type is None:
                return

            if not stmt.index and val_type != "unknown":
                if not self._compatible(sym.type_name, val_type):
                    self._err(
                        f"不能将 {val_type} 赋给 {sym.type_name} 变量 '{stmt.name}'",
                        stmt.line,
                        stmt.col,
                        "E303",
                        "保证赋值双方数据类型兼容"
                    )
            if stmt.index and val_type != "unknown":
                if not self._compatible(sym.type_name, val_type):
                    self._err(
                        "数组元素赋值类型不匹配",
                        stmt.line,
                        stmt.col,
                        "E314",
                        "保证数组赋值内容与数组定义类型一致"
                    )

        elif isinstance(stmt, IfStmt):
            self._check_condition(stmt.condition, stmt.line)
            if not stmt.then_block.statements:
                self._warn(
                    "if 语句分支代码块为空",
                    stmt.line,
                    stmt.col,
                    "W301",
                    "为空代码块补充逻辑，或删除多余的if结构",
                )
            self._analyze_block(stmt.then_block)
            for elif_cond, elif_block in stmt.elif_blocks:
                self._check_condition(elif_cond, stmt.line)
                self._analyze_block(elif_block)
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
                if stmt.value:
                    if self.current_function.return_type == "void":
                        self._err("void 函数不能使用 return 表达式", stmt.line, "E336")
                    else:
                        rt = self._check_expr(stmt.value, stmt.line)
                        if rt != "unknown" and not self._compatible(
                            self.current_function.return_type, rt
                        ):
                            self._err(
                                f"返回值类型 {rt} 与函数返回类型 "
                                f"{self.current_function.return_type} 不匹配",
                                stmt.line,
                                "E317",
                            )
                elif self.current_function.return_type != "void":
                    self._err("非 void 函数 return 必须带返回值", stmt.line, "E318")
        elif isinstance(stmt, BreakStmt):
            if self.loop_depth == 0:
                self._err(
                    "break 语句出现在循环外部",
                    stmt.line,
                    stmt.col,
                    "E318",
                    "删除循环外的break语句，或将其移入循环中",
                )

        elif isinstance(stmt, ContinueStmt):
            if self.loop_depth == 0:
                self._err(
                    "continue 语句出现在循环外部",
                    stmt.line,
                    stmt.col,
                    "E319",
                    "删除循环外的continue语句，或将其移入循环中",
                )

        elif isinstance(stmt, PrintStmt):
            for part in stmt.values:
                p_type = self._check_expr(part)
                if p_type is None:
                    continue

        elif isinstance(stmt, InputStmt):
            stmt.type_names = []
            for vname in stmt.names:
                sym = self.current_scope.lookup(vname)
                if not sym:
                    if vname not in self.undeclared_reported:
                        self._err(
                            f"input 语句目标变量 '{vname}' 未声明",
                            stmt.line,
                            stmt.col,
                            "E326",
                            "先声明该变量，再使用input赋值"
                        )
                        self.undeclared_reported.add(vname)
                    continue
                sym.used = True
                stmt.type_names.append(sym.type_name)
            if stmt.prompt:
                p_type = self._check_expr(stmt.prompt)
                if p_type is None:
                    return

        elif isinstance(stmt, WriteStmt):
            pt = self._check_expr(stmt.path)
            if pt is None:
                return
            if pt not in ("string", "unknown"):
                self._err(
                    "write 语句文件路径参数非 string 类型",
                    stmt.line,
                    stmt.col,
                    "E327",
                    "将文件路径修改为字符串类型"
                )
            val_type = self._check_expr(stmt.value)
            if val_type is None:
                return

        elif isinstance(stmt, Block):
            self._analyze_block(stmt)

    def _analyze_stmt_list(self, statements: List[Stmt]) -> None:
        seen_return = False
        for s in statements:
            if seen_return:
                self._warn("return 之后的语句不可达", s.line, "W314")
            self._analyze_stmt(s)
            if isinstance(s, ReturnStmt):
                seen_return = True

    def _analyze_block(self, block: Block) -> None:
        self._push_scope()
        self._analyze_stmt_list(block.statements)
        self._pop_scope()

    def _block_return_state(self, block: Block) -> int:
        state = self.RET_NEVER
        for stmt in block.statements:
            if isinstance(stmt, ReturnStmt):
                return self.RET_ALWAYS
            rs = self._stmt_return_state(stmt)
            if rs == self.RET_ALWAYS:
                return self.RET_ALWAYS
            if rs == self.RET_MAYBE:
                state = self.RET_MAYBE
        return state

    def _stmt_return_state(self, stmt: Stmt) -> int:
        if isinstance(stmt, ReturnStmt):
            return self.RET_ALWAYS
        if isinstance(stmt, IfStmt):
            then_s = self._block_return_state(stmt.then_block)
            if stmt.else_block:
                else_s = self._block_return_state(stmt.else_block)
                if then_s == self.RET_ALWAYS and else_s == self.RET_ALWAYS:
                    return self.RET_ALWAYS
                if then_s != self.RET_NEVER or else_s != self.RET_NEVER:
                    return self.RET_MAYBE
                return self.RET_NEVER
            if then_s == self.RET_ALWAYS:
                return self.RET_MAYBE
            return then_s
        if isinstance(stmt, (WhileStmt, ForStmt)):
            body_s = self._block_return_state(stmt.body)
            if body_s != self.RET_NEVER:
                return self.RET_MAYBE
            return self.RET_NEVER
        if isinstance(stmt, Block):
            return self._block_return_state(stmt)
        return self.RET_NEVER

    def _check_condition(self, expr: Expr, line: int = 0) -> None:
        t = self._check_expr(expr, line or getattr(expr, "line", 0))
        if t is None:
            return
        if isinstance(expr, RelExpr):
            return
        if isinstance(expr, BinaryExpr) and expr.op in ("&&", "||"):
            return
        if t in self.NUMERIC or t in self.LOGIC:
            return
        if t != "unknown":
            self._err(
                "条件表达式类型不符合要求",
                getattr(expr, "line", line),
                getattr(expr, "col", 0),
                "E304",
                "条件表达式请使用关系运算、逻辑运算生成布尔值",
            )

    # 递归检查表达式类型
    def _check_expr(self, expr: Expr, default_line: int = 0) -> Optional[str]:
        if expr is None:
            return None
        line = getattr(expr, "line", 0) or default_line
        col = getattr(expr, "col", 0)

        if isinstance(expr, IntLit):
            return "int"
        if isinstance(expr, FloatLit):
            return "float"
        if isinstance(expr, StringLit):
            return "string"

        if isinstance(expr, CallExpr):
            if expr.name == "len":
                if len(expr.args) != 1:
                    self._err(
                        "内置函数 len() 传入参数数量错误",
                        expr.line,
                        expr.col,
                        "E328",
                        "按照规则传入1个参数给len函数"
                    )
                    return "int"
                arg0 = expr.args[0]
                if isinstance(arg0, ArrayAccessExpr):
                    self._err("len 的参数应为变量名", line, col, "E330")
                elif isinstance(arg0, VarExpr):
                    sym = self.current_scope.lookup(arg0.name)
                    if not sym:
                        self._err(f"未声明的变量 '{arg0.name}'", line, col, "E303")
                    elif not sym.is_array and sym.type_name != "string":
                        self._err("len 仅支持 string 或数组", line, col, "E331")
                    elif sym:
                        sym.used = True
                else:
                    self._check_expr(arg0, default_line)
                expr.type_name = "int"
                return "int"

            # 内置函数 getint
            if expr.name == "getint":
                if len(expr.args) != 2:
                    self._err(
                        "内置函数 getint() 传入参数数量错误",
                        expr.line,
                        expr.col,
                        "E331",
                        "getint() 需要 2 个参数: getint(行字符串, 第几个数)"
                    )
                    return "int"
                lt = self._check_expr(expr.args[0])
                if lt is None:
                    return None
                if lt != "string" and lt != "unknown":
                    self._err(
                        "内置函数 getint() 第一个参数非 string 类型",
                        expr.line,
                        expr.col,
                        "E332",
                        "getint 第 1 个参数使用 string 类型"
                    )
                rt = self._check_expr(expr.args[1])
                if rt is None:
                    return None
                if rt not in self.NUMERIC and rt != "unknown":
                    self._err(
                        "内置函数 getint() 第二个参数非数值类型",
                        expr.line,
                        expr.col,
                        "E333",
                        "getint 第 2 个参数应为整数下标"
                    )
                expr.type_name = "int"
                return "int"

            # 自定义函数调用
            fn = self.functions.get(expr.name)
            if not fn:
                if expr.name not in self.undeclared_reported:
                    self._err(
                        f"调用未定义的自定义函数 '{expr.name}'",
                        expr.line,
                        expr.col,
                        "E320",
                        "先定义该函数，或修改函数名"
                    )
                    self.undeclared_reported.add(expr.name)
                return "unknown"
            if len(expr.args) != len(fn.params):
                self._err(
                    f"函数 '{expr.name}' 期望 {len(fn.params)} 个参数，实际 {len(expr.args)} 个",
                    expr.line,
                    expr.col,
                    "E321",
                    "调整传入参数数量，与函数定义保持一致"
                )
            for i, (arg, (pt, _)) in enumerate(zip(expr.args, fn.params)):
                at = self._check_expr(arg)
                if at is None:
                    return None
                if at != "unknown" and not self._compatible(pt, at):
                    self._err(
                        f"函数 '{expr.name}' 第 {i+1} 个参数类型不匹配（期望 {pt}，实际 {at}）",
                        expr.line,
                        expr.col,
                        "E322",
                        "修改参数类型，与函数形参类型匹配"
                    )
            expr.type_name = fn.return_type
            return fn.return_type

        # 数组下标访问
        if isinstance(expr, ArrayAccessExpr):
            sym = self.current_scope.lookup(expr.name)
            if not sym:
                # 未声明变量去重报错
                if expr.name not in self.undeclared_reported:
                    self._err(
                        f"未声明的变量 '{expr.name}'",
                        expr.line,
                        expr.col,
                        "E302",
                        "使用变量前先进行变量声明"
                    )
                    self.undeclared_reported.add(expr.name)
                return None
            if sym.is_array:
                sym.used = True
                # 数组下标强制int校验
                idx_type = self._check_expr(expr.index)
                if idx_type is None:
                    return None
                if idx_type != "int":
                    self._err(
                        f"数组下标必须为 int 类型，当前类型为 {idx_type}",
                        expr.line,
                        expr.col,
                        "E307",
                        "将数组下标修改为整数类型表达式"
                    )
                expr.type_name = sym.type_name
                return sym.type_name
            if sym.type_name == "string":
                sym.used = True
                idx_type = self._check_expr(expr.index)
                if idx_type is None:
                    return None
                expr.type_name = "string"
                return "string"
            self._err(
                f"'{expr.name}' 不支持下标访问",
                expr.line,
                expr.col,
                "E313",
                "移除下标访问，或将变量声明为数组/字符串"
            )
            return None

        # 普通变量引用
        if isinstance(expr, VarExpr):
            sym = self.current_scope.lookup(expr.name)
            if not sym:
                # 未声明变量去重报错
                if expr.name not in self.undeclared_reported:
                    self._err(
                        f"未声明的变量 '{expr.name}'",
                        expr.line,
                        expr.col,
                        "E302",
                        "使用变量前先进行变量声明"
                    )
                    self.undeclared_reported.add(expr.name)
                return None
            if sym.is_array:
                self._err(
                    f"数组 '{expr.name}' 未使用下标直接引用",
                    expr.line,
                    expr.col,
                    "E323",
                    "为数组变量补充下标访问"
                )
            sym.used = True
            expr.type_name = sym.type_name
            return sym.type_name

        # 一元表达式（负号、逻辑非 !）
        if isinstance(expr, UnaryExpr):
            if expr.op == "!":
                op_type = self._check_expr(expr.operand)
                if op_type is None:
                    return None
                # 逻辑非返回bool类型
                expr.type_name = "bool"
                return "bool"
            # 一元负号
            t = self._check_expr(expr.operand)
            if t is None:
                return None
            if expr.op == "-" and t in self.NUMERIC:
                expr.type_name = t
                return t
            if t != "unknown":
                self._err(
                    "一元 '-' 作用于非数值类型",
                    expr.line,
                    expr.col,
                    "E305",
                    "一元负号仅作用于int/float类型数据"
                )
            return "unknown"

        # 二元表达式（算术、逻辑运算）
        if isinstance(expr, BinaryExpr):
            # && || 逻辑运算返回bool
            if expr.op in ("&&", "||"):
                lt = self._check_expr(expr.left)
                rt = self._check_expr(expr.right)
                if lt is None or rt is None:
                    return None

                if lt == "string" or rt == "string":
                    self._err(
                        f"逻辑运算 '{expr.op}' 不允许 string 类型操作数",
                        expr.line,
                        expr.col,
                        "E304",
                        "逻辑运算仅支持布尔/数值类型"
                    )
                    return "unknown"
                
                if lt not in self.LOGICAL_ALLOWED and lt != "unknown":
                    self._warn(
                        f"逻辑运算左操作数类型 '{lt}' 非常规数值/逻辑类型",
                        expr.left.line,
                        expr.left.col,
                        "W304",
                        "建议使用布尔或数值类型作为逻辑运算操作数"
                    )
                if rt not in self.LOGICAL_ALLOWED and rt != "unknown":
                    self._warn(
                        f"逻辑运算右操作数类型 '{rt}' 非常规数值/逻辑类型",
                        expr.right.line,
                        expr.right.col,
                        "W305",
                        "建议使用布尔或数值类型作为逻辑运算操作数"
                    )

                if lt == "unknown" or rt == "unknown":
                    return "unknown"
                expr.type_name = "bool"
                return "bool"

            if expr.op == "/" and isinstance(expr.right, IntLit) and expr.right.value == 0:
                self._err(
                    "编译阶段检测到除零运算",
                    expr.line,
                    expr.col,
                    "E306",
                    "除数不能为0，请修改表达式"
                )
            if expr.op == "/" and isinstance(expr.right, FloatLit) and expr.right.value == 0.0:
                self._err(
                    "编译阶段检测到除零运算",
                    expr.line,
                    expr.col,
                    "E306",
                    "除数不能为0，请修改表达式"
                )

            lt = self._check_expr(expr.left)
            rt = self._check_expr(expr.right)
            if lt is None or rt is None:
                return None

            # 字符串拼接特例
            if expr.op == "+" and lt == "string" and rt == "string":
                expr.type_name = "string"
                return "string"
            if lt == "string" or rt == "string":
                self._err(
                    f"字符串不能使用算术运算 '{expr.op}'",
                    expr.line,
                    expr.col,
                    "E324",
                    "字符串仅支持+拼接，不支持其他算术运算符"
                )
                return "unknown"
            if lt not in self.NUMERIC or rt not in self.NUMERIC:
                if lt != "unknown" and rt != "unknown":
                    self._err(
                        f"算术运算 '{expr.op}' 的操作数必须是数值类型（当前 {lt} 与 {rt}）",
                        expr.line,
                        expr.col,
                        "E307",
                        "算术运算仅可作用于int/float类型"
                    )
                return "unknown"

            result = "float" if "float" in (lt, rt) else "int"
            expr.type_name = result
            return result

        # 关系表达式统一返回bool
        if isinstance(expr, RelExpr):
            lt = self._check_expr(expr.left)
            rt = self._check_expr(expr.right)
            if lt is None or rt is None:
                return None

            if lt == "string" or rt == "string":
                if expr.op not in ("==", "!="):
                    self._err(
                        "字符串使用非法关系运算符（仅支持 ==、!=）",
                        expr.line,
                        expr.col,
                        "E325",
                        "字符串仅支持相等/不等判断"
                    )
            elif lt not in self.NUMERIC or rt not in self.NUMERIC:
                if lt != "unknown" and rt != "unknown":
                    self._err(
                        f"关系运算 '{expr.op}' 的操作数必须是数值类型",
                        expr.line,
                        expr.col,
                        "E308",
                        "关系运算仅可作用于int/float类型"
                    )
            expr.type_name = "bool"
            return "bool"

        return "unknown"

    # 检测全局作用域未使用的变量
    def _check_unused_globals(self) -> None:
        seen: Set[str] = set()
        for sym in self.global_scope.all_symbols():
            if sym.name in seen:
                continue
            seen.add(sym.name)
            if not sym.used:
                self._warn(
                    f"全局变量 '{sym.name}' 已声明但从未使用",
                    sym.declared_line,
                    sym.declared_col,
                    "W302",
                    "删除无用变量，或补充使用逻辑"
                )
            if sym.is_array and not sym.array_initialized:
                self._warn(
                    f"全局数组 '{sym.name}' 声明后未进行初始化赋值",
                    sym.declared_line,
                    sym.declared_col,
                    "W302",
                    "为数组元素补充初始化赋值"
                )

    
    @staticmethod
    def _compatible(declared: str, assigned: str) -> bool:
        if declared == assigned:
            return True
        if declared == "float" and assigned == "int":
            return True
        return False