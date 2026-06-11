"""LR(0)/SLR(1)/LALR(1)/LR(1) 分析表构造。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple, Union

from .cfg import EPS, Grammar, Production
from .first_follow import compute_first, compute_follow

Action = Tuple[str, int]  # ('shift', state) | ('reduce', prod_idx) | ('accept', 0) | ('error', 0)
LRTable = Dict[Tuple[int, str], Action]
GotoTable = Dict[Tuple[int, str], int]


@dataclass(frozen=True)
class LRItem:
    prod_index: int
    dot: int
    lookahead: str = ""  # LR(1) only; empty for LR(0)

    def core(self) -> Tuple[int, int]:
        return (self.prod_index, self.dot)


@dataclass
class ParseTableSet:
    method: str
    action: LRTable
    goto: GotoTable
    states: List[FrozenSet[LRItem]]
    conflicts: List[str] = field(default_factory=list)
    prod_map: List[Production] = field(default_factory=list)


def build_lr_tables(grammar: Grammar, method: str) -> ParseTableSet:
    first = compute_first(grammar)
    follow = compute_follow(grammar, first)
    if method in ("LR0", "SLR1", "LR1"):
        return _build_lr_automaton(grammar, follow, first, method)
    if method == "LALR1":
        lr1 = _build_lr_automaton(grammar, follow, first, "LR1")
        return _merge_to_lalr(lr1, grammar)
    raise ValueError(f"未知 LR 方法: {method}")


def _first_seq(symbols: tuple, first: Dict[str, Set[str]]) -> Set[str]:
    from .first_follow import _first_of_sequence

    return _first_of_sequence(symbols, first)


def _lr1_lookaheads(
    item: LRItem, prod: Production, first: Dict[str, Set[str]]
) -> Set[str]:
    beta = prod.body[item.dot + 1 :]
    if not beta:
        return {item.lookahead} if item.lookahead else set()
    first_beta = _first_seq(beta, first)
    if EPS in first_beta:
        la = set(first_beta - {EPS})
        if item.lookahead:
            la.add(item.lookahead)
        return la
    return first_beta - {EPS}


def _closure(
    items: Set[LRItem], grammar: Grammar, lr1: bool, first: Dict[str, Set[str]]
) -> Set[LRItem]:
    result = set(items)
    stack = list(items)
    while stack:
        item = stack.pop()
        prod = grammar.productions[item.prod_index]
        if item.dot >= len(prod.body) or prod.body[item.dot] == EPS:
            continue
        sym = prod.body[item.dot]
        if sym not in grammar.nonterminals:
            continue
        for p in grammar.prod_by_head[sym]:
            if lr1:
                lookaheads = _lr1_lookaheads(item, prod, first)
                for la in lookaheads:
                    ni = LRItem(p.index, 0, la)
                    if ni not in result:
                        result.add(ni)
                        stack.append(ni)
            else:
                ni = LRItem(p.index, 0)
                if ni not in result:
                    result.add(ni)
                    stack.append(ni)
    return result


def _goto(
    items: Union[Set[LRItem], FrozenSet[LRItem]],
    sym: str,
    grammar: Grammar,
    lr1: bool,
    first: Dict[str, Set[str]],
) -> Set[LRItem]:
    moved: Set[LRItem] = set()
    for item in items:
        prod = grammar.productions[item.prod_index]
        if item.dot < len(prod.body) and prod.body[item.dot] == sym:
            moved.add(LRItem(item.prod_index, item.dot + 1, item.lookahead))
    if not moved:
        return set()
    return _closure(moved, grammar, lr1, first)


def _collect_symbols(grammar: Grammar) -> List[str]:
    syms: Set[str] = set()
    for p in grammar.productions:
        for s in p.body:
            if s != EPS:
                syms.add(s)
    return sorted(syms)


def _build_lr_automaton(
    grammar: Grammar,
    follow: Dict[str, Set[str]],
    first: Dict[str, Set[str]],
    method: str,
) -> ParseTableSet:
    lr1 = method == "LR1"
    start_prod = grammar.prod_by_head[grammar.start][0]
    start_item = LRItem(start_prod.index, 0, "$") if lr1 else LRItem(start_prod.index, 0)
    start_set = frozenset(_closure({start_item}, grammar, lr1, first))
    states: List[FrozenSet[LRItem]] = [start_set]
    state_index: Dict[FrozenSet[LRItem], int] = {start_set: 0}
    action: LRTable = {}
    goto: GotoTable = {}
    conflicts: List[str] = []
    symbols = _collect_symbols(grammar)
    use_prec = method in ("LR0", "SLR1")

    i = 0
    while i < len(states):
        state = states[i]
        for sym in symbols:
            nxt = _goto(state, sym, grammar, lr1, first)
            if not nxt:
                continue
            fs = frozenset(nxt)
            if fs not in state_index:
                state_index[fs] = len(states)
                states.append(fs)
            j = state_index[fs]
            if sym in grammar.terminals:
                _set_action(
                    action,
                    i,
                    sym,
                    ("shift", j),
                    conflicts,
                    method,
                    grammar if use_prec else None,
                )
            else:
                goto[(i, sym)] = j

        for item in state:
            prod = grammar.productions[item.prod_index]
            complete = item.dot >= len(prod.body) or prod.is_epsilon
            if not complete:
                continue
            if prod.head == grammar.start:
                la = item.lookahead if lr1 else "$"
                _set_action(action, i, la, ("accept", 0), conflicts, method)
            elif lr1:
                _set_action(
                    action, i, item.lookahead, ("reduce", prod.index), conflicts, method
                )
            elif method == "SLR1":
                for t in follow.get(prod.head, set()):
                    if t != "$":
                        _set_action(
                            action,
                            i,
                            t,
                            ("reduce", prod.index),
                            conflicts,
                            method,
                            grammar,
                        )
            else:
                for t in grammar.terminals:
                    if t != "$":
                        _set_action(
                            action,
                            i,
                            t,
                            ("reduce", prod.index),
                            conflicts,
                            method,
                            grammar,
                        )
        i += 1

    return ParseTableSet(method, action, goto, states, conflicts, grammar.productions)


def _merge_to_lalr(lr1: ParseTableSet, grammar: Grammar) -> ParseTableSet:
    core_map: Dict[FrozenSet[Tuple[int, int]], List[int]] = {}
    for idx, state in enumerate(lr1.states):
        core = frozenset(item.core() for item in state)
        core_map.setdefault(core, []).append(idx)

    old_to_new: Dict[int, int] = {}
    merged_states: List[FrozenSet[LRItem]] = []
    for _core, old_indices in core_map.items():
        merged: Set[LRItem] = set()
        for oi in old_indices:
            for item in lr1.states[oi]:
                merged.add(item)
        fs = frozenset(merged)
        new_idx = len(merged_states)
        merged_states.append(fs)
        for oi in old_indices:
            old_to_new[oi] = new_idx

    action: LRTable = {}
    goto: GotoTable = {}
    conflicts: List[str] = []

    for old_i, state in enumerate(lr1.states):
        new_i = old_to_new[old_i]
        for (si, sym), act in lr1.action.items():
            if si != old_i:
                continue
            mapped = act
            if act[0] == "shift":
                mapped = ("shift", old_to_new[act[1]])
            _set_action(action, new_i, sym, mapped, conflicts, "LALR1")

    for (si, sym), dest in lr1.goto.items():
        goto[(old_to_new[si], sym)] = old_to_new[dest]

    return ParseTableSet("LALR1", action, goto, merged_states, conflicts, grammar.productions)


def _set_action(
    table: LRTable,
    state: int,
    symbol: str,
    action: Action,
    conflicts: List[str],
    method: str,
    grammar: Optional[Grammar] = None,
) -> None:
    key = (state, symbol)
    if key in table and table[key] != action:
        if grammar:
            resolved = resolve_with_precedence(grammar, state, symbol, table[key], action)
            if resolved:
                table[key] = resolved
                return
        conflicts.append(
            f"{method} 冲突 状态{state} 符号{symbol}: {table[key]} vs {action}"
        )
        return
    table[key] = action


def resolve_with_precedence(
    grammar: Grammar,
    state: int,
    symbol: str,
    existing: Action,
    new: Action,
) -> Optional[Action]:
    """用优先级/结合性解决 shift-reduce 冲突。"""
    if existing[0] == new[0]:
        return None
    if existing[0] == "reduce" and new[0] == "shift":
        reduce_act, shift_act = existing, new
        term = symbol
    elif existing[0] == "shift" and new[0] == "reduce":
        shift_act, reduce_act = existing, new
        term = symbol
    else:
        return None

    prod = grammar.productions[reduce_act[1]]
    reduce_term = ""
    if len(prod.body) >= 2 and prod.body[1] in grammar.term_prec:
        reduce_term = prod.body[1]
    elif prod.head == "Factor" and len(prod.body) == 2 and prod.body[0] == "MINUS":
        reduce_term = "UMINUS"

    prec_shift = grammar.term_prec.get(term)
    prec_reduce = grammar.term_prec.get(reduce_term, (0, "left"))

    if not prec_shift:
        return None
    if prec_shift[0] > prec_reduce[0]:
        return shift_act
    if prec_shift[0] < prec_reduce[0]:
        return reduce_act
    if prec_shift[1] == "left":
        return reduce_act
    if prec_shift[1] == "right":
        return shift_act
    return None


def apply_precedence(grammar: Grammar, table: ParseTableSet) -> ParseTableSet:
    """后处理：尝试用优先级消解 shift-reduce 冲突。"""
    action = dict(table.action)
    new_conflicts = []
    for c in table.conflicts:
        if "shift" in c and "reduce" in c:
            parts = c.split(" vs ")
            new_conflicts.append(c)
        else:
            new_conflicts.append(c)
    return ParseTableSet(
        table.method, action, table.goto, table.states, new_conflicts, table.prod_map
    )
