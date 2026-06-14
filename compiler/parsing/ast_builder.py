"""将分析树转换为 AST。"""

from __future__ import annotations

from typing import List, Optional, Tuple, Union

from ..ast_nodes import (
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
    WriteStmt,
    WhileStmt,
)
from .parse_tree import PTNode


def build_program(root: PTNode) -> Program:
    functions: List[FuncDecl] = []
    statements: List[Stmt] = []
    top = root.child(0)
    if top:
        _collect_top(top, functions, statements)
    return Program(functions, statements)


def _collect_top(node: PTNode, functions: List[FuncDecl], statements: List[Stmt]) -> None:
    if not node.children:
        return
    item = node.child(0)
    rest = node.child(1)
    if item:
        fn = _build_top_item(item)
        if isinstance(fn, FuncDecl):
            functions.append(fn)
        elif fn:
            statements.append(fn)
    if rest:
        _collect_top(rest, functions, statements)


def _build_top_item(node: PTNode) -> Optional[Union[FuncDecl, Stmt]]:
    if not node.children:
        return None
    return _build_func(node.child(0)) if node.children[0].symbol == "FuncDecl" else _build_stmt(node.child(0))


def _build_func(node: PTNode) -> Optional[FuncDecl]:
    if not node or len(node.children) < 6:
        return None
    ret = _type_name(node.child(0))
    name = node.child(1).text() if node.child(1) else ""
    params = _build_params(node.child(3))
    body = _build_block(node.child(5))
    if not body:
        return None
    line = node.child(1).line() if node.child(1) else 0
    return FuncDecl(ret, name, params, body, line)


def _build_params(node: Optional[PTNode]) -> List[Tuple[str, str]]:
    if not node or not node.children:
        return []
    first = node.child(0)
    if not first or len(first.children) < 2:
        return []
    params = [( _type_name(first.child(0)), first.child(1).text())]
    tail = first.child(2)
    while tail and tail.children:
        if len(tail.children) >= 3:
            params.append((_type_name(tail.child(1)), tail.child(2).text()))
            tail = tail.child(3) if len(tail.children) > 3 else None
        else:
            break
    return params


def _type_name(node: Optional[PTNode]) -> str:
    if not node or not node.children:
        return "int"
    tok = node.children[0].token
    return tok.value.lower() if tok else node.children[0].symbol.lower()


def _build_block(node: Optional[PTNode]) -> Optional[Block]:
    if not node or len(node.children) < 3:
        return None
    stmts = _build_block_stmt_list(node.child(1))
    return Block(stmts)


def _build_block_stmt_list(node: Optional[PTNode]) -> List[Stmt]:
    if not node or not node.children:
        return []
    stmt = _build_stmt(node.child(0))
    rest = node.child(1)
    out: List[Stmt] = []
    if stmt:
        out.append(stmt)
    if rest:
        out.extend(_build_block_stmt_list(rest))
    return out


def _build_stmt(node: Optional[PTNode]) -> Optional[Stmt]:
    if not node or not node.children:
        return None
    inner = node.children[0]
    sym = inner.symbol
    if sym == "DeclStmt":
        return _build_decl(inner)
    if sym == "AssignStmt":
        return _build_assign(inner)
    if sym == "IfStmt":
        return _build_if(inner)
    if sym == "WhileStmt":
        return _build_while(inner)
    if sym == "ForStmt":
        return _build_for(inner)
    if sym == "PrintStmt":
        return _build_print(inner, True)
    if sym == "PrintnStmt":
        return _build_print(inner, False)
    if sym == "InputStmt":
        return _build_input(inner)
    if sym == "WriteStmt":
        return _build_write(inner)
    if sym == "ReturnStmt":
        return _build_return(inner)
    if sym == "BreakStmt":
        return BreakStmt(inner.child(0).line() if inner.child(0) else 0)
    if sym == "ContinueStmt":
        return ContinueStmt(inner.child(0).line() if inner.child(0) else 0)
    if sym == "Block":
        return _build_block(inner)
    return None


def _build_decl(node: PTNode) -> Optional[DeclStmt]:
    if len(node.children) < 3:
        return None
    tname = _type_name(node.child(0))
    names: List[str] = []
    sizes: List[Optional[int]] = []
    var_list = node.child(1)
    _collect_vars(var_list, names, sizes)
    if not names:
        return None
    return DeclStmt(tname, names, sizes, node.child(0).line())


def _collect_vars(node: Optional[PTNode], names: List[str], sizes: List[Optional[int]]) -> None:
    if not node or not node.children:
        return
    if node.symbol == "VarList":
        names.append(node.child(0).text())
        arr = node.child(1)
        array_size = None
        if arr and arr.children:
            lit = arr.child(1)
            if lit:
                array_size = int(lit.text())
        sizes.append(array_size)
        _collect_vars(node.child(2) if len(node.children) > 2 else None, names, sizes)
    elif node.symbol == "VarListTail":
        if len(node.children) >= 4:
            names.append(node.child(1).text())
            arr = node.child(2)
            array_size = None
            if arr and arr.children:
                lit = arr.child(1)
                if lit:
                    array_size = int(lit.text())
            sizes.append(array_size)
            _collect_vars(node.child(3), names, sizes)


def _build_assign(node: PTNode) -> Optional[AssignStmt]:
    if len(node.children) < 5:
        return None
    name = node.child(0).text()
    idx = _optional_index(node.child(1))
    val = _build_logic(node.child(3))
    if not val:
        return None
    return AssignStmt(name, val, idx, node.child(0).line())


def _optional_index(node: Optional[PTNode]) -> Optional[Expr]:
    if not node or not node.children:
        return None
    return _build_logic(node.child(1))


def _build_if(node: PTNode) -> Optional[IfStmt]:
    cond = _build_logic(node.child(2))
    then_b = _build_block(node.child(4))
    if not cond or not then_b:
        return None
    else_opt = node.child(5) if len(node.children) > 5 else None
    elif_blocks, else_b = _build_else_opt(else_opt)
    return IfStmt(cond, then_b, tuple(elif_blocks), else_b, node.child(0).line())


def _build_else_opt(node: Optional[PTNode]) -> Tuple[List[Tuple[Expr, Block]], Optional[Block]]:
    if not node or not node.children:
        return [], None
    return _build_elif_rest(node.child(1))


def _build_elif_rest(node: Optional[PTNode]) -> Tuple[List[Tuple[Expr, Block]], Optional[Block]]:
    if not node or not node.children:
        return [], None
    if node.children[0].symbol == "IF":
        elif_blocks: List[Tuple[Expr, Block]] = []
        cond = _build_logic(node.child(2))
        blk = _build_block(node.child(4))
        if cond and blk:
            elif_blocks.append((cond, blk))
        tail = node.child(5) if len(node.children) > 5 else None
        more_elif, else_b = _build_else_opt(tail)
        elif_blocks.extend(more_elif)
        return elif_blocks, else_b
    return [], _build_block(node.child(0))


def _build_while(node: PTNode) -> Optional[WhileStmt]:
    cond = _build_logic(node.child(2))
    body = _build_block(node.child(4))
    if not cond or not body:
        return None
    return WhileStmt(cond, body, node.child(0).line())


def _build_for(node: PTNode) -> Optional[ForStmt]:
    init_n = node.child(2)
    cond_n = node.child(3)
    upd_n = node.child(4)
    body = _build_block(node.child(6))
    if not body:
        return None
    init = None
    if init_n and init_n.children and init_n.children[0].symbol == "ForAssign":
        init = _build_for_assign(init_n.child(0))
    cond: Expr = IntLit(1)
    if cond_n and cond_n.children and cond_n.children[0].symbol == "Logic":
        c = _build_logic(cond_n.child(0))
        if c:
            cond = c
    update = None
    if upd_n and upd_n.children:
        update = _build_for_assign(upd_n.child(0))
    return ForStmt(init, cond, update, body, node.child(0).line())


def _build_for_assign(node: Optional[PTNode]) -> Optional[AssignStmt]:
    if not node or len(node.children) < 4:
        return None
    name = node.child(0).text()
    idx = _optional_index(node.child(1))
    val = _build_logic(node.child(3))
    if not val:
        return None
    return AssignStmt(name, val, idx, node.child(0).line())


def _build_print(node: PTNode, newline: bool) -> Optional[PrintStmt]:
    vals = _build_logic_list(node.child(2))
    if not vals:
        return None
    return PrintStmt(vals, newline, node.child(0).line())


def _build_logic_list(node: Optional[PTNode]) -> List[Expr]:
    if not node or not node.children:
        return []
    first = _build_logic(node.child(0))
    out = [first] if first else []
    tail = node.child(1)
    while tail and tail.children:
        nxt = _build_logic(tail.child(1))
        if nxt:
            out.append(nxt)
        tail = tail.child(2) if len(tail.children) > 2 else None
    return out


def _build_input(node: PTNode) -> Optional[InputStmt]:
    args = node.child(2)
    if not args or not args.children:
        return None
    names: List[str] = []
    prompt = None
    first = args.child(0)
    if first:
        names.append(first.text())
    tail = args.child(1)
    while tail and tail.children:
        if len(tail.children) >= 2 and tail.child(0) and tail.child(0).symbol == "COMMA":
            nxt = tail.child(1)
            if nxt and nxt.symbol == "IDENT":
                names.append(nxt.text())
                tail = tail.child(2) if len(tail.children) > 2 else None
            elif nxt and nxt.symbol == "Logic":
                lg = _build_logic(nxt)
                if isinstance(lg, VarExpr) and len(names) >= 1:
                    names.append(lg.name)
                    tail = tail.child(2) if len(tail.children) > 2 else None
                else:
                    prompt = lg
                    break
            else:
                break
        else:
            break
    return InputStmt(names, prompt, line=node.child(0).line())


def _build_write(node: PTNode) -> Optional[WriteStmt]:
    path = _build_logic(node.child(2))
    val = _build_logic(node.child(4))
    if not path or not val:
        return None
    return WriteStmt(path, val, node.child(0).line())


def _build_return(node: PTNode) -> Optional[ReturnStmt]:
    rest = node.child(1)
    val = None
    if rest and rest.children and rest.children[0].symbol == "Logic":
        val = _build_logic(rest.child(0))
    return ReturnStmt(val, node.child(0).line())


def _build_logic(node: Optional[PTNode]) -> Optional[Expr]:
    if not node:
        return None
    if node.symbol == "Logic":
        if len(node.children) == 1:
            return _build_logic_and(node.child(0))
        left = _build_logic(node.child(0))
        right = _build_logic_and(node.child(2))
        if left and right:
            n = BinaryExpr("||", left, right)
            n.type_name = "int"
            return n
    if node.symbol == "LogicAnd":
        if len(node.children) == 1:
            return _build_logic_not(node.child(0))
        left = _build_logic_and(node.child(0))
        right = _build_logic_not(node.child(2))
        if left and right:
            n = BinaryExpr("&&", left, right)
            n.type_name = "int"
            return n
    if node.symbol == "LogicNot":
        if len(node.children) == 1:
            return _build_rel(node.child(0))
        inner = _build_logic_not(node.child(1))
        if inner:
            n = UnaryExpr("!", inner)
            n.type_name = "int"
            return n
    if node.symbol in ("RelExpr", "Expr", "Term", "Factor"):
        return _build_expr_chain(node)
    return _build_expr_chain(node)


def _build_logic_and(node: Optional[PTNode]) -> Optional[Expr]:
    return _build_logic(node) if node else None


def _build_logic_not(node: Optional[PTNode]) -> Optional[Expr]:
    return _build_logic(node) if node else None


def _build_rel(node: Optional[PTNode]) -> Optional[Expr]:
    if not node:
        return None
    if len(node.children) == 1:
        return _build_expr_chain(node.child(0))
    left = _build_expr_chain(node.child(0))
    op_node = node.child(1)
    op = "=="
    if op_node and op_node.children and op_node.child(0) and op_node.child(0).token:
        op = op_node.child(0).token.value
    right = _build_expr_chain(node.child(2))
    if left and right:
        return RelExpr(op, left, right)
    return left


def _build_expr(node: Optional[PTNode]) -> Optional[Expr]:
    return _build_expr_chain(node)


def _build_expr_chain(node: Optional[PTNode]) -> Optional[Expr]:
    if not node:
        return None
    sym = node.symbol
    if sym == "RelExpr":
        return _build_rel(node)
    if sym == "Expr":
        if len(node.children) == 1:
            return _build_expr_chain(node.child(0))
        left = _build_expr_chain(node.child(0))
        op = node.child(1).token.value if node.child(1) and node.child(1).token else "+"
        right = _build_expr_chain(node.child(2))
        if left and right:
            return BinaryExpr(op, left, right)
    if sym == "Term":
        if len(node.children) == 1:
            return _build_factor(node.child(0))
        left = _build_expr_chain(node.child(0))
        op = node.child(1).token.value if node.child(1) and node.child(1).token else "*"
        right = _build_factor(node.child(2))
        if left and right:
            return BinaryExpr(op, left, right)
    if sym == "Factor":
        return _build_factor(node)
    if sym == "Logic":
        return _build_logic(node)
    if sym == "LogicAnd":
        return _build_logic_and(node)
    if sym == "LogicNot":
        return _build_logic_not(node)
    return None


def _build_factor(node: Optional[PTNode]) -> Optional[Expr]:
    if not node:
        return None
    if node.children and node.child(0) and node.child(0).symbol == "LPAREN":
        return _build_logic(node.child(1))
    if len(node.children) == 1:
        ch = node.child(0)
        if ch and ch.token:
            kind = ch.token.kind
            if kind == "INT_LIT":
                return IntLit(int(ch.text()))
            if kind == "FLOAT_LIT":
                return FloatLit(float(ch.text()))
            if kind == "STRING_LIT":
                return StringLit(ch.text())
        if ch and ch.symbol == "Logic":
            return _build_logic(ch)
    if len(node.children) == 2 and node.child(0).symbol == "MINUS":
        inner = _build_factor(node.child(1))
        if inner:
            return UnaryExpr("-", inner)
    if len(node.children) >= 2 and node.child(0).symbol == "IDENT":
        name = node.child(0).text()
        suffix = node.child(1)
        if not suffix or not suffix.children:
            return VarExpr(name)
        if suffix.child(0).symbol == "LPAREN":
            args = _build_arg_list(suffix.child(1))
            return CallExpr(name, args)
        if suffix.child(0).symbol == "LBRACKET":
            idx = _build_logic(suffix.child(1))
            return ArrayAccessExpr(name, idx) if idx else VarExpr(name)
        return VarExpr(name)
    return None


def _build_arg_list(node: Optional[PTNode]) -> List[Expr]:
    if not node or not node.children:
        return []
    first = _build_logic(node.child(0))
    out = [first] if first else []
    tail = node.child(1)
    while tail and tail.children:
        a = _build_logic(tail.child(1))
        if a:
            out.append(a)
        tail = tail.child(2) if len(tail.children) > 2 else None
    return out
