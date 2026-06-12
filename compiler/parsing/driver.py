"""LL(1) 与 LR 分析驱动器（含错误恢复）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple ,Dict, Set

from ..errors import CompileDiagnostic, Stage, diagnostic
from ..lexer import Token
from .cfg import EPS, Grammar, Production
from .ll1 import LL1Table
from .lr import ParseTableSet
from .parse_tree import PTNode
from .first_follow import compute_follow, compute_first

def _token_symbol(tok: Token) -> str:
    return "$" if tok.kind == "EOF" else tok.kind


SYNC_TOKENS = frozenset({
    "SEMI", "RBRACE", "EOF", "IF", "WHILE", "FOR", "PRINT", "PRINTN",
    "INPUT", "WRITE", "RETURN", "BREAK", "CONTINUE", "INT", "FLOAT", "STRING", "VOID",
})


@dataclass
class DriverResult:
    tree: Optional[PTNode] = None
    errors: List[CompileDiagnostic] = field(default_factory=list)


def parse_ll1(
    tokens: List[Token],
    grammar: Grammar,
    table: LL1Table,
) -> DriverResult:
    return _parse_ll1_std(tokens, grammar, table)


def _parse_ll1_std(tokens: List[Token], grammar: Grammar, table: LL1Table) -> DriverResult:
    errors: List[CompileDiagnostic] = []
    stack: List[str] = ["$", grammar.start]
    node_stack: List[PTNode] = []
    pos = 0
    steps = 0
    limit = len(tokens) * 30 + 100

    while stack and steps < limit:
        steps += 1
        top = stack[-1]
        cur = tokens[pos] if pos < len(tokens) else tokens[-1]
        a = _token_symbol(cur)

        if top in grammar.terminals or top == "$":
            if top == a:
                if top != "$":
                    node_stack.append(PTNode(top, token=cur))
                    if a != "EOF":
                        pos += 1
                stack.pop()
            else:
                code,des,sug = _infer_error_ll1(top, a)
                _add_err(errors, f"期望 {top}，实际为 {a} ({cur.value!r}),{des}", cur,code,sug)
                pos = _sync(tokens, pos, errors)
                if stack:
                    stack.pop()
            continue

        key = (top, a)
        if key not in table.table:
            _add_err(errors, f"无法应用 LL(1) 预测 ({top}, {a})", cur)
            pos = _sync(tokens, pos, errors)
            stack.pop()
            continue

        prod = grammar.productions[table.table[key]]
        stack.pop()
        rhs = [] if prod.is_epsilon else list(prod.body)
        children: List[PTNode] = []
        for _ in rhs:
            if node_stack:
                children.insert(0, node_stack.pop())
        parent = PTNode(prod.head, children, prod_index=prod.index)
        node_stack.append(parent)
        for sym in reversed(rhs):
            stack.append(sym)

    if node_stack:
        return DriverResult(node_stack[-1], errors)
    return DriverResult(None, errors)


def parse_lr(
    tokens: List[Token],
    grammar: Grammar,
    table: ParseTableSet,
) -> DriverResult:
    errors: List[CompileDiagnostic] = []
    state_stack = [0]
    node_stack: List[PTNode] = []
    pos = 0
    steps = 0
    limit = len(tokens) * 40 + 200

    first_set = compute_first(grammar)
    follow_set = compute_follow(grammar, first_set)

        
    while steps < limit:
        steps += 1
        cur = tokens[pos] if pos < len(tokens) else tokens[-1]
        a = _token_symbol(cur)
        state = state_stack[-1]
        action = table.action.get((state, a))

        if not action:
            error_code, des, suggestion = _infer_error_lr(state_stack, a, follow_set)
            _add_err(errors, msg=f"语法分析动作缺失 (状态{state}, {a}),{des}", tok=cur,code=error_code,sug=suggestion)
            pos = _sync(tokens, pos, errors)
            if len(state_stack) > 1:
                state_stack.pop()
                if node_stack:
                    node_stack.pop()
            else:
                pos += 1 if pos < len(tokens) - 1 else 0
            continue

        kind, arg = action
        if kind == "shift":
            leaf = PTNode(a, token=cur)
            node_stack.append(leaf)
            state_stack.append(arg)
            if a != "EOF":
                pos += 1
            continue

        if kind == "reduce":
            prod = grammar.productions[arg]
            rhs = [] if prod.is_epsilon else list(prod.body)
            children: List[PTNode] = []
            for _ in rhs:
                if state_stack:
                    state_stack.pop()
                if node_stack:
                    children.insert(0, node_stack.pop())
            parent = PTNode(prod.head, children, prod_index=prod.index)
            node_stack.append(parent)
            goto_state = table.goto.get((state_stack[-1], prod.head))
            if goto_state is None:
                _add_err(errors, f"GOTO 缺失 ({state_stack[-1]}, {prod.head}),文法本身有缺陷,或内部状态机崩溃", cur,"E226")
                break
            state_stack.append(goto_state)
            continue

        if kind == "accept":
            if node_stack:
                return DriverResult(node_stack[-1], errors)
            return DriverResult(None, errors)

    _add_err(errors, "语法分析错误恢复停滞，已中止", tokens[min(pos, len(tokens) - 1)], "E220")
    root = node_stack[-1] if node_stack else None
    return DriverResult(root, errors)


def _sync(tokens: List[Token], pos: int, errors: List[CompileDiagnostic]) -> int:
    if pos >= len(tokens):
        return pos
    start = pos
    while pos < len(tokens) - 1 and tokens[pos].kind not in SYNC_TOKENS:
        pos += 1
    if pos == start and pos < len(tokens) - 1:
        pos += 1
    if tokens[pos].kind == "SEMI":
        pos += 1
    return pos


def _add_err(
    errors: List[CompileDiagnostic],
    msg: str,
    tok: Token,
    code: str = "E201",
    sug: str=""
) -> None:
    if len(errors) >= 50:
        return
    errors.append(diagnostic(Stage.SYNTAX, msg, line=tok.line, col=tok.col, code=code,suggestion=sug))


def _infer_error_ll1(expected: str, actual: str) -> Tuple[str, str, str]:
    #根据期望的终结符和实际遇到的终结符，推断具体的语法错误码及辅助信息。
   
    des = ""
    suggestion = ""

    # 1. 检查成对符号缺失 (E202, E215-E218)
    if expected == "RPAREN":
        if actual in ["LBRACE", "IDENT", "IF", "WHILE", "FOR"]:
            code = "E215"
            des = "括号匹配错误,if语句条件缺少右括号"
            suggestion = "在'{'前补充右括号"
        elif actual in ["COMMA", "RPAREN"]:
            code = "E219"
            des = "函数调用或参数列表格式错误"
            suggestion = "请检查逗号分隔符或括号"
        else:
            code = "E202"
            des = "括号匹配错误,期望右括号 ')' 但未找到。"
            suggestion = "在当前位置添加括号"

    elif expected == "RBRACKET":
        code = "E218"
        des = "数组访问或下标表达式缺少右中括号 ']'。"
        suggestion = ""

    elif expected == "RBRACE":
        code = "E205"
        des = "代码块缺少闭合的大括号 '}'。"
        suggestion = "在代码块末尾添加右大括号 '}"

    # 2. 检查语句结束符 (E204)
    elif expected == "SEMI":
        code = "E204"
        des = "语句末尾缺少分号 ';'。"
        suggestion = "每条语句请以分号结尾"

    # 3. 检查运算符右操作数缺失 (E206-E210, E212-E214)
    elif expected in ["Logic", "LogicAnd", "LogicNot", "RelExpr", "Expr", "Term", "Factor"]:
        if actual in ["PLUS", "MINUS"]:
            code = "E207"
            des = "表达式语法错误，二元加减运算符右侧缺少操作数。"
            suggestion = "在运算符右侧补充操作数"
        elif actual in ["STAR", "SLASH"]:
            code = "E208"
            des = "表达式语法错误，乘除运算符右侧缺少操作数。"
            suggestion = "在运算符右侧补充操作数"
        elif actual == "OR":
            code = "E212"
            des = "逻辑表达式语法错误，逻辑或 '||' 运算符右侧缺少条件表达式。"
            suggestion = "在'||'后补充条件表达式"
        elif actual == "AND":
            code = "E213"
            des = "逻辑表达式错误，逻辑与 '&&' 运算符右侧缺少条件表达式。"
            suggestion = "在'&&'后补充条件表达式"
        elif actual in ["EQ", "NE", "LT", "LE", "GT", "GE"]:
            code = "E206"
            des = "关系运算符(==, !=, < 等)右侧缺少比较对象。"
            suggestion = "关系表达式错误"
        elif actual == "RPAREN":
            code = "E222"
            des = "表达式语法错误，括号内表达式为空或运算符后缺少操作数。"
            suggestion = "在括号内添加合法表达式"
            
    # 4. 检查一元运算符 (E209, E214)
    elif expected == "Factor":
        if actual == "MINUS":
            code = "E209"
            des = "一元负号 '-' 后缺少数字、变量或表达式。"
            suggestion = "在-号后补充数字或变量"
        elif actual == "NOT":
            code = "E214"
            des = "逻辑非 '!' 后缺少表达式。"
            suggestion = "在！号后补充表达式"
        else:
            code = "E210"
            des = f"无法解析表达式因子，意外的符号: {actual}"
            suggestion = "表达式请使用变量、数字、运算符等合法元素"

    # 5. 默认回退
    else:
        code = "E201"
        des = f"语法结构错误：期望 '{expected}'，但遇到 '{actual}'。"
        suggestion = "通用语法错误，仔细检查代码"

    return (code, des, suggestion)

def _infer_error_lr(state_stack: List[int], actual: str, follow_set: Dict[str, Set[str]]) -> Tuple[str, str, str]:
    #LR 专用错误推断。利用 Follow 集和当前 Lookahead 符号推断当前上下文

    #  1. 检查是否为运算符右操作数缺失 (E206 - E214) 
    # 当遇到运算符但当前状态不接受该运算符时，通常是左侧表达式不完整
    if actual == "PLUS" or actual == "MINUS":
        return ("E207", "表达式语法错误,加减运算符右侧缺少表达式", "在运算符右侧补充")
    elif actual in ["STAR", "SLASH"]:
        return ("E208", "表达式语法错误,乘除运算符右侧缺少表达式", "在运算符右侧补充")
    elif actual == "OR":
        return ("E212", "逻辑表达式错误,逻辑或 '||' 右侧缺少条件表达式", "在'||'后补充条件表达式")
    elif actual == "AND":
        return ("E213", "逻辑表达式错误,在'&&'后补充条件表达式", "在'&&'后补充条件表达式")
    elif actual in ["EQ", "NE", "LT", "LE", "GT", "GE"]:
        return ("E206", "关系表达式错误,关系运算符右侧缺少比较对象", "在关系运算符右侧补充比较对象")
    
    # 一元运算符出现在不合法的位置（例如连续出现）
    if actual == "NOT":
        return ("E214", "! 右侧无条件表达式", "逻辑表达式错误")
    
    # 2. 检查是否为结构/括号缺失 (E202, E205, E215-E219) 
    # 遍历 Follow 集，看 actual 是否是某个上下文的合法结束符
    for nonterm, follow_symbols in follow_set.items():
        if actual in follow_symbols:
            # 命中了 Follow 集，说明用户跳过了中间步骤，直接输入了合法的后续符号
            
            # 2.1 语句结束符缺失
            if actual == "SEMI":
                return ("E204", "语句结束符错误", "每条语句请以分号结尾")
                
            # 2.2 代码块未闭合
            if actual == "RBRACE":
                return ("E205", "代码块结构错误'", "请在代码块末尾添加右大括号 '}")
                
            # 2.3 控制流语句缺少右括号
            if actual == "LBRACE": 
                # 期望遇到 { 但遇到了其他，或者在条件表达式中直接遇到了 {
                return ("E215", "括号匹配错误", "在'{'前补充右括号")
                
            # 2.4 数组下标或参数列表缺失
            if actual == "RBRACKET":
                return ("E218", "括号匹配错误，数组下标缺少右中括号 ']'", "请补充右中括号 ']'")
                
            # 通用的右括号缺失
            if actual == "RPAREN":
                return ("E202", "括号匹配错误", "在当前位置添加括号")
                
            # 文件意外结束
            if actual == "EOF":
                return ("E205", "代码块结构错误", "在代码块末尾添加右大括号 '}'")
            
            # 其他合法的 Follow 符号，统一报通用结构缺失
            return ("E201", "语法结构错误", f"在 '{nonterm}' 上下文中，缺少必要的中间语法结构")

    # 3. 非法语句开头 (E203) 
    # 如果 actual 既不是运算符，也不在任何 Follow 集中，判定为非法语句起始
    # 防止完全无法识别的错误
    return ("E203", f"无法解析语句开头，遇到非法的起始Token '{actual}'", "请仔细检查代码")
